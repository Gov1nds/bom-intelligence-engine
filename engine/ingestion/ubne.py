"""
Universal BOM Normalization Engine (UBNE) v1.4
"""

import re
import csv
import logging
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Any
from difflib import SequenceMatcher
from core.schemas import NormalizedBOMItem

logger = logging.getLogger("ubne")

USE_NEW_NORMALIZER = True

# Import normalization functions from normalizer module
try:
    from engine.ingestion.normalizer import normalize_mpn as _normalize_mpn
    from engine.ingestion.normalizer import normalize_manufacturer as _normalize_mfr
    from engine.ingestion.normalizer import normalize_unit as _normalize_unit
    from engine.ingestion.normalizer import normalize_material_name as _normalize_material
except ImportError:
    # Fallback if circular import
    def _normalize_mpn(v):
        return re.sub(r"\s+", "", str(v).strip().upper()) if v else ""
    def _normalize_mfr(v):
        return str(v).strip().lower() if v else ""
    def _normalize_unit(v):
        return str(v).strip().lower() if v else "each"
    def _normalize_material(v):
        return re.sub(r"\s+", "_", str(v).strip().lower()) if v else ""

COLUMN_MAP: Dict[str, List[str]] = {
    "part_number": [
        "part number", "part no", "part no.", "part#", "part num", "pn", "p/n",
        "mpn", "mfr part number", "manufacturer part number", "component id",
        "item code", "item no", "item number", "sku", "stock keeping unit",
        "product code", "ref des", "reference", "reference designator",
        "catalog number", "cat no", "mfg part number", "part id",
        "drawing number", "dwg no", "dwg", "model number", "model no",
        "article number", "article no", "order code", "stock code",
    ],
    "quantity": [
        "qty", "qty.", "quantity", "qnty", "required qty", "order qty",
        "ordered quantity", "qty required", "qty needed", "units", "unit qty",
        "no of units", "count", "pcs", "pieces", "nos", "number", "amount",
        "req qty", "order quantity", "q", "numbers",
    ],
    "description": [
        "desc", "description", "component", "component description",
        "item description", "details", "product description", "part description",
        "item details", "specification", "specs", "remarks", "notes",
        "part name", "name", "item name", "component name", "product name",
        "material description", "material name", "title",
    ],
    "manufacturer": [
        "mfg", "mfg.", "manufacturer", "brand", "maker", "make",
        "oem", "original manufacturer", "manufactured by",
        "mfr", "manufacturer name",
    ],
    "supplier": [
        "supplier", "vendor", "source", "distributor", "reseller",
        "supplier name", "vendor name", "sold by",
    ],
    "material": [
        "material", "mat", "material type", "raw material", "material spec",
        "material grade", "alloy", "substrate",
    ],
    "category": [
        "category", "type", "component type", "class", "group", "item group",
        "product category", "classification", "family", "segment",
    ],
}

_DESC_PRIORITY = [
    "item name", "part name", "component name", "product name",
    "name", "item description", "description", "component",
    "component description", "part description",
]

_DESC_BLOCKLIST = {
    "sl no", "sl no.", "s no", "s no.", "sr no", "sr no.", "serial",
    "serial number", "sno", "no", "row",
    "category", "type", "component type", "class", "group",
    "item group", "product category", "classification", "family", "segment",
}

REQUIRED_FIELDS = {"part_number", "quantity"}

_CLEAN_RE = re.compile(r"[^a-z0-9\s]")
_SPACE_RE = re.compile(r"\s+")
_BRACKET_RE = re.compile(r"\(([^)]*)\)|\[([^\]]*)\]")
_SEP_RE = re.compile(r"[_\-/]")


def _extract_uom(raw: str) -> Optional[str]:
    m = _BRACKET_RE.search(str(raw).lower())
    if m:
        uom = (m.group(1) or m.group(2) or "").strip()
        if uom and len(uom) <= 10:
            return uom
    return None


