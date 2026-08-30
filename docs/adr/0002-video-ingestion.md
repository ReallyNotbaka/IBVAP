# ADR-0002: Video Ingestion — PyAV + MediaMTX + Bounded Queues

- **Status:** Accepted (Phase 0)
- **Date:** 2026-08-30
- **Spec:** §5 Video and media, §7 Camera sources, §8 Smartphone/IP workflow, §10 Video pipeline and timing, §17 Events/evidence

## Context

IBVAP must ingest authorized smartphone IP-webcam streams (§2: "smartphone acting as IP camera will be primary live source") plus standard IP cameras (RTSP/RTSPS), WHIP publishers, HTTP-MJPEG constrained adapter, HLS, and uploaded recordings (§7). Prototypes commonly misuse `cv2.VideoCapture` as sole demux, which hides PTS/time_base and reconnect semantics.

Required correctness properties (§10):
- Preserve PTS/DTS/time_base, receive/inference/event timestamps, sequence, stream epoch, dimensions, pix_fmt, keyframe association
- Detect timestamp resets/regression/wraparound/missing/VFR/gaps/frozen/clock-skew
- Never compare raw PTS across cameras; do not use float seconds as sole time representation (use `av.Rational` tick + `time_base`)
- Bounded queues with name/max/size/max-age/drop-policy/depth metric/dropped counter/put-get latency/warning threshold

## Decision

**Primary path:** `MediaMTX → PyAV (av.open) demux/decode → bounded latest-frame queue → sampling → inference`

| Layer | Choice | Version verified | Why |
|-------|--------|------------------|-----|
| Gateway | **MediaMTX 1.20.1** | 2026-08-18, MIT | Replaceable single binary; RTSP/RTSPS server+proxy, RTMP/SRT, HLS mux, WebRTC/WHIP/WHEP per spec §5. Image `bluenviron/mediamtx:1-ffmpeg`. Prototype had none — gap. |
| Demux/decode | **PyAV 18.1.0** | 2026-08-12, BSD-3 | `av.open(url, options=…)`, `container.demux(video=0)`, `packet.decode()`, `frame.pts/dts/time_base`, `frame.to_ndarray(format="bgr24")`. Spec: "PyAV for Python integration with FFmpeg" mandatory. Host FFmpeg 9.0 present; container targets FFmpeg 8.x bundled. |
| Image transforms | **opencv-python 5.0.0.93** | 2026-07-02, Apache-2 | Letterbox, geometry, motion/background. NOT ingestion. |
| Probe | PyAV `av.open(..., timeout=…)` + `container.streams.video[0].codec_context` | — | Extract codec, w×h, fps (`average_rate`), time_base, audio presence before decode. |
| Preview / playback | **WHEP/WebRTC** primary + **HLS fallback** | MediaMTX | Browser `<video>` via WHEP; spec §5/8: "Show actual preview — never placeholder". Prototype uses JPEG-over-WS (~200ms) — supplement with real WHEP for Phase 8 low-latency target. |

**Queue design (§10):**

```
demux/decode ──(latest eligible, max_size=2, max_age=400ms, drop=oldest-stale)──> sampling
sampling     ──(drop oldest stale)──────────────────────────────────────────────> inference
inference    ──(preserve order; reject stale >1.2s)───────────────────────────> tracking
tracking/events ──(durable, never drop)───────────────────────────────────────> PG outbox
```

Metrics per queue: `current_depth`, `dropped_total{reason="stale|full|overload"}`, `put_latency`, `queue_warning_threshold=0.8*max_size`. Logged via OpenTelemetry.

**Timing model:** `SourceTime { pts: int, time_base: Fraction, receive_monotonic_ns, receive_utc, decode_ts, fps_measured }`. Event timestamps are `qualified_at_utc` + `source_pts` + `stream_epoch`. Duration checks use media time (e.g., loitering per §13) not frame count.

**Transport options:**
- RTSP/RTSPS: try TCP first then UDP; auth digest/basic; `stimeout`/`rw_timeout`.
- MJPEG: `multipart/x-mixed-replace` boundary parser; JPEG validity (`soi/eoi`), max header/part/frame caps; effective FPS probe; frozen-frame detection via `ffmpeg` `select='gte(n\, …)'` equivalent or hash.
- WHIP: only if phone gateway publishes (not assumed per §7 — "No universal stream URL"); show missing-capability notice.
- Uploads: separate quarantine → hash → sandboxed FFmpeg probe → NO network in parser; handled in §9 uploaded-footage workflow.

## Alternatives Considered

| Alt | Verdict |
|-----|----------------|
| `cv2.VideoCapture` sole mechanism | **Rejected per spec** — hides time_base, no `Packet` boundary, no keyframe info, retry semantics opaque |
| GStreamer Python | **Rejected Phase 1** — heavier native dep; PyAV covers primary; document as scale-out GPU-decode path (`nvdec`) |
| FFmpeg CLI subprocess per camera | **Rejected** — PyAV gives Packet-level control + memory safety vs shell-interp risk (§21: "No shell interpolation") |

## Consequences

- Must implement **camera state machine** DRAFT→…→STREAMING (see spec §7) with `prev_state/new_state/ts/camera_id/stream_epoch/reason/msg/retry/correlation_id` — prototype lacks it.
- Need **hosted `uv`-locked `av` wheels**: `PyAV` requires FFmpeg 8.x; host 9.0 is newer — pin container `av` wheel's bundled FFmpeg, not host.
- Must never compare PTS across cameras; must detect resets (stream epoch bump).

## Validation (Phase 2 gate)

- Unit: `timebase_conversion`, `letterbox_roundtrip`, `timestamp_discontinuity` property tests
- Media tests: VFR, rotated, B-frames, missing timestamps, corrupt packets, frozen, missing keyframes, timestamp reset, reconnect (§26)
- Chaos: `MediaMTX restart`, `camera flapping`, `WAN loss` — queues must show drops not latency blowup

## Upgrade / Replacement

- Replace PyAV source build with prebuilt `av` manylinux wheels once `av 18.1.x` ships `manylinux_2_28` x64+arm64 (already does).
- MediaMTX version pin via digest `bluenviron/mediamtx:1.20.1@sha256:…`.
- GStreamer/nvdec path evaluated after CPU baseline benchmarks (§27) show decode bottleneck.

---

*References:* `docs/research/version-evidence.md:4.1-4.4`, spec §5/7/10, `PyAV` docs `pyav.basswood.io`.
