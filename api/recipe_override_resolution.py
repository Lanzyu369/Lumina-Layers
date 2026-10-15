"""Resolve effective recipe declarations for preflight and generation.

预检与生成共用的有效配方声明解析，缓存只回补缺失的材料声明。
"""

from __future__ import annotations

from copy import deepcopy
import numpy as np

from api.preview_cache_artifacts import get_preview_cache_metadata
from api.schemas.converter import ConvertGenerateRequest


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
                "color_layers": getattr(item, "color_layers", None),
                "actual_recipe_top_to_bottom": getattr(
                    item,
                    "actual_recipe_top_to_bottom",
                    None,
                ),
                "print_recipe_top_to_bottom": getattr(
                    item,
                    "print_recipe_top_to_bottom",
                    None,
                ),
                "actual_layer_count": getattr(item, "actual_layer_count", None),
                "padding_layer_count": getattr(item, "padding_layer_count", None),
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
            for count_field in (
                "color_layers",
                "actual_layer_count",
                "padding_layer_count",
            ):
                raw_count = item_data.get(count_field)
                if raw_count is not None:
                    payload[count_field] = int(raw_count)
            for recipe_field in (
                "actual_recipe_top_to_bottom",
                "print_recipe_top_to_bottom",
            ):
                raw_recipe = item_data.get(recipe_field)
                if raw_recipe is not None:
                    payload[recipe_field] = [
                        int(value) for value in raw_recipe
                    ]
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
    raw_cache = session_data.get("preview_cache") or {}
    cache = (
        get_preview_cache_metadata(raw_cache)
        if isinstance(raw_cache, dict)
        else {}
    )
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


def resolve_recipe_overrides(
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

    session_items_by_region: dict[str, dict[str, object]] = {}
    session_virtuals_by_region: dict[str, list[dict[str, str]]] = {}
    for session_item in session_overrides:
        region_id = session_item.get("region_id")
        if isinstance(region_id, str) and region_id:
            session_items_by_region[region_id] = session_item
        virtuals = session_item.get("virtual_materials")
        if isinstance(region_id, str) and region_id and virtuals:
            session_virtuals_by_region[region_id] = [
                dict(entry) for entry in virtuals  # type: ignore[arg-type]
            ]

    for item in request_overrides:
        region_id = item.get("region_id")
        if not isinstance(region_id, str):
            continue
        session_item = session_items_by_region.get(region_id)
        if (
            session_item is not None
            and item.get("recipe") == session_item.get("recipe")
            and item.get("layer_order") == session_item.get("layer_order")
        ):
            for field_name in (
                "color_layers",
                "actual_recipe_top_to_bottom",
                "print_recipe_top_to_bottom",
                "actual_layer_count",
                "padding_layer_count",
            ):
                if item.get(field_name) is None and session_item.get(
                    field_name
                ) is not None:
                    item[field_name] = deepcopy(session_item[field_name])
        if not item.get("virtual_materials"):
            backfill = session_virtuals_by_region.get(region_id)
            if backfill:
                item["virtual_materials"] = [dict(entry) for entry in backfill]

    return _backfill_recipe_override_virtual_materials(
        session_data,
        request_overrides,
    )
