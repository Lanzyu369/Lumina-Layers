"""Single-stage workflow API routes."""

from __future__ import annotations

import json
import os
import uuid
import zipfile
from typing import Any

import anyio
import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from api.dependencies import get_file_registry, get_session_store
from api.file_bridge import ndarray_to_png_bytes, upload_to_ndarray, upload_to_tempfile
from api.file_registry import FileRegistry
from api.schemas.single_stage import (
    GradientCardMaterialUpdateRequest,
    MaterialLibraryBulkExportRequest,
    MaterialRecipePreviewRequest,
    MaterialRecipeSwatchRequest,
    MaterialRecipeSwatchResponse,
)
from api.schemas.responses import (
    GradientCardMaterialBulkExportResponse,
    GradientCardMaterialBulkImportResponse,
    GradientCardMaterialDeleteResponse,
    GradientCardMaterialLibraryResponse,
    GradientCardMaterialSaveResponse,
    GradientCardMaterialUpdateResponse,
    GradientCardStageAExtractResponse,
    MaterialColorSuggestionItem,
    MaterialColorSuggestionsResponse,
    MaterialRecipeLayerResponse,
    MaterialRecipePreviewResponse,
    MaterialSolverCacheBuildResponse,
    MaterialSolverCacheDeleteResponse,
    MaterialSolverCacheEntryResponse,
    MaterialSolverCacheListResponse,
    MaterialSolverCacheStatusResponse,
    SingleStageExtractResponse,
    StageAFitResponse,
)
from api.session_store import SessionStore
from api.structured_logging import bind_session_id, get_logger
from core.material_cache import (
    ALLOWED_GRID_RESOLUTIONS,
    ALLOWED_LAYER_HEIGHTS_MM as _CACHE_ALLOWED_LAYER_HEIGHTS,  # noqa: N811
    DEFAULT_GRID_RESOLUTION,
    build_material_solver_cache,
    cache_file_path,
    delete_cached_entry,
    fingerprint_palette,
    list_cached_entries,
    load_material_solver_cache,
    save_material_solver_cache,
)
from core.material_color_solver import (
    DEFAULT_SUGGEST_MAX_COMBINATIONS,
    DEFAULT_SUGGEST_MIN_SPACING,
    DEFAULT_SUGGEST_TOP_K,
    MAX_LAYER_COUNT as _SOLVER_MAX_LAYER_COUNT,  # noqa: N811
    MIN_LAYER_COUNT as _SOLVER_MIN_LAYER_COUNT,  # noqa: N811
    ColorSuggestion,
    forward_model,
    linear_to_srgb_uint8,
    suggest_colors_for_target,
)
from core.material_lut_synthesis import load_multiple_materials
from core.single_stage import (
    delete_saved_stage_a_material_archive,
    export_saved_stage_a_material_archives,
    extract_single_stage_dataset,
    extract_stage_a_material_from_gradient_cards,
    fit_stage_a_from_stage_json,
    import_saved_stage_a_material_archives,
    list_saved_stage_a_material_archives,
    save_stage_a_material_archive,
    update_saved_stage_a_material_archive_metadata,
)

router = APIRouter(prefix="/api/extractor", tags=["Extractor"])
log = get_logger(__name__)
GRADIENT_CARD_PREVIEW_TTL_SECONDS = 600
MATERIAL_LIBRARY_FILE_TTL_SECONDS = 600
MATERIAL_SWATCH_EXPORT_TTL_SECONDS = 8 * 60 * 60


def _parse_corner_points(raw_points: str, field_name: str) -> list[list[float]]:
    try:
        points = json.loads(raw_points)
    except (json.JSONDecodeError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=f"Invalid {field_name} JSON: {exc}")
    if not isinstance(points, list) or len(points) != 4:
        raise HTTPException(
            status_code=422,
            detail=f"{field_name} must contain exactly 4 points",
        )
    return points


_VALID_MANUAL_ORIENTATION_LABELS: frozenset[str] = frozenset(
    {
        "identity",
        "rotate_90_cw",
        "rotate_180",
        "rotate_90_ccw",
        "flip_horizontal",
        "flip_vertical",
        "transpose",
        "transverse",
    }
)


_GRADIENT_CARD_ALLOWED_IMAGE_SOURCES: tuple[str, ...] = ("raw",)


def _normalize_image_source(raw: str | None) -> str | None:
    """Normalize and validate the gradient-card ``image_source`` form value.
    规范化并校验梯度卡 ``image_source`` 表单值。

    Stage A currently only supports ``"raw"`` direct camera/scanner captures.
    The historical ``"restored"`` tag (white-balanced / geometrically restored
    renders) is intentionally rejected at the API boundary as well, because:

    1. The frontend selector is hidden and ``imageSource`` is pinned to
       ``"raw"`` (`@frontend/src/components/GradientCardExtractPanel.tsx`).
    2. Allowing ``"restored"`` here creates a trap-door: an archive tagged
       ``restored`` cannot later be merged via the UI, since the merge
       consistency check in
       ``core.single_stage.materials.save_stage_a_material_archive`` rejects
       mixing ``raw`` and ``restored`` runs.

    The whitelist keeps API and UI in lock-step until a UI surface is added
    back to manage ``restored`` captures explicitly.

    目前 Stage A 仅支持 ``"raw"``。``"restored"`` 在前端选择器已隐藏的情况下
    若由 API 写入，会形成无法通过 UI 合并的死路；故双锁拒绝。

    Args:
        raw (str | None): Raw form value, possibly ``None`` or whitespace.

    Returns:
        str | None: ``None`` if the input is empty/blank (lets the core layer
        apply its ``raw`` default); otherwise the validated lowercase tag.

    Raises:
        HTTPException: ``422`` for any non-empty value outside the whitelist.
    """
    if raw is None:
        return None
    cleaned = raw.strip().lower()
    if not cleaned:
        return None
    if cleaned not in _GRADIENT_CARD_ALLOWED_IMAGE_SOURCES:
        allowed = ", ".join(repr(s) for s in _GRADIENT_CARD_ALLOWED_IMAGE_SOURCES)
        raise HTTPException(
            status_code=422,
            detail=(
                f"Unsupported image_source '{raw}'. Stage A currently only "
                f"accepts {allowed}; the gradient-card UI no longer exposes "
                "other capture origins."
            ),
        )
    return cleaned


