"""Postgres connection helpers for Phase A4 backends.
Phase A4 后端的 Postgres 连接辅助模块。

This module is imported only when ``LUMINA_BACKEND=postgres`` or by
Postgres-specific tests. The default desktop ``memory`` backend path keeps
SQLAlchemy out of the import graph.
仅在启用 ``LUMINA_BACKEND=postgres`` 或 Postgres 专项测试时导入；默认
``memory`` 桌面路径不加载 SQLAlchemy。
"""

from __future__ import annotations

import os
from typing import Any


def resolve_database_url() -> str:
    """Resolve the configured SQLAlchemy database URL.
    解析 SQLAlchemy 数据库连接串。

    Returns:
        str: A non-empty SQLAlchemy URL from ``LUMINA_DATABASE_URL``.
        来自 ``LUMINA_DATABASE_URL`` 的非空 SQLAlchemy URL。

    Raises:
        RuntimeError: The env var is missing or blank.
        环境变量缺失或为空时抛出。
    """
    url = os.environ.get("LUMINA_DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError(
            "LUMINA_DATABASE_URL is required when LUMINA_BACKEND=postgres. "
            "Example: postgresql+psycopg://lumina:lumina@localhost:5432/lumina_dev"
        )
    return url


def create_engine_from_env(**kwargs: Any):
    """Create a SQLAlchemy engine from ``LUMINA_DATABASE_URL``.
    基于 ``LUMINA_DATABASE_URL`` 创建 SQLAlchemy engine。

    Args:
        **kwargs: Extra keyword arguments forwarded to ``sqlalchemy.create_engine``.
            透传给 ``sqlalchemy.create_engine`` 的附加参数。

    Returns:
        sqlalchemy.Engine: A SQLAlchemy engine bound to the configured URL.
        绑定到配置连接串的 SQLAlchemy engine。
    """
    from sqlalchemy import create_engine

    options = {"pool_pre_ping": True, **kwargs}
    return create_engine(resolve_database_url(), **options)
