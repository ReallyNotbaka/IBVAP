from __future__ import annotations

from ibvap.core.alerts import create_alert
from ibvap.core.evidence import PacketRingBuffer


def test_ring_buffer_manifest() -> None:
    rb = PacketRingBuffer(max_seconds=5.0, max_bytes=1024 * 1024)
    rb.push(b"keyframe-data", is_keyframe=True)
    rb.push(b"p1", is_keyframe=False)
    snap, clip = rb.snapshot_clip(pre_seconds=1.0, post_seconds=1.0)
    assert snap is not None
    manifest = rb.manifest_for("ev-1", snap, clip)
    assert manifest.event_id == "ev-1"
    assert manifest.snapshot_sha256 is not None


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
