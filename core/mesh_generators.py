"""
Lumina Studio - Mesh Generation Strategies (Refactored v2.2)
Mesh generation strategy module - Refactored version

ARCHITECTURE:
- High-Fidelity Mode: exact labeled surfaces with optional material dilation
- Pixel Art Mode: exact labeled surfaces without material dilation

TOPOLOGY: Same-material cells share one exposed surface; edge/point-only
contacts retain independent closed index domains.

The polygon extrusion adapter remains only for non-grid boundary fragments.
"""

import logging
from abc import ABC, abstractmethod

import cv2
import numpy as np
import trimesh
from shapely.affinity import affine_transform
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon, box
from shapely.ops import unary_union

from config import ModelingMode
from core.layered_meshing import (
    build_labeled_surface_mesh,
    merge_boolean_rectangles,
)
from core.mesh_export_parts import (
    copy_mesh_export_part_ranges,
    set_concatenated_mesh_export_part_ranges,
)
from core.vector_engine import VectorProcessor
from core.vector_mesh_topology import (
    VECTOR_COVERAGE_ABS_TOL_MM2,
    VECTOR_COVERAGE_REL_TOL,
)

log = logging.getLogger(__name__)


def _normalize_polygonal_geometry(geometry):
    """Normalize polygonal geometry and drop non-polygon parts.
    规范化多边形几何并丢弃非多边形部分。
    """
    if geometry is None or getattr(geometry, "is_empty", True):
        return None

    candidate = geometry.buffer(0) if not geometry.is_valid else geometry
    if candidate.is_empty:
        return None
    if isinstance(candidate, Polygon):
        return candidate
    if isinstance(candidate, MultiPolygon):
        return candidate
    if isinstance(candidate, GeometryCollection):
        parts = [
            part
            for part in candidate.geoms
            if isinstance(part, (Polygon, MultiPolygon)) and not part.is_empty
        ]
        if not parts:
            return None
        return _normalize_polygonal_geometry(unary_union(parts))
    return None


def _iter_polygon_parts(geometry):
    """Yield individual polygon parts from arbitrary polygonal geometry.
    将任意多边形几何展开为单独 Polygon 片段。
    """
    normalized = _normalize_polygonal_geometry(geometry)
    if normalized is None:
        return ()
    if isinstance(normalized, Polygon):
        return (normalized,)
    if isinstance(normalized, MultiPolygon):
        return tuple(part for part in normalized.geoms if not part.is_empty)
    return ()


def _flip_geometry_to_world(geometry, height_px):
    """Flip a y-down pixel-space geometry into y-up world coordinates.
    将 y 向下的像素空间几何翻转到 y 向上的世界坐标。
    """
    normalized = _normalize_polygonal_geometry(geometry)
    if normalized is None:
        return None
    world = affine_transform(
        normalized,
        [1.0, 0.0, 0.0, -1.0, 0.0, float(height_px)],
    )
    return _normalize_polygonal_geometry(world)


def _merge_mesh_list(meshes):
    """Concatenate meshes while retaining independent closed shells.
    合并 mesh，同时保留各自独立的闭合壳体。
    """
    clean_meshes = [mesh for mesh in meshes if mesh is not None and len(mesh.faces) > 0]
    if not clean_meshes:
        return None

    # Adjacent prisms intentionally keep separate vertex indices. Welding
    # their coincident coordinates without removing both internal walls first
    # creates edges referenced by more than two triangles.
    if len(clean_meshes) == 1:
        return clean_meshes[0]
    combined = trimesh.util.concatenate(clean_meshes)
    set_concatenated_mesh_export_part_ranges(combined, clean_meshes)
    return combined


