from __future__ import annotations

import os
import tempfile

import cv2
import numpy as np

from ibvap.core.pipeline import MiniPipeline
from ibvap.events.outbox import clear_all, list_events


def test_pipeline_synthetic_frames_create_one_event() -> None:
    clear_all()
    pipe = MiniPipeline(camera_id="cam-test-1", stream_epoch=0)
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
        pipe = MiniPipeline(camera_id="cam-video-1")
        evs = pipe.process_video_file(tmp.name, max_frames=16)
        # should have at least one intrusion as avatar crosses central zone
        assert len(evs) >= 1
    finally:
        import contextlib

        with contextlib.suppress(Exception):
            os.unlink(tmp.name)
