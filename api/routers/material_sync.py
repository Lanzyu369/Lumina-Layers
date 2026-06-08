"""Material registry sync API routes.
耗材 Registry 同步 API 路由。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from api.schemas.responses import MaterialSyncStatusResponse
from api.structured_logging import get_logger
from core.single_stage import get_material_sync_status

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
