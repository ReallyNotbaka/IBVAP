"""Unit and integration tests for Models API endpoints."""

from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from ibvap.api.app import create_app
from ibvap.core.model_manager import (
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

    def test_delete_base_model_returns_400(self, test_client: TestClient) -> None:
        resp = test_client.delete("/api/v1/models/yolo26n/weights")
        assert resp.status_code == 400
        assert "base default model" in resp.json()["detail"].lower()

    def test_delete_active_model_returns_400(self, test_client: TestClient, tmp_path: Path) -> None:
        handle = get_shared_detector_handle()
        handle._active_model_name = "yolo26s"
        try:
            resp = test_client.delete("/api/v1/models/yolo26s/weights")
            assert resp.status_code == 400
            assert "active" in resp.json()["detail"].lower()
        finally:
            handle._active_model_name = "yolo26n"

    def test_delete_downloaded_model_weights(self, test_client: TestClient, tmp_path: Path) -> None:
        # First upload weights for yolo26m
        content = b"ONNX-MODEL-HEADER" + b"M" * 2000
        files = {"file": ("yolo26m.onnx", content, "application/octet-stream")}
        data = {"model_name": "yolo26m"}
        resp = test_client.post("/api/v1/models/upload", data=data, files=files)
        assert resp.status_code == 200

        # Verify it is installed
        resp_list = test_client.get("/api/v1/models")
        m_mod = next(m for m in resp_list.json()["models"] if m["name"] == "yolo26m")
        assert m_mod["is_installed"] is True

        # Delete weights
        resp_del = test_client.delete("/api/v1/models/yolo26m/weights")
        assert resp_del.status_code == 200
        assert resp_del.json()["status"] == "deleted"

        # Verify it is no longer installed
        resp_list2 = test_client.get("/api/v1/models")
        m_mod2 = next(m for m in resp_list2.json()["models"] if m["name"] == "yolo26m")
        assert m_mod2["is_installed"] is False
