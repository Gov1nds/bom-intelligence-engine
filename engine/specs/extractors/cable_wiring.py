"""Cable/Wiring domain extractor."""
from __future__ import annotations
import re
from typing import Any
from engine.specs.extractors.base import BaseDomainExtractor, DomainExtractionResult

class CableWiringExtractor(BaseDomainExtractor):
    @property
    def critical_attributes(self) -> list[str]:
        return ["conductor_count", "cross_section_mm2"]

    def extract(self, text: str, tokens: list) -> DomainExtractionResult:
        attrs: dict[str, Any] = {}
        m = re.search(r"\b(\d+)\s*(?:core|cond|conductor|c)\b", text, re.I)
        if m:
            attrs["conductor_count"] = int(m.group(1))
        m = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:mm2|mm²|sqmm)\b", text, re.I)
        if m:
            attrs["cross_section_mm2"] = float(m.group(1))
        m = re.search(r"\b(\d+)\s*AWG\b", text, re.I)
        if m:
            attrs["awg"] = int(m.group(1))
        m = re.search(r"(\d+(?:\.\d+)?)\s*([mMkK]?)\s*[vV](?:\b|\s|$)", text, re.I)
        if m:
            attrs["voltage_rating_v"] = float(m.group(1))
        completeness, missing = self._compute_completeness(attrs, self.critical_attributes)
        return DomainExtractionResult(attributes=attrs, confidence_boost=completeness*0.1,
                                       missing_critical=missing, extraction_method="cable_wiring_extractor")
