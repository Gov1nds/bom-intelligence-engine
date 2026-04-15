"""Component classification — category detection, procurement class, manufacturing flags.

classify_item / classify_bom: legacy keyword-based (retained for /api/analyze-bom).
classify_from_tokens: new token-aware classification for decomposed pipeline.
"""
import re
import logging
import warnings
from dataclasses import dataclass, field

from core.schemas import PartCategory, ProcurementClass, MaterialForm

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

# Subcategory detection
SUBCATEGORY_MAP = {
    "fastener": {
        "hex bolt": "hex_bolt", "socket cap": "socket_cap_screw",
        "set screw": "set_screw", "carriage bolt": "carriage_bolt",
        "hex nut": "hex_nut", "lock nut": "lock_nut", "wing nut": "wing_nut",
        "flat washer": "flat_washer", "lock washer": "lock_washer",
        "spring washer": "spring_washer", "rivet": "rivet",
        "screw": "screw", "bolt": "bolt", "nut": "nut", "washer": "washer",
        "stud": "stud", "anchor": "anchor",
    },
}

# Token-aware category indicators
TOKEN_CATEGORY_INDICATORS = {
    PartCategory.fastener.value: {
        "token_types": ["thread_spec", "grade_reference"],
        "keywords": ["bolt", "nut", "screw", "washer", "rivet", "stud", "anchor"],
    },
    PartCategory.electronics.value: {
        "token_types": ["package_type"],
        "keywords": ["resistor", "capacitor", "inductor", "ic", "microcontroller", "pcb", "chip", "led", "diode"],
    },
    PartCategory.passive_component.value: {
        "token_types": ["package_type"],
        "keywords": ["resistor", "capacitor", "inductor", "ferrite", "varistor"],
    },
    PartCategory.mechanical.value: {
        "token_types": ["dimension"],
        "keywords": ["bracket", "housing", "shaft", "gear", "spacer", "frame", "bushing", "bearing", "spring"],
    },
    PartCategory.machined.value: {
        "token_types": ["dimension", "tolerance"],
        "keywords": ["machined", "cnc", "turned", "milled", "drilled"],
    },
    PartCategory.custom_mechanical.value: {
        "token_types": ["dimension", "tolerance"],
        "keywords": ["custom", "fabricated", "prototype", "bespoke"],
    },
    PartCategory.raw_material.value: {
        "token_types": ["material_reference", "dimension"],
        "keywords": ["aluminum", "steel", "copper", "brass", "titanium", "sheet", "bar", "rod", "tube"],
    },
    PartCategory.sheet_metal.value: {
        "token_types": ["dimension"],
        "keywords": ["sheet metal", "laser cut", "bend", "formed", "stamped"],
    },
    PartCategory.connector.value: {
        "token_types": [],
        "keywords": ["connector", "header", "socket", "plug", "jack", "terminal block"],
    },
    PartCategory.sensor.value: {
        "token_types": [],
        "keywords": ["sensor", "accelerometer", "gyroscope", "proximity"],
    },
    PartCategory.power_supply.value: {
        "token_types": [],
        "keywords": ["power supply", "converter", "regulator", "transformer"],
    },
    PartCategory.enclosure.value: {
        "token_types": ["dimension"],
        "keywords": ["enclosure", "box", "case", "cabinet", "chassis"],
    },
    PartCategory.adhesive_sealant.value: {
        "token_types": [],
        "keywords": ["adhesive", "sealant", "epoxy", "silicone", "glue"],
    },
    PartCategory.thermal.value: {
        "token_types": [],
        "keywords": ["heater", "heat sink", "cooling", "fan", "radiator"],
    },
    PartCategory.pneumatic.value: {
        "token_types": [],
        "keywords": ["pneumatic", "air valve", "air cylinder"],
    },
    PartCategory.hydraulic.value: {
        "token_types": [],
        "keywords": ["hydraulic", "pump", "valve"],
    },
    PartCategory.optical.value: {
        "token_types": [],
        "keywords": ["lens", "optic", "camera", "fiber optic"],
    },
    PartCategory.cable_wiring.value: {
        "token_types": [],
        "keywords": ["cable assembly", "harness", "loom", "wire assembly"],
    },
    PartCategory.electrical.value: {
        "token_types": [],
        "keywords": ["wire", "cable", "terminal", "relay", "switch", "fuse"],
    },
    PartCategory.semiconductor.value: {
        "token_types": ["part_number_fragment"],
        "keywords": ["mosfet", "igbt", "triac", "thyristor"],
    },
}

SUBASSEMBLY_KEYWORDS = ["assembly", "assy", "sub-assembly", "subassembly", "module", "unit"]


