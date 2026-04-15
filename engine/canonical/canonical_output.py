"""Deterministic canonical part intelligence for normalized BOM lines.

Batch E adds stable, explainable canonical output without introducing a
second identity concept. The generated `normalized_part_key` is also the
value used for the existing `canonical_key` field.
"""
from __future__ import annotations

import re
from typing import Any

from core.canonical_key import build_structured_identity_key


_CATEGORY_LABELS = {
    "fastener": "Fastener",
    "electrical": "Electrical Component",
    "electronics": "Electronic Component",
    "passive_component": "Passive Component",
    "connector": "Connector",
    "sensor": "Sensor",
    "semiconductor": "Semiconductor",
    "power_supply": "Power Supply",
    "raw_material": "Material",
    "sheet_metal": "Sheet",
    "machined": "Machined Part",
    "custom_mechanical": "Custom Mechanical Part",
    "mechanical": "Mechanical Part",
    "enclosure": "Enclosure",
    "standard": "Standard Part",
    "unknown": "Part",
}

_MATERIAL_LABELS = {
    "stainless_steel": "Stainless Steel",
    "carbon_steel": "Carbon Steel",
    "steel": "Steel",
    "aluminum": "Aluminum",
    "brass": "Brass",
    "bronze": "Bronze",
    "copper": "Copper",
    "titanium": "Titanium",
    "abs": "ABS",
    "nylon": "Nylon",
    "polycarbonate": "Polycarbonate",
    "peek": "PEEK",
    "hdpe": "HDPE",
    "ptfe": "PTFE",
}

_FASTENER_NOUNS = (
    ("socket_cap_screw", "Socket Cap Screw"),
    ("set_screw", "Set Screw"),
    ("carriage_bolt", "Carriage Bolt"),
    ("hex_bolt", "Hex Bolt"),
    ("lock_nut", "Lock Nut"),
    ("hex_nut", "Hex Nut"),
    ("wing_nut", "Wing Nut"),
    ("lock_washer", "Lock Washer"),
    ("flat_washer", "Flat Washer"),
    ("spring_washer", "Spring Washer"),
    ("bolt", "Bolt"),
    ("screw", "Screw"),
    ("nut", "Nut"),
    ("washer", "Washer"),
    ("stud", "Stud"),
    ("anchor", "Anchor"),
    ("rivet", "Rivet"),
)

_CATALOG_CATEGORIES = {
    "fastener",
    "electrical",
    "electronics",
    "passive_component",
    "connector",
    "sensor",
    "semiconductor",
    "power_supply",
    "standard",
    "raw_material",
}


def _clean_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def _titleize_token(value: str | None) -> str:
    text = _clean_text(value).replace("_", " ")
    return text.title() if text else ""


def _material_label(material: str | None) -> str:
    cleaned = _clean_text(material).lower().replace(" ", "_")
    if not cleaned:
        return ""
    return _MATERIAL_LABELS.get(cleaned, cleaned.replace("_", " ").title())


def _format_decimal(value: float | int | str | None, decimals: int = 3) -> str:
    if value in (None, ""):
        return ""
    try:
        number = float(value)
    except Exception:
        return _clean_text(str(value))
    if number.is_integer():
        return str(int(number))
    return f"{number:.{decimals}f}".rstrip("0").rstrip(".")


def _format_mm(value: float | int | str | None) -> str:
    formatted = _format_decimal(value)
    return f"{formatted}mm" if formatted else ""


def _format_ohms(value: float | int | str | None) -> str:
    if value in (None, ""):
        return ""
    try:
        ohms = float(value)
    except Exception:
        return _clean_text(str(value))
    abs_ohms = abs(ohms)
    if abs_ohms >= 1_000_000:
        return f"{_format_decimal(ohms / 1_000_000)}MΩ"
    if abs_ohms >= 1_000:
        return f"{_format_decimal(ohms / 1_000)}kΩ"
    return f"{_format_decimal(ohms)}Ω"


def _format_percent(value: float | int | str | None) -> str:
    formatted = _format_decimal(value)
    return f"{formatted}%" if formatted else ""


