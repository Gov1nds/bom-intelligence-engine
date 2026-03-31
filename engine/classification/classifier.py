"""
PHASE 2 — Strict Classification Engine (FIXED).

Priority order (CHANGED — custom checked BEFORE brand/MPN):
  1. Custom fabrication signals → CUSTOM_MECHANICAL or SHEET_METAL (3_3)
  2. Sheet metal signals → SHEET_METAL (3_3)
  3. Raw material signals → RAW_MATERIAL (3_2)
  4. Has valid MPN AND recognized brand → ELECTRICAL or ELECTRONICS (3_1)
  5. Has valid MPN only (format-validated) → STANDARD or ELECTRONICS (3_1)
  6. Fastener keywords → FASTENER (3_1)
  7. Electrical keywords → ELECTRICAL (3_1)
  8. Electronics keywords → ELECTRONICS (3_1)
  9. Generic standard keywords → STANDARD (3_1)
  10. Material field present → CUSTOM_MECHANICAL (3_3)
  11. Fallback → UNKNOWN (NOT standard)
"""
import re
from typing import List, Optional, Set
from core.schemas import (
    NormalizedBOMItem, ClassifiedItem, PartCategory, ProcurementClass,
    ClassificationPath, MaterialForm, GeometryComplexity, ToleranceClass,
)

# ---- Knowledge bases ----
KNOWN_BRANDS: Set[str] = {
    "texas instruments","ti","stmicroelectronics","stm","microchip","analog devices",
    "infineon","nxp","renesas","murata","tdk","vishay","yageo","samsung","panasonic",
    "kemet","avx","wurth","bourns","molex","te connectivity","amphenol","hirose","jst",
    "misumi","mcmaster","bosch","siemens","abb","schneider","skf","omron","phoenix contact",
}

# MPN patterns — must match to count as a real MPN
MPN_PATTERNS = [
    re.compile(r"^[A-Z]{2,4}\d{3,}", re.I),
    re.compile(r"^\d{3,}-\d{3,}"),
    re.compile(r"^[A-Z]+\d+[A-Z]+\d+", re.I),
    re.compile(r"^ERJ-\d+", re.I),
    re.compile(r"^GRM\d+", re.I),
    re.compile(r"^[A-Z]{1,3}\d{4,}", re.I),          # e.g. LM7805, NE555
    re.compile(r"^\d{4,}[A-Z]{1,3}\d*", re.I),        # e.g. 2N2222A
]

# ---- Keyword sets (expanded) ----

ELECTRICAL_KW = {
    "resistor","capacitor","inductor","ferrite","thermistor","varistor",
    "potentiometer","fuse",
}

ELECTRONICS_KW = {
    "integrated_circuit","microcontroller","transistor","mosfet","diode","led",
    "regulator","sensor","connector","header","terminal","socket","plug","usb","pcb",
    "relay","crystal","oscillator","transformer","switch","optocoupler","amplifier",
    "comparator","adc","dac","fpga","memory","eeprom","flash",
}

FASTENER_KW = {
    "hex_bolt","screw","nut","washer","rivet","spring","bearing","bushing",
    "o-ring","gasket","seal","gear","sprocket","pulley","pin","circlip",
    "cotter","dowel","stud","anchor","insert","standoff","spacer",
}

CUSTOM_KW = {
    "fabricated","custom","bespoke",
    "as_per_drawing","per_drawing","welded","assembled","fabrication",
    "bracket","housing","enclosure","fixture","jig","tooling","mold",
    "manifold","chassis","frame","weldment",
}

MACHINED_KW = {
    "machined","cnc","milled","turned","lathe","boring",
    "cnc_machined","cnc_milled","cnc_turned","precision_machined",
    "shaft","bushing_custom","coupling","flange_custom","spindle",
    "sleeve","adapter","spacer_custom","plug_custom","nozzle",
    "collet","mandrel","arbor",
}

MACHINED_PAT = [
    re.compile(r"\bmachined\s+\w+", re.I),
    re.compile(r"\bcnc\s+(machined|milled|turned|part)", re.I),
    re.compile(r"\bturned\s+\w+", re.I),
    re.compile(r"\bmilled\s+\w+", re.I),
    re.compile(r"\bprecision\s+\w+", re.I),
]

SHEET_METAL_KW = {
    "sheet_metal","laser_cut","laser_cutting","press_brake","stamped",
    "punched","formed","bent","panel","cover","plate_fabricated",
    "sheet_fabricated","bracket_sheet",
}