def _normalize_header(raw: str) -> str:
    s = str(raw).lower().strip()
    s = _BRACKET_RE.sub("", s)
    s = _SEP_RE.sub(" ", s)
    s = _CLEAN_RE.sub(" ", s)
    s = _SPACE_RE.sub(" ", s).strip()
    return s


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def _is_sequential(rows: List[Dict], col: str, n: int = 20) -> bool:
    vals: List[float] = []
    for r in rows[:n]:
        v = str(r.get(col, "")).strip()
        if v:
            try:
                vals.append(float(v))
            except ValueError:
                return False
    if len(vals) < 3:
        return False
    return all(abs((vals[i + 1] - vals[i]) - 1) < 0.01 for i in range(len(vals) - 1))


def _is_mostly_numeric(rows: List[Dict], col: str, n: int = 20) -> bool:
    num = tot = 0
    for r in rows[:n]:
        v = str(r.get(col, "")).strip()
        if v:
            tot += 1
            try:
                float(v)
                num += 1
            except ValueError:
                pass
    return tot > 0 and num / tot > 0.8


def _avg_text_len(rows: List[Dict], col: str, n: int = 20) -> float:
    tl = c = 0
    for r in rows[:n]:
        v = str(r.get(col, "")).strip()
        if v:
            tl += len(v)
            c += 1
    return tl / max(c, 1)


