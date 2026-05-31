"""Test helper: an app hosting the MLS-migrated extract/generate/query routers.
测试辅助：承载已迁移到 MLS 的提取/生成/查询路由的应用。

Route B moved the extractor / single_stage / calibration / five_color routers
out of the main app and into the standalone Material-LUT Studio (MLS) service.
Tests that exercise those endpoints must therefore target an app that mounts
them. Rather than spin up the full MLS process, this helper builds a minimal
FastAPI app with exactly those routers plus the shared ``/api/files/{id}``
serving endpoint, wired to fresh in-memory ``SessionStore`` / ``FileRegistry``
singletons (overridable for isolation).

路线 B 把 extractor / single_stage / calibration / five_color 路由从主应用迁出，
移入独立的 MLS 服务。测试这些端点须指向挂载了它们的应用。本辅助不启动完整 MLS
进程，而是构建一个最小 FastAPI 应用，仅挂载这些路由及共享的
``/api/files/{id}`` 端点，并接到内存版 ``SessionStore`` / ``FileRegistry``。
"""

from __future__ import annotations

from fastapi import FastAPI

from api.dependencies import (
    get_file_registry as _main_get_file_registry,
    get_session_store as _main_get_session_store,
)
from api.file_registry import FileRegistry
from api.routers import (
    calibration_router,
    extractor_router,
    five_color_router,
    single_stage_router,
)
from api.session_store import SessionStore


def build_migrated_app(
    *,
    session_store: SessionStore | None = None,
    file_registry: FileRegistry | None = None,
) -> FastAPI:
    """Build an app that mirrors the main app PLUS the MLS-migrated routers.
    构建一个镜像主应用、并额外挂载已迁移路由的应用。

    Starts from the real :func:`api.app.create_app` (so system / converter /
    file-serving behavior is identical) and re-adds the extract / generate /
    query routers that Route B moved to MLS, wiring their session/registry
    dependencies to the same overridable singletons. This keeps endpoint
    behavior faithful for tests without resurrecting those routes in
    production.

    以真实的 :func:`api.app.create_app` 为基（system/converter/文件服务行为一致），
    再补回路线 B 迁出的提取/生成/查询路由，并接到可覆盖的会话/registry 单例。
    既保证测试中端点行为忠实，又不在生产中复活这些路由。

    Args:
        session_store: Optional explicit SessionStore. (可选会话存储)
        file_registry: Optional explicit FileRegistry. (可选 registry)

    Returns:
        FastAPI: Main app + migrated routers. (主应用 + 迁移路由)
    """
    from api.app import create_app as _main_create_app

    app = _main_create_app()
    app.include_router(extractor_router)
    app.include_router(single_stage_router)
    app.include_router(calibration_router)
    app.include_router(five_color_router)

    if session_store is not None:
        app.dependency_overrides[_main_get_session_store] = lambda: session_store
    if file_registry is not None:
        app.dependency_overrides[_main_get_file_registry] = lambda: file_registry

    return app


def create_app() -> FastAPI:
    """``api.app.create_app``-compatible factory for migrated-endpoint tests.
    与 ``api.app.create_app`` 接口兼容的工厂，供迁移端点测试使用。

    Returns a fresh app each call so tests that register their own
    ``dependency_overrides`` keep isolation, mirroring the main factory.
    每次调用返回全新 app，使注册自有 ``dependency_overrides`` 的测试保持隔离，
    与主工厂行为一致。
    """
    return build_migrated_app()


# Module-level instance for tests that used ``from api.app import app``.
# 供原先 ``from api.app import app`` 的测试使用的模块级实例。
app: FastAPI = build_migrated_app()