CUSTOM_PAT = [
    re.compile(r"\bcustom\s+\w+", re.I),
    re.compile(r"\bas\s*per\s*draw", re.I),
    re.compile(r"\bmachined\s+\w+", re.I),
    re.compile(r"\bcnc\s+\w+", re.I),
    re.compile(r"\bfabricat\w+", re.I),
]

SHEET_METAL_PAT = [
    re.compile(r"\bsheet\s*metal\b", re.I),
    re.compile(r"\blaser\s*cut\b", re.I),
    re.compile(r"\bpress\s*brake\b", re.I),
    re.compile(r"\bstamp(ed|ing)\b", re.I),
    re.compile(r"\bbend(ing)?\b", re.I),
]

RAW_KW = {
    "steel_plate","aluminum_sheet","copper_bar","brass_rod","steel_bar",
    "stainless_steel_sheet","carbon_steel","tool_steel","alloy_steel",
    "aluminum_billet","titanium","nickel_alloy","inconel",
    "hdpe","nylon","abs","polycarbonate","acetal","delrin","ptfe","peek",
    "pom","pvc","polypropylene","carbon_fiber","kevlar",
    "rubber_sheet","silicone","neoprene",
    "raw_material","stock_material","bar_stock","sheet_stock",
    "tube_stock","billet","ingot","blank",
}

RAW_PAT = [
    re.compile(r"\b(steel|aluminum|copper|brass|bronze)\s+(bar|rod|tube|pipe|sheet|plate|billet)\b", re.I),
    re.compile(r"\b(round|square|hex|flat)\s+(bar|stock)\b", re.I),
]
PNEUMATIC_KW = {
    "pneumatic", "air valve", "solenoid valve", "cylinder", "actuator",
    "air hose", "regulator", "compressor", "manifold", "fitting", "vacuum",
}

HYDRAULIC_KW = {
    "hydraulic", "hydraulic hose", "oil hose", "pump", "seal", "manifold",
    "valve", "cylinder", "pressure line", "fitting", "reservoir",
}

CABLE_WIRING_KW = {
    "cable", "wire", "wiring", "harness", "loom", "shielded", "awg",
    "twisted pair", "coax", "connector cable", "patch cord", "jumper",
}

OPTICAL_KW = {
    "optical", "fiber", "fibre", "fiber optic", "fibre optic", "lens",
    "photodiode", "laser diode", "transceiver", "optics", "waveguide",
}

THERMAL_KW = {
    "thermal", "heatsink", "heat sink", "heat-sink", "thermal pad",
    "thermal interface", "cooling", "fan", "blower", "radiator", "peltier",
}
STANDARD_KW = {
    "gear","sprocket","pulley",
}

# ---- Attribute detectors ----
def _material_form(t: str) -> Optional[MaterialForm]:
    if re.search(r"\b(sheet|plate|flat)\b", t, re.I): return MaterialForm.SHEET
    if re.search(r"\b(billet|block|blank)\b", t, re.I): return MaterialForm.BILLET
    if re.search(r"\b(bar|rod|round)\b", t, re.I): return MaterialForm.BAR
    if re.search(r"\b(tube|pipe)\b", t, re.I): return MaterialForm.TUBE
    if re.search(r"\b(composite|fiberglass|carbon_fiber)\b", t, re.I): return MaterialForm.COMPOSITE
    if re.search(r"\b(plastic|polymer|nylon|abs|peek|hdpe|pvc)\b", t, re.I): return MaterialForm.POLYMER
    return None

def _geometry(t: str) -> GeometryComplexity:
    if re.search(r"\b(5.axis|multi.axis|undercut)\b", t, re.I): return GeometryComplexity.MULTI_AXIS
    if re.search(r"\b(3d|contour|freeform)\b", t, re.I): return GeometryComplexity.FULL_3D
    if re.search(r"\b(pocket|step|slot)\b", t, re.I): return GeometryComplexity.PRISMATIC
    return GeometryComplexity.FLAT_2D

def _tolerance(t: str) -> ToleranceClass:
    m = re.search(r"[±]\s*(\d+\.?\d*)\s*(mm|um|µm)", t)
    if m:
        val = float(m.group(1))
        if m.group(2) in ("um","µm"): val /= 1000
        if val < 0.01: return ToleranceClass.ULTRA
        if val < 0.1: return ToleranceClass.PRECISION
        if val < 0.5: return ToleranceClass.STANDARD
        return ToleranceClass.LOOSE
    if re.search(r"\b(ultra|micro|optical)\b", t, re.I): return ToleranceClass.ULTRA
    if re.search(r"\b(precision|tight)\b", t, re.I): return ToleranceClass.PRECISION
    return ToleranceClass.STANDARD

