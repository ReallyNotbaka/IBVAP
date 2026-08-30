from __future__ import annotations

from ibvap.core.tracker import CentroidTracker


def test_tracker_persistence_and_iou() -> None:
    trk = CentroidTracker(iou_threshold=0.3, max_age=5)
    # first detection
    tracks, new, terminated = trk.update([{"bbox_norm": (0.4, 0.4, 0.6, 0.6), "class_name": "person", "class_id": 0, "confidence": 0.9}], timestamp=0.0)
    assert len(tracks) == 1
    assert len(new) == 1
    tid = tracks[0].track_id
    # second frame slightly moved - should retain same id
    tracks, new, terminated = trk.update([{"bbox_norm": (0.41, 0.41, 0.61, 0.61), "class_name": "person", "class_id": 0, "confidence": 0.9}], timestamp=0.1)
    assert len(tracks) == 1
    assert tracks[0].track_id == tid
    assert tracks[0].hits == 2


def test_tracker_new_id_for_distant_box() -> None:
    trk = CentroidTracker()
    trk.update([{"bbox_norm": (0.1, 0.1, 0.2, 0.2), "class_name": "person", "class_id": 0, "confidence": 0.9}], timestamp=0.0)
    tracks, _, _ = trk.update([{"bbox_norm": (0.8, 0.8, 0.9, 0.9), "class_name": "person", "class_id": 0, "confidence": 0.9}], timestamp=0.1)
    assert len(tracks) == 2


def test_tracker_epoch_reset() -> None:
    trk = CentroidTracker()
    trk.update([{"bbox_norm": (0.4, 0.4, 0.6, 0.6), "class_name": "person", "class_id": 0, "confidence": 0.9}], timestamp=0.0)
    assert len(trk.tracks) == 1
    trk.reset_epoch(1)
    assert len(trk.tracks) == 0
    tracks, _, _ = trk.update([{"bbox_norm": (0.4, 0.4, 0.6, 0.6), "class_name": "person", "class_id": 0, "confidence": 0.9}], timestamp=1.0)
    # new id after epoch reset should start at 1 again
    assert tracks[0].track_id == 1
