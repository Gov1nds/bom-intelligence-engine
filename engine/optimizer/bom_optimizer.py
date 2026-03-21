"""
PHASE E — BOM-Level Optimizer

After per-item decisions are made, this module:
  1. Groups items by category / process / region
  2. Identifies supplier consolidation opportunities
  3. Adjusts sourcing plan to reduce fragmentation
  4. Generates cluster-level insights

Does NOT modify individual item decisions — produces an optimization overlay.
"""

import logging
from typing import List, Dict, Any, Optional
from collections import defaultdict
from core.schemas import ItemDecision, ClassifiedItem, PartCategory, DecisionMode

logger = logging.getLogger("bom_optimizer")


def optimize_bom(
    classified: List[ClassifiedItem],
    decisions: List[ItemDecision],
    user_location: str = "",
) -> Dict[str, Any]:
    """
    BOM-level optimization pass.
    Returns optimization report (does not mutate decisions).
    """
    item_map = {c.item_id: c for c in classified}
    dec_map = {d.item_id: d for d in decisions if d.selected}

    # ── Step 1: Cluster by category ──
    clusters = _cluster_items(classified, dec_map)

    # ── Step 2: Analyze supplier fragmentation ──
    fragmentation = _analyze_fragmentation(dec_map)

    # ── Step 3: Generate consolidation suggestions ──
    consolidation = _suggest_consolidation(clusters, dec_map, item_map)

    # ── Step 4: Sourcing strategy by cluster ──
    strategy = _cluster_strategy(clusters, dec_map, item_map, user_location)

    # ── Step 5: Cost comparison (local vs offshore) ──
    comparisons = _cost_comparisons(dec_map, item_map)

    # ── Step 6: Summary metrics ──
    total_cost = sum(d.selected.simulated_tlc for d in decisions if d.selected)
    total_items = len(decisions)
    unique_suppliers = len(set(d.selected.supplier_id for d in decisions if d.selected))
    unique_regions = len(set(d.selected.region for d in decisions if d.selected))

    return {
        "total_items": total_items,
        "total_cost": round(total_cost, 2),
        "unique_suppliers": unique_suppliers,
        "unique_regions": unique_regions,
        "fragmentation_score": round(unique_suppliers / max(total_items, 1), 2),
        "clusters": clusters,
        "fragmentation_analysis": fragmentation,
        "consolidation_suggestions": consolidation,
        "cluster_strategy": strategy,
        "cost_comparisons": comparisons,
        "recommendation": _generate_recommendation(
            total_items, unique_suppliers, unique_regions, clusters, total_cost
        ),
    }


def _cluster_items(classified: List[ClassifiedItem], dec_map: Dict) -> Dict[str, Any]:
    """Group items into sourcing clusters."""
    clusters: Dict[str, List[str]] = defaultdict(list)

    for c in classified:
        cat = c.category.value
        if cat == "standard":
            # Sub-cluster: electronics vs mechanical
            txt = c.standard_text.lower()
            if any(w in txt for w in ["resistor", "capacitor", "inductor", "ic", "led",
                                       "diode", "transistor", "mosfet", "connector",
                                       "microcontroller", "regulator", "sensor"]):
                clusters["electronics"].append(c.item_id)
            elif any(w in txt for w in ["bolt", "screw", "nut", "washer", "rivet",
                                         "bearing", "spring", "pin", "spacer"]):
                clusters["fasteners"].append(c.item_id)
            else:
                clusters["standard_other"].append(c.item_id)
        elif cat == "raw_material":
            clusters["raw_materials"].append(c.item_id)
        elif cat == "custom":
            path = c.classification_path.value
            txt = c.standard_text.lower()
            if c.material_form and c.material_form.value == "sheet":
                clusters["sheet_metal"].append(c.item_id)
            elif c.material_form and c.material_form.value == "polymer":
                clusters["plastic_parts"].append(c.item_id)
            else:
                clusters["machined_parts"].append(c.item_id)
        else:
            clusters["uncategorized"].append(c.item_id)

    # Add cost/count summaries
    result = {}
    for name, item_ids in clusters.items():
        cost = sum(dec_map[iid].selected.simulated_tlc for iid in item_ids if iid in dec_map)
        result[name] = {
            "item_count": len(item_ids),
            "item_ids": item_ids,
            "total_cost": round(cost, 2),
            "regions_used": list(set(
                dec_map[iid].selected.region for iid in item_ids if iid in dec_map
            )),
        }

    return result


def _analyze_fragmentation(dec_map: Dict) -> Dict[str, Any]:
    """Analyze supplier and region fragmentation."""
    supplier_items: Dict[str, List[str]] = defaultdict(list)
    region_items: Dict[str, List[str]] = defaultdict(list)

    for iid, d in dec_map.items():
        supplier_items[d.selected.supplier_id].append(iid)
        region_items[d.selected.region].append(iid)

    single_item_suppliers = [sid for sid, items in supplier_items.items() if len(items) == 1]

    return {
        "total_suppliers": len(supplier_items),
        "single_item_suppliers": len(single_item_suppliers),
        "region_distribution": {r: len(items) for r, items in region_items.items()},
        "supplier_distribution": {
            sid: {"count": len(items), "items": items[:5]}
            for sid, items in sorted(supplier_items.items(), key=lambda x: -len(x[1]))[:10]
        },
    }


