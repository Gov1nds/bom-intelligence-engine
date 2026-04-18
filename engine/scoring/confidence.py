"""Domain-aware multi-dimensional confidence scoring.

Replaces the flat 4-factor confidence formula with domain-aware scoring
that penalizes missing critical attributes per category and provides
actionable confidence breakdown.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.schemas import ConfidenceLevel


# Critical attributes per domain
_CRITICAL_ATTRIBUTES: dict[str, list[str]] = {
    "fastener": ["thread_size", "length_mm", "material"],
    "electronics": ["part_type", "resistance_ohm", "capacitance_f"],
    "passive_component": ["part_type"],
    "semiconductor": ["part_type"],
    "electrical": ["voltage_v"],
    "power_supply": ["voltage_v"],
    "connector": ["part_type"],
    "sensor": ["part_type"],
    "mechanical": ["material"],
    "custom_mechanical": ["material"],
    "machined": ["material"],
    "sheet_metal": ["thickness_mm", "material"],
    "raw_material": ["material"],
    "cable_wiring": ["conductor_count"],
    "pneumatic": ["pressure_rating_bar"],
    "hydraulic": ["pressure_rating_bar"],
    "enclosure": [],
    "optical": [],
    "thermal": [],
    "adhesive_sealant": [],
    "standard": [],
    "unknown": [],
}


@dataclass
class ConfidenceBreakdown:
    """Detailed confidence scoring breakdown."""
    overall: float
    classification: float
    attribute_completeness: float
    token_quality: float
    critical_attribute_penalty: float
    ambiguity_penalty: float
    ocr_penalty: float
    breakdown_reason: str
    confidence_level: ConfidenceLevel


def _present(value: Any) -> bool:
    """Check if a value is meaningfully present."""
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) > 0
    return True


def compute_domain_confidence(
    category: str,
    classification_confidence: float,
    attributes: dict[str, Any],
    token_coverage: float,
    missing_critical: list[str],
    ambiguity_flags: list[str],
    ocr_healing_applied: bool = False,
    non_english_detected: bool = False,
) -> ConfidenceBreakdown:
    """Compute domain-aware multi-dimensional confidence score.

    Args:
        category: Classified part category
        classification_confidence: Confidence from the classifier
        attributes: Extracted attributes dictionary
        token_coverage: Ratio of tokens matched to words
        missing_critical: List of missing critical attribute names
        ambiguity_flags: List of ambiguity flag strings
        ocr_healing_applied: Whether OCR healing was performed
        non_english_detected: Whether non-English text was detected

    Returns:
        ConfidenceBreakdown with detailed scoring
    """
    # Get critical attributes for this domain
    domain_critical = _CRITICAL_ATTRIBUTES.get(category, [])
    total_critical = max(1, len(domain_critical))

    # Compute attribute completeness
    if domain_critical:
        present_count = sum(1 for k in domain_critical if _present(attributes.get(k)))
        attribute_completeness = present_count / total_critical
    else:
        # No critical attributes defined — base on overall attribute count
        attribute_completeness = min(1.0, len(attributes) / 3.0) if attributes else 0.3

    # Base scoring formula
    classification_component = classification_confidence * 0.30
    completeness_component = attribute_completeness * 0.35
    token_component = min(1.0, token_coverage) * 0.15

    # Critical attribute penalty
    critical_penalty_ratio = len(missing_critical) / total_critical if missing_critical else 0.0
    critical_component = (1.0 - critical_penalty_ratio) * 0.20

    base = classification_component + completeness_component + token_component + critical_component

    # Penalties
    ambiguity_penalty = min(0.25, len(ambiguity_flags) * 0.05)
    ocr_penalty = 0.10 if ocr_healing_applied else 0.0
    lang_penalty = 0.05 if non_english_detected else 0.0

    penalized = base - ambiguity_penalty - ocr_penalty - lang_penalty
    overall = round(min(1.0, max(0.0, penalized)), 4)

    # Determine confidence level
    if overall >= 0.80:
        confidence_level = ConfidenceLevel.HIGH
    elif overall >= 0.55:
        confidence_level = ConfidenceLevel.MEDIUM
    else:
        confidence_level = ConfidenceLevel.LOW

    # Build reason string
    reasons = []
    reasons.append(f"classification={classification_confidence:.2f}")
    reasons.append(f"completeness={attribute_completeness:.2f}")
    reasons.append(f"token_coverage={token_coverage:.2f}")
    if missing_critical:
        reasons.append(f"missing=[{','.join(missing_critical[:3])}]")
    if ambiguity_flags:
        reasons.append(f"ambiguity_count={len(ambiguity_flags)}")
    if ocr_healing_applied:
        reasons.append("ocr_healed")

    return ConfidenceBreakdown(
        overall=overall,
        classification=round(classification_confidence, 4),
        attribute_completeness=round(attribute_completeness, 4),
        token_quality=round(min(1.0, token_coverage), 4),
        critical_attribute_penalty=round(critical_penalty_ratio, 4),
        ambiguity_penalty=round(ambiguity_penalty, 4),
        ocr_penalty=round(ocr_penalty + lang_penalty, 4),
        breakdown_reason="; ".join(reasons),
        confidence_level=confidence_level,
    )
