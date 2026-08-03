"""Helpers for exposing committed dynamic material cache metadata.
用于公开已提交动态耗材缓存元数据的辅助函数。
"""

from typing import Any, Mapping

from api.schemas.dynamic_material import DynamicMaterialResultResponse


def dynamic_material_result_from_cache(
    cache: Mapping[str, Any] | None,
) -> DynamicMaterialResultResponse:
    """Build typed response fields from the committed preview cache.
    从已提交的预览缓存构建强类型响应字段。

    Args:
        cache: Preview cache mapping after a successful mutation, or ``None``.
            成功变更后的预览缓存映射，或 ``None``。

    Returns:
        DynamicMaterialResultResponse: Validated recipes and benefit curve;
            both fields are ``None`` when dynamic metadata is unavailable.
            经校验的配方和收益曲线；动态元数据不可用时两字段均为 ``None``。
    """
    if not isinstance(cache, Mapping):
        return DynamicMaterialResultResponse()
    info = cache.get("material_dynamic_layer_info")
    if not isinstance(info, Mapping):
        return DynamicMaterialResultResponse()
    recipes = info.get("colors")
    benefit_curve = info.get("benefit_curve")
    scope = info.get("benefit_curve_scope")
    if scope not in {"all_printable_pixels", "automatic_pixels"}:
        # Caches written before scope coverage was added described the whole
        # printable image. Preserve that historical interpretation instead of
        # dropping a valid legacy share/preview result.
        scope = "all_printable_pixels" if isinstance(benefit_curve, list) else None
    pixel_count = info.get("benefit_curve_pixel_count")
    if isinstance(pixel_count, bool):
        pixel_count = None
    elif pixel_count is not None:
        try:
            pixel_count = int(pixel_count)
        except (TypeError, ValueError):
            pixel_count = None
        if pixel_count is not None and pixel_count < 0:
            pixel_count = None
    if (scope is None) != (pixel_count is None):
        # Legacy caches do not have a reliable persisted coverage count. Do
        # not invent one in an API DTO; callers can still render the curve.
        scope = None
        pixel_count = None
    return DynamicMaterialResultResponse(
        material_dynamic_recipes=recipes if isinstance(recipes, list) else None,
        material_layer_benefit_curve=(
            benefit_curve if isinstance(benefit_curve, list) else None
        ),
        material_layer_benefit_scope=scope,
        material_layer_benefit_pixel_count=pixel_count,
    )
