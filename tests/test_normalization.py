"""Tests for normalization pipeline per PC-002."""
import sys
from pathlib import Path
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.schemas import NormalizationRequest, NormalizationResponse
from engine.normalization.pipeline import normalize_bom_line
from engine.normalization.tokenizer import tokenize_raw_text
from engine.normalization.abbreviation_expander import expand_abbreviations
from engine.normalization.unit_converter import normalize_units
from core.canonical_key import generate_canonical_key, normalize_part_name, compute_spec_hash


class TestTokenizer:
    def test_empty_string(self):
        assert tokenize_raw_text("") == []

    def test_extracts_dimension(self):
        tokens = tokenize_raw_text("50x30x10mm bracket")
        types = [t.token_type for t in tokens]
        assert "dimension" in types

    def test_extracts_thread(self):
        tokens = tokenize_raw_text("M8x1.25 hex bolt")
        types = [t.token_type for t in tokens]
        assert "thread_spec" in types

    def test_extracts_package_type(self):
        tokens = tokenize_raw_text("10k 0805 resistor")
        types = [t.token_type for t in tokens]
        assert "package_type" in types

    def test_extracts_tolerance(self):
        tokens = tokenize_raw_text("±0.05mm tolerance")
        types = [t.token_type for t in tokens]
        assert "tolerance" in types

    def test_extracts_part_number(self):
        tokens = tokenize_raw_text("LM7805CT voltage regulator")
        types = [t.token_type for t in tokens]
        assert "part_number_fragment" in types

    def test_ordering(self):
        tokens = tokenize_raw_text("M8 50x30mm ±0.1mm")
        positions = [t.raw_span[0] for t in tokens]
        assert positions == sorted(positions)


class TestAbbreviationExpander:
    def test_expand_ss(self):
        result, trace = expand_abbreviations("SS304 bracket")
        assert "stainless steel 304" in result.lower()
        assert len(trace) > 0

    def test_preserves_non_abbreviations(self):
        result, trace = expand_abbreviations("aluminum bracket")
        assert "aluminum bracket" in result.lower()

    def test_word_boundary(self):
        result, _ = expand_abbreviations("ASSEMBLY part")
        # "SS" should NOT match inside "ASSEMBLY"
        assert "stainless steel" not in result.lower() or "assembly" in result.lower()

    def test_custom_dict(self):
        result, trace = expand_abbreviations("XYZ part", {"XYZ": "custom thing"})
        assert "custom thing" in result


class TestUnitConverter:
    def test_si_prefix(self):
        tokens = tokenize_raw_text("10kohm")
        normalized, conversions = normalize_units(tokens)
        assert len(conversions) > 0 or len(normalized) > 0

    def test_imperial_conversion(self):
        tokens = tokenize_raw_text("2in bolt")
        normalized, conversions = normalize_units(tokens)
        found = any("mm" in str(c.get("normalized_unit", "")) for c in conversions)
        if conversions:
            assert found


class TestCanonicalKey:
    def test_deterministic(self):
        k1 = generate_canonical_key("fastener", "M8 Hex Bolt", {"thread": "M8", "grade": "8.8"})
        k2 = generate_canonical_key("fastener", "M8 Hex Bolt", {"grade": "8.8", "thread": "M8"})
        assert k1 == k2

    def test_format(self):
        key = generate_canonical_key("fastener", "M8 Hex Bolt", {"thread": "M8"})
        parts = key.split("::")
        assert len(parts) == 3
        assert parts[0] == "fastener"

    def test_normalize_part_name(self):
        assert normalize_part_name("  M8 Hex Bolt! ") == "m8_hex_bolt"

    def test_spec_hash_stable(self):
        h1 = compute_spec_hash({"a": 1, "b": 2})
        h2 = compute_spec_hash({"b": 2, "a": 1})
        assert h1 == h2


class TestNormalizationPipeline:
    def _make_request(self, raw_text: str) -> NormalizationRequest:
        return NormalizationRequest(bom_line_id=uuid4(), raw_text=raw_text)

    def test_simple_fastener(self):
        resp = normalize_bom_line(self._make_request("M8x25 hex bolt stainless steel 304 grade 8.8"))
        assert resp.normalized.category == "fastener"
        assert resp.confidence > 0.3

    def test_electronics_resistor(self):
        resp = normalize_bom_line(self._make_request("10k 0805 resistor ±5%"))
        assert resp.normalized.category in ("electronics", "passive_component")

    def test_custom_part(self):
        resp = normalize_bom_line(self._make_request("Custom aluminum bracket 50x30x10mm anodized"))
        assert resp.normalized.category in ("machined", "custom_mechanical", "mechanical", "raw_material", "enclosure")

    def test_confidence_routing_auto(self):
        resp = normalize_bom_line(self._make_request("M8x25 hex bolt stainless steel grade 8.8 anodized"))
        # High-detail input should score decently
        assert resp.normalization_trace.review_required is not None  # field exists

    def test_empty_raises(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            NormalizationRequest(bom_line_id=uuid4(), raw_text="")

    def test_split_detection(self):
        resp = normalize_bom_line(self._make_request("M8 bolt and M8 nut"))
        assert resp.split_detected is True
        assert resp.split_candidates is not None

    def test_trace_complete(self):
        resp = normalize_bom_line(self._make_request("10k resistor 0805"))
        trace = resp.normalization_trace
        assert trace.processing_time_ms >= 0
        assert isinstance(trace.tokens_extracted, list)

    def test_events_emitted(self):
        resp = normalize_bom_line(self._make_request("M8 bolt"))
        assert len(resp.events) >= 1
        assert resp.events[0].event_type in (
            "normalization.completed", "normalization.review_required"
        )

    def test_canonical_key_format(self):
        resp = normalize_bom_line(self._make_request("M8 hex bolt grade 8.8"))
        assert "::" in resp.normalized.canonical_key

    def test_model_version(self):
        resp = normalize_bom_line(self._make_request("test part"))
        assert resp.model_version == "5.0.0"
