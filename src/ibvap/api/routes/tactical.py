"""Tactical endpoints: 2D BEV Radar, Military SITREP, and Cross-Camera Dossiers."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ibvap.core.handover import SubjectDossier, get_handover_engine
from ibvap.core.homography import (
    HomographyProjector,
    compute_radar_blips,
    get_camera_projector,
    set_camera_projector,
)
from ibvap.core.sitrep import MilitarySitrep, generate_military_sitrep
from ibvap.services.stream_worker import _CAMERAS, _OBSERVATIONS

router = APIRouter(prefix="/api/v1/tactical", tags=["tactical"])


class RadarCalibrationRequest(BaseModel):
    camera_id: str
    image_points: list[list[float]] = Field(description="4 normalized [u, v] coordinates", min_length=4)
    ground_points: list[list[float]] = Field(description="4 ground [X, Y] coordinates in meters", min_length=4)
    azimuth_deg: float = 0.0


class RadarResponse(BaseModel):
    max_range_m: float = 100.0
    range_rings_m: list[float] = [10.0, 25.0, 50.0, 100.0]
    cameras: list[dict[str, Any]]
    blips: list[dict[str, Any]]


@router.get("/radar", response_model=RadarResponse)
async def get_tactical_radar() -> RadarResponse:
    """Get real-time 2D Bird's-Eye-View (BEV) radar blips projected from active cameras."""
    cameras_list = list(_CAMERAS.values())
    blips = compute_radar_blips(cameras_list, _OBSERVATIONS)

    camera_sectors: list[dict[str, Any]] = []
    for idx, cam in enumerate(cameras_list):
        cam_id = str(cam["id"])
        default_azimuth = float((idx * 60) % 360)
        projector = get_camera_projector(cam_id, azimuth_deg=default_azimuth)
        camera_sectors.append(
            {
                "camera_id": cam_id,
                "name": cam.get("name", cam_id[:8]),
                "azimuth_deg": projector.azimuth_deg,
                "fov_deg": projector.fov_deg,
                "range_m": projector.max_range_m,
                "status": cam.get("observed_state", "UNKNOWN"),
            }
        )

    return RadarResponse(
        max_range_m=100.0,
        range_rings_m=[10.0, 25.0, 50.0, 100.0],
        cameras=camera_sectors,
        blips=blips,
    )


@router.post("/radar/calibrate", response_model=dict[str, Any])
async def calibrate_radar(req: RadarCalibrationRequest) -> dict[str, Any]:
    """Calibrate planar homography projection for a camera using 4 ground correspondences."""
    if req.camera_id not in _CAMERAS:
        raise HTTPException(status_code=404, detail="Camera not found")

    try:
        projector = HomographyProjector.from_calibration_points(
            camera_id=req.camera_id,
            image_points=req.image_points,
            ground_points=req.ground_points,
            azimuth_deg=req.azimuth_deg,
        )
        set_camera_projector(projector)
        return {"status": "calibrated", "camera_id": req.camera_id}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/sitrep", response_model=MilitarySitrep)
async def get_military_sitrep() -> MilitarySitrep:
    """Generate standardized military intelligence situation report (SITREP) in STANAG format."""
    cameras_list = list(_CAMERAS.values())
    return generate_military_sitrep(
        cameras=cameras_list,
        observations_map=_OBSERVATIONS,
        unit_name="IBVAP FORWARD BORDER SECTOR 01",
    )


@router.get("/dossiers", response_model=list[SubjectDossier])
async def list_target_dossiers() -> list[SubjectDossier]:
    """List cross-camera target handover dossiers with multi-camera timelines."""
    cameras_list = list(_CAMERAS.values())
    engine = get_handover_engine()
    return engine.update_observations(cameras_list, _OBSERVATIONS)


@router.get("/dossiers/{dossier_id}", response_model=SubjectDossier)
async def get_target_dossier(dossier_id: str) -> SubjectDossier:
    """Get detailed cross-camera dossier by ID."""
    engine = get_handover_engine()
    dossier = engine.dossiers.get(dossier_id)
    if not dossier:
        raise HTTPException(status_code=404, detail="Dossier not found")
    return dossier
