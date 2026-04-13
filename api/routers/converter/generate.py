"""Converter router generate module."""

from __future__ import annotations

import asyncio
import math
import os
import tempfile
import time
import uuid
import zipfile

import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from PIL import Image
from pydantic import BaseModel

from api.dependencies import get_file_registry, get_session_store, get_worker_pool
from api.file_bridge import ensure_png_tempfile
from api.file_registry import FileRegistry
from api.schemas.converter import ConvertGenerateRequest, LargeFormatGenerateRequest
from api.schemas.responses import (
    BatchItemResult,
    BatchResponse,
    GenerateResponse,
    LargeFormatGenerateResponse,
)
from api.session_store import SessionStore
from api.structured_logging import get_logger
from api.worker_pool import WorkerPoolManager
from api.workers.converter_workers import (
    worker_batch_convert_item,
    worker_generate_large_format_svg_native,
    worker_generate_model,
)
from config import TEMP_DIR, ModelingMode as CoreModelingMode
from core.pipeline.processing_ops.svg_rasterizer import rasterize_svg
from core.vector_large_format import (
    SVG_LARGE_FORMAT_DENSITY_REDUCED_WARNING,
    SVG_LARGE_FORMAT_GENERATE_FALLBACK_WARNING,
    choose_svg_raster_fallback_density,
    inspect_svg_large_format_support,
)
from utils.lut_manager import LUTManager

from .common import (
    BATCH_DOWNLOAD_TTL_SECONDS,
    ROUTER_HANDLED_ERRORS,
    _require_preview_cache,
    _require_session,
)

router = APIRouter()
log = get_logger(__name__)


class _GenerateBody(BaseModel):
    """Wrapper combining session_id with generate parameters."""

    session_id: str
    params: ConvertGenerateRequest


def _serialize_fridge_magnets(request: ConvertGenerateRequest) -> list[dict]:
    """Serialize fridge-magnet items into plain JSON-compatible dicts.
    将冰箱贴磁铁槽项序列化为纯 JSON 兼容字典。
    """

    return [item.model_dump(mode="json") for item in request.fridge_magnets]


def _has_requested_fridge_magnet_cavities(request: ConvertGenerateRequest) -> bool:
    """Return whether fridge-magnet cavities are explicitly requested."""

    return bool(request.enable_fridge_magnet)


