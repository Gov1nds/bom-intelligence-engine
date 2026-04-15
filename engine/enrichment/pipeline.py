"""Enrichment pipeline per PC-003, WF-ENRICH-001, GAP-003.

Engine does NOT call external APIs (architecture.md THINGS TO NEVER DO #12).
Market/tariff/logistics data is provided by Platform-api-main in the request.
"""
from __future__ import annotations
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from core.config import config
from core.events import EventTypes, build_event
from core.schemas import (
    EnrichmentRequest, EnrichmentResponse, EngineEventSchema,
    FreshnessStatus, LogisticsEnrichment, MarketEnrichment,
    Money, PriceBand, RiskFlag, RiskFlagType, TariffEnrichment,
    TtlWindow,
)
from engine.estimation.cost_estimator import estimate_cost
from engine.estimation.lead_time_risk import estimate_lead_time, estimate_risk


def _safe_decimal(val: str | float | int | None, default: str = "0") -> Decimal:
    try:
        return Decimal(str(val)) if val is not None else Decimal(default)
    except (InvalidOperation, ValueError):
        return Decimal(default)


def _check_freshness(data_cache: dict, data_type: str) -> TtlWindow:
    fetched_at_str = data_cache.get("fetched_at")
    ttl = data_cache.get("ttl_seconds", 0)
    source = data_cache.get("source", "unknown")

    if not fetched_at_str or not ttl:
        return TtlWindow(
            data_type=data_type, freshness_status=FreshnessStatus.ESTIMATED, source=source
        )
    try:
        fetched_at = datetime.fromisoformat(fetched_at_str)
    except (ValueError, TypeError):
        return TtlWindow(
            data_type=data_type, freshness_status=FreshnessStatus.ESTIMATED, source=source
        )

    age = (datetime.now(timezone.utc) - fetched_at.replace(tzinfo=timezone.utc)).total_seconds()
    if age <= ttl:
        status = FreshnessStatus.FRESH
    elif age <= ttl * 2:
        status = FreshnessStatus.STALE
    else:
        status = FreshnessStatus.EXPIRED

    return TtlWindow(
        data_type=data_type, fetched_at=fetched_at, ttl_seconds=ttl,
        freshness_status=status, source=source,
    )


def _compute_price_band(nd, market_data: dict, currency: str) -> PriceBand:
    prices = market_data.get("prices", [])
    if prices:
        values = sorted([_safe_decimal(p.get("unit_price", 0)) for p in prices])
        floor = values[0]
        ceiling = values[-1]
        mid = sum(values, Decimal(0)) / len(values)
    else:
        # Fallback to heuristic estimator
        est = estimate_cost(
            category=nd.category, material=nd.material,
            quantity=nd.quantity, is_custom=nd.is_custom, has_mpn=nd.has_mpn,
        )
        floor = _safe_decimal(est["unit_cost_low"])
        mid = _safe_decimal(est["unit_cost_mid"])
        ceiling = _safe_decimal(est["unit_cost_high"])

    return PriceBand(
        floor=Money(amount=str(floor.quantize(Decimal("0.01"))), currency=currency),
        mid=Money(amount=str(mid.quantize(Decimal("0.01"))), currency=currency),
        ceiling=Money(amount=str(ceiling.quantize(Decimal("0.01"))), currency=currency),
    )


