"""Converter router preview module."""

from __future__ import annotations

import asyncio
import json
import os
import pickle
import time
import uuid
from pathlib import Path

import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from PIL import Image
from pydantic import ValidationError

from api.dependencies import get_file_registry, get_session_store, get_worker_pool
from api.file_bridge import ensure_png_tempfile, ndarray_to_png_bytes
from api.file_registry import FileRegistry
from api.schemas.converter import BedSizeItem, BedSizeListResponse
from api.schemas.lut import LutSourceSelection
from api.schemas.responses import (
    AutoDetectColorsResponse,
    CropResponse,
    HeightmapUploadResponse,
    PreviewResponse,
)
from api.session_store import SessionStore
from api.structured_logging import bind_session_id, get_logger
from api.worker_pool import WorkerPoolManager
from api.workers.converter_workers import worker_generate_preview
from config import BedManager, OUTPUT_DIR, PrinterConfig, TEMP_DIR
from core.converter import generate_empty_bed_glb, generate_segmented_glb
from core.naming import generate_segmented_glb_filename
from core.heightmap_loader import HeightmapLoader
from core.image_preprocessor import ImagePreprocessor
from core.vector_large_format import inspect_svg_large_format_support, normalize_large_format_source_basename
from utils.lut_manager import LUTManager

from .async_glb import get_glb_status
from .common import (
    EPHEMERAL_PREVIEW_TTL_SECONDS,
    NON_FATAL_GLB_ERRORS,
    ROUTER_HANDLED_ERRORS,
    _handle_core_error,
    _image_to_png_bytes,
    _require_preview_cache,
    _require_session,
    _resolve_material_backing_index,
    recompute_gradient_groups_into_session,
)

router = APIRouter()
log = get_logger(__name__)


def _resolve_upload_source_basename(filename: str | None, temp_path: str) -> str:
    """Resolve a stable source basename from upload metadata across path styles."""

    candidate = str(filename or "").strip()
    if candidate:
        normalized_filename = candidate.replace("\\", "/")
        source_basename = normalize_large_format_source_basename(
            os.path.splitext(os.path.basename(normalized_filename))[0]
        )
        if source_basename:
            return source_basename
    fallback_basename = os.path.splitext(os.path.basename(temp_path))[0]
    return normalize_large_format_source_basename(fallback_basename) or fallback_basename


def _cleanup_pre_session_temp_paths(*paths: str | None) -> None:
    """Best-effort cleanup for temp files created before a session exists."""

    seen: set[str] = set()
    for path in paths:
        if not path or path in seen:
            continue
        seen.add(path)
        try:
            if os.path.exists(path):
                os.unlink(path)
        except OSError as exc:
            log.warning(
                "Failed to clean pre-session temp file",
                extra={
                    "event": "converter_preview_temp_cleanup_failed",
                    "temp_path": path,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                },
            )


def _normalize_db_names(db_names: list[str] | str | None) -> list[str]:
    """Normalize native DB names from form inputs.

    Accepts repeated form fields, JSON-stringified arrays, and plain strings.
    """
    if db_names is None:
        return []

    if isinstance(db_names, str):
        value = db_names.strip()
        if not value:
            return []
        if value.startswith("[") and value.endswith("]"):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                return [db_names]
            if isinstance(parsed, list):
                return [item for item in parsed if isinstance(item, str)]
        return [db_names]

    normalized = list(db_names)
    if len(normalized) == 1 and isinstance(normalized[0], str):
        value = normalized[0].strip()
        if value.startswith("[") and value.endswith("]"):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                return normalized
            if isinstance(parsed, list):
                return [item for item in parsed if isinstance(item, str)]
    return normalized


def _parse_selected_materials(value: list[str] | str | None) -> list[str]:
    """Normalize selected-materials field from multipart/form-data inputs.
    规范化 multipart/form-data 中的 selected_materials 字段。

    Accepts repeated form fields, JSON-stringified arrays (the typical
    frontend shape: ``'["mat1","mat2"]'``), or comma-separated strings.
    """
    if value is None:
        return []

    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        if stripped.startswith("[") and stripped.endswith("]"):
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
        return [s.strip() for s in stripped.split(",") if s.strip()]

    normalized = [str(item) for item in value if str(item).strip()]
    if len(normalized) == 1:
        stripped = normalized[0].strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
    return [s.strip() for s in normalized if s.strip()]


@router.get("/bed-sizes", response_model=BedSizeListResponse)
def get_bed_sizes() -> BedSizeListResponse:
    """Return all available printer bed sizes including printer models and custom sizes.
    返回所有可用的打印热床尺寸列表，包括打印机型号和自定义尺寸。
    """
    beds = [
        BedSizeItem(
            label=label,
            width_mm=w,
            height_mm=h,
            is_default=(label == BedManager.DEFAULT_BED),
            printer_id=printer_id,
        )
        for label, w, h, printer_id in BedManager.get_all_bed_options()
    ]
    return BedSizeListResponse(beds=beds)


