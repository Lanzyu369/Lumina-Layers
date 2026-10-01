from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np
import shapely.affinity as sa
import shapely.geometry as sg
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
import trimesh

from core.layered_coordinate_domain import (
    LayeredCoordinateDomain,
    read_layered_coordinate_domain,
)
from core.model_surface.types import (
    MODEL_SURFACE_FATAL_ERRORS,
    ModelSurfaceError,
    SurfaceFootprint,
)
from core.model_surface.validation import (
    MODEL_SURFACE_INSUFFICIENT_THICKNESS,
    MODEL_SURFACE_THICKNESS_UNKNOWN,
    prepare_model_surface_mesh_for_boolean,
)

if TYPE_CHECKING:
    from manifold3d import Manifold

MODEL_SURFACE_DISPLAY_Z_BOUNDS_KEY = "model_surface_display_z_bounds_mm"
MODEL_SURFACE_DISPLAY_LAYER_HEIGHTS_KEY = (
    "model_surface_display_layer_heights_mm"
)
MODEL_SURFACE_LOGICAL_XY_BOUNDS_KEY = "model_surface_logical_xy_bounds_mm"
MODEL_SURFACE_PROJECT_SLOT_NAMES_KEY = "model_surface_project_slot_names"


@dataclass(frozen=True)
class PreparedSurfacePattern:
    """Printable pattern geometry paired with its exact local XY footprint.

    将可打印图案几何与其精确局部 XY 轮廓绑定的中间产物。
    """

    scene: trimesh.Scene
    printable_footprint: BaseGeometry

    @property
    def geometry(self) -> Mapping[str, trimesh.Trimesh]:
        """Expose scene geometry for compatibility with existing callers.

        暴露场景几何，兼容现有调用方。
        """

        return self.scene.geometry

    @property
    def metadata(self) -> dict[str, Any]:
        """Expose scene metadata for compatibility with existing callers.

        暴露场景元数据，兼容现有调用方。
        """

        return self.scene.metadata

    @property
    def bounds(self) -> np.ndarray:
        """Expose scene bounds for compatibility with existing callers.

        暴露场景包围盒，兼容现有调用方。
        """

        return self.scene.bounds


@dataclass(frozen=True)
class OverlaySceneResult:
    """Assembled model-surface overlay scene ready for export.

    可供导出的模型覆面装配场景。
    """

    scene: trimesh.Scene
    slot_names: list[str]
    preview_colors: dict[str, tuple[int, int, int]]

    @property
    def project_slot_names(self) -> list[str]:
        """Return the selected material palette independently of object names.

        返回所选材料调色板，不把对象名称当作新的材料。
        """
        selected = self.scene.metadata.get(MODEL_SURFACE_PROJECT_SLOT_NAMES_KEY)
        if selected is not None:
            return list(selected)
        materials = []
        for name in self.slot_names:
            mesh = self.scene.geometry.get(name)
            metadata = mesh.metadata if mesh is not None else {}
            materials.append(str(metadata.get("bambu_material_name") or name))
        return list(dict.fromkeys(materials))


