"""Strategy recommendation per PC-005, api-contract-review.md §6.3."""
from __future__ import annotations
from core.events import EventTypes, build_event
from core.schemas import (
    EngineEventSchema, StrategyRecommendation, StrategyRequest,
    StrategyResponse,
)


def _select_sourcing_mode(score_data) -> str:
    active = [v for v in score_data.vendor_scores if not v.eliminated]
    if not active:
        return "single_source"
    # High risk → dual or multi
    high_risk = any(
        v.confidence_level.value == "LOW" for v in active
    )
    if high_risk and len(active) >= 3:
        return "multi_source"
    if high_risk and len(active) >= 2:
        return "dual_source"
    return "single_source"


def _find_substitutions(enrichment_data, score_data) -> list[dict]:
    """Stub: substitution requires Part_Master cross-reference."""
    return []


def _detect_consolidation(request: StrategyRequest) -> dict | None:
    """Stub: consolidation requires multi-line BOM context."""
    return None


def _generate_explanation(sourcing_mode: str, recommended: list[str], score_data, enrichment_data) -> str:
    parts = [f"Recommended sourcing mode: {sourcing_mode}."]
    if recommended:
        parts.append(f"Top vendor(s): {', '.join(recommended[:3])}.")
    active = [v for v in score_data.vendor_scores if not v.eliminated]
    if active:
        best = active[0]
        parts.append(
            f"Best composite score: {best.composite_score:.1f}/100 "
            f"(confidence: {best.confidence_level.value})."
        )
    return " ".join(parts)


def compute_strategy(request: StrategyRequest) -> StrategyResponse:
    """Compute sourcing strategy recommendation."""
    bom_line_id_str = str(request.bom_line_id)
    score_data = request.score_data
    enrichment_data = request.enrichment_data

    sourcing_mode = _select_sourcing_mode(score_data)
    recommended = [
        v.vendor_id for v in score_data.vendor_scores if not v.eliminated
    ][:3]

    substitutions = _find_substitutions(enrichment_data, score_data)
    consolidation = _detect_consolidation(request)

    explanation = _generate_explanation(
        sourcing_mode, recommended, score_data, enrichment_data
    )

    # TLC comparison
    tlc_comparison: dict = {}
    for v in score_data.vendor_scores:
        if not v.eliminated and v.tlc:
            tlc_comparison[v.vendor_id] = v.tlc.amount

    events: list[EngineEventSchema] = []
    evt = build_event(
        EventTypes.STRATEGY_COMPUTED, bom_line_id_str,
        idempotency_key=request.idempotency_key,
        payload={"sourcing_mode": sourcing_mode, "recommended_count": len(recommended)},
    )
    events.append(EngineEventSchema(**evt.to_dict()))

    if substitutions:
        sub_evt = build_event(
            EventTypes.SUBSTITUTION_IDENTIFIED, bom_line_id_str,
            idempotency_key=request.idempotency_key,
            payload={"count": len(substitutions)},
        )
        events.append(EngineEventSchema(**sub_evt.to_dict()))

    if consolidation:
        cons_evt = build_event(
            EventTypes.CONSOLIDATION_COMPUTED, bom_line_id_str,
            idempotency_key=request.idempotency_key,
            payload={"consolidation": consolidation},
        )
        events.append(EngineEventSchema(**cons_evt.to_dict()))

    return StrategyResponse(
        bom_line_id=request.bom_line_id,
        strategy_recommendation=StrategyRecommendation(
            sourcing_mode=sourcing_mode,
            recommended_vendor_ids=recommended,
            tlc_comparison=tlc_comparison,
            crossover_quantity=None,
            explanation=explanation,
        ),
        substitution_candidates=substitutions,
        consolidation_signals=consolidation,
        data_freshness_summary=enrichment_data.data_freshness_summary,
        source_evidence=[],
        events=events,
    )