@router.post("/generate")
async def convert_generate(
    body: _GenerateBody,
    store: SessionStore = Depends(get_session_store),
    registry: FileRegistry = Depends(get_file_registry),
    pool: WorkerPoolManager = Depends(get_worker_pool),
) -> GenerateResponse:
    """Generate a printable 3MF model via process pool.
    通过进程池生成可打印的 3MF 模型。

    Session and FileRegistry operations run on the main thread.
    CPU-intensive model generation is offloaded to the worker pool.
    Session 和 FileRegistry 操作在主线程完成。
    CPU 密集型模型生成卸载到工作进程池。
    """
    api_t0 = time.perf_counter()

    # 1. Session validation (main thread)
    session_data = _require_session(store, body.session_id)
    cache = _require_preview_cache(session_data)

    request = body.params

    # Retrieve paths stored during preview
    image_path: str | None = session_data.get("image_path")
    lut_path: str | None = session_data.get("lut_path")
    if not image_path or not os.path.exists(image_path):
        raise HTTPException(status_code=409, detail="Image file missing. Call POST /api/convert/preview first.")
    if not lut_path or not os.path.exists(lut_path):
        raise HTTPException(status_code=409, detail="LUT file missing. Call POST /api/convert/preview first.")

    # Merge replacement_regions: prefer session state, fall back to request body
    replacement_regions = session_data.get("replacement_regions") or None
    if request.replacement_regions is not None:
        replacement_regions = [
            {
                "quantized_hex": r.quantized_hex,
                "matched_hex": r.matched_hex,
                "replacement_hex": r.replacement_hex,
            }
            for r in request.replacement_regions
        ]

    free_color_set = session_data.get("free_color_set") or None
    if request.free_color_set is not None:
        free_color_set = request.free_color_set

    # Convert API ModelingMode enum to core ModelingMode enum
    core_modeling_mode = CoreModelingMode(request.modeling_mode.value)

    # Resolve height_mode for relief branching
    # 解析 height_mode 用于浮雕分支选择
    height_mode = request.height_mode or "color"

    # If heightmap mode, save session heightmap to temp file for worker process
    # 高度图模式时，将 session 中的高度图保存为临时文件供工作进程使用
    heightmap_path: str | None = None
    if request.enable_relief and height_mode == "heightmap":
        heightmap_grayscale = session_data.get("heightmap_grayscale")
        if heightmap_grayscale is not None:
            fd, hm_temp_path = tempfile.mkstemp(suffix=".png", dir=TEMP_DIR)
            os.close(fd)
            Image.fromarray(heightmap_grayscale).save(hm_temp_path)
            heightmap_path = hm_temp_path
            store.register_temp_file(body.session_id, hm_temp_path)

    # 2a. Serialize cached matched_rgb to temp file if requested
    # 当存在区域替换时，将缓存的 matched_rgb 序列化为临时文件供 Worker 使用
    matched_rgb_path: str | None = None
    log.info(
        "[GENERATE][DEBUG-COMPARE] use_cached_matched_rgb=%s, has_replacement_regions=%s",
        request.use_cached_matched_rgb,
        bool(replacement_regions),
    )
    if request.use_cached_matched_rgb:
        cached_matched_rgb = cache.get("matched_rgb")
        if cached_matched_rgb is not None:
            fd, mr_temp_path = tempfile.mkstemp(suffix=".npy", dir=TEMP_DIR)
            os.close(fd)
            np.save(mr_temp_path, cached_matched_rgb)
            matched_rgb_path = mr_temp_path
            store.register_temp_file(body.session_id, mr_temp_path)
            log.info(
                "[GENERATE][DEBUG-COMPARE] cached matched_rgb saved: shape=%s, dtype=%s",
                cached_matched_rgb.shape,
                cached_matched_rgb.dtype,
            )

    # 2b. Collect scalar parameters into a dict for the worker
    params: dict = {
        "target_width_mm": request.target_width_mm,
        "spacer_thick": request.spacer_thick,
        "structure_mode": request.structure_mode.value,
        "auto_bg": request.auto_bg,
        "bg_tol": request.bg_tol,
        "color_mode": request.color_mode.value,
        "add_loop": request.add_loop,
        "loop_width": request.loop_width,
        "loop_length": request.loop_length,
        "loop_hole": request.loop_hole,
        "loop_pos": request.loop_pos,
        "enable_fridge_magnet": request.enable_fridge_magnet,
        "fridge_magnets": _serialize_fridge_magnets(request),
        "loop_angle": request.loop_angle,
        "loop_offset_x": request.loop_offset_x,
        "loop_offset_y": request.loop_offset_y,
        "loop_position_preset": request.loop_position_preset,
        "modeling_mode": core_modeling_mode,
        "quantize_colors": request.quantize_colors,
        "replacement_regions": replacement_regions,
        "separate_backing": request.separate_backing,
        "enable_relief": request.enable_relief,
        "height_mode": height_mode,
        "heightmap_path": heightmap_path,
        "color_height_map": request.color_height_map,
        "heightmap_max_height": request.heightmap_max_height,
        "enable_cleanup": request.enable_cleanup,
        "enable_outline": request.enable_outline,
        "outline_width": request.outline_width,
        "enable_cloisonne": request.enable_cloisonne,
        "wire_width_mm": request.wire_width_mm,
        "wire_height_mm": request.wire_height_mm,
        "free_color_set": free_color_set,
        "enable_coating": request.enable_coating,
        "coating_height_mm": request.coating_height_mm,
        "hue_weight": request.hue_weight,
        "chroma_gate": request.chroma_gate,
        "matched_rgb_path": matched_rgb_path,
        "printer_id": request.printer_id,
        "slicer": request.slicer,
    }

    # 3. CPU computation offloaded to process pool (only paths and scalars)
    worker_t0 = time.perf_counter()
    try:
        result = await pool.submit(
            worker_generate_model,
            image_path,
            lut_path,
            params,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="3MF generation timed out")
    except ROUTER_HANDLED_ERRORS as e:
        raise HTTPException(status_code=500, detail=f"3MF generation failed: {str(e)}")
    worker_elapsed = time.perf_counter() - worker_t0

    # 4. Result processing (I/O + FileRegistry, main thread)
    threemf_path: str | None = result.get("threemf_path")
    glb_path: str | None = result.get("glb_path")
    status_msg: str = result.get("status_msg", "")

    if not threemf_path or not os.path.exists(threemf_path):
        raise HTTPException(status_code=500, detail=status_msg or "3MF generation failed")

    # Register output files via FileRegistry
    sid = body.session_id
    download_id = registry.register_path(sid, threemf_path)

    preview_3d_url: str | None = None
    if glb_path and os.path.exists(glb_path):
        glb_id = registry.register_path(sid, glb_path)
        preview_3d_url = f"/api/files/{glb_id}"

    api_total = time.perf_counter() - api_t0
    log.info(
        "Generate endpoint timing",
        extra={
            "event": "converter_generate_timing",
            "duration_ms": round(api_total * 1000, 3),
            "worker_ms": round(worker_elapsed * 1000, 3),
            "overhead_ms": round((api_total - worker_elapsed) * 1000, 3),
        },
    )

    return GenerateResponse(
        status="ok",
        message=status_msg or "Model generated",
        download_url=f"/api/files/{download_id}",
        preview_3d_url=preview_3d_url,
        threemf_disk_path=threemf_path,
    )


