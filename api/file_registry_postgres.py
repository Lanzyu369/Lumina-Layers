"""Postgres-backed FileRegistry implementation for Phase A4.
Phase A4 的 Postgres 版 FileRegistry 实现。

The class mirrors :class:`api.file_registry.FileRegistry` and stores file
metadata in the A4 ``files`` table while keeping bytes/path handling on the
local filesystem.
该类与 :class:`api.file_registry.FileRegistry` 保持同一公开接口，将文件元数据
写入 A4 ``files`` 表，文件内容仍保留在本地文件系统。
"""

from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Tuple

from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, Integer, MetaData, Table, Text, delete, insert, or_, select, update
from sqlalchemy.dialects import postgresql

from api.file_registry import FileRegistry
from api.postgres_db import create_engine_from_env
from api.structured_logging import get_logger

_log = get_logger(__name__)


_METADATA = MetaData()
_FILES = Table(
    "files",
    _METADATA,
    Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
    Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
    Column("owner_id", Text, nullable=True),
    Column("storage_kind", Text, nullable=False),
    Column("storage_key", Text, nullable=False),
    Column("filename", Text, nullable=False),
    Column("lifecycle", Text, nullable=False),
    Column("delete_on_cleanup", Boolean, nullable=False),
    Column("is_public", Boolean, nullable=False),
    Column("purpose", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=True),
    Column("ttl_seconds", Integer, nullable=True),
    CheckConstraint("storage_kind IN ('local', 's3')"),
    CheckConstraint("lifecycle IN ('session_bound', 'ephemeral', 'shared_cache')"),
)
_SESSIONS = Table(
    "sessions",
    _METADATA,
    Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
)
_SESSION_ID_NAMESPACE = uuid.UUID("0e4c9b87-4e0f-43b4-9d65-76e8c0f08d17")


