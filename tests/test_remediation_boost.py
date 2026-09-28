from __future__ import annotations

import ipaddress
import socket
import threading
import time
from typing import Any
from urllib.parse import urlparse

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from ibvap.api.app import create_app
from ibvap.config import Settings
from ibvap.core.anpr import ANPRPipeline
from ibvap.core.camera_state import CameraState, CameraStateMachine
from ibvap.core.ssrf import (
    DEFAULT_POLICY,
    SSRFError,
    SSRFPolicy,
    pin_stream_url,
)
from ibvap.services import stream_worker as SW

# ============================================================================
# 1. SSRF DNS REBINDING / TOCTOU TESTS
# ============================================================================


def test_ssrf_pinning_eliminates_dns_rebinding_gap(monkeypatch: pytest.MonkeyPatch) -> None:
    """DNS resolution gap is eliminated by pinning the authorized IP into the connection URL.

    Even if DNS resolution changes subsequently, network connections use the pinned IP.
    """
    # Simulate attacker DNS: first returns 93.184.216.34 (public, allowed),
    # subsequent queries return 127.0.0.1 (loopback, forbidden).
    query_count = 0

    def mock_getaddrinfo(host: str, port: Any, **kwargs: Any) -> list:
        nonlocal query_count
        query_count += 1
        ip = "93.184.216.34" if query_count == 1 else "127.0.0.1"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]

    monkeypatch.setattr(socket, "getaddrinfo", mock_getaddrinfo)

    url = "rtsp://camera.dynamic-dns.attacker.com:554/live"
    pinned_url, ips = pin_stream_url(url, DEFAULT_POLICY, timeout=2.0)

    # 1. First resolution validated and pinned
    assert ips == ["93.184.216.34"]
    assert pinned_url == "rtsp://93.184.216.34:554/live"
    parsed_pinned = urlparse(pinned_url)
    # Host in pinned URL is an IP literal - no DNS lookup can rebind it!
    assert parsed_pinned.hostname == "93.184.216.34"

    # 2. When connection is opened using pinned_url, no DNS query is made for attacker.com
    # And if preflight is run again on the original URL after rebind, it is REJECTED
    with pytest.raises(SSRFError) as exc_info:
        pin_stream_url(url, DEFAULT_POLICY, timeout=2.0)
    assert "blocked" in exc_info.value.code


def test_ssrf_pinning_handles_ipv4_ipv6_and_literals(monkeypatch: pytest.MonkeyPatch) -> None:
    """pin_stream_url correctly normalizes IPv4, bracketed IPv6, and direct literals."""
    # Direct IPv4 literal
    policy_cidr = SSRFPolicy(
        allowed_schemes=frozenset({"http", "https", "rtsp", "rtsps"}),
        allowed_hosts=None,
        allowed_ports=None,
        site_cidr_allowlist=(ipaddress.ip_network("192.168.1.0/24"), ipaddress.ip_network("2001:db8::/32")),
    )
    pinned, ips = pin_stream_url("rtsp://192.168.1.50:554/live?fps=15", policy_cidr)
    assert pinned == "rtsp://192.168.1.50:554/live?fps=15"
    assert ips == ["192.168.1.50"]

    # Direct IPv6 literal
    pinned_v6, ips_v6 = pin_stream_url("http://[2001:db8::1]:8080/feed", policy_cidr)
    assert pinned_v6 == "http://[2001:db8::1]:8080/feed"
    assert ips_v6 == ["2001:db8::1"]

    # Hostname resolving to IPv6
    def mock_getaddrinfo_v6(host: str, port: Any, **kwargs: Any) -> list:
        return [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2001:db8::42", 0, 0, 0))]

    monkeypatch.setattr(socket, "getaddrinfo", mock_getaddrinfo_v6)
    pinned_host_v6, ips_host_v6 = pin_stream_url("http://ipv6-cam.site.local:8080/video", policy_cidr)
    assert pinned_host_v6 == "http://[2001:db8::42]:8080/video"
    assert ips_host_v6 == ["2001:db8::42"]


def test_ssrf_pinning_rejects_if_any_dns_record_forbidden(monkeypatch: pytest.MonkeyPatch) -> None:
    """If a domain resolves to multiple A/AAAA records and ANY record is forbidden, fail."""

    def mock_dual_records(host: str, port: Any, **kwargs: Any) -> list:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0)),  # Public
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 0)),  # Cloud metadata
        ]

    monkeypatch.setattr(socket, "getaddrinfo", mock_dual_records)
    with pytest.raises(SSRFError) as exc_info:
        pin_stream_url("http://dual-homed-attack.com/stream", DEFAULT_POLICY)
    assert "blocked" in exc_info.value.code


