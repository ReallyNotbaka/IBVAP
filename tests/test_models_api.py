"""Unit and integration tests for Models API endpoints."""

from __future__ import annotations

from pathlib import Path
import pytest
from starlette.testclient import TestClient

from ibvap.api.app import create_app
from ibvap.core.model_manager import (
    YOLO_MODELS_MANIFEST,
    get_download_manager,
    get_model_registry,
    get_shared_detector_handle,
)


@pytest.fixture
def test_client(tmp_path: Path):
    registry = get_model_registry()
    registry.models_dir = tmp_path
    dm = get_download_manager()
    dm.models_dir = tmp_path
    
    app = create_app()
    with TestClient(app) as client:
        yield client


class TestModelsAPI:
    def test_list_models(self, test_client: TestClient) -> None:
        resp = test_client.get("/api/v1/models")
        assert resp.status_code == 200
        data = resp.json()
        assert "models" in data
        assert len(data["models"]) == 5
        names = [m["name"] for m in data["models"]]
        assert "yolo26n" in names
        assert "yolo26x" in names

    def test_activate_missing_model_returns_400(self, test_client: TestClient) -> None:
        resp = test_client.post("/api/v1/models/activate", json={"model_name": "yolo26x"})
        assert resp.status_code == 400
        assert "not installed" in resp.json()["detail"]

    def test_upload_offline_model(self, test_client: TestClient, tmp_path: Path) -> None:
        content = b"ONNX-MODEL-HEADER" + b"X" * 2000
        files = {"file": ("yolo26s.onnx", content, "application/octet-stream")}
        data = {"model_name": "yolo26s"}
        
        resp = test_client.post("/api/v1/models/upload", data=data, files=files)
        assert resp.status_code == 200
        assert resp.json()["status"] == "uploaded"
        
        # Verify it now shows as installed
        resp_list = test_client.get("/api/v1/models")
        s_mod = next(m for m in resp_list.json()["models"] if m["name"] == "yolo26s")
        assert s_mod["is_installed"] is True