class ColumnMapper:
    FUZZY_THRESHOLD = 0.72

    def __init__(
        self,
        raw_headers: List[str],
        sample_rows: Optional[List[Dict]] = None,
        hints: Optional[Dict[str, str]] = None,
    ):
        self.raw_headers = raw_headers
        self.normalized = [_normalize_header(h) for h in raw_headers]
        self.sample_rows = sample_rows or []
        self.hints = hints or {}
        self.mapping: Dict[str, Optional[str]] = {}
        self.confidence: Dict[str, float] = {}
        self.uom_map: Dict[str, Optional[str]] = {}
        self.warnings: List[str] = []
        self.rejected: Dict[str, List[str]] = {}

    def detect(self) -> Dict[str, Optional[str]]:
        used: set = set()

        # Pass 0: Cross-sheet hints
        for field, hint in self.hints.items():
            for idx, raw in enumerate(self.raw_headers):
                if idx in used:
                    continue
                if _normalize_header(raw) == _normalize_header(hint):
                    self.mapping[field] = raw
                    self.confidence[field] = 0.85
                    used.add(idx)
                    break

        # Pass 1: Exact
        for field, syns in COLUMN_MAP.items():
            if field in self.mapping:
                continue
            for idx, norm in enumerate(self.normalized):
                if idx in used:
                    continue
                if norm in syns:
                    self.mapping[field] = self.raw_headers[idx]
                    self.confidence[field] = 1.0
                    used.add(idx)
                    break

        # Pass 1.5: Description priority
        if "description" not in self.mapping:
            for idx, norm in enumerate(self.normalized):
                if idx in used or norm in _DESC_BLOCKLIST:
                    continue
                for psyn in _DESC_PRIORITY:
                    if norm == psyn or psyn in norm or norm in psyn:
                        self.mapping["description"] = self.raw_headers[idx]
                        self.confidence["description"] = 0.95
                        used.add(idx)
                        break
                if "description" in self.mapping:
                    break

        # Pass 2: Partial
        for field, syns in COLUMN_MAP.items():
            if field in self.mapping:
                continue
            best_idx: Optional[int] = None
            best_sc: float = 0.0
            for idx, norm in enumerate(self.normalized):
                if idx in used:
                    continue
                if field == "description" and norm in _DESC_BLOCKLIST:
                    continue
                for syn in syns:
                    if syn in norm or norm in syn:
                        if 0.9 > best_sc:
                            best_sc = 0.9
                            best_idx = idx
            if best_idx is not None and best_sc > 0:
                self.mapping[field] = self.raw_headers[best_idx]
                self.confidence[field] = best_sc
                used.add(best_idx)

        # Pass 3: Fuzzy
        for field, syns in COLUMN_MAP.items():
            if field in self.mapping:
                continue
            best_idx2: Optional[int] = None
            best_sc2: float = 0.0
            for idx, norm in enumerate(self.normalized):
                if idx in used:
                    continue
                if field == "description" and norm in _DESC_BLOCKLIST:
                    continue
                for syn in syns:
                    sc = _similarity(norm, syn)
                    if sc > best_sc2 and sc >= self.FUZZY_THRESHOLD:
                        best_sc2 = sc
                        best_idx2 = idx
            if best_idx2 is not None:
                self.mapping[field] = self.raw_headers[best_idx2]
                self.confidence[field] = round(best_sc2, 3)
                used.add(best_idx2)

        # Pass 4: Content-based fallbacks
        unmapped = [i for i in range(len(self.raw_headers)) if i not in used]

        # 4a: Description
        if "description" not in self.mapping and self.sample_rows:
            bi: Optional[int] = None
            bl: float = 0.0
            for idx in unmapped:
                col = self.raw_headers[idx]
                if self.normalized[idx] in _DESC_BLOCKLIST:
                    self.rejected.setdefault("description", []).append(col)
                    continue
                if _is_sequential(self.sample_rows, col) or _is_mostly_numeric(self.sample_rows, col):
                    self.rejected.setdefault("description", []).append(col)
                    continue
                vals = [str(r.get(col, "")).strip() for r in self.sample_rows[:20] if str(r.get(col, "")).strip()]
                if len(vals) >= 3:
                    uniqueness = len(set(vals)) / len(vals)
                    if uniqueness < 0.15:
                        self.rejected.setdefault("description", []).append(f"{col}(low-uniq)")
                        continue
                al = _avg_text_len(self.sample_rows, col)
                if al > bl:
                    bl = al
                    bi = idx
            if bi is not None and bl > 3:
                self.mapping["description"] = self.raw_headers[bi]
                self.confidence["description"] = 0.4
                used.add(bi)
                unmapped = [i for i in unmapped if i != bi]
                self.warnings.append(f"description fallback: '{self.raw_headers[bi]}'")

        # 4b: Quantity
        if "quantity" not in self.mapping and self.sample_rows:
            unmapped = [i for i in range(len(self.raw_headers)) if i not in used]
            q_bi: Optional[int] = None
            q_br: float = 0.0
            for idx in unmapped:
                col = self.raw_headers[idx]
                if _is_sequential(self.sample_rows, col):
                    self.rejected.setdefault("quantity", []).append(col)
                    continue
                nc = tot = 0
                for r in self.sample_rows[:20]:
                    v = str(r.get(col, "")).strip()
                    if v:
                        tot += 1
                        try:
                            float(re.sub(r"[^\d.]", "", v))
                            nc += 1
                        except ValueError:
                            pass
                ratio = nc / max(tot, 1)
                if ratio > q_br:
                    q_br = ratio
                    q_bi = idx
            if q_bi is not None and q_br > 0.5:
                self.mapping["quantity"] = self.raw_headers[q_bi]
                self.confidence["quantity"] = 0.4
                used.add(q_bi)
                self.warnings.append(f"quantity fallback: '{self.raw_headers[q_bi]}'")

        # 4c: Part number
        if "part_number" not in self.mapping:
            unmapped = [i for i in range(len(self.raw_headers)) if i not in used]
            for idx in unmapped:
                col = self.raw_headers[idx]
                if _is_sequential(self.sample_rows, col):
                    self.rejected.setdefault("part_number", []).append(col)
                    continue
                self.mapping["part_number"] = col
                self.confidence["part_number"] = 0.3
                used.add(idx)
                self.warnings.append(f"part_number fallback: '{col}'")
                break

        # 4d: Manufacturer
        if "manufacturer" not in self.mapping and self.sample_rows:
            unmapped = [i for i in range(len(self.raw_headers)) if i not in used]
            m_bi: Optional[int] = None
            m_bs: float = 0.0
            for idx in unmapped:
                col = self.raw_headers[idx]
                vals = [str(r.get(col, "")).strip() for r in self.sample_rows[:30] if str(r.get(col, "")).strip()]
                if len(vals) < 3:
                    continue
                ur = len(set(vals)) / len(vals)
                if 0.05 < ur < 0.7 and ur > m_bs:
                    m_bs = ur
                    m_bi = idx
            if m_bi is not None:
                self.mapping["manufacturer"] = self.raw_headers[m_bi]
                self.confidence["manufacturer"] = 0.35
                used.add(m_bi)

        # Pass 5: Validation
        pn_col = self.mapping.get("part_number")
        if pn_col and self.sample_rows and _is_sequential(self.sample_rows, pn_col):
            logger.warning(f"Validation: part_number '{pn_col}' is serial — removing")
            self.rejected.setdefault("part_number", []).append(pn_col)
            del self.mapping["part_number"]
            self.confidence.pop("part_number", None)

        dc_col = self.mapping.get("description")
        if dc_col and _normalize_header(dc_col) in _DESC_BLOCKLIST:
            logger.warning(f"Validation: description '{dc_col}' blocklisted — removing")
            self.rejected.setdefault("description", []).append(dc_col)
            del self.mapping["description"]
            self.confidence.pop("description", None)

        for f in REQUIRED_FIELDS:
            if f not in self.mapping:
                self.warnings.append(f"Required '{f}' not detected")

        for field, raw_col in self.mapping.items():
            if raw_col:
                uom = _extract_uom(raw_col)
                if uom:
                    self.uom_map[field] = uom

        logger.info(f"Mapping: {self.mapping}")
        logger.info(f"Confidence: {self.confidence}")
        if self.rejected:
            logger.info(f"Rejected: {self.rejected}")
        for w in self.warnings:
            logger.warning(w)

        return self.mapping