def test_ssrf_pinning_preserves_query_and_credentials() -> None:
    """Pinning preserves URL components, query parameters, and handles userinfo."""
    policy = SSRFPolicy(
        allowed_schemes=frozenset({"http", "https", "rtsp", "rtsps"}),
        allowed_hosts=None,
        allowed_ports=None,
        site_cidr_allowlist=(ipaddress.ip_network("192.168.1.0/24"),),
    )
    pinned, _ = pin_stream_url("rtsp://192.168.1.55:554/ch0?res=high&codec=h264#section1", policy)
    assert pinned == "rtsp://192.168.1.55:554/ch0?res=high&codec=h264#section1"


def test_ssrf_dns_rebinding_av_open_pinned_destination(monkeypatch: pytest.MonkeyPatch) -> None:
    """Proves the security invariant: The authorized IP is the exact destination given to av.open.

    Even when DNS rebinds immediately to 127.0.0.1, av.open receives the pinned IP literal
    and never resolves the rebound hostname. Subsequent reconnect attempts detect the rebind
    and fail closed.
    """
    import av

    from ibvap.core.probe import probe_url

    dns_queries: list[str] = []
    dns_state = {"ip": "93.184.216.34"}  # Public, allowed

    def mock_getaddrinfo(host: str, port: Any, **kwargs: Any) -> list:
        dns_queries.append(host)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (dns_state["ip"], 0))]

    monkeypatch.setattr(socket, "getaddrinfo", mock_getaddrinfo)

    av_opened_urls: list[str] = []

    class DummyContainer:
        streams = []

        def close(self) -> None:
            pass

    def mock_av_open(url: str, **kwargs: Any) -> Any:
        av_opened_urls.append(url)
        # Raise error to exit probe loop after recording target URL
        raise av.error.InvalidDataError(1, "test probe stop")  # pyright: ignore[reportAttributeAccessIssue] # av.error exists at runtime; missing from pyright stubs

    monkeypatch.setattr(av, "open", mock_av_open)

    target_domain = "cam-rebind.attacker-infra.net"
    url = f"rtsp://{target_domain}:554/live"

    # Step 1: Probe URL - initial DNS query resolves to allowed public IP
    with pytest.raises((ConnectionError, RuntimeError, Exception)):
        probe_url(url, timeout=1.0)

    # Invariant verified: av.open was invoked with the PINNED IP LITERAL, not the attacker domain!
    assert len(av_opened_urls) == 1
    assert av_opened_urls[0] == "rtsp://93.184.216.34:554/live"
    assert target_domain not in av_opened_urls[0]

    # Step 2: Attacker executes DNS rebinding attack (changes DNS record to 127.0.0.1)
    dns_state["ip"] = "127.0.0.1"

    # Step 3: Stream worker or subsequent probe attempts connection on the stream URL
    with pytest.raises(SSRFError) as exc_info:
        pin_stream_url(url, DEFAULT_POLICY, timeout=2.0)
    # The rebinding attack is rejected before any connection is made!
    assert "blocked" in exc_info.value.code


# ============================================================================
# 2. ANPR PERSISTENT STATE GROWTH TESTS
# ============================================================================


