from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import main as engine_main

client = TestClient(engine_main.app)


def test_multipart_upload_contract(tmp_path):
    fake_result = {"ok": True, "contract": "upload"}

    def fake_run_pipeline(file_path, user_location="", target_currency="USD", email=""):
        assert Path(file_path).exists() is True
        return fake_result

    with patch.object(engine_main.engine, "run_pipeline", side_effect=fake_run_pipeline) as mocked:
        response = client.post(
            "/api/analyze-bom",
            files={"file": ("sample.csv", b"part_name,quantity\nbolt,1\n", "text/csv")},
            data={"user_location": "Mumbai, India", "target_currency": "USD", "email": "buyer@example.com"},
        )

    assert response.status_code == 200
    assert response.json() == fake_result
    assert mocked.call_count == 1


def test_path_input_contract(tmp_path, monkeypatch):
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    input_file = upload_dir / "sample.csv"
    input_file.write_text("part_name,quantity\nbolt,1\n")

    monkeypatch.setattr(engine_main, "UPLOAD_DIR", upload_dir.resolve())
    monkeypatch.setattr(engine_main, "ALLOW_ARBITRARY_PATH_INPUT", False)

    fake_result = {"ok": True, "contract": "path"}

    def fake_run_pipeline(file_path, user_location="", target_currency="USD", email=""):
        assert Path(file_path).resolve() == input_file.resolve()
        return fake_result

    with patch.object(engine_main.engine, "run_pipeline", side_effect=fake_run_pipeline) as mocked:
        response = client.post(
            "/api/analyze-bom-path",
            data={"file_path": str(input_file), "user_location": "Mumbai, India", "target_currency": "USD"},
        )

    assert response.status_code == 200
    assert response.json() == fake_result
    assert mocked.call_count == 1