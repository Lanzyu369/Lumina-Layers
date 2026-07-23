from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import shapely.geometry as sg
import trimesh

from core.model_surface.types import ModelSurfaceError, SurfaceFootprint

MODEL_SURFACE_DISPLAY_Z_BOUNDS_KEY = "model_surface_display_z_bounds_mm"
MODEL_SURFACE_DISPLAY_LAYER_HEIGHTS_KEY = (
    "model_surface_display_layer_heights_mm"
)


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
    allow_uncut_base: bool = False,
) -> OverlaySceneResult:
    """Place color pattern meshes into the selected model surface frame.

    将彩色图案网格放入选中模型表面的局部坐标系。
    """

    if pocket_depth_mm <= 0.0:
        raise ModelSurfaceError("Pocket depth must be positive.")

    result_scene = trimesh.Scene()
    embed_depth_mm = _pattern_depth_mm(pattern_scene)
    available_depth_mm = _available_surface_depth_mm(base_mesh, footprint)
    if embed_depth_mm > available_depth_mm + 1e-6:
        raise ModelSurfaceError(
            "Overlay pattern depth exceeds the available model thickness "
            f"({embed_depth_mm:.3f} mm > {available_depth_mm:.3f} mm)."
        )
    display_layer_heights_mm = _pattern_layer_heights_mm(pattern_scene)
    base_copy = (
        base_mesh.copy()
        if allow_uncut_base
        else cut_surface_pocket(base_mesh, footprint, pocket_depth_mm=embed_depth_mm)
    )
    base_copy.metadata["name"] = base_slot_name
    _apply_face_color(base_copy, base_color)
    result_scene.add_geometry(base_copy, node_name=base_slot_name, geom_name=base_slot_name)

    transform = _pattern_to_surface_transform(pattern_scene, footprint, embed_depth_mm)
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
    if display_layer_heights_mm:
        result_scene.metadata[MODEL_SURFACE_DISPLAY_LAYER_HEIGHTS_KEY] = (
            display_layer_heights_mm
        )
        result_scene.metadata[MODEL_SURFACE_DISPLAY_Z_BOUNDS_KEY] = (
            _pattern_z_bounds_mm(pattern_scene)
        )
    return OverlaySceneResult(result_scene, slot_names, preview_colors)


def apply_model_transform_to_overlay_scene(
    result: OverlaySceneResult,
    model_transform: dict | None,
) -> OverlaySceneResult:
    """Apply the selected model object transform to the assembled overlay scene.

    将用户在三维预览中设置的模型对象变换应用到已合成的覆面场景。
    """

    rotation_deg = _model_rotation_degrees(model_transform)
    if all(abs(value) <= 1e-9 for value in rotation_deg):
        return result

    bounds = np.asarray(result.scene.bounds, dtype=np.float64)
    if bounds.shape != (2, 3) or not np.all(np.isfinite(bounds)):
        raise ModelSurfaceError("Overlay scene has invalid bounds.")
    anchor = np.array(
        [
            (bounds[0, 0] + bounds[1, 0]) / 2.0,
            (bounds[0, 1] + bounds[1, 1]) / 2.0,
            bounds[0, 2],
        ],
        dtype=np.float64,
    )
    matrix = _rotation_matrix_about_anchor(rotation_deg, anchor)
    transformed_scene = result.scene.copy()
    transformed_scene.apply_transform(matrix)
    return OverlaySceneResult(
        scene=transformed_scene,
        slot_names=list(result.slot_names),
        preview_colors=dict(result.preview_colors),
    )


