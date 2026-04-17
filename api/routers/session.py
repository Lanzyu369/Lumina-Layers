"""Session heartbeat and close router."""

from __future__ import annotations

import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import get_file_registry, get_session_store
from api.file_registry import FileRegistry
from api.schemas.session import (
    SessionCloseResponse,
    SessionHeartbeatResponse,
    SessionRequest,
)
from api.session_store import SessionStore

router = APIRouter(prefix="/api/session", tags=["Session"])


@router.post("/heartbeat")
def heartbeat(
    body: SessionRequest,
    store: SessionStore = Depends(get_session_store),
) -> SessionHeartbeatResponse:
    """Renew a session lease.
    续期指定 Session 的租约。
    """
    expires_at = store.touch(body.session_id)
    if expires_at is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return SessionHeartbeatResponse(
        status="ok",
        expires_at=datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat(),
    )


@router.post("/close")
def close_session(
    body: SessionRequest,
    store: SessionStore = Depends(get_session_store),
    registry: FileRegistry = Depends(get_file_registry),
) -> SessionCloseResponse:
    """Close a session immediately and clean its registered files.
    立即关闭指定 Session，并清理其注册文件。
    """
    candidate_paths = {
        *store.get_temp_file_paths(body.session_id),
        *(
            entry["path"]
            for entry in registry.get_session_entries(body.session_id).values()
            if entry.get("path")
        ),
    }
    existing_paths = {path for path in candidate_paths if os.path.exists(path)}

    store.close(body.session_id)
    registry.cleanup_session(body.session_id)

    cleaned_files = sum(1 for path in existing_paths if not os.path.exists(path))
    return SessionCloseResponse(
        status="ok",
        cleaned_files=cleaned_files,
    )
