from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np
import trimesh

from core.mesh_generators import BaseMesher

_BOX_FACE_TEMPLATE = np.array(
    [
        [0, 2, 1],
        [0, 3, 2],
        [4, 5, 6],
        [4, 6, 7],
        [0, 1, 5],
        [0, 5, 4],
        [1, 2, 6],
        [1, 6, 5],
        [2, 3, 7],
        [2, 7, 6],
        [3, 0, 4],
        [3, 4, 7],
    ],
    dtype=np.int64,
)


def build_slot_box_scene_from_voxels(
    *,
    full_matrix: np.ndarray,
    slot_names: Sequence[str],
    preview_colors: Mapping[object, object],
    target_h: int,
    pixel_scale: float,
    layer_heights_mm: Sequence[float],
) -> trimesh.Scene:
    """Build a model-surface-safe slot scene from material voxels.

    This keeps each greedy rectangle prism topologically independent instead
    of merging shared vertices between adjacent prisms. Bambu-family slicers
    then see closed shells rather than multi-face shared edges.

    根据材料体素构建适合模型覆面的材料场景。这里不合并相邻矩形柱的
    共享顶点，避免 Bambu/Orca 将多面共边识别为非流形。
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
        layer_rectangles = _material_layer_rectangles(
            full_matrix,
            mat_id,
            layer_z_boundaries_mm,
        )
        mesh = _build_box_mesh_without_shared_vertices(layer_rectangles, target_h)
        if mesh is None:
            continue
        mesh.apply_transform(transform)
        mesh.visual.face_colors = _coerce_rgba(preview_colors.get(mat_id))
        mesh.metadata["name"] = str(slot_name)
        scene.add_geometry(mesh, node_name=str(slot_name), geom_name=str(slot_name))

    return scene


def _material_layer_rectangles(
    full_matrix: np.ndarray,
    mat_id: int,
    layer_z_boundaries_mm: np.ndarray,
) -> list[tuple[float, float, np.ndarray]]:
    layer_rectangles: list[tuple[float, float, np.ndarray]] = []
    for start_z, end_z, mask in BaseMesher._merge_layers_no_dilation(full_matrix, mat_id):
        rects = BaseMesher._greedy_rect_merge(mask)
        if rects.shape[0] > 0:
            layer_rectangles.append(
                (
                    float(layer_z_boundaries_mm[int(start_z)]),
                    float(layer_z_boundaries_mm[int(end_z) + 1]),
                    rects,
                )
            )
    return layer_rectangles


def _build_box_mesh_without_shared_vertices(
    layer_rectangles: Sequence[tuple[float, float, np.ndarray]],
    height_px: int,
) -> trimesh.Trimesh | None:
    total_rects = sum(rects.shape[0] for _, _, rects in layer_rectangles)
    if total_rects == 0:
        return None

    vertices = np.empty((total_rects * 8, 3), dtype=np.float64)
    faces = np.empty((total_rects * 12, 3), dtype=np.int64)
    rect_offset = 0

    for z_bottom, z_top, rects in layer_rectangles:
        rect_count = int(rects.shape[0])
        if rect_count == 0:
            continue

        x0, y0, x1, y1 = rects[:, 0], rects[:, 1], rects[:, 2], rects[:, 3]
        wy0 = float(height_px) - y1
        wy1 = float(height_px) - y0

        boxes = np.empty((rect_count, 8, 3), dtype=np.float64)
        boxes[:, 0, :] = np.column_stack([x0, wy0, np.full(rect_count, z_bottom)])
        boxes[:, 1, :] = np.column_stack([x1, wy0, np.full(rect_count, z_bottom)])
        boxes[:, 2, :] = np.column_stack([x1, wy1, np.full(rect_count, z_bottom)])
        boxes[:, 3, :] = np.column_stack([x0, wy1, np.full(rect_count, z_bottom)])
        boxes[:, 4, :] = np.column_stack([x0, wy0, np.full(rect_count, z_top)])
        boxes[:, 5, :] = np.column_stack([x1, wy0, np.full(rect_count, z_top)])
        boxes[:, 6, :] = np.column_stack([x1, wy1, np.full(rect_count, z_top)])
        boxes[:, 7, :] = np.column_stack([x0, wy1, np.full(rect_count, z_top)])

        vertex_start = rect_offset * 8
        vertices[vertex_start : vertex_start + rect_count * 8] = boxes.reshape(-1, 3)

        face_start = rect_offset * 12
        offsets = (np.arange(rect_count, dtype=np.int64) * 8 + vertex_start).reshape(-1, 1, 1)
        faces[face_start : face_start + rect_count * 12] = (
            _BOX_FACE_TEMPLATE.reshape(1, 12, 3) + offsets
        ).reshape(-1, 3)
        rect_offset += rect_count

    return trimesh.Trimesh(vertices=vertices, faces=faces, process=False)


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
