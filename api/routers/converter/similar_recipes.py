"""Similar-recipe suggestions for quick recolouring in Color Adjustment.

「颜色调整」快速换色的相似配方推荐：LUT 会话返回 LUT 中色差最小的可打印
配方（以及可用时的预测配方）；耗材档案会话返回图中已有的相近颜色。
"""

from __future__ import annotations

import time

import numpy as np
from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import get_session_store
from api.preview_cache_artifacts import is_preview_cache_artifact_ref
from api.schemas.converter import SimilarRecipesRequest
from api.schemas.responses import SimilarRecipeItem, SimilarRecipesResponse
from api.session_store import SessionStore
from api.structured_logging import get_logger
from api.visible_region_cache import get_valid_visible_region_cache
from core.color_similarity import (
    SimilarRecipeCandidate,
    parse_hex_color,
    rank_image_colors,
    rank_similar_recipes,
    rgb_to_hex,
    unique_color_hexes,
)
from core.native_reference import opencv_lab_to_rgb_uint8
from core.recipe_order import convert_recipe_between_orders

from .common import (
    PREVIEW_CACHE_UNAVAILABLE_DETAIL,
    _require_preview_cache,
    _require_session,
    load_session_lut_runtime,
)

router = APIRouter()
log = get_logger(__name__)

SIMILAR_RECIPES_LUT_UNAVAILABLE_DETAIL = (
    "The LUT for this session could not be loaded. Re-run preview and try again."
)

# Recipes are returned in the material-matrix storage convention so that the
# frontend can render and apply every item without per-item order handling.
# 统一以 material_matrix 的存储层序返回，前端无需逐条处理层序。
_RESPONSE_LAYER_ORDER = "Top2Bottom"


def _session_layer_params(session_data: dict) -> tuple[int, float]:
    """Resolve the colour layer count/height the session previews with.
    解析会话预览使用的叠色层数与层高；优先使用预览缓存中的实际值。

    Raises:
        HTTPException(409): No preview has been built for this session yet.
    """
    cache = session_data.get("preview_cache")
    if cache is None:
        raise HTTPException(status_code=409, detail=PREVIEW_CACHE_UNAVAILABLE_DETAIL)
    if is_preview_cache_artifact_ref(cache):
        cache = cache.get("metadata") or {}
    if not isinstance(cache, dict):
        cache = {}
    layers = cache.get("color_layers") or session_data.get("color_layers")
    if not layers:
        raise HTTPException(status_code=409, detail=PREVIEW_CACHE_UNAVAILABLE_DETAIL)
    height = cache.get("layer_height_mm") or session_data.get("layer_height_mm") or 0.08
    return int(layers), float(height)


def _image_color_hexes(session_data: dict) -> set[str]:
    """Colours currently printed in the image (solid pixels only).
    当前图像中实际打印的颜色（仅实体像素）。

    Uses the visible-block cache kept by the selection tools; right after an
    edit that cache may still be rebuilding, so fall back to the preview cache.
    优先使用选区工具维护的可见色块缓存；编辑后缓存可能尚在重建，此时回退到预览缓存。
    """
    component_cache = get_valid_visible_region_cache(session_data)
    if component_cache is not None:
        return {str(item["color_hex"]).lower() for item in component_cache["components"].values()}
    preview_cache = _require_preview_cache(session_data)
    matched_rgb = preview_cache.get("matched_rgb")
    if matched_rgb is None:
        return set()
    mask_solid = preview_cache.get("mask_solid")
    return unique_color_hexes(matched_rgb, mask_solid)


def _predictive_candidates(lut_data: dict) -> tuple[np.ndarray, np.ndarray, str] | None:
    """Return ``(rgb, recipes, layer_order)`` from the predictive runtime, if any.
    返回预测运行时的候选颜色、配方及其层序；无预测模型时返回 None。
    """
    runtime = lut_data.get("predictive_runtime")
    if runtime is None:
        return None
    recipes = np.asarray(runtime.candidate_recipes)
    pred_lab = np.asarray(runtime.pred_lab)
    if recipes.ndim != 2 or recipes.shape[0] == 0 or pred_lab.shape[0] != recipes.shape[0]:
        return None
    return opencv_lab_to_rgb_uint8(pred_lab), recipes, str(runtime.layer_order)


