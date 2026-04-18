"""Slicer domain API router.
Slicer 领域 API 路由模块 — 切片软件检测与启动端点。
"""

from __future__ import annotations

import os
import shutil
import tempfile
import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from api.dependencies import get_file_registry
from api.file_registry import FileRegistry
from api.schemas.slicer import (
    SlicerDetectResponse,
    SlicerInfo,
    SlicerLaunchRequest,
    SlicerLaunchResponse,
)
from config import TEMP_DIR
from core.slicer import detect_installed_slicers, launch_slicer

router = APIRouter(prefix="/api/slicer", tags=["Slicer"])
_SLICER_LAUNCH_COPY_TTL_SECONDS = 60 * 60


def _create_launch_copy(file_path: str, registry: FileRegistry) -> str:
    """Create an isolated launch copy so slicers cannot mutate the canonical output."""
    stem, ext = os.path.splitext(os.path.basename(file_path))
    fd, launch_copy_path = tempfile.mkstemp(
        prefix=f"{stem}_launch_",
        suffix=ext or ".3mf",
        dir=TEMP_DIR,
    )
    os.close(fd)
    try:
        shutil.copy2(file_path, launch_copy_path)
    except Exception:
        try:
            os.unlink(launch_copy_path)
        except OSError:
            pass
        raise

    registry.register_path(
        session_id=f"slicer-launch:{uuid.uuid4().hex}",
        path=launch_copy_path,
        filename=os.path.basename(launch_copy_path),
        ttl_seconds=_SLICER_LAUNCH_COPY_TTL_SECONDS,
    )
    return launch_copy_path


@router.get("/detect")
def detect_slicers() -> SlicerDetectResponse:
    """扫描系统已安装的切片软件。"""
    slicers = detect_installed_slicers()
    return SlicerDetectResponse(
        slicers=[
            SlicerInfo(
                id=s.id,
                display_name=s.display_name,
                exe_path=s.exe_path,
            )
            for s in slicers
        ]
    )


@router.post("/launch")
def launch_slicer_endpoint(
    request: SlicerLaunchRequest,
    registry: FileRegistry = Depends(get_file_registry),
) -> SlicerLaunchResponse:
    """启动切片软件打开指定文件。"""
    # 1) Validate file exists
    if not os.path.isfile(request.file_path):
        return JSONResponse(
            status_code=400,
            content=SlicerLaunchResponse(
                status="error",
                message=f"文件不存在: {request.file_path}",
            ).model_dump(),
        )

    # 2) Get fresh slicer list
    slicers = detect_installed_slicers()
    if not any(s.id == request.slicer_id for s in slicers):
        return JSONResponse(
            status_code=404,
            content=SlicerLaunchResponse(
                status="error",
                message=f"未找到切片软件: {request.slicer_id}",
            ).model_dump(),
        )
    try:
        launch_file_path = _create_launch_copy(request.file_path, registry)
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content=SlicerLaunchResponse(
                status="error",
                message=f"准备切片器打开副本失败: {exc}",
            ).model_dump(),
        )

    # 3) Attempt launch
    try:
        success, message = launch_slicer(request.slicer_id, launch_file_path, slicers)
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content=SlicerLaunchResponse(
                status="error",
                message=f"启动失败: {exc}",
            ).model_dump(),
        )

    if not success:
        # Distinguish 404 (slicer not found) from 500 (launch failure)
        if "not found" in message.lower():
            return JSONResponse(
                status_code=404,
                content=SlicerLaunchResponse(
                    status="error",
                    message=f"未找到切片软件: {request.slicer_id}",
                ).model_dump(),
            )
        return JSONResponse(
            status_code=500,
            content=SlicerLaunchResponse(
                status="error",
                message=f"启动失败: {message}",
            ).model_dump(),
        )

    return SlicerLaunchResponse(status="success", message=message)
