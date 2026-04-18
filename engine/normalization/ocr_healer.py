"""OCR noise healing and text pre-processing layer.

Deterministic pre-processing that repairs common OCR noise, delimiter
confusion, encoding artifacts, and structural corruption before
normalization begins. First line of defense for messy real-world BOMs.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field


@dataclass
class HealingOp:
    """Record of a single healing operation applied."""
    rule: str
    original: str
    healed: str
    position: int = 0


# Context-aware OCR confusion patterns
_PART_NUMBER_PATTERN = re.compile(r'\b[A-Z0-9]{3,}[-/]?[A-Z0-9]{2,}\b')
_ALPHA_DIGIT_BOUNDARY = re.compile(r'([a-zA-Z])(\d)')
_DIGIT_ALPHA_BOUNDARY = re.compile(r'(\d)([a-zA-Z])')

# Known OCR confusions - applied context-sensitively
_OCR_CHAR_CONFUSIONS = [
    # (pattern, replacement, context_description)
    (re.compile(r'\bB0lt\b', re.I), 'Bolt', 'ocr_0_to_O'),
    (re.compile(r'\bb0lt\b', re.I), 'bolt', 'ocr_0_to_O'),
    (re.compile(r'\bNut\b'), 'Nut', 'ocr_preserve'),
    (re.compile(r'\bRes1stor\b', re.I), 'Resistor', 'ocr_1_to_i'),
    (re.compile(r'\bres1stor\b', re.I), 'resistor', 'ocr_1_to_i'),
    (re.compile(r'\bCapac1tor\b', re.I), 'Capacitor', 'ocr_1_to_i'),
    (re.compile(r'\bcapac1tor\b', re.I), 'capacitor', 'ocr_1_to_i'),
    (re.compile(r'\bD1ode\b', re.I), 'Diode', 'ocr_1_to_i'),
    (re.compile(r'\bd1ode\b', re.I), 'diode', 'ocr_1_to_i'),
    (re.compile(r'\bWash3r\b', re.I), 'Washer', 'ocr_3_to_e'),
    (re.compile(r'\bwash3r\b', re.I), 'washer', 'ocr_3_to_e'),
    (re.compile(r'\bScr3w\b', re.I), 'Screw', 'ocr_3_to_e'),
    (re.compile(r'\bscr3w\b', re.I), 'screw', 'ocr_3_to_e'),
]

# Greek/special character normalization
_GREEK_MAP = {
    'Ω': 'ohm', 'ω': 'ohm',
    'µ': 'u', 'μ': 'u',
    'α': 'alpha', 'β': 'beta', 'γ': 'gamma', 'δ': 'delta',
    'ε': 'epsilon', 'π': 'pi', 'σ': 'sigma', 'τ': 'tau',
    'φ': 'phi', 'θ': 'theta', 'λ': 'lambda',
}

# Superscript/subscript normalization
_SUPERSCRIPT_MAP = {
    '²': '2', '³': '3', '¹': '1', '⁰': '0',
    '⁴': '4', '⁵': '5', '⁶': '6', '⁷': '7', '⁸': '8', '⁹': '9',
    '₀': '0', '₁': '1', '₂': '2', '₃': '3', '₄': '4',
    '₅': '5', '₆': '6', '₇': '7', '₈': '8', '₉': '9',
}

# Bracket normalization
_BRACKET_MAP = {
    '【': '[', '】': ']', '〔': '[', '〕': ']',
    '（': '(', '）': ')', '｛': '{', '｝': '}',
    '「': '[', '」': ']', '『': '[', '』': ']',
}

# Quote normalization
_QUOTE_MAP = {
    '\u201c': '"', '\u201d': '"',  # " "
    '\u2018': "'", '\u2019': "'",  # ' '
    '\u00ab': '"', '\u00bb': '"',  # « »
}


class OcrHealer:
    """Aggressive deterministic pre-processing layer for OCR noise repair."""

    def heal(self, raw_text: str) -> tuple[str, list[dict]]:
        """Heal OCR noise in raw BOM text.

        Returns:
            tuple of (healed_text, list_of_healing_operations_applied)
        """
        if not raw_text:
            return '', []

        ops: list[HealingOp] = []
        text = raw_text

        # 1. Encoding normalization: strip BOM, normalize unicode (NFKC)
        text = self._normalize_encoding(text, ops)

        # 2. Bracket normalization
        text = self._normalize_brackets(text, ops)

        # 3. Quote normalization
        text = self._normalize_quotes(text, ops)

        # 4. Hyphen/dash normalization in non-part-number context
        text = self._normalize_hyphens(text, ops)

        # 5. Greek character normalization
        text = self._normalize_greek(text, ops)

        # 6. Superscript/subscript normalization
        text = self._normalize_superscripts(text, ops)

        # 7. Multiplication sign normalization
        text = self._normalize_multiplication(text, ops)

        # 8. Context-aware OCR character confusions
        text = self._fix_ocr_confusions(text, ops)

        # 9. Thousands separator handling (MUST come before decimal comma)
        text = self._normalize_thousands(text, ops)

        # 10. Decimal comma normalization (European format)
        text = self._normalize_decimal_comma(text, ops)

        # 11. Stray dot removal
        text = self._remove_stray_dots(text, ops)

        # 12. OCR space insertion (alpha-digit transitions)
        text = self._insert_missing_spaces(text, ops)

        # 13. Whitespace normalization (must be last)
        text = self._normalize_whitespace(text, ops)

        return text, [{'rule': op.rule, 'original': op.original, 'healed': op.healed} for op in ops]

    def _normalize_encoding(self, text: str, ops: list[HealingOp]) -> str:
        """Strip BOM, normalize unicode (NFKC), fix mojibake."""
        # Strip BOM
        cleaned = text.lstrip('\ufeff\ufffe')
        if cleaned != text:
            ops.append(HealingOp('strip_bom', text[:10], cleaned[:10]))

        # NFKC normalization
        normalized = unicodedata.normalize('NFKC', cleaned)
        if normalized != cleaned:
            ops.append(HealingOp('unicode_nfkc', '', ''))

        return normalized

    def _normalize_brackets(self, text: str, ops: list[HealingOp]) -> str:
        result = text
        for src, tgt in _BRACKET_MAP.items():
            if src in result:
                result = result.replace(src, tgt)
                ops.append(HealingOp('bracket_normalize', src, tgt))
        return result

    def _normalize_quotes(self, text: str, ops: list[HealingOp]) -> str:
        result = text
        for src, tgt in _QUOTE_MAP.items():
            if src in result:
                result = result.replace(src, tgt)
                ops.append(HealingOp('quote_normalize', src, tgt))
        return result

    def _normalize_hyphens(self, text: str, ops: list[HealingOp]) -> str:
        """Normalize em/en dashes to hyphens except in part number context."""
        result = text
        for dash in ('\u2014', '\u2013', '\u2012', '\u2015', '\u2010', '\u2011', '\u2212'):
            if dash in result:
                result = result.replace(dash, '-')
                ops.append(HealingOp('hyphen_normalize', dash, '-'))
        return result

    def _normalize_greek(self, text: str, ops: list[HealingOp]) -> str:
        result = text
        for src, tgt in _GREEK_MAP.items():
            if src in result:
                # Don't replace Ω/µ when adjacent to digits (they're valid unit symbols)
                # But normalize them to ASCII equivalents
                result = result.replace(src, tgt)
                ops.append(HealingOp('greek_normalize', src, tgt))
        return result

    def _normalize_superscripts(self, text: str, ops: list[HealingOp]) -> str:
        result = text
        for src, tgt in _SUPERSCRIPT_MAP.items():
            if src in result:
                result = result.replace(src, tgt)
                ops.append(HealingOp('superscript_normalize', src, tgt))
        return result

    def _normalize_multiplication(self, text: str, ops: list[HealingOp]) -> str:
        """Normalize × ✕ · to x in dimension context."""
        result = text
        for char in ('×', '✕', '✖'):
            if char in result:
                result = result.replace(char, 'x')
                ops.append(HealingOp('multiplication_normalize', char, 'x'))
        return result

    def _fix_ocr_confusions(self, text: str, ops: list[HealingOp]) -> str:
        """Fix common OCR character confusions context-sensitively."""
        result = text
        for pattern, replacement, rule_name in _OCR_CHAR_CONFUSIONS:
            match = pattern.search(result)
            if match:
                original = match.group(0)
                result = pattern.sub(replacement, result)
                ops.append(HealingOp(rule_name, original, replacement))
        return result

    def _normalize_decimal_comma(self, text: str, ops: list[HealingOp]) -> str:
        """Convert European decimal commas: '0,5mm' → '0.5mm'."""
        # Pattern: digit,digit where NOT followed by 3+ digits (which would be thousands)
        pattern = re.compile(r'(\d),(\d{1,2})(?!\d)')
        result = text
        if pattern.search(result):
            new_result = pattern.sub(r'\1.\2', result)
            if new_result != result:
                ops.append(HealingOp('decimal_comma_to_dot', '', ''))
                result = new_result
        return result

    def _normalize_thousands(self, text: str, ops: list[HealingOp]) -> str:
        """Remove thousands separators: '1,000' → '1000', '1.000,50' → '1000.50'."""
        result = text
        # European: 1.000,50 → 1000.50 (period as thousands, comma as decimal)
        # Must check this BEFORE US format since both use digits+separator+3digits
        euro_pattern = re.compile(r'\b(\d{1,3})\.(\d{3})(?:\.(\d{3}))?,(\d{1,2})\b')
        for m in euro_pattern.finditer(result):
            full = m.group(0)
            # Remove dots (thousands), replace comma with dot (decimal)
            cleaned = full.replace('.', '').replace(',', '.')
            result = result.replace(full, cleaned, 1)
            ops.append(HealingOp('european_thousands_normalize', full, cleaned))

        if not euro_pattern.search(text):
            # US/UK: 1,000 → 1000 (only if no European format detected)
            us_pattern = re.compile(r'(\d{1,3}),(\d{3})(?:,(\d{3}))?(?!\d)')
            for m in us_pattern.finditer(result):
                full = m.group(0)
                cleaned = full.replace(',', '')
                result = result.replace(full, cleaned, 1)
                ops.append(HealingOp('thousands_separator_remove', full, cleaned))
        return result

    def _remove_stray_dots(self, text: str, ops: list[HealingOp]) -> str:
        """Remove dots that are not decimal points: 'bolt . hex' → 'bolt hex'."""
        # Dot surrounded by spaces (not between digits)
        pattern = re.compile(r'(?<!\d)\s+\.\s+(?!\d)')
        result = text
        if pattern.search(result):
            result = pattern.sub(' ', result)
            ops.append(HealingOp('stray_dot_remove', '', ''))
        return result

    def _insert_missing_spaces(self, text: str, ops: list[HealingOp]) -> str:
        """Insert spaces at alpha-digit boundaries: 'M8bolt' → 'M8 bolt'."""
        result = text
        # Don't touch known patterns like M8, SS304, etc.
        # Only insert space when a multi-char alpha word follows digits without space
        pattern = re.compile(r'([A-Za-z])(\d+)([a-z]{3,})', re.I)
        for m in pattern.finditer(result):
            # e.g., M8bolt → we want "M8 bolt", but keep "SS304" as is
            full = m.group(0)
            prefix = m.group(1) + m.group(2)
            suffix = m.group(3)
            if suffix.lower() in ('mm', 'cm', 'in', 'ft', 'kg', 'ohm', 'v', 'w', 'hz', 'pcs', 'ea'):
                continue  # Don't split measurement units
            replacement = f'{prefix} {suffix}'
            result = result.replace(full, replacement, 1)
            ops.append(HealingOp('ocr_space_insert', full, replacement))

        # Also handle: digit immediately followed by alpha word (3+ chars)
        pattern2 = re.compile(r'(\d)([a-zA-Z]{3,})\b')
        for m in pattern2.finditer(result):
            full = m.group(0)
            digit_part = m.group(1)
            alpha_part = m.group(2)
            if alpha_part.lower() in ('mm', 'cm', 'in', 'ft', 'kg', 'ohm', 'ohms', 'pcs', 'ea',
                                       'khz', 'mhz', 'ghz', 'kohm', 'mohm'):
                continue
            replacement = f'{digit_part} {alpha_part}'
            result = result.replace(full, replacement, 1)
            ops.append(HealingOp('ocr_space_insert', full, replacement))

        return result

    def _normalize_whitespace(self, text: str, ops: list[HealingOp]) -> str:
        """Normalize whitespace: multiple spaces → single, tabs → space, NBSP → space."""
        result = text
        # NBSP and other whitespace to regular space
        result = result.replace('\u00a0', ' ')
        result = result.replace('\t', ' ')
        result = result.replace('\r', ' ')
        result = result.replace('\n', ' ')

        cleaned = re.sub(r'\s+', ' ', result).strip()
        if cleaned != text.strip():
            ops.append(HealingOp('whitespace_normalize', '', ''))
        return cleaned
