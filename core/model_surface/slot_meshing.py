from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np
import shapely.geometry as sg
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
import trimesh

from core.layered_meshing import (
    build_labeled_surface_mesh,
    merge_boolean_rectangles,
)


def build_printable_footprint_from_voxels(
    *,
    full_matrix: np.ndarray,
    material_count: int,
    target_h: int,
    pixel_scale: float,
) -> BaseGeometry:
    """Build the exact XY footprint occupied by printable material voxels.

    构建实际可打印材料体素占据的精确 XY 轮廓。

    A pixel belongs to the footprint only when at least one displayed layer
    references a valid material slot. The pixel-corner coordinates and Y-axis
    flip intentionally match :func:`build_slot_surface_scene_from_voxels`.

    只有展示层中至少一层引用合法材料槽时，该像素才属于轮廓。像素角点坐标
    和 Y 轴翻转规则与 :func:`build_slot_surface_scene_from_voxels` 保持一致。
    """

    matrix = np.asarray(full_matrix)
    if matrix.ndim != 3:
        raise ValueError("full_matrix must be a 3D voxel matrix.")
    if material_count <= 0:
        raise ValueError("material_count must be positive.")
    if target_h <= 0 or pixel_scale <= 0:
        raise ValueError("target_h and pixel_scale must be positive.")

    printable = np.any(
        (matrix >= 0) & (matrix < int(material_count)),
        axis=0,
    )
    rectangles = merge_boolean_rectangles(printable).astype(
        np.float64,
        copy=False,
    )
    if rectangles.shape[0] == 0:
        return sg.GeometryCollection()

    scale = float(pixel_scale)
    boxes = []
    for x0, y0, x1, y1 in rectangles:
        world_y0 = float(target_h) - float(y1)
        world_y1 = float(target_h) - float(y0)
        boxes.append(
            sg.box(
                float(x0) * scale,
                world_y0 * scale,
                float(x1) * scale,
                world_y1 * scale,
            )
        )
    return unary_union(boxes)


def build_slot_surface_scene_from_voxels(
    *,
    full_matrix: np.ndarray,
    slot_names: Sequence[str],
    preview_colors: Mapping[object, object],
    target_h: int,
    pixel_scale: float,
    layer_heights_mm: Sequence[float],
) -> trimesh.Scene:
    """Build a model-surface slot scene with the shared indexed core.
    使用统一索引核心构建模型覆面材料场景。

    The common surface builder removes internal voxel interfaces and shares
    final boundary indices. Its integer or half-integer Z levels are then
    mapped once onto the supplied physical layer-height schedule. / 统一表面
    构建器会移除内部体素接口并共享最终边界索引，随后将整数或半整数 Z
    格点映射到给定物理层高。
    """

    if full_matrix.ndim != 3:
        raise ValueError("full_matrix must be a 3D voxel matrix.")
    if target_h <= 0 or pixel_scale <= 0:
        raise ValueError("target_h and pixel_scale must be positive.")
    layer_heights = np.asarray(layer_heights_mm, dtype=np.float64)
    if layer_heights.shape != (full_matrix.shape[0],):
        raise ValueError("layer_heights_mm must match the voxel matrix Z depth.")
    if not np.all(np.isfinite(layer_heights)) or np.any(layer_heights <= 0.0):
        raise ValueError("layer_heights_mm must contain positive finite values.")
    layer_z_boundaries_mm = np.concatenate(
        (np.zeros(1, dtype=np.float64), np.cumsum(layer_heights)),
    )

    scene = trimesh.Scene()
    transform = np.eye(4)
    transform[0, 0] = float(pixel_scale)
    transform[1, 1] = float(pixel_scale)

    for mat_id, slot_name in enumerate(slot_names):
        mesh = build_labeled_surface_mesh(
            full_matrix,
            material_id=mat_id,
            height_px=target_h,
        )
        if mesh is None:
            continue
        vertices = np.asarray(mesh.vertices, dtype=np.float64).copy()
        lattice_z = vertices[:, 2]
        if not np.all(np.isfinite(lattice_z)):
            raise ValueError("Shared surface mesh left the model layer lattice.")
        doubled_layer_positions = np.rint(lattice_z * 2.0).astype(np.int64)
        maximum_doubled_layer = 2 * (len(layer_z_boundaries_mm) - 1)
        if (
            np.any(doubled_layer_positions < 0)
            or np.any(doubled_layer_positions > maximum_doubled_layer)
            or not np.allclose(
                lattice_z * 2.0,
                doubled_layer_positions,
                rtol=0.0,
                atol=1e-9,
            )
        ):
            raise ValueError("Shared surface mesh left the model layer lattice.")
        lower_layer_indices = doubled_layer_positions // 2
        vertices[:, 2] = layer_z_boundaries_mm[lower_layer_indices]
        half_layer = (doubled_layer_positions % 2) == 1
        if np.any(half_layer):
            half_layer_indices = lower_layer_indices[half_layer]
            vertices[half_layer, 2] = 0.5 * (
                layer_z_boundaries_mm[half_layer_indices]
                + layer_z_boundaries_mm[half_layer_indices + 1]
            )
        mesh.vertices = vertices
        mesh.apply_transform(transform)
        mesh.visual.face_colors = _coerce_rgba(preview_colors.get(mat_id))
        mesh.metadata["name"] = str(slot_name)
        mesh.metadata["model_surface_physical_z_schedule"] = True
        scene.add_geometry(mesh, node_name=str(slot_name), geom_name=str(slot_name))

    return scene


def _coerce_rgba(value: object) -> np.ndarray:
    if isinstance(value, np.ndarray):
        raw = value.tolist()
    elif isinstance(value, (list, tuple)):
        raw = list(value)
    else:
        raw = [200, 200, 200, 255]
    if len(raw) < 4:
        raw = [*raw[:3], 255]
    return np.asarray([int(channel) for channel in raw[:4]], dtype=np.uint8)
