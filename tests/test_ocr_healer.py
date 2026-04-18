"""Comprehensive tests for OCR healer — WP-11-D."""
from __future__ import annotations

import pytest
from engine.normalization.ocr_healer import OcrHealer


@pytest.fixture
def healer():
    return OcrHealer()


class TestEncodingNormalization:
    def test_strip_bom(self, healer):
        text, ops = healer.heal("\ufeffM8 bolt")
        assert text == "M8 bolt"

    def test_nfkc_normalization(self, healer):
        text, _ = healer.heal("ﬁne")  # fi ligature
        assert "fi" in text


class TestOCRCharacterConfusions:
    def test_zero_to_O_in_bolt(self, healer):
        text, ops = healer.heal("B0lt M8x30")
        assert "Bolt" in text
        assert any(op["rule"] == "ocr_0_to_O" for op in ops)

    def test_one_to_i_in_resistor(self, healer):
        text, _ = healer.heal("Res1stor 10K")
        assert "Resistor" in text or "resistor" in text.lower()

    def test_three_to_e_in_washer(self, healer):
        text, _ = healer.heal("Wash3r M8")
        assert "Washer" in text or "washer" in text.lower()


class TestDecimalComma:
    def test_european_decimal_comma(self, healer):
        text, ops = healer.heal("0,5 mm")
        assert "0.5" in text

    def test_decimal_comma_in_dimension(self, healer):
        text, _ = healer.heal("1,5mm thick sheet")
        assert "1.5" in text

    def test_thousands_not_converted(self, healer):
        # 1,000 should become 1000, not 1.000
        text, _ = healer.heal("1,000 kg")
        assert "1000" in text


class TestMultiplicationSign:
    def test_unicode_times(self, healer):
        text, _ = healer.heal("2×4×10 mm")
        assert "2x4x10" in text

    def test_heavy_multiplication(self, healer):
        text, _ = healer.heal("2✕4 mm")
        assert "2x4" in text


class TestGreekCharacters:
    def test_omega_to_ohm(self, healer):
        text, _ = healer.heal("10 Ω resistor")
        assert "ohm" in text

    def test_mu_to_u(self, healer):
        text, _ = healer.heal("4.7µF")
        assert "4.7uF" in text


class TestSuperscriptSubscript:
    def test_squared(self, healer):
        text, _ = healer.heal("mm²")
        assert "mm2" in text

    def test_cubed(self, healer):
        text, _ = healer.heal("cm³")
        assert "cm3" in text


class TestThousandsSeparator:
    def test_us_thousands(self, healer):
        text, _ = healer.heal("1,000 kg")
        assert "1000" in text

    def test_european_thousands(self, healer):
        text, _ = healer.heal("1.000,50 kg")
        assert "1000.50" in text or "1000.5" in text


class TestSpaceInsertion:
    def test_digit_alpha_boundary(self, healer):
        # M8bolt should get space inserted
        text, _ = healer.heal("M8bolt")
        assert "M8 bolt" in text

    def test_no_split_measurement_unit(self, healer):
        # 30mm should NOT become "30 mm" (healer doesn't touch this)
        text, _ = healer.heal("30mm")
        assert "30mm" in text  # healer preserves; text_normalizer adds space later


class TestWhitespace:
    def test_multiple_spaces(self, healer):
        text, _ = healer.heal("bolt   hex   M8")
        assert "bolt hex M8" == text

    def test_tabs(self, healer):
        text, _ = healer.heal("bolt\thex\tM8")
        assert "bolt hex M8" == text

    def test_nbsp(self, healer):
        text, _ = healer.heal("bolt\u00a0hex")
        assert "bolt hex" == text


class TestBrackets:
    def test_fullwidth_brackets(self, healer):
        text, _ = healer.heal("bolt【M8】")
        assert "bolt[M8]" in text

    def test_fullwidth_parens(self, healer):
        text, _ = healer.heal("bolt（M8）")
        assert "bolt(M8)" in text


class TestQuotes:
    def test_smart_quotes(self, healer):
        text, _ = healer.heal("\u201cM8\u201d bolt")
        assert '"M8"' in text


class TestHyphens:
    def test_em_dash(self, healer):
        text, _ = healer.heal("M8\u2014bolt")
        assert "M8-bolt" in text

    def test_en_dash(self, healer):
        text, _ = healer.heal("M8\u2013bolt")
        assert "M8-bolt" in text


class TestStrayDots:
    def test_stray_dot_between_words(self, healer):
        text, _ = healer.heal("bolt . hex")
        assert "bolt hex" in text


class TestHealingOperationsLogged:
    def test_operations_returned(self, healer):
        _, ops = healer.heal("B0lt 0,5mm 2×4mm")
        assert len(ops) > 0
        assert all("rule" in op for op in ops)

    def test_no_ops_for_clean_text(self, healer):
        _, ops = healer.heal("M8 hex bolt 30mm stainless steel")
        # Clean text should have minimal ops (maybe just whitespace)
        assert len(ops) <= 1
