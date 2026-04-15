"""Tests for scoring pipeline per PC-004, PC-005."""
import sys
from pathlib import Path
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.schemas import (
    ScoringRequest, ScoringResponse, VendorCandidate,
    EnrichmentData, WeightProfile,
)
from engine.scoring.pipeline import score_bom_line
from engine.scoring.weight_profiles import WEIGHT_PROFILES, validate_weight_profile


class TestWeightProfiles:
    def test_all_sum_to_one(self):
        for name, weights in WEIGHT_PROFILES.items():
            assert abs(sum(weights.values()) - 1.0) < 0.001, f"{name} doesn't sum to 1"

    def test_balanced_values(self):
        w = WEIGHT_PROFILES["balanced"]
        assert w["cost"] == 0.25
        assert w["quality"] == 0.25

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            validate_weight_profile("nonexistent")


class TestScoringPipeline:
    def _make_request(self, n_vendors=3, profile="balanced") -> ScoringRequest:
        vendors = []
        for i in range(n_vendors):
            vendors.append(VendorCandidate(
                vendor_id=f"V-{i:03d}",
                vendor_name=f"Vendor {i}",
                unit_price=str(10 + i * 5),
                lead_time_days=7 + i * 3,
                quality_rating=4.0 - i * 0.5,
                on_time_rate=0.95 - i * 0.05,
                certifications=["ISO9001"] if i == 0 else [],
                capabilities=["machining", "turning"],
                country_code="US",
                currency="USD",
            ))
        return ScoringRequest(
            bom_line_id=uuid4(),
            enrichment_data=EnrichmentData(quantity=100, category="mechanical", is_custom=True),
            candidate_vendors=vendors,
            weight_profile=WeightProfile(profile),
        )

    def test_5_dimensions_present(self):
        resp = score_bom_line(self._make_request())
        for v in resp.vendor_scores:
            if not v.eliminated:
                ds = v.dimension_scores
                assert "cost" in ds
                assert "lead_time" in ds
                assert "quality" in ds
                assert "strategic_fit" in ds
                assert "operational_capability" in ds

    def test_sorted_by_composite(self):
        resp = score_bom_line(self._make_request())
        active = [v for v in resp.vendor_scores if not v.eliminated]
        scores = [v.composite_score for v in active]
        assert scores == sorted(scores, reverse=True)

    def test_hard_filter_eliminates(self):
        req = self._make_request(n_vendors=1)
        req.candidate_vendors[0].capabilities = []
        req.enrichment_data.is_custom = True
        resp = score_bom_line(req)
        assert resp.vendor_scores[0].eliminated is True
        assert resp.vendor_scores[0].elimination_reason is not None

    def test_tlc_present(self):
        resp = score_bom_line(self._make_request())
        active = [v for v in resp.vendor_scores if not v.eliminated]
        for v in active:
            assert v.tlc is not None
            assert v.tlc_breakdown is not None

    def test_explanation_generated(self):
        resp = score_bom_line(self._make_request())
        active = [v for v in resp.vendor_scores if not v.eliminated]
        for v in active:
            assert len(v.explanation) > 0

    def test_confidence_levels(self):
        resp = score_bom_line(self._make_request())
        for v in resp.vendor_scores:
            if not v.eliminated:
                assert v.confidence_level.value in ("HIGH", "MEDIUM", "LOW")

    def test_weight_profile_applied(self):
        resp = score_bom_line(self._make_request(profile="cost_first"))
        assert resp.weight_profile_applied["cost"] == 0.40

    def test_events_emitted(self):
        resp = score_bom_line(self._make_request())
        assert len(resp.events) >= 1
        assert resp.events[0].event_type == "scoring.completed"
