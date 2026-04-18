"""Fastener domain extractor — threads, head types, drive types, grades."""
from __future__ import annotations

import re
from typing import Any

from engine.specs.extractors.base import BaseDomainExtractor, DomainExtractionResult


_METRIC_THREAD = re.compile(r"\bM(\d+(?:\.\d+)?)(?:\s*[xX×]\s*(\d+(?:\.\d+)?))?\b", re.I)
_UNC_THREAD = re.compile(r"\b(\d+/\d+|\d+(?:\.\d+)?)\s*-\s*(\d+)\s*(?:UNC)?\b", re.I)
_UNF_THREAD = re.compile(r"\b(\d+/\d+|\d+(?:\.\d+)?)\s*-\s*(\d+)\s*UNF\b", re.I)
_BSP_THREAD = re.compile(r"\b(\d+/\d+|\d+(?:\.\d+)?)\s*BSP[PT]?\b", re.I)
_NPT_THREAD = re.compile(r"\b(\d+/\d+|\d+(?:\.\d+)?)\s*NPT[F]?\b", re.I)
_PG_THREAD = re.compile(r"\bPG\s*(\d+)\b", re.I)

_HEAD_TYPES = {
    "hex": re.compile(r"\b(?:hex|hexagonal|hex\s*head)\b", re.I),
    "socket": re.compile(r"\b(?:socket|socket\s*head|allen|shcs)\b", re.I),
    "countersunk": re.compile(r"\b(?:countersunk|csk|flat\s*head|fhcs)\b", re.I),
    "button": re.compile(r"\b(?:button\s*head|bhcs|button)\b", re.I),
    "pan": re.compile(r"\b(?:pan\s*head|pan|pphms)\b", re.I),
    "round": re.compile(r"\b(?:round\s*head|round)\b", re.I),
    "cheese": re.compile(r"\b(?:cheese\s*head|cheese)\b", re.I),
    "truss": re.compile(r"\b(?:truss\s*head|truss)\b", re.I),
    "flange": re.compile(r"\b(?:flange\s*head|flange\s*bolt)\b", re.I),
    "eye": re.compile(r"\b(?:eye\s*bolt|eye\s*head)\b", re.I),
    "t_head": re.compile(r"\b(?:t-bolt|t\s*head|tee\s*bolt)\b", re.I),
}

_DRIVE_TYPES = {
    "hex_socket": re.compile(r"\b(?:hex\s*socket|allen|socket\s*head)\b", re.I),
    "torx": re.compile(r"\b(?:torx|star|t\d{1,2})\b", re.I),
    "phillips": re.compile(r"\b(?:phillips|ph|pozi|pozidrive)\b", re.I),
    "slotted": re.compile(r"\b(?:slotted|flat\s*blade)\b", re.I),
    "robertson": re.compile(r"\b(?:robertson|square\s*drive)\b", re.I),
}

_GRADE_PATTERNS = [
    re.compile(r"\b(?:grade|class|gr|cl)\s*[:=]?\s*(\d+\.\d+)\b", re.I),
    re.compile(r"\b(4\.6|4\.8|5\.6|5\.8|6\.8|8\.8|9\.8|10\.9|12\.9)\b"),
    re.compile(r"\b(A[24]-[0-9]{2})\b", re.I),
    re.compile(r"\b(?:SAE\s*)?Grade\s*([258])\b", re.I),
    re.compile(r"\b(A307|A325|A490|F1554)\b", re.I),
]

_LENGTH_PATTERN = re.compile(r"\b(\d+(?:\.\d+)?)\s*(mm|cm|in|inch)?\b", re.I)

_FASTENER_TYPE_MAP = {
    "bolt": re.compile(r"\bbolt\b", re.I),
    "screw": re.compile(r"\bscrew\b", re.I),
    "nut": re.compile(r"\bnut\b", re.I),
    "washer": re.compile(r"\bwasher\b", re.I),
    "rivet": re.compile(r"\brivet\b", re.I),
    "stud": re.compile(r"\bstud\b", re.I),
    "pin": re.compile(r"\bpin\b", re.I),
    "anchor": re.compile(r"\banchor\b", re.I),
    "insert": re.compile(r"\b(?:threaded\s*insert|helicoil|keensert)\b", re.I),
    "retaining_ring": re.compile(r"\b(?:retaining\s*ring|circlip|snap\s*ring|e-clip|c-clip)\b", re.I),
    "threaded_rod": re.compile(r"\b(?:threaded\s*rod|allthread|all\s*thread)\b", re.I),
}


