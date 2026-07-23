from __future__ import annotations

import math

import numpy as np
import trimesh

from core.model_surface.types import ModelSurfaceError, SurfaceCandidate, SurfaceSelection

SLICER_SURFACE_PICK_LIMIT = 254


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

    normals = np.asarray(mesh.face_normals, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    adjacency = _build_face_adjacency(mesh)
    return _select_planar_component_from_arrays(
        normals=normals,
        faces=faces,
        vertices=vertices,
        area_faces=np.asarray(mesh.area_faces, dtype=np.float64),
        adjacency=adjacency,
        face_index=face_index,
        angle_tolerance_deg=angle_tolerance_deg,
        plane_tolerance_mm=plane_tolerance_mm,
    )


def list_planar_surface_candidates(
    mesh: trimesh.Trimesh,
    *,
    angle_tolerance_deg: float = 1.0,
    plane_tolerance_mm: float = 0.05,
    min_area_mm2: float = 5.0,
    max_candidates: int = SLICER_SURFACE_PICK_LIMIT,
) -> tuple[SurfaceCandidate, ...]:
    """List large planar candidates suitable for slicer-style face picking.

    列出适合切片软件式选面的较大平面候选区域。
    """

    normals = np.asarray(mesh.face_normals, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    area_faces = np.asarray(mesh.area_faces, dtype=np.float64)
    adjacency = _build_face_adjacency(mesh)
    visited: set[int] = set()
    candidates: list[SurfaceCandidate] = []

    from core.model_surface.footprint import build_surface_footprint

    for face_index in range(len(faces)):
        if face_index in visited:
            continue
        try:
            selection = _select_planar_component_from_arrays(
                normals=normals,
                faces=faces,
                vertices=vertices,
                area_faces=area_faces,
                adjacency=adjacency,
                face_index=face_index,
                angle_tolerance_deg=angle_tolerance_deg,
                plane_tolerance_mm=plane_tolerance_mm,
            )
        except ModelSurfaceError:
            visited.add(face_index)
            continue

        visited.update(selection.face_indices)
        if selection.area_mm2 < min_area_mm2:
            continue
        try:
            footprint = build_surface_footprint(mesh, selection.face_indices)
        except ModelSurfaceError:
            continue

        seed_face = int(selection.face_indices[0])
        candidates.append(
            SurfaceCandidate(
                id=surface_candidate_id(seed_face),
                face_index=seed_face,
                face_indices=selection.face_indices,
                normal=selection.normal,
                plane_origin=selection.plane_origin,
                area_mm2=selection.area_mm2,
                face_count=selection.face_count,
                footprint=footprint,
            )
        )

    candidates.sort(key=lambda candidate: candidate.area_mm2, reverse=True)
    return tuple(candidates[: max(0, max_candidates)])


def surface_candidate_id(face_index: int) -> str:
    """Return the stable public id for a surface candidate seed face.

    返回候选平面种子面的稳定公开 ID。
    """

    return f"surface-{int(face_index)}"


def face_index_from_surface_candidate_id(candidate_id: str) -> int:
    """Decode a public surface candidate id into its seed face index.

    将公开候选平面 ID 解码为种子三角面索引。
    """

    prefix = "surface-"
    if not candidate_id.startswith(prefix):
        raise ModelSurfaceError("Selected surface candidate is invalid.")
    try:
        face_index = int(candidate_id[len(prefix) :])
    except ValueError as exc:
        raise ModelSurfaceError("Selected surface candidate is invalid.") from exc
    if face_index < 0:
        raise ModelSurfaceError("Selected surface candidate is invalid.")
    return face_index


def _select_planar_component_from_arrays(
    *,
    normals: np.ndarray,
    faces: np.ndarray,
    vertices: np.ndarray,
    area_faces: np.ndarray,
    adjacency: dict[int, list[int]],
    face_index: int,
    angle_tolerance_deg: float,
    plane_tolerance_mm: float,
) -> SurfaceSelection:
    if face_index < 0 or face_index >= len(faces):
        raise ModelSurfaceError("Selected face index is outside the model.")

    seed_normal = normals[face_index]
    normal_len = float(np.linalg.norm(seed_normal))
    if normal_len <= 0.0:
        raise ModelSurfaceError("Selected face has invalid normal.")
    seed_normal = seed_normal / normal_len
    seed_origin = vertices[faces[face_index]].mean(axis=0)
    min_dot = math.cos(math.radians(angle_tolerance_deg))

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
    area = float(area_faces[list(selected_indices)].sum())
    return SurfaceSelection(
        face_indices=selected_indices,
        normal=tuple(float(value) for value in seed_normal),
        plane_origin=tuple(float(value) for value in seed_origin),
        area_mm2=area,
        face_count=len(selected_indices),
    )


def _build_face_adjacency(mesh: trimesh.Trimesh) -> dict[int, list[int]]:
    adjacency: dict[int, list[int]] = {}
    for left, right in np.asarray(mesh.face_adjacency, dtype=np.int64):
        adjacency.setdefault(int(left), []).append(int(right))
        adjacency.setdefault(int(right), []).append(int(left))
    return adjacency
