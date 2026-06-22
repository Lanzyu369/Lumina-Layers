"""Slicer domain API router.
Slicer 领域 API 路由模块 — 切片软件检测与启动端点。
"""

from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from urllib.parse import urlparse

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from api.dependencies import get_file_registry
from api.file_registry import FileRegistry
from api.local_origin_guard import require_local_app_origin
from api.schemas.slicer import (
    SlicerCustomPathRequest,
    SlicerCustomPathResponse,
    SlicerDetectResponse,
    SlicerInfo,
    SlicerLaunchRequest,
    SlicerLaunchResponse,
)
from api.structured_logging import get_logger
from config import OUTPUT_DIR, TEMP_DIR
from core.slicer import (
    DetectedSlicer,
    detect_installed_slicers,
    launch_slicer,
    validate_custom_slicer_path,
)

router = APIRouter(
    prefix="/api/slicer",
    tags=["Slicer"],
    dependencies=[Depends(require_local_app_origin)],
)
log = get_logger(__name__)
_SLICER_LAUNCH_COPY_TTL_SECONDS = 60 * 60
_ALLOWED_SLICER_LAUNCH_SUFFIXES = {".3mf"}
SLICER_LAUNCH_COPY_FAILED_MESSAGE = "准备切片器打开文件失败，请重新生成 3MF 后再试。"
SLICER_LAUNCH_FAILED_MESSAGE = "启动切片器失败，请确认切片软件可用后再试。"
SLICER_LAUNCH_SOURCE_MISSING_MESSAGE = "找不到要打开的 3MF 文件，请重新生成 3MF 后再试。"
_API_FILES_PREFIX = "/api/files/"


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


def _resolve_launch_source_path(file_path: str) -> tuple[str | None, str | None]:
    """Validate that a slicer launch source is a Lumina-generated 3MF.
    校验切片器启动源只能是 Lumina 输出目录内的 3MF 文件。
    """
    real_source_path = os.path.realpath(file_path)
    real_output_dir = os.path.realpath(OUTPUT_DIR)
    suffix = os.path.splitext(real_source_path)[1].lower()
    if suffix not in _ALLOWED_SLICER_LAUNCH_SUFFIXES:
        return None, "仅支持打开 Lumina 生成的 3MF 文件"
    try:
        if os.path.commonpath([real_output_dir, real_source_path]) != real_output_dir:
            return None, "只能打开 Lumina 输出目录中的 3MF 文件"
    except ValueError:
        return None, "只能打开 Lumina 输出目录中的 3MF 文件"
    if not os.path.isfile(real_source_path):
        return None, SLICER_LAUNCH_SOURCE_MISSING_MESSAGE
    return real_source_path, None


def _extract_file_id_from_download_url(download_url: str | None) -> str | None:
    if not isinstance(download_url, str) or not download_url.strip():
        return None
    parsed = urlparse(download_url.strip())
    if parsed.scheme or parsed.netloc:
        return None
    path = parsed.path
    if not path.startswith(_API_FILES_PREFIX):
        return None
    file_id = path[len(_API_FILES_PREFIX):].strip()
    if (
        not file_id
        or file_id in {".", ".."}
        or "/" in file_id
        or "\\" in file_id
        or any(char.isspace() for char in file_id)
    ):
        return None
    return file_id


def _resolve_launch_download_url_path(
    download_url: str,
    registry: FileRegistry,
) -> tuple[str | None, str | None]:
    file_id = _extract_file_id_from_download_url(download_url)
    if file_id is None:
        return None, SLICER_LAUNCH_SOURCE_MISSING_MESSAGE
    entry = registry.get_entry(file_id)
    if entry is None or entry.get("is_public") is False:
        return None, SLICER_LAUNCH_SOURCE_MISSING_MESSAGE
    resolved = registry.resolve(file_id)
    if resolved is None:
        return None, SLICER_LAUNCH_SOURCE_MISSING_MESSAGE
    source_path, _filename = resolved
    return _resolve_launch_source_path(source_path)


def _resolve_launch_request_source_path(
    request: SlicerLaunchRequest,
    registry: FileRegistry,
) -> tuple[str | None, str | None]:
    if request.download_url:
        return _resolve_launch_download_url_path(request.download_url, registry)
    if request.file_path:
        return _resolve_launch_source_path(request.file_path)
    return None, SLICER_LAUNCH_SOURCE_MISSING_MESSAGE


