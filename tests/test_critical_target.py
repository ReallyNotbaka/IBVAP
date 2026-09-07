"""Tests for critical target tracking and biometric identification.

Covers:
- Immediate track-locking on RED match for CRITICAL threat level targets
- Persistent identity retention through occlusion and movement
- Pipeline biometric fusion generating watchlist_suspect_identified event with CRITICAL threat level
- Observation endpoint serialization preserving identity and locked status
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any
import numpy as np
import pytest

from ibvap.core.detector import Detection
from ibvap.core.face import FaceDetection, FaceQuality
from ibvap.core.pipeline import MiniPipeline
from ibvap.core.tracker import CentroidTracker, Track
from ibvap.core.watchlist import (
    MatchResult,
    ThreatLevel,
    WatchlistEntry,
    WatchlistStore,
    get_watchlist_store,
)


def _make_unit_vector(seed: int, dim: int = 128) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(dim).astype(np.float32)
    norm = np.linalg.norm(v)
    return v / norm if norm > 0 else v


class TestCriticalTargetTrackLocking:
    def test_critical_target_locks_immediately_on_first_match(self) -> None:
        """A CRITICAL target must lock on the very first RED tier biometric match."""
        track = Track(
            track_id=1,
            class_name="person",
            class_id=0,
            bbox_norm=(0.3, 0.2, 0.6, 0.8),
            confidence=0.92,
        )

        # Record match for a CRITICAL threat level target
        is_locked = track.record_biometric_match(
            entry_id="target-crit-001",
            name="Vikram Singh",
            score=0.88,
            tier="RED",
            threat_level=ThreatLevel.CRITICAL,
        )

        assert is_locked is True
        assert track.identity_locked is True
        assert track.identity is not None
        assert track.identity["name"] == "Vikram Singh"
        assert track.identity["threat_level"] == "CRITICAL"
        assert track.identity["locked"] is True
        assert track.identity["score"] == pytest.approx(0.88)

    def test_standard_target_requires_two_matches_to_lock(self) -> None:
        """Non-critical targets get tentative identity on 1st match and lock on 2nd match."""
        track = Track(
            track_id=2,
            class_name="person",
            class_id=0,
            bbox_norm=(0.2, 0.2, 0.5, 0.7),
            confidence=0.89,
        )

        # 1st match: tentative identity set, but not locked
        locked_1 = track.record_biometric_match(
            entry_id="target-std-002",
            name="Standard Subject",
            score=0.72,
            tier="RED",
            threat_level=ThreatLevel.HIGH,
        )
        assert locked_1 is False
        assert track.identity_locked is False
        assert track.identity is not None
        assert track.identity["name"] == "Standard Subject"
        assert track.identity["locked"] is False

        # 2nd match: confirmed and locked!
        locked_2 = track.record_biometric_match(
            entry_id="target-std-002",
            name="Standard Subject",
            score=0.75,
            tier="RED",
            threat_level=ThreatLevel.HIGH,
        )
        assert locked_2 is True
        assert track.identity_locked is True
        assert track.identity["locked"] is True
        assert track.identity["score"] == pytest.approx(0.75)

    def test_critical_target_persists_through_occlusion_and_head_turns(self) -> None:
        """Once locked, a critical target's identity and red box latch must endure across frames without faces."""
        tracker = CentroidTracker(max_age=30)

        # Frame 1: person enters
        det = {
            "bbox_norm": (0.35, 0.2, 0.55, 0.8),
            "class_name": "person",
            "class_id": 0,
            "confidence": 0.95,
        }
        tracks, _, _ = tracker.update([det], timestamp=1.0)
        assert len(tracks) == 1
        tid = tracks[0].track_id
        trk = tracker.tracks[tid]

        # Lock onto critical target
        trk.record_biometric_match(
            entry_id="crit-99",
            name="High Value Target",
            score=0.91,
            tier="RED",
            threat_level=ThreatLevel.CRITICAL,
        )
        assert trk.identity_locked is True

        # Simulate 15 consecutive frames of movement where face is turned / occluded (no face match)
        for i in range(15):
            det_move = {
                "bbox_norm": (0.35 + i * 0.01, 0.2, 0.55 + i * 0.01, 0.8),
                "class_name": "person",
                "class_id": 0,
                "confidence": 0.94,
            }
            active_tracks, _, _ = tracker.update([det_move], timestamp=1.0 + (i + 1) * 0.033)
            curr_track = next(t for t in active_tracks if t.track_id == tid)
            # Identity and lock must be preserved seamlessly!
            assert curr_track.identity_locked is True
            assert curr_track.identity is not None
            assert curr_track.identity["name"] == "High Value Target"
            assert curr_track.identity["threat_level"] == "CRITICAL"

    def test_locked_critical_target_cannot_be_overwritten_by_amber_match(self) -> None:
        """A stray AMBER match must NEVER overwrite a locked CRITICAL target or corrupt its tier."""
        track = Track(
            track_id=3,
            class_name="person",
            class_id=0,
            bbox_norm=(0.3, 0.2, 0.6, 0.8),
            confidence=0.92,
        )

        track.record_biometric_match(
            entry_id="target-crit-001",
            name="Vikram Singh",
            score=0.88,
            tier="RED",
            threat_level=ThreatLevel.CRITICAL,
        )
        assert track.identity_locked is True
        assert track.identity["name"] == "Vikram Singh"

        # Subsequent ambiguous AMBER match for another enrolled subject
        track.record_biometric_match(
            entry_id="suspect-amb-999",
            name="Ambiguous Match",
            score=0.45,
            tier="AMBER",
            threat_level=ThreatLevel.LOW,
        )

        # Critical identity must remain completely uncorrupted
        assert track.identity_locked is True
        assert track.identity["entry_id"] == "target-crit-001"
        assert track.identity["name"] == "Vikram Singh"
        assert track.identity["threat_level"] == "CRITICAL"
        assert track.identity["tier"] == "RED"

    def test_locked_critical_target_cannot_be_overwritten_by_non_critical_match(self) -> None:
        """A single non-critical RED match cannot overwrite a locked CRITICAL target."""
        track = Track(
            track_id=4,
            class_name="person",
            class_id=0,
            bbox_norm=(0.3, 0.2, 0.6, 0.8),
            confidence=0.92,
        )

        track.record_biometric_match(
            entry_id="target-crit-001",
            name="Vikram Singh",
            score=0.88,
            tier="RED",
            threat_level=ThreatLevel.CRITICAL,
        )

        track.record_biometric_match(
            entry_id="target-std-002",
            name="Standard Subject",
            score=0.82,
            tier="RED",
            threat_level=ThreatLevel.HIGH,
        )

        assert track.identity["name"] == "Vikram Singh"
        assert track.identity["threat_level"] == "CRITICAL"

    def test_locked_identity_updates_peak_score_on_same_suspect(self) -> None:
        """Subsequent matches for the same suspect update score if higher."""
        track = Track(
            track_id=5,
            class_name="person",
            class_id=0,
            bbox_norm=(0.3, 0.2, 0.6, 0.8),
            confidence=0.92,
        )

        track.record_biometric_match(
            entry_id="target-crit-001",
            name="Vikram Singh",
            score=0.85,
            tier="RED",
            threat_level=ThreatLevel.CRITICAL,
        )
        assert track.identity["score"] == pytest.approx(0.85)

        track.record_biometric_match(
            entry_id="target-crit-001",
            name="Vikram Singh",
            score=0.96,
            tier="RED",
            threat_level=ThreatLevel.CRITICAL,
        )
        assert track.identity["score"] == pytest.approx(0.96)

    def test_person_track_with_identity_protected_from_cross_class_degradation(self) -> None:
        """If a track is identified as a person, overlapping detections must not reclassify it as a vehicle."""
        tracker = CentroidTracker()
        tracker.update(
            [{"bbox_norm": (0.2, 0.2, 0.5, 0.7), "class_name": "person", "class_id": 0, "confidence": 0.80}],
            timestamp=1.0,
        )
        assert 1 in tracker.tracks
        tracker.tracks[1].record_biometric_match(
            entry_id="target-crit-001",
            name="Vikram Singh",
            score=0.90,
            tier="RED",
            threat_level=ThreatLevel.CRITICAL,
        )

        # In frame 2, detector falsely flags overlapping area as motorcycle with higher confidence
        tracker.update(
            [{"bbox_norm": (0.2, 0.2, 0.5, 0.7), "class_name": "motorcycle", "class_id": 3, "confidence": 0.95}],
            timestamp=2.0,
        )

        # Track class must remain person and keep identity!
        trk = tracker.tracks[1]
        assert trk.class_name == "person"
        assert trk.identity is not None
        assert trk.identity["name"] == "Vikram Singh"


