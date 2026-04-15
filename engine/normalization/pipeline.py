"""Normalization pipeline per PC-002, WF-NORM-001, GAP-035."""
from __future__ import annotations
import re
import time

from core.canonical_key import generate_canonical_key
from core.config import config
from core.events import EventTypes, build_event
from core.schemas import (
    SCHEMA_VERSION, AmbiguityFlag, EngineEventSchema,
    NormalizationRequest, NormalizationResponse, NormalizationTraceOutput,
    NormalizedItem,
)
from engine.normalization.part_master_matcher import match_against_part_master
from engine.normalization.tokenizer import Token, tokenize_raw_text
from engine.normalization.unit_converter import normalize_units
from engine.normalization.text_normalizer import normalize_text
from engine.classification.classifier import classify_from_tokens
from engine.specs.spec_extractor import extract_specs_from_tokens


SPLIT_PATTERN = re.compile(r"\b(and|&|\+|with)\b", re.I)



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



def _compute_confidence(
    classification_confidence: float,
    best_match_similarity: float,
    token_coverage: float,
    field_completeness: float,
) -> float:
    score = (
        classification_confidence * 0.35
        + best_match_similarity * 0.30
        + token_coverage * 0.15
        + field_completeness * 0.20
    )
    return round(min(1.0, max(0.0, score)), 4)



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



def normalize_bom_line(
    request: NormalizationRequest, part_master_index: object | None = None
) -> NormalizationResponse:
    """Execute the canonical normalization pipeline."""
    t0 = time.monotonic()
    bom_line_id_str = str(request.bom_line_id)

    normalized_text, text_trace = normalize_text(request.raw_text)

    tokens = tokenize_raw_text(normalized_text)
    normalized_tokens, unit_trace = normalize_units(tokens)

    category, subcategory, classification_confidence, classification_reason = (
        classify_from_tokens(normalized_tokens, normalized_text)
    )

    mpn = _extract_mpn(normalized_tokens)
    candidates = match_against_part_master(
        normalized_tokens, normalized_text, category, mpn=mpn,
        part_master_index=part_master_index,
    )
    best_match = candidates[0] if candidates else None

    spec_json = extract_specs_from_tokens(normalized_tokens, normalized_text)

    word_count = max(len(normalized_text.split()), 1)
    token_coverage = min(1.0, len(normalized_tokens) / word_count)
    field_completeness = _compute_field_completeness(normalized_tokens)
    confidence = _compute_confidence(
        classification_confidence,
        best_match.similarity_score if best_match else 0.0,
        token_coverage,
        field_completeness,
    )

    review_required = confidence < config.CONFIDENCE_AUTO_THRESHOLD
    review_reason = None
    if confidence < config.CONFIDENCE_REVIEW_REQUIRED_THRESHOLD:
        review_reason = "Confidence below manual review threshold"
    elif confidence < config.CONFIDENCE_AUTO_THRESHOLD:
        review_reason = "Confidence below auto-normalize threshold; human review recommended"

    part_name = (
        best_match.canonical_name
        if best_match and best_match.part_master_id
        else normalized_text[:120]
    )
    canonical_key = generate_canonical_key(category, part_name, spec_json)

    split_detected, split_candidates = _detect_split(normalized_text, tokens)
    ambiguity_flags = _compute_ambiguity_flags(tokens, candidates, confidence)

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
            canonical_key=canonical_key,
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