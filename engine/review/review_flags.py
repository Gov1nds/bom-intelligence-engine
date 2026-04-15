"""Deterministic review flag and uncertainty detection for normalized BOM lines.

Batch F annotates, but never blocks, the normalization output.
"""
from __future__ import annotations

import re
from typing import Any


_LOW_CONFIDENCE_THRESHOLD = 0.55
_AMBIGUOUS_CONFIDENCE_THRESHOLD = 0.70
_WEAK_EXTRACTION_CONFIDENCE_THRESHOLD = 0.75

_MISSING_PLACEHOLDER_PATTERNS = (
    "tbd",
    "to be defined",
    "unknown",
    "n/a",
    "na",
    "?",
    "xxx",
    "xx",
)

_CRITICAL_ATTRIBUTE_RULES: dict[str, tuple[tuple[str, ...], ...]] = {
    "fastener": (("thread_size",), ("length_mm",), ("material",)),
    "electronics": (("resistance_ohm", "capacitance_f"), ("tolerance_percent", "voltage_v")),
    "passive_component": (("resistance_ohm", "capacitance_f"), ("tolerance_percent", "voltage_v")),
    "electrical": (("voltage_v", "current_a", "power_w"),),
    "sheet_metal": (("thickness_mm",), ("material",)),
    "custom_mechanical": (("width_mm", "height_mm", "thickness_mm", "diameter_mm", "length_mm", "process_hints"),),
    "machined": (("width_mm", "height_mm", "thickness_mm", "diameter_mm", "length_mm", "tolerance_percent"),),
    "mechanical": (("width_mm", "height_mm", "thickness_mm", "diameter_mm", "length_mm", "process_hints"),),
    "raw_material": (("material",), ("thickness_mm", "diameter_mm", "length_mm", "width_mm", "height_mm")),
}

_DIMENSION_KEYS = ("width_mm", "height_mm", "thickness_mm", "diameter_mm", "length_mm")


_UNIT_PATTERN = re.compile(r"\b(mm|cm|m|in|inch|ft|kg|g|lb|oz|v|volt|volts|a|amp|amps|w|watt|watts|ohm|ohms|Ω|ω|f|farad|farads)\b", re.I)
_BARE_NUMBER_PATTERN = re.compile(r"\b\d+(?:\.\d+)?\b")
_UNKNOWN_TOKEN_PATTERN = re.compile(r"\b(?:unknown|tbd|n/?a|xxx|unspecified|generic)\b|[?]{2,}", re.I)
_MATERIAL_PATTERN = re.compile(
    r"\b(stainless\s*steel(?:\s*304|\s*316)?|ss\s*304|ss\s*316|ss304|ss316|aluminum|aluminium|brass|bronze|copper|carbon\s*steel|steel|titanium|abs|nylon|polycarbonate|peek|hdpe|ptfe)\b",
    re.I,
)


def _attrs(spec_json: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(spec_json, dict):
        return {}
    attrs = spec_json.get("attributes", {})
    return attrs if isinstance(attrs, dict) else {}


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) > 0
    return True


def _has_any(attrs: dict[str, Any], keys: tuple[str, ...]) -> bool:
    return any(_present(attrs.get(key)) for key in keys)


def _collect_spec_confidences(spec_json: dict[str, Any] | None) -> list[float]:
    if not isinstance(spec_json, dict):
        return []
    confidences: list[float] = []
    for value in spec_json.values():
        if isinstance(value, dict):
            confidence = value.get("confidence")
            if isinstance(confidence, (int, float)):
                confidences.append(float(confidence))
    return confidences


def _material_mentions(normalized_text: str) -> list[str]:
    found: list[str] = []
    for match in _MATERIAL_PATTERN.finditer(normalized_text or ""):
        token = re.sub(r"\s+", " ", match.group(1).strip().lower())
        if token not in found:
            found.append(token)
    return found


def _unknown_tokens_present(normalized_text: str) -> bool:
    return bool(_UNKNOWN_TOKEN_PATTERN.search(normalized_text or ""))


def _multiple_units(normalized_text: str) -> bool:
    units = {m.group(1).lower() for m in _UNIT_PATTERN.finditer(normalized_text or "")}
    canonical = set()
    for unit in units:
        if unit in {"volt", "volts"}:
            canonical.add("v")
        elif unit in {"amp", "amps"}:
            canonical.add("a")
        elif unit in {"watt", "watts"}:
            canonical.add("w")
        elif unit in {"ohm", "ohms", "ω", "Ω"}:
            canonical.add("ohm")
        elif unit in {"farad", "farads"}:
            canonical.add("f")
        elif unit == "inch":
            canonical.add("in")
        else:
            canonical.add(unit)
    return len(canonical) >= 2