def _attrs(spec_json: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(spec_json, dict):
        return {}
    attrs = spec_json.get("attributes", {})
    return attrs if isinstance(attrs, dict) else {}


def _contextual_fractional_power_w(normalized_text: str) -> float | None:
    match = re.search(r"\b(\d+)\s*/\s*(\d+)\s*w\b", normalized_text, re.I)
    if not match:
        return None
    denominator = float(match.group(2))
    if denominator == 0:
        return None
    return round(float(match.group(1)) / denominator, 12)


def _contextual_thickness_mm(normalized_text: str) -> float | None:
    match = re.search(r"\b(\d+(?:\.\d+)?)\s*(mm|cm|m|in|inch)\s*thick\b", normalized_text, re.I)
    if not match:
        return None
    value = float(match.group(1))
    unit = match.group(2).lower()
    factors = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4, "inch": 25.4}
    return round(value * factors.get(unit, 1.0), 6)


def _effective_power_w(attrs: dict[str, Any], normalized_text: str) -> float | None:
    contextual = _contextual_fractional_power_w(normalized_text)
    if contextual is not None:
        return contextual
    value = attrs.get("power_w")
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def _effective_thickness_mm(attrs: dict[str, Any], normalized_text: str, category: str) -> float | None:
    contextual = _contextual_thickness_mm(normalized_text)
    if contextual is not None:
        return contextual
    if attrs.get("thickness_mm") is not None:
        try:
            return float(attrs.get("thickness_mm"))
        except Exception:
            return None
    if category == "sheet_metal" and attrs.get("length_mm") is not None and "thick" in normalized_text.lower():
        try:
            candidate = float(attrs.get("length_mm"))
        except Exception:
            candidate = None
        if candidate is not None and candidate <= 1000:
            return candidate
    return None


def _fastener_length_mm(attrs: dict[str, Any], normalized_text: str) -> float | None:
    thread = _clean_text(attrs.get("thread_size")).upper().replace(" ", "")
    if "X" in thread:
        maybe = thread.split("X", 1)[1]
        if re.fullmatch(r"\d+(?:\.\d+)?", maybe):
            return float(maybe)
    text_match = re.findall(r"\b(\d+(?:\.\d+)?)\s*mm\b", normalized_text, re.I)
    if text_match:
        try:
            return float(text_match[-1])
        except Exception:
            pass
    value = attrs.get("length_mm")
    if value is None:
        return None
    try:
        value = float(value)
    except Exception:
        return None
    return value if value <= 1000 else None


def _normalize_fastener_family(subcategory: str | None, normalized_text: str) -> str:
    text = f"{_clean_text(subcategory)} {normalized_text}".lower()
    for family in ("bolt", "screw", "nut", "washer", "stud", "anchor", "rivet"):
        if family in text:
            return family
    return "fastener"

def _pick_fastener_noun(subcategory: str | None, normalized_text: str) -> str:
    lowered_subcategory = _clean_text(subcategory).lower().replace(" ", "_")
    text = normalized_text.lower()
    generic_family = _normalize_fastener_family(subcategory, normalized_text)
    if generic_family == "bolt":
        return "Bolt"
    if generic_family == "screw":
        return "Screw"
    if generic_family == "nut":
        return "Nut"
    if generic_family == "washer":
        return "Washer"
    for key, label in _FASTENER_NOUNS:
        if lowered_subcategory == key or key in text or key.replace("_", " ") in text:
            return label
    return "Fastener"


def _infer_form(category: str, normalized_text: str) -> str:
    text = normalized_text.lower()
    if category == "sheet_metal" or "sheet" in text:
        return "Sheet"
    if "plate" in text:
        return "Plate"
    if "tube" in text or "pipe" in text or "tubing" in text:
        return "Tube"
    if "rod" in text:
        return "Rod"
    if "bar" in text:
        return "Bar"
    if "wire" in text:
        return "Wire"
    return "Material"


def _infer_component_noun(category: str, normalized_text: str) -> str:
    text = normalized_text.lower()
    if "resistor" in text:
        return "Resistor"
    if "capacitor" in text:
        return "Capacitor"
    if "inductor" in text:
        return "Inductor"
    if "diode" in text:
        return "Diode"
    if "transistor" in text:
        return "Transistor"
    if "regulator" in text:
        return "Regulator"
    if "connector" in text:
        return "Connector"
    if "sensor" in text:
        return "Sensor"
    return _CATEGORY_LABELS.get(category, "Part")


