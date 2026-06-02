"""MLS — Health & data-root introspection router.
MLS — 健康检查与数据根自省路由。

Provides ``GET /api/mls/health`` for liveness plus the resolved data-root
snapshot so operators can confirm the service points at the expected
material-archive and LUT directories.
提供 ``GET /api/mls/health`` 用于存活探测，并返回已解析的数据根快照，
便于运维确认服务指向预期的耗材档案与 LUT 目录。
"""

from __future__ import annotations

import time

from fastapi import APIRouter

from .. import data_root

router = APIRouter(prefix="/api/mls", tags=["Health"])

_START_TIME: float = time.time()


@router.get("/health")
async def health_check() -> dict:
    """Return service liveness, version, uptime, and resolved data roots.
    返回服务存活状态、版本号、运行时间和已解析的数据根目录。

    Returns:
        dict: Status payload with ``status``, ``service``, ``version``,
            ``uptime_seconds`` and ``data_roots``. (健康状态载荷)
    """
    return {
        "status": "ok",
        "service": "material-lut-studio",
        "version": "0.1.0",
        "uptime_seconds": round(time.time() - _START_TIME, 2),
        "data_roots": data_root.describe_roots(),
    }
