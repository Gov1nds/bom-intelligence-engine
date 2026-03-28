"""
PHASE 1 — BOM Ingestion & NLP Normalization
Parses CSV/XLSX. Applies generic abbreviation expansion, value normalization.
Outputs List[NormalizedBOMItem].
"""
import csv, re, os
from pathlib import Path
from typing import List, Dict, Tuple
from core.schemas import NormalizedBOMItem

# ---- Abbreviation expansion (word-boundary safe, compiled once) ----
_ABBREV_SRC = [
    (r"\bres\b", "resistor"), (r"\br\b(?=\s*\d)", "resistor"),
    (r"\bcap\b", "capacitor"), (r"\bc\b(?=\s*\d)", "capacitor"),
    (r"\bind\b", "inductor"),
    (r"\bic\b", "integrated_circuit"), (r"\bmcu\b", "microcontroller"),
    (r"\bconn\b", "connector"), (r"\bhdr\b", "header"),
    (r"\bled\b", "LED"),
    (r"\bss\b(?=\s)", "stainless_steel"), (r"\bms\b(?=\s)", "mild_steel"),
    (r"\bal\b(?=\s)", "aluminum"), (r"\balu\b", "aluminum"),
    (r"\bcu\b(?=\s)", "copper"),
    (r"\bhex\s*bolt\b", "hex_bolt"), (r"\bpcb\b", "PCB"), (r"\bpcba\b", "PCB_assembly"),
    (r"\bpcs\b", "pieces"), (r"\bea\b", "each"), (r"\bqty\b", "quantity"),
]
ABBREVIATIONS = [(re.compile(p, re.I), r) for p, r in _ABBREV_SRC]

# ---- Unit normalization ----
_UNIT_MAP = {
    "pcs": "each", "pieces": "each", "pc": "each", "ea": "each",
    "nos": "each", "no": "each", "units": "each", "unit": "each",
    "set": "set", "sets": "set", "pair": "pair", "pairs": "pair",
    "kg": "kg", "kgs": "kg", "kilogram": "kg", "kilograms": "kg",
    "g": "g", "gm": "g", "gms": "g", "gram": "g", "grams": "g",
    "lb": "lb", "lbs": "lb", "pound": "lb", "pounds": "lb",
    "oz": "oz", "ounce": "oz", "ounces": "oz",
    "m": "m", "mtr": "m", "meter": "m", "meters": "m", "metre": "m", "metres": "m",
    "mm": "mm", "millimeter": "mm", "millimeters": "mm",
    "cm": "cm", "centimeter": "cm", "centimeters": "cm",
    "in": "in", "inch": "in", "inches": "in",
    "ft": "ft", "feet": "ft", "foot": "ft",
    "l": "l", "ltr": "l", "liter": "l", "liters": "l", "litre": "l", "litres": "l",
    "ml": "ml", "milliliter": "ml", "milliliters": "ml",
    "roll": "roll", "rolls": "roll",
    "reel": "reel", "reels": "reel",
    "box": "box", "boxes": "box",
    "pack": "pack", "packs": "pack",
    "bag": "bag", "bags": "bag",
    "sheet": "sheet", "sheets": "sheet",
    "length": "length", "lengths": "length",
}

def normalize_unit(unit: str) -> str:
    """Normalize UOM to a canonical form."""
    if not unit or not unit.strip():
        return "each"
    s = unit.strip().lower().rstrip(".")
    return _UNIT_MAP.get(s, s)


# ---- Material name normalization ----
_MATERIAL_NORM = {
    "ss 304": "stainless_steel_304", "ss304": "stainless_steel_304", "stainless steel 304": "stainless_steel_304",
    "ss 316": "stainless_steel_316", "ss316": "stainless_steel_316", "stainless steel 316": "stainless_steel_316",
    "ss 316l": "stainless_steel_316l", "ss316l": "stainless_steel_316l",
    "ss 202": "stainless_steel_202", "ss202": "stainless_steel_202",
    "ms": "mild_steel", "mild steel": "mild_steel", "carbon steel": "carbon_steel",
    "al 6061": "aluminum_6061", "al6061": "aluminum_6061", "aluminium 6061": "aluminum_6061", "aluminum 6061": "aluminum_6061",
    "al 7075": "aluminum_7075", "al7075": "aluminum_7075", "aluminum 7075": "aluminum_7075",
    "gi": "galvanized_iron", "galvanized iron": "galvanized_iron",
    "cu": "copper", "brass": "brass", "bronze": "bronze",
    "nylon": "nylon", "abs": "abs", "pom": "pom", "delrin": "pom",
    "ptfe": "ptfe", "teflon": "ptfe", "peek": "peek", "hdpe": "hdpe", "pvc": "pvc",
    "polycarbonate": "polycarbonate", "pc": "polycarbonate",
    "titanium": "titanium", "ti": "titanium",
    "inconel": "inconel", "nickel alloy": "nickel_alloy",
}