def _normalize_manual_orientation(raw: str | None) -> str | None:
    """Normalize an optional manual orientation form value.
    规范化可选的手动方向表单值。

    Treats empty/blank/``"auto"``/``"none"`` as "no override". Validates the
    label against the canonical orientation enum and raises ``HTTPException``
    on unknown labels.
    """
    if raw is None:
        return None
    cleaned = raw.strip().lower()
    if not cleaned or cleaned in {"auto", "none", "null"}:
        return None
    if cleaned not in _VALID_MANUAL_ORIENTATION_LABELS:
        valid = ", ".join(sorted(_VALID_MANUAL_ORIENTATION_LABELS))
        raise HTTPException(
            status_code=422,
            detail=f"Invalid manual orientation label {raw!r}; expected one of: {valid}",
        )
    return cleaned


def _rollback_imported_materials(directory_names: list[str]) -> None:
    for directory_name in reversed(directory_names):
        try:
            delete_saved_stage_a_material_archive(directory_name=directory_name)
        except (FileNotFoundError, ValueError, TypeError, OSError, RuntimeError):
            pass


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
    log.info(
        "Single-stage dataset extracted",
        extra={
            "event": "extractor_extract_single_stage_done",
            "session_id": session_id,
            "dataset_summary_count": (
                len(result.dataset_summary)
                if isinstance(result.dataset_summary, dict)
                else 0
            ),
            "warning_count": len(result.warnings),
            "stage_json_id": stage_json_id,
        },
    )
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
    source_mode: str

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
        source_mode = "session"
    elif stage_json is not None:
        stage_json_path = await upload_to_tempfile(stage_json, suffix=".json")
        sid_for_registry = store.create()
        store.register_temp_file(sid_for_registry, stage_json_path)
        store.put(sid_for_registry, "single_stage_stage_json_path", stage_json_path)
        source_mode = "upload"
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
    log.info(
        "Stage A parameters fitted",
        extra={
            "event": "extractor_fit_stage_a_done",
            "session_id": sid_for_registry,
            "params_id": params_id,
            "source_mode": source_mode,
            "fit_summary_count": (
                len(result.fit_summary)
                if isinstance(result.fit_summary, dict)
                else 0
            ),
        },
    )
    return StageAFitResponse(
        status="ok",
        message="Stage A parameters fitted successfully",
        stage_a_params_url=f"/api/files/{params_id}",
        fit_summary=result.fit_summary,
    )