def _extrude_polygon_geometry(geometry, height, z_offset, extrude_cache=None):
    """Extrude polygonal geometry into 3D meshes.
    将多边形几何挤出为 3D mesh。
    """
    meshes = []
    if geometry is None or geometry.is_empty:
        return meshes

    for poly in _iter_polygon_parts(geometry):
        if poly.is_empty or getattr(poly, "area", 0.0) <= 0.0:
            continue

        cache_key = None
        cached_base = None
        if extrude_cache is not None:
            cache_key = (poly.wkb, round(float(height), 8))
            cached_base = extrude_cache.get(cache_key)

        if cached_base is None:
            try:
                base_meshes = VectorProcessor._extrude_geometry(
                    poly,
                    height=1.0,
                    z_offset=0.0,
                    scale=1.0,
                    extrude_cache=None,
                )
                if not base_meshes:
                    raise ValueError("indexed polygon extrusion returned no mesh")
                base_mesh = _merge_mesh_list(base_meshes)
                if base_mesh is None:
                    raise ValueError("indexed polygon extrusion returned no mesh")
            except (ValueError, TypeError, RuntimeError, AttributeError, OSError) as exc:
                log.warning(
                    "Failed to extrude polygon: %s",
                    exc,
                    extra={"event": "polygon_extrusion_failed", "error_type": type(exc).__name__},
                )
                raise ValueError(
                    "Raster boundary polygon extrusion failed; refusing partial export"
                ) from exc
            if not bool(base_mesh.is_watertight):
                raise ValueError(
                    "Raster boundary polygon extrusion produced non-manifold topology"
                )
            expected_volume = float(poly.area)
            actual_volume = abs(float(base_mesh.volume))
            # VectorProcessor may remove float32-collapsed duplicate vertices
            # after proving that the resulting area remains inside the shared
            # export bound.  Reuse that same bound here so the raster wrapper
            # does not reject an already-validated normalization.
            coverage_tolerance = max(
                VECTOR_COVERAGE_ABS_TOL_MM2,
                expected_volume * VECTOR_COVERAGE_REL_TOL,
            )
            if actual_volume + coverage_tolerance < expected_volume:
                raise ValueError(
                    "Raster boundary polygon extrusion coverage incomplete; "
                    "refusing partial export"
                )
            if extrude_cache is not None and cache_key is not None:
                cached_copy = base_mesh.copy()
                copy_mesh_export_part_ranges(base_mesh, cached_copy)
                extrude_cache[cache_key] = cached_copy
            cached_base = base_mesh

        mesh = cached_base.copy()
        copy_mesh_export_part_ranges(cached_base, mesh)
        mesh.apply_scale([1.0, 1.0, float(height)])
        mesh.apply_translation([0.0, 0.0, float(z_offset)])
        meshes.append(mesh)

    return meshes


def _merge_layers_no_dilation(voxel_matrix, mat_id):
    """Group consecutive Z-layers with identical masks (no dilation).
    将连续相同掩码的 Z 层合并为组（不做膨胀）。
    """
    layer_groups = []
    prev_mask = None
    start_z = 0
    for z in range(voxel_matrix.shape[0]):
        curr_mask = voxel_matrix[z] == mat_id
        if not np.any(curr_mask):
            if prev_mask is not None:
                layer_groups.append((start_z, z - 1, prev_mask))
                prev_mask = None
            continue
        if prev_mask is None:
            start_z = z
            prev_mask = curr_mask
        elif np.array_equal(curr_mask, prev_mask):
            pass
        else:
            layer_groups.append((start_z, z - 1, prev_mask))
            start_z = z
            prev_mask = curr_mask
    if prev_mask is not None:
        layer_groups.append((start_z, voxel_matrix.shape[0] - 1, prev_mask))
    return layer_groups


def _mask_volume_from_layer_groups(layer_groups, shape):
    """Expand merged masks into an exact boolean Z/Y/X volume.
    将合并后的掩码组还原为精确的 Z/Y/X 布尔体。
    """

    mask_volume = np.zeros(shape, dtype=bool)
    for start_z, end_z, mask in layer_groups:
        mask_volume[start_z : end_z + 1] = mask
    return mask_volume


