"""Electronics domain extractor — resistors, capacitors, ICs, LEDs, etc."""
from __future__ import annotations

import re
from typing import Any

from engine.specs.extractors.base import BaseDomainExtractor, DomainExtractionResult


_RESISTANCE_PATTERN = re.compile(
    r"(\d+(?:\.\d+)?)\s*([kKmMgG]?)\s*(?:ohm|ohms|Ω|ω|R)(?:\b|\s|$)", re.I
)
_CAPACITANCE_PATTERN = re.compile(
    r"(\d+(?:\.\d+)?)\s*([pPnNuUµmM]?)\s*[fF](?:arad|arads)?(?:\b|\s|$)", re.I
)
_INDUCTANCE_PATTERN = re.compile(
    r"(\d+(?:\.\d+)?)\s*([nNuUµmM]?)\s*[hH](?:enry|enries)?(?:\b|\s|$)", re.I
)
_VOLTAGE_PATTERN = re.compile(
    r"(\d+(?:\.\d+)?)\s*([mMkK]?)\s*[vV](?:DC|AC)?(?:\b|\s|$)", re.I
)
_CURRENT_PATTERN = re.compile(
    r"(\d+(?:\.\d+)?)\s*([mMuUµkK]?)\s*[aA](?:mp|mps)?(?:\b|\s|$)", re.I
)
_POWER_PATTERN = re.compile(
    r"(\d+(?:\.\d+)?)\s*([mMkK]?)\s*[wW](?:att|atts)?(?:\b|\s|$)", re.I
)
_FRACTIONAL_POWER = re.compile(r"\b(\d+)\s*/\s*(\d+)\s*[wW]\b")
_TOLERANCE_PATTERN = re.compile(r"[±]?\s*(\d+(?:\.\d+)?)\s*%")
_PACKAGE_PATTERN = re.compile(
    r"\b(0201|0402|0603|0805|1206|1210|1812|2010|2512|"
    r"SOT-\d+|QFP-?\d+|BGA-?\d+|DIP-?\d+|SOP-?\d+|TSSOP-?\d+|QFN-?\d+|"
    r"TO-\d+|DO-\d+|SOD-\d+|SOIC-?\d+|PLCC-?\d+|LQFP-?\d+)\b",
    re.I,
)
_DIELECTRIC_PATTERN = re.compile(r"\b(C0G|NP0|X5R|X7R|Y5V|X7S|X6S|X8R|X8L)\b", re.I)
_COMPONENT_TYPES = {
    "resistor": re.compile(r"\bresistor\b", re.I),
    "capacitor": re.compile(r"\bcapacitor\b", re.I),
    "inductor": re.compile(r"\binductor\b", re.I),
    "diode": re.compile(r"\bdiode\b", re.I),
    "led": re.compile(r"\bled\b", re.I),
    "transistor": re.compile(r"\btransistor\b", re.I),
    "mosfet": re.compile(r"\bmosfet\b", re.I),
    "igbt": re.compile(r"\bigbt\b", re.I),
    "crystal": re.compile(r"\b(?:crystal|xtal)\b", re.I),
    "oscillator": re.compile(r"\boscillator\b", re.I),
    "regulator": re.compile(r"\b(?:regulator|ldo)\b", re.I),
    "opamp": re.compile(r"\b(?:opamp|operational\s*amplifier|op\s*amp)\b", re.I),
    "microcontroller": re.compile(r"\b(?:microcontroller|mcu)\b", re.I),
    "integrated_circuit": re.compile(r"\b(?:integrated\s*circuit|ic)\b", re.I),
    "fuse": re.compile(r"\bfuse\b", re.I),
}

_SI_PREFIXES = {
    "p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6,
    "m": 1e-3, "k": 1e3, "K": 1e3, "M": 1e6, "G": 1e9, "g": 1e9,
}


