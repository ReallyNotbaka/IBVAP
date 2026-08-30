from __future__ import annotations

import numpy as np

from ibvap.core.night import NightDetector


def test_day_night_hysteresis() -> None:
    nd = NightDetector(night_threshold=40.0, day_threshold=70.0, temporal_seconds=0.0)
    bright = np.full((100, 100, 3), 200, dtype=np.uint8)
    dark = np.full((100, 100, 3), 10, dtype=np.uint8)
    assert nd.update(bright, timestamp=0.0).is_night is False
    # dark should switch to night
    assert nd.update(dark, timestamp=1.0).is_night is True
    # bright again should switch back
    assert nd.update(bright, timestamp=2.0).is_night is False


def test_motion_detection() -> None:
    nd = NightDetector(temporal_seconds=0.0)
    frame1 = np.zeros((100, 100, 3), dtype=np.uint8)
    nd.update(frame1, timestamp=0.0)
    frame2 = np.zeros((100, 100, 3), dtype=np.uint8)
    frame2[40:60, 40:60] = 255
    res = nd.update(frame2, timestamp=0.1)
    assert res.motion_area > 0
    assert res.confidence >= 0
