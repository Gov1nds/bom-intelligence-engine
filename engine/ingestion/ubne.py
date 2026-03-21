"""
Universal BOM Normalization Engine (UBNE) v1.1

Industrial-grade ingestion layer that handles:
- Multi-sheet Excel files with automatic header row detection
- Flexible column detection (exact + substring + fuzzy + heuristic)
- UOM (unit of measure) extraction from headers
- Advanced quantity parsing (multiplication, reels, tolerances)
- Messy engineering inputs and metadata rows
- Strict output schema with full traceability
- Complete fallback to old parser on failure

Activated by USE_NEW_NORMALIZER flag.
"""

import re
import csv
import logging
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Any
from difflib import SequenceMatcher
from core.schemas import NormalizedBOMItem

logger = logging.getLogger("ubne")

# =========================================================
# FEATURE FLAG
# =========================================================
USE_NEW_NORMALIZER = True

# =========================================================
# COLUMN MAPPING DICTIONARY (extensible)
# =========================================================
COLUMN_MAP: Dict[str, List[str]] = {
    "part_number": [
        "part number", "part no", "part no.", "part#", "part num", "pn", "p/n",
        "mpn", "mfr part number", "manufacturer part number", "component id",
        "item code", "item no", "item number", "sku", "stock keeping unit",
        "product code", "ref des", "reference", "reference designator",
        "catalog number", "cat no", "mfg part number", "part id",
    ],
    "quantity": [
        "qty", "qty.", "quantity", "qnty", "required qty", "order qty",
        "ordered quantity", "qty required", "qty needed", "units", "unit qty",
        "no of units", "count", "pcs", "pieces", "nos", "number", "amount",
        "req qty", "order quantity", "q",
    ],
    "description": [
        "desc", "description", "component", "component description",
        "item description", "details", "product description", "part description",
        "item details", "specification", "specs", "remarks", "notes",
        "part name", "name", "item name", "component name",
    ],
    "manufacturer": [
        "mfg", "mfg.", "manufacturer", "brand", "maker", "vendor", "make",
        "supplier", "oem", "original manufacturer", "manufactured by",
        "mfr", "manufacturer name",
    ],
    "material": [
        "material", "mat", "material type", "raw material", "material spec",
    ],
    "category": [
        "category", "type", "component type", "class", "group", "item group",
        "product category", "classification", "family", "segment",
    ],
}

REQUIRED_FIELDS = {"part_number", "quantity"}
CRITICAL_FIELDS = {"part_number", "description"}

# =========================================================
# HEADER NORMALIZATION + UOM EXTRACTION
# =========================================================

_CLEAN_RE = re.compile(r"[^a-z0-9\s]")
_SPACE_RE = re.compile(r"\s+")
_BRACKET_RE = re.compile(r"\(([^)]*)\)|\[([^\]]*)\]")


def _extract_uom(raw: str) -> Optional[str]:
    """Extract unit of measure from parentheses/brackets in a header."""
    m = _BRACKET_RE.search(str(raw).lower())
    if m:
        uom = (m.group(1) or m.group(2) or "").strip()
        if uom and len(uom) <= 10:
            return uom
    return None


def _normalize_header(raw: str) -> str:
    """Normalize a column header for matching."""
    s = str(raw).lower().strip()
    s = _BRACKET_RE.sub("", s)
    s = _CLEAN_RE.sub(" ", s)
    s = _SPACE_RE.sub(" ", s).strip()
    return s


def _similarity(a: str, b: str) -> float:
    """Token-aware similarity score 0-1."""
    return SequenceMatcher(None, a, b).ratio()


# =========================================================
# COLUMN DETECTION ENGINE
# =========================================================