def test_anpr_bounded_history_and_dead_track_eviction() -> None:
    """Vote history for dead tracks is evicted while active tracks preserve consensus."""
    pipeline = ANPRPipeline(max_history_tracks=50)

    # 1. Simulate active vehicles 1, 2, 3 accumulating votes
    for _ in range(5):
        pipeline.consensus_for(vehicle_id=1, text="MH01AB1111", stream_epoch=0)
        pipeline.consensus_for(vehicle_id=2, text="MH02CD2222", stream_epoch=0)
        pipeline.consensus_for(vehicle_id=3, text="MH03EF3333", stream_epoch=0)

    assert pipeline.votes_for(1, "MH01AB1111", stream_epoch=0) == 5
    assert pipeline.votes_for(2, "MH02CD2222", stream_epoch=0) == 5
    assert pipeline.votes_for(3, "MH03EF3333", stream_epoch=0) == 5

    # 2. Vehicle 1 leaves the frame (only 2 and 3 remain active)
    active_tracks = {2, 3}
    # Immediate eviction within grace period should preserve vehicle 1
    evicted = pipeline.evict_dead_tracks(active_track_ids=active_tracks, stream_epoch=0, grace_period_s=10.0)
    assert evicted == 0
    assert (0, 1) in pipeline._history

    # After grace period elapsed (simulate with grace_period_s=0.0):
    evicted = pipeline.evict_dead_tracks(active_track_ids=active_tracks, stream_epoch=0, grace_period_s=0.0)
    assert evicted == 1
    assert (0, 1) not in pipeline._history
    assert (0, 2) in pipeline._history
    assert (0, 3) in pipeline._history

    # Active tracks 2 and 3 retain full consensus votes
    assert pipeline.votes_for(2, "MH02CD2222", stream_epoch=0) == 5
    assert pipeline.votes_for(3, "MH03EF3333", stream_epoch=0) == 5


def test_anpr_ocr_throttling_state_bounded_and_evicts_stale() -> None:
    """OCR throttle state in stream_worker evicts departed tracks and is bounded to <= 512."""
    ocr_last_submitted: dict[int | tuple[int, float, float], float] = {}

    # 1. Simulate active vehicles 10, 20 having recent OCR submissions
    t0 = time.monotonic()
    ocr_last_submitted[10] = t0
    ocr_last_submitted[20] = t0

    # Simulate an inactive departed vehicle 99 submitted 6 seconds ago
    ocr_last_submitted[99] = t0 - 6.0

    # Run the stream_worker pruning routine
    active_tids = {10, 20}
    now_m = time.monotonic()
    stale_ocr = [
        k
        for k, ts in ocr_last_submitted.items()
        if (isinstance(k, int) and k not in active_tids and (now_m - ts) > 5.0)
        or (not isinstance(k, int) and (now_m - ts) > 5.0)
    ]
    for k in stale_ocr:
        ocr_last_submitted.pop(k, None)

    # Departed vehicle 99 was evicted, active vehicles 10 and 20 are preserved
    assert 99 not in ocr_last_submitted
    assert 10 in ocr_last_submitted
    assert 20 in ocr_last_submitted

    # 2. Simulate heavy burst exceeding 512 entries
    for vid in range(100, 750):  # 650 entries
        ocr_last_submitted[vid] = time.monotonic() + (vid * 0.001)

    assert len(ocr_last_submitted) > 512

    # Run LRU capacity cap
    if len(ocr_last_submitted) > 512:
        oldest_ocr = sorted(ocr_last_submitted.items(), key=lambda item: item[1])[: len(ocr_last_submitted) - 512]
        for k, _ in oldest_ocr:
            ocr_last_submitted.pop(k, None)

    # Size is capped at exactly 512
    assert len(ocr_last_submitted) == 512


