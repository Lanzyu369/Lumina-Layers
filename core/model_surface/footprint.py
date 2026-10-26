from __future__ import annotations

import numpy as np
import shapely.geometry as sg
import shapely.ops as so
import trimesh

from core.model_surface.types import ModelSurfaceError, PlaneFrame, SurfaceFootprint


def build_surface_footprint(
    mesh: trimesh.Trimesh,
    face_indices: tuple[int, ...],
) -> SurfaceFootprint:
    """Project selected mesh faces into a 2D footprint with holes.

    将选中的模型面片投影为带孔洞信息的二维轮廓。

    Args:
        mesh: Source triangle mesh.
            源三角网格。
        face_indices: Selected face indices that belong to one planar surface.
            属于同一平面的已选面索引。

    Returns:
        Two-dimensional footprint in the selected plane's local frame.
        选中平面局部坐标系中的二维轮廓。

    Raises:
        ModelSurfaceError: If the selection is empty or cannot form a valid
            polygon.
            当选择为空或无法形成有效多边形时抛出。
    """

    if not face_indices:
        raise ModelSurfaceError("Surface selection is empty.")

    frame = _frame_from_faces(mesh, face_indices)
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    selected_faces = faces[list(face_indices)]
    projected = _project(frame, vertices[selected_faces.reshape(-1)]).reshape((-1, 3, 2))

    polygons = []
    for triangle in projected:
        polygon = sg.Polygon(triangle)
        if polygon.area > 1e-9:
            polygons.append(polygon)
    if not polygons:
        raise ModelSurfaceError("Selected surface footprint is empty.")

    merged = so.unary_union(polygons)
    if not merged.is_valid:
        merged = merged.buffer(0)
    if merged.geom_type == "MultiPolygon":
        merged = max(merged.geoms, key=lambda geometry: geometry.area)
    if not isinstance(merged, sg.Polygon) or merged.area <= 0.0:
        raise ModelSurfaceError("Selected surface footprint is invalid.")

    minx, miny, maxx, maxy = merged.bounds
    return SurfaceFootprint(
        frame=frame,
        outer=tuple((float(x), float(y)) for x, y in merged.exterior.coords),
        holes=tuple(
            tuple((float(x), float(y)) for x, y in ring.coords)
            for ring in merged.interiors
        ),
        bounds_min=(float(minx), float(miny)),
        bounds_max=(float(maxx), float(maxy)),
        bounds_width_mm=float(maxx - minx),
        bounds_height_mm=float(maxy - miny),
        area_mm2=float(merged.area),
        hole_count=len(merged.interiors),
        face_indices=tuple(int(index) for index in face_indices),
    )


def _frame_from_faces(mesh: trimesh.Trimesh, face_indices: tuple[int, ...]) -> PlaneFrame:
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    points = vertices[faces[list(face_indices)].reshape(-1)]
    origin = points.mean(axis=0)

    normal = np.asarray(mesh.face_normals[list(face_indices)], dtype=np.float64).mean(axis=0)
    normal_len = float(np.linalg.norm(normal))
    if normal_len <= 0.0:
        raise ModelSurfaceError("Selected surface has invalid normal.")
    normal = normal / normal_len

    u_axis = _project_axis_onto_plane(np.array([1.0, 0.0, 0.0]), normal)
    if u_axis is None:
        u_axis = _project_axis_onto_plane(np.array([0.0, 1.0, 0.0]), normal)
    if u_axis is None:
        raise ModelSurfaceError("Selected surface frame is invalid.")
    v_axis = np.cross(normal, u_axis)
    v_axis = v_axis / np.linalg.norm(v_axis)

    return PlaneFrame(
        origin=tuple(float(value) for value in origin),
        normal=tuple(float(value) for value in normal),
        u_axis=tuple(float(value) for value in u_axis),
        v_axis=tuple(float(value) for value in v_axis),
    )


def _project_axis_onto_plane(axis: np.ndarray, normal: np.ndarray) -> np.ndarray | None:
    projected = axis - float(np.dot(axis, normal)) * normal
    length = float(np.linalg.norm(projected))
    if length <= 1e-9:
        return None
    return projected / length


def _project(frame: PlaneFrame, points: np.ndarray) -> np.ndarray:
    origin = np.asarray(frame.origin, dtype=np.float64)
    u_axis = np.asarray(frame.u_axis, dtype=np.float64)
    v_axis = np.asarray(frame.v_axis, dtype=np.float64)
    relative = points - origin
    return np.column_stack([relative @ u_axis, relative @ v_axis])
