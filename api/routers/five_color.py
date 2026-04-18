"""Lumina Studio API — Five-Color Query Router.
Lumina Studio API — 五色组合查询路由。

Provides endpoints for querying base colors from a LUT and
performing five-color combination lookups.
提供从 LUT 获取基础颜色和执行五色组合查询的端点。
"""

import threading
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query

from api.dependencies import get_file_registry
from api.file_registry import FileRegistry
from api.schemas.five_color import (
    BaseColorEntry,
    BaseColorsResponse,
    FiveColorQueryRequest,
    FiveColorQueryResponse,
    RecipeSwatchRequest,
    RecipeSwatchResponse,
)
from api.structured_logging import get_request_id
from core.five_color_combination import (
    ColorCountDetector,
    ColorQueryEngine,
    StackFileManager,
    StackLUTLoader,
    rgb_to_hex,
)
from utils.lut_manager import LUTManager

router = APIRouter(prefix="/api/five-color", tags=["Five-Color"])
STATELESS_EXPORT_TTL_SECONDS = 8 * 60 * 60

# ---- LUT Engine 内存缓存 ----
_engine_cache: dict[str, ColorQueryEngine] = {}
_engine_cache_lock = threading.Lock()


def clear_engine_cache():
    """Clear the LUT engine cache.
    清空 LUT 引擎缓存。
    """
    with _engine_cache_lock:
        _engine_cache.clear()
    print("[FIVE_COLOR] Engine cache cleared")


@router.post("/clear-cache")
def clear_cache():
    """Clear the LUT engine cache.
    清空 LUT 引擎缓存，强制重新加载所有 LUT。
    """
    clear_engine_cache()
    return {"success": True, "message": "Cache cleared successfully"}


def _extract_sources_from_keyed_json(json_path: str) -> list[str]:
    """Extract per-entry 'source' fields from a Keyed JSON LUT file.
    从 Keyed JSON LUT 文件中提取每条记录的 source 字段。
    """
    import json as _json
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = _json.load(f)
        entries = data.get("entries", [])
        return [e.get("source", "") if isinstance(e, dict) else "" for e in entries]
    except Exception:
        return []


def _load_engine(lut_name: str) -> tuple[ColorQueryEngine, str]:
    """Load a LUT and create a ColorQueryEngine (with in-memory cache).
    加载 LUT 并创建 ColorQueryEngine（带内存缓存）。

    Args:
        lut_name: LUT 显示名称。

    Returns:
        (engine, lut_display_name)

    Raises:
        HTTPException 404: LUT 不存在。
        HTTPException 400: LUT 格式无法识别。
        HTTPException 500: 加载失败。
    """
    with _engine_cache_lock:
        if lut_name in _engine_cache:
            return _engine_cache[lut_name], lut_name

    path: str | None = LUTManager.get_lut_path(lut_name)
    if path is None:
        raise HTTPException(status_code=404, detail=f"LUT not found: {lut_name}")

    try:
        if path.endswith(".npz"):
            success, msg, stack_data, rgb_data = StackLUTLoader.load_npz_file(path)
            if not success:
                raise HTTPException(status_code=500, detail=f"Failed to load LUT: {msg}")
            sources = StackLUTLoader.load_sources_from_json(path)
            engine = ColorQueryEngine(stack_lut=stack_data, lut_rgb=rgb_data, sources=sources)
        elif path.endswith(".json"):
            # Keyed JSON format — use LUTManager unified loader
            rgb_data, stack_data, metadata = LUTManager.load_lut_with_metadata(path)
            if rgb_data is None or len(rgb_data) == 0:
                raise HTTPException(status_code=500, detail="Failed to load JSON LUT: no RGB data")
            # Use palette names for color_count
            color_count = len(metadata.palette) if metadata.palette else None
            # Extract per-entry sources from JSON
            sources = _extract_sources_from_keyed_json(path)
            engine = ColorQueryEngine(
                stack_lut=stack_data, lut_rgb=rgb_data, color_count=color_count,
                sources=sources,
            )
            # Override base_colors from palette hex_color
            if metadata.palette:
                engine._palette_names = [e.color for e in metadata.palette]
                base_from_palette = []
                for e in metadata.palette:
                    if e.hex_color:
                        h = e.hex_color.lstrip("#")
                        if len(h) == 6:
                            base_from_palette.append((int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)))
                        else:
                            base_from_palette.append((128, 128, 128))
                    else:
                        base_from_palette.append((128, 128, 128))
                engine.base_colors = base_from_palette
        else:
            # .npy file
            success, msg, rgb_data = StackLUTLoader.load_lut_rgb(path)
            if not success:
                raise HTTPException(status_code=500, detail=f"Failed to load LUT: {msg}")

            color_count, combination_count = ColorCountDetector.detect_color_count(rgb_data)
            if color_count == 0:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unrecognized LUT format: {combination_count} combinations",
                )

            stack_path = StackFileManager.find_stack_file(color_count)
            stack_data = None
            if stack_path is not None:
                ok, _, loaded_stack = StackLUTLoader.load_stack_lut(stack_path)
                if ok:
                    stack_data = loaded_stack

            engine = ColorQueryEngine(
                stack_lut=stack_data, lut_rgb=rgb_data, color_count=color_count,
                sources=StackLUTLoader.load_sources_from_json(path)
            )

        with _engine_cache_lock:
            _engine_cache[lut_name] = engine

        return engine, lut_name

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to load LUT: {exc}"
        ) from exc