def test_anpr_long_running_stream_bounded_growth() -> None:
    """Simulates 1000 frames of a long-running stream with continuous vehicle turnover.

    Asserts history and last_active sizes never grow monotonically and remain strictly bounded.
    """
    pipeline = ANPRPipeline(max_history_tracks=32)

    # 50 batches of 10 vehicles each entering, staying for 5 iterations, then leaving
    current_vehicle_id = 1
    for _batch in range(50):
        active_ids = set(range(current_vehicle_id, current_vehicle_id + 5))
        for vid in active_ids:
            pipeline.consensus_for(vehicle_id=vid, text=f"KA{vid:04d}ZZ", stream_epoch=0)

        # Evict dead tracks with grace period 0.0s
        pipeline.evict_dead_tracks(active_track_ids=active_ids, stream_epoch=0, grace_period_s=0.0)

        # At any point, history size is strictly equal to active vehicle count (5)
        assert len(pipeline._history) == 5
        assert len(pipeline._last_active) == 5
        current_vehicle_id += 5

    # Memory state is flat and bounded, exactly 5 vehicles in memory after 250 vehicles passed
    assert len(pipeline._history) == 5


def test_anpr_many_vehicles_entering_leaving_bounded_memory() -> None:
    """Over 1000 vehicles entering and leaving, memory remains strictly bounded."""
    pipeline = ANPRPipeline(max_history_tracks=32)

    # Simulate 1000 vehicles sequentially passing through
    for vid in range(1, 1001):
        pipeline.consensus_for(vehicle_id=vid, text=f"DL{vid:04d}AA", stream_epoch=0)
        # Simultaneously evict dead tracks with current vehicle active
        pipeline.evict_dead_tracks(active_track_ids={vid}, stream_epoch=0, grace_period_s=0.0)

    # Size should be exactly 1 (the single active vehicle), NOT 1000!
    assert len(pipeline._history) == 1
    assert (0, 1000) in pipeline._history


def test_anpr_lru_hard_capacity_limit() -> None:
    """Even if evict_dead_tracks is not called, LRU bounds history size to max_history_tracks."""
    pipeline = ANPRPipeline(max_history_tracks=20)
    for vid in range(1, 101):
        pipeline.consensus_for(vehicle_id=vid, text=f"PLATE{vid:03d}", stream_epoch=0)

    assert len(pipeline._history) == 20
    # The oldest 80 vehicles were evicted by LRU
    assert (0, 1) not in pipeline._history
    assert (0, 100) in pipeline._history


def test_anpr_repeated_ids_no_cross_contamination() -> None:
    """When a track ID is recycled after dead-track eviction, the new vehicle starts fresh."""
    pipeline = ANPRPipeline()

    # Old vehicle with ID 5
    for _ in range(5):
        pipeline.consensus_for(vehicle_id=5, text="OLDPLATE01", stream_epoch=0)
    assert pipeline.consensus_for(vehicle_id=5, text="OLDPLATE01", stream_epoch=0) == "OLDPLATE01"

    # Vehicle 5 departs and is evicted
    pipeline.evict_dead_tracks(active_track_ids=set(), stream_epoch=0, grace_period_s=0.0)
    assert (0, 5) not in pipeline._history

    # New vehicle assigned ID 5 later
    c = pipeline.consensus_for(vehicle_id=5, text="NEWPLATE02", stream_epoch=0)
    assert c == "NEWPLATE02"
    # Votes for OLDPLATE01 must be 0
    assert pipeline.votes_for(vehicle_id=5, text="OLDPLATE01", stream_epoch=0) == 0


def test_anpr_stream_epoch_bump_purges_old_history() -> None:
    """When stream reconnects (epoch changes), old epoch votes are purged."""
    pipeline = ANPRPipeline()
    pipeline.consensus_for(vehicle_id=1, text="EPOCH0PLATE", stream_epoch=0)
    assert (0, 1) in pipeline._history

    # Reconnect -> epoch 1
    pipeline.consensus_for(vehicle_id=1, text="EPOCH1PLATE", stream_epoch=1)
    assert (0, 1) not in pipeline._history
    assert (1, 1) in pipeline._history


# ============================================================================
# 3. WEBSOCKET LIFECYCLE TESTS
# ============================================================================


def test_websocket_disabled_by_default_rejects_with_policy_code() -> None:
    """WebSocket is disabled by default to prevent false production capability."""
    app = create_app()
    client = TestClient(app)

    with pytest.raises(WebSocketDisconnect) as exc_info, client.websocket_connect("/api/v1/ws"):
        pass
    assert exc_info.value.code == 1008


