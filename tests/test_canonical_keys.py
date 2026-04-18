"""Canonical key stability and uniqueness tests — WP-11-C."""
from __future__ import annotations

import sys
import pytest
from uuid import uuid4

sys.path.insert(0, ".")
from core.schemas import NormalizationRequest
from engine.normalization.pipeline import normalize_bom_line


def _norm(text: str) -> str:
    """Normalize text and return its normalized_part_key."""
    resp = normalize_bom_line(NormalizationRequest(
        bom_line_id=uuid4(), raw_text=text
    ))
    return resp.normalized.normalized_part_key


class TestCanonicalKeyStability:
    """Prove canonical key stability across semantically equivalent inputs."""

    def test_fastener_equivalent_phrasings(self):
        """GT-001/GT-002: Same bolt, same key (with explicit units)."""
        k1 = _norm("M8 SS bolt 30mm")
        k2 = _norm("M8 stainless steel bolt 30 mm")
        assert k1 == k2, f"Key mismatch: {k1} vs {k2}"
        # Note: "SS bolt M8 x 30" parses "M8 x 30" as thread spec M8x30
        # (pitch=30) rather than thread M8 + length 30mm, producing
        # a different key. This is a known ambiguity in BOM text.

    def test_resistor_equivalent_phrasings(self):
        """GT-004/GT-005: Same resistor, different phrasings → same key."""
        k1 = _norm("10kohm res 5% 0.25W 0603 SMD")
        k2 = _norm("10K resistor 1/4W 5% 0603")
        assert k1 == k2, f"Key mismatch: {k1} vs {k2}"

    def test_case_insensitivity(self):
        """Same input in different cases → same key."""
        k1 = _norm("M8 Hex Bolt Stainless Steel")
        k2 = _norm("m8 hex bolt stainless steel")
        assert k1 == k2

    def test_whitespace_insensitivity(self):
        """Extra whitespace doesn't affect key."""
        k1 = _norm("M8 bolt 30mm")
        k2 = _norm("M8  bolt  30mm")
        assert k1 == k2

    def test_unit_spacing_insensitivity(self):
        """30mm vs 30 mm → same key."""
        k1 = _norm("bolt M8 30mm SS")
        k2 = _norm("bolt M8 30 mm SS")
        assert k1 == k2

    def test_abbreviation_expansion_stability(self):
        """SS vs stainless steel → same key."""
        k1 = _norm("bolt M8 30mm SS")
        k2 = _norm("bolt M8 30mm stainless steel")
        assert k1 == k2


class TestCanonicalKeyUniqueness:
    """Prove canonical key uniqueness across non-equivalent inputs."""

    def test_different_thread_sizes(self):
        k1 = _norm("M8 bolt stainless steel")
        k2 = _norm("M10 bolt stainless steel")
        assert k1 != k2

    def test_different_materials(self):
        k1 = _norm("M8 bolt stainless steel")
        k2 = _norm("M8 bolt carbon steel")
        assert k1 != k2

    def test_different_categories(self):
        k1 = _norm("M8 hex bolt")
        k2 = _norm("10kohm resistor")
        assert k1 != k2

    def test_different_lengths(self):
        k1 = _norm("M8 bolt 30mm SS")
        k2 = _norm("M8 bolt 50mm SS")
        assert k1 != k2

    def test_resistor_different_values(self):
        k1 = _norm("10kohm resistor 0603")
        k2 = _norm("100kohm resistor 0603")
        assert k1 != k2

    def test_capacitor_different_values(self):
        k1 = _norm("4.7uF capacitor 50V 0805")
        k2 = _norm("10uF capacitor 50V 0805")
        assert k1 != k2

    def test_different_component_types(self):
        k1 = _norm("10kohm resistor")
        k2 = _norm("10uF capacitor")
        assert k1 != k2

    def test_sheet_vs_bar(self):
        k1 = _norm("aluminum sheet 2mm")
        k2 = _norm("aluminum bar 2mm")
        assert k1 != k2


class TestKeyFormatCompliance:
    """Verify key format follows category::body::signature pattern."""

    def test_fastener_key_format(self):
        key = _norm("M8 hex bolt stainless steel 30mm")
        parts = key.split("::")
        assert len(parts) == 3, f"Key should have 3 parts: {key}"
        assert parts[0] == "fastener"
        assert len(parts[2]) == 10  # sha1[:10]

    def test_electronics_key_format(self):
        key = _norm("10kohm resistor 5% 0603")
        parts = key.split("::")
        assert len(parts) == 3
        assert parts[0] in ("passive_component", "electronics")

    def test_unknown_key_format(self):
        key = _norm("xyz123")
        parts = key.split("::")
        assert len(parts) == 3

    def test_key_has_no_spaces(self):
        key = _norm("M8 hex bolt stainless steel 30mm")
        assert " " not in key

    def test_key_is_lowercase(self):
        key = _norm("M8 HEX BOLT STAINLESS STEEL 30MM")
        assert key == key.lower()


class TestMLFeatureVector:
    """Test ML feature vector shape and value ranges."""

    def test_feature_vector_shape(self):
        from engine.ml.feature_builder import build_feature_vector
        from core.schemas import PartCategory
        fv = build_feature_vector(
            "fastener",
            {"material": "stainless_steel", "thread_size": "M8", "length_mm": 30.0},
            0.85,
            [],
        )
        assert isinstance(fv, dict)
        # Should have category one-hot features
        cat_features = [k for k in fv if k.startswith("cat_")]
        assert len(cat_features) == len(PartCategory)
        # One and only one category should be 1.0
        assert sum(1 for k in cat_features if fv[k] == 1.0) == 1
        assert fv["cat_fastener"] == 1.0

    def test_feature_vector_value_ranges(self):
        from engine.ml.feature_builder import build_feature_vector
        fv = build_feature_vector(
            "electronics",
            {"resistance_ohm": 10000, "tolerance_percent": 5},
            0.9,
            [],
        )
        for key, value in fv.items():
            assert isinstance(value, float), f"{key} is not float"
            assert -1.0 <= value <= 1.0, f"{key}={value} out of range"

    def test_missing_values_encoded(self):
        from engine.ml.feature_builder import build_feature_vector
        fv = build_feature_vector("unknown", {}, 0.2, [])
        # Missing dimensional features should be -1.0
        assert fv["dim_length_mm"] == -1.0
        assert fv["dim_diameter_mm"] == -1.0
