import pytest

from engine.ingestion.ubne import normalize_row, deduplicate
from engine.classification.classifier import classify_item
from core.schemas import BOMItem


def test_dedup_merges_duplicate_rows():
    rows = [
        {
            "part_number": "M6-25",
            "manufacturer": "ABC",
            "material": "SS304",
            "category": "fastener",
            "normalized_description": "hex bolt m6x25",
            "quantity": 2,
            "source_rows": [1],
            "source_sheets": ["Sheet1"],
        },
        {
            "part_number": "M6-25",
            "manufacturer": "ABC",
            "material": "SS304",
            "category": "fastener",
            "normalized_description": "hex bolt m6x25",
            "quantity": 3,
            "source_rows": [2],
            "source_sheets": ["Sheet1"],
        },
    ]
    out = deduplicate(rows)
    assert len(out) == 1
    assert out[0]["quantity"] == 5


@pytest.mark.parametrize(
    "text,expected",
    [
        ("M6 bolt SS304", "fastener"),
        ("pneumatic solenoid valve 24v", "pneumatic"),
        ("hydraulic hose fitting", "hydraulic"),
        ("shielded cable 18awg", "cable_wiring"),
        ("fiber optic cable", "optical"),
        ("thermal pad 1.5mm", "thermal"),
    ],
)
def test_category_boundaries(text, expected):
    item = BOMItem(
        item_id="1",
        description=text,
        raw_text=text,
        quantity=1,
        part_number="",
        manufacturer="",
        material="",
        unit="each",
        supplier_name="",
        make="",
        notes="",
    )
    c = classify_item(item)
    assert c.category.value == expected