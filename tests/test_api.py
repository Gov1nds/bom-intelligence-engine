"""Tests for API endpoints per api-contract-review.md."""
import sys
from pathlib import Path
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient
from main import app


client = TestClient(app)


class TestHealthProbes:
    def test_root(self):
        resp = client.get("/")
        assert resp.status_code == 200
        assert resp.json()["version"] == "5.0.0"

    def test_readiness(self):
        assert client.get("/readiness").status_code == 200

    def test_liveness(self):
        assert client.get("/liveness").status_code == 200

    def test_startup(self):
        assert client.get("/startup").status_code == 200


class TestNormalizeEndpoint:
    def test_valid_request(self):
        resp = client.post("/api/normalize", json={
            "bom_line_id": str(uuid4()),
            "raw_text": "M8x25 hex bolt stainless steel",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "normalized" in data
        assert "confidence" in data
        assert "events" in data

    def test_missing_raw_text(self):
        resp = client.post("/api/normalize", json={
            "bom_line_id": str(uuid4()),
            "raw_text": "",
        })
        assert resp.status_code == 422  # Pydantic validation


class TestEnrichEndpoint:
    def test_valid_request(self):
        resp = client.post("/api/enrich", json={
            "bom_line_id": str(uuid4()),
            "normalized_data": {"part_name": "M8 bolt", "category": "fastener", "quantity": 10},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "market_enrichment" in data
        assert "risk_flags" in data


class TestScoreEndpoint:
    def test_valid_request(self):
        resp = client.post("/api/score", json={
            "bom_line_id": str(uuid4()),
            "candidate_vendors": [
                {"vendor_id": "V-001", "unit_price": "10.00", "capabilities": ["machining"]},
            ],
            "weight_profile": "balanced",
        })
        assert resp.status_code == 200
        assert "vendor_scores" in resp.json()


class TestStrategyEndpoint:
    def test_valid_request(self):
        resp = client.post("/api/strategy", json={
            "bom_line_id": str(uuid4()),
            "score_data": {"vendor_scores": []},
            "enrichment_data": {},
        })
        assert resp.status_code == 200
        assert "strategy_recommendation" in resp.json()


class TestAnalyzeBom:
    def test_unsupported_file_type(self):
        from io import BytesIO
        resp = client.post(
            "/api/analyze-bom",
            files={"file": ("test.pdf", BytesIO(b"fake"), "application/pdf")},
        )
        assert resp.status_code == 400
        assert "UNSUPPORTED_FILE_TYPE" in str(resp.json())

    def test_valid_csv(self):
        from io import BytesIO
        csv_content = b"description,quantity\nM8 bolt,10\nM10 nut,20\n"
        resp = client.post(
            "/api/analyze-bom",
            files={"file": ("test.csv", BytesIO(csv_content), "text/csv")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "components" in data
        assert "summary" in data


class TestErrorResponse:
    def test_error_envelope(self):
        resp = client.post("/api/normalize", json={"invalid": True})
        assert resp.status_code == 422  # Pydantic validation error
