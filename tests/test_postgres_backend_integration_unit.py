"""Optional integration tests for Phase A4 Postgres backends.
Phase A4 Postgres 后端可选集成测试。

These tests are skipped unless ``LUMINA_INTEGRATION_DB_URL`` points at a
throwaway Postgres database. They apply the Alembic schema before running
and truncate the A4 tables around each test.
仅当 ``LUMINA_INTEGRATION_DB_URL`` 指向可丢弃的 Postgres 数据库时运行；测试前
应用 Alembic schema，并在每个用例前后清空 A4 表。
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Iterator

import numpy as np
import pytest


ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = ROOT / "api" / "migrations" / "alembic.ini"


def _integration_db_url() -> str:
    url = os.environ.get("LUMINA_INTEGRATION_DB_URL", "").strip()
    if not url:
        pytest.skip("LUMINA_INTEGRATION_DB_URL is not set")
    return url


@pytest.fixture()
def postgres_engine(monkeypatch: pytest.MonkeyPatch) -> Iterator[object]:
    """Create a migrated SQLAlchemy engine for an integration test.
    为集成测试创建已应用迁移的 SQLAlchemy engine。
    """
    pytest.importorskip("sqlalchemy")
    pytest.importorskip("psycopg")
    pytest.importorskip("alembic")
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text

    url = _integration_db_url()
    monkeypatch.setenv("LUMINA_DATABASE_URL", url)
    command.upgrade(Config(str(ALEMBIC_INI)), "head")
    engine = create_engine(url, pool_pre_ping=True)
    truncate_sql = text("TRUNCATE TABLE session_temp_files, files, sessions CASCADE")
    with engine.begin() as conn:
        conn.execute(truncate_sql)
    try:
        yield engine
    finally:
        with engine.begin() as conn:
            conn.execute(truncate_sql)
        engine.dispose()


def test_postgres_session_backend_crud_and_close(postgres_engine: object) -> None:
    """Postgres session backend should support CRUD, temp-file cleanup, and close.
    Postgres session 后端应支持 CRUD、临时文件清理和关闭。
    """
    from api.session_store_postgres import PostgresSessionBackend

    store = PostgresSessionBackend(ttl=30, engine=postgres_engine)
    session_id = store.create()
    store.put(session_id, "color_mode", "4-Color")
    store.put(session_id, "region_mask", np.array([[True, False]], dtype=np.bool_))
    store.put(session_id, "free_color_set", {"#000000", "#ffffff"})
    session_data = store.get(session_id)
    assert session_data is not None
    assert session_data["color_mode"] == "4-Color"
    np.testing.assert_array_equal(
        session_data["region_mask"],
        np.array([[True, False]], dtype=np.bool_),
    )
    assert session_data["free_color_set"] == {"#000000", "#ffffff"}

    fd, path = tempfile.mkstemp(suffix=".tmp")
    os.close(fd)
    store.register_temp_file(session_id, path)
    assert store.get_temp_file_paths(session_id) == [path]

    assert store.close(session_id) == 1
    assert store.exists(session_id) is False
    assert os.path.exists(path) is False
    assert session_id in store.get_registry_cleanup_candidate_session_ids()


def test_postgres_file_registry_register_resolve_and_cleanup(postgres_engine: object) -> None:
    """Postgres registry should register, resolve, and clean session files.
    Postgres registry 应能注册、解析并清理 session 文件。
    """
    from api.file_registry_postgres import PostgresFileRegistryBackend
    from api.session_store_postgres import PostgresSessionBackend

    store = PostgresSessionBackend(ttl=30, engine=postgres_engine)
    registry = PostgresFileRegistryBackend(engine=postgres_engine)
    session_id = store.create()

    fd, path = tempfile.mkstemp(suffix=".bin")
    os.write(fd, b"content")
    os.close(fd)

    file_id = registry.register_path(session_id, path, "artifact.bin")
    assert registry.resolve(file_id) == (path, "artifact.bin")
    entry = registry.get_entry(file_id)
    assert entry is not None
    assert entry["lifecycle"] == "session_bound"

    assert registry.cleanup_session(session_id) == 1
    assert registry.resolve(file_id) is None
    assert os.path.exists(path) is False


def test_postgres_file_registry_preserves_non_uuid_owner_ids(postgres_engine: object) -> None:
    """Postgres registry should retain arbitrary FileRegistry owner IDs.
    Postgres registry 应保留任意 FileRegistry owner ID。
    """
    from api.file_registry_postgres import PostgresFileRegistryBackend

    registry = PostgresFileRegistryBackend(engine=postgres_engine)
    owner_id = "material-library:owner"
    fd, path = tempfile.mkstemp(suffix=".bin")
    os.write(fd, b"content")
    os.close(fd)

    file_id = registry.register_path(owner_id, path, "artifact.bin")
    entry = registry.get_entry(file_id)
    assert entry is not None
    assert entry["session_id"] == owner_id
    assert set(registry.get_session_entries(owner_id)) == {file_id}

    assert registry.cleanup_session(owner_id) == 1
    assert registry.resolve(file_id) is None
    assert os.path.exists(path) is False
