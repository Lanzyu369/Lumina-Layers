"""
Lumina Studio - Mesh Generation Strategies (Refactored v2.2)
Mesh generation strategy module - Refactored version

ARCHITECTURE:
- High-Fidelity Mode: RLE-based solid extrusion with morphological dilation
- Pixel Art Mode: Legacy voxel mesher (blocky aesthetic with gaps)

PERFORMANCE: Optimized for 100k+ faces with instant generation.

CHANGELOG v2.2:
- Vectorized _greedy_rect_merge using NumPy operations
- np.diff + np.where replaces pixel-by-pixel horizontal scanning
- np.all on slices replaces inner for-loop for vertical expansion
- ~10-50x faster for large images (1000x1000+)

CHANGELOG v2.1:
- Added morphological dilation to HighFidelityMesher to fix thin wall issues
- Ensures all features are printable (>0.4mm nozzle width)
- Eliminates micro-gaps between adjacent color regions
"""

from abc import ABC, abstractmethod
import logging
import numpy as np
import cv2
import trimesh
from shapely.affinity import affine_transform
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon, box
from shapely.ops import unary_union
from config import ModelingMode
from core.vector_engine import VectorProcessor
from core.vector_mesh_topology import (
    VECTOR_COVERAGE_ABS_TOL_MM2,
    VECTOR_COVERAGE_REL_TOL,
)

try:
    import numba

    HAS_NUMBA = True
except ImportError:
    numba = None
    HAS_NUMBA = False

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
        parts = [part for part in candidate.geoms if isinstance(part, (Polygon, MultiPolygon)) and not part.is_empty]
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
    world = affine_transform(normalized, [1.0, 0.0, 0.0, -1.0, 0.0, float(height_px)])
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
    return trimesh.util.concatenate(clean_meshes) if len(clean_meshes) > 1 else clean_meshes[0]


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
                extrude_cache[cache_key] = base_mesh.copy()
            cached_base = base_mesh

        mesh = cached_base.copy()
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


if HAS_NUMBA:

    @numba.njit(cache=True)
    def _greedy_rect_numba(mask):
        h, w = mask.shape
        processed = np.zeros((h, w), dtype=np.uint8)
        rects = np.empty((h * w, 4), dtype=np.int32)
        count = 0

        for y in range(h):
            x = 0
            while x < w:
                if mask[y, x] and processed[y, x] == 0:
                    x_start = x
                    x_end = x + 1
                    while x_end < w and mask[y, x_end] and processed[y, x_end] == 0:
                        x_end += 1

                    y_end = y + 1
                    while y_end < h:
                        valid = 1
                        for xx in range(x_start, x_end):
                            if (not mask[y_end, xx]) or processed[y_end, xx] != 0:
                                valid = 0
                                break
                        if valid == 0:
                            break
                        y_end += 1

                    for yy in range(y, y_end):
                        for xx in range(x_start, x_end):
                            processed[yy, xx] = 1

                    rects[count, 0] = x_start
                    rects[count, 1] = y
                    rects[count, 2] = x_end
                    rects[count, 3] = y_end
                    count += 1
                    x = x_end
                else:
                    x += 1

        return rects[:count]

else:

    def _greedy_rect_numba(mask):
        return None