def _build_fastener_name(subcategory: str | None, attrs: dict[str, Any], normalized_text: str) -> str:
    noun = _pick_fastener_noun(subcategory, normalized_text)
    parts: list[str] = [noun]
    material = _material_label(attrs.get("material"))
    if material:
        parts.append(material)
    thread = _clean_text(attrs.get("thread_size"))
    if thread:
        parts.append(thread.upper())
    length_mm = _fastener_length_mm(attrs, normalized_text)
    if length_mm:
        if thread:
            parts[-1] = f"{parts[-1]} x {_format_mm(length_mm)}"
        else:
            parts.append(_format_mm(length_mm))
    grade = _titleize_token(attrs.get("grade"))
    if grade:
        parts.append(grade)
    finish = _titleize_token(attrs.get("finish"))
    if finish:
        parts.append(finish)
    return " ".join(part for part in parts if part)


def _build_electronics_name(category: str, attrs: dict[str, Any], normalized_text: str) -> str:
    noun = _infer_component_noun(category, normalized_text)
    parts: list[str] = [noun]
    if attrs.get("resistance_ohm") is not None:
        parts.append(_format_ohms(attrs.get("resistance_ohm")))
    if attrs.get("capacitance_f") is not None:
        cap = attrs.get("capacitance_f")
        if isinstance(cap, (int, float)):
            if cap >= 1e-6:
                parts.append(f"{_format_decimal(cap / 1e-6)}µF")
            elif cap >= 1e-9:
                parts.append(f"{_format_decimal(cap / 1e-9)}nF")
            else:
                parts.append(f"{_format_decimal(cap / 1e-12)}pF")
    if attrs.get("inductance_h") is not None:
        parts.append(f"{_format_decimal(attrs.get('inductance_h'))}H")
    effective_power = _effective_power_w(attrs, normalized_text)
    if effective_power is not None:
        parts.append(f"{_format_decimal(effective_power)}W")
    if attrs.get("voltage_v") is not None:
        parts.append(f"{_format_decimal(attrs.get('voltage_v'))}V")
    if attrs.get("current_a") is not None:
        parts.append(f"{_format_decimal(attrs.get('current_a'))}A")
    tolerance = _format_percent(attrs.get("tolerance_percent"))
    if tolerance:
        parts.append(tolerance)
    package = _clean_text((attrs.get("package_type") or "")).upper()
    if package:
        parts.append(package)
    return " ".join(part for part in parts if part)


def _build_material_name(category: str, attrs: dict[str, Any], normalized_text: str) -> str:
    form = _infer_form(category, normalized_text)
    material = _material_label(attrs.get("material"))
    parts = [form]
    if material:
        parts.append(material)
    thickness_mm = _effective_thickness_mm(attrs, normalized_text, category)
    if thickness_mm is not None:
        parts.append(_format_mm(thickness_mm))
    elif attrs.get("diameter_mm") is not None and form in {"Rod", "Tube", "Wire"}:
        parts.append(_format_mm(attrs.get("diameter_mm")))
    return " ".join(part for part in parts if part)


def _build_mechanical_name(category: str, subcategory: str | None, attrs: dict[str, Any], normalized_text: str) -> str:
    base = _titleize_token(subcategory) or _CATEGORY_LABELS.get(category, "Mechanical Part")
    if category == "sheet_metal":
        base = "Sheet Metal Part"
    elif category == "machined":
        base = "Machined Part"
    elif category == "custom_mechanical":
        base = "Custom Mechanical Part"

    parts = [base]
    material = _material_label(attrs.get("material"))
    if material:
        parts.append(material)
    dims = [
        _format_mm(attrs.get("width_mm")),
        _format_mm(attrs.get("height_mm")),
        _format_mm(attrs.get("thickness_mm")),
    ]
    compact_dims = [d for d in dims if d]
    if compact_dims:
        parts.append(" x ".join(compact_dims))
    elif attrs.get("diameter_mm") is not None:
        parts.append(_format_mm(attrs.get("diameter_mm")))
    finish = _titleize_token(attrs.get("finish"))
    if finish:
        parts.append(finish)
    return " ".join(part for part in parts if part)