class TestFaceAssociationRobustness:
    def test_waist_up_close_up_face_association(self) -> None:
        """Faces on waist-up / close-up camera angles must be associated correctly."""
        from ibvap.core.association import associate_faces_to_tracks

        trk = Track(1, "person", 0, (0.2, 0.1, 0.8, 0.8), 0.9)
        # Face is waist-up / bust framing: ratio fh/th is 0.57
        face = {"bbox_norm": (0.35, 0.12, 0.65, 0.52), "confidence": 0.95}
        matched = associate_faces_to_tracks([trk], [face])
        assert 1 in matched
        assert matched[1]["bbox_norm"] == (0.35, 0.12, 0.65, 0.52)


class TestWatchlistStoreRobustness:
    def test_watchlist_store_case_insensitive_threat_level(self, tmp_path: Path) -> None:
        """WatchlistStore must parse lowercase or mixed case threat levels correctly."""
        p = tmp_path / "watchlist.json"
        import json
        p.write_text(
            json.dumps({
                "entries": [
                    {
                        "id": "crit-case-test",
                        "name": "Case Test Target",
                        "threat_level": "critical",
                        "notes": "Testing case insensitivity",
                        "gallery": [],
                    }
                ]
            }),
            encoding="utf-8",
        )
        store = WatchlistStore(storage_path=p)
        entry = store.get_entry("crit-case-test")
        assert entry is not None
        assert entry.threat_level == ThreatLevel.CRITICAL