class BaseMesher(ABC):
    """Mesh generator abstract base class"""

    _VERTEX_TEMPLATE = np.array(
        [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1]],
        dtype=np.float64,
    )
    _FACE_TEMPLATE = np.array(
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
        if HAS_NUMBA:
            rects = _greedy_rect_numba(mask)
            return rects.astype(np.float64)

        h, w = mask.shape
        processed = np.zeros_like(mask, dtype=bool)
        rectangles = []
        for y in range(h):
            row_valid = mask[y] & ~processed[y]
            if not np.any(row_valid):
                continue
            padded = np.concatenate([[False], row_valid, [False]])
            diff = np.diff(padded.astype(np.int8))
            starts = np.where(diff == 1)[0]
            ends = np.where(diff == -1)[0]
            for x_start, x_end in zip(starts, ends):
                if processed[y, x_start]:
                    continue
                y_end = y + 1
                while y_end < h:
                    segment_mask = mask[y_end, x_start:x_end]
                    segment_proc = processed[y_end, x_start:x_end]
                    if not (np.all(segment_mask) and not np.any(segment_proc)):
                        break
                    y_end += 1
                processed[y:y_end, x_start:x_end] = True
                rectangles.append((float(x_start), float(y), float(x_end), float(y_end)))
        if not rectangles:
            return np.empty((0, 4), dtype=np.float64)
        return np.array(rectangles, dtype=np.float64)

    @staticmethod
    def _merge_layers_no_dilation(voxel_matrix, mat_id):
        """Group consecutive Z-layers with identical masks (no dilation).
        将连续相同掩码的 Z 层合并为组（不做膨胀）。
        """
        return _merge_layers_no_dilation(voxel_matrix, mat_id)

    def _build_mesh_from_layer_rects(self, layer_rectangles, height_px):
        """Build trimesh from list of (z_bottom, z_top, rects_array) tuples.
        从层矩形列表构建 trimesh。

        Args:
            layer_rectangles: list of (z_bottom, z_top, np.ndarray(R,4)).
            height_px (int): Image height for Y-axis inversion.

        Returns:
            trimesh.Trimesh or None
        """
        total_rects = sum(r.shape[0] for _, _, r in layer_rectangles)
        if total_rects == 0:
            return None

        raw_verts = np.empty((total_rects * 8, 3), dtype=np.float64)
        raw_faces = np.empty((total_rects * 12, 3), dtype=np.int64)
        rect_idx = 0

        for z_bottom, z_top, rect_arr in layer_rectangles:
            n = rect_arr.shape[0]
            if n == 0:
                continue
            x0, y0, x1, y1 = (
                rect_arr[:, 0],
                rect_arr[:, 1],
                rect_arr[:, 2],
                rect_arr[:, 3],
            )
            wy0 = height_px - y1
            wy1 = height_px - y0

            base = np.empty((n, 8, 3), dtype=np.float64)
            base[:, [0, 3, 4, 7], 0] = x0[:, None]
            base[:, [1, 2, 5, 6], 0] = x1[:, None]
            base[:, [0, 1, 4, 5], 1] = wy0[:, None]
            base[:, [2, 3, 6, 7], 1] = wy1[:, None]
            base[:, :4, 2] = z_bottom
            base[:, 4:, 2] = z_top

            v_start = rect_idx * 8
            raw_verts[v_start : v_start + n * 8] = base.reshape(-1, 3)
            offsets = (np.arange(n, dtype=np.int64) * 8 + v_start).reshape(
                -1, 1, 1
            )
            faces = self._FACE_TEMPLATE.reshape(1, 12, 3) + offsets
            f_start = rect_idx * 12
            raw_faces[f_start : f_start + n * 12] = faces.reshape(-1, 3)
            rect_idx += n

        # Do not weld touching prisms. Each indexed box stays independently
        # closed, avoiding the >2-face edge incidence caused by the old global
        # coordinate deduplication while retaining the fast vectorized path.
        return trimesh.Trimesh(
            vertices=raw_verts,
            faces=raw_faces,
            process=False,
        )

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

            meshes.extend(_extrude_polygon_geometry(world_geometry, height, z_bottom, extrude_cache=extrude_cache))

        return _merge_mesh_list(meshes)


class VoxelMesher(BaseMesher):
    """
    Pixel art mode mesh generator
    Uses greedy rectangle merging + Z-layer compression for optimized blocky mesh.
    """

    def generate_mesh(self, voxel_matrix, mat_id, height_px):
        """Generate pixel mode mesh with greedy rect merging and Z-compression.
        生成像素模式网格（贪婪矩形合并 + Z 层压缩）。

        Args:
            voxel_matrix (np.ndarray): (Z, H, W) int voxel matrix.
            mat_id (int): Material ID (0-7 or -2 for backing).
            height_px (int): Image height in pixels.

        Returns:
            trimesh.Trimesh or None
        """
        layer_groups = self._merge_layers_no_dilation(voxel_matrix, mat_id)
        if not layer_groups:
            return None

        mesh_type = "Backing" if mat_id == -2 else f"Mat ID {mat_id}"
        log.info(
            "%s: merged %s Z-layers into %s groups",
            mesh_type,
            voxel_matrix.shape[0],
            len(layer_groups),
            extra={
                "event": "voxel_mesher_layers_merged",
                "mesh_type": mesh_type,
                "layer_count": int(voxel_matrix.shape[0]),
                "group_count": len(layer_groups),
            },
        )

        layer_rects = []
        for start_z, end_z, mask in layer_groups:
            rects = self._greedy_rect_merge(mask)
            if rects.shape[0] > 0:
                layer_rects.append((float(start_z), float(end_z + 1), rects))

        mesh = self._build_mesh_from_layer_rects(layer_rects, height_px)
        if mesh is not None:
            total_rects = sum(r.shape[0] for _, _, r in layer_rects)
            log.info(
                "%s: built mesh from %s rects",
                mesh_type,
                total_rects,
                extra={
                    "event": "voxel_mesher_mesh_built",
                    "mesh_type": mesh_type,
                    "rect_count": total_rects,
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
    Uses Greedy Rectangle Merging algorithm to generate optimized, watertight 3D mesh

    ALGORITHM:
    1. Apply morphological dilation to thicken thin features
    2. Vertical layer compression (merge identical Z-layers)
    3. Greedy rectangle merging (find maximal rectangles in 2D mask)
    4. Generate ONE box per rectangle (instead of per-pixel-row)

    OPTIMIZATION:
    - Old method: 1 box per horizontal run → ~100k faces for 200x200 image
    - New method: 1 box per maximal rectangle → ~5k-10k faces (80-95% reduction)

    GEOMETRY:
    - Dilation: Expands features by ~0.1-0.15mm to ensure printability
    - Perfect edge-to-edge contact (watertight)
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
        """Generate high-fidelity mode mesh with greedy rect merging and dilation.
        生成高保真模式网格（贪婪矩形合并 + 形态学膨胀）。

        Args:
            voxel_matrix (np.ndarray): (Z, H, W) int voxel matrix.
            mat_id (int): Material ID (0-7 or -2 for backing).
            height_px (int): Image height in pixels.

        Returns:
            trimesh.Trimesh or None
        """
        boundary_geometry = self.boundary_geometry if boundary_geometry is None else _normalize_polygonal_geometry(boundary_geometry)
        use_no_dilation = self.disable_material_dilation if disable_material_dilation is None else bool(disable_material_dilation)

        if use_no_dilation:
            layer_groups = self._merge_layers_no_dilation(voxel_matrix, mat_id)
        else:
            layer_groups = self._merge_layers_with_dilation(voxel_matrix, mat_id)
        if not layer_groups:
            return None

        mesh_type = "Backing" if mat_id == -2 else f"Mat ID {mat_id}"
        boundary_enabled = boundary_geometry is not None
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

        layer_rects = []
        layer_polygons = []
        for start_z, end_z, mask in layer_groups:
            rects = self._greedy_rect_merge(mask)
            if rects.shape[0] == 0:
                continue

            if not boundary_enabled:
                layer_rects.append((float(start_z), float(end_z + 1), rects))
                continue

            interior_rects = []
            clipped_geoms = []
            for rect in rects:
                x0, y0, x1, y1 = rect
                rect_geom = box(float(x0), float(y0), float(x1), float(y1))
                try:
                    clipped = _normalize_polygonal_geometry(rect_geom.intersection(boundary_geometry))
                except (ValueError, TypeError, RuntimeError, AttributeError, OSError) as exc:
                    self._log_boundary_clip_fallback(exc, rect, mat_id)
                    interior_rects.append(rect)
                    continue
                if clipped is None or clipped.is_empty:
                    continue
                if clipped.equals(rect_geom):
                    interior_rects.append(rect)
                else:
                    clipped_geoms.append(clipped)

            if interior_rects:
                layer_rects.append((float(start_z), float(end_z + 1), np.array(interior_rects, dtype=np.float64)))
            if clipped_geoms:
                layer_polygons.append((float(start_z), float(end_z + 1), _normalize_polygonal_geometry(unary_union(clipped_geoms))))

        rect_mesh = self._build_mesh_from_layer_rects(layer_rects, height_px) if layer_rects else None
        polygon_mesh = self._build_mesh_from_layer_polygons(layer_polygons, height_px) if layer_polygons else None
        if rect_mesh is None:
            mesh = polygon_mesh
        elif polygon_mesh is None:
            mesh = rect_mesh
        else:
            mesh = _merge_mesh_list([rect_mesh, polygon_mesh])
        if mesh is not None:
            total_rects = sum(r.shape[0] for _, _, r in layer_rects)
            log.info(
                "%s: built high-fidelity mesh from %s rects",
                mesh_type,
                total_rects,
                extra={
                    "event": "high_fidelity_mesh_built",
                    "mesh_type": mesh_type,
                    "rect_count": total_rects,
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


def get_mesher(mode_name: ModelingMode, disable_material_dilation: bool = False, boundary_geometry=None):
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
            extra={"event": "mesher_selected", "mode": str(mode_name), "mesher": "HighFidelityMesher"},
        )
        return HighFidelityMesher(
            disable_material_dilation=disable_material_dilation,
            boundary_geometry=boundary_geometry,
        )

    # Vector mode uses same algorithm as High-Fidelity
    if mode_name == ModelingMode.VECTOR:
        log.info(
            "Selected HighFidelityMesher for vector mode",
            extra={"event": "mesher_selected", "mode": str(mode_name), "mesher": "HighFidelityMesher"},
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
        extra={"event": "mesher_defaulted", "mode": str(mode_name), "mesher": "HighFidelityMesher"},
    )
    return HighFidelityMesher(
        disable_material_dilation=disable_material_dilation,
        boundary_geometry=boundary_geometry,
    )
