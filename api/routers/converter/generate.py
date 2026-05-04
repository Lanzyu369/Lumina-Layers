"""Converter router generate module."""

from __future__ import annotations

import asyncio
import math
import os
import pickle
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
from core.recipe_order import convert_recipe_between_orders
from core.vector_large_format import (
    SVG_LARGE_FORMAT_DENSITY_REDUCED_WARNING,
    SVG_LARGE_FORMAT_GENERATE_FALLBACK_WARNING,
    choose_svg_raster_fallback_density,
    format_large_format_tile_label,
    inspect_svg_large_format_support,
    normalize_large_format_source_basename,
)
from utils.lut_manager import LUTManager

from .common import (
    BATCH_DOWNLOAD_TTL_SECONDS,
    ROUTER_HANDLED_ERRORS,
    _require_preview_cache,
    _require_session,
    _resolve_material_backing_index,
)

router = APIRouter()
log = get_logger(__name__)


class _GenerateBody(BaseModel):
    """Wrapper combining session_id with generate parameters."""

    session_id: str
    params: ConvertGenerateRequest


def _remove_temp_path(path: str | None) -> None:
    """Best-effort delete for route-owned temporary files."""

    if not path:
        return
    try:
        if os.path.exists(path):
            os.unlink(path)
    except OSError:
        pass


def _remove_temp_paths(paths: list[str] | set[str]) -> None:
    """Best-effort delete for multiple route-owned temporary files."""

    for path in paths:
        _remove_temp_path(path)


def _normalize_recipe_overrides(recipe_overrides: object | None) -> list[dict[str, object]] | None:
    """Normalize recipe overrides into per-region dict items.
    将配方覆盖归一化为按单区域展开的字典条目。
    """

    if recipe_overrides is None:
        return None

    normalized: list[dict[str, object]] = []
    for item in recipe_overrides:
        if isinstance(item, dict):
            item_data = item
        else:
            item_data = {
                "region_id": getattr(item, "region_id", None),
                "region_ids": getattr(item, "region_ids", None),
                "recipe": getattr(item, "recipe", None),
                "layer_order": getattr(item, "layer_order", None),
                "virtual_materials": getattr(item, "virtual_materials", None),
            }

        region_id = item_data.get("region_id")
        region_ids = item_data.get("region_ids")
        recipe = item_data.get("recipe")
        layer_order = item_data.get("layer_order")
        # Preserve virtual_materials through normalization so the worker can
        # extend the pipeline palette with the user's declared extra colours.
        # 透传 virtual_materials，让 worker 能把用户声明的额外颜色合并进管线
        # 调色板里（preview_colors / slot_names）。
        raw_virtuals = item_data.get("virtual_materials")
        virtuals_payload: list[dict[str, str]] | None = None
        if raw_virtuals:
            accumulated: list[dict[str, str]] = []
            for vm in raw_virtuals:
                if isinstance(vm, dict):
                    name = vm.get("name")
                    hex_value = vm.get("hex")
                else:
                    name = getattr(vm, "name", None)
                    hex_value = getattr(vm, "hex", None)
                if name and hex_value:
                    accumulated.append(
                        {"name": str(name), "hex": str(hex_value)}
                    )
            virtuals_payload = accumulated or None

        expanded_region_ids: list[str] = []
        if isinstance(region_id, str) and region_id:
            expanded_region_ids.append(region_id)
        elif isinstance(region_ids, list):
            expanded_region_ids.extend(str(value) for value in region_ids if value)

        if not expanded_region_ids or recipe is None:
            continue

        recipe_values = [int(value) for value in recipe]
        if not recipe_values:
            continue

        for expanded_region_id in expanded_region_ids:
            payload: dict[str, object] = {
                "region_id": expanded_region_id,
                "recipe": list(recipe_values),
                "layer_order": str(layer_order or "Top2Bottom"),
            }
            if virtuals_payload:
                payload["virtual_materials"] = [
                    dict(entry) for entry in virtuals_payload
                ]
            normalized.append(payload)

    return normalized or None


def _rgba_to_hex(value: object) -> str | None:
    try:
        arr = np.asarray(value, dtype=np.uint8).reshape(-1)
    except (TypeError, ValueError):
        return None
    if arr.shape[0] < 3:
        return None
    return f"#{int(arr[0]):02X}{int(arr[1]):02X}{int(arr[2]):02X}"


def _native_palette_length_for_virtual_recovery(
    session_data: dict,
    cache: dict,
) -> int:
    """Return the native channel count before preview-cache virtuals.

    LUT sessions normally get this from ``lut_metadata.palette``. Material
    archives do not carry LUT metadata into generation, so their selected
    material count is the native channel count and virtual recipe channels
    start after it.

    LUT 会话通常从 ``lut_metadata.palette`` 取原生通道数。耗材档案生成时
    没有 LUT metadata，因此已选耗材数量就是原生通道数，虚拟配方通道从
    其后开始。
    """
    lut_metadata = cache.get("lut_metadata")
    native_palette = getattr(lut_metadata, "palette", None)
    if native_palette:
        return len(native_palette)

    if str(session_data.get("material_source") or "lut") == "material_archive":
        selected_materials = session_data.get("selected_materials") or []
        if isinstance(selected_materials, (list, tuple)) and selected_materials:
            return len(selected_materials)

    return 0


