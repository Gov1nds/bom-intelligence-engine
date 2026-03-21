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
        mpn = str(row.get(cmap.get("mpn", ""), "")).strip()
        mfr = str(row.get(cmap.get("manufacturer", ""), "")).strip()
        mat = str(row.get(cmap.get("material", ""), "")).strip()
        notes = str(row.get(cmap.get("notes", ""), "")).strip()
        items.append(NormalizedBOMItem(
            item_id=f"BOM-{idx+1:04d}", raw_text=raw,
            standard_text=normalize_text(raw), quantity=_extract_qty(row, cmap),
            description=normalize_text(raw), mpn=mpn, manufacturer=mfr, make=mfr,
            material=normalize_text(mat), notes=notes,
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