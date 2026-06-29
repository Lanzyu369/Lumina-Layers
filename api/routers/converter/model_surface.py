from __future__ import annotations

from dataclasses import asdict
import json
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
from core.model_surface.artwork import render_surface_artwork
from core.model_surface.footprint import build_surface_footprint
from core.model_surface.loader import load_model_surface_mesh
from core.model_surface.selection import select_planar_component
from core.model_surface.serialization import (
    surface_footprint_from_payload,
    surface_placement_from_payload,
)
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


def resolve_surface_preview_config(
    *,
    registry: FileRegistry,
    model_file_id: str | None,
    selection_json: str | None,
    footprint_json: str | None,
    placement_json: str | None,
    source_path: str,
) -> dict | None:
    """Resolve and render optional model-surface preview config.

    解析并渲染可选的模型覆面预览配置。
    """

    supplied = [model_file_id, selection_json, footprint_json, placement_json]
    if not any(supplied):
        return None
    if not all(supplied):
        raise HTTPException(
            status_code=422,
            detail="Model surface preview requires model, selection, footprint, and placement.",
        )

    assert model_file_id is not None
    resolved = registry.resolve(model_file_id)
    if resolved is None:
        raise HTTPException(status_code=404, detail="Uploaded model file is unavailable.")
    model_path, _filename = resolved

    try:
        selection_payload = _loads_object(selection_json)
        footprint_payload = _loads_object(footprint_json)
        placement_payload = _loads_object(placement_json)
        footprint = surface_footprint_from_payload(footprint_payload)
        placement = surface_placement_from_payload(placement_payload)
        rendered = render_surface_artwork(
            source_path=source_path,
            footprint=footprint,
            placement=placement,
            output_dir=TEMP_DIR,
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError, ModelSurfaceError) as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid model surface preview configuration: {exc}",
        ) from exc

    placement_public = asdict(placement)
    placement_public["mode"] = placement.mode.value
    return {
        "surface_model_file_id": model_file_id,
        "surface_model_path": model_path,
        "surface_selection": selection_payload,
        "surface_footprint": asdict(footprint),
        "surface_placement": placement_public,
        "surface_artwork_path": str(rendered.output_path),
        "target_width_mm": rendered.target_width_mm,
        "target_height_mm": rendered.target_height_mm,
    }


def _loads_object(raw: str | None) -> dict:
    if raw is None:
        raise ValueError("missing JSON payload")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")
    return payload
