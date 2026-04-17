"""Converter router cleanup module."""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends

from api.dependencies import get_file_registry, get_session_store
from api.file_registry import FileRegistry
from api.schemas.converter import (
    CleanupSessionFilesRequest,
    CleanupSessionFilesResponse,
)
from api.session_store import SessionStore

router = APIRouter()


@router.post("/cleanup-session-files")
def cleanup_session_files(
    body: CleanupSessionFilesRequest,
    registry: FileRegistry = Depends(get_file_registry),
    store: SessionStore = Depends(get_session_store),
) -> CleanupSessionFilesResponse:
    """Delete intermediate files for a session, preserving specified file IDs.
    删除 session 的中间文件（预览 PNG、GLB 等），保留指定的文件 ID（如已下载的 3MF）。
    """
    keep_file_ids = set(body.keep_file_ids) if body.keep_file_ids else set()
    session_entries = registry.get_session_entries(body.session_id)
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

    store.cleanup_temp_files_except(body.session_id, keep_paths=keep_paths or None)
    registry.cleanup_session_except(
        body.session_id,
        keep_file_ids=valid_keep_file_ids or None,
    )
    cleaned = sum(1 for path in existing_paths if not os.path.exists(path))
    return CleanupSessionFilesResponse(
        status="success",
        cleaned=cleaned,
    )
