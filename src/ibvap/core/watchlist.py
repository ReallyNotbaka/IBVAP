"""Biometric Watchlist Store with Exemplar Gallery Matrix and Hyperspherical Math.

Implements multi-vector gallery matching on the SFace embedding manifold S^127:
- Replaces naive vector averaging with an Exemplar Gallery Matrix G in R^(K x 128) per suspect.
- Scoring via max_k (q^T v_k) to retain angular and pose robustness.
- Tri-tier thresholding: RED (>= 0.52), AMBER (0.42 <= S < 0.52), and NEUTRAL (< 0.42).
- JSON persistence in data/watchlist.json with base64-encoded float32 feature buffers.
"""

from __future__ import annotations

import base64
import contextlib
import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)


class ThreatLevel(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class TargetType(str, Enum):
    FACE = "face"
    PLATE = "plate"


def normalize_plate_string(text: str) -> str:
    """Strip whitespace and non-alphanumeric characters, convert to uppercase."""
    import re

    return re.sub(r"[^A-Za-z0-9]", "", text).upper()


@dataclass
class MatchResult:
    entry_id: str
    name: str
    score: float
    threat_level: ThreatLevel
    tier: str  # RED or AMBER
    notes: str = ""


@dataclass
class WatchlistEntry:
    id: str
    name: str
    threat_level: ThreatLevel = ThreatLevel.HIGH
    notes: str = ""
    created_at: float = field(default_factory=time.time)
    gallery: list[np.ndarray] = field(default_factory=list)  # (128,) SFace embedding vectors
    thumbnail_b64: str = ""
    sight_count: int = 0
    last_sighted: float | None = None
    target_type: TargetType = TargetType.FACE
    plate_number: str | None = None
    normalized_plate: str | None = None
    vehicle_description: str | None = None
    _cached_matrix: np.ndarray | None = field(default=None, init=False, repr=False)

    @property
    def matrix(self) -> np.ndarray:
        """Return (K, 128) exemplar gallery matrix normalized to unit hypersphere (cached)."""
        if getattr(self, "_cached_matrix", None) is not None:
            return self._cached_matrix
        if not self.gallery:
            self._cached_matrix = np.zeros((0, 128), dtype=np.float32)
            return self._cached_matrix
        m = np.vstack([np.asarray(v, dtype=np.float32).reshape(1, -1) for v in self.gallery])
        norms = np.linalg.norm(m, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        self._cached_matrix = (m / norms).astype(np.float32)
        return self._cached_matrix

    def invalidate_cache(self) -> None:
        self._cached_matrix = None


def is_valid_exemplar(arr: np.ndarray) -> bool:
    """True if 128-d float array has non-trivial variance (not all zeros or corrupt)."""
    if arr is None:
        return False
    a = np.asarray(arr, dtype=np.float32).flatten()
    if a.shape != (128,) or not np.all(np.isfinite(a)):
        return False
    norm = float(np.linalg.norm(a))
    if norm < 1e-4:
        return False
    var = float(np.var(a))
    return var >= 1e-4


class WatchlistStore:
    """Thread-safe persistent storage and matcher for biometric watchlist targets."""

    def __init__(self, storage_path: Path | str = Path("data/watchlist.json")) -> None:
        self.storage_path = Path(storage_path).resolve()
        # Task 3: single RLock guards writers AND readers (identify/match_plate
        # iterate _entries — torn-read risk). RLock: _save() takes the lock and
        # is also called with the lock held. Sightings defer to a coalesced
        # 0.5s background save; add/remove save synchronously.
        self._lock = threading.RLock()
        self._dirty = False
        self._save_timer: threading.Timer | None = None
        self._save_debounce_s = 0.5
        self._entries: dict[str, WatchlistEntry] = {}
        self._load()

    def flush(self, timeout: float = 2.0) -> None:
        """Block until any pending debounced save drains, then persist if dirty.

        Cancels the pending debounce timer and saves synchronously under the
        lock (which also waits out an in-flight background save). ``timeout``
        is kept for API compatibility.
        """
        del timeout
        with self._lock:
            self._cancel_debounce_locked()
            if self._dirty:
                self._save()
                self._dirty = False

    def _schedule_debounce_locked(self) -> None:
        """(Re)arm the single coalescing save timer. Caller must hold _lock."""
        if self._save_timer is not None and self._save_timer.is_alive():
            return
        timer = threading.Timer(self._save_debounce_s, self._debounced_save)
        timer.daemon = True
        timer.name = f"watchlist-save-{id(self):x}"
        self._save_timer = timer
        timer.start()

    def _cancel_debounce_locked(self) -> None:
        """Drop a not-yet-fired debounce timer. Caller must hold _lock."""
        timer, self._save_timer = self._save_timer, None
        if timer is not None:
            with contextlib.suppress(Exception):
                timer.cancel()

    def _debounced_save(self) -> None:
        """Background coalesced persist (single pending timer at a time)."""
        try:
            with self._lock:
                self._save_timer = None
                if not self._dirty:
                    return
                self._save()
                self._dirty = False
        except Exception as ex:
            logger.error("Debounced watchlist save failed: %s", ex)

    def _load(self) -> None:
        if not self.storage_path.exists():
            return
        try:
            with open(self.storage_path, encoding="utf-8") as f:
                data = json.load(f)
            entries: dict[str, WatchlistEntry] = {}
            for item in data.get("entries", []):
                # decode gallery vectors from base64 or lists
                gallery: list[np.ndarray] = []
                for raw_v in item.get("gallery", []):
                    if isinstance(raw_v, str):
                        b = base64.b64decode(raw_v.encode("ascii"))
                        arr = np.frombuffer(b, dtype=np.float32).copy()
                        if is_valid_exemplar(arr):
                            gallery.append(arr)
                    elif isinstance(raw_v, list):
                        arr = np.array(raw_v, dtype=np.float32)
                        if is_valid_exemplar(arr):
                            gallery.append(arr)

                raw_threat = str(item.get("threat_level", "HIGH")).upper()
                try:
                    threat = ThreatLevel(raw_threat)
                except ValueError:
                    threat = ThreatLevel.HIGH

                target_type_str = str(item.get("target_type", "face")).lower()
                target_type = TargetType.PLATE if target_type_str == "plate" else TargetType.FACE
                plate_number = item.get("plate_number")
                normalized_plate = item.get("normalized_plate") or (normalize_plate_string(plate_number) if plate_number else None)

                entry = WatchlistEntry(
                    id=item["id"],
                    name=item["name"],
                    threat_level=threat,
                    notes=item.get("notes", ""),
                    created_at=float(item.get("created_at", time.time())),
                    gallery=gallery,
                    thumbnail_b64=item.get("thumbnail_b64", ""),
                    sight_count=int(item.get("sight_count", 0)),
                    last_sighted=float(item["last_sighted"]) if item.get("last_sighted") is not None else None,
                    target_type=target_type,
                    plate_number=plate_number,
                    normalized_plate=normalized_plate,
                    vehicle_description=item.get("vehicle_description"),
                )
                entries[entry.id] = entry
            self._entries = entries
            logger.info("Loaded %d watchlist targets from %s", len(self._entries), self.storage_path)
        except Exception as ex:
            logger.warning("Failed to load watchlist from %s: %s", self.storage_path, ex)

    def _save(self, sync: bool = True) -> None:
        # Whole save under the lock (RLock: callers already hold it): snapshot,
        # serialize, AND atomic replace are one critical section so two racing
        # saves cannot interleave tmp-write/replace and resurrect stale counts.
        with self._lock:
            entries_snapshot = list(self._entries.values())
            serialized = []
            for e in entries_snapshot:
                b64_gallery = [base64.b64encode(np.asarray(v, dtype=np.float32).tobytes()).decode("ascii") for v in e.gallery]
                serialized.append(
                    {
                        "id": e.id,
                        "name": e.name,
                        "threat_level": e.threat_level.value,
                        "notes": e.notes,
                        "created_at": e.created_at,
                        "gallery": b64_gallery,
                        "thumbnail_b64": e.thumbnail_b64,
                        "sight_count": e.sight_count,
                        "last_sighted": e.last_sighted,
                        "target_type": e.target_type.value,
                        "plate_number": e.plate_number,
                        "normalized_plate": e.normalized_plate,
                        "vehicle_description": e.vehicle_description,
                    }
                )
            try:
                self.storage_path.parent.mkdir(parents=True, exist_ok=True)
                tmp_path = self.storage_path.with_suffix(f".{uuid.uuid4().hex[:8]}.tmp")
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump({"entries": serialized}, f, indent=2)
                tmp_path.replace(self.storage_path)
            except Exception as ex:
                logger.error("Failed to persist watchlist to %s: %s", self.storage_path, ex)

    def add_entry(self, entry: WatchlistEntry) -> None:
        with self._lock:
            entry.gallery = [v for v in entry.gallery if is_valid_exemplar(v)]
            if entry.target_type == TargetType.PLATE and entry.plate_number and not entry.normalized_plate:
                entry.normalized_plate = normalize_plate_string(entry.plate_number)
            entry.invalidate_cache()
            self._cancel_debounce_locked()
            self._entries[entry.id] = entry
            self._save()
            self._dirty = False

    def remove_entry(self, entry_id: str) -> bool:
        with self._lock:
            if entry_id in self._entries:
                del self._entries[entry_id]
                self._cancel_debounce_locked()
                self._save()
                self._dirty = False
                return True
            return False

    def get_entry(self, entry_id: str) -> WatchlistEntry | None:
        with self._lock:
            return self._entries.get(entry_id)

    def list_entries(self) -> list[WatchlistEntry]:
        with self._lock:
            return list(self._entries.values())

    def record_sighting(self, entry_id: str, timestamp: float) -> None:
        with self._lock:
            entry = self._entries.get(entry_id)
            if entry is None:
                return
            entry.sight_count += 1
            entry.last_sighted = timestamp
            # Hot path: mutate under lock, persist via coalesced background
            # save (0.5s) so per-alert JSON rewrites don't stall inference.
            self._dirty = True
            self._schedule_debounce_locked()

    def match_plate(
        self,
        plate_text: str,
        amber_threshold: float = 0.80,
    ) -> MatchResult | None:
        """Perform normalized and fuzzy matching against plate watchlist targets."""
        with self._lock:
            snapshot = list(self._entries.values())
        if not snapshot or not plate_text:
            return None

        q = normalize_plate_string(plate_text)
        if not q or len(q) < 3:
            return None

        # 1. Exact match
        for entry in snapshot:
            if entry.target_type == TargetType.PLATE and entry.normalized_plate == q:
                return MatchResult(
                    entry_id=entry.id,
                    name=entry.name,
                    threat_level=entry.threat_level,
                    score=1.0,
                    tier="RED",
                    notes=entry.notes,
                )

        # 2. Character substitution matrix for OCR confusions
        def _canon(s: str) -> str:
            return s.replace("O", "0").replace("I", "1").replace("B", "8").replace("Z", "2").replace("S", "5")

        q_canon = _canon(q)
        for entry in snapshot:
            if entry.target_type == TargetType.PLATE and entry.normalized_plate and _canon(entry.normalized_plate) == q_canon:
                return MatchResult(
                    entry_id=entry.id,
                    name=entry.name,
                    threat_level=entry.threat_level,
                    score=0.92,
                    tier="RED" if entry.threat_level == ThreatLevel.CRITICAL else "AMBER",
                    notes=entry.notes,
                )

        # 3. Single-character edit distance for longer plates (len >= 8)
        if len(q) >= 8:
            for entry in snapshot:
                if entry.target_type == TargetType.PLATE and entry.normalized_plate:
                    np_str = entry.normalized_plate
                    if len(np_str) == len(q):
                        diffs = sum(1 for c1, c2 in zip(np_str, q, strict=True) if c1 != c2)
                        if diffs == 1 and amber_threshold <= 0.85:
                            return MatchResult(
                                entry_id=entry.id,
                                name=entry.name,
                                threat_level=entry.threat_level,
                                score=0.85,
                                tier="AMBER",
                                notes=entry.notes,
                            )

        return None

    def identify(
        self,
        query_feat: np.ndarray,
        red_threshold: float = 0.52,
        amber_threshold: float = 0.42,
    ) -> MatchResult | None:
        """Perform Exemplar Gallery max-cosine matching for a 128-d query feature vector."""
        with self._lock:
            snapshot = list(self._entries.values())
        if not snapshot or query_feat.size == 0:
            return None

        q = np.asarray(query_feat, dtype=np.float32).flatten()
        if not is_valid_exemplar(q):
            return None
        q = q / float(np.linalg.norm(q))

        best_score = -1.0
        best_entry: WatchlistEntry | None = None

        for entry in snapshot:
            mat = entry.matrix
            if mat.shape[0] == 0:
                continue
            # Cosine similarity against each exemplar vector in gallery
            sims = np.dot(mat, q)
            max_sim = float(np.max(sims))
            if max_sim > best_score:
                best_score = max_sim
                best_entry = entry

        if best_entry is None or best_score < amber_threshold:
            return None

        tier = "RED" if best_score >= red_threshold else "AMBER"
        return MatchResult(
            entry_id=best_entry.id,
            name=best_entry.name,
            threat_level=best_entry.threat_level,
            score=best_score,
            tier=tier,
            notes=best_entry.notes,
        )


# Global singleton instance for application runtime
_GLOBAL_WATCHLIST_STORE: WatchlistStore | None = None


def get_watchlist_store() -> WatchlistStore:
    global _GLOBAL_WATCHLIST_STORE
    if _GLOBAL_WATCHLIST_STORE is None:
        _GLOBAL_WATCHLIST_STORE = WatchlistStore()
    return _GLOBAL_WATCHLIST_STORE
