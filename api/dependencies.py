"""Lumina Studio API — Dependency Injection.
Lumina Studio API — 依赖注入模块。

Global singletons and FastAPI dependency functions.
Separated from app.py to avoid circular imports between
app and router modules.
全局单例和 FastAPI 依赖注入函数。
从 app.py 分离以避免 app 与 router 模块之间的循环导入。

Phase A4 backend dispatch
-------------------------
``LUMINA_BACKEND`` selects which storage backend powers the global
``SessionStore`` / ``FileRegistry`` singletons. The default ``memory``
keeps the historical desktop / single-user behaviour bit-exact:
in-process Python dicts, restart drops everything. ``postgres`` is the
server-side backend that lands across PRs A4-2 (session store) + A4-3
(file registry); the env value is accepted today but each ``_build_*``
helper raises ``NotImplementedError`` until its backend ships.

``LUMINA_BACKEND`` 决定全局 SessionStore / FileRegistry 单例的存储后端。
默认 ``memory`` 与 A4 之前完全一致 (内存字典, 重启清零). ``postgres`` 后端
随 A4-2 / A4-3 分别落地; 当前 PR 接受 env 取值但抛 NotImplementedError
指向后续 PR.
"""

from __future__ import annotations

import os

from api.file_registry import FileRegistry
from api.session_store import SessionStore
from api.worker_pool import WorkerPoolManager
from config import WorkerPoolConfig


_VALID_BACKENDS: tuple[str, ...] = ("memory", "postgres")


def _resolve_backend_name() -> str:
    """Read and validate the ``LUMINA_BACKEND`` env var.
    读取并校验 ``LUMINA_BACKEND`` 环境变量。

    Returns:
        str: A normalised backend name from :data:`_VALID_BACKENDS`. Empty
        / unset env value resolves to ``"memory"`` so existing desktop
        deployments are unaffected.
        归一化后的后端名称; 未设或为空时回落到 ``"memory"``, 不影响桌面环境.

    Raises:
        ValueError: ``LUMINA_BACKEND`` is set to an unknown value. Caller
            sees a precise list of accepted values rather than a silent
            fallback.
            ``LUMINA_BACKEND`` 取值不在白名单时抛错, 避免静默回落到默认.
    """
    raw = os.environ.get("LUMINA_BACKEND", "").strip().lower()
    if not raw:
        return "memory"
    if raw not in _VALID_BACKENDS:
        accepted = ", ".join(repr(name) for name in _VALID_BACKENDS)
        raise ValueError(
            f"LUMINA_BACKEND={raw!r} is not supported. "
            f"Accepted values: {accepted}. Leave the variable unset for "
            "the default desktop / single-user behavior."
        )
    return raw


def _build_session_store() -> SessionStore:
    """Construct the global :class:`SessionStore` singleton per env.
    根据环境变量构造全局 :class:`SessionStore` 单例。

    Returns:
        SessionStore: An in-memory store when ``LUMINA_BACKEND`` resolves
        to ``"memory"`` (the default).
        默认 ``memory`` 时返回内存版 :class:`SessionStore`.

    Raises:
        NotImplementedError: ``LUMINA_BACKEND=postgres`` is set but the
            Postgres backend has not landed yet (PR A4-2). The desktop
            default is unchanged; this guard exists so a typo in CI / a
            premature production deploy fails loud rather than silently
            corrupting state.
            ``postgres`` 后端尚未落地 (PR A4-2); 显式抛错防止误用.
    """
    backend = _resolve_backend_name()
    if backend == "memory":
        return SessionStore(ttl=1800)
    if backend == "postgres":
        raise NotImplementedError(
            "PostgresSessionBackend lands in PR A4-2. "
            "Set LUMINA_BACKEND=memory (or leave unset) for current "
            "desktop / single-user behavior."
        )
    raise AssertionError(f"unreachable backend dispatch: {backend!r}")


def _build_file_registry() -> FileRegistry:
    """Construct the global :class:`FileRegistry` singleton per env.
    根据环境变量构造全局 :class:`FileRegistry` 单例。

    Returns:
        FileRegistry: An in-memory registry when ``LUMINA_BACKEND``
        resolves to ``"memory"`` (the default).
        默认 ``memory`` 时返回内存版 :class:`FileRegistry`.

    Raises:
        NotImplementedError: ``LUMINA_BACKEND=postgres`` is set but the
            Postgres-backed registry has not landed yet (PR A4-3).
            ``postgres`` 后端尚未落地 (PR A4-3); 显式抛错防止误用.
    """
    backend = _resolve_backend_name()
    if backend == "memory":
        return FileRegistry()
    if backend == "postgres":
        raise NotImplementedError(
            "PostgresFileRegistryBackend lands in PR A4-3. "
            "Set LUMINA_BACKEND=memory (or leave unset) for current "
            "desktop / single-user behavior."
        )
    raise AssertionError(f"unreachable backend dispatch: {backend!r}")


# Global singletons. Instantiated at import time so existing callers
# importing ``session_store`` / ``file_registry`` directly keep working
# without API changes (lossless refactor per AGENTS.md L48-51).
# 全局单例; 在 import 时实例化, 兼容直接导入 ``session_store`` /
# ``file_registry`` 的现有调用方, 公共 API 保持不变.
session_store: SessionStore = _build_session_store()
file_registry: FileRegistry = _build_file_registry()

_worker_pool_config = WorkerPoolConfig.from_env()
worker_pool: WorkerPoolManager = WorkerPoolManager(max_workers=_worker_pool_config.MAX_WORKERS)


def get_session_store() -> SessionStore:
    """FastAPI dependency: return global SessionStore.
    FastAPI 依赖注入: 返回全局 SessionStore 单例.
    """
    return session_store


def get_file_registry() -> FileRegistry:
    """FastAPI dependency: return global FileRegistry.
    FastAPI 依赖注入: 返回全局 FileRegistry 单例.
    """
    return file_registry


def get_worker_pool() -> WorkerPoolManager:
    """FastAPI dependency: return global WorkerPoolManager.
    FastAPI 依赖注入：返回全局 WorkerPoolManager 实例。

    Returns:
        WorkerPoolManager: The global worker pool singleton. (全局工作进程池单例)
    """
    return worker_pool