def _lut_suggestions(
    session_data: dict,
    request: SimilarRecipesRequest,
    reference_rgb: tuple[int, int, int],
) -> tuple[list[SimilarRecipeCandidate], str, bool]:
    """Rank LUT (and predictive) recipes; returns ``(items, predictive_order, predictive)``.
    排序 LUT（及预测）配方，返回候选、预测配方层序和是否有预测模型。
    """
    color_layers, layer_height_mm = _session_layer_params(session_data)
    try:
        lut_data = load_session_lut_runtime(
            session_data,
            color_layers=color_layers,
            layer_height_mm=layer_height_mm,
        )
    except (KeyError, OSError, TypeError, ValueError) as exc:
        log.warning(
            "Similar recipe LUT load failed",
            extra={
                "event": "converter_similar_recipes_lut_load_failed",
                "session_id": request.session_id,
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
        )
        raise HTTPException(status_code=409, detail=SIMILAR_RECIPES_LUT_UNAVAILABLE_DETAIL) from exc
    if lut_data is None:
        raise HTTPException(status_code=409, detail=SIMILAR_RECIPES_LUT_UNAVAILABLE_DETAIL)

    lut_rgb = np.asarray(lut_data.get("lut_rgb"))
    ref_stacks = np.asarray(lut_data.get("ref_stacks"))
    if lut_rgb.size == 0 or ref_stacks.ndim != 2 or ref_stacks.shape[0] != lut_rgb.reshape(-1, 3).shape[0]:
        raise HTTPException(status_code=409, detail=SIMILAR_RECIPES_LUT_UNAVAILABLE_DETAIL)

    predictive = _predictive_candidates(lut_data) if request.include_predictive else None
    candidates = rank_similar_recipes(
        reference_rgb,
        lut_rgb,
        ref_stacks,
        limit=request.limit,
        predictive_rgb=predictive[0] if predictive is not None else None,
        predictive_recipes=predictive[1] if predictive is not None else None,
    )
    predictive_order = predictive[2] if predictive is not None else _RESPONSE_LAYER_ORDER
    return candidates, predictive_order, predictive is not None


def _image_suggestions(
    session_data: dict,
    request: SimilarRecipesRequest,
    reference_rgb: tuple[int, int, int],
) -> list[SimilarRecipeCandidate]:
    """Rank colours already printed in the image (material-archive sources).
    排序图中已有的颜色（耗材档案来源）。
    """
    preview_cache = _require_preview_cache(session_data)
    matched_rgb = preview_cache.get("matched_rgb")
    if matched_rgb is None:
        raise HTTPException(status_code=409, detail=PREVIEW_CACHE_UNAVAILABLE_DETAIL)
    return rank_image_colors(
        reference_rgb,
        matched_rgb,
        preview_cache.get("mask_solid"),
        preview_cache.get("material_matrix"),
        limit=request.limit,
    )


@router.post("/similar-recipes", response_model=SimilarRecipesResponse)
def similar_recipes(
    request: SimilarRecipesRequest,
    store: SessionStore = Depends(get_session_store),
) -> SimilarRecipesResponse:
    """Suggest recipes whose colour is closest to a target colour.
    推荐与目标颜色色差最小的配方。

    LUT sessions rank LUT entries from the same runtime the replacement stack
    sync uses, so applying a ``lut`` item through region replacement writes
    exactly the listed recipe; ``predictive`` items must be applied as recipe
    overrides. Material-archive sessions rank colours already in the image
    (``image`` items), applied through region replacement as well.
    LUT 会话排序 LUT 条目（与替换叠层同步使用同一运行时），``lut`` 条目经区域
    替换写入的正是列出的配方；``predictive`` 条目需以配方覆盖方式应用。耗材档案
    会话排序图中已有颜色（``image`` 条目），同样经区域替换应用。

    Args:
        request (SimilarRecipesRequest): Target colour and limits. (目标颜色与数量限制)
        store (SessionStore): Session store dependency. (会话存储依赖)

    Returns:
        SimilarRecipesResponse: Suggestions sorted by ascending ΔE00. (按 ΔE00 升序的推荐)

    Raises:
        HTTPException(404): Session not found. (会话不存在)
        HTTPException(409): No preview yet, or LUT unavailable. (尚未预览或 LUT 不可用)
    """
    started_at = time.perf_counter()
    session_data = _require_session(store, request.session_id)
    reference_rgb = parse_hex_color(request.target_color)
    if str(session_data.get("material_source") or "lut") == "material_archive":
        candidates = _image_suggestions(session_data, request, reference_rgb)
        predictive_order, predictive_available = _RESPONSE_LAYER_ORDER, False
    else:
        candidates, predictive_order, predictive_available = _lut_suggestions(
            session_data, request, reference_rgb
        )
    image_colors = _image_color_hexes(session_data)
    log.debug(
        "similar recipes ranked",
        extra={
            "event": "converter_similar_recipes_ranked",
            "session_id": request.session_id,
            "item_count": len(candidates),
            "predictive_available": predictive_available,
            "elapsed_ms": round((time.perf_counter() - started_at) * 1000, 2),
        },
    )
    return SimilarRecipesResponse(
        target_color=rgb_to_hex(reference_rgb),
        layer_order=_RESPONSE_LAYER_ORDER,
        predictive_available=predictive_available,
        items=[
            SimilarRecipeItem(
                hex=candidate.hex,
                rgb=list(candidate.rgb),
                delta_e00=round(candidate.delta_e00, 3),
                # LUT and image stacks are stored Top2Bottom; only predictive recipes may differ.
                recipe=convert_recipe_between_orders(
                    candidate.recipe,
                    predictive_order if candidate.source == "predictive" else _RESPONSE_LAYER_ORDER,
                    _RESPONSE_LAYER_ORDER,
                ),
                source=candidate.source,
                in_image=candidate.source == "image" or candidate.hex in image_colors,
            )
            for candidate in candidates
        ],
    )
