"""Comprehensive tests for domain extractors — WP-11-B."""
from __future__ import annotations

import pytest
from engine.specs.extractors.fastener import FastenerExtractor
from engine.specs.extractors.electronics import ElectronicsExtractor
from engine.specs.extractors.mechanical import MechanicalExtractor
from engine.specs.extractors.sheet_metal import SheetMetalExtractor
from engine.specs.extractors.raw_material import RawMaterialExtractor
from engine.specs.extractors.electrical import ElectricalExtractor
from engine.specs.extractors.cable_wiring import CableWiringExtractor
from engine.specs.extractors.fluid_power import FluidPowerExtractor
from engine.specs.domain_dispatcher import DomainDispatcher


class TestFastenerExtractor:
    @pytest.fixture
    def extractor(self):
        return FastenerExtractor()

    def test_metric_thread_simple(self, extractor):
        result = extractor.extract("m8 hex bolt stainless steel 30 mm", [])
        assert result.attributes.get("thread_size") == "M8"
        assert result.attributes.get("material") == "stainless_steel"

    def test_metric_thread_with_pitch(self, extractor):
        result = extractor.extract("M10x1.5 bolt 40mm", [])
        assert result.attributes.get("thread_size") == "M10x1.5"

    def test_unc_thread(self, extractor):
        result = extractor.extract("1/4-20 UNC hex bolt", [])
        assert "1/4-20" in result.attributes.get("thread_size", "")

    def test_bsp_thread(self, extractor):
        result = extractor.extract("1/4 BSP fitting", [])
        assert "BSP" in result.attributes.get("thread_size", "")

    def test_npt_thread(self, extractor):
        result = extractor.extract("1/2 NPT pipe fitting", [])
        assert "NPT" in result.attributes.get("thread_size", "")

    def test_head_type_hex(self, extractor):
        result = extractor.extract("hex bolt M8", [])
        assert result.attributes.get("head_type") == "hex"

    def test_head_type_socket(self, extractor):
        result = extractor.extract("socket head cap screw M6", [])
        assert result.attributes.get("head_type") == "socket"

    def test_head_type_countersunk(self, extractor):
        result = extractor.extract("countersunk screw M4", [])
        assert result.attributes.get("head_type") == "countersunk"

    def test_head_type_button(self, extractor):
        result = extractor.extract("button head cap screw M5", [])
        assert result.attributes.get("head_type") == "button"

    def test_grade_class_88(self, extractor):
        result = extractor.extract("M10 bolt grade 8.8", [])
        assert result.attributes.get("grade_class") == "8.8"

    def test_grade_class_a2(self, extractor):
        result = extractor.extract("M8 bolt A2-70", [])
        assert result.attributes.get("grade_class") == "A2-70"

    def test_fastener_length(self, extractor):
        result = extractor.extract("M8 bolt 30 mm stainless steel", [])
        assert result.attributes.get("length_mm") == 30.0

    def test_nut_detection(self, extractor):
        result = extractor.extract("M10 hex nut stainless steel", [])
        assert result.attributes.get("fastener_type") == "nut"

    def test_washer_detection(self, extractor):
        result = extractor.extract("M8 flat washer zinc plated", [])
        assert result.attributes.get("fastener_type") == "washer"

    def test_stud_detection(self, extractor):
        result = extractor.extract("M12 stud 100mm steel", [])
        assert result.attributes.get("fastener_type") == "stud"

    def test_material_stainless(self, extractor):
        result = extractor.extract("M8 bolt stainless steel 304", [])
        assert "stainless_steel" in result.attributes.get("material", "")

    def test_finish_zinc(self, extractor):
        result = extractor.extract("M8 bolt zinc plated", [])
        assert result.attributes.get("finish") == "zinc_plated"

    def test_complete_fastener_no_missing(self, extractor):
        result = extractor.extract("M8 hex bolt 30mm stainless steel grade 8.8", [])
        assert len(result.missing_critical) == 0

    def test_incomplete_fastener_missing_fields(self, extractor):
        result = extractor.extract("bolt", [])
        assert len(result.missing_critical) > 0


