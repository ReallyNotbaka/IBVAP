"""Task 1 P0: evidence traversal + webhook SSRF + auth regression tests.

Fix-round 1: mutating routes are fail-closed, so the shared ``client`` fixture
sends the test token; separate headerless clients prove 401 enforcement.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ibvap.api.app import create_app

# Ledger (Task 6 fix-round 1): when frontend/dist is built in the working tree,
# the app mounts the SPA fallback at "/" AFTER the API routes, so a request whose
# path cannot match any single-segment API route (e.g. httpx-decoded "%2F"
# traversal probes) is served index.html with 200 instead of falling through to
# Starlette's 404. CI's backend job never builds frontend/dist, so the guard is
# exercised there. The guard itself is covered by the single-segment 422 tests
# and unit tests below, which run unconditionally.
_SPA_FALLBACK_MOUNTED = Path("frontend/dist/index.html").exists()
_requires_no_spa_fallback = pytest.mark.skipif(
    _SPA_FALLBACK_MOUNTED,
    reason="frontend/dist present: SPA fallback serves 200 for unmatched paths; CI (no dist) exercises the guard",
)


@pytest.fixture
def client() -> TestClient:
    app = create_app()
    c = TestClient(app)
    # Authenticated: mutating routes are fail-closed (fix-round 1).
    c.headers["X-API-Token"] = os.environ["IBVAP_API_TOKEN"]
    return c


@pytest.fixture
def anon_client() -> TestClient:
    """Headerless client: every mutating call must 401 (token IS configured)."""
    return TestClient(create_app())


@_requires_no_spa_fallback
def test_evidence_traversal_blocked(client: TestClient):
    r = client.get("/api/v1/evidence/..%2F..%2Fetc%2Fpasswd/snapshot")
    assert r.status_code in (404, 422)


def test_webhook_ssrf_blocked(client: TestClient):
    r = client.post("/api/v1/system/webhook/test", json={"url": "http://169.254.169.254/latest"})
    assert r.status_code == 400


@_requires_no_spa_fallback
def test_evidence_bad_id_rejected_with_422(client: TestClient):
    # Characters outside [A-Za-z0-9_-] must be rejected by validation (422),
    # not treated as a missing file (404-from-missing-file hides the guard).
    # (Multi-segment probe; single-segment guards run unconditionally below.)
    r = client.get("/api/v1/evidence/..%2Fevil/snapshot")
    assert r.status_code in (404, 422)
    r2 = client.get("/api/v1/evidence/evil!id$/snapshot")
    assert r2.status_code == 422


@pytest.mark.parametrize("bad_id", ["evil!id", "evil!id$", "a" * 65, "has space", "semi;colon", "evil%21id"])
def test_evidence_single_segment_bad_id_is_422(client: TestClient, bad_id: str):
    """Fix-round 1: single-segment invalid ids must reach the guard → strict 422."""
    r = client.get(f"/api/v1/evidence/{bad_id}/snapshot")
    assert r.status_code == 422
    r2 = client.get(f"/api/v1/evidence/{bad_id}/crop")
    assert r2.status_code == 422


def test_validate_event_id_unit():
    from ibvap.core.evidence import validate_event_id

    assert validate_event_id("abc-123_XYZ") == "abc-123_XYZ"
    for bad in ("../evil", "..", "", "a" * 65, "evil!id", "foo/bar", ".", " space "):
        with pytest.raises(ValueError):
            validate_event_id(bad)


def test_get_evidence_file_traversal_returns_none(tmp_path):
    from ibvap.core.evidence import get_evidence_file

    # Even if a file exists outside base_dir, traversal ids must not resolve to it.
    outside = tmp_path / "outside_snap.jpg"
    outside.write_bytes(b"fakejpeg")
    assert get_evidence_file("../outside", kind="snapshot", base_dir=tmp_path / "sub") is None
    assert get_evidence_file("..%2Foutside", kind="snapshot", base_dir=tmp_path) is None


def test_webhook_save_settings_ssrf_blocked(client: TestClient):
    r = client.post(
        "/api/v1/system/settings",
        json={
            "c2_webhook_url": "http://169.254.169.254/latest",
            "c2_webhook_enabled": True,
        },
    )
    assert r.status_code == 400


def test_mutating_route_requires_token_when_configured(monkeypatch):
    from ibvap.api.app import create_app as _create

    monkeypatch.setenv("IBVAP_API_TOKEN", "test-secret-token")
    app = _create()
    c = TestClient(app)
    # No token -> 401
    r = c.post("/api/v1/system/settings", json={"c2_webhook_enabled": False})
    assert r.status_code == 401
    # Wrong token -> 401
    r2 = c.post("/api/v1/system/settings", json={"c2_webhook_enabled": False}, headers={"X-API-Token": "wrong"})
    assert r2.status_code == 401
    # Correct token -> allowed (200; validation of empty URL passes when disabled)
    r3 = c.post(
        "/api/v1/system/settings", json={"c2_webhook_enabled": False}, headers={"X-API-Token": "test-secret-token"}
    )
    assert r3.status_code == 200
    # Bearer form also accepted
    r4 = c.post(
        "/api/v1/system/settings",
        json={"c2_webhook_enabled": False},
        headers={"Authorization": "Bearer test-secret-token"},
    )
    assert r4.status_code == 200


def test_mutating_routes_fail_closed_without_token(monkeypatch):
    """Fix-round 1: no anonymous mode — unset IBVAP_API_TOKEN still 401s."""
    from ibvap.api.app import create_app as _create

    monkeypatch.delenv("IBVAP_API_TOKEN", raising=False)
    c = TestClient(_create())
    assert c.post("/api/v1/system/settings", json={"c2_webhook_enabled": False}).status_code == 401
    assert c.delete("/api/v1/events").status_code == 401


_MISSING_AUTH_CASES = [
    ("POST", "/api/v1/system/settings", {"json": {"c2_webhook_enabled": False}}),
    ("POST", "/api/v1/system/webhook/test", {"json": {"url": "https://8.8.8.8/hook"}}),
    ("POST", "/api/v1/cameras", {"json": {"name": "x", "site_id": "s", "endpoint": "synthetic://probe"}}),
    ("POST", "/api/v1/cameras/test", {"json": {"endpoint": "synthetic://probe"}}),
    ("PUT", "/api/v1/cameras/nonexistent/fence", {"json": {"polygon": []}}),
    ("DELETE", "/api/v1/cameras/nonexistent/fence", {}),
    ("DELETE", "/api/v1/cameras/nonexistent", {}),
    ("POST", "/api/v1/cameras/nonexistent/playback/seek", {"json": {"position_seconds": 1.0}}),
    ("POST", "/api/v1/cameras/nonexistent/enable", {}),
    ("POST", "/api/v1/cameras/nonexistent/disable", {}),
    ("POST", "/api/v1/cameras/nonexistent/reconnect", {}),
    ("POST", "/api/v1/cameras/nonexistent/test", {}),
    ("DELETE", "/api/v1/events", {}),
    ("POST", "/api/v1/sites", {"json": {"name": "n", "organization_id": "o"}}),
    ("POST", "/api/v1/models/activate", {"json": {"model_name": "yolo26s"}}),
    ("POST", "/api/v1/models/download", {"json": {"model_name": "yolo26s"}}),
    ("DELETE", "/api/v1/models/yolo26s/weights", {}),
    (
        "POST",
        "/api/v1/tactical/radar/calibrate",
        {
            "json": {
                "camera_id": "x",
                "image_points": [[0, 0], [1, 0], [1, 1], [0, 1]],
                "ground_points": [[0, 0], [1, 0], [1, 1], [0, 1]],
            }
        },
    ),
    ("DELETE", "/api/v1/uploads/nope", {}),
    ("POST", "/api/v1/uploads/nope/finalize", {}),
    ("POST", "/api/v1/uploads/nope/analyze", {}),
    ("POST", "/api/v1/watchlist/enroll-plate", {"json": {"name": "n", "plate_number": "ABC123"}}),
    ("DELETE", "/api/v1/watchlist/nope", {}),
]


@pytest.mark.parametrize(("method", "path", "kwargs"), _MISSING_AUTH_CASES)
def test_mutating_routes_require_auth(anon_client: TestClient, method: str, path: str, kwargs: dict):
    """Fix-round 1: every mutating route 401s without a token (auth runs first)."""
    r = anon_client.request(method, path, **kwargs)
    assert r.status_code == 401, f"{method} {path} -> {r.status_code}"


def test_read_routes_stay_open_without_token(anon_client: TestClient):
    assert anon_client.get("/api/v1/system/settings").status_code == 200
    assert anon_client.get("/api/v1/events").status_code == 200


async def test_mjpeg_stream_has_no_wildcard_cors():
    from ibvap.api.routes.cameras import camera_stream
    from ibvap.services.stream_worker import _CAMERAS

    _CAMERAS["cors-probe"] = {"id": "cors-probe", "endpoint": "synthetic://probe"}
    try:
        resp = await camera_stream("cors-probe")
        assert resp.headers.get("Access-Control-Allow-Origin") != "*"
    finally:
        _CAMERAS.pop("cors-probe", None)


def test_pin_url_to_ip_unit():
    from ibvap.core.dispatcher import pin_url_to_ip

    assert pin_url_to_ip("http://example.com/hook", "93.184.216.34") == "http://93.184.216.34/hook"
    assert pin_url_to_ip("http://example.com:8080/a?b=c", "93.184.216.34") == "http://93.184.216.34:8080/a?b=c"
    assert pin_url_to_ip("http://example.com/hook", "::1") == "http://[::1]/hook"


def test_webhook_explicit_port_pass_through_when_public(client: TestClient):
    # Fix-round 1: policy pins destination, not port — public IP on :8443 saves fine.
    r = client.post(
        "/api/v1/system/settings",
        json={"c2_webhook_url": "https://8.8.8.8:8443/hook", "c2_webhook_enabled": False},
    )
    assert r.status_code == 200


def test_webhook_metadata_with_explicit_port_still_blocked(client: TestClient):
    # Literal-IP denial fires before the port pass-through.
    r = client.post(
        "/api/v1/system/settings",
        json={"c2_webhook_url": "http://169.254.169.254:8443/latest", "c2_webhook_enabled": True},
    )
    assert r.status_code == 400
    r2 = client.post("/api/v1/system/webhook/test", json={"url": "http://169.254.169.254:8443/latest"})
    assert r2.status_code == 400


def test_webhook_unresolvable_host_rejected_on_save(client: TestClient):
    # Fix-round 1, strict: DNS failure at save time is a 400, not leniency.
    r = client.post(
        "/api/v1/system/settings",
        json={"c2_webhook_url": "https://nonexistent.invalid/hook", "c2_webhook_enabled": True},
    )
    assert r.status_code == 400