def cut_surface_pocket(
    base_mesh: trimesh.Trimesh,
    footprint: SurfaceFootprint,
    *,
    pocket_depth_mm: float,
) -> trimesh.Trimesh:
    """Cut a shallow pocket into the selected model surface.

    在选中的模型表面切出浅口袋。
    """

    if pocket_depth_mm <= 0.0:
        raise ModelSurfaceError("Pocket depth must be positive.")

    polygon = sg.Polygon(footprint.outer, holes=list(footprint.holes))
    if not polygon.is_valid:
        polygon = polygon.buffer(0)
    if polygon.is_empty or polygon.area <= 0.0:
        raise ModelSurfaceError("Selected surface footprint is empty.")

    epsilon = min(0.02, max(0.002, pocket_depth_mm * 0.05))
    try:
        cutter = trimesh.creation.extrude_polygon(
            polygon,
            height=float(pocket_depth_mm + epsilon * 2.0),
            engine="earcut",
        )
    except Exception as exc:
        raise ModelSurfaceError("model_surface_boolean_failed") from exc

    cutter.apply_transform(
        _footprint_prism_to_surface_transform(
            footprint,
            z_offset_mm=-(float(pocket_depth_mm) + epsilon),
        )
    )
    try:
        result = trimesh.boolean.difference(
            [base_mesh.copy(), cutter],
            engine="manifold",
        )
    except Exception as exc:
        raise ModelSurfaceError("model_surface_boolean_failed") from exc

    result_mesh = _coerce_boolean_result(result)
    if result_mesh is None or len(result_mesh.faces) == 0:
        raise ModelSurfaceError("model_surface_boolean_failed")
    result_mesh.metadata.update(base_mesh.metadata or {})
    return result_mesh


def _pattern_to_surface_transform(
    pattern_scene: trimesh.Scene,
    footprint: SurfaceFootprint,
    pocket_depth_mm: float,
) -> np.ndarray:
    bounds = np.asarray(pattern_scene.bounds, dtype=np.float64)
    if bounds.shape != (2, 3) or not np.all(np.isfinite(bounds)):
        raise ModelSurfaceError("Overlay pattern scene has invalid bounds.")

    pattern_min, pattern_max = bounds
    logical_z_min, _logical_z_max = _pattern_z_bounds_mm(pattern_scene)
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
        - normal * (float(pocket_depth_mm) + logical_z_min)
    )
    return transform


def _model_rotation_degrees(model_transform: dict | None) -> tuple[float, float, float]:
    if not model_transform:
        return (0.0, 0.0, 0.0)
    rotation = model_transform.get("rotation_deg", {})
    if not isinstance(rotation, dict):
        raise ModelSurfaceError("surface_model_transform.rotation_deg must be an object.")
    try:
        return (
            float(rotation.get("x", 0.0)),
            float(rotation.get("y", 0.0)),
            float(rotation.get("z", 0.0)),
        )
    except (TypeError, ValueError) as exc:
        raise ModelSurfaceError("surface_model_transform rotation values must be numbers.") from exc


def _rotation_matrix_about_anchor(
    rotation_deg: tuple[float, float, float],
    anchor: np.ndarray,
) -> np.ndarray:
    rx, ry, rz = (np.deg2rad(value) for value in rotation_deg)
    rotation = trimesh.transformations.euler_matrix(rx, ry, rz, axes="sxyz")
    to_origin = np.eye(4)
    to_origin[:3, 3] = -anchor
    from_origin = np.eye(4)
    from_origin[:3, 3] = anchor
    return from_origin @ rotation @ to_origin


def _pattern_depth_mm(pattern_scene: trimesh.Scene) -> float:
    min_z, max_z = _pattern_z_bounds_mm(pattern_scene)
    return max_z - min_z


def _available_surface_depth_mm(
    base_mesh: trimesh.Trimesh,
    footprint: SurfaceFootprint,
) -> float:
    vertices = np.asarray(base_mesh.vertices, dtype=np.float64)
    normal = np.asarray(footprint.frame.normal, dtype=np.float64)
    origin = np.asarray(footprint.frame.origin, dtype=np.float64)
    normal_length = float(np.linalg.norm(normal))
    if vertices.size == 0 or normal_length <= 1e-9:
        raise ModelSurfaceError("Selected surface has invalid model thickness.")
    normal /= normal_length
    surface_plane = float(np.dot(origin, normal))
    inward_extent = surface_plane - float(np.min(vertices @ normal))
    if inward_extent <= 1e-6:
        raise ModelSurfaceError("Selected surface has no available model thickness.")
    return inward_extent