def _dilate_mask_preserving_enclosed_voids(mask, kernel):
    """Dilate into exterior background while keeping enclosed voids open."""
    if not np.any(mask):
        return mask

    mask_uint8 = mask.astype(np.uint8)
    dilated_mask = cv2.dilate(mask_uint8, kernel, iterations=1).astype(bool)

    background = (~mask).astype(np.uint8)
    if not np.any(background):
        return dilated_mask

    _, labels = cv2.connectedComponents(background, connectivity=8)
    border_labels = np.unique(
        np.concatenate((labels[0, :], labels[-1, :], labels[:, 0], labels[:, -1]))
    )
    exterior_background = np.isin(labels, border_labels)
    enclosed_voids = background.astype(bool) & ~exterior_background
    if not np.any(enclosed_voids):
        return dilated_mask

    return dilated_mask & ~enclosed_voids


class BaseMesher(ABC):
    """Mesh generator abstract base class"""

    @abstractmethod
    def generate_mesh(self, voxel_matrix, mat_id, height_px):
        """
        Generate 3D mesh for specified material

        Args:
            voxel_matrix: (Z, H, W) voxel matrix
            mat_id: Material ID (0-7 for regular materials, -2 for backing layer)
            height_px: Image height (pixels)

        Returns:
            trimesh.Trimesh or None
        """
        pass

    def generate_backing_mesh(self, voxel_matrix, height_px):
        """
        Generate backing mesh (convenience method)

        Args:
            voxel_matrix: (Z, H, W) voxel matrix
            height_px: Image height (pixels)

        Returns:
            trimesh.Trimesh or None
        """
        return self.generate_mesh(voxel_matrix, mat_id=-2, height_px=height_px)

    @staticmethod
    def _greedy_rect_merge(mask):
        """Greedy rectangle merging on a 2D boolean mask.
        贪婪矩形合并（2D 布尔掩码）。

        Args:
            mask (np.ndarray): (H, W) bool array. (布尔掩码)

        Returns:
            np.ndarray: (R, 4) float64 array of rectangles [x0, y0, x1, y1].
                (矩形数组，像素坐标)
        """
        return merge_boolean_rectangles(mask).astype(np.float64, copy=False)

    @staticmethod
    def _merge_layers_no_dilation(voxel_matrix, mat_id):
        """Group consecutive Z-layers with identical masks (no dilation).
        将连续相同掩码的 Z 层合并为组（不做膨胀）。
        """
        return _merge_layers_no_dilation(voxel_matrix, mat_id)

    def _build_mesh_from_layer_polygons(self, layer_polygons, height_px):
        """Build trimesh from list of (z_bottom, z_top, geometry) tuples.
        从层多边形列表构建 trimesh。
        """
        meshes = []
        extrude_cache = {}

        for z_bottom, z_top, geometry in layer_polygons:
            if geometry is None or geometry.is_empty:
                continue

            height = float(z_top - z_bottom)
            if height <= 0:
                continue

            world_geometry = _flip_geometry_to_world(geometry, height_px)
            if world_geometry is None or world_geometry.is_empty:
                continue

            meshes.extend(
                _extrude_polygon_geometry(
                    world_geometry,
                    height,
                    z_bottom,
                    extrude_cache=extrude_cache,
                )
            )

        return _merge_mesh_list(meshes)


class VoxelMesher(BaseMesher):
    """
    Pixel art mode mesh generator
    Builds one exact exposed surface from the material label volume.
    """

    def generate_mesh(self, voxel_matrix, mat_id, height_px):
        """Generate a pixel-mode exact labeled surface.
        生成像素模式的精确标签表面。

        Args:
            voxel_matrix (np.ndarray): (Z, H, W) int voxel matrix.
            mat_id (int): Material ID (0-7 or -2 for backing).
            height_px (int): Image height in pixels.

        Returns:
            trimesh.Trimesh or None
        """
        mesh_type = "Backing" if mat_id == -2 else f"Mat ID {mat_id}"
        mesh = build_labeled_surface_mesh(
            np.asarray(voxel_matrix),
            material_id=mat_id,
            height_px=height_px,
        )
        if mesh is not None:
            patch_count = int(
                mesh.metadata["layered_mesh_stats"]["merged_patch_count"]
            )
            log.info(
                "%s: built exact surface from %s patches",
                mesh_type,
                patch_count,
                extra={
                    "event": "voxel_mesher_mesh_built",
                    "mesh_type": mesh_type,
                    "patch_count": patch_count,
                    "vertex_count": len(mesh.vertices),
                    "face_count": len(mesh.faces),
                },
            )
        return mesh

    @staticmethod
    def _merge_layers_no_dilation(voxel_matrix, mat_id):
        """Group consecutive Z-layers with identical masks (no dilation).
        将连续相同掩码的 Z 层合并为组（不做膨胀）。"""
        return _merge_layers_no_dilation(voxel_matrix, mat_id)


