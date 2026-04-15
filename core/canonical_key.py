"""Canonical key generation per api-contract-review.md §6.2.

Format: {category}::{normalized_part_name}::{spec_hash}
"""
import hashlib
import json
import re


def compute_spec_hash(spec_json: dict) -> str:
    serialized = json.dumps(spec_json, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]


def normalize_part_name(part_name: str) -> str:
    name = part_name.lower().strip()
    name = re.sub(r"[^a-z0-9\s_]", "", name)
    name = re.sub(r"\s+", "_", name).strip("_")
    return name[:80]


def generate_canonical_key(category: str, part_name: str, spec_json: dict) -> str:
    norm_name = normalize_part_name(part_name)
    spec_hash = compute_spec_hash(spec_json)
    return f"{category}::{norm_name}::{spec_hash}"


def generate_mpn_lookup_key(category: str, manufacturer: str, mpn: str) -> str:
    mfr = re.sub(r"\s+", "_", manufacturer.strip().lower()[:20])
    clean_mpn = re.sub(r"[\s\-]", "", mpn.strip().upper())
    return f"{category}::mpn::{mfr}::{clean_mpn}".lower()
