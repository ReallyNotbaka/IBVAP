"""Evidence - ring buffer + manifest. Phase 5, spec 17."""

from __future__ import annotations

import atexit
import contextlib
import hashlib
import re
import threading
import time
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


@dataclass(frozen=True)
class EvidenceManifest:
    event_id: str
    snapshot_path: str | None
    clip_path: str | None
    snapshot_sha256: str | None
    clip_sha256: str | None
    created_at: float
    encryption: str = "none"  # envelope in Phase 5 prod
    retention_days: int = 90


class PacketRingBuffer:
    """Time+bounds encoded-packet ring buffer."""

    def __init__(self, max_seconds: float = 30.0, max_bytes: int = 200 * 1024 * 1024) -> None:
        self.max_seconds = max_seconds
        self.max_bytes = max_bytes
        self._packets: deque[tuple[float, bytes, bool]] = deque()  # ts, data, is_keyframe
        self._bytes = 0
        self._dirs_ensured: set[str] = set()

    def push(self, data: bytes, is_keyframe: bool) -> None:
        now = time.time()
        self._packets.append((now, data, is_keyframe))
        self._bytes += len(data)
        # evict old
        while self._packets and (now - self._packets[0][0] > self.max_seconds or self._bytes > self.max_bytes):
            _, d, _ = self._packets.popleft()
            self._bytes -= len(d)

    def snapshot_clip(self, pre_seconds: float = 2.0, post_seconds: float = 2.0) -> tuple[bytes | None, bytes | None]:
        """Return (snapshot_jpeg, clip_bytes) placeholder - caller would remux."""
        if not self._packets:
            return None, None
        # snapshot: last keyframe-ish packet (no copy — reference existing bytes)
        snap = self._packets[-1][1] if self._packets else None
        # clip: packets in window, capped to avoid oversized join on long buffers.
        # Cap at 8MB: beyond that callers only hash/truncate anyway.
        now = time.time()
        window = pre_seconds + post_seconds
        clip_parts: list[bytes] = []
        clip_bytes = 0
        for ts, d, _ in self._packets:
            if (now - ts) > window:
                continue
            # Stop accumulating once cap reached (packets are time-ordered).
            if clip_bytes + len(d) > 8 * 1024 * 1024 and clip_parts:
                break
            clip_parts.append(d)
            clip_bytes += len(d)
        clip = b"".join(clip_parts) if clip_parts else None
        return snap, clip

    def manifest_for(self, event_id: str, snap: bytes | None, clip: bytes | None) -> EvidenceManifest:
        def sha(b: bytes | None) -> str | None:
            if not b:
                return None
            # Incremental hash avoids holding a second full copy.
            h = hashlib.sha256()
            mv = memoryview(b)
            for off in range(0, len(mv), 1024 * 1024):
                h.update(mv[off : off + 1024 * 1024])
            return h.hexdigest()

        # In prod, write to FS/S3 and compute paths
        snap_path = f"data/evidence/{event_id}_snap.jpg" if snap else None
        clip_path = f"data/evidence/{event_id}_clip.mp4" if clip else None
        if snap and snap_path:
            p_snap = Path(snap_path)
            p_snap.parent.mkdir(parents=True, exist_ok=True)
            p_snap.write_bytes(snap)
        if clip and clip_path:
            p_clip = Path(clip_path)
            p_clip.parent.mkdir(parents=True, exist_ok=True)
            p_clip.write_bytes(clip)
        return EvidenceManifest(
            event_id=event_id,
            snapshot_path=snap_path,
            clip_path=clip_path,
            snapshot_sha256=sha(snap),
            clip_sha256=sha(clip),
            created_at=time.time(),
        )


MAX_EVIDENCE_FILES = 1000
_EVIDENCE_LOCK = threading.Lock()