def classify_from_tokens(
    tokens: list, expanded_text: str
) -> tuple[str, str | None, float, str]:
    """Token-aware classification for the decomposed pipeline.

    Returns: (category, subcategory, confidence, reason)
    """
    text_lower = expanded_text.lower()
    category_scores: dict[str, float] = {}
    match_reasons: dict[str, list[str]] = {}

    for cat, indicators in TOKEN_CATEGORY_INDICATORS.items():
        score = 0.0
        reasons: list[str] = []
        for token in tokens:
            if token.token_type in indicators.get("token_types", []):
                score += 2.0
                reasons.append(f"token:{token.token_type}")
        for kw in indicators.get("keywords", []):
            if kw in text_lower:
                score += 1.5
                reasons.append(f"kw:{kw}")
        if score > 0:
            category_scores[cat] = score
            match_reasons[cat] = reasons

    # Check subassembly
    if any(kw in text_lower for kw in SUBASSEMBLY_KEYWORDS):
        category_scores["subassembly_flag"] = 3.0

    if not category_scores:
        return "standard", None, 0.3, "no matching indicators"

    best_cat = max(
        (k for k in category_scores if k != "subassembly_flag"),
        key=lambda k: category_scores[k],
        default="standard",
    )
    best_score = category_scores.get(best_cat, 0)
    reason = f"matched: {', '.join(match_reasons.get(best_cat, []))}"

    # Confidence: scale from scores
    confidence = min(0.95, 0.35 + best_score * 0.10)

    # Subcategory detection
    subcategory = None
    subcat_map = SUBCATEGORY_MAP.get(best_cat, {})
    for pattern, subcat_value in subcat_map.items():
        if pattern in text_lower:
            subcategory = subcat_value
            break

    return best_cat, subcategory, round(confidence, 4), reason


# ── Legacy functions (retained for /api/analyze-bom backward compat) ──


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


def classify_item(raw_row) -> ClassifiedItem:
    """Legacy keyword-based classifier. Retained for backward compat."""
    text_blob = f"{raw_row.description} {raw_row.material} {raw_row.notes} {raw_row.part_number}".lower()

    ci = ClassifiedItem(
        item_id=f"ITEM-{raw_row.row_index:04d}",
        raw_text=raw_row.description,
        standard_text=raw_row.description.strip(),
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
    )

    ci.has_mpn = bool(ci.mpn and len(ci.mpn.strip()) >= 4)
    ci.has_brand = bool(ci.manufacturer and len(ci.manufacturer.strip()) >= 2)

    best_cat = PartCategory.standard
    best_score = 0
    best_reason = "default classification"

    for cat, keywords in CATEGORY_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in text_blob)
        if score > best_score:
            best_score = score
            best_cat = cat
            best_reason = f"matched keywords: {', '.join(kw for kw in keywords if kw in text_blob)}"

    ci.category = best_cat
    ci.classification_reason = best_reason
    ci.confidence = min(0.95, 0.4 + best_score * 0.15)

    for form, keywords in MATERIAL_FORM_KEYWORDS.items():
        if any(kw in text_blob for kw in keywords):
            ci.material_form = form
            break

    ci.is_raw = ci.category == PartCategory.raw_material
    ci.is_custom = ci.category in (PartCategory.custom_mechanical, PartCategory.sheet_metal, PartCategory.machined)
    ci.is_generic = not ci.has_mpn and not ci.is_custom

    # Subassembly detection (fix for never-assigned ProcurementClass.subassembly)
    if any(kw in text_blob for kw in SUBASSEMBLY_KEYWORDS):
        ci.procurement_class = ProcurementClass.subassembly
    elif ci.has_mpn or ci.is_generic:
        ci.procurement_class = ProcurementClass.catalog_purchase
    elif ci.is_raw:
        ci.procurement_class = ProcurementClass.raw_material_order
    elif ci.is_custom:
        ci.procurement_class = ProcurementClass.custom_fabrication
    else:
        ci.procurement_class = ProcurementClass.catalog_purchase

    ci.rfq_required = ci.is_custom or ci.procurement_class == ProcurementClass.custom_fabrication
    ci.drawing_required = ci.is_custom

    tol_match = re.search(r"[±+\-]\s*[\d.]+\s*(mm|in|thou|µm)", text_blob)
    if tol_match:
        ci.tolerance = tol_match.group(0).strip()

    ops_keywords = {
        "anodize": "anodizing", "anodizing": "anodizing", "plat": "plating",
        "paint": "painting", "powder coat": "powder_coating", "heat treat": "heat_treatment",
        "chrome": "chrome_plating", "polish": "polishing", "deburr": "deburring",
    }
    for kw, op in ops_keywords.items():
        if kw in text_blob:
            ci.secondary_ops.append(op)

    ci.classification_path = f"{ci.category.value}/{ci.procurement_class.value}"
    return ci


def classify_bom(raw_rows: list) -> list[ClassifiedItem]:
    """Legacy batch classifier."""
    return [classify_item(row) for row in raw_rows]
