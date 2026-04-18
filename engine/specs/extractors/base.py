"""Abstract base class for domain-specific spec extractors."""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class DomainExtractionResult:
    """Result from a domain-specific extractor."""
    attributes: dict[str, Any] = field(default_factory=dict)
    confidence_boost: float = 0.0
    missing_critical: list[str] = field(default_factory=list)
    extraction_method: str = "generic"


_UNIT_TO_MM = {
    "mm": 1.0, "cm": 10.0, "m": 1000.0,
    "in": 25.4, "inch": 25.4, "ft": 304.8,
}

_SI_PREFIXES = {
    "p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6,
    "m": 1e-3, "k": 1e3, "M": 1e6, "G": 1e9,
}

_MATERIAL_PATTERN = re.compile(
    r"\b(stainless\s*steel(?:\s*(?:304|304l|316|316l|301|310|321|347|410|420|430|2205|2507))?|"
    r"aluminum(?:\s*(?:1100|2024|3003|5052|5083|6061|6063|7075))?|"
    r"carbon\s*steel(?:\s*(?:1018|1020|1045|1060|1095|a36|a572))?|"
    r"alloy\s*steel(?:\s*(?:4130|4140|4340|8620))?|"
    r"tool\s*steel(?:\s*(?:d2|h13|m2|o1|a2|s7|p20))?|"
    r"copper|brass|bronze|titanium(?:\s*(?:grade\s*[125]|6al4v))?|"
    r"inconel(?:\s*(?:600|625|718))?|hastelloy|monel|"
    r"abs|polycarbonate|acetal|nylon(?:\s*(?:6|66|12))?|"
    r"peek|ptfe|pvc|hdpe|ldpe|acrylic|polypropylene|polyethylene|"
    r"nitrile\s*rubber|epdm|silicone|neoprene|fluoroelastomer|"
    r"mild\s*steel|galvanized\s*steel|cold\s*rolled\s*steel|hot\s*rolled\s*steel|"
    r"spring\s*steel|cast\s*iron|ductile\s*iron|steel)\b",
    re.I,
)

_FINISH_PATTERN = re.compile(
    r"\b(anodized|anodizing|plated|painted|powder\s*coat(?:ed)?|"
    r"chrome|polished|galvanized|zinc\s*plated|black\s*oxide|"
    r"passivated|nickel\s*plated|hot\s*dip\s*galvanized|"
    r"electropolished|bead\s*blasted|shot\s*blasted|phosphated|"
    r"epoxy\s*coated|hard\s*anodized)\b",
    re.I,
)


class BaseDomainExtractor(ABC):
    """Abstract base class for all domain-specific extractors."""

    @abstractmethod
    def extract(self, text: str, tokens: list) -> DomainExtractionResult:
        """Extract domain-specific attributes from normalized text and tokens."""
        ...

    @property
    @abstractmethod
    def critical_attributes(self) -> list[str]:
        """List of critical attribute keys for this domain."""
        ...

    def _extract_material(self, text: str) -> str | None:
        """Extract material reference from text."""
        m = _MATERIAL_PATTERN.search(text)
        if m:
            raw = m.group(1).strip().lower()
            return re.sub(r"\s+", "_", raw)
        return None

    def _extract_finish(self, text: str) -> str | None:
        """Extract surface finish/coating from text."""
        m = _FINISH_PATTERN.search(text)
        if m:
            return m.group(1).strip().lower().replace(" ", "_")
        return None

    def _to_mm(self, value: float, unit: str | None) -> float | None:
        """Convert a dimension value to millimeters."""
        if value is None:
            return None
        factor = _UNIT_TO_MM.get((unit or "mm").lower())
        if factor is None:
            return None
        return round(value * factor, 6)

    def _parse_value_with_prefix(self, value_str: str, prefix: str | None) -> float:
        """Parse a numeric value with optional SI prefix."""
        multiplier = _SI_PREFIXES.get((prefix or "").lower(), 1.0)
        return float(value_str) * multiplier

    def _extract_dimensions(self, text: str) -> dict[str, float]:
        """Extract dimension expressions like 2x4x10mm."""
        dims: dict[str, float] = {}
        pattern = re.compile(
            r"(\d+(?:\.\d+)?)\s*[xX×]\s*(\d+(?:\.\d+)?)"
            r"(?:\s*[xX×]\s*(\d+(?:\.\d+)?))?\s*(mm|cm|in|m)?",
            re.I,
        )
        m = pattern.search(text)
        if m:
            unit = m.group(4)
            vals = [float(m.group(1)), float(m.group(2))]
            if m.group(3):
                vals.append(float(m.group(3)))
            # Sort ascending for consistent assignment
            vals_sorted = sorted(vals)
            if len(vals_sorted) == 3:
                dims["thickness_mm"] = self._to_mm(vals_sorted[0], unit) or vals_sorted[0]
                dims["width_mm"] = self._to_mm(vals_sorted[1], unit) or vals_sorted[1]
                dims["length_mm"] = self._to_mm(vals_sorted[2], unit) or vals_sorted[2]
            elif len(vals_sorted) == 2:
                dims["width_mm"] = self._to_mm(vals_sorted[0], unit) or vals_sorted[0]
                dims["length_mm"] = self._to_mm(vals_sorted[1], unit) or vals_sorted[1]
        return dims

    def _extract_standard(self, text: str) -> str | None:
        """Extract standards references (DIN, ISO, ASTM, etc.)."""
        pattern = re.compile(r"\b(DIN|ISO|ASTM|ANSI|BS|JIS|EN|SAE|MIL|AISI|AWS)\s*[-:]?\s*(\d+[-\w]*)\b", re.I)
        m = pattern.search(text)
        if m:
            return f"{m.group(1).upper()} {m.group(2)}"
        return None

    def _compute_completeness(self, attributes: dict, critical_keys: list[str]) -> tuple[float, list[str]]:
        """Compute attribute completeness against critical requirements."""
        if not critical_keys:
            return 1.0, []
        present = sum(1 for k in critical_keys if k in attributes and attributes[k] is not None)
        missing = [k for k in critical_keys if k not in attributes or attributes[k] is None]
        return present / len(critical_keys), missing
