"""Unit and integration tests for Watchlist API endpoints."""

from __future__ import annotations

import os
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
        # Task 1 P0 fix-round 1: mutating routes are fail-closed; send the test token.
        client.headers["X-API-Token"] = os.environ["IBVAP_API_TOKEN"]
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
        assert "items" in data
        assert len(data["items"]) == 0

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
        assert len(data["items"]) == 1
        assert data["items"][0]["id"] == "suspect-test-1"
        assert data["items"][0]["name"] == "Suspect Alpha"
        assert data["items"][0]["photo_count"] == 1

        # Delete
        resp_del = test_client.delete("/api/v1/watchlist/suspect-test-1")
        assert resp_del.status_code == 200
        assert resp_del.json()["status"] == "removed"

        # Verify empty
        resp_after = test_client.get("/api/v1/watchlist")
        assert len(resp_after.json()["items"]) == 0

    def test_enroll_blank_image_rejected(self, test_client: TestClient) -> None:
        blank_img = np.zeros((100, 100, 3), dtype=np.uint8)
        _, buf = cv2.imencode(".jpg", blank_img)
        files = [("photos", ("blank.jpg", buf.tobytes(), "image/jpeg"))]
        data = {"name": "Blank Person", "threat_level": "HIGH", "notes": "test"}
        resp = test_client.post("/api/v1/watchlist/enroll", data=data, files=files)
        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert detail["code"] == "no_face_detected"
        assert "No suitable faces found" in detail["message"]

    def test_list_paginated_envelope(self, test_client: TestClient) -> None:
        """Task 5 contract: bounded page + total, uniform `items` envelope key."""
        store = get_watchlist_store()
        v = np.zeros(128, dtype=np.float32)
        v[0] = 1.0
        for i in range(5):
            store.add_entry(
                WatchlistEntry(
                    id=f"suspect-pag-{i}",
                    name=f"Paginated {i}",
                    threat_level=ThreatLevel.MEDIUM,
                    notes="",
                    gallery=[v],
                )
            )
        resp = test_client.get("/api/v1/watchlist?limit=2&offset=2")
        assert resp.status_code == 200
        body = resp.json()
        assert set(body) >= {"items", "total", "limit", "offset"}
        assert body["total"] == 5
        assert body["limit"] == 2
        assert body["offset"] == 2
        assert len(body["items"]) == 2
