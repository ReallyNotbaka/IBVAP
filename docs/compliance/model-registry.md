# IBVAP Compliance — Model Registry

**Date:** 2026-08-30
**Status:** Phase 0 — Stubs only. No model approved for production until checksum + license + evaluation recorded.
**Policy:** Never silently download weights in production (§4). Every artifact must have entry below before use.

> **Reference prototype note:** `attempt/models/*.onnx` contents inspected 2026-08-30 — several artifacts are placeholders (479 bytes or 137 bytes). Those are NOT valid models (see `attempt/src/sentinel/core/models.py:140-169` validation). IBVAP must not copy them.

---

## 1. Registry Schema (required per artifact)

Each row must fill:

- `Artifact name & version` — e.g. `yolo26n.pt v1.0 (Ultralytics Jan 2026)`
- `Task` — `detect` | `face-detect` | `face-embed` | `plate-detect` | `ocr` | `enhance`
- `Source URL` — canonical download (Ultralytics release, OpenCV Zoo, Paddle, etc.)
- `SHA-256 checksum` — computed on fetched file; stored here + in `ModelArtifact` DB row
- `Code license` (SPDX) — license of the architecture/training code
- `Weight license` (SPDX) — license of pretrained weights (often different)
- `Training data` — e.g. COCO 2017, WIDER FACE, private plate dataset
- `Approved use` — `approved` | `pending-legal` | `blocked` | `experimental-disabled-by-default`
- `Input/output contract` — e.g. `input [1,3,640,640] normalized RGB, output [N,6] x1,y1,x2,y2,score,class`
- `Preprocessing` — letterbox, normalization, etc.
- `Thresholds` — inference confidence, NMS, pose gate defaults
- `Runtime` — `onnxruntime` / `openvino` / `tensorrt`
- `Evaluation` — link to `docs/evaluation/<model>.md` with precision/recall etc.
- `Known limitations` — e.g. "does not detect faces"
- `Approval status` — `gate-passed` / `gate-blocked`

---

## 2. Current Artifacts (Phase 0 Baseline — unverified placeholders flagged)

### 2.1 General Person/Vehicle Detector — YOLO26 Family (Primary)

