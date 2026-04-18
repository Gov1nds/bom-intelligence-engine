"""Normalization pipeline per PC-002, WF-NORM-001, GAP-035.

Upgraded pipeline order:
1. OCR healing
2. Text normalization
3. Tokenization
4. Unit normalization
5. Classification
6. Domain dispatch
7. Domain-aware confidence scoring
8. Part master matching
9. Canonical output
10. Review & uncertainty flags
11. Learning signals
"""
from __future__ import annotations

import re
import time
from typing import Any

from core.config import config
from core.events import EventTypes, build_event
from core.schemas import (
    SCHEMA_VERSION, AmbiguityFlag, EngineEventSchema,
    NormalizationRequest, NormalizationResponse, NormalizationTraceOutput,
    NormalizedItem,
)
from engine.normalization.ocr_healer import OcrHealer
from engine.normalization.part_master_matcher import match_against_part_master
from engine.normalization.tokenizer import Token, tokenize_raw_text
from engine.normalization.unit_converter import normalize_units
from engine.normalization.text_normalizer import normalize_text
from engine.classification.classifier import classify_from_tokens
from engine.specs.spec_extractor import extract_specs_from_tokens
from engine.specs.domain_dispatcher import DomainDispatcher
from engine.scoring.confidence import compute_domain_confidence
from engine.canonical.canonical_output import build_canonical_output
from engine.review.review_flags import detect_review_and_uncertainty_flags
from engine.learning.signal_builder import build_learning_signals


SPLIT_PATTERN = re.compile(r"\b(and|&|\+|with)\b", re.I)

_ocr_healer = OcrHealer()
_domain_dispatcher = DomainDispatcher()


def _extract_mpn(tokens: list[Token]) -> str | None:
    for t in tokens:
        if t.token_type == "part_number_fragment":
            return t.value
    return None


def _extract_quantity(tokens: list[Token]) -> int | None:
    for t in tokens:
        if t.token_type == "value_unit_pair" and t.normalized_value:
            if any(u in t.value.lower() for u in ("ea", "pcs", "nos")):
                try:
                    return int(float(re.search(r"\d+", t.value).group()))
                except Exception:
                    pass
    return None


def _extract_unit(tokens: list[Token]) -> str | None:
    for t in tokens:
        if t.token_type == "value_unit_pair":
            for u in ("mm", "cm", "m", "in", "kg", "g", "lb"):
                if u in t.value.lower():
                    return u
    return None


def _detect_split(raw_text: str, tokens: list[Token]) -> tuple[bool, list[dict] | None]:
    parts = SPLIT_PATTERN.split(raw_text)
    meaningful = [p.strip() for p in parts if p.strip() and not SPLIT_PATTERN.match(p)]
    if len(meaningful) >= 2:
        return True, [{"candidate_text": p} for p in meaningful]
    return False, None


def _compute_field_completeness(tokens: list[Token]) -> float:
    types_found = {t.token_type for t in tokens}
    key_types = {"value_unit_pair", "dimension", "material_reference", "part_number_fragment"}
    return len(types_found & key_types) / len(key_types)


def _compute_ambiguity_flags(
    tokens: list[Token], candidates: list, confidence: float
) -> list[AmbiguityFlag]:
    flags: list[AmbiguityFlag] = []
    if confidence < 0.5:
        flags.append(AmbiguityFlag(
            flag_type="low_confidence",
            reason="Overall confidence below manual review threshold",
            impact_on_confidence=-0.2,
        ))
    type_counts: dict[str, int] = {}
    for t in tokens:
        type_counts[t.token_type] = type_counts.get(t.token_type, 0) + 1
    if type_counts.get("material_reference", 0) > 1:
        flags.append(AmbiguityFlag(
            flag_type="multiple_materials",
            reason="Multiple material references detected",
            impact_on_confidence=-0.1,
        ))
    if len(candidates) > 1:
        top_scores = [c.similarity_score for c in candidates[:2]]
        if len(top_scores) == 2 and abs(top_scores[0] - top_scores[1]) < 0.05:
            flags.append(AmbiguityFlag(
                flag_type="close_match_scores",
                reason="Top candidates have similar scores",
                impact_on_confidence=-0.05,
            ))
    return flags


