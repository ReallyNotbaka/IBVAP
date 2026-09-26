"""Tests for forensic evidence capture and system settings / C2 dispatch."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from ibvap.api.app import create_app
from ibvap.core.dispatcher import (
    SystemSettings,
    get_settings,
    save_settings,
)
from ibvap.core.evidence import get_evidence_file, save_frame_evidence


@pytest.fixture
def client() -> TestClient:
    app = create_app()
    return TestClient(app)


def test_save_frame_evidence_and_crop(tmp_path: Path):
    # Create synthetic 200x200 BGR test frame
    frame = np.zeros((200, 200, 3), dtype=np.uint8)
    frame[50:150, 50:150] = (0, 255, 0)  # Green box in middle

    event_id = "test-event-001"
    bbox_norm = [0.25, 0.25, 0.75, 0.75]

    snap_path, crop_path = save_frame_evidence(
        event_id=event_id,
        frame=frame,
        bbox_norm=bbox_norm,
        output_dir=tmp_path,
    )

    assert snap_path is not None
    assert crop_path is not None
    assert Path(snap_path).is_file()
    assert Path(crop_path).is_file()
    assert Path(snap_path).stat().st_size > 0
    assert Path(crop_path).stat().st_size > 0

    # Test retrieval helper
    retrieved_snap = get_evidence_file(event_id, kind="snapshot", base_dir=tmp_path)
    retrieved_crop = get_evidence_file(event_id, kind="crop", base_dir=tmp_path)
    assert retrieved_snap == Path(snap_path)
    assert retrieved_crop == Path(crop_path)


def test_save_frame_evidence_invalid_frame(tmp_path: Path):
    snap, crop = save_frame_evidence("empty-001", np.array([]), output_dir=tmp_path)
    assert snap is None
    assert crop is None


def test_evidence_api_endpoints(client: TestClient):
    # Save a test snapshot into data/evidence
    evidence_dir = Path("data/evidence")
    evidence_dir.mkdir(parents=True, exist_ok=True)

    event_id = "api-test-evidence-999"
    frame = np.full((100, 100, 3), 128, dtype=np.uint8)
    save_frame_evidence(event_id, frame, bbox_norm=[0.2, 0.2, 0.8, 0.8], output_dir=evidence_dir)

    # Fetch snapshot
    resp_snap = client.get(f"/api/v1/evidence/{event_id}/snapshot")
    assert resp_snap.status_code == 200
    assert resp_snap.headers["content-type"] == "image/jpeg"

    # Fetch crop
    resp_crop = client.get(f"/api/v1/evidence/{event_id}/crop")
    assert resp_crop.status_code == 200
    assert resp_crop.headers["content-type"] == "image/jpeg"

    # Non-existent evidence returns 404
    resp_404 = client.get("/api/v1/evidence/non-existent-xyz/snapshot")
    assert resp_404.status_code == 404


def test_system_settings_api(client: TestClient):
    # Get current settings
    resp = client.get("/api/v1/system/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert "detection_confidence_threshold" in data
    assert "c2_webhook_enabled" in data

    # Update settings
    update_payload = {
        "c2_webhook_url": "https://example.com/webhook",
        "c2_webhook_enabled": True,
        "c2_min_severity": "CRITICAL",
        "detection_confidence_threshold": 0.55,
        "loiter_cooldown_seconds": 15.0,
        "evidence_retention_days": 60,
    }
    resp_update = client.post("/api/v1/system/settings", json=update_payload)
    assert resp_update.status_code == 200
    assert resp_update.json()["status"] == "saved"

    # Verify update in memory
    current = get_settings()
    assert current.c2_webhook_url == "https://example.com/webhook"
    assert current.c2_webhook_enabled is True
    assert current.c2_min_severity == "CRITICAL"
    assert current.detection_confidence_threshold == 0.55

    # Reset
    save_settings(SystemSettings())


def test_webhook_test_endpoint_invalid_url(client: TestClient):
    resp = client.post("/api/v1/system/webhook/test", json={"url": "not-a-valid-url"})
    assert resp.status_code == 400
