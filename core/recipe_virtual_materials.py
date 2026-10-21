"""Shared virtual-material identity for preflight and raster/vector generation.

预检、光栅与矢量生成共用的虚拟材料身份和通道映射。
"""

from collections.abc import Mapping, Sequence
from typing import Any


def build_virtual_material_registry(
    recipe_overrides: Sequence[Mapping[str, Any]], native_palette_length: int,
) -> tuple[list[dict[str, str]], dict[str, dict[int, int]]]:
    """Resolve declared virtual materials and stable local-to-global channels.

    按名称和颜色去重虚拟材料，并生成与原生调色板衔接的稳定通道映射。
    """
    registry: list[dict[str, str]] = []
    lookup: dict[tuple[str, str], int] = {}
    region_maps: dict[str, dict[int, int]] = {}
    for item in recipe_overrides:
        if not isinstance(item, Mapping):
            continue
        region_id = str(item.get("region_id", "")).strip()
        local_map: dict[int, int] = {}
        for local_index, material in enumerate(item.get("virtual_materials") or []):
            if not isinstance(material, Mapping):
                continue
            name = str(material.get("name") or "").strip()
            colour = str(material.get("hex") or "").strip()
            if not name or not colour:
                continue
            key = (name.lower(), colour.lower())
            global_index = lookup.get(key)
            if global_index is None:
                global_index = native_palette_length + len(registry)
                registry.append({"name": name, "hex": colour})
                lookup[key] = global_index
            local_map[native_palette_length + local_index] = global_index
        if region_id:
            region_maps[region_id] = local_map
    return registry, region_maps
