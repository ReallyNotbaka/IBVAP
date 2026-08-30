from __future__ import annotations

from fastapi.testclient import TestClient

from ibvap.api.app import create_app


def test_health_endpoint() -> None:
    app = create_app()
    client = TestClient(app)
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["version"] == "0.1.0"
    assert "timestamp" in data
    assert data["checks"]["api"] == "ok"


def test_capabilities_endpoint() -> None:
    app = create_app()
    client = TestClient(app)
    resp = client.get("/api/v1/capabilities")
    assert resp.status_code == 200
    data = resp.json()
    assert data["version"] == "0.1.0"
    assert data["python"] == "3.12"
    assert "YOLO26 BLOCKED" in data["detectors"]["primary"]
    assert data["features"]["smartphone_ip_webcam"] is True
    assert "mediamtx" in data["media"]["gateway"].lower()
    assert "PyAV" in data["media"]["decoder"]


def test_version_endpoint() -> None:
    app = create_app()
    client = TestClient(app)
    resp = client.get("/api/v1/system/version")
    assert resp.status_code == 200
    assert resp.json()["version"] == "0.1.0"
