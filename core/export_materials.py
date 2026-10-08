"""Shared product palette lookup for scene and puzzle exports.

场景与拼图导出共用的产品调色板查找；不选择原生耗材配置。
"""

from __future__ import annotations

import re
from collections.abc import Mapping

import numpy as np

RGB = tuple[int, int, int]


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
