"""ANPR worker sharing (A1), cache freshness (A2), vehicle match (A3), Paddle retry (A4)."""

from __future__ import annotations

import inspect

import pytest


def test_ocr_submit_decouples_worker_list() -> None:
    """The list handed to the OCR executor must be a copy.

    recognize_vehicle appends/fills the submitted list on the worker thread
    while the analyze thread extends published observations from the same
    object -> torn reads and post-hoc mutation. Deepcopy at submit gives
    each thread its own object (results still flow back via the future).
    """
    from ibvap.api.routes import cameras as C

    src = inspect.getsource(C._camera_worker)
    assert "copy.deepcopy(vehicle_plate_detections)" in src


def test_stale_plate_cache_not_published() -> None:
    """Cached OCR boxes publish only while fresh AND a vehicle is still there."""
    from ibvap.api.routes.cameras import _select_plate_detections

    fresh: list[dict] = []
    cached = [{"bbox_norm": (0.1, 0.1, 0.3, 0.3)}]
    # Ghost: batch completed 2s ago, vehicle long gone.
    assert _select_plate_detections(fresh, cached, 0.0, 2.0, []) == []
    # Fresh batch but no current vehicle overlapping it.
    assert _select_plate_detections(fresh, cached, 0.0, 0.5, []) == []
    # Fresh batch + vehicle still present -> reuse.
    assert _select_plate_detections(fresh, cached, 0.0, 0.5, [(0.1, 0.1, 0.3, 0.3)]) == cached


def test_vehicle_association_prefers_iou() -> None:
    """Max-IoU (not raw area) picks the owning track; order must not decide ties."""
    from ibvap.api.routes.cameras import _match_vehicle_track
    from ibvap.core.tracker import Track

    own = Track(track_id=1, class_name="car", class_id=2, bbox_norm=(0.10, 0.10, 0.20, 0.20), confidence=0.9)
    bus = Track(track_id=2, class_name="bus", class_id=5, bbox_norm=(0.0, 0.0, 0.5, 0.5), confidence=0.9)
    # Bus first: raw areas tie at 0.01 and first-wins would pick the bus.
    assert _match_vehicle_track((0.10, 0.10, 0.20, 0.20), [bus, own]) == 1
    assert _match_vehicle_track((0.9, 0.9, 0.95, 0.95), [bus, own]) == 0


def test_paddle_transient_failure_recovers(monkeypatch: pytest.MonkeyPatch) -> None:
    """A transient Paddle failure must not permanently kill OCR (retry, don't latch)."""
    import sys
    import types

    import numpy as np

    from ibvap.core.anpr import OCRReader

    calls = {"n": 0}

    class Flaky:
        def predict(self, input: object) -> list:
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("transient gpu hiccup")
            return []

    fake_mod = types.ModuleType("paddleocr")
    fake_mod.PaddleOCR = lambda **kw: Flaky()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "paddleocr", fake_mod)
    r = OCRReader(ocr_engine=None, device="cpu")
    rng = np.random.default_rng(3)
    crop = rng.integers(0, 255, (40, 120, 3), dtype=np.uint8)
    assert r.recognize(crop) == []
    r._paddle_last_error_at = 0.0  # force retry window elapsed
    assert r.recognize(crop) == []
    assert calls["n"] == 2


def test_paddle_device_defaults_to_cpu(monkeypatch: pytest.MonkeyPatch) -> None:
    from ibvap.core.anpr import OCRReader

    monkeypatch.delenv("IBVAP_ANPR_DEVICE", raising=False)
    assert OCRReader(ocr_engine=lambda c: []).device == "cpu"
