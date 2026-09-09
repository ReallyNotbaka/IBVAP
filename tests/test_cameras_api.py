from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from ibvap.core import probe as probe_module


def test_ip_webcam_uses_mjpeg_demuxer(monkeypatch: Any) -> None:
    calls = []

    def fake_open(url: Any, **kwargs: Any):
        calls.append((url, kwargs))
        raise RuntimeError("stop after inspecting options")

    monkeypatch.setattr(probe_module.av, "open", fake_open)

    # Probing a private IP requires an explicit operator-style policy now.
    import ipaddress

    from ibvap.core.ssrf import SSRFPolicy

    policy = SSRFPolicy(
        allowed_schemes=frozenset({"http", "https", "rtsp", "rtsps"}),
        allowed_hosts=None,
        allowed_ports=None,
        site_cidr_allowlist=(ipaddress.ip_network("192.168.0.0/16"),),
    )
    try:
        probe_module.probe_url("http://192.168.1.20:8080/video", timeout=3, policy=policy)
    except probe_module.ProbeError as error:
        assert error.code == "open_failed"
    assert calls == [
        (
            "http://192.168.1.20:8080/video",
            {
                "format": "mpjpeg",
                "options": {
                    "timeout": "3000000",
                    "stimeout": "3000000",
                    "analyzeduration": "3000000",
                    "probesize": "500000",
                },
            },
        )
    ]


@pytest.mark.parametrize(
    ("endpoint", "expected_result", "expected_reason"),
    [
        ("http://user:pass@example.com/video", {"blocked", "error"}, "credential_in_url"),
        # loopback will be resolved to 127.0.0.1 and blocked
        ("http://127.0.0.1:8080/video", {"blocked"}, "blocked"),
        ("http://192.168.1.10:8080/video", {"blocked"}, "blocked_private"),
    ],
)
def test_unsaved_test_blocks_unsafe_endpoints(api_client: TestClient, endpoint: str, expected_result: set[str], expected_reason: str) -> None:
    resp = api_client.post(
        "/api/v1/cameras/test",
        json={"endpoint": endpoint, "protocol": "http"},
    )
    assert resp.status_code == 200
    data = resp.json()
    # should be blocked / error
    assert data["result"] in expected_result
    assert expected_reason in (data["reason_code"] or "")


def test_unsaved_test_private_with_allowlist_synthetic_ok(api_client: TestClient) -> None:
    c = api_client
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


def test_private_endpoint_blocked_despite_request_allowlist(api_client: TestClient) -> None:
    """Caller-supplied CIDRs must never authorize private IPs (server config owns policy)."""
    resp = api_client.post(
        "/api/v1/cameras/test",
        json={
            "endpoint": "http://192.168.1.10:8080/video",
            "protocol": "http",
            "site_cidr_allowlist": ["192.168.1.0/24"],
        },
    )
    assert resp.status_code == 200
    assert resp.json()["result"] == "blocked"