@router.post("/extract-gradient-card-stage-a")
async def extractor_extract_gradient_card_stage_a(
    white_image: UploadFile = File(..., description="White-substrate gradient card image"),
    black_image: UploadFile = File(..., description="Black-substrate gradient card image"),
    dataset_zip: UploadFile = File(..., description="Generated gradient card kit ZIP"),
    white_corner_points: str = Form(..., description="White image corners JSON [[x,y], ...]"),
    black_corner_points: str = Form(..., description="Black image corners JSON [[x,y], ...]"),
    manual_white_orientation: str | None = Form(
        None,
        description=(
            "Optional manual orientation label for the white capture; "
            "one of identity, rotate_90_cw, rotate_180, rotate_90_ccw, "
            "flip_horizontal, flip_vertical, transpose, transverse"
        ),
    ),
    manual_black_orientation: str | None = Form(
        None,
        description="Optional manual orientation label for the black capture (same enum as white)",
    ),
    image_source: str | None = Form(
        None,
        description=(
            "Optional gradient-card capture origin tag. Currently only "
            "'raw' (direct camera/scanner capture, default) is accepted; "
            "the historical 'restored' tag is rejected at the API "
            "boundary because the gradient-card UI no longer exposes a "
            "selector for it, and a 'restored'-tagged archive cannot "
            "later be merged via the UI."
        ),
    ),
    store: SessionStore = Depends(get_session_store),
    registry: FileRegistry = Depends(get_file_registry),
) -> GradientCardStageAExtractResponse:
    """Extract Stage A material data from dual gradient-card images."""
    if not (dataset_zip.filename or "").lower().endswith(".zip"):
        raise HTTPException(status_code=422, detail="Gradient card kit must be uploaded as a ZIP file")

    white_points = _parse_corner_points(white_corner_points, "white_corner_points")
    black_points = _parse_corner_points(black_corner_points, "black_corner_points")
    manual_white = _normalize_manual_orientation(manual_white_orientation)
    manual_black = _normalize_manual_orientation(manual_black_orientation)
    validated_image_source = _normalize_image_source(image_source)
    zip_path: str | None = None
    session_id: str | None = None
    try:
        white_rgb = await upload_to_ndarray(white_image)
        black_rgb = await upload_to_ndarray(black_image)
        zip_path = await upload_to_tempfile(dataset_zip, suffix=".zip")
        result = extract_stage_a_material_from_gradient_cards(
            white_rgb,
            black_rgb,
            white_points,
            black_points,
            zip_path,
            manual_white_orientation=manual_white,
            manual_black_orientation=manual_black,
            image_source=validated_image_source,
        )
        session_id = store.create()
        bind_session_id(session_id)
        store.register_temp_file(session_id, zip_path)
        store.register_temp_file(session_id, result.params_path)
        store.put(session_id, "gradient_card_stage_a_params", result.params_payload)
        store.put(session_id, "gradient_card_fit_summary", result.fit_summary)
        store.put(session_id, "gradient_card_material_summary", result.material_summary)
        store.put(session_id, "gradient_card_source_summary", result.source_summary)
        stage_a_id = registry.register_path(session_id, result.params_path)
        white_warp_id = registry.register_bytes(
            session_id,
            ndarray_to_png_bytes(result.white_warp_rgb),
            "white_gradient_warp.png",
            ttl_seconds=GRADIENT_CARD_PREVIEW_TTL_SECONDS,
        )
        black_warp_id = registry.register_bytes(
            session_id,
            ndarray_to_png_bytes(result.black_warp_rgb),
            "black_gradient_warp.png",
            ttl_seconds=GRADIENT_CARD_PREVIEW_TTL_SECONDS,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    except (ValueError, TypeError, OSError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    finally:
        if zip_path is not None and session_id is None:
            try:
                os.remove(zip_path)
            except OSError:
                pass

    log.info(
        "Gradient card Stage A material extracted",
        extra={
            "event": "extractor_extract_gradient_card_stage_a_done",
            "session_id": session_id,
            "warning_count": len(result.warnings),
            "material_summary_count": (
                len(result.material_summary)
                if isinstance(result.material_summary, dict)
                else 0
            ),
            "manual_white_orientation": manual_white,
            "manual_black_orientation": manual_black,
            "stage_a_id": stage_a_id,
        },
    )
    return GradientCardStageAExtractResponse(
        session_id=session_id,
        status="ok",
        message="Gradient card Stage A material extracted successfully",
        stage_a_params_url=f"/api/files/{stage_a_id}",
        white_warp_preview_url=f"/api/files/{white_warp_id}",
        black_warp_preview_url=f"/api/files/{black_warp_id}",
        fit_summary=result.fit_summary,
        material_summary=result.material_summary,
        orientation_ranking=result.fit_summary.get("orientation_ranking"),
        warnings=result.warnings,
    )


@router.post("/save-gradient-card-material")
async def extractor_save_gradient_card_material(
    session_id: str = Form(...),
    material_name: str = Form(...),
    target_directory_name: str | None = Form(None),
    save_mode: str = Form("merge"),
    brand: str | None = Form(None),
    store: SessionStore = Depends(get_session_store),
    registry: FileRegistry = Depends(get_file_registry),
) -> GradientCardMaterialSaveResponse:
    """Persist a computed gradient-card Stage A material archive."""
    bind_session_id(session_id)
    session_data = store.get(session_id)
    if session_data is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    cleaned_material_name = material_name.strip()
    if not cleaned_material_name:
        raise HTTPException(status_code=422, detail="material_name is required")

    params_payload = session_data.get("gradient_card_stage_a_params")
    fit_summary = session_data.get("gradient_card_fit_summary")
    material_summary = session_data.get("gradient_card_material_summary")
    source_summary = session_data.get("gradient_card_source_summary")
    if not isinstance(params_payload, dict) or not isinstance(fit_summary, dict) or not isinstance(material_summary, dict) or not isinstance(source_summary, dict):
        raise HTTPException(
            status_code=400,
            detail="Session does not contain a computed gradient-card Stage A result",
        )

    try:
        validated_save_mode = save_mode.strip().lower() if isinstance(save_mode, str) else "merge"
        if validated_save_mode not in ("merge", "override"):
            validated_save_mode = "merge"
        result = save_stage_a_material_archive(
            material_name=cleaned_material_name,
            params_payload=params_payload,
            fit_summary=fit_summary,
            source_summary=source_summary,
            material_summary=material_summary,
            existing_directory_name=target_directory_name.strip() if isinstance(target_directory_name, str) and target_directory_name.strip() else None,
            save_mode=validated_save_mode,
            brand=brand.strip() if isinstance(brand, str) and brand.strip() else None,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except (ValueError, TypeError, OSError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    persistent_registry_session = f"material:{uuid.uuid4().hex}"
    material_id = registry.register_path(
        persistent_registry_session,
        result.archive_path,
        ttl_seconds=MATERIAL_LIBRARY_FILE_TTL_SECONDS,
    )
    stage_a_id = registry.register_path(
        persistent_registry_session,
        result.stage_a_params_path,
        ttl_seconds=MATERIAL_LIBRARY_FILE_TTL_SECONDS,
    )
    verification_count = int(result.material_summary.get("verification_count") or 1)
    directory_name = getattr(result, "directory_name", None)
    if not isinstance(directory_name, str) or not directory_name:
        directory_name = str(
            result.material_summary.get("directory_name")
            or os.path.splitext(os.path.basename(result.archive_path))[0]
        )
    log.info(
        "Gradient card material saved",
        extra={
            "event": "extractor_save_gradient_card_material_done",
            "session_id": session_id,
            "material_name": cleaned_material_name,
            "directory_name": directory_name,
            "verification_count": verification_count,
            "save_mode": validated_save_mode,
            "material_id": material_id,
        },
    )
    return GradientCardMaterialSaveResponse(
        status="ok",
        message=(
            f"Gradient card verification saved successfully ({verification_count} runs aggregated)"
            if verification_count > 1
            else "Gradient card material saved successfully"
        ),
        material_file_url=f"/api/files/{material_id}",
        stage_a_params_url=f"/api/files/{stage_a_id}",
        material_summary=result.material_summary,
    )


@router.delete("/gradient-card-materials/{directory_name:path}")
async def extractor_delete_gradient_card_material(
    directory_name: str,
) -> GradientCardMaterialDeleteResponse:
    """Delete a saved gradient-card material archive.
    删除已保存的梯度卡耗材档案。
    """
    try:
        result = delete_saved_stage_a_material_archive(directory_name=directory_name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except (ValueError, TypeError, OSError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    log.info(
        "Gradient card material deleted",
        extra={
            "event": "extractor_delete_gradient_card_material_done",
            "directory_name": result.directory_name,
            "material_name": result.material_name,
        },
    )
    return GradientCardMaterialDeleteResponse(
        status="ok",
        message="Gradient card material deleted successfully",
        directory_name=result.directory_name,
        material_name=result.material_name,
    )


@router.patch("/gradient-card-materials/{directory_name:path}")
async def extractor_update_gradient_card_material(
    directory_name: str,
    payload: GradientCardMaterialUpdateRequest,
    registry: FileRegistry = Depends(get_file_registry),
) -> GradientCardMaterialUpdateResponse:
    """Update saved gradient-card material metadata.
    更新已保存的梯度卡耗材元数据。
    """
    update_kwargs: dict[str, Any] = {
        "directory_name": directory_name,
        "material_name": payload.material_name,
        "brand": payload.brand,
    }
    if payload.estimated_rgb is not None:
        update_kwargs["estimated_rgb"] = payload.estimated_rgb
    try:
        result = update_saved_stage_a_material_archive_metadata(**update_kwargs)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except (ValueError, TypeError, OSError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    persistent_registry_session = f"material-library:{uuid.uuid4().hex}"
    material_file_url = f"/api/files/{registry.register_path(
        persistent_registry_session,
        result.archive_path,
        ttl_seconds=MATERIAL_LIBRARY_FILE_TTL_SECONDS,
    )}"
    stage_a_params_url = f"/api/files/{registry.register_path(
        persistent_registry_session,
        result.stage_a_params_path,
        ttl_seconds=MATERIAL_LIBRARY_FILE_TTL_SECONDS,
    )}"
    material_name = (
        payload.material_name
        if payload.material_name is not None
        else str(
            result.material_summary.get("material_name")
            or result.material_summary.get("name")
            or ""
        )
    )
    metadata_keys_updated = sum(
        1
        for value in (payload.material_name, payload.brand, payload.estimated_rgb)
        if value is not None
    )
    log.info(
        "Gradient card material metadata updated",
        extra={
            "event": "extractor_update_gradient_card_material_done",
            "directory_name": directory_name,
            "material_name": material_name,
            "metadata_keys_updated": metadata_keys_updated,
        },
    )
    return GradientCardMaterialUpdateResponse(
        status="ok",
        message="Gradient card material updated successfully",
        material={
            **result.material_summary,
            "material_file_url": material_file_url,
            "stage_a_params_url": stage_a_params_url,
        },
    )


@router.post("/gradient-card-materials/export")
async def extractor_export_gradient_card_materials(
    payload: MaterialLibraryBulkExportRequest,
    registry: FileRegistry = Depends(get_file_registry),
) -> GradientCardMaterialBulkExportResponse:
    """Export multiple saved gradient-card materials as one ZIP archive.
    将多个已保存的梯度卡耗材导出为一个 ZIP 归档。
    """
    try:
        result = export_saved_stage_a_material_archives(
            directory_names=payload.directory_names,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except (ValueError, TypeError, OSError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    persistent_registry_session = f"material-export:{uuid.uuid4().hex}"
    download_id = registry.register_path(
        persistent_registry_session,
        result.archive_path,
        filename=result.download_filename,
        ttl_seconds=MATERIAL_LIBRARY_FILE_TTL_SECONDS,
    )
    log.info(
        "Gradient card materials exported",
        extra={
            "event": "extractor_export_gradient_card_materials_done",
            "exported_count": len(result.exported_directory_names),
            "download_id": download_id,
            "download_filename": result.download_filename,
        },
    )
    return GradientCardMaterialBulkExportResponse(
        status="ok",
        message=f"Exported {len(result.exported_directory_names)} saved materials",
        download_url=f"/api/files/{download_id}",
        filename=result.download_filename,
        exported_count=len(result.exported_directory_names),
        exported_directory_names=result.exported_directory_names,
    )


@router.post("/gradient-card-materials/import")
async def extractor_import_gradient_card_materials(
    archives: list[UploadFile] = File(...),
) -> GradientCardMaterialBulkImportResponse:
    """Import one or more saved-material ZIP archives into the material library.
    导入一个或多个已保存耗材 ZIP 归档到耗材库。
    """
    if not archives:
        raise HTTPException(status_code=422, detail="At least one archive must be uploaded")

    uploaded_archive_paths: list[str] = []
    imported_materials: list[dict[str, object]] = []
    imported_directory_names: list[str] = []
    try:
        for archive in archives:
            filename = archive.filename or ""
            if not filename.lower().endswith(".zip"):
                raise HTTPException(
                    status_code=422,
                    detail=f"Uploaded file must be a ZIP archive: {filename or '<unnamed>'}",
                )
            archive_path = await upload_to_tempfile(archive, suffix=".zip")
            uploaded_archive_paths.append(archive_path)
            result = import_saved_stage_a_material_archives(archive_path=archive_path)
            imported_materials.extend(result.imported_materials)
            imported_directory_names.extend(
                str(item.get("directory_name") or "")
                for item in result.imported_materials
                if isinstance(item.get("directory_name"), str)
                and str(item.get("directory_name") or "").strip()
            )
    except HTTPException:
        _rollback_imported_materials(imported_directory_names)
        raise
    except FileNotFoundError as exc:
        _rollback_imported_materials(imported_directory_names)
        raise HTTPException(status_code=404, detail=str(exc))
    except (ValueError, TypeError, OSError, RuntimeError) as exc:
        _rollback_imported_materials(imported_directory_names)
        raise HTTPException(status_code=422, detail=str(exc))
    finally:
        for archive_path in uploaded_archive_paths:
            try:
                os.remove(archive_path)
            except OSError:
                pass

    log.info(
        "Gradient card materials imported",
        extra={
            "event": "extractor_import_gradient_card_materials_done",
            "imported_count": len(imported_materials),
            "imported_directory_names_count": len(imported_directory_names),
            "archives_received": len(archives),
        },
    )
    return GradientCardMaterialBulkImportResponse(
        status="ok",
        message=f"Imported {len(imported_materials)} saved materials",
        imported_count=len(imported_materials),
        imported_materials=imported_materials,
    )


@router.get("/gradient-card-materials")
async def extractor_list_gradient_card_materials(
    registry: FileRegistry = Depends(get_file_registry),
) -> GradientCardMaterialLibraryResponse:
    """List saved gradient-card material archives.
    列出已保存的梯度卡耗材档案。
    """
    try:
        materials = list_saved_stage_a_material_archives()
    except (ValueError, TypeError, OSError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    persistent_registry_session = f"material-library:{uuid.uuid4().hex}"
    response_items: list[dict[str, object]] = []
    for item in materials:
        material_file_url = (
            f"/api/files/{registry.register_path(
                persistent_registry_session,
                str(item['archive_path']),
                ttl_seconds=MATERIAL_LIBRARY_FILE_TTL_SECONDS,
            )}"
        )
        stage_a_path = item.get("stage_a_params_path")
        stage_a_params_url = (
            f"/api/files/{registry.register_path(
                persistent_registry_session,
                str(stage_a_path),
                ttl_seconds=MATERIAL_LIBRARY_FILE_TTL_SECONDS,
            )}"
            if isinstance(stage_a_path, str) and stage_a_path
            else None
        )
        response_items.append(
            {
                **item,
                "material_file_url": material_file_url,
                "stage_a_params_url": stage_a_params_url,
            }
        )

    return GradientCardMaterialLibraryResponse(
        status="ok",
        message=f"Loaded {len(response_items)} saved materials",
        materials=response_items,
    )


# ---------------------------------------------------------------------------
# Material-solver cache (64³ Lab-grid persistent recipe lookup)
# 耗材求解器缓存（64³ Lab 网格持久化配方查询）
# ---------------------------------------------------------------------------


def _parse_material_directory_names(raw: str) -> list[str]:
    """Parse the ``material_directory_names`` JSON-encoded form field.
    解析 JSON 编码的 ``material_directory_names`` 表单字段。
    """
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid material_directory_names JSON: {exc}",
        )
    if not isinstance(parsed, list) or not all(
        isinstance(name, str) and name.strip() for name in parsed
    ):
        raise HTTPException(
            status_code=422,
            detail="material_directory_names must be a JSON array of non-empty strings",
        )
    cleaned = [name.strip() for name in parsed]
    if not cleaned:
        raise HTTPException(
            status_code=422,
            detail="material_directory_names must contain at least one entry",
        )
    return cleaned


def _validate_cache_parameters(
    layer_count: int, layer_height_mm: float, substrate: str
) -> None:
    if layer_count < _SOLVER_MIN_LAYER_COUNT or layer_count > _SOLVER_MAX_LAYER_COUNT:
        raise HTTPException(
            status_code=422,
            detail=(
                f"layer_count must be in [{_SOLVER_MIN_LAYER_COUNT}, "
                f"{_SOLVER_MAX_LAYER_COUNT}], got {layer_count}"
            ),
        )
    if layer_height_mm not in _CACHE_ALLOWED_LAYER_HEIGHTS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"layer_height_mm must be one of {list(_CACHE_ALLOWED_LAYER_HEIGHTS)}, "
                f"got {layer_height_mm}"
            ),
        )
    if substrate not in ("white", "black"):
        raise HTTPException(
            status_code=422,
            detail=f"substrate must be 'white' or 'black', got {substrate!r}",
        )


