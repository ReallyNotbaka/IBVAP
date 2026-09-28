"""Comprehensive tests for novel tactical features:

1. Planar Homography & 2D Bird's-Eye-View (BEV) Radar
2. Automated Military SITREP Generator
3. Tactical Night/Thermal FLIR Simulation & Defog Filters
4. Cross-Camera Target Handover & Dossiers
5. Tactical API Routes
"""

from __future__ import annotations

import numpy as np
from fastapi.testclient import TestClient

from ibvap.core.handover import HandoverEngine
from ibvap.core.homography import (
    HomographyProjector,
    compute_radar_blips,
)
from ibvap.core.sitrep import generate_military_sitrep
from ibvap.core.vision_filters import (
    apply_black_hot_flir,
    apply_ironbow_flir,
    apply_tactical_defog,
    apply_white_hot_flir,
    process_tactical_filter,
)
from ibvap.services.stream_worker import _CAMERAS, _OBSERVATIONS


def test_planar_homography_4_point_calibration():
    # 4 points on image (normalized [0, 1]) mapped to ground rectangle [0..10m, 0..20m]
    img_pts = [[0.2, 0.8], [0.8, 0.8], [0.3, 0.4], [0.7, 0.4]]
    gnd_pts = [[-5.0, 5.0], [5.0, 5.0], [-5.0, 20.0], [5.0, 20.0]]

    proj = HomographyProjector.from_calibration_points(
        camera_id="cam-test-1",
        image_points=img_pts,
        ground_points=gnd_pts,
        azimuth_deg=45.0,
    )
    assert proj.H is not None

    # Test footpoint projection
    bbox = (0.2, 0.6, 0.4, 0.8)  # footpoint is at u=0.3, v=0.8
    res = proj.project_footpoint(bbox)
    assert "x_m" in res
    assert "y_m" in res
    assert "distance_m" in res
    assert "bearing_deg" in res
    assert res["distance_m"] > 0


def test_perspective_fallback_homography():
    proj = HomographyProjector(camera_id="cam-fallback", azimuth_deg=90.0, fov_deg=60.0)
    bbox = (0.4, 0.5, 0.6, 0.9)
    res = proj.project_footpoint(bbox)
    assert res["distance_m"] > 0
    assert 0.0 <= res["bearing_deg"] <= 360.0


def test_compute_radar_blips():
    cams = [
        {"id": "c1", "name": "North Gate", "observed_state": "STREAMING"},
        {"id": "c2", "name": "South Perimeter", "observed_state": "STREAMING"},
    ]
    obs_map = {
        "c1": {
            "tracks": [
                {
                    "track_id": 101,
                    "class_name": "person",
                    "bbox_norm": [0.4, 0.4, 0.6, 0.8],
                    "confidence": 0.88,
                    "intrusion": True,
                }
            ]
        },
        "c2": {
            "tracks": [
                {
                    "track_id": 202,
                    "class_name": "car",
                    "bbox_norm": [0.3, 0.5, 0.7, 0.9],
                    "confidence": 0.92,
                    "intrusion": False,
                }
            ]
        },
    }
    blips = compute_radar_blips(cams, obs_map)
    assert len(blips) == 2
    b1 = next(b for b in blips if b["track_id"] == 101)
    assert b1["is_intrusion"] is True
    assert b1["threat_level"] == "CRITICAL"
    assert b1["camera_name"] == "North Gate"

    b2 = next(b for b in blips if b["track_id"] == 202)
    assert b2["class_name"] == "car"


def test_military_sitrep_generator():
    cams = [{"id": "c1", "name": "East Tower", "observed_state": "STREAMING"}]
    obs_map = {
        "c1": {
            "tracks": [
                {
                    "track_id": 42,
                    "class_name": "person",
                    "bbox_norm": [0.1, 0.2, 0.3, 0.8],
                    "confidence": 0.95,
                    "intrusion": True,
                    "identity": {"name": "Ivan Petrov", "tier": "RED", "threat_level": "CRITICAL", "score": 0.94},
                }
            ],
            "plates": [{"text": "KA01AB1234", "confidence": 0.89}],
            "night": {"is_night": True},
        }
    }
    sitrep = generate_military_sitrep(cams, obs_map, unit_name="CHECKPOINT CHARLIE")
    assert sitrep.threat_posture == "RED"
    assert sitrep.critical_breaches == 1
    assert sitrep.watchlist_hits == 1
    assert "IVAN PETROV" in sitrep.formatted_text
    assert "KA01AB1234" in sitrep.formatted_text
    assert "QUICK REACTION FORCE" in sitrep.formatted_text
    assert "CHECKPOINT CHARLIE" in sitrep.formatted_text


