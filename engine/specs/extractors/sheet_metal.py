"""Sheet metal domain extractor."""
from __future__ import annotations
import re
from typing import Any
from engine.specs.extractors.base import BaseDomainExtractor, DomainExtractionResult

_GAUGE_TABLE_SWG = {"10":3.251,"11":2.946,"12":2.642,"13":2.337,"14":2.032,"15":1.829,
    "16":1.626,"17":1.422,"18":1.219,"19":1.016,"20":0.914,"21":0.813,"22":0.711,
    "23":0.610,"24":0.559,"25":0.508,"26":0.457}

class SheetMetalExtractor(BaseDomainExtractor):
    @property
    def critical_attributes(self) -> list[str]:
        return ["thickness_mm", "material"]

    def extract(self, text: str, tokens: list) -> DomainExtractionResult:
        attrs: dict[str, Any] = {}
        material = self._extract_material(text)
        if material:
            attrs["material"] = material
        # Thickness - handle both "thk 1.5mm" and "1.5mm thk"
        m = re.search(r"(?:thick|thk|thkns|t)\s*[:=]?\s*(\d+(?:\.\d+)?)\s*(mm|cm|in)?", text, re.I)
        if m:
            attrs["thickness_mm"] = self._to_mm(float(m.group(1)), m.group(2))
        else:
            # value-before-keyword: "1.5mm thk"
            m = re.search(r"(\d+(?:\.\d+)?)\s*(mm|cm|in)?\s*(?:thick|thk|thkns)\b", text, re.I)
            if m:
                attrs["thickness_mm"] = self._to_mm(float(m.group(1)), m.group(2))
        # Gauge
        m = re.search(r"\b(\d{1,2})\s*(?:ga|gauge|swg|g)\b", text, re.I)
        if m and "thickness_mm" not in attrs:
            gauge_str = m.group(1)
            if gauge_str in _GAUGE_TABLE_SWG:
                attrs["thickness_mm"] = _GAUGE_TABLE_SWG[gauge_str]
                attrs["gauge"] = int(gauge_str)
        # Dimensions
        dims = self._extract_dimensions(text)
        if "length_mm" in dims:
            attrs["length_mm"] = dims["length_mm"]
        if "width_mm" in dims:
            attrs["width_mm"] = dims["width_mm"]
        finish = self._extract_finish(text)
        if finish:
            attrs["finish"] = finish
        # Process hints
        processes = []
        for kw, proc in [("laser","laser_cutting"),("bend","bending"),("bent","bending"),
                         ("punch","punching"),("stamp","stamping"),("form","forming"),
                         ("weld","welding"),("waterjet","waterjet_cutting"),("fold","folding")]:
            if re.search(rf"\b{kw}\b", text, re.I):
                processes.append(proc)
        if processes:
            attrs["process_hints"] = list(dict.fromkeys(processes))
        completeness, missing = self._compute_completeness(attrs, self.critical_attributes)
        return DomainExtractionResult(attributes=attrs, confidence_boost=completeness*0.12,
                                       missing_critical=missing, extraction_method="sheet_metal_extractor")
