"""Tests for enrichment pipeline per PC-003."""
import sys
from pathlib import Path
from uuid import uuid4
import pytest
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.schemas import EnrichmentRequest, EnrichmentResponse, NormalizedData, EnrichmentProjectContext
from engine.enrichment.pipeline import enrich_bom_line


def _make_request(material="stainless steel", is_custom=False,
                  procurement_class="catalog_purchase", has_mpn=True) -> EnrichmentRequest:
    nd = NormalizedData(
        part_name="M8 hex bolt", category="fastener", quantity=100,
        material=material, procurement_class=procurement_class,
        has_mpn=has_mpn, is_custom=is_custom,
    )
    return EnrichmentRequest(
        bom_line_id=uuid4(), normalized_data=nd,
        project_context=EnrichmentProjectContext(preferred_currency="USD"),
    )


class TestEnrichmentPipeline:
    def test_basic_enrichment(self):
        resp = enrich_bom_line(_make_request())
        assert isinstance(resp, EnrichmentResponse)
        assert resp.market_enrichment.price_band is not None

    def test_price_band_ordering(self):
        resp = enrich_bom_line(_make_request())
        pb = resp.market_enrichment.price_band
        assert float(pb.floor.amount) <= float(pb.mid.amount) <= float(pb.ceiling.amount)

    def test_missing_market_data_estimated(self):
        resp = enrich_bom_line(_make_request())
        assert any(f.freshness_status.value == "ESTIMATED" for f in resp.data_freshness_summary)

    def test_risk_flags_populated(self):
        resp = enrich_bom_line(_make_request(is_custom=True, procurement_class="custom_fabrication", has_mpn=False))
        flag_types = [f.flag_type.value for f in resp.risk_flags]
        assert "CUSTOM_PART" in flag_types

    def test_exotic_material_flag(self):
        resp = enrich_bom_line(_make_request(material="titanium grade 5"))
        flag_types = [f.flag_type.value for f in resp.risk_flags]
        assert "EXOTIC_MATERIAL" in flag_types

    def test_events_emitted(self):
        resp = enrich_bom_line(_make_request())
        assert len(resp.events) >= 1
        assert resp.events[0].event_type == "enrichment.completed"

    def test_freshness_summary_complete(self):
        resp = enrich_bom_line(_make_request())
        types = [f.data_type for f in resp.data_freshness_summary]
        assert "pricing" in types
        assert "tariff" in types
        assert "logistics" in types
