from __future__ import annotations

import ipaddress

import pytest

from ibvap.core.ssrf import (
    DEFAULT_POLICY,
    SSRFPolicy,
    check_http_redirect,
    preflight_stream_url,
    validate_endpoint,
    validate_resolved_ips,
)


def test_blocked_scheme() -> None:
    policy = DEFAULT_POLICY
    with pytest.raises(Exception) as ei:
        validate_endpoint("ftp://example.com/video", policy)
    assert "blocked_scheme" in str(ei.value) or hasattr(ei.value, "code")


def test_credential_in_url_blocked() -> None:
    with pytest.raises(Exception) as ei:
        validate_endpoint("http://user:pass@example.com/video", DEFAULT_POLICY)
    assert getattr(ei.value, "code", "") == "credential_in_url"


def test_loopback_blocked() -> None:
    policy = DEFAULT_POLICY
    # validate_resolved_ips should block 127.0.0.1
    with pytest.raises(Exception) as ei:
        validate_resolved_ips(["127.0.0.1"], policy)
    assert getattr(ei.value, "code", "") == "blocked_address"


def test_link_local_blocked() -> None:
    with pytest.raises(Exception) as ei:
        validate_resolved_ips(["169.254.0.5"], DEFAULT_POLICY)
    assert getattr(ei.value, "code", "") == "blocked_address"


def test_metadata_blocked() -> None:
    with pytest.raises(Exception) as ei:
        validate_resolved_ips(["169.254.169.254"], DEFAULT_POLICY)
    assert getattr(ei.value, "code", "") == "blocked_address"


def test_private_without_allowlist_blocked() -> None:
    with pytest.raises(Exception) as ei:
        validate_resolved_ips(["192.168.1.10"], DEFAULT_POLICY)
    assert getattr(ei.value, "code", "") == "blocked_private"


def test_private_with_allowlist_allowed() -> None:
    policy = SSRFPolicy(
        allowed_schemes=frozenset({"http", "https", "rtsp", "rtsps"}),
        allowed_hosts=None,
        allowed_ports=None,
        site_cidr_allowlist=(ipaddress.ip_network("192.168.1.0/24"),),
    )
    # should not raise
    validate_resolved_ips(["192.168.1.10"], policy)


def test_public_allowed_when_not_blocked() -> None:
    policy = DEFAULT_POLICY
    # 8.8.8.8 is public and not blocked
    validate_resolved_ips(["8.8.8.8"], policy)


def test_validate_endpoint_allows_http() -> None:
    parsed = validate_endpoint("http://192.168.1.10:8080/video", DEFAULT_POLICY)
    assert parsed.hostname == "192.168.1.10"


def _redirect_server(target: str) -> tuple[object, int]:
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class H(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(302)
            self.send_header("Location", target)
            self.end_headers()

        def do_HEAD(self) -> None:
            self.do_GET()

        def log_message(self, *a: object) -> None:
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_port


def test_redirect_to_denied_host_refused() -> None:
    srv, _port = _redirect_server("http://127.0.0.1:9/internal")
    try:
        from ibvap.core.ssrf import SSRFError

        with pytest.raises(SSRFError) as ei:
            check_http_redirect(f"http://127.0.0.1:{_port}/video", DEFAULT_POLICY, timeout=2.0)
        assert ei.value.code == "blocked_redirect"
    finally:
        srv.shutdown()


def test_rebinding_revalidated_every_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    import socket as socket_mod

    ips = iter([["8.8.8.8"], ["10.0.0.5"]])

    def fake_getaddrinfo(*a: object, **k: object) -> list:
        return [(socket_mod.AF_INET, socket_mod.SOCK_STREAM, 6, "", (next(ips)[0], 0))]

    monkeypatch.setattr(socket_mod, "getaddrinfo", fake_getaddrinfo)
    # rtsp:// skips the HTTP redirect check (no urllib traffic in this test).
    preflight_stream_url("rtsp://example.com:554/stream", DEFAULT_POLICY, timeout=2.0)
    from ibvap.core.ssrf import SSRFError

    with pytest.raises(SSRFError) as ei:
        preflight_stream_url("rtsp://example.com:554/stream", DEFAULT_POLICY, timeout=2.0)
    assert ei.value.code == "blocked_private"


def test_probe_url_validates_policy_before_open(monkeypatch: pytest.MonkeyPatch) -> None:
    from ibvap.core import probe as probe_module

    calls: list[str] = []

    def fake_open(url: object, **kwargs: object) -> object:
        calls.append(str(url))
        raise RuntimeError("must not be reached")

    monkeypatch.setattr(probe_module.av, "open", fake_open)
    with pytest.raises(Exception) as ei:
        probe_module.probe_url("http://127.0.0.1:9/video", timeout=2.0, policy=DEFAULT_POLICY)
    assert getattr(ei.value, "code", "").startswith("blocked")
    assert calls == []
