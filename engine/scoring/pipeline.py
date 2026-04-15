"""Scoring pipeline per PC-004, PC-005, WF-SCORE-001.

6-step vendor matching: Hard Filter → Technical Fit → Commercial Fit →
Operational Fit → Strategic Fit → Confidence Model.
5-dimension scoring: cost, lead_time, quality, strategic_fit, operational_capability.
"""
from __future__ import annotations
from core.events import EventTypes, build_event
from core.schemas import (
    ConfidenceLevel, EngineEventSchema, ScoringRequest, ScoringResponse,
    VendorScoreEntry,
)
from engine.scoring.tlc import compute_tlc
from engine.scoring.weight_profiles import WEIGHT_PROFILES


def _score_cost(vendor, enrichment_data) -> float:
    if not vendor.unit_price:
        return 50.0
    price = float(vendor.unit_price)
    me = enrichment_data.market_enrichment
    if me and me.price_band:
        mid = float(me.price_band.mid.amount or 0)
        if mid > 0:
            ratio = price / mid
            return max(0, min(100, 100 * (1.5 - ratio)))
    return 50.0


def _score_lead_time(vendor, enrichment_data) -> float:
    if not vendor.lead_time_days:
        return 50.0
    le = enrichment_data.logistics_enrichment
    if le and le.lead_time_band:
        mid_days = le.lead_time_band.get("mid_days", 14)
        if mid_days > 0:
            ratio = vendor.lead_time_days / mid_days
            return max(0, min(100, 100 * (1.5 - ratio)))
    return max(0, min(100, 100 - vendor.lead_time_days * 2))


def _score_quality(vendor) -> float:
    base = 50.0
    if vendor.quality_rating is not None:
        base = vendor.quality_rating * 20  # 0-5 scale → 0-100
    cert_bonus = min(20, len(vendor.certifications) * 5)
    return min(100, base + cert_bonus)


def _score_strategic_fit(vendor, project_context) -> float:
    score = 50.0
    if project_context.target_country and vendor.country_code:
        if vendor.country_code.upper() == project_context.target_country.upper():
            score += 25  # local source bonus
    return min(100, score)


def _score_operational(vendor) -> float:
    score = 50.0
    if vendor.on_time_rate is not None:
        score = vendor.on_time_rate * 100
    if vendor.response_speed_hours and vendor.response_speed_hours < 24:
        score = min(100, score + 10)
    return min(100, score)


def _passes_hard_filter(vendor, enrichment_data) -> tuple[bool, str | None]:
    if enrichment_data.is_custom and not vendor.capabilities:
        return False, "Vendor has no listed capabilities for custom fabrication"
    if vendor.moq and enrichment_data.quantity < vendor.moq:
        return False, f"Quantity {enrichment_data.quantity} below vendor MOQ {vendor.moq}"
    return True, None


def _determine_confidence(vendor) -> ConfidenceLevel:
    data_points = 0
    if vendor.unit_price:
        data_points += 1
    if vendor.lead_time_days is not None:
        data_points += 1
    if vendor.quality_rating is not None:
        data_points += 1
    if vendor.on_time_rate is not None:
        data_points += 1
    if data_points >= 3:
        return ConfidenceLevel.HIGH
    if data_points >= 2:
        return ConfidenceLevel.MEDIUM
    return ConfidenceLevel.LOW


def score_bom_line(request: ScoringRequest) -> ScoringResponse:
    """Execute the 6-step scoring pipeline."""
    profile_name = request.weight_profile.value
    weights = WEIGHT_PROFILES[profile_name]
    bom_line_id_str = str(request.bom_line_id)
    vendor_scores: list[VendorScoreEntry] = []

    for vendor in request.candidate_vendors:
        # Step 1: Hard Filter
        passes, reason = _passes_hard_filter(vendor, request.enrichment_data)
        if not passes:
            vendor_scores.append(VendorScoreEntry(
                vendor_id=vendor.vendor_id,
                eliminated=True,
                elimination_reason=reason,
            ))
            continue

        # Steps 2-5: Dimension scoring
        cost_s = _score_cost(vendor, request.enrichment_data)
        lt_s = _score_lead_time(vendor, request.enrichment_data)
        qual_s = _score_quality(vendor)
        strat_s = _score_strategic_fit(vendor, request.project_context)
        ops_s = _score_operational(vendor)

        # Composite
        composite = round(
            cost_s * weights["cost"]
            + lt_s * weights["lead_time"]
            + qual_s * weights["quality"]
            + strat_s * weights["strategic_fit"]
            + ops_s * weights["operational_capability"],
            2,
        )

        # Step 6: Confidence
        confidence_level = _determine_confidence(vendor)

        # TLC
        tlc_result = compute_tlc(
            vendor, request.enrichment_data, request.project_context,
            currency=vendor.currency or "USD",
        )

        explanation = (
            f"Composite score {composite:.1f}/100 "
            f"(cost={cost_s:.0f}, lead_time={lt_s:.0f}, quality={qual_s:.0f}, "
            f"strategic_fit={strat_s:.0f}, ops={ops_s:.0f}) "
            f"using {profile_name} profile. "
            f"TLC: {tlc_result['total'].amount} {tlc_result['total'].currency}. "
            f"Confidence: {confidence_level.value}."
        )

        vendor_scores.append(VendorScoreEntry(
            vendor_id=vendor.vendor_id,
            composite_score=composite,
            dimension_scores={
                "cost": round(cost_s, 2),
                "lead_time": round(lt_s, 2),
                "quality": round(qual_s, 2),
                "strategic_fit": round(strat_s, 2),
                "operational_capability": round(ops_s, 2),
            },
            tlc=tlc_result["total"],
            tlc_breakdown=tlc_result["breakdown"],
            confidence_level=confidence_level,
            eliminated=False,
            elimination_reason=None,
            explanation=explanation,
        ))

    # Sort non-eliminated by composite descending
    vendor_scores.sort(
        key=lambda v: v.composite_score if not v.eliminated else -1, reverse=True
    )

    events: list[EngineEventSchema] = []
    evt = build_event(
        EventTypes.SCORING_COMPLETED, bom_line_id_str,
        idempotency_key=request.idempotency_key,
        payload={"vendor_count": len(vendor_scores), "profile": profile_name},
    )
    events.append(EngineEventSchema(**evt.to_dict()))

    return ScoringResponse(
        bom_line_id=request.bom_line_id,
        vendor_scores=vendor_scores,
        weight_profile_applied=weights,
        data_sources_snapshot={"profile": profile_name},
        events=events,
    )
