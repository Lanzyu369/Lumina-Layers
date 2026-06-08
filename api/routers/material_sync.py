"""Material registry sync API routes.
耗材 Registry 同步 API 路由。
"""

from __future__ import annotations

import os

from fastapi import APIRouter, File, HTTPException, UploadFile

from api.file_bridge import upload_to_tempfile
from api.schemas.responses import MaterialSyncInstallResponse, MaterialSyncStatusResponse
from api.structured_logging import get_logger
from core.single_stage import get_material_sync_status, import_saved_stage_a_material_archives

router = APIRouter(prefix="/api/material-sync", tags=["Material Sync"])
log = get_logger(__name__)


@router.get("/status", response_model=MaterialSyncStatusResponse)
async def material_sync_status() -> MaterialSyncStatusResponse:
    """Return local material sync-index health and installed package presence.
    返回本地耗材同步索引健康状态与已安装包存在性信息。

    Returns:
        MaterialSyncStatusResponse: Status payload for local/cloud sync UI.
            （用于本地/云同步 UI 的状态载荷）
    """
    try:
        status_payload = get_material_sync_status()
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    response = MaterialSyncStatusResponse(
        status="ok",
        message="Material sync status loaded",
        **status_payload,
    )
    log.info(
        "Material sync status loaded",
        extra={
            "event": "material_sync_status_done",
            "index_state": response.index_state,
            "installed_count": response.installed_count,
        },
    )
    return response


@router.post("/install", response_model=MaterialSyncInstallResponse)
async def material_sync_install(
    archive: UploadFile = File(...),
) -> MaterialSyncInstallResponse:
    """Install one uploaded material package into the local material library.
    将上传的耗材包安装到本地耗材库。

    Args:
        archive: ZIP package produced by material export/registry download.
            （由耗材导出或 Registry 下载得到的 ZIP 包）

    Returns:
        MaterialSyncInstallResponse: Installed material summaries.
            （已安装耗材摘要）
    """
    filename = archive.filename or ""
    if not filename.lower().endswith(".zip"):
        raise HTTPException(
            status_code=422,
            detail=f"Uploaded file must be a ZIP archive: {filename or '<unnamed>'}",
        )

    archive_path: str | None = None
    try:
        archive_path = await upload_to_tempfile(archive, suffix=".zip")
        result = import_saved_stage_a_material_archives(archive_path=archive_path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, TypeError, OSError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        if archive_path is not None:
            try:
                os.remove(archive_path)
            except OSError:
                pass

    log.info(
        "Material package installed",
        extra={
            "event": "material_sync_install_done",
            "installed_count": len(result.imported_materials),
        },
    )
    return MaterialSyncInstallResponse(
        status="ok",
        message=f"Installed {len(result.imported_materials)} material packages",
        installed_count=len(result.imported_materials),
        installed_materials=result.imported_materials,
    )
