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


def _night_mover_frames(w: int, h: int, contrast: int, n: int = 12, seed_lum: int = 12) -> list:
    base = np.full((180, 320, 3), seed_lum, dtype=np.uint8)
    frames = []
    for i in range(n):
        f = base.copy()
        x = 40 + 2 * i
        f[80 : 80 + h, x : x + w] = np.clip(base[80 : 80 + h, x : x + w].astype(int) + contrast, 0, 255)
        frames.append(f.astype(np.uint8))
    return frames


def test_night_dim_mover_detected() -> None:
    """Dark-clothed person (30x60, contrast 16) must alert at night, not vanish."""
    nd = NightDetector(temporal_seconds=0.0)
    base = np.full((180, 320, 3), 12, dtype=np.uint8)
    for _ in range(5):
        nd.update(base, timestamp=0.0)
    res = None
    for i, f in enumerate(_night_mover_frames(30, 60, 16)):
        res = nd.update(f, timestamp=0.5 * (i + 1))
    assert res is not None and res.confidence >= 0.7


def test_night_sensor_noise_stays_quiet() -> None:
    """Static sensor grain must never motion-alert (false-fire guard)."""
    rng = np.random.default_rng(0)
    nd = NightDetector(temporal_seconds=0.0)
    base = np.full((180, 320, 3), 12, dtype=np.uint8)
    for _ in range(5):
        nd.update(base, timestamp=0.0)
    res = None
    for i in range(12):
        noisy = np.clip(base.astype(int) + rng.normal(0, 3, base.shape), 0, 255).astype(np.uint8)
        res = nd.update(noisy, timestamp=0.5 * (i + 1))
    assert res is not None and res.confidence == 0.0


def test_night_illumination_step_stays_quiet() -> None:
    """Global exposure/IR step (no object) must not motion-alert."""
    nd = NightDetector(temporal_seconds=0.0)
    base = np.full((180, 320, 3), 12, dtype=np.uint8)
    for _ in range(5):
        nd.update(base, timestamp=0.0)
    step = np.full((180, 320, 3), 22, dtype=np.uint8)
    res = None
    for i in range(6):
        res = nd.update(step, timestamp=0.5 * (i + 1))
    assert res is not None and res.confidence == 0.0
