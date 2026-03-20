"""
PHASE 4 — RL Decision Engine.
UCB + Thompson Sampling + Directed Exploration.
Falls back to deterministic min-TLC if RL produces no valid result.
"""
import math, random
from typing import List
from core.schemas import *
from engine.memory.memory_store import SupplierMemory, DecisionMemory
from config.settings import RLConfig, RegionConfig

def _reward(c: SourcingCandidate) -> float:
    if c.simulated_tlc <= 0: return 0.0
    cost_r = 1.0 / (1 + c.simulated_tlc / 1000)
    time_r = 1.0 / (1 + c.expected_lead_days / 30)
    rel_r = c.reliability_score
    var_r = 1.0 - min(c.historical_variance, 1.0)
    return round(RLConfig.COST_WEIGHT*cost_r + RLConfig.LEADTIME_WEIGHT*time_r + RLConfig.RELIABILITY_WEIGHT*rel_r + RLConfig.VARIANCE_WEIGHT*var_r, 6)

def _risk_penalty(c: SourcingCandidate, dm: DecisionMemory) -> float:
    vp = c.historical_variance * RLConfig.UCB_RISK_PENALTY_WEIGHT
    rr = min(dm.region_regret(c.region) * 0.01, 0.3)
    lr = 0.1 if c.expected_lead_days > 30 else (0.05 if c.expected_lead_days > 14 else 0)
    return vp + rr + lr

def _time_penalty(c: SourcingCandidate) -> float:
    return max(0, c.expected_lead_days - 10) * RLConfig.TIME_PENALTY_PER_DAY

def _ucb(c: SourcingCandidate, sm: SupplierMemory, dm: DecisionMemory) -> float:
    t = max(dm.iterations, 1)
    n = sm.selections(c.supplier_id)
    mu = _reward(c)
    explore = RLConfig.UCB_EXPLORATION_COEFFICIENT * math.sqrt(math.log(t) / (n + 1))
    return mu + explore - _risk_penalty(c, dm) - _time_penalty(c)

def _thompson(c: SourcingCandidate, sm: SupplierMemory) -> float:
    n = max(sm.selections(c.supplier_id), 1)
    r = _reward(c)
    a = RLConfig.THOMPSON_PRIOR_ALPHA + r * n
    b = RLConfig.THOMPSON_PRIOR_BETA + (1 - r) * n
    try: return random.betavariate(max(a, 0.01), max(b, 0.01))
    except: return 0.5

def _explore_select(cands: List[SourcingCandidate]) -> SourcingCandidate:
    best, bs = cands[0], -1e18
    for c in cands:
        if c.simulated_tlc <= 0: continue
        s = (1 / c.simulated_tlc) * c.uncertainty_score
        if s > bs: bs, best = s, c
    return best

def _exploit_select(cands: List[SourcingCandidate], sm: SupplierMemory, dm: DecisionMemory) -> SourcingCandidate:
    best, bs = cands[0], -1e18
    for c in cands:
        n = sm.selections(c.supplier_id)
        s = _thompson(c, sm) if n < RLConfig.THOMPSON_SAMPLING_THRESHOLD else _ucb(c, sm, dm)
        if s > bs: bs, best = s, c
    return best

def _build_explanation(sel, cands, mode, expl_rate, sm, dm):
    e = DecisionExplanation()
    e.decision_mode = mode
    e.mode_probability = expl_rate if mode == DecisionMode.EXPLORATION else (1 - expl_rate)
    e.trigger_condition = f"r < {expl_rate:.3f}" if mode == DecisionMode.EXPLORATION else "UCB/Thompson"
    e.selected_supplier_id = sel.supplier_id
    e.selected_region = sel.region
    e.selected_tlc = sel.simulated_tlc
    srt = sorted(cands, key=lambda c: c.simulated_tlc)
    if len(srt) >= 2:
        nb = srt[1] if srt[0].candidate_id == sel.candidate_id else srt[0]
        e.delta_vs_next_best = round(sel.simulated_tlc - nb.simulated_tlc, 2)
    e.confidence_score = max(0.4, 1.0 - sel.historical_variance) if sel.from_memory else 0.4
    e.confidence_interval_pct = round(sel.historical_variance * 25, 1) if sel.from_memory else 20.0
    e.supply_risk = RegionConfig.RISK.get(sel.region, 0.3)
    e.logistics_risk = 0.3 if sel.expected_lead_days > 20 else 0.15
    e.cost_volatility = sel.historical_variance * 0.5
    e.quality_risk = 1.0 - sel.quality_score
    t = max(dm.iterations, 1); n = sm.selections(sel.supplier_id)
    e.ucb_formula_used = f"μ={_reward(sel):.4f} + {RLConfig.UCB_EXPLORATION_COEFFICIENT:.3f}*sqrt(ln({t})/{n+1}) - risk={_risk_penalty(sel,dm):.4f}"
    tlc = sel.tlc
    e.tlc_proof = (f"({tlc.c_mfg:.2f}×{tlc.quantity})+{tlc.c_nre:.2f}+{tlc.c_log:.2f}+"
                   f"tariff({tlc.c_tariff:.2f})+inv({tlc.c_inventory:.2f})+risk({tlc.c_risk:.2f})+comp({tlc.c_compliance:.2f})={tlc.industrial_tlc:.2f}")
    e.local_vs_offshore = ("Local: lower risk/faster" if sel.region in ("local","US") else
                           f"Offshore ({sel.region}): cost advantage outweighs logistics")
    e.volume_logic = "High vol: offshore cost dominance" if sel.tlc.quantity > 1000 else "Low vol: local preferred"
    e.contributes_to_exploration = mode == DecisionMode.EXPLORATION
    e.expected_info_gain = sel.uncertainty_score if mode == DecisionMode.EXPLORATION else 0.0
    return e

def select_optimal_strategy(item: ClassifiedItem, cands: List[SourcingCandidate],
                            sm: SupplierMemory, dm: DecisionMemory) -> ItemDecision:
    if not cands:
        return ItemDecision(item_id=item.item_id, description=item.standard_text, quantity=item.quantity, category=item.category)
    expl_rate = dm.exploration_rate
    r = random.random()
    if r < expl_rate:
        sel = _explore_select(cands); mode = DecisionMode.EXPLORATION
    else:
        sel = _exploit_select(cands, sm, dm)
        mode = DecisionMode.THOMPSON if sm.selections(sel.supplier_id) < RLConfig.THOMPSON_SAMPLING_THRESHOLD else DecisionMode.EXPLOITATION
    # Deterministic fallback: if selected TLC is > 3x median, pick min-TLC instead
    tlcs = sorted(c.simulated_tlc for c in cands if c.simulated_tlc > 0)
    if tlcs:
        median_tlc = tlcs[len(tlcs)//2]
        if sel.simulated_tlc > 3 * median_tlc:
            sel = min(cands, key=lambda c: c.simulated_tlc)
            mode = DecisionMode.EXPLOITATION
    alts = sorted([c for c in cands if c.candidate_id != sel.candidate_id], key=lambda c: c.simulated_tlc)[:3]
    exp = _build_explanation(sel, cands, mode, expl_rate, sm, dm)
    dm.record(item.item_id, sel.supplier_id, mode.value, sel.simulated_tlc, sel.region)
    sm.record_selection(sel.supplier_id, sel.simulated_tlc)
    return ItemDecision(
        item_id=item.item_id, description=item.standard_text, quantity=item.quantity,
        category=item.category, selected=sel, alternatives=alts,
        decision_mode=mode, score=_reward(sel), explanation=exp, all_candidates=cands,
    )