def test_operator_allowlist_permits_configured_private(api_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Operator-owned server setting (not the request) authorizes private ranges."""
    monkeypatch.setenv("IBVAP_MEDIA__SITE_CIDR_ALLOWLIST", '["192.168.1.0/24"]')
    resp = api_client.post(
        "/api/v1/cameras/test",
        json={"endpoint": "http://192.168.1.10:8080/video", "protocol": "http"},
    )
    assert resp.status_code == 200
    assert resp.json()["result"] != "blocked"


def test_create_and_list_cameras(api_client: TestClient) -> None:
    c = api_client
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


def test_camera_fence_is_validated_and_saved(api_client: TestClient) -> None:
    c = api_client
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


def test_camera_line_fence_and_deletion(api_client: TestClient) -> None:
    c = api_client
    resp = c.post(
        "/api/v1/cameras",
        json={
            "name": "Line tripwire camera",
            "site_id": "00000000-0000-0000-0000-000000000001",
            "source_type": "smartphone_ip_webcam",
            "endpoint": "synthetic://tripwire",
            "protocol": "http",
        },
    )
    camera_id = resp.json()["id"]
    line = [[0.1, 0.3], [0.9, 0.7]]
    # Save as line fence via fence_type="line"
    saved_line = c.put(
        f"/api/v1/cameras/{camera_id}/fence",
        json={"polygon": line, "fence_type": "line"},
    )
    assert saved_line.status_code == 200
    assert saved_line.json()["fence"]["polygon"] == line
    assert saved_line.json()["fence"]["fence_type"] == "line"

    # Save via line field
    saved_line_field = c.put(
        f"/api/v1/cameras/{camera_id}/fence",
        json={"line": line},
    )
    assert saved_line_field.status_code == 200
    assert saved_line_field.json()["fence"]["polygon"] == line

    # Delete fence via DELETE endpoint
    deleted = c.delete(f"/api/v1/cameras/{camera_id}/fence")
    assert deleted.status_code == 200
    assert deleted.json().get("fence") is None

    # Clear fence via PUT empty polygon
    saved_again = c.put(
        f"/api/v1/cameras/{camera_id}/fence",
        json={"polygon": line, "fence_type": "line"},
    )
    assert saved_again.status_code == 200
    cleared = c.put(
        f"/api/v1/cameras/{camera_id}/fence",
        json={"polygon": []},
    )
    assert cleared.status_code == 200
    assert cleared.json().get("fence") is None

    # Save with enabled=False
    saved_disabled = c.put(
        f"/api/v1/cameras/{camera_id}/fence",
        json={"polygon": line, "fence_type": "line", "enabled": False},
    )
    assert saved_disabled.status_code == 200
    assert saved_disabled.json()["fence"]["enabled"] is False


def test_disable_and_reconnect(api_client: TestClient) -> None:
    c = api_client
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


def test_create_rejects_credential_in_url(api_client: TestClient) -> None:
    c = api_client
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


def test_create_rejects_private_endpoint_without_allowlist(api_client: TestClient) -> None:
    c = api_client
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


def test_droidcam_port_4747_uses_mjpeg_demuxer(monkeypatch: Any) -> None:
    calls = []

    def fake_open(url: Any, **kwargs: Any):
        calls.append((url, kwargs))
        raise RuntimeError("stop after inspecting options")

    monkeypatch.setattr(probe_module.av, "open", fake_open)

    import ipaddress

    from ibvap.core.ssrf import SSRFPolicy

    policy = SSRFPolicy(
        allowed_schemes=frozenset({"http", "https", "rtsp", "rtsps"}),
        allowed_hosts=None,
        allowed_ports=None,
        site_cidr_allowlist=(ipaddress.ip_network("10.0.0.0/8"),),
    )
    try:
        probe_module.probe_url("http://10.80.5.52:4747", timeout=3, policy=policy)
    except probe_module.ProbeError as error:
        assert error.code == "open_failed"
    assert len(calls) == 1
    assert calls[0][0] == "http://10.80.5.52:4747/video"
    assert calls[0][1]["format"] == "mpjpeg"


def test_normalize_mjpeg_url() -> None:
    assert probe_module.normalize_mjpeg_url("http://10.80.5.52:4747") == "http://10.80.5.52:4747/video"
    assert probe_module.normalize_mjpeg_url("http://10.80.5.52:4747/") == "http://10.80.5.52:4747/video"
    assert probe_module.normalize_mjpeg_url("http://10.80.5.52:4747/video") == "http://10.80.5.52:4747/video"
    assert probe_module.normalize_mjpeg_url("http://192.168.1.50:8080") == "http://192.168.1.50:8080/video"
    assert probe_module.normalize_mjpeg_url("rtsp://192.168.1.50:554/stream1") == "rtsp://192.168.1.50:554/stream1"


def test_redact_strips_query_token() -> None:
    from ibvap.core.credentials import redact_url

    redacted = redact_url("http://192.168.1.10:8080/video?token=secret123")
    assert "secret123" not in redacted
    assert redacted.startswith("http://192.168.1.10:8080/video")
    # userinfo stripping still works
    assert "pass" not in redact_url("http://admin:pass@192.168.1.10:8080/video")


def test_probe_uses_supplied_credentials(monkeypatch: Any) -> None:
    import ipaddress

    from ibvap.core.ssrf import SSRFPolicy

    calls = []

    def fake_open(url: Any, **kwargs: Any):
        calls.append(url)
        raise RuntimeError("stop after inspecting url")

    monkeypatch.setattr(probe_module.av, "open", fake_open)
    policy = SSRFPolicy(
        allowed_schemes=frozenset({"http", "https", "rtsp", "rtsps"}),
        allowed_hosts=None,
        allowed_ports=None,
        site_cidr_allowlist=(ipaddress.ip_network("192.168.0.0/16"),),
    )
    try:
        probe_module.probe_url("http://192.168.1.20:8080/video", timeout=3, policy=policy, auth=("admin", "s3cret"))
    except probe_module.ProbeError as error:
        assert error.code == "open_failed"
    assert calls == ["http://admin:s3cret@192.168.1.20:8080/video"]


def test_create_with_credentials_but_no_key_rejected(api_client: TestClient, monkeypatch: Any) -> None:
    monkeypatch.delenv("IBVAP_CREDENTIAL_KEY", raising=False)
    resp = api_client.post(
        "/api/v1/cameras",
        json={
            "name": "authed",
            "site_id": "00000000-0000-0000-0000-000000000006",
            "endpoint": "synthetic://authed",
            "protocol": "http",
            "username": "admin",
            "password": "s3cret",
        },
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "credential_storage_unavailable"
