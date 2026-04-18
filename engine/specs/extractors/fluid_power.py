"""Fluid power (pneumatic/hydraulic) domain extractor."""
from __future__ import annotations
import re
from typing import Any
from engine.specs.extractors.base import BaseDomainExtractor, DomainExtractionResult

class FluidPowerExtractor(BaseDomainExtractor):
    @property
    def critical_attributes(self) -> list[str]:
        return ["pressure_rating_bar"]

    def extract(self, text: str, tokens: list) -> DomainExtractionResult:
        attrs: dict[str, Any] = {}
        m = re.search(r"(\d+(?:\.\d+)?)\s*(?:bar)\b", text, re.I)
        if m:
            attrs["pressure_rating_bar"] = float(m.group(1))
        m = re.search(r"(\d+(?:\.\d+)?)\s*(?:psi)\b", text, re.I)
        if m:
            attrs["pressure_rating_bar"] = round(float(m.group(1)) * 0.0689476, 2)
        m = re.search(r"(?:bore|bore\s*dia)\s*[:=]?\s*(\d+(?:\.\d+)?)\s*(mm)?", text, re.I)
        if m:
            attrs["bore_mm"] = float(m.group(1))
        m = re.search(r"(?:stroke)\s*[:=]?\s*(\d+(?:\.\d+)?)\s*(mm)?", text, re.I)
        if m:
            attrs["stroke_mm"] = float(m.group(1))
        m = re.search(r"(\d+/\d+|\d+(?:\.\d+)?)\s*(?:BSP|NPT|BSPT|BSPP)\b", text, re.I)
        if m:
            attrs["port_size"] = m.group(0).strip()
        completeness, missing = self._compute_completeness(attrs, self.critical_attributes)
        return DomainExtractionResult(attributes=attrs, confidence_boost=completeness*0.1,
                                       missing_critical=missing, extraction_method="fluid_power_extractor")
