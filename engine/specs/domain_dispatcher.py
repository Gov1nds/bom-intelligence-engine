"""Domain dispatcher — routes BOM lines to domain-specific extractors.

Pattern: normalize → classify domain → dispatch to domain extractor → build canonical output.
"""
from __future__ import annotations

from typing import Any

from engine.specs.extractors.base import BaseDomainExtractor, DomainExtractionResult
from engine.specs.extractors.fastener import FastenerExtractor
from engine.specs.extractors.electronics import ElectronicsExtractor
from engine.specs.extractors.electrical import ElectricalExtractor
from engine.specs.extractors.mechanical import MechanicalExtractor
from engine.specs.extractors.sheet_metal import SheetMetalExtractor
from engine.specs.extractors.raw_material import RawMaterialExtractor
from engine.specs.extractors.cable_wiring import CableWiringExtractor
from engine.specs.extractors.fluid_power import FluidPowerExtractor


class GenericExtractor(BaseDomainExtractor):
    """Fallback extractor for categories without a specific extractor."""

    @property
    def critical_attributes(self) -> list[str]:
        return []

    def extract(self, text: str, tokens: list) -> DomainExtractionResult:
        attrs: dict[str, Any] = {}
        material = self._extract_material(text)
        if material:
            attrs["material"] = material
        dims = self._extract_dimensions(text)
        attrs.update(dims)
        finish = self._extract_finish(text)
        if finish:
            attrs["finish"] = finish
        return DomainExtractionResult(
            attributes=attrs,
            confidence_boost=0.0,
            missing_critical=[],
            extraction_method="generic_extractor",
        )


# Routing table: category → extractor class
_ROUTING_TABLE: dict[str, type[BaseDomainExtractor]] = {
    "fastener": FastenerExtractor,
    "electronics": ElectronicsExtractor,
    "passive_component": ElectronicsExtractor,
    "semiconductor": ElectronicsExtractor,
    "electrical": ElectricalExtractor,
    "power_supply": ElectricalExtractor,
    "connector": ElectricalExtractor,
    "sensor": ElectricalExtractor,
    "mechanical": MechanicalExtractor,
    "custom_mechanical": MechanicalExtractor,
    "machined": MechanicalExtractor,
    "enclosure": MechanicalExtractor,
    "sheet_metal": SheetMetalExtractor,
    "raw_material": RawMaterialExtractor,
    "cable_wiring": CableWiringExtractor,
    "pneumatic": FluidPowerExtractor,
    "hydraulic": FluidPowerExtractor,
}

# Singleton instances cache
_EXTRACTORS: dict[str, BaseDomainExtractor] = {}
_GENERIC = GenericExtractor()


def _get_extractor(category: str) -> BaseDomainExtractor:
    """Get or create a singleton extractor for a category."""
    cls = _ROUTING_TABLE.get(category)
    if cls is None:
        return _GENERIC
    key = cls.__name__
    if key not in _EXTRACTORS:
        _EXTRACTORS[key] = cls()
    return _EXTRACTORS[key]


class DomainDispatcher:
    """Routes BOM lines to domain-specific extractors based on category."""

    def dispatch(
        self,
        category: str,
        normalized_text: str,
        tokens: list,
    ) -> DomainExtractionResult:
        """Dispatch to the appropriate domain extractor.

        Args:
            category: Classified part category
            normalized_text: Normalized text of the BOM line
            tokens: Extracted tokens from tokenizer

        Returns:
            DomainExtractionResult with extracted attributes and metadata
        """
        try:
            extractor = _get_extractor(category)
            return extractor.extract(normalized_text, tokens)
        except Exception:
            # Graceful degradation — never crash on a single line
            return DomainExtractionResult(
                attributes={},
                confidence_boost=0.0,
                missing_critical=[],
                extraction_method="fallback_on_error",
            )
