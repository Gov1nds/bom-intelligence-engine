"""Part Master Ingestion Service — platform-api module.

NOTE: This belongs to platform-api, NOT bom-intelligence-engine.
Called after each analyser normalization response to ingest learning signals
and build/update the Part Master Index.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from platform_api_scaffold.part_master.models import (
    CanonicalOverride,
    ConfidenceHistoryEntry,
    CorrectionEntry,
    PartMasterRecord,
)


def _jaro_winkler_similarity(s1: str, s2: str) -> float:
    """Simplified Jaro-Winkler similarity for alias detection."""
    if s1 == s2:
        return 1.0
    if not s1 or not s2:
        return 0.0
    max_dist = max(len(s1), len(s2)) // 2 - 1
    if max_dist < 0:
        max_dist = 0
    s1_matches = [False] * len(s1)
    s2_matches = [False] * len(s2)
    matches = 0
    transpositions = 0
    for i in range(len(s1)):
        start = max(0, i - max_dist)
        end = min(len(s2), i + max_dist + 1)
        for j in range(start, end):
            if s2_matches[j] or s1[i] != s2[j]:
                continue
            s1_matches[i] = True
            s2_matches[j] = True
            matches += 1
            break
    if matches == 0:
        return 0.0
    k = 0
    for i in range(len(s1)):
        if not s1_matches[i]:
            continue
        while not s2_matches[k]:
            k += 1
        if s1[i] != s2[k]:
            transpositions += 1
        k += 1
    jaro = (matches / len(s1) + matches / len(s2) + (matches - transpositions / 2) / matches) / 3
    # Winkler prefix bonus
    prefix_len = 0
    for i in range(min(4, min(len(s1), len(s2)))):
        if s1[i] == s2[i]:
            prefix_len += 1
        else:
            break
    return jaro + prefix_len * 0.1 * (1 - jaro)


class PartMasterIngestionService:
    """Ingests analyser output into the Part Master Index.

    In production, this would be backed by a database (PostgreSQL, etc.).
    This scaffold uses an in-memory dict for design illustration.
    """

    def __init__(self) -> None:
        self._records: dict[str, PartMasterRecord] = {}
        self._alias_map: dict[str, str] = {}  # alias_key → canonical_key

    def ingest_learning_signal(
        self,
        bom_line_id: UUID,
        learning_signal: dict[str, Any],
    ) -> None:
        """Called after each analyser normalization response."""
        key = learning_signal.get("normalized_part_key", "")
        if not key:
            return
        self.upsert_part_record(
            normalized_part_key=key,
            canonical_name=learning_signal.get("canonical_name", ""),
            category=learning_signal.get("category", "unknown"),
            attributes=learning_signal.get("attributes", {}),
            confidence=learning_signal.get("category_confidence", 0.0),
            raw_input=learning_signal.get("raw_input", ""),
            model_version=learning_signal.get("model_version", ""),
            extraction_quality=learning_signal.get("extraction_quality", "unknown"),
        )

    def upsert_part_record(
        self,
        normalized_part_key: str,
        canonical_name: str,
        category: str,
        attributes: dict[str, Any],
        confidence: float = 0.0,
        raw_input: str = "",
        model_version: str = "",
        extraction_quality: str = "unknown",
    ) -> PartMasterRecord:
        """Create or update a Part Master record."""
        # Check alias map first
        canonical_key = self._alias_map.get(normalized_part_key, normalized_part_key)

        if canonical_key in self._records:
            record = self._records[canonical_key]
            # Merge attributes (union of all observed values)
            for k, v in attributes.items():
                if v is not None and (k not in record.attributes or record.attributes[k] is None):
                    record.attributes[k] = v
            record.occurrence_count += 1
            # Update canonical name if higher confidence
            if confidence > (record.confidence_history[-1].confidence if record.confidence_history else 0):
                record.canonical_name = canonical_name
            record.confidence_history.append(ConfidenceHistoryEntry(
                confidence=confidence,
                timestamp=datetime.utcnow(),
                model_version=model_version,
                extraction_quality=extraction_quality,
            ))
            if raw_input and len(record.raw_input_samples) < 10:
                if raw_input not in record.raw_input_samples:
                    record.raw_input_samples.append(raw_input)
            record.updated_at = datetime.utcnow()
        else:
            record = PartMasterRecord(
                normalized_part_key=canonical_key,
                canonical_name=canonical_name,
                category=category,
                attributes=attributes,
                occurrence_count=1,
                raw_input_samples=[raw_input] if raw_input else [],
                confidence_history=[ConfidenceHistoryEntry(
                    confidence=confidence,
                    timestamp=datetime.utcnow(),
                    model_version=model_version,
                    extraction_quality=extraction_quality,
                )],
            )
            self._records[canonical_key] = record

            # Fuzzy alias detection against existing records
            self._detect_fuzzy_aliases(canonical_key)

        return record

    def register_alias(self, source_key: str, canonical_key: str) -> None:
        """Register an alias mapping."""
        self._alias_map[source_key] = canonical_key
        if canonical_key in self._records:
            record = self._records[canonical_key]
            if source_key not in record.alias_keys:
                record.alias_keys.append(source_key)

    def record_correction(
        self,
        part_master_id: UUID,
        correction: CorrectionEntry,
    ) -> None:
        """Record a human correction."""
        for record in self._records.values():
            if record.part_master_id == part_master_id:
                record.correction_log.append(correction)
                # Apply the correction
                if correction.field in ("category", "canonical_name"):
                    setattr(record, correction.field, correction.new_value)
                elif correction.field.startswith("attributes."):
                    attr_key = correction.field.split(".", 1)[1]
                    record.attributes[attr_key] = correction.new_value
                record.review_status = "approved"
                record.updated_at = datetime.utcnow()
                return

    def apply_canonical_override(
        self,
        part_master_id: UUID,
        override: CanonicalOverride,
    ) -> None:
        """Apply a canonical override to a record."""
        for record in self._records.values():
            if record.part_master_id == part_master_id:
                record.canonical_override = override
                record.canonical_name = override.approved_canonical_name
                record.category = override.approved_category
                record.attributes.update(override.approved_attributes)
                record.review_status = "approved"
                record.updated_at = datetime.utcnow()
                return

    def _detect_fuzzy_aliases(self, new_key: str) -> list[tuple[str, float]]:
        """Detect potential aliases by comparing with existing keys."""
        candidates: list[tuple[str, float]] = []
        for existing_key in self._records:
            if existing_key == new_key:
                continue
            similarity = _jaro_winkler_similarity(new_key, existing_key)
            if similarity > 0.92:
                candidates.append((existing_key, similarity))
                # Flag for review but do NOT auto-merge
                self._records[new_key].review_status = "needs_review"
        return candidates