def normalize_material_name(material: str) -> str:
    """Normalize material name variants to canonical forms."""
    if not material or not material.strip():
        return ""
    s = material.strip().lower()
    # Try exact lookup
    if s in _MATERIAL_NORM:
        return _MATERIAL_NORM[s]
    # Try prefix match
    for key, val in _MATERIAL_NORM.items():
        if s.startswith(key) or key.startswith(s):
            return val
    # Fallback: basic normalize
    return re.sub(r"\s+", "_", s).strip("_")

# ---- Metric bolt pattern ----
BOLT_PATTERN = (re.compile(r"\bm(\d+)\s*x\s*(\d+)", re.I), r"metric_bolt_M\1x\2")

# ---- Value scaling: 10k → 10000 ----
VALUE_SCALES = [
    (re.compile(r"(\d+(?:\.\d+)?)\s*k\b", re.I), lambda m: str(int(float(m.group(1)) * 1000))),
    (re.compile(r"(\d+(?:\.\d+)?)\s*M\b"), lambda m: str(int(float(m.group(1)) * 1e6))),
]

def normalize_text(text: str) -> str:
    if not text:
        return ""
    r = text.strip().lower()
    # Metric bolt (before abbreviations since M5x20 contains 'M')
    r = BOLT_PATTERN[0].sub(BOLT_PATTERN[1], r)
    # Abbreviations: apply each pattern, but stop processing a region
    # once any abbreviation has expanded it (one expansion per token).
    expanded = set()  # start positions already expanded
    for pat, repl in ABBREVIATIONS:
        m = pat.search(r)
        if m and m.start() not in expanded:
            expanded.add(m.start())
            r = pat.sub(repl, r, count=1)  # only first occurrence
    # Value scaling
    for pat, fn in VALUE_SCALES:
        r = pat.sub(fn, r)
    # Collapse duplicate adjacent words ("resistor resistor" → "resistor")
    r = re.sub(r"\b(\w+)\s+\1\b", r"\1", r)
    # Clean whitespace
    return re.sub(r"\s+", " ", r).strip()

# ---- Package / footprint normalization ----
_PACKAGE_NORM = {
    "0201": "0201", "0402": "0402", "0603": "0603", "0805": "0805",
    "1206": "1206", "1210": "1210", "2010": "2010", "2512": "2512",
    "sot23": "SOT-23", "sot-23": "SOT-23", "sot223": "SOT-223", "sot-223": "SOT-223",
    "soic8": "SOIC-8", "soic-8": "SOIC-8", "soic16": "SOIC-16", "soic-16": "SOIC-16",
    "tssop": "TSSOP", "qfn": "QFN", "qfp": "QFP", "bga": "BGA",
    "dip8": "DIP-8", "dip-8": "DIP-8", "dip16": "DIP-16", "dip-16": "DIP-16",
    "dip14": "DIP-14", "dip-14": "DIP-14",
    "to92": "TO-92", "to-92": "TO-92", "to220": "TO-220", "to-220": "TO-220",
    "lqfp": "LQFP", "sop": "SOP",
}
_PACKAGE_RE = re.compile(
    r"\b(0201|0402|0603|0805|1206|1210|2010|2512|"
    r"SOT-?\d+|SOIC-?\d*|TSSOP-?\d*|QFN-?\d*|QFP-?\d*|BGA-?\d*|"
    r"DIP-?\d*|TO-?\d+|LQFP-?\d*|SOP-?\d*)\b", re.I
)

def normalize_package(pkg: str) -> str:
    """Normalize package/footprint notation to canonical form."""
    if not pkg or not pkg.strip():
        return ""
    s = pkg.strip().lower().replace(" ", "")
    if s in _PACKAGE_NORM:
        return _PACKAGE_NORM[s]
    # Try regex match
    m = _PACKAGE_RE.search(pkg)
    if m:
        return m.group(1).upper()
    return pkg.strip()