| Field | Value |
|-------|-------|
| **Artifacts** | `yolo26n.pt`, `yolo26s.pt`, `yolo26m.pt`, `yolo26l.pt`, `yolo26x.pt` (five variants, verified at `docs.ultralytics.com/models/yolo26`) |
| Task | `detect` (COCO 80-class; IBVAP uses person + car/truck/bus/motorcycle/bicycle subset) |
| Source URL | Ultralytics assets via `ultralytics` package on first `YOLO("yolo26n.pt")` — `https://platform.ultralytics.com/ultralytics/yolo26` + `https://github.com/ultralytics/ultralytics/releases` (assets). Direct pt URLs per docs: hub. |
| SHA-256 | **PENDING** — must be recorded after `YOLO(...).export(format="onnx")` or direct `.pt` fetch; verify against Ultralytics release checksums when published. Attempt placeholders (`models/yolo26n.onnx` 10,741,399 B, `yolo26s.onnx` identical size) are suspect duplicates — **do not trust**. |
| Code license | **AGPL-3.0** (`ultralytics/ultralytics` LICENSE, `ultralytics/yolo26` LICENSE) — source at `github.com/ultralytics/ultralytics` |
| Weight license | **AGPL-3.0** by default for Ultralytics trained models (per https://www.ultralytics.com/license FAQ: "All Ultralytics YOLO trained models fall under AGPL-3.0 by default") — **separate from code** but same terms |
| Training data | COCO 2017 (80 classes). Fine-tune data for IBVAP: none yet; use COCO-pretrained as-is. |
| Approved use | **PENDING GATE** — depends on AGPL vs Enterprise decision (ADR-0004). Academic/personally-open-sourced evaluation = AGPL-acceptable; closed commercial/product SaaS/embedded IBVAP = **requires Enterprise license** or permissive alternative (RF-DETR). |
| Input/output | Input: `[1,3,640,640]` RGB normalized [0,1], letterboxed (spec §11). Output: YOLO26 native **NMS-free** end-to-end ` [N,6]` (`x1,y1,x2,y2,score,class_id`) OR `[N,84]` legacy fallback. See `attempt/src/sentinel/detectors/objects.py:80-187` postprocess branches. |
| Preprocessing | Letterbox preserve aspect, pad 114, RGB, CHW, /255. Scale/pad recorded per frame for source-box remap. |
| Thresholds | `confidence_threshold 0.40` (IBVAP default §12), NMS only if legacy output (`sv.Detections.with_nms(0.5)`). |
| Runtime | `onnxruntime` CPU baseline; `openvino` Intel; `tensorrt` NVIDIA. Export verified: ONNX, OpenVINO, TensorRT per docs (see research). |
| Evaluation | **PENDING** — must measure precision/recall @640 on IBVAP footage; CPU ONNX 38.9ms (n) cited per docs table, not IBVAP measured. |
| Known limitations | **Does NOT detect faces or plates** (§4). Only COCO vehicle subset; no make/model. `yolo26n.pt` STAL small-target; low-light RGB not IR. |
| Approval status | `gate-blocked-until-license-decision` |

**Licensing gate excerpt (see ADR-0004):** Ultralytics dual-licenses AGPL-3.0 vs Enterprise. FAQ triggers Enterprise for: closed-source commercial product, SaaS/API behind scenes, embedded hardware/edge, internal private tools not open-sourced, fine-tuned proprietary use. IBVAP as border security platform — if deployed as closed/commercial/government proprietary system without open-sourcing entire derivative work — **conflicts with AGPL §13 (network use = distribution)**. Must resolve before `uv add ultralytics` in product repo.

**If blocked, documented alternative:** RF-DETR (Roboflow, ICLR 2026, Apache-2.0, DINOv2) — first >60 mAP COCO, permissive weights. Compare perf/export cost per ADR-0004 §5.

### 2.2 Face Detection — YuNet + SFace (OpenCV Zoo)

| Field | Value |
|-------|-------|
| Artifacts | `face_detection_yunet_2023mar.onnx` (232,589 B, present in `attempt/models`) + `face_recognition_sface_2021dec.onnx` (38,696,353 B) |
| Task | `face-detect` (YuNet) → 5 landmarks + `face-embed` (SFace 512-d, 112×112 aligned) |
| Source URL | OpenCV Zoo — `https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx` + `…/face_recognition_sface/…` |
| SHA-256 | **PENDING** — compute after fresh fetch; do not trust attempt's files without re-hash |
| Code license | OpenCV Zoo code: **Apache-2.0** |
| Weight license | **Pending legal review** — OpenCV Zoo weights historically permissive but must verify per-artifact LICENSE in `opencv_zoo` repo; YuNet/SFace weights have separate terms from code. InsightFace SCRFD/ArcFace alternative weights flagged as **non-commercial** — do not use InsightFace pretrained packs without separate review (§15). |
| Training data | WIDER FACE (YuNet), CASIA/WebFace (SFace) — verify. |
| Approved use | **pending-legal** — face detection approved for metadata; **facial identity matching disabled by default** per spec §15 gate (requires legal/privacy approval, RBAC, encryption, bias eval). |
| Input/output | YuNet: input dynamic size `(w,h)`, output `[N,15]` (x,y,w,h + 5×(x,y) + score). SFace: input aligned `112×112`, output 128-d or 512-d normalized embedding. |
| Preprocessing | BGR input, dynamic `setInputSize((w,h))`; SFace align via `alignCrop`. |
| Thresholds | YuNet `confidence 0.65`, SFace `match_threshold 0.363` (cosine). Probe gate: min face 20px. |
| Runtime | OpenCV DNN (`cv2.FaceDetectorYN`/`FaceRecognizerSF`) — CPU; no ORT path needed. |
| Known limitations | Not a liveness detector; low-light/occlusion degrades; must not infer intent/ethnicity. SCRFD placeholder `scrfd_2.5g_bnkps.onnx` 532 B in `attempt` is **invalid** — ignore. |

### 2.3 Plate Detection — Dedicated Plate Detector

| Field | Value |
|-------|-------|
| Artifact | `plate_detector_nano.onnx` (**479 B placeholder — INVALID**, per `attempt/models` listing) |
| Task | `plate-detect` (crop from vehicle) |
| Source | TBD — candidate `fast-alpr` YOLO plate detector (65+ jurisdictions, MIT) OR fine-tuned YOLO26-Nano. Spec §16 requires dedicated detector. |
| Status | **MISSING** — no valid artifact in prototype; must acquire permissive license (Apache-2.0/MIT) with jurisdictional evaluation (fast-alpr 0.4.0) or train own. |
| SHA-256 | — |
| Code/Weight license | Must be **permissive** (Apache-2.0/MIT) — record both |
| Approved use | `blocked-until-artifact-acquired` |

### 2.4 Plate OCR — PaddleOCR PP-OCRv6 (Candidate)

| Field | Value |
|-------|-------|
| Artifact | PaddleOCR 3.7.0 PP-OCRv6 pipeline (`det` + `rec` models auto-downloaded to `models/easyocr` equivalent dir) |
| Task | `ocr` (crop → text) |
| Source URL | `pip install paddleocr` + models from HuggingFace/BOS per `paddleocr.dev`; `paddleocr==3.7.0` |
| Code license | **Apache-2.0** (PaddleOCR); PaddlePaddle `2.5+` framework Apache-2.0 |
| Weight license | **Apache-2.0** (PP-OCRv6 weights per paddleocr.ai) — verify per `PP-OCRv6` model card |
| Training data | Paddle private + open OCR datasets; 50-language unified |
| Input/output | Input: rectified plate crop; Output: text + per-char confidence; handles O/0 I/1 ambiguous via jurisdiction config |
| Thresholds | Quality gates: min 4 chars, max 12, char confidence, perspective/blur gates per spec §16 |
| Runtime | Paddle Inference or ONNX Runtime after export; OpenVINO speedup noted. For IBVAP, ONNX-extractable path preferred. |
| Known limitations | Universal plate support not claimed; jurisdiction-aware validation required; multi-frame consensus needed. |
| Alternative | `easyocr 1.7.2` (attempt fallback) — **rejected as primary** (maintenance mode). |

### 2.5 Low-Light Enhancement — CLAHE + Multinex Nano (Experimental)

| Field | Value |
|-------|-------|
| Artifact | `multinex_nano.onnx` (**137 B placeholder — INVALID**) claimed CVPR 2026 0.7K params Retinex |
| Source | Research paper/GitHub (CVPR 2026) — must verify ONNX export before selection |
| License | Need to verify (research/MIT) — do not assume |
| Status | **experimental-disabled-by-default** (§13); fallback Zero-DCE++ (~10K params, MIT) documented in `attempt/docs/004` |

---

## 3. Model Download & Verification Policy

1. **No silent download in production.** `ModelManager.ensure_model()` must raise `FileNotFoundError` with actionable message if artifact missing; only explicit CLI `setup --weights` or admin endpoint (with audit) downloads.
2. **Input-dependent validation.** Per `attempt/src/sentinel/core/models.py:_is_valid_onnx_model` — graph output must depend on image input; constant-only graphs rejected. IBVAP must port this.
3. **SHA-256 recorded.** After fetch, compute `hashlib.sha256(file.read()).hexdigest()` and compare to registry; store in `model_artifacts.sha256`.
4. **Separate code/weight licenses reviewed.** AGPL copyleft weights cannot be silently bundled into proprietary binary distribution.
5. **Evaluation before promotion.** Each artifact needs `docs/evaluation/<artifact>.md` with precision/recall/ID switches/ANPR CER measured on IBVAP footage (spec §27).

---

## 4. Pending Actions (Phase 0 → Phase 1)

- [ ] Fetch fresh `yolo26n.pt`/`yolo26s.pt` from Ultralytics release; export to ONNX via `YOLO(...).export(format="onnx", imgsz=640)`; record SHA-256 and file size (expected ~10-20 MB ONNX, not 479 B placeholders).
- [ ] Confirm YuNet/SFace SHA-256 from OpenCV Zoo release.
- [ ] Acquire or train dedicated plate detector ONNX (fast-alpr or YOLO26-nano-plate); record license.
- [ ] Evaluate PaddleOCR 3.7.0 vs EasyOCR on plate crops; lock choice.
- [ ] Legal review: InsightFace weight non-commercial clause if SCRFD considered.

---

*Registry is source of truth for `GET /api/v1/models` and `docs/traceability.md` model provenance columns.*
