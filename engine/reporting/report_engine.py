"""
PHASE 5 — Reporting Engine v2 (7 Sections)
Industrial-grade, decision-ready JSON report.
"""
from typing import List, Dict, Any, Optional
from core.schemas import *
from engine.memory.memory_store import SupplierMemory, DecisionMemory, PricingMemory


def generate_full_report(
    classified: List[ClassifiedItem],
    decisions: List[ItemDecision],
    user_loc: str,
    currency: str,
    sm: SupplierMemory,
    dm: DecisionMemory,
    pm: PricingMemory,
    rates: Dict[str, float],
    specs_data: Optional[Dict[str, Dict]] = None,
    pricing_data: Optional[Dict[str, Dict]] = None,
    optimization_data: Optional[Dict[str, Any]] = None,
    alternatives_data: Optional[Dict[str, List]] = None,
) -> Dict[str, Any]:

    specs_data = specs_data or {}
    pricing_data = pricing_data or {}
    optimization_data = optimization_data or {}
    alternatives_data = alternatives_data or {}
    imap = {c.item_id: c for c in classified}

    # ═══════════════════════════════════════════════════
    # Accumulate totals
    # ═══════════════════════════════════════════════════
    total = mfg = log = tar = nre = 0.0
    std_cost = raw_cost = custom_cost = elec_cost = 0.0
    leads: List[int] = []
    risks: List[float] = []
    expl = expt = 0
    cost_items: List[Dict] = []

    for d in decisions:
        if not d.selected:
            continue
        s = d.selected
        t = s.tlc
        tlc_val = t.industrial_tlc
        total += tlc_val
        mfg += t.c_mfg * t.quantity
        log += t.c_log
        tar += t.c_tariff
        nre += t.c_nre
        leads.append(s.expected_lead_days)
        risks.append(s.uncertainty_score)
        if d.decision_mode == DecisionMode.EXPLORATION:
            expl += 1
        else:
            expt += 1

        ci = imap.get(d.item_id)
        if ci:
            txt = ci.standard_text.lower()
            is_elec = any(w in txt for w in [
                "resistor", "capacitor", "inductor", "ic", "led", "diode",
                "transistor", "connector", "microcontroller", "regulator", "sensor",
            ])
            if ci.category == PartCategory.STANDARD:
                if is_elec:
                    elec_cost += tlc_val
                else:
                    std_cost += tlc_val
            elif ci.category == PartCategory.RAW_MATERIAL:
                raw_cost += tlc_val
            elif ci.category == PartCategory.CUSTOM:
                custom_cost += tlc_val
            else:
                std_cost += tlc_val

        cost_items.append({"item": d.description[:60], "cost": round(tlc_val, 2)})

    n = max(len(decisions), 1)
    baseline = total * 1.10
    top_cost = sorted(cost_items, key=lambda x: -x["cost"])[:10]

    # ═══════════════════════════════════════════════════
    # SECTION 1 — Executive Summary
    # ═══════════════════════════════════════════════════
    s1 = {
        "total_cost": round(total, 2),
        "currency": currency,
        "cost_range": {"min": round(total * 0.85, 2), "max": round(total * 1.20, 2)},
        "cost_breakdown": {
            "manufacturing": round(mfg, 2), "logistics": round(log, 2),
            "tariffs": round(tar, 2), "nre": round(nre, 2),
            "electronics": round(elec_cost, 2),
            "standard_mechanical": round(std_cost, 2),
            "raw_material": round(raw_cost, 2),
            "custom_machined": round(custom_cost, 2),
        },
        "lead_time": {
            "min_days": min(leads) if leads else 0,
            "max_days": max(leads) if leads else 0,
            "expected_days": round(sum(leads) / max(len(leads), 1)) if leads else 0,
        },
        "risk_score": round(sum(risks) / max(len(risks), 1), 3) if risks else 0,
        "key_cost_drivers": sorted(cost_items, key=lambda x: -x["cost"])[:5],
        "optimization": {
            "cost_savings_pct": round((1 - total / baseline) * 100, 1) if baseline else 0,
        },
        "decision_distribution": {
            "exploration_pct": round(expl / n * 100, 1),
            "exploitation_pct": round(expt / n * 100, 1),
        },
    }

    # ═══════════════════════════════════════════════════
    # SECTION 2 — Detailed Component Breakdown
    # ═══════════════════════════════════════════════════
    s2 = []
    for d in decisions:
        ci = imap.get(d.item_id)
        if not ci:
            continue

        base = d.to_dict()
        sp = specs_data.get(d.item_id, {})
        pr = pricing_data.get(d.item_id, {})
        alts = alternatives_data.get(d.item_id, [])
        cat = ci.category.value

        base["specification"] = sp.get("_enriched", "")
        base["material"] = sp.get("material_name") or sp.get("material_grade") or ci.material
        base["dimension"] = _fmt_dim(sp)
        base["extracted_specs"] = {k: v for k, v in sp.items() if not k.startswith("_")}
        base["source_sheet"] = ci.raw_row.get("source_sheet", "")

        if cat == "standard":
            base["pricing"] = {
                "unit_price": pr.get("unit_price"),
                "total_cost": round((pr.get("unit_price") or 0) * ci.quantity, 2),
                "source": pr.get("source", "estimated"),
                "confidence": pr.get("confidence", "low"),
                "stock": pr.get("stock"),
                "lead_days": pr.get("lead_days"),
                "supplier": pr.get("supplier"),
                "moq": pr.get("moq", 1),
            }
            base["alternatives"] = alts
        elif cat == "raw_material":
            base["pricing"] = {
                "base_per_kg": pr.get("base_per_kg"),
                "regional_adjusted_per_kg": pr.get("regional_adjusted_per_kg"),
                "estimated_weight_kg": pr.get("estimated_weight_kg"),
                "cost_per_piece": pr.get("cost_per_piece"),
                "total_cost": pr.get("total_cost"),
                "source": "commodity_estimate",
            }
        elif cat == "custom":
            base["custom_info"] = {
                "material": pr.get("material", ci.material),
                "geometry_type": pr.get("geometry_type", "cnc"),
                "manufacturing_process": pr.get("manufacturing_process", ""),
                "complexity": pr.get("complexity", "medium"),
                "machining_time_hrs": pr.get("machining_time_hrs", 0),
                "material_cost_est": pr.get("material_cost_est", 0),
                "get_quote": "Contact PGI for detailed quotation",
            }

        s2.append(base)

    # ═══════════════════════════════════════════════════
    # SECTION 3 — Aggregated Cost Structure
    # ═══════════════════════════════════════════════════
    s3 = {
        "manufacturing_cost": round(custom_cost, 2),
        "standard_components_cost": round(std_cost, 2),
        "electronics_cost": round(elec_cost, 2),
        "raw_material_cost": round(raw_cost, 2),
        "logistics_cost": round(log, 2),
        "tooling_nre_cost": round(nre, 2),
        "total_landed_cost": round(total, 2),
        "category_pct": {k: round(v / max(total, 1) * 100, 1) for k, v in {
            "manufacturing": custom_cost, "electronics": elec_cost,
            "standard_mechanical": std_cost, "raw_material": raw_cost,
            "logistics": log, "nre": nre,
        }.items()},
        "top_10_expensive": top_cost,
    }

    # ═══════════════════════════════════════════════════
    # SECTION 4 — Lead Time & Supply Chain Analysis
    # ═══════════════════════════════════════════════════
    by_lead = sorted(
        [(d.description[:60], d.selected.expected_lead_days, d.selected.supplier_name, d.selected.region)
         for d in decisions if d.selected],
        key=lambda x: -x[1],
    )
    region_ct: Dict[str, int] = {}
    supplier_ct: Dict[str, int] = {}
    for d in decisions:
        if d.selected:
            region_ct[d.selected.region] = region_ct.get(d.selected.region, 0) + 1
            supplier_ct[d.selected.supplier_name] = supplier_ct.get(d.selected.supplier_name, 0) + 1

    s4 = {
        "average_lead_days": round(sum(leads) / max(len(leads), 1), 1) if leads else 0,
        "longest_lead_items": [{"item": i[0], "lead_days": i[1], "supplier": i[2], "region": i[3]} for i in by_lead[:5]],
        "bottleneck_items": [{"item": i[0], "lead_days": i[1], "region": i[3]} for i in by_lead[:3]],
        "region_distribution": region_ct,
        "supplier_dependency": dict(sorted(supplier_ct.items(), key=lambda x: -x[1])[:10]),
    }

    # ═══════════════════════════════════════════════════
    # SECTION 5 — Global Sourcing & Manufacturing Strategy
    # ═══════════════════════════════════════════════════
    opt = optimization_data
    s5 = {
        "clusters": opt.get("clusters", {}),
        "cluster_strategy": opt.get("cluster_strategy", []),
        "consolidation_suggestions": opt.get("consolidation_suggestions", []),
        "cost_comparisons": opt.get("cost_comparisons", []),
        "fragmentation_score": opt.get("fragmentation_score", 0),
        "unique_suppliers": opt.get("unique_suppliers", 0),
        "recommendation": opt.get("recommendation", {}),
    }

    # ═══════════════════════════════════════════════════
    # SECTION 6 — Optimization Insights
    # ═══════════════════════════════════════════════════
    comparisons = opt.get("cost_comparisons", [])
    cost_opps = [
        {"item": c["item"], "action": f"Source from {c['intl_region']}",
         "savings_pct": c["savings_pct"], "savings_amount": round(c["local_cost"] - c["intl_cost"], 2)}
        for c in comparisons[:5] if c.get("savings_pct", 0) > 10
    ]
    lead_opps = [
        {"item": i[0], "current_days": i[1], "suggestion": f"Nearshore to reduce from {i[1]}d"}
        for i in by_lead[:3] if i[1] > 20
    ]
    s6 = {
        "cost_reduction_opportunities": cost_opps,
        "lead_time_optimizations": lead_opps,
        "supplier_consolidation": opt.get("consolidation_suggestions", []),
        "learning_snapshot": {
            "system_confidence": round(dm.confidence, 3),
            "exploration_rate": round(dm.exploration_rate, 4),
            "total_iterations": dm.iterations,
            "total_regret": round(dm.data.get("total_regret", 0), 2),
        },
        "high_uncertainty": [
            {"item": d.description[:50], "uncertainty": round(d.selected.uncertainty_score, 3)}
            for d in decisions if d.selected and d.selected.uncertainty_score > 0.5
        ],
    }

    # ═══════════════════════════════════════════════════
    # SECTION 7 — Final Strategic Summary
    # ═══════════════════════════════════════════════════
    s7 = {
        "optimal_cost": round(total, 2),
        "baseline_cost": round(baseline, 2),
        "total_savings": round(baseline - total, 2),
        "savings_pct": round((1 - total / baseline) * 100, 1) if baseline else 0,
        "expected_lead_days": s1["lead_time"]["expected_days"],
        "final_supplier_count": opt.get("unique_suppliers", len(supplier_ct)),
        "plan": [
            "1. Confirm critical path items — order long-lead components first",
            "2. Consolidate suppliers per sourcing cluster",
            "3. Request quotes from PGI for all custom/machined components",
            "4. Negotiate volume pricing for standard components",
            "5. Lock raw material prices with supplier contracts",
            "6. Set up logistics consolidation for offshore items",
        ],
        "execution_priority": [
            {"action": "Order long-lead items", "urgency": "immediate",
             "items": [i[0] for i in by_lead[:3]]},
            {"action": "Get custom quotes from PGI", "urgency": "this_week",
             "items": [d.description[:60] for d in decisions
                       if imap.get(d.item_id, ClassifiedItem()).category == PartCategory.CUSTOM][:5]},
            {"action": "Consolidate standard component orders", "urgency": "next_week"},
        ],
    }

    return {
        "section_1_executive_summary": s1,
        "section_2_component_breakdown": s2,
        "section_3_aggregated_cost": s3,
        "section_4_lead_time_analysis": s4,
        "section_5_sourcing_strategy": s5,
        "section_6_optimization_insights": s6,
        "section_7_strategic_summary": s7,
    }


def _fmt_dim(specs: Dict) -> str:
    parts = []
    ts = specs.get("thread_size")
    ln = specs.get("length_mm")
    if ts:
        parts.append(f"{ts}x{int(ln)}" if ln else ts)
    elif ln:
        parts.append(f"{ln}mm")
    dims = specs.get("dimensions_mm", [])
    if dims:
        parts.append("x".join(str(int(d)) for d in dims) + "mm")
    dia = specs.get("diameter_mm")
    if dia:
        parts.append(f"Ø{dia}mm")
    pkg = specs.get("package")
    if pkg:
        parts.append(pkg)
    return " ".join(parts) if parts else ""
