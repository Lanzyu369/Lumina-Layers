"""Converter router cleanup module."""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends

from api.dependencies import get_file_registry, get_session_store
from api.file_registry import FileRegistry
from api.preview_cache_artifacts import (
    get_preview_cache_metadata,
    is_preview_cache_artifact_ref,
)
from api.replacement_history import collect_checkpoint_artifact_paths
from api.schemas.converter import (
    CleanupSessionFilesRequest,
    CleanupSessionFilesResponse,
)
from api.session_store import SessionStore
from api.structured_logging import get_logger

router = APIRouter()
log = get_logger(__name__)

def _collect_preview_cache_artifact_paths(session_data: dict | None) -> set[str]:
    """Keep the active editor cache and history until the source session closes."""

    if not session_data:
        return set()
    preview_cache = session_data.get("preview_cache")
    keep_paths = collect_checkpoint_artifact_paths(session_data)
    if is_preview_cache_artifact_ref(preview_cache):
        for field in preview_cache.get("fields", {}).values():
            path = field.get("path")
            if isinstance(path, str) and os.path.exists(path):
                keep_paths.add(path)
    if isinstance(preview_cache, dict):
        metadata = get_preview_cache_metadata(preview_cache)
        vector_source = metadata.get("vector_parse_clip_cache_path")
        if isinstance(vector_source, str) and os.path.exists(vector_source):
            keep_paths.add(vector_source)
    return keep_paths


def _collect_regeneration_input_paths(session_data: dict | None) -> set[str]:
    """Return temp-file paths required for another generate call."""

    if not session_data:
        return set()
    keep_paths: set[str] = _collect_preview_cache_artifact_paths(session_data)
    for key in ("image_path", "lut_path"):
        path = session_data.get(key)
        if not isinstance(path, str) or not path:
            continue
        if path == "__material_archive__":
            continue
        if os.path.exists(path):
            keep_paths.add(path)
    return keep_paths


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
    keep_paths: set[str] = _collect_regeneration_input_paths(
        store.get(body.session_id)
    )
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
    log.info(
        "Session files cleaned",
        extra={
            "event": "converter_cleanup_session_files_done",
            "session_id": body.session_id,
            "cleaned": cleaned,
            "keep_file_id_count": len(valid_keep_file_ids),
            "keep_path_count": len(keep_paths),
            "candidate_path_count": len(candidate_paths),
        },
    )
    return CleanupSessionFilesResponse(
        status="success",
        cleaned=cleaned,
    )
