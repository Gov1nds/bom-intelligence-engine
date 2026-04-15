"""Deterministic canonical identity helpers.

Current public format keeps the historic 3-part `category::body::signature`
shape for backward compatibility while making the middle body structured,
explainable, and stable across semantically equivalent inputs.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Iterable


_VERSION_MARKER = "v2"


def compute_spec_hash(spec_json: dict) -> str:
    serialized = json.dumps(spec_json, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]


def normalize_part_name(part_name: str) -> str:
    name = part_name.lower().strip()
    name = re.sub(r"[^a-z0-9\s_\-\.]", "", name)
    name = re.sub(r"[\s\-]+", "_", name).strip("_")
    return name[:120]


def _normalize_key_fragment(value: str) -> str:
    cleaned = normalize_part_name(value).replace("__", "_")
    return cleaned.strip("_")


def build_structured_identity_key(category: str, key_parts: Iterable[str]) -> str:
    normalized_category = _normalize_key_fragment(category) or "unknown"
    normalized_parts = [_normalize_key_fragment(part) for part in key_parts if _normalize_key_fragment(part)]
    body = "|".join(normalized_parts)[:180] if normalized_parts else "unspecified"
    signature_source = f"{normalized_category}|{body}|{_VERSION_MARKER}"
    signature = hashlib.sha1(signature_source.encode("utf-8")).hexdigest()[:10]
    return f"{normalized_category}::{body}::{signature}"


def generate_canonical_key(category: str, part_name: str, spec_json: dict) -> str:
    attributes = spec_json.get("attributes", {}) if isinstance(spec_json, dict) else {}
    key_parts: list[str] = []
    if isinstance(attributes, dict):
        preferred_order = [
            "material",
            "thread_size",
            "diameter_mm",
            "length_mm",
            "width_mm",
            "height_mm",
            "thickness_mm",
            "resistance_ohm",
            "capacitance_f",
            "voltage_v",
            "current_a",
            "power_w",
            "tolerance_percent",
            "grade",
            "finish",
        ]
        for key in preferred_order:
            value = attributes.get(key)
            if value not in (None, "", []):
                key_parts.append(f"{key}_{value}")
    if not key_parts:
        key_parts.append(part_name or "part")
    return build_structured_identity_key(category, key_parts)


def generate_mpn_lookup_key(category: str, manufacturer: str, mpn: str) -> str:
    mfr = re.sub(r"\s+", "_", manufacturer.strip().lower()[:20])
    clean_mpn = re.sub(r"[\s\-]", "", mpn.strip().upper())
    return f"{category}::mpn::{mfr}::{clean_mpn}".lower()