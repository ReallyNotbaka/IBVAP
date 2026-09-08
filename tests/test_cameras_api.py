from __future__ import annotations

from fastapi.testclient import TestClient

from ibvap.api.app import create_app


def _client() -> TestClient:
    return TestClient(create_app())


def test_unsaved_test_blocks_credential_in_url() -> None:
    c = _client()
    resp = c.post(
        "/api/v1/cameras/test",
        json={"endpoint": "http://user:pass@example.com/video", "protocol": "http"},
    )
    assert resp.status_code == 200
    data = resp.json()
    # should be blocked / error
    assert data["result"] in {"blocked", "error"}
    assert data["reason_code"] == "credential_in_url"


def test_unsaved_test_blocks_loopback() -> None:
    c = _client()
    # loopback will be resolved to 127.0.0.1 and blocked
    resp = c.post(
        "/api/v1/cameras/test",
        json={"endpoint": "http://127.0.0.1:8080/video", "protocol": "http"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["result"] == "blocked"
    assert "blocked" in (data["reason_code"] or "")


def test_unsaved_test_private_without_allowlist_blocked() -> None:
    c = _client()
    resp = c.post(
        "/api/v1/cameras/test",
        json={"endpoint": "http://192.168.1.10:8080/video", "protocol": "http"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["result"] == "blocked"
    assert data["reason_code"] == "blocked_private"


def test_unsaved_test_private_with_allowlist_synthetic_ok() -> None:
    c = _client()
    # synthetic harness bypasses network - returns ok
    resp = c.post(
        "/api/v1/cameras/test",
        json={"endpoint": "synthetic://test", "protocol": "http", "site_cidr_allowlist": ["192.168.1.0/24"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["result"] == "ok"
    assert data["probe"] is not None
    assert data["probe"]["codec"] == "h264"


def test_create_and_list_cameras() -> None:
    c = _client()
    # allow private via CIDR allowlist + synthetic endpoint
    resp = c.post(
        "/api/v1/cameras",
        json={
            "name": "Entrance phone",
            "site_id": "00000000-0000-0000-0000-000000000001",
            "source_type": "smartphone_ip_webcam",
            "endpoint": "synthetic://entrance",
            "protocol": "http",
            "site_cidr_allowlist": ["10.0.0.0/8"],
        },
    )
    assert resp.status_code == 200, resp.text
    cam = resp.json()
    assert cam["name"] == "Entrance phone"
    assert cam["observed_state"] == "STREAMING"
    # credentials not leaked
    assert "password" not in str(cam).lower()
    assert cam["endpoint"] == "synthetic://entrance"

    # list
    resp = c.get("/api/v1/cameras")
    assert resp.status_code == 200
    lst = resp.json()
    assert any(x["id"] == cam["id"] for x in lst)


def test_camera_fence_is_validated_and_saved() -> None:
    c = _client()
    resp = c.post(
        "/api/v1/cameras",
        json={
            "name": "Fence camera",
            "site_id": "00000000-0000-0000-0000-000000000001",
            "source_type": "smartphone_ip_webcam",
            "endpoint": "synthetic://fence",
            "protocol": "http",
        },
    )
    camera_id = resp.json()["id"]
    polygon = [[0.1, 0.2], [0.9, 0.2], [0.8, 0.8], [0.2, 0.8]]
    saved = c.put(f"/api/v1/cameras/{camera_id}/fence", json={"polygon": polygon})
    assert saved.status_code == 200
    assert saved.json()["fence"]["polygon"] == polygon

    invalid = c.put(f"/api/v1/cameras/{camera_id}/fence", json={"polygon": [[0.1, 0.1], [0.2, 0.2]]})
    assert invalid.status_code == 422


def test_disable_and_reconnect() -> None:
    c = _client()
    resp = c.post(
        "/api/v1/cameras",
        json={
            "name": "Road-facing phone",
            "site_id": "00000000-0000-0000-0000-000000000002",
            "source_type": "smartphone_ip_webcam",
            "endpoint": "synthetic://road",
            "protocol": "http",
        },
    )
    cam_id = resp.json()["id"]
    # disable
    resp = c.post(f"/api/v1/cameras/{cam_id}/disable")
    assert resp.status_code == 200
    assert resp.json()["observed_state"] == "DISABLED"
    # reconnect should fail when disabled
    resp = c.post(f"/api/v1/cameras/{cam_id}/reconnect")
    assert resp.status_code == 400
    # enable
    resp = c.post(f"/api/v1/cameras/{cam_id}/enable")
    assert resp.status_code == 200
    # health
    resp = c.get(f"/api/v1/cameras/{cam_id}/health")
    assert resp.status_code == 200
    assert resp.json()["camera_id"] == cam_id


def test_create_rejects_credential_in_url() -> None:
    c = _client()
    resp = c.post(
        "/api/v1/cameras",
        json={
            "name": "bad",
            "site_id": "00000000-0000-0000-0000-000000000003",
            "endpoint": "http://user:pass@192.168.1.10/video",
            "protocol": "http",
            "username": "user",
            "password": "pass",
        },
    )
    assert resp.status_code == 400


def test_create_rejects_private_endpoint_without_allowlist() -> None:
    c = _client()
    resp = c.post(
        "/api/v1/cameras",
        json={
            "name": "private-no-allowlist",
            "site_id": "00000000-0000-0000-0000-000000000004",
            "endpoint": "http://192.168.1.10:8080/video",
            "protocol": "http",
        },
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "blocked_private"