class HighFidelityMesher(BaseMesher):
    """
    High-fidelity mode mesh generator
    Builds an optimized closed surface after optional material dilation.

    ALGORITHM:
    1. Apply morphological dilation to thicken thin features
    2. Reconstruct the effective labeled volume
    3. Emit only exposed faces and merge coplanar cells
    4. Preserve independent index domains for edge/point-only contacts

    OPTIMIZATION:
    - Removes internal faces between same-material cells
    - Triangulates split rectangular boundaries without extra center vertices

    GEOMETRY:
    - Dilation: Expands features by ~0.1-0.15mm to ensure printability
    - Exact edge-to-edge topology on an integer lattice
    - Vertices match pixel coordinates exactly
    """

    def __init__(self, disable_material_dilation: bool = False, boundary_geometry=None):
        """Create a configurable high-fidelity mesher.
        创建可配置的高保真 mesher。

        Args:
            disable_material_dilation: If True, skip per-material dilation.
                (若为 True，则跳过每材质膨胀)
            boundary_geometry: Optional polygonal boundary in pixel space.
                (可选的像素空间 polygon 边界)
        """
        self.disable_material_dilation = bool(disable_material_dilation)
        self.boundary_geometry = _normalize_polygonal_geometry(boundary_geometry)

    @staticmethod
    def _log_boundary_clip_fallback(exc, rect, mat_id):
        """Emit structured logging when polygon clipping falls back to rect extrusion.
        在多边形裁剪回退到矩形挤出时输出结构化日志。
        """
        x0, y0, x1, y1 = (float(value) for value in rect)
        log.warning(
            "Boundary clip fallback for material %s rect=(%.3f, %.3f, %.3f, %.3f): %s",
            mat_id,
            x0,
            y0,
            x1,
            y1,
            exc,
            extra={
                "event": "boundary_polygon_clip_fallback",
                "material_id": mat_id,
                "rect": [x0, y0, x1, y1],
                "error_type": type(exc).__name__,
            },
        )

    def generate_mesh(
        self,
        voxel_matrix,
        mat_id,
        height_px,
        boundary_geometry=None,
        disable_material_dilation=None,
    ):
        """Generate a high-fidelity exact surface with optional dilation.
        生成可选膨胀的高保真精确表面。

        Args:
            voxel_matrix (np.ndarray): (Z, H, W) int voxel matrix.
            mat_id (int): Material ID (0-7 or -2 for backing).
            height_px (int): Image height in pixels.

        Returns:
            trimesh.Trimesh or None
        """
        boundary_geometry = (
            self.boundary_geometry
            if boundary_geometry is None
            else _normalize_polygonal_geometry(boundary_geometry)
        )
        use_no_dilation = (
            self.disable_material_dilation
            if disable_material_dilation is None
            else bool(disable_material_dilation)
        )
        boundary_enabled = boundary_geometry is not None

        if use_no_dilation and not boundary_enabled:
            layer_groups = None
        elif use_no_dilation:
            layer_groups = self._merge_layers_no_dilation(voxel_matrix, mat_id)
        else:
            layer_groups = self._merge_layers_with_dilation(voxel_matrix, mat_id)
        if layer_groups is not None and not layer_groups:
            return None

        mesh_type = "Backing" if mat_id == -2 else f"Mat ID {mat_id}"
        grid_mesh = None
        polygon_mesh = None
        boundary_polygon_count = 0
        if layer_groups is not None:
            log.info(
                "%s: merged %s layers into %s groups%s%s",
                mesh_type,
                voxel_matrix.shape[0],
                len(layer_groups),
                " [no-dilation]" if use_no_dilation else "",
                " [boundary-aware]" if boundary_enabled else "",
                extra={
                    "event": "mesh_layers_merged",
                    "mesh_type": mesh_type,
                    "layer_count": int(voxel_matrix.shape[0]),
                    "group_count": len(layer_groups),
                    "no_dilation": use_no_dilation,
                    "boundary_enabled": boundary_enabled,
                },
            )

        if not boundary_enabled:
            if use_no_dilation:
                effective_volume = np.asarray(voxel_matrix)
                effective_material_id = mat_id
            else:
                effective_volume = _mask_volume_from_layer_groups(
                    layer_groups,
                    np.asarray(voxel_matrix).shape,
                )
                effective_material_id = True
            grid_mesh = build_labeled_surface_mesh(
                effective_volume,
                material_id=effective_material_id,
                height_px=height_px,
            )
            mesh = grid_mesh
        else:
            interior_volume = np.zeros(np.asarray(voxel_matrix).shape, dtype=bool)
            layer_polygons = []
            for start_z, end_z, mask in layer_groups:
                rects = self._greedy_rect_merge(mask)
                if rects.shape[0] == 0:
                    continue

                clipped_geoms = []
                for rect in rects:
                    x0, y0, x1, y1 = rect
                    rect_geom = box(float(x0), float(y0), float(x1), float(y1))
                    try:
                        clipped = _normalize_polygonal_geometry(
                            rect_geom.intersection(boundary_geometry)
                        )
                    except (
                        ValueError,
                        TypeError,
                        RuntimeError,
                        AttributeError,
                        OSError,
                    ) as exc:
                        self._log_boundary_clip_fallback(exc, rect, mat_id)
                        interior_volume[
                            start_z : end_z + 1,
                            int(y0) : int(y1),
                            int(x0) : int(x1),
                        ] = True
                        continue
                    if clipped is None or clipped.is_empty:
                        continue
                    if clipped.equals(rect_geom):
                        interior_volume[
                            start_z : end_z + 1,
                            int(y0) : int(y1),
                            int(x0) : int(x1),
                        ] = True
                    else:
                        clipped_geoms.append(clipped)

                if clipped_geoms:
                    layer_polygons.append(
                        (
                            float(start_z),
                            float(end_z + 1),
                            _normalize_polygonal_geometry(
                                unary_union(clipped_geoms)
                            ),
                        )
                    )

            grid_mesh = build_labeled_surface_mesh(
                interior_volume,
                material_id=True,
                height_px=height_px,
            )
            boundary_polygon_count = sum(
                len(_iter_polygon_parts(geometry))
                for _start_z, _end_z, geometry in layer_polygons
            )
            polygon_mesh = (
                self._build_mesh_from_layer_polygons(layer_polygons, height_px)
                if layer_polygons
                else None
            )
            mesh = _merge_mesh_list([grid_mesh, polygon_mesh])
        if mesh is not None:
            lattice_stats = (
                grid_mesh.metadata.get("layered_mesh_stats", {})
                if grid_mesh is not None
                else {}
            )
            if not isinstance(lattice_stats, dict):
                lattice_stats = {}
            lattice_patch_count = int(
                lattice_stats.get("merged_patch_count", 0)
            )
            patch_count = lattice_patch_count + boundary_polygon_count
            if polygon_mesh is not None:
                mesh.metadata.pop("integer_topology_scale", None)
                if lattice_stats:
                    mesh.metadata["layered_mesh_stats"] = dict(lattice_stats)
                else:
                    mesh.metadata.pop("layered_mesh_stats", None)
            mesh.metadata["raster_surface_stats"] = {
                "patch_count": patch_count,
                "lattice_patch_count": lattice_patch_count,
                "boundary_polygon_count": boundary_polygon_count,
                "boundary_adapter_used": bool(polygon_mesh is not None),
                "boundary_enabled": boundary_enabled,
                "material_dilation_applied": not use_no_dilation,
            }
            log.info(
                "%s: built high-fidelity surface from %s patches",
                mesh_type,
                patch_count,
                extra={
                    "event": "high_fidelity_mesh_built",
                    "mesh_type": mesh_type,
                    "patch_count": patch_count,
                    "vertex_count": len(mesh.vertices),
                    "face_count": len(mesh.faces),
                },
            )
        return mesh

    def _merge_layers_with_dilation(self, voxel_matrix, mat_id):
        """
        Merge identical vertical layers and apply morphological dilation

        Groups consecutive Z-layers with identical masks to reduce geometry.
        Applies morphological dilation to ensure thin features are printable.

        Returns:
            list of tuples: [(start_z, end_z, dilated_mask), ...]
        """
        kernel = np.ones((3, 3), np.uint8)

        layer_groups = []
        prev_mask = None
        start_z = 0

        for z in range(voxel_matrix.shape[0]):
            curr_mask = voxel_matrix[z] == mat_id

            if not np.any(curr_mask):
                if prev_mask is not None and np.any(prev_mask):
                    layer_groups.append((start_z, z - 1, prev_mask))
                    prev_mask = None
                continue

            dilated_mask = _dilate_mask_preserving_enclosed_voids(curr_mask, kernel)

            if prev_mask is None:
                start_z = z
                prev_mask = dilated_mask.copy()
            elif np.array_equal(dilated_mask, prev_mask):
                pass
            else:
                layer_groups.append((start_z, z - 1, prev_mask))
                start_z = z
                prev_mask = dilated_mask.copy()

        if prev_mask is not None and np.any(prev_mask):
            layer_groups.append((start_z, voxel_matrix.shape[0] - 1, prev_mask))

        return layer_groups


