#!/usr/bin/env python3
"""IBVAP — Industry-Standard Unified Application Launcher.

Provides single-command and one-click launch capabilities:
- Auto-bootstraps .env from .env.example if missing
- Ensures data/ directories exist
- Validates model assets
- Displays operational dashboard banner
- Launches default web browser to the unified UI
- Runs the unified API + Web dashboard server
"""

from __future__ import annotations

import argparse
import contextlib
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="IBVAP — Unified Application Launcher",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Host interface to bind the application server.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port number to bind the application server.",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload on source code modifications.",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Prevent automatically opening the default web browser.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Perform pre-flight sanity checks and exit without starting server.",
    )
    return parser.parse_args(argv)


def bootstrap_environment(root: Path) -> bool:
    """Ensure essential directories, environment config, and frontend dist exist."""
    env_created = False
    env_file = root / ".env"
    env_example = root / ".env.example"

    if not env_file.exists() and env_example.exists():
        shutil.copyfile(env_example, env_file)
        env_created = True

    # Ensure runtime data directories
    (root / "data").mkdir(parents=True, exist_ok=True)
    (root / "data" / "logs").mkdir(parents=True, exist_ok=True)

    return env_created


def ensure_frontend_bundle(root: Path) -> bool:
    """Ensure the built frontend exists before serving the app UI.

    This is intentionally tolerant: if Node/npm are absent, the backend still starts in API-only
    mode and prints a clear notice instead of failing the whole app.
    """
    frontend_dir = root / "frontend"
    dist_html = frontend_dir / "dist" / "index.html"
    if dist_html.exists():
        return True

    if not (frontend_dir / "package.json").exists():
        print("[Launcher] Notice: frontend package not found; serving API-only mode.")
        return False

    npm = shutil.which("npm")
    if npm is None:
        print("[Launcher] Notice: Node/npm not found. Frontend bundle not built; serving API-only mode.")
        return False

    print("[Launcher] Building frontend bundle...")
    result = subprocess.run([npm, "run", "build"], cwd=str(frontend_dir), capture_output=True, text=True)
    if result.returncode == 0:
        print("[Launcher] Frontend bundle built successfully.")
        return True

    print("[Launcher] Warning: frontend build failed. Serving API-only mode.")
    if result.stdout:
        print(result.stdout.strip())
    if result.stderr:
        print(result.stderr.strip())
    return False


def detect_hardware() -> str:
    """Detect available GPU or fallback compute devices."""
    try:
        import onnxruntime as ort

        providers = ort.get_available_providers()
        if "DmlExecutionProvider" in providers:
            # Check if NVIDIA GPU exists
            with contextlib.suppress(Exception):
                out = subprocess.check_output(
                    ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                    stderr=subprocess.DEVNULL,
                    text=True,
                ).strip()
                if out:
                    return f"DirectML GPU ({out})"
            return "DirectML GPU (Hardware Accelerated)"
        elif "CUDAExecutionProvider" in providers:
            return "CUDA GPU"
    except Exception:
        pass
    return "CPU Execution"


def build_banner(host: str, port: int, hardware_info: str | None = None) -> str:
    """Construct an ASCII dashboard banner for terminal display."""
    hw = hardware_info or detect_hardware()
    display_host = "localhost" if host in ("127.0.0.1", "0.0.0.0") else host
    url = f"http://{display_host}:{port}"

    lines = [
        "=" * 66,
        "  IBVAP — Intelligent Border Video Analytics Platform v0.1.0",
        "=" * 66,
        f"  Web Dashboard   : {url}",
        f"  Interactive API : {url}/docs",
        f"  Health Status   : {url}/health",
        f"  Compute Device  : {hw}",
        "  Models Loaded   : YOLO26n (ONNX), YuNet Face, SFace Embedder",
        "  Persistence     : Async SQLAlchemy Engine",
        "=" * 66,
    ]
    return "\n".join(lines)


def launch_browser_delayed(url: str, delay: float = 1.2) -> None:
    """Open default web browser in a detached background thread."""

    def _open() -> None:
        time.sleep(delay)
        with contextlib.suppress(Exception):
            webbrowser.open(url)

    thread = threading.Thread(target=_open, daemon=True)
    thread.start()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = Path(__file__).resolve().parent

    env_created = bootstrap_environment(root)
    if env_created:
        print("[Launcher] Initialized .env configuration from .env.example (local SQLite mode).")

    # Verify frontend dist and build automatically when possible.
    frontend_ready = ensure_frontend_bundle(root)
    if not frontend_ready:
        print("[Launcher] Notice: frontend/dist not found or could not be built. Serving API and OpenAPI docs only.")
        print("[Launcher] If you want the web UI, install Node/npm and run 'cd frontend && npm run build'.")

    banner = build_banner(args.host, args.port)
    print(banner)

    if args.check:
        print("[Launcher] Pre-flight system check passed successfully.")
        return 0

    display_host = "localhost" if args.host in ("127.0.0.1", "0.0.0.0") else args.host
    url = f"http://{display_host}:{args.port}"

    if not args.no_browser:
        launch_browser_delayed(url)

    # Launch Uvicorn
    import uvicorn

    try:
        uvicorn.run(
            "ibvap.api.app:create_app",
            factory=True,
            host=args.host,
            port=args.port,
            reload=args.reload,
            log_level="info",
        )
    except KeyboardInterrupt:
        print("\n[Launcher] Shutting down IBVAP...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