def _suggest_consolidation(clusters: Dict, dec_map: Dict, item_map: Dict) -> List[Dict]:
    """Generate supplier consolidation suggestions."""
    suggestions = []

    for cluster_name, info in clusters.items():
        if not isinstance(info, dict):
            continue
        item_ids = info.get("item_ids", [])
        if len(item_ids) < 2:
            continue

        # Find most common region in this cluster
        regions = defaultdict(float)
        for iid in item_ids:
            if iid in dec_map:
                r = dec_map[iid].selected.region
                regions[r] += dec_map[iid].selected.simulated_tlc

        if not regions:
            continue

        best_region = max(regions, key=regions.get)
        items_not_in_best = [
            iid for iid in item_ids
            if iid in dec_map and dec_map[iid].selected.region != best_region
        ]

        if items_not_in_best and len(items_not_in_best) >= 1:
            savings_est = len(items_not_in_best) * 15  # ~$15 logistics savings per consolidated item
            suggestions.append({
                "cluster": cluster_name,
                "recommendation": f"Consolidate {len(items_not_in_best)} items to {best_region}",
                "items_to_move": len(items_not_in_best),
                "target_region": best_region,
                "estimated_logistics_savings": round(savings_est, 2),
                "reason": f"{cluster_name}: {len(item_ids)} items, "
                          f"most cost-effective in {best_region}",
            })

    return suggestions


def _cluster_strategy(clusters: Dict, dec_map: Dict, item_map: Dict,
                       user_location: str) -> List[Dict]:
    """Generate sourcing strategy per cluster."""
    strategies = []
    user_country = user_location.split(",")[-1].strip() if user_location else "Local"

    for name, info in clusters.items():
        if not isinstance(info, dict):
            continue
        item_ids = info.get("item_ids", [])
        if not item_ids:
            continue

        total = info.get("total_cost", 0)
        regions = info.get("regions_used", [])

        # Strategy recommendation by cluster type
        if name == "electronics":
            strat = f"Source from major distributors (DigiKey/Mouser/LCSC). " \
                    f"Consider LCSC for {user_country} delivery if lead time permits."
        elif name == "fasteners":
            strat = f"Consolidate all {len(item_ids)} fasteners to single regional supplier. " \
                    f"India/China offer 40-60% savings vs EU/US for standard fasteners."
        elif name == "sheet_metal":
            strat = f"Group all sheet metal for single fabricator. " \
                    f"India/China for cost ({len(item_ids)} parts), local for urgent items."
        elif name == "machined_parts":
            strat = f"CNC parts: evaluate local vs offshore based on tolerance. " \
                    f"Precision parts local, standard offshore."
        elif name == "raw_materials":
            strat = f"Source raw materials from regional commodity suppliers. " \
                    f"Lock pricing with volume contracts."
        else:
            strat = f"Evaluate per-item based on specifications."

        strategies.append({
            "cluster": name,
            "item_count": len(item_ids),
            "total_cost": round(total, 2),
            "current_regions": regions,
            "strategy": strat,
        })

    return strategies


def _cost_comparisons(dec_map: Dict, item_map: Dict) -> List[Dict]:
    """Generate local vs international cost comparisons."""
    comparisons = []
    for iid, d in dec_map.items():
        if not d.all_candidates or len(d.all_candidates) < 2:
            continue

        local_cands = [c for c in d.all_candidates if c.region == "local"]
        intl_cands = [c for c in d.all_candidates if c.region != "local"]

        if local_cands and intl_cands:
            local_best = min(local_cands, key=lambda c: c.simulated_tlc)
            intl_best = min(intl_cands, key=lambda c: c.simulated_tlc)
            savings_pct = round((1 - intl_best.simulated_tlc / max(local_best.simulated_tlc, 0.01)) * 100, 1)

            if abs(savings_pct) > 5:  # only report meaningful differences
                comparisons.append({
                    "item": d.description[:60],
                    "local_cost": round(local_best.simulated_tlc, 2),
                    "local_region": "local",
                    "intl_cost": round(intl_best.simulated_tlc, 2),
                    "intl_region": intl_best.region,
                    "savings_pct": savings_pct,
                    "lead_time_diff_days": intl_best.expected_lead_days - local_best.expected_lead_days,
                })

    return sorted(comparisons, key=lambda x: -abs(x["savings_pct"]))[:15]


def _generate_recommendation(total_items, unique_suppliers, unique_regions,
                               clusters, total_cost) -> Dict[str, Any]:
    """Generate final BOM-level recommendation."""
    frag_ratio = unique_suppliers / max(total_items, 1)

    if frag_ratio > 0.7:
        frag_verdict = "HIGH fragmentation — significant consolidation needed"
    elif frag_ratio > 0.4:
        frag_verdict = "MODERATE fragmentation — some consolidation possible"
    else:
        frag_verdict = "LOW fragmentation — well consolidated"

    cluster_names = [k for k in clusters if isinstance(clusters[k], dict)]

    return {
        "fragmentation_verdict": frag_verdict,
        "supplier_target": max(3, min(total_items // 3, 8)),
        "current_suppliers": unique_suppliers,
        "sourcing_clusters": cluster_names,
        "top_action": "Consolidate suppliers per cluster to reduce logistics cost and complexity",
        "estimated_savings_pct": round(max(0, (frag_ratio - 0.3) * 25), 1),
    }
