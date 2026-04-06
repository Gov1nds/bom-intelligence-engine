"""BOM file ingestion — CSV, XLSX, TSV parsing and row normalization."""
import csv
import io
import re
import logging
from pathlib import Path
from dataclasses import dataclass, field

logger = logging.getLogger("ingestion")

HEADER_PATTERNS = {
    "description": r"(?i)(description|desc|item[\s_]*name|part[\s_]*name|component|name)",
    "quantity": r"(?i)(qty|quantity|count|amount|nos)",
    "part_number": r"(?i)(part[\s_]*no|part[\s_]*number|p/?n|item[\s_]*no|item[\s_]*number)",
    "mpn": r"(?i)(mpn|mfr[\s_]*part|manufacturer[\s_]*part)",
    "manufacturer": r"(?i)(manufacturer|mfr|brand|make|oem)",
    "material": r"(?i)(material|mat|raw[\s_]*material)",
    "unit": r"(?i)(unit|uom|measure)",
    "notes": r"(?i)(notes|remarks|comment|remark)",
    "supplier": r"(?i)(supplier|vendor|source)",
}


@dataclass
class RawRow:
    row_index: int = 0
    description: str = ""
    quantity: float = 1.0
    part_number: str = ""
    mpn: str = ""
    manufacturer: str = ""
    material: str = ""
    unit: str = "each"
    notes: str = ""
    supplier: str = ""
    raw_fields: dict = field(default_factory=dict)


def _parse_quantity(val: str) -> float:
    if not val:
        return 1.0
    cleaned = re.sub(r"[^\d.]", "", str(val).strip())
    try:
        return max(float(cleaned), 0.001)
    except (ValueError, TypeError):
        return 1.0


def _detect_headers(row: list[str]) -> dict[str, int] | None:
    mapping = {}
    for col_idx, cell in enumerate(row):
        cell_str = str(cell).strip()
        if not cell_str:
            continue
        for field_name, pattern in HEADER_PATTERNS.items():
            if re.search(pattern, cell_str):
                if field_name not in mapping:
                    mapping[field_name] = col_idx
                break
    return mapping if "description" in mapping or len(mapping) >= 2 else None


def _read_csv(file_path: str) -> list[list[str]]:
    path = Path(file_path)
    text = path.read_text(errors="replace")
    delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
    if delimiter == "," and text.count("\t") > text.count(","):
        delimiter = "\t"
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    return [row for row in reader]


def _read_xlsx(file_path: str) -> list[list[str]]:
    from openpyxl import load_workbook
    wb = load_workbook(file_path, read_only=True, data_only=True)
    rows = []
    for sheet in wb.sheetnames:
        ws = wb[sheet]
        for row in ws.iter_rows(values_only=True):
            rows.append([str(c) if c is not None else "" for c in row])
    wb.close()
    return rows


def ingest_file(file_path: str) -> list[RawRow]:
    ext = Path(file_path).suffix.lower()
    if ext in (".xlsx", ".xls"):
        all_rows = _read_xlsx(file_path)
    elif ext in (".csv", ".tsv", ".txt"):
        all_rows = _read_csv(file_path)
    else:
        all_rows = _read_csv(file_path)

    if not all_rows:
        return []

    # Find header row
    header_map = None
    data_start = 0
    for i, row in enumerate(all_rows[:10]):
        detected = _detect_headers(row)
        if detected:
            header_map = detected
            data_start = i + 1
            break

    if not header_map:
        # Fallback: treat first column as description
        header_map = {"description": 0}
        if len(all_rows[0]) > 1:
            header_map["quantity"] = 1
        data_start = 0

    results = []
    for idx, row in enumerate(all_rows[data_start:], start=data_start):
        if not any(str(c).strip() for c in row):
            continue

        raw = RawRow(row_index=idx)
        raw.raw_fields = {str(i): str(c) for i, c in enumerate(row)}

        desc_idx = header_map.get("description")
        if desc_idx is not None and desc_idx < len(row):
            raw.description = str(row[desc_idx]).strip()

        qty_idx = header_map.get("quantity")
        if qty_idx is not None and qty_idx < len(row):
            raw.quantity = _parse_quantity(str(row[qty_idx]))

        for fld in ("part_number", "mpn", "manufacturer", "material", "unit", "notes", "supplier"):
            fidx = header_map.get(fld)
            if fidx is not None and fidx < len(row):
                setattr(raw, fld, str(row[fidx]).strip())

        if raw.description or raw.part_number or raw.mpn:
            results.append(raw)

    logger.info(f"Ingested {len(results)} rows from {file_path}")
    return results