class MockPersonDetector:
    def __init__(self, bbox_norm=(0.3, 0.2, 0.6, 0.85)) -> None:
        self.model_id = "yolo26n-mock"
        self.runtime = "mock"
        self.bbox_norm = bbox_norm

    def detect(self, frame: np.ndarray, frame_idx: int = 0) -> list[Detection]:
        return [
            Detection(
                class_id=0,
                class_name="person",
                confidence=0.93,
                bbox_norm=self.bbox_norm,
                model_id=self.model_id,
                runtime=self.runtime,
            )
        ]


class MockFaceDetector:
    def __init__(self, face_bbox_norm=(0.4, 0.22, 0.5, 0.35)) -> None:
        self.face_bbox_norm = face_bbox_norm

    def detect(self, frame: np.ndarray) -> list[FaceDetection]:
        q = FaceQuality(blur=80.0, pose_yaw=0.0, occlusion=0.0, illumination=120.0, passed=True)
        return [
            FaceDetection(
                bbox_norm=self.face_bbox_norm,
                confidence=0.96,
                quality=q,
                landmarks=[(100.0, 100.0), (140.0, 100.0), (120.0, 120.0), (110.0, 140.0), (130.0, 140.0)],
                raw_row=np.array([100.0, 100.0, 50.0, 50.0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0.96], dtype=np.float32),
            )
        ]


class MockFaceRecognizer:
    def __init__(self, feature_vector: np.ndarray) -> None:
        self.feature_vector = feature_vector

    def align_crop(self, frame: np.ndarray, face_row: Any) -> np.ndarray:
        return np.ones((112, 112, 3), dtype=np.uint8) * 128

    def extract_feature(self, aligned_crop: np.ndarray) -> np.ndarray:
        return self.feature_vector.reshape(1, 128)


