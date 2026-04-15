"""Batch G learning signal emission tests."""
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.schemas import NormalizationRequest
from engine.normalization.pipeline import normalize_bom_line


def _req(raw_text: str) -> NormalizationRequest:
    return NormalizationRequest(bom_line_id=uuid4(), raw_text=raw_text)


def test_strong_signal_output():
    resp = normalize_bom_line(_req("M8 SS bolt 30mm"))
    signals = resp.normalized.learning_signals

    assert signals["signal_strength"] == "strong"
    assert signals["extraction_quality"] == "complete"
    assert signals["has_critical_missing"] is False
    assert signals["category"] == "fastener"
    assert signals["normalized_part_key"] == resp.normalized.normalized_part_key


def test_medium_signal_output():
    resp = normalize_bom_line(_req("aluminum bracket 50x20x3 mm"))
    signals = resp.normalized.learning_signals

    assert signals["signal_strength"] == "medium"
    assert signals["extraction_quality"] == "partial"
    assert signals["has_critical_missing"] is False
    assert signals["category"] in {"mechanical", "custom_mechanical"}


def test_weak_signal_output():
    resp = normalize_bom_line(_req("resistor"))
    signals = resp.normalized.learning_signals

    assert signals["signal_strength"] == "weak"
    assert signals["extraction_quality"] == "poor"
    assert signals["has_critical_missing"] is True


def test_missing_attributes_payload_is_stable_and_safe():
    resp = normalize_bom_line(_req("custom bracket tbd ???"))
    signals = resp.normalized.learning_signals

    assert signals["raw_input"] == "custom bracket tbd ???"
    assert isinstance(signals["attributes"], dict)
    assert signals["signal_strength"] == "weak"
    assert signals["has_critical_missing"] is True