class ColumnMapper:
    """
    Maps raw column headers to standard schema fields.
    Pipeline: exact match → substring match → fuzzy match → heuristic fallback.
    """

    FUZZY_THRESHOLD = 0.78

    def __init__(self, raw_headers: List[str]):
        self.raw_headers = raw_headers
        self.normalized = [_normalize_header(h) for h in raw_headers]
        self.mapping: Dict[str, Optional[str]] = {}
        self.confidence: Dict[str, float] = {}
        self.uom_map: Dict[str, Optional[str]] = {}
        self.warnings: List[str] = []
        self._unmapped: List[str] = []

    def detect(self) -> Dict[str, Optional[str]]:
        """Run full detection pipeline. Returns {schema_field: raw_header_name}."""
        used_indices = set()

        # Pass 1: Exact match
        for field, synonyms in COLUMN_MAP.items():
            for idx, norm in enumerate(self.normalized):
                if idx in used_indices:
                    continue
                if norm in synonyms:
                    self.mapping[field] = self.raw_headers[idx]
                    self.confidence[field] = 1.0
                    used_indices.add(idx)
                    break

        # Pass 2: Substring match
        for field, synonyms in COLUMN_MAP.items():
            if field in self.mapping:
                continue
            best_idx, best_score = None, 0
            for idx, norm in enumerate(self.normalized):
                if idx in used_indices:
                    continue
                for syn in synonyms:
                    if syn in norm or norm in syn:
                        score = 0.9
                        if score > best_score:
                            best_score = score
                            best_idx = idx
            if best_idx is not None:
                self.mapping[field] = self.raw_headers[best_idx]
                self.confidence[field] = best_score
                used_indices.add(best_idx)

        # Pass 3: Fuzzy match
        for field, synonyms in COLUMN_MAP.items():
            if field in self.mapping:
                continue
            best_idx, best_score = None, 0
            for idx, norm in enumerate(self.normalized):
                if idx in used_indices:
                    continue
                for syn in synonyms:
                    score = _similarity(norm, syn)
                    if score > best_score and score >= self.FUZZY_THRESHOLD:
                        best_score = score
                        best_idx = idx
            if best_idx is not None:
                self.mapping[field] = self.raw_headers[best_idx]
                self.confidence[field] = round(best_score, 3)
                used_indices.add(best_idx)

        # Pass 4: Heuristic fallback
        unmapped_indices = [i for i in range(len(self.raw_headers)) if i not in used_indices]
        self._unmapped = [self.raw_headers[i] for i in unmapped_indices]

        if "part_number" not in self.mapping and unmapped_indices:
            for idx in unmapped_indices:
                self.mapping["part_number"] = self.raw_headers[idx]
                self.confidence["part_number"] = 0.4
                used_indices.add(idx)
                self.warnings.append(f"part_number inferred from column position: '{self.raw_headers[idx]}'")
                break

        for f in REQUIRED_FIELDS:
            if f not in self.mapping:
                self.warnings.append(f"Required field '{f}' not detected in columns")

        if self._unmapped:
            self.warnings.append(f"Unmapped columns: {self._unmapped}")

        # Extract UOMs from raw headers for mapped fields
        for field, raw_col in self.mapping.items():
            if raw_col:
                uom = _extract_uom(raw_col)
                if uom:
                    self.uom_map[field] = uom

        logger.info(f"Column mapping: {self.mapping}")
        logger.info(f"Confidence: {self.confidence}")
        if self.uom_map:
            logger.info(f"Extracted UOMs: {self.uom_map}")
        for w in self.warnings:
            logger.warning(w)

        return self.mapping


# =========================================================
# DATA CLEANING
# =========================================================

_QTY_RE = re.compile(r"([\d]+(?:\.[\d]+)?)")
_QTY_MULT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*[xX×*]\s*(\d+(?:\.\d+)?)")
_QTY_REELS_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:reels?|rolls?|packs?|bags?|boxes?)\s*(?:of|@)\s*(\d+(?:\.\d+)?)",
    re.I,
)
_QTY_PLUSMINUS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*[+±]\s*/?\s*-?\s*\d+")

_ABBREVS = [
    (re.compile(r"\bres\b", re.I), "resistor"),
    (re.compile(r"\bcap\b", re.I), "capacitor"),
    (re.compile(r"\bind\b", re.I), "inductor"),
    (re.compile(r"\bconn\b", re.I), "connector"),
    (re.compile(r"\bled\b", re.I), "LED"),
    (re.compile(r"\bss\b(?=\s)", re.I), "stainless_steel"),
    (re.compile(r"\bal\b(?=\s)", re.I), "aluminum"),
    (re.compile(r"\bpcb\b", re.I), "PCB"),
]

_VALUE_SCALES = [
    (re.compile(r"(\d+(?:\.\d+)?)\s*k\b", re.I), lambda m: str(int(float(m.group(1)) * 1000))),
    (re.compile(r"(\d+(?:\.\d+)?)\s*M\b"), lambda m: str(int(float(m.group(1)) * 1e6))),
]

