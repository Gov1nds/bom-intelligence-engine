"""Batch F review and uncertainty detection tests."""
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.schemas import NormalizationRequest
from engine.normalization.pipeline import normalize_bom_line


def _req(raw_text: str) -> NormalizationRequest:
    return NormalizationRequest(bom_line_id=uuid4(), raw_text=raw_text)


def test_flags_always_present_even_when_empty_or_small():
    resp = normalize_bom_line(_req("M8 SS bolt 30mm"))
    assert isinstance(resp.normalized.review_flags, list)
    assert isinstance(resp.normalized.uncertainty_flags, list)


def test_fastener_missing_critical_attribute_flagged():
    resp = normalize_bom_line(_req("M8 bolt"))
    assert "MISSING_CRITICAL_ATTRIBUTE" in resp.normalized.review_flags
    assert "MISSING_MATERIAL" in resp.normalized.uncertainty_flags


def test_electronics_missing_required_specs_flagged():
    resp = normalize_bom_line(_req("resistor"))
    assert "INSUFFICIENT_SPEC" in resp.normalized.review_flags
    assert "MISSING_CRITICAL_ATTRIBUTE" in resp.normalized.review_flags
    assert "NEEDS_MANUAL_REVIEW" in resp.normalized.review_flags


def test_conflicting_materials_and_multiple_units_flagged():
    resp = normalize_bom_line(_req("steel aluminum bracket 2mm 0.125in"))
    assert "CONFLICTING_ATTRIBUTES" in resp.normalized.uncertainty_flags
    assert "MULTIPLE_UNITS" in resp.normalized.uncertainty_flags


def test_unknown_tokens_surface_uncertainty():
    resp = normalize_bom_line(_req("custom bracket tbd ???"))
    assert "UNKNOWN_TOKEN_PRESENT" in resp.normalized.uncertainty_flags
    assert "WEAK_SIGNAL_INPUT" in resp.normalized.review_flags
