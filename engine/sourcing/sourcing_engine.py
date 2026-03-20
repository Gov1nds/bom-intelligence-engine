"""
PHASE 3 — Sourcing + Simulation Engine.
Step 1: Multi-region candidate generation (configurable regions)
Step 2: Learning-aware simulation (Supplier_Memory adjustment)
Step 3: Industrial TLC calculation
Step 4: Custom part process selection
"""
import math, uuid, hashlib
from typing import List, Dict
from core.schemas import *
from engine.memory.memory_store import SupplierMemory, PricingMemory
from config.settings import RegionConfig, ForexConfig

def _regions(user_loc: str = "") -> List[Dict]:
    out = []
    for r in RegionConfig.REGIONS:
        rid = r["id"]
        if rid == "local" and r.get("dynamic"):
            country = user_loc.split(",")[-1].strip() if user_loc else "USA"
            out.append({"id":"local","label":f"Local ({country})","country":country,
                        "currency":"USD","cost_mult":1.0,"lead_days":5,"risk":0.10,"tariff":0.0})
        else:
            out.append({"id":rid,"label":r["label"],"country":r.get("country",""),
                        "currency":r.get("currency","USD"),
                        "cost_mult":RegionConfig.COST_MULT.get(rid,0.5),
                        "lead_days":RegionConfig.LEAD_DAYS.get(rid,20),
                        "risk":RegionConfig.RISK.get(rid,0.3),
                        "tariff":RegionConfig.TARIFF.get(rid,0.05)})
    return out

def _deterministic_price(seed_str: str, base_lo: float, base_hi: float) -> float:
    h = int(hashlib.md5(seed_str.encode()).hexdigest()[:8], 16)
    frac = (h % 10000) / 10000.0
    return base_lo + frac * (base_hi - base_lo)

def _transport(days):
    if days <= 5: return TransportMode.ROAD
    if days <= 10: return TransportMode.AIR
    if days <= 20: return TransportMode.RAIL
    return TransportMode.SEA

# ---- Process selection engine ----
def select_process_chain(item: ClassifiedItem) -> List[ManufacturingProcess]:
    chain = []
    mat = item.material_form or MaterialForm.BILLET
    geom = item.geometry or GeometryComplexity.PRISMATIC
    tol = item.tolerance or ToleranceClass.STANDARD
    q = item.quantity
    text = item.standard_text.lower()
    if mat == MaterialForm.SHEET:
        chain.append(ManufacturingProcess.LASER_CUTTING)
        if geom != GeometryComplexity.FLAT_2D: chain.append(ManufacturingProcess.PRESS_BRAKE)
        if q > 5000: chain = [ManufacturingProcess.STAMPING]
    elif mat in (MaterialForm.BILLET, MaterialForm.BAR):
        if any(w in text for w in ["shaft","spindle","pin","cylinder"]): chain.append(ManufacturingProcess.CNC_TURNING)
        elif geom in (GeometryComplexity.FULL_3D, GeometryComplexity.MULTI_AXIS): chain.append(ManufacturingProcess.CNC_5AXIS)
        else: chain.append(ManufacturingProcess.CNC_3AXIS)
        if q > 10000: chain = [ManufacturingProcess.DIE_CASTING]
    elif mat == MaterialForm.POLYMER:
        if q > 1000: chain.append(ManufacturingProcess.INJECTION_MOLDING)
        elif geom in (GeometryComplexity.FULL_3D, GeometryComplexity.MULTI_AXIS): chain.append(ManufacturingProcess.SLA)
        else: chain.append(ManufacturingProcess.CNC_3AXIS)
    elif mat == MaterialForm.TUBE:
        chain.extend([ManufacturingProcess.CNC_TURNING, ManufacturingProcess.LASER_CUTTING])
    if not chain: chain.append(ManufacturingProcess.CNC_3AXIS)
    if tol == ToleranceClass.PRECISION: chain.append(ManufacturingProcess.GRINDING)
    elif tol == ToleranceClass.ULTRA: chain.extend([ManufacturingProcess.GRINDING, ManufacturingProcess.HONING])
    if any(w in text for w in ["internal channel","lattice","conformal"]):
        chain = [ManufacturingProcess.DMLS if mat != MaterialForm.POLYMER else ManufacturingProcess.SLS]
    for op in (item.secondary_ops or []):
        if "thread" in op: chain.append(ManufacturingProcess.THREADING)
        if "coat" in op or "anod" in op: chain.append(ManufacturingProcess.SURFACE_COATING)
        if "heat" in op: chain.append(ManufacturingProcess.HEAT_TREATMENT)
    return chain

