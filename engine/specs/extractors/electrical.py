"""Electrical domain extractor — relays, breakers, motors, cables."""
from __future__ import annotations
import re
from typing import Any
from engine.specs.extractors.base import BaseDomainExtractor, DomainExtractionResult

class ElectricalExtractor(BaseDomainExtractor):
    @property
    def critical_attributes(self) -> list[str]:
        return ["voltage_v"]

    def extract(self, text: str, tokens: list) -> DomainExtractionResult:
        attrs: dict[str, Any] = {}
        # Voltage
        m = re.search(r"(\d+(?:\.\d+)?)\s*([mMkK]?)\s*[vV](?:DC|AC)?(?:\b|\s|$)", text, re.I)
        if m:
            val = float(m.group(1))
            prefix = m.group(2)
            mult = {"k":1e3,"K":1e3,"m":1e-3,"M":1e6}.get(prefix, 1.0)
            attrs["voltage_v"] = round(val * mult, 6)
        # Current
        m = re.search(r"(\d+(?:\.\d+)?)\s*([mMuUµkK]?)\s*[aA](?:mp|mps)?(?:\b|\s|$)", text, re.I)
        if m:
            val = float(m.group(1))
            prefix = m.group(2)
            mult = {"k":1e3,"K":1e3,"m":1e-3,"M":1e6,"u":1e-6,"µ":1e-6}.get(prefix, 1.0)
            attrs["current_a"] = round(val * mult, 6)
        # Power
        m = re.search(r"(\d+(?:\.\d+)?)\s*([mMkK]?)\s*[wW](?:att)?(?:\b|\s|$)", text, re.I)
        if m:
            val = float(m.group(1))
            prefix = m.group(2)
            mult = {"k":1e3,"K":1e3,"m":1e-3,"M":1e6}.get(prefix, 1.0)
            attrs["power_w"] = round(val * mult, 6)
        # IP rating
        m = re.search(r"\bIP\s*(\d{2})\b", text, re.I)
        if m:
            attrs["ip_rating"] = f"IP{m.group(1)}"
        # Phase
        m = re.search(r"\b(\d)\s*(?:phase|ph)\b", text, re.I)
        if m:
            attrs["phase"] = int(m.group(1))
        # Pole count
        m = re.search(r"\b(\d)\s*(?:pole|p)\b", text, re.I)
        if m:
            attrs["pole_count"] = int(m.group(1))
        completeness, missing = self._compute_completeness(attrs, self.critical_attributes)
        return DomainExtractionResult(attributes=attrs, confidence_boost=completeness*0.1,
                                       missing_critical=missing, extraction_method="electrical_extractor")