_BOLT_RE = re.compile(r"\bm(\d+)\s*x\s*(\d+)", re.I)


def clean_text(text: str) -> str:
    """Clean and normalize a text field."""
    if not text or not str(text).strip():
        return ""
    s = str(text).strip()
    s = re.sub(r"\s+", " ", s)
    return s


def normalize_description(text: str) -> str:
    """NLP-light normalization for descriptions."""
    if not text:
        return ""
    s = text.strip().lower()
    s = _BOLT_RE.sub(r"metric_bolt_M\1x\2", s)
    for pat, repl in _ABBREVS:
        s = pat.sub(repl, s, count=1)
    for pat, fn in _VALUE_SCALES:
        s = pat.sub(fn, s)
    s = re.sub(r"\b(\w+)\s+\1\b", r"\1", s)
    return re.sub(r"\s+", " ", s).strip()


def parse_quantity(raw) -> float:
    """
    Parse quantity from various formats. Returns float, defaults to 1.0.
    Handles: "2 x 4" → 8, "5 reels of 1000" → 5000, "10 +/- 1" → 10
    """
    if raw is None:
        return 1.0
    s = str(raw).strip()
    if not s:
        return 1.0

    # Pattern 1: multiplication — "2 x 4", "3*100", "5×20"
    m = _QTY_MULT_RE.search(s)
    if m:
        try:
            result = float(m.group(1)) * float(m.group(2))
            logger.debug(f"Qty parsed '{s}' as multiplication → {result}")
            return max(1.0, result)
        except (ValueError, TypeError):
            pass

    # Pattern 2: reels/packs — "5 reels of 1000", "2 packs of 50"
    m = _QTY_REELS_RE.search(s)
    if m:
        try:
            result = float(m.group(1)) * float(m.group(2))
            logger.debug(f"Qty parsed '{s}' as container × count → {result}")
            return max(1.0, result)
        except (ValueError, TypeError):
            pass

    # Pattern 3: plus/minus — "10 +/- 1" → take base value
    m = _QTY_PLUSMINUS_RE.search(s)
    if m:
        try:
            result = float(m.group(1))
            logger.debug(f"Qty parsed '{s}' as base±tolerance → {result}")
            return max(1.0, result)
        except (ValueError, TypeError):
            pass

    # Default: extract first number
    m = _QTY_RE.search(s)
    if m:
        try:
            return max(1.0, float(m.group(1)))
        except (ValueError, TypeError):
            return 1.0

    return 1.0


def clean_part_number(raw) -> Optional[str]:
    """Clean and normalize a part number."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    return s


def clean_manufacturer(raw) -> Optional[str]:
    """Clean manufacturer name."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s or len(s) < 1:
        return None
    return s.strip()


# =========================================================
# MULTI-SHEET EXCEL PARSER WITH HEADER DETECTION
# =========================================================

_HEADER_SCAN_ROWS = 15


def _score_row_as_header(row_values: List[str]) -> int:
    """Score how many values in a row match known column synonyms."""
    score = 0
    for val in row_values:
        norm = _normalize_header(str(val))
        if not norm or len(norm) < 1:
            continue
        for synonyms in COLUMN_MAP.values():
            if norm in synonyms:
                score += 2
                break
            elif any(syn in norm or norm in syn for syn in synonyms):
                score += 1
                break
    return score


def _detect_header_row(df_raw, sheet_name: str) -> int:
    """
    Scan first N rows to find the actual header row.
    Returns the row index (0-based) to use as pandas header parameter.
    """
    max_rows = min(_HEADER_SCAN_ROWS, len(df_raw))

    # Score row 0 (the default pandas header = column names)
    best_row = 0
    best_score = _score_row_as_header([str(c) for c in df_raw.columns])

    # Score data rows (which would become headers if selected)
    for i in range(max_rows):
        row_vals = [str(v) for v in df_raw.iloc[i].values]
        score = _score_row_as_header(row_vals)
        if score > best_score:
            best_score = score
            best_row = i + 1  # +1 because iloc[0] is the first data row below default header

    if best_row == 0:
        logger.info(f"Sheet '{sheet_name}': header at default row 0 (score={best_score})")
    else:
        logger.info(
            f"Sheet '{sheet_name}': header detected at data row {best_row} "
            f"(score={best_score}), skipping {best_row} metadata rows"
        )

    return best_row


