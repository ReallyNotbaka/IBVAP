import hashlib
from pathlib import Path
from typing import Any

import pytest

EXPECTED_MODELS: dict[str, dict[str, Any]] = {
    "yolo26n.onnx": {
        "min_size": 10_000_000,
        "max_size": 12_000_000,
        "sha256": "5738273eeaddb82150cb75f5a70b75c0651f792a82afcf6c8b4819c038ca57bd",
    },
    "face_detection_yunet_2023mar.onnx": {
        "min_size": 200_000,
        "max_size": 300_000,
        "sha256": "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
    },
    "face_recognition_sface_2021dec.onnx": {
        "min_size": 35_000_000,
        "max_size": 40_000_000,
        "sha256": "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
    },
}

MODELS_DIR = Path(__file__).resolve().parent.parent / "models"


@pytest.mark.parametrize("model_name,expected_info", EXPECTED_MODELS.items())
def test_model_artifact_exists_and_valid(model_name: str, expected_info: dict[str, Any]):
    model_path = MODELS_DIR / model_name
    assert model_path.exists(), f"Model file {model_name} missing in {MODELS_DIR}"

    size = model_path.stat().st_size
    min_size = int(expected_info["min_size"])
    max_size = int(expected_info["max_size"])
    assert min_size <= size <= max_size, f"Model {model_name} size {size} not within [{min_size}, {max_size}]"

    hasher = hashlib.sha256()
    with open(model_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            hasher.update(chunk)
    actual_hash = hasher.hexdigest().lower()

    assert actual_hash == expected_info["sha256"], f"Model {model_name} hash mismatch: got {actual_hash}, expected {expected_info['sha256']}"