@router.get("/bed-preview")
def get_bed_preview(
    bed_label: str = BedManager.DEFAULT_BED,
    registry: FileRegistry = Depends(get_file_registry),
) -> dict:
    """Generate a GLB preview of the empty print bed.
    生成空热床的 GLB 3D 预览。

    Args:
        bed_label: Bed size label (e.g. "256×256 mm"). (热床尺寸标签)

    Returns:
        dict: Contains preview_3d_url pointing to the GLB file. (包含 GLB 文件 URL)
    """
    bed_w, bed_h = BedManager.get_bed_size(bed_label)
    try:
        glb_path = generate_empty_bed_glb(bed_w, bed_h)
    except ROUTER_HANDLED_ERRORS as e:
        _handle_core_error(e, "Bed preview generation")

    if glb_path is None:
        raise HTTPException(status_code=500, detail="Failed to generate bed preview")

    glb_id = registry.register_path(
        str(uuid.uuid4()),
        glb_path,
        ttl_seconds=EPHEMERAL_PREVIEW_TTL_SECONDS,
    )
    return {"preview_3d_url": f"/api/files/{glb_id}"}


@router.post("/auto-detect-colors", response_model=AutoDetectColorsResponse)
async def auto_detect_colors(
    image: UploadFile = File(..., description="输入图像"),
    target_width_mm: float = Form(60.0, description="目标打印宽度（毫米）"),
) -> AutoDetectColorsResponse:
    """Analyze an image and recommend the optimal quantization color count.
    分析图片，自动推荐最佳量化颜色数。

    This endpoint is session-less: the uploaded temp file is deleted in a
    ``finally`` block because no session exists to register it for later
    cleanup.
    此端点无会话：上传的临时文件在 finally 块中删除，因为没有会话来注册它
    以便后续清理。
    """
    temp_path = await ensure_png_tempfile(image)
    try:
        result = ImagePreprocessor.analyze_recommended_colors(temp_path, target_width_mm)
    except (ValueError, TypeError, OSError, RuntimeError) as e:
        raise HTTPException(status_code=422, detail=f"颜色分析失败: {e}")
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
    log.info(
        "Auto-detected color count",
        extra={
            "event": "converter_auto_detect_colors_done",
            "image_filename": image.filename or "",
            "target_width_mm": target_width_mm,
            "recommended": result.get("recommended", 48),
            "max_safe": result.get("max_safe", 64),
            "unique_colors": result.get("unique_colors", 0),
            "complexity_score": result.get("complexity_score", 0),
        },
    )
    return AutoDetectColorsResponse(
        recommended=result.get("recommended", 48),
        max_safe=result.get("max_safe", 64),
        unique_colors=result.get("unique_colors", 0),
        complexity_score=result.get("complexity_score", 0),
    )


@router.post("/crop", response_model=CropResponse)
async def crop_image(
    image: UploadFile = File(..., description="输入图像"),
    x: int = Form(0, description="裁剪起点 X"),
    y: int = Form(0, description="裁剪起点 Y"),
    width: int = Form(100, ge=1, description="裁剪宽度"),
    height: int = Form(100, ge=1, description="裁剪高度"),
    registry: FileRegistry = Depends(get_file_registry),
) -> CropResponse:
    """Crop an uploaded image and return the cropped result URL.
    裁剪上传的图片并返回裁剪后的文件 URL。

    Args:
        image: 上传的图片文件
        x: 裁剪起点 X 坐标
        y: 裁剪起点 Y 坐标
        width: 裁剪宽度（像素）
        height: 裁剪高度（像素）
        registry: FileRegistry 依赖

    Returns:
        CropResponse: 包含裁剪后图片 URL 和尺寸
    """
    # 1. Save uploaded file to temp path
    temp_path = await ensure_png_tempfile(image)

    # 2. Validate that the file is a readable image
    try:
        ImagePreprocessor.get_image_dimensions(temp_path)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid image file")

    # 3. Crop image (CropRegion.clamp is called internally)
    try:
        cropped_path = ImagePreprocessor.crop_image(temp_path, x, y, width, height)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # 4. Get cropped image dimensions
    w, h = ImagePreprocessor.get_image_dimensions(cropped_path)

    # 5. Register cropped file and return response
    file_id = registry.register_path(
        str(uuid.uuid4()),
        cropped_path,
        ttl_seconds=EPHEMERAL_PREVIEW_TTL_SECONDS,
    )
    return CropResponse(
        status="ok",
        message="Image cropped successfully",
        cropped_url=f"/api/files/{file_id}",
        width=w,
        height=h,
    )