def _recover_virtual_materials_from_preview_cache(
    session_data: dict,
    recipe: list[int],
) -> list[dict[str, str]] | None:
    """Recover missing virtual material declarations from preview cache.

    ``apply-recipe-override`` extends ``preview_cache`` with virtual entries.
    If a stale client later sends only recipe indices, rebuild the local
    ``virtual_materials`` list so worker generation can extend its palette.

    ``apply-recipe-override`` 会把虚拟耗材写入 preview_cache。若旧前端后续
    只发送 recipe 索引，这里从 cache 重建 virtual_materials，避免 worker
    看到虚拟通道索引却没有对应调色板。
    """
    if not recipe:
        return None
    cache = session_data.get("preview_cache") or {}
    if not isinstance(cache, dict):
        return None

    native_count = _native_palette_length_for_virtual_recovery(session_data, cache)
    if native_count <= 0:
        return None
    virtual_indices = sorted({int(ch) for ch in recipe if int(ch) >= native_count})
    if not virtual_indices:
        return None

    max_offset = max(index - native_count for index in virtual_indices)
    slot_names_src = cache.get("slot_names")
    slot_names = (
        list(slot_names_src)
        if isinstance(slot_names_src, (list, tuple))
        else list((cache.get("color_conf") or {}).get("slots") or [])
    )
    preview_colors = cache.get("preview_colors")
    if not isinstance(preview_colors, dict):
        preview_colors = (cache.get("color_conf") or {}).get("preview") or {}

    recovered: list[dict[str, str]] = []
    for offset in range(max_offset + 1):
        global_index = native_count + offset
        name = (
            str(slot_names[global_index])
            if global_index < len(slot_names) and slot_names[global_index]
            else f"Virtual_{offset}"
        )
        rgba = preview_colors.get(global_index)
        if rgba is None and global_index < len(slot_names):
            rgba = preview_colors.get(slot_names[global_index])
        hex_value = _rgba_to_hex(rgba) if rgba is not None else None
        recovered.append({"name": name, "hex": hex_value or "#808080"})

    return recovered or None


def _backfill_recipe_override_virtual_materials(
    session_data: dict,
    recipe_overrides: list[dict[str, object]] | None,
) -> list[dict[str, object]] | None:
    if not recipe_overrides:
        return recipe_overrides
    for item in recipe_overrides:
        if item.get("virtual_materials"):
            continue
        recipe = item.get("recipe")
        if not isinstance(recipe, list):
            continue
        recovered = _recover_virtual_materials_from_preview_cache(
            session_data,
            [int(value) for value in recipe],
        )
        if recovered:
            item["virtual_materials"] = recovered
    return recipe_overrides


def _resolve_session_material_backing_index(
    session_data: dict,
    request: ConvertGenerateRequest,
) -> int:
    selected_materials = session_data.get("selected_materials") or []
    requested_index = (
        request.material_backing_material_index
        if request.material_backing_material_index is not None
        else session_data.get("material_backing_material_index")
    )
    return _resolve_material_backing_index(selected_materials, requested_index)


def _resolve_recipe_overrides(
    session_data: dict,
    request: ConvertGenerateRequest,
) -> list[dict[str, object]] | None:
    """Resolve effective recipe overrides from session state and request body.

    When the request body provides non-empty ``recipe_overrides``, it is the
    source of truth for recipes / layer_order. However, older clients (and
    any caller that merely round-trips ``{region_id, recipe, layer_order}``
    without carrying the virtual-material tail) may drop the
    ``virtual_materials`` declared at apply time. The apply endpoint persists
    per-region ``virtual_materials`` into ``session_data["recipe_overrides"]``
    so the generate pipeline can rebuild the extended palette in a fresh
    worker process. To keep the virtual palette extension alive across a
    stale client, this resolver backfills ``virtual_materials`` from the
    session by ``region_id`` whenever the request body leaves them unset for
    that region — without ever overriding ``virtual_materials`` the request
    explicitly provides.

    Empty request arrays are treated like "not supplied" when the session
    already has applied overrides. The frontend can briefly send
    ``recipe_overrides: []`` from stale local state after the apply endpoint
    has updated the backend session; letting that empty array clear the
    session makes the 3MF generation silently ignore the custom recipe.

    当请求体带了非空 ``recipe_overrides`` 时它是 recipe / layer_order 的事实
    来源；但旧前端 / 第三方调用方可能只回传
    ``{region_id, recipe, layer_order}``，把 apply 时声明的
    ``virtual_materials`` 丢掉。apply 端点把每个 region 的
    ``virtual_materials`` 一并持久化进 session，保证 worker 进程可以重建
    扩展调色板；这里按 ``region_id`` 从 session 回补缺失的
    ``virtual_materials``，同时绝不覆盖请求体显式给出的 virtuals。

    空数组请求在 session 已有已应用配方时按"未提供"处理。前端局部状态
    可能在 apply 成功后仍短暂发出 ``recipe_overrides: []``；如果让这个空
    数组清掉 session，最终 3MF 会静默忽略用户刚应用的自定义配方。
    """

    session_overrides = _normalize_recipe_overrides(session_data.get("recipe_overrides") or None)
    if request.recipe_overrides is None:
        return _backfill_recipe_override_virtual_materials(
            session_data,
            session_overrides,
        )

    request_overrides = _normalize_recipe_overrides(request.recipe_overrides)
    if not request_overrides:
        return _backfill_recipe_override_virtual_materials(
            session_data,
            session_overrides,
        )

    if not session_overrides:
        return _backfill_recipe_override_virtual_materials(
            session_data,
            request_overrides,
        )

    session_virtuals_by_region: dict[str, list[dict[str, str]]] = {}
    for session_item in session_overrides:
        region_id = session_item.get("region_id")
        virtuals = session_item.get("virtual_materials")
        if isinstance(region_id, str) and region_id and virtuals:
            session_virtuals_by_region[region_id] = [
                dict(entry) for entry in virtuals  # type: ignore[arg-type]
            ]

    for item in request_overrides:
        if item.get("virtual_materials"):
            continue
        region_id = item.get("region_id")
        if not isinstance(region_id, str):
            continue
        backfill = session_virtuals_by_region.get(region_id)
        if backfill:
            item["virtual_materials"] = [dict(entry) for entry in backfill]

    return _backfill_recipe_override_virtual_materials(
        session_data,
        request_overrides,
    )