def _validate_grid_resolution(grid_resolution: int) -> None:
    """Reject grid resolutions outside the user-facing whitelist.
    拒绝白名单之外的网格分辨率。

    The whitelist is enforced at the API boundary so every shipped value
    has matching UI/docs/build-size expectations. ``core`` keeps looser
    constraints (positive integer) so tests and internal callers can
    still exercise arbitrary resolutions.
    """
    if int(grid_resolution) not in ALLOWED_GRID_RESOLUTIONS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"grid_resolution must be one of {list(ALLOWED_GRID_RESOLUTIONS)}, "
                f"got {grid_resolution}"
            ),
        )


def _load_palette_or_raise(directory_names: list[str]):
    """Load MaterialParams for the given directory names with API-friendly errors."""
    try:
        return load_multiple_materials(directory_names)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))


def _resolve_substrate_linear(materials, substrate: str) -> np.ndarray:
    """Resolve the substrate color in linear RGB for the forward model.
    解析正向模型所需的基底线性 RGB。

    The white substrate is fully modelled (every material archive carries
    ``C0_white``). For black we fall back to a near-zero linear color because
    Stage A archives currently only persist the white substrate parameter.
    The fallback is conservative — any change here must keep
    ``forward_model`` numerically stable for subsequent Beer-Lambert layers.

    白基底由 ``C0_white`` 直接给出；黑基底退化为近似零线性色（当前 Stage A
    存档只持久化白基底参数）。
    """
    if substrate == "white" and materials:
        return np.asarray(materials[0].C0_white, dtype=np.float64).reshape(3)
    if substrate == "black":
        return np.full(3, 0.01, dtype=np.float64)
    return np.ones(3, dtype=np.float64)


