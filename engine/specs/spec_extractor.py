"""
PHASE A — Specification Extraction Engine

Extracts structured attributes from raw BOM text:
  - Mechanical: thread, dimensions, material grade, head type, coating, standard
  - Electrical: resistance, capacitance, voltage, tolerance, package, component type
  - Raw material: grade, form, dimensions, finish

All regex-based, no ML. Fast, deterministic, scalable.
"""

import re
import logging
from typing import Dict, Any, Optional, List

logger = logging.getLogger("spec_extractor")


# ══════════════════════════════════════════════════════════
# MATERIAL DATABASE
# ══════════════════════════════════════════════════════════

MATERIAL_DB = {
    # Stainless steel
    "ss304": {"name": "Stainless Steel 304", "family": "stainless_steel", "grade": "304"},
    "ss316": {"name": "Stainless Steel 316", "family": "stainless_steel", "grade": "316"},
    "ss316l": {"name": "Stainless Steel 316L", "family": "stainless_steel", "grade": "316L"},
    "ss202": {"name": "Stainless Steel 202", "family": "stainless_steel", "grade": "202"},
    "ss410": {"name": "Stainless Steel 410", "family": "stainless_steel", "grade": "410"},
    # Carbon / mild steel
    "ms": {"name": "Mild Steel", "family": "carbon_steel", "grade": "MS"},
    "en8": {"name": "EN8 Carbon Steel", "family": "carbon_steel", "grade": "EN8"},
    "en19": {"name": "EN19 Alloy Steel", "family": "alloy_steel", "grade": "EN19"},
    "en24": {"name": "EN24 Alloy Steel", "family": "alloy_steel", "grade": "EN24"},
    "1018": {"name": "AISI 1018", "family": "carbon_steel", "grade": "1018"},
    "1045": {"name": "AISI 1045", "family": "carbon_steel", "grade": "1045"},
    "4140": {"name": "AISI 4140", "family": "alloy_steel", "grade": "4140"},
    # Aluminum
    "6061": {"name": "Aluminum 6061", "family": "aluminum", "grade": "6061"},
    "7075": {"name": "Aluminum 7075", "family": "aluminum", "grade": "7075"},
    "5052": {"name": "Aluminum 5052", "family": "aluminum", "grade": "5052"},
    "2024": {"name": "Aluminum 2024", "family": "aluminum", "grade": "2024"},
    # Plastics
    "abs": {"name": "ABS", "family": "plastic", "grade": "ABS"},
    "nylon": {"name": "Nylon", "family": "plastic", "grade": "Nylon"},
    "pom": {"name": "POM / Delrin", "family": "plastic", "grade": "POM"},
    "ptfe": {"name": "PTFE", "family": "plastic", "grade": "PTFE"},
    "peek": {"name": "PEEK", "family": "plastic", "grade": "PEEK"},
    "hdpe": {"name": "HDPE", "family": "plastic", "grade": "HDPE"},
    "pvc": {"name": "PVC", "family": "plastic", "grade": "PVC"},
    "delrin": {"name": "Delrin / POM", "family": "plastic", "grade": "POM"},
    "polycarbonate": {"name": "Polycarbonate", "family": "plastic", "grade": "PC"},
    # Copper / Brass
    "c110": {"name": "Copper C110", "family": "copper", "grade": "C110"},
    "c360": {"name": "Brass C360", "family": "brass", "grade": "C360"},
}

# ══════════════════════════════════════════════════════════
# COMPILED REGEX PATTERNS
# ══════════════════════════════════════════════════════════

