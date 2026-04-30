"""Initial schema — sessions / files / session_temp_files.
初始 schema — sessions / files / session_temp_files.

Creates the tables that ``PostgresSessionBackend`` (PR A4-2) and
``PostgresFileRegistryBackend`` (PR A4-3) will use. Shipped inert in the
A4-1 scaffold PR (no application code touches the tables yet) so the
schema is locked-in before either backend implementation lands, avoiding
late-stage drift.
建立 PR A4-2 / A4-3 即将使用的表; A4-1 阶段表为空载 (无应用代码读写),
后续 PR 可直接落入实现而无 schema 漂移风险.

Schema rationale (mirrors progress/server-architecture.md §4.4):
- ``sessions``: 1:1 maps to current ``api/session_store.py`` in-memory state.
  Adds explicit ``state`` column ('active' / 'closing' / 'retired')
  replacing the in-memory ``_closing_sessions`` / ``_retired_sessions``
  bookkeeping. ``data jsonb`` holds the per-session payload dict.
- ``files``: 1:1 maps to ``api/file_registry.py`` registry entries.
  ``storage_kind`` ('local' / 's3') is added now so Phase A6 (object
  storage) can drop in without another migration.
- ``session_temp_files``: tracks temp paths registered for cleanup
  (matches ``api/session_store.py::register_temp_file``).
schema 设计映射现有 SessionStore 与 FileRegistry; ``state`` 列取代内存
中的 closing / retired 集合, ``storage_kind`` 列预留 Phase A6 对象存储切换.

Revision ID: 001
Revises: (none)
Create Date: 2026-04-30
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create initial Lumina session / file metadata tables.
    建表: sessions / files / session_temp_files.
    """
    op.create_table(
        "sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "data",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "state",
            sa.Text(),
            nullable=False,
            server_default="active",
        ),
        sa.CheckConstraint(
            "state IN ('active', 'closing', 'retired')",
            name="ck_sessions_state_enum",
        ),
    )
    op.create_index("idx_sessions_expires_at", "sessions", ["expires_at"])
    op.create_index("idx_sessions_state", "sessions", ["state"])

    op.create_table(
        "files",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sessions.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("storage_kind", sa.Text(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column(
            "lifecycle",
            sa.Text(),
            nullable=False,
            server_default="session_bound",
        ),
        sa.Column(
            "delete_on_cleanup",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ttl_seconds", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "storage_kind IN ('local', 's3')",
            name="ck_files_storage_kind_enum",
        ),
        sa.CheckConstraint(
            "lifecycle IN ('session_bound', 'ephemeral', 'shared_cache')",
            name="ck_files_lifecycle_enum",
        ),
    )
    op.create_index("idx_files_session_id", "files", ["session_id"])
    op.create_index("idx_files_expires_at", "files", ["expires_at"])

    op.create_table(
        "session_temp_files",
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("path", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("session_id", "path"),
    )


def downgrade() -> None:
    """Drop the tables created by :func:`upgrade`.
    回滚: 删除 upgrade 建立的表.

    Tables are dropped in reverse FK order so cascading constraints do
    not block the operation.
    按 FK 反向顺序删表, 避免级联约束阻塞.
    """
    op.drop_table("session_temp_files")
    op.drop_index("idx_files_expires_at", table_name="files")
    op.drop_index("idx_files_session_id", table_name="files")
    op.drop_table("files")
    op.drop_index("idx_sessions_state", table_name="sessions")
    op.drop_index("idx_sessions_expires_at", table_name="sessions")
    op.drop_table("sessions")
