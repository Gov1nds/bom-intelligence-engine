"""Part Master Query Service — platform-api module.

NOTE: This belongs to platform-api, NOT bom-intelligence-engine.
Provides lookup, similarity search, and coverage statistics.
"""
from __future__ import annotations

from typing import Optional

from platform_api_scaffold.part_master.models import (
    CoverageStats,
    LowConfidencePattern,
    PartMasterRecord,
    SimilarityResult,
)
from platform_api_scaffold.part_master.ingestion_service import (
    PartMasterIngestionService,
    _jaro_winkler_similarity,
)


class PartMasterQueryService:
    """Query interface for the Part Master Index."""

    def __init__(self, ingestion_service: PartMasterIngestionService) -> None:
        self._ingestion = ingestion_service

    def lookup_by_key(self, normalized_part_key: str) -> Optional[PartMasterRecord]:
        """Exact lookup by normalized_part_key."""
        canonical = self._ingestion._alias_map.get(
            normalized_part_key, normalized_part_key
        )
        return self._ingestion._records.get(canonical)

    def lookup_by_alias(self, alias_key: str) -> Optional[PartMasterRecord]:
        """Lookup by alias key."""
        canonical = self._ingestion._alias_map.get(alias_key)
        if canonical:
            return self._ingestion._records.get(canonical)
        # Fallback: scan all records for alias
        for record in self._ingestion._records.values():
            if alias_key in record.alias_keys:
                return record
        return None

    def find_similar(
        self,
        normalized_part_key: str,
        top_k: int = 5,
    ) -> list[SimilarityResult]:
        """Find similar parts by key similarity."""
        results: list[SimilarityResult] = []
        for key, record in self._ingestion._records.items():
            if key == normalized_part_key:
                continue
            score = _jaro_winkler_similarity(normalized_part_key, key)
            if score > 0.7:
                results.append(SimilarityResult(
                    part_master_id=record.part_master_id,
                    canonical_name=record.canonical_name,
                    similarity_score=round(score, 4),
                    match_method="jaro_winkler",
                ))
        results.sort(key=lambda r: r.similarity_score, reverse=True)
        return results[:top_k]

    def get_coverage_stats(
        self, category: Optional[str] = None,
    ) -> CoverageStats:
        """Get coverage statistics, optionally filtered by category."""
        records = list(self._ingestion._records.values())
        if category:
            records = [r for r in records if r.category == category]

        by_category: dict[str, int] = {}
        total_confidence = 0.0
        review_pending = 0

        for record in records:
            by_category[record.category] = by_category.get(record.category, 0) + 1
            if record.confidence_history:
                total_confidence += record.confidence_history[-1].confidence
            if record.review_status == "needs_review":
                review_pending += 1

        return CoverageStats(
            total_parts=len(records),
            by_category=by_category,
            avg_confidence=round(total_confidence / max(len(records), 1), 4),
            review_pending=review_pending,
        )

    def get_low_confidence_patterns(
        self, threshold: float = 0.55,
    ) -> list[LowConfidencePattern]:
        """Identify recurring low-confidence input patterns."""
        patterns: dict[str, LowConfidencePattern] = {}
        for record in self._ingestion._records.values():
            if not record.confidence_history:
                continue
            latest = record.confidence_history[-1].confidence
            if latest < threshold:
                cat = record.category
                if cat not in patterns:
                    patterns[cat] = LowConfidencePattern(
                        category=cat,
                        pattern_description=f"Low confidence {cat} parts",
                    )
                patterns[cat].occurrence_count += 1
                if len(patterns[cat].typical_raw_inputs) < 5:
                    for sample in record.raw_input_samples[:2]:
                        if sample not in patterns[cat].typical_raw_inputs:
                            patterns[cat].typical_raw_inputs.append(sample)
        return list(patterns.values())