@router.post("/material-recipe-preview")
async def material_recipe_preview(
    payload: MaterialRecipePreviewRequest,
) -> MaterialRecipePreviewResponse:
    """Forward-simulate a stacked-material recipe to predict its visible color.
    根据选定耗材按顺序叠层，使用 Beer-Lambert 正向模型预测可见颜色。

    Layer count is intentionally unconstrained beyond the schema's
    ``max_length`` so users can preview any depth (the 5-layer limits in
    :data:`MIN_LAYER_COUNT` / :data:`MAX_LAYER_COUNT` only apply to the
    inverse solver, not this forward query).

    层数仅受 schema 上限限制；求解器的 5 层下限不约束本接口。
    """
    materials = _load_palette_or_raise(payload.directory_names)
    substrate_linear = _resolve_substrate_linear(materials, payload.substrate)

    recipe = np.arange(len(materials), dtype=np.int32)
    predicted_linear = forward_model(
        recipe=recipe,
        materials=materials,
        layer_height_mm=float(payload.layer_height_mm),
        substrate_linear=substrate_linear,
    )
    predicted_srgb = linear_to_srgb_uint8(predicted_linear.reshape(1, 3))[0]
    predicted_rgb = [int(c) for c in predicted_srgb.tolist()]
    predicted_hex = "#{:02X}{:02X}{:02X}".format(*predicted_rgb)

    layers: list[MaterialRecipeLayerResponse] = []
    for idx, mat in enumerate(materials):
        rgb = [int(c) for c in np.asarray(mat.estimated_rgb).reshape(3).tolist()]
        layers.append(
            MaterialRecipeLayerResponse(
                layer_index=idx,
                directory_name=mat.directory_name,
                material_name=mat.name,
                estimated_rgb=rgb,
                estimated_hex="#{:02X}{:02X}{:02X}".format(*rgb),
            )
        )

    log.info(
        "Material recipe preview computed",
        extra={
            "event": "extractor_material_recipe_preview_done",
            "layer_count": len(materials),
            "layer_height_mm": float(payload.layer_height_mm),
            "substrate": payload.substrate,
            "predicted_hex": predicted_hex,
        },
    )

    return MaterialRecipePreviewResponse(
        status="ok",
        layer_count=len(materials),
        layer_height_mm=float(payload.layer_height_mm),
        substrate=payload.substrate,
        predicted_rgb=predicted_rgb,
        predicted_hex=predicted_hex,
        layers=layers,
    )