# ---------------------------------------------------------------------------
# Large-format tiled generation
# ---------------------------------------------------------------------------


class _LargeFormatBody(BaseModel):
    """Wrapper combining session_id with large-format parameters."""

    session_id: str
    params: LargeFormatGenerateRequest


def _resolve_large_format_dimensions(
    cache: dict,
    request,
    target_height_mm: float | None,
) -> tuple[float, float]:
    ratio_w = float(cache.get("target_w") or 0.0)
    ratio_h = float(cache.get("target_h") or 0.0)
    if ratio_w <= 0 or ratio_h <= 0:
        raise HTTPException(status_code=409, detail="Preview cache is missing valid aspect ratio data.")

    aspect_ratio = ratio_w / ratio_h
    requested_width = request.target_width_mm
    requested_height = target_height_mm

    if requested_width is None and requested_height is None:
        raise HTTPException(
            status_code=422,
            detail="Large-format generation requires width or height. Provide at least one dimension.",
        )

    if requested_width is None:
        requested_width = round(float(requested_height) * aspect_ratio, 4)
    elif requested_height is None:
        requested_height = round(float(requested_width) / aspect_ratio, 4)
    else:
        expected_height = float(requested_width) / aspect_ratio
        if abs(float(requested_height) - expected_height) > 1.0:
            raise HTTPException(
                status_code=422,
                detail="Provided width and height do not match the preview aspect ratio.",
            )

    return float(requested_width), float(requested_height)


def _resolve_relief_global_max_height(session_data: dict, request) -> float | None:
    relief_global_max_height: float | None = None
    if request.enable_relief:
        height_mode = request.height_mode or "color"
        if height_mode == "color" and request.color_height_map:
            relief_global_max_height = max(request.color_height_map.values())
        elif height_mode == "heightmap":
            hm_gray = session_data.get("heightmap_grayscale")
            if hm_gray is not None:
                hm_max_cfg = request.heightmap_max_height if request.heightmap_max_height else 5.0
                relief_global_max_height = float(hm_max_cfg)
    return relief_global_max_height


