from __future__ import annotations

from dataclasses import asdict
import os
import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from api.dependencies import get_file_registry
from api.file_registry import FileRegistry
from api.schemas.model_surface import (
    ModelSurfaceSelectRequest,
    ModelSurfaceSelectResponse,
    ModelSurfaceUploadResponse,
)
from api.structured_logging import get_logger
from config import TEMP_DIR
from core.model_surface.footprint import build_surface_footprint
from core.model_surface.loader import load_model_surface_mesh
from core.model_surface.selection import select_planar_component
from core.model_surface.types import ModelSurfaceError

router = APIRouter(prefix="/model-surface")
log = get_logger(__name__)
_SUPPORTED_MODEL_EXTENSIONS = {".stl", ".obj"}
_MODEL_SURFACE_FILE_TTL_SECONDS = 3600


@router.post("/upload", response_model=ModelSurfaceUploadResponse)
async def upload_model_surface(
    model: UploadFile = File(...),
    registry: FileRegistry = Depends(get_file_registry),
) -> ModelSurfaceUploadResponse:
    """Upload an STL/OBJ model for surface-overlay selection.

    上传用于覆面选区的 STL/OBJ 模型。
    """

    suffix = Path(model.filename or "").suffix.lower()
    if suffix not in _SUPPORTED_MODEL_EXTENSIONS:
        raise HTTPException(
            status_code=422,
            detail="Only STL and OBJ model files are supported.",
        )

    fd, temp_path = tempfile.mkstemp(suffix=suffix, dir=TEMP_DIR)
    os.close(fd)
    registered = False
    try:
        with open(temp_path, "wb") as handle:
            handle.write(await model.read())
        loaded = load_model_surface_mesh(temp_path)
        file_id = registry.register_path(
            session_id=f"model-surface-{uuid.uuid4()}",
            path=temp_path,
            filename=model.filename or f"model{suffix}",
            ttl_seconds=_MODEL_SURFACE_FILE_TTL_SECONDS,
            is_public=False,
            purpose="model_surface_source",
        )
        registered = True
    except ModelSurfaceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        if not registered:
            Path(temp_path).unlink(missing_ok=True)

    warnings = [loaded.summary.unit_warning] if loaded.summary.unit_warning else []
    log.info(
        "Model surface source uploaded",
        extra={
            "event": "model_surface_upload_done",
            "model_file_id": file_id,
            "upload_filename": model.filename or "",
            "vertex_count": loaded.summary.vertex_count,
            "face_count": loaded.summary.face_count,
            "warning_count": len(warnings),
        },
    )
    return ModelSurfaceUploadResponse(
        status="ok",
        model_file_id=file_id,
        summary=loaded.summary.to_public_dict(),
        warnings=warnings,
    )


@router.post("/select", response_model=ModelSurfaceSelectResponse)
def select_model_surface(
    request: ModelSurfaceSelectRequest,
    registry: FileRegistry = Depends(get_file_registry),
) -> ModelSurfaceSelectResponse:
    """Select a connected planar face area on an uploaded model.

    在已上传模型上选择连通平面区域。
    """

    resolved = registry.resolve(request.model_file_id)
    if resolved is None:
        raise HTTPException(status_code=404, detail="Uploaded model file is unavailable.")
    model_path, _filename = resolved

    try:
        loaded = load_model_surface_mesh(model_path)
        face_index = request.hit.face_index
        if face_index is None:
            raise ModelSurfaceError(
                "A face_index is required for model-surface selection."
            )
        selection = select_planar_component(loaded.mesh, int(face_index))
        footprint = build_surface_footprint(loaded.mesh, selection.face_indices)
    except ModelSurfaceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    selection_id = str(uuid.uuid4())
    log.info(
        "Model surface selected",
        extra={
            "event": "model_surface_select_done",
            "model_file_id": request.model_file_id,
            "selection_id": selection_id,
            "face_count": selection.face_count,
            "area_mm2": round(float(selection.area_mm2), 6),
            "footprint_hole_count": footprint.hole_count,
        },
    )
    return ModelSurfaceSelectResponse(
        status="ok",
        selection_id=selection_id,
        selection=asdict(selection),
        footprint=asdict(footprint),
        warnings=[],
    )
