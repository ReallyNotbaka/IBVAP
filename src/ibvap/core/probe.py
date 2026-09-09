"""Quick probe for camera URLs before we commit to streaming them.

Opens the stream with PyAV, grabs a few frames to make sure there's
actually video there. Handles the phone apps (DroidCam / IP Webcam)
specially since they serve endless MJPEG and normal probing hangs.

Note: don't use float seconds for media timing, stick to time_base + pts.
"""

from __future__ import annotations

import contextlib
import hashlib
import time
from dataclasses import dataclass
from urllib.parse import urlparse, urlunparse

import av

from ibvap.core.ssrf import DEFAULT_POLICY, SSRFPolicy, preflight_stream_url


def normalize_mjpeg_url(url: str) -> str:
    """Fix up phone URLs. Most folks just type IP:port, we add /video.

    DroidCam runs on 4747, IP Webcam on 8080. Both expect /video at the end,
    without it you get the settings page instead of the feed.
    """
    try:
        parsed = urlparse(url)
        path = parsed.path.lower().rstrip("/")
        if parsed.port in (4747, 8080) and not path:
            return urlunparse(parsed._replace(path="/video"))
    except Exception:
        pass
    return url


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
    policy: SSRFPolicy | None = None,
) -> tuple[ProbeResult, list[FrameProbe]]:
    """Try opening the URL, check for a video track, decode a couple frames.

    Raises ProbeError if there's no video, nothing decodes, or it times out.
    When policy is given, the URL is preflighted first (DNS + redirect
    inspection) and SSRFError propagates on denial.
    Phone feeds need format="mpjpeg" or ffmpeg sits there guessing forever.
    Retries 3x on those since phone wifi drops packets a lot.
    """
    url = normalize_mjpeg_url(url)
    if policy is None:
        policy = DEFAULT_POLICY
    preflight_stream_url(url, policy, timeout=min(timeout, 3.0))
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
    parsed_url = urlparse(url)
    path = parsed_url.path.lower().rstrip("/")
    is_ip_webcam_mjpeg = (
        path in {"/video", "/videofeed", "/mjpegfeed"}
        or parsed_url.port == 4747
        or parsed_url.scheme == "mjpeg"
        or path.endswith((".mjpg", ".mjpeg"))
    )

    container = None
    max_open_attempts = 3 if is_ip_webcam_mjpeg else 1
    for attempt in range(max_open_attempts):
        try:
            # IP Webcam / DroidCam serves an endless multipart/x-mixed-replace response.
            # Explicit mpjpeg demuxer avoids format probing delays and network timeouts.
            container = (
                av.open(url, format="mpjpeg", options=opts)
                if is_ip_webcam_mjpeg
                else av.open(url, options=opts)
            )
            break
        except Exception as e:
            # Only retry transient I/O / socket busy errors on phone streams
            if attempt < max_open_attempts - 1 and isinstance(e, (av.error.InvalidDataError, av.error.EOFError, ConnectionResetError)):
                time.sleep(0.4)
                continue
            raise ProbeError(f"Failed to open: {e}", code="open_failed") from e

    if container is None:
        raise ProbeError("Failed to open container", code="open_failed")

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
                # compute sha for frozen detection (downsampled hash).
                # Avoid arr.tobytes() full-frame copy (~6MB @1080p); hash a
                # small strided sample via buffer view instead.
                try:
                    arr = frame.to_ndarray(format="rgb24")
                    sample = arr[::16, ::16]
                    h = hashlib.sha256(memoryview(sample).cast("B")[:4096]).hexdigest()[:16]
                except Exception:
                    try:
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