def _resolve_large_format_shared_params(session_data: dict, request, relief_global_max_height: float | None) -> dict:
    replacement_regions = session_data.get("replacement_regions") or None
    if request.replacement_regions is not None:
        replacement_regions = [
            {"quantized_hex": r.quantized_hex, "matched_hex": r.matched_hex, "replacement_hex": r.replacement_hex}
            for r in request.replacement_regions
        ]
    free_color_set = session_data.get("free_color_set") or None
    if request.free_color_set is not None:
        free_color_set = request.free_color_set

    return {
        "spacer_thick": request.spacer_thick,
        "structure_mode": request.structure_mode.value,
        "auto_bg": request.auto_bg,
        "bg_tol": request.bg_tol,
        "color_mode": request.color_mode.value,
        "add_loop": request.add_loop,
        "loop_width": request.loop_width,
        "loop_length": request.loop_length,
        "loop_hole": request.loop_hole,
        "loop_pos": request.loop_pos,
        "enable_fridge_magnet": request.enable_fridge_magnet,
        "fridge_magnets": _serialize_fridge_magnets(request),
        "loop_angle": request.loop_angle,
        "loop_offset_x": request.loop_offset_x,
        "loop_offset_y": request.loop_offset_y,
        "loop_position_preset": request.loop_position_preset,
        "modeling_mode": CoreModelingMode(request.modeling_mode.value),
        "quantize_colors": request.quantize_colors,
        "replacement_regions": replacement_regions,
        "separate_backing": request.separate_backing,
        "enable_relief": request.enable_relief,
        "height_mode": request.height_mode or "color",
        "color_height_map": request.color_height_map,
        "heightmap_max_height": request.heightmap_max_height,
        "enable_cleanup": request.enable_cleanup,
        "enable_outline": request.enable_outline,
        "outline_width": request.outline_width,
        "enable_cloisonne": request.enable_cloisonne,
        "wire_width_mm": request.wire_width_mm,
        "wire_height_mm": request.wire_height_mm,
        "free_color_set": free_color_set,
        "enable_coating": request.enable_coating,
        "coating_height_mm": request.coating_height_mm,
        "hue_weight": request.hue_weight,
        "chroma_gate": request.chroma_gate,
        "printer_id": request.printer_id,
        "slicer": request.slicer,
        "relief_global_max_height": relief_global_max_height,
    }


async def _generate_large_format_svg_native(
    *,
    image_path: str,
    lut_path: str,
    total_width_mm: float,
    total_height_mm: float,
    tile_width_mm: float,
    tile_height_mm: float,
    request,
    session_data: dict,
    sid: str,
    store: SessionStore,
    registry: FileRegistry,
    pool: WorkerPoolManager,
    warnings: list[str] | None = None,
) -> dict:
    shared_params = _resolve_large_format_shared_params(
        session_data,
        request,
        _resolve_relief_global_max_height(session_data, request),
    )
    result = await pool.submit(
        worker_generate_large_format_svg_native,
        image_path,
        lut_path,
        {
            **shared_params,
            "total_width_mm": total_width_mm,
            "total_height_mm": total_height_mm,
            "tile_width_mm": tile_width_mm,
            "tile_height_mm": tile_height_mm,
        },
    )
    zip_path = result["zip_path"]
    store.register_temp_file(sid, zip_path)
    download_id = registry.register_path(sid, zip_path)
    return {
        "status": "ok",
        "message": f"Generated {result['tile_count']}/{result['grid_cols'] * result['grid_rows']} tiles ({result['grid_cols']}×{result['grid_rows']})",
        "download_url": f"/api/files/{download_id}",
        "tile_count": result["tile_count"],
        "grid_cols": result["grid_cols"],
        "grid_rows": result["grid_rows"],
        "warnings": list(warnings or []) + list(result.get("warnings", [])),
    }


