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
    SlicerCustomPathRequest,
    SlicerCustomPathResponse,
    SlicerDetectResponse,
    SlicerInfo,
    SlicerLaunchRequest,
    SlicerLaunchResponse,
)
from api.structured_logging import get_logger
from config import TEMP_DIR
from core.slicer import (
    DetectedSlicer,
    detect_installed_slicers,
    launch_slicer,
    validate_custom_slicer_path,
)

router = APIRouter(prefix="/api/slicer", tags=["Slicer"])
log = get_logger(__name__)
_SLICER_LAUNCH_COPY_TTL_SECONDS = 60 * 60


def _remove_launch_copy(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


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
    except OSError:
        _remove_launch_copy(launch_copy_path)
        raise

    try:
        registry.register_path(
            session_id=f"slicer-launch:{uuid.uuid4().hex}",
            path=launch_copy_path,
            filename=os.path.basename(launch_copy_path),
            ttl_seconds=_SLICER_LAUNCH_COPY_TTL_SECONDS,
        )
    except Exception:
        _remove_launch_copy(launch_copy_path)
        raise
    return launch_copy_path


def _to_slicer_info(slicer: DetectedSlicer) -> SlicerInfo:
    return SlicerInfo(
        id=slicer.id,
        display_name=slicer.display_name,
        exe_path=slicer.exe_path,
        source=slicer.source,
    )


@router.get("/detect")
def detect_slicers() -> SlicerDetectResponse:
    """扫描系统已安装的切片软件。"""
    slicers = detect_installed_slicers()
    return SlicerDetectResponse(slicers=[_to_slicer_info(s) for s in slicers])


@router.post("/custom-path/validate")
def validate_custom_slicer_path_endpoint(
    request: SlicerCustomPathRequest,
) -> SlicerCustomPathResponse:
    """校验用户手动提供的切片软件路径。"""
    slicer = validate_custom_slicer_path(request.path)
    if slicer is None:
        return JSONResponse(
            status_code=400,
            content=SlicerCustomPathResponse(
                status="error",
                message="未识别到受支持的切片软件，请确认路径指向 .app 应用包。",
                slicer=None,
            ).model_dump(),
        )
    return SlicerCustomPathResponse(
        status="success",
        message=f"已识别 {slicer.display_name}",
        slicer=_to_slicer_info(slicer),
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
    if request.slicer_path:
        custom_slicer = validate_custom_slicer_path(request.slicer_path)
        if custom_slicer is not None and custom_slicer.id == request.slicer_id:
            slicers = [custom_slicer] + [
                slicer
                for slicer in slicers
                if slicer.id != custom_slicer.id
            ]
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
    except (OSError, RuntimeError, ValueError) as exc:
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

    log.info(
        "Slicer launched",
        extra={
            "event": "slicer_launch_done",
            "slicer_id": request.slicer_id,
            "original_file_path": request.file_path,
            "launch_copy_path": launch_file_path,
            "launch_copy_filename": os.path.basename(launch_file_path),
            "launch_message_length": len(message or ""),
        },
    )
    return SlicerLaunchResponse(status="success", message=message)
