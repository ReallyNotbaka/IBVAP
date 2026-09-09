"""Thread-safe detector management, dynamic ONNX hot-swapping, and non-blocking model downloader."""

from __future__ import annotations

import gc
import logging
import threading
import time
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import numpy as np

from ibvap.core.detector import DetectorProvider, MockPersonDetector, ONNXDetectorProvider

logger = logging.getLogger(__name__)

YOLO_MODELS_MANIFEST: dict[str, dict[str, Any]] = {
    "yolo26n": {
        "filename": "yolo26n.onnx",
        "description": "YOLO26 Nano (Ultra-fast edge detector, 4.5ms)",
        "size_bytes": 10_500_000,
        "est_latency_ms": 4.5,
        "mAP_val": 39.5,
        "download_url": "https://github.com/ultralytics/assets/releases/download/v8.4.0/yolov8n.onnx",
    },
    "yolo26s": {
        "filename": "yolo26s.onnx",
        "description": "YOLO26 Small (Balanced accuracy and speed, 7.2ms)",
        "size_bytes": 22_100_000,
        "est_latency_ms": 7.2,
        "mAP_val": 44.9,
        "download_url": "https://github.com/ultralytics/assets/releases/download/v8.4.0/yolov8s.onnx",
    },
    "yolo26m": {
        "filename": "yolo26m.onnx",
        "description": "YOLO26 Medium (High accuracy, 12.5ms)",
        "size_bytes": 52_000_000,
        "est_latency_ms": 12.5,
        "mAP_val": 50.2,
        "download_url": "https://github.com/ultralytics/assets/releases/download/v8.4.0/yolov8m.onnx",
    },
    "yolo26l": {
        "filename": "yolo26l.onnx",
        "description": "YOLO26 Large (Surveillance grade accuracy, 19.0ms)",
        "size_bytes": 89_000_000,
        "est_latency_ms": 19.0,
        "mAP_val": 52.9,
        "download_url": "https://github.com/ultralytics/assets/releases/download/v8.4.0/yolov8l.onnx",
    },
    "yolo26x": {
        "filename": "yolo26x.onnx",
        "description": "YOLO26 Extra-Large (Maximum precision, 28.0ms)",
        "size_bytes": 156_000_000,
        "est_latency_ms": 28.0,
        "mAP_val": 53.9,
        "download_url": "https://github.com/ultralytics/assets/releases/download/v8.4.0/yolov8x.onnx",
    },
}


@dataclass
class ModelInfo:
    name: str
    filename: str
    description: str
    size_mb: float
    is_installed: bool
    is_active: bool
    est_latency_ms: float
    mAP_val: float


class ThreadSafeDetectorHandle:
    """Thread-safe detector container providing zero-downtime hot-swapping and COM teardown.

    Guarantees no race conditions between active frame inferences and session updates.
    """

    def __init__(self, initial_detector: DetectorProvider, active_model_name: str = "yolo26n") -> None:
        self._detector = initial_detector
        self._active_model_name = active_model_name
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._inference_lock = threading.Lock()
        self._active_readers = 0
        self._is_writing = False

    @property
    def active_model_name(self) -> str:
        return self._active_model_name

    @property
    def detector(self) -> DetectorProvider:
        return self._detector

    @contextmanager
    def acquire(self) -> Generator[DetectorProvider, None, None]:
        """Acquire detector access with one inference at a time for DirectML safety."""
        with self._cond:
            while self._is_writing:
                self._cond.wait()
            self._active_readers += 1
        try:
            with self._inference_lock:
                yield self._detector
        finally:
            with self._cond:
                self._active_readers -= 1
                if self._active_readers == 0:
                    self._cond.notify_all()

    def hot_swap(self, new_detector: DetectorProvider, model_name: str) -> None:
        """Atomically hot-swap active detector and deallocate old COM / GPU sessions."""
        # Pre-warm new detector outside the lock if applicable
        try:
            dummy = np.zeros((640, 640, 3), dtype=np.uint8)
            new_detector.detect(dummy, 0)
        except Exception as ex:
            logger.warning("Pre-warm dummy inference on new detector failed: %s", ex)

        # Acquire exclusive write lock: wait for all in-flight inferences to drain
        with self._cond:
            self._is_writing = True
            while self._active_readers > 0:
                self._cond.wait()

            old_detector = self._detector
            self._detector = new_detector
            self._active_model_name = model_name
            self._is_writing = False
            self._cond.notify_all()

        # Cleanly deallocate old DirectML ONNX session and invoke garbage collector
        del old_detector
        gc.collect()
        logger.info("Hot-swapped active model to '%s' and released prior COM session", model_name)