async def _generate_large_format_raster(
    *,
    image_path: str,
    lut_path: str,
    total_width_mm: float,
    total_height_mm: float,
    tile_width_mm: float,
    tile_height_mm: float,
    request,
    session_data: dict,
    sid: str,
    store: SessionStore,
    registry: FileRegistry,
    pool: WorkerPoolManager,
    warnings: list[str] | None = None,
) -> dict:
    with Image.open(image_path) as img:
        px_w, px_h = img.size
        full_img = img.copy()

    px_per_mm_x = px_w / total_width_mm
    px_per_mm_y = px_h / total_height_mm
    cols = max(1, math.ceil(total_width_mm / tile_width_mm))
    rows = max(1, math.ceil(total_height_mm / tile_height_mm))
    shared_params = _resolve_large_format_shared_params(
        session_data,
        request,
        _resolve_relief_global_max_height(session_data, request),
    )
    if str(image_path).lower().endswith(".png") and shared_params["modeling_mode"] == CoreModelingMode.VECTOR:
        shared_params["modeling_mode"] = CoreModelingMode.HIGH_FIDELITY
    hm_gray = (
        session_data.get("heightmap_grayscale")
        if (request.enable_relief and (request.height_mode or "color") == "heightmap")
        else None
    )

    futures = []
    tile_labels: list[str] = []
    base_name = os.path.splitext(os.path.basename(image_path))[0]
    for r in range(rows):
        for c in range(cols):
            x0_mm = c * tile_width_mm
            y0_mm = r * tile_height_mm
            x1_mm = min(x0_mm + tile_width_mm, total_width_mm)
            y1_mm = min(y0_mm + tile_height_mm, total_height_mm)
            cur_tile_w = x1_mm - x0_mm

            px_x0 = int(round(x0_mm * px_per_mm_x))
            px_y0 = int(round(y0_mm * px_per_mm_y))
            px_x1 = min(int(round(x1_mm * px_per_mm_x)), px_w)
            px_y1 = min(int(round(y1_mm * px_per_mm_y)), px_h)

            tile_img = full_img.crop((px_x0, px_y0, px_x1, px_y1))
            fd, tile_path = tempfile.mkstemp(suffix=".png", dir=TEMP_DIR)
            os.close(fd)
            tile_img.save(tile_path)
            store.register_temp_file(sid, tile_path)

            tile_params = dict(shared_params, target_width_mm=cur_tile_w)
            if hm_gray is not None:
                hm_tile = hm_gray[px_y0:px_y1, px_x0:px_x1]
                fd2, hm_tile_path = tempfile.mkstemp(suffix=".png", dir=TEMP_DIR)
                os.close(fd2)
                Image.fromarray(hm_tile).save(hm_tile_path)
                store.register_temp_file(sid, hm_tile_path)
                tile_params["heightmap_path"] = hm_tile_path

            label = f"{base_name}_R{r + 1}C{c + 1}"
            tile_labels.append(label)
            futures.append(pool.submit(worker_generate_model, tile_path, lut_path, tile_params))

    successful_paths: list[tuple[str, str]] = []
    errors: list[str] = []
    for label, fut in zip(tile_labels, futures):
        try:
            result = await fut
            tp = result.get("threemf_path")
            if tp and os.path.exists(tp):
                successful_paths.append((label, tp))
            else:
                errors.append(f"{label}: generation failed — {result.get('status_msg', 'unknown')}")
        except ROUTER_HANDLED_ERRORS as e:
            errors.append(f"{label}: {e}")

    if not successful_paths:
        detail = "All tiles failed"
        if errors:
            detail += ": " + "; ".join(errors[:5])
        raise HTTPException(status_code=500, detail=detail)

    fd, zip_path = tempfile.mkstemp(suffix=".zip", dir=TEMP_DIR)
    os.close(fd)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for label, tp in successful_paths:
            zf.write(tp, f"{label}.3mf")
    store.register_temp_file(sid, zip_path)
    download_id = registry.register_path(sid, zip_path)

    msg = f"Generated {len(successful_paths)}/{cols * rows} tiles ({cols}×{rows})"
    if errors:
        msg += f" — {len(errors)} failed"
    return {
        "status": "ok",
        "message": msg,
        "download_url": f"/api/files/{download_id}",
        "tile_count": len(successful_paths),
        "grid_cols": cols,
        "grid_rows": rows,
        "warnings": list(warnings or []),
    }


def _rasterize_svg_for_large_format_fallback(
    *,
    svg_path: str,
    total_width_mm: float,
    total_height_mm: float,
    sid: str,
    store: SessionStore,
) -> tuple[str, list[str]]:
    density, density_warnings = choose_svg_raster_fallback_density(
        total_width_mm=total_width_mm,
        total_height_mm=total_height_mm,
    )
    raster_rgba = rasterize_svg(svg_path, total_width_mm, pixels_per_mm=density)
    fd, png_path = tempfile.mkstemp(suffix=".png", dir=TEMP_DIR)
    os.close(fd)
    Image.fromarray(raster_rgba).save(png_path)
    store.register_temp_file(sid, png_path)
    return png_path, density_warnings


