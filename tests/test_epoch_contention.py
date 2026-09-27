"""Task 3 (P1 inference): contention + epoch-resync regression tests.

TDD: written first against the intended post-fix APIs, adapted to the real
signatures (``record_sighting(entry_id, timestamp)``, ``get_entry``,
``process_frame(frame)``). Expected pre-fix: FAIL/ERROR (lost sightings,
missing offload/predict-lock/epoch-purge helpers, allowlist ignored,
handle race). Post-fix: PASS.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import Future
from pathlib import Path

import numpy as np

from ibvap.core.pipeline import MiniPipeline
from ibvap.core.watchlist import TargetType, WatchlistEntry, WatchlistStore


def _contention_store(tmp_path: Path) -> WatchlistStore:
    entry = WatchlistEntry(
        id="ABC123",
        name="Contention Car",
        target_type=TargetType.PLATE,
        plate_number="ABC 123",
    )
    store = WatchlistStore(storage_path=tmp_path / "watchlist.json")
    store.add_entry(entry)
    return store


def test_watchlist_concurrent_no_lost_updates(tmp_path: Path) -> None:
    """8 threads x 25 sightings must credit exactly 200 (no lost updates)."""
    store = _contention_store(tmp_path)
    per_thread = 25
    n_threads = 8
    barrier = threading.Barrier(n_threads)

    def hammer() -> None:
        barrier.wait()
        for _ in range(per_thread):
            store.record_sighting("ABC123", time.time())

    threads = [threading.Thread(target=hammer) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30.0)
    assert not any(t.is_alive() for t in threads)
    store.flush()

    got = store.get_entry("ABC123")
    assert got is not None
    assert got.sight_count == n_threads * per_thread

    reloaded = WatchlistStore(storage_path=tmp_path / "watchlist.json")
    assert reloaded.get_entry("ABC123").sight_count == n_threads * per_thread


def test_watchlist_sighting_save_debounced_until_flush(tmp_path: Path) -> None:
    """Hot-path sightings must defer the JSON rewrite until flush()/debounce.

    Prevents sync full-file saves stalling inference per alert; flush() must
    then make the sighting durable on disk.
    """
    store = _contention_store(tmp_path)
    store.flush()
    assert WatchlistStore(storage_path=tmp_path / "watchlist.json").get_entry("ABC123").sight_count == 0

    store.record_sighting("ABC123", time.time())

    assert WatchlistStore(storage_path=tmp_path / "watchlist.json").get_entry("ABC123").sight_count == 0

    store.flush()
    assert WatchlistStore(storage_path=tmp_path / "watchlist.json").get_entry("ABC123").sight_count == 1


def test_epoch_bump_clears_latch() -> None:
    """An intrusion latch must not survive a stream-epoch bump."""
    from ibvap.core.detector import Detection
    from ibvap.events.outbox import clear_all

    clear_all()

    class _InsideDetector:
        model_id = "stub"
        runtime = "cpu"

        def detect(self, frame: np.ndarray, frame_id: int) -> list:
            return [
                Detection(
                    class_id=0,
                    class_name="person",
                    bbox_norm=(0.3, 0.4, 0.5, 0.8),
                    confidence=0.9,
                    model_id="s",
                    runtime="c",
                )
            ]

    pipe = MiniPipeline(
        camera_id="cam-epoch-latch",
        stream_epoch=1,
        detector=_InsideDetector(),  # type: ignore[arg-type]
        face_detector=None,
        enable_face=False,
    )
    for _ in range(8):
        pipe.process_frame(np.zeros((480, 640, 3), dtype=np.uint8))
    assert len(pipe.alerted_tracks) >= 1, "setup must latch an intrusion alert"

    pipe.reset_epoch(2)

    assert pipe.alerted_tracks == set()
    assert pipe.watchlist_alerted_tracks == set()
    assert pipe.stream_epoch == 2
    assert pipe.tracker.stream_epoch == 2


def test_policy_allowlist_override_isolates_sites() -> None:
    """A non-None per-request allowlist replaces global settings (override)."""
    from ibvap.services.stream_worker import _policy_from_request

    policy = _policy_from_request(["10.9.0.0/16"])
    assert [str(n) for n in policy.site_cidr_allowlist] == ["10.9.0.0/16"]

    # Explicit empty list stays empty: private ranges denied (fail-closed).
    denied = _policy_from_request([])
    assert list(denied.site_cidr_allowlist) == []


def test_shared_detector_handle_singleton_under_threads(
    monkeypatch,
) -> None:
    """Concurrent first-use must yield one shared handle (double-checked lock)."""
    import ibvap.core.model_manager as mm

    class _SlowDet:
        model_id = "slow"
        runtime = "cpu"

        def __init__(self, *args, **kwargs) -> None:
            time.sleep(0.2)

        def detect(self, frame, frame_id: int = 0):  # pragma: no cover
            return []

    monkeypatch.setattr(mm, "MockPersonDetector", _SlowDet)
    monkeypatch.setattr(mm, "ONNXDetectorProvider", _SlowDet)
    mm._GLOBAL_DETECTOR_HANDLE = None
    try:
        n_threads = 8
        barrier = threading.Barrier(n_threads)
        handles: list = []
        errors: list = []

        def grab() -> None:
            try:
                barrier.wait(timeout=10.0)
                handles.append(mm.get_shared_detector_handle())
            except Exception as exc:  # pragma: no cover
                errors.append(exc)

        threads = [threading.Thread(target=grab) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30.0)
        assert not errors
        assert len(handles) == n_threads
        assert len({id(h) for h in handles}) == 1
    finally:
        mm._GLOBAL_DETECTOR_HANDLE = None


def test_ocr_predict_lock_exists() -> None:
    """OCRReader must serialize native Paddle predict calls (instance lock)."""
    import inspect

    from ibvap.core.anpr import OCRReader

    assert hasattr(OCRReader(), "_predict_lock")
    src = inspect.getsource(OCRReader.recognize)
    assert "_predict_lock" in src


def test_epoch_resync_purges_worker_ocr_state() -> None:
    """Epoch bump helper must reset pipeline latch AND drop old-epoch OCR state."""
    from ibvap.services.stream_worker import _resync_epoch_if_bumped

    pipe = MiniPipeline(
        camera_id="cam-epoch-purge",
        stream_epoch=1,
        face_detector=None,
        enable_face=False,
    )
    pipe.alerted_tracks.add(7)
    stale = Future()  # unfinished: belongs to the old epoch
    track_plates = {7: "KA01AB1234"}
    ocr_last_submitted = {7: time.monotonic()}
    pending_ocr: list = [stale]
    plate_cache: dict = {
        "detections": [{"text": "KA01AB1234"}],
        "plates": [{"text": "KA01AB1234"}],
        "at_mono": 1234.0,
    }

    bumped = _resync_epoch_if_bumped(
        2,
        pipe,
        track_plates=track_plates,
        ocr_last_submitted=ocr_last_submitted,
        pending_ocr=pending_ocr,
        plate_cache=plate_cache,
    )

    assert bumped is True
    assert pipe.stream_epoch == 2
    assert pipe.alerted_tracks == set()
    assert track_plates == {}
    assert ocr_last_submitted == {}
    assert pending_ocr == []
    assert stale.cancelled()
    assert plate_cache == {"detections": [], "plates": [], "at_mono": 0.0}

    assert (
        _resync_epoch_if_bumped(
            2,
            pipe,
            track_plates=track_plates,
            ocr_last_submitted=ocr_last_submitted,
            pending_ocr=pending_ocr,
            plate_cache=plate_cache,
        )
        is False
    )


def test_epoch_resync_polled_before_drain_and_infer() -> None:
    """Epoch poll must run BEFORE OCR-drain/process_frame/submit in analyze().

    A late poll lets a bumped first new-epoch frame run with stale latches and
    lets old-epoch OCR votes apply before being discarded. Exactly one call
    site, ordered before the drain and the inference call.
    """
    import inspect
    import re

    from ibvap.services import stream_worker as sw

    src = inspect.getsource(sw._camera_worker)
    calls = [m.start() for m in re.finditer(r"_resync_epoch_if_bumped\(", src)]
    # Exactly one call site inside _camera_worker (the def lives at module level).
    assert len(calls) == 1
    call_pos = calls[0]
    assert call_pos < src.index("pipeline.process_frame(current)")
    assert call_pos < src.index("_drain_ocr_futures(")


def test_wedged_ocr_unblocks_and_counts() -> None:
    """A never-completing OCR future past max age must reap: cancel+count+drop."""
    from ibvap.services.stream_worker import _drain_ocr_futures

    wedged: Future = Future()  # never completes: wedged worker
    wedged._ocr_submitted_mono = time.monotonic() - 10.0  # type: ignore[attr-defined]
    ok: Future = Future()
    ok.set_result(([{"text": "KA01AB1234"}], {"text": "KA01AB1234", "confidence": 0.9, "track_id": 1}))
    pending: list = [wedged, ok]

    t0 = time.monotonic()
    results, timeouts = _drain_ocr_futures(pending)
    assert time.monotonic() - t0 < 5.0, "drain must not block on wedged futures"

    assert timeouts == 1
    assert wedged.cancelled()
    assert pending == [], "reaped+resolved futures leave the queue so the len<3 cap unblocks"
    assert len(pending) < 3
    assert len(results) == 1
    assert results[0][1]["text"] == "KA01AB1234"


def test_young_pending_retained_not_blocking() -> None:
    """Young unfinished futures are retained (not reaped), drain never blocks."""
    from ibvap.services.stream_worker import _drain_ocr_futures

    young: Future = Future()  # unfinished, fresh stamp
    young._ocr_submitted_mono = time.monotonic()  # type: ignore[attr-defined]
    pending: list = [young]

    t0 = time.monotonic()
    results, timeouts = _drain_ocr_futures(pending)
    elapsed = time.monotonic() - t0

    assert results == []
    assert timeouts == 0
    assert pending == [young], "young-pending must be retained for a later iteration"
    assert elapsed < 1.0, "hot-path drain must be non-blocking"


def test_evidence_offload_eventual_files(tmp_path: Path) -> None:
    """Offload storm: fast submits; every file either lands or is drop-counted."""
    from ibvap.core import evidence as ev

    dropped_before = ev.get_evidence_dropped()
    submitted: list[tuple[str | None, str | None]] = []
    t0 = time.monotonic()
    for i in range(40):
        frame = np.full((100, 100, 3), 128, dtype=np.uint8)
        snap, crop = ev.submit_frame_evidence(
            f"storm-{i:03d}",
            frame,
            bbox_norm=[0.2, 0.2, 0.8, 0.8],
            output_dir=tmp_path,
        )
        assert snap is not None
        submitted.append((snap, crop))
    assert time.monotonic() - t0 < 5.0, "offload submit must stay off the hot path"

    # Drain: stop polling once every still-missing file is accounted for as a
    # bounded-queue drop (drop-oldest under backpressure is the design, not a bug).
    deadline = time.monotonic() + 15.0
    while True:
        missing = [s for s, _ in submitted if not Path(str(s)).is_file()]
        dropped = ev.get_evidence_dropped() - dropped_before
        if len(missing) <= dropped or time.monotonic() >= deadline:
            break
        time.sleep(0.05)
    dropped = ev.get_evidence_dropped() - dropped_before
    # Note: a drop-counted future already RUNNING cannot be cancelled and still
    # lands its file, so missing <= dropped (not ==) is the exact invariant.
    assert len(missing) <= dropped, f"{len(missing)} missing but only {dropped} drop-counted"
    assert len(submitted) - len(missing) > 0, "worker must land files, not drop everything"
