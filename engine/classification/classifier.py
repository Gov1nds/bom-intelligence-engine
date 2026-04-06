"""Component classification — category detection, procurement class, manufacturing flags."""
import re
import logging
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

    # MPN detection
    ci.has_mpn = bool(ci.mpn and len(ci.mpn.strip()) >= 4)
    ci.has_brand = bool(ci.manufacturer and len(ci.manufacturer.strip()) >= 2)

    # Category classification
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

    # Material form
    for form, keywords in MATERIAL_FORM_KEYWORDS.items():
        if any(kw in text_blob for kw in keywords):
            ci.material_form = form
            break

    # Flags
    ci.is_raw = ci.category == PartCategory.raw_material
    ci.is_custom = ci.category in (PartCategory.custom_mechanical, PartCategory.sheet_metal, PartCategory.machined)
    ci.is_generic = not ci.has_mpn and not ci.is_custom

    # Procurement class
    if ci.has_mpn or ci.is_generic:
        ci.procurement_class = ProcurementClass.catalog_purchase
    elif ci.is_raw:
        ci.procurement_class = ProcurementClass.raw_material_order
    elif ci.is_custom:
        ci.procurement_class = ProcurementClass.custom_fabrication
    else:
        ci.procurement_class = ProcurementClass.catalog_purchase

    # RFQ / drawing flags
    ci.rfq_required = ci.is_custom or ci.procurement_class == ProcurementClass.custom_fabrication
    ci.drawing_required = ci.is_custom

    # Tolerance detection
    tol_match = re.search(r"[±+\-]\s*[\d.]+\s*(mm|in|thou|µm)", text_blob)
    if tol_match:
        ci.tolerance = tol_match.group(0).strip()

    # Secondary ops
    ops_keywords = {"anodize": "anodizing", "anodizing": "anodizing", "plat": "plating",
                    "paint": "painting", "powder coat": "powder_coating", "heat treat": "heat_treatment",
                    "chrome": "chrome_plating", "polish": "polishing", "deburr": "deburring"}
    for kw, op in ops_keywords.items():
        if kw in text_blob:
            ci.secondary_ops.append(op)

    ci.classification_path = f"{ci.category.value}/{ci.procurement_class.value}"
    return ci


def classify_bom(raw_rows: list) -> list[ClassifiedItem]:
    return [classify_item(row) for row in raw_rows]
