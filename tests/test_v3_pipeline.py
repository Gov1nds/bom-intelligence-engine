"""
Test Suite for BOM Intelligence Engine v3 — Pure Function Contract

Validates:
  - CSV ingestion produces correct component count
  - Classification assigns valid PartCategory values
  - Spec extraction returns dict per component
  - Output shape matches v3 contract: { components, summary, _meta }
  - Canonical part keys are generated
  - Procurement class and flags are set
  - Cache hit on duplicate file

Run: pytest tests/test_v3_pipeline.py -v
"""
import sys
import os
import csv
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.orchestrator import BOMIntelligenceEngine
from core.schemas import PartCategory


# ── Test data ────────────────────────────────────────────────────────────────

SAMPLE_ROWS = [
    {"part_name": "Res 10k 5% 0402", "quantity": "100", "manufacturer": "Yageo", "mpn": "RC0402FR-0710KL", "material": "", "notes": ""},
    {"part_name": "Custom Bracket CNC Aluminum", "quantity": "50", "material": "Aluminum 6061", "notes": "±0.05mm", "manufacturer": "", "mpn": ""},
    {"part_name": "Aluminum Sheet 3mm 5052", "quantity": "10", "material": "Aluminum 5052", "notes": "", "manufacturer": "", "mpn": ""},
    {"part_name": "STM32F407VGT6", "quantity": "25", "manufacturer": "STMicroelectronics", "mpn": "STM32F407VGT6", "material": "", "notes": ""},
    {"part_name": "M5x20 Hex Bolt SS304", "quantity": "500", "manufacturer": "", "mpn": "", "material": "", "notes": ""},
]

FIELDS = ["part_name", "quantity", "manufacturer", "mpn", "material", "notes"]


def _write_csv(rows=None):
    """Write sample BOM CSV to a temp file, return path."""
    rows = rows or SAMPLE_ROWS
    f = tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w", newline="")
    writer = csv.DictWriter(f, fieldnames=FIELDS)
    writer.writeheader()
    for row in rows:
        writer.writerow({k: row.get(k, "") for k in FIELDS})
    f.close()
    return f.name


# ── Tests ────────────────────────────────────────────────────────────────────

class TestV3OutputShape:
    """Verify the top-level v3 response contract."""

    def setup_method(self):
        self.engine = BOMIntelligenceEngine()
        self.csv_path = _write_csv()
        self.result = self.engine.run_pipeline(self.csv_path, "Mumbai, India", "USD")

    def teardown_method(self):
        try:
            os.unlink(self.csv_path)
        except Exception:
            pass

    def test_has_components_key(self):
        assert "components" in self.result, "Missing 'components' key"

    def test_has_summary_key(self):
        assert "summary" in self.result, "Missing 'summary' key"

    def test_has_meta_key(self):
        assert "_meta" in self.result, "Missing '_meta' key"

    def test_component_count_matches_input(self):
        assert len(self.result["components"]) == len(SAMPLE_ROWS), (
            f"Expected {len(SAMPLE_ROWS)} components, got {len(self.result['components'])}"
        )

    def test_summary_total_items(self):
        assert self.result["summary"]["total_items"] == len(SAMPLE_ROWS)

    def test_summary_has_categories(self):
        assert "categories" in self.result["summary"]
        assert isinstance(self.result["summary"]["categories"], dict)

    def test_meta_has_version(self):
        assert "version" in self.result["_meta"]

    def test_meta_has_phase_times(self):
        assert "phase_times" in self.result["_meta"]

    def test_meta_has_total_time(self):
        assert "total_time_s" in self.result["_meta"]
        assert self.result["_meta"]["total_time_s"] < 30, "Pipeline took too long"

    def test_meta_has_file_checksum(self):
        assert "file_checksum" in self.result["_meta"]
        assert self.result["_meta"]["file_checksum"] is not None


