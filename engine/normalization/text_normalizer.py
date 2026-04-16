"""Deterministic BOM text normalization using bundled reference assets."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from engine.normalization.reference_loader import get_normalization_references


_SAFE_SHORT_ABBREVIATIONS = {"ss", "al", "cu", "cs"}
_MEASUREMENT_UNITS = (
    "mm", "cm", "m", "in", "ft", "kg", "g", "lb", "oz", "ohm", "v", "a", "w", "hz"
)
_UNICODE_REPLACEMENTS = {
    "µ": "u",
    "μ": "u",
    "Ω": "ohm",
    "ω": "ohm",
    "°": " deg ",
    "º": " deg ",
    "Ø": " diameter ",
    "ø": " diameter ",
    "⌀": " diameter ",
    "∅": " diameter ",
    "–": "-",
    "—": "-",
    "−": "-",
    "•": " ",
    "·": " ",
    "／": "/",
    "，": ",",
    "：": ":",
    "；": ";",
    "（": "(",
    "）": ")",
}


@dataclass
class TextNormalizationTrace:
    unicode_cleanup_applied: bool = False
    punctuation_cleanup_applied: bool = False
    casing_normalized: bool = False
    numeric_cleanup_applied: list[dict] = field(default_factory=list)
    abbreviation_expansions: list[dict] = field(default_factory=list)
    synonym_rewrites: list[dict] = field(default_factory=list)
    unit_normalizations: list[dict] = field(default_factory=list)



def _normalize_unicode(text: str) -> tuple[str, bool]:
    normalized = unicodedata.normalize("NFKC", text)
    for source, target in _UNICODE_REPLACEMENTS.items():
        normalized = normalized.replace(source, target)
    changed = normalized != text or ("×" in text)
    return normalized, changed



def _cleanup_numeric_formatting(text: str, trace: TextNormalizationTrace) -> str:
    updated = text

    decimal_cleaned = re.sub(r"(?<=\d),(?=\d)", ".", updated)
    if decimal_cleaned != updated:
        trace.numeric_cleanup_applied.append({"rule": "decimal_comma_to_dot"})
    updated = decimal_cleaned

    unit_spacing_cleaned = re.sub(
        rf"(?<=\d)(?=({'|'.join(_MEASUREMENT_UNITS)})(?![A-Za-z]))",
        " ",
        updated,
        flags=re.IGNORECASE,
    )
    if unit_spacing_cleaned != updated:
        trace.numeric_cleanup_applied.append({"rule": "insert_space_before_measurement_unit"})
    updated = unit_spacing_cleaned

    multiplier_spacing_cleaned = re.sub(r"(?<=\d)[xX](?=\d)", " x ", updated)
    if multiplier_spacing_cleaned != updated:
        trace.numeric_cleanup_applied.append({"rule": "normalize_dimension_separator_spacing"})
    updated = multiplier_spacing_cleaned

    return updated



def _cleanup_punctuation(text: str) -> tuple[str, bool]:
    original = text
    text = text.replace("×", " x ")
    text = re.sub(r"([0-9])\s*[xX]\s*([0-9])", r"\1 x \2", text)
    text = re.sub(r"\s*/\s*(?=\d)", "/", text)
    text = re.sub(r"[;,]+", " ", text)
    text = re.sub(r"\s*[:=]\s*", " ", text)
    text = re.sub(r"[\[\]{}()]+", " ", text)
    text = re.sub(r"(?<!\d)\.(?!\d)", " ", text)
    text = re.sub(r"\s+-\s+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text, text != original



def _expand_abbreviations(text: str, trace: TextNormalizationTrace) -> str:
    refs = get_normalization_references()
    result = text
    for source in sorted(refs.abbreviations, key=len, reverse=True):
        replacement = refs.abbreviations[source]
        if source in _SAFE_SHORT_ABBREVIATIONS:
            pattern = re.compile(rf"\b{re.escape(source)}(?=\d{{3,}}|\b)\b", re.IGNORECASE)
        else:
            pattern = re.compile(rf"\b{re.escape(source)}\b", re.IGNORECASE)
        if pattern.search(result):
            result = pattern.sub(replacement, result)
            trace.abbreviation_expansions.append({"abbreviation": source, "expanded_to": replacement})
    return result



def _apply_synonyms(text: str, trace: TextNormalizationTrace) -> str:
    refs = get_normalization_references()
    result = text
    for source in sorted(refs.synonyms, key=len, reverse=True):
        replacement = refs.synonyms[source]
        pattern = re.compile(rf"\b{re.escape(source)}\b", re.IGNORECASE)
        if pattern.search(result):
            result = pattern.sub(replacement, result)
            trace.synonym_rewrites.append({"from": source, "to": replacement})
    return result



def _normalize_units(text: str, trace: TextNormalizationTrace) -> str:
    refs = get_normalization_references()
    result = text

    result = re.sub(r"(\d+(?:\.\d+)?)\s*([kmgupn])\s*ohm\b", r"\1 \2ohm", result, flags=re.IGNORECASE)

    for source, target in refs.units.items():
        pattern = re.compile(rf"(?<![A-Za-z]){re.escape(source)}\b", re.IGNORECASE)
        if pattern.search(result):
            result = pattern.sub(target, result)
            if source != target:
                trace.unit_normalizations.append({"from": source, "to": target})

    result = re.sub(r"(\d)\s*(x)\s*(\d)", r"\1 x \3", result, flags=re.IGNORECASE)
    result = re.sub(
        rf"(\d(?:\.\d+)?)\s*({'|'.join(_MEASUREMENT_UNITS)})\b",
        r"\1 \2",
        result,
        flags=re.IGNORECASE,
    )
    result = re.sub(r"(\d+(?:\.\d+)?)\s*([kmgupn]ohm)\b", r"\1 \2", result, flags=re.IGNORECASE)
    result = re.sub(r"\bdeg\b", "deg", result, flags=re.IGNORECASE)
    result = re.sub(r"\s+", " ", result).strip().rstrip('.')
    return result



def normalize_text(raw_text: str) -> tuple[str, TextNormalizationTrace]:
    trace = TextNormalizationTrace()
    text, unicode_changed = _normalize_unicode(raw_text)
    trace.unicode_cleanup_applied = unicode_changed

    text = _cleanup_numeric_formatting(text, trace)

    punct_cleaned, punctuation_changed = _cleanup_punctuation(text)
    text = punct_cleaned.lower()
    trace.punctuation_cleanup_applied = punctuation_changed
    trace.casing_normalized = text != punct_cleaned

    text = _expand_abbreviations(text, trace)
    text = _apply_synonyms(text, trace)
    text = _normalize_units(text, trace)
    text = re.sub(r"\s+", " ", text).strip()
    return text, trace