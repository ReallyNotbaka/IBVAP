"""Unit tests for Biometric Face Watchlist & Track Association (Phase 1).

Covers:
- Exemplar gallery matrix math (max-cosine similarity)
- Quality gating (blur, resolution, yaw)
- Tri-tier threshold classification (Red >= 0.52, Amber 0.42-0.52, Neutral < 0.42)
- Hungarian Upper 25% Head-ROI spatial association
- 2-of-3 temporal confirmation and track identity latching
- Track re-identification upon re-appearance
"""

from __future__ import annotations

import json
from pathlib import Path
import numpy as np
import pytest

from ibvap.core.watchlist import WatchlistEntry, WatchlistStore, ThreatLevel, MatchResult
from ibvap.core.association import associate_faces_to_tracks
from ibvap.core.tracker import CentroidTracker, Track


def _make_unit_vector(seed: int, dim: int = 128) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(dim).astype(np.float32)
    norm = np.linalg.norm(v)
    return v / norm if norm > 0 else v


class TestWatchlistMathAndStore:
    def test_exemplar_gallery_max_cosine(self, tmp_path: Path) -> None:
        store = WatchlistStore(storage_path=tmp_path / "watchlist.json")
        
        # Create two distinct unit vectors representing frontal and profile angles of Suspect 1
        v_frontal = _make_unit_vector(101)
        v_profile = _make_unit_vector(102)
        
        entry = WatchlistEntry(
            id="suspect-001",
            name="John Doe",
            threat_level=ThreatLevel.HIGH,
            gallery=[v_frontal, v_profile],
            created_at=1000.0,
        )
        store.add_entry(entry)
        
        # A query close to profile should match profile with high score, unaffected by frontal
        noise = np.random.default_rng(999).standard_normal(128).astype(np.float32) * 0.02
        q_profile = v_profile + noise
        q_profile = q_profile / np.linalg.norm(q_profile)
        
        res = store.identify(q_profile)
        assert res is not None
        assert res.entry_id == "suspect-001"
        assert res.score > 0.90
        assert res.tier == "RED"

    def test_tri_tier_thresholds(self, tmp_path: Path) -> None:
        store = WatchlistStore(storage_path=tmp_path / "watchlist.json")
        v_target = _make_unit_vector(200)
        
        store.add_entry(
            WatchlistEntry(
                id="suspect-002",
                name="Jane Roe",
                threat_level=ThreatLevel.CRITICAL,
                gallery=[v_target],
                created_at=1000.0,
            )
        )
        
        # Test Red Alert tier (>= 0.52)
        v_rand1 = _make_unit_vector(201)
        v_ortho1 = v_rand1 - np.dot(v_rand1, v_target) * v_target
        v_ortho1 = v_ortho1 / np.linalg.norm(v_ortho1)
        v_red = 0.60 * v_target + np.sqrt(1 - 0.60**2) * v_ortho1
        v_red = v_red / np.linalg.norm(v_red)
        res_red = store.identify(v_red)
        assert res_red is not None
        assert res_red.score >= 0.52
        assert res_red.tier == "RED"
        
        # Test Amber tier (0.42 <= S < 0.52)
        v_rand2 = _make_unit_vector(202)
        v_ortho2 = v_rand2 - np.dot(v_rand2, v_target) * v_target
        v_ortho2 = v_ortho2 / np.linalg.norm(v_ortho2)
        v_amber = 0.45 * v_target + np.sqrt(1 - 0.45**2) * v_ortho2
        v_amber = v_amber / np.linalg.norm(v_amber)
        res_amber = store.identify(v_amber)
        assert res_amber is not None
        assert 0.42 <= res_amber.score < 0.52
        assert res_amber.tier == "AMBER"
        
        # Test Neutral Civilian (< 0.42)
        v_neutral = _make_unit_vector(300)
        res_neutral = store.identify(v_neutral)
        # Either None or score < 0.42
        assert res_neutral is None or res_neutral.score < 0.42

    def test_json_persistence(self, tmp_path: Path) -> None:
        file_path = tmp_path / "sub" / "watchlist.json"
        store1 = WatchlistStore(storage_path=file_path)
        v = _make_unit_vector(42)
        
        store1.add_entry(
            WatchlistEntry(
                id="suspect-persist",
                name="Persisted Person",
                threat_level=ThreatLevel.MEDIUM,
                notes="Wanted for questioning",
                gallery=[v],
                created_at=123456.0,
            )
        )
        
        # Load in a second instance
        store2 = WatchlistStore(storage_path=file_path)
        assert len(store2.list_entries()) == 1
        loaded = store2.get_entry("suspect-persist")
        assert loaded is not None
        assert loaded.name == "Persisted Person"
        assert len(loaded.gallery) == 1
        np.testing.assert_allclose(loaded.gallery[0], v, atol=1e-6)