# ── Quantity parsing (unchanged from v1.3) ──

_QTY_RE = re.compile(r"([\d]+(?:\.[\d]+)?)")
_QTY_MULT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*[xX×*]\s*(\d+(?:\.\d+)?)")
_QTY_REELS_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:reels?|rolls?|packs?|bags?|boxes?)\s*(?:of|@)\s*(\d+(?:\.\d+)?)", re.I,
)
_QTY_PLUSMINUS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*[+±]\s*/?\s*-?\s*\d+")
_ALPHA_NUMERIC_RE = re.compile(r"[a-zA-Z].*\d|\d.*[a-zA-Z]")
_QTY_SANITY_MAX = 10000


def _qty_safe(v: float, orig: str = "") -> float:
    if v <= 0:
        return 1.0
    if v > _QTY_SANITY_MAX:
        logger.warning(f"Qty {v} from '{orig}' capped")
        return 1.0
    return v


def parse_quantity(raw: Any) -> float:
    if raw is None:
        return 1.0
    s = str(raw).strip()
    if not s:
        return 1.0
    if _ALPHA_NUMERIC_RE.search(s):
        return 1.0
    for pat, grp in [
        (_QTY_MULT_RE, lambda m: float(m.group(1)) * float(m.group(2))),
        (_QTY_REELS_RE, lambda m: float(m.group(1)) * float(m.group(2))),
        (_QTY_PLUSMINUS_RE, lambda m: float(m.group(1))),
    ]:
        m = pat.search(s)
        if m:
            try:
                return _qty_safe(grp(m), s)
            except (ValueError, TypeError):
                pass
    m = _QTY_RE.search(s)
    if m:
        try:
            return _qty_safe(float(m.group(1)), s)
        except (ValueError, TypeError):
            pass
    return 1.0


# ── Text cleaning ──

def clean_part_number(raw: Any) -> Optional[str]:
    if raw is None:
        return None
    s = str(raw).strip()
    return s if s else None


def clean_manufacturer(raw: Any) -> Optional[str]:
    if raw is None:
        return None
    s = str(raw).strip()
    return s if s else None


def clean_text(text: Any) -> str:
    if not text or not str(text).strip():
        return ""
    return re.sub(r"\s+", " ", str(text).strip())


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