def build_embedded_overlay_scene(
    *,
    base_mesh: trimesh.Trimesh,
    pattern_scene: PreparedSurfacePattern | trimesh.Scene,
    footprint: SurfaceFootprint,
    pocket_depth_mm: float,
    base_slot_name: str,
    base_color: tuple[int, int, int],
    allow_uncut_base: bool = False,
    _take_pattern_ownership: bool = False,
) -> OverlaySceneResult:
    """Place color pattern meshes into the selected model surface frame.

    将彩色图案网格放入选中模型表面的局部坐标系。
    """

    if pocket_depth_mm <= 0.0:
        raise ModelSurfaceError("Pocket depth must be positive.")

    prepared_pattern = _coerce_prepared_surface_pattern(pattern_scene)
    printable_scene = prepared_pattern.scene
    result_scene = trimesh.Scene()
    embed_depth_mm = _pattern_depth_mm(printable_scene)
    available_depth_mm = _available_surface_depth_mm(base_mesh, footprint)
    if embed_depth_mm > available_depth_mm + 1e-6:
        raise ModelSurfaceError(
            f"{MODEL_SURFACE_INSUFFICIENT_THICKNESS}: "
            f"pattern={embed_depth_mm:.6f}, "
            f"available={available_depth_mm:.6f}"
        )
    display_layer_heights_mm = _pattern_layer_heights_mm(printable_scene)
    display_z_bounds_mm = (
        _pattern_z_bounds_mm(printable_scene)
        if display_layer_heights_mm
        else None
    )
    base_copy = (
        base_mesh.copy()
        if allow_uncut_base
        else cut_pattern_surface_pocket(
            base_mesh,
            footprint,
            prepared_pattern,
            pocket_depth_mm=embed_depth_mm,
        )
    )
    base_copy.metadata["name"] = base_slot_name
    _apply_face_color(base_copy, base_color)
    result_scene.add_geometry(base_copy, node_name=base_slot_name, geom_name=base_slot_name)

    transform = _pattern_to_surface_transform(
        printable_scene,
        footprint,
        embed_depth_mm,
    )
    slot_names = [base_slot_name]
    preview_colors: dict[str, tuple[int, int, int]] = {base_slot_name: base_color}
    for name, mesh in printable_scene.geometry.items():
        if not isinstance(mesh, trimesh.Trimesh) or len(mesh.faces) == 0:
            continue
        mesh_copy = mesh if _take_pattern_ownership else mesh.copy()
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
            display_z_bounds_mm
        )
    return OverlaySceneResult(result_scene, slot_names, preview_colors)


