"""
S11 — GLB 3D preview export.
S11 — GLB 3D 预览导出。

从 converter.py 搬入的 GLB 预览函数：
- _create_preview_mesh: 简化预览网格生成
- _merge_low_frequency_colors: 低频颜色合并
- _build_color_extruded_mesh: 按颜色轮廓挤出网格（替换原逐像素体素盒）
- generate_segmented_glb: 分色 GLB 预览
- generate_realtime_glb: 实时 GLB 预览
- generate_empty_bed_glb: 空热床 GLB
"""

from api.structured_logging import get_logger
import os
import time
from typing import Optional

import cv2
import numpy as np
import trimesh

from config import PrinterConfig, OUTPUT_DIR, BedManager
from core.naming import generate_preview_filename

_log = get_logger(__name__)


def _iter_valid_polygons(geometry_obj, min_area: float = 1e-4):
    """Yield valid Polygon geometries from Polygon/MultiPolygon-like objects."""
    if geometry_obj is None:
        return

    geom_type = getattr(geometry_obj, "geom_type", "")
    if geom_type == "Polygon":
        polygons = [geometry_obj]
    elif geom_type == "MultiPolygon":
        polygons = list(getattr(geometry_obj, "geoms", []))
    else:
        return

    for poly in polygons:
        if poly is None:
            continue
        if not getattr(poly, "is_valid", False):
            try:
                poly = poly.buffer(0)
            except (ValueError, TypeError, RuntimeError):
                continue
        if getattr(poly, "is_empty", True):
            continue
        area = float(getattr(poly, "area", 0.0) or 0.0)
        if area < min_area:
            continue
        if getattr(poly, "geom_type", "") == "Polygon":
            yield poly
        elif getattr(poly, "geom_type", "") == "MultiPolygon":
            for sub in getattr(poly, "geoms", []):
                if sub is None or getattr(sub, "is_empty", True):
                    continue
                sub_area = float(getattr(sub, "area", 0.0) or 0.0)
                if sub_area >= min_area:
                    yield sub


