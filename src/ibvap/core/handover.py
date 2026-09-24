"""Cross-Camera Target Handover and Intelligence Dossier engine.

Tracks and correlates targets (intruders, suspects, vehicles) moving across
multiple cameras into unified subject trajectories and investigative dossiers.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from pydantic import BaseModel, Field


class SightingRecord(BaseModel):
    camera_id: str
    camera_name: str
    timestamp: float
    track_id: int | None = None
    bbox_norm: list[float] | tuple[float, float, float, float]
    confidence: float
    identity: str | None = None
    plate: str | None = None
    is_intrusion: bool = False


class SubjectDossier(BaseModel):
    dossier_id: str
    subject_type: str = "person"
    label: str
    threat_level: str = "LOW"
    first_seen_ts: float
    last_seen_ts: float
    cameras_visited: list[str] = Field(default_factory=list)
    sightings: list[SightingRecord] = Field(default_factory=list)
    plate: str | None = None
    is_active: bool = True


class HandoverEngine:
    """Manages cross-camera target handover correlation and dossiers."""

    def __init__(self, max_dossiers: int = 100, handover_window_s: float = 60.0) -> None:
        self.max_dossiers = max_dossiers
        self.handover_window_s = handover_window_s
        self.dossiers: dict[str, SubjectDossier] = {}
        # Track-to-dossier lookup: (camera_id, track_id) -> dossier_id
        self._track_map: dict[tuple[str, int], str] = {}
        # Identity to dossier lookup: name -> dossier_id
        self._identity_map: dict[str, str] = {}
        # Plate to dossier lookup: plate -> dossier_id
        self._plate_map: dict[str, str] = {}

    def update_observations(
        self,
        cameras: list[dict[str, Any]],
        observations_map: dict[str, dict[str, Any]],
    ) -> list[SubjectDossier]:
        now = time.time()

        for cam in cameras:
            cam_id = str(cam["id"])
            cam_name = str(cam.get("name", cam_id[:8]))
            obs = observations_map.get(cam_id)
            if not obs:
                continue

            tracks = obs.get("tracks", [])
            for track in tracks:
                track_id = track.get("track_id")
                bbox = track.get("bbox_norm")
                if track_id is None or not bbox:
                    continue

                class_name = track.get("class_name", "person")
                identity_obj = track.get("identity")
                identity_name = identity_obj.get("name") if identity_obj else None
                threat = "LOW"
                is_intrusion = bool(track.get("intrusion"))

                if is_intrusion:
                    threat = "CRITICAL"
                elif identity_obj and identity_obj.get("threat_level"):
                    threat = str(identity_obj["threat_level"]).upper()

                dossier_id = None

                # 1. Match by identity if known
                if identity_name and identity_name in self._identity_map:
                    dossier_id = self._identity_map[identity_name]

                # 2. Match by camera & track ID
                if not dossier_id and (cam_id, track_id) in self._track_map:
                    dossier_id = self._track_map[(cam_id, track_id)]

                # 3. Spatio-temporal association for unassigned tracks
                if not dossier_id:
                    # Check recent dossiers of same class that were active within handover_window_s
                    for d in self.dossiers.values():
                        if (
                            d.subject_type == class_name
                            and (now - d.last_seen_ts) <= self.handover_window_s
                            and cam_name not in d.cameras_visited
                            and all(s.camera_id != cam_id for s in d.sightings)
                        ):
                            dossier_id = d.dossier_id
                            break

                # 4. Create new dossier if still unassigned
                if not dossier_id:
                    short_id = uuid.uuid4().hex[:6].upper()
                    dossier_id = f"DOS-{short_id}"
                    label = identity_name or f"{class_name.upper()} #{track_id}"
                    new_dossier = SubjectDossier(
                        dossier_id=dossier_id,
                        subject_type=class_name,
                        label=label,
                        threat_level=threat,
                        first_seen_ts=now,
                        last_seen_ts=now,
                        cameras_visited=[cam_name],
                        sightings=[],
                        is_active=True,
                    )
                    self.dossiers[dossier_id] = new_dossier

                # Update matched dossier
                dossier = self.dossiers[dossier_id]
                dossier.last_seen_ts = now
                dossier.is_active = True
                if cam_name not in dossier.cameras_visited:
                    dossier.cameras_visited.append(cam_name)
                if identity_name and not dossier.label.startswith("DOS-"):
                    dossier.label = identity_name
                    self._identity_map[identity_name] = dossier_id

                if is_intrusion or threat == "CRITICAL":
                    dossier.threat_level = "CRITICAL"
                elif threat == "HIGH" and dossier.threat_level not in {"CRITICAL"}:
                    dossier.threat_level = "HIGH"

                self._track_map[(cam_id, track_id)] = dossier_id

                sighting = SightingRecord(
                    camera_id=cam_id,
                    camera_name=cam_name,
                    timestamp=now,
                    track_id=track_id,
                    bbox_norm=bbox,
                    confidence=float(track.get("confidence", 0.0)),
                    identity=identity_name,
                    is_intrusion=is_intrusion,
                )
                dossier.sightings.append(sighting)
                del dossier.sightings[:-20]  # Keep last 20 sightings

            # Associate plates with vehicle dossiers
            for plate in obs.get("plates", []):
                plate_text = plate.get("text")
                if not plate_text:
                    continue
                plate_track_id = plate.get("track_id")
                matched_dossier_id = None
                if plate_track_id is not None and (cam_id, plate_track_id) in self._track_map:
                    matched_dossier_id = self._track_map[(cam_id, plate_track_id)]
                elif plate_text in self._plate_map:
                    matched_dossier_id = self._plate_map[plate_text]

                if matched_dossier_id and matched_dossier_id in self.dossiers:
                    d = self.dossiers[matched_dossier_id]
                    d.plate = plate_text
                    self._plate_map[plate_text] = matched_dossier_id

        # Mark inactive dossiers (not seen for > 30s)
        for d in self.dossiers.values():
            if now - d.last_seen_ts > 30.0:
                d.is_active = False

        # Prune old dossiers if exceeded max_dossiers
        if len(self.dossiers) > self.max_dossiers:
            sorted_dossiers = sorted(self.dossiers.items(), key=lambda item: item[1].last_seen_ts)
            to_remove = len(self.dossiers) - self.max_dossiers
            for k, _ in sorted_dossiers[:to_remove]:
                del self.dossiers[k]

        return list(self.dossiers.values())


# Global singleton handover engine
_GLOBAL_HANDOVER_ENGINE = HandoverEngine()


def get_handover_engine() -> HandoverEngine:
    return _GLOBAL_HANDOVER_ENGINE
