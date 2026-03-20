"""
PHASE 5 — Reporting Engine.
Generates structured JSON report with 6 sections.
"""
from typing import List, Dict, Any
from core.schemas import *
from engine.memory.memory_store import SupplierMemory, DecisionMemory, PricingMemory

def generate_full_report(classified: List[ClassifiedItem], decisions: List[ItemDecision],
                         user_loc: str, currency: str, sm: SupplierMemory,
                         dm: DecisionMemory, pm: PricingMemory, rates: Dict[str,float]) -> Dict[str,Any]:
    # Section 1: Executive Summary
    total=mfg=log=tar=nre=mat=0.0; leads=[]; risks=[]; expl=0; expt=0
    for d in decisions:
        if not d.selected: continue
        s, t = d.selected, d.selected.tlc
        total += t.industrial_tlc; mfg += t.c_mfg * t.quantity; log += t.c_log
        tar += t.c_tariff; nre += t.c_nre; mat += t.c_mfg * t.quantity * 0.3
        leads.append(s.expected_lead_days); risks.append(s.uncertainty_score)
        if d.decision_mode == DecisionMode.EXPLORATION: expl += 1
        else: expt += 1
    n = max(len(decisions), 1)
    baseline = total * 1.10
    s1 = {
        "total_cost": round(total,2), "currency": currency,
        "cost_breakdown": {"material":round(mat,2),"manufacturing":round(mfg,2),"logistics":round(log,2),"tariffs":round(tar,2),"nre":round(nre,2)},
        "lead_time": {"min_days":min(leads) if leads else 0,"max_days":max(leads) if leads else 0,"expected_days":round(sum(leads)/max(len(leads),1)) if leads else 0},
        "risk_score": round(sum(risks)/max(len(risks),1),3) if risks else 0,
        "optimization": {"cost_savings_pct": round((1 - total/baseline)*100,1) if baseline else 0},
        "decision_distribution": {"exploration_pct":round(expl/n*100,1),"exploitation_pct":round(expt/n*100,1)},
    }
    # Section 2: Component Breakdown
    s2 = [d.to_dict() for d in decisions]
    # Section 3: Sourcing Strategy
    imap = {c.item_id: c for c in classified}
    lvo = []; vol = []; proc = []; risk_ins = []
    for d in decisions:
        if not d.selected: continue
        sc = d.selected
        # Local vs offshore
        rt = {}
        for c in d.all_candidates:
            if c.region not in rt or c.simulated_tlc < rt[c.region]: rt[c.region] = c.simulated_tlc
        lvo.append({"item":d.description[:50],"selected_region":sc.region,"selected_tlc":round(sc.simulated_tlc,2),
                     "region_comparison":{k:round(v,2) for k,v in sorted(rt.items(),key=lambda x:x[1])},
                     "justification":d.explanation.local_vs_offshore})
        # Volume
        vt = "low" if d.quantity <= 50 else ("medium" if d.quantity <= 1000 else "high")
        vol.append({"item":d.description[:50],"qty":d.quantity,"type":vt,"region":sc.region,"tlc":round(sc.simulated_tlc,2)})
        # Process
        ci = imap.get(d.item_id)
        if ci and ci.classification_path == ClassificationPath.PATH_3_3:
            proc.append({"item":d.description[:50],"material_form":ci.material_form.value if ci.material_form else "?",
                          "process_chain":[p.value for p in sc.process_chain],"machining_hrs":sc.machining_time_hrs,"labor_hrs":sc.labor_hours})
        if sc.uncertainty_score > 0.6:
            risk_ins.append({"item":d.description[:50],"supplier":sc.supplier_name,"variance":round(sc.historical_variance,3)})
    s3 = {"local_vs_offshore":lvo,"volume_strategy":vol,"process_summary":proc,"risk_insights":risk_ins}
    # Section 4: Financial
    s4 = {"target_currency":currency,"exchange_rates":rates,"total_cost":round(total,2),
           "note":f"All costs in {currency}. 2% forex buffer on cross-border."}
    # Section 5: Recommendation
    prio = sorted([d for d in decisions if d.selected], key=lambda d: d.selected.expected_lead_days, reverse=True)
    s5 = {"optimal_cost":round(total,2),"expected_days":s1["lead_time"]["expected_days"],
           "tradeoffs":f"Cost: {total:.2f} {currency}. Lead: {s1['lead_time']['min_days']}-{s1['lead_time']['max_days']}d. Risk: {s1['risk_score']:.3f}",
           "order_priority":[{"item":d.description[:50],"supplier":d.selected.supplier_name,
                               "lead_days":d.selected.expected_lead_days,
                               "action":"Order now" if d.selected.expected_lead_days>20 else "Standard"} for d in prio[:5]],
           "plan":"1. Confirm pricing. 2. Order long-lead first. 3. Negotiate bulk. 4. Monitor new suppliers."}
    # Section 6: Learning Snapshot
    s6 = {"system_confidence":round(dm.confidence,3),"exploration_rate":round(dm.exploration_rate,4),
           "total_iterations":dm.iterations,"total_regret":round(dm.data.get("total_regret",0),2),
           "exploration_decisions":[{"item":d.description[:50],"supplier":d.selected.supplier_name if d.selected else "?",
                                      "info_gain":round(d.explanation.expected_info_gain,3)}
                                     for d in decisions if d.decision_mode==DecisionMode.EXPLORATION],
           "high_uncertainty":[{"item":d.description[:50],"uncertainty":round(d.selected.uncertainty_score,3)}
                                for d in decisions if d.selected and d.selected.uncertainty_score>0.5],
           "note":"Submit actuals via /api/feedback to improve predictions."}
    return {"section_1_executive_summary":s1,"section_2_component_breakdown":s2,
            "section_3_sourcing_strategy":s3,"section_4_financial":s4,
            "section_5_recommendation":s5,"section_6_learning_snapshot":s6}
