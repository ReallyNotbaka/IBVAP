from __future__ import annotations

from ibvap.models import Base, Camera


def test_models_import_and_tables() -> None:
    # Ensure tables are defined
    table_names = {t.name for t in Base.metadata.tables.values()}
    assert "organizations" in table_names
    assert "sites" in table_names
    assert "cameras" in table_names
    assert "outbox" in table_names


def test_uuid_generation() -> None:
    from ibvap.models import _uuid7

    a = _uuid7()
    b = _uuid7()
    assert a != b
    assert isinstance(a, type(b))


def test_camera_defaults() -> None:
    # stream_epoch column has server_default 0 - instance may be None before flush
    assert Camera.__table__.c.stream_epoch.default is not None
    assert True