class TestElectronicsExtractor:
    @pytest.fixture
    def extractor(self):
        return ElectronicsExtractor()

    def test_resistor_kohm(self, extractor):
        result = extractor.extract("10kohm resistor 5% 0.25w 0603", [])
        assert result.attributes.get("resistance_ohm") == 10000.0
        assert result.attributes.get("part_type") == "resistor"

    def test_resistor_megaohm(self, extractor):
        result = extractor.extract("1Mohm resistor", [])
        assert result.attributes.get("resistance_ohm") == 1e6

    def test_capacitor_uf(self, extractor):
        result = extractor.extract("4.7uF capacitor 50v x7r 0805", [])
        assert abs(result.attributes.get("capacitance_f", 0) - 4.7e-6) < 1e-10
        assert result.attributes.get("part_type") == "capacitor"

    def test_capacitor_nf(self, extractor):
        result = extractor.extract("100nF capacitor", [])
        assert abs(result.attributes.get("capacitance_f", 0) - 100e-9) < 1e-14

    def test_capacitor_pf(self, extractor):
        result = extractor.extract("22pF capacitor", [])
        assert abs(result.attributes.get("capacitance_f", 0) - 22e-12) < 1e-16

    def test_inductor_uh(self, extractor):
        result = extractor.extract("10uH inductor", [])
        assert abs(result.attributes.get("inductance_h", 0) - 10e-6) < 1e-10

    def test_voltage(self, extractor):
        result = extractor.extract("capacitor 50V", [])
        assert result.attributes.get("voltage_v") == 50.0

    def test_tolerance(self, extractor):
        result = extractor.extract("resistor 5%", [])
        assert result.attributes.get("tolerance_percent") == 5.0

    def test_power_fractional(self, extractor):
        result = extractor.extract("resistor 1/4W", [])
        assert result.attributes.get("power_w") == 0.25

    def test_power_decimal(self, extractor):
        result = extractor.extract("resistor 0.25W", [])
        assert result.attributes.get("power_w") == 0.25

    def test_package_0603(self, extractor):
        result = extractor.extract("resistor 10k 0603", [])
        assert result.attributes.get("package") == "0603"

    def test_package_0805(self, extractor):
        result = extractor.extract("capacitor 100nF 0805", [])
        assert result.attributes.get("package") == "0805"

    def test_dielectric_x7r(self, extractor):
        result = extractor.extract("capacitor 100nF X7R", [])
        assert result.attributes.get("dielectric") == "X7R"

    def test_dielectric_c0g(self, extractor):
        result = extractor.extract("capacitor 22pF C0G", [])
        assert result.attributes.get("dielectric") == "C0G"

    def test_led_detection(self, extractor):
        result = extractor.extract("LED red 3mm", [])
        assert result.attributes.get("part_type") == "led"

    def test_mosfet_detection(self, extractor):
        result = extractor.extract("MOSFET N-channel 60V 30A", [])
        assert result.attributes.get("part_type") == "mosfet"

    def test_implied_resistance(self, extractor):
        result = extractor.extract("10K resistor", [])
        assert result.attributes.get("resistance_ohm") == 10000.0


class TestMechanicalExtractor:
    @pytest.fixture
    def extractor(self):
        return MechanicalExtractor()

    def test_dimensions(self, extractor):
        result = extractor.extract("bracket aluminum 50x30x5mm", [])
        assert result.attributes.get("material") is not None

    def test_diameter(self, extractor):
        result = extractor.extract("shaft dia 25mm steel", [])
        assert result.attributes.get("diameter_mm") == 25.0

    def test_tolerance_class(self, extractor):
        result = extractor.extract("shaft H7 25mm", [])
        assert result.attributes.get("tolerance_class") == "H7"

    def test_surface_finish(self, extractor):
        result = extractor.extract("shaft Ra 0.8 um", [])
        assert result.attributes.get("surface_finish_ra_um") == 0.8

    def test_hardness(self, extractor):
        result = extractor.extract("shaft 58 HRC tool steel", [])
        assert result.attributes.get("hardness_hrc") == 58.0

    def test_process_hints(self, extractor):
        result = extractor.extract("cnc machined bracket aluminum", [])
        assert "cnc_machining" in result.attributes.get("process_hints", [])