def test_tactical_vision_filters():
    # Synthetic RGB image (128x128x3)
    img = np.zeros((128, 128, 3), dtype=np.uint8)
    img[40:80, 40:80] = [180, 180, 180]  # bright target

    w_hot = apply_white_hot_flir(img)
    assert w_hot.shape == img.shape
    assert w_hot.dtype == np.uint8

    b_hot = apply_black_hot_flir(img)
    assert b_hot.shape == img.shape
    assert b_hot.dtype == np.uint8

    iron = apply_ironbow_flir(img)
    assert iron.shape == img.shape
    assert iron.dtype == np.uint8

    defog = apply_tactical_defog(img)
    assert defog.shape == img.shape
    assert defog.dtype == np.uint8

    assert process_tactical_filter(img, "white-hot").shape == img.shape
    assert process_tactical_filter(img, "ironbow").shape == img.shape


def test_cross_camera_handover_engine():
    engine = HandoverEngine(handover_window_s=30.0)
    cams = [
        {"id": "cam-A", "name": "Zone A"},
        {"id": "cam-B", "name": "Zone B"},
    ]
    # Step 1: Suspect sighted on Cam A
    obs_1 = {
        "cam-A": {
            "tracks": [
                {
                    "track_id": 1,
                    "class_name": "person",
                    "bbox_norm": [0.2, 0.2, 0.4, 0.8],
                    "confidence": 0.9,
                    "identity": {"name": "Target Alpha", "threat_level": "HIGH"},
                }
            ]
        }
    }
    dossiers = engine.update_observations(cams, obs_1)
    assert len(dossiers) == 1
    d1 = dossiers[0]
    assert d1.label == "Target Alpha"
    assert "Zone A" in d1.cameras_visited

    # Step 2: Target moves to Cam B with same identity
    obs_2 = {
        "cam-B": {
            "tracks": [
                {
                    "track_id": 99,
                    "class_name": "person",
                    "bbox_norm": [0.3, 0.3, 0.5, 0.9],
                    "confidence": 0.88,
                    "identity": {"name": "Target Alpha", "threat_level": "CRITICAL"},
                    "intrusion": True,
                }
            ]
        }
    }
    dossiers = engine.update_observations(cams, obs_2)
    assert len(dossiers) == 1
    d2 = dossiers[0]
    assert d2.dossier_id == d1.dossier_id
    assert "Zone A" in d2.cameras_visited
    assert "Zone B" in d2.cameras_visited
    assert d2.threat_level == "CRITICAL"
    assert len(d2.sightings) == 2


def test_tactical_api_endpoints(api_client: TestClient):
    client = api_client
    _CAMERAS.clear()
    _OBSERVATIONS.clear()

    _CAMERAS["cam-radar-1"] = {
        "id": "cam-radar-1",
        "name": "Radar Cam 1",
        "observed_state": "STREAMING",
        "endpoint": "synthetic://test",
    }
    _OBSERVATIONS["cam-radar-1"] = {
        "tracks": [
            {
                "track_id": 55,
                "class_name": "person",
                "bbox_norm": [0.45, 0.5, 0.55, 0.85],
                "confidence": 0.87,
                "intrusion": False,
            }
        ]
    }

    # 1. GET /api/v1/tactical/radar
    resp = client.get("/api/v1/tactical/radar")
    assert resp.status_code == 200
    data = resp.json()
    assert "range_rings_m" in data
    assert len(data["blips"]) == 1
    assert data["blips"][0]["track_id"] == 55

    # 2. POST /api/v1/tactical/radar/calibrate
    cal_payload = {
        "camera_id": "cam-radar-1",
        "image_points": [[0.1, 0.9], [0.9, 0.9], [0.2, 0.3], [0.8, 0.3]],
        "ground_points": [[-10.0, 2.0], [10.0, 2.0], [-10.0, 30.0], [10.0, 30.0]],
        "azimuth_deg": 180.0,
    }
    cal_resp = client.post("/api/v1/tactical/radar/calibrate", json=cal_payload)
    assert cal_resp.status_code == 200

    # 3. GET /api/v1/tactical/sitrep
    sitrep_resp = client.get("/api/v1/tactical/sitrep")
    assert sitrep_resp.status_code == 200
    sitrep_data = sitrep_resp.json()
    assert "threat_posture" in sitrep_data
    assert "formatted_text" in sitrep_data
    assert "MILITARY INTELLIGENCE SITUATION REPORT" in sitrep_data["formatted_text"]

    # 4. GET /api/v1/tactical/dossiers
    dos_resp = client.get("/api/v1/tactical/dossiers")
    assert dos_resp.status_code == 200
    dossiers = dos_resp.json()
    assert len(dossiers) >= 1
    dos_id = dossiers[0]["dossier_id"]

    # 5. GET /api/v1/tactical/dossiers/{id}
    single_dos = client.get(f"/api/v1/tactical/dossiers/{dos_id}")
    assert single_dos.status_code == 200
    assert single_dos.json()["dossier_id"] == dos_id


