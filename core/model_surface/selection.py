from __future__ import annotations

import math

import numpy as np
import trimesh

from core.model_surface.types import ModelSurfaceError, SurfaceSelection


def select_planar_component(
    mesh: trimesh.Trimesh,
    face_index: int,
    *,
    angle_tolerance_deg: float = 1.0,
    plane_tolerance_mm: float = 0.05,
) -> SurfaceSelection:
    """Select connected faces that stay on the seed face's plane.

    选择与种子三角面连通且仍位于同一平面上的面片。

    Args:
        mesh: Source triangle mesh.
            源三角网格。
        face_index: Hit triangle index used as the seed.
            作为种子的命中三角面索引。
        angle_tolerance_deg: Maximum normal angle difference in degrees.
            允许的法线角度差，单位为度。
        plane_tolerance_mm: Maximum vertex distance from the seed plane.
            顶点到种子平面的最大距离，单位为毫米。

    Returns:
        Connected planar selection with face indices and area.
        包含面索引和面积的连通平面选择结果。

    Raises:
        ModelSurfaceError: If the requested face is invalid or no planar
            component can be selected.
            当面索引无效或无法选中平面区域时抛出。
    """

    if face_index < 0 or face_index >= len(mesh.faces):
        raise ModelSurfaceError("Selected face index is outside the model.")

    normals = np.asarray(mesh.face_normals, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    seed_normal = normals[face_index]
    normal_len = float(np.linalg.norm(seed_normal))
    if normal_len <= 0.0:
        raise ModelSurfaceError("Selected face has invalid normal.")
    seed_normal = seed_normal / normal_len
    seed_origin = vertices[faces[face_index]].mean(axis=0)
    min_dot = math.cos(math.radians(angle_tolerance_deg))

    adjacency: dict[int, list[int]] = {}
    for left, right in np.asarray(mesh.face_adjacency, dtype=np.int64):
        adjacency.setdefault(int(left), []).append(int(right))
        adjacency.setdefault(int(right), []).append(int(left))

    selected: set[int] = set()
    pending = [int(face_index)]
    while pending:
        current = pending.pop()
        if current in selected:
            continue
        current_normal = normals[current]
        current_len = float(np.linalg.norm(current_normal))
        if current_len <= 0.0:
            continue
        current_normal = current_normal / current_len
        if float(np.dot(current_normal, seed_normal)) < min_dot:
            continue
        triangle = vertices[faces[current]]
        distances = np.abs((triangle - seed_origin) @ seed_normal)
        if float(np.max(distances)) > plane_tolerance_mm:
            continue
        selected.add(current)
        pending.extend(adjacency.get(current, []))

    if not selected:
        raise ModelSurfaceError("No planar surface could be selected.")

    selected_indices = tuple(sorted(selected))
    area = float(np.asarray(mesh.area_faces, dtype=np.float64)[list(selected_indices)].sum())
    return SurfaceSelection(
        face_indices=selected_indices,
        normal=tuple(float(value) for value in seed_normal),
        plane_origin=tuple(float(value) for value in seed_origin),
        area_mm2=area,
        face_count=len(selected_indices),
    )
