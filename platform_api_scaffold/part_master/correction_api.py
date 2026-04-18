"""Part Master Correction API — FastAPI router for platform-api.

NOTE: This belongs to platform-api, NOT bom-intelligence-engine.
Provides endpoints for human correction and approval workflows.
"""
from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from platform_api_scaffold.part_master.models import (
    CanonicalOverride,
    CorrectionEntry,
)

router = APIRouter(prefix="/part-master", tags=["part-master"])


class CategoryCorrectionRequest(BaseModel):
    new_category: str
    corrected_by: str = ""
    reason: str = ""


class AttributeCorrectionRequest(BaseModel):
    attribute_name: str
    old_value: Any = None
    new_value: Any = None
    corrected_by: str = ""


class CanonicalNameCorrectionRequest(BaseModel):
    new_canonical_name: str
    corrected_by: str = ""
    reason: str = ""


class OverrideApprovalRequest(BaseModel):
    approved_canonical_name: str
    approved_category: str
    approved_attributes: dict[str, Any] = Field(default_factory=dict)
    approved_by: str = ""
    override_reason: str = ""


class CorrectionHistoryResponse(BaseModel):
    corrections: list[dict] = Field(default_factory=list)


class ReviewQueueItem(BaseModel):
    part_master_id: UUID
    normalized_part_key: str
    canonical_name: str
    category: str
    review_status: str
    occurrence_count: int
    raw_input_samples: list[str] = Field(default_factory=list)


class ReviewQueueResponse(BaseModel):
    items: list[ReviewQueueItem] = Field(default_factory=list)
    total: int = 0


# ── Endpoints ──

@router.post("/{part_master_id}/correct-category")
async def correct_category(
    part_master_id: UUID,
    request: CategoryCorrectionRequest,
) -> dict[str, str]:
    """Submit a category correction for a Part Master record."""
    # In production: inject PartMasterIngestionService via dependency
    # service.record_correction(part_master_id, CorrectionEntry(...))
    return {"status": "correction_recorded", "part_master_id": str(part_master_id)}


@router.post("/{part_master_id}/correct-attribute")
async def correct_attribute(
    part_master_id: UUID,
    request: AttributeCorrectionRequest,
) -> dict[str, str]:
    """Submit an attribute correction for a Part Master record."""
    return {"status": "correction_recorded", "part_master_id": str(part_master_id)}


@router.post("/{part_master_id}/correct-canonical-name")
async def correct_canonical_name(
    part_master_id: UUID,
    request: CanonicalNameCorrectionRequest,
) -> dict[str, str]:
    """Submit a canonical name correction."""
    return {"status": "correction_recorded", "part_master_id": str(part_master_id)}


@router.post("/{part_master_id}/approve-override")
async def approve_override(
    part_master_id: UUID,
    request: OverrideApprovalRequest,
) -> dict[str, str]:
    """Approve a pending canonical override."""
    return {"status": "override_approved", "part_master_id": str(part_master_id)}


@router.get("/{part_master_id}/correction-history", response_model=CorrectionHistoryResponse)
async def get_correction_history(part_master_id: UUID) -> CorrectionHistoryResponse:
    """View all corrections for a Part Master record."""
    return CorrectionHistoryResponse(corrections=[])


@router.get("/review-queue", response_model=ReviewQueueResponse)
async def get_review_queue() -> ReviewQueueResponse:
    """List records needing review."""
    return ReviewQueueResponse(items=[], total=0)