class FastenerExtractor(BaseDomainExtractor):
    """Domain extractor for fastener BOM lines."""

    @property
    def critical_attributes(self) -> list[str]:
        return ["thread_size", "length_mm", "material"]

    def extract(self, text: str, tokens: list) -> DomainExtractionResult:
        attrs: dict[str, Any] = {}
        text_lower = text.lower()

        # Thread extraction
        thread = self._extract_thread(text)
        if thread:
            attrs["thread_size"] = thread

        # Head type
        for head_name, pattern in _HEAD_TYPES.items():
            if pattern.search(text):
                attrs["head_type"] = head_name
                break

        # Drive type
        for drive_name, pattern in _DRIVE_TYPES.items():
            if pattern.search(text):
                attrs["drive_type"] = drive_name
                break

        # Grade/class
        grade = self._extract_grade(text)
        if grade:
            attrs["grade_class"] = grade

        # Material
        material = self._extract_material(text)
        if material:
            attrs["material"] = material

        # Length - extract from thread spec or standalone
        length = self._extract_fastener_length(text, attrs.get("thread_size"))
        if length is not None:
            attrs["length_mm"] = length

        # Finish
        finish = self._extract_finish(text)
        if finish:
            attrs["finish"] = finish

        # Fastener type
        for ftype, pattern in _FASTENER_TYPE_MAP.items():
            if pattern.search(text):
                attrs["fastener_type"] = ftype
                break

        # Diameter from thread
        thread_str = attrs.get("thread_size", "")
        if isinstance(thread_str, str):
            m = re.match(r"M(\d+(?:\.\d+)?)", thread_str, re.I)
            if m:
                attrs["diameter_mm"] = float(m.group(1))

        completeness, missing = self._compute_completeness(attrs, self.critical_attributes)
        boost = completeness * 0.15

        return DomainExtractionResult(
            attributes=attrs,
            confidence_boost=boost,
            missing_critical=missing,
            extraction_method="fastener_extractor",
        )

    def _extract_thread(self, text: str) -> str | None:
        """Extract thread specification from text."""
        # Metric threads first (most common)
        m = _METRIC_THREAD.search(text)
        if m:
            size = m.group(1)
            pitch = m.group(2)
            if pitch:
                return f"M{size}x{pitch}"
            return f"M{size}"

        # UNF
        m = _UNF_THREAD.search(text)
        if m:
            return f"{m.group(1)}-{m.group(2)} UNF"

        # UNC
        m = _UNC_THREAD.search(text)
        if m:
            return f"{m.group(1)}-{m.group(2)} UNC"

        # BSP
        m = _BSP_THREAD.search(text)
        if m:
            return f"{m.group(1)} BSP"

        # NPT
        m = _NPT_THREAD.search(text)
        if m:
            return f"{m.group(1)} NPT"

        # PG
        m = _PG_THREAD.search(text)
        if m:
            return f"PG{m.group(1)}"

        return None

    def _extract_grade(self, text: str) -> str | None:
        for pattern in _GRADE_PATTERNS:
            m = pattern.search(text)
            if m:
                return m.group(1).strip()
        return None

    def _extract_fastener_length(self, text: str, thread: str | None) -> float | None:
        """Extract fastener length, considering thread spec contains length."""
        # Check if thread spec has length embedded (M8x30 → 30 is the pitch, not length)
        # For metric, the second number after x is pitch, not length
        # Length is usually a standalone mm value
        length_matches = re.findall(r"\b(\d+(?:\.\d+)?)\s*(mm|cm|in|inch)\b", text, re.I)
        if length_matches:
            # Filter out thread size matches
            for val_str, unit in length_matches:
                val = float(val_str)
                mm_val = self._to_mm(val, unit)
                if mm_val and 2.0 <= mm_val <= 2000.0:  # Reasonable fastener length
                    return mm_val
        return None