PROC_TIME = {
    ManufacturingProcess.CNC_3AXIS:0.5, ManufacturingProcess.CNC_5AXIS:1.2,
    ManufacturingProcess.CNC_TURNING:0.3, ManufacturingProcess.LASER_CUTTING:0.1,
    ManufacturingProcess.WATERJET:0.15, ManufacturingProcess.PRESS_BRAKE:0.05,
    ManufacturingProcess.STAMPING:0.02, ManufacturingProcess.DIE_CASTING:0.03,
    ManufacturingProcess.INJECTION_MOLDING:0.02, ManufacturingProcess.SLS:2.0,
    ManufacturingProcess.DMLS:3.0, ManufacturingProcess.SLA:1.5,
    ManufacturingProcess.GRINDING:0.3, ManufacturingProcess.HONING:0.4,
    ManufacturingProcess.THREADING:0.05, ManufacturingProcess.SURFACE_COATING:0.1,
    ManufacturingProcess.HEAT_TREATMENT:0.2,
}
GEOM_MULT = {GeometryComplexity.FLAT_2D:1.0, GeometryComplexity.PRISMATIC:1.3,
             GeometryComplexity.FULL_3D:1.8, GeometryComplexity.MULTI_AXIS:2.5}

def _est_time(chain, geom, qty):
    gm = GEOM_MULT.get(geom, 1.3)
    mt = sum(PROC_TIME.get(p, 0.5) * gm for p in chain)
    setup = (0.5 + len(chain) * 0.25) * max(1, math.ceil(qty / 50))
    labor = setup + mt * qty * 0.3 + qty * 0.02
    return mt, labor, setup

def _nre(chain, qty):
    n = 0.0
    for p in chain:
        if p == ManufacturingProcess.INJECTION_MOLDING: n += 5000
        elif p == ManufacturingProcess.DIE_CASTING: n += 8000
        elif p == ManufacturingProcess.STAMPING: n += 3000
        elif p in (ManufacturingProcess.CNC_3AXIS, ManufacturingProcess.CNC_5AXIS): n += 200
    return n

# ---- TLC computation ----
def _compute_tlc(cand: SourcingCandidate, item: ClassifiedItem, region: Dict) -> TLCBreakdown:
    t = TLCBreakdown()
    t.c_mfg = cand.unit_price; t.quantity = item.quantity; t.c_nre = cand.nre
    wt = 0.1 * item.quantity
    rate = {TransportMode.AIR:12,TransportMode.SEA:3,TransportMode.ROAD:2,TransportMode.RAIL:4}.get(cand.transport_mode, 5)
    t.c_log = round(wt * rate * (1 + region["risk"] * 0.2), 2)
    t.tariff_rate = region.get("tariff", 0.05)
    t.c_inventory = round(t.c_mfg * item.quantity * 0.02 * (1 + region["risk"]), 2)
    t.c_risk = round(t.c_log * 0.08 + t.c_log * region["risk"] * 0.05 + t.c_mfg * item.quantity * ForexConfig.FX_VOLATILITY_BUFFER_PCT, 2)
    t.c_compliance = round((50.0 if region["id"] not in ("local","US") else 10.0) + item.quantity * 0.01, 2)
    t.compute()
    return t

# ---- Memory-aware simulation ----
def _apply_memory(cand: SourcingCandidate, sm: SupplierMemory):
    sid = cand.supplier_id
    if sm.exists(sid):
        cand.unit_price = round(cand.unit_price * (1 + sm.cost_buffer(sid)), 4)
        cand.cost_buffer_pct = sm.cost_buffer(sid)
        cand.expected_lead_days = cand.quoted_lead_days + sm.time_buffer(sid)
        cand.time_buffer_days = sm.time_buffer(sid)
        cand.historical_variance = sm.variance(sid)
        cand.from_memory = True
    else:
        cand.unit_price = round(cand.unit_price * 1.10, 4)
        cand.expected_lead_days = cand.quoted_lead_days
        cand.historical_variance = 0.8
        cand.from_memory = False