def _secondary_ops(t: str) -> List[str]:
    ops = []
    if re.search(r"\b(thread|tapped|tap)\b", t, re.I): ops.append("threading")
    if re.search(r"\b(anodiz|plat(ed|ing)|coat(ed|ing)|paint|powder)\b", t, re.I): ops.append("coating")
    if re.search(r"\b(heat.treat|harden|temper)\b", t, re.I): ops.append("heat_treatment")
    if re.search(r"\b(grind|grinding|ground)\b", t, re.I): ops.append("grinding")
    return ops

def _has_kw(text: str, keywords: Set[str]) -> Optional[str]:
    tl = text.lower()
    for kw in keywords:
        if kw in tl or kw.replace("_", " ") in tl:
            return kw
    return None

def _has_pat(text: str, patterns: list) -> bool:
    return any(p.search(text) for p in patterns)

def _domain_category(text: str):
    for category, keywords in [
        (PartCategory.PNEUMATIC, PNEUMATIC_KW),
        (PartCategory.HYDRAULIC, HYDRAULIC_KW),
        (PartCategory.CABLE_WIRING, CABLE_WIRING_KW),
        (PartCategory.OPTICAL, OPTICAL_KW),
        (PartCategory.THERMAL, THERMAL_KW),
    ]:
        kw = _has_kw(text, keywords)
        if kw:
            return category, kw
    return None, None

def _is_valid_mpn(mpn: str) -> bool:
    """Validate MPN against known part number formats. Rejects drawing numbers and short codes."""
    if not mpn or len(mpn) < 3:
        return False
    clean = mpn.strip()
    # Reject purely numeric short strings (likely row numbers or quantities)
    if clean.isdigit() and len(clean) < 5:
        return False
    # Reject common drawing/internal prefixes
    drawing_prefixes = ("DWG", "DRG", "DRAW", "ASSY", "PART-", "ITEM-", "REF-")
    if any(clean.upper().startswith(p) for p in drawing_prefixes):
        return False
    return any(p.match(clean) for p in MPN_PATTERNS)

def _set_procurement_intent(c: ClassifiedItem) -> ClassifiedItem:
    """Set procurement_class, rfq_required, drawing_required based on category."""
    if c.category == PartCategory.MACHINED:
        c.procurement_class = ProcurementClass.MACHINED_PART
        c.rfq_required = True
        c.drawing_required = True
    elif c.category in (PartCategory.CUSTOM_MECHANICAL, PartCategory.SHEET_METAL):
        c.procurement_class = ProcurementClass.RFQ_REQUIRED
        c.rfq_required = True
        c.drawing_required = True
    elif c.category == PartCategory.RAW_MATERIAL:
        c.procurement_class = ProcurementClass.RAW_STOCK
        c.rfq_required = False
        c.drawing_required = False
    elif c.category == PartCategory.UNKNOWN:
        c.procurement_class = ProcurementClass.ENGINEERING_REVIEW
        c.rfq_required = False
        c.drawing_required = False
    else:
        # STANDARD, ELECTRICAL, ELECTRONICS, FASTENER
        c.procurement_class = ProcurementClass.CATALOG_PURCHASE
        c.rfq_required = False
        c.drawing_required = False
    return c


