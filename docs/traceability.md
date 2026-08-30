# IBVAP Traceability Matrix — Phase 0 Seed

**Date:** 2026-08-30
**For:** IBVAP 0.1.0 (empty workspace start)
**Spec coverage:** REQ-01..REQ-24 (§29) + IBVAP §1 features 1..26
**Status meaning:** `planned` | `in-dev` | `verified-test` | `verified-manual` | `blocked` | `approved-YOLO-gate`
**Evidence artifact:** file/route/test that proves requirement; Phase 0 entries are stubs.

> Spec §29: "No requirement may be marked complete without an automated test or explicit documented manual acceptance evidence."

---

## 1. Core Requirement Map (REQ-01 .. REQ-24) — per spec §29

| Req ID | Original Requirement | Architecture Component | API / UI | Data Entities | Security / Privacy | Acceptance Tests | Evidence Artifact (Phase 0 stub) | Status | Limitation |
|--------|---------------------|------------------------|----------|---------------|--------------------|------------------|----------------------------------|--------|------------|
| REQ-01 | Existing ordinary IP CCTV | Camera ingestion (§6/7): PyAV + MediaMTX + bounded queues | `POST /api/v1/cameras`, wizard `Other IP camera options`, tile preview | `cameras`, `camera_stream_profiles`, `camera_health_samples` | SSRF controls §21.1; creds envelope encrypted; egress firewall per site CIDR | unit: URL/host/port validation; int: probe RTSP→decode; sec: SSRF alt-IP/DNS-rebind/redirect; media: B-frame/VFR; e2e: RTSP camera creates event | `docs/adr/0002-video-ingestion.md`, `docs/threat-model.md:T-01` | planned | RTSP/RTSPS MVP first; ONVIF/PTZ out-of-initial |
| REQ-02 | Smartphone initial camera | `CameraSource type=smartphone_ip_webcam` (§8-§15 UX override) | Empty state `Connect phone camera` wizard Step 1..9; `Add another phone camera` | same as REQ-01 + `source_type enum` | MJPEG/RTSP validation without scanning wider net; mask auth header | browser: onboarding → real preview not placeholder; chaos: DHCP addr change reconnect new epoch, tracker reset; health: orientation/frames-frozen metrics | `docs/adr/0002-video-ingestion.md` | planned | HTTP-MJPEG fallback adapter must validate `multipart/x-mixed-replace` — not placeholder image |
| REQ-03 | Uploaded footage | Upload pipeline (§9): quarantine→hash→probe→validate→durable job → timeline | `Use video footage` wizard + upload CRUD + job progress bar | `evidence_assets`, `durable_jobs`, `audits` (promotion) | §21.2 upload: quarantine, size/duration/res limits, magic+container validation, sandboxed probe, no shell interp, quotas, cleanup | sec: polyglot media/oversize/path-traversal; int: quarantine→promotion atomic; media: corrupt packet/unsupported codec | planned | Capture-time vs upload-time distinction; not live camera |
| REQ-04 | Live video ingestion | PyAV demux/decode + sampling + provenance timestamps (§10) | Monitoring workspace live player | `tracks/tracks_summaries` (stream_epoch) | Parser sandbox, host HW caps, clock stability | media: VFR/rotated/frozen/no-keyframe/ts-reset/reconnect; chaos: MediaMTX restart | `docs/adr/0002-video-ingestion.md` | planned | Do not use float seconds sole; no raw PTS cross-camera compare |
| REQ-05 | Human detection | DetectorProvider + YOLO26 (§12) | Model registry panel | `model_artifacts`, `model_deployments` | Detector input caps; no PII at detection | unit+property: letterbox + NMSfree postprocess + normalized box round-trip; benchmark precision/recall | `docs/adr/0004-detector-and-licensing.md` | **blocked-YOLO-gate** | Requires license grant or RF-DETR alternate before Phase 3 slice |
| REQ-06 | Human tracking | ByteTrack initial (§12) | Trajectory overlay (Diagnostic) | `tracks` (camera-scoped ID, epoch, class/quality flags) | N/A | bench ByteTrack vs BoT-SORT on ID switches/fragmentation/occlusion/CPU; chaos tracker reset on reconnect | `src/sentinel/tracking/tracker.py` (prototype port) | planned | IDs local per camera+epoch; reset safely after reconnect |
| REQ-07 | Vehicle detection/classification | YOLO26 COCO vehicle subset (car/bus/truck/motorcycle/bicycle) | Overlays + vehicle count rules | `model_artifacts` | N/A | Bench per class; no make/model claim unless classifier added | — | **blocked-YOLO-gate** | Only model-supported classes exposed (attempt `COCO_CLASSES` subset) |
| REQ-08 | Face detection | Dedicated YuNet/SCRFD (§15) | Face bounding + quality chips (blur/pose/occlusion) | `face_detections` (+ gallery tables gated) | Face as PII; RBAC; retention+deletion; no liveness claim | sec: gallery scope; unit: face quality gating; evaluation FAR/FNMR at threshold | `src/sentinel/detectors/faces.py` | planned (detector gated pending weight license) | Not YOLO-COCO; identity matching disabled by default |
| REQ-09 | Facial recognition candidate workflow | Identity candidate pipeline (§15) — **disabled default** | Gated candidate review page (accept/reject/uncertain) | `face_galleries`, `identity_candidates` (added only if gate passes) | Legal/privacy gate, gallery enrollment, encryption, bias eval, audit immutable | sec+bench: threshold calibration, top-k, FAR/FNMR at operating point | — | **blocked until legal/bias/threshold gate** |
| REQ-10 | ANPR | Dedicated plate detector + PaddleOCR PP-OCRv6 + consensus (§16) | Plate review page | `plate_observations`, `plate_candidates` (+ original candidate before human correction) | Plate as sensitive ID — encrypt/tokenize search, never log full string, audit views/exports, retention | unit: ANPR normalization + consensus; bench exact-match + CER + false-positive + day/night/distance/angle/blur/weather | `src/sentinel/detectors/plates.py` + PaddleOCR | planned | Never regex-force invalid OCR; jurisdiction rules; at least 479B placeholder detector is invalid |
| REQ-11 | Virtual fence / tripwire | Polygon zones + directional tripwires (§11/13) | Zone/tripwire editor (Konva/SVG) over real frame + rule config | `zones`, `tripwires`, `schedules`, `alert_rules` | Zone config authz per site | unit: polygon validation (finite/within-range/≥3 non-coincident vertices/non-zero area/no self-intersection/min edge/max verts); property: arbitrary polygon + line crossing + hysteresis/direction | `src/sentinel/tracking/zones.py` | planned | Normalized `[0,1]` coords — never browser CSS/canvas-size persisted (§11) |
| REQ-12 | Suspicious activity | Explainable deterministic rules (§13) | Alerts inbox + timeline with explanation panel | `events` (+ rule_version, facts, thresholds) | Deterministic only initially; no intent/nationality inference | unit: loitering media-duration, repeated crossing, pacing, after-hours; property: rule invariants | `src/sentinel/tracking/activity.py` | planned | Learned anomaly/action-recog/pose-violence remain experimental-disabled |
| REQ-13 | Night movement | Scheduled + luminance + motion + detector fusion (§14) | Night-mode chip + explain panel (illumination/motion/persistence/camera-motion/confidence/limitation) | `schedules` + calibration version | Not only global brightness threshold; no thermal/IR claim | media: very dark + noisy; unit: background adapt + exposure change + shake detection | `src/sentinel/detectors/enhancement.py` | planned | RGB not thermal; motion alone = lower-confidence review event |
| REQ-14 | Real-time alerts | Dedupe + cooldown + escalation + ack/assign/resolve/dismiss (§17) | Alerts inbox (severity/state/site/camera/explain/confidence/assignee/actions) | `alerts` + `event_observations` + audit | Authz per site/camera; audit on every workflow action | integration: event/outbox atomicity; unit: cooldown/dedup continuation; browser: critical banner non-obstructive, rail limited to 5 | `docs/adr/0005-event-delivery.md` | planned | Transient detection observations ≠ alerts (no flooding) |
| REQ-15 | Event logging / evidence | Snapshots + pre/post clips + manifests + hashes (§17) | Evidence viewer (clip/snapshot/step/speed/markers/overlays/manifest/hash/integrity/retention/legal-hold/audit) | `events`, `evidence_assets` (manifest, sha256, retention_id, legal_hold) | Encryption + redaction orchestration + derivative retention | unit: retention/legal-hold precedence; int: ring buffer remux without transcode vs documented transcode; chaos: clip-creation failure partial-mark | `docs/adr/0005-event-delivery.md` | planned | Ring buffer bounded byte+time; Legal-hold never deleted silently |
| REQ-16 | Actionable intelligence | Explainable alerts with model provenance + confidence + uncertainty + evidence refs (§22) | C2 outbox adapter generic versioned (webhook) | `integrations`, `webhook_deliveries` (HMAC digest) | Signed evidence refs; no raw exposure | int: C2 delivery history+replay audited; sec: webhook replay/forged/retry classification | `docs/adr/0005-event-delivery.md` | planned | C2 unavailability never blocks local persistence |
| REQ-17 | Reduced specialist hardware | Software transforms ordinary IP camera | — | — | — | bench: CPU-only baseline sustainable stream count | — | planned | Scales with codec/FPS/resolution (§27: no universal N-camera claim) |
| REQ-18 | Situational awareness / response time | Low-latency overlay (PTS-synced) + alert rail + health | Monitoring workspace (dominant player, WHEP/HLS) | — | Overlay staleness fade not misleading boxes | metrics: `overlay_staleness`, `end_to_end_alert_latency`, `queue_drops` | — | planned | Stale overlays fade instead of ghost boxes |
| REQ-19 | C2 integration | Generic versioned adapter → signed HTTPS webhook v1 (HMAC) (§22) | Integrations page + delivery_history + replay | `integrations`, `webhook_deliveries`, `outbox_messages` | HMAC-SHA256 + timestamp/nonce/keyId + allowlist + redirect-strict + timeout + size cap + mTLS optional | sec: forged webhook; integration: durable retry/backoff/DLQ; chaos: WAN loss backlog | `docs/adr/0005-event-delivery.md` | planned | Do not claim named C2 product without contract |
| REQ-20 | Remote deployment | Offline edge + deferred sync with checksum/idempotency (§23) | Backlog badge: count/bytes/oldest/last-sync/runway; storage-pressure banner | `outbox` + `storage_usage` + sync queue | Disk thresholds Normal→Emergency; never delete legal-hold/unsynced critical | chaos: WAN loss → critical metadata→snapshots→clips order on reconnect | — | planned | Without WAN: ingest/inference/events/evidence/local operator all continue |
| REQ-21 | Cost effectiveness | CPU-only deploy with optional accel (spec §25) | Model choice UX (YOLO26n cost vs accuracy) | — | — | bench CPU degradation order (lower FPS→res→disable experimental→preserve human/vehicle + health) | `docs/adr/0003-inference-runtime.md` | planned | Never silent GPU→CPU fallback (report it) |
| REQ-22 | Scalability | Bounded queues + per-camera pipeline + fair share across cameras (§10 UX §5 multi-phone) | Camera list with priority Critical/Standard/Low + degradation banner | `camera_health_samples` | N/A | load+soak: sustainable stream count measured; overload drops not latency growth | — | planned | Supports multi-phone without corrupting tracker state per epoch |
| REQ-23 | Resilience | Health + tamper/frozen detection + chaos recovery (§16 cam-tamper + §26) | Health pages (camera health, processing jobs, system, storage pressure) | `camera_health_samples`, `storage_usage` | evid temper manifest | chaos: worker killed/db restart/storage outage/GPU OOM/expired creds/clock jump | — | planned | Bounded recovery demonstrated before completeness |
| REQ-24 | Complete polished workflow | Spec §8 empty state → connect → preview → name/locate → zones→ analytics→ rules→ schedules→ cooldown/retention→ C2 select→ estimate/privacy→ save → startup progress → monitor | Full frontend per §24 page list + every loading/empty/offline/degraded/permission/error state | — | WCAG 2.2 AA, keyboard/touch/reduced-motion: all counted | browser: empty→onboard→failed-retry→preview→save→monitor + disable/remove impact preview; Playwright | `product/frontend/src` scaffold (not yet) | planned |