def _merge_attributes(spec_attrs: dict[str, Any], domain_attrs: dict[str, Any]) -> dict[str, Any]:
    """Merge domain extractor attributes into spec attributes. Spec wins on conflict."""
    merged = dict(spec_attrs)
    for key, value in domain_attrs.items():
        if value is not None and key not in merged:
            merged[key] = value
    return merged


def normalize_bom_line(
    request: NormalizationRequest, part_master_index: object | None = None
) -> NormalizationResponse:
    """Execute the canonical normalization pipeline."""
    t0 = time.monotonic()
    bom_line_id_str = str(request.bom_line_id)

    # 1. OCR healing
    try:
        healed_text, healing_ops = _ocr_healer.heal(request.raw_text)
        ocr_healing_applied = len(healing_ops) > 0
    except Exception:
        healed_text = request.raw_text
        healing_ops = []
        ocr_healing_applied = False

    # 2. Text normalization
    normalized_text, text_trace = normalize_text(healed_text)

    # 3. Tokenization
    tokens = tokenize_raw_text(normalized_text)

    # 4. Unit normalization
    normalized_tokens, unit_trace = normalize_units(tokens)

    # 5. Classification
    category, subcategory, classification_confidence, classification_reason = (
        classify_from_tokens(normalized_tokens, normalized_text)
    )

    # 6. Domain dispatch
    try:
        domain_result = _domain_dispatcher.dispatch(category, normalized_text, normalized_tokens)
    except Exception:
        from engine.specs.extractors.base import DomainExtractionResult
        domain_result = DomainExtractionResult()

    # Also run existing spec extractor for backward compat
    spec_json = extract_specs_from_tokens(normalized_tokens, normalized_text)

    # Merge domain attributes
    existing_attrs = spec_json.get("attributes", {}) if isinstance(spec_json, dict) else {}
    merged_attrs = _merge_attributes(existing_attrs, domain_result.attributes)
    if merged_attrs:
        spec_json["attributes"] = merged_attrs

    # 7. Confidence scoring
    mpn = _extract_mpn(normalized_tokens)
    candidates = match_against_part_master(
        normalized_tokens, normalized_text, category, mpn=mpn,
        part_master_index=part_master_index,
    )
    best_match = candidates[0] if candidates else None

    word_count = max(len(normalized_text.split()), 1)
    token_coverage = min(1.0, len(normalized_tokens) / word_count)

    try:
        confidence_breakdown = compute_domain_confidence(
            category=category,
            classification_confidence=classification_confidence,
            attributes=merged_attrs,
            token_coverage=token_coverage,
            missing_critical=domain_result.missing_critical,
            ambiguity_flags=[],
            ocr_healing_applied=ocr_healing_applied,
        )
        confidence = confidence_breakdown.overall
    except Exception:
        field_completeness = _compute_field_completeness(normalized_tokens)
        confidence = round(min(1.0, max(0.0,
            classification_confidence * 0.35
            + (best_match.similarity_score if best_match else 0.0) * 0.30
            + token_coverage * 0.15
            + field_completeness * 0.20
        )), 4)

    confidence = round(min(1.0, confidence + domain_result.confidence_boost), 4)

    review_required = confidence < config.CONFIDENCE_AUTO_THRESHOLD
    review_reason = None
    if confidence < config.CONFIDENCE_REVIEW_REQUIRED_THRESHOLD:
        review_reason = "Confidence below manual review threshold"
    elif confidence < config.CONFIDENCE_AUTO_THRESHOLD:
        review_reason = "Confidence below auto-normalize threshold; human review recommended"

    # 9. Canonical output
    canonical_output = build_canonical_output(category, subcategory, normalized_text, spec_json)
    part_name = canonical_output["canonical_name"] or (
        best_match.canonical_name
        if best_match and best_match.part_master_id
        else normalized_text[:120]
    )
    canonical_key = canonical_output["normalized_part_key"]

    # 10. Review flags
    split_detected, split_candidates = _detect_split(normalized_text, tokens)
    ambiguity_flags = _compute_ambiguity_flags(tokens, candidates, confidence)
    review_flags, uncertainty_flags = detect_review_and_uncertainty_flags(
        category=category,
        classification_confidence=classification_confidence,
        spec_json=spec_json,
        canonical_output=canonical_output,
        normalized_text=normalized_text,
        ambiguity_flags=[f.flag_type for f in ambiguity_flags],
    )

    # 11. Learning signals
    learning_signals = build_learning_signals(
        raw_input=request.raw_text,
        normalized_text=normalized_text,
        canonical_name=canonical_output["canonical_name"],
        normalized_part_key=canonical_output["normalized_part_key"],
        category=category,
        category_confidence=classification_confidence,
        spec_json=spec_json,
        review_flags=review_flags,
        uncertainty_flags=uncertainty_flags,
    )

    # ML features if enabled
    if config.EMIT_ML_FEATURES:
        try:
            from engine.ml.feature_builder import build_feature_vector
            from engine.ml.embedding_signal import build_embedding_signal
            learning_signals["ml_feature_vector"] = build_feature_vector(
                category, merged_attrs, confidence, review_flags + uncertainty_flags)
            learning_signals["embedding_signal"] = build_embedding_signal(
                canonical_output["canonical_name"], category, merged_attrs)
        except Exception:
            pass

    learning_signals["domain_extraction_method"] = domain_result.extraction_method
    learning_signals["missing_critical_attributes"] = domain_result.missing_critical

    processing_time_ms = (time.monotonic() - t0) * 1000
    trace = NormalizationTraceOutput(
        tokens_extracted=[t.to_dict() for t in tokens],
        unit_conversion_applied=text_trace.unit_normalizations + unit_trace,
        abbreviations_expanded=text_trace.abbreviation_expansions,
        candidate_matches=[c.to_dict() for c in candidates],
        selected_match_confidence=best_match.similarity_score if best_match else None,
        ambiguity_flags=ambiguity_flags,
        review_required=review_required,
        review_reason=review_reason,
        split_detected=split_detected,
        processing_time_ms=round(processing_time_ms, 2),
    )

    events: list[EngineEventSchema] = []
    evt_type = (
        EventTypes.NORMALIZATION_REVIEW_REQUIRED
        if review_required
        else EventTypes.NORMALIZATION_COMPLETED
    )
    evt = build_event(
        evt_type, bom_line_id_str,
        idempotency_key=request.idempotency_key,
        payload={"confidence": confidence, "category": category, "normalized_text": normalized_text},
    )
    events.append(EngineEventSchema(**evt.to_dict()))

    if split_detected:
        split_evt = build_event(
            EventTypes.NORMALIZATION_SPLIT_PROPOSED, bom_line_id_str,
            idempotency_key=request.idempotency_key,
            payload={"split_candidates": split_candidates},
        )
        events.append(EngineEventSchema(**split_evt.to_dict()))

    return NormalizationResponse(
        bom_line_id=request.bom_line_id,
        normalized=NormalizedItem(
            part_name=part_name,
            category=category,
            subcategory=subcategory,
            spec_json=spec_json,
            quantity=_extract_quantity(normalized_tokens) or 1,
            unit=_extract_unit(normalized_tokens) or "each",
            manufacturer_part_number=mpn,
            canonical_name=canonical_output["canonical_name"],
            normalized_part_key=canonical_output["normalized_part_key"],
            canonical_key=canonical_key,
            suggested_processes=canonical_output["suggested_processes"],
            requires_rfq=canonical_output["requires_rfq"],
            drawing_required=canonical_output["drawing_required"],
            review_flags=review_flags,
            uncertainty_flags=uncertainty_flags,
            learning_signals=learning_signals,
        ),
        confidence=confidence,
        ambiguity_flags=[f.flag_type for f in ambiguity_flags],
        split_detected=split_detected,
        split_candidates=split_candidates,
        merge_candidate_ids=None,
        matched_part_master_id=(
            best_match.part_master_id if best_match and best_match.part_master_id else None
        ),
        normalization_trace=trace,
        model_version=SCHEMA_VERSION,
        events=events,
    )