@router.post("/generate-large-format")
async def convert_generate_large_format(
    body: _LargeFormatBody,
    store: SessionStore = Depends(get_session_store),
    registry: FileRegistry = Depends(get_file_registry),
    pool: WorkerPoolManager = Depends(get_worker_pool),
) -> LargeFormatGenerateResponse:
    """Split image into tiles, generate a 3MF per tile, and package into ZIP.
    将图片切割为网格切片，每片生成 3MF，打包为 ZIP。
    """
    # 1. Session validation
    session_data = _require_session(store, body.session_id)
    cache = _require_preview_cache(session_data)

    lf = body.params
    request = lf.params

    if _has_requested_fridge_magnet_cavities(request):
        raise HTTPException(
            status_code=422,
            detail="Large-format tiled generation does not support fridge magnet cavities.",
        )

    image_path: str | None = session_data.get("image_path")
    lut_path: str | None = session_data.get("lut_path")
    if not image_path or not os.path.exists(image_path):
        raise HTTPException(status_code=409, detail="Image file missing. Call POST /api/convert/preview first.")
    if not lut_path or not os.path.exists(lut_path):
        raise HTTPException(status_code=409, detail="LUT file missing. Call POST /api/convert/preview first.")

    sid = body.session_id
    total_w_mm, total_h_mm = _resolve_large_format_dimensions(cache, request, lf.target_height_mm)
    tile_w_mm = lf.tile_width_mm
    tile_h_mm = lf.tile_height_mm

    warnings: list[str] = []
    is_svg_vector = str(image_path).lower().endswith(".svg") and request.modeling_mode.value == "vector"
    if is_svg_vector:
        policy = session_data.get("svg_large_format_policy")
        if not isinstance(policy, dict):
            policy = inspect_svg_large_format_support(image_path)
            session_data["svg_large_format_policy"] = policy
        warnings.extend(list(policy.get("warnings", [])))

        if bool(policy.get("native_tiling_supported", False)):
            result = await _generate_large_format_svg_native(
                image_path=image_path,
                lut_path=lut_path,
                total_width_mm=total_w_mm,
                total_height_mm=total_h_mm,
                tile_width_mm=tile_w_mm,
                tile_height_mm=tile_h_mm,
                request=request,
                session_data=session_data,
                sid=sid,
                store=store,
                registry=registry,
                pool=pool,
                warnings=warnings,
            )
        else:
            fallback_png_path, density_warnings = _rasterize_svg_for_large_format_fallback(
                svg_path=image_path,
                total_width_mm=total_w_mm,
                total_height_mm=total_h_mm,
                sid=sid,
                store=store,
            )
            result = await _generate_large_format_raster(
                image_path=fallback_png_path,
                lut_path=lut_path,
                total_width_mm=total_w_mm,
                total_height_mm=total_h_mm,
                tile_width_mm=tile_w_mm,
                tile_height_mm=tile_h_mm,
                request=request,
                session_data=session_data,
                sid=sid,
                store=store,
                registry=registry,
                pool=pool,
                warnings=warnings + [SVG_LARGE_FORMAT_GENERATE_FALLBACK_WARNING] + density_warnings,
            )
    else:
        result = await _generate_large_format_raster(
            image_path=image_path,
            lut_path=lut_path,
            total_width_mm=total_w_mm,
            total_height_mm=total_h_mm,
            tile_width_mm=tile_w_mm,
            tile_height_mm=tile_h_mm,
            request=request,
            session_data=session_data,
            sid=sid,
            store=store,
            registry=registry,
            pool=pool,
            warnings=warnings,
        )

    return LargeFormatGenerateResponse(**result)


