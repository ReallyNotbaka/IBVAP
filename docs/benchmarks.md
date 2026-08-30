# IBVAP Benchmarks — Phase 8 (Not yet measured)

**Status:** No claim until measured. This doc is a template per spec 27.

## Required record per run

CPU, RAM, GPU, VRAM, OS/kernel, driver, container runtime, model checksum, ORT version, precision, input dims (640), camera res/FPS/codec, stream count, analysis FPS, thermal.

## Metrics to measure

- Decode FPS, analyzed FPS
- p50/p95/p99 inference latency
- End-to-end alert latency
- Overlay staleness
- Queue depth / drops
- CPU/RAM/GPU/VRAM, storage/network throughput
- Reconnect time, event duplication/loss
- Evidence generation time
- Sustainable stream count

## Analytics evaluations

- Detection precision/recall
- False alerts per camera-hour
- Tracking ID switches/fragmentation
- ANPR exact-string, CER, false-positive, day/night/distance/angle/blur/weather
- Face FAR/FNMR only if gate passes (currently disabled)

No universal "supports N cameras" claim — capacity depends on hardware/codec/res/analysis cadence/model/runtime.

## Current state (honest)

- Synthetic pipeline (MockPersonDetector + centroid tracker) processes 30 frames → 1+ intrusion events, 10-16 frame video → 1+ events (test_pipeline.py).
- No real YOLO weights exercised due to ADR-0004 BLOCKED. No GPU benchmark.
- `uv run pytest` 63 tests green; frontend 93 modules transformed (264kB JS) — not benchmarked on edge hardware.