@router.post("/preview")
async def convert_preview(
    image: UploadFile = File(..., description="输入图像"),
    source_kind: str = Form("legacy_single", description="源类型: legacy_single | native_bundle"),
    lut_name: str | None = Form(None, description="LUT 名称"),
    material_type: str | None = Form(None, description="原生材料类型"),
    vendor: str | None = Form(None, description="原生厂商"),
    db_names: list[str] | str | None = Form(None, description="原生 DB 名称列表"),
    target_width_mm: float = Form(60.0, description="目标宽度 (mm)"),
    color_mode: str = Form("4-Color (RYBW)", description="颜色模式"),
    modeling_mode: str = Form("high-fidelity", description="建模模式"),
    color_layers: int | None = Form(None, description="叠色层数"),
    layer_height_mm: float | None = Form(None, description="叠色层高 (mm)"),
    model_enable: bool = Form(False, description="启用模型辅助匹配"),
    model_only: bool = Form(False, description="仅使用模型匹配"),
    model_threshold: float | None = Form(None, description="模型回退阈值"),
    model_margin: float | None = Form(None, description="模型回退边距"),
    quantize_colors: int = Form(48, description="K-Means 色彩细节（仅高保真模式生效）"),
    enable_cleanup: bool = Form(True, description="孤立像素清理"),
    hue_weight: float = Form(0.0, description="色相保护权重"),
    chroma_gate: float = Form(15.0, description="暗色彩度门槛"),
    use_lut_constrained: bool = Form(False, description="高精度LUT约束匹配"),
    auto_dynamic_range: bool = Form(False, description="自动动态范围压缩（实验性）"),
    is_dark: bool = Form(True, description="深色主题"),
    material_source: str = Form("lut", description="颜色来源: lut | material_archive"),
    selected_materials: list[str] | str | None = Form(None, description="已选耗材目录名列表"),
    material_layer_count: int | None = Form(None, description="耗材模式叠色层数 (5-10)"),
    material_layer_height_mm: float | None = Form(None, description="耗材模式层高 (mm)"),
    material_grid_resolution: int | None = Form(
        None,
        description=(
            "Opt-in exhaustive-cache Lab grid resolution (64/128/256); "
            "forwarded to the solver cache lookup. ``None`` uses the backend "
            "default so low-tier caches keep working unchanged. "
            "穷举缓存 Lab 网格分辨率，None 时走后端默认。"
        ),
    ),
    material_backing_material_index: int | None = Form(
        None,
        description="耗材档案模式底板耗材索引（基于 selected_materials 的 0-based 索引）",
    ),
    store: SessionStore = Depends(get_session_store),
    registry: FileRegistry = Depends(get_file_registry),
    pool: WorkerPoolManager = Depends(get_worker_pool),
) -> PreviewResponse:
    """Generate a 2D color-matched preview via process pool.
    通过进程池生成 2D 颜色匹配预览图。

    File upload and session/registry operations run on the main thread.
    CPU-intensive preview generation is offloaded to the worker pool.
    文件上传和 session/registry 操作在主线程完成。
    CPU 密集型预览生成卸载到工作进程池。
    """
    _api_t0 = time.perf_counter()
    temp_path: str | None = None
    temp_native_bundle_path: str | None = None
    worker_preview_png_path: str | None = None
    worker_cache_data_path: str | None = None
    svg_large_format_policy = None
    # Material-archive mode: skip LUT resolution entirely
    if material_source == "material_archive":
        request = LutSourceSelection.model_validate(
            {"source_kind": "legacy_single", "lut_name": "__material_archive__", "material_type": None, "vendor": None, "db_names": []}
        )
        lut_path = "__material_archive__"
        resolved_lut_name = "__material_archive__"
        resolved_lut_path = "__material_archive__"
    else:
        try:
            normalized_db_names = _normalize_db_names(db_names)
            request = LutSourceSelection.model_validate(
                {
                    "source_kind": source_kind,
                    "lut_name": lut_name,
                    "material_type": material_type,
                    "vendor": vendor,
                    "db_names": normalized_db_names,
                }
            )
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=json.loads(exc.json())) from exc

        try:
            lut_path, resolved_lut_name = LUTManager.resolve_source_selection(
                source_kind=request.source_kind,
                lut_name=request.lut_name,
                material_type=request.material_type,
                vendor=request.vendor,
                db_names=request.db_names,
            )
        except ValueError as exc:
            detail = str(exc)
            status_code = 404 if detail.startswith("LUT not found:") else 422
            raise HTTPException(status_code=status_code, detail=detail) from exc

        resolved_lut_path = os.path.abspath(lut_path)
    if request.source_kind == "native_bundle":
        try:
            Path(resolved_lut_path).resolve().relative_to(Path(TEMP_DIR).resolve())
        except ValueError:
            temp_native_bundle_path = None
        else:
            temp_native_bundle_path = resolved_lut_path

    # Mint session_id at endpoint entry and bind to contextvar so worker-emitted
    # log records (image_processor_init/done, isolated_pixels_cleaned, ...) carry
    # the same id that will be returned in the preview response.
    # 在端点入口生成 session_id 并写入 contextvar，使 worker 内日志事件能溯源到最终返回的会话。
    preview_session_id = str(uuid.uuid4())
    bind_session_id(preview_session_id)

    worker_completed = False
    try:
        # 1. File upload (I/O, main thread)
        _t = time.perf_counter()
        temp_path = await ensure_png_tempfile(image)
        _t_upload = time.perf_counter() - _t
        is_svg_upload = str(temp_path).lower().endswith(".svg")
        if modeling_mode == "vector" and is_svg_upload:
            svg_large_format_policy = {
                **inspect_svg_large_format_support(temp_path),
                "inspection_source": "preview-vector-svg",
            }

        # 2. CPU computation offloaded to process pool (only paths and scalars)
        log.debug(
            "Submitting preview worker task",
            extra={
                "event": "converter_preview_submit",
                "hue_weight": hue_weight,
                "lut_name": resolved_lut_name,
                "source_kind": request.source_kind,
                "color_mode": color_mode,
                "color_layers": color_layers,
                "layer_height_mm": layer_height_mm,
                "model_enable": model_enable,
                "model_only": model_only,
                "model_threshold": model_threshold,
                "model_margin": model_margin,
            },
        )
        _t = time.perf_counter()
        _selected_mats: list[str] | None = None
        _material_backing_index = 0
        if material_source == "material_archive":
            _selected_mats = (
                _parse_selected_materials(selected_materials)
                if selected_materials is not None
                else []
            )
            _material_backing_index = _resolve_material_backing_index(
                _selected_mats,
                material_backing_material_index,
            )
            log.debug(
                "Material mode parsed: count=%d names=%s",
                len(_selected_mats or []),
                _selected_mats,
                extra={
                    "event": "converter_preview_material_mode_parsed",
                    "selected_material_count": len(_selected_mats or []),
                },
            )

        result = await pool.submit(
            worker_generate_preview,
            temp_path,
            lut_path if material_source != "material_archive" else "__material_archive__",
            target_width_mm,
            color_mode,
            modeling_mode,
            color_layers,
            layer_height_mm,
            quantize_colors,
            enable_cleanup,
            is_dark,
            model_enable,
            model_only,
            model_threshold,
            model_margin,
            hue_weight,
            chroma_gate,
            use_lut_constrained,
            material_source,
            _selected_mats,
            material_layer_count,
            material_layer_height_mm,
            material_grid_resolution,
            auto_dynamic_range,
        )
        _t_worker = time.perf_counter() - _t
        worker_completed = True
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Preview generation timed out")
    except ROUTER_HANDLED_ERRORS as e:
        log.exception(
            "Preview generation failed",
            extra={
                "event": "converter_preview_worker_error",
                "error_type": type(e).__name__,
                "error_message": str(e),
            },
        )
        raise HTTPException(status_code=500, detail=f"Preview generation failed: {str(e)}")
    finally:
        if not worker_completed:
            _cleanup_pre_session_temp_paths(temp_path, temp_native_bundle_path)

    # 3. Result processing (I/O + Session, main thread)
    result_loaded = False
    try:
        worker_preview_png_path = result["preview_png_path"]
        worker_cache_data_path = result["cache_data_path"]
        if worker_preview_png_path is None:
            raise HTTPException(status_code=500, detail=result["status_msg"] or "Preview generation failed")

        # Load cache_data from disk (worker serialized to .pkl)
        _t = time.perf_counter()
        with open(worker_cache_data_path, "rb") as f:
            cache_data = pickle.load(f)
        _t_pickle_load = time.perf_counter() - _t

        # Load preview image from disk (worker saved as .png)
        preview_img = Image.open(worker_preview_png_path)
        result_loaded = True
    finally:
        if not result_loaded:
            _cleanup_pre_session_temp_paths(
                temp_path,
                temp_native_bundle_path,
                worker_preview_png_path,
                worker_cache_data_path,
            )

    status_msg: str = result["status_msg"]

    # Reuse the session_id minted before worker submit so worker logs and the
    # returned session use the same id; SessionStore.create() will fall back to
    # a fresh UUID if the pre-minted id ever collides.
    # 复用 worker submit 前生成的 session_id，确保 worker 日志与返回会话同 id；
    # 若 id 与现有会话冲突，SessionStore.create() 会自动改用新 UUID。
    session_id = store.create(session_id=preview_session_id)
    store.put(session_id, "preview_cache", cache_data)
    # Synchronously compute gradient-banding groups so the Color Workstation
    # can surface them (group-level multi-select + optional auto-replace)
    # without a second round-trip. Best-effort: failures are logged and do
    # not block the preview response.
    # 同步计算渐变海带纹分组，便于颜色工作站的分组多选与自动换色。
    recompute_gradient_groups_into_session(cache_data, session_id, store)
    store.put(session_id, "image_path", temp_path)
    source_basename = _resolve_upload_source_basename(image.filename, temp_path)
    store.put(session_id, "source_basename", source_basename)
    store.put(session_id, "lut_path", lut_path)
    store.put(session_id, "lut_name", resolved_lut_name)
    store.put(session_id, "lut_source_kind", request.source_kind)
    store.put(session_id, "lut_material_type", request.material_type)
    store.put(session_id, "lut_vendor", request.vendor)
    store.put(session_id, "lut_db_names", list(request.db_names))
    store.put(session_id, "color_mode", color_mode)
    store.put(session_id, "color_layers", color_layers)
    store.put(session_id, "layer_height_mm", layer_height_mm)
    store.put(session_id, "model_enable", model_enable)
    store.put(session_id, "model_only", model_only)
    store.put(session_id, "model_threshold", model_threshold)
    store.put(session_id, "model_margin", model_margin)
    store.put(session_id, "material_source", material_source)
    if material_source == "material_archive":
        store.put(session_id, "selected_materials", _selected_mats or [])
        store.put(session_id, "material_layer_count", material_layer_count)
        store.put(session_id, "material_layer_height_mm", material_layer_height_mm)
        store.put(
            session_id,
            "material_grid_resolution",
            material_grid_resolution,
        )
        store.put(
            session_id,
            "material_backing_material_index",
            _material_backing_index,
        )
    store.put(session_id, "replacement_regions", [])
    store.put(session_id, "replacement_history", [])
    store.put(session_id, "free_color_set", set())
    if svg_large_format_policy is not None:
        store.put(session_id, "svg_large_format_policy", svg_large_format_policy)
    # Save a pristine copy of matched_rgb for reset-replacements
    if cache_data and "matched_rgb" in cache_data:
        store.put(session_id, "original_matched_rgb", cache_data["matched_rgb"].copy())
    if cache_data and "material_matrix" in cache_data:
        store.put(
            session_id,
            "original_material_matrix",
            cache_data["material_matrix"].copy(),
        )
    store.register_temp_file(session_id, temp_path)
    if temp_native_bundle_path is not None:
        store.register_temp_file(session_id, temp_native_bundle_path)
    # Register worker temp files for cleanup
    store.register_temp_file(session_id, worker_preview_png_path)
    store.register_temp_file(session_id, worker_cache_data_path)

    # Register preview image (bed-rendered, for general display)
    preview_bytes = _image_to_png_bytes(preview_img)
    preview_id = registry.register_bytes(session_id, preview_bytes, "preview.png")

    # Register raw RGBA preview (no bed, pixel-aligned with previewPixelWidth/Height)
    # Used by ColorPreview2D so SVG contour overlays and click coords align.
    preview_raw_url: str | None = None
    if cache_data and "preview_rgba" in cache_data:
        raw_rgba = cache_data["preview_rgba"]
        raw_bytes = ndarray_to_png_bytes(raw_rgba)
        raw_id = registry.register_bytes(session_id, raw_bytes, "preview_raw.png")
        preview_raw_url = f"/api/files/{raw_id}"

    # Generate segmented GLB (one Mesh per color)
    _t = time.perf_counter()
    preview_glb_url: str | None = None
    try:
        target_path = os.path.join(
            OUTPUT_DIR,
            generate_segmented_glb_filename(session_id),
        )
        glb_path = generate_segmented_glb(cache_data, output_path=target_path)
        if glb_path and os.path.exists(glb_path):
            glb_id = registry.register_path(session_id, glb_path)
            preview_glb_url = f"/api/files/{glb_id}"
    except NON_FATAL_GLB_ERRORS as e:
        # Non-fatal: log and continue without GLB
        log.warning(
            "Segmented GLB generation failed",
            extra={
                "event": "converter_segmented_glb_failed",
                "error_type": type(e).__name__,
                "error_message": str(e),
            },
        )
    _t_glb = time.perf_counter() - _t

    # Build palette with quantized_hex, matched_hex, pixel_count, percentage
    _t = time.perf_counter()
    raw_palette: list[dict] = cache_data.get("color_palette", []) if cache_data else []
    quantized_image = cache_data.get("quantized_image") if cache_data else None
    matched_rgb_arr = cache_data.get("matched_rgb") if cache_data else None
    mask_solid_arr = cache_data.get("mask_solid") if cache_data else None

    palette: list[dict] = []
    if raw_palette and matched_rgb_arr is not None and mask_solid_arr is not None:
        matched_to_quantized: dict[str, str] = {}
        if quantized_image is not None:
            solid_mask = mask_solid_arr
            q_pixels = quantized_image[solid_mask]  # (N, 3)
            m_pixels = matched_rgb_arr[solid_mask]  # (N, 3)

            # Vectorized: encode RGB triplets as uint32 scalars, find dominant
            # quantized color per matched color in a single np.unique pass.
            m_enc = (
                (m_pixels[:, 0].astype(np.uint32) << 16)
                | (m_pixels[:, 1].astype(np.uint32) << 8)
                | m_pixels[:, 2].astype(np.uint32)
            )
            q_enc = (
                (q_pixels[:, 0].astype(np.uint32) << 16)
                | (q_pixels[:, 1].astype(np.uint32) << 8)
                | q_pixels[:, 2].astype(np.uint32)
            )

            pair_key = m_enc.astype(np.uint64) * (1 << 24) + q_enc.astype(np.uint64)
            unique_keys, counts = np.unique(pair_key, return_counts=True)

            u_m = (unique_keys >> 24).astype(np.uint32)
            u_q = (unique_keys & 0xFFFFFF).astype(np.uint32)

            order = np.lexsort((-counts, u_m))
            sorted_m = u_m[order]
            sorted_q = u_q[order]
            _, first_idx = np.unique(sorted_m, return_index=True)

            for mk, qk in zip(sorted_m[first_idx], sorted_q[first_idx]):
                m_hex = f"#{(mk >> 16) & 0xFF:02x}{(mk >> 8) & 0xFF:02x}{mk & 0xFF:02x}"
                q_hex = f"#{(qk >> 16) & 0xFF:02x}{(qk >> 8) & 0xFF:02x}{qk & 0xFF:02x}"
                matched_to_quantized[m_hex] = q_hex

        for entry in raw_palette:
            m_hex = entry["hex"]  # '#rrggbb'
            q_hex = matched_to_quantized.get(m_hex, m_hex)
            palette.append(
                {
                    "quantized_hex": q_hex,
                    "matched_hex": m_hex,
                    "pixel_count": entry["count"],
                    "percentage": entry["percentage"],
                }
            )

    dimensions: dict = {}
    if cache_data:
        dimensions = {
            "width": cache_data.get("target_w", 0),
            "height": cache_data.get("target_h", 0),
        }
    if preview_raw_url:
        dimensions["preview_raw_url"] = preview_raw_url

    _t_palette = time.perf_counter() - _t

    # Extract color contours from cache (generated by generate_segmented_glb)
    contours_data: dict[str, list[list[list[float]]]] | None = None
    if cache_data and "color_contours" in cache_data:
        contours_data = cache_data["color_contours"]

    _t_api_total = time.perf_counter() - _api_t0
    log.info(
        "Preview endpoint timing",
        extra={
            "event": "converter_preview_timing",
            "duration_ms": round(_t_api_total * 1000, 3),
            "upload_ms": round(_t_upload * 1000, 3),
            "worker_ms": round(_t_worker * 1000, 3),
            "pickle_load_ms": round(_t_pickle_load * 1000, 3),
            "segmented_glb_ms": round(_t_glb * 1000, 3),
            "palette_ms": round(_t_palette * 1000, 3),
        },
    )

    return PreviewResponse(
        session_id=session_id,
        status="ok",
        message=status_msg or "Preview generated",
        preview_url=f"/api/files/{preview_id}",
        preview_glb_url=preview_glb_url,
        lut_match_mode=(cache_data.get("lut_match_info", {}) or {}).get("match_mode"),
        lut_match_info=cache_data.get("lut_match_info"),
        palette=palette,
        dimensions=dimensions,
        contours=contours_data,
        warnings=list((svg_large_format_policy or {}).get("warnings", [])),
    )