def _create_preview_mesh(
    matched_rgb: np.ndarray,
    mask_solid: np.ndarray,
    total_layers: int,
    backing_color_id: int = 0,
    backing_z_range: tuple = None,
    preview_colors: list = None,
) -> Optional[trimesh.Trimesh]:
    """Create simplified 3D preview mesh for browser display.
    为浏览器显示创建简化的 3D 预览网格。

    Args:
        matched_rgb (np.ndarray): RGB color array of shape (H, W, 3).
        mask_solid (np.ndarray): Boolean mask of solid pixels of shape (H, W).
        total_layers (int): Total number of Z layers.
        backing_color_id (int): Backing material ID (0-7), default is 0 (White).
        backing_z_range (tuple): Tuple of (start_z, end_z) for backing layer, or None.
        preview_colors (list): List of preview colors for materials.

    Returns:
        trimesh.Trimesh: Simplified preview mesh, downsampled for large models.
    """
    height, width = matched_rgb.shape[:2]
    total_pixels = width * height

    SIMPLIFY_THRESHOLD = 500_000
    TARGET_PIXELS = 300_000

    if total_pixels > SIMPLIFY_THRESHOLD:
        scale_factor = int(np.sqrt(total_pixels / TARGET_PIXELS))
        scale_factor = max(2, min(scale_factor, 16))

        _log.debug(f"Downsampling by {scale_factor}x ({total_pixels:,} -> ~{TARGET_PIXELS:,} pixels)")

        new_height = height // scale_factor
        new_width = width // scale_factor

        matched_rgb = cv2.resize(matched_rgb, (new_width, new_height), interpolation=cv2.INTER_AREA)
        mask_solid = cv2.resize(
            mask_solid.astype(np.uint8), (new_width, new_height), interpolation=cv2.INTER_NEAREST
        ).astype(bool)

        height, width = new_height, new_width
        shrink = 0.0
    else:
        shrink = 0.0

    # --- numpy vectorized mesh build ---
    _CUBE_FACES = np.array(
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
    )  # (12, 3)

    def _boxes_np(px, py, z0_scalar, z1_scalar, colors_rgba):
        """Build voxel boxes for N pixels, all at same z range."""
        n = len(px)
        if n == 0:
            return np.empty((0, 3)), np.empty((0, 3), dtype=np.int64), np.empty((0, 4), dtype=np.uint8)
        x0 = px + shrink
        x1 = px + 1 - shrink
        y0 = py + shrink
        y1 = py + 1 - shrink
        z0 = np.full(n, z0_scalar, dtype=np.float64)
        z1 = np.full(n, z1_scalar, dtype=np.float64)
        # verts: (n,8,3)
        verts = np.stack(
            [
                np.column_stack([x0, y0, z0]),
                np.column_stack([x1, y0, z0]),
                np.column_stack([x1, y1, z0]),
                np.column_stack([x0, y1, z0]),
                np.column_stack([x0, y0, z1]),
                np.column_stack([x1, y0, z1]),
                np.column_stack([x1, y1, z1]),
                np.column_stack([x0, y1, z1]),
            ],
            axis=1,
        )  # (n,8,3)
        all_verts = verts.reshape(-1, 3)
        offsets = (np.arange(n, dtype=np.int64) * 8)[:, None, None]
        all_faces = (_CUBE_FACES[None] + offsets).reshape(-1, 3)
        if colors_rgba.ndim == 1:
            all_colors = np.tile(colors_rgba, (n * 12, 1))
        else:
            all_colors = np.repeat(colors_rgba, 12, axis=0)
        return all_verts, all_faces, all_colors

    ys_all, xs_all = np.where(mask_solid)
    world_ys = (height - 1 - ys_all).astype(np.float64)
    xs_f = xs_all.astype(np.float64)

    all_v_list, all_f_list, all_c_list = [], [], []
    face_offset = 0

    if backing_z_range is not None and preview_colors is not None:
        backing_start, backing_end = backing_z_range
        backing_color_rgba = np.array(preview_colors[backing_color_id], dtype=np.uint8)[:4]
        pixel_colors = np.column_stack(
            [matched_rgb[ys_all, xs_all].astype(np.uint8), np.full(len(ys_all), 255, dtype=np.uint8)]
        )  # (N,4)

        # backing box
        v, f, c = _boxes_np(xs_f, world_ys, float(backing_start), float(backing_end + 1), backing_color_rgba)
        if len(v):
            all_v_list.append(v)
            all_f_list.append(f + face_offset)
            all_c_list.append(c)
            face_offset += len(v)

        # bottom box (z 0 -> backing_start)
        if backing_start > 0:
            v, f, c = _boxes_np(xs_f, world_ys, 0.0, float(backing_start), pixel_colors)
            if len(v):
                all_v_list.append(v)
                all_f_list.append(f + face_offset)
                all_c_list.append(c)
                face_offset += len(v)

        # top box (backing_end+1 -> total_layers)
        if backing_end + 1 < total_layers:
            v, f, c = _boxes_np(xs_f, world_ys, float(backing_end + 1), float(total_layers), pixel_colors)
            if len(v):
                all_v_list.append(v)
                all_f_list.append(f + face_offset)
                all_c_list.append(c)
                face_offset += len(v)
    else:
        pixel_colors = np.column_stack(
            [matched_rgb[ys_all, xs_all].astype(np.uint8), np.full(len(ys_all), 255, dtype=np.uint8)]
        )
        v, f, c = _boxes_np(xs_f, world_ys, 0.0, float(total_layers), pixel_colors)
        if len(v):
            all_v_list.append(v)
            all_f_list.append(f)
            all_c_list.append(c)

    if not all_v_list:
        return None

    vertices_np = np.concatenate(all_v_list, axis=0)
    faces_np = np.concatenate(all_f_list, axis=0)
    face_colors_np = np.concatenate(all_c_list, axis=0)

    mesh = trimesh.Trimesh(vertices=vertices_np, faces=faces_np, process=False)
    mesh.visual.face_colors = face_colors_np
    _log.debug(f"Generated: {len(mesh.vertices):,} vertices, {len(mesh.faces):,} faces")
    return mesh