def _prepare_recipe_override_worker_inputs(
    *,
    cache: dict,
    session_data: dict,
    recipe_overrides: list[dict[str, object]] | None,
    request: ConvertGenerateRequest,
    sid: str,
    store: SessionStore,
) -> tuple[str | None, str | None]:
    """Serialize recipe-override artifacts required by the worker pipeline."""

    if not recipe_overrides:
        return None, None

    cached_material_matrix = cache.get("material_matrix")
    region_masks = session_data.get("selected_region_masks") or {}
    lut_metadata = cache.get("lut_metadata")
    if cached_material_matrix is None:
        raise HTTPException(status_code=409, detail="Preview cache missing material_matrix")
    if not isinstance(region_masks, dict):
        region_masks = {}

    material_matrix_override = np.asarray(cached_material_matrix).copy()
    current_layers = int(material_matrix_override.shape[2]) if material_matrix_override.ndim == 3 else 0
    target_layers = int(request.color_layers or current_layers)
    metadata_order = getattr(lut_metadata, "layer_order", "Top2Bottom")
    base_channel_idx = int(getattr(lut_metadata, "base_channel_idx", 0))

    if target_layers > current_layers and material_matrix_override.ndim == 3:
        # Pad the grown layers so that:
        #   (a) ``~mask_solid`` (transparent background — p03 has already
        #       marked it as ``-1``) stays as ``-1`` air, otherwise S07
        #       emits a ring-shaped White mesh around the model ("透明通道
        #       失效 / 整块白矩形包裹" regression).
        #   (b) ``mask_solid`` non-override pixels keep the LUT base channel
        #       so the extended column stays continuous with the backing
        #       slab; padding them with ``-1`` leaves the user's 6th layer
        #       visually empty ("第 6 层空层" regression).
        # The override region is overwritten below with ``recipe_full``.
        # 扩展层要同时兼顾两件事：(a) mask_solid 外的透明背景保持 -1 空气，
        # 避免 S07 围着模型生成一圈白色 mesh；(b) mask_solid 内非 override
        # 像素保留 base channel，避免第 6 层塌成空层。
        cached_mask_solid = cache.get("mask_solid")
        if cached_mask_solid is None:
            raise HTTPException(
                status_code=409,
                detail="Preview cache missing mask_solid; re-run preview before generating with recipe overrides.",
            )
        mask_solid_arr = np.asarray(cached_mask_solid, dtype=bool)
        if mask_solid_arr.shape != material_matrix_override.shape[:2]:
            raise HTTPException(
                status_code=409,
                detail=(
                    "mask_solid shape does not match material_matrix; "
                    "re-run preview before generating with recipe overrides."
                ),
            )
        # uint dtypes would wrap ``-1`` into ``255`` and reintroduce the bug
        # under a different channel id; promote to signed first.
        # uint 类型会把 -1 绕回 255 把同一个 bug 换个编号复现，先升到 signed。
        if np.issubdtype(material_matrix_override.dtype, np.unsignedinteger):
            material_matrix_override = material_matrix_override.astype(np.int32)
        pad_slab = np.full(
            (
                material_matrix_override.shape[0],
                material_matrix_override.shape[1],
                target_layers - current_layers,
            ),
            -1,
            dtype=material_matrix_override.dtype,
        )
        pad_slab[mask_solid_arr] = base_channel_idx
        if metadata_order == "Top2Bottom":
            material_matrix_override = np.concatenate([material_matrix_override, pad_slab], axis=2)
        else:
            material_matrix_override = np.concatenate([pad_slab, material_matrix_override], axis=2)
    elif target_layers < current_layers:
        raise HTTPException(
            status_code=422,
            detail="Recipe overrides cannot reduce the current optical layer count",
        )

    for item in recipe_overrides:
        region_id = item["region_id"]
        item_recipe = item["recipe"]
        item_layer_order = item["layer_order"]
        region_mask = region_masks.get(region_id)
        if region_mask is None:
            raise HTTPException(
                status_code=422,
                detail=f"Region mask not found for recipe override: {region_id}",
            )
        recipe = convert_recipe_between_orders(
            list(item_recipe),
            item_layer_order,
            metadata_order,
        )
        if len(recipe) < target_layers:
            pad_count = target_layers - len(recipe)
            if metadata_order == "Top2Bottom":
                recipe = recipe + [base_channel_idx] * pad_count
            else:
                recipe = [base_channel_idx] * pad_count + recipe
        elif len(recipe) > target_layers:
            raise HTTPException(
                status_code=422,
                detail=f"Recipe override has {len(recipe)} layers but target mode is {target_layers}",
            )
        material_matrix_override[np.asarray(region_mask, dtype=bool)] = np.asarray(
            recipe,
            dtype=material_matrix_override.dtype,
        )

    fd, mm_temp_path = tempfile.mkstemp(suffix=".npy", dir=TEMP_DIR)
    os.close(fd)
    np.save(mm_temp_path, material_matrix_override)
    store.register_temp_file(sid, mm_temp_path)

    recipe_override_masks_path: str | None = None
    if isinstance(region_masks, dict):
        selected_masks = {
            item["region_id"]: region_masks[item["region_id"]]
            for item in recipe_overrides
            if item["region_id"] in region_masks
        }
        if selected_masks:
            fd, masks_temp_path = tempfile.mkstemp(suffix=".pkl", dir=TEMP_DIR)
            os.close(fd)
            with open(masks_temp_path, "wb") as f:
                pickle.dump(selected_masks, f)
            recipe_override_masks_path = masks_temp_path
            store.register_temp_file(sid, masks_temp_path)

    return mm_temp_path, recipe_override_masks_path


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
    session_material_source = session_data.get("material_source", "lut")
    if not image_path or not os.path.exists(image_path):
        raise HTTPException(status_code=409, detail="Image file missing. Call POST /api/convert/preview first.")
    if session_material_source != "material_archive":
        if not lut_path or not os.path.exists(lut_path):
            raise HTTPException(status_code=409, detail="LUT file missing. Call POST /api/convert/preview first.")
    else:
        lut_path = "__material_archive__"

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
    recipe_overrides = _resolve_recipe_overrides(session_data, request)

    free_color_set = session_data.get("free_color_set") or None
    if request.free_color_set is not None:
        free_color_set = request.free_color_set

    # Convert API ModelingMode enum to core ModelingMode enum
    core_modeling_mode = CoreModelingMode(request.modeling_mode.value)

    # Resolve height_mode for relief branching
    # 解析 height_mode 用于浮雕分支选择
    height_mode = request.height_mode or "color"
    _require_heightmap_for_relief(session_data, request)

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
    mask_solid_path: str | None = None
    material_matrix_path: str | None = None
    log.debug(
        "Cached matched RGB input state resolved: use_cached_matched_rgb=%s, has_replacement_regions=%s",
        request.use_cached_matched_rgb,
        bool(replacement_regions),
        extra={
            "event": "converter_generate_cached_input_state",
            "use_cached_matched_rgb": request.use_cached_matched_rgb,
            "has_replacement_regions": bool(replacement_regions),
        },
    )
    if request.use_cached_matched_rgb:
        cached_matched_rgb = cache.get("matched_rgb")
        if cached_matched_rgb is not None:
            fd, mr_temp_path = tempfile.mkstemp(suffix=".npy", dir=TEMP_DIR)
            os.close(fd)
            np.save(mr_temp_path, cached_matched_rgb)
            matched_rgb_path = mr_temp_path
            store.register_temp_file(body.session_id, mr_temp_path)
            log.debug(
                "Cached matched RGB saved for worker: shape=%s, dtype=%s",
                cached_matched_rgb.shape,
                cached_matched_rgb.dtype,
                extra={
                    "event": "converter_generate_cached_matched_rgb_saved",
                    "matched_rgb_shape": list(cached_matched_rgb.shape),
                    "matched_rgb_dtype": str(cached_matched_rgb.dtype),
                },
            )

            # Forward mask_solid alongside matched_rgb so the SVG-native
            # vector branch can intersect each shape mask with the solid
            # area when projecting region edits back into matched_shapes.
            # Without this the vector 3MF stays on the SVG fill colour and
            # silently drops every /region-replace mutation.
            # 把 mask_solid 与 matched_rgb 一起透传给 worker，让矢量分支
            # 可以在求交后回写颜色；不传就会丢掉用户的区域替换。
            cached_mask_solid = cache.get("mask_solid")
            if cached_mask_solid is not None:
                fd, ms_temp_path = tempfile.mkstemp(suffix=".npy", dir=TEMP_DIR)
                os.close(fd)
                np.save(ms_temp_path, cached_mask_solid)
                mask_solid_path = ms_temp_path
                store.register_temp_file(body.session_id, ms_temp_path)

    material_matrix_path, recipe_override_masks_path = _prepare_recipe_override_worker_inputs(
        cache=cache,
        session_data=session_data,
        recipe_overrides=recipe_overrides,
        request=request,
        sid=body.session_id,
        store=store,
    )

    # 2b. Collect scalar parameters into a dict for the worker
    params: dict = {
        "target_width_mm": request.target_width_mm,
        "spacer_thick": request.spacer_thick,
        "structure_mode": request.structure_mode.value,
        "color_mode": request.color_mode.value,
        "color_layers": request.color_layers,
        "layer_height_mm": request.layer_height_mm,
        "model_enable": request.model_enable,
        "model_only": request.model_only,
        "model_threshold": request.model_threshold,
        "model_margin": request.model_margin,
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
        "recipe_overrides": (
            [
                {
                    "region_id": item["region_id"],
                    "recipe": list(item["recipe"]),
                    "layer_order": item["layer_order"],
                    # Forward the per-region virtual materials to the worker
                    # so the pipeline can rebuild the extended palette inside
                    # the CPU-offloaded process.
                    # 把 per-region 的虚拟耗材一起传给 worker，方便在 CPU 进程
                    # 里重建扩展调色板。
                    **(
                        {
                            "virtual_materials": [
                                dict(vm) for vm in item["virtual_materials"]
                            ]
                        }
                        if item.get("virtual_materials")
                        else {}
                    ),
                }
                for item in recipe_overrides
            ]
            if recipe_overrides is not None
            else None
        ),
        "recipe_override_masks_path": recipe_override_masks_path,
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
        "mask_solid_path": mask_solid_path,
        "material_matrix_path": material_matrix_path,
        "printer_id": request.printer_id,
        "slicer": request.slicer,
        "nozzle_size": request.nozzle_size,
        "enable_base_layer_height_modifier": request.enable_base_layer_height_modifier,
        "material_source": session_material_source,
    }
    if session_material_source == "material_archive":
        selected_materials = session_data.get("selected_materials") or []
        params["selected_materials"] = selected_materials
        params["material_layer_count"] = session_data.get("material_layer_count")
        params["material_layer_height_mm"] = session_data.get("material_layer_height_mm")
        # Plumb the opt-in exhaustive-cache grid_resolution from preview time
        # so the 3MF generation path hits the same cache file the user built
        # in the dialog. ``None`` keeps the backend's low-tier default.
        # 把预览阶段确定的穷举缓存网格分辨率透传过来，让 3MF 生成命中用户
        # 在弹窗里实际构建的那份缓存文件。``None`` 表示走低档默认。
        params["material_grid_resolution"] = session_data.get(
            "material_grid_resolution"
        )
        params["material_backing_material_index"] = _resolve_session_material_backing_index(
            session_data,
            request,
        )

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
    download_id = registry.register_path(
        str(uuid.uuid4()),
        threemf_path,
        ttl_seconds=BATCH_DOWNLOAD_TTL_SECONDS,
    )

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


