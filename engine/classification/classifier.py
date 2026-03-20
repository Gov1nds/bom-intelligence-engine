"""
PHASE 2 — Strict Classification Engine.

Priority order:
  1. Has valid MPN or recognized brand → STANDARD (3_1)
  2. Custom fabrication signals → CUSTOM (3_3)  [checked BEFORE raw to handle overlap]
  3. Base material signals → RAW (3_2)
  4. Generic component keyword → STANDARD (3_1)
  5. Material-in-field fallback → CUSTOM (3_3)
  6. Unknown fallback → STANDARD (low confidence)
"""
import re
from typing import List, Optional, Set
from core.schemas import (
    NormalizedBOMItem, ClassifiedItem, PartCategory, ClassificationPath,
    MaterialForm, GeometryComplexity, ToleranceClass,
)

# ---- Knowledge bases ----
KNOWN_BRANDS: Set[str] = {
    "texas instruments","ti","stmicroelectronics","stm","microchip","analog devices",
    "infineon","nxp","renesas","murata","tdk","vishay","yageo","samsung","panasonic",
    "kemet","avx","wurth","bourns","molex","te connectivity","amphenol","hirose","jst",
    "misumi","mcmaster","bosch","siemens","abb","schneider","skf","omron","phoenix contact",
}

MPN_PATTERNS = [
    re.compile(r"^[A-Z]{2,4}\d{3,}", re.I),
    re.compile(r"^\d{3,}-\d{3,}"),
    re.compile(r"^[A-Z]+\d+[A-Z]+\d+", re.I),
    re.compile(r"^ERJ-\d+", re.I),
    re.compile(r"^GRM\d+", re.I),
]

STANDARD_KW = {
    "resistor","capacitor","inductor","ferrite","thermistor","varistor","potentiometer",
    "fuse","integrated_circuit","microcontroller","transistor","mosfet","diode","led",
    "regulator","sensor","connector","header","terminal","socket","plug","usb",
    "hex_bolt","screw","nut","washer","rivet","spring","bearing","bushing",
    "o-ring","gasket","seal","gear","sprocket","pulley","pcb",
}

CUSTOM_KW = {
    "machined","cnc","milled","turned","fabricated","custom","bespoke",
    "as_per_drawing","per_drawing","welded","assembled","fabrication",
    "bracket","housing","enclosure","fixture","jig","tooling","mold",
    "manifold","chassis","frame","panel","weldment",
}

CUSTOM_PAT = [
    re.compile(r"\bcustom\s+\w+", re.I),
    re.compile(r"\bas\s*per\s*draw", re.I),
    re.compile(r"\bmachined\s+\w+", re.I),
    re.compile(r"\bcnc\s+\w+", re.I),
    re.compile(r"\bfabricat\w+", re.I),
    re.compile(r"\bbracket\b", re.I),
    re.compile(r"\bhousing\b", re.I),
    re.compile(r"\benclosure\b", re.I),
]

RAW_KW = {
    "steel_plate","aluminum_sheet","copper_bar","brass_rod","steel_bar",
    "stainless_steel_sheet","carbon_steel","tool_steel","alloy_steel",
    "aluminum_billet","titanium","nickel_alloy","inconel",
    "hdpe","nylon","abs","polycarbonate","acetal","delrin","ptfe","peek",
    "pom","pvc","polypropylene","carbon_fiber","kevlar",
    "rubber_sheet","silicone","neoprene",
    "raw_material","stock_material","bar_stock","sheet_stock",
    "tube_stock","plate","billet","ingot","blank",
}

RAW_PAT = [
    re.compile(r"\b(steel|aluminum|copper|brass|bronze)\s+(bar|rod|tube|pipe|sheet|plate|billet)\b", re.I),
    re.compile(r"\b(round|square|hex|flat)\s+(bar|stock)\b", re.I),
]

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
    """Check if any keyword is in text (handles underscores)."""
    tl = text.lower()
    for kw in keywords:
        if kw in tl or kw.replace("_", " ") in tl:
            return kw
    return None