# -- Mechanical --
_METRIC_THREAD = re.compile(r"\bM(\d+(?:\.\d+)?)\s*[xX×]\s*(\d+(?:\.\d+)?)", re.I)
_METRIC_THREAD_ONLY = re.compile(r"\bM(\d+(?:\.\d+)?)\b(?!\s*[xX×])", re.I)
_UNC_THREAD = re.compile(r"\b(\d+/\d+)-(\d+)\s*(UNC|UNF)\b", re.I)
_THREAD_PITCH = re.compile(r"\bM\d+\s*[xX]\s*\d+(?:\.\d+)?\s*[xX×]\s*(\d+(?:\.\d+)?)\b", re.I)
_BOLT_GRADE = re.compile(r"\b(\d+\.\d+)\s*(?:grade|class)?\b")
_BOLT_GRADE2 = re.compile(r"\b(?:grade|class)\s*(\d+\.\d+)\b", re.I)

_DIM_MM = re.compile(r"\b(\d+(?:\.\d+)?)\s*(?:mm)\b", re.I)
_DIM_INCH = re.compile(r"""(\d+(?:\.\d+)?)\s*(?:"|inch(?:es)?|in)\b""", re.I)
_DIM_MULTI = re.compile(r"\b(\d+(?:\.\d+)?)\s*[xX×]\s*(\d+(?:\.\d+)?)\s*(?:[xX×]\s*(\d+(?:\.\d+)?))?\s*(?:mm)?\b")
_DIAMETER = re.compile(r"(?:Ø|dia(?:meter)?\.?)\s*(\d+(?:\.\d+)?)\s*(?:mm)?", re.I)
_THICKNESS = re.compile(r"\b(\d+(?:\.\d+)?)\s*mm\s*(?:thick|thk|t)\b", re.I)

_TOLERANCE = re.compile(r"[±]\s*(\d+(?:\.\d+)?)\s*(mm|um|µm|inch|\")?", re.I)
_IT_GRADE = re.compile(r"\b(H[67]|h[67]|IT\d+)\b")
_RA_FINISH = re.compile(r"\bRa\s*(\d+(?:\.\d+)?)\s*(µm|um)?\b", re.I)

_HEAD_TYPES = {
    "hex": re.compile(r"\bhex(?:\s*head)?\b", re.I),
    "socket_head": re.compile(r"\bsocket\s*head\b", re.I),
    "countersunk": re.compile(r"\b(?:countersunk|csk|flat\s*head)\b", re.I),
    "pan_head": re.compile(r"\bpan\s*head\b", re.I),
    "button_head": re.compile(r"\bbutton\s*head\b", re.I),
    "grub": re.compile(r"\b(?:grub|set)\s*screw\b", re.I),
}

_FASTENER_TYPE = {
    "bolt": re.compile(r"\bbolt\b", re.I),
    "screw": re.compile(r"\bscrew\b", re.I),
    "nut": re.compile(r"\bnut\b", re.I),
    "washer": re.compile(r"\bwasher\b", re.I),
    "stud": re.compile(r"\bstud\b", re.I),
    "threaded_rod": re.compile(r"\b(?:threaded\s*rod|studding)\b", re.I),
    "rivet": re.compile(r"\brivet\b", re.I),
    "pin": re.compile(r"\b(?:dowel\s*)?pin\b", re.I),
    "spring": re.compile(r"\bspring\b", re.I),
}

_COATING = {
    "zinc_plated": re.compile(r"\b(?:zinc\s*plat|zn\s*plat|galvan)\w*\b", re.I),
    "hot_dip_galvanized": re.compile(r"\b(?:hdg|hot\s*dip)\b", re.I),
    "black_oxide": re.compile(r"\bblack\s*oxide\b", re.I),
    "anodized": re.compile(r"\banodi[sz]\w*\b", re.I),
    "powder_coated": re.compile(r"\bpowder\s*coat\w*\b", re.I),
    "chrome": re.compile(r"\bchrome\s*plat\w*\b", re.I),
    "nickel": re.compile(r"\bnickel\s*plat\w*\b", re.I),
    "passivated": re.compile(r"\bpassivat\w*\b", re.I),
}

