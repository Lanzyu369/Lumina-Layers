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
from math import isfinite
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse, Response

from api.env_loader import load_env_local
from api.runtime_limits import configure_blas_thread_limits

# Populate process env from <repo>/.env.local before any module reads
# os.environ. This must happen before logging setup (which reads
# LUMINA_LOG_*) and before feedback_email's lru_cached
# is_email_configured() is first invoked by a request handler. Putting
# the call at api.app module scope (rather than only in api_server.py)
# ensures coverage for every entry point that imports the FastAPI app:
# api_server.py, ``python -m uvicorn api.app:app``, debugpy launches,
# start_dev.py spawns, and Docker / CI runners.
# 在任何模块读取 os.environ 之前，从 <repo>/.env.local 把值填入进程
# 环境。必须早于日志初始化（它会读 LUMINA_LOG_*）以及第一次请求触发
# feedback_email 的 lru_cached is_email_configured()。把调用放在
# api.app 模块作用域而不是仅限 api_server.py，可以覆盖所有导入 FastAPI
# 应用的入口：api_server.py、``python -m uvicorn api.app:app``、
# debugpy 启动、start_dev.py 子进程、Docker / CI 等。
load_env_local()
configure_blas_thread_limits()

from api.logger import setup_file_logging
from api.structured_logging import (
    configure_structured_logging,
    get_logger,
    reset_request_id,
    reset_session_id,
    set_request_id,
    set_session_id,
)

# Select file logging as early as possible, then ensure structured handlers are active.
setup_file_logging()
configure_structured_logging()

from api.dependencies import (
    file_registry,
    get_file_registry,
    get_session_store,
    session_store,
    worker_pool,
)
from api.file_bridge import file_to_response
from api.material_sync_scheduler import (
    cancel_material_sync_auto_refresh_tasks,
    start_material_sync_auto_refresh_tasks,
)
from api.routers import (
    calibration_router,
    converter_router,
    extractor_router,
    feedback_router,
    five_color_router,
    health_router,
    lut_router,
    material_registry_router,
    material_sync_router,
    session_router,
    slicer_router,
    single_stage_router,
    system_router,
    vectorizer_router,
)

log = get_logger(__name__)

_REQUEST_COMPLETED_SLOW_MS = 1000.0
_VALIDATION_LOG_MESSAGE_LIMIT = 1200
_CLIENT_LOG_FIELD_LIMIT = 256
_CLIENT_LOG_DETAILS_DEPTH = 4
_CLIENT_LOG_DETAILS_ITEMS = 24
_CLIENT_LOG_DETAILS_STRING_LIMIT = 1200


def _compact_log_extra(extra: dict) -> dict:
    """Drop null structured-log fields while preserving explicit false/zero values.
    删除结构化日志中的空字段，同时保留 false / 0 等有效值。
    """
    return {key: value for key, value in extra.items() if value is not None}


def _truncate_log_message(message: str, limit: int) -> str:
    """Return a bounded log message without changing the HTTP response body.
    限制日志消息长度，但不改变 HTTP 响应内容。
    """
    if len(message) <= limit:
        return message
    return f"{message[:limit]}...<truncated>"


def _sanitize_client_log_value(value: Any, *, depth: int = 0) -> Any:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, str):
        return _truncate_log_message(value, _CLIENT_LOG_DETAILS_STRING_LIMIT)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if isfinite(value) else str(value)
    if depth >= _CLIENT_LOG_DETAILS_DEPTH:
        return "<truncated:depth>"
    if isinstance(value, (list, tuple)):
        items = [
            _sanitize_client_log_value(item, depth=depth + 1)
            for item in list(value)[:_CLIENT_LOG_DETAILS_ITEMS]
        ]
        remaining = len(value) - _CLIENT_LOG_DETAILS_ITEMS
        if remaining > 0:
            items.append(f"<truncated:{remaining}>")
        return items
    if isinstance(value, dict):
        sanitized = {}
        items = list(value.items())
        for raw_key, raw_value in items[:_CLIENT_LOG_DETAILS_ITEMS]:
            key = _truncate_log_message(str(raw_key), 120)
            sanitized[key] = _sanitize_client_log_value(raw_value, depth=depth + 1)
        remaining = len(items) - _CLIENT_LOG_DETAILS_ITEMS
        if remaining > 0:
            sanitized["__truncated_keys"] = remaining
        return sanitized
    return _truncate_log_message(str(value), _CLIENT_LOG_DETAILS_STRING_LIMIT)


