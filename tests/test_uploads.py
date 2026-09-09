from __future__ import annotations

import cv2
import pytest
from fastapi.testclient import TestClient


def test_upload_rejects_unsupported_extension(api_client: TestClient) -> None:
    c = api_client
    resp = c.post("/api/v1/uploads", files={"file": ("evil.html", b"<html>hello", "text/html")})
    assert resp.status_code == 400


def _real_mp4_bytes() -> bytes:
    import tempfile
    from pathlib import Path

    import numpy as np

    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "clip.mp4"
        writer = cv2.VideoWriter(str(p), cv2.VideoWriter_fourcc(*"mp4v"), 5.0, (64, 64))
        frame = np.zeros((64, 64, 3), dtype=np.uint8)
        writer.write(frame)
        writer.write(frame)
        writer.release()
        return p.read_bytes()


def test_upload_happy_path_and_promote(api_client: TestClient) -> None:
    c = api_client
    # Real (tiny) mp4: finalize decode-validates, so dummies no longer promote.
    resp = c.post("/api/v1/uploads", files={"file": ("clip.mp4", _real_mp4_bytes(), "video/mp4")})
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

    resp = c.delete(f"/api/v1/uploads/{upload_id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "deleted"
    assert c.get(f"/api/v1/uploads/{upload_id}").status_code == 404


def test_finalize_rejects_dummy_bytes(api_client: TestClient) -> None:
    c = api_client
    content = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 1024
    resp = c.post("/api/v1/uploads", files={"file": ("clip.mp4", content, "video/mp4")})
    assert resp.status_code == 200, resp.text
    uid = resp.json()["upload_id"]
    try:
        resp = c.post(f"/api/v1/uploads/{uid}/finalize")
        assert resp.status_code == 422, resp.text
    finally:
        c.delete(f"/api/v1/uploads/{uid}")


def test_finalize_rejects_empty_file(api_client: TestClient) -> None:
    c = api_client
    resp = c.post("/api/v1/uploads", files={"file": ("empty.mp4", b"", "video/mp4")})
    assert resp.status_code == 200, resp.text
    uid = resp.json()["upload_id"]
    try:
        resp = c.post(f"/api/v1/uploads/{uid}/finalize")
        assert resp.status_code == 422, resp.text
    finally:
        c.delete(f"/api/v1/uploads/{uid}")


async def test_failed_read_leaves_no_orphan() -> None:
    """Any read failure (disconnect, cancel, disk error) must not orphan bytes."""
    from pathlib import Path

    from ibvap.api.routes.uploads import create_upload

    class Boom:
        filename = "clip.mp4"

        async def read(self, n: int = -1) -> bytes:
            raise RuntimeError("client disconnect")

    qdir = Path("data/quarantine")
    before = set(qdir.iterdir()) if qdir.exists() else set()
    with pytest.raises(RuntimeError):
        await create_upload(file=Boom())  # type: ignore[arg-type]
    after = set(qdir.iterdir()) if qdir.exists() else set()
    assert after == before


def test_upload_rejects_html_masquerading_as_mp4(api_client: TestClient) -> None:
    c = api_client
    resp = c.post("/api/v1/uploads", files={"file": ("clip.mp4", b"<!DOCTYPE html><html>", "video/mp4")})
    assert resp.status_code == 400


def test_video_footage_can_be_tested_and_saved(api_client: TestClient, tmp_path) -> None:
    c = api_client
    video_path = tmp_path / "test-footage.mp4"
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
