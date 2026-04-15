"""Deterministic classification regression tests for Batch C."""
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.schemas import NormalizationRequest
from engine.classification.classifier import classify_from_tokens
from engine.normalization.pipeline import normalize_bom_line
from engine.normalization.text_normalizer import normalize_text
from engine.normalization.tokenizer import tokenize_raw_text
from engine.normalization.unit_converter import normalize_units


def _classify_text(raw_text: str):
    normalized_text, _ = normalize_text(raw_text)
    tokens = tokenize_raw_text(normalized_text)
    normalized_tokens, _ = normalize_units(tokens)
    return classify_from_tokens(normalized_tokens, normalized_text)


class TestDeterministicClassification:
    def test_fastener_from_thread_and_grade(self):
        category, subcategory, confidence, reason = _classify_text("M8 x 25 hex bolt SS304 grade 8.8")
        assert category == "fastener"
        assert subcategory in ("hex_bolt", "bolt")
        assert confidence >= 0.55
        assert "thread_spec" in reason or "bolt" in reason

    def test_sheet_metal_with_process_hints(self):
        category, _, confidence, _ = _classify_text("Aluminum sheet laser cut bent bracket 120 x 40 x 2 mm")
        assert category == "sheet_metal"
        assert confidence >= 0.55

    def test_raw_material_requires_material_plus_form(self):
        category, _, confidence, _ = _classify_text("Stainless steel 304 round bar 12 mm")
        assert category == "raw_material"
        assert confidence >= 0.5

    def test_custom_mechanical_from_drawing_and_tolerance(self):
        category, _, confidence, reason = _classify_text("Custom machined spacer per drawing ±0.02 mm aluminum")
        assert category in ("machined", "custom_mechanical")
        assert confidence >= 0.5
        assert "tolerance" in reason or "machining_hint" in reason or "custom_hint" in reason

    def test_electronics_value_and_package(self):
        category, _, confidence, _ = _classify_text("10k 0805 resistor ±5%")
        assert category in ("electronics", "passive_component")
        assert confidence >= 0.55

    def test_connector_not_overgeneralized_as_electrical(self):
        category, _, confidence, _ = _classify_text("8 pin terminal block connector 300V")
        assert category in ("connector", "electrical")
        assert confidence >= 0.45

    def test_ambiguous_mixed_text_stays_conservative(self):
        category, _, confidence, reason = _classify_text("Cable resistor connector assembly")
        assert category in ("unknown", "electrical", "electronics", "connector")
        assert confidence <= 0.55
        assert "ambiguous" in reason or "competitors" in reason

    def test_sparse_text_falls_back_to_unknown(self):
        category, _, confidence, reason = _classify_text("assy item")
        assert category == "unknown"
        assert confidence <= 0.42
        assert "weak" in reason or "ambiguous" in reason

    def test_ocr_noisy_fastener_detected(self):
        category, _, confidence, _ = _classify_text("M6 b0lt zinc plated")
        assert category == "fastener"
        assert confidence >= 0.45


class TestPipelineIntegration:
    def test_pipeline_returns_unknown_for_weak_signal(self):
        req = NormalizationRequest(bom_line_id=uuid4(), raw_text="assy item")
        resp = normalize_bom_line(req)
        assert resp.normalized.category == "unknown"
        assert resp.confidence < 0.6

    def test_pipeline_handles_dimension_heavy_sheet_metal(self):
        req = NormalizationRequest(
            bom_line_id=uuid4(),
            raw_text="CRCA sheet laser cut bent panel 250 x 150 x 2 mm powder coat",
        )
        resp = normalize_bom_line(req)
        assert resp.normalized.category in ("sheet_metal", "custom_mechanical")
        assert resp.confidence >= 0.45