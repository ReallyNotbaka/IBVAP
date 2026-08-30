"""Evidence - ring buffer + manifest. Phase 5, spec 17."""

from __future__ import annotations

import hashlib
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path


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
        # snapshot: last keyframe-ish packet
        snap = self._packets[-1][1] if self._packets else None
        # clip: all packets in window
        now = time.time()
        clip_parts = [d for ts, d, _ in self._packets if (now - ts) <= (pre_seconds + post_seconds)]
        clip = b"".join(clip_parts) if clip_parts else None
        return snap, clip

    def manifest_for(self, event_id: str, snap: bytes | None, clip: bytes | None) -> EvidenceManifest:
        def sha(b: bytes | None) -> str | None:
            return hashlib.sha256(b).hexdigest() if b else None

        # In prod, write to FS/S3 and compute paths
        snap_path = f"data/evidence/{event_id}_snap.jpg" if snap else None
        clip_path = f"data/evidence/{event_id}_clip.mp4" if clip else None
        if snap and snap_path:
            Path(snap_path).parent.mkdir(parents=True, exist_ok=True)
            Path(snap_path).write_bytes(snap)
        if clip and clip_path:
            Path(clip_path).write_bytes(clip[:1024])  # truncated for test
        return EvidenceManifest(
            event_id=event_id,
            snapshot_path=snap_path,
            clip_path=clip_path,
            snapshot_sha256=sha(snap),
            clip_sha256=sha(clip),
            created_at=time.time(),
        )
