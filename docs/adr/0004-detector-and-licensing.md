# ADR-0004: Detection & Licensing — YOLO26 Primary with AGPL Gate

- **Status:** Pending-Ratification (Phase 0 gate report)
- **Date:** 2026-08-30
- **Spec:** §4 YOLO26 Requirement and License Gate, §12 Human/Vehicle Analytics
- **Owners:** Legal / Engineering (must jointly ratify before integration)

## Context

Spec §4 mandates Ultralytics YOLO26 as primary general object detector **subject to a mandatory licensing decision**. The five expected variants `yolo26{ n,s,m,l,x }.pt` are verified real at `docs.ultralytics.com/models/yolo26` (five scales; architecture-only `yolo26-p2.yaml`/`p6.yaml` are YAML-only, not separate weights).

Reference facts (web-verified 2026-08-30):

| Fact | Evidence |
|------|----------|
| Release | 2026-01-14 (Ultralytics blog + docs hero "Newest SOTA … released January 2026") |
| Package | `ultralytics>=8.4.0` upgrade required; attempt pins `8.4.135` |
| COCO classes | Weights cover `person, bicycle, car, motorcycle, bus, truck` among 80 COCO; face & plate are NOT covered |
| NMS-free / DFL-free | Documented: "Native end-to-end inference without NMS by default; DFL-free regression and lighter head" at `docs.ultralytics.com/models/yolo26` |
| Export | ONNX, OpenVINO, TensorRT, CoreML, LiteRT per same page; "Flexible export formats" |
| Tracker compatibility | ByteTrack/BoT-SORT via `ultralytics` + `supervision` — confirmed in attempt `detectors/objects.py:179` `with_nms` path and tracking at `tracking/tracker.py` |
| Code+weight license link | `github.com/ultralytics/yolo26` lists `License: AGPL-3.0` (both code and hub banner: "Open Source, AGPL-3.0") |

## Licensing — Primary Finding (Gate)

**Ultralytics dual-licensing:** All Ultralytics YOLO code and **trained models** are AGPL-3.0 by default; Enterprise license is required for closed/commercial use.

Canonical source: `https://www.ultralytics.com/license` (retrieved 2026-08-30):

> "AGPL-3.0 covers a lot of use cases — but there are specific triggers that require an Ultralytics Enterprise license."  
> Triggers include: **Internal business tools or private company applications; any commercial product or service; proprietary/closed-source software; SaaS platforms/APIs/cloud systems using YOLO behind the scenes; embedded deployments in hardware/edge/robotics/cameras/appliances; using custom-trained/fine-tuned YOLO models in proprietary/commercial setting; customer-facing solutions where you do not want to publish code; R&D projects that are not fully open-sourced.**  
> FAQ: **"Are Ultralytics YOLO trained models licensed under AGPL-3.0? Yes. All Ultralytics YOLO trained models fall under AGPL-3.0 by default. The AGPL-3.0 covers the training code and models produced by that training code."**

AGPL-3.0 §13 (Affero, network use): Making IBVAP available over a network to border operators **is distribution** — IBVAP must offer Corresponding Source (entire derivative work, not just YOLO) to every operator who can interact with it, if AGPL-licensed.

IBVAP mission (spec §1) is a **government border security platform** — government/commercial deployment with closed source. Under Ultralytics guidance, that is per se an Enterprise trigger (private deployment, internal tools, embedded camera edge, not open-sourced R&D).

**Conclusion:** IBVAP's **intended deployment conflicts with pure AGPL obligations** unless the entire IBVAP product is open-sourced under AGPL-3.0. Maintaining IBVAP as closed/proprietary without an Enterprise grant is **incompatible**.

## Decision (Branch)

### Branch A — Enterprise Granted (Preferred if sponsor funds)

- Acquire **Ultralytics Enterprise License** (contact https://www.ultralytics.com/license — sales responds ~24h). Scope: per-project or org-wide, term-bound, covers YOLO26 + future Ultralytics releases + hub.
- Then proceed per spec §4→§5: integrate YOLO26 as `DetectorProvider` default, record grant in `docs/compliance/model-registry.md` line for `yolo26*`, commit no AGPL tarball into product image without attribution.
- Document grant reference (quote ID) in `docs/compliance/third-party-licenses.md §4` and `model-registry.md` weight license column (`AGPL-3.0; Enterprise grant <ID> on <date>`).

### Branch B — AGPL Blocked / No Grant (Required Alternative)

If no Enterprise license is secured:

1. **Stop YOLO26 integration in `product/`.** Keep `detector` work in isolated `attempt/` research dir only — do NOT `uv add ultralytics` or commit `.pt` weights to `product/`.
2. **Preserve `DetectorProvider` interface** (vendor-neutral) — YOLO26 becomes an unactivated provider implementation.
3. **Research permissively licensed alternatives** with pass/fail on code AND weight licenses, performance, export, migration cost. Documented alternative at 2026-08-30:
   - **RF-DETR (Roboflow, ICLR 2026) — Apache-2.0 code + Apache-2.0 weights, DINOv2 backbone, first >60 mAP COCO (60.1), transformer.** Pros: permissive, SOTA accuracy. Cons: heavier on GPU memory/CPU ms vs YOLO26 NMS-free. Already in `docs/research/technology-comparison.md`.
   - Other 2026 Apache-2.0 candidates: D-FINE (~100+ FPS T4, Apache-2.0), RT-DETRv4 (ECCV 2026, Apache-2.0, but research-tooling heavy). **YOLO-NAS is frozen** (Deci→NVIDIA) — not recommended.
4. **Do not silently substitute.** Explicit ratification meeting per spec §4 `11-7` before swapping.
5. Continue Phase 1–2 (DB, API, ingestion, rules) while gate is pending; defer Phase 3 YOLO slice until ratified.

## Consequences of Either Branch

- Phase 3 E2E slice spec — "One actual video must create one persisted event" — depends on whichever detector is ratified. Scope Phase 3 to that branch.
- Geo/design: §12 vehicle classes remain only COCO-supported subset; make/model recognition stays unclaimed (§12: "Do not claim vehicle make/model recognition unless separate classifier…").
- §11 geometry, §13 rules, §17 outbox are detector-agnostic and can proceed.

## Evaluation Required Before Claiming Readiness

- Re-verify artifact names (done): five `yolo26{ n,s,m,l,x }.pt` confirmed; `yolo26-p2.yaml`/`p6.yaml` are ARCHITECTURE-ONLY not weights (attempt docs warned).
- Export smoke: `YOLO("yolo26n.pt").export(format="onnx", imgsz=640)` → ONNX with `output0` of shape batch-disconnected; verify DFL-free behavior via net inspection.
- ByteTrack compat: run `supervision.ByteTracker` on YOLO26 detections — confirmed in prototype `tracking/tracker.py`.

## Approval Status

- **Gate:** **BLOCKED-UNTIL-ENTERPRISE-GRANT-OR-APACHE-ALTERNATIVE-RATIFIED** — recorded as `gate-blocked-until-license-decision` in `docs/compliance/model-registry.md:2.1`.
- **No `product/pyproject.toml` may list `ultralytics` until ratified.** CIPipeline must fail if `ultralytics` appears without grant reference file.

---

*Sources:* `docs.ultralytics.com/models/yolo26`, `platform.ultralytics.com/ultralytics/yolo26`, `www.ultralytics.com/license` FAQ, `github.com/ultralytics/yolo26` LICENSE, `attempt/docs/decisions/001-detection-tracking-backbone.md` prior comparison.