def _compute_layer_images_cache_key(
    material_matrix: np.ndarray,
    preview_colors_src: object,
    slots_src: object,
) -> str:
    """Hash key derived from the inputs that determine the rendered layer PNGs.
    Key = sha1(material_matrix bytes + shape + preview_colors repr + slots repr).
    基于决定层图像素内容的输入计算缓存 key；material_matrix / 调色板没变就命中。
    """
    import hashlib

    hasher = hashlib.sha1()
    # material_matrix is dtype-stable (int16) and its bytes uniquely identify
    # the per-pixel per-layer material id distribution. Include shape so two
    # different-shaped matrices can't collide.
    # material_matrix 是决定每层可视内容的唯一数据源；shape 避免不同形状冲突。
    hasher.update(bytes(str(material_matrix.shape), "ascii"))
    hasher.update(material_matrix.tobytes())
    # preview_colors + slots affect only the colour mapping but are cheap to
    # serialise and small, so include them to stay correct when a caller
    # rebinds colours in-place without touching material_matrix.
    # 把调色板也塞进 key，支持颜色 dict 变化但 matrix 不变的边缘情况。
    hasher.update(repr(preview_colors_src).encode("utf-8", errors="replace"))
    hasher.update(repr(slots_src).encode("utf-8", errors="replace"))
    return hasher.hexdigest()


