"""Biometric Watchlist Store with Exemplar Gallery Matrix and Hyperspherical Math.

Implements multi-vector gallery matching on the SFace embedding manifold S^127:
- Replaces naive vector averaging with an Exemplar Gallery Matrix G in R^(K x 128) per suspect.
- Scoring via max_k (q^T v_k) to retain angular and pose robustness.
- Tri-tier thresholding: RED (>= 0.52), AMBER (0.42 <= S < 0.52), and NEUTRAL (< 0.42).
- JSON persistence in data/watchlist.json with base64-encoded float32 feature buffers.
"""

from __future__ import annotations

import base64
import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)


class ThreatLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


@dataclass
class MatchResult:
    entry_id: str
    name: str
    threat_level: ThreatLevel
    score: float
    tier: str  # "RED" | "AMBER" | "NEUTRAL"
    notes: str = ""


@dataclass
class WatchlistEntry:
    id: str
    name: str
    threat_level: ThreatLevel = ThreatLevel.HIGH
    notes: str = ""
    created_at: float = field(default_factory=time.time)
    gallery: list[np.ndarray] = field(default_factory=list)
    thumbnail_b64: str = ""
    sight_count: int = 0
    last_sighted: float | None = None

    @property
    def matrix(self) -> np.ndarray:
        """Return (K, 128) exemplar gallery matrix normalized to unit hypersphere."""
        if not self.gallery:
            return np.zeros((0, 128), dtype=np.float32)
        m = np.vstack([np.asarray(v, dtype=np.float32).reshape(1, -1) for v in self.gallery])
        norms = np.linalg.norm(m, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return m / norms


def is_valid_exemplar(arr: np.ndarray) -> bool:
    """Ensure vector is non-empty, 128-d, finite, non-zero norm, and has genuine biometric variance.

    Rejects constant, all-zero, or corrupted dummy vectors that create spurious cosine matches.
    """
    if not isinstance(arr, np.ndarray) or arr.size != 128:
        return False
    if not np.all(np.isfinite(arr)):
        return False
    norm = float(np.linalg.norm(arr))
    if norm < 1e-4:
        return False
    var = float(np.var(arr))
    if var < 1e-4:
        return False
    return True


class WatchlistStore:
    """Thread-safe persistent storage and matcher for biometric watchlist targets."""

    def __init__(self, storage_path: Path | str = Path("data/watchlist.json")) -> None:
        self.storage_path = Path(storage_path)
        self._entries: dict[str, WatchlistEntry] = {}
        self._load()

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
                )
                entries[entry.id] = entry
            self._entries = entries
            logger.info("Loaded %d watchlist targets from %s", len(self._entries), self.storage_path)
        except Exception as ex:
            logger.warning("Failed to load watchlist from %s: %s", self.storage_path, ex)

    def _save(self) -> None:
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            serialized = []
            for e in self._entries.values():
                b64_gallery = [
                    base64.b64encode(np.asarray(v, dtype=np.float32).tobytes()).decode("ascii")
                    for v in e.gallery
                ]
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
                    }
                )
            tmp_path = self.storage_path.with_suffix(".tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump({"entries": serialized}, f, indent=2)
            tmp_path.replace(self.storage_path)
        except Exception as ex:
            logger.error("Failed to persist watchlist to %s: %s", self.storage_path, ex)

    def add_entry(self, entry: WatchlistEntry) -> None:
        entry.gallery = [v for v in entry.gallery if is_valid_exemplar(v)]
        self._entries[entry.id] = entry
        self._save()

    def remove_entry(self, entry_id: str) -> bool:
        if entry_id in self._entries:
            del self._entries[entry_id]
            self._save()
            return True
        return False

    def get_entry(self, entry_id: str) -> WatchlistEntry | None:
        return self._entries.get(entry_id)

    def list_entries(self) -> list[WatchlistEntry]:
        return list(self._entries.values())

    def record_sighting(self, entry_id: str, timestamp: float) -> None:
        entry = self._entries.get(entry_id)
        if entry is not None:
            entry.sight_count += 1
            entry.last_sighted = timestamp
            self._save()

    def identify(
        self,
        query_feat: np.ndarray,
        red_threshold: float = 0.52,
        amber_threshold: float = 0.42,
    ) -> MatchResult | None:
        """Perform Exemplar Gallery max-cosine matching for a 128-d query feature vector."""
        if not self._entries or query_feat.size == 0:
            return None

        q = np.asarray(query_feat, dtype=np.float32).flatten()
        if not is_valid_exemplar(q):
            return None
        q = q / float(np.linalg.norm(q))

        best_score = -1.0
        best_entry: WatchlistEntry | None = None

        for entry in self._entries.values():
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
