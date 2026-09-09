"""File-jail tests: footage endpoints must stay inside the jail, in every env."""

from __future__ import annotations

import os
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi import HTTPException


def _write_mp4(path: Path) -> Path:
    w = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10.0, (64, 64))
    w.write(np.zeros((64, 64, 3), np.uint8))
    w.release()
    return path


def test_outside_jail_video_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A video outside ALL jail roots must be rejected even with default env."""
    from ibvap.api.routes import cameras as C

    monkeypatch.delenv("IBVAP_ENV", raising=False)
    C._cached_jail_roots.cache_clear()
    C._cached_writable_jail.cache_clear()
    # tmp_path lives under the system tempdir, which IS a jail root - so a
    # tmp file can never prove rejection. Use a unique file in the home dir,
    # asserting the premise (outside every root) explicitly.
    p = Path.home() / f"ibvap_jail_probe_{os.getpid()}.mp4"
    resolved = p.resolve()
    assert not any(resolved.is_relative_to(r) for r in C._file_jail_roots()), C._file_jail_roots()
    _write_mp4(p)
    try:
        with pytest.raises(HTTPException):
            C._resolve_jailed_file(str(p))
    finally:
        p.unlink(missing_ok=True)


def test_inside_jail_video_allowed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A video inside a jail root (tmp dir) resolves fine."""
    from ibvap.api.routes import cameras as C

    monkeypatch.delenv("IBVAP_ENV", raising=False)
    C._cached_jail_roots.cache_clear()
    C._cached_writable_jail.cache_clear()
    p = _write_mp4(tmp_path / "inside.mp4")
    assert C._resolve_jailed_file(str(p)) == p.resolve()