class PostgresFileRegistryBackend(FileRegistry):
    """Postgres-backed drop-in replacement for ``FileRegistry``.
    ``FileRegistry`` 的 Postgres 后端替身。

    Args:
        engine: Optional pre-built SQLAlchemy engine, mainly for tests.
            可选的 SQLAlchemy engine，主要用于测试。
    """

    def __init__(self, engine: Any | None = None) -> None:
        if engine is not None:
            self._engine = engine
            return
        try:
            self._engine = create_engine_from_env()
        except Exception as exc:  # noqa: BLE001 — escalation boundary for Postgres init
            _log.error(
                "Postgres file registry backend init failed",
                extra={
                    "event": "postgres_file_registry_init_failed",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "dependency": "postgres",
                },
            )
            raise

    def register_path(
        self,
        session_id: str,
        path: str,
        filename: Optional[str] = None,
        ttl_seconds: Optional[int] = None,
        is_public: bool = True,
        purpose: Optional[str] = None,
    ) -> str:
        """注册磁盘文件，返回 file_id。"""
        file_id = uuid.uuid4()
        if filename is None:
            filename = os.path.basename(path)
        now = self._now()
        expires_at = self._expiry_from(now, ttl_seconds) if ttl_seconds is not None else None
        session_uuid = self._session_uuid(session_id)
        delete_on_cleanup = self._should_delete_path(path)
        lifecycle = "ephemeral" if ttl_seconds is not None else "session_bound"
        with self._engine.begin() as conn:
            if not self._session_exists(conn, session_uuid):
                session_uuid_for_fk = None
            else:
                session_uuid_for_fk = session_uuid
            conn.execute(
                insert(_FILES).values(
                    id=file_id,
                    session_id=session_uuid_for_fk,
                    owner_id=session_id,
                    storage_kind="local",
                    storage_key=path,
                    filename=filename,
                    lifecycle=lifecycle,
                    delete_on_cleanup=delete_on_cleanup,
                    is_public=bool(is_public),
                    purpose=purpose,
                    created_at=now,
                    expires_at=expires_at,
                    ttl_seconds=ttl_seconds,
                )
            )
        return str(file_id)

    def resolve(self, file_id: str) -> Optional[Tuple[str, str]]:
        """解析 file_id，返回 (path, filename) 或 None。"""
        file_uuid = self._file_uuid_or_none(file_id)
        if file_uuid is None:
            return None
        now = self._now()
        with self._engine.begin() as conn:
            row = self._select_file(conn, file_uuid)
        if row is None:
            return None
        entry = self._entry_from_row(row)
        path = entry["path"]
        filename = entry["filename"]
        expires_at = entry.get("expires_at")
        ttl_seconds = entry.get("ttl_seconds")
        delete_on_cleanup = bool(entry.get("delete_on_cleanup", True))

        if expires_at is not None and self._timestamp(now) >= float(expires_at):
            cleaned = True if not delete_on_cleanup else self._delete_path(path)
            if cleaned:
                with self._engine.begin() as conn:
                    conn.execute(delete(_FILES).where(_FILES.c.id == file_uuid).where(_FILES.c.storage_key == path))
            return None

        if not os.path.exists(path):
            with self._engine.begin() as conn:
                conn.execute(delete(_FILES).where(_FILES.c.id == file_uuid).where(_FILES.c.storage_key == path))
            return None

        if ttl_seconds is not None:
            with self._engine.begin() as conn:
                conn.execute(
                    update(_FILES)
                    .where(_FILES.c.id == file_uuid)
                    .where(_FILES.c.storage_key == path)
                    .values(expires_at=self._expiry_from(now, int(ttl_seconds)))
                )
        return path, filename

    def get_entry(self, file_id: str) -> dict | None:
        """Return a shallow copy of a registry entry.
        返回指定条目的只读浅拷贝。
        """
        file_uuid = self._file_uuid_or_none(file_id)
        if file_uuid is None:
            return None
        with self._engine.begin() as conn:
            row = self._select_file(conn, file_uuid)
            if row is None:
                return None
            return self._entry_from_row(row)

    def set_purpose(self, file_id: str, purpose: Optional[str]) -> bool:
        """Update the purpose metadata for one registered file.
        更新单个注册文件的 purpose 元数据。
        """
        file_uuid = self._file_uuid_or_none(file_id)
        if file_uuid is None:
            return False
        with self._engine.begin() as conn:
            result = conn.execute(
                update(_FILES).where(_FILES.c.id == file_uuid).values(purpose=purpose)
            )
            return int(result.rowcount or 0) > 0

    def get_session_entries(self, session_id: str) -> dict[str, dict]:
        """Return shallow copies of all entries owned by a session.
        返回指定 session 拥有的所有条目的浅拷贝。
        """
        with self._engine.begin() as conn:
            rows = conn.execute(select(_FILES).where(self._owner_clause(session_id))).all()
            return {str(row._mapping["id"]): self._entry_from_row(row) for row in rows}

    def cleanup_expired(self) -> int:
        """删除所有已过期条目及磁盘文件，返回清理数量。"""
        now = self._now()
        with self._engine.begin() as conn:
            rows = conn.execute(select(_FILES.c.id).where(_FILES.c.expires_at.is_not(None)).where(_FILES.c.expires_at <= now)).all()
            file_ids = [str(row._mapping["id"]) for row in rows]
        return self._cleanup_entries(file_ids)

    def cleanup_session(self, session_id: str) -> int:
        """Clean up all registered files for a session and delete from disk.
        清理指定 session 的所有注册文件并删除磁盘文件，返回清理数量。
        """
        with self._engine.begin() as conn:
            rows = conn.execute(select(_FILES.c.id).where(self._owner_clause(session_id))).all()
            file_ids = [str(row._mapping["id"]) for row in rows]
        return self._cleanup_entries(file_ids, expire_failed_session_bound=True)

    def cleanup_session_except(self, session_id: str, keep_file_ids: set[str] | None = None) -> int:
        """Delete all registered files for a session except those in *keep_file_ids*.
        删除指定 session 的注册文件（保留 keep_file_ids 中的），返回清理数量。
        """
        keep_file_ids = keep_file_ids or set()
        keep_uuids = {value for value in (self._file_uuid_or_none(fid) for fid in keep_file_ids) if value is not None}
        with self._engine.begin() as conn:
            query = select(_FILES.c.id).where(self._owner_clause(session_id))
            if keep_uuids:
                query = query.where(_FILES.c.id.not_in(keep_uuids))
            rows = conn.execute(query).all()
            file_ids = [str(row._mapping["id"]) for row in rows]
        return self._cleanup_entries(file_ids, expire_failed_session_bound=True)

    def cleanup_file(self, file_id: str) -> int:
        """Clean up one registered file and delete it from disk.
        清理单个注册文件并删除磁盘文件。
        """
        return self._cleanup_entries([file_id], expire_failed_session_bound=True)

    def clear_all(self) -> int:
        """清除所有注册文件并删除磁盘文件，返回清理数量。"""
        with self._engine.begin() as conn:
            rows = conn.execute(select(_FILES.c.id)).all()
            file_ids = [str(row._mapping["id"]) for row in rows]
        return self._cleanup_entries(file_ids)

    def dispose(self) -> None:
        """Dispose the underlying SQLAlchemy engine.
        释放底层 SQLAlchemy engine。

        Best-effort: dispose failures are logged at WARNING but never
        re-raised, so callers in shutdown paths can keep tearing down
        other resources.
        尽力清理: 释放失败仅 WARNING 记录, 不再抛, 以免阻塞后续 shutdown.
        """
        try:
            self._engine.dispose()
        except Exception as exc:  # noqa: BLE001 — best-effort cleanup boundary
            _log.warning(
                "Postgres file registry backend dispose failed",
                extra={
                    "event": "postgres_file_registry_dispose_failed",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "dependency": "postgres",
                },
            )

    def _cleanup_entries(
        self,
        file_ids: list[str],
        expire_failed_session_bound: bool = False,
    ) -> int:
        snapshots: list[tuple[uuid.UUID, str, bool, str]] = []
        with self._engine.begin() as conn:
            for file_id in file_ids:
                file_uuid = self._file_uuid_or_none(file_id)
                if file_uuid is None:
                    continue
                row = self._select_file(conn, file_uuid)
                if row is None:
                    continue
                mapping = row._mapping
                path = str(mapping["storage_key"])
                if not path:
                    conn.execute(delete(_FILES).where(_FILES.c.id == file_uuid))
                    continue
                snapshots.append((file_uuid, path, bool(mapping["delete_on_cleanup"]), str(mapping["lifecycle"])))

        outcomes = [
            (file_uuid, path, True if not delete_on_cleanup else self._delete_path(path), lifecycle)
            for file_uuid, path, delete_on_cleanup, lifecycle in snapshots
        ]

        removed = 0
        with self._engine.begin() as conn:
            for file_uuid, path, cleaned, lifecycle in outcomes:
                current = self._select_file(conn, file_uuid)
                if current is None or str(current._mapping["storage_key"]) != path:
                    continue
                if cleaned:
                    conn.execute(delete(_FILES).where(_FILES.c.id == file_uuid))
                    removed += 1
                    continue
                if expire_failed_session_bound and lifecycle == "session_bound":
                    conn.execute(update(_FILES).where(_FILES.c.id == file_uuid).values(expires_at=self._now()))
        return removed

    def _select_file(self, conn: Any, file_uuid: uuid.UUID):
        return conn.execute(select(_FILES).where(_FILES.c.id == file_uuid)).first()

    def _entry_from_row(self, row: Any) -> dict:
        mapping = row._mapping
        created_at = mapping["created_at"]
        expires_at = mapping["expires_at"]
        session_id = mapping["owner_id"] or mapping["session_id"]
        return {
            "path": str(mapping["storage_key"]),
            "filename": str(mapping["filename"]),
            "session_id": str(session_id) if session_id is not None else None,
            "created_at": self._timestamp(created_at),
            "expires_at": self._timestamp(expires_at) if expires_at is not None else None,
            "ttl_seconds": mapping["ttl_seconds"],
            "lifecycle": str(mapping["lifecycle"]),
            "delete_on_cleanup": bool(mapping["delete_on_cleanup"]),
            "is_public": bool(mapping["is_public"]),
            "purpose": mapping["purpose"],
        }

    def _session_exists(self, conn: Any, session_uuid: uuid.UUID) -> bool:
        return conn.execute(select(_SESSIONS.c.id).where(_SESSIONS.c.id == session_uuid)).first() is not None

    def _owner_clause(self, session_id: str):
        session_uuid = self._session_uuid(session_id)
        return or_(_FILES.c.owner_id == session_id, _FILES.c.session_id == session_uuid)

    def _session_uuid(self, session_id: str) -> uuid.UUID:
        try:
            return uuid.UUID(str(session_id))
        except (TypeError, ValueError):
            return uuid.uuid5(_SESSION_ID_NAMESPACE, str(session_id))

    def _file_uuid_or_none(self, file_id: str) -> uuid.UUID | None:
        try:
            return uuid.UUID(str(file_id))
        except (TypeError, ValueError):
            return None

    def _now(self) -> datetime:
        return datetime.fromtimestamp(time.time(), tz=timezone.utc)

    def _expiry_from(self, now: datetime, ttl_seconds: int | None) -> datetime | None:
        if ttl_seconds is None:
            return None
        return now + timedelta(seconds=ttl_seconds)

    def _timestamp(self, value: datetime) -> float:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.timestamp()
