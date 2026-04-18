"""Mechanical domain extractor — dimensions, tolerances, bearings, gears, springs."""
from __future__ import annotations
import re
from typing import Any
from engine.specs.extractors.base import BaseDomainExtractor, DomainExtractionResult

class MechanicalExtractor(BaseDomainExtractor):
    @property
    def critical_attributes(self) -> list[str]:
        return ["material"]

    def extract(self, text: str, tokens: list) -> DomainExtractionResult:
        attrs: dict[str, Any] = {}
        material = self._extract_material(text)
        if material:
            attrs["material"] = material
        dims = self._extract_dimensions(text)
        attrs.update(dims)
        # Diameter
        m = re.search(r"(?:dia|diameter|[øØ⌀∅])\s*[:=]?\s*(\d+(?:\.\d+)?)\s*(mm|cm|in)?", text, re.I)
        if m:
            attrs["diameter_mm"] = self._to_mm(float(m.group(1)), m.group(2))
        # Tolerance class
        m = re.search(r"\b([hHkKgGfFeEdDcCbBaAnNpPrRsStTuU]\d{1,2})\b", text)
        if m:
            attrs["tolerance_class"] = m.group(1)
        # Surface finish
        m = re.search(r"Ra\s*[:=]?\s*(\d+(?:\.\d+)?)\s*(um|µm)?", text, re.I)
        if m:
            attrs["surface_finish_ra_um"] = float(m.group(1))
        # Hardness
        m = re.search(r"(\d+(?:\.\d+)?)\s*HRC\b", text, re.I)
        if m:
            attrs["hardness_hrc"] = float(m.group(1))
        finish = self._extract_finish(text)
        if finish:
            attrs["finish"] = finish
        # Process hints
        processes = []
        for kw, proc in [("cnc","cnc_machining"),("machined","cnc_machining"),("milled","milling"),
                         ("turned","turning"),("ground","grinding"),("drilled","drilling"),
                         ("honed","honing"),("lapped","lapping"),("reamed","reaming")]:
            if re.search(rf"\b{kw}\b", text, re.I):
                processes.append(proc)
        if processes:
            attrs["process_hints"] = list(dict.fromkeys(processes))

        completeness, missing = self._compute_completeness(attrs, self.critical_attributes)
        return DomainExtractionResult(attributes=attrs, confidence_boost=completeness*0.1,
                                       missing_critical=missing, extraction_method="mechanical_extractor")