def _coerce_client_log_duration(value: Any) -> float | None:
    if isinstance(value, (int, float)) and isfinite(float(value)):
        return round(float(value), 3)
    return None


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
        - Run feedback startup cleanup to mark interrupted tickets and
          prune TTL-expired attachments (see
          :func:`api.feedback_assembler.run_startup_cleanup`).
          执行反馈工单启动清理，标记中断工单并删除过期大附件。

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

    # Feedback startup cleanup: best-effort; never blocks app boot.
    # 反馈启动清理：尽力而为，绝不阻塞应用启动。
    try:
        from pathlib import Path as _Path
        from api.feedback_assembler import run_startup_cleanup

        override = os.environ.get("LUMINA_FEEDBACK_DUMP_DIR")
        repo_root = _Path(__file__).resolve().parent.parent
        feedback_root = _Path(override).resolve() if override else (repo_root / "feedback").resolve()
        run_startup_cleanup(feedback_root)
    except Exception as exc:  # noqa: BLE001 — cleanup must never crash startup.
        log.error(
            "Feedback startup cleanup raised.",
            extra={
                "event": "feedback_ticket_assembled_failed",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
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
    material_sync_refresh_tasks = start_material_sync_auto_refresh_tasks()

    yield

    # --- Shutdown ---
    cleanup_task.cancel()
    await cancel_material_sync_auto_refresh_tasks(material_sync_refresh_tasks)
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
        request.state.request_id = request_id
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
                    "request_id": request_id,
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
        request_completed_extra = {
                "event": "request_completed",
                "request_id": request_id,
                "path": request.url.path,
                "method": request.method,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
        }
        if response.status_code >= 500:
            log.warning("Request completed", extra=request_completed_extra)
        elif response.status_code >= 400:
            log.info("Request completed", extra=request_completed_extra)
        else:
            log.debug("Request completed", extra=request_completed_extra)
        reset_request_id(request_token)
        reset_session_id(session_token)
        return response

    @app.exception_handler(RequestValidationError)
    async def _log_request_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """Log FastAPI 422 validation details so frontend bugs are diagnosable.

        记录 FastAPI 422 验证错误详情，方便定位前端载荷不匹配的 bug。
        """
        # Pydantic v2 stores the originating exception in ``ctx.error`` which is
        # not JSON-serialisable by the default encoder, so both the structured
        # log payload and the response body must go through ``jsonable_encoder``
        # to coerce those values to strings. Without this the handler itself
        # raises ``TypeError`` and the client sees a 500 instead of the real
        # 422, which in turn breaks frontend error-detail mapping (e.g. the
        # gradient-card store's ``detail === "material_name is required"``
        # path). (Pydantic v2 将原始异常放在 ctx.error 中，必须通过
        # jsonable_encoder 统一序列化，否则 handler 本身会抛 TypeError
        # 导致前端拿不到 422，错误文案映射随之失效。)
        encoded_errors = jsonable_encoder(exc.errors())
        request_id = getattr(request.state, "request_id", request.headers.get("X-Request-ID"))
        log.warning(
            "Request validation failed",
            extra=_compact_log_extra({
                "event": "request_validation_failed",
                "request_id": request_id,
                "path": request.url.path,
                "method": request.method,
                "status_code": 422,
                "error_type": "RequestValidationError",
                "error_message": _truncate_log_message(
                    str(encoded_errors),
                    _VALIDATION_LOG_MESSAGE_LIMIT,
                ),
                "validation_error_count": len(encoded_errors),
            }),
        )
        return JSONResponse(
            status_code=422,
            content={"detail": encoded_errors},
        )

    app.include_router(converter_router)
    app.include_router(extractor_router)
    app.include_router(feedback_router)
    app.include_router(calibration_router)
    app.include_router(five_color_router)
    app.include_router(health_router)
    app.include_router(lut_router)
    app.include_router(material_registry_router)
    app.include_router(material_sync_router)
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
        if entry.get("is_public") is False:
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
    async def client_log(payload: dict[str, Any]):
        """Receive frontend timing events and write to server log."""
        label = _truncate_log_message(str(payload.get("label", "?")), _CLIENT_LOG_FIELD_LIMIT)
        elapsed = _coerce_client_log_duration(payload.get("elapsed_ms"))
        scope = payload.get("scope", None)
        phase = payload.get("phase", None)
        details = payload.get("details", None)
        log.debug(
            "Client log received",
            extra=_compact_log_extra({
                "event": "client_log",
                "client_label": label,
                "client_scope": (
                    _truncate_log_message(str(scope), _CLIENT_LOG_FIELD_LIMIT)
                    if scope is not None
                    else None
                ),
                "client_phase": (
                    _truncate_log_message(str(phase), _CLIENT_LOG_FIELD_LIMIT)
                    if phase is not None
                    else None
                ),
                "client_details": (
                    _sanitize_client_log_value(details)
                    if details is not None
                    else None
                ),
                "duration_ms": elapsed,
            }),
        )
        return {"ok": True}

    return app


app: FastAPI = create_app()
