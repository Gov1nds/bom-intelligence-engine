"""Domain-specific extractors package."""
from engine.specs.extractors.base import BaseDomainExtractor, DomainExtractionResult
from engine.specs.extractors.fastener import FastenerExtractor
from engine.specs.extractors.electronics import ElectronicsExtractor
from engine.specs.extractors.electrical import ElectricalExtractor
from engine.specs.extractors.mechanical import MechanicalExtractor
from engine.specs.extractors.sheet_metal import SheetMetalExtractor
from engine.specs.extractors.raw_material import RawMaterialExtractor
from engine.specs.extractors.cable_wiring import CableWiringExtractor
from engine.specs.extractors.fluid_power import FluidPowerExtractor

__all__ = [
    "BaseDomainExtractor", "DomainExtractionResult",
    "FastenerExtractor", "ElectronicsExtractor", "ElectricalExtractor",
    "MechanicalExtractor", "SheetMetalExtractor", "RawMaterialExtractor",
    "CableWiringExtractor", "FluidPowerExtractor",
]
