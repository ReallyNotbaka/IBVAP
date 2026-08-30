"""CLI entry - ibvap."""

from __future__ import annotations

import argparse

import uvicorn

from ibvap.config import Settings


def main() -> None:
    parser = argparse.ArgumentParser(description="IBVAP — Intelligent Border Video Analytics Platform")
    parser.add_argument("--host", type=str, default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()
    cfg = Settings()
    host = args.host or cfg.app.host
    port = args.port or cfg.app.port
    uvicorn.run("ibvap.api.app:create_app", factory=True, host=host, port=port, reload=args.reload)


if __name__ == "__main__":
    main()