def _slicer_launch_failure_extra(
    *,
    request: SlicerLaunchRequest,
    status_code: int,
    original_file_path: str,
    safe_message: str,
    error: BaseException | None = None,
    error_type: str | None = None,
    error_message: str | None = None,
    launch_copy_path: str | None = None,
) -> dict[str, object]:
    """Build actionable launch-failure fields while responses stay safe."""
    resolved_error_type = error_type or (
        type(error).__name__ if error is not None else "SlicerLaunchFailed"
    )
    resolved_error_message = (
        str(error)
        if error is not None
        else error_message
        if error_message is not None
        else safe_message
    )
    extra: dict[str, object] = {
        "status_code": status_code,
        "slicer_id": request.slicer_id,
        "original_file_path": original_file_path,
        "safe_message": safe_message,
        "error_type": resolved_error_type,
        "error_message": resolved_error_message,
    }
    if launch_copy_path is not None:
        extra["launch_copy_path"] = launch_copy_path
        extra["launch_copy_filename"] = os.path.basename(launch_copy_path)
    return extra


def _log_slicer_launch_copy_failed(
    *,
    request: SlicerLaunchRequest,
    status_code: int,
    original_file_path: str,
    safe_message: str,
    error: BaseException,
) -> None:
    """Log launch-copy preparation failures."""
    log.error(
        "Slicer launch failed",
        extra={
            "event": "slicer_launch_copy_failed",
            **_slicer_launch_failure_extra(
                request=request,
                status_code=status_code,
                original_file_path=original_file_path,
                safe_message=safe_message,
                error=error,
            ),
        },
    )


def _log_slicer_launch_failed(
    *,
    request: SlicerLaunchRequest,
    status_code: int,
    original_file_path: str,
    safe_message: str,
    launch_copy_path: str,
    error: BaseException | None = None,
    error_type: str | None = None,
    error_message: str | None = None,
) -> None:
    """Log slicer process launch failures."""
    log.error(
        "Slicer launch failed",
        extra={
            "event": "slicer_launch_failed",
            **_slicer_launch_failure_extra(
                request=request,
                status_code=status_code,
                original_file_path=original_file_path,
                safe_message=safe_message,
                error=error,
                error_type=error_type,
                error_message=error_message,
                launch_copy_path=launch_copy_path,
            ),
        },
    )


def _to_slicer_info(slicer: DetectedSlicer) -> SlicerInfo:
    """Build public slicer metadata without exposing local executable paths.
    构建公开切片器元数据，不暴露本机可执行文件路径。
    """
    return SlicerInfo(
        id=slicer.id,
        display_name=slicer.display_name,
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
    # 1) Validate launch source before touching slicer detection or copy state.
    source_file_path, validation_error = _resolve_launch_request_source_path(
        request,
        registry,
    )
    if validation_error is not None:
        return JSONResponse(
            status_code=400,
            content=SlicerLaunchResponse(
                status="error",
                message=validation_error,
            ).model_dump(),
        )
    assert source_file_path is not None

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
        launch_file_path = _create_launch_copy(source_file_path, registry)
    except Exception as exc:
        _log_slicer_launch_copy_failed(
            request=request,
            status_code=500,
            original_file_path=source_file_path,
            safe_message=SLICER_LAUNCH_COPY_FAILED_MESSAGE,
            error=exc,
        )
        return JSONResponse(
            status_code=500,
            content=SlicerLaunchResponse(
                status="error",
                message=SLICER_LAUNCH_COPY_FAILED_MESSAGE,
            ).model_dump(),
        )

    # 3) Attempt launch
    try:
        success, message = launch_slicer(request.slicer_id, launch_file_path, slicers)
    except (OSError, RuntimeError, ValueError) as exc:
        _log_slicer_launch_failed(
            request=request,
            status_code=500,
            original_file_path=source_file_path,
            safe_message=SLICER_LAUNCH_FAILED_MESSAGE,
            error=exc,
            launch_copy_path=launch_file_path,
        )
        return JSONResponse(
            status_code=500,
            content=SlicerLaunchResponse(
                status="error",
                message=SLICER_LAUNCH_FAILED_MESSAGE,
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
        _log_slicer_launch_failed(
            request=request,
            status_code=500,
            original_file_path=source_file_path,
            safe_message=SLICER_LAUNCH_FAILED_MESSAGE,
            error_type="SlicerLaunchFailed",
            error_message=message,
            launch_copy_path=launch_file_path,
        )
        return JSONResponse(
            status_code=500,
            content=SlicerLaunchResponse(
                status="error",
                message=SLICER_LAUNCH_FAILED_MESSAGE,
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
