"""Specification extraction from component text.

extract_specs: legacy regex-based (retained for /api/analyze-bom).
extract_specs_from_tokens: new token-aware extraction for decomposed pipeline.
"""
import re
import logging
from typing import Any

logger = logging.getLogger("spec_extractor")

DIMENSION_PATTERN = re.compile(
    r"(\d+(?:\.\d+)?)\s*[xX×]\s*(\d+(?:\.\d+)?)(?:\s*[xX×]\s*(\d+(?:\.\d+)?))?\s*(mm|cm|in|inch|m)?"
)
DIAMETER_PATTERN = re.compile(r"(?:dia|diameter|ø|Ø)\s*[:=]?\s*(\d+(?:\.\d+)?)\s*(mm|in|cm)?", re.I)
THICKNESS_PATTERN = re.compile(r"(?:thick|thickness|thk|t)\s*[:=]?\s*(\d+(?:\.\d+)?)\s*(mm|in|cm)?", re.I)
LENGTH_PATTERN = re.compile(r"(?:length|len|l)\s*[:=]?\s*(\d+(?:\.\d+)?)\s*(mm|in|cm|m|ft)?", re.I)
WEIGHT_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*(kg|g|lb|oz)", re.I)
VOLTAGE_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*[Vv](?:olt)?(?:s)?(?:\s|$|,)")
CURRENT_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*[Aa](?:mp)?(?:s)?(?:\s|$|,)")
RESISTANCE_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*(?:k|M|G)?[Ωo](?:hm)?", re.I)
CAPACITANCE_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*(?:p|n|µ|u|m)?[Ff](?:arad)?", re.I)
THREAD_PATTERN = re.compile(r"(M\d+(?:\.\d+)?(?:\s*[xX]\s*\d+(?:\.\d+)?)?)", re.I)
GRADE_PATTERN = re.compile(r"(?:grade|class|type)\s*[:=]?\s*(\S+)", re.I)
FINISH_PATTERN = re.compile(r"(?:finish|surface)\s*[:=]?\s*([A-Za-z][A-Za-z0-9\s]{2,20})", re.I)
TOLERANCE_PATTERN = re.compile(r"([±+\-]\s*\d+(?:\.\d+)?\s*(?:mm|in|thou|µm)?)", re.I)
TEMP_PATTERN = re.compile(r"(-?\d+(?:\.\d+)?)\s*°?\s*[CF]", re.I)


def extract_specs(text: str, category: str = "auto") -> dict:
    """Legacy regex-based spec extraction. Retained for /api/analyze-bom."""
    if not text:
        return {}
    specs: dict[str, Any] = {}

    m = DIMENSION_PATTERN.search(text)
    if m:
        dims: dict[str, Any] = {"width": float(m.group(1)), "height": float(m.group(2))}
        if m.group(3):
            dims["depth"] = float(m.group(3))
        if m.group(4):
            dims["unit"] = m.group(4)
        specs["dimensions"] = dims

    for name, pat in [("diameter", DIAMETER_PATTERN), ("thickness", THICKNESS_PATTERN), ("length", LENGTH_PATTERN)]:
        m = pat.search(text)
        if m:
            specs[name] = {"value": float(m.group(1)), "unit": m.group(2) or "mm"}

    m = WEIGHT_PATTERN.search(text)
    if m:
        specs["weight"] = {"value": float(m.group(1)), "unit": m.group(2)}

    for name, pat in [("voltage", VOLTAGE_PATTERN), ("current", CURRENT_PATTERN),
                      ("resistance", RESISTANCE_PATTERN), ("capacitance", CAPACITANCE_PATTERN)]:
        m = pat.search(text)
        if m:
            specs[name] = m.group(0).strip()

    m = THREAD_PATTERN.search(text)
    if m:
        specs["thread"] = m.group(1)

    m = GRADE_PATTERN.search(text)
    if m:
        specs["grade"] = m.group(1)

    m = FINISH_PATTERN.search(text)
    if m:
        specs["finish"] = m.group(1).strip()

    m = TOLERANCE_PATTERN.search(text)
    if m:
        specs["tolerance"] = m.group(1).strip()

    m = TEMP_PATTERN.search(text)
    if m:
        specs["temperature_rating"] = m.group(0).strip()

    return specs