def _merge_low_frequency_colors(
    unique_colors: np.ndarray,
    pixel_counts: np.ndarray,
    max_meshes: int,
) -> np.ndarray:
    """Merge low-frequency colors into their nearest high-frequency neighbors.
    将低频颜色合并到最近的高频邻居。

    Args:
        unique_colors (np.ndarray): (N, 3) uint8 array of unique RGB colors.
        pixel_counts (np.ndarray): (N,) int array of pixel counts per color.
        max_meshes (int): Maximum number of colors to keep.

    Returns:
        np.ndarray: (N, 3) uint8 array where tail colors are replaced by nearest kept color.
    """
    n = len(unique_colors)
    if n <= max_meshes:
        return unique_colors.copy()

    order = np.argsort(-pixel_counts)
    keep_indices = order[:max_meshes]
    tail_indices = order[max_meshes:]

    kept_colors = unique_colors[keep_indices].astype(np.float64)
    merged = unique_colors.copy()

    tail_rgb = unique_colors[tail_indices].astype(np.float64)
    # Vectorized nearest-neighbor via broadcasting: (T, 1, 3) - (1, K, 3)
    diff = tail_rgb[:, None, :] - kept_colors[None, :, :]
    dist_sq = np.sum(diff**2, axis=2)
    nearest = np.argmin(dist_sq, axis=1)

    merged[tail_indices] = unique_colors[keep_indices[nearest]]
    return merged


def _build_color_extruded_mesh(
    mask: np.ndarray,
    height: int,
    total_layers: int,
    rgba: np.ndarray,
) -> Optional[trimesh.Trimesh]:
    """Build an extruded Trimesh for pixels indicated by *mask*.
    为 mask 指示的像素构建挤出式 Trimesh。

    Replaces the per-pixel voxel-box representation. For a connected pixel
    region of N pixels the old approach emitted 8·N vertices / 12·N triangles
    regardless of shape complexity; this approach computes the region's true
    pixel-corner polygonal boundary (including any interior holes) and
    extrudes it along Z. For the preview the two are mathematically
    equivalent (identical footprint, identical height) but the extrusion
    typically uses 20–100× fewer vertices and faces.
    将逐像素体素盒替换为挤出方案：对 N 像素的连通区域，直接求出它在像素
    栅格上的外轮廓多边形（含内部孔洞），沿 Z 方向挤出一次。预览视角下两者
    完全等效（相同占地与高度），但挤出通常使用 20–100 倍更少的顶点和面。

    Implementation note / 实现说明:
        We build the mask's pixel-corner polygon by run-length-encoding each
        row into unit-tall rectangles and unioning them with Shapely's
        ``unary_union``. RLE keeps the object count to O(N_runs) which for
        typical color-layer masks is 10–100× smaller than N_pixels, so the
        union stays fast even for ~300k-pixel previews. We deliberately do
        NOT use ``cv2.findContours`` here: it traces pixel CENTERS, which
        collapse 1-pixel-thin strips into degenerate zero-area lines.
        通过逐行 RLE + Shapely ``unary_union`` 构造像素角点级精度的多边形。
        RLE 把对象数量控制在 O(N_runs)，通常比 N_pixels 少 10–100 倍，
        因此即便 ~30 万像素的预览也能快速求并。这里刻意不使用
        ``cv2.findContours``，因为它沿像素中心追踪，会把 1 像素窄条退化
        成零面积直线。

    Args:
        mask (np.ndarray): (H, W) bool array of pixels belonging to this color.
        height (int): Image height used for Y-axis flip so image-up maps to world-up.
        total_layers (int): Number of Z layers for the extrusion height.
        rgba (np.ndarray): (4,) uint8 RGBA color for face coloring.

    Returns:
        trimesh.Trimesh or None: Generated mesh, or None if mask has no True pixels.
    """
    from shapely.geometry import box as shapely_box
    from shapely.ops import unary_union

    if not np.any(mask):
        return None

    mask_arr = np.asarray(mask, dtype=bool)
    if mask_arr.ndim != 2:
        return None

    h, _w = mask_arr.shape
    # Vectorised row-wise RLE: pad each row with a False sentinel on both sides
    # so that np.diff marks every run's start (+1) and end (-1) symmetrically.
    # 逐行向量化 RLE：两端补 False 哨兵，np.diff 即可对称标记每段起止。
    padded = np.pad(mask_arr.astype(np.int8), ((0, 0), (1, 1)), mode="constant")
    diff = np.diff(padded, axis=1)
    starts_per_row = [np.flatnonzero(diff[y] == 1) for y in range(h)]
    ends_per_row = [np.flatnonzero(diff[y] == -1) for y in range(h)]

    boxes: list = []
    for y in range(h):
        starts = starts_per_row[y]
        ends = ends_per_row[y]
        if starts.size == 0:
            continue
        world_y0 = float(height - y - 1)
        world_y1 = float(height - y)
        for s, e in zip(starts, ends):
            boxes.append(shapely_box(float(s), world_y0, float(e), world_y1))

    if not boxes:
        return None

    try:
        region = unary_union(boxes)
    except (ValueError, TypeError, RuntimeError) as exc:
        _log.warning(f"unary_union failed: {exc}")
        return None

    if region.is_empty:
        return None

    valid_polygons = list(_iter_valid_polygons(region, min_area=1e-4))
    if not valid_polygons:
        return None

    extrude_h = float(total_layers)
    meshes: list[trimesh.Trimesh] = []
    extrude_fail = 0
    for poly in valid_polygons:
        try:
            m = trimesh.creation.extrude_polygon(poly, height=extrude_h)
            meshes.append(m)
        except (ValueError, TypeError, RuntimeError, AttributeError):
            extrude_fail += 1
            continue

    if not meshes:
        _log.warning(
            f"Color mesh extrusion failed for all components: "
            f"components={len(valid_polygons)}, extrude_fail={extrude_fail}"
        )
        return None

    result = trimesh.util.concatenate(meshes) if len(meshes) > 1 else meshes[0]
    result.visual.face_colors = np.tile(rgba, (len(result.faces), 1))
    return result