# Task 1 P0: allowlist for event ids (used by evidence routes; Task 5 reuses).
_EVID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def save_frame_evidence(
    event_id: str,
    frame: np.ndarray,
    bbox_norm: tuple[float, float, float, float] | list[float] | None = None,
    output_dir: str | Path = "data/evidence",
) -> tuple[str | None, str | None]:
    """Save full-frame JPEG snapshot and cropped suspect/vehicle JPEG evidence.

    Returns (snapshot_path, crop_path) as relative paths, or (None, None) if frame is invalid.
    """
    snap_path, crop_path = _write_frame_evidence(event_id, frame, bbox_norm, output_dir)

    # Evict oldest files if exceeding threshold
    out_dir = Path(output_dir)
    try:
        with _EVIDENCE_LOCK:
            _evict_oldest_locked(out_dir)
    except Exception:
        pass

    return snap_path, crop_path


def _write_frame_evidence(
    event_id: str,
    frame: np.ndarray,
    bbox_norm: tuple[float, float, float, float] | list[float] | None,
    output_dir: str | Path,
) -> tuple[str | None, str | None]:
    """Encode + write snapshot/crop JPEGs. No eviction (caller amortizes)."""
    if frame is None or getattr(frame, "size", 0) == 0 or len(getattr(frame, "shape", ())) < 2:
        return None, None

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    snap_path = out_dir / f"{event_id}_snap.jpg"
    crop_path = out_dir / f"{event_id}_crop.jpg"

    h, w = frame.shape[:2]
    # Encode full frame snapshot
    try:
        success, snap_buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 82])
        if success:
            snap_path.write_bytes(snap_buf.tobytes())
        else:
            return None, None
    except Exception:
        return None, None

    has_crop = False
    if bbox_norm and len(bbox_norm) == 4:
        try:
            x1, y1, x2, y2 = bbox_norm
            # Add 15% contextual padding
            bw = x2 - x1
            bh = y2 - y1
            pad_x = bw * 0.15
            pad_y = bh * 0.15

            px1 = max(0, int((x1 - pad_x) * w))
            py1 = max(0, int((y1 - pad_y) * h))
            px2 = min(w, int((x2 + pad_x) * w))
            py2 = min(h, int((y2 + pad_y) * h))

            if px2 - px1 >= 8 and py2 - py1 >= 8:
                crop_img = frame[py1:py2, px1:px2]
                c_success, crop_buf = cv2.imencode(".jpg", crop_img, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
                if c_success:
                    crop_path.write_bytes(crop_buf.tobytes())
                    has_crop = True
        except Exception:
            has_crop = False

    return str(snap_path), (str(crop_path) if has_crop else None)


def _evict_oldest_locked(out_dir: Path) -> None:
    """FIFO-evict oldest JPEGs beyond MAX_EVIDENCE_FILES. Caller holds _EVIDENCE_LOCK."""
    files = sorted(out_dir.glob("*.jpg"), key=lambda p: p.stat().st_mtime)
    if len(files) > MAX_EVIDENCE_FILES:
        for old_f in files[: len(files) - MAX_EVIDENCE_FILES]:
            with contextlib.suppress(Exception):
                old_f.unlink()


# --- Task 3: bounded background offload -------------------------------------
# Single-worker executor keeps encode/write off the inference hot path. The
# pending queue is bounded (drop-oldest + counter) so an alert storm degrades
# to dropped evidence files, never unbounded memory or hot-path stalls.

_EVIDENCE_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="evidence-offload")
# Non-daemon worker would hang interpreter exit (idle queue-get never returns).
atexit.register(lambda: _EVIDENCE_EXECUTOR.shutdown(wait=True, cancel_futures=True))
_EVIDENCE_MAX_PENDING = 32
_EVIDENCE_EVICT_EVERY_N = 16
_EVIDENCE_QUEUE_LOCK = threading.Lock()
_EVIDENCE_PENDING: deque[Future[None]] = deque()
_evidence_dropped = 0
_evidence_saves_since_evict = 0  # worker-thread only


def get_evidence_dropped() -> int:
    """Number of offloaded evidence saves dropped under backpressure."""
    with _EVIDENCE_QUEUE_LOCK:
        return _evidence_dropped