def generate_canonical_name(category: str, subcategory: str | None, normalized_text: str, spec_json: dict[str, Any] | None) -> str:
    attrs = _attrs(spec_json)
    if category == "fastener":
        return _build_fastener_name(subcategory, attrs, normalized_text)
    if category in {"electronics", "electrical", "passive_component", "connector", "sensor", "semiconductor", "power_supply"}:
        return _build_electronics_name(category, attrs, normalized_text)
    if category in {"raw_material", "sheet_metal"} and (attrs.get("material") or attrs.get("thickness_mm") is not None):
        return _build_material_name(category, attrs, normalized_text)
    if category in {"mechanical", "machined", "custom_mechanical", "enclosure"}:
        return _build_mechanical_name(category, subcategory, attrs, normalized_text)

    material = _material_label(attrs.get("material"))
    base = _CATEGORY_LABELS.get(category, "Part")
    fallback = " ".join(part for part in [base, material] if part).strip()
    if category == "unknown":
        text = _clean_text(normalized_text)
        if text:
            return text[:120]
    return fallback or _clean_text(normalized_text)[:120] or "Part"


def _normalized_key_material(attrs: dict[str, Any]) -> str | None:
    material = _clean_text(attrs.get("material")).lower().replace(" ", "_")
    return material or None


def _key_dimension_triplet(attrs: dict[str, Any]) -> str | None:
    dims = [attrs.get("width_mm"), attrs.get("height_mm"), attrs.get("thickness_mm")]
    formatted = [_format_mm(value) for value in dims if value is not None]
    return "x".join(formatted) if formatted else None


def _normalized_key_parts(category: str, subcategory: str | None, normalized_text: str, spec_json: dict[str, Any] | None) -> list[str]:
    attrs = _attrs(spec_json)
    parts: list[str] = []

    if category == "fastener":
        parts.append(_normalize_fastener_family(subcategory, normalized_text))
        if _normalized_key_material(attrs):
            parts.append(_normalized_key_material(attrs))
        thread = _clean_text(attrs.get("thread_size")).lower().replace(" ", "")
        if thread:
            parts.append(thread)
        if attrs.get("length_mm") is not None:
            parts.append(_format_mm(attrs.get("length_mm")))
        if attrs.get("grade"):
            parts.append(_clean_text(str(attrs.get("grade"))).lower().replace(" ", "_"))
        if attrs.get("finish"):
            parts.append(_clean_text(str(attrs.get("finish"))).lower().replace(" ", "_"))
        return [part for part in parts if part]

    if category in {"electronics", "electrical", "passive_component", "connector", "sensor", "semiconductor", "power_supply"}:
        parts.append(_infer_component_noun(category, normalized_text).lower().replace(" ", "_"))
        for key in ("resistance_ohm", "capacitance_f", "inductance_h", "voltage_v", "current_a", "power_w"):
            value = attrs.get(key)
            if value is not None:
                unit = key.split("_", 1)[1]
                if unit == "ohm":
                    parts.append(f"{_format_decimal(value)}ohm")
                elif unit == "f":
                    parts.append(f"{_format_decimal(value, 12)}f")
                elif unit == "h":
                    parts.append(f"{_format_decimal(value, 12)}h")
                elif key == "power_w":
                    parts.append(f"{_format_decimal(_effective_power_w(attrs, normalized_text) or value)}{unit}")
                else:
                    parts.append(f"{_format_decimal(value)}{unit}")
        if attrs.get("tolerance_percent") is not None:
            parts.append(f"{_format_decimal(attrs.get('tolerance_percent'))}pct")
        package = _clean_text(attrs.get("package_type")).lower()
        if package:
            parts.append(package)
        return parts

    if category in {"raw_material", "sheet_metal"}:
        parts.append(_infer_form(category, normalized_text).lower())
        if _normalized_key_material(attrs):
            parts.append(_normalized_key_material(attrs))
        triplet = _key_dimension_triplet(attrs)
        thickness_mm = _effective_thickness_mm(attrs, normalized_text, category)
        if triplet:
            parts.append(triplet)
        elif thickness_mm is not None:
            parts.append(_format_mm(thickness_mm))
        return parts

    if category in {"mechanical", "machined", "custom_mechanical", "enclosure"}:
        parts.append((_clean_text(subcategory) or category).lower().replace(" ", "_").replace("__", "_"))
        if _normalized_key_material(attrs):
            parts.append(_normalized_key_material(attrs))
        triplet = _key_dimension_triplet(attrs)
        if triplet:
            parts.append(triplet)
        elif attrs.get("diameter_mm") is not None:
            parts.append(_format_mm(attrs.get("diameter_mm")))
        if attrs.get("tolerance_percent") is not None:
            parts.append(f"{_format_decimal(attrs.get('tolerance_percent'))}pct")
        if attrs.get("finish"):
            parts.append(_clean_text(str(attrs.get("finish"))).lower().replace(" ", "_"))
        return parts

    if _normalized_key_material(attrs):
        parts.append(_normalized_key_material(attrs))
    triplet = _key_dimension_triplet(attrs)
    if triplet:
        parts.append(triplet)
    return parts


