"""Add original FileRegistry owner id.
新增 FileRegistry 原始 owner id。

Revision ID: 002
Revises: 001
Create Date: 2026-05-01
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add ``files.owner_id`` for lossless FileRegistry session ids.
    增加 ``files.owner_id`` 以无损保存 FileRegistry session id。
    """
    op.add_column("files", sa.Column("owner_id", sa.Text(), nullable=True))
    op.execute("UPDATE files SET owner_id = session_id::text WHERE owner_id IS NULL")
    op.create_index("idx_files_owner_id", "files", ["owner_id"])


def downgrade() -> None:
    """Remove ``files.owner_id``.
    删除 ``files.owner_id``。
    """
    op.drop_index("idx_files_owner_id", table_name="files")
    op.drop_column("files", "owner_id")
