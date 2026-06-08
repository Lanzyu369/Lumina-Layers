"""Material registry sync API routes.
耗材 Registry 同步 API 路由。
"""

from __future__ import annotations

import os

from fastapi import APIRouter, File, HTTPException, UploadFile

from api.file_bridge import upload_to_tempfile
from api.schemas.single_stage import MaterialSyncRollbackRequest
from api.schemas.responses import (
    MaterialSyncInstallResponse,
    MaterialSyncRefreshResponse,
    MaterialSyncRollbackResponse,
    MaterialSyncStatusResponse,
)
from api.structured_logging import get_logger
from core.single_stage import (
    get_material_sync_status,
    import_saved_stage_a_material_archives,
    refresh_material_sync_from_registry,
    rollback_material_sync_revision,
)

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


@router.post("/refresh", response_model=MaterialSyncRefreshResponse)
async def material_sync_refresh() -> MaterialSyncRefreshResponse:
    """Pull read-only material package updates from the configured Registry.
    从已配置 Registry 只读拉取耗材包更新。

    Returns:
        MaterialSyncRefreshResponse: Refresh summary and per-package failures.
            （刷新摘要与包级失败明细）
    """
    try:
        result = refresh_material_sync_from_registry()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    log.info(
        "Material registry refresh completed",
        extra={
            "event": "material_sync_refresh_done",
            "registry_url": result["registry_url"],
            "channels": result["channels"],
            "checked_count": result["checked_count"],
            "installed_count": result["installed_count"],
            "skipped_count": result["skipped_count"],
            "failed_count": result["failed_count"],
        },
    )
    return MaterialSyncRefreshResponse(
        status="ok" if int(result["failed_count"]) == 0 else "partial",
        message=(
            f"Installed {result['installed_count']} material packages; "
            f"skipped {result['skipped_count']}; failed {result['failed_count']}"
        ),
        **result,
    )


@router.post("/rollback", response_model=MaterialSyncRollbackResponse)
async def material_sync_rollback(
    payload: MaterialSyncRollbackRequest,
) -> MaterialSyncRollbackResponse:
    """Rollback one synced material to a previously installed revision.
    将一个已同步耗材回滚到历史 revision。
    """
    try:
        result = rollback_material_sync_revision(
            material_id=payload.material_id,
            revision_id=payload.revision_id,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    log.info(
        "Material sync rollback completed",
        extra={
            "event": "material_sync_rollback_done",
            "material_id": result["material_id"],
            "revision_id": result["revision_id"],
            "channel": result["channel"],
        },
    )
    return MaterialSyncRollbackResponse(
        status="ok",
        message=f"Rolled back {result['material_id']} to {result['revision_id']}",
        **result,
    )
