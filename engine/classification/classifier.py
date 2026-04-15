"""Component classification — deterministic category detection and confidence scoring.

classify_item / classify_bom: legacy keyword-based path retained for /api/analyze-bom.
classify_from_tokens: deterministic token-aware classification used by the normalization pipeline.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Iterable

from core.schemas import MaterialForm, PartCategory, ProcurementClass
from engine.normalization.reference_loader import get_normalization_references
from engine.normalization.text_normalizer import normalize_text

logger = logging.getLogger("classifier")

CATEGORY_KEYWORDS = {
    PartCategory.fastener: ["bolt", "nut", "screw", "washer", "rivet", "stud", "threaded rod", "anchor"],
    PartCategory.electrical: ["wire", "cable", "connector", "terminal", "relay", "switch", "sensor", "harness", "fuse"],
    PartCategory.electronics: ["resistor", "capacitor", "inductor", "ic", "microcontroller", "pcb", "chip", "led", "diode", "transistor"],
    PartCategory.mechanical: ["bracket", "housing", "shaft", "gear", "spacer", "plate", "frame", "bushing", "bearing", "spring"],
    PartCategory.raw_material: ["aluminum", "steel", "copper", "brass", "titanium", "nylon", "abs", "polycarbonate", "stainless", "sheet", "bar", "rod", "tube", "plate stock"],
    PartCategory.sheet_metal: ["sheet metal", "laser cut", "bend", "formed", "stamped", "punched"],
    PartCategory.machined: ["machined", "cnc", "turned", "milled", "drilled", "lathe"],
    PartCategory.custom_mechanical: ["custom", "fabricated", "prototype", "bespoke"],
    PartCategory.pneumatic: ["pneumatic", "air valve", "air cylinder", "fitting"],
    PartCategory.hydraulic: ["hydraulic", "seal", "pump", "valve"],
    PartCategory.optical: ["lens", "optic", "camera", "fiber optic"],
    PartCategory.thermal: ["heater", "heat sink", "cooling", "fan", "radiator", "thermocouple"],
    PartCategory.cable_wiring: ["cable assembly", "harness", "loom", "wire assembly"],
    PartCategory.connector: ["connector", "header", "socket", "plug", "jack", "terminal block"],
    PartCategory.sensor: ["sensor", "accelerometer", "gyroscope", "thermocouple", "proximity", "photocell"],
    PartCategory.semiconductor: ["mosfet", "igbt", "triac", "thyristor", "transistor", "diode"],
    PartCategory.passive_component: ["resistor", "capacitor", "inductor", "ferrite", "varistor"],
    PartCategory.power_supply: ["power supply", "converter", "regulator", "transformer", "inverter"],
    PartCategory.enclosure: ["enclosure", "box", "case", "cabinet", "chassis"],
    PartCategory.adhesive_sealant: ["adhesive", "sealant", "epoxy", "silicone", "loctite", "glue"],
}

MATERIAL_FORM_KEYWORDS = {
    MaterialForm.sheet: ["sheet", "plate"],
    MaterialForm.bar: ["bar", "flat bar"],
    MaterialForm.rod: ["rod", "round bar"],
    MaterialForm.tube: ["tube", "pipe", "tubing"],
    MaterialForm.wire: ["wire"],
    MaterialForm.block: ["block", "billet"],
    MaterialForm.casting: ["casting", "cast"],
    MaterialForm.forging: ["forging", "forged"],
}

SUBCATEGORY_MAP = {
    "fastener": {
        "hex bolt": "hex_bolt",
        "socket cap": "socket_cap_screw",
        "set screw": "set_screw",
        "carriage bolt": "carriage_bolt",
        "hex nut": "hex_nut",
        "lock nut": "lock_nut",
        "wing nut": "wing_nut",
        "flat washer": "flat_washer",
        "lock washer": "lock_washer",
        "spring washer": "spring_washer",
        "rivet": "rivet",
        "screw": "screw",
        "bolt": "bolt",
        "nut": "nut",
        "washer": "washer",
        "stud": "stud",
        "anchor": "anchor",
    },
}

SUBASSEMBLY_KEYWORDS = ["assembly", "assy", "sub-assembly", "subassembly", "module", "unit"]

_MECHANICAL_SHAPE_KEYWORDS = {
    "bracket", "housing", "shaft", "gear", "spacer", "frame", "plate", "base", "block", "cover",
    "mount", "mounting", "bushing", "bearing", "spring", "pin", "hinge", "panel", "shim",
}
_FASTENER_KEYWORDS = {"bolt", "nut", "screw", "washer", "rivet", "stud", "threaded rod", "anchor"}
_FINISHED_PART_KEYWORDS = _FASTENER_KEYWORDS | _MECHANICAL_SHAPE_KEYWORDS | {
    "resistor", "capacitor", "inductor", "connector", "sensor", "relay", "switch", "fuse", "pcb",
    "printed circuit board", "semiconductor", "diode", "transistor", "motor", "bearing",
}
_SHEET_PROCESS_HINTS = {"laser cut", "bent", "bend", "formed", "stamped", "punched", "turret punched", "folded"}
_MACHINING_HINTS = {"cnc", "machined", "milled", "turned", "lathe", "drilled", "reamed", "ground", "machining"}
_CUSTOM_HINTS = {"custom", "fabricated", "prototype", "bespoke", "fabrication", "made to print", "drawing", "dwg"}
_ELECTRICAL_VALUE_UNITS = {"v", "a", "w", "hz", "ohm", "f", "h"}
_STANDARD_HINTS = {"din", "iso", "astm", "ansi", "bs", "jis", "standard", "std"}

_OCR_REGEX_HINTS: dict[str, tuple[re.Pattern[str], ...]] = {
    PartCategory.electronics.value: (
        re.compile(r"\bres[il1]stor\b", re.I),
        re.compile(r"\bcapac[il1]tor\b", re.I),
        re.compile(r"\bd[il1]ode\b", re.I),
    ),
    PartCategory.fastener.value: (
        re.compile(r"\bb[o0]lt\b", re.I),
        re.compile(r"\bn[uuv]t\b", re.I),
        re.compile(r"\bwash[e3]r\b", re.I),
    ),
}


@dataclass
class _CategoryEvidence:
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)
    negatives: list[str] = field(default_factory=list)

    def add(self, amount: float, reason: str) -> None:
        self.score += amount
        self.reasons.append(reason)

    def penalize(self, amount: float, reason: str) -> None:
        self.score -= amount
        self.negatives.append(reason)


_DEFENSIVE_CATEGORY_FALLBACK = PartCategory.unknown.value


def _safe_normalize_category_name(name: str) -> str:
    return name.strip().lower().replace(" ", "_")


def _iter_keywords(values: Iterable[str]) -> Iterable[str]:
    for value in values:
        cleaned = value.strip().lower()
        if cleaned:
            yield cleaned


def _has_keyword(text: str, keyword: str) -> bool:
    if " " in keyword or "-" in keyword:
        return keyword in text
    return re.search(rf"\b{re.escape(keyword)}\b", text) is not None


def _keyword_hits(text: str, keywords: Iterable[str]) -> list[str]:
    return [kw for kw in _iter_keywords(keywords) if _has_keyword(text, kw)]


def _extract_token_values(tokens: list) -> dict[str, list[str]]:
    values: dict[str, list[str]] = {}
    for token in tokens:
        values.setdefault(token.token_type, []).append((token.normalized_value or token.value or "").lower())
    return values


def _score_reference_keywords(text: str, evidence: dict[str, _CategoryEvidence]) -> None:
    refs = get_normalization_references()
    for raw_category, keywords in refs.category_keywords.items():
        category = _safe_normalize_category_name(raw_category)
        if category not in evidence:
            continue
        hits = _keyword_hits(text, keywords)
        for kw in hits:
            evidence[category].add(1.4, f"ref_kw:{kw}")

    for raw_category, hints in refs.process_hints.items():
        category = _safe_normalize_category_name(raw_category)
        if category not in evidence:
            category = _safe_normalize_category_name(raw_category.replace(" ", "_"))
        if category not in evidence:
            continue
        hits = _keyword_hits(text, hints)
        for kw in hits:
            evidence[category].add(1.8, f"process_hint:{kw}")


def _score_category_keywords(text: str, evidence: dict[str, _CategoryEvidence]) -> None:
    for category_enum, keywords in CATEGORY_KEYWORDS.items():
        category = category_enum.value
        hits = _keyword_hits(text, keywords)
        for kw in hits:
            evidence[category].add(1.3, f"kw:{kw}")

    for category, regexes in _OCR_REGEX_HINTS.items():
        for pattern in regexes:
            if pattern.search(text):
                evidence[category].add(0.9, f"ocr_hint:{pattern.pattern}")


def _score_token_signals(text: str, tokens: list, evidence: dict[str, _CategoryEvidence]) -> None:
    token_map = _extract_token_values(tokens)

    if token_map.get("thread_spec"):
        evidence[PartCategory.fastener.value].add(2.8, "token:thread_spec")
    if token_map.get("grade_reference"):
        evidence[PartCategory.fastener.value].add(1.2, "token:grade_reference")
    if token_map.get("package_type"):
        evidence[PartCategory.electronics.value].add(2.6, "token:package_type")
        evidence[PartCategory.passive_component.value].add(2.2, "token:package_type")
    if token_map.get("part_number_fragment"):
        if _keyword_hits(text, CATEGORY_KEYWORDS[PartCategory.electronics]):
            evidence[PartCategory.electronics.value].add(1.6, "token:part_number_fragment")
        if _keyword_hits(text, CATEGORY_KEYWORDS[PartCategory.electrical]):
            evidence[PartCategory.electrical.value].add(1.0, "token:part_number_fragment")
    if token_map.get("tolerance"):
        evidence[PartCategory.custom_mechanical.value].add(1.8, "token:tolerance")
        evidence[PartCategory.machined.value].add(1.6, "token:tolerance")
    if token_map.get("dimension"):
        evidence[PartCategory.mechanical.value].add(0.8, "token:dimension")
        if _keyword_hits(text, _SHEET_PROCESS_HINTS):
            evidence[PartCategory.sheet_metal.value].add(1.5, "dimension+sheet_process")
        elif _keyword_hits(text, _MACHINING_HINTS):
            evidence[PartCategory.machined.value].add(1.5, "dimension+machining_hint")
        elif _keyword_hits(text, _MECHANICAL_SHAPE_KEYWORDS):
            evidence[PartCategory.custom_mechanical.value].add(1.0, "dimension+mechanical_shape")
    if token_map.get("material_reference"):
        evidence[PartCategory.raw_material.value].add(1.4, "token:material_reference")

    electrical_values = 0
    for value in token_map.get("value_unit_pair", []):
        if any(unit in value for unit in _ELECTRICAL_VALUE_UNITS):
            electrical_values += 1
    if electrical_values:
        evidence[PartCategory.electronics.value].add(1.0 + electrical_values * 0.35, "token:value_unit_pair")
        evidence[PartCategory.electrical.value].add(0.7 + electrical_values * 0.25, "token:value_unit_pair")


def _score_attribute_rules(text: str, evidence: dict[str, _CategoryEvidence]) -> None:
    material_hits = _keyword_hits(text, get_normalization_references().materials)
    form_hits = [form for form, keywords in MATERIAL_FORM_KEYWORDS.items() if _keyword_hits(text, keywords)]
    process_hits = _keyword_hits(text, _SHEET_PROCESS_HINTS | _MACHINING_HINTS | _CUSTOM_HINTS)
    finished_hits = _keyword_hits(text, _FINISHED_PART_KEYWORDS)

    if material_hits and form_hits and not finished_hits:
        evidence[PartCategory.raw_material.value].add(2.6, "material+form")

    if material_hits and _keyword_hits(text, _SHEET_PROCESS_HINTS):
        evidence[PartCategory.sheet_metal.value].add(2.5, "material+sheet_process")

    if _keyword_hits(text, _MACHINING_HINTS):
        evidence[PartCategory.machined.value].add(2.4, "machining_hint")

    if _keyword_hits(text, _CUSTOM_HINTS):
        evidence[PartCategory.custom_mechanical.value].add(2.0, "custom_hint")

    if _keyword_hits(text, _STANDARD_HINTS) and not process_hits:
        evidence[PartCategory.standard.value].add(1.1, "standard_hint")

    if _keyword_hits(text, {"connector", "header", "socket", "plug", "jack", "terminal block"}):
        evidence[PartCategory.connector.value].add(2.2, "connector_family")
        evidence[PartCategory.electrical.value].add(0.8, "connector_family")

    if _keyword_hits(text, {"sensor", "proximity", "thermocouple", "encoder"}):
        evidence[PartCategory.sensor.value].add(2.0, "sensor_family")
        evidence[PartCategory.electrical.value].add(0.7, "sensor_family")


def _apply_negative_rules(text: str, evidence: dict[str, _CategoryEvidence]) -> None:
    finished_hits = _keyword_hits(text, _FINISHED_PART_KEYWORDS)
    material_hits = _keyword_hits(text, get_normalization_references().materials)
    form_hits = any(_keyword_hits(text, keywords) for keywords in MATERIAL_FORM_KEYWORDS.values())

    if finished_hits:
        evidence[PartCategory.raw_material.value].penalize(2.0, "finished_part_present")

    if material_hits and form_hits and _keyword_hits(text, _FASTENER_KEYWORDS):
        evidence[PartCategory.raw_material.value].penalize(1.6, "fastener_over_raw_material")
        evidence[PartCategory.fastener.value].add(0.8, "materialized_fastener")

    if _keyword_hits(text, {"wire", "cable", "harness"}) and _keyword_hits(text, {"resistor", "capacitor", "pcb", "ic"}):
        evidence[PartCategory.electrical.value].penalize(0.8, "mixed_electrical_electronics")
        evidence[PartCategory.electronics.value].penalize(0.5, "mixed_electrical_electronics")

    if _keyword_hits(text, _SHEET_PROCESS_HINTS):
        evidence[PartCategory.raw_material.value].penalize(1.1, "processed_sheet_not_raw")
        evidence[PartCategory.mechanical.value].penalize(0.5, "sheet_process_present")

    if _keyword_hits(text, _MACHINING_HINTS):
        evidence[PartCategory.standard.value].penalize(0.6, "machining_implies_nonstandard")
        evidence[PartCategory.raw_material.value].penalize(0.6, "machining_implies_nonraw")

    if _keyword_hits(text, {"drawing", "dwg", "print"}):
        evidence[PartCategory.standard.value].penalize(0.7, "drawing_implies_custom")


def _apply_precedence_rules(text: str, evidence: dict[str, _CategoryEvidence]) -> None:
    if evidence[PartCategory.fastener.value].score >= 3.0:
        evidence[PartCategory.raw_material.value].penalize(0.8, "fastener_precedence")
        evidence[PartCategory.standard.value].penalize(0.4, "fastener_precedence")

    if evidence[PartCategory.connector.value].score >= 2.2:
        evidence[PartCategory.electrical.value].penalize(0.4, "connector_precedence")

    if evidence[PartCategory.sensor.value].score >= 2.0:
        evidence[PartCategory.electrical.value].penalize(0.3, "sensor_precedence")

    if evidence[PartCategory.sheet_metal.value].score >= 3.0:
        evidence[PartCategory.custom_mechanical.value].add(0.4, "sheet_metal_implies_custom")
        evidence[PartCategory.raw_material.value].penalize(0.8, "sheet_metal_precedence")

    if evidence[PartCategory.machined.value].score >= 3.0 and _keyword_hits(text, _MECHANICAL_SHAPE_KEYWORDS):
        evidence[PartCategory.custom_mechanical.value].add(0.8, "machined_mechanical_shape")


def _sorted_candidates(evidence: dict[str, _CategoryEvidence]) -> list[tuple[str, _CategoryEvidence]]:
    return sorted(evidence.items(), key=lambda item: (item[1].score, len(item[1].reasons)), reverse=True)


def _compute_confidence(best_score: float, second_score: float, signal_count: int, has_strong_identifier: bool) -> float:
    if best_score <= 0:
        return 0.12

    margin = max(0.0, best_score - max(second_score, 0.0))
    base = 0.24 + min(best_score, 8.0) * 0.07
    base += min(signal_count, 6) * 0.04
    base += min(margin, 3.0) * 0.06
    if has_strong_identifier:
        base += 0.08
    if margin < 0.75:
        base -= 0.12
    if best_score < 2.0:
        base -= 0.10
    return round(max(0.08, min(base, 0.96)), 4)


def _select_category(evidence: dict[str, _CategoryEvidence]) -> tuple[str, float, list[tuple[str, _CategoryEvidence]]]:
    ranked = _sorted_candidates(evidence)
    best_cat, best_ev = ranked[0]
    second_score = ranked[1][1].score if len(ranked) > 1 else 0.0
    signal_count = len(best_ev.reasons)
    has_strong_identifier = any(
        reason.startswith(("token:thread_spec", "token:package_type", "material+form", "material+sheet_process", "machining_hint", "custom_hint"))
        for reason in best_ev.reasons
    )
    confidence = _compute_confidence(best_ev.score, second_score, signal_count, has_strong_identifier)

    margin = best_ev.score - second_score
    active_competitors = sum(1 for _, ev in ranked[:4] if ev.score >= 1.2)

    if best_ev.score < 1.5:
        return _DEFENSIVE_CATEGORY_FALLBACK, min(confidence, 0.28), ranked

    if margin < 0.5 and best_ev.score < 3.6:
        return _DEFENSIVE_CATEGORY_FALLBACK, min(confidence, 0.42), ranked

    if active_competitors >= 3:
        return best_cat, min(confidence, 0.55), ranked

    if margin < 0.4:
        return best_cat, min(confidence, 0.52), ranked

    if confidence < 0.25:
        return _DEFENSIVE_CATEGORY_FALLBACK, confidence, ranked

    return best_cat, confidence, ranked


def _derive_subcategory(category: str, text_lower: str) -> str | None:
    subcat_map = SUBCATEGORY_MAP.get(category, {})
    for pattern, subcat_value in subcat_map.items():
        if pattern in text_lower:
            return subcat_value
    return None


def _build_reason(category: str, evidence: dict[str, _CategoryEvidence], ranked: list[tuple[str, _CategoryEvidence]]) -> str:
    if category == _DEFENSIVE_CATEGORY_FALLBACK:
        top = ", ".join(f"{name}:{round(ev.score, 2)}" for name, ev in ranked[:3] if ev.score > 0)
        return f"ambiguous or weak deterministic signals; candidates={top or 'none'}"

    selected = evidence[category]
    primary = ", ".join(selected.reasons[:6]) if selected.reasons else "no_positive_signals"
    negatives = f"; negatives={', '.join(selected.negatives[:3])}" if selected.negatives else ""
    others = ", ".join(f"{name}:{round(ev.score, 2)}" for name, ev in ranked[1:3] if ev.score > 0)
    competitors = f"; competitors={others}" if others else ""
    return f"matched: {primary}{negatives}{competitors}"


def classify_from_tokens(tokens: list, expanded_text: str) -> tuple[str, str | None, float, str]:
    """Deterministic token-aware classification for the decomposed pipeline.

    Returns: (category, subcategory, confidence, reason)
    """
    text_lower = (expanded_text or "").lower().strip()
    if not text_lower:
        return PartCategory.unknown.value, None, 0.08, "empty normalized_text"

    evidence = {category.value: _CategoryEvidence() for category in PartCategory}

    _score_reference_keywords(text_lower, evidence)
    _score_category_keywords(text_lower, evidence)
    _score_token_signals(text_lower, tokens, evidence)
    _score_attribute_rules(text_lower, evidence)
    _apply_negative_rules(text_lower, evidence)
    _apply_precedence_rules(text_lower, evidence)

    if any(_has_keyword(text_lower, kw) for kw in SUBASSEMBLY_KEYWORDS):
        evidence[PartCategory.standard.value].add(0.7, "subassembly_indicator")

    category, confidence, ranked = _select_category(evidence)
    subcategory = _derive_subcategory(category, text_lower)
    reason = _build_reason(category, evidence, ranked)
    return category, subcategory, confidence, reason


@dataclass
class ClassifiedItem:
    item_id: str = ""
    raw_text: str = ""
    standard_text: str = ""
    description: str = ""
    quantity: float = 1.0
    part_number: str = ""
    mpn: str = ""
    manufacturer: str = ""
    supplier_name: str = ""
    material: str = ""
    notes: str = ""
    unit: str = "each"
    category: PartCategory = PartCategory.unknown
    classification_path: str = ""
    confidence: float = 0.0
    classification_reason: str = ""
    has_mpn: bool = False
    has_brand: bool = False
    is_generic: bool = False
    is_raw: bool = False
    is_custom: bool = False
    material_form: MaterialForm | None = None
    geometry: str | None = None
    tolerance: str | None = None
    secondary_ops: list = field(default_factory=list)
    procurement_class: ProcurementClass = ProcurementClass.unknown
    rfq_required: bool = False
    drawing_required: bool = False
    source_row: int = 0


@dataclass
class _LegacyToken:
    token_type: str
    value: str
    normalized_value: str | None = None


_LEGACY_TOKEN_PATTERNS: dict[str, re.Pattern[str]] = {
    "thread_spec": re.compile(r"\bm\d+(?:\.\d+)?(?:\s*[xX]\s*\d+(?:\.\d+)?)?\b", re.I),
    "grade_reference": re.compile(r"\b(?:grade|class)\s*[:=]?\s*\d+(?:\.\d+)?\b", re.I),
    "package_type": re.compile(r"\b(0201|0402|0603|0805|1206|1210|2512|sot-\d+|qfp-\d+|bga-\d+|dip-\d+|sop-\d+|tssop-\d+|qfn-\d+)\b", re.I),
    "part_number_fragment": re.compile(r"\b[a-z]{2,5}[-]?\d{3,}[a-z0-9\-]*\b", re.I),
    "value_unit_pair": re.compile(r"\b\d+(?:\.\d+)?\s*(?:k|m|g|u|p|n)?\s*(?:ohm|v|a|w|hz|f|h|mm|cm|in|m|kg|g)\b", re.I),
    "dimension": re.compile(r"\b\d+(?:\.\d+)?\s*[xX]\s*\d+(?:\.\d+)?(?:\s*[xX]\s*\d+(?:\.\d+)?)?(?:\s*(?:mm|cm|in))?\b", re.I),
    "tolerance": re.compile(r"[±+\-]\s*\d+(?:\.\d+)?\s*(?:mm|in|thou|um|%)?", re.I),
    "material_reference": re.compile(r"\b(stainless\s*steel(?:\s*304|\s*316)?|aluminum|copper|brass|titanium|nylon|abs|polycarbonate|peek|carbon\s*fiber|steel|inconel|hdpe|ptfe)\b", re.I),
}


def _legacy_tokens(text: str) -> list[_LegacyToken]:
    tokens: list[_LegacyToken] = []
    for token_type, pattern in _LEGACY_TOKEN_PATTERNS.items():
        for match in pattern.finditer(text):
            tokens.append(_LegacyToken(token_type=token_type, value=match.group(0), normalized_value=match.group(0).lower()))
    return tokens


def classify_item(raw_row) -> ClassifiedItem:
    """Legacy deterministic classifier retained for backward compatibility."""
    text_blob_raw = f"{raw_row.description} {raw_row.material} {raw_row.notes} {raw_row.part_number} {raw_row.mpn}".strip()
    normalized_text, _ = normalize_text(text_blob_raw)
    category_str, _, confidence, classification_reason = classify_from_tokens(_legacy_tokens(normalized_text), normalized_text)

    try:
        category = PartCategory(category_str)
    except ValueError:
        category = PartCategory.unknown

    ci = ClassifiedItem(
        item_id=f"ITEM-{raw_row.row_index:04d}",
        raw_text=raw_row.description,
        standard_text=normalized_text or raw_row.description.strip(),
        description=raw_row.description.strip(),
        quantity=raw_row.quantity,
        part_number=raw_row.part_number,
        mpn=raw_row.mpn or raw_row.part_number,
        manufacturer=raw_row.manufacturer,
        supplier_name=raw_row.supplier,
        material=raw_row.material,
        notes=raw_row.notes,
        unit=raw_row.unit or "each",
        source_row=raw_row.row_index,
        category=category,
        confidence=confidence,
        classification_reason=classification_reason,
    )

    ci.has_mpn = bool(ci.mpn and len(ci.mpn.strip()) >= 4)
    ci.has_brand = bool(ci.manufacturer and len(ci.manufacturer.strip()) >= 2)

    for form, keywords in MATERIAL_FORM_KEYWORDS.items():
        if any(_has_keyword(normalized_text, kw) for kw in keywords):
            ci.material_form = form
            break

    ci.is_raw = ci.category == PartCategory.raw_material
    ci.is_custom = ci.category in (PartCategory.custom_mechanical, PartCategory.sheet_metal, PartCategory.machined)
    ci.is_generic = not ci.has_mpn and not ci.is_custom and ci.category not in (PartCategory.unknown,)

    if any(_has_keyword(normalized_text, kw) for kw in SUBASSEMBLY_KEYWORDS):
        ci.procurement_class = ProcurementClass.subassembly
    elif ci.is_raw:
        ci.procurement_class = ProcurementClass.raw_material_order
    elif ci.is_custom:
        ci.procurement_class = ProcurementClass.custom_fabrication
    elif ci.category == PartCategory.unknown:
        ci.procurement_class = ProcurementClass.unknown
    else:
        ci.procurement_class = ProcurementClass.catalog_purchase

    ci.rfq_required = ci.is_custom or ci.procurement_class == ProcurementClass.custom_fabrication
    ci.drawing_required = ci.is_custom or any(_has_keyword(normalized_text, kw) for kw in {"drawing", "dwg", "print"})

    tol_match = re.search(r"[±+\-]\s*[\d.]+\s*(mm|in|thou|µm|um|%)", normalized_text)
    if tol_match:
        ci.tolerance = tol_match.group(0).strip()

    ops_keywords = {
        "anodize": "anodizing",
        "anodizing": "anodizing",
        "plat": "plating",
        "paint": "painting",
        "powder coat": "powder_coating",
        "heat treat": "heat_treatment",
        "chrome": "chrome_plating",
        "polish": "polishing",
        "deburr": "deburring",
    }
    for kw, op in ops_keywords.items():
        if kw in normalized_text:
            ci.secondary_ops.append(op)

    ci.classification_path = f"{ci.category.value}/{ci.procurement_class.value}"
    return ci


def classify_bom(raw_rows: list) -> list[ClassifiedItem]:
    """Legacy batch classifier."""
    return [classify_item(row) for row in raw_rows]
