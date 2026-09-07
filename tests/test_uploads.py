from __future__ import annotations

from pathlib import Path

import cv2
from fastapi.testclient import TestClient

from ibvap.api.app import create_app


def _client() -> TestClient:
    return TestClient(create_app())


def test_upload_rejects_unsupported_extension() -> None:
    c = _client()
    resp = c.post("/api/v1/uploads", files={"file": ("evil.html", b"<html>hello", "text/html")})
    assert resp.status_code == 400


def test_upload_happy_path_and_promote() -> None:
    c = _client()
    # minimal mp4 header (not real video but passes extension check; html detection fails for <html)
    # Use 1KB dummy mp4 - our endpoint only checks extension and html prefix, not container yet
    content = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 1024
    resp = c.post("/api/v1/uploads", files={"file": ("clip.mp4", content, "video/mp4")})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["filename"] == "clip.mp4"
    assert data["sha256"]
    upload_id = data["upload_id"]

    # get
    resp = c.get(f"/api/v1/uploads/{upload_id}")
    assert resp.status_code == 200

    # finalize
    resp = c.post(f"/api/v1/uploads/{upload_id}/finalize")
    assert resp.status_code == 200
    assert resp.json()["status"] == "promoted"


def test_upload_rejects_html_masquerading_as_mp4() -> None:
    c = _client()
    resp = c.post("/api/v1/uploads", files={"file": ("clip.mp4", b"<!DOCTYPE html><html>", "video/mp4")})
    assert resp.status_code == 400


def test_video_footage_can_be_tested_and_saved() -> None:
    c = _client()
    video_path = Path("tests/fixtures/test-footage.mp4")
    video_path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(video_path), cv2.VideoWriter_fourcc(*"mp4v"), 5.0, (64, 64))
    assert writer.isOpened()
    frame = 255 * __import__("numpy").ones((64, 64, 3), dtype="uint8")
    writer.write(frame)
    writer.write(frame)
    writer.release()

    resp = c.post("/api/v1/cameras/test", json={"endpoint": str(video_path), "protocol": "file"})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["result"] == "ok"

    resp = c.post(
        "/api/v1/cameras",
        json={
            "name": "Uploaded footage",
            "site_id": "00000000-0000-0000-0000-000000000005",
            "source_type": "video_footage",
            "endpoint": str(video_path),
            "protocol": "file",
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["source_type"] == "video_footage"
