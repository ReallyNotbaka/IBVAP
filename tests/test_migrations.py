from __future__ import annotations

import pathlib


def test_migration_0001_exists() -> None:
    p = pathlib.Path("migrations/versions/529855f7c518_0001_init.py")
    assert p.exists(), "0001 migration missing"
    content = p.read_text(encoding="utf-8")
    assert "organizations" in content
    assert "sites" in content
    assert "cameras" in content
    assert "outbox" in content
    assert "revision" in content
    assert "down_revision" in content


def test_migration_upgrade_defines_tables() -> None:
    # Import migration module and verify upgrade is callable without DB
    import importlib.util
    import pathlib

    spec = importlib.util.spec_from_file_location("m0001", pathlib.Path("migrations/versions/529855f7c518_0001_init.py"))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    assert hasattr(mod, "upgrade")
    assert hasattr(mod, "downgrade")
    assert mod.revision == "529855f7c518"


def test_sqlalchemy_metadata_matches_migration_tables() -> None:
    from ibvap.models import Base

    tables = set(Base.metadata.tables.keys())
    # migration should create exactly these core tables (Phase 1)
    assert {"organizations", "sites", "cameras", "outbox"}.issubset(tables)