@router.get("/layer-images/{session_id}")
def get_layer_images(
    session_id: str,
    store: SessionStore = Depends(get_session_store),
    registry: FileRegistry = Depends(get_file_registry),
):
    """Generate per-layer material preview images from cached preview data.
    从缓存的预览数据生成每层材料预览图。

    Returns a list of layer image URLs with material names.
    返回每层图片 URL 和材料名称列表。
    """
    session_data = _require_session(store, session_id)
    cache = _require_preview_cache(session_data)

    material_matrix = cache.get("material_matrix")
    mask_solid = cache.get("mask_solid")
    color_conf = cache.get("color_conf")
    if material_matrix is None or mask_solid is None or color_conf is None:
        raise HTTPException(status_code=400, detail="Preview cache missing required data")

    h, w = material_matrix.shape[:2]
    n_layers = material_matrix.shape[2]

    # For Merged LUTs, use the corrected preview_colors and slot_names from cache
    # (constructed in P01 from LUT palette), otherwise fall back to color_conf
    preview_colors = cache.get("preview_colors")
    slots = cache.get("slot_names")

    if preview_colors is None or slots is None:
        # Fallback to color_conf for standard color modes
        preview_colors = color_conf.get("preview", {})
        slots = color_conf.get("slots", [])

    # Cache lookup: /layer-images was the single biggest latency contributor
    # after a replace (~6s for 6 layers at ~500x500) because every request
    # re-encoded every layer as PNG. Reuse cached PNG bytes when the inputs
    # that drive pixel content (material_matrix + palette) haven't changed.
    # 缓存命中：matched_rgb/调色板没改就复用已编码的 PNG bytes，免去 6 秒重算。
    cache_key = _compute_layer_images_cache_key(
        material_matrix, preview_colors, slots
    )
    cached_entry = session_data.get("layer_images_cache")
    if (
        isinstance(cached_entry, dict)
        and cached_entry.get("key") == cache_key
        and isinstance(cached_entry.get("layers"), list)
    ):
        t_hit = time.perf_counter()
        layers_out: list[dict] = []
        for idx, item in enumerate(cached_entry["layers"]):
            png_bytes = item.get("png_bytes")
            slot_name = item.get("name", f"Layer {idx}")
            if not isinstance(png_bytes, (bytes, bytearray)):
                # Defensive: if somehow malformed, fall through to full recompute
                # 防御性：cache 坏了就走 miss 路径全量重算，不让端点崩掉。
                cached_entry = None
                layers_out = []
                break
            file_id = registry.register_bytes(
                session_id, bytes(png_bytes), f"layer_{idx}.png"
            )
            layers_out.append(
                {
                    "layer_index": idx,
                    "name": slot_name,
                    "url": f"/api/files/{file_id}",
                }
            )
        if cached_entry is not None and layers_out:
            log.debug(
                "layer-images cache hit",
                extra={
                    "event": "converter_layer_images_cache_hit",
                    "n_layers": len(layers_out),
                    "duration_ms": round((time.perf_counter() - t_hit) * 1000, 1),
                },
            )
            return {"session_id": session_id, "layers": layers_out}

    # Build material_id -> rgba mapping
    # preview_colors can be either dict[str, rgba] (Merged LUT) or dict[int, rgba] (standard)
    mat_id_to_rgba: dict[int, object] = {}
    if slots and preview_colors:
        for mat_id, slot_name in enumerate(slots):
            # Try to get color by name first (Merged LUT), then by ID (standard)
            if slot_name in preview_colors:
                mat_id_to_rgba[mat_id] = preview_colors[slot_name]
            elif mat_id in preview_colors:
                mat_id_to_rgba[mat_id] = preview_colors[mat_id]

    t_miss = time.perf_counter()

    # Vectorised palette build: instead of looping over each material and
    # running ``(layer == mat_id) & mask_solid`` (O(materials * h*w) per layer
    # plus a boolean mask allocation per material), look up every pixel's RGB
    # via fancy indexing. Palette slot 0 defaults to the body-grey background
    # (220,220,220) so any pixel whose material id is not in mat_id_to_rgba
    # keeps the old visual.
    # 向量化调色板：把 N_materials×N_layers 的嵌套 mask 计算替换成单次
    # fancy indexing，层生成耗时从秒级降到几十毫秒。
    max_mat_id = int(material_matrix.max()) if material_matrix.size > 0 else 0
    palette_arr = np.full((max_mat_id + 1, 3), 220, dtype=np.uint8)
    for mat_id, rgba in mat_id_to_rgba.items():
        if 0 <= mat_id <= max_mat_id:
            palette_arr[mat_id] = np.asarray(rgba[:3], dtype=np.uint8)

    non_solid_color = np.array([240, 240, 240], dtype=np.uint8)
    non_solid_mask = ~mask_solid

    # PNG encode tuned for near-flat layer previews. Default PIL compress_level
    # is 6; dropping to 1 is ~3-5x faster on these images with a negligible
    # size increase (layers are 2 colours + grey background so entropy is tiny
    # regardless of level).
    # 层图几乎是纯色，编码级别从 6 降到 1，速度提升 3-5×，体积几乎无差。
    def _encode_fast(arr: np.ndarray) -> bytes:
        import io as _io

        buf = _io.BytesIO()
        Image.fromarray(arr).save(buf, format="PNG", compress_level=1)
        return buf.getvalue()

    def _build_layer_array(layer_idx: int) -> np.ndarray:
        layer = material_matrix[:, :, layer_idx]
        # np.clip + fancy indexing: out-of-range ids fall back to slot 0 (body grey).
        layer_clipped = np.clip(layer, 0, max_mat_id)
        layer_img = palette_arr[layer_clipped]
        # Ensure writable contiguous buffer for the non-solid overwrite below
        # (advanced indexing already returns a copy, but be explicit).
        # fancy indexing 已返回 copy；此处显式保证写入连通性。
        layer_img[non_solid_mask] = non_solid_color
        return layer_img

    # Parallel PNG encoding: PIL/libpng releases the GIL during compression so
    # a ThreadPool scales well on multicore. ``min(n_layers, 4)`` keeps the
    # pool small enough to avoid thrashing on 2-core machines.
    # PNG 编码并发：libpng 释放 GIL，线程池在多核上近线性扩展。
    from concurrent.futures import ThreadPoolExecutor

    def _encode_one(layer_idx: int) -> bytes:
        return _encode_fast(_build_layer_array(layer_idx))

    max_workers = max(1, min(n_layers, 4))
    if n_layers > 1 and max_workers > 1:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            encoded_bytes: list[bytes] = list(pool.map(_encode_one, range(n_layers)))
    else:
        encoded_bytes = [_encode_one(0)] if n_layers == 1 else []

    layers: list[dict] = []
    cached_layers: list[dict] = []
    for layer_idx, png_bytes in enumerate(encoded_bytes):
        file_id = registry.register_bytes(
            session_id, png_bytes, f"layer_{layer_idx}.png"
        )
        slot_name = (
            slots[layer_idx] if layer_idx < len(slots) else f"Layer {layer_idx}"
        )
        layers.append(
            {
                "layer_index": layer_idx,
                "name": slot_name,
                "url": f"/api/files/{file_id}",
            }
        )
        cached_layers.append({"name": slot_name, "png_bytes": png_bytes})

    # Persist the newly built PNGs so the next call with the same inputs
    # hits the fast path above.
    # 写回缓存，下一次相同 matrix 直接命中。
    store.put(
        session_id,
        "layer_images_cache",
        {"key": cache_key, "layers": cached_layers},
    )
    log.debug(
        "layer-images cache miss",
        extra={
            "event": "converter_layer_images_cache_miss",
            "n_layers": n_layers,
            "duration_ms": round((time.perf_counter() - t_miss) * 1000, 1),
            "matrix_shape": list(material_matrix.shape),
        },
    )

    return {"session_id": session_id, "layers": layers}


