"""Unit tests for Unified Plate Watchlist and Historical Vehicle Sightings."""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from ibvap.api.app import create_app
from ibvap.core.anpr import SightingsStore
from ibvap.core.watchlist import (
    TargetType,
    ThreatLevel,
    WatchlistEntry,
    WatchlistStore,
    normalize_plate_string,
)


def test_normalize_plate_string():
    assert normalize_plate_string("dl 01 ab 1234") == "DL01AB1234"
    assert normalize_plate_string("KA-05-NB-9999") == "KA05NB9999"
    assert normalize_plate_string("mh.02.cd.5555") == "MH02CD5555"
    assert normalize_plate_string("  abc 123  ") == "ABC123"


def test_plate_watchlist_exact_and_fuzzy_matching():
    with tempfile.TemporaryDirectory() as td:
        store = WatchlistStore(storage_path=Path(td) / "wl.json")
        entry = WatchlistEntry(
            id="plate-1",
            name="Stolen Red Sedan",
            threat_level=ThreatLevel.CRITICAL,
            notes="Armed and dangerous suspect vehicle",
            target_type=TargetType.PLATE,
            plate_number="DL01AB1234",
            normalized_plate="DL01AB1234",
            vehicle_description="Red Honda City",
        )
        store.add_entry(entry)

        # 1. Exact match
        m1 = store.match_plate("DL01AB1234")
        assert m1 is not None
        assert m1.entry_id == "plate-1"
        assert m1.score == 1.0
        assert m1.tier == "RED"
        assert m1.name == "Stolen Red Sedan"

        # 2. Punctuation / whitespace variation
        m2 = store.match_plate("dl-01 ab 1234")
        assert m2 is not None
        assert m2.entry_id == "plate-1"
        assert m2.score == 1.0

        # 3. Optical character substitution (O for 0)
        m3 = store.match_plate("DLO1AB1234")
        assert m3 is not None
        assert m3.entry_id == "plate-1"
        assert m3.score >= 0.90

        # 4. Single-character edit distance
        m4 = store.match_plate("DL01AB1235")
        assert m4 is not None
        assert m4.entry_id == "plate-1"
        assert m4.tier == "AMBER"

        # 5. Completely different plate
        m5 = store.match_plate("KA04MH9999")
        assert m5 is None


def test_plate_sightings_store_and_deduplication():
    store = SightingsStore(max_sightings=100)

    # First sighting
    s1 = store.record_sighting(
        camera_id="cam-gate",
        plate_text="DL01AB1234",
        confidence=0.92,
        vehicle_class="car",
        timestamp=1000.0,
    )
    assert s1.sight_count == 1
    assert s1.plate_text == "DL01AB1234"

    # Second sighting within 30 seconds -> deduplicated
    s2 = store.record_sighting(
        camera_id="cam-gate",
        plate_text="dl 01 ab 1234",
        confidence=0.96,
        vehicle_class="car",
        timestamp=1010.0,
    )
    assert s2.id == s1.id
    assert s2.sight_count == 2
    assert s2.confidence == 0.96

    # Query sightings
    results = store.query_sightings(plate_prefix="DL01", camera_id="cam-gate")
    assert len(results) == 1
    assert results[0].plate_text == "DL01AB1234"


def test_anpr_and_watchlist_endpoints():
    app = create_app()
    client = TestClient(app)

    # Enroll a plate target
    resp = client.post(
        "/api/v1/watchlist/enroll-plate",
        json={
            "name": "BOLO White Scorpio",
            "plate_number": "HR26DK8888",
            "threat_level": "CRITICAL",
            "notes": "Wanted in kidnapping case",
            "vehicle_description": "White Mahindra Scorpio",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "enrolled"
    assert data["target_type"] == "plate"
    assert data["plate_number"] == "HR26DK8888"

    # Check that GET /api/v1/watchlist lists this entry
    wl_resp = client.get("/api/v1/watchlist")
    assert wl_resp.status_code == 200
    entries = wl_resp.json()["entries"]
    plate_entries = [e for e in entries if e.get("target_type") == "plate"]
    assert len(plate_entries) >= 1
    assert any(e["name"] == "BOLO White Scorpio" for e in plate_entries)

    # Check GET /api/v1/anpr/sightings
    sightings_resp = client.get("/api/v1/anpr/sightings")
    assert sightings_resp.status_code == 200
    assert isinstance(sightings_resp.json(), list)
