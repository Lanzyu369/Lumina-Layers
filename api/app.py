"""Lumina Studio API — Application Factory.
Lumina Studio API — 应用工厂模块。

Provides a ``create_app()`` factory function that builds a fully-configured
FastAPI instance with CORS middleware and all domain routers registered.
Uses an async ``lifespan`` context manager to manage WorkerPool and
background tasks lifecycle.
提供 ``create_app()`` 工厂函数，构建配置完整的 FastAPI 实例，
包含 CORS 中间件和所有领域路由的注册。
使用异步 ``lifespan`` 上下文管理器管理 WorkerPool 和后台任务的生命周期。
"""

import asyncio
import os
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import Response

from api.logger import setup_file_logging
from api.structured_logging import (
    get_logger,
    reset_request_id,
    reset_session_id,
    set_request_id,
    set_session_id,
)

# Install file logging as early as possible so all startup prints are captured.
_log_path = setup_file_logging()
if _log_path is not None:
    os.environ["LUMINA_LOG_PATH"] = str(_log_path.resolve())

from api.dependencies import (
    file_registry,
    get_file_registry,
    get_session_store,
    session_store,
    worker_pool,
)
from api.file_bridge import file_to_response
from api.routers import (
    calibration_router,
    converter_router,
    extractor_router,
    five_color_router,
    health_router,
    lut_router,
    session_router,
    slicer_router,
    single_stage_router,
    system_router,
    vectorizer_router,
)

log = get_logger(__name__)


def _run_cleanup_pass(
    active_session_store=None,
    active_file_registry=None,
) -> tuple[list[str], list[str], int]:
    """Run one cleanup pass for expired sessions and registry files.
    执行一次过期 session 与 registry 文件清理。
    """
    store = session_store if active_session_store is None else active_session_store
    registry = file_registry if active_file_registry is None else active_file_registry

    expired_sids = store.cleanup_expired()
    registry_cleanup_sids = list(
        dict.fromkeys([*expired_sids, *store.get_registry_cleanup_candidate_session_ids()])
    )
    for sid in registry_cleanup_sids:
        registry.cleanup_session(sid)
    expired_files = registry.cleanup_expired()
    return expired_sids, registry_cleanup_sids, expired_files


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage application startup and shutdown lifecycle.
    管理应用启动和关闭的生命周期。

    Startup:
        - Initialize the WorkerPool process pool.
          初始化 WorkerPool 进程池。
        - Start the periodic session cleanup background task.
          启动定期会话清理后台任务。

    Shutdown:
        - Gracefully shut down the WorkerPool, waiting for in-flight tasks.
          优雅关闭 WorkerPool，等待正在执行的任务完成。
    """
    # --- Startup ---
    worker_pool.start()
    log.info(
        "Worker pool started",
        extra={"event": "worker_pool_started", "max_workers": worker_pool.max_workers},
    )

    async def _cleanup_loop() -> None:
        """Periodically clean up expired sessions and their registered files.
        定期清理过期会话及其注册文件。
        """
        while True:
            await asyncio.sleep(60)
            expired_sids, registry_cleanup_sids, expired_files = _run_cleanup_pass()
            if expired_sids:
                log.info(
                    "Expired sessions cleaned",
                    extra={"event": "session_cleanup", "cleaned_sessions": len(expired_sids)},
                )
            inactive_registry_cleanup_count = len(
                [sid for sid in registry_cleanup_sids if sid not in expired_sids]
            )
            if inactive_registry_cleanup_count:
                log.info(
                    "Inactive session registry files cleaned",
                    extra={
                        "event": "inactive_session_registry_cleanup",
                        "cleaned_sessions": inactive_registry_cleanup_count,
                    },
                )
            if expired_files:
                log.info(
                    "Expired files cleaned",
                    extra={"event": "file_cleanup", "cleaned_files": expired_files},
                )

    cleanup_task = asyncio.create_task(_cleanup_loop())

    yield

    # --- Shutdown ---
    cleanup_task.cancel()
    worker_pool.shutdown(wait=True)
    log.info("Worker pool shutdown complete", extra={"event": "worker_pool_shutdown"})


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.
    创建并配置 FastAPI 应用实例。

    Returns:
        FastAPI: A fully-configured application instance with CORS middleware,
            lifespan manager, and all domain routers registered.
            配置完整的应用实例，已注册 CORS 中间件、生命周期管理器和所有领域路由。
    """
    app = FastAPI(title="Lumina Studio API", version="2.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_context_middleware(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        request_token = set_request_id(request_id)
        session_token = set_session_id(None)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:
            duration_ms = round((time.perf_counter() - started) * 1000, 3)
            log.exception(
                "Request failed",
                extra={
                    "event": "request_failed",
                    "path": request.url.path,
                    "method": request.method,
                    "status_code": 500,
                    "duration_ms": duration_ms,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                },
            )
            reset_request_id(request_token)
            reset_session_id(session_token)
            raise

        if isinstance(response, Response):
            response.headers["X-Request-ID"] = request_id
        duration_ms = round((time.perf_counter() - started) * 1000, 3)
        log.info(
            "Request completed",
            extra={
                "event": "request_completed",
                "path": request.url.path,
                "method": request.method,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        reset_request_id(request_token)
        reset_session_id(session_token)
        return response

    app.include_router(converter_router)
    app.include_router(extractor_router)
    app.include_router(calibration_router)
    app.include_router(five_color_router)
    app.include_router(health_router)
    app.include_router(lut_router)
    app.include_router(session_router)
    app.include_router(slicer_router)
    app.include_router(single_stage_router)
    app.include_router(system_router)
    app.include_router(vectorizer_router)

    @app.get("/api/files/{file_id}")
    def serve_file(
        file_id: str,
        registry=Depends(get_file_registry),
        store=Depends(get_session_store),
    ):
        """Serve a registered file by file_id."""
        entry = registry.get_entry(file_id)
        if entry is None:
            raise HTTPException(status_code=404, detail="File not found or expired")

        result = registry.resolve(file_id)
        if result is None:
            raise HTTPException(status_code=404, detail="File not found or expired")

        if entry.get("lifecycle") == "session_bound":
            session_id = entry.get("session_id")
            if not session_id or store.touch(session_id) is None:
                raise HTTPException(status_code=404, detail="File not found or expired")

        path, filename = result
        return file_to_response(path, filename)

    @app.post("/api/client-log")
    async def client_log(payload: dict):
        """Receive frontend timing events and write to server log."""
        label = payload.get("label", "?")
        elapsed = payload.get("elapsed_ms", None)
        log.info(
            "Client log received",
            extra={
                "event": "client_log",
                "client_label": label,
                "duration_ms": elapsed,
            },
        )
        return {"ok": True}

    return app


app: FastAPI = create_app()
