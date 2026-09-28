"""Planar homography and tactical Bird's-Eye-View (BEV) radar projection.

Maps intruder bounding box footpoints from 2D camera image coordinates
into 2D top-down ground coordinates (X, Y in meters) using either calibrated
4-point planar homography or a perspective ground-plane projection model.
"""

from __future__ import annotations

import math
import threading
from typing import Any

import cv2
import numpy as np


class HomographyProjector:
    """Projects image footpoints to ground coordinates in meters."""

    def __init__(
        self,
        camera_id: str,
        homography_matrix: list[list[float]] | np.ndarray | None = None,
        azimuth_deg: float = 0.0,
        fov_deg: float = 75.0,
        camera_height_m: float = 3.5,
        camera_pitch_deg: float = 25.0,
        max_range_m: float = 100.0,
    ) -> None:
        self.camera_id = camera_id
        self.azimuth_deg = azimuth_deg
        self.fov_deg = fov_deg
        self.camera_height_m = camera_height_m
        self.camera_pitch_deg = camera_pitch_deg
        self.max_range_m = max_range_m

        if homography_matrix is not None:
            self.H: np.ndarray | None = np.array(homography_matrix, dtype=np.float64)
        else:
            self.H = None

    @classmethod
    def from_calibration_points(
        cls,
        camera_id: str,
        image_points: list[list[float]],
        ground_points: list[list[float]],
        azimuth_deg: float = 0.0,
    ) -> HomographyProjector:
        """Compute homography matrix from 4 image points [u, v] to ground points [X, Y] in meters."""
        if len(image_points) < 4 or len(ground_points) < 4:
            raise ValueError("At least 4 correspondence points are required for planar homography")

        src = np.array(image_points, dtype=np.float32)
        dst = np.array(ground_points, dtype=np.float32)
        # Task 5 (RANSAC-side): robust estimation over all 4-8 correspondences.
        # With exactly 4 points RANSAC coincides with the direct solution.
        h_matrix, mask = cv2.findHomography(src, dst, cv2.RANSAC, 5.0)
        if h_matrix is None:
            raise ValueError("Failed to compute valid homography matrix from points")
        if mask is not None and int(mask.sum()) < 4:
            raise ValueError("Calibration points are degenerate: fewer than 4 inliers")

        return cls(camera_id=camera_id, homography_matrix=h_matrix, azimuth_deg=azimuth_deg)

    def project_footpoint(self, bbox_norm: tuple[float, float, float, float] | list[float]) -> dict[str, float]:
        """Project footpoint (bottom-center of bounding box) to ground (x_m, y_m, distance_m, bearing_deg)."""
        x1, y1, x2, y2 = bbox_norm[:4]
        u = float((x1 + x2) / 2.0)
        v = float(y2)  # Bottom of bounding box = ground contact point

        if self.H is not None:
            # Planar homography projection: [X, Y, W]^T = H * [u, v, 1]^T
            pt = np.array([[[u, v]]], dtype=np.float32)
            projected = cv2.perspectiveTransform(pt, self.H)
            gx = float(projected[0][0][0])
            gy = float(projected[0][0][1])
            dist = float(math.hypot(gx, gy))
            bearing = float((math.degrees(math.atan2(gx, gy)) + 360.0) % 360.0)
            return {
                "x_m": round(gx, 2),
                "y_m": round(gy, 2),
                "distance_m": round(dist, 2),
                "bearing_deg": round(bearing, 1),
            }

        # Fallback perspective ground-plane projection
        # Azimuth angle relative to camera optical axis
        azimuth_offset = (u - 0.5) * self.fov_deg
        azimuth_rad = math.radians(self.azimuth_deg + azimuth_offset)

        # Vertical angle calculation
        vfov_deg = self.fov_deg * 9.0 / 16.0
        pitch_offset = (v - 0.5) * vfov_deg
        effective_pitch_deg = max(3.0, self.camera_pitch_deg + pitch_offset)
        effective_pitch_rad = math.radians(effective_pitch_deg)

        # Ground distance r = height / tan(pitch)
        dist_m = min(self.max_range_m, self.camera_height_m / math.tan(effective_pitch_rad))
        gx = dist_m * math.sin(azimuth_rad)
        gy = dist_m * math.cos(azimuth_rad)
        bearing = (math.degrees(math.atan2(gx, gy)) + 360.0) % 360.0

        return {
            "x_m": round(gx, 2),
            "y_m": round(gy, 2),
            "distance_m": round(dist_m, 2),
            "bearing_deg": round(bearing, 1),
        }


# Global store for camera homography calibrations
_CAMERA_HOMOGRAPHY: dict[str, HomographyProjector] = {}
_HOMOGRAPHY_LOCK = threading.Lock()


def get_camera_projector(camera_id: str, azimuth_deg: float = 0.0) -> HomographyProjector:
    with _HOMOGRAPHY_LOCK:
        if camera_id not in _CAMERA_HOMOGRAPHY:
            _CAMERA_HOMOGRAPHY[camera_id] = HomographyProjector(camera_id=camera_id, azimuth_deg=azimuth_deg)
        return _CAMERA_HOMOGRAPHY[camera_id]


def set_camera_projector(projector: HomographyProjector) -> None:
    with _HOMOGRAPHY_LOCK:
        _CAMERA_HOMOGRAPHY[projector.camera_id] = projector


def compute_radar_blips(
    cameras: list[dict[str, Any]],
    observations_map: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Aggregate detected tracks across cameras and project them into top-down radar coordinates."""
    blips: list[dict[str, Any]] = []

    for cam_idx, cam in enumerate(cameras):
        cam_id = str(cam["id"])
        obs = observations_map.get(cam_id)
        if not obs or not obs.get("tracks"):
            continue

        default_azimuth = float((cam_idx * 60) % 360)
        projector = get_camera_projector(cam_id, azimuth_deg=default_azimuth)

        for track in obs["tracks"]:
            bbox = track.get("bbox_norm")
            if not bbox:
                continue

            proj = projector.project_footpoint(bbox)
            identity = track.get("identity")
            is_intrusion = bool(track.get("intrusion"))
            class_name = track.get("class_name", "person")
            threat_level = "LOW"
            if is_intrusion:
                threat_level = "CRITICAL"
            elif identity and identity.get("threat_level"):
                threat_level = str(identity["threat_level"]).upper()

            blip = {
                "track_id": track.get("track_id"),
                "camera_id": cam_id,
                "camera_name": cam.get("name", cam_id[:8]),
                "class_name": class_name,
                "threat_level": threat_level,
                "is_intrusion": is_intrusion,
                "identity": identity.get("name") if identity else None,
                "x_m": proj["x_m"],
                "y_m": proj["y_m"],
                "distance_m": proj["distance_m"],
                "bearing_deg": proj["bearing_deg"],
            }
            blips.append(blip)

    return blips