def _build_backing_plate_mesh(
    mask_solid: np.ndarray,
    height: int,
    pixel_scale: float,
    rgba: np.ndarray,
) -> Optional[trimesh.Trimesh]:
    """用 cv2.findContours 轮廓拉伸构建底板，替代逐像素体素方案。
    顶点数从 ~3M 降至 <5k，节省约 2.5s。
    """
    from shapely.geometry import Polygon

    mask_u8 = mask_solid.astype(np.uint8) * 255
    contours, _ = cv2.findContours(mask_u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_TC89_KCOS)
    if not contours:
        return None

    extrude_h = float(PrinterConfig.LAYER_HEIGHT)
    meshes = []
    skipped_short = 0
    skipped_tiny = 0
    skipped_invalid = 0
    extrude_fail = 0
    for cnt in contours:
        if len(cnt) < 3:
            skipped_short += 1
            continue
        pts = cnt.squeeze(1).astype(np.float64)
        world_pts = np.column_stack(
            [
                pts[:, 0] * pixel_scale,
                (height - pts[:, 1]) * pixel_scale,
            ]
        )
        try:
            base_poly = Polygon(world_pts)
            if not base_poly.is_valid:
                try:
                    base_poly = base_poly.buffer(0)
                except (ValueError, TypeError, RuntimeError):
                    skipped_invalid += 1
                    continue
            if float(getattr(base_poly, "area", 0.0) or 0.0) < 1e-4:
                skipped_tiny += 1
                continue

            valid_polygons = list(_iter_valid_polygons(base_poly, min_area=1e-4))
            if not valid_polygons:
                skipped_invalid += 1
                continue

            for poly in valid_polygons:
                try:
                    m = trimesh.creation.extrude_polygon(poly, height=extrude_h)
                    meshes.append(m)
                except (ValueError, TypeError, RuntimeError, AttributeError):
                    # Keep pipeline alive on isolated geometry fragments.
                    extrude_fail += 1
                    continue
        except (ValueError, TypeError, RuntimeError, AttributeError):
            skipped_invalid += 1
            continue

    if not meshes:
        _log.warning(
            f"Backing plate skipped: short={skipped_short}, invalid={skipped_invalid}, "
            f"tiny={skipped_tiny}, extrude_fail={extrude_fail}"
        )
        return None

    result = trimesh.util.concatenate(meshes) if len(meshes) > 1 else meshes[0]
    result.visual.face_colors = np.tile(rgba, (len(result.faces), 1))
    _log.debug(
        f"Backing plate contour stats: short={skipped_short}, invalid={skipped_invalid}, "
        f"tiny={skipped_tiny}, extrude_fail={extrude_fail}, kept={len(meshes)}"
    )
    return result


