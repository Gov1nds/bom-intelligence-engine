"""Abbreviation expansion backed by repo-local bundled references."""
from __future__ import annotations

from engine.normalization.reference_loader import get_normalization_references
from engine.normalization.text_normalizer import normalize_text


DEFAULT_ABBREVIATIONS: dict[str, str] = get_normalization_references().abbreviations



def expand_abbreviations(
    text: str, custom_dict: dict[str, str] | None = None
) -> tuple[str, list[dict]]:
    """Expand abbreviations in text. Returns (expanded_text, trace)."""
    if custom_dict:
        lowered = text.lower()
        expansions: list[dict] = []
        for key, value in custom_dict.items():
            if key.lower() in lowered:
                lowered = lowered.replace(key.lower(), value.lower())
                expansions.append({"abbreviation": key, "expanded_to": value.lower()})
        return lowered, expansions

    normalized_text, trace = normalize_text(text)
    return normalized_text, trace.abbreviation_expansions