@router.post("/generate-material-swatch")
async def generate_material_swatch(
    payload: MaterialRecipeSwatchRequest,
    registry: FileRegistry = Depends(get_file_registry),
) -> MaterialRecipeSwatchResponse:
    """Generate a 3MF swatch file from collected material-archive recipes.
    根据收集的耗材档案配方列表生成 3MF 色块验证文件。
    """
    from api.file_bridge import pil_to_png_bytes
    from api.structured_logging import get_request_id
    from core.material_recipe_swatch import (
        MaterialRecipeSwatchItem,
        generate_material_recipe_swatch,
    )

    items: list[MaterialRecipeSwatchItem] = []
    for recipe_req in payload.recipes:
        materials = _load_palette_or_raise(recipe_req.directory_names)
        mat_names = [m.name for m in materials]
        mat_hexes = [
            "#{:02X}{:02X}{:02X}".format(
                *[int(c) for c in np.asarray(m.estimated_rgb).reshape(3).tolist()]
            )
            for m in materials
        ]
        items.append(
            MaterialRecipeSwatchItem(
                directory_names=recipe_req.directory_names,
                material_names=mat_names,
                material_hexes=mat_hexes,
                result_hex=recipe_req.result_hex,
                layer_height_mm=float(recipe_req.layer_height_mm),
                substrate=recipe_req.substrate,
            )
        )

    output_path, legend_img, status_msg = generate_material_recipe_swatch(
        recipes=items,
        block_size_mm=payload.block_size_mm,
        gap_mm=payload.gap_mm,
        cols=payload.cols,
        structure_mode=payload.structure_mode,
        printer_id=payload.printer_id,
        slicer=payload.slicer,
        nozzle_size=payload.nozzle_size,
    )

    if not output_path:
        raise HTTPException(status_code=500, detail=status_msg or "Material swatch generation failed")

    request_id = get_request_id()
    unique_suffix = uuid.uuid4().hex
    sid = (
        f"material-recipe-swatch:{request_id}:{unique_suffix}"
        if request_id
        else f"material-recipe-swatch:{unique_suffix}"
    )
    download_id = registry.register_path(
        sid,
        output_path,
        ttl_seconds=MATERIAL_SWATCH_EXPORT_TTL_SECONDS,
    )

    preview_url: str | None = None
    if legend_img is not None:
        preview_bytes = pil_to_png_bytes(legend_img)
        preview_id = registry.register_bytes(
            sid,
            preview_bytes,
            "material_swatch_legend.png",
            ttl_seconds=MATERIAL_SWATCH_EXPORT_TTL_SECONDS,
        )
        preview_url = f"/api/files/{preview_id}"

    log.info(
        "Material recipe swatch generated",
        extra={
            "event": "extractor_material_swatch_done",
            "recipe_count": len(items),
            "download_id": download_id,
            "block_size_mm": payload.block_size_mm,
            "gap_mm": payload.gap_mm,
            "cols": payload.cols,
        },
    )

    return MaterialRecipeSwatchResponse(
        status="ok",
        message=status_msg,
        download_url=f"/api/files/{download_id}",
        preview_url=preview_url,
        recipe_count=len(items),
    )


def _cache_entry_from_metadata(
    metadata: dict,
    *,
    cache_file_size_bytes: int,
    cache_file_path: str | None,
) -> MaterialSolverCacheEntryResponse:
    canonical_materials = metadata.get("canonical_materials") or []
    material_dir_names = [
        str(entry.get("directory_name"))
        for entry in canonical_materials
        if isinstance(entry, dict) and entry.get("directory_name")
    ]
    return MaterialSolverCacheEntryResponse(
        palette_hash=str(metadata.get("palette_hash", "")),
        material_directory_names=material_dir_names,
        layer_count=int(metadata.get("layer_count", 0)),
        layer_height_mm=float(metadata.get("layer_height_mm", 0.0)),
        substrate=str(metadata.get("substrate", "white")),
        grid_resolution=int(metadata.get("grid_resolution", DEFAULT_GRID_RESOLUTION)),
        total_combinations=int(metadata.get("total_combinations", 0)),
        valid_cell_count=int(metadata.get("valid_cell_count", 0)),
        total_cell_count=int(metadata.get("total_cell_count", 0)),
        mean_delta_e=float(metadata.get("mean_delta_e", 0.0)),
        max_delta_e=float(metadata.get("max_delta_e", 0.0)),
        build_time_seconds=float(metadata.get("build_time_seconds", 0.0)),
        built_at=metadata.get("built_at"),
        cache_file_size_bytes=int(cache_file_size_bytes),
        cache_file_path=cache_file_path,
    )


@router.get("/material-solver-caches")
async def material_solver_cache_list() -> MaterialSolverCacheListResponse:
    """List every persisted solver-cache entry with its metadata.
    列出所有已持久化的求解器缓存条目及其元数据。
    """
    try:
        raw_entries = list_cached_entries()
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    entries = [
        _cache_entry_from_metadata(
            entry,
            cache_file_size_bytes=int(entry.get("cache_file_size_bytes", 0)),
            cache_file_path=entry.get("cache_file_path"),
        )
        for entry in raw_entries
    ]
    return MaterialSolverCacheListResponse(
        status="ok",
        message=f"Loaded {len(entries)} cache entries",
        entries=entries,
    )