def normalize_description(text: str) -> str:
    if not text:
        return ""
    s = text.strip().lower()
    s = _BOLT_RE.sub(r"metric_bolt_M\1x\2", s)
    for p, r in _ABBREVS:
        s = p.sub(r, s, count=1)
    for p, fn in _VALUE_SCALES:
        s = p.sub(fn, s)
    s = re.sub(r"\b(\w+)\s+\1\b", r"\1", s)
    return re.sub(r"\s+", " ", s).strip()


# ── Forward fill (hierarchical + common merged columns) ──

_FF_ALLOWED = {"category", "assembly", "section", "group", "sub assembly", "module"}
# Columns that are commonly merged in industrial BOMs (carry-down for blanks)
_FF_MERGE_ALLOWED = {"manufacturer", "material", "supplier", "vendor", "brand", "oem",
                     "mfg", "make", "source", "material type", "raw material"}


def forward_fill_rows(rows: List[Dict], sheet_name: str = "") -> List[Dict]:
    if not rows:
        return rows
    filled: List[Dict] = []
    last: Dict[str, Any] = {}
    for row in rows:
        nr: Dict[str, Any] = {}
        for k, v in row.items():
            nk = str(k).strip().lower().replace("_", " ").replace("-", " ")
            hier = any(a in nk for a in _FF_ALLOWED)
            merge = any(a in nk for a in _FF_MERGE_ALLOWED)
            if v is not None and str(v).strip():
                if hier or merge:
                    last[k] = v
                nr[k] = v
            else:
                nr[k] = last.get(k, "") if (hier or merge) else ""
        filled.append(nr)
    logger.info(f"Forward fill '{sheet_name}': {len(filled)} rows (hierarchical + merged)")
    return filled


# ── Header detection (Issue 1 fix) ──

_HEADER_SCAN = 15
_HEADER_MIN = 3


def _score_header(vals: List[str]) -> int:
    sc = 0
    for v in vals:
        n = _normalize_header(str(v))
        if not n:
            continue
        for syns in COLUMN_MAP.values():
            if n in syns:
                sc += 2
                break
            elif any(s in n or n in s for s in syns):
                sc += 1
                break
    return sc


def _detect_header_row(df_raw: Any, sheet_name: str) -> int:
    nr = len(df_raw)
    if nr < 1:
        return 0
    best_row = 0
    best_sc = _score_header([str(v) for v in df_raw.iloc[0].values])
    for i in range(1, min(_HEADER_SCAN, nr)):
        sc = _score_header([str(v) for v in df_raw.iloc[i].values])
        if sc > best_sc + 1:
            best_sc = sc
            best_row = i
    if best_row > 0 and best_sc < _HEADER_MIN:
        best_row = 0
    logger.info(f"Sheet '{sheet_name}': header@row {best_row} (score={best_sc})")
    return best_row


# ── Excel / CSV parsers ──

def parse_excel_all_sheets(file_path: str) -> List[Tuple[str, List[str], List[Dict]]]:
    import pandas as pd
    out: List[Tuple[str, List[str], List[Dict]]] = []
    try:
        xls = pd.ExcelFile(file_path, engine="openpyxl")
    except Exception as e:
        logger.error(f"Open failed: {e}")
        raise
    for sn in xls.sheet_names:
        logger.info(f"Sheet: '{sn}'")
        try:
            df_raw = pd.read_excel(xls, sheet_name=sn, header=None, engine="openpyxl").fillna("")
            if df_raw.empty:
                continue
            hr = _detect_header_row(df_raw, sn)
            df = pd.read_excel(xls, sheet_name=sn, header=hr, engine="openpyxl").fillna("")
            if df.empty:
                continue
            heads = [str(c).strip() for c in df.columns]
            rows = [r for r in df.to_dict("records") if any(str(v).strip() for v in r.values())]
            if rows:
                out.append((sn, heads, rows))
                logger.info(f"Sheet '{sn}': {len(rows)} rows, header@{hr}")
        except Exception as e:
            logger.error(f"Sheet '{sn}' error: {e}")
    return out


