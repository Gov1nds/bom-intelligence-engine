"""Cost estimation based on category, material, process, and quantity.

Heuristic model retained as fallback for enrichment pipeline.
"""
import logging

logger = logging.getLogger("cost_estimator")

CATEGORY_BASE_COSTS = {
    "fastener": (0.02, 0.50), "electrical": (0.50, 15.0),
    "electronics": (0.10, 25.0), "mechanical": (5.0, 150.0),
    "raw_material": (2.0, 80.0), "sheet_metal": (10.0, 200.0),
    "machined": (15.0, 500.0), "custom_mechanical": (20.0, 800.0),
    "pneumatic": (5.0, 100.0), "hydraulic": (10.0, 200.0),
    "optical": (5.0, 300.0), "thermal": (3.0, 80.0),
    "cable_wiring": (2.0, 50.0), "standard": (1.0, 50.0),
    "unknown": (1.0, 100.0), "connector": (0.50, 20.0),
    "sensor": (5.0, 100.0), "semiconductor": (0.10, 30.0),
    "passive_component": (0.01, 5.0), "power_supply": (5.0, 200.0),
    "enclosure": (10.0, 300.0), "adhesive_sealant": (2.0, 50.0),
}

MATERIAL_MULTIPLIERS = {
    "titanium": 3.5, "inconel": 4.0, "stainless": 1.8, "steel": 1.0,
    "aluminum": 1.2, "copper": 2.0, "brass": 1.6, "nylon": 0.6,
    "abs": 0.5, "polycarbonate": 0.7, "peek": 5.0, "carbon fiber": 4.0,
}


def _quantity_factor(qty: float) -> float:
    if qty <= 1: return 1.0
    if qty <= 10: return 0.9
    if qty <= 100: return 0.7
    if qty <= 1000: return 0.5
    return 0.35


def estimate_cost(category: str, material: str, quantity: float,
                  is_custom: bool, has_mpn: bool) -> dict:
    low, high = CATEGORY_BASE_COSTS.get(category, (1.0, 100.0))
    mat_mult = 1.0
    mat_lower = (material or "").lower()
    for mat_key, mult in MATERIAL_MULTIPLIERS.items():
        if mat_key in mat_lower:
            mat_mult = mult
            break
    qty_factor = _quantity_factor(quantity)
    custom_mult = 1.5 if is_custom else 1.0
    catalog_factor = 0.85 if has_mpn else 1.0

    est_low = round(low * mat_mult * qty_factor * custom_mult * catalog_factor, 2)
    est_high = round(high * mat_mult * qty_factor * custom_mult * catalog_factor, 2)
    est_mid = round((est_low + est_high) / 2, 2)

    return {
        "unit_cost_low": est_low,
        "unit_cost_mid": est_mid,
        "unit_cost_high": est_high,
        "total_cost_low": round(est_low * quantity, 2),
        "total_cost_mid": round(est_mid * quantity, 2),
        "total_cost_high": round(est_high * quantity, 2),
        "currency": "USD",
        "confidence": 0.4 if category == "unknown" else 0.5,
        "basis": "category_material_quantity_model",
        "data_source": "heuristic_model",
        "freshness_status": "ESTIMATED",
    }