def generate_empty_bed_glb(
    bed_w: int = None,
    bed_h: int = None,
    is_dark: bool = False,
) -> Optional[str]:
    """Generate a GLB file containing only the print bed (no model).
    生成仅包含打印热床的 GLB 文件（无模型）。

    Args:
        bed_w (int): Bed width in mm. Defaults to BedManager default.
        bed_h (int): Bed height in mm. Defaults to BedManager default.
        is_dark (bool): Use dark PEI theme.

    Returns:
        str: Path to GLB file, or None on failure.
    """
    try:
        # Lazy import: _create_bed_mesh lives in converter.py until P06 is wired
        from core.converter import _create_bed_mesh

        if bed_w is None or bed_h is None:
            bed_w, bed_h = BedManager.get_bed_size(BedManager.DEFAULT_BED)
        bed_mesh = _create_bed_mesh(bed_w, bed_h, is_dark=is_dark)
        if bed_mesh is None:
            return None
        glb_scene = trimesh.Scene()
        glb_scene.add_geometry(bed_mesh, node_name="bed")
        glb_path = os.path.join(OUTPUT_DIR, f"empty_bed_{bed_w}x{bed_h}.glb")
        glb_scene.export(glb_path)
        return glb_path
    except (OSError, ImportError, ValueError, TypeError, RuntimeError) as e:
        _log.warning(f"Failed: {e}")
        return None