def _require_heightmap_for_relief(session_data: dict, request) -> None:
    """Reject heightmap relief generation when the session heightmap cache is gone.

    拒绝缺少 session 高度图缓存的高度图浮雕生成，避免静默退回平面模型。
    """
    if not request.enable_relief:
        return
    if (request.height_mode or "color") != "heightmap":
        return
    if session_data.get("heightmap_grayscale") is None:
        raise HTTPException(
            status_code=409,
            detail="Heightmap missing. Upload heightmap before generating relief models.",
        )


def _resolve_large_format_shared_params(
    session_data: dict,
    request,
    relief_global_max_height: float | None,
    *,
    recipe_overrides: list[dict[str, object]] | None = None,
    recipe_override_masks_path: str | None = None,
    material_matrix_path: str | None = None,
) -> dict:
    replacement_regions = session_data.get("replacement_regions") or None
    if request.replacement_regions is not None:
        replacement_regions = [
            {"quantized_hex": r.quantized_hex, "matched_hex": r.matched_hex, "replacement_hex": r.replacement_hex}
            for r in request.replacement_regions
        ]
    free_color_set = session_data.get("free_color_set") or None
    if request.free_color_set is not None:
        free_color_set = request.free_color_set

    params = {
        "spacer_thick": request.spacer_thick,
        "structure_mode": request.structure_mode.value,
        "color_mode": request.color_mode.value,
        "color_layers": request.color_layers,
        "layer_height_mm": request.layer_height_mm,
        "model_enable": request.model_enable,
        "model_only": request.model_only,
        "model_threshold": request.model_threshold,
        "model_margin": request.model_margin,
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
        "recipe_overrides": (
            [
                {
                    "region_id": item["region_id"],
                    "recipe": list(item["recipe"]),
                    "layer_order": item["layer_order"],
                    # Forward the per-region virtual materials to the worker
                    # so the pipeline can rebuild the extended palette inside
                    # the CPU-offloaded process.
                    # 把 per-region 的虚拟耗材一起传给 worker，方便在 CPU 进程
                    # 里重建扩展调色板。
                    **(
                        {
                            "virtual_materials": [
                                dict(vm) for vm in item["virtual_materials"]
                            ]
                        }
                        if item.get("virtual_materials")
                        else {}
                    ),
                }
                for item in recipe_overrides
            ]
            if recipe_overrides is not None
            else None
        ),
        "recipe_override_masks_path": recipe_override_masks_path,
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
        "material_matrix_path": material_matrix_path,
        "printer_id": request.printer_id,
        "slicer": request.slicer,
        "nozzle_size": request.nozzle_size,
        "enable_base_layer_height_modifier": request.enable_base_layer_height_modifier,
        "relief_global_max_height": relief_global_max_height,
    }
    if str(session_data.get("material_source") or "lut") == "material_archive":
        params["material_source"] = "material_archive"
        params["selected_materials"] = session_data.get("selected_materials") or []
        params["material_layer_count"] = session_data.get("material_layer_count")
        params["material_layer_height_mm"] = session_data.get("material_layer_height_mm")
        params["material_grid_resolution"] = session_data.get(
            "material_grid_resolution"
        )
        resolved_backing_idx = _resolve_session_material_backing_index(
            session_data,
            request,
        )
        params["material_backing_material_index"] = resolved_backing_idx
        # Surface the backing slot index as backing_color_id for the tile
        # worker so the Board geometry is assigned to the user-selected
        # material slot instead of the hardcoded slot 0.
        # 将底板槽位索引作为 backing_color_id 透传给 tile worker，
        # 避免大幅面导出仍把底板硬编码成第一条耗材。
        params["backing_color_id"] = int(resolved_backing_idx or 0)
    return params