def parse_excel_all_sheets(file_path: str) -> List[Tuple[str, List[str], List[Dict]]]:
    """
    Parse ALL sheets from an Excel file with automatic header row detection.
    Returns: [(sheet_name, headers, rows), ...]
    """
    import pandas as pd

    sheets_data = []

    try:
        xls = pd.ExcelFile(file_path, engine="openpyxl")
    except Exception as e:
        logger.error(f"Failed to open Excel file: {e}")
        raise

    for sheet_name in xls.sheet_names:
        try:
            # First pass: read raw (header=None) to detect true header row
            df_raw = pd.read_excel(
                xls, sheet_name=sheet_name, header=None, engine="openpyxl"
            ).fillna("")

            if df_raw.empty or len(df_raw) < 2:
                logger.info(f"Skipping empty/tiny sheet: '{sheet_name}'")
                continue

            if len(df_raw.columns) < 2:
                logger.info(f"Skipping narrow sheet: '{sheet_name}' ({len(df_raw.columns)} cols)")
                continue

            # Detect header row
            header_row_idx = _detect_header_row(df_raw, sheet_name)

            # Second pass: re-read with correct header
            df = pd.read_excel(
                xls, sheet_name=sheet_name, header=header_row_idx, engine="openpyxl"
            ).fillna("")

            if df.empty:
                continue

            headers = [str(c).strip() for c in df.columns]
            rows = df.to_dict("records")

            # Filter out fully empty rows
            rows = [r for r in rows if any(str(v).strip() for v in r.values())]

            if rows:
                sheets_data.append((sheet_name, headers, rows))
                logger.info(
                    f"Sheet '{sheet_name}': {len(rows)} rows, {len(headers)} columns "
                    f"(header at row {header_row_idx})"
                )

        except Exception as e:
            logger.warning(f"Error reading sheet '{sheet_name}': {e}")
            continue

    return sheets_data


def parse_csv_sheet(file_path: str) -> List[Tuple[str, List[str], List[Dict]]]:
    """Parse a CSV file as a single sheet."""
    with open(file_path, "r", encoding="utf-8-sig") as f:
        sample = f.read(4096)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(f, dialect=dialect)
        headers = reader.fieldnames or []
        rows = [r for r in reader if any(str(v).strip() for v in r.values())]

    return [("Sheet1", headers, rows)] if rows else []


# =========================================================
# ROW NORMALIZATION
# =========================================================