@router.get("/glb-status/{session_id}")
def get_segmented_glb_status(
    session_id: str,
    store: SessionStore = Depends(get_session_store),
):
    """Return the async segmented-GLB build status for *session_id*.

    The replace endpoints (``/replace-color``, ``/region-replace``, batch
    variants, ``/apply-recipe-override``) no longer wait for
    ``generate_segmented_glb`` — on a 3k-pixel-wide image that one step
    alone was responsible for ~35 s (≥75 %) of their total HTTP latency.
    They now return as soon as the PNG is ready and hand GLB regeneration
    off to a background thread (see :mod:`api.routers.converter.async_glb`).
    The frontend polls this endpoint until it sees ``status == "ready"``
    and then swaps its 3D preview to the newly produced GLB URL.
    replace 端点不再等 GLB：PNG 一就绪就响应，GLB 在后台线程跑。前端轮询
    本端点，看到 ``status == "ready"`` 后再用新 GLB URL 刷新 3D 预览。

    Status values / 状态取值：
        - ``idle``    — 该会话从未调度过 GLB 构建（通常只在预览之前出现）。
        - ``pending`` — GLB 正在后台生成；``job_token`` 标识当前任务。
        - ``ready``   — 新 GLB 已写入 FileRegistry，URL 在 ``glb_url`` 中。
        - ``error``   — 后台构建抛错；错误类型/消息在 ``error`` 中。

    The payload is ``{ status, glb_url, job_token, error }``. ``glb_url``
    is the same ``/api/files/<id>`` form the synchronous code used to
    return, so the frontend can feed it straight into ``previewGlbUrl``
    without any rewriting.
    返回体字段：``status`` / ``glb_url`` / ``job_token`` / ``error``；
    ``glb_url`` 与原同步路径返回的格式一致，前端无需额外处理即可直接
    写入 ``previewGlbUrl``。
    """

    session_data = _require_session(store, session_id)
    cache = session_data.get("preview_cache")
    # No preview cache at all: treat as idle rather than erroring so the
    # frontend can poll through the brief window between session create
    # and first /preview completion without getting spurious 409s.
    # 尚无 preview_cache：视为 idle，避免新会话短暂窗口期 polling 报 409。
    if not isinstance(cache, dict):
        return {
            "session_id": session_id,
            "status": "idle",
            "glb_url": None,
            "job_token": None,
            "error": None,
        }

    snapshot = get_glb_status(cache)
    return {
        "session_id": session_id,
        "status": snapshot.get("status", "idle"),
        "glb_url": snapshot.get("glb_url"),
        "job_token": snapshot.get("job_token"),
        "error": snapshot.get("error"),
    }


