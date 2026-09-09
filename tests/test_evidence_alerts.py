from __future__ import annotations

from ibvap.core.alerts import create_alert
from ibvap.core.evidence import PacketRingBuffer


def test_ring_buffer_manifest() -> None:
    from pathlib import Path

    rb = PacketRingBuffer(max_seconds=5.0, max_bytes=1024 * 1024)
    rb.push(b"keyframe-data", is_keyframe=True)
    rb.push(b"p1", is_keyframe=False)
    snap, clip = rb.snapshot_clip(pre_seconds=1.0, post_seconds=1.0)
    assert snap is not None
    manifest = rb.manifest_for("ev-1", snap, clip)
    assert manifest.event_id == "ev-1"
    assert manifest.snapshot_sha256 is not None
    for attr in ("clip_path", "snapshot_path"):
        p = getattr(manifest, attr, None)
        if p:
            Path(p).unlink(missing_ok=True)


def test_alert_workflow() -> None:
    a = create_alert("ev-1", "cam-1", "high")
    assert a.state == "open"
    a.acknowledge("operator1")
    assert a.state == "acknowledged"
    a.assign("operator2", actor="operator1")
    assert a.state == "assigned"
    assert a.assignee == "operator2"
    a.resolve("operator2")
    assert a.state == "resolved"


def test_alert_dismiss_requires_reason() -> None:
    a = create_alert("ev-2", "cam-1", "low")
    try:
        a.dismiss("op", reason="")
        raise AssertionError("should raise")
    except ValueError:
        pass


def test_manifest_matches_stored_clip() -> None:
    """A verifier hashing the stored clip file must reproduce the manifest hash."""
    import hashlib
    from pathlib import Path

    rb = PacketRingBuffer(max_seconds=30, max_bytes=200 * 1024 * 1024)
    for _ in range(5):
        rb.push(b"X" * 5000, is_keyframe=False)
    snap, clip = rb.snapshot_clip()
    assert clip is not None and len(clip) > 1024
    m = rb.manifest_for("ev-probe", snap, clip)
    try:
        assert m.clip_path is not None and m.clip_sha256 is not None
        assert hashlib.sha256(Path(m.clip_path).read_bytes()).hexdigest() == m.clip_sha256
    finally:
        if m.clip_path:
            Path(m.clip_path).unlink(missing_ok=True)
        if m.snapshot_path:
            Path(m.snapshot_path).unlink(missing_ok=True)