# ---- Process hint normalization ----
_PROCESS_NORM = {
    "cnc": "CNC_machining", "cnc machining": "CNC_machining", "cnc milling": "CNC_milling",
    "cnc turning": "CNC_turning", "milling": "CNC_milling", "turning": "CNC_turning",
    "3 axis": "CNC_3axis", "5 axis": "CNC_5axis", "5-axis": "CNC_5axis",
    "laser cut": "laser_cutting", "laser cutting": "laser_cutting",
    "waterjet": "waterjet_cutting", "water jet": "waterjet_cutting",
    "plasma": "plasma_cutting", "plasma cut": "plasma_cutting",
    "press brake": "press_brake", "bending": "press_brake", "bend": "press_brake",
    "stamping": "stamping", "stamped": "stamping",
    "die casting": "die_casting", "die cast": "die_casting",
    "injection molding": "injection_molding", "injection mold": "injection_molding",
    "3d printing": "additive_3d", "additive": "additive_3d", "sls": "SLS", "sla": "SLA",
    "edm": "EDM", "wire edm": "wire_EDM",
    "grinding": "grinding", "honing": "honing",
    "welding": "welding", "welded": "welding", "tig": "TIG_welding", "mig": "MIG_welding",
    "threading": "threading", "tapping": "threading",
    "anodizing": "anodizing", "anodised": "anodizing",
    "powder coating": "powder_coating", "plating": "plating",
    "heat treatment": "heat_treatment", "hardening": "heat_treatment",
    "forging": "forging", "casting": "casting",
}

def normalize_process(process: str) -> str:
    """Normalize process/operation hints to canonical form."""
    if not process or not process.strip():
        return ""
    s = process.strip().lower()
    if s in _PROCESS_NORM:
        return _PROCESS_NORM[s]
    # Try prefix match
    for key, val in _PROCESS_NORM.items():
        if key in s:
            return val
    return re.sub(r"\s+", "_", s).strip("_")

# ---- Column mapping ----
COL_ALIASES = {
    "part_name": ["part_name","part name","part","component","item","description","name","part description","item name"],
    "quantity": ["quantity","qty","count","amount","order qty","req qty"],
    "material": ["material","mat","material_type","raw material"],
    "notes": ["notes","note","comments","remark","remarks","specification","spec"],
    "mpn": ["mpn","part_number","part number","pn","mfg_part_number","catalog number"],
    "manufacturer": ["manufacturer","mfr","vendor","supplier","mfg","make","brand","oem"],
    "unit": ["unit","uom"],
    "reference": ["reference","ref","designator","ref_des"],
}

def _map_columns(headers: List[str]) -> Dict[str, str]:
    norm = {h.strip().lower(): h for h in headers}
    mapping = {}
    for std, aliases in COL_ALIASES.items():
        for a in aliases:
            if a.lower() in norm:
                mapping[std] = norm[a.lower()]
                break
    return mapping
def _open_file_safe(path: str):
    encodings = ["utf-8-sig", "utf-8", "cp1252", "latin-1"]

    for enc in encodings:
        try:
            return open(path, "r", encoding=enc, errors="replace")
        except Exception:
            continue

    raise ValueError(f"Unable to open file with supported encodings: {path}")
def _parse_csv(path: str) -> Tuple[List[str], List[Dict]]:
    with _open_file_safe(path) as f:
        sample = f.read(4096)
        f.seek(0)

        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel

        reader = csv.DictReader(f, dialect=dialect)
        headers = reader.fieldnames or []

        rows = [
            r for r in reader
            if any(str(v).strip() for v in r.values())
        ]

    return headers, rows
def _parse_xlsx(path: str) -> Tuple[List[str], List[Dict]]:
    import pandas as pd
    df = pd.read_excel(path, engine="openpyxl").fillna("")
    return list(df.columns), df.to_dict("records")

def _extract_qty(row, cmap):
    k = cmap.get("quantity")
    if not k: return 1
    m = re.search(r"(\d+(?:\.\d+)?)", str(row.get(k, "1")))
    return max(1, int(float(m.group(1)))) if m else 1


# ---- MPN Normalization ----
def normalize_mpn(mpn: str) -> str:
    """Normalize MPN: strip whitespace/hyphens, uppercase. Preserves alphanumeric structure."""
    if not mpn or not mpn.strip():
        return ""
    s = mpn.strip()
    # Remove common wrapping chars
    s = re.sub(r"^['\"\s]+|['\"\s]+$", "", s)
    # Uppercase
    s = s.upper()
    # Collapse internal whitespace but preserve hyphens (some MPNs use them)
    s = re.sub(r"\s+", "", s)
    return s


