#!/usr/bin/env python3
"""Profile single-task converter workloads without changing output quality.

在不改变输出质量的前提下分析转换器单任务工作负载。
"""

from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import numpy as np
import trimesh

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config import ModelingMode


_BASE_EIGHT = [
    "纵维立方/纵维立方PLA白色",
    "纵维立方/纵维立方PLA黑色",
    "纵维立方/纵维立方PLA红色",
    "纵维立方/纵维立方PLA黄色",
    "纵维立方/纵维立方PLA蓝色",
    "纵维立方/纵维立方PLA绿色",
    "纵维立方/纵维立方PLA青色",
    "纵维立方/纵维立方PLA品红色",
]
_EXTRA_SEVEN = [
    "Karvax/Karvax PLA 晴山蓝",
    "Karvax/Karvax PLA 流光蓝",
    "Karvax/Karvax PLA 烟笼紫霞",
    "Karvax/Karvax PLA 暖黄",
    "Karvax/Karvax PLA 朱砂红",
    "Karvax/Karvax PLA 拓竹绿",
    "Karvax/Karvax PLA 耀石黑",
]
MATERIAL_PALETTES = {
    8: list(_BASE_EIGHT),
    12: [*_BASE_EIGHT, *_EXTRA_SEVEN[:4]],
    15: [*_BASE_EIGHT, *_EXTRA_SEVEN],
}


@dataclass(frozen=True)
class ProfileCase:
    """Describe one deterministic converter profiling case.

    描述一个确定性的转换器性能分析案例。

    Attributes:
        name: Stable case identifier. 稳定的案例标识。
        kind: Raster or vector workflow. 位图或矢量工作流。
        input_path: Source asset path. 输入素材路径。
        target_width_mm: Requested model width. 目标模型宽度。
        material_count: Material Archive palette size. 耗材档案颜色数量。
    """

    name: str
    kind: Literal["raster", "vector"]
    input_path: Path
    target_width_mm: float
    material_count: Literal[8, 12, 15] = 12


def build_pipeline_context(case: ProfileCase) -> dict[str, Any]:
    """Build a quality-locked pipeline context for a profile case.

    为性能分析案例构建质量参数锁定的流水线上下文。

    Args:
        case: Deterministic profile case. 确定性的性能分析案例。

    Returns:
        Context accepted by the raster or vector pipeline.
        位图或矢量流水线可接受的上下文字典。
    """

    modeling_mode = (
        ModelingMode.VECTOR
        if case.kind == "vector"
        else ModelingMode.HIGH_FIDELITY
    )
    return {
        "image_path": str(case.input_path),
        "lut_path": "__material_archive__",
        "target_width_mm": float(case.target_width_mm),
        "spacer_thick": 1.2,
        "structure_mode": "single-sided",
        "color_mode": "4-Color (RYBW)",
        "add_loop": False,
        "loop_width": 4.0,
        "loop_length": 8.0,
        "loop_hole": 2.5,
        "loop_pos": None,
        "modeling_mode": modeling_mode,
        "color_layers": 10,
        "layer_height_mm": 0.08,
        "quantize_colors": 64,
        "color_replacements": None,
        "replacement_regions": None,
        "backing_color_id": 0,
        "separate_backing": False,
        "enable_relief": False,
        "color_height_map": None,
        "height_mode": "color",
        "heightmap_path": None,
        "heightmap_max_height": None,
        "enable_cleanup": True,
        "enable_outline": False,
        "outline_width": 2.0,
        "enable_cloisonne": False,
        "wire_width_mm": 0.4,
        "wire_height_mm": 0.4,
        "free_color_set": None,
        "enable_coating": False,
        "coating_height_mm": 0.08,
        "hue_weight": 0.5,
        "chroma_gate": 15.0,
        "matched_rgb_path": None,
        "loop_angle": 0.0,
        "loop_offset_x": 0.0,
        "loop_offset_y": 0.0,
        "loop_position_preset": "top-center",
        "printer_id": "bambu-h2d",
        "slicer": "BambuStudio",
        "nozzle_size": "0.4",
        "relief_global_max_height": None,
        "progress": None,
        "need_2d_preview": False,
        "material_source": "material_archive",
        "selected_materials": list(MATERIAL_PALETTES[case.material_count]),
        "material_layer_count": 10,
        "material_layer_height_mm": 0.08,
        "material_grid_resolution": 8,
        "material_backing_material_index": 0,
        "use_lut_constrained": False,
        "auto_dynamic_range": False,
        "high_precision_3d_preview": False,
    }