def suggest_processes(category: str, normalized_text: str, spec_json: dict[str, Any] | None) -> list[str]:
    attrs = _attrs(spec_json)
    hints = attrs.get("process_hints") if isinstance(attrs.get("process_hints"), list) else []
    lowered_hints = {str(h).lower() for h in hints}
    suggestions: list[str] = []

    def add(name: str) -> None:
        if name not in suggestions:
            suggestions.append(name)

    if category == "sheet_metal":
        if lowered_hints & {"laser_cut", "punched", "stamped"} or attrs.get("width_mm") is not None:
            add("laser_cutting")
        if lowered_hints & {"bent", "formed"} or attrs.get("thickness_mm") is not None:
            add("bending")
        return suggestions[:3]

    if category in {"machined", "custom_mechanical", "mechanical", "enclosure"}:
        if lowered_hints & {"machined", "milled", "turned", "drilled"} or attrs.get("diameter_mm") is not None or attrs.get("tolerance_percent") is not None:
            add("cnc_machining")
        if "drilled" in lowered_hints:
            add("drilling")
        if attrs.get("finish") in {"anodized", "anodizing"}:
            add("anodizing")
        return suggestions[:3]

    return []


def determine_drawing_required(category: str, normalized_text: str, spec_json: dict[str, Any] | None) -> bool:
    attrs = _attrs(spec_json)
    text = normalized_text.lower()
    has_dims = any(attrs.get(key) is not None for key in ("width_mm", "height_mm", "thickness_mm", "diameter_mm", "length_mm"))
    has_tolerance = attrs.get("tolerance_percent") is not None or "tolerance" in (spec_json or {})
    if category in {"custom_mechanical", "machined"}:
        return True
    if category == "sheet_metal":
        return bool(has_dims or has_tolerance or attrs.get("process_hints"))
    if category in {"mechanical", "enclosure"} and (has_tolerance or "drawing" in text or "dwg" in text or "print" in text):
        return True
    return False


def determine_requires_rfq(category: str, normalized_text: str, spec_json: dict[str, Any] | None, drawing_required: bool) -> bool:
    attrs = _attrs(spec_json)
    text = normalized_text.lower()
    if category in {"custom_mechanical", "sheet_metal", "machined"}:
        return True
    if drawing_required:
        return True
    if category in _CATALOG_CATEGORIES or category == "unknown":
        return False
    has_custom_dimensions = sum(1 for key in ("width_mm", "height_mm", "thickness_mm", "diameter_mm", "length_mm") if attrs.get(key) is not None) >= 2
    has_custom_hints = any(word in text for word in ("custom", "fabricated", "prototype", "drawing", "dwg", "made to print"))
    if category == "unknown" and (has_custom_dimensions or has_custom_hints):
        return True
    return False


def build_canonical_output(category: str, subcategory: str | None, normalized_text: str, spec_json: dict[str, Any] | None) -> dict[str, Any]:
    canonical_name = generate_canonical_name(category, subcategory, normalized_text, spec_json)
    key_parts = _normalized_key_parts(category, subcategory, normalized_text, spec_json)
    normalized_part_key = build_structured_identity_key(category, key_parts)
    suggested_processes = suggest_processes(category, normalized_text, spec_json)
    drawing_required = determine_drawing_required(category, normalized_text, spec_json)
    requires_rfq = determine_requires_rfq(category, normalized_text, spec_json, drawing_required)
    return {
        "canonical_name": canonical_name,
        "normalized_part_key": normalized_part_key,
        "suggested_processes": suggested_processes,
        "requires_rfq": requires_rfq,
        "drawing_required": drawing_required,
    }