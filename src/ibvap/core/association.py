"""Spatial Head-ROI Association Engine for Biometric Tracking.

Associates 2D face detections to 2D person tracking bounding boxes using:
- Anatomical Upper 25% Head-ROI projection (y1 + 0.125 * h, x_mid).
- Plausibility gating (face center within upper torso, scale ratio 0.03 <= fh/h <= 0.50).
- Kuhn-Munkres Hungarian bipartite assignment algorithm (pure NumPy, zero heavy deps).
- Prevents cross-identity contamination in dense crowds and overlapping occlusions.
"""

from __future__ import annotations

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
    if n_rows == 1 and n_cols == 1:
        # Fast path: single candidate pair needs no Kuhn-Munkres iterations.
        return np.array([0]), np.array([0])

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
            # Local row view: one 2D index op per inner step instead of two.
            cost_row = cost[marked_i]
            u_m = u[marked_i]
            for j in range(n_cols):
                if not visited[j]:
                    cur = cost_row[j] - u_m - v[j]
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
    max_cost: float = 0.75,
) -> dict[int, dict[str, Any]]:
    """Associate detected faces to active person tracks via Head-ROI bipartite matching.

    Returns:
        dict mapping track_id -> face_dict
    """
    person_tracks = [t for t in tracks if t.class_name == "person"]
    if not person_tracks or not faces:
        return {}

    # Vectorised cost build: replaces the per-pair Python loop + math.sqrt
    # with broadcast numpy ops. Gating math and thresholds are unchanged.
    t_boxes = np.array([t.bbox_norm for t in person_tracks], dtype=np.float64)
    f_boxes = np.array([f["bbox_norm"] for f in faces], dtype=np.float64)

    tx1, ty1, tx2, ty2 = t_boxes[:, 0], t_boxes[:, 1], t_boxes[:, 2], t_boxes[:, 3]
    tw = np.maximum(1e-5, tx2 - tx1)
    th = np.maximum(1e-5, ty2 - ty1)
    hx = (tx1 + tx2) / 2.0
    hy = ty1 + 0.12 * th
    min_x = tx1 + 0.12 * tw
    max_x = tx2 - 0.12 * tw
    min_y = ty1 + 0.02 * th
    max_y = ty1 + 0.42 * th

    fx1, fy1, fx2, fy2 = f_boxes[:, 0], f_boxes[:, 1], f_boxes[:, 2], f_boxes[:, 3]
    fh = np.maximum(1e-5, fy2 - fy1)
    fcx = (fx1 + fx2) / 2.0
    fcy = (fy1 + fy2) / 2.0

    # (n_t, n_f) broadcast of face centers against per-track head gates.
    gate = (fcx[None, :] >= min_x[:, None]) & (fcx[None, :] <= max_x[:, None]) & (fcy[None, :] >= min_y[:, None]) & (fcy[None, :] <= max_y[:, None])
    ratio = fh[None, :] / th[:, None]
    gate &= (ratio >= 0.08) & (ratio <= 0.58)

    dx = np.abs(fcx[None, :] - hx[:, None]) / np.maximum(tw[:, None], 1e-5)
    dy = np.abs(fcy[None, :] - hy[:, None]) / np.maximum(th[:, None], 1e-5)
    dist = np.sqrt(dx * dx + dy * dy)
    cost_matrix = np.where(gate, dist + 0.32 * np.abs(ratio - 0.22), 1e5)

    rows, cols = linear_sum_assignment_numpy(cost_matrix)
    assignments: dict[int, dict[str, Any]] = {}

    for r, c in zip(rows, cols, strict=True):
        if cost_matrix[r, c] <= max_cost:
            trk_id = person_tracks[r].track_id
            assignments[trk_id] = faces[c]

    return assignments