@router.post("/upload-heightmap")
async def upload_heightmap(
    heightmap: UploadFile = File(..., description="高度图文件"),
    session_id: str = Form(..., description="Session ID"),
    max_relief_height: float = Form(2.0, description="最大浮雕高度 (mm)"),
    store: SessionStore = Depends(get_session_store),
    registry: FileRegistry = Depends(get_file_registry),
) -> HeightmapUploadResponse:
    """上传高度图并计算基于高度图的 color_height_map。

    根据高度图灰度值和 preview_cache 中的颜色匹配数据，
    计算每个调色板颜色对应区域的平均高度。

    Args:
        heightmap: 高度图图像文件
        session_id: 会话 ID
        max_relief_height: 最大浮雕高度 (mm)
        store: SessionStore 依赖
        registry: FileRegistry 依赖

    Returns:
        HeightmapUploadResponse: 包含 color_height_map 和缩略图 URL
    """
    # 1. Validate session
    session_data = _require_session(store, session_id)

    # 2. Validate preview_cache exists
    cache = _require_preview_cache(session_data)

    # 3. Read uploaded file and save to temp
    temp_path = await ensure_png_tempfile(heightmap)
    store.register_temp_file(session_id, temp_path)

    # 4. Load and validate heightmap using HeightmapLoader
    result = HeightmapLoader.load_and_validate(temp_path)
    if not result["success"]:
        raise HTTPException(
            status_code=422,
            detail=result["error"] or "Invalid heightmap file",
        )

    grayscale: np.ndarray = result["grayscale"]
    original_size: tuple[int, int] = result["original_size"]  # (w, h)
    thumbnail: np.ndarray | None = result["thumbnail"]
    warnings: list[str] = list(result["warnings"])

    # 5. Check aspect ratio vs original image
    matched_rgb: np.ndarray = cache["matched_rgb"]
    target_h, target_w = matched_rgb.shape[:2]
    hm_w, hm_h = original_size

    ar_warning = HeightmapLoader._check_aspect_ratio(hm_w, hm_h, target_w, target_h)
    if ar_warning:
        warnings.append(ar_warning)

    # 6. Resize heightmap to match target dimensions
    grayscale_resized = HeightmapLoader._resize_to_target(grayscale, target_w, target_h)

    # 7. Compute per-color average height from heightmap
    base_thickness: float = PrinterConfig.LAYER_HEIGHT  # 0.08mm
    mask_solid: np.ndarray | None = cache.get("mask_solid")

    color_height_map: dict[str, float] = {}
    palette_data: list[dict] = cache.get("color_palette", [])

    for entry in palette_data:
        color_rgb = np.array(entry["color"], dtype=np.uint8)  # (3,)
        hex_val: str = entry["hex"]  # '#rrggbb'
        hex_key = hex_val.lstrip("#").lower()

        # Find pixels matching this color in matched_rgb
        color_mask = np.all(matched_rgb == color_rgb, axis=2)  # (H, W) bool
        if mask_solid is not None:
            color_mask = color_mask & mask_solid

        if not np.any(color_mask):
            # No pixels for this color, assign base thickness
            color_height_map[hex_key] = base_thickness
            continue

        # Average grayscale value at matching pixel positions
        avg_gray = float(np.mean(grayscale_resized[color_mask]))

        # Map to height range [base_thickness, max_relief_height]
        height = max_relief_height - (avg_gray / 255.0) * (max_relief_height - base_thickness)
        color_height_map[hex_key] = round(height, 4)

    # 8. Store heightmap data in session
    store.put(session_id, "heightmap_grayscale", grayscale_resized)
    store.put(session_id, "heightmap_original_size", original_size)
    store.put(session_id, "heightmap_max_relief_height", max_relief_height)
    store.put(session_id, "heightmap_color_height_map", color_height_map)

    # 9. Register thumbnail in FileRegistry
    thumbnail_url = ""
    if thumbnail is not None:
        thumb_bytes = ndarray_to_png_bytes(thumbnail)
        thumb_id = registry.register_bytes(session_id, thumb_bytes, "heightmap_thumb.png")
        thumbnail_url = f"/api/files/{thumb_id}"

    return HeightmapUploadResponse(
        status="ok",
        message="Heightmap uploaded and processed",
        thumbnail_url=thumbnail_url,
        original_size=original_size,
        color_height_map=color_height_map,
        warnings=warnings,
    )