@router.post("/material-solver-cache/status")
async def material_solver_cache_status(
    material_directory_names: str = Form(...),
    layer_count: int = Form(...),
    layer_height_mm: float = Form(...),
    substrate: str = Form("white"),
    grid_resolution: int = Form(DEFAULT_GRID_RESOLUTION),
) -> MaterialSolverCacheStatusResponse:
    """Check whether a cache exists for the given palette & parameters.
    查询指定调色板与参数组合的缓存是否存在。
    """
    dir_names = _parse_material_directory_names(material_directory_names)
    _validate_cache_parameters(layer_count, layer_height_mm, substrate)
    _validate_grid_resolution(grid_resolution)
    materials = _load_palette_or_raise(dir_names)
    palette_hash = fingerprint_palette(materials)
    npz_path = cache_file_path(
        materials, layer_count, layer_height_mm, substrate,
        grid_resolution=grid_resolution,
    )
    cache = load_material_solver_cache(
        materials, layer_count, layer_height_mm, substrate,
        grid_resolution=grid_resolution,
    )
    cached_flag = cache is not None
    log.info(
        "Material solver cache status checked",
        extra={
            "event": "material_solver_cache_status_done",
            "cached": cached_flag,
            "palette_hash": palette_hash,
            "material_count": len(dir_names),
            "layer_count": layer_count,
            "layer_height_mm": layer_height_mm,
            "substrate": substrate,
            "grid_resolution": grid_resolution,
        },
    )
    if cache is None:
        return MaterialSolverCacheStatusResponse(
            status="ok",
            message="No cache found for this combination",
            cached=False,
            palette_hash=palette_hash,
            layer_count=layer_count,
            layer_height_mm=layer_height_mm,
            substrate=substrate,
            entry=None,
        )
    try:
        file_size = npz_path.stat().st_size
    except OSError:
        file_size = 0
    entry = _cache_entry_from_metadata(
        cache.metadata,
        cache_file_size_bytes=file_size,
        cache_file_path=str(npz_path),
    )
    return MaterialSolverCacheStatusResponse(
        status="ok",
        message="Cache found",
        cached=True,
        palette_hash=palette_hash,
        layer_count=layer_count,
        layer_height_mm=layer_height_mm,
        substrate=substrate,
        entry=entry,
    )