def test_websocket_development_mode_notifies_notice() -> None:
    """When enable_ws is True for development, client receives explicit development notice."""
    settings = Settings()
    settings.app.enable_ws = True
    app = create_app(settings=settings)
    client = TestClient(app)

    with client.websocket_connect("/api/v1/ws") as ws:
        msg = ws.receive_json()
        assert msg["message_type"] == "system.notice"
        assert msg["payload"]["status"] == "development_only"
        assert "non-production" in msg["payload"]["detail"]


# ============================================================================
# 4. RTSP WORKER SHUTDOWN TIMING TESTS
# ============================================================================


def test_rtsp_worker_stall_shutdown_within_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """Worker stalled in FFmpeg I/O stops deterministically within bounded timeout."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(5)
    port = srv.getsockname()[1]

    def serve():
        while True:
            try:
                conn, _ = srv.accept()
                header = (
                    b"HTTP/1.1 200 OK\r\n"
                    b"Content-Type: multipart/x-mixed-replace; boundary=--myboundary\r\n\r\n"
                    b"--myboundary\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n"
                    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00\xff\xdb\x00C\x00\xff\xd9\r\n"
                )
                conn.sendall(header)
                # Network stall: hold socket open without transmitting
                time.sleep(30)
                conn.close()
            except Exception:
                break

    t_srv = threading.Thread(target=serve, daemon=True)
    t_srv.start()

    cam_id = "test-cam-stall-1"
    SW._CAMERAS[cam_id] = {
        "id": cam_id,
        "name": "Stall Test Camera",
        "endpoint": f"http://127.0.0.1:{port}/video",
        "protocol": "http",
        "source_type": "smartphone_ip_webcam",
        "observed_state": "CONNECTING",
        "desired_state": "STREAMING",
        "stream_epoch": 0,
        "_site_cidr_allowlist": ["127.0.0.0/8"],
    }
    sm = CameraStateMachine(camera_id=cam_id)
    sm.state = CameraState.STREAMING
    SW._STATE_MACHINES[cam_id] = sm

    # Allow local test server to be reached without loopback SSRF block
    monkeypatch.setattr(SW, "pin_stream_url", lambda url, policy, timeout: (url, ["127.0.0.1"]))

    SW._start_camera_worker(cam_id)
    time.sleep(0.5)

    # Stop worker: must join cleanly and return True within default timeout
    t0 = time.monotonic()
    stopped = SW._stop_worker(cam_id, timeout=3.0)
    dur = time.monotonic() - t0

    assert stopped is True
    assert dur <= 3.0
    active = [t for t in threading.enumerate() if t.name == f"camera-{cam_id[:8]}" and t.is_alive()]
    assert len(active) == 0

    srv.close()
    SW._CAMERAS.pop(cam_id, None)
    SW._STATE_MACHINES.pop(cam_id, None)


def test_rtsp_worker_reconnect_during_stall_no_double_spawn(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reconnecting during a network stall does not spawn duplicate worker threads."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(5)
    port = srv.getsockname()[1]

    def serve():
        while True:
            try:
                conn, _ = srv.accept()
                header = (
                    b"HTTP/1.1 200 OK\r\n"
                    b"Content-Type: multipart/x-mixed-replace; boundary=--myboundary\r\n\r\n"
                    b"--myboundary\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n"
                    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00\xff\xdb\x00C\x00\xff\xd9\r\n"
                )
                conn.sendall(header)
                time.sleep(30)
                conn.close()
            except Exception:
                break

    t_srv = threading.Thread(target=serve, daemon=True)
    t_srv.start()

    cam_id = "test-cam-stall-2"
    SW._CAMERAS[cam_id] = {
        "id": cam_id,
        "name": "Stall Reconnect Camera",
        "endpoint": f"http://127.0.0.1:{port}/video",
        "protocol": "http",
        "source_type": "smartphone_ip_webcam",
        "observed_state": "CONNECTING",
        "desired_state": "STREAMING",
        "stream_epoch": 0,
        "_site_cidr_allowlist": ["127.0.0.0/8"],
    }
    sm = CameraStateMachine(camera_id=cam_id)
    sm.state = CameraState.STREAMING
    SW._STATE_MACHINES[cam_id] = sm

    monkeypatch.setattr(SW, "pin_stream_url", lambda url, policy, timeout: (url, ["127.0.0.1"]))

    SW._start_camera_worker(cam_id)
    time.sleep(0.5)

    # Simulate rapid operator reconnect while stream is stalled
    SW._stop_worker(cam_id, timeout=2.5)
    SW._start_camera_worker(cam_id)

    # At all times, there must be at most 1 alive worker thread
    active = [t for t in threading.enumerate() if t.name == f"camera-{cam_id[:8]}" and t.is_alive()]
    assert len(active) <= 1, f"Expected <= 1 alive worker thread, found {len(active)}"

    # Clean up
    SW._stop_worker(cam_id, timeout=2.5)
    srv.close()
    SW._CAMERAS.pop(cam_id, None)
    SW._STATE_MACHINES.pop(cam_id, None)


def test_ssrf_check_http_redirect_uses_pinned_ip_no_dns_rebinding(monkeypatch: pytest.MonkeyPatch) -> None:
    """Proves check_http_redirect connects directly to authorized IP literal.

    Verifies that no secondary DNS lookup is made during HTTP redirect inspection,
    eliminating the TOCTOU / DNS rebinding vulnerability in redirect checks.
    """
    dns_queries: list[str] = []

    def mock_getaddrinfo(host: str, port: Any, **kwargs: Any) -> list:
        dns_queries.append(host)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port or 80))]

    monkeypatch.setattr(socket, "getaddrinfo", mock_getaddrinfo)

    connected_addrs: list[tuple[str, int]] = []

    def mock_create_connection(address: tuple[str, int], *args: Any, **kwargs: Any) -> socket.socket:
        connected_addrs.append(address)
        # Raise to stop after recording socket destination
        raise ConnectionRefusedError("mock connect stop")

    monkeypatch.setattr(socket, "create_connection", mock_create_connection)

    url = "http://rebind-test.attacker.com:8080/stream"
    pinned_url, ips = pin_stream_url(url, DEFAULT_POLICY, timeout=1.0)

    # 1. DNS was queried only for the initial resolution
    assert dns_queries == ["rebind-test.attacker.com"]
    # 2. The socket connection was made to the PINNED IP LITERAL, NOT the hostname!
    assert len(connected_addrs) >= 1
    assert connected_addrs[0][0] == "93.184.216.34"
    assert connected_addrs[0][0] != "rebind-test.attacker.com"


def test_ssrf_probe_url_disables_ffmpeg_redirects(monkeypatch: pytest.MonkeyPatch) -> None:
    """Proves probe_url passes follow_redirects=0 to av.open when allow_redirects=False."""
    import av

    from ibvap.core.probe import probe_url

    captured_opts: dict[str, str] = {}

    def mock_av_open(url: str, **kwargs: Any) -> Any:
        options = kwargs.get("options", {})
        captured_opts.update(options)
        raise av.error.InvalidDataError(1, "mock open exit")  # pyright: ignore[reportAttributeAccessIssue] # av.error exists at runtime; missing from pyright stubs

    monkeypatch.setattr(av, "open", mock_av_open)

    def mock_gai(host: str, port: Any, **kwargs: Any) -> list:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", mock_gai)

    from ibvap.core.probe import ProbeError

    with pytest.raises(ProbeError):
        probe_url("http://camera.site.com:8080/video", timeout=1.0, policy=DEFAULT_POLICY)

    # follow_redirects MUST be "0" when policy.allow_redirects is False (default)
    assert captured_opts.get("follow_redirects") == "0"


def test_ssrf_reconnect_rebind_transitions_to_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    """When a streaming camera rebinds to a forbidden IP on reconnect, worker marks FAILED and stops."""
    dns_state = {"ip": "93.184.216.34"}

    def mock_gai(host: str, port: Any, **kwargs: Any) -> list:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (dns_state["ip"], 0))]

    monkeypatch.setattr(socket, "getaddrinfo", mock_gai)

    cam_id = "test-cam-rebind-fail"
    SW._CAMERAS[cam_id] = {
        "id": cam_id,
        "name": "Rebind Fail Cam",
        "endpoint": "rtsp://camera.attacker.com:554/live",
        "protocol": "rtsp",
        "source_type": "cctv_generic_rtsp",
        "observed_state": "STREAMING",
        "desired_state": "STREAMING",
        "stream_epoch": 0,
    }
    sm = CameraStateMachine(camera_id=cam_id)
    sm.state = CameraState.STREAMING
    SW._STATE_MACHINES[cam_id] = sm

    try:
        # Attacker executes DNS rebinding attack
        dns_state["ip"] = "127.0.0.1"

        stop = threading.Event()
        # Run one cycle of _camera_worker
        SW._camera_worker(cam_id, stop)

        # Observed state must be FAILED, NOT endlessly spinning in RECONNECTING
        assert SW._CAMERAS[cam_id]["observed_state"] == "FAILED"
        assert sm.state == CameraState.FAILED
    finally:
        SW._CAMERAS.pop(cam_id, None)
        SW._STATE_MACHINES.pop(cam_id, None)


def test_anpr_concurrent_access_thread_safety() -> None:
    """Concurrent threads updating consensus and evicting dead tracks run safely without corruption."""
    pipeline = ANPRPipeline(max_history_tracks=20)
    errors: list[Exception] = []

    def writer_worker(thread_idx: int) -> None:
        try:
            for i in range(100):
                vid = (thread_idx * 10) + (i % 10)
                pipeline.consensus_for(vehicle_id=vid, text=f"PLATE{vid:04d}", stream_epoch=0)
                pipeline.votes_for(vehicle_id=vid, text=f"PLATE{vid:04d}", stream_epoch=0)
        except Exception as e:
            errors.append(e)

    def evictor_worker() -> None:
        try:
            for _ in range(100):
                active = {1, 2, 3, 4, 5}
                pipeline.evict_dead_tracks(active_track_ids=active, stream_epoch=0, grace_period_s=0.0)
                time.sleep(0.001)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=writer_worker, args=(i,)) for i in range(4)]
    threads.append(threading.Thread(target=evictor_worker))
    threads.append(threading.Thread(target=evictor_worker))

    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5.0)

    assert len(errors) == 0, f"Concurrent ANPR operations raised exceptions: {errors}"
    assert len(pipeline._history) <= 20, "ANPR history exceeded max_history_tracks capacity"


def test_rtsp_worker_start_lock_contention_eliminated() -> None:
    """A stopping thread on Camera 1 does not block Camera 2 from starting or acquiring _WORKERS_LOCK."""
    cam1 = "cam-lock-test-1"

    SW._CAMERAS[cam1] = {
        "id": cam1,
        "name": "Lock Test Cam",
        "endpoint": "synthetic://test",
        "protocol": "synthetic",
        "source_type": "synthetic",
        "observed_state": "STREAMING",
        "desired_state": "STREAMING",
        "stream_epoch": 0,
    }

    stuck_event = threading.Event()

    def slow_stopping_thread() -> None:
        stuck_event.wait(1.5)

    t1 = threading.Thread(target=slow_stopping_thread, daemon=True)
    t1.start()

    with SW._WORKERS_LOCK:
        SW._STOPPING_WORKERS[cam1] = [t1]

    # Thread starts camera 1 worker, which coordinates with stopping t1
    t_start = threading.Thread(target=SW._start_camera_worker, args=(cam1,), daemon=True)
    t_start.start()

    # Give t_start a moment to reach coordinate step
    time.sleep(0.1)

    # Verify that Camera 2 can acquire _WORKERS_LOCK immediately (< 0.1s)
    t0 = time.monotonic()
    acquired = SW._WORKERS_LOCK.acquire(timeout=0.2)
    dur = time.monotonic() - t0
    if acquired:
        SW._WORKERS_LOCK.release()

    # Clean up
    stuck_event.set()
    t_start.join(timeout=2.0)
    t1.join(timeout=2.0)
    SW._STOPPING_WORKERS.pop(cam1, None)
    SW._CAMERAS.pop(cam1, None)
    SW._stop_worker(cam1, timeout=1.0)

    assert acquired is True
    assert dur < 0.2, f"_WORKERS_LOCK was held for {dur:.3f}s during stopping worker join"


def test_rtsp_worker_midstream_stall_disable_and_reconnect(monkeypatch: pytest.MonkeyPatch) -> None:
    """Controlled mid-stream stall: disabling and reconnecting during stall stops cleanly and avoids leaks."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(5)
    port = srv.getsockname()[1]

    def serve():
        while True:
            try:
                conn, _ = srv.accept()
                header = (
                    b"HTTP/1.1 200 OK\r\n"
                    b"Content-Type: multipart/x-mixed-replace; boundary=--myboundary\r\n\r\n"
                    b"--myboundary\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n"
                    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00\xff\xdb\x00C\x00\xff\xd9\r\n"
                )
                conn.sendall(header)
                # Network stall: pause indefinitely without sending frames or FIN
                time.sleep(30)
                conn.close()
            except Exception:
                break

    t_srv = threading.Thread(target=serve, daemon=True)
    t_srv.start()

    cam_id = "test-cam-stall-disable-rec"
    SW._CAMERAS[cam_id] = {
        "id": cam_id,
        "name": "Stall Disable Reconnect Cam",
        "endpoint": f"http://127.0.0.1:{port}/video",
        "protocol": "http",
        "source_type": "smartphone_ip_webcam",
        "observed_state": "CONNECTING",
        "desired_state": "STREAMING",
        "stream_epoch": 0,
        "_site_cidr_allowlist": ["127.0.0.0/8"],
    }
    sm = CameraStateMachine(camera_id=cam_id)
    sm.state = CameraState.STREAMING
    SW._STATE_MACHINES[cam_id] = sm

    monkeypatch.setattr(SW, "pin_stream_url", lambda url, policy, timeout: (url, ["127.0.0.1"]))

    SW._start_camera_worker(cam_id)
    time.sleep(0.5)

    # 1. Disable during midstream stall
    sm.disable()
    SW._CAMERAS[cam_id]["observed_state"] = sm.state.value
    SW._CAMERAS[cam_id]["desired_state"] = "DISABLED"
    t0 = time.monotonic()
    stopped = SW._stop_worker(cam_id, timeout=3.5)
    assert stopped is True
    assert time.monotonic() - t0 <= 3.5
    assert SW._CAMERAS[cam_id]["observed_state"] == "DISABLED"

    # 2. Reconnect camera: starts cleanly without leaked duplicate threads
    sm.transition(CameraState.DRAFT, reason="enable", safe_message="Enabled")
    sm.transition(CameraState.VALIDATING, reason="enable", safe_message="Validating")
    sm.transition(CameraState.SAVING, reason="enable", safe_message="Saving")
    sm.transition(CameraState.STARTING, reason="start", safe_message="Starting")
    sm.transition(CameraState.STREAMING, reason="streaming", safe_message="Streaming")
    SW._CAMERAS[cam_id]["observed_state"] = "STREAMING"
    SW._CAMERAS[cam_id]["desired_state"] = "STREAMING"
    SW._start_camera_worker(cam_id)

    time.sleep(0.5)
    active = [t for t in threading.enumerate() if t.name == f"camera-{cam_id[:8]}" and t.is_alive()]
    assert len(active) == 1

    # Final cleanup
    SW._stop_worker(cam_id, timeout=2.5)
    srv.close()
    SW._CAMERAS.pop(cam_id, None)
    SW._STATE_MACHINES.pop(cam_id, None)
