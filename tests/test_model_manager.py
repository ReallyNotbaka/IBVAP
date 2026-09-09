"""Unit and concurrency stress tests for ModelManager, ThreadSafeDetectorHandle, and Downloader."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import numpy as np
import pytest

from ibvap.core.detector import MockPersonDetector
from ibvap.core.model_manager import (
    YOLO_MODELS_MANIFEST,
    ModelDownloadManager,
    ModelRegistry,
    ThreadSafeDetectorHandle,
)


class TestModelRegistry:
    def test_manifest_contains_all_yolo26_variants(self) -> None:
        variants = {"yolo26n", "yolo26s", "yolo26m", "yolo26l", "yolo26x"}
        assert variants.issubset(set(YOLO_MODELS_MANIFEST.keys()))

    def test_registry_lists_installed_status(self, tmp_path: Path) -> None:
        # Create a fake installed model file in tmp_path
        (tmp_path / "yolo26n.onnx").write_bytes(b"fake-onnx-content")
        registry = ModelRegistry(models_dir=tmp_path)

        models = registry.list_models()
        assert len(models) == 5
        n_mod = next(m for m in models if m.name == "yolo26n")
        assert n_mod.is_installed is True

        x_mod = next(m for m in models if m.name == "yolo26x")
        assert x_mod.is_installed is False


class TestThreadSafeDetectorHandle:
    def test_acquire_and_detect(self) -> None:
        mock1 = MockPersonDetector(model_id="mock-1")
        handle = ThreadSafeDetectorHandle(initial_detector=mock1, active_model_name="mock-1")

        with handle.acquire() as det:
            assert det.model_id == "mock-1"
            res = det.detect(np.zeros((100, 100, 3), dtype=np.uint8), 0)
            assert isinstance(res, list)

    def test_concurrent_swapping_stress(self) -> None:
        """Stress test: 4 worker threads running continuous detections while 1 thread swaps detectors."""
        mock1 = MockPersonDetector(model_id="mock-1")
        handle = ThreadSafeDetectorHandle(initial_detector=mock1, active_model_name="mock-1")

        stop_event = threading.Event()
        inference_count = [0]
        errors = []

        def worker(w_id: int):
            while not stop_event.is_set():
                try:
                    with handle.acquire() as det:
                        assert det is not None
                        _ = det.detect(np.zeros((64, 64, 3), dtype=np.uint8), 0)
                        inference_count[0] += 1
                    time.sleep(0.001)
                except Exception as ex:
                    errors.append(ex)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()

        # Perform multiple hot-swaps under load
        time.sleep(0.05)
        for i in range(5):
            new_det = MockPersonDetector(model_id=f"swap-{i}")
            handle.hot_swap(new_det, model_name=f"swap-{i}")
            assert handle.active_model_name == f"swap-{i}"
            time.sleep(0.02)

        stop_event.set()
        for t in threads:
            t.join(timeout=2.0)

        assert len(errors) == 0
        assert inference_count[0] > 50


class TestModelDownloadManager:
    @pytest.mark.asyncio
    async def test_download_progress_tracking(self, tmp_path: Path) -> None:
        mgr = ModelDownloadManager(models_dir=tmp_path)

        # Test simulated download of a chunked stream
        content = b"ONNX-WEIGHTS-TEST-DATA" * 1024
        target_file = tmp_path / "test_model.onnx"

        progress = mgr.get_or_create_progress("yolo26s")
        assert progress.status == "idle"

        # Test file writing directly through manager's safe atomic write
        mgr.save_model_file("yolo26s", content)
        assert target_file.exists() or (tmp_path / "yolo26s.onnx").exists()
        assert mgr.get_or_create_progress("yolo26s").status == "ready"


def test_warmup_shared_detector_initializes_handle() -> None:
    """App boot warmup must leave the shared YOLO handle ready (no per-camera load)."""
    import ibvap.core.model_manager as mm

    mm._GLOBAL_DETECTOR_HANDLE = None
    try:
        handle = mm.warmup_shared_detector()
        assert handle is not None
        with handle.acquire() as det:
            dets = det.detect(np.zeros((64, 64, 3), dtype=np.uint8), 0)
            assert isinstance(dets, list)
    finally:
        mm._GLOBAL_DETECTOR_HANDLE = None
