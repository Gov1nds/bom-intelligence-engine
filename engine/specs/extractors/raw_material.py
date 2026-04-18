"""Raw material domain extractor."""
from __future__ import annotations
import re
from typing import Any
from engine.specs.extractors.base import BaseDomainExtractor, DomainExtractionResult

_FORM_PATTERNS = {
    "sheet": re.compile(r"\bsheet\b", re.I),
    "plate": re.compile(r"\bplate\b", re.I),
    "flat_bar": re.compile(r"\bflat\s*bar\b", re.I),
    "round_bar": re.compile(r"\b(?:round\s*bar|rod)\b", re.I),
    "tube": re.compile(r"\b(?:tube|tubing|pipe)\b", re.I),
    "wire": re.compile(r"\bwire\b", re.I),
    "angle": re.compile(r"\bangle\b", re.I),
    "channel": re.compile(r"\bchannel\b", re.I),
    "beam": re.compile(r"\b(?:i-?beam|h-?beam|beam)\b", re.I),
    "bar": re.compile(r"\bbar\b", re.I),
    "block": re.compile(r"\b(?:block|billet)\b", re.I),
}

class RawMaterialExtractor(BaseDomainExtractor):
    @property
    def critical_attributes(self) -> list[str]:
        return ["material"]

    def extract(self, text: str, tokens: list) -> DomainExtractionResult:
        attrs: dict[str, Any] = {}
        material = self._extract_material(text)
        if material:
            attrs["material"] = material
        # Form
        for form_name, pattern in _FORM_PATTERNS.items():
            if pattern.search(text):
                attrs["form"] = form_name
                break
        # Grade / condition
        m = re.search(r"\b([THOF]\d{1,2})\b", text)
        if m:
            attrs["grade"] = m.group(1)
        m = re.search(r"\b(\d{4})-?([THOF]\d{1,2})?\b", text)
        if m:
            alloy = m.group(1)
            temper = m.group(2)
            attrs["alloy_designation"] = alloy
            if temper:
                attrs["grade"] = temper
        # Dimensions
        dims = self._extract_dimensions(text)
        attrs.update(dims)
        # Single dimension values
        m = re.search(r"(?:thick|thk)\s*[:=]?\s*(\d+(?:\.\d+)?)\s*(mm|cm|in)?", text, re.I)
        if m and "thickness_mm" not in attrs:
            attrs["thickness_mm"] = self._to_mm(float(m.group(1)), m.group(2))
        m = re.search(r"(?:dia|diameter|[øØ])\s*[:=]?\s*(\d+(?:\.\d+)?)\s*(mm|cm|in)?", text, re.I)
        if m:
            attrs["diameter_mm"] = self._to_mm(float(m.group(1)), m.group(2))
        # Length as standalone with meter conversion
        m = re.search(r"\b(\d+(?:\.\d+)?)\s*(m|ft)\b", text, re.I)
        if m and "length_mm" not in attrs:
            val = float(m.group(1))
            unit = m.group(2)
            attrs["length_mm"] = self._to_mm(val, unit)
        finish = self._extract_finish(text)
        if finish:
            attrs["finish"] = finish
        completeness, missing = self._compute_completeness(attrs, self.critical_attributes)
        return DomainExtractionResult(attributes=attrs, confidence_boost=completeness*0.1,
                                       missing_critical=missing, extraction_method="raw_material_extractor")