def _compute_risk_flags(nd, price_band: PriceBand, tariff: TariffEnrichment, logistics: LogisticsEnrichment) -> list[RiskFlag]:
    flags: list[RiskFlag] = []
    if nd.is_custom:
        flags.append(RiskFlag(flag_type=RiskFlagType.CUSTOM_PART, severity="medium", mitigation="Request multiple quotes", data_source="classification"))
    if not nd.has_mpn and not nd.is_custom:
        flags.append(RiskFlag(flag_type=RiskFlagType.NO_MPN, severity="low", mitigation="Verify part specification", data_source="classification"))
    if nd.procurement_class in ("custom_fabrication", "subassembly"):
        flags.append(RiskFlag(flag_type=RiskFlagType.SOLE_SOURCE, severity="high", mitigation="Identify alternative fabricators", data_source="classification"))
    mat_lower = (nd.material or "").lower()
    exotic = ["titanium", "inconel", "peek", "carbon fiber"]
    if any(m in mat_lower for m in exotic):
        flags.append(RiskFlag(flag_type=RiskFlagType.EXOTIC_MATERIAL, severity="medium", mitigation="Verify availability and lead time", data_source="material_analysis"))
    if tariff.duty_rate_pct > 15:
        flags.append(RiskFlag(flag_type=RiskFlagType.HIGH_TARIFF, severity="medium", mitigation=f"Duty rate {tariff.duty_rate_pct}% — explore FTA options", data_source="tariff_data"))
    mid_val = _safe_decimal(price_band.mid.amount) * nd.quantity
    if mid_val > 500:
        flags.append(RiskFlag(flag_type=RiskFlagType.HIGH_VALUE, severity="low", mitigation="Consider volume discounts", data_source="price_estimate"))
    return flags


def enrich_bom_line(request: EnrichmentRequest) -> EnrichmentResponse:
    """Execute the enrichment pipeline."""
    nd = request.normalized_data
    currency = request.project_context.preferred_currency or "USD"
    bom_line_id_str = str(request.bom_line_id)
    freshness_entries: list[TtlWindow] = []

    # Market data
    market_data = nd.market_data_cache
    pricing_freshness = _check_freshness(market_data, "pricing")
    freshness_entries.append(pricing_freshness)
    price_band = _compute_price_band(nd, market_data, currency)

    # Tariff data
    tariff_data = nd.tariff_data_cache
    tariff_freshness = _check_freshness(tariff_data, "tariff")
    freshness_entries.append(tariff_freshness)
    tariff = TariffEnrichment(
        hs_code=tariff_data.get("hs_code"),
        duty_rate_pct=float(tariff_data.get("duty_rate_pct", 0)),
        fta_eligible=bool(tariff_data.get("fta_eligible", False)),
        data_source=tariff_data.get("source", "estimated"),
        data_freshness=tariff_freshness,
    )

    # Logistics data
    logistics_data = nd.logistics_data_cache
    logistics_freshness = _check_freshness(logistics_data, "logistics")
    freshness_entries.append(logistics_freshness)
    freight_val = logistics_data.get("freight_estimate")
    lead_time_band_data = logistics_data.get("lead_time_band")
    if not lead_time_band_data:
        lt_est = estimate_lead_time(nd.procurement_class, nd.category, nd.quantity)
        lead_time_band_data = {
            "low_days": lt_est["lead_time_low_days"],
            "mid_days": lt_est["lead_time_mid_days"],
            "high_days": lt_est["lead_time_high_days"],
        }
    logistics = LogisticsEnrichment(
        freight_estimate=Money(amount=str(freight_val), currency=currency) if freight_val else None,
        lead_time_band=lead_time_band_data,
        data_freshness=logistics_freshness,
    )

    # Risk flags
    risk_flags = _compute_risk_flags(nd, price_band, tariff, logistics)

    # Events
    events: list[EngineEventSchema] = []
    evt = build_event(
        EventTypes.ENRICHMENT_COMPLETED, bom_line_id_str,
        idempotency_key=request.idempotency_key,
        payload={"category": nd.category, "risk_count": len(risk_flags)},
    )
    events.append(EngineEventSchema(**evt.to_dict()))

    stale = [f for f in freshness_entries if f.freshness_status in (FreshnessStatus.STALE, FreshnessStatus.EXPIRED)]
    if stale:
        stale_evt = build_event(
            EventTypes.ENRICHMENT_STALE_DATA, bom_line_id_str,
            idempotency_key=request.idempotency_key,
            payload={"stale_sources": [s.data_type for s in stale]},
        )
        events.append(EngineEventSchema(**stale_evt.to_dict()))

    return EnrichmentResponse(
        bom_line_id=request.bom_line_id,
        market_enrichment=MarketEnrichment(
            price_band=price_band,
            sources=market_data.get("sources", []),
            data_freshness=pricing_freshness,
        ),
        tariff_enrichment=tariff,
        logistics_enrichment=logistics,
        risk_flags=risk_flags,
        data_freshness_summary=freshness_entries,
        events=events,
    )