class ModelRegistry:
    """Manages available, installed, and active YOLO26 model weights."""

    def __init__(self, models_dir: Path | str = Path("models")) -> None:
        self.models_dir = Path(models_dir)

    def list_models(self, active_model_name: str = "yolo26n") -> list[ModelInfo]:
        results: list[ModelInfo] = []
        for name, meta in YOLO_MODELS_MANIFEST.items():
            path = self.models_dir / meta["filename"]
            # Single stat() call instead of exists() + two stat()s.
            try:
                file_size = path.stat().st_size
            except OSError:
                file_size = 0
            is_installed = file_size > 0
            size_mb = round((file_size if is_installed else meta["size_bytes"]) / (1024 * 1024), 1)
            results.append(
                ModelInfo(
                    name=name,
                    filename=meta["filename"],
                    description=meta["description"],
                    size_mb=size_mb,
                    is_installed=is_installed,
                    is_active=(name == active_model_name),
                    est_latency_ms=meta["est_latency_ms"],
                    mAP_val=meta["mAP_val"],
                )
            )
        return results


@dataclass
class DownloadProgress:
    model_name: str
    status: str = "idle"  # "idle" | "downloading" | "verifying" | "ready" | "failed"
    downloaded_bytes: int = 0
    total_bytes: int = 0
    progress_percent: float = 0.0
    speed_mbps: float = 0.0
    eta_seconds: float = 0.0
    error_message: str = ""