# ---- Main classifier ----
def classify_item(item: NormalizedBOMItem) -> ClassifiedItem:
    text = item.standard_text.lower()
    combined = f"{text} {item.mpn} {item.manufacturer} {item.material} {item.notes}".lower()
    c = ClassifiedItem(**{k: getattr(item, k) for k in item.__dataclass_fields__})

    # ---- Rule 1a: Machined parts → MACHINED (checked FIRST) ----
    kw = _has_kw(combined, MACHINED_KW)
    if kw or _has_pat(combined, MACHINED_PAT):
        c.category = PartCategory.MACHINED
        c.classification_path = ClassificationPath.PATH_3_3
        c.is_custom = True
        c.confidence = 0.85 if kw else 0.75
        c.classification_reason = f"Machined: '{kw}'" if kw else "Machined pattern"
        c.material_form = _material_form(combined)
        c.geometry = _geometry(combined)
        c.tolerance = _tolerance(combined)
        c.secondary_ops = _secondary_ops(combined)
        return _set_procurement_intent(c)

    # ---- Rule 1b: Custom fabrication → CUSTOM_MECHANICAL ----
    kw = _has_kw(combined, CUSTOM_KW)
    if kw or _has_pat(combined, CUSTOM_PAT):
        c.category = PartCategory.CUSTOM_MECHANICAL
        c.classification_path = ClassificationPath.PATH_3_3
        c.is_custom = True
        c.confidence = 0.82 if kw else 0.72
        c.classification_reason = f"Custom: '{kw}'" if kw else "Custom pattern"
        c.material_form = _material_form(combined)
        c.geometry = _geometry(combined)
        c.tolerance = _tolerance(combined)
        c.secondary_ops = _secondary_ops(combined)
        return _set_procurement_intent(c)

    # ---- Rule 2: Sheet metal signals → SHEET_METAL ----
    kw = _has_kw(combined, SHEET_METAL_KW)
    if kw or _has_pat(combined, SHEET_METAL_PAT):
        c.category = PartCategory.SHEET_METAL
        c.classification_path = ClassificationPath.PATH_3_3
        c.is_custom = True
        c.confidence = 0.80 if kw else 0.70
        c.classification_reason = f"Sheet metal: '{kw}'" if kw else "Sheet metal pattern"
        c.material_form = _material_form(combined)
        c.geometry = _geometry(combined)
        c.tolerance = _tolerance(combined)
        c.secondary_ops = _secondary_ops(combined)
        return _set_procurement_intent(c)

    # ---- Rule 3: Raw material → RAW_MATERIAL ----
    kw = _has_kw(combined, RAW_KW)
    if kw or _has_pat(combined, RAW_PAT):
        c.category = PartCategory.RAW_MATERIAL
        c.classification_path = ClassificationPath.PATH_3_2
        c.is_raw = True
        c.confidence = 0.85 if kw else 0.75
        c.classification_reason = f"Raw: '{kw}'" if kw else "Raw pattern"
        c.material_form = _material_form(combined)
        return _set_procurement_intent(c)

    # ---- Rule 4: MPN or Brand ----
    has_mpn = _is_valid_mpn(item.mpn)
    if has_mpn:
        c.has_mpn = True

    has_brand = False
    mfr = item.manufacturer.strip().lower()
    if len(mfr) >= 2:
        for b in KNOWN_BRANDS:
            if b in mfr or mfr in b:
                has_brand = True
                break
    c.has_brand = has_brand

    # Domain override first — these must not be swallowed by generic electronics / standard
    dom_cat, dom_kw = _domain_category(combined)
    if dom_cat:
        c.category = dom_cat
        c.classification_path = ClassificationPath.PATH_3_1
        c.is_generic = True
        c.confidence = 0.82 if (c.has_mpn or has_brand) else 0.78
        c.classification_reason = f"{dom_cat.value.title()}: '{dom_kw}'"
        return _set_procurement_intent(c)

    if c.has_mpn or has_brand:
        elec_kw = _has_kw(combined, ELECTRICAL_KW)
        elect_kw = _has_kw(combined, ELECTRONICS_KW)
        fast_kw = _has_kw(combined, FASTENER_KW)

        if elec_kw:
            c.category = PartCategory.ELECTRICAL
        elif elect_kw:
            c.category = PartCategory.ELECTRONICS
        elif fast_kw:
            c.category = PartCategory.FASTENER
        else:
            c.category = PartCategory.ELECTRONICS if has_brand else PartCategory.STANDARD

        c.classification_path = ClassificationPath.PATH_3_1
        c.confidence = 0.95 if (c.has_mpn and has_brand) else 0.85
        c.classification_reason = f"MPN={'Y' if c.has_mpn else 'N'}, Brand={'Y' if has_brand else 'N'}"
        return _set_procurement_intent(c)

    # ---- Rule 5: Fastener keywords ----
    kw = _has_kw(combined, FASTENER_KW)
    if kw:
        c.category = PartCategory.FASTENER
        c.classification_path = ClassificationPath.PATH_3_1
        c.is_generic = True
        c.confidence = 0.82
        c.classification_reason = f"Fastener: '{kw}'"
        return _set_procurement_intent(c)

    # ---- Rule 6: Pneumatic ----
    kw = _has_kw(combined, PNEUMATIC_KW)
    if kw:
        c.category = PartCategory.PNEUMATIC
        c.classification_path = ClassificationPath.PATH_3_1
        c.is_generic = True
        c.confidence = 0.80
        c.classification_reason = f"Pneumatic: '{kw}'"
        return _set_procurement_intent(c)

    # ---- Rule 7: Hydraulic ----
    kw = _has_kw(combined, HYDRAULIC_KW)
    if kw:
        c.category = PartCategory.HYDRAULIC
        c.classification_path = ClassificationPath.PATH_3_1
        c.is_generic = True
        c.confidence = 0.80
        c.classification_reason = f"Hydraulic: '{kw}'"
        return _set_procurement_intent(c)

    # ---- Rule 8: Cable / wiring ----
    kw = _has_kw(combined, CABLE_WIRING_KW)
    if kw:
        c.category = PartCategory.CABLE_WIRING
        c.classification_path = ClassificationPath.PATH_3_1
        c.is_generic = True
        c.confidence = 0.80
        c.classification_reason = f"Cable/wiring: '{kw}'"
        return _set_procurement_intent(c)

    # ---- Rule 9: Optical ----
    kw = _has_kw(combined, OPTICAL_KW)
    if kw:
        c.category = PartCategory.OPTICAL
        c.classification_path = ClassificationPath.PATH_3_1
        c.is_generic = True
        c.confidence = 0.80
        c.classification_reason = f"Optical: '{kw}'"
        return _set_procurement_intent(c)

    # ---- Rule 10: Thermal ----
    kw = _has_kw(combined, THERMAL_KW)
    if kw:
        c.category = PartCategory.THERMAL
        c.classification_path = ClassificationPath.PATH_3_1
        c.is_generic = True
        c.confidence = 0.80
        c.classification_reason = f"Thermal: '{kw}'"
        return _set_procurement_intent(c)

    # ---- Rule 11: Electrical keywords ----
    kw = _has_kw(text, ELECTRICAL_KW)
    if kw:
        c.category = PartCategory.ELECTRICAL
        c.classification_path = ClassificationPath.PATH_3_1
        c.is_generic = True
        c.confidence = 0.80
        c.classification_reason = f"Electrical: '{kw}'"
        return _set_procurement_intent(c)

    # ---- Rule 12: Electronics keywords ----
    kw = _has_kw(text, ELECTRONICS_KW)
    if kw:
        c.category = PartCategory.ELECTRONICS
        c.classification_path = ClassificationPath.PATH_3_1
        c.is_generic = True
        c.confidence = 0.80
        c.classification_reason = f"Electronics: '{kw}'"
        return _set_procurement_intent(c)

    # ---- Rule 13: Generic standard keywords ----
    kw = _has_kw(text, STANDARD_KW)
    if kw:
        c.category = PartCategory.STANDARD
        c.classification_path = ClassificationPath.PATH_3_1
        c.is_generic = True
        c.confidence = 0.75
        c.classification_reason = f"Standard: '{kw}'"
        return _set_procurement_intent(c)

    # ---- Rule 14: Material-only fallback ----
    if item.material.strip():
        mat_lower = item.material.strip().lower()
        mat_combined = f"{text} {mat_lower}"
        raw_kw = _has_kw(mat_combined, RAW_KW)
        raw_pat = _has_pat(mat_combined, RAW_PAT)
        if raw_kw or raw_pat:
            c.category = PartCategory.RAW_MATERIAL
            c.classification_path = ClassificationPath.PATH_3_2
            c.is_raw = True
            c.confidence = 0.55
            c.classification_reason = f"Material-only fallback → raw: '{raw_kw or 'pattern'}'"
            c.material_form = _material_form(mat_combined)
            return _set_procurement_intent(c)

        c.category = PartCategory.UNKNOWN
        c.classification_path = ClassificationPath.PATH_3_1
        c.confidence = 0.35
        c.classification_reason = (
            f"Material '{item.material.strip()[:30]}' specified but no classification signals — needs review"
        )
        c.material_form = _material_form(combined)
        return _set_procurement_intent(c)

    # ---- Rule 15: Unknown fallback ----

    c.category = PartCategory.UNKNOWN
    c.classification_path = ClassificationPath.PATH_3_1
    c.confidence = 0.30
    c.classification_reason = "Fallback: no signals — needs review"
    c.failure_reason_code = "NO_CLASSIFICATION_SIGNAL"
    c.failure_reason = "No category, MPN, brand, material, or keyword signal found"
    return _set_procurement_intent(c)

def classify_bom(items):
    """
    Wrapper to classify a list of BOM items.
    REQUIRED for orchestrator import compatibility.
    """
    return [classify_item(item) for item in items]