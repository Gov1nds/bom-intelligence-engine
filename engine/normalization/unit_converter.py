"""Unit conversion and SI prefix normalization per GAP-035, WF-NORM-001."""
from __future__ import annotations
from engine.normalization.tokenizer import Token
import re

SI_PREFIXES = {
    "p": 1e-12, "n": 1e-9, "µ": 1e-6, "u": 1e-6,
    "m": 1e-3, "k": 1e3, "M": 1e6, "G": 1e9,
}

UNIT_CONVERSIONS = {
    "in": ("mm", 25.4), "inch": ("mm", 25.4),
    "ft": ("m", 0.3048), "lb": ("kg", 0.4536), "oz": ("g", 28.35),
}

_VU_PATTERN = re.compile(
    r"(\d+(?:\.\d+)?)\s*(k|M|G|µ|u|m|p|n)?\s*"
    r"(ohm|Ω|F|H|V|A|W|Hz|mm|cm|in|m|kg|g|lb|oz)\b",
    re.I,
)


def normalize_units(tokens: list[Token]) -> tuple[list[Token], list[dict]]:
    """Normalize SI prefixes and convert imperial to metric."""
    conversions: list[dict] = []
    normalized: list[Token] = []
    for token in tokens:
        if token.token_type == "value_unit_pair":
            m = _VU_PATTERN.match(token.value)
            if m:
                raw_val = float(m.group(1))
                prefix = m.group(2)
                unit = m.group(3)
                val = raw_val * SI_PREFIXES.get(prefix, 1.0) if prefix else raw_val
                if unit.lower() in UNIT_CONVERSIONS:
                    target_unit, factor = UNIT_CONVERSIONS[unit.lower()]
                    val = val * factor
                    conversions.append({
                        "original": token.value,
                        "normalized_value": val,
                        "normalized_unit": target_unit,
                    })
                    unit = target_unit
                elif prefix:
                    conversions.append({
                        "original": token.value,
                        "normalized_value": val,
                        "normalized_unit": unit,
                    })
                new_token = Token(
                    token_type=token.token_type,
                    value=token.value,
                    raw_span=token.raw_span,
                    normalized_value=f"{val}{unit}",
                )
                normalized.append(new_token)
                continue
        normalized.append(token)
    return normalized, conversions
