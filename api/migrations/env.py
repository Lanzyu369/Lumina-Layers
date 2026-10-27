"""Alembic env module — Lumina Studio Phase A4 schema migrations.
Alembic 环境模块 — Lumina Studio Phase A4 数据库迁移入口.

Reads ``LUMINA_DATABASE_URL`` at runtime so the same ``alembic.ini`` works
across desktop dev (when explicitly opted in via ``LUMINA_BACKEND=postgres``),
B2B Elegoo on-prem, and B2C SaaS environments.
运行时读取 ``LUMINA_DATABASE_URL``, 同一份 alembic.ini 适用于桌面 (显式开启
``LUMINA_BACKEND=postgres`` 时) / B2B / B2C 各部署环境.

This module is loaded only by the ``alembic`` CLI. Importing it from
application code would force ``sqlalchemy`` / ``alembic`` into the
default desktop import graph, which we keep optional per the A4-1
zero-impact contract.
本模块仅由 ``alembic`` CLI 加载; 应用代码不应导入它, 以保持桌面默认运行
路径无须 ``sqlalchemy`` / ``alembic`` 这两条额外依赖.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool


config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _resolve_database_url() -> str:
    """Resolve the runtime Postgres URL from the environment.
    从环境变量解析运行期 Postgres 连接串.

    Returns:
        str: A non-empty SQLAlchemy URL such as
        ``postgresql+psycopg://user:pass@host:5432/db``.
        非空 SQLAlchemy URL.

    Raises:
        RuntimeError: ``LUMINA_DATABASE_URL`` is unset or blank, which
            would otherwise let Alembic silently fall back to its built-in
            default and corrupt an unrelated database.
            ``LUMINA_DATABASE_URL`` 未设置或为空, 防止 Alembic 默认值误伤
            其他无关数据库.
    """
    url = os.environ.get("LUMINA_DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError(
            "LUMINA_DATABASE_URL is not set. Required for Alembic operations. "
            "Example: postgresql+psycopg://lumina:lumina@localhost:5432/lumina_dev"
        )
    return url


# A4-1 ships raw migrations only; declarative metadata lands with
# the Postgres session/file backends in A4-2/A4-3.
# A4-1 仅提供原始迁移; 声明式 ORM 元数据随 A4-2/A4-3 后端实现一并加入.
target_metadata = None


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL without a live DB).
    离线模式: 仅生成 SQL, 不连真实数据库.
    """
    url = _resolve_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live Postgres connection.
    在线模式: 连接真实 Postgres 应用迁移.
    """
    cfg_section = config.get_section(config.config_ini_section, {})
    cfg_section["sqlalchemy.url"] = _resolve_database_url()
    connectable = engine_from_config(
        cfg_section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