_STANDARDS = {
    "DIN933": "hex_bolt", "DIN931": "hex_bolt", "DIN912": "socket_head_cap_screw",
    "DIN934": "hex_nut", "DIN125": "flat_washer", "DIN127": "spring_washer",
    "DIN7991": "countersunk_screw", "DIN603": "carriage_bolt",
    "ISO4762": "socket_head_cap_screw", "ISO4014": "hex_bolt", "ISO4017": "hex_bolt",
    "ISO4032": "hex_nut", "ISO7380": "button_head_screw",
}
_STANDARD_PAT = re.compile(r"\b((?:DIN|ISO|ANSI|ASTM|JIS|BS)\s*\d+[A-Z]?)\b", re.I)

# -- Electrical --
_RESISTANCE = re.compile(r"\b(\d+(?:\.\d+)?)\s*([mkMG]?)(?:Ω|ohm|OHM)\b", re.I)
_RESISTANCE_SHORT = re.compile(r"\b(\d+(?:\.\d+)?)\s*([kKmM])\b(?=.*(?:resist|ohm|%|tol))", re.I)
_CAPACITANCE = re.compile(r"\b(\d+(?:\.\d+)?)\s*(p|n|u|µ|m)?F\b", re.I)
_INDUCTANCE = re.compile(r"\b(\d+(?:\.\d+)?)\s*(n|u|µ|m)?H\b", re.I)
_VOLTAGE = re.compile(r"\b(\d+(?:\.\d+)?)\s*V\s*(AC|DC)?\b", re.I)
_CURRENT = re.compile(r"\b(\d+(?:\.\d+)?)\s*(m)?A\b", re.I)
_POWER_W = re.compile(r"\b(\d+(?:\.\d+)?)\s*W\b", re.I)
_POWER_FRAC = re.compile(r"\b(\d+)/(\d+)\s*W\b", re.I)
_TOLERANCE_PCT = re.compile(r"[±]?\s*(\d+(?:\.\d+)?)\s*%")
_FREQUENCY = re.compile(r"\b(\d+(?:\.\d+)?)\s*(k|M|G)?Hz\b", re.I)
_TEMP_RANGE = re.compile(r"(-?\d+)\s*°?\s*C\s*(?:to|~|-)\s*(-?\d+)\s*°?\s*C", re.I)

_SMD_PACKAGES = re.compile(r"\b(0201|0402|0603|0805|1206|1210|2010|2512)\b")
_IC_PACKAGES = re.compile(r"\b(SOT-?\d+|SOIC-?\d*|TSSOP-?\d*|QFN-?\d*|QFP-?\d*|BGA-?\d*|DIP-?\d*|TO-?\d+|LQFP-?\d*|SOP-?\d*)\b", re.I)
_DIELECTRIC = re.compile(r"\b(X7R|X5R|C0G|NP0|Y5V|X7S|X6S)\b", re.I)

_COMPONENT_TYPES = {
    "resistor": re.compile(r"\bresist(?:or)?\b", re.I),
    "capacitor": re.compile(r"\bcapacit(?:or)?\b", re.I),
    "inductor": re.compile(r"\binduct(?:or)?\b", re.I),
    "diode": re.compile(r"\bdiode\b", re.I),
    "transistor": re.compile(r"\btransistor\b", re.I),
    "mosfet": re.compile(r"\bmosfet\b", re.I),
    "ic": re.compile(r"\b(?:ic|integrated.circuit)\b", re.I),
    "microcontroller": re.compile(r"\b(?:mcu|microcontroller)\b", re.I),
    "regulator": re.compile(r"\b(?:regulator|ldo|vreg)\b", re.I),
    "connector": re.compile(r"\bconnect(?:or)?\b", re.I),
    "relay": re.compile(r"\brelay\b", re.I),
    "fuse": re.compile(r"\bfuse\b", re.I),
    "crystal": re.compile(r"\b(?:crystal|oscillator|xtal)\b", re.I),
    "transformer": re.compile(r"\btransformer\b", re.I),
    "led": re.compile(r"\bled\b", re.I),
    "sensor": re.compile(r"\bsensor\b", re.I),
    "switch": re.compile(r"\bswitch\b", re.I),
}