---

## 2. Coverage vs Spec §1 Features 1..26 (gap-closed)

Features 5-10 map to REQ-05..10 above; 11-13 to REQ-11..13; 14-22 to REQ-14+19+20+5+13; remaining (18-searchable logs, 20-pre/post clips etc.) collapse into REQ-14/15. No feature marked complete until Phase-gated test attached per §29.

---

## 3. Phase 0 Artifacts Produced

| Doc | Path | Covers traceability |
|-----|------|---------------------|
| Version evidence | `docs/research/version-evidence.md` | Verifies §5 technology availability for every feature's dependency |
| Technology comparison | `docs/research/technology-comparison.md` | Alternative analysis per feature |
| Dependency matrix | `docs/compliance/dependency-matrix.md` | License for every dependency per feature |
| Model registry | `docs/compliance/model-registry.md` | Weight licensing per REQ-05/08/10 |
| Third-party licenses | `docs/compliance/third-party-licenses.md` | Redistribution for every REQ |
| ADR-0001 | `docs/adr/0001-system-architecture.md` | REQ-21/22/23 |
| ADR-0002 | `docs/adr/0002-video-ingestion.md` | REQ-01/02/04 |
| ADR-0003 | `docs/adr/0003-inference-runtime.md` | REQ-05/07/13 + 21 degrade |
| ADR-0004 | `docs/adr/0004-detector-and-licensing.md` | REQ-05/07 GATE |
| ADR-0005 | `docs/adr/0005-event-delivery.md` | REQ-14/15/19 |
| Threat model | `docs/threat-model.md` | Privacy/security columns for every REQ |

---

## 4. Phase 1 Plan Hook (hook to executed Phase 1 gate)

See `PHASE_0_REPORT.md` "Exact Phase 1 Plan" for checklist that ticks first rows of this matrix (auth, DB migrations, PG outbox stub, camera CRUD skeleton, frontend design tokens) before Phase 3 detector slice attempts to close REQ-05.

---

*Phase 0 seed: all rows are intentional `planned`/`blocked`. Evidence artifact links go live as PRs land and CI turns green.*