class ElectronicsExtractor(BaseDomainExtractor):
    """Domain extractor for electronics/passive component BOM lines."""

    @property
    def critical_attributes(self) -> list[str]:
        return ["part_type"]

    def extract(self, text: str, tokens: list) -> DomainExtractionResult:
        attrs: dict[str, Any] = {}

        # Component type detection
        for ctype, pattern in _COMPONENT_TYPES.items():
            if pattern.search(text):
                attrs["part_type"] = ctype
                break

        # Resistance
        m = _RESISTANCE_PATTERN.search(text)
        if m:
            val = float(m.group(1))
            prefix = m.group(2)
            attrs["resistance_ohm"] = round(val * _SI_PREFIXES.get(prefix, 1.0), 12)
            if "part_type" not in attrs:
                attrs["part_type"] = "resistor"

        # Also check for implied resistance like "10k resistor"
        if "resistance_ohm" not in attrs:
            implied = re.search(r"\b(\d+(?:\.\d+)?)\s*([kKmMgG])\s*(?:resistor|res)\b", text, re.I)
            if implied:
                val = float(implied.group(1))
                prefix = implied.group(2)
                attrs["resistance_ohm"] = round(val * _SI_PREFIXES.get(prefix, 1.0), 12)
                attrs["part_type"] = "resistor"

        # Capacitance
        m = _CAPACITANCE_PATTERN.search(text)
        if m:
            val = float(m.group(1))
            prefix = m.group(2)
            attrs["capacitance_f"] = round(val * _SI_PREFIXES.get(prefix, 1.0), 18)
            if "part_type" not in attrs:
                attrs["part_type"] = "capacitor"

        # Inductance
        m = _INDUCTANCE_PATTERN.search(text)
        if m:
            val = float(m.group(1))
            prefix = m.group(2)
            attrs["inductance_h"] = round(val * _SI_PREFIXES.get(prefix, 1.0), 18)
            if "part_type" not in attrs:
                attrs["part_type"] = "inductor"

        # Voltage
        m = _VOLTAGE_PATTERN.search(text)
        if m:
            val = float(m.group(1))
            prefix = m.group(2)
            attrs["voltage_v"] = round(val * _SI_PREFIXES.get(prefix, 1.0), 12)

        # Current
        m = _CURRENT_PATTERN.search(text)
        if m:
            val = float(m.group(1))
            prefix = m.group(2)
            attrs["current_a"] = round(val * _SI_PREFIXES.get(prefix, 1.0), 12)

        # Power - check fractional first (1/4W, 1/2W)
        m = _FRACTIONAL_POWER.search(text)
        if m:
            num = float(m.group(1))
            den = float(m.group(2))
            if den > 0:
                attrs["power_w"] = round(num / den, 12)
        else:
            m = _POWER_PATTERN.search(text)
            if m:
                val = float(m.group(1))
                prefix = m.group(2)
                attrs["power_w"] = round(val * _SI_PREFIXES.get(prefix, 1.0), 12)

        # Tolerance
        m = _TOLERANCE_PATTERN.search(text)
        if m:
            attrs["tolerance_percent"] = float(m.group(1))

        # Package
        m = _PACKAGE_PATTERN.search(text)
        if m:
            attrs["package"] = m.group(1).upper()

        # Dielectric
        m = _DIELECTRIC_PATTERN.search(text)
        if m:
            attrs["dielectric"] = m.group(1).upper()

        # Determine critical attributes based on component type
        part_type = attrs.get("part_type", "")
        if part_type == "resistor":
            critical = ["resistance_ohm", "tolerance_percent"]
        elif part_type == "capacitor":
            critical = ["capacitance_f", "voltage_v"]
        elif part_type == "inductor":
            critical = ["inductance_h"]
        else:
            critical = ["part_type"]

        completeness, missing = self._compute_completeness(attrs, critical)
        boost = completeness * 0.15

        return DomainExtractionResult(
            attributes=attrs,
            confidence_boost=boost,
            missing_critical=missing,
            extraction_method="electronics_extractor",
        )