def _missing_unit(normalized_text: str, attrs: dict[str, Any]) -> bool:
    has_numeric_signal = bool(_BARE_NUMBER_PATTERN.search(normalized_text or ""))
    has_units = bool(_UNIT_PATTERN.search(normalized_text or ""))
    has_dimensional_attrs = any(_present(attrs.get(key)) for key in _DIMENSION_KEYS)
    return has_numeric_signal and has_dimensional_attrs is False and not has_units


def _has_conflicting_attributes(normalized_text: str, attrs: dict[str, Any]) -> bool:
    materials = _material_mentions(normalized_text)
    if len(materials) > 1:
        return True
    material_attr = attrs.get("material")
    if _present(material_attr) and len(materials) == 1:
        normalized_attr = str(material_attr).strip().lower().replace("_", " ")
        if "stainless steel" in normalized_attr:
            normalized_attr = "stainless steel"
        if materials[0] not in normalized_attr and normalized_attr not in materials[0]:
            return True
    return False


def _minimal_expectations_satisfied(category: str, attrs: dict[str, Any]) -> bool:
    rule_sets = _CRITICAL_ATTRIBUTE_RULES.get(category, ())
    if not rule_sets:
        return True
    return all(_has_any(attrs, keys) for keys in rule_sets)


def _canonical_output_strength(canonical_output: dict[str, Any], attrs: dict[str, Any]) -> bool:
    if not isinstance(canonical_output, dict):
        return False
    if canonical_output.get("normalized_part_key") and canonical_output.get("canonical_name"):
        return True
    return bool(attrs)


def detect_review_and_uncertainty_flags(
    *,
    category: str,
    classification_confidence: float,
    spec_json: dict[str, Any] | None,
    canonical_output: dict[str, Any] | None,
    normalized_text: str,
    ambiguity_flags: list[str] | None = None,
) -> tuple[list[str], list[str]]:
    attrs = _attrs(spec_json)
    ambiguity_flags = ambiguity_flags or []
    review_flags: list[str] = []
    uncertainty_flags: list[str] = []

    def add_review(flag: str) -> None:
        if flag not in review_flags:
            review_flags.append(flag)

    def add_uncertainty(flag: str) -> None:
        if flag not in uncertainty_flags:
            uncertainty_flags.append(flag)

    spec_confidences = _collect_spec_confidences(spec_json)
    min_spec_confidence = min(spec_confidences) if spec_confidences else None
    has_strong_canonical_output = _canonical_output_strength(canonical_output or {}, attrs)
    text = (normalized_text or "").strip().lower()
    word_count = len([p for p in re.split(r"\s+", text) if p])

    if classification_confidence < _LOW_CONFIDENCE_THRESHOLD:
        add_review("LOW_CONFIDENCE_CATEGORY")
    if category == "unknown" or (classification_confidence < _AMBIGUOUS_CONFIDENCE_THRESHOLD and ambiguity_flags):
        add_review("AMBIGUOUS_CATEGORY")
    if category == "unknown" and has_strong_canonical_output is False:
        add_review("POSSIBLE_MISCLASSIFICATION")
    if word_count <= 2 or any(marker in text for marker in _MISSING_PLACEHOLDER_PATTERNS):
        add_review("WEAK_SIGNAL_INPUT")
    if any(flag in {"multiple_materials", "close_match_scores"} for flag in ambiguity_flags):
        add_review("MULTIPLE_POSSIBLE_INTERPRETATIONS")
    if not _minimal_expectations_satisfied(category, attrs):
        add_review("MISSING_CRITICAL_ATTRIBUTE")
    if len(attrs) <= 1 or not spec_confidences:
        add_review("INSUFFICIENT_SPEC")
    elif min_spec_confidence is not None and min_spec_confidence < _WEAK_EXTRACTION_CONFIDENCE_THRESHOLD:
        add_review("INSUFFICIENT_SPEC")

    if attrs.get("material") in (None, ""):
        add_uncertainty("MISSING_MATERIAL")
    if not any(_present(attrs.get(key)) for key in _DIMENSION_KEYS) and category in {"fastener", "sheet_metal", "custom_mechanical", "machined", "mechanical", "raw_material"}:
        add_uncertainty("MISSING_DIMENSION")
    if _missing_unit(text, attrs):
        add_uncertainty("MISSING_UNIT")
    if _multiple_units(text):
        add_uncertainty("MULTIPLE_UNITS")
    if _has_conflicting_attributes(text, attrs):
        add_uncertainty("CONFLICTING_ATTRIBUTES")
    if min_spec_confidence is not None and min_spec_confidence < _WEAK_EXTRACTION_CONFIDENCE_THRESHOLD:
        add_uncertainty("LOW_CONFIDENCE_EXTRACTION")
    if _unknown_tokens_present(text):
        add_uncertainty("UNKNOWN_TOKEN_PRESENT")

    if review_flags or uncertainty_flags or classification_confidence < _AMBIGUOUS_CONFIDENCE_THRESHOLD:
        add_review("NEEDS_MANUAL_REVIEW")

    return review_flags, uncertainty_flags