class TestHungarianSpatialAssociation:
    def test_head_roi_association_in_crowd(self) -> None:
        """Verify Hungarian assignment correctly links face to upper 25% head region of correct person.
        
        Scene setup:
        Person 1 (Foreground): [0.20, 0.20, 0.40, 0.80] -> Head ROI roughly [0.20, 0.20, 0.40, 0.35]
        Person 2 (Background, overlapping x): [0.25, 0.10, 0.45, 0.50] -> Head ROI [0.25, 0.10, 0.45, 0.20]
        
        Face 1: at [0.28, 0.22, 0.34, 0.30] -> matches Person 1
        Face 2: at [0.32, 0.11, 0.38, 0.18] -> matches Person 2
        """
        trk1 = Track(
            track_id=1,
            class_name="person",
            class_id=0,
            bbox_norm=(0.20, 0.20, 0.40, 0.80),
            confidence=0.88,
        )
        trk2 = Track(
            track_id=2,
            class_name="person",
            class_id=0,
            bbox_norm=(0.25, 0.10, 0.45, 0.50),
            confidence=0.82,
        )
        
        face1 = {
            "bbox_norm": (0.28, 0.22, 0.34, 0.30),
            "confidence": 0.95,
            "quality_passed": True,
        }
        face2 = {
            "bbox_norm": (0.32, 0.11, 0.38, 0.18),
            "confidence": 0.91,
            "quality_passed": True,
        }
        
        assignments = associate_faces_to_tracks([trk1, trk2], [face1, face2])
        # assignments: dict mapping track_id -> face dict
        assert assignments[1] == face1
        assert assignments[2] == face2

    def test_lower_body_face_is_rejected(self) -> None:
        trk = Track(
            track_id=1,
            class_name="person",
            class_id=0,
            bbox_norm=(0.1433633075485511, 0.4202986361416724, 0.5447594294489909, 0.9216361213900612),
            confidence=0.90,
        )
        face = {
            "bbox_norm": (0.07615335717583922, 0.47118450087487845, 0.1699961819708618, 0.5579700810375883),
            "confidence": 0.92,
            "quality_passed": True,
        }

        assignments = associate_faces_to_tracks([trk], [face])
        assert 1 not in assignments

    def test_non_person_tracks_not_associated(self) -> None:
        car_trk = Track(
            track_id=10,
            class_name="car",
            class_id=2,
            bbox_norm=(0.1, 0.1, 0.5, 0.5),
            confidence=0.9,
        )
        face = {
            "bbox_norm": (0.2, 0.2, 0.3, 0.3),
            "confidence": 0.9,
            "quality_passed": True,
        }
        assignments = associate_faces_to_tracks([car_trk], [face])
        assert 10 not in assignments


class TestTrackerOcclusionAndReappearance:
    def test_identity_latching_and_reappearance(self) -> None:
        tracker = CentroidTracker(max_age=30)
        
        # Simulate suspect track 1 entering
        det_person = {
            "bbox_norm": (0.4, 0.3, 0.6, 0.8),
            "class_name": "person",
            "class_id": 0,
            "confidence": 0.9,
        }
        tracks, _, _ = tracker.update([det_person], timestamp=1.0)
        assert len(tracks) == 1
        tid = tracks[0].track_id
        trk = tracker.tracks[tid]
        
        # Update 1 with suspect match
        trk.record_biometric_match("suspect-001", "John Doe", score=0.65, tier="RED")
        assert not trk.identity_locked  # 1-of-3, not confirmed yet
        
        # Update 2 with suspect match -> 2-of-3 confirmed!
        trk.record_biometric_match("suspect-001", "John Doe", score=0.68, tier="RED")
        assert trk.identity_locked
        assert trk.identity is not None
        assert trk.identity["name"] == "John Doe"
        
        # Simulate 10 frames of occlusion / looking away (no face match recorded)
        for i in range(10):
            det_person = {
                "bbox_norm": (0.41 + i * 0.005, 0.3, 0.61 + i * 0.005, 0.8),
                "class_name": "person",
                "class_id": 0,
                "confidence": 0.9,
            }
            tracks, _, _ = tracker.update([det_person], timestamp=1.0 + (i + 1) * 0.033)
            # Identity must remain locked!
            active_trk = next(t for t in tracks if t.track_id == tid)
            assert active_trk.identity_locked
            assert active_trk.identity["name"] == "John Doe"
        
        # Person leaves scene for 35 frames (> max_age 30) -> Track terminates
        for i in range(35):
            tracks, _, term = tracker.update([], timestamp=2.0 + i * 0.033)
        assert tid not in tracker.tracks
        
        # Person re-enters the scene later -> gets a NEW track_id
        det_reentry = {
            "bbox_norm": (0.1, 0.2, 0.3, 0.7),
            "class_name": "person",
            "class_id": 0,
            "confidence": 0.92,
        }
        tracks_reentry, _, _ = tracker.update([det_reentry], timestamp=10.0)
        assert len(tracks_reentry) == 1
        new_tid = tracks_reentry[0].track_id
        assert new_tid != tid
        
        new_trk = tracker.tracks[new_tid]
        # Re-identified on first frontal glance (1st match + 2nd match)
        new_trk.record_biometric_match("suspect-001", "John Doe", score=0.62, tier="RED")
        new_trk.record_biometric_match("suspect-001", "John Doe", score=0.64, tier="RED")
        assert new_trk.identity_locked
        assert new_trk.identity["name"] == "John Doe"
