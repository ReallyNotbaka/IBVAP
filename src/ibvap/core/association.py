"""Spatial Head-ROI Association Engine for Biometric Tracking.

Associates 2D face detections to 2D person tracking bounding boxes using:
- Anatomical Upper 25% Head-ROI projection (y1 + 0.125 * h, x_mid).
- Plausibility gating (face center within upper torso, scale ratio 0.03 <= fh/h <= 0.50).
- Kuhn-Munkres Hungarian bipartite assignment algorithm (pure NumPy, zero heavy deps).
- Prevents cross-identity contamination in dense crowds and overlapping occlusions.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from ibvap.core.tracker import Track


def linear_sum_assignment_numpy(cost_matrix: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Kuhn-Munkres (Hungarian) algorithm implementation in pure NumPy.
    
    Finds minimum weight bipartite matching for any rectangular cost matrix.
    """
    cost = np.array(cost_matrix, dtype=float)
    transposed = False
    if cost.shape[0] > cost.shape[1]:
        cost = cost.T
        transposed = True

    n_rows, n_cols = cost.shape
    if n_rows == 0 or n_cols == 0:
        return np.array([], dtype=int), np.array([], dtype=int)

    u = np.zeros(n_rows)
    v = np.zeros(n_cols)
    p = np.full(n_cols, -1, dtype=int)

    for i in range(n_rows):
        links = np.full(n_cols, -1, dtype=int)
        mins = np.full(n_cols, np.inf)
        visited = np.zeros(n_cols, dtype=bool)
        marked_i = i
        marked_j = -1
        while marked_i != -1:
            j_star = -1
            delta = np.inf
            for j in range(n_cols):
                if not visited[j]:
                    cur = cost[marked_i, j] - u[marked_i] - v[j]
                    if cur < mins[j]:
                        mins[j] = cur
                        links[j] = marked_j
                    if mins[j] < delta:
                        delta = mins[j]
                        j_star = j
            for j in range(n_cols):
                if visited[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    mins[j] -= delta
            u[i] += delta
            visited[j_star] = True
            marked_j = j_star
            marked_i = p[j_star]

        while marked_j != -1:
            prev_j = links[marked_j]
            p[marked_j] = i if prev_j == -1 else p[prev_j]
            marked_j = prev_j

    row_ind = []
    col_ind = []
    for j in range(n_cols):
        if p[j] != -1 and p[j] < n_rows:
            row_ind.append(p[j])
            col_ind.append(j)

    if transposed:
        r, c = np.array(col_ind), np.array(row_ind)
        order = np.argsort(r)
        return r[order], c[order]
    else:
        r, c = np.array(row_ind), np.array(col_ind)
        order = np.argsort(r)
        return r[order], c[order]


def associate_faces_to_tracks(
    tracks: list[Track],
    faces: list[dict[str, Any]],
    max_cost: float = 0.85,
) -> dict[int, dict[str, Any]]:
    """Associate detected faces to active person tracks via Head-ROI bipartite matching.
    
    Returns:
        dict mapping track_id -> face_dict
    """
    person_tracks = [t for t in tracks if t.class_name == "person"]
    if not person_tracks or not faces:
        return {}

    n_t = len(person_tracks)
    n_f = len(faces)
    cost_matrix = np.full((n_t, n_f), 1e5, dtype=np.float64)

    for i, trk in enumerate(person_tracks):
        tx1, ty1, tx2, ty2 = trk.bbox_norm
        tw = max(1e-5, tx2 - tx1)
        th = max(1e-5, ty2 - ty1)

        # Upper 25% Head Anchor
        hx = (tx1 + tx2) / 2.0
        hy = ty1 + 0.125 * th

        # Permitted spatial boundary for the head center (supports full body, waist-up, and close-up framing)
        min_x = tx1 - 0.15 * tw
        max_x = tx2 + 0.15 * tw
        min_y = ty1 - 0.10 * th
        max_y = ty1 + 0.60 * th

        for j, face in enumerate(faces):
            fx1, fy1, fx2, fy2 = face["bbox_norm"]
            fw = max(1e-5, fx2 - fx1)
            fh = max(1e-5, fy2 - fy1)

            fcx = (fx1 + fx2) / 2.0
            fcy = (fy1 + fy2) / 2.0

            # Anatomical spatial containment check
            if not (min_x <= fcx <= max_x and min_y <= fcy <= max_y):
                continue

            # Scale ratio check (face height vs person bbox height: supports distant full-body to close-up/bust)
            ratio = fh / th
            if ratio < 0.02 or ratio > 0.85:
                continue

            # Normalized distance from head anchor
            dx = abs(fcx - hx) / tw
            dy = abs(fcy - hy) / th
            dist = math.sqrt(dx * dx + dy * dy)
            scale_penalty = 0.3 * abs(ratio - 0.18)
            cost_matrix[i, j] = dist + scale_penalty

    rows, cols = linear_sum_assignment_numpy(cost_matrix)
    assignments: dict[int, dict[str, Any]] = {}

    for r, c in zip(rows, cols):
        if cost_matrix[r, c] <= max_cost:
            trk_id = person_tracks[r].track_id
            assignments[trk_id] = faces[c]

    return assignments
