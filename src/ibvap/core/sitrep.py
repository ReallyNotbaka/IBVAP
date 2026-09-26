"""Automated Military Intelligence Situation Report (SITREP) generator.

Aggregates detections, active tracks, vehicle license plates, biometric matches,
and perimeter intrusions into standardized military/tactical situation reports
formatted in standard military DTG (Date-Time-Group) format with actionable
command recommendations.
"""

from __future__ import annotations

import datetime
from typing import Any

from pydantic import BaseModel, Field


class SitrepSection(BaseModel):
    title: str
    content: list[str]


class MilitarySitrep(BaseModel):
    dtg: str = Field(description="Military Date-Time Group e.g. 122345Z SEP 26")
    classification: str = "CONFIDENTIAL // BORDER COMMAND SECURE"
    unit_station: str = "IBVAP TACTICAL OPERATIONS CENTER (TOC)"
    threat_posture: str = Field(description="GREEN | AMBER | RED | BLACK")
    total_active_tracks: int
    critical_breaches: int
    watchlist_hits: int
    vehicles_tracked: int
    sections: list[SitrepSection]
    formatted_text: str


def format_dtg(dt: datetime.datetime | None = None) -> str:
    """Format datetime as Military Date-Time Group (e.g. 121805Z SEP 26)."""
    if dt is None:
        dt = datetime.datetime.now(datetime.UTC)
    day = dt.strftime("%d")
    time_z = dt.strftime("%H%M") + "Z"
    mon = dt.strftime("%b").upper()
    yr = dt.strftime("%y")
    return f"{day}{time_z} {mon} {yr}"