class TestCriticalTargetPipelineIntegration:
    def test_pipeline_identifies_critical_target_and_emits_alert(self, tmp_path: Path) -> None:
        """Verify MiniPipeline end-to-end: identifies critical target, produces alert event, updates observations."""
        # 1. Setup Watchlist Store with an enrolled CRITICAL target
        store = get_watchlist_store()
        store.storage_path = tmp_path / "watchlist.json"
        store._entries.clear()

        target_vector = _make_unit_vector(42)
        critical_entry = WatchlistEntry(
            id="crit-target-007",
            name="James Bond (Rogue)",
            threat_level=ThreatLevel.CRITICAL,
            notes="Extremely dangerous operative",
            gallery=[target_vector],
            created_at=time.time(),
        )
        store.add_entry(critical_entry)

        # 2. Setup MiniPipeline with mock detector and recognizer matching this vector
        det = MockPersonDetector(bbox_norm=(0.3, 0.2, 0.6, 0.85))
        f_det = MockFaceDetector(face_bbox_norm=(0.4, 0.22, 0.5, 0.35))
        f_rec = MockFaceRecognizer(feature_vector=target_vector)

        pipeline = MiniPipeline(
            camera_id="cam-test-crit",
            stream_epoch=1,
            detector=det,
            face_detector=f_det,
            face_recognizer=f_rec,
            enable_face=True,
            sample_stride=1,
            face_stride=1,
        )

        # 3. Process synthetic frame
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        event = pipeline.process_frame(frame)

        # 4. Verify primary event or created events
        assert pipeline.events_created >= 1

        # Check track identity
        assert len(pipeline.last_tracks) == 1
        track = pipeline.last_tracks[0]
        assert track.identity_locked is True
        assert track.identity is not None
        assert track.identity["name"] == "James Bond (Rogue)"
        assert track.identity["threat_level"] == "CRITICAL"
        assert track.identity["tier"] == "RED"
        assert track.identity["score"] >= 0.99

        # 5. Verify get_last_observations serialization for API / Frontend
        obs = pipeline.get_last_observations()
        assert "tracks" in obs
        assert len(obs["tracks"]) == 1
        obs_track = obs["tracks"][0]
        assert obs_track["identity"] is not None
        assert obs_track["identity"]["name"] == "James Bond (Rogue)"
        assert obs_track["identity"]["threat_level"] == "CRITICAL"
        assert obs_track["identity_locked"] is True


class TestObservationsAPIWithCriticalTarget:
    def test_camera_observations_endpoint_returns_critical_identity(self) -> None:
        """API endpoint /api/v1/cameras/{id}/observations must preserve identity, name, threat level, and lock status."""
        from starlette.testclient import TestClient
        from ibvap.api.app import create_app
        from ibvap.api.routes.cameras import _CAMERAS, _OBSERVATIONS

        app = create_app()
        cam_id = "test-cam-crit-api"
        _CAMERAS[cam_id] = {
            "id": cam_id,
            "name": "Perimeter Cam 1",
            "endpoint": "http://192.168.1.50/video",
            "observed_state": "STREAMING",
            "stream_epoch": 1,
        }
        _OBSERVATIONS[cam_id] = {
            "runtime": "directml",
            "active_model": "yolo26n",
            "detections": [],
            "tracks": [
                {
                    "track_id": 42,
                    "class_name": "person",
                    "confidence": 0.95,
                    "bbox_norm": [0.25, 0.20, 0.55, 0.75],
                    "identity": {
                        "entry_id": "suspect-alpha",
                        "name": "Marcus Kane",
                        "threat_level": "CRITICAL",
                        "score": 0.92,
                        "tier": "RED",
                        "locked": True,
                    },
                    "identity_locked": True,
                }
            ],
            "faces": [],
            "plates": [],
            "night": {"is_night": False},
            "frame_at": time.time(),
        }

        try:
            with TestClient(app) as client:
                resp = client.get(f"/api/v1/cameras/{cam_id}/observations")
                assert resp.status_code == 200
                data = resp.json()
                assert "tracks" in data
                assert len(data["tracks"]) == 1
                track = data["tracks"][0]
                assert track["track_id"] == 42
                assert track["identity_locked"] is True
                assert track["identity"] is not None
                assert track["identity"]["name"] == "Marcus Kane"
                assert track["identity"]["threat_level"] == "CRITICAL"
                assert track["identity"]["locked"] is True
        finally:
            _CAMERAS.pop(cam_id, None)
            _OBSERVATIONS.pop(cam_id, None)

