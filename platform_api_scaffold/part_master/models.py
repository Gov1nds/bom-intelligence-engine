"""Part Master Index — Data models for platform-api.

NOTE: This module belongs to platform-api, NOT bom-intelligence-engine.
The analyser remains stateless. These models define the data structures
that platform-api uses to store, query, and learn from analyser output.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class ConfidenceHistoryEntry(BaseModel):
    """Tracks confidence evolution over time."""
    confidence: float
    timestamp: datetime
    model_version: str
    extraction_quality: str = "unknown"


class CorrectionEntry(BaseModel):
    """Audit trail for human corrections."""
    field: str
    old_value: Any = None
    new_value: Any = None
    corrected_by: str = ""
    corrected_at: datetime = Field(default_factory=datetime.utcnow)
    source: str = "manual"


class CanonicalOverride(BaseModel):
    """Human-approved override of analyser output."""
    approved_canonical_name: str
    approved_category: str
    approved_attributes: dict[str, Any] = Field(default_factory=dict)
    approved_by: str = ""
    approved_at: datetime = Field(default_factory=datetime.utcnow)
    override_reason: str = ""


class ProvenanceRecord(BaseModel):
    """Tracks where a part observation came from."""
    bom_line_id: Optional[UUID] = None
    project_id: Optional[str] = None
    upload_timestamp: Optional[datetime] = None
    analyser_version: str = ""


class PartMasterRecord(BaseModel):
    """Core Part Master record — the canonical representation of a part.

    Each unique `normalized_part_key` from the analyser maps to one
    PartMasterRecord. Multiple raw BOM inputs that normalize to the
    same key merge into a single record.
    """
    part_master_id: UUID = Field(default_factory=uuid4)
    normalized_part_key: str = Field(..., description="Stable key from analyser, indexed")
    canonical_name: str = ""
    category: str = "unknown"
    subcategory: Optional[str] = None
    attributes: dict[str, Any] = Field(
        default_factory=dict,
        description="Merged attributes from all observations",
    )
    alias_keys: list[str] = Field(
        default_factory=list,
        description="Other normalized_part_keys that map to this record",
    )
    raw_input_samples: list[str] = Field(
        default_factory=list,
        description="Up to 10 observed raw inputs",
    )
    occurrence_count: int = 0
    confidence_history: list[ConfidenceHistoryEntry] = Field(default_factory=list)
    correction_log: list[CorrectionEntry] = Field(default_factory=list)
    canonical_override: Optional[CanonicalOverride] = None
    source_provenance: list[ProvenanceRecord] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    review_status: str = Field(
        default="auto",
        description="auto|needs_review|approved|rejected",
    )
    ml_feature_vector: Optional[dict[str, float]] = None


class SimilarityResult(BaseModel):
    """Result from a similarity search."""
    part_master_id: UUID
    canonical_name: str = ""
    similarity_score: float = 0.0
    match_method: str = ""


class CoverageStats(BaseModel):
    """Part Master coverage statistics."""
    total_parts: int = 0
    by_category: dict[str, int] = Field(default_factory=dict)
    avg_confidence: float = 0.0
    review_pending: int = 0


class LowConfidencePattern(BaseModel):
    """Identifies recurring low-confidence input patterns."""
    category: str
    pattern_description: str = ""
    occurrence_count: int = 0
    typical_raw_inputs: list[str] = Field(default_factory=list)
