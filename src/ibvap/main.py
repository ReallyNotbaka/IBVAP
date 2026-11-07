"""CLI entry - ibvap."""

from __future__ import annotations

import argparse
import contextlib
import os

import uvicorn

from ibvap.config import Settings


def main() -> None:
    parser = argparse.ArgumentParser(description="IBVAP — Intelligent Border Video Analytics Platform")
    parser.add_argument("--host", type=str, default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    with contextlib.suppress(Exception):
        from dotenv import load_dotenv

        load_dotenv(".env", override=False)

    os.environ.setdefault("IBVAP_API_TOKEN", "ibvap-local-dev-token")
    os.environ.setdefault("IBVAP_CREDENTIAL_KEY", "ibvap-local-dev-credential-key-32b")
    os.environ.setdefault("IBVAP_DB__ALLOW_SQLITE_FALLBACK", "1")
    os.environ.setdefault(
        "IBVAP_MEDIA__SITE_CIDR_ALLOWLIST",
        '["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10"]',
    )

    cfg = Settings()
    host = args.host or cfg.app.host
    port = args.port or cfg.app.port
    uvicorn.run("ibvap.api.app:create_app", factory=True, host=host, port=port, reload=args.reload)


if __name__ == "__main__":
    main()