def submit_frame_evidence(
    event_id: str,
    frame: np.ndarray,
    bbox_norm: tuple[float, float, float, float] | list[float] | None = None,
    output_dir: str | Path = "data/evidence",
) -> tuple[str | None, str | None]:
    """Enqueue an evidence save; returns predicted paths immediately.

    Optimistic URLs: callers may publish ``/api/v1/evidence/{id}/...`` before
    the worker writes the files ms later (tiny 404 window). Returns
    (None, None) for invalid frames. Copy-on-submit: the worker encodes a
    private copy so caller buffer reuse cannot tear the JPEG.
    """
    if frame is None or getattr(frame, "size", 0) == 0 or len(getattr(frame, "shape", ())) < 2:
        return None, None
    out_dir = Path(output_dir)
    snap_rel = str(out_dir / f"{event_id}_snap.jpg")
    crop_rel = str(out_dir / f"{event_id}_crop.jpg") if (bbox_norm and len(bbox_norm) == 4) else None
    try:
        payload = frame.copy()
    except Exception:
        return None, None
    try:
        future: Future[None] = _EVIDENCE_EXECUTOR.submit(
            _evidence_worker_job, event_id, payload, bbox_norm, str(out_dir)
        )
    except RuntimeError:
        # Executor shutting down (interpreter exit racing a late alert):
        # best-effort synchronous save instead of raising on the hot path.
        with contextlib.suppress(Exception):
            _write_frame_evidence(event_id, payload, bbox_norm, out_dir)
        return snap_rel, crop_rel
    global _evidence_dropped
    overflow: Future[None] | None = None
    with _EVIDENCE_QUEUE_LOCK:
        if len(_EVIDENCE_PENDING) >= _EVIDENCE_MAX_PENDING:
            overflow = _EVIDENCE_PENDING.popleft()
            _evidence_dropped += 1
        _EVIDENCE_PENDING.append(future)
    # Cancel OUTSIDE the queue lock: Future.cancel() synchronously invokes
    # done-callbacks (_evidence_done) in the calling thread, which take the
    # same lock — cancelling while holding it deadlocks against the worker's
    # set_result path (faulthandler-verified). A completion racing the cancel
    # is harmless (cancel returns False; remove tolerates ValueError).
    if overflow is not None and not overflow.done():
        overflow.cancel()
    future.add_done_callback(_evidence_done)
    return snap_rel, crop_rel


def _evidence_done(future: Future[None]) -> None:
    with _EVIDENCE_QUEUE_LOCK, contextlib.suppress(ValueError):
        _EVIDENCE_PENDING.remove(future)


def _evidence_worker_job(
    event_id: str,
    frame: np.ndarray,
    bbox_norm: tuple[float, float, float, float] | list[float] | None,
    output_dir: str,
) -> None:
    """Background encode+write with amortized FIFO eviction (every N saves)."""
    global _evidence_saves_since_evict
    with contextlib.suppress(Exception):
        _write_frame_evidence(event_id, frame, bbox_norm, Path(output_dir))
    _evidence_saves_since_evict += 1
    if _evidence_saves_since_evict >= _EVIDENCE_EVICT_EVERY_N:
        _evidence_saves_since_evict = 0
        try:
            with _EVIDENCE_LOCK:
                _evict_oldest_locked(Path(output_dir))
        except Exception:
            pass


def validate_event_id(event_id: str) -> str:
    """Return event_id if safe, else raise ValueError (route maps to 422)."""
    if not event_id or not _EVID_RE.match(event_id):
        raise ValueError(f"Invalid event_id: {event_id!r}")
    return event_id


def get_evidence_file(event_id: str, kind: str = "snapshot", base_dir: str | Path = "data/evidence") -> Path | None:
    """Retrieve Path to evidence JPEG (snapshot or crop) if it exists on disk."""
    # Task 1 P0: reject traversal ids before touching the filesystem.
    try:
        validate_event_id(event_id)
    except ValueError:
        return None
    out_dir = Path(base_dir)
    filename = f"{event_id}_crop.jpg" if kind == "crop" else f"{event_id}_snap.jpg"
    try:
        resolved_base = out_dir.resolve()
        target = (resolved_base / filename).resolve()
    except Exception:
        return None
    # Task 1 P0: resolved path must stay inside the evidence dir.
    if not target.is_relative_to(resolved_base):
        return None
    return target if target.is_file() else None
