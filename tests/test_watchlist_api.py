"""Unit and integration tests for Watchlist API endpoints."""

from __future__ import annotations

import io
from pathlib import Path
import cv2
import numpy as np
import pytest
from starlette.testclient import TestClient

from ibvap.api.app import create_app
from ibvap.core.watchlist import ThreatLevel, WatchlistEntry, get_watchlist_store


@pytest.fixture
def test_client(tmp_path: Path):
    store = get_watchlist_store()
    store.storage_path = tmp_path / "watchlist.json"
    store._entries.clear()
    
    app = create_app()
    with TestClient(app) as client:
        yield client


def _create_synthetic_face_image() -> bytes:
    # Create a 200x200 synthetic BGR image with high contrast gradient
    img = np.zeros((200, 200, 3), dtype=np.uint8)
    cv2.circle(img, (100, 100), 50, (200, 200, 200), -1)
    cv2.circle(img, (80, 85), 8, (50, 50, 50), -1)
    cv2.circle(img, (120, 85), 8, (50, 50, 50), -1)
    cv2.line(img, (80, 130), (120, 130), (50, 50, 50), 3)
    ok, buf = cv2.imencode(".jpg", img)
    return buf.tobytes()


class TestWatchlistAPI:
    def test_list_empty_watchlist(self, test_client: TestClient) -> None:
        resp = test_client.get("/api/v1/watchlist")
        assert resp.status_code == 200
        data = resp.json()
        assert "entries" in data
        assert len(data["entries"]) == 0

    def test_delete_nonexistent_entry(self, test_client: TestClient) -> None:
        resp = test_client.delete("/api/v1/watchlist/unknown-999")
        assert resp.status_code == 404

    def test_manual_add_and_list_and_delete(self, test_client: TestClient) -> None:
        store = get_watchlist_store()
        v = np.zeros(128, dtype=np.float32)
        v[0] = 1.0
        entry = WatchlistEntry(
            id="suspect-test-1",
            name="Suspect Alpha",
            threat_level=ThreatLevel.HIGH,
            notes="Known counterfeiter",
            gallery=[v],
        )
        store.add_entry(entry)

        # List
        resp = test_client.get("/api/v1/watchlist")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["entries"]) == 1
        assert data["entries"][0]["id"] == "suspect-test-1"
        assert data["entries"][0]["name"] == "Suspect Alpha"
        assert data["entries"][0]["photo_count"] == 1

        # Delete
        resp_del = test_client.delete("/api/v1/watchlist/suspect-test-1")
        assert resp_del.status_code == 200
        assert resp_del.json()["status"] == "removed"

        # Verify empty
        resp_after = test_client.get("/api/v1/watchlist")
        assert len(resp_after.json()["entries"]) == 0

    def test_enroll_blank_image_rejected(self, test_client: TestClient) -> None:
        blank_img = np.zeros((100, 100, 3), dtype=np.uint8)
        _, buf = cv2.imencode(".jpg", blank_img)
        files = [("photos", ("blank.jpg", buf.tobytes(), "image/jpeg"))]
        data = {"name": "Blank Person", "threat_level": "HIGH", "notes": "test"}
        resp = test_client.post("/api/v1/watchlist/enroll", data=data, files=files)
        assert resp.status_code == 400
        assert "No suitable faces found" in resp.json()["detail"]