_MOUNTING = re.compile(r"\b(smd|smt|surface\s*mount|through[\s-]*hole|tht|dip)\b", re.I)

# -- Raw material forms --
_RAW_FORMS = {
    "sheet": re.compile(r"\bsheet\b", re.I),
    "plate": re.compile(r"\bplate\b", re.I),
    "rod": re.compile(r"\b(?:rod|round\s*bar)\b", re.I),
    "bar": re.compile(r"\b(?:bar|flat\s*bar|square\s*bar)\b", re.I),
    "tube": re.compile(r"\b(?:tube|pipe)\b", re.I),
    "billet": re.compile(r"\bbillet\b", re.I),
    "coil": re.compile(r"\bcoil\b", re.I),
    "wire": re.compile(r"\bwire\b", re.I),
    "strip": re.compile(r"\bstrip\b", re.I),
    "block": re.compile(r"\bblock\b", re.I),
}


# ══════════════════════════════════════════════════════════
# UNIT NORMALIZATION
# ══════════════════════════════════════════════════════════

_ELEC_MULT = {"p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "m": 1e-3, "": 1, "k": 1e3, "K": 1e3, "M": 1e6, "G": 1e9}


def _scale(value: float, prefix: str) -> float:
    return value * _ELEC_MULT.get(prefix, 1)


def _inch_to_mm(val: float) -> float:
    return round(val * 25.4, 2)


# ══════════════════════════════════════════════════════════
# MATERIAL EXTRACTOR
# ══════════════════════════════════════════════════════════

_MAT_PAT = re.compile(
    r"\b(?:"
    r"SS\s*304L?|SS\s*316L?|SS\s*202|SS\s*410|"
    r"6061|7075|5052|2024|"
    r"EN\s*[89]|EN\s*19|EN\s*24|"
    r"AISI\s*\d{4}|1018|1045|4140|"
    r"C110|C360|"
    r"ABS|NYLON|POM|PTFE|PEEK|HDPE|PVC|DELRIN|POLYCARBONATE|"
    r"MILD\s*STEEL|CARBON\s*STEEL|STAINLESS\s*STEEL|"
    r"ALUMINUM|ALUMINIUM|COPPER|BRASS|BRONZE|TITANIUM"
    r")\b",
    re.I,
)

_TEMPER = re.compile(r"\b([THO]\d{1,4})\b")


def extract_material(text: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    m = _MAT_PAT.search(text)
    if m:
        raw = m.group(0).strip()
        key = re.sub(r"\s+", "", raw).lower()
        # Try direct lookup
        info = MATERIAL_DB.get(key)
        if not info:
            # Try partial key match
            for k, v in MATERIAL_DB.items():
                if k in key or key in k:
                    info = v
                    break
        if info:
            out["material_name"] = info["name"]
            out["material_family"] = info["family"]
            out["material_grade"] = info["grade"]
        else:
            out["material_name"] = raw
            out["material_grade"] = raw

    # Temper
    tm = _TEMPER.search(text)
    if tm:
        out["temper"] = tm.group(1)

    return out


# ══════════════════════════════════════════════════════════
# MAIN EXTRACTION FUNCTIONS
# ══════════════════════════════════════════════════════════

def extract_mechanical(text: str) -> Dict[str, Any]:
    """Extract mechanical specs from text."""
    specs: Dict[str, Any] = {"domain": "mechanical"}

    # Thread
    m = _METRIC_THREAD.search(text)
    if m:
        specs["thread_size"] = f"M{m.group(1)}"
        specs["length_mm"] = float(m.group(2))
    else:
        m = _METRIC_THREAD_ONLY.search(text)
        if m:
            specs["thread_size"] = f"M{m.group(1)}"
        m2 = _UNC_THREAD.search(text)
        if m2:
            specs["thread_size"] = f"{m2.group(1)}-{m2.group(2)} {m2.group(3).upper()}"

    # Pitch
    m = _THREAD_PITCH.search(text)
    if m:
        specs["thread_pitch"] = float(m.group(1))

    # Bolt grade
    m = _BOLT_GRADE2.search(text) or _BOLT_GRADE.search(text)
    if m:
        specs["bolt_grade"] = m.group(1)

    # Dimensions
    m = _DIM_MULTI.search(text)
    if m and not specs.get("thread_size"):
        dims = [float(m.group(1)), float(m.group(2))]
        if m.group(3):
            dims.append(float(m.group(3)))
        specs["dimensions_mm"] = dims

    m = _DIAMETER.search(text)
    if m:
        specs["diameter_mm"] = float(m.group(1))

    m = _THICKNESS.search(text)
    if m:
        specs["thickness_mm"] = float(m.group(1))

    # Inch dimensions → convert to mm
    for im in _DIM_INCH.finditer(text):
        if "length_mm" not in specs:
            specs["length_mm"] = _inch_to_mm(float(im.group(1)))

    # Length from mm pattern if not from thread
    if "length_mm" not in specs:
        mm_vals = _DIM_MM.findall(text)
        if mm_vals:
            specs["length_mm"] = float(mm_vals[-1])

    # Material
    specs.update(extract_material(text))

    # Head type
    for htype, pat in _HEAD_TYPES.items():
        if pat.search(text):
            specs["head_type"] = htype
            break

    # Fastener type
    for ftype, pat in _FASTENER_TYPE.items():
        if pat.search(text):
            specs["fastener_type"] = ftype
            break

    # Coating
    for ctype, pat in _COATING.items():
        if pat.search(text):
            specs["coating"] = ctype
            break

    # Standard
    m = _STANDARD_PAT.search(text)
    if m:
        std = re.sub(r"\s+", "", m.group(1)).upper()
        specs["standard"] = std
        if std in _STANDARDS:
            specs["standard_part_type"] = _STANDARDS[std]

    # Tolerance
    m = _TOLERANCE.search(text)
    if m:
        val = float(m.group(1))
        unit = (m.group(2) or "mm").lower()
        if unit in ("um", "µm"):
            val /= 1000
        elif unit in ("inch", '"'):
            val = _inch_to_mm(val)
        specs["tolerance_mm"] = val

    m = _IT_GRADE.search(text)
    if m:
        specs["fit_class"] = m.group(1)

    m = _RA_FINISH.search(text)
    if m:
        specs["surface_roughness_ra"] = float(m.group(1))

    # Geometry classification
    if specs.get("fastener_type"):
        specs["geometry_class"] = "fastener"
    elif any(w in text.lower() for w in ["shaft", "spindle", "axle"]):
        specs["geometry_class"] = "shaft"
    elif any(w in text.lower() for w in ["plate", "sheet"]):
        specs["geometry_class"] = "plate"
    elif any(w in text.lower() for w in ["bracket", "mount"]):
        specs["geometry_class"] = "bracket"
    else:
        specs["geometry_class"] = "general"

    return specs


def extract_electrical(text: str) -> Dict[str, Any]:
    """Extract electrical/electronic specs from text."""
    specs: Dict[str, Any] = {"domain": "electrical"}

    # Component type
    for ctype, pat in _COMPONENT_TYPES.items():
        if pat.search(text):
            specs["component_type"] = ctype
            break

    # Resistance
    m = _RESISTANCE.search(text)
    if m:
        specs["resistance_ohm"] = _scale(float(m.group(1)), m.group(2))
    else:
        m = _RESISTANCE_SHORT.search(text)
        if m:
            specs["resistance_ohm"] = _scale(float(m.group(1)), m.group(2))

    # Capacitance
    m = _CAPACITANCE.search(text)
    if m:
        specs["capacitance_f"] = _scale(float(m.group(1)), m.group(2) or "")
        specs["capacitance_display"] = f"{m.group(1)}{m.group(2) or ''}F"

    # Inductance
    m = _INDUCTANCE.search(text)
    if m:
        specs["inductance_h"] = _scale(float(m.group(1)), m.group(2) or "")

    # Voltage
    m = _VOLTAGE.search(text)
    if m:
        specs["voltage_v"] = float(m.group(1))
        if m.group(2):
            specs["voltage_type"] = m.group(2).upper()

    # Current
    m = _CURRENT.search(text)
    if m:
        val = float(m.group(1))
        if m.group(2) and m.group(2).lower() == "m":
            val /= 1000
        specs["current_a"] = val

    # Power
    m = _POWER_FRAC.search(text)
    if m:
        specs["power_w"] = round(float(m.group(1)) / float(m.group(2)), 4)
    else:
        m = _POWER_W.search(text)
        if m:
            specs["power_w"] = float(m.group(1))

    # Tolerance
    m = _TOLERANCE_PCT.search(text)
    if m:
        specs["tolerance_pct"] = float(m.group(1))

    # Package
    m = _SMD_PACKAGES.search(text)
    if m:
        specs["package"] = m.group(1)
        specs["mounting"] = "smd"
    else:
        m = _IC_PACKAGES.search(text)
        if m:
            specs["package"] = m.group(1).upper()

    # Mounting
    if "mounting" not in specs:
        m = _MOUNTING.search(text)
        if m:
            mt = m.group(1).lower()
            specs["mounting"] = "smd" if mt in ("smd", "smt", "surface mount") else "through_hole"

    # Dielectric
    m = _DIELECTRIC.search(text)
    if m:
        specs["dielectric"] = m.group(1).upper()

    # Frequency
    m = _FREQUENCY.search(text)
    if m:
        specs["frequency_hz"] = _scale(float(m.group(1)), m.group(2) or "")

    # Temperature
    m = _TEMP_RANGE.search(text)
    if m:
        specs["temp_min_c"] = int(m.group(1))
        specs["temp_max_c"] = int(m.group(2))

    return specs


def extract_raw_material(text: str) -> Dict[str, Any]:
    """Extract raw material specs from text."""
    specs: Dict[str, Any] = {"domain": "raw_material"}
    specs.update(extract_material(text))

    # Form
    for form, pat in _RAW_FORMS.items():
        if pat.search(text):
            specs["form"] = form
            break

    # Dimensions
    m = _THICKNESS.search(text)
    if m:
        specs["thickness_mm"] = float(m.group(1))

    m = _DIAMETER.search(text)
    if m:
        specs["diameter_mm"] = float(m.group(1))

    m = _DIM_MULTI.search(text)
    if m:
        dims = [float(m.group(1)), float(m.group(2))]
        if m.group(3):
            dims.append(float(m.group(3)))
        specs["dimensions_mm"] = dims

    # Coating / finish
    for ctype, pat in _COATING.items():
        if pat.search(text):
            specs["finish"] = ctype
            break

    # Standard
    m = _STANDARD_PAT.search(text)
    if m:
        specs["standard"] = re.sub(r"\s+", "", m.group(1)).upper()

    return specs


# ══════════════════════════════════════════════════════════
# UNIFIED EXTRACTOR
# ══════════════════════════════════════════════════════════

# Signals that text is electrical
_ELEC_SIGNALS = re.compile(
    r"\b(?:resistor|capacitor|inductor|diode|transistor|mosfet|ic|mcu|"
    r"regulator|connector|relay|fuse|crystal|led|sensor|switch|"
    r"ohm|farad|henry|[0-9]+[kKmM]?Ω|smd|smt|"
    r"0201|0402|0603|0805|1206|SOT|SOIC|QFN|BGA|DIP|TO-)\b",
    re.I,
)

# Signals that text is raw material
_RAW_SIGNALS = re.compile(
    r"\b(?:sheet|plate|rod|bar|tube|billet|coil|wire|strip|block|"
    r"stock|raw\s*material|per\s*kg|per\s*ton)\b",
    re.I,
)

# Mechanical signals
_MECH_SIGNALS = re.compile(
    r"\b(?:bolt|screw|nut|washer|stud|rivet|pin|spring|bearing|"
    r"bracket|shaft|housing|flange|bushing|spacer|standoff|"
    r"M\d+\s*x|DIN|ISO\d|thread|hex|socket)\b",
    re.I,
)


def extract_specs(text: str, category: str = "auto") -> Dict[str, Any]:
    """
    Main entry point. Extracts structured specifications from BOM text.

    Args:
        text: Raw or normalized description text
        category: "standard", "raw_material", "custom", or "auto" (detect)

    Returns:
        Dict with structured specs, always includes 'domain' key.
    """
    if not text or not text.strip():
        return {"domain": "unknown"}

    combined = text.strip()

    # Auto-detect domain
    if category == "auto":
        elec_score = len(_ELEC_SIGNALS.findall(combined))
        raw_score = len(_RAW_SIGNALS.findall(combined))
        mech_score = len(_MECH_SIGNALS.findall(combined))

        if elec_score > raw_score and elec_score > mech_score:
            category = "standard"
        elif raw_score > mech_score:
            category = "raw_material"
        else:
            category = "custom"  # default to mechanical/custom

    # Extract based on category
    if category in ("standard",):
        specs = extract_electrical(combined)
    elif category == "raw_material":
        specs = extract_raw_material(combined)
    else:
        specs = extract_mechanical(combined)

    # Always try to extract material if not already found
    if "material_grade" not in specs:
        mat = extract_material(combined)
        if mat:
            specs.update(mat)

    # Build enriched description
    specs["_enriched"] = _build_enriched(specs, combined)

    return specs


def _build_enriched(specs: Dict, original: str) -> str:
    """Build a human-readable enriched description from extracted specs."""
    parts = []

    # Type
    ft = specs.get("fastener_type") or specs.get("component_type") or specs.get("geometry_class")
    if ft:
        parts.append(ft.replace("_", " ").title())

    # Material
    mg = specs.get("material_name") or specs.get("material_grade")
    if mg:
        parts.append(mg)

    # Thread + length
    ts = specs.get("thread_size")
    if ts:
        ln = specs.get("length_mm")
        parts.append(f"{ts}x{int(ln)}" if ln else ts)

    # Electrical values
    if specs.get("resistance_ohm") is not None:
        r = specs["resistance_ohm"]
        if r >= 1e6:
            parts.append(f"{r/1e6:.1f}MΩ")
        elif r >= 1e3:
            parts.append(f"{r/1e3:.1f}kΩ")
        else:
            parts.append(f"{r:.1f}Ω")

    if specs.get("capacitance_display"):
        parts.append(specs["capacitance_display"])

    if specs.get("voltage_v") is not None:
        parts.append(f"{specs['voltage_v']}V")

    if specs.get("tolerance_pct") is not None:
        parts.append(f"±{specs['tolerance_pct']}%")

    if specs.get("package"):
        parts.append(specs["package"])

    # Head type
    if specs.get("head_type"):
        parts.append(specs["head_type"].replace("_", " "))

    # Coating
    if specs.get("coating") or specs.get("finish"):
        parts.append((specs.get("coating") or specs.get("finish", "")).replace("_", " "))

    # Standard
    if specs.get("standard"):
        parts.append(specs["standard"])

    # Form (raw material)
    if specs.get("form"):
        parts.append(specs["form"])

    if parts:
        return " ".join(parts)

    # Fallback: return cleaned original
    return original.strip()