@router.post("/material-solver-cache/build")
async def material_solver_cache_build(
    material_directory_names: str = Form(...),
    layer_count: int = Form(...),
    layer_height_mm: float = Form(...),
    substrate: str = Form("white"),
    grid_resolution: int = Form(DEFAULT_GRID_RESOLUTION),
) -> MaterialSolverCacheBuildResponse:
    """Build and persist a solver cache synchronously.
    同步构建并持久化求解器缓存。

    Build time is roughly ``M**N`` combinations times a few tens of FLOPs per
    combo. For 10 materials × 10 layers this can take 30-180 seconds; callers
    should treat the request as long-running and surface a progress indicator.
    The build itself is executed on a worker thread to keep the event loop free.
    """
    dir_names = _parse_material_directory_names(material_directory_names)
    _validate_cache_parameters(layer_count, layer_height_mm, substrate)
    _validate_grid_resolution(grid_resolution)
    materials = _load_palette_or_raise(dir_names)

    def _run_build():
        return build_material_solver_cache(
            materials,
            layer_count,
            layer_height_mm,
            substrate,
            grid_resolution=grid_resolution,
        )

    try:
        cache = await anyio.to_thread.run_sync(_run_build)
    except (ValueError, TypeError, OSError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    try:
        npz_path = await anyio.to_thread.run_sync(save_material_solver_cache, cache)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to save cache: {exc}")

    try:
        file_size = npz_path.stat().st_size
    except OSError:
        file_size = 0
    entry = _cache_entry_from_metadata(
        cache.metadata,
        cache_file_size_bytes=file_size,
        cache_file_path=str(npz_path),
    )
    log.info(
        "Material solver cache built",
        extra={
            "event": "material_solver_cache_build_done",
            "material_count": len(dir_names),
            "layer_count": layer_count,
            "layer_height_mm": layer_height_mm,
            "substrate": substrate,
            "grid_resolution": grid_resolution,
            "valid_cell_count": entry.valid_cell_count,
            "total_cell_count": entry.total_cell_count,
            "mean_delta_e": entry.mean_delta_e,
            "cache_file_size_bytes": file_size,
        },
    )
    return MaterialSolverCacheBuildResponse(
        status="ok",
        message=(
            f"Built material solver cache for {len(dir_names)} materials, "
            f"N={layer_count}, t={layer_height_mm} mm, substrate={substrate} "
            f"({entry.valid_cell_count}/{entry.total_cell_count} cells, "
            f"mean ΔE={entry.mean_delta_e:.2f})"
        ),
        entry=entry,
    )


@router.post("/material-solver-cache/delete")
async def material_solver_cache_delete(
    material_directory_names: str = Form(...),
    layer_count: int = Form(...),
    layer_height_mm: float = Form(...),
    substrate: str = Form("white"),
    grid_resolution: int = Form(DEFAULT_GRID_RESOLUTION),
) -> MaterialSolverCacheDeleteResponse:
    """Delete a persisted solver cache entry.
    删除已持久化的求解器缓存条目。
    """
    dir_names = _parse_material_directory_names(material_directory_names)
    _validate_cache_parameters(layer_count, layer_height_mm, substrate)
    _validate_grid_resolution(grid_resolution)
    materials = _load_palette_or_raise(dir_names)
    palette_hash = fingerprint_palette(materials)
    deleted = delete_cached_entry(
        materials, layer_count, layer_height_mm, substrate,
        grid_resolution=grid_resolution,
    )
    log.info(
        "Material solver cache delete checked",
        extra={
            "event": "material_solver_cache_delete_done",
            "deleted": bool(deleted),
            "palette_hash": palette_hash,
            "material_count": len(dir_names),
            "layer_count": layer_count,
            "layer_height_mm": layer_height_mm,
            "substrate": substrate,
            "grid_resolution": grid_resolution,
        },
    )
    return MaterialSolverCacheDeleteResponse(
        status="ok",
        message=(
            "Cache deleted" if deleted else "No cache entry found for the given parameters"
        ),
        deleted=bool(deleted),
        palette_hash=palette_hash,
        layer_count=layer_count,
        layer_height_mm=layer_height_mm,
        substrate=substrate,
    )


# ---------------------------------------------------------------------------
# Material color suggestions (picker support for material-archive mode)
# 耗材颜色建议（材料档案模式取色器支持）
# ---------------------------------------------------------------------------


def _parse_target_hex(raw: str) -> tuple[str, tuple[int, int, int]]:
    """Normalise a user-supplied hex color to ``(hex_noprefix, (r,g,b))``.
    将用户输入的 hex 颜色规范化为 ``(去前缀 hex, (r,g,b))``。

    Accepts ``#RRGGBB`` / ``RRGGBB`` (case-insensitive) and the 3-digit short
    form ``#RGB``. Rejects malformed inputs with HTTP 422 so the frontend can
    surface a validation error without leaking tracebacks.
    """
    if not isinstance(raw, str):
        raise HTTPException(status_code=422, detail="target_hex must be a string")
    cleaned = raw.strip().lstrip("#").lower()
    if len(cleaned) == 3:
        cleaned = "".join(ch * 2 for ch in cleaned)
    if len(cleaned) != 6 or any(c not in "0123456789abcdef" for c in cleaned):
        raise HTTPException(
            status_code=422,
            detail=f"target_hex must be #RRGGBB or #RGB, got {raw!r}",
        )
    r = int(cleaned[0:2], 16)
    g = int(cleaned[2:4], 16)
    b = int(cleaned[4:6], 16)
    return cleaned, (r, g, b)


def _validate_suggest_parameters(
    top_k: int, min_spacing: float, max_combinations: int
) -> None:
    if top_k <= 0 or top_k > 100:
        raise HTTPException(
            status_code=422,
            detail=f"top_k must be in [1, 100], got {top_k}",
        )
    if min_spacing < 0.0 or min_spacing > 50.0:
        raise HTTPException(
            status_code=422,
            detail=f"min_spacing must be in [0, 50], got {min_spacing}",
        )
    if max_combinations <= 0 or max_combinations > 50_000_000:
        raise HTTPException(
            status_code=422,
            detail=(
                "max_combinations must be in (0, 50_000_000], "
                f"got {max_combinations}"
            ),
        )


def _suggestions_to_response_items(
    suggestions: list[ColorSuggestion],
) -> list[MaterialColorSuggestionItem]:
    items: list[MaterialColorSuggestionItem] = []
    for suggestion in suggestions:
        rgb = [int(v) for v in suggestion.matched_rgb.tolist()]
        recipe = [int(v) for v in suggestion.recipe.tolist()]
        items.append(
            MaterialColorSuggestionItem(
                hex="#{:02X}{:02X}{:02X}".format(*rgb),
                rgb=rgb,
                delta_e=float(suggestion.delta_e),
                recipe=recipe,
                recipe_display="[" + ",".join(str(v) for v in recipe) + "]",
            )
        )
    return items


@router.post("/material-solver-cache/suggest-colors")
async def material_solver_cache_suggest_colors(
    material_directory_names: str = Form(...),
    layer_count: int = Form(...),
    layer_height_mm: float = Form(...),
    substrate: str = Form("white"),
    target_hex: str = Form(...),
    top_k: int = Form(DEFAULT_SUGGEST_TOP_K),
    min_spacing: float = Form(DEFAULT_SUGGEST_MIN_SPACING),
    max_combinations: int = Form(DEFAULT_SUGGEST_MAX_COMBINATIONS),
    grid_resolution: int = Form(DEFAULT_GRID_RESOLUTION),
) -> MaterialColorSuggestionsResponse:
    """Return up to ``top_k`` achievable colors near ``target_hex``.
    为 ``target_hex`` 返回至多 ``top_k`` 个可达近似色建议。

    Fast path: when a persisted :class:`core.material_cache.MaterialSolverCache`
    matches the ``(palette, N, t, substrate)`` parameters the response is
    served from the KDTree-over-Lab-buckets lookup (microseconds per query).
    Fallback: no cache available → runs
    :func:`core.material_color_solver.suggest_colors_for_target` in a worker
    thread, bounded by ``max_combinations`` to keep interactive UX responsive.

    The frontend reports ``source`` in the response so it can surface a
    "build cache for instant suggestions" hint when the MITM fallback runs.
    前端会根据 ``source`` 判断是否提示用户构建缓存以获得毫秒级响应。
    """
    dir_names = _parse_material_directory_names(material_directory_names)
    _validate_cache_parameters(layer_count, layer_height_mm, substrate)
    _validate_grid_resolution(grid_resolution)
    _validate_suggest_parameters(top_k, min_spacing, max_combinations)
    target_hex_clean, target_rgb_tuple = _parse_target_hex(target_hex)
    materials = _load_palette_or_raise(dir_names)
    palette_hash = fingerprint_palette(materials)

    target_rgb_arr = np.asarray(target_rgb_tuple, dtype=np.uint8)

    cache = load_material_solver_cache(
        materials, layer_count, layer_height_mm, substrate,
        grid_resolution=grid_resolution,
    )
    if cache is not None:
        try:
            suggestions = cache.lookup_top_k(
                target_rgb_arr,
                materials,
                top_k=top_k,
                min_spacing=min_spacing,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        source = "cache"
        message = (
            f"Returned {len(suggestions)} achievable colors "
            f"(via solver cache, {cache.valid_cell_count} cells)."
        )
    else:
        def _run_suggest() -> list[ColorSuggestion]:
            return suggest_colors_for_target(
                target_rgb_arr,
                materials,
                layer_count=layer_count,
                layer_height_mm=layer_height_mm,
                substrate=substrate,
                top_k=top_k,
                min_spacing=min_spacing,
                max_combinations=max_combinations,
            )

        try:
            suggestions = await anyio.to_thread.run_sync(_run_suggest)
        except OverflowError as exc:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"{exc}. Please build the material solver cache first to "
                    "enable interactive suggestions for this palette."
                ),
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        source = "mitm"
        message = (
            f"Returned {len(suggestions)} achievable colors "
            f"(via MITM fallback)."
        )

    log.info(
        "Material solver cache color suggestions returned",
        extra={
            "event": "material_solver_cache_suggest_colors_done",
            "source": source,
            "palette_hash": palette_hash,
            "material_count": len(dir_names),
            "target_hex": f"#{target_hex_clean.upper()}",
            "suggestions_count": len(suggestions),
            "top_k": top_k,
        },
    )
    return MaterialColorSuggestionsResponse(
        status="ok",
        message=message,
        source=source,
        palette_hash=palette_hash,
        layer_count=layer_count,
        layer_height_mm=layer_height_mm,
        substrate=substrate,
        target_hex=f"#{target_hex_clean.upper()}",
        target_rgb=[int(v) for v in target_rgb_tuple],
        suggestions=_suggestions_to_response_items(suggestions),
    )
