from fastapi.testclient import TestClient

from ibvap.events.outbox import clear_all, transactional_write


def test_events_api_tabs_and_timestamp_sorting(api_client: TestClient) -> None:
    clear_all()
    test_client = api_client

    # Write events spanning categories and different timestamp formats
    transactional_write(
        {
            "camera_id": "c1",
            "event_type": "zone_intrusion",
            "created_at": 1000.0,
            "explanation": {"rule": "restricted_zone_intrusion"},
        },
        dedup_key="ev1",
    )
    transactional_write(
        {
            "camera_id": "c1",
            "event_type": "zone_exit",
            "created_at": "2026-09-08T00:50:00+00:00",
            "explanation": {"rule": "restricted_zone_exit"},
        },
        dedup_key="ev2",
    )
    transactional_write(
        {
            "camera_id": "c2",
            "event_type": "watchlist_suspect_identified",
            "created_at": None,
            "explanation": {"suspect_name": "Arjun Rao", "tier": "RED"},
        },
        dedup_key="ev3",
    )
    transactional_write(
        {
            "camera_id": "c2",
            "event_type": "system_low_vis",
            "created_at": 1050.0,
            "explanation": {"rule": "low_visibility"},
        },
        dedup_key="ev4",
    )

    # 1. Fetch all events - verify 200 and robust parsing with None and ISO string
    resp_all = test_client.get("/api/v1/events")
    assert resp_all.status_code == 200
    all_evs = resp_all.json()
    assert len(all_evs) == 4

    # 2. Test tab filters
    resp_intrusions = test_client.get("/api/v1/events?tab=intrusions")
    assert resp_intrusions.status_code == 200
    intrusions = resp_intrusions.json()
    assert len(intrusions) == 1
    assert intrusions[0]["event_type"] == "zone_intrusion"

    resp_exits = test_client.get("/api/v1/events?tab=exits")
    assert resp_exits.status_code == 200
    exits = resp_exits.json()
    assert len(exits) == 1
    assert exits[0]["event_type"] == "zone_exit"

    resp_wl = test_client.get("/api/v1/events?tab=watchlist")
    assert resp_wl.status_code == 200
    wl = resp_wl.json()
    assert len(wl) == 1
    assert wl[0]["event_type"] == "watchlist_suspect_identified"

    resp_sys = test_client.get("/api/v1/events?tab=system")
    assert resp_sys.status_code == 200
    sys_evs = resp_sys.json()
    assert len(sys_evs) == 1
    assert sys_evs[0]["event_type"] == "system_low_vis"

    # 3. Test delete/clear events
    resp_del = test_client.delete("/api/v1/events")
    assert resp_del.status_code == 200
    assert resp_del.json()["status"] == "cleared"
    assert resp_del.json()["deleted_count"] == 4

    # Verify empty after delete
    resp_empty = test_client.get("/api/v1/events")
    assert resp_empty.status_code == 200
    assert len(resp_empty.json()) == 0
