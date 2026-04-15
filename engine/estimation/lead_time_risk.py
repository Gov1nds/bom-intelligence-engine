"""Lead-time and risk estimation. Heuristic model retained as fallback."""
import logging

logger = logging.getLogger("lead_time_estimator")

BASE_LEAD_TIMES = {
    "catalog_purchase": (3, 14), "custom_fabrication": (15, 45),
    "raw_material_order": (7, 21), "subassembly": (20, 60),
    "unknown": (7, 30),
}

CATEGORY_ADJUSTMENTS = {
    "electronics": -2, "fastener": -3, "machined": 5,
    "custom_mechanical": 10, "sheet_metal": 3,
}


def _quantity_delay(qty: float) -> int:
    if qty <= 10: return 0
    if qty <= 100: return 3
    if qty <= 1000: return 7
    return 14


def estimate_lead_time(procurement_class: str, category: str, quantity: float) -> dict:
    low, high = BASE_LEAD_TIMES.get(procurement_class, (7, 30))
    adj = CATEGORY_ADJUSTMENTS.get(category, 0)
    qty_delay = _quantity_delay(quantity)
    est_low = max(1, low + adj + qty_delay)
    est_high = max(est_low + 1, high + adj + qty_delay)
    est_mid = round((est_low + est_high) / 2)
    return {
        "lead_time_low_days": est_low,
        "lead_time_mid_days": est_mid,
        "lead_time_high_days": est_high,
        "confidence": 0.55,
        "basis": "procurement_category_quantity_model",
        "data_source": "heuristic_model",
        "freshness_status": "ESTIMATED",
    }


RISK_FACTORS = {
    "single_source": {"weight": 0.25, "triggers": ["custom_fabrication", "subassembly"]},
    "long_lead": {"weight": 0.20, "threshold_days": 30},
    "high_value": {"weight": 0.15, "threshold_usd": 500},
    "custom_part": {"weight": 0.20},
    "no_mpn": {"weight": 0.10},
    "exotic_material": {"weight": 0.10, "materials": ["titanium", "inconel", "peek", "carbon fiber"]},
}


def estimate_risk(category: str, procurement_class: str, material: str, quantity: float,
                  is_custom: bool, has_mpn: bool, estimated_cost_mid: float,
                  estimated_lead_mid: int) -> dict:
    flags = []
    total_risk = 0.0

    if procurement_class in RISK_FACTORS["single_source"]["triggers"]:
        total_risk += RISK_FACTORS["single_source"]["weight"]
        flags.append("single_source_risk")
    if estimated_lead_mid > RISK_FACTORS["long_lead"]["threshold_days"]:
        total_risk += RISK_FACTORS["long_lead"]["weight"]
        flags.append("long_lead_time")
    if estimated_cost_mid * quantity > RISK_FACTORS["high_value"]["threshold_usd"]:
        total_risk += RISK_FACTORS["high_value"]["weight"] * 0.5
    if is_custom:
        total_risk += RISK_FACTORS["custom_part"]["weight"]
        flags.append("custom_part")
    if not has_mpn and not is_custom:
        total_risk += RISK_FACTORS["no_mpn"]["weight"]
        flags.append("no_mpn_identified")
    mat_lower = (material or "").lower()
    if any(m in mat_lower for m in RISK_FACTORS["exotic_material"]["materials"]):
        total_risk += RISK_FACTORS["exotic_material"]["weight"]
        flags.append("exotic_material")

    risk_score = min(1.0, total_risk)
    level = "high" if risk_score >= 0.6 else ("medium" if risk_score >= 0.3 else "low")

    return {
        "risk_score": round(risk_score, 3),
        "risk_level": level,
        "risk_flags": flags,
        "confidence": 0.6,
        "data_source": "heuristic_model",
        "freshness_status": "ESTIMATED",
    }
