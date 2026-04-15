"""Engine event builder per events.yaml EVT-NORM-*, EVT-ENRICH-*, EVT-SCORE-*."""
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from uuid import uuid4


@dataclass
class EngineEvent:
    event_id: str
    event_type: str
    bom_line_id: str
    correlation_id: str
    idempotency_key: str
    timestamp: str
    payload: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


class EventTypes:
    NORMALIZATION_COMPLETED = "normalization.completed"
    NORMALIZATION_REVIEW_REQUIRED = "normalization.review_required"
    NORMALIZATION_FAILED = "normalization.failed"
    NORMALIZATION_SPLIT_PROPOSED = "normalization.split_proposed"
    NORMALIZATION_MERGE_PROPOSED = "normalization.merge_proposed"
    ENRICHMENT_COMPLETED = "enrichment.completed"
    ENRICHMENT_FAILED = "enrichment.failed"
    ENRICHMENT_STALE_DATA = "enrichment.stale_data_detected"
    SCORING_COMPLETED = "scoring.completed"
    STRATEGY_COMPUTED = "strategy.computed"
    SUBSTITUTION_IDENTIFIED = "substitution.identified"
    CONSOLIDATION_COMPUTED = "consolidation.computed"


def build_event(
    event_type: str,
    bom_line_id: str,
    correlation_id: str = "",
    idempotency_key: str = "",
    payload: dict | None = None,
) -> EngineEvent:
    return EngineEvent(
        event_id=str(uuid4()),
        event_type=event_type,
        bom_line_id=bom_line_id,
        correlation_id=correlation_id or str(uuid4()),
        idempotency_key=idempotency_key,
        timestamp=datetime.now(timezone.utc).isoformat(),
        payload=payload or {},
    )
