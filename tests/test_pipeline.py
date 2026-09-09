from __future__ import annotations

import os
import tempfile

import cv2
import numpy as np

from ibvap.core.detector import MockPersonDetector
from ibvap.core.pipeline import MiniPipeline
from ibvap.core.zone_engine import Zone
from ibvap.events.outbox import clear_all, list_events


def test_pipeline_synthetic_frames_create_one_event() -> None:
    clear_all()
    pipe = MiniPipeline(camera_id="cam-test-1", stream_epoch=0, detector=MockPersonDetector())
    # feed 30 synthetic frames - mock detector will fire between 5-20 and intrusion at central zone
    events = []
    for i in range(30):
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        # put moving white avatar to ensure mean >0 for some frames
        if 5 <= i <= 20:
            x = int(100 + i * 10)
            cv2.rectangle(frame, (x, 100), (x + 60, 250), (255, 255, 255), -1)
        ev = pipe.process_frame(frame)
        if ev:
            events.append(ev)
    # at least one intrusion event
    assert len(events) >= 1
    assert events[0]["event_type"] == "zone_intrusion"
    assert events[0]["camera_id"] == "cam-test-1"
    # persisted in outbox
    assert len(list_events()) >= 1
    # dedup: same dedup window should not create duplicate
    from ibvap.events.outbox import transactional_write

    e = {"camera_id": "cam-test-1", "event_type": "zone_intrusion"}
    a = transactional_write(e, dedup_key="dup-key-123")
    b = transactional_write(e, dedup_key="dup-key-123")
    assert a.id == b.id


def test_pipeline_from_real_video_file() -> None:
    clear_all()
    # create temp video file with 16 frames
    tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)  # noqa: SIM115
    tmp.close()
    try:
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")  # type: ignore[attr-defined]
        writer = cv2.VideoWriter(tmp.name, fourcc, 10.0, (640, 480))
        for i in range(16):
            frame = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.rectangle(frame, (50 + i * 20, 100), (110 + i * 20, 300), (255, 255, 255), -1)
            writer.write(frame)
        writer.release()
        assert os.path.exists(tmp.name)
        pipe = MiniPipeline(camera_id="cam-video-1", detector=MockPersonDetector())
        evs = pipe.process_video_file(tmp.name, max_frames=16)
        # should have at least one intrusion as avatar crosses central zone
        assert len(evs) >= 1
    finally:
        import contextlib

        with contextlib.suppress(Exception):
            os.unlink(tmp.name)


def test_pipeline_zone_intrusion_and_exit_events() -> None:
    """Verify zone intrusion followed by zone exit produces debounced events without spam."""
    clear_all()
    pipe = MiniPipeline(camera_id="cam-zone-test", stream_epoch=1, detector=MockPersonDetector())

    # Feed frames 5..20 where mock detector produces box entering central zone
    for i in range(25):
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        if 5 <= i <= 20:
            x = int(100 + i * 10)
            cv2.rectangle(frame, (x, 100), (x + 60, 250), (255, 255, 255), -1)
        pipe.process_frame(frame)

    events = list_events()
    event_types = [e["event_type"] for e in events]
    assert "zone_intrusion" in event_types, f"Expected zone_intrusion in {event_types}"

    # Now feed blank frames so the target moves out or terminates
    for _ in range(35):
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        pipe.process_frame(frame)

    events_after = list_events()
    event_types_after = [e["event_type"] for e in events_after]
    assert "zone_exit" in event_types_after, f"Expected zone_exit in {event_types_after}"
    # Ensure neither zone_intrusion nor zone_exit flooded hundreds of events
    intrusion_count = sum(1 for e in events_after if e["event_type"] == "zone_intrusion")
    exit_count = sum(1 for e in events_after if e["event_type"] == "zone_exit")
    assert intrusion_count == 1, f"Expected 1 debounced intrusion, got {intrusion_count}"
    assert exit_count == 1, f"Expected 1 debounced exit, got {exit_count}"


def test_pipeline_line_tripwire_crossing() -> None:
    """Verify that a 2-point line tripwire flags crossing targets as zone intrusions."""
    clear_all()
    pipe = MiniPipeline(camera_id="cam-line-test", stream_epoch=1, detector=MockPersonDetector())
    # Configure a vertical tripwire line at x = 0.25 (x pixel ~ 160)
    pipe.zone = Zone(
        id="zone-tripwire-1",
        name="Perimeter Tripwire",
        polygon=[[0.25, 0.0], [0.25, 1.0]],
        fence_type="line",
    )

    # Feed frames 5..20 where target crosses from x ~ 100 to x ~ 300
    for i in range(25):
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        if 5 <= i <= 20:
            x = int(100 + i * 10)
            cv2.rectangle(frame, (x, 100), (x + 60, 250), (255, 255, 255), -1)
        pipe.process_frame(frame)

    events = list_events()
    event_types = [e["event_type"] for e in events]
    assert "zone_intrusion" in event_types, f"Expected zone_intrusion for tripwire crossing in {event_types}"
    intrusions = [e for e in events if e["event_type"] == "zone_intrusion"]
    assert len(intrusions) >= 1
    assert intrusions[0]["explanation"]["rule"] == "tripwire_line_crossing"


def test_pipeline_line_tripwire_exit_and_intruder_cleanup() -> None:
    """Verify that when a line intruder terminates, zone_exit is emitted with rule tripwire_line_exit and tracked set is cleaned up."""
    clear_all()
    pipe = MiniPipeline(camera_id="cam-cleanup-test", stream_epoch=1, detector=MockPersonDetector())
    pipe.zone = Zone(
        id="zone-tripwire-clean",
        name="Perimeter Tripwire",
        polygon=[[0.25, 0.0], [0.25, 1.0]],
        fence_type="line",
    )

    # Frame 1..15: target enters and crosses line
    for i in range(15):
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        x = int(120 + i * 10)
        cv2.rectangle(frame, (x, 100), (x + 60, 250), (255, 255, 255), -1)
        pipe.process_frame(frame)

    assert len(pipe._active_line_intruders) >= 1

    # Feed 35 empty frames so track ages out and terminates (max_age=30)
    for _ in range(35):
        empty = np.zeros((480, 640, 3), dtype=np.uint8)
        pipe.process_frame(empty)

    # _active_line_intruders MUST be empty after track termination (no leak)
    assert len(pipe._active_line_intruders) == 0, f"Expected active line intruders to be empty, got {pipe._active_line_intruders}"

    events = list_events()
    exits = [e for e in events if e["event_type"] == "zone_exit"]
    assert len(exits) >= 1
    assert exits[0]["explanation"]["rule"] == "tripwire_line_exit"
