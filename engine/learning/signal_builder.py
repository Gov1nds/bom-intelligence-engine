"""Deterministic learning signal builder for analyzed BOM lines.

Batch G emits a stable, log-safe learning payload without introducing
state, persistence, or external dependencies.
"""
from __future__ import annotations

from typing import Any

from engine.review.review_flags import _attrs


_MAJOR_UNCERTAINTY_FLAGS = {
    "CONFLICTING_ATTRIBUTES",
    "LOW_CONFIDENCE_EXTRACTION",
    "UNKNOWN_TOKEN_PRESENT",
    "MISSING_DIMENSION",
    "MISSING_MATERIAL",
    "MISSING_UNIT",
    "MULTIPLE_UNITS",
}

_CRITICAL_ATTRIBUTE_KEYS: dict[str, tuple[str, ...]] = {
    "fastener": ("thread_size", "length_mm", "material"),
    "electronics": ("resistance_ohm", "capacitance_f", "tolerance_percent", "voltage_v"),
    "passive_component": ("resistance_ohm", "capacitance_f", "tolerance_percent", "voltage_v"),
    "electrical": ("voltage_v", "current_a", "power_w"),
    "sheet_metal": ("thickness_mm", "material"),
    "custom_mechanical": ("width_mm", "height_mm", "thickness_mm", "diameter_mm", "length_mm", "process_hints"),
    "machined": ("width_mm", "height_mm", "thickness_mm", "diameter_mm", "length_mm", "tolerance_percent"),
    "mechanical": ("width_mm", "height_mm", "thickness_mm", "diameter_mm", "length_mm", "process_hints"),
    "raw_material": ("material", "thickness_mm", "diameter_mm", "length_mm", "width_mm", "height_mm"),
}


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) > 0
    return True


def _normalize_attributes(spec_json: dict[str, Any] | None) -> dict[str, Any]:
    attrs = _attrs(spec_json)
    stable: dict[str, Any] = {}
    for key in sorted(attrs):
        value = attrs[key]
        if isinstance(value, dict):
            stable[key] = {k: value[k] for k in sorted(value)}
        elif isinstance(value, set):
            stable[key] = sorted(value)
        else:
            stable[key] = value
    return stable


def _signal_strength(category_confidence: float, review_flags: list[str], uncertainty_flags: list[str]) -> str:
    review_count = len(review_flags)
    uncertainty_count = len(uncertainty_flags)
    has_critical_review = "MISSING_CRITICAL_ATTRIBUTE" in review_flags

    if (
        category_confidence >= 0.85
        and not has_critical_review
        and review_count <= 2
        and uncertainty_count <= 1
    ):
        return "strong"
    if category_confidence < 0.60 or has_critical_review or review_count >= 3 or uncertainty_count >= 3:
        return "weak"
    return "medium"


def _critical_attribute_status(category: str, attributes: dict[str, Any]) -> tuple[int, int]:
    keys = _CRITICAL_ATTRIBUTE_KEYS.get(category, ())
    if not keys:
        return 0, 0
    present = sum(1 for key in keys if _present(attributes.get(key)))
    return present, len(keys)


def _extraction_quality(
    *,
    category: str,
    attributes: dict[str, Any],
    review_flags: list[str],
    uncertainty_flags: list[str],
    signal_strength: str,
) -> str:
    critical_present, critical_total = _critical_attribute_status(category, attributes)
    has_missing_critical = "MISSING_CRITICAL_ATTRIBUTE" in review_flags
    major_uncertainty_count = sum(1 for flag in uncertainty_flags if flag in _MAJOR_UNCERTAINTY_FLAGS)

    if signal_strength == "weak" or has_missing_critical or major_uncertainty_count >= 2:
        return "poor"
    if critical_total == 0:
        return "complete" if attributes else "partial"
    if critical_present == critical_total:
        return "complete"
    if critical_present == 0:
        return "poor"
    return "partial"


def _has_critical_missing(review_flags: list[str], uncertainty_flags: list[str]) -> bool:
    if "MISSING_CRITICAL_ATTRIBUTE" in review_flags:
        return True
    major_uncertainty_count = sum(1 for flag in uncertainty_flags if flag in _MAJOR_UNCERTAINTY_FLAGS)
    return major_uncertainty_count >= 2


def build_learning_signals(
    *,
    raw_input: str,
    normalized_text: str,
    canonical_name: str,
    normalized_part_key: str,
    category: str,
    category_confidence: float,
    spec_json: dict[str, Any] | None,
    review_flags: list[str] | None,
    uncertainty_flags: list[str] | None,
) -> dict[str, Any]:
    """Build a deterministic, externally safe learning payload."""
    review_flags = list(review_flags or [])
    uncertainty_flags = list(uncertainty_flags or [])
    attributes = _normalize_attributes(spec_json)

    signal_strength = _signal_strength(category_confidence, review_flags, uncertainty_flags)
    extraction_quality = _extraction_quality(
        category=category,
        attributes=attributes,
        review_flags=review_flags,
        uncertainty_flags=uncertainty_flags,
        signal_strength=signal_strength,
    )
    has_critical_missing = _has_critical_missing(review_flags, uncertainty_flags)

    return {
        "raw_input": raw_input or "",
        "normalized_text": normalized_text or "",
        "canonical_name": canonical_name or "",
        "normalized_part_key": normalized_part_key or "",
        "category": category or "unknown",
        "category_confidence": round(float(category_confidence or 0.0), 4),
        "attributes": attributes,
        "review_flags": review_flags,
        "uncertainty_flags": uncertainty_flags,
        "signal_strength": signal_strength,
        "extraction_quality": extraction_quality,
        "has_critical_missing": has_critical_missing,
    }