def test_radar_calibration_validators_reject_bad_payloads(api_client: TestClient):
    """Task 5 contract: radar validators 422 (mismatched counts, >8 points,
    non-finite floats) before anything reaches the estimator."""
    base = {
        "camera_id": "cam-radar-1",
        "image_points": [[0.1, 0.9], [0.9, 0.9], [0.2, 0.3], [0.8, 0.3]],
        "ground_points": [[-10.0, 2.0], [10.0, 2.0], [-10.0, 30.0], [10.0, 30.0]],
        "azimuth_deg": 180.0,
    }

    # mismatched correspondence counts
    bad_counts = dict(base, ground_points=base["ground_points"][:3])
    r = api_client.post("/api/v1/tactical/radar/calibrate", json=bad_counts)
    assert r.status_code == 422, r.text

    # more than 8 correspondences
    many = [[0.1 * i, 0.1 * i] for i in range(9)]
    bad_many = dict(base, image_points=many, ground_points=[[float(i), float(i)] for i in range(9)])
    r = api_client.post("/api/v1/tactical/radar/calibrate", json=bad_many)
    assert r.status_code == 422, r.text

    # non-finite coordinate (FiniteFloat) — sent as raw JSON since the
    # client-side encoder rejects inf before it reaches the server.
    # Task 5 fix-round 1: must be a 422 with {code,message}, never a 500.
    import json as _json

    raw = _json.dumps(base, allow_nan=True)
    raw = raw.replace("0.1, 0.9", "Infinity, 0.9", 1)
    r = api_client.post(
        "/api/v1/tactical/radar/calibrate",
        content=raw,
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["code"] == "validation_error"


def test_handover_engine_eviction_without_key_error():
    """Verify that HandoverEngine cleans up reverse mappings when evicting stale dossiers."""
    engine = HandoverEngine(max_dossiers=5)
    cams = {"cam-1": {"name": "Gate Cam"}}

    # Insert 15 unique tracks across time
    for i in range(15):
        obs = {
            "cam-1": {
                "tracks": [
                    {
                        "track_id": i + 1,
                        "class_name": "person",
                        "bbox_norm": [0.1, 0.1, 0.2, 0.2],
                        "identity": {"name": f"Suspect {i + 1}"},
                        "plate_text": f"DL01AB{i + 1:04d}",
                    }
                ]
            }
        }
        engine.update_observations(cams, obs)

    # Dossiers should be strictly bounded by max_dossiers
    assert len(engine.dossiers) <= 5

    # Reverse lookup maps must not point to deleted dossiers
    assert all(v in engine.dossiers for v in engine._track_map.values())
    assert all(v in engine.dossiers for v in engine._identity_map.values())
    assert all(v in engine.dossiers for v in engine._plate_map.values())

    # Re-observing an evicted track (e.g. track 1) must NOT crash with KeyError
    reobserved = {
        "cam-1": {
            "tracks": [
                {
                    "track_id": 1,
                    "class_name": "person",
                    "bbox_norm": [0.1, 0.1, 0.2, 0.2],
                    "identity": {"name": "Suspect 1"},
                }
            ]
        }
    }
    dossiers = engine.update_observations(cams, reobserved)
    assert len(dossiers) <= 5
    assert all(v in engine.dossiers for v in engine._track_map.values())


def test_vision_filters_empty_guard():
    """Verify that vision filters gracefully handle empty, none, or degenerate frame inputs."""
    empty_frame = np.zeros((0, 0, 3), dtype=np.uint8)
    tiny_frame = np.zeros((1, 1, 3), dtype=np.uint8)

    assert process_tactical_filter(empty_frame, "white-hot").size == 0
    assert process_tactical_filter(tiny_frame, "black-hot").shape == (1, 1, 3)
    assert process_tactical_filter(empty_frame, "ironbow").size == 0
    assert process_tactical_filter(empty_frame, "defog").size == 0
    assert process_tactical_filter(None, "white-hot") is None  # pyright: ignore[reportArgumentType] # documents the None-input guard