# ---- Manufacturer / Supplier Name Normalization ----
_MANUFACTURER_ALIASES = {
    "ti": "texas instruments", "t.i.": "texas instruments", "texas inst": "texas instruments",
    "stm": "stmicroelectronics", "st micro": "stmicroelectronics", "st ": "stmicroelectronics",
    "adi": "analog devices", "analog dev": "analog devices",
    "nxp semi": "nxp", "nxp semiconductors": "nxp",
    "te conn": "te connectivity", "tyco": "te connectivity",
    "avx corp": "avx", "kyocera avx": "avx",
    "tdk corp": "tdk", "tdk corporation": "tdk",
    "murata mfg": "murata", "murata manufacturing": "murata",
    "yageo corp": "yageo", "yageo corporation": "yageo",
    "vishay": "vishay", "vishay intertechnology": "vishay",
    "samsung electro": "samsung", "samsung electro-mechanics": "samsung",
    "panasonic corp": "panasonic", "panasonic electronic": "panasonic",
    "molex inc": "molex", "molex llc": "molex",
    "amphenol corp": "amphenol", "amphenol corporation": "amphenol",
    "phoenix con": "phoenix contact",
    "wurth elek": "wurth", "wurth elektronik": "wurth",
    "mcmaster carr": "mcmaster", "mcmaster-carr": "mcmaster",
    "misumi corp": "misumi",
    "abb ltd": "abb", "abb group": "abb",
    "schneider elec": "schneider", "schneider electric": "schneider",
    "siemens ag": "siemens",
    "bosch gmbh": "bosch", "robert bosch": "bosch",
    "skf group": "skf", "skf ab": "skf",
}

def normalize_manufacturer(name: str) -> str:
    """Normalize manufacturer name: lowercase, trim, resolve known aliases."""
    if not name or not name.strip():
        return ""
    s = name.strip()
    sl = s.lower()
    # Remove trailing legal suffixes
    sl = re.sub(r"\s+(inc\.?|llc|ltd\.?|corp\.?|co\.?|gmbh|ag|plc|sa|nv|bv)\s*$", "", sl, flags=re.I)
    sl = sl.strip()
    # Check aliases
    for alias, canonical in _MANUFACTURER_ALIASES.items():
        if sl == alias or sl.startswith(alias):
            return canonical
    return sl


def process_bom(file_path: str, user_location: str = "", target_currency: str = "USD", email: str = "") -> List[NormalizedBOMItem]:
    p = Path(file_path)
    if not p.exists(): raise FileNotFoundError(f"Not found: {file_path}")
    ext = p.suffix.lower()
    if ext == ".csv": headers, rows = _parse_csv(file_path)
    elif ext in (".xlsx", ".xls"): headers, rows = _parse_xlsx(file_path)
    else: raise ValueError(f"Unsupported: {ext}")
    if not rows: raise ValueError("No data rows")
    cmap = _map_columns(headers)
    if "part_name" not in cmap and headers:
        cmap["part_name"] = headers[0]
    items = []
    for idx, row in enumerate(rows):
        pk = cmap.get("part_name", headers[0] if headers else "")
        raw = str(row.get(pk, "")).strip()
        if not raw: continue
        mpn_raw = str(row.get(cmap.get("mpn", ""), "")).strip()
        mfr_raw = str(row.get(cmap.get("manufacturer", ""), "")).strip()
        mat = str(row.get(cmap.get("material", ""), "")).strip()
        notes = str(row.get(cmap.get("notes", ""), "")).strip()
        unit_raw = str(row.get(cmap.get("unit", ""), "")).strip()
        items.append(NormalizedBOMItem(
            item_id=f"BOM-{idx+1:04d}", raw_text=raw,
            standard_text=normalize_text(raw), quantity=_extract_qty(row, cmap),
            description=normalize_text(raw),
            mpn=normalize_mpn(mpn_raw),
            manufacturer=normalize_manufacturer(mfr_raw),
            make=normalize_manufacturer(mfr_raw),
            material=normalize_material_name(mat) or normalize_text(mat),
            notes=notes,
            unit=normalize_unit(unit_raw),
            raw_row={str(k): str(v) for k, v in row.items()},
        ))
    return items
# =========================================================
# UBNE INTEGRATION (append — do not modify above)
# =========================================================

def process_bom_v2(
    file_path: str,
    user_location: str = "",
    target_currency: str = "USD",
    email: str = "",
):
    """
    Enhanced BOM processing with UBNE.
    Falls back to original process_bom on failure.
    Returns: (items, diagnostics_or_none)
    """
    from engine.ingestion.ubne import USE_NEW_NORMALIZER, ubne_process_bom
    import logging
    _logger = logging.getLogger("ubne")

    if USE_NEW_NORMALIZER:
        try:
            _logger.info("UBNE pipeline active — processing with new normalizer")
            items, diagnostics = ubne_process_bom(file_path, user_location, target_currency, email)
            if items:
                _logger.info(f"UBNE success: {len(items)} items")
                return items, diagnostics
            else:
                _logger.warning("UBNE returned empty — falling back to legacy parser")
        except Exception as e:
            _logger.error(f"UBNE failed: {e} — falling back to legacy parser")

    # Fallback to original
    items = process_bom(file_path, user_location, target_currency, email)
    return items, None