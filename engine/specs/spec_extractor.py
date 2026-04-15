"""Specification extraction from component text.

extract_specs: legacy regex-based (retained for /api/analyze-bom).
extract_specs_from_tokens: deterministic token-aware extraction for decomposed pipeline.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from engine.normalization.reference_loader import get_normalization_references

logger = logging.getLogger("spec_extractor")

DIMENSION_PATTERN = re.compile(
    r"(\d+(?:\.\d+)?)\s*[xX×]\s*(\d+(?:\.\d+)?)(?:\s*[xX×]\s*(\d+(?:\.\d+)?))?\s*(mm|cm|in|inch|m)?"
)
DIAMETER_PATTERN = re.compile(
    r"(?:\b(?:dia|diameter)\b|[øØ])\s*[:=]?\s*(\d+(?:\.\d+)?)\s*(mm|cm|in|inch|m)?",
    re.I,
)
THICKNESS_PATTERN = re.compile(r"(?:\bthick(?:ness)?\b|\bthk\b|\bt\b)\s*[:=]?\s*(\d+(?:\.\d+)?)\s*(mm|cm|in|inch|m)?", re.I)
LENGTH_PATTERN = re.compile(r"(?:\blength\b|\blen\b|\bl\b)\s*[:=]?\s*(\d+(?:\.\d+)?)\s*(mm|cm|in|inch|m|ft)?", re.I)
WIDTH_PATTERN = re.compile(r"(?:\bwidth\b|\bw\b)\s*[:=]?\s*(\d+(?:\.\d+)?)\s*(mm|cm|in|inch|m)?", re.I)
HEIGHT_PATTERN = re.compile(r"(?:\bheight\b|\bh\b)\s*[:=]?\s*(\d+(?:\.\d+)?)\s*(mm|cm|in|inch|m)?", re.I)
WEIGHT_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*(kg|g|lb|oz)\b", re.I)
VOLTAGE_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*(k|m|u|µ|n|p)?\s*(v|volt|volts)\b", re.I)
CURRENT_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*(k|m|u|µ|n|p)?\s*(a|amp|amps|ampere|amperes)\b", re.I)
POWER_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*(k|m|u|µ|n|p)?\s*(w|watt|watts)\b", re.I)
RESISTANCE_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*(k|m|g)?\s*(?:ohm|ohms|ω|Ω|r)(?=\b|\s|$)", re.I)
CAPACITANCE_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*(p|n|u|µ|m)?\s*(f|farad|farads)\b", re.I)
TOLERANCE_PERCENT_PATTERN = re.compile(r"(?:±\s*(\d+(?:\.\d+)?)\s*%|(\d+(?:\.\d+)?)\s*%)", re.I)
TOLERANCE_DIM_PATTERN = re.compile(r"([±+\-]\s*\d+(?:\.\d+)?)\s*(mm|cm|in|inch|thou|µm|um|mils?)\b", re.I)
THREAD_PATTERN = re.compile(r"\b(M\d+(?:\.\d+)?(?:\s*[xX]\s*\d+(?:\.\d+)?)?)\b", re.I)
FINISH_PATTERN = re.compile(
    r"\b(anodized|anodizing|plated|painted|powder\s*coat(?:ed)?|chrome|polished|galvanized|zinc\s*plated|black\s*oxide|passivated|nickel\s*plated|hot\s*dip\s*galvanized)\b",
    re.I,
)
GRADE_PATTERN = re.compile(
    r"\b(ss\s*304|ss304|304\s*ss|ss\s*316|ss316|316\s*ss|stainless\s*steel\s*304|stainless\s*steel\s*316|grade\s*[:=]?\s*[a-z0-9.\-]+|class\s*[:=]?\s*[a-z0-9.\-]+)\b",
    re.I,
)
QUANTITY_PATTERN = re.compile(r"(?:\bqty\b|\bquantity\b)\s*[:=]?\s*(\d+)\b|\b(\d+)\s*(pcs?|pieces?|ea|each|nos?)\b", re.I)
TEMP_PATTERN = re.compile(r"(-?\d+(?:\.\d+)?)\s*°?\s*[CF]", re.I)


_UNIT_TO_MM = {
    "mm": 1.0,
    "cm": 10.0,
    "m": 1000.0,
    "in": 25.4,
    "inch": 25.4,
    "ft": 304.8,
}

_VALUE_PREFIX_MULTIPLIERS = {
    "p": 1e-12,
    "n": 1e-9,
    "u": 1e-6,
    "µ": 1e-6,
    "m": 1e-3,
    "k": 1e3,
    "g": 1e9,
}

_MATERIAL_ALIASES = {
    "stainless steel 304": "stainless_steel",
    "stainless steel 316": "stainless_steel",
    "stainless steel": "stainless_steel",
    "ss304": "stainless_steel",
    "ss 304": "stainless_steel",
    "ss316": "stainless_steel",
    "ss 316": "stainless_steel",
    "aluminum": "aluminum",
    "aluminium": "aluminum",
    "brass": "brass",
    "bronze": "bronze",
    "copper": "copper",
    "steel": "steel",
    "carbon steel": "carbon_steel",
    "titanium": "titanium",
    "abs": "abs",
    "nylon": "nylon",
    "polycarbonate": "polycarbonate",
    "peek": "peek",
    "hdpe": "hdpe",
    "ptfe": "ptfe",
}

_PROCESS_HINTS = {
    "laser cut": "laser_cut",
    "laser-cut": "laser_cut",
    "formed": "formed",
    "bent": "bent",
    "bend": "bent",
    "stamped": "stamped",
    "punched": "punched",
    "machined": "machined",
    "cnc": "machined",
    "milled": "milled",
    "turned": "turned",
    "drilled": "drilled",
}


def _to_mm(value: float, unit: str | None) -> float | None:
    if value is None:
        return None
    normalized_unit = (unit or "mm").lower()
    factor = _UNIT_TO_MM.get(normalized_unit)
    if factor is None:
        return None
    return round(value * factor, 6)



def _value_with_prefix_to_base(value: str, prefix: str | None) -> float:
    multiplier = _VALUE_PREFIX_MULTIPLIERS.get((prefix or "").lower(), 1.0)
    return float(value) * multiplier



def _set_attr(attributes: dict[str, Any], key: str, value: Any) -> None:
    if value is None:
        return
    if key not in attributes:
        attributes[key] = value



def _normalize_material(raw: str) -> str:
    cleaned = raw.strip().lower()
    return _MATERIAL_ALIASES.get(cleaned, cleaned.replace(" ", "_"))



def _extract_material(expanded_text: str) -> str | None:
    refs = get_normalization_references()
    candidates = list(refs.materials) + list(_MATERIAL_ALIASES.keys())
    candidates = sorted({c.lower() for c in candidates}, key=len, reverse=True)
    for candidate in candidates:
        if re.search(rf"\b{re.escape(candidate)}\b", expanded_text, re.I):
            return _normalize_material(candidate)
    return None



def _extract_finish(expanded_text: str) -> str | None:
    match = FINISH_PATTERN.search(expanded_text)
    if not match:
        return None
    return match.group(1).strip().lower().replace(" ", "_")



def _extract_grade(expanded_text: str) -> str | None:
    match = GRADE_PATTERN.search(expanded_text)
    if not match:
        return None
    grade = re.sub(r"\s+", " ", match.group(1).strip().lower())
    if grade in {"ss304", "ss 304", "304 ss", "stainless steel 304"}:
        return "ss304"
    if grade in {"ss316", "ss 316", "316 ss", "stainless steel 316"}:
        return "ss316"
    return grade.replace(" ", "_")



def _extract_quantity(expanded_text: str) -> int | None:
    match = QUANTITY_PATTERN.search(expanded_text)
    if not match:
        return None
    qty = match.group(1) or match.group(2)
    try:
        return int(qty)
    except Exception:
        return None



def _extract_process_hints(expanded_text: str) -> list[str]:
    found: list[str] = []
    refs = get_normalization_references()
    for _, hints in refs.process_hints.items():
        for hint in hints:
            if hint in expanded_text and _PROCESS_HINTS.get(hint, hint.replace(" ", "_")) not in found:
                found.append(_PROCESS_HINTS.get(hint, hint.replace(" ", "_")))
    for raw, normalized in _PROCESS_HINTS.items():
        if raw in expanded_text and normalized not in found:
            found.append(normalized)
    return found



def extract_specs(text: str, category: str = "auto") -> dict:
    """Legacy regex-based spec extraction. Retained for /api/analyze-bom."""
    if not text:
        return {}
    specs: dict[str, Any] = {}

    m = DIMENSION_PATTERN.search(text)
    if m:
        dims: dict[str, Any] = {"width": float(m.group(1)), "height": float(m.group(2))}
        if m.group(3):
            dims["depth"] = float(m.group(3))
        if m.group(4):
            dims["unit"] = m.group(4)
        specs["dimensions"] = dims

    for name, pat in [("diameter", DIAMETER_PATTERN), ("thickness", THICKNESS_PATTERN), ("length", LENGTH_PATTERN)]:
        m = pat.search(text)
        if m:
            specs[name] = {"value": float(m.group(1)), "unit": m.group(2) or "mm"}

    m = WEIGHT_PATTERN.search(text)
    if m:
        specs["weight"] = {"value": float(m.group(1)), "unit": m.group(2)}

    for name, pat in [
        ("voltage", VOLTAGE_PATTERN),
        ("current", CURRENT_PATTERN),
        ("resistance", RESISTANCE_PATTERN),
        ("capacitance", CAPACITANCE_PATTERN),
        ("power", POWER_PATTERN),
    ]:
        m = pat.search(text)
        if m:
            specs[name] = m.group(0).strip()

    m = THREAD_PATTERN.search(text)
    if m:
        specs["thread"] = m.group(1)

    m = GRADE_PATTERN.search(text)
    if m:
        specs["grade"] = m.group(1)

    m = FINISH_PATTERN.search(text)
    if m:
        specs["finish"] = m.group(1).strip()

    m = TOLERANCE_DIM_PATTERN.search(text)
    if m:
        specs["tolerance"] = f"{m.group(1).strip()} {m.group(2)}".strip()
    else:
        m = TOLERANCE_PERCENT_PATTERN.search(text)
        if m:
            specs["tolerance"] = m.group(0).strip()

    m = TEMP_PATTERN.search(text)
    if m:
        specs["temperature_rating"] = m.group(0).strip()

    return specs



def extract_specs_from_tokens(tokens: list, expanded_text: str) -> dict:
    """Deterministic token-aware extraction for the normalization pipeline.

    Keeps the existing spec_json shape while extending it with a flat
    `attributes` map for Batch D structured extraction.
    """
    specs: dict[str, Any] = {}
    attributes: dict[str, Any] = {}

    normalized_text = (expanded_text or "").lower()

    for token in tokens:
        tt = token.token_type
        val = token.value

        if tt == "dimension":
            m = DIMENSION_PATTERN.match(val)
            if m:
                unit = (m.group(4) or "mm").lower()
                width = float(m.group(1))
                height = float(m.group(2))
                depth = float(m.group(3)) if m.group(3) else None
                dims: dict[str, Any] = {"width": width, "height": height, "unit": unit}
                if depth is not None:
                    dims["depth"] = depth
                specs["dimensions"] = {
                    "value": dims,
                    "confidence": 0.92,
                    "extraction_method": "token_extraction",
                }
                _set_attr(attributes, "width_mm", _to_mm(width, unit))
                _set_attr(attributes, "height_mm", _to_mm(height, unit))
                if depth is not None:
                    _set_attr(attributes, "thickness_mm", _to_mm(depth, unit))

        elif tt == "thread_spec":
            thread_value = val.upper().replace(" ", "")
            specs["thread"] = {
                "value": thread_value,
                "unit": None,
                "confidence": 0.94,
                "extraction_method": "token_extraction",
            }
            _set_attr(attributes, "thread_size", thread_value)
            thread_match = re.match(r"M(\d+(?:\.\d+)?)", thread_value, re.I)
            if thread_match:
                _set_attr(attributes, "diameter_mm", float(thread_match.group(1)))

        elif tt == "tolerance":
            tol_value = val.strip()
            specs["tolerance"] = {
                "value": tol_value,
                "unit": None,
                "confidence": 0.87,
                "extraction_method": "token_extraction",
            }
            percent_match = TOLERANCE_PERCENT_PATTERN.search(tol_value)
            if percent_match:
                pct = percent_match.group(1) or percent_match.group(2)
                _set_attr(attributes, "tolerance_percent", float(pct))

        elif tt == "package_type":
            specs["package_type"] = {
                "value": val,
                "confidence": 0.95,
                "extraction_method": "token_extraction",
            }

        elif tt == "grade_reference":
            specs["grade"] = {
                "value": val,
                "confidence": 0.85,
                "extraction_method": "token_extraction",
            }

        elif tt == "finish_reference":
            finish_val = val.strip().lower().replace(" ", "_")
            specs["finish"] = {
                "value": finish_val,
                "confidence": 0.9,
                "extraction_method": "token_extraction",
            }
            _set_attr(attributes, "finish", finish_val)

        elif tt == "material_reference":
            material_val = _normalize_material(val)
            specs["material"] = {
                "value": material_val,
                "confidence": 0.92,
                "extraction_method": "token_extraction",
            }
            _set_attr(attributes, "material", material_val)

        elif tt == "value_unit_pair":
            raw_lower = val.lower()
            parsed = re.match(
                r"(\d+(?:\.\d+)?)\s*(k|m|u|µ|n|p|g)?\s*(ohm|ohms|Ω|ω|f|farad|farads|v|volt|volts|a|amp|amps|ampere|amperes|w|watt|watts|hz|mm|cm|in|inch|m|kg|g|lb|oz)(?=\b|\s|$)",
                raw_lower,
                re.I,
            )
            normalized_value = token.normalized_value or raw_lower
            if parsed:
                base_value = _value_with_prefix_to_base(parsed.group(1), parsed.group(2))
                unit = parsed.group(3).lower()
                if unit in {"v", "volt", "volts"}:
                    specs["voltage"] = {"value": normalized_value, "confidence": 0.87, "extraction_method": "token_extraction"}
                    _set_attr(attributes, "voltage_v", round(base_value, 12))
                elif unit in {"a", "amp", "amps", "ampere", "amperes"}:
                    specs["current"] = {"value": normalized_value, "confidence": 0.87, "extraction_method": "token_extraction"}
                    _set_attr(attributes, "current_a", round(base_value, 12))
                elif unit in {"w", "watt", "watts"}:
                    specs["power"] = {"value": normalized_value, "confidence": 0.87, "extraction_method": "token_extraction"}
                    _set_attr(attributes, "power_w", round(base_value, 12))
                elif unit in {"ohm", "ohms", "ω", "Ω"}:
                    specs["resistance"] = {"value": normalized_value, "confidence": 0.88, "extraction_method": "token_extraction"}
                    _set_attr(attributes, "resistance_ohm", round(base_value, 12))
                elif unit in {"f", "farad", "farads"}:
                    specs["capacitance"] = {"value": normalized_value, "confidence": 0.88, "extraction_method": "token_extraction"}
                    _set_attr(attributes, "capacitance_f", round(base_value, 18))
                elif unit in {"mm", "cm", "in", "inch", "m"}:
                    if "length" not in specs:
                        specs["length"] = {"value": normalized_value, "confidence": 0.72, "extraction_method": "token_extraction"}
                    _set_attr(attributes, "length_mm", _to_mm(float(parsed.group(1)), unit))
                elif unit in {"kg", "g", "lb", "oz"}:
                    specs["weight"] = {"value": normalized_value, "confidence": 0.85, "extraction_method": "token_extraction"}

    # Regex fallback and structured field completion.
    diameter_match = DIAMETER_PATTERN.search(expanded_text)
    if diameter_match:
        diameter_value = float(diameter_match.group(1))
        diameter_unit = diameter_match.group(2) or "mm"
        if "diameter" not in specs:
            specs["diameter"] = {
                "value": {"value": diameter_value, "unit": diameter_unit},
                "confidence": 0.82,
                "extraction_method": "regex_raw_text",
            }
        _set_attr(attributes, "diameter_mm", _to_mm(diameter_value, diameter_unit))

    thickness_match = THICKNESS_PATTERN.search(expanded_text)
    if thickness_match:
        thickness_value = float(thickness_match.group(1))
        thickness_unit = thickness_match.group(2) or "mm"
        if "thickness" not in specs:
            specs["thickness"] = {
                "value": {"value": thickness_value, "unit": thickness_unit},
                "confidence": 0.8,
                "extraction_method": "regex_raw_text",
            }
        _set_attr(attributes, "thickness_mm", _to_mm(thickness_value, thickness_unit))

    length_match = LENGTH_PATTERN.search(expanded_text)
    if length_match:
        length_value = float(length_match.group(1))
        length_unit = length_match.group(2) or "mm"
        specs.setdefault(
            "length",
            {"value": {"value": length_value, "unit": length_unit}, "confidence": 0.8, "extraction_method": "regex_raw_text"},
        )
        _set_attr(attributes, "length_mm", _to_mm(length_value, length_unit))

    width_match = WIDTH_PATTERN.search(expanded_text)
    if width_match:
        _set_attr(attributes, "width_mm", _to_mm(float(width_match.group(1)), width_match.group(2) or "mm"))

    height_match = HEIGHT_PATTERN.search(expanded_text)
    if height_match:
        _set_attr(attributes, "height_mm", _to_mm(float(height_match.group(1)), height_match.group(2) or "mm"))

    if "voltage" not in specs:
        m = VOLTAGE_PATTERN.search(expanded_text)
        if m:
            specs["voltage"] = {"value": m.group(0).strip(), "confidence": 0.72, "extraction_method": "regex_raw_text"}
            _set_attr(attributes, "voltage_v", round(_value_with_prefix_to_base(m.group(1), m.group(2)), 12))

    if "current" not in specs:
        m = CURRENT_PATTERN.search(expanded_text)
        if m:
            specs["current"] = {"value": m.group(0).strip(), "confidence": 0.72, "extraction_method": "regex_raw_text"}
            _set_attr(attributes, "current_a", round(_value_with_prefix_to_base(m.group(1), m.group(2)), 12))

    if "resistance" not in specs:
        m = RESISTANCE_PATTERN.search(expanded_text)
        if m:
            specs["resistance"] = {"value": m.group(0).strip(), "confidence": 0.74, "extraction_method": "regex_raw_text"}
            _set_attr(attributes, "resistance_ohm", round(_value_with_prefix_to_base(m.group(1), m.group(2)), 12))
        else:
            implied_resistance = re.search(r"\b(\d+(?:\.\d+)?)\s*(k|m|g|r)?\s*resistor\b", expanded_text, re.I)
            if implied_resistance:
                prefix = implied_resistance.group(2)
                ohms = round(_value_with_prefix_to_base(implied_resistance.group(1), prefix if prefix and prefix.lower() != "r" else None), 12)
                specs["resistance"] = {"value": implied_resistance.group(0).strip(), "confidence": 0.62, "extraction_method": "regex_contextual_inference"}
                _set_attr(attributes, "resistance_ohm", ohms)

    if "capacitance" not in specs:
        m = CAPACITANCE_PATTERN.search(expanded_text)
        if m:
            specs["capacitance"] = {"value": m.group(0).strip(), "confidence": 0.74, "extraction_method": "regex_raw_text"}
            _set_attr(attributes, "capacitance_f", round(_value_with_prefix_to_base(m.group(1), m.group(2)), 18))

    if "power" not in specs:
        m = POWER_PATTERN.search(expanded_text)
        if m:
            specs["power"] = {"value": m.group(0).strip(), "confidence": 0.72, "extraction_method": "regex_raw_text"}
            _set_attr(attributes, "power_w", round(_value_with_prefix_to_base(m.group(1), m.group(2)), 12))

    if "thread" not in specs:
        m = THREAD_PATTERN.search(expanded_text)
        if m:
            thread_val = m.group(1).upper().replace(" ", "")
            specs["thread"] = {"value": thread_val, "unit": None, "confidence": 0.75, "extraction_method": "regex_raw_text"}
            _set_attr(attributes, "thread_size", thread_val)
            thread_match = re.match(r"M(\d+(?:\.\d+)?)", thread_val, re.I)
            if thread_match:
                _set_attr(attributes, "diameter_mm", float(thread_match.group(1)))

    if "grade" not in specs:
        grade = _extract_grade(expanded_text)
        if grade:
            specs["grade"] = {"value": grade, "confidence": 0.72, "extraction_method": "regex_raw_text"}
            _set_attr(attributes, "grade", grade)
    else:
        existing_grade = specs["grade"]["value"] if isinstance(specs["grade"], dict) else specs["grade"]
        _set_attr(attributes, "grade", str(existing_grade).lower().replace(" ", "_"))

    if "finish" not in specs:
        finish = _extract_finish(expanded_text)
        if finish:
            specs["finish"] = {"value": finish, "confidence": 0.75, "extraction_method": "regex_raw_text"}
            _set_attr(attributes, "finish", finish)

    if "material" not in specs:
        material = _extract_material(normalized_text)
        if material:
            specs["material"] = {"value": material, "confidence": 0.78, "extraction_method": "reference_lookup"}
            _set_attr(attributes, "material", material)

    if "tolerance" not in specs:
        percent_match = TOLERANCE_PERCENT_PATTERN.search(expanded_text)
        dim_match = TOLERANCE_DIM_PATTERN.search(expanded_text)
        if percent_match:
            pct = percent_match.group(1) or percent_match.group(2)
            specs["tolerance"] = {"value": f"±{pct}%", "confidence": 0.78, "extraction_method": "regex_raw_text"}
            _set_attr(attributes, "tolerance_percent", float(pct))
        elif dim_match:
            specs["tolerance"] = {"value": f"{dim_match.group(1)} {dim_match.group(2)}".strip(), "confidence": 0.76, "extraction_method": "regex_raw_text"}
    else:
        percent_match = TOLERANCE_PERCENT_PATTERN.search(str(specs["tolerance"].get("value", ""))) if isinstance(specs["tolerance"], dict) else None
        if percent_match:
            pct = percent_match.group(1) or percent_match.group(2)
            _set_attr(attributes, "tolerance_percent", float(pct))

    quantity = _extract_quantity(expanded_text)
    if quantity is not None:
        _set_attr(attributes, "quantity", quantity)

    process_hints = _extract_process_hints(normalized_text)
    if process_hints:
        _set_attr(attributes, "process_hints", process_hints)
        specs["process_hints"] = {
            "value": process_hints,
            "confidence": 0.68,
            "extraction_method": "reference_lookup",
        }

    m = TEMP_PATTERN.search(expanded_text)
    if m:
        specs.setdefault("temperature_rating", {"value": m.group(0).strip(), "confidence": 0.68, "extraction_method": "regex_raw_text"})

    if attributes:
        specs["attributes"] = attributes

    return specs
