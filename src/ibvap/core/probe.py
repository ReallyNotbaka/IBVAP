"""PyAV probe - demux, decode, measure. Spec 10.

Never use float seconds as sole media time. Uses PyAV time_base + pts.
"""

from __future__ import annotations

import contextlib
import hashlib
import time
from dataclasses import dataclass

import av


@dataclass(frozen=True)
class ProbeResult:
    codec: str
    width: int
    height: int
    pix_fmt: str | None
    fps: float | None
    time_base_num: int
    time_base_den: int
    has_audio: bool
    duration_seconds: float | None
    is_valid: bool
    warnings: list[str]


@dataclass(frozen=True)
class FrameProbe:
    pts: int | None
    dts: int | None
    time_base: tuple[int, int]
    width: int
    height: int
    pix_fmt: str | None
    is_keyframe: bool
    sha256: str  # for frozen-frame detection
    decode_ms: float


def probe_url(
    url: str,
    timeout: float = 5.0,
    max_frames: int = 5,
) -> tuple[ProbeResult, list[FrameProbe]]:
    """Probe url via PyAV: open, find video stream, read up to max_frames.

    Raises ProbeError on unsupported codec / no video track / timeout.
    """
    start = time.monotonic()
    # FFmpeg-level network timeout in microseconds.
    # Do NOT pass timeout= kwarg to av.open() — PyAV's I/O callback
    # triggers AVERROR_EXIT on continuous MJPEG streams before negotiation
    # completes, since multipart/x-mixed-replace has no finite container end.
    us = str(int(timeout * 1_000_000))
    opts: dict[str, str] = {
        "timeout": us,          # generic ffmpeg I/O timeout (microseconds)
        "stimeout": us,         # RTSP socket timeout (microseconds)
        "analyzeduration": us,  # limit format analysis time
        "probesize": "500000",  # 500KB probe buffer (enough for MJPEG headers)
    }
    try:
        container = av.open(url, options=opts)
    except Exception as e:
        raise ProbeError(f"Failed to open: {e}", code="open_failed") from e

    try:
        # Use context manager? av.Container supports closing
        video_streams = [s for s in container.streams if s.type == "video"]
        audio_streams = [s for s in container.streams if s.type == "audio"]
        if not video_streams:
            raise ProbeError("No video track", code="no_video")
        v = video_streams[0]
        codec = v.codec_context.name or "unknown"  # type: ignore[attr-defined]
        # av versions differ on where width/height live; prefer stream then context
        width = int(getattr(v, "width", 0) or getattr(v.codec_context, "width", 0) or 0)  # type: ignore[attr-defined]
        height = int(getattr(v, "height", 0) or getattr(v.codec_context, "height", 0) or 0)  # type: ignore[attr-defined]
        pix_fmt = getattr(v.codec_context, "pix_fmt", None)  # type: ignore[attr-defined]
        # time_base
        tb = v.time_base
        tb_num, tb_den = (int(tb.numerator), int(tb.denominator)) if tb else (1, 1000)
        # fps via average_rate
        fps: float | None = None
        try:
            if v.average_rate and v.average_rate.denominator:
                fps = float(v.average_rate)
        except Exception:
            fps = None
        duration: float | None = None
        try:
            if container.duration and v.time_base:
                duration = float(container.duration * v.time_base)
        except Exception:
            duration = None
        warnings: list[str] = []
        if width == 0 or height == 0:
            warnings.append("zero_dimensions")
        has_audio = len(audio_streams) > 0

        result = ProbeResult(
            codec=codec,
            width=width,
            height=height,
            pix_fmt=str(pix_fmt) if pix_fmt else None,
            fps=fps,
            time_base_num=tb_num,
            time_base_den=tb_den,
            has_audio=has_audio,
            duration_seconds=duration,
            is_valid=True,
            warnings=warnings,
        )

        # decode few frames
        frames: list[FrameProbe] = []
        decode_deadline = start + timeout
        for packet in container.demux(video=0):
            if time.monotonic() > decode_deadline:
                break
            for frame in packet.decode():
                t0 = time.monotonic()
                # compute sha for frozen detection (downsampled hash)
                try:
                    arr = frame.to_ndarray(format="rgb24")
                    h = hashlib.sha256(arr.tobytes()[:4096]).hexdigest()[:16]
                except Exception:
                    h = "nohash"
                dt = (time.monotonic() - t0) * 1000
                frames.append(
                    FrameProbe(
                        pts=frame.pts,
                        dts=frame.dts,
                        time_base=(tb_num, tb_den),
                        width=frame.width,
                        height=frame.height,
                        pix_fmt=str(frame.format.name) if frame.format else None,
                        is_keyframe=bool(frame.key_frame),
                        sha256=h,
                        decode_ms=dt,
                    )
                )
                if len(frames) >= max_frames:
                    break
            if len(frames) >= max_frames:
                break

        if not frames:
            raise ProbeError("No decodable frames", code="no_frames")

        return result, frames
    finally:
        with contextlib.suppress(Exception):
            container.close()


class ProbeError(RuntimeError):
    def __init__(self, msg: str, code: str) -> None:
        super().__init__(msg)
        self.code = code
