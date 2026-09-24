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

from pathlib import Path

import numpy as np

from ibvap.core.association import associate_faces_to_tracks
from ibvap.core.tracker import CentroidTracker, Track
from ibvap.core.watchlist import ThreatLevel, WatchlistEntry, WatchlistStore


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

    def test_head_and_shoulders_face_is_associated(self) -> None:
        """Near-camera head-and-shoulders framing must still link face to person.

        Real geometry from YuNet + YOLO on a head-and-shoulders portrait
        (person standing in front of the camera): the person box runs almost
        full-frame height while the face center sits mid-box (~51% down),
        below the old top-42% head gate. The face clearly belongs to the
        track, so it must associate (else close-standing persons never get
        an identity).
        """
        trk = Track(
            track_id=1,
            class_name="person",
            class_id=0,
            bbox_norm=(0.114, 0.099, 0.819, 0.998),
            confidence=0.65,
        )
        face = {
            "bbox_norm": (0.406, 0.357, 0.691, 0.761),
            "confidence": 0.91,
            "quality_passed": True,
        }

        assignments = associate_faces_to_tracks([trk], [face])
        assert assignments[1] == face

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


class TestBystanderNearCriticalTarget:
    """Rigorous verification: when A is our critical target and person B stands near

    or walks in front of A, B must NEVER also be marked as critical.
    """

    def test_global_iou_matching_prevents_track_hijacking_by_earlier_detection(self) -> None:
        """A bystander B appearing before target A in the detector's output list

        must not hijack A's existing track when A has higher IoU.
        """
        tracker = CentroidTracker(max_age=30)
        # Frame 1: Person A alone in scene -> Track 1
        det_A_init = {
            "bbox_norm": (0.40, 0.20, 0.60, 0.80),
            "class_name": "person",
            "class_id": 0,
            "confidence": 0.90,
        }
        tracks, _, _ = tracker.update([det_A_init], timestamp=1.0)
        assert len(tracks) == 1
        trk_A = tracks[0]
        trk_A.record_biometric_match("crit-001", "Target A", score=0.85, tier="RED", threat_level="CRITICAL")
        assert trk_A.identity_locked
        assert trk_A.identity["threat_level"] == "CRITICAL"
        orig_tid = trk_A.track_id

        # Frame 2: Person B stands near A. Detector outputs Person B FIRST, Person A SECOND.
        # Person B has IoU ~0.35 with Track 1. Person A has IoU ~0.95 with Track 1.
        det_B = {
            "bbox_norm": (0.48, 0.20, 0.68, 0.80),
            "class_name": "person",
            "class_id": 0,
            "confidence": 0.88,
        }
        det_A = {
            "bbox_norm": (0.40, 0.20, 0.60, 0.80),
            "class_name": "person",
            "class_id": 0,
            "confidence": 0.92,
        }
        # det_B is placed at index 0 (earlier in list)
        tracks, new_entries, _ = tracker.update([det_B, det_A], timestamp=1.033)
        assert len(tracks) == 2

        # Track 1 MUST remain with Person A (at 0.40..0.60)
        track_1 = next(t for t in tracks if t.track_id == orig_tid)
        assert track_1.identity_locked
        assert track_1.identity["entry_id"] == "crit-001"
        # Track 1's horizontal center must remain close to Person A's position (0.50), not Person B's (0.58)
        assert track_1.center[0] < 0.54

        # The new track must be Person B, and MUST NOT carry critical identity
        bystander_track = next(t for t in tracks if t.track_id != orig_tid)
        assert bystander_track.identity is None
        assert not bystander_track.identity_locked

    def test_full_body_person_rejects_bystander_mid_body_face(self) -> None:
        """When person B is in front of A, A's face sits ~50% down B's body.

        For normal full-body framing, max_y gate (0.42) must reject it from B.
        """
        bystander_trk = Track(
            track_id=2,
            class_name="person",
            class_id=0,
            bbox_norm=(0.30, 0.10, 0.70, 0.90),  # full body: h = 0.80
            confidence=0.90,
        )
        # Target A's face seen behind B, at y=0.50..0.60 (mid-body of B, ~56% down)
        target_face = {
            "bbox_norm": (0.45, 0.50, 0.55, 0.60),  # fh = 0.10, ratio = 0.125
            "confidence": 0.95,
            "quality_passed": True,
        }
        assignments = associate_faces_to_tracks([bystander_trk], [target_face])
        assert 2 not in assignments

    def test_locked_target_track_prioritized_over_nearby_bystander(self) -> None:
        """When both target A and bystander B overlap face A's gate, target A's

        locked identity gives it affinity priority so bystander B cannot steal the face.
        """
        target_trk = Track(
            track_id=1,
            class_name="person",
            class_id=0,
            bbox_norm=(0.35, 0.10, 0.65, 0.90),
            confidence=0.90,
        )
        target_trk.identity_locked = True
        target_trk.identity = {"entry_id": "crit-001", "name": "Target A", "threat_level": "CRITICAL"}

        bystander_trk = Track(
            track_id=2,
            class_name="person",
            class_id=0,
            bbox_norm=(0.38, 0.10, 0.68, 0.90),
            confidence=0.88,
        )

        face_A = {
            "bbox_norm": (0.47, 0.14, 0.55, 0.24),
            "confidence": 0.95,
            "quality_passed": True,
        }

        assignments = associate_faces_to_tracks([target_trk, bystander_trk], [face_A])
        # Face must go to target_trk (1), not bystander (2)
        assert assignments.get(1) == face_A
        assert 2 not in assignments

    def test_duplicate_and_bad_bounding_boxes_suppressed_by_tracker(self) -> None:
        """Duplicate detections and bad sub-boxes (e.g. torso inside full-body)

        must be deduplicated and must NOT spawn duplicate phantom tracks.
        """
        tracker = CentroidTracker()
        det_full = {
            "bbox_norm": (0.35, 0.15, 0.55, 0.85),
            "class_name": "person",
            "class_id": 0,
            "confidence": 0.92,
        }
        det_dup = {
            "bbox_norm": (0.355, 0.152, 0.553, 0.848),  # IoU > 0.90 duplicate box
            "class_name": "person",
            "class_id": 0,
            "confidence": 0.86,
        }
        det_sub_torso = {
            "bbox_norm": (0.36, 0.16, 0.54, 0.52),  # sub-box contained inside full-body
            "class_name": "person",
            "class_id": 0,
            "confidence": 0.75,
        }
        tracks, new_entries, _ = tracker.update([det_full, det_dup, det_sub_torso], timestamp=1.0)
        # Exactly 1 clean track created, not 3
        assert len(tracks) == 1
        assert len(new_entries) == 1

    def test_unmatched_duplicate_detection_does_not_spawn_duplicate_track(self) -> None:
        """When an established track exists, a subsequent duplicate detection

        overlapping it must be discarded in Stage 2 rather than spawning a duplicate track.
        """
        tracker = CentroidTracker()
        det_1 = {
            "bbox_norm": (0.35, 0.15, 0.55, 0.85),
            "class_name": "person",
            "class_id": 0,
            "confidence": 0.92,
        }
        tracker.update([det_1], timestamp=1.0)

        # Frame 2: Det 1 matched, Det 2 is a duplicate box
        det_2_dup = {
            "bbox_norm": (0.354, 0.151, 0.552, 0.849),
            "class_name": "person",
            "class_id": 0,
            "confidence": 0.85,
        }
        tracks, new_entries, _ = tracker.update([det_1, det_2_dup], timestamp=1.033)
        assert len(tracks) == 1
        assert len(new_entries) == 0

    def test_torso_subbox_with_higher_confidence_does_not_replace_full_body(self) -> None:
        """When YOLO produces both a torso sub-box (e.g. conf 0.88) and a full-body box (conf 0.82),

        the tracker MUST retain the enclosing full-body box and discard the torso sub-box.
        Footpoint must be at the feet (y=0.90), not waist (y=0.50).
        """
        tracker = CentroidTracker()
        det_torso = {
            "bbox_norm": (0.40, 0.20, 0.60, 0.50),  # Torso only!
            "class_name": "person",
            "class_id": 0,
            "confidence": 0.88,
        }
        det_full = {
            "bbox_norm": (0.40, 0.20, 0.60, 0.90),  # Full body!
            "class_name": "person",
            "class_id": 0,
            "confidence": 0.82,
        }
        tracks, _, _ = tracker.update([det_torso, det_full], timestamp=1.0)
        assert len(tracks) == 1
        trk = tracks[0]
        assert trk.bbox_norm[3] >= 0.88, f"Expected feet near 0.90, got {trk.bbox_norm[3]}"
        assert trk.footpoint[1] >= 0.88
        assert trk.confidence >= 0.88  # Peak confidence transferred

    def test_inverted_and_degenerate_bounding_boxes_sanitized(self) -> None:
        """Inverted coordinates (x1 > x2 or y1 > y2), out-of-bounds, or degenerate

        bounding boxes must be sanitized or rejected so the tracker never corrupts.
        """
        tracker = CentroidTracker()
        det_inverted = {
            "bbox_norm": (0.60, 0.90, 0.40, 0.20),  # inverted x and y
            "class_name": "person",
            "class_id": 0,
            "confidence": 0.85,
        }
        det_oob = {
            "bbox_norm": (-0.10, 0.20, 0.60, 1.05),  # out of bounds x1 and y2
            "class_name": "person",
            "class_id": 0,
            "confidence": 0.80,
        }
        det_zero = {
            "bbox_norm": (0.50, 0.50, 0.50, 0.50),  # zero area degenerate
            "class_name": "person",
            "class_id": 0,
            "confidence": 0.90,
        }
        tracks, _, _ = tracker.update([det_inverted, det_zero], timestamp=1.0)
        # Inverted box sanitized to (0.40, 0.20, 0.60, 0.90), degenerate dropped
        assert len(tracks) == 1
        trk = tracks[0]
        assert trk.bbox_norm == (0.40, 0.20, 0.60, 0.90)
        assert trk.footpoint == (0.50, 0.90)

        # OOB box is clamped: (-0.10, 0.20, 0.60, 1.05) -> (0.0, 0.20, 0.60, 1.0)
        tracks_oob, _, _ = tracker.update([det_oob], timestamp=1.033)
        assert len(tracks_oob) == 1
        assert tracks_oob[0].bbox_norm[0] >= 0.0
        assert tracks_oob[0].bbox_norm[3] <= 1.0

    def test_two_tracks_cannot_simultaneously_hold_same_critical_identity(self) -> None:
        """At tracker level, two tracks cannot simultaneously hold the same entry_id.

        If a second track claims the entry_id, only the highest score/active track retains it.
        """
        tracker = CentroidTracker()
        det_1 = {"bbox_norm": (0.30, 0.15, 0.50, 0.85), "class_name": "person", "class_id": 0, "confidence": 0.90}
        det_2 = {"bbox_norm": (0.60, 0.15, 0.80, 0.85), "class_name": "person", "class_id": 0, "confidence": 0.90}
        tracks, _, _ = tracker.update([det_1, det_2], timestamp=1.0)
        assert len(tracks) == 2
        t1, t2 = tracks[0], tracks[1]

        t1.record_biometric_match("crit-001", "Target A", score=0.85, tier="RED", threat_level="CRITICAL")
        t2.record_biometric_match("crit-001", "Target A", score=0.92, tier="RED", threat_level="CRITICAL")

        # After update cycle:
        tracks, _, _ = tracker.update([det_1, det_2], timestamp=1.033)
        crit_tracks = [t for t in tracks if t.identity and t.identity.get("entry_id") == "crit-001"]
        assert len(crit_tracks) == 1
        assert crit_tracks[0].track_id == t2.track_id  # Higher score retains it
