"""Add file visibility metadata.

Revision ID: 003
Revises: 002
Create Date: 2026-05-23
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add public/private metadata for registered files.
    增加注册文件的公开/内部元数据。
    """
    op.add_column(
        "files",
        sa.Column(
            "is_public",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.add_column("files", sa.Column("purpose", sa.Text(), nullable=True))


def downgrade() -> None:
    """Remove public/private metadata from registered files.
    移除注册文件的公开/内部元数据。
    """
    op.drop_column("files", "purpose")
    op.drop_column("files", "is_public")