def _resolve_large_format_source_basename(session_data: dict, image_path: str) -> str:
    source_basename = normalize_large_format_source_basename(session_data.get("source_basename"))
    if source_basename:
        return source_basename
    return normalize_large_format_source_basename(os.path.splitext(os.path.basename(image_path))[0])


async def _generate_large_format_svg_native(
    *,
    image_path: str,
    lut_path: str,
    source_basename: str,
    recipe_overrides: list[dict[str, object]] | None,
    recipe_override_masks_path: str | None,
    material_matrix_path: str | None,
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
        recipe_overrides=recipe_overrides,
        recipe_override_masks_path=recipe_override_masks_path,
        material_matrix_path=material_matrix_path,
    )
    try:
        result = await pool.submit(
            worker_generate_large_format_svg_native,
            image_path,
            lut_path,
            {
                **shared_params,
                "tile_name_prefix": source_basename,
                "total_width_mm": total_width_mm,
                "total_height_mm": total_height_mm,
                "tile_width_mm": tile_width_mm,
                "tile_height_mm": tile_height_mm,
            },
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Large-format SVG generation timed out")
    except ROUTER_HANDLED_ERRORS as e:
        raise HTTPException(status_code=500, detail=f"Large-format SVG generation failed: {str(e)}")
    zip_path = result["zip_path"]
    download_id = registry.register_path(
        str(uuid.uuid4()),
        zip_path,
        ttl_seconds=BATCH_DOWNLOAD_TTL_SECONDS,
    )
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
    source_basename: str,
    recipe_overrides: list[dict[str, object]] | None,
    recipe_override_masks_path: str | None,
    material_matrix_path: str | None,
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

    successful_paths: list[tuple[str, str]] = []
    route_local_cleanup_paths: set[str] = set()
    cleanup_paths: set[str] = set()
    errors: list[str] = []
    zip_path: str | None = None
    zip_ready = False
    full_material_matrix: np.ndarray | None = None
    full_recipe_override_masks: dict[str, np.ndarray] | None = None
    override_target_w = 0
    override_target_h = 0
    if recipe_overrides and material_matrix_path is not None:
        try:
            full_material_matrix = np.load(material_matrix_path)
        except (OSError, ValueError, TypeError) as exc:
            raise HTTPException(status_code=500, detail=f"Failed to load large-format recipe override matrix: {exc}")
        if full_material_matrix.ndim != 3:
            raise HTTPException(status_code=500, detail="Large-format recipe override matrix must be 3-dimensional")
        override_target_h, override_target_w = full_material_matrix.shape[:2]
        if recipe_override_masks_path is not None:
            try:
                with open(recipe_override_masks_path, "rb") as f:
                    loaded_masks = pickle.load(f)
            except (OSError, ValueError, TypeError, pickle.PickleError) as exc:
                raise HTTPException(status_code=500, detail=f"Failed to load large-format recipe override masks: {exc}")
            if isinstance(loaded_masks, dict):
                full_recipe_override_masks = {
                    str(region_id): np.asarray(mask, dtype=bool)
                    for region_id, mask in loaded_masks.items()
                }

    px_per_mm_x = px_w / total_width_mm
    px_per_mm_y = px_h / total_height_mm
    cols = max(1, math.ceil(total_width_mm / tile_width_mm))
    rows = max(1, math.ceil(total_height_mm / tile_height_mm))
    shared_params = _resolve_large_format_shared_params(
        session_data,
        request,
        _resolve_relief_global_max_height(session_data, request),
        recipe_overrides=recipe_overrides,
        recipe_override_masks_path=recipe_override_masks_path,
        material_matrix_path=material_matrix_path,
    )
    if str(image_path).lower().endswith(".png") and shared_params["modeling_mode"] == CoreModelingMode.VECTOR:
        shared_params["modeling_mode"] = CoreModelingMode.HIGH_FIDELITY
    hm_gray = (
        session_data.get("heightmap_grayscale")
        if (request.enable_relief and (request.height_mode or "color") == "heightmap")
        else None
    )

    try:
        futures = []
        tile_labels: list[str] = []
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
                route_local_cleanup_paths.add(tile_path)

                tile_params = dict(shared_params, target_width_mm=cur_tile_w)
                if hm_gray is not None:
                    hm_tile = hm_gray[px_y0:px_y1, px_x0:px_x1]
                    fd2, hm_tile_path = tempfile.mkstemp(suffix=".png", dir=TEMP_DIR)
                    os.close(fd2)
                    Image.fromarray(hm_tile).save(hm_tile_path)
                    route_local_cleanup_paths.add(hm_tile_path)
                    tile_params["heightmap_path"] = hm_tile_path
                if full_material_matrix is not None and override_target_w > 0 and override_target_h > 0:
                    ov_x0 = int(round(x0_mm * (override_target_w / total_width_mm)))
                    ov_y0 = int(round(y0_mm * (override_target_h / total_height_mm)))
                    ov_x1 = min(int(round(x1_mm * (override_target_w / total_width_mm))), override_target_w)
                    ov_y1 = min(int(round(y1_mm * (override_target_h / total_height_mm))), override_target_h)
                    material_matrix_tile = full_material_matrix[ov_y0:ov_y1, ov_x0:ov_x1, :]
                    fd_mm, mm_tile_path = tempfile.mkstemp(suffix=".npy", dir=TEMP_DIR)
                    os.close(fd_mm)
                    np.save(mm_tile_path, material_matrix_tile)
                    route_local_cleanup_paths.add(mm_tile_path)
                    tile_params["material_matrix_path"] = mm_tile_path
                    tile_params["recipe_override_masks_path"] = None

                    selected_mask_tiles: dict[str, np.ndarray] = {}
                    for region_id, mask in (full_recipe_override_masks or {}).items():
                        if mask.shape != (override_target_h, override_target_w):
                            continue
                        mask_tile = mask[ov_y0:ov_y1, ov_x0:ov_x1]
                        if mask_tile.any():
                            selected_mask_tiles[region_id] = mask_tile
                    if selected_mask_tiles:
                        fd_masks, masks_tile_path = tempfile.mkstemp(suffix=".pkl", dir=TEMP_DIR)
                        os.close(fd_masks)
                        with open(masks_tile_path, "wb") as f:
                            pickle.dump(selected_mask_tiles, f)
                        route_local_cleanup_paths.add(masks_tile_path)
                        tile_params["recipe_override_masks_path"] = masks_tile_path

                label = format_large_format_tile_label(
                    source_basename=source_basename,
                    tile_label=f"R{r + 1}C{c + 1}",
                )
                tile_labels.append(label)
                futures.append(pool.submit(worker_generate_model, tile_path, lut_path, tile_params))

        for label, fut in zip(tile_labels, futures):
            try:
                result = await fut
                glb_path = result.get("glb_path")
                if glb_path and os.path.exists(glb_path):
                    cleanup_paths.add(glb_path)

                tp = result.get("threemf_path")
                if tp and os.path.exists(tp):
                    successful_paths.append((label, tp))
                    cleanup_paths.add(tp)
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
        download_id = registry.register_path(
            str(uuid.uuid4()),
            zip_path,
            ttl_seconds=BATCH_DOWNLOAD_TTL_SECONDS,
        )
        zip_ready = True

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
    finally:
        _remove_temp_paths(route_local_cleanup_paths)
        _remove_temp_paths(cleanup_paths)
        if zip_path is not None and not zip_ready:
            _remove_temp_path(zip_path)


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
    session_material_source = session_data.get("material_source", "lut")
    if not image_path or not os.path.exists(image_path):
        raise HTTPException(status_code=409, detail="Image file missing. Call POST /api/convert/preview first.")
    if session_material_source == "material_archive":
        lut_path = "__material_archive__"
    elif not lut_path or not os.path.exists(lut_path):
        raise HTTPException(status_code=409, detail="LUT file missing. Call POST /api/convert/preview first.")
    _require_heightmap_for_relief(session_data, request)

    sid = body.session_id
    total_w_mm, total_h_mm = _resolve_large_format_dimensions(cache, request, lf.target_height_mm)
    source_basename = _resolve_large_format_source_basename(session_data, image_path)
    recipe_overrides = _resolve_recipe_overrides(session_data, request)
    material_matrix_path, recipe_override_masks_path = _prepare_recipe_override_worker_inputs(
        cache=cache,
        session_data=session_data,
        recipe_overrides=recipe_overrides,
        request=request,
        sid=sid,
        store=store,
    )
    tile_w_mm = lf.tile_width_mm
    tile_h_mm = lf.tile_height_mm

    warnings: list[str] = []
    is_svg_vector = str(image_path).lower().endswith(".svg") and request.modeling_mode.value == "vector"
    prefer_raster_svg = bool(recipe_overrides) or session_material_source == "material_archive"
    if is_svg_vector:
        policy = session_data.get("svg_large_format_policy")
        if not isinstance(policy, dict) or policy.get("inspection_source") not in {
            "preview-vector-svg",
            "generate-large-format",
        }:
            policy = {
                **inspect_svg_large_format_support(image_path),
                "inspection_source": "generate-large-format",
            }
            session_data["svg_large_format_policy"] = policy
            store.put(sid, "svg_large_format_policy", policy)
        warnings.extend(list(policy.get("warnings", [])))

        if bool(policy.get("native_tiling_supported", False)) and not prefer_raster_svg:
            result = await _generate_large_format_svg_native(
                image_path=image_path,
                lut_path=lut_path,
                source_basename=source_basename,
                recipe_overrides=recipe_overrides,
                recipe_override_masks_path=recipe_override_masks_path,
                material_matrix_path=material_matrix_path,
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
            fallback_warnings = warnings + [SVG_LARGE_FORMAT_GENERATE_FALLBACK_WARNING]
            if not prefer_raster_svg:
                fallback_warnings += density_warnings
            try:
                result = await _generate_large_format_raster(
                    image_path=fallback_png_path,
                    lut_path=lut_path,
                    source_basename=source_basename,
                    recipe_overrides=recipe_overrides,
                    recipe_override_masks_path=recipe_override_masks_path,
                    material_matrix_path=material_matrix_path,
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
                    warnings=fallback_warnings,
                )
            finally:
                _remove_temp_path(fallback_png_path)
    else:
        result = await _generate_large_format_raster(
            image_path=image_path,
            lut_path=lut_path,
            source_basename=source_basename,
            recipe_overrides=recipe_overrides,
            recipe_override_masks_path=recipe_override_masks_path,
            material_matrix_path=material_matrix_path,
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

    log.info(
        "Large-format conversion generated",
        extra={
            "event": "converter_generate_large_format_done",
            "session_id": body.session_id,
            "total_width_mm": total_w_mm,
            "total_height_mm": total_h_mm,
            "tile_width_mm": lf.tile_width_mm,
            "tile_height_mm": lf.tile_height_mm,
            "is_svg_vector": is_svg_vector,
            "prefer_raster_svg": prefer_raster_svg,
            "recipe_override_count": len(recipe_overrides or []),
            "warning_count": len(result.get("warnings", [])),
        },
    )
    return LargeFormatGenerateResponse(**result)


@router.post("/batch")
async def convert_batch(
    images: list[UploadFile] = File(..., description="批量图像"),
    lut_name: str = Form(..., description="LUT 名称"),
    target_width_mm: float = Form(60.0, description="目标宽度 (mm)"),
    spacer_thick: float = Form(1.2, description="底板厚度 (mm)"),
    structure_mode: str = Form("Double-sided", description="打印结构模式"),
    color_mode: str = Form("4-Color (RYBW)", description="颜色模式"),
    modeling_mode: str = Form("high-fidelity", description="建模模式"),
    color_layers: int | None = Form(None, ge=1, le=20, description="叠色层数"),
    layer_height_mm: float | None = Form(None, gt=0.0, le=1.0, description="叠色层高 (mm)"),
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
    image_count = len(images)
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
        temp_path: str | None = None
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
                color_mode,
                modeling_mode,
                color_layers,
                layer_height_mm,
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
        finally:
            _remove_temp_path(temp_path)

    # Package successful 3MF files into a ZIP (main thread)
    cleanup_3mf_paths = [path_3mf for path_3mf, _src_filename in successful_entries]
    zip_path: str | None = None
    zip_ready = False
    try:
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
        zip_ready = True

        success_count = sum(1 for r in results if r.status == "success")
        total_count = len(results)

        log.info(
            "Batch conversion completed",
            extra={
                "event": "converter_batch_done",
                "image_count": image_count,
                "success_count": success_count,
                "total_count": total_count,
                "lut_name": lut_name,
                "color_mode": color_mode,
                "modeling_mode": modeling_mode,
            },
        )
        return BatchResponse(
            status="ok" if success_count > 0 else "failed",
            message=f"Batch complete: {success_count}/{total_count} succeeded",
            download_url=f"/api/files/{download_id}",
            results=results,
        )
    finally:
        _remove_temp_paths(cleanup_3mf_paths)
        if zip_path is not None and not zip_ready:
            _remove_temp_path(zip_path)