def generate_military_sitrep(
    cameras: list[dict[str, Any]],
    observations_map: dict[str, dict[str, Any]],
    events: list[dict[str, Any]] | None = None,
    watchlist: list[dict[str, Any]] | None = None,
    unit_name: str = "IBVAP PERIMETER SENSOR SECTOR 1",
) -> MilitarySitrep:
    """Generate structured and plaintext military SITREP from current surveillance posture."""
    dtg = format_dtg()
    events = events or []
    watchlist = watchlist or []

    # Aggregates
    active_cameras = [c for c in cameras if c.get("observed_state") == "STREAMING"]
    offline_cameras = [c for c in cameras if c.get("observed_state") in {"OFFLINE", "DISABLED"}]

    total_tracks = 0
    intrusions: list[dict[str, Any]] = []
    vehicles: list[dict[str, Any]] = []
    watchlist_matches: list[dict[str, Any]] = []
    night_sensors: list[str] = []

    for cam in cameras:
        cam_id = str(cam["id"])
        cam_name = str(cam.get("name", cam_id[:8]))
        obs = observations_map.get(cam_id)
        if not obs:
            continue

        if obs.get("night", {}).get("is_night"):
            night_sensors.append(cam_name)

        # Tracks
        cam_vehicles: list[dict[str, Any]] = []
        for track in obs.get("tracks", []):
            total_tracks += 1
            is_intrusion = bool(track.get("intrusion"))
            class_name = str(track.get("class_name", "person")).lower()
            identity = track.get("identity")

            if is_intrusion:
                intrusions.append(
                    {
                        "camera": cam_name,
                        "track_id": track.get("track_id"),
                        "class": class_name,
                        "confidence": track.get("confidence", 0.0),
                    }
                )

            if class_name in {"car", "truck", "bus", "motorcycle"}:
                cam_vehicles.append(
                    {
                        "camera": cam_name,
                        "track_id": track.get("track_id"),
                        "class": class_name,
                    }
                )

            if identity and identity.get("name"):
                watchlist_matches.append(
                    {
                        "camera": cam_name,
                        "name": identity.get("name"),
                        "tier": identity.get("tier", "AMBER"),
                        "threat_level": identity.get("threat_level", "HIGH"),
                        "score": identity.get("score", 0.0),
                    }
                )

        # Plates: attach to vehicle tracks on this camera or add if unmatched
        for plate in obs.get("plates", []):
            plate_text = plate.get("text")
            if plate_text:
                unassigned = next((v for v in cam_vehicles if "plate" not in v), None)
                if unassigned is not None:
                    unassigned["plate"] = plate_text
                    unassigned["confidence"] = plate.get("confidence", 0.0)
                else:
                    cam_vehicles.append(
                        {
                            "camera": cam_name,
                            "plate": plate_text,
                            "confidence": plate.get("confidence", 0.0),
                        }
                    )
        vehicles.extend(cam_vehicles)

    # Determine Threat Posture
    if len(intrusions) > 0 or any(m.get("tier") == "RED" or m.get("threat_level") == "CRITICAL" for m in watchlist_matches):
        threat_posture = "RED"
    elif len(watchlist_matches) > 0 or total_tracks > 5:
        threat_posture = "AMBER"
    else:
        threat_posture = "GREEN"

    # Compile Sections
    sections: list[SitrepSection] = []

    # 1. Situation Overview
    situation_lines = [
        f"OPERATIONAL SENSORS: {len(active_cameras)} ONLINE / {len(offline_cameras)} OFFLINE",
        f"CURRENT PERIMETER POSTURE: CONDITION {threat_posture}",
        f"TOTAL TARGET CONTACTS ACTIVE: {total_tracks}",
    ]
    if night_sensors:
        situation_lines.append(f"INFRARED NIGHT MODE ENGAGED ON: {', '.join(night_sensors)}")
    sections.append(SitrepSection(title="1. PERIMETER SITUATION & SENSOR POSTURE", content=situation_lines))

    # 2. Hostile / Intrusion Activity
    intrusion_lines: list[str] = []
    if intrusions:
        for i, breach in enumerate(intrusions, 1):
            intrusion_lines.append(
                f"INCIDENT #{i:02d}: INTRUSION DETECTED AT [{breach['camera']}] "
                f"TARGET #{breach['track_id']} ({breach['class'].upper()}) - CONF: {int(breach['confidence'] * 100)}%"
            )
    else:
        intrusion_lines.append("NO ACTIVE GEOFENCE OR TRIPWIRE BREACHES RECORDED IN CURRENT TIMEFRAME.")
    sections.append(SitrepSection(title="2. PERIMETER & GEOFENCE BREACHES", content=intrusion_lines))

    # 3. Biometric Matches & Watchlist
    watchlist_lines: list[str] = []
    if watchlist_matches:
        for m in watchlist_matches:
            watchlist_lines.append(
                f"TARGET ALERT: [{m['name'].upper()}] - TIER {m['tier']} ({m['threat_level']}) CONFIDENCE: {int(m['score'] * 100)}% DETECTED AT {m['camera']}"
            )
    else:
        watchlist_lines.append("NO WATCHLIST SUSPECT MATCHES DETECTED.")
    sections.append(SitrepSection(title="3. HIGH-VALUE TARGETS & BIOMETRIC SIGHTINGS", content=watchlist_lines))

    # 4. Vehicle & ANPR Surveillance
    vehicle_lines: list[str] = []
    if vehicles:
        plates_seen = [v["plate"] for v in vehicles if "plate" in v]
        if plates_seen:
            vehicle_lines.append(f"LICENSE PLATES IDENTIFIED: {', '.join(set(plates_seen))}")
        vehicle_lines.append(f"TOTAL MOTORIZED TARGETS MONITORED: {len(vehicles)}")
    else:
        vehicle_lines.append("NO VEHICULAR TRAFFIC MONITORED IN SECTOR.")
    sections.append(SitrepSection(title="4. VEHICLE & ANPR SURVEILLANCE", content=vehicle_lines))

    # 5. Tactical Command Recommendations
    command_recs: list[str] = []
    if threat_posture == "RED":
        command_recs.extend(
            [
                "IMMEDIATE ACTION: DISPATCH QUICK REACTION FORCE (QRF) TO BREACH LOCATIONS.",
                "DIRECT SENSOR PAN TILT ILLUMINATION AND LOCK RADAR TRACKERS.",
                "NOTIFY ADJACENT CHECKPOINTS AND HOLD OUTBOUND TRAFFIC.",
            ]
        )
    elif threat_posture == "AMBER":
        command_recs.extend(
            [
                "INCREASE SURVEILLANCE SAMPLE RATE ON MONITORED SECTORS.",
                "CONFIRM IDENTIFICATION ON SIGHTED TARGETS PRIOR TO INTERDICTION.",
                "DISPATCH MOBILE PATROL FOR VISUAL RECONNAISSANCE.",
            ]
        )
    else:
        command_recs.extend(
            [
                "CONTINUE STANDARD AUTOMATED PERIMETER SCAN PROTOCOLS.",
                "ALL GEOFENCE AND RADAR TRIPWIRES ACTIVE AND NOMINAL.",
            ]
        )
    sections.append(SitrepSection(title="5. COMMAND DIRECTIVES & INTERDICTION RECOMMENDATIONS", content=command_recs))

    # Format into standard military plaintext layout
    header_border = "=" * 70
    sub_border = "-" * 70
    lines = [
        header_border,
        f"MILITARY INTELLIGENCE SITUATION REPORT (SITREP) - {dtg}",
        f"STATION: {unit_name.upper()}",
        "CLASSIFICATION: CONFIDENTIAL // BORDER DEFENSE SECURE",
        f"THREAT POSTURE: CONDITION {threat_posture}",
        header_border,
        "",
    ]
    for sec in sections:
        lines.append(sec.title)
        lines.append(sub_border)
        for c in sec.content:
            lines.append(f"  * {c}")
        lines.append("")
    lines.append(header_border)
    lines.append(f"END OF REPORT // TRANSMITTED AT {dtg} // AUTH: IBVAP AUTONOMOUS TOC")
    lines.append(header_border)

    formatted_text = "\n".join(lines)

    return MilitarySitrep(
        dtg=dtg,
        classification="CONFIDENTIAL // BORDER COMMAND SECURE",
        unit_station=unit_name,
        threat_posture=threat_posture,
        total_active_tracks=total_tracks,
        critical_breaches=len(intrusions),
        watchlist_hits=len(watchlist_matches),
        vehicles_tracked=len(vehicles),
        sections=sections,
        formatted_text=formatted_text,
    )
