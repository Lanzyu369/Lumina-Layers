from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import trimesh

from core.model_surface.types import ModelSurfaceError, SurfaceFootprint


@dataclass(frozen=True)
class OverlaySceneResult:
    """Assembled model-surface overlay scene ready for export.

    可供导出的模型覆面装配场景。
    """

    scene: trimesh.Scene
    slot_names: list[str]
    preview_colors: dict[str, tuple[int, int, int]]


def build_embedded_overlay_scene(
    *,
    base_mesh: trimesh.Trimesh,
    pattern_scene: trimesh.Scene,
    footprint: SurfaceFootprint,
    pocket_depth_mm: float,
    base_slot_name: str,
    base_color: tuple[int, int, int],
) -> OverlaySceneResult:
    """Place color pattern meshes into the selected model surface frame.

    将彩色图案网格放入选中模型表面的局部坐标系。
    """

    if pocket_depth_mm <= 0.0:
        raise ModelSurfaceError("Pocket depth must be positive.")

    result_scene = trimesh.Scene()
    base_copy = base_mesh.copy()
    base_copy.metadata["name"] = base_slot_name
    _apply_face_color(base_copy, base_color)
    result_scene.add_geometry(base_copy, node_name=base_slot_name, geom_name=base_slot_name)

    transform = _pattern_to_surface_transform(pattern_scene, footprint, pocket_depth_mm)
    slot_names = [base_slot_name]
    preview_colors: dict[str, tuple[int, int, int]] = {base_slot_name: base_color}
    for name, mesh in pattern_scene.geometry.items():
        if not isinstance(mesh, trimesh.Trimesh) or len(mesh.faces) == 0:
            continue
        mesh_copy = mesh.copy()
        mesh_copy.apply_transform(transform)
        mesh_copy.metadata["name"] = str(name)
        result_scene.add_geometry(mesh_copy, node_name=str(name), geom_name=str(name))
        slot_names.append(str(name))
        preview_colors[str(name)] = _extract_preview_color(mesh_copy)

    if len(slot_names) == 1:
        raise ModelSurfaceError("Overlay pattern scene contains no printable color meshes.")
    return OverlaySceneResult(result_scene, slot_names, preview_colors)


def _pattern_to_surface_transform(
    pattern_scene: trimesh.Scene,
    footprint: SurfaceFootprint,
    pocket_depth_mm: float,
) -> np.ndarray:
    bounds = np.asarray(pattern_scene.bounds, dtype=np.float64)
    if bounds.shape != (2, 3) or not np.all(np.isfinite(bounds)):
        raise ModelSurfaceError("Overlay pattern scene has invalid bounds.")

    pattern_min, pattern_max = bounds
    pattern_size = pattern_max - pattern_min
    if pattern_size[0] <= 0.0 or pattern_size[1] <= 0.0:
        raise ModelSurfaceError("Overlay pattern scene has invalid XY size.")

    u_axis = np.asarray(footprint.frame.u_axis, dtype=np.float64)
    v_axis = np.asarray(footprint.frame.v_axis, dtype=np.float64)
    normal = np.asarray(footprint.frame.normal, dtype=np.float64)
    origin = np.asarray(footprint.frame.origin, dtype=np.float64)
    min_x, min_y = footprint.bounds_min
    scale_x = float(footprint.bounds_width_mm) / float(pattern_size[0])
    scale_y = float(footprint.bounds_height_mm) / float(pattern_size[1])

    transform = np.eye(4)
    transform[:3, 0] = u_axis * scale_x
    transform[:3, 1] = v_axis * scale_y
    transform[:3, 2] = normal
    transform[:3, 3] = (
        origin
        + u_axis * (float(min_x) - scale_x * float(pattern_min[0]))
        + v_axis * (float(min_y) - scale_y * float(pattern_min[1]))
        - normal * (float(pocket_depth_mm) + float(pattern_min[2]))
    )
    return transform


def _apply_face_color(mesh: trimesh.Trimesh, rgb: tuple[int, int, int]) -> None:
    color = np.array((*rgb, 255), dtype=np.uint8)
    mesh.visual.face_colors = np.tile(color, (len(mesh.faces), 1))


def _extract_preview_color(mesh: trimesh.Trimesh) -> tuple[int, int, int]:
    rgba = getattr(mesh.visual, "face_colors", None)
    if rgba is not None and len(rgba):
        return tuple(int(value) for value in rgba[0][:3])
    return (200, 200, 200)