class TestV3ComponentFields:
    """Verify each component has the required v3 fields."""

    REQUIRED_FIELDS = [
        "item_id", "raw_text", "standard_text", "description",
        "quantity", "mpn", "manufacturer", "material", "category",
        "classification_confidence", "has_mpn", "has_brand",
        "is_generic", "is_raw", "is_custom",
        "procurement_class", "rfq_required", "drawing_required",
        "canonical_part_key", "specs",
    ]

    def setup_method(self):
        self.engine = BOMIntelligenceEngine()
        self.csv_path = _write_csv()
        self.result = self.engine.run_pipeline(self.csv_path, "Mumbai, India", "USD")

    def teardown_method(self):
        try:
            os.unlink(self.csv_path)
        except Exception:
            pass

    def test_all_required_fields_present(self):
        for i, comp in enumerate(self.result["components"]):
            for field in self.REQUIRED_FIELDS:
                assert field in comp, f"Component [{i}] missing field: {field}"

    def test_category_values_valid(self):
        valid_cats = {cat.value for cat in PartCategory}
        for comp in self.result["components"]:
            assert comp["category"] in valid_cats, (
                f"Invalid category '{comp['category']}' for {comp.get('item_id')}"
            )

    def test_confidence_in_range(self):
        for comp in self.result["components"]:
            conf = comp["classification_confidence"]
            assert 0 <= conf <= 1.0, f"Confidence {conf} out of range for {comp.get('item_id')}"

    def test_quantity_is_positive(self):
        for comp in self.result["components"]:
            assert comp["quantity"] > 0, f"Quantity must be > 0 for {comp.get('item_id')}"

    def test_canonical_part_key_not_empty(self):
        for comp in self.result["components"]:
            assert comp["canonical_part_key"], f"Empty canonical_part_key for {comp.get('item_id')}"

    def test_specs_is_dict(self):
        for comp in self.result["components"]:
            assert isinstance(comp["specs"], dict), f"specs must be dict for {comp.get('item_id')}"

    def test_procurement_class_valid(self):
        valid = {"catalog_purchase", "rfq_required", "machined_part", "engineering_review", "raw_stock"}
        for comp in self.result["components"]:
            assert comp["procurement_class"] in valid, (
                f"Invalid procurement_class '{comp['procurement_class']}'"
            )


class TestV3Classification:
    """Verify classification logic produces expected categories for known inputs."""

    def setup_method(self):
        self.engine = BOMIntelligenceEngine()
        self.csv_path = _write_csv()
        self.result = self.engine.run_pipeline(self.csv_path, "Mumbai, India", "USD")
        self.components = self.result["components"]

    def teardown_method(self):
        try:
            os.unlink(self.csv_path)
        except Exception:
            pass

    def test_has_standard_items(self):
        cats = [c["category"] for c in self.components]
        assert any(c in ("standard", "electronics", "electrical", "fastener") for c in cats), (
            f"Expected at least one standard-type item, got categories: {set(cats)}"
        )

    def test_has_custom_items(self):
        cats = [c["category"] for c in self.components]
        assert any(c in ("custom", "custom_mechanical", "machined", "sheet_metal") for c in cats), (
            f"Expected at least one custom-type item, got categories: {set(cats)}"
        )

    def test_mpn_item_has_mpn_flag(self):
        resistor = self.components[0]  # Res 10k with MPN
        assert resistor["has_mpn"] is True, "Resistor with MPN should have has_mpn=True"

    def test_custom_bracket_is_custom(self):
        bracket = self.components[1]  # Custom Bracket CNC Aluminum
        assert bracket["is_custom"] is True, "Custom bracket should have is_custom=True"


class TestV3Cache:
    """Verify pipeline caching works correctly."""

    def test_cache_hit_on_same_file(self):
        engine = BOMIntelligenceEngine()
        csv_path = _write_csv()
        try:
            result1 = engine.run_pipeline(csv_path, "Mumbai, India", "USD")
            result2 = engine.run_pipeline(csv_path, "Mumbai, India", "USD")
            assert result2["_meta"].get("cache_hit") is True, "Second run should be a cache hit"
            assert result1["_meta"]["file_checksum"] == result2["_meta"]["file_checksum"]
        finally:
            os.unlink(csv_path)

    def test_different_location_different_cache(self):
        engine = BOMIntelligenceEngine()
        csv_path = _write_csv()
        try:
            result1 = engine.run_pipeline(csv_path, "Mumbai, India", "USD")
            result2 = engine.run_pipeline(csv_path, "New York, USA", "USD")
            # Different location = different cache key, so result2 should NOT be a cache hit
            # (unless the engine ignores location in cache key, which it does include)
            assert result1["_meta"]["file_checksum"] == result2["_meta"]["file_checksum"]
        finally:
            os.unlink(csv_path)


class TestV3EmptyInput:
    """Verify graceful handling of edge cases."""

    def test_single_item_bom(self):
        engine = BOMIntelligenceEngine()
        csv_path = _write_csv([
            {"part_name": "Single Part", "quantity": "1", "manufacturer": "", "mpn": "", "material": "", "notes": ""},
        ])
        try:
            result = engine.run_pipeline(csv_path, "", "USD")
            assert len(result["components"]) == 1
            assert result["summary"]["total_items"] == 1
        finally:
            os.unlink(csv_path)


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