def generate_segmented_glb(cache: dict, max_meshes: int = 64, output_path: Optional[str] = None) -> Optional[str]:
    """Generate a color-segmented GLB preview with one named Mesh per color.
    生成按颜色分段的 GLB 预览，每种颜色一个独立 Mesh。

    Args:
        cache (dict): Preview cache dict containing at least:
            - matched_rgb: (H, W, 3) uint8 array
            - mask_solid: (H, W) bool array
            - target_w, target_h: pixel dimensions
            - target_width_mm: physical width in mm
            - glb_max_meshes (optional): per-session override that bumps
              the merge cap above the function default. Set by edit
              endpoints (e.g. ``/region-requantize``) that intentionally
              add many low-frequency colours which would otherwise be
              wiped out by the default 64-mesh merge.
              可选：调用方写入的 mesh 数上限覆盖。例如二次量化会引入
              大量低频新色，若按默认 64 合并它们会被丢回原色，导致 GLB
              和 2D 预览不一致。
        max_meshes (int): Default Mesh count before merging when no cache
            override is present (default 64).

    Returns:
        str: Path to the exported GLB file, or None on failure.
    """
    if cache is None:
        return None

    matched_rgb = cache.get("matched_rgb")
    mask_solid = cache.get("mask_solid")
    target_w = cache.get("target_w")
    target_width_mm = cache.get("target_width_mm")

    if matched_rgb is None or mask_solid is None:
        return None

    # Honour per-session override before the merge step. Anything below
    # the function default is ignored — we never want to merge MORE than
    # the caller-provided default (which is sized to a known-good upper
    # bound for three.js perf). Anything above bumps the cap so newly
    # added colours from edit endpoints survive into the segmented GLB.
    # 仅在 cache 覆盖值大于默认时生效；小于默认时退回默认，避免下调上限
    # 反而让正常预览的颜色被多砍。
    cache_override = cache.get("glb_max_meshes")
    if isinstance(cache_override, (int, np.integer)) and int(cache_override) > max_meshes:
        max_meshes = int(cache_override)

    try:
        _glb_t0 = time.perf_counter()

        # 1. Downsample large images
        _t = time.perf_counter()
        height, width = matched_rgb.shape[:2]
        total_pixels = width * height
        SIMPLIFY_THRESHOLD = 500_000
        TARGET_PIXELS = 300_000

        if total_pixels > SIMPLIFY_THRESHOLD:
            scale_factor = int(np.sqrt(total_pixels / TARGET_PIXELS))
            scale_factor = max(2, min(scale_factor, 16))
            _log.debug(f"Downsampling by {scale_factor}x")

            new_h = height // scale_factor
            new_w = width // scale_factor
            matched_rgb = cv2.resize(matched_rgb, (new_w, new_h), interpolation=cv2.INTER_NEAREST)
            mask_solid = cv2.resize(
                mask_solid.astype(np.uint8),
                (new_w, new_h),
                interpolation=cv2.INTER_NEAREST,
            ).astype(bool)
            height, width = new_h, new_w
            shrink = 0.0
        else:
            shrink = 0.0
        _t_downsample = time.perf_counter() - _t

        # 2. Extract unique colors and pixel counts (solid pixels only)
        _t = time.perf_counter()
        flat_mask = mask_solid.reshape(-1)
        solid_idx = np.flatnonzero(flat_mask)
        flat_rgb = matched_rgb.reshape(-1, 3).astype(np.uint32, copy=False)
        solid_pixels = flat_rgb[solid_idx]  # (N, 3)
        if len(solid_pixels) == 0:
            _log.warning("No solid pixels, returning None")
            return None

        solid_codes = (solid_pixels[:, 0] << 16) | (solid_pixels[:, 1] << 8) | solid_pixels[:, 2]
        unique_codes, inverse, pixel_counts = np.unique(
            solid_codes,
            return_inverse=True,
            return_counts=True,
        )
        n_unique = len(unique_codes)
        _log.debug(
            "unique-colour scan",
            extra={
                "event": "segmented_glb_unique_scan",
                "n_unique": int(n_unique),
                "max_meshes": int(max_meshes),
                "cache_override": int(cache_override) if isinstance(cache_override, (int, np.integer)) else None,
                "will_merge": bool(n_unique > max_meshes),
            },
        )
        _t_unique = time.perf_counter() - _t

        # 3. Merge low-frequency colors if exceeding max_meshes
        _t = time.perf_counter()
        if n_unique > max_meshes:
            _log.debug(
                "merging low-frequency colours",
                extra={
                    "event": "segmented_glb_merge_low_freq",
                    "n_unique_before": int(n_unique),
                    "max_meshes": int(max_meshes),
                    "n_to_merge": int(n_unique - max_meshes),
                },
            )
            unique_colors = np.column_stack(
                [
                    (unique_codes >> 16) & 0xFF,
                    (unique_codes >> 8) & 0xFF,
                    unique_codes & 0xFF,
                ]
            ).astype(np.uint8)
            merged_colors = _merge_low_frequency_colors(unique_colors, pixel_counts, max_meshes)
            merged_codes = (
                (merged_colors[:, 0].astype(np.uint32) << 16)
                | (merged_colors[:, 1].astype(np.uint32) << 8)
                | merged_colors[:, 2].astype(np.uint32)
            )
            code_map = merged_codes[inverse]
            updated_flat = matched_rgb.reshape(-1, 3).copy()
            updated_flat[solid_idx, 0] = (code_map >> 16) & 0xFF
            updated_flat[solid_idx, 1] = (code_map >> 8) & 0xFF
            updated_flat[solid_idx, 2] = code_map & 0xFF
            matched_rgb = updated_flat.reshape(matched_rgb.shape).astype(np.uint8, copy=False)

            unique_codes, inverse, pixel_counts = np.unique(
                code_map,
                return_inverse=True,
                return_counts=True,
            )
            _log.debug(f"After merge: {len(unique_codes)} colors")
        color_indices: dict[int, np.ndarray] = {}
        for code_idx in range(len(unique_codes)):
            color_indices[code_idx] = solid_idx[inverse == code_idx]
        _t_merge = time.perf_counter() - _t

        # 4. Build per-color Meshes + Extract 2D contours (single pass)
        _t = time.perf_counter()
        total_layers = 25
        scene = trimesh.Scene()
        contours_data: dict[str, list[list[list[float]]]] = {}

        pixel_scale = target_width_mm / width if width > 0 else 0.42
        scale_transform = np.eye(4)
        scale_transform[0, 0] = pixel_scale
        scale_transform[1, 1] = pixel_scale
        scale_transform[2, 2] = PrinterConfig.LAYER_HEIGHT

        flat_total = width * height
        color_match_flat = np.zeros(flat_total, dtype=bool)
        _t_mask_build = 0.0
        for code_idx, code in enumerate(unique_codes):
            r = int((code >> 16) & 0xFF)
            g = int((code >> 8) & 0xFF)
            b = int(code & 0xFF)
            hex_name = f"{r:02x}{g:02x}{b:02x}"
            rgba = np.array([r, g, b, 255], dtype=np.uint8)

            idxs = color_indices.get(code_idx)
            if idxs is None or len(idxs) == 0:
                continue
            _mask_t0 = time.perf_counter()
            color_match_flat[idxs] = True
            color_match = color_match_flat.reshape(height, width)
            _t_mask_build += time.perf_counter() - _mask_t0

            mesh = _build_color_extruded_mesh(
                color_match,
                height,
                total_layers,
                rgba,
            )
            if mesh is not None:
                mesh.apply_transform(scale_transform)
                min_z = mesh.vertices[:, 2].min()
                if min_z != 0.0:
                    mesh.vertices[:, 2] -= min_z
                scene.add_geometry(mesh, node_name=f"color_{hex_name}")

            # Reuse same color_match for contour extraction
            mask_u8 = color_match.astype(np.uint8) * 255
            cv_contours, _ = cv2.findContours(mask_u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if cv_contours:
                color_contour_list: list[list[list[float]]] = []
                for cnt in cv_contours:
                    if len(cnt) < 3:
                        continue
                    pts = cnt.squeeze(1).astype(float)
                    world_pts = [[float(px * pixel_scale), float((height - py) * pixel_scale)] for px, py in pts]
                    color_contour_list.append(world_pts)
                if color_contour_list:
                    contours_data[hex_name] = color_contour_list
            color_match_flat[idxs] = False

        _t_mesh_loop = time.perf_counter() - _t

        if len(scene.geometry) == 0:
            _log.warning("No meshes generated")
            return None

        # 4.5 Build backing plate mesh (contour extrusion)
        _t = time.perf_counter()
        backing_mesh = _build_backing_plate_mesh(
            mask_solid=mask_solid,
            height=height,
            pixel_scale=pixel_scale,
            rgba=np.array([245, 245, 245, 255], dtype=np.uint8),
        )
        if backing_mesh is not None:
            scene.add_geometry(backing_mesh, node_name="backing_plate")
            _log.debug(f"Backing plate added ({backing_mesh.vertices.shape[0]} vertices)")
        _t_backing = time.perf_counter() - _t

        cache["color_contours"] = contours_data
        _log.debug(f"Extracted contours for {len(contours_data)} colors")

        # 6. Export GLB
        _t = time.perf_counter()
        glb_path = output_path if output_path else os.path.join(OUTPUT_DIR, "segmented_preview.glb")
        scene.export(glb_path)
        _t_export = time.perf_counter() - _t

        _t_glb_total = time.perf_counter() - _glb_t0
        cache["_segmented_glb_timings"] = {
            "downsample_s": _t_downsample,
            "unique_s": _t_unique,
            "merge_s": _t_merge,
            "mask_build_s": _t_mask_build,
            "mesh_loop_s": _t_mesh_loop,
            "backing_s": _t_backing,
            "export_s": _t_export,
            "total_s": _t_glb_total,
        }
        _log.debug(f"Exported {len(scene.geometry)} meshes -> {glb_path}")
        _log.debug(
            f"Timing: downsample={_t_downsample:.2f}s, "
            f"unique={_t_unique:.2f}s, merge={_t_merge:.2f}s, mask_build={_t_mask_build:.2f}s, "
            f"mesh_loop={_t_mesh_loop:.2f}s, backing={_t_backing:.2f}s, "
            f"export={_t_export:.2f}s, total={_t_glb_total:.2f}s"
        )
        return glb_path

    except (OSError, ValueError, TypeError, RuntimeError) as e:
        _log.exception(f"Failed: {e}")
        return None


def generate_realtime_glb(cache: dict) -> Optional[str]:
    """Generate a lightweight GLB preview from cached preview data.
    从缓存的预览数据生成轻量级 GLB 预览。

    Called during preview stage so the 3D thumbnail updates immediately
    without waiting for the full 3MF export.

    Args:
        cache (dict): Preview cache dict from generate_preview_cached.

    Returns:
        str: Path to GLB file, or None on failure.
    """
    if cache is None:
        return None

    matched_rgb = cache.get("matched_rgb")
    mask_solid = cache.get("mask_solid")
    target_w = cache.get("target_w")
    target_h = cache.get("target_h")
    target_width_mm = cache.get("target_width_mm")
    color_conf = cache.get("color_conf")

    if matched_rgb is None or mask_solid is None:
        return None

    try:
        total_layers = 25
        preview_colors = color_conf.get("preview") if color_conf else None

        preview_mesh = _create_preview_mesh(
            matched_rgb,
            mask_solid,
            total_layers,
            backing_color_id=cache.get("backing_color_id", 0),
            preview_colors=preview_colors,
        )

        if preview_mesh is None:
            _log.warning("Preview mesh is None (model too large?)")
            return None

        # Scale from pixel/voxel coords to mm
        mesh_width = preview_mesh.bounds[1][0] - preview_mesh.bounds[0][0]
        pixel_scale = target_width_mm / mesh_width if mesh_width > 0 else 0.42
        transform = np.eye(4)
        transform[0, 0] = pixel_scale
        transform[1, 1] = pixel_scale
        transform[2, 2] = PrinterConfig.LAYER_HEIGHT
        preview_mesh.apply_transform(transform)

        glb_path = os.path.join(OUTPUT_DIR, "realtime_preview.glb")
        preview_mesh.export(glb_path)
        _log.debug(f"Exported: {glb_path}")
        return glb_path

    except (OSError, ValueError, TypeError, RuntimeError) as e:
        _log.warning(f"Failed: {e}")
        return None


def run(ctx: dict) -> dict:
    """Generate GLB 3D preview for the converted model.
    为转换后的模型生成 GLB 3D 预览。

    PipelineContext 输入键 / Input keys:
        - matched_rgb (np.ndarray): (H, W, 3) 匹配后的 RGB
        - mask_solid (np.ndarray): (H, W) bool 实体掩码
        - total_layers (int): 总层数
        - backing_color_id (int): 底板材料 ID
        - backing_metadata (dict): 底板元数据
        - preview_colors (dict): 材料预览颜色
        - pixel_scale (float): mm/px 缩放因子
        - loop_info (dict | None): 挂件环信息
        - loop_added (bool): 挂件环是否已添加
        - image_path (str): 原始图像路径
        - modeling_mode (ModelingMode): 建模模式
        - enable_outline (bool): 启用描边
        - outline_width (float): 描边宽度
        - outline_added (bool): 描边是否已添加
        - target_h (int): 图像高度（像素）
        - transform (np.ndarray): 4x4 变换矩阵

    PipelineContext 输出键 / Output keys:
        - glb_path (str | None): GLB 预览文件路径
    """
    _t0 = time.perf_counter()

    matched_rgb = ctx["matched_rgb"]
    mask_solid = ctx["mask_solid"]
    pixel_scale = ctx["pixel_scale"]
    image_path = ctx["image_path"]

    _prog = ctx.get("progress")
    if _prog is not None:
        _prog(0.90, "生成 3D 预览中... | Generating 3D preview...")

    height, width = matched_rgb.shape[:2]
    target_width_mm = pixel_scale * width
    base_name = os.path.splitext(os.path.basename(image_path))[0]
    out_path = os.path.join(OUTPUT_DIR, generate_preview_filename(base_name))

    cache = {
        "matched_rgb": matched_rgb,
        "mask_solid": mask_solid,
        "target_w": width,
        "target_h": height,
        "target_width_mm": target_width_mm,
    }
    glb_path = generate_segmented_glb(cache, output_path=out_path)

    ctx["glb_path"] = glb_path

    _elapsed = time.perf_counter() - _t0
    _log.debug(f"glb_preview done: {_elapsed:.3f}s")
    _hifi_timings = ctx.setdefault("_hifi_timings", {})
    _hifi_timings["glb_preview_s"] = _elapsed
    seg_timing = cache.get("_segmented_glb_timings")
    if isinstance(seg_timing, dict):
        _hifi_timings["s11_unique_s"] = float(seg_timing.get("unique_s", 0.0))
        _hifi_timings["s11_merge_s"] = float(seg_timing.get("merge_s", 0.0))
        _hifi_timings["s11_mask_build_s"] = float(seg_timing.get("mask_build_s", 0.0))
        _hifi_timings["s11_mesh_loop_s"] = float(seg_timing.get("mesh_loop_s", 0.0))
        _hifi_timings["s11_backing_s"] = float(seg_timing.get("backing_s", 0.0))
        _hifi_timings["s11_export_s"] = float(seg_timing.get("export_s", 0.0))
    return ctx