def _pattern_z_bounds_mm(pattern_scene: trimesh.Scene) -> tuple[float, float]:
    bounds = np.asarray(pattern_scene.bounds, dtype=np.float64)
    if bounds.shape != (2, 3) or not np.all(np.isfinite(bounds)):
        raise ModelSurfaceError("Overlay pattern scene has invalid bounds.")
    actual_min_z = float(bounds[0, 2])
    actual_max_z = float(bounds[1, 2])
    raw_bounds = pattern_scene.metadata.get(MODEL_SURFACE_DISPLAY_Z_BOUNDS_KEY)
    if raw_bounds is None:
        logical_min_z, logical_max_z = actual_min_z, actual_max_z
    else:
        try:
            logical_min_z, logical_max_z = (float(value) for value in raw_bounds)
        except (TypeError, ValueError) as exc:
            raise ModelSurfaceError("Overlay pattern logical Z bounds are invalid.") from exc
        if not np.all(np.isfinite([logical_min_z, logical_max_z])):
            raise ModelSurfaceError("Overlay pattern logical Z bounds are invalid.")
        if actual_min_z < logical_min_z - 1e-9 or actual_max_z > logical_max_z + 1e-9:
            raise ModelSurfaceError("Overlay pattern geometry exceeds its logical Z bounds.")
    if logical_max_z <= logical_min_z:
        raise ModelSurfaceError("Overlay pattern scene has invalid Z depth.")
    return logical_min_z, logical_max_z


def _pattern_layer_heights_mm(pattern_scene: trimesh.Scene) -> tuple[float, ...]:
    raw_heights = pattern_scene.metadata.get(
        MODEL_SURFACE_DISPLAY_LAYER_HEIGHTS_KEY
    )
    if raw_heights is None:
        return ()
    try:
        layer_heights = tuple(float(value) for value in raw_heights)
    except (TypeError, ValueError) as exc:
        raise ModelSurfaceError("Overlay pattern layer heights are invalid.") from exc
    if not layer_heights or not np.all(np.isfinite(layer_heights)):
        raise ModelSurfaceError("Overlay pattern layer heights are invalid.")
    if any(value <= 0.0 for value in layer_heights):
        raise ModelSurfaceError("Overlay pattern layer heights must be positive.")
    logical_min_z, logical_max_z = _pattern_z_bounds_mm(pattern_scene)
    if abs(sum(layer_heights) - (logical_max_z - logical_min_z)) > 1e-9:
        raise ModelSurfaceError(
            "Overlay pattern layer heights do not match its logical Z depth."
        )
    return layer_heights


def _footprint_prism_to_surface_transform(
    footprint: SurfaceFootprint,
    *,
    z_offset_mm: float,
) -> np.ndarray:
    u_axis = np.asarray(footprint.frame.u_axis, dtype=np.float64)
    v_axis = np.asarray(footprint.frame.v_axis, dtype=np.float64)
    normal = np.asarray(footprint.frame.normal, dtype=np.float64)
    origin = np.asarray(footprint.frame.origin, dtype=np.float64)

    transform = np.eye(4)
    transform[:3, 0] = u_axis
    transform[:3, 1] = v_axis
    transform[:3, 2] = normal
    transform[:3, 3] = origin + normal * float(z_offset_mm)
    return transform


def _coerce_boolean_result(result: object) -> trimesh.Trimesh | None:
    if isinstance(result, trimesh.Trimesh):
        return result
    if isinstance(result, list):
        meshes = [mesh for mesh in result if isinstance(mesh, trimesh.Trimesh) and len(mesh.faces) > 0]
        if meshes:
            return trimesh.util.concatenate(meshes)
    return None


def _apply_face_color(mesh: trimesh.Trimesh, rgb: tuple[int, int, int]) -> None:
    color = np.array((*rgb, 255), dtype=np.uint8)
    mesh.visual.face_colors = np.tile(color, (len(mesh.faces), 1))


def _extract_preview_color(mesh: trimesh.Trimesh) -> tuple[int, int, int]:
    rgba = getattr(mesh.visual, "face_colors", None)
    if rgba is not None and len(rgba):
        return tuple(int(value) for value in rgba[0][:3])
    return (200, 200, 200)