# ========== Factory Method ==========


def get_mesher(
    mode_name: ModelingMode,
    disable_material_dilation: bool = False,
    boundary_geometry=None,
):
    """
    Return corresponding Mesher instance based on mode name

    Args:
        mode_name: ModelingMode enum value
            - ModelingMode.HIGH_FIDELITY → HighFidelityMesher
            - ModelingMode.PIXEL → VoxelMesher
            - ModelingMode.VECTOR → HighFidelityMesher (vector uses same algorithm)

    Returns:
        BaseMesher instance
    """
    # High-Fidelity mode (replaces Vector and Woodblock)
    if mode_name == ModelingMode.HIGH_FIDELITY:
        log.info(
            "Selected HighFidelityMesher",
            extra={
                "event": "mesher_selected",
                "mode": str(mode_name),
                "mesher": "HighFidelityMesher",
            },
        )
        return HighFidelityMesher(
            disable_material_dilation=disable_material_dilation,
            boundary_geometry=boundary_geometry,
        )

    # Vector mode uses same algorithm as High-Fidelity
    if mode_name == ModelingMode.VECTOR:
        log.info(
            "Selected HighFidelityMesher for vector mode",
            extra={
                "event": "mesher_selected",
                "mode": str(mode_name),
                "mesher": "HighFidelityMesher",
            },
        )
        return HighFidelityMesher(
            disable_material_dilation=disable_material_dilation,
            boundary_geometry=boundary_geometry,
        )

    # Pixel Art mode (legacy voxel)
    if mode_name == ModelingMode.PIXEL:
        log.info(
            "Selected VoxelMesher",
            extra={"event": "mesher_selected", "mode": str(mode_name), "mesher": "VoxelMesher"},
        )
        return VoxelMesher()

    # Default fallback to High-Fidelity
    log.info(
        "Unknown mode; defaulting to HighFidelityMesher",
        extra={
            "event": "mesher_defaulted",
            "mode": str(mode_name),
            "mesher": "HighFidelityMesher",
        },
    )
    return HighFidelityMesher(
        disable_material_dilation=disable_material_dilation,
        boundary_geometry=boundary_geometry,
    )