def _has_pat(text: str, patterns: list) -> bool:
    return any(p.search(text) for p in patterns)

# ---- Main classifier ----
def classify_item(item: NormalizedBOMItem) -> ClassifiedItem:
    text = item.standard_text.lower()
    combined = f"{text} {item.mpn} {item.manufacturer} {item.material} {item.notes}".lower()
    c = ClassifiedItem(**{k: getattr(item, k) for k in item.__dataclass_fields__})

    # ---- Rule 1: MPN or Brand → STANDARD ----
    has_mpn = bool(item.mpn and len(item.mpn) >= 3)
    if has_mpn:
        c.has_mpn = True  # any 3+ char part number counts

    has_brand = False
    mfr = item.manufacturer.strip().lower()
    if len(mfr) >= 2:
        for b in KNOWN_BRANDS:
            if b in mfr or mfr in b:
                has_brand = True; break
    c.has_brand = has_brand

    if c.has_mpn or has_brand:
        c.category = PartCategory.STANDARD
        c.classification_path = ClassificationPath.PATH_3_1
        c.confidence = 0.95 if (c.has_mpn and has_brand) else 0.85
        c.classification_reason = f"MPN={'Y' if c.has_mpn else 'N'}, Brand={'Y' if has_brand else 'N'}"
        return c

    # ---- Rule 2: Custom fabrication → CUSTOM (checked BEFORE raw) ----
    kw = _has_kw(combined, CUSTOM_KW)
    if kw or _has_pat(combined, CUSTOM_PAT):
        c.category = PartCategory.CUSTOM
        c.classification_path = ClassificationPath.PATH_3_3
        c.is_custom = True
        c.confidence = 0.82 if kw else 0.72
        c.classification_reason = f"Custom: '{kw}'" if kw else "Custom pattern"
        c.material_form = _material_form(combined)
        c.geometry = _geometry(combined)
        c.tolerance = _tolerance(combined)
        c.secondary_ops = _secondary_ops(combined)
        return c

    # ---- Rule 3: Raw material → RAW ----
    kw = _has_kw(combined, RAW_KW)
    if kw or _has_pat(combined, RAW_PAT):
        c.category = PartCategory.RAW_MATERIAL
        c.classification_path = ClassificationPath.PATH_3_2
        c.is_raw = True
        c.confidence = 0.85 if kw else 0.75
        c.classification_reason = f"Raw: '{kw}'" if kw else "Raw pattern"
        c.material_form = _material_form(combined)
        return c

    # ---- Rule 4: Generic component keyword → STANDARD ----
    kw = _has_kw(text, STANDARD_KW)
    if kw:
        c.category = PartCategory.STANDARD
        c.classification_path = ClassificationPath.PATH_3_1
        c.is_generic = True
        c.confidence = 0.80
        c.classification_reason = f"Generic: '{kw}'"
        return c

    # ---- Rule 5: Has material field → likely CUSTOM ----
    if item.material.strip():
        c.category = PartCategory.CUSTOM
        c.classification_path = ClassificationPath.PATH_3_3
        c.is_custom = True
        c.confidence = 0.50
        c.classification_reason = "Fallback: material specified"
        c.material_form = _material_form(combined)
        c.geometry = _geometry(combined)
        c.tolerance = _tolerance(combined)
        c.secondary_ops = _secondary_ops(combined)
        return c

    # ---- Rule 6: Unknown fallback ----
    c.category = PartCategory.STANDARD
    c.classification_path = ClassificationPath.PATH_3_1
    c.confidence = 0.40
    c.classification_reason = "Fallback: no signals"
    return c

def classify_bom(items: List[NormalizedBOMItem]) -> List[ClassifiedItem]:
    return [classify_item(i) for i in items]
