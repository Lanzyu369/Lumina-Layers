"""Shared product palette lookup for scene and puzzle exports.

场景与拼图导出共用的产品调色板查找；不选择原生耗材配置。
"""

from __future__ import annotations

import re
from collections.abc import Mapping, MutableMapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from core.material_lut_provider import load_materials

RGB = tuple[int, int, int]


@dataclass(frozen=True)
class ExportMaterial:
    """Resolved source identity shared by auxiliary geometry and native metadata."""

    name: str
    material_type: str | None
    rgb: RGB


def resolve_coating_material(
    reference: Mapping[str, str] | None,
    *,
    slot_names: Sequence[str],
    preview_colors: Mapping[object, object],
    material_types: Mapping[str, str | None],
) -> ExportMaterial:
    """Resolve an explicit palette slot or independent material archive.

    Args:
        reference: User-selected source and stable key. 用户选择的来源和键。
        slot_names: Current optical palette identities. 当前光学调色板身份。
        preview_colors: Source preview colours. 来源预览颜色。
        material_types: Actual source material types. 来源材料类型。

    Returns:
        Actual coating identity, type and colour. 涂层的实际材料身份、类型和颜色。

    Raises:
        ValueError: Missing or stale selection. 未选择涂层耗材或选择已失效。
    """
    if not isinstance(reference, Mapping) or not reference.get("key"):
        raise ValueError("Choose a coating material before generating / 请先选择涂层耗材")
    source, key = reference.get("source"), str(reference["key"])
    if source == "palette" and key in slot_names:
        material_type = material_types.get(key)
        # Missing legacy archive types remain unknown. Native preflight
        # resolves the user's selected preset; never invent PLA here.
        rgb, _ = resolve_preview_color_for_slot(key, slot_names.index(key), preview_colors)
        return ExportMaterial(key, material_type, rgb)
    if source == "material_archive":
        try:
            material = load_materials([key])[0]
        except (FileNotFoundError, OSError, ValueError, IndexError) as exc:
            raise ValueError("Coating material archive is unavailable; choose it again / 涂层耗材档案不可用，请重新选择") from exc
        return ExportMaterial(
            f"Coating: {material.name}", material.material_type,
            coerce_preview_rgb(material.estimated_rgb),
        )
    raise ValueError("Coating material selection is no longer available / 涂层材料选择已失效")


def configure_coating_material(ctx: MutableMapping[str, Any]) -> ExportMaterial | None:
    """Bind explicit coating export facts without adding an optical solver channel.

    Args:
        ctx: Resolved source and conversion settings. 已解析来源及转换设置。

    Returns:
        Resolved material when coating is enabled. 启用涂层时返回解析后的材料。
    """
    if not ctx.get("enable_coating"):
        return None
    material = resolve_coating_material(
        ctx.get("coating_material"), slot_names=ctx["slot_names"],
        preview_colors=ctx["preview_colors"], material_types=ctx.get("material_types") or {},
    )
    ctx["resolved_coating_material"] = material
    ctx["material_types"] = {**(ctx.get("material_types") or {}), material.name: material.material_type}
    ctx["preview_colors"] = {**ctx["preview_colors"], material.name: [*material.rgb, 255]}
    return material


def coerce_preview_rgb(value: object) -> RGB:
    """Read the first three channels of a pipeline preview colour.

    读取流水线预览颜色的前三个通道。

    Args:
        value: Array, list or tuple of colour channels. 颜色数组、列表或元组。

    Returns:
        Integer RGB channels. 整数 RGB 通道。

    Raises:
        ValueError: Unsupported value or fewer than three channels.
            输入类型不支持或不足三个通道。
    """
    if isinstance(value, np.ndarray):
        channels = value.tolist()
    elif isinstance(value, (list, tuple)):
        channels = list(value)
    else:
        raise ValueError(f"Unsupported preview color value: {type(value)!r}")
    if len(channels) < 3:
        raise ValueError("Preview color value must have at least 3 channels.")
    return int(channels[0]), int(channels[1]), int(channels[2])


def resolve_preview_color_for_slot(
    slot_name: str,
    slot_index: int,
    preview_colors: Mapping[object, object],
) -> tuple[RGB, str]:
    """Resolve a colour by name, numbered slot, then palette index.

    按名称、带编号的槽名、调色板索引依次解析颜色。

    Args:
        slot_name: Display material or slot name. 材料或槽位显示名。
        slot_index: Zero-based palette index. 从零开始的调色板索引。
        preview_colors: Name or numeric key to preview channels.
            名称或数值键到预览颜色通道的映射。

    Returns:
        RGB and the resolution source used for existing diagnostics.
        RGB 与现有诊断使用的解析来源。
    """
    if slot_name in preview_colors:
        return coerce_preview_rgb(preview_colors[slot_name]), "by name"
    match = re.match(r"Slot\s+(\d+)\b", slot_name)
    if match is not None:
        slot_key = int(match.group(1)) - 1
        for key in (slot_key, str(slot_key)):
            if key in preview_colors:
                return coerce_preview_rgb(preview_colors[key]), "by slot"
    for key in (slot_index, str(slot_index)):
        if key in preview_colors:
            return coerce_preview_rgb(preview_colors[key]), "by index"
    return (200, 200, 200), "fallback"
