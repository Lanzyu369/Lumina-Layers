"""Single-stage workflow API routes."""

from __future__ import annotations

import json
import os
import uuid
import zipfile

import anyio
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from api.dependencies import get_file_registry, get_session_store
from api.file_bridge import ndarray_to_png_bytes, upload_to_ndarray, upload_to_tempfile
from api.file_registry import FileRegistry
from api.schemas.responses import (
    GradientCardMaterialDeleteResponse,
    GradientCardMaterialLibraryResponse,
    GradientCardMaterialSaveResponse,
    GradientCardStageAExtractResponse,
    MaterialSolverCacheBuildResponse,
    MaterialSolverCacheDeleteResponse,
    MaterialSolverCacheEntryResponse,
    MaterialSolverCacheListResponse,
    MaterialSolverCacheStatusResponse,
    SingleStageExtractResponse,
    StageAFitResponse,
)
from api.session_store import SessionStore
from api.structured_logging import bind_session_id
from core.material_cache import (
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
    MAX_LAYER_COUNT as _SOLVER_MAX_LAYER_COUNT,  # noqa: N811
    MIN_LAYER_COUNT as _SOLVER_MIN_LAYER_COUNT,  # noqa: N811
)
from core.material_lut_synthesis import load_multiple_materials
from core.single_stage import (
    delete_saved_stage_a_material_archive,
    extract_single_stage_dataset,
    extract_stage_a_material_from_gradient_cards,
    fit_stage_a_from_stage_json,
    list_saved_stage_a_material_archives,
    save_stage_a_material_archive,
)

router = APIRouter(prefix="/api/extractor", tags=["Extractor"])
GRADIENT_CARD_PREVIEW_TTL_SECONDS = 600


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
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except (ValueError, TypeError, OSError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    persistent_registry_session = f"material:{uuid.uuid4().hex}"
    material_id = registry.register_path(persistent_registry_session, result.archive_path)
    stage_a_id = registry.register_path(persistent_registry_session, result.stage_a_params_path)
    verification_count = int(result.material_summary.get("verification_count") or 1)
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


@router.delete("/gradient-card-materials/{directory_name}")
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

    return GradientCardMaterialDeleteResponse(
        status="ok",
        message="Gradient card material deleted successfully",
        directory_name=result.directory_name,
        material_name=result.material_name,
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
        material_file_url = f"/api/files/{registry.register_path(persistent_registry_session, str(item['archive_path']))}"
        stage_a_path = item.get("stage_a_params_path")
        stage_a_params_url = (
            f"/api/files/{registry.register_path(persistent_registry_session, str(stage_a_path))}"
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


def _load_palette_or_raise(directory_names: list[str]):
    """Load MaterialParams for the given directory names with API-friendly errors."""
    try:
        return load_multiple_materials(directory_names)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))


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
) -> MaterialSolverCacheStatusResponse:
    """Check whether a cache exists for the given palette & parameters.
    查询指定调色板与参数组合的缓存是否存在。
    """
    dir_names = _parse_material_directory_names(material_directory_names)
    _validate_cache_parameters(layer_count, layer_height_mm, substrate)
    materials = _load_palette_or_raise(dir_names)
    palette_hash = fingerprint_palette(materials)
    npz_path = cache_file_path(
        materials, layer_count, layer_height_mm, substrate
    )
    cache = load_material_solver_cache(
        materials, layer_count, layer_height_mm, substrate
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
    if grid_resolution < 8 or grid_resolution > 256:
        raise HTTPException(
            status_code=422,
            detail=f"grid_resolution must be in [8, 256], got {grid_resolution}",
        )
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
) -> MaterialSolverCacheDeleteResponse:
    """Delete a persisted solver cache entry.
    删除已持久化的求解器缓存条目。
    """
    dir_names = _parse_material_directory_names(material_directory_names)
    _validate_cache_parameters(layer_count, layer_height_mm, substrate)
    materials = _load_palette_or_raise(dir_names)
    palette_hash = fingerprint_palette(materials)
    deleted = delete_cached_entry(
        materials, layer_count, layer_height_mm, substrate
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
