# ADR-0003: Inference Runtime — ONNX Runtime Baseline + Isolated Accelerators

- **Status:** Accepted (Phase 0)
- **Date:** 2026-08-30
- **Spec:** §5 Inference, §27 Benchmarks, §28 Deployment

## Context

Spec requires CPU-only deployment with optional hardware acceleration (§5) via three isolated paths:
- **Portable baseline:** ONNX Runtime
- **Intel:** OpenVINO profile for supported Intel systems
- **NVIDIA:** TensorRT or ONNX Runtime CUDA profile

And separate `CPU / OpenVINO / NVIDIA` deployment images/extras — **do not install every accelerator into one environment**.

## Decision

### Baseline (every image)

- **ONNX Runtime 1.29.0** (MIT, 2026-08-12) as baseline — via `onnxruntime` package.
- **onnx 1.22.0** checker for graph validation (`onnx.checker.check_model`) and `is_model_downloaded` input-dependent test ported from `attempt/src/sentinel/core/models.py:140-169`.
- **FP16** on GPU where supported; CPU uses FP32 (auto).
- All YOLO26/plate/PaddleOCR models exported to ONNX (`opset 17+`, `dynamic=False, imgsz=640`), inputs `[1,3,640,640]`.

### Isolation

```
pyproject.toml groups
  [project.dependencies]           → onnxruntime>=1.29.0, onnx>=1.22.0 (baseline)

  [project.optional-dependencies]
    openvino  → openvino>=2026.3.0
    cuda      → onnxruntime-gpu>=1.29.0  (TensorRT EP, CUDA 12.x)

compose profiles
  dev / cpu        → baseline only
  openvino         → + openvino extras, image build-args OPENVOINO_VERSION=2026.3
  cuda             → + cuda extras, base nvidia/cuda:12.x-runtime, TRT 11.2.1
```

**Provider selection per image (ORT `session.get_providers()`):**
- CPU: `CPUExecutionProvider`
- OpenVINO: `OpenVINOExecutionProvider` (+ fallback `CPUExecutionProvider`)
- CUDA: `CUDAExecutionProvider` or `TensorrtExecutionProvider` (+ fallback)

Windows dev hosts may use `onnxruntime-directml` (`DmlExecutionProvider`) as `cpu` Windows variant — not in Linux images.

### Model hot-swap (from prototype)

Port `attempt/src/sentinel/core/inference.py` pattern:
- `InferenceEngine` with `threading.Lock`, `available_providers` check, `_create_session` with `SessionOptions(graph_optimization_level=ORT_ENABLE_ALL, intra_op_num_threads=4)`, GPU fallback to CPU on load failure, warm-up `np.zeros((1,3,640,640))`.

### Export matrix (validated at `docs.ultralytics.com/models/yolo26`)

- YOLO26 supports export: **ONNX ✓**, **OpenVINO ✓**, **TensorRT ✓**, CoreML, TFLite — document which are validated in IBVAP (ONNX mandatory, OpenVINO/TensorRT validated in Phase 8).

## Consequences

- Dependency resolver stays tractable (no 2GB CUDA wheel collision in `dev`).
- Benchmarks (§27) must record: CPU/RAM/GPU/VRAM/OS/kernel/driver/container-runtime/model-checksum/ORT version/precision/input-dims/camera-res/FPS — per device profile.
- CPU degradation order (§28) is respected: lower FPS → lower resolution → disable experimental → disable face embed → preserve human/vehicle + health — implemented in scheduler, not just docs.

## Alternatives Considered

| Alt | Why rejected |
|-----|--------------|
| Single env with ORT+OpenVINO+CUDA | Spec explicitly forbids; manylinux wheel conflicts + 2GB GPU dep bloat |
| PyTorch direct (no ONNX) | Not portable across CPU/OpenVINO/TensorRT; spec mandates ONNX baseline |
| OpenVINO-only baseline | Intel vendor lock; not portable to ARM/AMD or thermal edge without Intel |

## Validation

- Soak (§27): 24h CPU profile bounded memory; `GPUUnavailable` chaos test must surface `system.degraded` not silently fall back to CPU (`Never silently fall back from GPU to CPU without reporting it` — §28).
- CI: `pytest -k test_model_ort_session_providers_cpu` + `pytest -k test_model_openvino_export_validates`.

## Upgrade Plan

- Track ORT monthly releases at `github.com/microsoft/onnxruntime/releases`; pin `1.29.0` now, trial `1.30.x` in feature branch with `uv lock --upgrade-package onnxruntime`.
- OpenVINO: 2026.3 → 2026.4 when 2026.4 publishes (Intel cadence ~quarterly).

---

*Evidence:* `docs/research/version-evidence.md:6`, `docs/research/technology-comparison.md:6`, spec §5.