@router.post("/batch")
async def convert_batch(
    images: list[UploadFile] = File(..., description="批量图像"),
    lut_name: str = Form(..., description="LUT 名称"),
    target_width_mm: float = Form(60.0, description="目标宽度 (mm)"),
    spacer_thick: float = Form(1.2, description="底板厚度 (mm)"),
    structure_mode: str = Form("Double-sided", description="打印结构模式"),
    auto_bg: bool = Form(False, description="自动去背景"),
    bg_tol: int = Form(40, description="背景容差"),
    color_mode: str = Form("4-Color (RYBW)", description="颜色模式"),
    modeling_mode: str = Form("high-fidelity", description="建模模式"),
    quantize_colors: int = Form(48, description="K-Means 色彩细节"),
    enable_cleanup: bool = Form(True, description="孤立像素清理"),
    hue_weight: float = Form(0.0, description="色相保护权重"),
    chroma_gate: float = Form(15.0, description="暗色彩度门槛"),
    registry: FileRegistry = Depends(get_file_registry),
    pool: WorkerPoolManager = Depends(get_worker_pool),
) -> BatchResponse:
    """Batch-convert multiple images via process pool.
    通过进程池批量转换多张图像。

    File uploads and FileRegistry operations run on the main thread.
    Each batch item's CPU-intensive conversion is submitted sequentially
    to the worker pool, one at a time.
    文件上传和 FileRegistry 操作在主线程完成。
    每个批量项的 CPU 密集型转换逐个提交到工作进程池。
    """
    # Resolve LUT path (main thread)
    lut_path = LUTManager.get_lut_path(lut_name)
    if lut_path is None:
        raise HTTPException(status_code=404, detail=f"LUT not found: {lut_name}")

    # Validate modeling_mode string (main thread)
    try:
        CoreModelingMode(modeling_mode)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid modeling_mode: {modeling_mode}",
        )

    results: list[BatchItemResult] = []
    successful_entries: list[tuple[str, str]] = []

    # Submit each batch item sequentially to the process pool
    for upload_file in images:
        filename = upload_file.filename or "unknown"
        try:
            # 1. File upload (I/O, main thread)
            temp_path = await ensure_png_tempfile(upload_file)

            # 2. CPU computation offloaded to process pool (only paths and scalars)
            result = await pool.submit(
                worker_batch_convert_item,
                temp_path,
                lut_path,
                target_width_mm,
                spacer_thick,
                structure_mode,
                auto_bg,
                bg_tol,
                color_mode,
                modeling_mode,
                quantize_colors,
                enable_cleanup,
                hue_weight,
                chroma_gate,
            )

            # 3. Result processing (main thread)
            threemf_path: str | None = result.get("threemf_path")
            status_msg: str = result.get("status_msg", "")

            if threemf_path and os.path.exists(threemf_path):
                successful_entries.append((threemf_path, filename))
                results.append(
                    BatchItemResult(
                        filename=filename,
                        status="success",
                    )
                )
            else:
                results.append(
                    BatchItemResult(
                        filename=filename,
                        status="failed",
                        error=status_msg or "3MF generation returned no output",
                    )
                )
        except asyncio.TimeoutError:
            results.append(
                BatchItemResult(
                    filename=filename,
                    status="failed",
                    error="Batch item conversion timed out",
                )
            )
        except ROUTER_HANDLED_ERRORS as e:
            results.append(
                BatchItemResult(
                    filename=filename,
                    status="failed",
                    error=str(e),
                )
            )

    # Package successful 3MF files into a ZIP (main thread)
    fd, zip_path = tempfile.mkstemp(suffix=".zip", dir=TEMP_DIR)
    os.close(fd)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for idx, (path_3mf, src_filename) in enumerate(successful_entries, start=1):
            base_name = os.path.splitext(os.path.basename(src_filename))[0] or "item"
            arcname = f"{idx:03d}_{base_name}.3mf"
            zf.write(path_3mf, arcname)

    # Register ZIP via FileRegistry (main thread)
    download_id = registry.register_path(
        str(uuid.uuid4()),
        zip_path,
        ttl_seconds=BATCH_DOWNLOAD_TTL_SECONDS,
    )

    success_count = sum(1 for r in results if r.status == "success")
    total_count = len(results)

    return BatchResponse(
        status="ok" if success_count > 0 else "failed",
        message=f"Batch complete: {success_count}/{total_count} succeeded",
        download_url=f"/api/files/{download_id}",
        results=results,
    )
