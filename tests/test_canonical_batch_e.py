"""Batch E canonical intelligence tests."""
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.schemas import NormalizationRequest
from engine.normalization.pipeline import normalize_bom_line


def _req(raw_text: str) -> NormalizationRequest:
    return NormalizationRequest(bom_line_id=uuid4(), raw_text=raw_text)


def test_fastener_canonical_name_and_flags():
    resp = normalize_bom_line(_req("M8 SS bolt 30mm"))
    assert resp.normalized.canonical_name == "Bolt Stainless Steel M8 x 30mm"
    assert resp.normalized.part_name == resp.normalized.canonical_name
    assert resp.normalized.requires_rfq is False
    assert resp.normalized.drawing_required is False


def test_resistor_canonical_name():
    resp = normalize_bom_line(_req("10k resistor 1/4W 5%"))
    assert resp.normalized.canonical_name == "Resistor 10kΩ 0.25W 5%"
    assert "resistor|10000ohm|0.25w|5pct" in resp.normalized.normalized_part_key


def test_sheet_metal_processes_and_flags():
    resp = normalize_bom_line(_req("Aluminum sheet 2mm thick laser cut bent"))
    assert resp.normalized.canonical_name == "Sheet Aluminum 2mm"
    assert resp.normalized.suggested_processes == ["laser_cutting", "bending"]
    assert resp.normalized.requires_rfq is True
    assert resp.normalized.drawing_required is True


def test_equivalent_inputs_converge_on_identity():
    a = normalize_bom_line(_req("M8x30 SS304 hex bolt"))
    b = normalize_bom_line(_req("stainless steel 304 bolt M8 x 30"))
    assert a.normalized.normalized_part_key == b.normalized.normalized_part_key


def test_unknown_partial_output_is_safe():
    resp = normalize_bom_line(_req("custom bracket"))
    assert resp.normalized.canonical_name
    assert resp.normalized.normalized_part_key.startswith("custom_mechanical::") or resp.normalized.normalized_part_key.startswith("mechanical::") or resp.normalized.normalized_part_key.startswith("unknown::")