def apply_model_transform_to_overlay_scene(
    result: OverlaySceneResult,
    model_transform: dict | None,
    *,
    _copy_scene: bool = True,
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
    transformed_scene = result.scene.copy() if _copy_scene else result.scene
    _apply_transform_to_scene_geometry(transformed_scene, matrix)
    return OverlaySceneResult(
        scene=transformed_scene,
        slot_names=list(result.slot_names),
        preview_colors=dict(result.preview_colors),
    )


def orient_overlay_scene_for_print(
    result: OverlaySceneResult,
    face_orientation: str,
    *,
    _copy_scene: bool = True,
) -> OverlaySceneResult:
    """Orient the assembled display face for printing.

    按打印朝向放置已装配场景；面朝下时将覆面转到底部。

    Args:
        result: Assembled model and embedded artwork.
            已装配的模型与嵌入图案。
        face_orientation: Canonical ``down`` or ``up`` orientation.
            标准化后的 ``down`` 或 ``up`` 朝向。

    Returns:
        A scene whose decorated face follows the requested print orientation.
        覆面符合所需打印朝向的场景。
    """

    normalized_orientation = str(face_orientation or "down").lower()
    if normalized_orientation == "up":
        return result
    if normalized_orientation != "down":
        raise ModelSurfaceError("Model-surface overlay requires a single display face.")

    bounds = np.asarray(result.scene.bounds, dtype=np.float64)
    if bounds.shape != (2, 3) or not np.all(np.isfinite(bounds)):
        raise ModelSurfaceError("Overlay scene has invalid bounds.")
    center = (bounds[0] + bounds[1]) / 2.0
    face_down_rotation = trimesh.transformations.rotation_matrix(
        np.pi,
        [0.0, 1.0, 0.0],
        point=center,
    )
    transformed_scene = result.scene.copy() if _copy_scene else result.scene
    _apply_transform_to_scene_geometry(transformed_scene, face_down_rotation)
    return OverlaySceneResult(
        scene=transformed_scene,
        slot_names=list(result.slot_names),
        preview_colors=dict(result.preview_colors),
    )


def _apply_transform_to_scene_geometry(
    scene: trimesh.Scene,
    matrix: np.ndarray,
) -> None:
    """Apply a transform to raw meshes consumed by the 3MF writer."""

    for geometry in scene.geometry.values():
        if isinstance(geometry, trimesh.Trimesh):
            geometry.apply_transform(matrix)


def cut_pattern_surface_pocket(
    base_mesh: trimesh.Trimesh,
    footprint: SurfaceFootprint,
    pattern: PreparedSurfacePattern,
    *,
    pocket_depth_mm: float,
) -> trimesh.Trimesh:
    """Cut a pocket only below the pattern's printable local XY footprint.

    仅在图案的实际可打印局部 XY 轮廓下方开槽。
    """

    pocket_polygon = _pattern_footprint_in_surface_coordinates(
        pattern,
        footprint,
    )
    return _cut_surface_polygon_pocket(
        base_mesh,
        footprint,
        pocket_polygon,
        pocket_depth_mm=pocket_depth_mm,
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
    return _cut_surface_polygon_pocket(
        base_mesh,
        footprint,
        polygon,
        pocket_depth_mm=pocket_depth_mm,
    )


def _cut_surface_polygon_pocket(
    base_mesh: trimesh.Trimesh,
    footprint: SurfaceFootprint,
    polygon: BaseGeometry,
    *,
    pocket_depth_mm: float,
) -> trimesh.Trimesh:
    if pocket_depth_mm <= 0.0:
        raise ModelSurfaceError("Pocket depth must be positive.")

    polygon = _coerce_polygonal_geometry(
        polygon,
        empty_error="Selected surface footprint is empty.",
    )
    epsilon = min(0.02, max(0.002, pocket_depth_mm * 0.05))
    prepared_base_mesh = prepare_model_surface_mesh_for_boolean(
        base_mesh,
        _take_ownership=True,
    )
    try:
        import manifold3d as m3d

        cutter = _build_polygon_prism(
            polygon,
            height_mm=float(pocket_depth_mm + epsilon * 2.0),
        )
        transform = _footprint_prism_to_surface_transform(
            footprint,
            z_offset_mm=-(float(pocket_depth_mm) + epsilon),
        )
        base = m3d.Manifold(m3d.Mesh64(
            np.asarray(prepared_base_mesh.vertices, dtype=np.float64),
            np.asarray(prepared_base_mesh.faces, dtype=np.uint64),
        ))
        # Export only the final solid: exporting/reimporting the intermediate
        # cutter loses native topology at tiny holes and coincident vertices.
        result = base - cutter.transform(transform[:3, :])
        if result.status() != m3d.Error.NoError or result.is_empty():
            raise ModelSurfaceError("model_surface_boolean_failed")
        mesh_data = result.to_mesh64()
        result_mesh = trimesh.Trimesh(
            vertices=np.asarray(mesh_data.vert_properties)[:, :3].copy(),
            faces=np.asarray(mesh_data.tri_verts).copy(),
            process=False,
        )
    except ModelSurfaceError:
        raise
    except MODEL_SURFACE_FATAL_ERRORS:
        raise
    except Exception as exc:
        raise ModelSurfaceError("model_surface_boolean_failed") from exc

    result_mesh.metadata.update(base_mesh.metadata or {})
    return result_mesh


def _build_polygon_prism(
    polygon: BaseGeometry,
    *,
    height_mm: float,
) -> Manifold:
    """Keep the pocket prism in its native solid representation."""

    if not np.isfinite(height_mm) or height_mm <= 0.0:
        raise ModelSurfaceError("Pocket depth must be positive.")
    components = _iter_polygon_components(polygon)
    contours = []
    for component in components:
        for ring in (component.exterior, *component.interiors):
            coordinates = np.asarray(ring.coords, dtype=np.float64)
            if coordinates.ndim != 2 or coordinates.shape[0] < 4:
                continue
            coordinates = coordinates[:-1, :2]
            if len(coordinates) >= 3 and np.all(np.isfinite(coordinates)):
                contours.append(coordinates)
    if not contours:
        raise ModelSurfaceError("Selected surface footprint is empty.")

    try:
        import manifold3d as m3d

        section = m3d.CrossSection(contours, m3d.FillRule.EvenOdd)
        solid = section.extrude(float(height_mm))
        if solid.is_empty() or solid.status() != m3d.Error.NoError:
            raise ModelSurfaceError("model_surface_boolean_failed")
        return solid
    except ModelSurfaceError:
        raise
    except MODEL_SURFACE_FATAL_ERRORS:
        raise
    except Exception as exc:
        raise ModelSurfaceError("model_surface_boolean_failed") from exc


def _coerce_prepared_surface_pattern(
    pattern: PreparedSurfacePattern | trimesh.Scene,
) -> PreparedSurfacePattern:
    if isinstance(pattern, PreparedSurfacePattern):
        printable_footprint = _coerce_polygonal_geometry(
            pattern.printable_footprint,
            empty_error="Overlay pattern printable footprint is empty.",
        )
        return PreparedSurfacePattern(pattern.scene, printable_footprint)
    if isinstance(pattern, trimesh.Scene):
        logical_bounds = _pattern_xy_bounds_mm(pattern)
        return PreparedSurfacePattern(
            pattern,
            sg.box(*logical_bounds),
        )
    raise ModelSurfaceError("Overlay pattern scene is invalid.")


def _pattern_footprint_in_surface_coordinates(
    pattern: PreparedSurfacePattern,
    footprint: SurfaceFootprint,
) -> BaseGeometry:
    logical_min_x, logical_min_y, logical_max_x, logical_max_y = (
        _pattern_xy_bounds_mm(pattern.scene)
    )
    pattern_width = logical_max_x - logical_min_x
    pattern_height = logical_max_y - logical_min_y
    scale_x = float(footprint.bounds_width_mm) / pattern_width
    scale_y = float(footprint.bounds_height_mm) / pattern_height
    min_x, min_y = footprint.bounds_min

    printable = _coerce_polygonal_geometry(
        pattern.printable_footprint,
        empty_error="Overlay pattern printable footprint is empty.",
    )
    printable_bounds = printable.bounds
    if (
        printable_bounds[0] < logical_min_x - 1e-9
        or printable_bounds[1] < logical_min_y - 1e-9
        or printable_bounds[2] > logical_max_x + 1e-9
        or printable_bounds[3] > logical_max_y + 1e-9
    ):
        raise ModelSurfaceError(
            "Overlay pattern printable footprint exceeds its logical XY bounds."
        )

    mapped = sa.affine_transform(
        printable,
        (
            scale_x,
            0.0,
            0.0,
            scale_y,
            float(min_x) - scale_x * logical_min_x,
            float(min_y) - scale_y * logical_min_y,
        ),
    )
    surface_polygon = sg.Polygon(
        footprint.outer,
        holes=list(footprint.holes),
    )
    surface_polygon = _coerce_polygonal_geometry(
        surface_polygon,
        empty_error="Selected surface footprint is empty.",
    )
    try:
        clipped = mapped.intersection(surface_polygon)
    except MODEL_SURFACE_FATAL_ERRORS:
        raise
    except Exception as exc:
        raise ModelSurfaceError("model_surface_boolean_failed") from exc
    return _coerce_polygonal_geometry(
        clipped,
        empty_error="Overlay pattern does not overlap the selected surface.",
    )


def _coerce_polygonal_geometry(
    geometry: BaseGeometry,
    *,
    empty_error: str,
) -> BaseGeometry:
    if geometry is None:
        raise ModelSurfaceError(empty_error)
    candidate = geometry
    try:
        if not candidate.is_valid:
            candidate = candidate.buffer(0)
    except MODEL_SURFACE_FATAL_ERRORS:
        raise
    except Exception as exc:
        raise ModelSurfaceError(empty_error) from exc

    components = _iter_polygon_components(candidate)
    if not components:
        raise ModelSurfaceError(empty_error)
    try:
        polygonal = (
            components[0]
            if len(components) == 1
            else unary_union(components)
        )
    except MODEL_SURFACE_FATAL_ERRORS:
        raise
    except Exception as exc:
        raise ModelSurfaceError(empty_error) from exc
    if (
        polygonal is None
        or polygonal.is_empty
        or not np.isfinite(float(polygonal.area))
        or polygonal.area <= 0.0
    ):
        raise ModelSurfaceError(empty_error)
    return polygonal


def _iter_polygon_components(
    geometry: BaseGeometry,
) -> list[sg.Polygon]:
    if geometry is None or geometry.is_empty:
        return []
    if isinstance(geometry, sg.Polygon):
        return [geometry] if geometry.area > 0.0 else []
    if isinstance(geometry, (sg.MultiPolygon, sg.GeometryCollection)):
        components: list[sg.Polygon] = []
        for child in geometry.geoms:
            components.extend(_iter_polygon_components(child))
        return components
    return []


def _pattern_to_surface_transform(
    pattern_scene: trimesh.Scene,
    footprint: SurfaceFootprint,
    pocket_depth_mm: float,
) -> np.ndarray:
    logical_min_x, logical_min_y, logical_max_x, logical_max_y = (
        _pattern_xy_bounds_mm(pattern_scene)
    )
    logical_z_min, _logical_z_max = _pattern_z_bounds_mm(pattern_scene)
    pattern_width = logical_max_x - logical_min_x
    pattern_height = logical_max_y - logical_min_y

    u_axis = np.asarray(footprint.frame.u_axis, dtype=np.float64)
    v_axis = np.asarray(footprint.frame.v_axis, dtype=np.float64)
    normal = np.asarray(footprint.frame.normal, dtype=np.float64)
    origin = np.asarray(footprint.frame.origin, dtype=np.float64)
    min_x, min_y = footprint.bounds_min
    scale_x = float(footprint.bounds_width_mm) / pattern_width
    scale_y = float(footprint.bounds_height_mm) / pattern_height

    transform = np.eye(4)
    transform[:3, 0] = u_axis * scale_x
    transform[:3, 1] = v_axis * scale_y
    transform[:3, 2] = normal
    transform[:3, 3] = (
        origin
        + u_axis * (float(min_x) - scale_x * logical_min_x)
        + v_axis * (float(min_y) - scale_y * logical_min_y)
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
        raise ModelSurfaceError(MODEL_SURFACE_THICKNESS_UNKNOWN)
    normal /= normal_length
    u_axis = np.asarray(footprint.frame.u_axis, dtype=np.float64)
    v_axis = np.asarray(footprint.frame.v_axis, dtype=np.float64)
    polygon = sg.Polygon(footprint.outer, holes=list(footprint.holes))
    if not polygon.is_valid:
        polygon = polygon.buffer(0)
    if polygon.is_empty:
        raise ModelSurfaceError(MODEL_SURFACE_THICKNESS_UNKNOWN)

    min_x, min_y, max_x, max_y = polygon.bounds
    sample_points = [polygon.representative_point(), polygon.centroid]
    for x_value in np.linspace(min_x, max_x, num=6)[1:-1]:
        for y_value in np.linspace(min_y, max_y, num=6)[1:-1]:
            point = sg.Point(float(x_value), float(y_value))
            if polygon.contains(point):
                sample_points.append(point)

    triangles = np.asarray(base_mesh.triangles, dtype=np.float64)
    inward_direction = -normal
    surface_epsilon = 1e-5
    local_depths: list[float] = []
    for point in sample_points:
        surface_point = (
            origin
            + u_axis * float(point.x)
            + v_axis * float(point.y)
        )
        ray_origin = surface_point + inward_direction * surface_epsilon
        hit_distance = _first_triangle_hit_distance(
            triangles,
            ray_origin,
            inward_direction,
        )
        if hit_distance is not None:
            local_depths.append(hit_distance + surface_epsilon)

    if not local_depths:
        raise ModelSurfaceError(MODEL_SURFACE_THICKNESS_UNKNOWN)
    return min(local_depths)


def _pattern_xy_bounds_mm(
    pattern_scene: trimesh.Scene,
) -> tuple[float, float, float, float]:
    certified_domain = _certified_pattern_domain(pattern_scene)
    if certified_domain is not None:
        return certified_domain.writer_canvas_bounds_mm

    bounds = np.asarray(pattern_scene.bounds, dtype=np.float64)
    if bounds.shape != (2, 3) or not np.all(np.isfinite(bounds)):
        raise ModelSurfaceError("Overlay pattern scene has invalid bounds.")
    actual_min_x = float(bounds[0, 0])
    actual_min_y = float(bounds[0, 1])
    actual_max_x = float(bounds[1, 0])
    actual_max_y = float(bounds[1, 1])
    raw_bounds = pattern_scene.metadata.get(MODEL_SURFACE_LOGICAL_XY_BOUNDS_KEY)
    if raw_bounds is None:
        logical_bounds = (
            actual_min_x,
            actual_min_y,
            actual_max_x,
            actual_max_y,
        )
    else:
        try:
            logical_bounds = tuple(float(value) for value in raw_bounds)
        except (TypeError, ValueError) as exc:
            raise ModelSurfaceError(
                "Overlay pattern logical XY bounds are invalid."
            ) from exc
        if len(logical_bounds) != 4 or not np.all(np.isfinite(logical_bounds)):
            raise ModelSurfaceError("Overlay pattern logical XY bounds are invalid.")

    logical_min_x, logical_min_y, logical_max_x, logical_max_y = logical_bounds
    if logical_max_x <= logical_min_x or logical_max_y <= logical_min_y:
        raise ModelSurfaceError("Overlay pattern scene has invalid logical XY size.")
    if (
        actual_min_x < logical_min_x - 1e-9
        or actual_min_y < logical_min_y - 1e-9
        or actual_max_x > logical_max_x + 1e-9
        or actual_max_y > logical_max_y + 1e-9
    ):
        raise ModelSurfaceError(
            "Overlay pattern geometry exceeds its logical XY bounds."
        )
    return logical_bounds


def _first_triangle_hit_distance(
    triangles: np.ndarray,
    ray_origin: np.ndarray,
    ray_direction: np.ndarray,
) -> float | None:
    edge_a = triangles[:, 1] - triangles[:, 0]
    edge_b = triangles[:, 2] - triangles[:, 0]
    direction = np.broadcast_to(ray_direction, edge_b.shape)
    cross_direction_edge_b = np.cross(direction, edge_b)
    determinant = np.einsum("ij,ij->i", edge_a, cross_direction_edge_b)
    valid = np.abs(determinant) > 1e-10
    inverse_determinant = np.zeros_like(determinant)
    inverse_determinant[valid] = 1.0 / determinant[valid]

    origin_delta = ray_origin - triangles[:, 0]
    barycentric_u = inverse_determinant * np.einsum(
        "ij,ij->i",
        origin_delta,
        cross_direction_edge_b,
    )
    origin_cross_edge_a = np.cross(origin_delta, edge_a)
    barycentric_v = inverse_determinant * np.einsum(
        "ij,ij->i",
        direction,
        origin_cross_edge_a,
    )
    distance = inverse_determinant * np.einsum(
        "ij,ij->i",
        edge_b,
        origin_cross_edge_a,
    )
    valid &= barycentric_u >= -1e-9
    valid &= barycentric_v >= -1e-9
    valid &= barycentric_u + barycentric_v <= 1.0 + 1e-9
    valid &= distance > 1e-6
    if not np.any(valid):
        return None
    return float(np.min(distance[valid]))


def _pattern_z_bounds_mm(pattern_scene: trimesh.Scene) -> tuple[float, float]:
    certified_domain = _certified_pattern_domain(pattern_scene)
    if certified_domain is not None:
        return certified_domain.writer_z_bounds_mm

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
    certified_domain = _certified_pattern_domain(pattern_scene)
    if certified_domain is not None:
        return certified_domain.layer_heights_mm

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


def _certified_pattern_domain(
    pattern_scene: trimesh.Scene,
) -> LayeredCoordinateDomain | None:
    """Return the producer-certified domain or preserve the legacy path."""

    try:
        return read_layered_coordinate_domain(
            pattern_scene,
            require_certified=True,
        )
    except ValueError as exc:
        raise ModelSurfaceError(
            "Overlay pattern coordinate-domain metadata is invalid."
        ) from exc


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


def _apply_face_color(mesh: trimesh.Trimesh, rgb: tuple[int, int, int]) -> None:
    color = np.array((*rgb, 255), dtype=np.uint8)
    mesh.visual.face_colors = np.tile(color, (len(mesh.faces), 1))


def _extract_preview_color(mesh: trimesh.Trimesh) -> tuple[int, int, int]:
    rgba = getattr(mesh.visual, "face_colors", None)
    if rgba is not None and len(rgba):
        return tuple(int(value) for value in rgba[0][:3])
    return (200, 200, 200)
