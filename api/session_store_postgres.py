"""Postgres-backed SessionStore implementation for Phase A4.
Phase A4 的 Postgres 版 SessionStore 实现。

The public methods mirror :class:`api.session_store.SessionStore` so routers
can keep using the existing dependency contract while ``LUMINA_BACKEND``
selects the storage backend.
公开方法与 :class:`api.session_store.SessionStore` 保持一致，使路由在
``LUMINA_BACKEND`` 切换存储后端时无需改调用方式。
"""

from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from sqlalchemy import CheckConstraint, Column, DateTime, MetaData, Table, Text, delete, insert, select, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import insert as pg_insert

from api.postgres_db import create_engine_from_env
from api.session_store import SessionStore
from api.session_value_codec import decode_session_value, encode_session_value
from api.structured_logging import get_logger

_log = get_logger(__name__)


_METADATA = MetaData()
_SESSIONS = Table(
    "sessions",
    _METADATA,
    Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
    Column("data", postgresql.JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("last_seen_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("state", Text, nullable=False),
    CheckConstraint("state IN ('active', 'closing', 'retired')"),
)
_SESSION_TEMP_FILES = Table(
    "session_temp_files",
    _METADATA,
    Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
    Column("path", Text, nullable=False),
)
_FILES = Table(
    "files",
    _METADATA,
    Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
)
_SESSION_ID_NAMESPACE = uuid.UUID("0e4c9b87-4e0f-43b4-9d65-76e8c0f08d17")


class PostgresSessionBackend(SessionStore):
    """Postgres-backed drop-in replacement for ``SessionStore``.
    ``SessionStore`` 的 Postgres 后端替身。

    Args:
        ttl: Session lease length in seconds.
            Session 租约秒数。
        engine: Optional pre-built SQLAlchemy engine, mainly for tests.
            可选的 SQLAlchemy engine，主要用于测试。
    """

    def __init__(self, ttl: int = SessionStore.DEFAULT_TTL, engine: Any | None = None) -> None:
        if engine is not None:
            self._engine = engine
        else:
            try:
                self._engine = create_engine_from_env()
            except Exception as exc:  # noqa: BLE001 — escalation boundary for Postgres init
                _log.error(
                    "Postgres session backend init failed",
                    extra={
                        "event": "postgres_session_backend_init_failed",
                        "error_type": type(exc).__name__,
                        "error_message": str(exc),
                        "dependency": "postgres",
                    },
                )
                raise
        self._lease_seconds = ttl

    def create(self, session_id: str | None = None) -> str:
        """Create a new session.
        创建新 session。
        """
        requested_id = session_id
        if session_id is None:
            session_uuid = uuid.uuid4()
            session_id = str(session_uuid)
        else:
            session_uuid = self._session_uuid(session_id)

        with self._engine.begin() as conn:
            now = self._now()
            self._prune_retired(conn, now)
            while self._session_row_exists(conn, session_uuid):
                session_uuid = uuid.uuid4()
                session_id = str(session_uuid)
            conn.execute(
                insert(_SESSIONS).values(
                    id=session_uuid,
                    data={},
                    created_at=now,
                    last_seen_at=now,
                    expires_at=self._expiry_from(now),
                    state="active",
                )
            )
        return requested_id if requested_id is not None and session_id == requested_id else session_id

    def get(self, session_id: str) -> Optional[Dict[str, Any]]:
        """获取 session 数据，更新访问时间戳。不存在返回 None。"""
        session_uuid = self._session_uuid(session_id)
        with self._engine.begin() as conn:
            now = self._now()
            self._prune_retired(conn, now)
            row = conn.execute(
                select(_SESSIONS.c.data, _SESSIONS.c.state).where(_SESSIONS.c.id == session_uuid)
            ).first()
            if row is None:
                return None
            mapping = row._mapping
            if mapping["state"] != "active":
                return None
            conn.execute(
                update(_SESSIONS)
                .where(_SESSIONS.c.id == session_uuid)
                .values(last_seen_at=now, expires_at=self._expiry_from(now))
            )
            return decode_session_value(mapping["data"] or {})

    def put(self, session_id: str, key: str, value: Any) -> None:
        """写入 session 数据字段。session 不存在时自动创建。"""
        session_uuid = self._session_uuid(session_id)
        with self._engine.begin() as conn:
            now = self._now()
            self._prune_retired(conn, now)
            row = conn.execute(
                select(_SESSIONS.c.data, _SESSIONS.c.state).where(_SESSIONS.c.id == session_uuid)
            ).first()
            if row is not None and row._mapping["state"] in {"closing", "retired"}:
                return
            if row is None:
                conn.execute(
                    insert(_SESSIONS).values(
                        id=session_uuid,
                        data={},
                        created_at=now,
                        last_seen_at=now,
                        expires_at=self._expiry_from(now),
                        state="active",
                    )
                )
                data: dict[str, Any] = {}
            else:
                data = decode_session_value(row._mapping["data"] or {})
            data[key] = value
            conn.execute(
                update(_SESSIONS)
                .where(_SESSIONS.c.id == session_uuid)
                .values(data=encode_session_value(data), last_seen_at=now, expires_at=self._expiry_from(now))
            )

    def register_temp_file(self, session_id: str, path: str) -> None:
        """注册临时文件路径，session 清理时一并删除。"""
        session_uuid = self._session_uuid(session_id)
        with self._engine.begin() as conn:
            now = self._now()
            self._prune_retired(conn, now)
            state = conn.execute(select(_SESSIONS.c.state).where(_SESSIONS.c.id == session_uuid)).scalar_one_or_none()
            if state != "active":
                return
            conn.execute(
                pg_insert(_SESSION_TEMP_FILES)
                .values(session_id=session_uuid, path=path)
                .on_conflict_do_nothing(index_elements=["session_id", "path"])
            )

    def touch(self, session_id: str) -> float | None:
        """Renew the session lease and return the new expiry timestamp.
        续期指定 session 的租约，并返回新的过期时间戳。
        """
        session_uuid = self._session_uuid(session_id)
        with self._engine.begin() as conn:
            now = self._now()
            self._prune_retired(conn, now)
            state = conn.execute(select(_SESSIONS.c.state).where(_SESSIONS.c.id == session_uuid)).scalar_one_or_none()
            if state != "active":
                return None
            expires_at = self._expiry_from(now)
            conn.execute(
                update(_SESSIONS)
                .where(_SESSIONS.c.id == session_uuid)
                .values(last_seen_at=now, expires_at=expires_at)
            )
            return self._timestamp(expires_at)

    def close(self, session_id: str) -> int:
        """Close a session immediately and clean its tracked temp files.
        立即关闭指定 session，并清理其追踪的临时文件。
        """
        return self.close_except(session_id, keep_paths=None)

    def cleanup_temp_files_except(self, session_id: str, keep_paths: set[str] | None = None) -> int:
        """Clean tracked temp files while preserving the session itself.
        清理追踪的临时文件，但保留 session 数据本身。
        """
        cleaned, _ = self._cleanup_session(session_id, keep_paths=keep_paths, remove_session=False)
        return cleaned

    def close_except(self, session_id: str, keep_paths: set[str] | None = None) -> int:
        """Close a session while preserving selected temp-file paths.
        关闭指定 session，并保留 keep_paths 中的临时文件路径。
        """
        cleaned, _ = self._cleanup_session(session_id, keep_paths=keep_paths, remove_session=True)
        return cleaned

    def cleanup_expired(self) -> list[str]:
        """Clean up expired sessions and return their IDs.
        清理过期 session，返回已清理的 session ID 列表。
        """
        with self._engine.begin() as conn:
            now = self._now()
            self._prune_retired(conn, now)
            rows = conn.execute(
                select(_SESSIONS.c.id)
                .where(_SESSIONS.c.state.in_(["active", "closing"]))
                .where(_SESSIONS.c.expires_at <= now)
            ).all()
        cleaned_sessions: list[str] = []
        for row in rows:
            sid = str(row._mapping["id"])
            _, closed = self._cleanup_session(sid, keep_paths=None, remove_session=True)
            if closed:
                cleaned_sessions.append(sid)
        return cleaned_sessions

    def clear_all(self) -> int:
        """清除所有会话及其临时文件，返回清理的会话数量。"""
        with self._engine.begin() as conn:
            now = self._now()
            self._prune_retired(conn, now)
            rows = conn.execute(select(_SESSIONS.c.id).where(_SESSIONS.c.state != "retired")).all()
        cleaned_sessions = 0
        for row in rows:
            _, closed = self._cleanup_session(str(row._mapping["id"]), keep_paths=None, remove_session=True)
            if closed:
                cleaned_sessions += 1
        return cleaned_sessions

    def exists(self, session_id: str) -> bool:
        """检查 session 是否存在。"""
        session_uuid = self._session_uuid(session_id)
        with self._engine.begin() as conn:
            now = self._now()
            self._prune_retired(conn, now)
            state = conn.execute(select(_SESSIONS.c.state).where(_SESSIONS.c.id == session_uuid)).scalar_one_or_none()
            return state == "active"

    def get_temp_file_paths(self, session_id: str) -> list[str]:
        """Return a snapshot of tracked temp-file paths for a session.
        返回指定 session 当前追踪的临时文件路径快照。
        """
        session_uuid = self._session_uuid(session_id)
        with self._engine.begin() as conn:
            rows = conn.execute(
                select(_SESSION_TEMP_FILES.c.path).where(_SESSION_TEMP_FILES.c.session_id == session_uuid)
            ).all()
            return [str(row._mapping["path"]) for row in rows]

    def get_inactive_session_ids(self) -> list[str]:
        """Return inactive session IDs that are still tracked for follow-up cleanup.
        返回当前仍被追踪、且已进入 inactive/closing 状态的 session ID 列表。
        """
        with self._engine.begin() as conn:
            now = self._now()
            self._prune_retired(conn, now)
            rows = conn.execute(
                select(_SESSIONS.c.id).where(_SESSIONS.c.state == "closing").order_by(_SESSIONS.c.id)
            ).all()
            return [str(row._mapping["id"]) for row in rows]

    def get_registry_cleanup_candidate_session_ids(self) -> list[str]:
        """Return session IDs whose registry files still need periodic cleanup attempts.
        返回其 registry 文件仍需周期性重试清理的 session ID 列表。
        """
        with self._engine.begin() as conn:
            now = self._now()
            self._prune_retired(conn, now)
            rows = conn.execute(
                select(_SESSIONS.c.id)
                .where(_SESSIONS.c.state.in_(["closing", "retired"]))
                .order_by(_SESSIONS.c.id)
            ).all()
            return [str(row._mapping["id"]) for row in rows]

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
                "Postgres session backend dispose failed",
                extra={
                    "event": "postgres_session_backend_dispose_failed",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "dependency": "postgres",
                },
            )

    def _cleanup_session(
        self,
        session_id: str,
        keep_paths: set[str] | None = None,
        remove_session: bool = True,
    ) -> tuple[int, bool]:
        keep_paths = keep_paths or set()
        session_uuid = self._session_uuid(session_id)
        with self._engine.begin() as conn:
            now = self._now()
            self._prune_retired(conn, now)
            state = conn.execute(select(_SESSIONS.c.state).where(_SESSIONS.c.id == session_uuid)).scalar_one_or_none()
            if state is None or state == "retired":
                return 0, True
            if remove_session:
                conn.execute(update(_SESSIONS).where(_SESSIONS.c.id == session_uuid).values(state="closing"))
            snapshot_paths = [
                str(row._mapping["path"])
                for row in conn.execute(
                    select(_SESSION_TEMP_FILES.c.path).where(_SESSION_TEMP_FILES.c.session_id == session_uuid)
                ).all()
            ]

        attempted_paths = [path for path in snapshot_paths if path not in keep_paths]
        cleaned, failed_paths = self._delete_paths(attempted_paths)
        attempted_path_set = set(attempted_paths)
        failed_path_set = set(failed_paths)

        with self._engine.begin() as conn:
            now = self._now()
            self._prune_retired(conn, now)
            state = conn.execute(select(_SESSIONS.c.state).where(_SESSIONS.c.id == session_uuid)).scalar_one_or_none()
            if state is None or state == "retired":
                return cleaned, True

            current_paths = [
                str(row._mapping["path"])
                for row in conn.execute(
                    select(_SESSION_TEMP_FILES.c.path).where(_SESSION_TEMP_FILES.c.session_id == session_uuid)
                ).all()
            ]
            retained_paths: list[str] = []
            can_close = True
            for path in current_paths:
                if path in keep_paths or path in failed_path_set:
                    retained_paths.append(path)
                    if path in failed_path_set:
                        can_close = False
                    continue
                if path in attempted_path_set:
                    continue
                retained_paths.append(path)
                if remove_session and path not in keep_paths:
                    can_close = False

            conn.execute(delete(_SESSION_TEMP_FILES).where(_SESSION_TEMP_FILES.c.session_id == session_uuid))
            for path in retained_paths:
                conn.execute(
                    pg_insert(_SESSION_TEMP_FILES)
                    .values(session_id=session_uuid, path=path)
                    .on_conflict_do_nothing(index_elements=["session_id", "path"])
                )

            if remove_session and can_close:
                conn.execute(delete(_SESSION_TEMP_FILES).where(_SESSION_TEMP_FILES.c.session_id == session_uuid))
                conn.execute(
                    update(_SESSIONS)
                    .where(_SESSIONS.c.id == session_uuid)
                    .values(data={}, state="retired", expires_at=self._expiry_from(now), last_seen_at=now)
                )
                return cleaned, True
            return cleaned, False

    def _delete_paths(self, paths: list[str]) -> tuple[int, list[str]]:
        cleaned = 0
        failed_paths: list[str] = []
        for path in paths:
            if not os.path.exists(path):
                cleaned += 1
                continue
            try:
                os.remove(path)
                cleaned += 1
            except FileNotFoundError:
                cleaned += 1
            except (PermissionError, OSError):
                if os.path.exists(path):
                    failed_paths.append(path)
                else:
                    cleaned += 1
        return cleaned, failed_paths

    def _session_row_exists(self, conn: Any, session_uuid: uuid.UUID) -> bool:
        return conn.execute(select(_SESSIONS.c.id).where(_SESSIONS.c.id == session_uuid)).first() is not None

    def _session_uuid(self, session_id: str) -> uuid.UUID:
        try:
            return uuid.UUID(str(session_id))
        except (TypeError, ValueError):
            return uuid.uuid5(_SESSION_ID_NAMESPACE, str(session_id))

    def _now(self) -> datetime:
        return datetime.fromtimestamp(time.time(), tz=timezone.utc)

    def _expiry_from(self, now: datetime) -> datetime:
        return now + timedelta(seconds=self._lease_seconds)

    def _timestamp(self, value: datetime) -> float:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.timestamp()

    def _prune_retired(self, conn: Any, now: datetime) -> None:
        no_registry_files = ~select(_FILES.c.session_id).where(_FILES.c.session_id == _SESSIONS.c.id).exists()
        conn.execute(
            delete(_SESSIONS)
            .where(_SESSIONS.c.state == "retired")
            .where(_SESSIONS.c.expires_at <= now)
            .where(no_registry_files)
        )
