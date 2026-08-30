from __future__ import annotations

from pathlib import Path

from ibvap.config import DBConfig, Settings


def test_default_settings_load() -> None:
    # Internal defaults check
    db_default = DBConfig()
    assert db_default.url.startswith("postgresql+asyncpg://")
    assert "localhost:5432" in db_default.url

    s = Settings()
    assert s.app.name == "IBVAP"
    assert s.app.version == "0.1.0"
    assert s.app.port == 8000
    assert s.db.url.startswith("postgresql+asyncpg://") or s.db.url.startswith("sqlite+aiosqlite://")
    assert s.media.mediamtx_api_url.startswith("http://")


def test_yaml_config_loading(tmp_path: Path) -> None:
    yaml_content = """
app:
  name: IBVAP-test
  port: 9000
db:
  url: postgresql+asyncpg://u:p@host/db
"""
    p = tmp_path / "cfg.yaml"
    p.write_text(yaml_content, encoding="utf-8")
    s = Settings.load(str(p))
    assert s.app.name == "IBVAP-test"
    assert s.app.port == 9000
    assert s.db.url == "postgresql+asyncpg://u:p@host/db"


def test_missing_yaml_returns_defaults(tmp_path: Path) -> None:
    p = tmp_path / "nonexistent.yaml"
    s = Settings.load(str(p))
    assert s.app.name == "IBVAP"


def test_cors_origins_not_wildcard() -> None:
    s = Settings()
    assert "*" not in s.app.cors_origins

    assert len(s.app.cors_origins) >= 1
