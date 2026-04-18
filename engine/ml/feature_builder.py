"""ML feature vector builder — output-only, no inference.

Produces flat numeric feature vectors suitable for sklearn, numpy, or
vector DB ingestion. All features normalized to [0, 1] range where
applicable. Unknown/missing values encoded as -1.0.
"""
from __future__ import annotations

import math
from typing import Any

from core.schemas import PartCategory


_CATEGORY_LIST = [cat.value for cat in PartCategory]
_TOP_MATERIALS = [
    "stainless_steel", "aluminum", "carbon_steel", "steel", "brass",
    "copper", "titanium", "abs", "nylon", "polycarbonate",
    "peek", "ptfe", "hdpe", "acetal", "pvc",
    "cast_iron", "bronze", "silicone", "inconel", "spring_steel",
]


def _log_normalize(value: float | None, min_val: float = 0.001, max_val: float = 1e9) -> float:
    """Log-scale normalize a value to [0, 1] range."""
    if value is None or value <= 0:
        return -1.0
    clamped = max(min_val, min(max_val, abs(value)))
    return round((math.log10(clamped) - math.log10(min_val)) / (math.log10(max_val) - math.log10(min_val)), 6)


def build_feature_vector(
    category: str,
    attributes: dict[str, Any],
    confidence: float,
    flags: list[str],
) -> dict[str, float]:
    """Build a flat feature vector for ML/embedding use.

    Args:
        category: Part category string
        attributes: Extracted attributes dictionary
        confidence: Overall confidence score
        flags: Combined review and uncertainty flags

    Returns:
        dict[str, float] with named features, all normalized
    """
    features: dict[str, float] = {}

    # Categorical features: one-hot encoded category
    for cat in _CATEGORY_LIST:
        features[f"cat_{cat}"] = 1.0 if cat == category else 0.0

    # Dimensional features (log-normalized)
    for dim_key in ("length_mm", "width_mm", "height_mm", "diameter_mm", "thickness_mm"):
        features[f"dim_{dim_key}"] = _log_normalize(attributes.get(dim_key), 0.01, 100000)

    # Electrical features (log-normalized)
    features["elec_resistance_ohm"] = _log_normalize(attributes.get("resistance_ohm"), 0.001, 1e12)
    features["elec_capacitance_f"] = _log_normalize(attributes.get("capacitance_f"), 1e-15, 1)
    features["elec_voltage_v"] = _log_normalize(attributes.get("voltage_v"), 0.001, 100000)
    features["elec_current_a"] = _log_normalize(attributes.get("current_a"), 1e-9, 10000)
    features["elec_power_w"] = _log_normalize(attributes.get("power_w"), 0.001, 1e6)

    # Confidence features
    features["conf_overall"] = round(confidence, 6)

    # Flag features
    flag_set = set(flags)
    features["flag_has_mpn"] = 1.0 if attributes.get("manufacturer_part_number") else 0.0
    features["flag_is_custom"] = 1.0 if category in ("custom_mechanical", "machined", "sheet_metal") else 0.0
    features["flag_is_raw"] = 1.0 if category == "raw_material" else 0.0
    features["flag_review_required"] = 1.0 if "NEEDS_MANUAL_REVIEW" in flag_set else 0.0
    features["flag_missing_material"] = 1.0 if "MISSING_MATERIAL" in flag_set else 0.0

    # Material features: one-hot for top materials
    material = str(attributes.get("material", "")).lower().replace(" ", "_")
    for mat in _TOP_MATERIALS:
        features[f"mat_{mat}"] = 1.0 if mat in material else 0.0

    return features
