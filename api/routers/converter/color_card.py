"""Converter router — colour-card 3MF generation.
转换器路由 — 验证色卡 3MF 生成。

Generates a printable colour swatch card from the current session's
palette so the user can physically verify matched colours on their
printer before committing to a full model print.
从当前预览 session 的调色板生成一张可打印的色卡 3MF，用户可以先打印
色卡验证颜色是否准确，再打印完整模型。
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
import os
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.dependencies import get_file_registry, get_session_store, get_worker_pool
from api.export_device_validation import validate_export_device_selection
from api.file_registry import FileRegistry
from api.preview_cache_artifacts import (
    get_preview_cache_metadata,
    is_preview_cache_artifact_ref,
)
from api.schemas.responses import GenerateResponse
from api.session_store import SessionStore
from api.structured_logging import get_logger
from api.worker_pool import WorkerPoolManager
from api.workers.converter_workers import worker_generate_model
from config import (
    DEFAULT_PRINTER_ID,
    DEFAULT_SLICER_ID,
    TEMP_DIR,
    ModelingMode as CoreModelingMode,
)
from core.errors import VectorHostMemoryAdmissionError, VectorMeshMemoryBudgetError
from core.vector_mesh_memory import (
    estimate_vector_task_memory_reservation_bytes,
    resolve_vector_mesh_memory_budget_bytes,
)

from .common import (
    BATCH_DOWNLOAD_TTL_SECONDS,
    LUT_DATA_UNAVAILABLE_DETAIL,
    PREVIEW_CACHE_INVALID_DETAIL,
    PREVIEW_CACHE_UNAVAILABLE_DETAIL,
    PREVIEW_COLOR_PALETTE_UNAVAILABLE_DETAIL,
    ROUTER_HANDLED_ERRORS,
    _handle_core_error,
    _resolve_material_backing_index,
    _resolve_session_dynamic_material_settings,
    _require_session,
)

router = APIRouter()
log = get_logger(__name__)
_COLOR_CARD_GENERATION_FAILED_DETAIL = (
    "Color card 3MF generation failed. Re-run preview and try "
    "generating the color card again."
)


def _remove_temp_path(path: str | None) -> None:
    """Best-effort delete for route-owned temporary files."""
    if not path:
        return
    try:
        os.unlink(path)
    except OSError:
        pass


def _require_color_card_cache_metadata(session_data: dict) -> dict:
    """Return preview-cache metadata needed for color-card generation.

    返回色卡生成所需的 preview-cache 元数据。
    """
    cache = session_data.get("preview_cache")
    if cache is None:
        raise HTTPException(
            status_code=409,
            detail=PREVIEW_CACHE_UNAVAILABLE_DETAIL,
        )
    if not isinstance(cache, dict):
        raise HTTPException(
            status_code=409,
            detail=PREVIEW_CACHE_INVALID_DETAIL,
        )
    if is_preview_cache_artifact_ref(cache):
        return get_preview_cache_metadata(cache)
    return cache


class ColorCardRequest(BaseModel):
    """Request body for ``POST /api/convert/color-card``."""

    session_id: str
    target_width_mm: float = Field(
        default=100.0,
        description="Physical width (mm) of the colour card. 色卡物理宽度（毫米）。",
    )
    spacer_thick: float = Field(
        default=0.48,
        description="Backing thickness (mm). 底板厚度（毫米）。",
    )
    show_labels: bool = Field(
        default=True,
        description="Render hex labels below each swatch. 在色块下方显示十六进制色值。",
    )
    printer_id: str = Field(DEFAULT_PRINTER_ID, description="Printer profile ID.")
    slicer: str = Field(DEFAULT_SLICER_ID, description="Slicer software ID.")
    nozzle_size: str = Field("0.4", description="Nozzle size.")
    device_profile_id: str | None = Field(
        None,
        description="Machine registry device profile ID.",
    )
    build_plate_id: str | None = Field(
        None,
        description="Slicer-native build plate ID.",
    )
    enable_wipe_tower_auto_placement: bool = Field(
        True,
        description=(
            "Automatically place the wipe tower for the generated 3MF. "
            "自动为生成的 3MF 摆放擦料塔。"
        ),
    )


@router.post("/color-card", response_model=GenerateResponse)
async def generate_color_card(
    body: ColorCardRequest,
    store: SessionStore = Depends(get_session_store),
    registry: FileRegistry = Depends(get_file_registry),
    pool: WorkerPoolManager = Depends(get_worker_pool),
) -> GenerateResponse:
    """Generate a printable colour-card 3MF from the session palette.
    从 session 调色板生成可打印的验证色卡 3MF。

    1. Read ``color_palette`` from preview cache.
    2. Generate colour-card SVG via ``core.color_card``.
    3. Run the SVG through the vector pipeline to produce a 3MF.
    4. Register and return the download URL.
    """
    api_t0 = time.perf_counter()

    validate_export_device_selection(
        printer_id=body.printer_id,
        slicer=body.slicer,
        nozzle_size=body.nozzle_size,
        device_profile_id=body.device_profile_id,
        build_plate_id=body.build_plate_id,
    )

    # 1. Session + cache validation
    session_data = _require_session(store, body.session_id)
    cache = _require_color_card_cache_metadata(session_data)

    lut_path: str | None = session_data.get("lut_path")
    session_material_source = session_data.get("material_source", "lut")
    if session_material_source != "material_archive":
        if not lut_path or not os.path.exists(lut_path):
            raise HTTPException(
                status_code=409,
                detail=LUT_DATA_UNAVAILABLE_DETAIL,
            )
    else:
        lut_path = "__material_archive__"

    dynamic_material_settings = _resolve_session_dynamic_material_settings(
        session_data=session_data,
        request=body,
        material_source=str(session_material_source or "lut"),
        native_svg_vector=False,
    )
    if dynamic_material_settings[0]:
        raise HTTPException(
            status_code=422,
            detail=(
                "Dynamic material layer count does not support generated "
                "color-card SVGs. Use a native uploaded SVG instead."
            ),
        )

    # 2. Extract unique colours from preview cache
    color_palette = cache.get("color_palette")
    if not color_palette:
        raise HTTPException(
            status_code=409,
            detail=PREVIEW_COLOR_PALETTE_UNAVAILABLE_DETAIL,
        )

    hex_colors = [entry["hex"] for entry in color_palette if "hex" in entry]
    if not hex_colors:
        raise HTTPException(
            status_code=409,
            detail="color_palette contains no hex entries.",
        )

    log.info(
        "Color card generation started",
        extra={
            "event": "color_card_init",
            "session_id": body.session_id,
            "color_count": len(hex_colors),
            "target_width_mm": body.target_width_mm,
        },
    )

    # 3. Generate colour-card SVG
    from core.color_card import generate_color_card_svg

    svg_path = generate_color_card_svg(
        hex_colors,
        show_labels=body.show_labels,
        output_dir=TEMP_DIR,
    )
    store.register_temp_file(body.session_id, svg_path)

    # 4. Build worker params — minimal vector generation
    color_mode = cache.get("color_mode", "4-Color CMYW")
    params: dict = {
        "target_width_mm": body.target_width_mm,
        "spacer_thick": body.spacer_thick,
        "structure_mode": "Single-sided",
        "color_mode": color_mode,
        "color_layers": cache.get("color_conf", {}).get(
            "layer_count", None
        ),
        "layer_height_mm": None,
        "model_enable": False,
        "model_only": False,
        "model_threshold": None,
        "model_margin": None,
        "add_loop": False,
        "loop_width": 0,
        "loop_length": 0,
        "loop_hole": 0,
        "loop_pos": None,
        "enable_fridge_magnet": False,
        "fridge_magnets": [],
        "loop_angle": 0,
        "loop_offset_x": 0,
        "loop_offset_y": 0,
        "loop_position_preset": None,
        "modeling_mode": CoreModelingMode.VECTOR,
        "quantize_colors": len(hex_colors),
        "replacement_regions": None,
        "recipe_overrides": None,
        "recipe_override_masks_path": None,
        "separate_backing": False,
        "enable_relief": False,
        "height_mode": "color",
        "heightmap_path": None,
        "color_height_map": None,
        "heightmap_max_height": None,
        "enable_cleanup": False,
        "enable_outline": False,
        "outline_width": None,
        "enable_cloisonne": False,
        "wire_width_mm": None,
        "wire_height_mm": None,
        "free_color_set": None,
        "enable_coating": False,
        "coating_height_mm": 0.08,
        "hue_weight": 0.0,
        "chroma_gate": 0,
        "use_lut_constrained": False,
        "auto_dynamic_range": False,
        "matched_rgb_path": None,
        "mask_solid_path": None,
        "material_matrix_path": None,
        "printer_id": body.printer_id,
        "slicer": body.slicer,
        "nozzle_size": body.nozzle_size,
        "device_profile_id": body.device_profile_id,
        "build_plate_id": body.build_plate_id,
        "enable_base_layer_height_modifier": False,
        "enable_wipe_tower_auto_placement": (
            body.enable_wipe_tower_auto_placement
        ),
        "material_source": session_material_source,
    }
    if session_material_source == "material_archive":
        selected_materials = session_data.get("selected_materials") or []
        params["selected_materials"] = selected_materials
        params["material_layer_count"] = session_data.get("material_layer_count")
        params["material_layer_height_mm"] = session_data.get("material_layer_height_mm")
        params["material_grid_resolution"] = session_data.get("material_grid_resolution")
        params["material_backing_material_index"] = _resolve_material_backing_index(
            selected_materials,
            session_data.get("material_backing_material_index"),
        )

    # 5. Submit to worker pool
    worker_t0 = time.perf_counter()
    try:
        result = await pool.submit(
            worker_generate_model,
            svg_path,
            lut_path,
            params,
            host_memory_reservation_bytes=(
                # The material solver's implicit runtimes have no complete
                # parent-visible path list to estimate safely.
                resolve_vector_mesh_memory_budget_bytes()
                if session_material_source == "material_archive"
                else estimate_vector_task_memory_reservation_bytes(
                    svg_path,
                    resident_paths=(lut_path,),
                )
            ),
        )
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504,
            detail="Color card 3MF generation timed out.",
        )
    except (VectorHostMemoryAdmissionError, VectorMeshMemoryBudgetError) as exc:
        _handle_core_error(exc, "color-card generation")
    except ROUTER_HANDLED_ERRORS:
        raise HTTPException(
            status_code=500,
            detail=_COLOR_CARD_GENERATION_FAILED_DETAIL,
        )
    worker_elapsed = time.perf_counter() - worker_t0

    # 6. Register result files
    threemf_path: str | None = result.get("threemf_path")
    glb_path: str | None = result.get("glb_path")
    status_msg: str = result.get("status_msg", "")

    if not threemf_path or not os.path.exists(threemf_path):
        raise HTTPException(
            status_code=500,
            detail=_COLOR_CARD_GENERATION_FAILED_DETAIL,
        )

    preview_3d_url: str | None = None
    download_id: str | None = None
    registration_complete = False
    glb_registered = False
    try:
        try:
            download_id = registry.register_path(
                str(uuid.uuid4()),
                threemf_path,
                ttl_seconds=BATCH_DOWNLOAD_TTL_SECONDS,
            )
        except ROUTER_HANDLED_ERRORS as exc:
            log.exception(
                "Color card 3MF download registration failed",
                extra={
                    "event": "color_card_download_registration_failed",
                    "session_id": body.session_id,
                    "artifact_role": "threemf_download",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "path": threemf_path,
                },
            )
            raise HTTPException(
                status_code=500,
                detail=_COLOR_CARD_GENERATION_FAILED_DETAIL,
            ) from exc

        if glb_path and os.path.exists(glb_path):
            try:
                glb_id = registry.register_path(body.session_id, glb_path)
            except Exception as exc:
                log.warning(
                    "Color card GLB preview registration failed",
                    extra={
                        "event": "color_card_glb_registration_failed",
                        "session_id": body.session_id,
                        "error_type": type(exc).__name__,
                        "error_message": str(exc),
                        "path": glb_path,
                    },
                )
            else:
                glb_registered = True
                preview_3d_url = f"/api/files/{glb_id}"
        registration_complete = True
    finally:
        if download_id is None:
            _remove_temp_path(threemf_path)
        elif not registration_complete:
            with suppress(Exception):
                registry.cleanup_file(download_id)
        if glb_path and not glb_registered:
            _remove_temp_path(glb_path)

    api_total = time.perf_counter() - api_t0
    log.info(
        "Color card generation complete",
        extra={
            "event": "color_card_done",
            "session_id": body.session_id,
            "color_count": len(hex_colors),
            "duration_ms": round(api_total * 1000, 3),
            "worker_ms": round(worker_elapsed * 1000, 3),
        },
    )

    return GenerateResponse(
        status="ok",
        message=status_msg or "Color card generated",
        download_url=f"/api/files/{download_id}",
        preview_3d_url=preview_3d_url,
        threemf_disk_path=None,
    )