def _build(item, sid, sname, region, price, moq, days, sm, chain=None, nre_val=0, mt=0, lh=0, st=0):
    c = SourcingCandidate(
        item_id=item.item_id, supplier_id=sid, supplier_name=sname,
        region=region["id"], country=region.get("country",""),
        unit_price=round(price, 4), moq=moq, currency=region["currency"],
        quoted_lead_days=max(1, days), expected_lead_days=max(1, days),
        process_chain=chain or [], nre=nre_val,
        machining_time_hrs=mt, labor_hours=lh, setup_time_hrs=st,
        transport_mode=_transport(days),
        quality_score=max(0.5, 1.0 - region["risk"]),
        reliability_score=max(0.5, 1.0 - region["risk"] * 0.8),
    )
    _apply_memory(c, sm)
    c.tlc = _compute_tlc(c, item, region)
    c.simulated_tlc = c.tlc.industrial_tlc
    rf = 1 + region["risk"] * 0.15 + c.historical_variance * 0.10
    c.risk_adjusted_tlc = round(c.simulated_tlc * rf, 2)
    c.uncertainty_score = round(c.historical_variance, 3) if c.from_memory else 0.8
    return c

# ---- Candidate generators ----
def _gen_standard(item, regions, sm, pm):
    cands = []
    for reg in regions:
        for i in range(2):
            sid = f"{reg['id']}_dist_{i}"
            seed = f"{item.standard_text}_{reg['id']}_{i}"
            price = _deterministic_price(seed, 0.5, 50.0) * reg["cost_mult"]
            baseline = pm.get_baseline(f"{item.standard_text}_{reg['id']}")
            if baseline: price = baseline * reg["cost_mult"]
            days = reg["lead_days"] + (hash(seed) % 5)
            cands.append(_build(item, sid, f"Dist-{reg['label']}-{i+1}", reg, price, max(1, hash(seed)%50), days, sm))
    return cands

def _gen_raw(item, regions, sm, pm):
    cands = []
    commodity = item.material.split()[0] if item.material else item.standard_text.split()[0]
    cp = pm.get_commodity(commodity)
    for reg in regions:
        sid = f"{reg['id']}_raw_0"
        price = (cp or _deterministic_price(f"{commodity}_{reg['id']}", 5, 200)) * reg["cost_mult"]
        days = reg["lead_days"] + 3
        cands.append(_build(item, sid, f"Mat-{reg['label']}", reg, price, max(1, item.quantity), days, sm))
    return cands

def _gen_custom(item, regions, sm, pm):
    cands = []
    chain = select_process_chain(item)
    geom = item.geometry or GeometryComplexity.PRISMATIC
    mt, lh, st = _est_time(chain, geom, item.quantity)
    nre_val = _nre(chain, item.quantity)
    for reg in regions:
        sid = f"{reg['id']}_mfg_0"
        price = mt * 85.0 * reg["cost_mult"]
        days = reg["lead_days"] + 5
        cands.append(_build(item, sid, f"Mfg-{reg['label']}", reg, price, max(1,item.quantity), days, sm,
                            chain=chain, nre_val=nre_val, mt=mt, lh=lh, st=st))
    return cands

def generate_candidate_strategies(classified: List[ClassifiedItem], user_loc: str,
                                   sm: SupplierMemory, pm: PricingMemory) -> Dict[str, List[SourcingCandidate]]:
    regions = _regions(user_loc)
    out = {}
    for item in classified:
        if item.classification_path == ClassificationPath.PATH_3_2:
            out[item.item_id] = _gen_raw(item, regions, sm, pm)
        elif item.classification_path == ClassificationPath.PATH_3_3:
            out[item.item_id] = _gen_custom(item, regions, sm, pm)
        else:
            out[item.item_id] = _gen_standard(item, regions, sm, pm)
    return out
