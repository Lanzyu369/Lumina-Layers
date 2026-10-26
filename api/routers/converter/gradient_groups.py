"""Converter gradient-groups read endpoint.

暴露预览完成时缓存的"渐变海带纹分组"分析结果。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import get_session_store
from api.schemas.converter import GradientGroupsResponse
from api.session_store import SessionStore
from api.structured_logging import get_logger

from .common import _require_session

router = APIRouter()
log = get_logger(__name__)


@router.get("/gradient-groups/{session_id}", response_model=GradientGroupsResponse)
def get_gradient_groups(
    session_id: str,
    store: SessionStore = Depends(get_session_store),
) -> GradientGroupsResponse:
    """Return the preview's gradient banding analysis cached in the session.
    返回预览时同步计算并缓存在 session 中的渐变海带纹分组结果。

    The preview endpoint computes gradient groups synchronously and writes
    them into ``session["gradient_groups"]``. This endpoint is a pure read:
    if the session has no groups yet (e.g. because the preview failed, the
    analysis degraded, or the session pre-dates this feature) we return
    ``status="unavailable"`` with an empty list so the UI can degrade
    gracefully without surfacing a visible error.

    Status values:
        ``ok``: Groups available. Payload is the list of gradient groups
            sorted by descending pixel count.
        ``unavailable``: The session does not carry gradient-group
            metadata. The ``groups`` field is an empty list. Callers
            should treat this as "no banding detected" or "feature off".

    Raises:
        HTTPException 404: Session not found.
    """
    session_data = _require_session(store, session_id)
    groups = session_data.get("gradient_groups")
    if not isinstance(groups, list):
        return GradientGroupsResponse(
            session_id=session_id, status="unavailable", groups=[]
        )
    try:
        return GradientGroupsResponse(
            session_id=session_id, status="ok", groups=groups
        )
    except (TypeError, ValueError) as exc:
        # The cached payload has an unexpected shape — log and degrade.
        log.warning(
            "Cached gradient_groups payload failed validation",
            extra={
                "event": "gradient_groups_payload_invalid",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
        )
        raise HTTPException(
            status_code=500,
            detail="Cached gradient group payload is corrupted",
        ) from exc