def normalize_row(
    row: Dict[str, Any],
    col_map: Dict[str, Optional[str]],
    sheet_name: str,
    row_index: int,
    warnings: List[str],
    uom_map: Optional[Dict[str, str]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Normalize a single row into the standard schema.
    Returns None if row should be skipped.
    """

    def _get(field: str):
        col = col_map.get(field)
        if col and col in row:
            return row[col]
        return None

    raw_pn = _get("part_number")
    raw_desc = _get("description")
    raw_qty = _get("quantity")
    raw_mfr = _get("manufacturer")
    raw_mat = _get("material")
    raw_cat = _get("category")

    part_number = clean_part_number(raw_pn)
    description = clean_text(raw_desc)
    quantity = parse_quantity(raw_qty)
    manufacturer = clean_manufacturer(raw_mfr)
    material = clean_text(raw_mat)
    category = clean_text(raw_cat) or None

    # Skip if both critical fields missing
    if not part_number and not description:
        warnings.append(
            f"Row {row_index} in '{sheet_name}': both part_number and description missing — skipped"
        )
        return None

    # Normalize description
    normalized_desc = normalize_description(description) if description else ""
    if not normalized_desc and part_number:
        normalized_desc = normalize_description(str(part_number))

    # UOM
    uom = (uom_map or {}).get("quantity", None)

    # group_key: future-ready field for aggregation stages (not used now)
    group_key = normalized_desc or part_number or ""

    return {
        "part_number": part_number,
        "description": description,
        "normalized_description": normalized_desc,
        "quantity": quantity,
        "uom": uom,
        "manufacturer": manufacturer,
        "material": material,
        "category": category,
        "source_sheet": sheet_name,
        "row_index": row_index,
        "group_key": group_key,
    }

# =========================================================
# DEDUPLICATION
# =========================================================

def deduplicate(rows: List[Dict]) -> List[Dict]:
    """
    Non-destructive pass-through.
    Multi-sheet BOMs contain valid duplicates across assemblies/modules.
    Removing them causes data loss. Aggregation belongs to later stages.
    """
    count = len(rows)
    logger.info(f"Dedup check: {count} rows in → {count} rows out (no removal — multi-sheet safe)")
    return rows

# =========================================================
# MAIN UBNE PIPELINE
# =========================================================

def ubne_process_bom(
    file_path: str,
    user_location: str = "",
    target_currency: str = "USD",
    email: str = "",
) -> Tuple[List[NormalizedBOMItem], Dict[str, Any]]:
    """
    Universal BOM Normalization Engine — main entry point.

    Returns:
        (items, diagnostics)
        items: List[NormalizedBOMItem] compatible with downstream pipeline
        diagnostics: dict with warnings, mapping info, sheet info
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    ext = path.suffix.lower()
    diagnostics = {
        "file": path.name,
        "sheets_processed": [],
        "total_raw_rows": 0,
        "total_output_rows": 0,
        "column_mappings": {},
        "column_confidence": {},
        "uom_detected": {},
        "header_rows_detected": {},
        "warnings": [],
        "errors": [],
    }

    # ── Parse all sheets ────────────────────────────────
    try:
        if ext == ".csv":
            sheets = parse_csv_sheet(file_path)
        elif ext in (".xlsx", ".xls"):
            sheets = parse_excel_all_sheets(file_path)
        else:
            raise ValueError(f"Unsupported format: {ext}")
    except Exception as e:
        diagnostics["errors"].append(f"Parse failed: {e}")
        raise

    if not sheets:
        diagnostics["errors"].append("No valid sheets/data found")
        raise ValueError("BOM file contains no processable data")

    all_normalized: List[Dict] = []

    # ── Process each sheet ──────────────────────────────
    for sheet_name, headers, rows in sheets:
        diagnostics["sheets_processed"].append(sheet_name)
        diagnostics["total_raw_rows"] += len(rows)

        # Detect columns
        mapper = ColumnMapper(headers)
        col_map = mapper.detect()

        diagnostics["column_mappings"][sheet_name] = {
            k: v for k, v in col_map.items() if v is not None
        }
        diagnostics["column_confidence"][sheet_name] = mapper.confidence
        if mapper.uom_map:
            diagnostics["uom_detected"][sheet_name] = mapper.uom_map
        diagnostics["warnings"].extend(mapper.warnings)

        # Normalize each row (pass UOM map)
        for idx, row in enumerate(rows):
            result = normalize_row(
                row, col_map, sheet_name, idx + 1,
                diagnostics["warnings"], uom_map=mapper.uom_map,
            )
            if result is not None:
                all_normalized.append(result)

# ── Deduplicate (non-destructive) ───────────────────
    pre_count = len(all_normalized)
    all_normalized = deduplicate(all_normalized)
    post_count = len(all_normalized)
    diagnostics["total_output_rows"] = post_count
    diagnostics["dedup_before"] = pre_count
    diagnostics["dedup_after"] = post_count
    if pre_count != post_count:
        logger.warning(f"Dedup removed {pre_count - post_count} rows — investigate if unexpected")

    # ── Convert to NormalizedBOMItem ────────────────────
    items: List[NormalizedBOMItem] = []
    for idx, row in enumerate(all_normalized):
        items.append(
            NormalizedBOMItem(
                item_id=f"BOM-{idx + 1:04d}",
                raw_text=row.get("description", "") or row.get("part_number", ""),
                standard_text=row.get("normalized_description", ""),
                quantity=float(row.get("quantity", 1)),
                description=row.get("normalized_description", ""),
                part_number=row.get("part_number", "") or "",
                mpn=row.get("part_number", "") or "",
                manufacturer=row.get("manufacturer", "") or "",
                make=row.get("manufacturer", "") or "",
                material=row.get("material", "") or "",
                notes="",
                raw_row={str(k): str(v) for k, v in row.items()},
            )
        )

    logger.info(
        f"UBNE complete: {len(sheets)} sheets, {diagnostics['total_raw_rows']} raw rows "
        f"→ {len(items)} normalized items"
    )

    return items, diagnostics