class TestSheetMetalExtractor:
    @pytest.fixture
    def extractor(self):
        return SheetMetalExtractor()

    def test_thickness(self, extractor):
        result = extractor.extract("sheet metal 1.5mm thk steel laser cut", [])
        assert result.attributes.get("thickness_mm") == 1.5

    def test_gauge_to_mm(self, extractor):
        result = extractor.extract("18 gauge sheet steel", [])
        assert result.attributes.get("thickness_mm") is not None
        assert result.attributes.get("gauge") == 18

    def test_process_hints_laser(self, extractor):
        result = extractor.extract("sheet metal laser cut 2mm steel", [])
        assert "laser_cutting" in result.attributes.get("process_hints", [])

    def test_process_hints_bend(self, extractor):
        result = extractor.extract("sheet metal bend 1.5mm", [])
        assert "bending" in result.attributes.get("process_hints", [])


class TestRawMaterialExtractor:
    @pytest.fixture
    def extractor(self):
        return RawMaterialExtractor()

    def test_flat_bar(self, extractor):
        result = extractor.extract("aluminum 6061 flat bar 25x6mm", [])
        assert result.attributes.get("form") == "flat_bar"

    def test_round_bar(self, extractor):
        result = extractor.extract("steel round bar dia 25mm", [])
        assert result.attributes.get("form") in ("round_bar", "bar")

    def test_tube(self, extractor):
        result = extractor.extract("stainless steel tube 25x2mm", [])
        assert result.attributes.get("form") == "tube"

    def test_sheet(self, extractor):
        result = extractor.extract("aluminum sheet 2mm", [])
        assert result.attributes.get("form") == "sheet"

    def test_temper_grade(self, extractor):
        result = extractor.extract("aluminum 6061-T6 bar", [])
        assert result.attributes.get("grade") == "T6"

    def test_length_meters(self, extractor):
        result = extractor.extract("steel rod 3m long", [])
        assert result.attributes.get("length_mm") == 3000.0


class TestElectricalExtractor:
    @pytest.fixture
    def extractor(self):
        return ElectricalExtractor()

    def test_voltage(self, extractor):
        result = extractor.extract("relay 24VDC", [])
        assert result.attributes.get("voltage_v") == 24.0

    def test_current(self, extractor):
        result = extractor.extract("circuit breaker 16A", [])
        assert result.attributes.get("current_a") == 16.0

    def test_ip_rating(self, extractor):
        result = extractor.extract("enclosure IP65", [])
        assert result.attributes.get("ip_rating") == "IP65"

    def test_pole_count(self, extractor):
        result = extractor.extract("3 pole circuit breaker", [])
        assert result.attributes.get("pole_count") == 3


class TestFluidPowerExtractor:
    @pytest.fixture
    def extractor(self):
        return FluidPowerExtractor()

    def test_pressure_bar(self, extractor):
        result = extractor.extract("pneumatic cylinder 10 bar", [])
        assert result.attributes.get("pressure_rating_bar") == 10.0

    def test_pressure_psi(self, extractor):
        result = extractor.extract("hydraulic valve 150 psi", [])
        assert result.attributes.get("pressure_rating_bar") is not None
        assert abs(result.attributes["pressure_rating_bar"] - 10.34) < 0.1

    def test_bore(self, extractor):
        result = extractor.extract("cylinder bore 50mm stroke 100mm", [])
        assert result.attributes.get("bore_mm") == 50.0
        assert result.attributes.get("stroke_mm") == 100.0


class TestDomainDispatcher:
    @pytest.fixture
    def dispatcher(self):
        return DomainDispatcher()

    def test_fastener_routing(self, dispatcher):
        result = dispatcher.dispatch("fastener", "M8 bolt 30mm stainless steel", [])
        assert result.extraction_method == "fastener_extractor"
        assert "thread_size" in result.attributes

    def test_electronics_routing(self, dispatcher):
        result = dispatcher.dispatch("electronics", "10kohm resistor 0603", [])
        assert result.extraction_method == "electronics_extractor"

    def test_passive_component_routing(self, dispatcher):
        result = dispatcher.dispatch("passive_component", "4.7uF capacitor 50V", [])
        assert result.extraction_method == "electronics_extractor"

    def test_sheet_metal_routing(self, dispatcher):
        result = dispatcher.dispatch("sheet_metal", "1.5mm steel sheet laser cut", [])
        assert result.extraction_method == "sheet_metal_extractor"

    def test_unknown_routing(self, dispatcher):
        result = dispatcher.dispatch("unknown", "some unknown part", [])
        assert result.extraction_method == "generic_extractor"

    def test_graceful_degradation(self, dispatcher):
        # Should not crash on bad input
        result = dispatcher.dispatch("fastener", "", [])
        assert isinstance(result.attributes, dict)