def parse_csv_sheet(fp: str) -> List[Tuple[str, List[str], List[Dict]]]:
    with open(fp, "r", encoding="utf-8-sig") as f:
        sample = f.read(4096)
        f.seek(0)
        try:
            dia = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        except csv.Error:
            dia = csv.excel
        rdr = csv.DictReader(f, dialect=dia)
        heads = rdr.fieldnames or []
        rows = [r for r in rdr if any(str(v).strip() for v in r.values())]
    return [("Sheet1", heads, rows)] if rows else []


# ── Row normalization (Issues 2, 7, 9) ──

def normalize_row(
    row: Dict[str, Any],
    col_map: Dict[str, Optional[str]],
    sheet_name: str,
    row_index: int,
    warnings: List[str],
    uom_map: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:

    def _get(f: str) -> Any:
        c = col_map.get(f)
        return row[c] if c and c in row else None

    pn = clean_part_number(_get("part_number"))
    raw_desc = clean_text(_get("description"))
    qty = parse_quantity(_get("quantity"))
    mfr = clean_manufacturer(_get("manufacturer"))
    supplier = clean_manufacturer(_get("supplier"))  # Separate supplier field
    mat = clean_text(_get("material"))
    cat = clean_text(_get("category")) or None
    uom = (uom_map or {}).get("quantity")

    if not pn and not raw_desc:
        best = ""
        for k, v in row.items():
            vs = str(v).strip()
            nk = _normalize_header(k)
            if not vs or nk in _DESC_BLOCKLIST:
                continue
            try:
                float(vs)
                continue
            except ValueError:
                pass
            if len(vs) > len(best):
                best = vs
        if best and len(best) > 2:
            raw_desc = best
        else:
            vals = [str(v).strip() for v in row.values() if v is not None and str(v).strip()]
            fb = " | ".join(vals) if vals else f"UNMAPPED_{sheet_name}_{row_index}"
            try:
                nd = normalize_description(fb)
            except Exception:
                nd = fb
            sq = qty if qty and qty > 0 else 1.0
            if sq > _QTY_SANITY_MAX:
                sq = 1.0
            return {
                "part_number": str(pn or ""),
                "raw_description": fb,
                "description": fb,
                "normalized_description": nd,
                "quantity": sq,
                "uom": str(uom or ""),
                "manufacturer": str(mfr or ""),
                "material": str(mat or ""),
                "category": str(cat or ""),
                "source_sheet": sheet_name,
                "row_index": row_index,
                "group_key": f"{str(pn or '')}_{fb}".strip("_").lower(),
            }

    nd = normalize_description(raw_desc) if raw_desc else ""
    if not nd and pn:
        nd = normalize_description(str(pn))
    if not qty or qty <= 0:
        qty = 1.0
    if qty > _QTY_SANITY_MAX:
        qty = 1.0

    return {
        "part_number": pn,
        "raw_description": raw_desc,
        "description": raw_desc or nd,
        "normalized_description": nd,
        "quantity": qty,
        "uom": uom,
        "manufacturer": mfr,
        "supplier": supplier,
        "material": mat,
        "category": cat,
        "source_sheet": sheet_name,
        "row_index": row_index,
        "group_key": f"{pn or ''}_{nd or ''}".strip("_").lower(),
    }


def deduplicate(rows: List[Dict]) -> List[Dict]:
    logger.info(f"Dedup: {len(rows)} → {len(rows)} (pass-through)")
    return rows


# ── Main pipeline ──

def ubne_process_bom(
    file_path: str,
    user_location: str = "",
    target_currency: str = "USD",
    email: str = "",
) -> Tuple[List[NormalizedBOMItem], Dict[str, Any]]:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Not found: {file_path}")

    ext = path.suffix.lower()
    diag: Dict[str, Any] = {
        "file": path.name,
        "sheets_processed": [],
        "total_raw_rows": 0,
        "total_output_rows": 0,
        "column_mappings": {},
        "column_confidence": {},
        "column_rejected": {},
        "uom_detected": {},
        "fallback_count": 0,
        "warnings": [],
        "errors": [],
    }

    try:
        if ext == ".csv":
            sheets = parse_csv_sheet(file_path)
        elif ext in (".xlsx", ".xls"):
            sheets = parse_excel_all_sheets(file_path)
        else:
            raise ValueError(f"Unsupported: {ext}")
    except Exception as e:
        diag["errors"].append(str(e))
        raise

    if not sheets:
        raise ValueError("No data")

    all_norm: List[Dict] = []
    hints: Dict[str, str] = {}

    for sn, heads, rows in sheets:
        diag["sheets_processed"].append(sn)
        diag["total_raw_rows"] += len(rows)
        logger.info(f"Sheet '{sn}': {len(rows)} rows, cols={heads}")

        mapper = ColumnMapper(heads, sample_rows=rows[:20], hints=hints)
        cm = mapper.detect()

        for f, c in cm.items():
            if c and mapper.confidence.get(f, 0) >= 0.85:
                hints[f] = c

        diag["column_mappings"][sn] = {k: v for k, v in cm.items() if v}
        diag["column_confidence"][sn] = mapper.confidence
        if mapper.rejected:
            diag["column_rejected"][sn] = mapper.rejected
        if mapper.uom_map:
            diag["uom_detected"][sn] = mapper.uom_map
        diag["warnings"].extend(mapper.warnings)

        rows = forward_fill_rows(rows, sheet_name=sn)
        si: List[Dict] = []
        for idx, r in enumerate(rows):
            si.append(normalize_row(r, cm, sn, idx + 1, diag["warnings"], uom_map=mapper.uom_map))

        fb = sum(1 for x in si if " | " in x.get("description", ""))
        diag["fallback_count"] += fb
        all_norm.extend(si)

    pre = len(all_norm)
    all_norm = deduplicate(all_norm)
    diag["total_output_rows"] = len(all_norm)
    diag["dedup_before"] = pre
    diag["dedup_after"] = len(all_norm)

    items: List[NormalizedBOMItem] = []
    for idx, r in enumerate(all_norm):
        rd = r.get("raw_description", "") or r.get("description", "")
        nd = r.get("normalized_description", "")
        ss = r.get("source_sheet", "")
        final_desc = rd or nd
        final_pn = r.get("part_number", "") or ""

        if not final_desc and not final_pn:
            diag["warnings"].append(f"BOM-{idx + 1:04d}: empty desc + pn")
            logger.warning(f"BOM-{idx + 1:04d}: empty description and part_number")

        raw_row_out = {str(k): str(v) for k, v in r.items()}
        raw_row_out["source_sheet"] = ss

        items.append(NormalizedBOMItem(
            item_id=f"BOM-{idx + 1:04d}",
            raw_text=rd or final_pn,
            standard_text=nd,
            quantity=max(1, round(float(r.get("quantity", 1)), 2)),
            description=final_desc,
            part_number=final_pn,
            mpn=_normalize_mpn(final_pn),
            manufacturer=_normalize_mfr(r.get("manufacturer", "") or ""),
            supplier_name=_normalize_mfr(r.get("supplier", "") or ""),
            make=_normalize_mfr(r.get("manufacturer", "") or ""),
            material=_normalize_material(r.get("material", "") or "") or (r.get("material", "") or ""),
            unit=_normalize_unit(r.get("uom", "") or ""),
            notes=f"[Sheet: {ss}]" if ss else "",
            source_sheet=ss,
            source_row=idx + 1,
            raw_row=raw_row_out,
        ))

    warn_count = len([i for i in items if not i.description and not i.part_number])
    default_qty = len([i for i in items if i.quantity == 1])
    diag["empty_row_warnings"] = warn_count
    diag["default_quantity_rows"] = default_qty

    logger.info(
        f"UBNE v1.4: {len(sheets)} sheets, {pre} raw -> {len(items)} items, "
        f"{diag['fallback_count']} fallbacks, {warn_count} warnings, {default_qty} default-qty"
    )
    return items, diag