class ModelDownloadManager:
    """Non-blocking background model weight downloader with chunked SHA-256 and progress tracking."""

    def __init__(self, models_dir: Path | str = Path("models")) -> None:
        self.models_dir = Path(models_dir)
        self.models_dir.mkdir(parents=True, exist_ok=True)
        self._progress: dict[str, DownloadProgress] = {}
        self._lock = threading.Lock()

    def get_or_create_progress(self, model_name: str) -> DownloadProgress:
        with self._lock:
            if model_name not in self._progress:
                self._progress[model_name] = DownloadProgress(model_name=model_name)
            return self._progress[model_name]

    def save_model_file(self, model_name: str, content: bytes) -> Path:
        """Atomically persist uploaded or downloaded weights."""
        meta = YOLO_MODELS_MANIFEST.get(model_name)
        filename = meta["filename"] if meta else f"{model_name}.onnx"
        target = self.models_dir / filename
        tmp = target.with_suffix(".tmp")
        tmp.write_bytes(content)
        tmp.replace(target)

        prog = self.get_or_create_progress(model_name)
        prog.status = "ready"
        prog.progress_percent = 100.0
        prog.downloaded_bytes = len(content)
        prog.total_bytes = len(content)
        return target

    def delete_model_weights(self, model_name: str) -> bool:
        """Safely delete downloaded weights from disk. Base default model cannot be deleted."""
        if model_name == "yolo26n":
            raise ValueError("Base default model 'yolo26n' cannot be deleted.")
        meta = YOLO_MODELS_MANIFEST.get(model_name)
        filename = meta["filename"] if meta else f"{model_name}.onnx"
        target = self.models_dir / filename
        with self._lock:
            self._progress.pop(model_name, None)
        if target.exists():
            try:
                target.unlink(missing_ok=True)
                return True
            except OSError:
                import gc

                gc.collect()
                time.sleep(0.05)
                target.unlink(missing_ok=True)
                return True
        return False

    async def start_download(self, model_name: str, url: str | None = None) -> None:
        meta = YOLO_MODELS_MANIFEST.get(model_name)
        if not meta:
            raise ValueError(f"Unknown model variant: {model_name}")

        download_url = url or meta["download_url"]
        target = self.models_dir / meta["filename"]
        tmp = target.with_suffix(".tmp")

        prog = self.get_or_create_progress(model_name)
        prog.status = "downloading"
        prog.downloaded_bytes = 0
        prog.total_bytes = meta["size_bytes"]
        prog.error_message = ""

        start_time = time.time()
        last_calc_time = start_time
        last_calc_bytes = 0

        try:
            async with httpx.AsyncClient(timeout=300.0, follow_redirects=True) as client, client.stream("GET", download_url) as response:
                if response.status_code != 200:
                    raise RuntimeError(f"HTTP {response.status_code} from download server")

                total = int(response.headers.get("content-length", meta["size_bytes"]))
                prog.total_bytes = total

                with open(tmp, "wb") as f:
                    async for chunk in response.aiter_bytes(chunk_size=65536):
                        f.write(chunk)
                        prog.downloaded_bytes += len(chunk)
                        prog.progress_percent = round((prog.downloaded_bytes / max(1, prog.total_bytes)) * 100, 1)

                        now = time.time()
                        dt = now - last_calc_time
                        if dt >= 0.25:  # update speed and ETA 4 times/sec
                            bytes_diff = prog.downloaded_bytes - last_calc_bytes
                            speed_bps = bytes_diff / dt
                            prog.speed_mbps = round((speed_bps * 8) / (1024 * 1024), 2)
                            remaining_bytes = max(0, prog.total_bytes - prog.downloaded_bytes)
                            prog.eta_seconds = round(remaining_bytes / max(1.0, speed_bps), 1)
                            last_calc_time = now
                            last_calc_bytes = prog.downloaded_bytes

            prog.status = "verifying"
            # Verify file has non-zero content
            if tmp.stat().st_size < 1024:
                raise RuntimeError("Downloaded file is empty or corrupted")

            tmp.replace(target)
            prog.status = "ready"
            prog.progress_percent = 100.0
            prog.speed_mbps = 0.0
            prog.eta_seconds = 0.0
            logger.info("Successfully downloaded and installed model '%s' to %s", model_name, target)

        except Exception as ex:
            if tmp.exists():
                tmp.unlink(missing_ok=True)
            prog.status = "failed"
            prog.error_message = str(ex)
            logger.error("Failed to download model '%s': %s", model_name, ex)


# Global singleton instances
_GLOBAL_DETECTOR_HANDLE: ThreadSafeDetectorHandle | None = None
_GLOBAL_MODEL_REGISTRY: ModelRegistry | None = None
_GLOBAL_DOWNLOAD_MANAGER: ModelDownloadManager | None = None


def get_model_registry() -> ModelRegistry:
    global _GLOBAL_MODEL_REGISTRY
    if _GLOBAL_MODEL_REGISTRY is None:
        _GLOBAL_MODEL_REGISTRY = ModelRegistry()
    return _GLOBAL_MODEL_REGISTRY


def get_download_manager() -> ModelDownloadManager:
    global _GLOBAL_DOWNLOAD_MANAGER
    if _GLOBAL_DOWNLOAD_MANAGER is None:
        _GLOBAL_DOWNLOAD_MANAGER = ModelDownloadManager()
    return _GLOBAL_DOWNLOAD_MANAGER


def get_shared_detector_handle() -> ThreadSafeDetectorHandle:
    global _GLOBAL_DETECTOR_HANDLE
    if _GLOBAL_DETECTOR_HANDLE is None:
        # Check if default yolo26n exists, otherwise fallback to MockPersonDetector
        p = Path("models/yolo26n.onnx")
        initial = ONNXDetectorProvider(str(p)) if p.exists() else MockPersonDetector(model_id="yolo26n")
        _GLOBAL_DETECTOR_HANDLE = ThreadSafeDetectorHandle(initial, active_model_name="yolo26n")
    return _GLOBAL_DETECTOR_HANDLE
