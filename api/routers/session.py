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
    session_entries = registry.get_session_entries(body.session_id)
    keep_file_ids = set(body.keep_file_ids or [])
    valid_keep_file_ids: set[str] = set()
    keep_paths: set[str] = set()
    for file_id in keep_file_ids:
        entry = session_entries.get(file_id)
        if entry is None:
            continue
        path = entry.get("path")
        if not path or not os.path.exists(path):
            continue
        valid_keep_file_ids.add(file_id)
        keep_paths.add(path)

    candidate_paths = {
        *(
            path
            for path in store.get_temp_file_paths(body.session_id)
            if path not in keep_paths
        ),
        *(
            entry["path"]
            for file_id, entry in session_entries.items()
            if file_id not in valid_keep_file_ids and entry.get("path")
        ),
    }
    existing_paths = {path for path in candidate_paths if os.path.exists(path)}

    store.close_except(body.session_id, keep_paths=keep_paths or None)
    registry.cleanup_session_except(
        body.session_id,
        keep_file_ids=valid_keep_file_ids or None,
    )

    cleaned_files = sum(1 for path in existing_paths if not os.path.exists(path))
    return SessionCloseResponse(
        status="ok",
        cleaned_files=cleaned_files,
    )