@router.get("/base-colors")
def get_base_colors(lut_name: str = Query(..., description="LUT 显示名称")) -> BaseColorsResponse:
    """Return the base colors of a LUT.
    返回指定 LUT 的基础颜色列表。
    """
    engine, display_name = _load_engine(lut_name)
    base_colors = engine.get_base_colors()
    color_names = engine.get_color_names()

    colors: list[BaseColorEntry] = [
        BaseColorEntry(
            index=i,
            rgb=rgb,
            name=color_names[i] if i < len(color_names) else "",
            hex=rgb_to_hex(rgb),
        )
        for i, rgb in enumerate(base_colors)
    ]

    combinations = engine.stack_lut.tolist() if engine.stack_lut is not None else None
    
    # Debug logging
    if engine.stack_lut is not None:
        print(f"[DEBUG] Returning {len(engine.stack_lut)} combinations for {lut_name}")
    else:
        print(f"[DEBUG] WARNING: stack_lut is None for {lut_name}")

    return BaseColorsResponse(
        lut_name=display_name,
        color_count=len(colors),
        colors=colors,
        combinations=combinations,
    )


@router.post("/query")
def query_five_color(request: FiveColorQueryRequest) -> FiveColorQueryResponse:
    """Query a five-color combination result.
    查询五色组合结果。
    """
    engine, _ = _load_engine(request.lut_name)

    # Validate index range
    for idx in request.selected_indices:
        if idx < 0 or idx >= engine.color_count:
            raise HTTPException(
                status_code=400,
                detail=f"Index {idx} out of range [0, {engine.color_count})",
            )

    result = engine.query(request.selected_indices)

    return FiveColorQueryResponse(
        found=result.found,
        selected_indices=result.selected_indices,
        result_rgb=result.result_rgb,
        result_hex=rgb_to_hex(result.result_rgb) if result.result_rgb else None,
        row_index=result.row_index,
        message=result.message,
        source=result.source,
    )


@router.post("/generate-swatch")
def generate_swatch(
    request: RecipeSwatchRequest,
    registry: FileRegistry = Depends(get_file_registry),
) -> RecipeSwatchResponse:
    """Generate a 3MF swatch file from collected recipes.
    根据收集的配方列表生成 3MF 色块验证文件。
    """
    from api.file_bridge import pil_to_png_bytes
    from core.recipe_swatch import RecipeSwatchItem, generate_recipe_swatch

    engine, _ = _load_engine(request.lut_name)
    base_color_names = engine.get_color_names()
    base_color_hexes = [rgb_to_hex(rgb) for rgb in engine.get_base_colors()]

    items: list[RecipeSwatchItem] = []
    for recipe_request in request.recipes:
        for idx in recipe_request.selected_indices:
            if idx < 0 or idx >= engine.color_count:
                raise HTTPException(
                    status_code=400,
                    detail=f"Index {idx} out of range [0, {engine.color_count})",
                )
        query_result = engine.query(recipe_request.selected_indices)
        if not query_result.found or query_result.result_rgb is None:
            raise HTTPException(
                status_code=400,
                detail=f"No LUT match for selected indices: {recipe_request.selected_indices}",
            )
        items.append(
            RecipeSwatchItem(
                selected_indices=recipe_request.selected_indices,
                result_hex=rgb_to_hex(query_result.result_rgb),
                base_color_names=base_color_names,
                base_color_hexes=base_color_hexes,
            )
        )

    output_path, legend_img, status_msg = generate_recipe_swatch(
        recipes=items,
        block_size_mm=request.block_size_mm,
        gap_mm=request.gap_mm,
        cols=request.cols,
        structure_mode=request.structure_mode,
        printer_id=request.printer_id,
        slicer=request.slicer,
        nozzle_size=request.nozzle_size,
    )

    if not output_path:
        raise HTTPException(status_code=500, detail=status_msg or "Swatch generation failed")

    request_id = get_request_id()
    unique_suffix = uuid.uuid4().hex
    sid = (
        f"recipe-swatch:{request_id}:{unique_suffix}"
        if request_id
        else f"recipe-swatch:{unique_suffix}"
    )
    download_id = registry.register_path(
        sid,
        output_path,
        ttl_seconds=STATELESS_EXPORT_TTL_SECONDS,
    )

    preview_url: str | None = None
    if legend_img is not None:
        preview_bytes = pil_to_png_bytes(legend_img)
        preview_id = registry.register_bytes(
            sid,
            preview_bytes,
            "swatch_legend.png",
            ttl_seconds=STATELESS_EXPORT_TTL_SECONDS,
        )
        preview_url = f"/api/files/{preview_id}"

    return RecipeSwatchResponse(
        status="ok",
        message=status_msg,
        download_url=f"/api/files/{download_id}",
        preview_url=preview_url,
        recipe_count=len(items),
    )
