"""Specification extraction from component text."""
import re
import logging

logger = logging.getLogger("spec_extractor")

DIMENSION_PATTERN = re.compile(
    r"(\d+(?:\.\d+)?)\s*[xX×]\s*(\d+(?:\.\d+)?)\s*(?:[xX×]\s*(\d+(?:\.\d+)?))?\s*(mm|cm|in|inch|m)?"
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
    if not text:
        return {}
    specs = {}

    # Dimensions
    m = DIMENSION_PATTERN.search(text)
    if m:
        dims = {"width": float(m.group(1)), "height": float(m.group(2))}
        if m.group(3):
            dims["depth"] = float(m.group(3))
        if m.group(4):
            dims["unit"] = m.group(4)
        specs["dimensions"] = dims

    # Individual measurements
    for name, pat in [("diameter", DIAMETER_PATTERN), ("thickness", THICKNESS_PATTERN), ("length", LENGTH_PATTERN)]:
        m = pat.search(text)
        if m:
            specs[name] = {"value": float(m.group(1)), "unit": m.group(2) or "mm"}

    # Weight
    m = WEIGHT_PATTERN.search(text)
    if m:
        specs["weight"] = {"value": float(m.group(1)), "unit": m.group(2)}

    # Electrical
    for name, pat in [("voltage", VOLTAGE_PATTERN), ("current", CURRENT_PATTERN),
                      ("resistance", RESISTANCE_PATTERN), ("capacitance", CAPACITANCE_PATTERN)]:
        m = pat.search(text)
        if m:
            specs[name] = m.group(0).strip()

    # Thread
    m = THREAD_PATTERN.search(text)
    if m:
        specs["thread"] = m.group(1)

    # Grade
    m = GRADE_PATTERN.search(text)
    if m:
        specs["grade"] = m.group(1)

    # Finish
    m = FINISH_PATTERN.search(text)
    if m:
        specs["finish"] = m.group(1).strip()

    # Tolerance
    m = TOLERANCE_PATTERN.search(text)
    if m:
        specs["tolerance"] = m.group(1).strip()

    # Temperature
    m = TEMP_PATTERN.search(text)
    if m:
        specs["temperature_rating"] = m.group(0).strip()

    return specs
