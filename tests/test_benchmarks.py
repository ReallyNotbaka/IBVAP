from __future__ import annotations

import pytest

from scripts.benchmark import (
    benchmark_decoder,
    benchmark_face_detector,
    benchmark_face_recognizer,
    benchmark_onnx_detector,
    benchmark_tracker,
    generate_markdown_report,
    get_system_info,
    run_system_benchmarks,
)


def test_system_info_detection() -> None:
    info = get_system_info()
    assert isinstance(info, dict)
    assert "os" in info and len(info["os"]) > 0
    assert "cpu" in info and len(info["cpu"]) > 0
    assert "logical_cores" in info and info["logical_cores"] > 0
    assert "ram_gb" in info and info["ram_gb"] >= 0.0
    assert "gpu" in info
    assert "ort_version" in info
    assert "ort_providers" in info
    assert isinstance(info["ort_providers"], list)


def test_benchmark_onnx_detector_cpu() -> None:
    res = benchmark_onnx_detector(model_path="models/yolo26n.onnx", runs=3, provider="CPUExecutionProvider")
    assert isinstance(res, dict)
    assert res["model"] == "models/yolo26n.onnx"
    assert res["provider"] == "CPUExecutionProvider"
    assert res["runs"] == 3
    assert res["mean_ms"] > 0.0
    assert res["p50_ms"] > 0.0
    assert res["p95_ms"] > 0.0
    assert res["p99_ms"] > 0.0
    assert res["fps"] > 0.0


def test_benchmark_onnx_detector_dml() -> None:
    info = get_system_info()
    if "DmlExecutionProvider" in info["ort_providers"]:
        res = benchmark_onnx_detector(model_path="models/yolo26n.onnx", runs=3, provider="DmlExecutionProvider")
        assert isinstance(res, dict)
        assert res["provider"] == "DmlExecutionProvider"
        assert res["mean_ms"] > 0.0
        assert res["fps"] > 0.0
    else:
        pytest.skip("DmlExecutionProvider not available on this host")


def test_benchmark_face_detector() -> None:
    res = benchmark_face_detector(model_path="models/face_detection_yunet_2023mar.onnx", runs=3)
    assert isinstance(res, dict)
    assert res["model"] == "models/face_detection_yunet_2023mar.onnx"
    assert res["mean_ms"] > 0.0
    assert res["p50_ms"] > 0.0
    assert res["fps"] > 0.0


def test_benchmark_face_recognizer() -> None:
    res = benchmark_face_recognizer(model_path="models/face_recognition_sface_2021dec.onnx", runs=3)
    assert isinstance(res, dict)
    assert res["model"] == "models/face_recognition_sface_2021dec.onnx"
    assert res["mean_ms"] > 0.0
    assert res["p50_ms"] > 0.0
    assert res["fps"] > 0.0


def test_benchmark_tracker() -> None:
    res = benchmark_tracker(runs=10)
    assert isinstance(res, dict)
    assert res["mean_ms"] > 0.0
    assert res["fps"] > 0.0


def test_benchmark_decoder() -> None:
    res = benchmark_decoder(runs=15)
    assert isinstance(res, dict)
    assert res["total_frames"] >= 15
    assert res["mean_ms"] > 0.0
    assert res["fps"] > 0.0


def test_run_system_benchmarks_full() -> None:
    results = run_system_benchmarks(num_runs=3)
    assert "system_info" in results
    assert "benchmarks" in results
    assert "timestamp" in results

    b = results["benchmarks"]
    assert "onnx_detector_cpu" in b
    assert "yunet_face_detector" in b
    assert "sface_recognizer" in b
    assert "centroid_tracker" in b
    assert "pyav_decoder" in b

    report = generate_markdown_report(results)
    assert "# IBVAP Hardware Performance Benchmarks" in report
    assert "AMD Ryzen 7 7435HS" in report or results["system_info"]["cpu"] in report
    assert "Execution Latency & Throughput" in report
