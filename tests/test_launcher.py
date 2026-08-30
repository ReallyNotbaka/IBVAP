from __future__ import annotations

from pathlib import Path

from run import bootstrap_environment, build_banner, parse_args


def test_parse_args_defaults() -> None:
    args = parse_args([])
    assert args.host == "127.0.0.1"
    assert args.port == 8000
    assert args.reload is False
    assert args.no_browser is False
    assert args.check is False


def test_parse_args_custom() -> None:
    args = parse_args(["--host", "0.0.0.0", "--port", "9000", "--reload", "--no-browser", "--check"])
    assert args.host == "0.0.0.0"
    assert args.port == 9000
    assert args.reload is True
    assert args.no_browser is True
    assert args.check is True


def test_bootstrap_environment(tmp_path: Path) -> None:
    # Setup mock root
    root = tmp_path / "app"
    root.mkdir()
    (root / ".env.example").write_text("IBVAP_DB__URL=sqlite+aiosqlite:///data/ibvap.db\n", encoding="utf-8")
    models_dir = root / "models"
    models_dir.mkdir()
    (models_dir / "yolo26n.onnx").write_bytes(b"mock-yolo")

    env_file = root / ".env"
    assert not env_file.exists()

    env_created = bootstrap_environment(root)
    assert env_created is True
    assert env_file.exists()
    assert "sqlite+aiosqlite" in env_file.read_text(encoding="utf-8")


def test_build_banner() -> None:
    banner = build_banner("127.0.0.1", 8000)
    assert "IBVAP" in banner
    assert "http://localhost:8000" in banner
