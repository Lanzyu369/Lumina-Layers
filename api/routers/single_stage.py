"""Single-stage workflow API routes."""

from __future__ import annotations

import os
import uuid
import zipfile

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from api.dependencies import get_file_registry, get_session_store
from api.file_bridge import upload_to_tempfile
from api.file_registry import FileRegistry
from api.schemas.responses import SingleStageExtractResponse, StageAFitResponse
from api.session_store import SessionStore
from api.structured_logging import bind_session_id
from core.single_stage import extract_single_stage_dataset, fit_stage_a_from_stage_json

router = APIRouter(prefix="/api/extractor", tags=["Extractor"])


@router.post("/extract-single-stage")
async def extractor_extract_single_stage(
    dataset_zip: UploadFile = File(..., description="Single-stage dataset ZIP"),
    store: SessionStore = Depends(get_session_store),
    registry: FileRegistry = Depends(get_file_registry),
) -> SingleStageExtractResponse:
    """Extract a single-stage dataset zip into stage JSON."""
    if not (dataset_zip.filename or "").lower().endswith(".zip"):
        raise HTTPException(
            status_code=422,
            detail="Single-stage dataset must be uploaded as a ZIP file",
        )

    zip_path: str | None = None
    session_id: str | None = None
    try:
        zip_path = await upload_to_tempfile(dataset_zip, suffix=".zip")
        result = extract_single_stage_dataset(zip_path)
        session_id = store.create()
        store.register_temp_file(session_id, zip_path)
        store.register_temp_file(session_id, result.stage_json_path)
        store.put(session_id, "single_stage_stage_json_path", result.stage_json_path)
        store.put(session_id, "single_stage_dataset_summary", result.dataset_summary)
        store.put(session_id, "single_stage_warnings", result.warnings)
    except FileNotFoundError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except zipfile.BadZipFile:
        raise HTTPException(status_code=422, detail="Malformed ZIP archive")
    except (ValueError, TypeError, OSError, RuntimeError) as e:
        raise HTTPException(status_code=422, detail=str(e))
    finally:
        if zip_path is not None and session_id is None:
            try:
                os.remove(zip_path)
            except OSError:
                pass

    stage_json_id = registry.register_path(session_id, result.stage_json_path)
    return SingleStageExtractResponse(
        session_id=session_id,
        status="ok",
        message=f"Single-stage dataset extracted with {len(result.warnings)} warnings.",
        stage_json_url=f"/api/files/{stage_json_id}",
        warnings=result.warnings,
        dataset_summary=result.dataset_summary,
    )


@router.post("/fit-stage-a")
async def extractor_fit_stage_a(
    session_id: str | None = Form(None),
    stage_json: UploadFile | None = File(None),
    store: SessionStore = Depends(get_session_store),
    registry: FileRegistry = Depends(get_file_registry),
) -> StageAFitResponse:
    """Fit Stage A parameters from single-stage JSON or session state."""
    stage_json_path: str | None = None
    sid_for_registry: str | None = None

    if session_id:
        bind_session_id(session_id)
        session_data = store.get(session_id)
        if session_data is None:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
        stage_json_path = session_data.get("single_stage_stage_json_path")
        if not stage_json_path:
            raise HTTPException(
                status_code=400,
                detail="Session does not contain an extracted single-stage dataset",
            )
        sid_for_registry = session_id
    elif stage_json is not None:
        stage_json_path = await upload_to_tempfile(stage_json, suffix=".json")
        sid_for_registry = store.create()
        store.register_temp_file(sid_for_registry, stage_json_path)
        store.put(sid_for_registry, "single_stage_stage_json_path", stage_json_path)
    else:
        raise HTTPException(
            status_code=422,
            detail="Provide either session_id or a stage_json upload",
        )

    try:
        result = fit_stage_a_from_stage_json(stage_json_path)
    except FileNotFoundError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except (ValueError, TypeError, OSError, RuntimeError) as e:
        raise HTTPException(status_code=422, detail=str(e))

    store.register_temp_file(sid_for_registry, result.params_path)
    store.put(sid_for_registry, "stage_a_params_path", result.params_path)
    store.put(sid_for_registry, "stage_a_fit_summary", result.fit_summary)

    params_id = registry.register_path(sid_for_registry, result.params_path)
    return StageAFitResponse(
        status="ok",
        message="Stage A parameters fitted successfully",
        stage_a_params_url=f"/api/files/{params_id}",
        fit_summary=result.fit_summary,
    )
