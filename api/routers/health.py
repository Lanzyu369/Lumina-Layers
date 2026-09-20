"""Lumina Studio API — Health Check Router.
Lumina Studio API — 健康检查路由。

Provides a ``GET /api/health`` endpoint that returns service status,
version, uptime, and Worker Pool health information.
提供 ``GET /api/health`` 端点，返回服务状态、版本号、运行时间和 Worker Pool 健康信息。
"""

import os
import time

from fastapi import APIRouter, Depends

from api.dependencies import get_worker_pool
from api.schemas.responses import HealthResponse, WorkerPoolStatus
from api.worker_pool import WorkerPoolManager

router = APIRouter(prefix="/api", tags=["Health"])

_start_time: float = time.time()


@router.get("/health")
def health_check(
    pool: WorkerPoolManager = Depends(get_worker_pool),
) -> HealthResponse:
    """Return health, Worker Pool state, and optional desktop launch identity.
    返回健康状态、Worker Pool 状态及可选的桌面启动标识。
    """
    return HealthResponse(
        status="ok",
        version="2.0",
        desktop_instance_id=os.environ.get("LUMINA_DESKTOP_INSTANCE_ID") or None,
        uptime_seconds=round(time.time() - _start_time, 2),
        worker_pool=WorkerPoolStatus(
            healthy=pool.is_alive,
            max_workers=pool.max_workers,
        ),
    )