def _array_summary(value: object) -> dict[str, object] | None:
    if value is None:
        return None
    array = np.ascontiguousarray(np.asarray(value))
    digest = hashlib.sha256()
    digest.update(array.dtype.str.encode("ascii"))
    digest.update(repr(tuple(int(item) for item in array.shape)).encode("ascii"))
    digest.update(memoryview(array).cast("B"))
    return {
        "shape": [int(item) for item in array.shape],
        "dtype": array.dtype.str,
        "sha256": digest.hexdigest(),
    }


def _canonical_triangle_sha256(mesh: trimesh.Trimesh) -> str:
    vertices = np.round(np.asarray(mesh.vertices, dtype=np.float64), 9)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    triangles = vertices[faces]
    vertex_order = np.lexsort(
        (triangles[:, :, 2], triangles[:, :, 1], triangles[:, :, 0]),
        axis=1,
    )
    ordered_vertices = np.take_along_axis(
        triangles,
        vertex_order[:, :, np.newaxis],
        axis=1,
    )
    flattened = np.ascontiguousarray(ordered_vertices.reshape((-1, 9)))
    face_order = np.lexsort(
        tuple(flattened[:, index] for index in range(8, -1, -1))
    )
    canonical = np.ascontiguousarray(flattened[face_order])
    return hashlib.sha256(memoryview(canonical).cast("B")).hexdigest()


def _mesh_summary(mesh: trimesh.Trimesh) -> dict[str, object]:
    bounds = np.asarray(mesh.bounds, dtype=np.float64)
    return {
        "vertices": int(len(mesh.vertices)),
        "faces": int(len(mesh.faces)),
        "bounds": np.round(bounds, 9).tolist(),
        "area": round(float(mesh.area), 9),
        "volume": round(float(mesh.volume), 9),
        "watertight": bool(mesh.is_watertight),
        "euler_number": int(mesh.euler_number),
        "degenerate_faces": int(
            np.count_nonzero(np.asarray(mesh.area_faces) <= 1e-12)
        ),
        "canonical_triangle_sha256": _canonical_triangle_sha256(mesh),
    }


def semantic_snapshot(ctx: dict[str, Any]) -> dict[str, object]:
    """Summarize output arrays and geometry using deterministic semantics.

    以确定性语义摘要记录输出数组与几何结果。

    Args:
        ctx: Completed pipeline context. 已完成的流水线上下文。

    Returns:
        Order-independent semantic snapshot. 与顺序无关的语义快照。
    """

    cache = ctx.get("cache")
    payload = cache if isinstance(cache, dict) else ctx
    scene = ctx.get("scene")
    if scene is None:
        scene = payload.get("scene")
    geometry: dict[str, object] = {}
    if isinstance(scene, trimesh.Scene):
        for name in sorted(scene.geometry):
            raw = scene.geometry[name]
            if isinstance(raw, trimesh.Trimesh):
                geometry[str(name)] = _mesh_summary(raw)
    return {
        "matched_rgb": _array_summary(payload.get("matched_rgb")),
        "material_matrix": _array_summary(payload.get("material_matrix")),
        "mask_solid": _array_summary(payload.get("mask_solid")),
        "slot_names": [str(item) for item in payload.get("slot_names") or []],
        "geometry": geometry,
    }
