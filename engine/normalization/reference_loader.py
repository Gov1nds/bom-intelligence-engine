"""Centralized bundled reference asset loader for normalization."""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any


_RESOURCE_ROOT = Path(__file__).resolve().parent / "resources" / "v1"


@dataclass(frozen=True)
class NormalizationReferences:
    version: str
    abbreviations: dict[str, str]
    synonyms: dict[str, str]
    units: dict[str, str]
    materials: tuple[str, ...]
    category_keywords: dict[str, tuple[str, ...]]
    process_hints: dict[str, tuple[str, ...]]
    spec_patterns: dict[str, Any]



def _load_json(name: str) -> dict[str, Any]:
    with (_RESOURCE_ROOT / name).open("r", encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def get_normalization_references() -> NormalizationReferences:
    abbreviations = _load_json("abbreviations.json")
    synonyms = _load_json("synonyms.json")
    units = _load_json("units.json")
    materials = _load_json("materials.json")
    category_keywords = _load_json("category_keywords.json")
    process_hints = _load_json("process_hints.json")
    spec_patterns = _load_json("spec_patterns.json")

    version = abbreviations.get("version", "1.0.0")
    return NormalizationReferences(
        version=version,
        abbreviations={k.lower(): v.lower() for k, v in abbreviations.get("entries", {}).items()},
        synonyms={k.lower(): v.lower() for k, v in synonyms.get("entries", {}).items()},
        units={k.lower(): v.lower() for k, v in units.get("symbols", {}).items()},
        materials=tuple(m.lower() for m in materials.get("entries", [])),
        category_keywords={
            k.lower(): tuple(vv.lower() for vv in values)
            for k, values in category_keywords.get("entries", {}).items()
        },
        process_hints={
            k.lower(): tuple(vv.lower() for vv in values)
            for k, values in process_hints.get("entries", {}).items()
        },
        spec_patterns=spec_patterns.get("patterns", {}),
    )