"""Abbreviation expansion per GAP-035, WF-NORM-001 step 2."""
import re

DEFAULT_ABBREVIATIONS: dict[str, str] = {
    "SS": "stainless steel", "AL": "aluminum", "CU": "copper",
    "BRG": "bearing", "BRKT": "bracket", "CONN": "connector",
    "CAP": "capacitor", "RES": "resistor", "IND": "inductor",
    "ASSY": "assembly", "SHTMTL": "sheet metal", "MACH": "machined",
    "GR": "grade", "DIA": "diameter", "THK": "thickness",
    "LG": "length", "QTY": "quantity", "EA": "each",
    "HEX": "hexagonal", "RD": "round", "SQ": "square",
    "GALV": "galvanized", "ANOD": "anodized",
    "SS304": "stainless steel 304", "SS316": "stainless steel 316",
    "CS": "carbon steel", "HDPE": "high density polyethylene",
    "PTFE": "polytetrafluoroethylene", "PCB": "printed circuit board",
    "IC": "integrated circuit", "MCU": "microcontroller",
    "MOSFET": "metal-oxide-semiconductor field-effect transistor",
    "SMD": "surface mount device", "THT": "through hole technology",
    "CNC": "computer numerical control", "EDM": "electrical discharge machining",
    "PWR": "power", "XFMR": "transformer", "MTG": "mounting",
    "BLK": "block", "SHT": "sheet", "PNL": "panel",
    "HSG": "housing", "FLG": "flange", "BRZ": "bronze",
}


def expand_abbreviations(
    text: str, custom_dict: dict[str, str] | None = None
) -> tuple[str, list[dict]]:
    """Expand abbreviations in text. Returns (expanded_text, trace)."""
    expansions: list[dict] = []
    merged = {**DEFAULT_ABBREVIATIONS, **(custom_dict or {})}
    result = text
    for abbrev, full_form in merged.items():
        pattern = re.compile(r"\b" + re.escape(abbrev) + r"\b", re.IGNORECASE)
        if pattern.search(result):
            result = pattern.sub(full_form, result)
            expansions.append({"abbreviation": abbrev, "expanded_to": full_form})
    return result, expansions