def extract_specs_from_tokens(tokens: list, expanded_text: str) -> dict:
    """Token-aware spec extraction for the decomposed pipeline.

    Returns structured spec_json with per-field confidence and extraction_method.
    """
    specs: dict[str, Any] = {}

    for token in tokens:
        tt = token.token_type
        val = token.value

        if tt == "dimension":
            m = DIMENSION_PATTERN.match(val)
            if m:
                dims: dict[str, Any] = {"width": float(m.group(1)), "height": float(m.group(2))}
                if m.group(3):
                    dims["depth"] = float(m.group(3))
                if m.group(4):
                    dims["unit"] = m.group(4)
                specs["dimensions"] = {
                    "value": dims, "confidence": 0.9,
                    "extraction_method": "token_extraction",
                }

        elif tt == "thread_spec":
            specs["thread"] = {
                "value": val, "unit": None, "confidence": 0.9,
                "extraction_method": "token_extraction",
            }

        elif tt == "tolerance":
            specs["tolerance"] = {
                "value": val, "unit": None, "confidence": 0.85,
                "extraction_method": "token_extraction",
            }

        elif tt == "package_type":
            specs["package_type"] = {
                "value": val, "confidence": 0.95,
                "extraction_method": "token_extraction",
            }

        elif tt == "grade_reference":
            specs["grade"] = {
                "value": val, "confidence": 0.85,
                "extraction_method": "token_extraction",
            }

        elif tt == "finish_reference":
            specs["finish"] = {
                "value": val, "confidence": 0.85,
                "extraction_method": "token_extraction",
            }

        elif tt == "material_reference":
            specs["material"] = {
                "value": val, "confidence": 0.9,
                "extraction_method": "token_extraction",
            }

        elif tt == "value_unit_pair":
            nv = token.normalized_value or val
            val_lower = val.lower()
            if any(u in val_lower for u in ("v", "volt")):
                specs["voltage"] = {"value": nv, "confidence": 0.85, "extraction_method": "token_extraction"}
            elif any(u in val_lower for u in ("a", "amp")):
                specs["current"] = {"value": nv, "confidence": 0.85, "extraction_method": "token_extraction"}
            elif any(u in val_lower for u in ("ohm", "ω")):
                specs["resistance"] = {"value": nv, "confidence": 0.85, "extraction_method": "token_extraction"}
            elif "f" in val_lower and not any(u in val_lower for u in ("ft",)):
                specs["capacitance"] = {"value": nv, "confidence": 0.85, "extraction_method": "token_extraction"}
            elif any(u in val_lower for u in ("mm", "cm", "in", "m")):
                if "length" not in specs:
                    specs["length"] = {"value": nv, "confidence": 0.7, "extraction_method": "token_extraction"}
            elif any(u in val_lower for u in ("kg", "g", "lb", "oz")):
                specs["weight"] = {"value": nv, "confidence": 0.85, "extraction_method": "token_extraction"}

    # Fallback regex pass for anything tokens missed
    if "voltage" not in specs:
        m = VOLTAGE_PATTERN.search(expanded_text)
        if m:
            specs["voltage"] = {"value": m.group(0).strip(), "confidence": 0.7, "extraction_method": "regex_raw_text"}

    if "thread" not in specs:
        m = THREAD_PATTERN.search(expanded_text)
        if m:
            specs["thread"] = {"value": m.group(1), "unit": None, "confidence": 0.7, "extraction_method": "regex_raw_text"}

    if "grade" not in specs:
        m = GRADE_PATTERN.search(expanded_text)
        if m:
            specs["grade"] = {"value": m.group(1), "confidence": 0.65, "extraction_method": "regex_raw_text"}

    return specs
