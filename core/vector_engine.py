"""
Lumina Studio - Native Vector Engine (v2 - Chroma-aligned)

SVG to 3D mesh conversion using vector geometry operations.
Aligned with ChromaPrint3D's processing philosophy:

Pipeline:
    SVG → Parse Paths → Occlusion Clip → Match Colors → Run-Length Extrude
        → Silhouette Backing → (optional Double-sided) → Assemble Scene

Key changes from v1:
    - Per-shape reverse-order occlusion clipping (no "small feature" exemptions)
    - Per-unique-color recipe caching via LUT KDTree
    - Run-length layer extrusion (consecutive same-channel layers merged)
    - No micro Z-offset between overlapping colors on the same material
    - Output objects sorted by material ID for stable slicer ordering
"""

import os
import re
import json
import numpy as np
import time
import xml.etree.ElementTree as ET
import trimesh
import cv2
from dataclasses import dataclass, field
from svgelements import SVG, Path, Shape, Move, Line, Close, CubicBezier, QuadraticBezier, Color
from shapely.geometry import Polygon, MultiPolygon, LineString, Point, box
from shapely import affinity
from shapely.ops import polygonize, unary_union
from shapely.strtree import STRtree
from shapely.validation import make_valid
from shapely import set_precision

from api.structured_logging import get_logger
from config import PrinterConfig, ColorSystem, VectorConfig

_log = get_logger(__name__)

MIN_SHAPE_AREA_MM2 = 0.01
BASE_COLOR_GAP_MM = 0.005
_MAX_BEZIER_DEPTH = 16

# Supersample factor for the hard membership masks (mask_solid / matched_rgb /
# quantized_image / material_matrix) built in ``build_preview_cache``. Plain
# ``cv2.fillPoly`` truncates float vertices to int at base resolution and can
# drop geometry-covered pixels along edges / thin interior-hole borders,
# producing the 1px seams users saw as "holes" in the hair (clickable as
# background, exported as air). Filling on an N× sub-grid restricted to each
# shape's bbox and center-sampling decides membership by "pixel center inside
# geometry", eliminating those seams. 4 reduces the reported seam from 208 to
# only sub-pixel boundary jitter (<1px) while keeping cost ~shape_area*16.
# 外观面归属掩膜的超采样倍率：修复 fillPoly 整数截断导致的 1px 缝。
_MASK_SUPERSAMPLE = 4


def _color_object_to_hex(color_obj):
    """Return a lowercase hex string for svgelements Color objects."""
    if color_obj is None:
        return None
    try:
        value = getattr(color_obj, "value", None)
        if value is None or str(value).lower() == "none":
            return None
        return f"#{int(color_obj.red) & 255:02x}{int(color_obj.green) & 255:02x}{int(color_obj.blue) & 255:02x}"
    except Exception:
        value = getattr(color_obj, "value", None)
        return None if value is None else str(value)


def _rgb_to_hex(rgb):
    """Return a stable lowercase hex string for RGB tuples."""
    try:
        return f"#{int(rgb[0]) & 255:02x}{int(rgb[1]) & 255:02x}{int(rgb[2]) & 255:02x}"
    except Exception:
        return None


def _flatten_cubic(
    x0,
    y0,
    x1,
    y1,
    x2,
    y2,
    x3,
    y3,
    tolerance,
    out,
    depth,
):
    """Adaptive de Casteljau subdivision for cubic Bézier curves.

    Appends flattened points to *out*.  Mirrors the algorithm used
    by ``ChromaPrint3D::FlattenCubicBezier``.
    """
    bx = x3 - x0
    by = y3 - y0
    d1 = abs((x1 - x3) * by - (y1 - y3) * bx)
    d2 = abs((x2 - x3) * by - (y2 - y3) * bx)
    len_sq = bx * bx + by * by
    tol_sq = tolerance * tolerance * len_sq
    if (d1 + d2) * (d1 + d2) <= tol_sq or depth >= _MAX_BEZIER_DEPTH:
        out.append((x3, y3))
        return
    m01x = (x0 + x1) * 0.5
    m01y = (y0 + y1) * 0.5
    m12x = (x1 + x2) * 0.5
    m12y = (y1 + y2) * 0.5
    m23x = (x2 + x3) * 0.5
    m23y = (y2 + y3) * 0.5
    m012x = (m01x + m12x) * 0.5
    m012y = (m01y + m12y) * 0.5
    m123x = (m12x + m23x) * 0.5
    m123y = (m12y + m23y) * 0.5
    mx = (m012x + m123x) * 0.5
    my = (m012y + m123y) * 0.5
    _flatten_cubic(x0, y0, m01x, m01y, m012x, m012y, mx, my, tolerance, out, depth + 1)
    _flatten_cubic(mx, my, m123x, m123y, m23x, m23y, x3, y3, tolerance, out, depth + 1)


def _flatten_quadratic(
    x0,
    y0,
    x1,
    y1,
    x2,
    y2,
    tolerance,
    out,
    depth,
):
    """Adaptive de Casteljau subdivision for quadratic Bézier curves."""
    bx = x2 - x0
    by = y2 - y0
    d = abs((x1 - x2) * by - (y1 - y2) * bx)
    len_sq = bx * bx + by * by
    if d * d <= tolerance * tolerance * len_sq or depth >= _MAX_BEZIER_DEPTH:
        out.append((x2, y2))
        return
    m01x = (x0 + x1) * 0.5
    m01y = (y0 + y1) * 0.5
    m12x = (x1 + x2) * 0.5
    m12y = (y1 + y2) * 0.5
    mx = (m01x + m12x) * 0.5
    my = (m01y + m12y) * 0.5
    _flatten_quadratic(x0, y0, m01x, m01y, mx, my, tolerance, out, depth + 1)
    _flatten_quadratic(mx, my, m12x, m12y, x2, y2, tolerance, out, depth + 1)


def _sample_gradient_stops(stops, t):
    """Interpolate colour at parameter *t* along a gradient stop list."""
    if not stops:
        return (128, 128, 128)
    if t <= stops[0][0]:
        return stops[0][1]
    if t >= stops[-1][0]:
        return stops[-1][1]
    for i in range(len(stops) - 1):
        t0, c0 = stops[i]
        t1, c1 = stops[i + 1]
        if t0 <= t <= t1:
            if t1 - t0 < 1e-9:
                return c0
            f = (t - t0) / (t1 - t0)
            return (
                int(c0[0] + (c1[0] - c0[0]) * f),
                int(c0[1] + (c1[1] - c0[1]) * f),
                int(c0[2] + (c1[2] - c0[2]) * f),
            )
    return stops[-1][1]


def _parse_svg_transform(transform_str):
    """Parse an SVG ``transform`` attribute into a 3x3 affine matrix.

    Supports ``translate``, ``scale``, ``rotate``, ``matrix``,
    ``skewX`` and ``skewY``, including concatenated transforms.

    解析 SVG transform 属性字符串为 3×3 仿射矩阵，
    支持 translate/scale/rotate/matrix/skewX/skewY 及其组合。
    """
    if not transform_str:
        return np.eye(3, dtype=np.float64)

    result = np.eye(3, dtype=np.float64)
    _tf_re = re.compile(r"(matrix|translate|scale|rotate|skewX|skewY)\s*\(([^)]*)\)")

    for match in _tf_re.finditer(transform_str):
        func = match.group(1)
        args = [float(v) for v in re.split(r"[\s,]+", match.group(2).strip()) if v]
        m = np.eye(3, dtype=np.float64)

        if func == "translate":
            m[0, 2] = args[0] if len(args) >= 1 else 0.0
            m[1, 2] = args[1] if len(args) >= 2 else 0.0
        elif func == "scale":
            sx = args[0] if len(args) >= 1 else 1.0
            m[0, 0] = sx
            m[1, 1] = args[1] if len(args) >= 2 else sx
        elif func == "rotate":
            angle = np.radians(args[0]) if args else 0.0
            cos_a, sin_a = np.cos(angle), np.sin(angle)
            if len(args) >= 3:
                cx, cy = args[1], args[2]
                m[0, 0] = cos_a
                m[0, 1] = -sin_a
                m[0, 2] = cx - cos_a * cx + sin_a * cy
                m[1, 0] = sin_a
                m[1, 1] = cos_a
                m[1, 2] = cy - sin_a * cx - cos_a * cy
            else:
                m[0, 0] = cos_a
                m[0, 1] = -sin_a
                m[1, 0] = sin_a
                m[1, 1] = cos_a
        elif func == "matrix" and len(args) >= 6:
            m[0, 0] = args[0]
            m[1, 0] = args[1]
            m[0, 1] = args[2]
            m[1, 1] = args[3]
            m[0, 2] = args[4]
            m[1, 2] = args[5]
        elif func == "skewX" and args:
            m[0, 1] = np.tan(np.radians(args[0]))
        elif func == "skewY" and args:
            m[1, 0] = np.tan(np.radians(args[0]))

        result = result @ m

    return result


def _parse_gradient_length(val, default=0.0):
    """Parse an SVG gradient coordinate value, handling ``%`` suffix.

    解析 SVG 渐变坐标值，支持百分比后缀。
    """
    if val is None:
        return default
    s = str(val).strip()
    if not s:
        return default
    try:
        if s.endswith("%"):
            return float(s[:-1]) / 100.0
        return float(s)
    except (ValueError, TypeError):
        return default


VECTOR_HANDLED_ERRORS = (
    ValueError,
    TypeError,
    KeyError,
    IndexError,
    AttributeError,
    OSError,
    RuntimeError,
    ImportError,
    ModuleNotFoundError,
    ArithmeticError,
)


# Lazy import to avoid circular dependency at module load time
_LuminaImageProcessor = None
_VECTOR_PARSE_CLIP_CACHE = {}
_VECTOR_PARSE_CLIP_CACHE_MAX = 3


def _get_image_processor_class():
    global _LuminaImageProcessor
    if _LuminaImageProcessor is None:
        from core.image_processing import LuminaImageProcessor

        _LuminaImageProcessor = LuminaImageProcessor
    return _LuminaImageProcessor


@dataclass
class VectorAnalysis:
    """Intermediate result of SVG parsing, clipping, and color matching.
    SVG 解析、裁剪、配色的中间结果 — 预览与 3D 构建共享。

    Produced by ``VectorProcessor.analyze_svg`` and consumed by both
    ``build_mesh`` (3D extrusion) and ``render_preview`` (2D raster).
    """

    shape_data: list
    clipped_shapes: list
    matched_shapes: list
    silhouette: object  # Polygon | MultiPolygon | None
    scale_factor: float
    bbox: tuple  # (gx0, gy0, real_w, real_h) in SVG user units
    color_conf: dict
    slot_names: list
    num_channels: int
    num_layers: int
    preview_colors: dict
    stage_timings: dict = field(default_factory=dict)
    image_vectorizer_bounds: object | None = None


def apply_recipe_overrides_to_analysis(
    analysis: "VectorAnalysis",
    *,
    recipe_overrides,
    region_masks,
    target_layers=None,
    base_channel_idx: int = 0,
    pixels_per_mm: float = 10.0,
    max_width_px: int = 1600,
    min_overlap_ratio: float = 0.5,
    img_processor=None,
) -> None:
    """Apply user-declared per-region recipe overrides to a ``VectorAnalysis``.
    将用户通过自定义配方对话框声明的 per-region 覆盖回写到 ``VectorAnalysis``。

    The raster pipeline mutates ``preview_cache["material_matrix"]`` inside
    ``/convert/apply-recipe-override`` so the 2D preview + segmented GLB echo
    the user's picks and any extra layers they appended. The SVG-native
    branch used to skip this entirely — it re-ran ``analyze_svg`` and built
    the 3MF from the LUT's default match, so "custom recipe + added layers"
    applied on a vector input never made it into the generated 3MF even
    though the preview showed them. This helper mirrors
    ``s03_color_replacement`` for the vector branch:

    - Rasterises each ``analysis.matched_shapes`` entry onto the same grid
      used by :meth:`VectorProcessor.build_preview_cache` so the preview-time
      region masks line up pixel-for-pixel.
    - Picks the dominant region (by mask overlap) for each shape; shapes
      whose footprint sits mostly inside a region mask inherit that
      region's recipe.
    - Translates each override recipe into the vector internal order
      (``Top2Bottom`` — recipe[0] is the visible face at z=0) and pads it
      up to the effective layer count with the base backing channel.
    - Non-overridden shapes keep their LUT recipe but are also padded so
      the extended layers stay continuous with the backing slab.
    - Virtual (non-native) materials declared per-region are deduped into a
      global registry and appended to ``slot_names`` / ``preview_colors``
      so ``build_mesh`` can emit one geometry per extra material.

    Args:
        analysis: Analysis result from ``analyze_svg``. Mutated in place.
        recipe_overrides: Sequence of ``{"region_id", "recipe", "layer_order",
            "virtual_materials"?}`` dicts coming from the generate request.
        region_masks: Mapping of ``region_id`` to a boolean mask that was
            computed at preview time and lives on the preview grid.
        target_layers: Requested ``color_layers`` from the generate request;
            used to extend ``analysis.num_layers`` when the user appended
            layers. ``None`` falls back to the max length found in
            ``recipe_overrides``.
        base_channel_idx: LUT base channel id used when padding non-override
            recipes; typically 0 (white / backing).
        pixels_per_mm: Preview-grid rasterisation density. Must match the
            value passed to :meth:`VectorProcessor.build_preview_cache`.
        max_width_px: Preview-grid width cap. Must match
            :meth:`VectorProcessor.build_preview_cache`.
        min_overlap_ratio: Minimum ratio of a shape's pixels that must fall
            inside a region mask before that region "claims" the shape.
            0.5 matches the "majority wins" rule used by the raster path.
    """
    from core.recipe_order import convert_recipe_between_orders, pad_recipe_to_layer_count
    from core.pipeline.pipeline_utils import _hex_to_rgb_tuple

    if not recipe_overrides or not region_masks:
        return

    # --- Reproduce build_preview_cache grid so region masks line up exactly ---
    real_w = float(analysis.bbox[2])
    real_h = float(analysis.bbox[3])
    sf = float(analysis.scale_factor)
    w_mm = real_w * sf
    h_mm = real_h * sf
    if w_mm <= 0 or h_mm <= 0:
        return
    ppm = float(pixels_per_mm)
    w_px = max(1, int(round(w_mm * ppm)))
    h_px = max(1, int(round(h_mm * ppm)))
    if w_px > max_width_px:
        ratio = max_width_px / w_px
        w_px = max_width_px
        h_px = max(1, int(round(h_px * ratio)))
        ppm = w_px / w_mm
    coord_scale = sf * ppm

    # --- Normalise region masks to the preview grid ---
    normalised_masks: dict[str, np.ndarray] = {}
    for rid, mask in (region_masks or {}).items():
        arr = np.asarray(mask, dtype=bool)
        if arr.ndim != 2 or arr.shape != (h_px, w_px):
            error_message = (
                f"Region mask {rid} shape {arr.shape} does not match "
                f"preview grid {(h_px, w_px)}"
            )
            _log.warning(
                "Region mask does not match preview grid; skipped",
                extra={
                    "event": "vector_recipe_region_mask_skipped",
                    "error_type": "ValueError",
                    "error_message": error_message,
                    "region_id": str(rid),
                    "mask_shape": list(arr.shape),
                    "expected_shape": [int(h_px), int(w_px)],
                },
            )
            continue
        normalised_masks[str(rid)] = arr

    if not normalised_masks:
        _log.warning(
            "No region masks matched preview grid; recipe overrides ignored",
            extra={
                "event": "vector_recipe_region_masks_missing",
                "error_type": "ValueError",
                "error_message": "No recipe override region masks matched the preview grid",
                "region_count": len(region_masks or {}),
                "expected_shape": [int(h_px), int(w_px)],
            },
        )
        return

    # --- Build a global virtual-material registry (dedupe by name+hex) ---
    lut_palette_length = int(analysis.num_channels)
    virtual_registry: list[dict] = []
    virtual_lookup: dict[tuple, int] = {}
    per_region_virtual_maps: dict[str, dict[int, int]] = {}
    for item in recipe_overrides:
        if not isinstance(item, dict):
            continue
        rid = str(item.get("region_id", "")).strip()
        local_map: dict[int, int] = {}
        for local_idx, vm in enumerate(item.get("virtual_materials") or []):
            if not isinstance(vm, dict):
                continue
            name = str(vm.get("name") or "").strip()
            hex_value = str(vm.get("hex") or "").strip()
            if not name or not hex_value:
                continue
            key = (name.lower(), hex_value.lower())
            gidx = virtual_lookup.get(key)
            if gidx is None:
                gidx = lut_palette_length + len(virtual_registry)
                virtual_registry.append({"name": name, "hex": hex_value})
                virtual_lookup[key] = gidx
            local_map[lut_palette_length + local_idx] = gidx
        if rid:
            per_region_virtual_maps[rid] = local_map

    # --- Compute effective target layer count ---
    recipe_max_len = max(
        (len(item.get("recipe", [])) for item in recipe_overrides if isinstance(item, dict)),
        default=0,
    )
    effective_target = max(int(analysis.num_layers), recipe_max_len)
    if target_layers is not None:
        try:
            effective_target = max(effective_target, int(target_layers))
        except (TypeError, ValueError):
            pass
    effective_target = max(1, effective_target)

    # --- Extend slot_names / preview_colors / color_conf with virtuals ---
    if virtual_registry:
        new_slot_names = list(analysis.slot_names)
        new_preview_colors = dict(analysis.preview_colors)
        new_color_conf = dict(analysis.color_conf)
        conf_preview = dict(new_color_conf.get("preview") or {})
        conf_slots = list(new_color_conf.get("slots") or [])
        new_color_conf["preview"] = conf_preview
        new_color_conf["slots"] = conf_slots
        for offset, material in enumerate(virtual_registry):
            cache_index = lut_palette_length + offset
            try:
                r, g, b = _hex_to_rgb_tuple(material["hex"])
            except (ValueError, TypeError, KeyError):
                continue
            rgba = [int(r), int(g), int(b), 255]
            name = str(material.get("name") or f"Virtual_{offset}")
            while len(new_slot_names) < cache_index:
                new_slot_names.append(f"Slot_{len(new_slot_names)}")
            if len(new_slot_names) == cache_index:
                new_slot_names.append(name)
            else:
                new_slot_names[cache_index] = name
            while len(conf_slots) < cache_index:
                conf_slots.append(f"Slot_{len(conf_slots)}")
            if len(conf_slots) == cache_index:
                conf_slots.append(name)
            else:
                conf_slots[cache_index] = name
            new_preview_colors[cache_index] = rgba
            conf_preview[cache_index] = rgba
        analysis.slot_names = new_slot_names
        analysis.preview_colors = new_preview_colors
        analysis.color_conf = new_color_conf
        analysis.num_channels = max(
            int(analysis.num_channels),
            lut_palette_length + len(virtual_registry),
        )

    # --- Rasterise every shape onto the preview grid ---
    def _iter_polygons(geom):
        if geom is None or geom.is_empty:
            return []
        if geom.geom_type == "Polygon":
            return [geom]
        if geom.geom_type == "MultiPolygon":
            return list(geom.geoms)
        return []

    def _coords_to_pts(coords):
        pts = np.column_stack(
            [
                coords[:, 0] * coord_scale,
                coords[:, 1] * coord_scale,
            ]
        ).astype(np.int32)
        if len(pts) < 3:
            return None
        return pts

    def _shape_mask(geom):
        region = np.zeros((h_px, w_px), dtype=np.uint8)
        painted = False
        for poly in _iter_polygons(geom):
            if poly.is_empty:
                continue
            ext_pts = _coords_to_pts(np.array(poly.exterior.coords))
            if ext_pts is None:
                continue
            cv2.fillPoly(region, [ext_pts], 255)
            painted = True
            for interior in poly.interiors:
                hole_pts = _coords_to_pts(np.array(interior.coords))
                if hole_pts is not None:
                    cv2.fillPoly(region, [hole_pts], 0)
        if not painted:
            return None
        return region.astype(bool)

    shape_masks: list = []
    for shape in analysis.matched_shapes:
        shape_masks.append(_shape_mask(shape.get("geometry")))

    # --- Pick the dominant region for every shape (majority wins) ---
    override_by_region: dict[str, dict] = {}
    for item in recipe_overrides:
        if not isinstance(item, dict):
            continue
        rid = str(item.get("region_id", "")).strip()
        if rid:
            override_by_region[rid] = item

    shape_overrides: dict[int, dict] = {}
    for shape_idx, mask in enumerate(shape_masks):
        if mask is None:
            continue
        shape_px = int(mask.sum())
        if shape_px == 0:
            continue
        best_rid: str | None = None
        best_overlap = 0
        for rid, rmask in normalised_masks.items():
            overlap = int(np.logical_and(mask, rmask).sum())
            if overlap > best_overlap:
                best_overlap = overlap
                best_rid = rid
        if best_rid is None:
            continue
        if best_overlap / shape_px < min_overlap_ratio:
            continue
        item = override_by_region.get(best_rid)
        if item is not None:
            shape_overrides[shape_idx] = item

    # --- Apply recipes: overridden shapes use user recipe, others get padded ---
    overridden_count = 0
    for shape_idx, shape in enumerate(analysis.matched_shapes):
        override = shape_overrides.get(shape_idx)
        if override is not None:
            raw_recipe = [int(v) for v in override.get("recipe", [])]
            rid = str(override.get("region_id", "")).strip()
            local_map = per_region_virtual_maps.get(rid) or {}
            if local_map:
                raw_recipe = [int(local_map.get(int(v), int(v))) for v in raw_recipe]
            source_order = str(override.get("layer_order") or "Top2Bottom")
            # Vector runs recipe[0] at z=0 (the visible face for face-down
            # prints), i.e. Top2Bottom by convention. Normalise user recipes
            # into that order before padding.
            # 矢量管道约定 recipe[0] 在 z=0（面朝下打印时的可视面），即
            # Top2Bottom；用户 recipe 先归一到该序再补齐。
            normalised = convert_recipe_between_orders(raw_recipe, source_order, "Top2Bottom")
            padded = pad_recipe_to_layer_count(
                normalised,
                effective_target,
                int(base_channel_idx),
                "Top2Bottom",
            )
            shape["recipe"] = padded
            overridden_count += 1
        else:
            existing = [int(v) for v in shape.get("recipe") or []]
            if len(existing) < effective_target:
                shape["recipe"] = pad_recipe_to_layer_count(
                    existing,
                    effective_target,
                    int(base_channel_idx),
                    "Top2Bottom",
                )
            elif len(existing) > effective_target:
                shape["recipe"] = existing[:effective_target]

    analysis.num_layers = int(effective_target)

    new_preview_colors = dict(analysis.preview_colors)
    new_slot_names = list(analysis.slot_names)
    changed_preview = False
    for shape in analysis.matched_shapes:
        recipe = shape.get("recipe") or []
        if not recipe:
            continue
        top_ch = int(recipe[0])
        if top_ch in new_preview_colors:
            continue
        if top_ch < lut_palette_length and img_processor is not None and hasattr(img_processor, "lut_rgb"):
            try:
                lut_color = img_processor.lut_rgb[top_ch]
                new_preview_colors[top_ch] = [int(c) for c in lut_color] + [255]
                changed_preview = True
            except (IndexError, TypeError, ValueError):
                pass
        elif top_ch >= lut_palette_length:
            vidx = top_ch - lut_palette_length
            if 0 <= vidx < len(virtual_registry):
                try:
                    r, g, b = _hex_to_rgb_tuple(virtual_registry[vidx]["hex"])
                    new_preview_colors[top_ch] = [int(r), int(g), int(b), 255]
                    changed_preview = True
                except (ValueError, TypeError, KeyError):
                    pass
        while len(new_slot_names) <= top_ch:
            new_slot_names.append("Slot_" + str(len(new_slot_names)))
    if changed_preview:
        analysis.preview_colors = new_preview_colors
        analysis.slot_names = new_slot_names

    _log.debug(
        "Applied recipe overrides: shapes=%s, overridden=%s, regions=%s, "
        "virtuals=%s, target_layers=%s",
        len(analysis.matched_shapes),
        overridden_count,
        len(normalised_masks),
        len(virtual_registry),
        effective_target,
    )


def apply_matched_rgb_overrides_to_analysis(
    analysis: "VectorAnalysis",
    *,
    matched_rgb: np.ndarray,
    material_matrix: np.ndarray | None = None,
    mask_solid: np.ndarray,
    img_processor,
    pixels_per_mm: float = 10.0,
    max_width_px: int = 1600,
) -> int:
    """Propagate region-level ``matched_rgb`` edits into ``matched_shapes``.
    把 ``cache.matched_rgb`` 上的像素级改色回写到 ``analysis.matched_shapes``。

    The 2D preview / GLB previews route through ``cache.matched_rgb``:
    ``/region-replace`` and ``/region-replace-batch`` mutate that array
    by mask, so the preview reflects the user's edit immediately. The
    SVG-native ``_run_vector_branch`` previously re-derived per-shape
    colours from the SVG fill alone, silently dropping every spatial
    edit. This helper closes that gap by:

    1. Reproducing the same preview grid ``build_preview_cache`` uses
       so the ``matched_rgb`` / ``mask_solid`` arrays line up pixel-for-
       pixel with the analysis geometry.
    2. Rasterising each ``analysis.matched_shapes`` entry into its own
       boolean mask and intersecting it with ``mask_solid`` (background
       pixels are ignored so a "carved out" hole cannot poison the
       per-shape colour vote).
    3. Picking the dominant RGB inside the effective mask. If it differs
       from ``shape['matched_rgb']`` we re-run the same KDTree lookup
       ``_match_colors`` uses so the new ``matched_rgb`` / ``recipe``
       come from the LUT — guaranteeing the generated 3MF stays inside
       the user's calibrated material set.

    The helper preserves every public surface (the module exports it,
    nothing else changes) and is therefore opt-in for callers that have
    a fresh ``cache.matched_rgb`` to forward.

    2D 预览 / GLB 走 ``cache.matched_rgb``，``/region-replace`` 之类
    端点会按 mask 改写它，但生成阶段的矢量分支以前只从 SVG fill 复算
    颜色，用户的空间改色被静默丢弃。本 helper 复现 ``build_preview_cache``
    网格，逐 shape 求 mask，与 ``mask_solid`` 求交后取 dominant RGB，
    若与原 ``matched_rgb`` 不一致则重新走 KDTree 查 LUT，把新颜色和配方
    回写到 ``matched_shapes``，让 3MF 与 2D 预览保持一致。

    Args:
        analysis: ``VectorAnalysis`` from ``analyze_svg``; mutated in place.
            （``analyze_svg`` 返回的分析结果，就地修改）
        matched_rgb: ``(H, W, 3) uint8`` array taken from ``cache["matched_rgb"]``.
            （取自 ``cache["matched_rgb"]`` 的预览栅格）
        mask_solid: ``(H, W) bool`` array taken from ``cache["mask_solid"]``.
            （取自 ``cache["mask_solid"]`` 的实体像素掩码）
        img_processor: Object exposing ``_rgb_to_lab``, ``kdtree``,
            ``lut_rgb`` and ``ref_stacks`` — the same interface
            ``VectorProcessor._match_colors`` consumes.
            （提供 LUT KDTree / 调色板 / 配方 stack 的处理器对象）
        pixels_per_mm: Preview-grid density. Must match the value used
            by :meth:`VectorProcessor.build_preview_cache`.
            （预览网格密度，需与 ``build_preview_cache`` 一致）
        max_width_px: Preview-grid width cap. Same constraint.
            （预览网格宽度上限，同上）

    Returns:
        int: Number of shapes whose ``matched_rgb`` was rewritten.
            （颜色被改写的 shape 数量）
    """
    if matched_rgb is None or mask_solid is None:
        return 0
    if not analysis.matched_shapes:
        return 0

    real_w = float(analysis.bbox[2])
    real_h = float(analysis.bbox[3])
    sf = float(analysis.scale_factor)
    w_mm = real_w * sf
    h_mm = real_h * sf
    if w_mm <= 0 or h_mm <= 0:
        return 0

    ppm = float(pixels_per_mm)
    w_px = max(1, int(round(w_mm * ppm)))
    h_px = max(1, int(round(h_mm * ppm)))
    if w_px > max_width_px:
        ratio = max_width_px / w_px
        w_px = max_width_px
        h_px = max(1, int(round(h_px * ratio)))
        ppm = w_px / w_mm
    coord_scale = sf * ppm

    matched_arr = np.asarray(matched_rgb)
    mask_arr = np.asarray(mask_solid, dtype=bool)
    if matched_arr.ndim != 3 or matched_arr.shape[2] != 3 or matched_arr.dtype != np.uint8:
        error_message = (
            f"matched_rgb shape/dtype {matched_arr.shape}/{matched_arr.dtype} "
            "is not (H,W,3) uint8"
        )
        _log.warning(
            "Vector matched RGB overrides skipped because input array is invalid",
            extra={
                "event": "vector_overrides_input_invalid",
                "error_type": "ValueError",
                "error_message": error_message,
                "matched_rgb_shape": list(matched_arr.shape),
                "matched_rgb_dtype": str(matched_arr.dtype),
            },
        )
        return 0
    if matched_arr.shape[:2] != (h_px, w_px) or mask_arr.shape != (h_px, w_px):
        error_message = (
            f"matched_rgb/mask_solid shape {matched_arr.shape[:2]}/{mask_arr.shape} "
            f"does not match preview grid {(h_px, w_px)}"
        )
        _log.warning(
            "Vector matched RGB overrides skipped because cache grid mismatched analysis",
            extra={
                "event": "vector_overrides_grid_mismatch",
                "error_type": "ValueError",
                "error_message": error_message,
                "matched_rgb_shape": list(matched_arr.shape[:2]),
                "mask_solid_shape": list(mask_arr.shape),
                "expected_shape": [int(h_px), int(w_px)],
            },
        )
        return 0

    def _iter_polygons(geom):
        if geom is None or geom.is_empty:
            return []
        if geom.geom_type == "Polygon":
            return [geom]
        if geom.geom_type == "MultiPolygon":
            return list(geom.geoms)
        return []

    def _coords_to_pts(coords):
        pts = np.column_stack(
            [
                coords[:, 0] * coord_scale,
                coords[:, 1] * coord_scale,
            ]
        ).astype(np.int32)
        if len(pts) < 3:
            return None
        return pts

    def _shape_mask(geom):
        region = np.zeros((h_px, w_px), dtype=np.uint8)
        painted = False
        for poly in _iter_polygons(geom):
            if poly.is_empty:
                continue
            ext_pts = _coords_to_pts(np.array(poly.exterior.coords))
            if ext_pts is None:
                continue
            cv2.fillPoly(region, [ext_pts], 255)
            painted = True
            for interior in poly.interiors:
                hole_pts = _coords_to_pts(np.array(interior.coords))
                if hole_pts is not None:
                    cv2.fillPoly(region, [hole_pts], 0)
        if not painted:
            return None
        return region.astype(bool)

    num_channels = int(getattr(analysis, "num_channels", 0) or 0)
    num_layers = int(getattr(analysis, "num_layers", 0) or 0)
    if num_channels <= 0 or num_layers <= 0:
        return 0

    lut_rgb = img_processor.lut_rgb
    ref_stacks = img_processor.ref_stacks
    matrix_arr = None
    if material_matrix is not None:
        candidate_matrix = np.asarray(material_matrix)
        if candidate_matrix.ndim == 3 and candidate_matrix.shape[:2] == (h_px, w_px):
            matrix_arr = candidate_matrix
        else:
            _log.warning(
                "Vector material matrix overrides skipped because cache grid mismatched analysis",
                extra={
                    "event": "vector_material_matrix_grid_mismatch",
                    "error_type": "ValueError",
                    "error_message": (
                        f"material_matrix shape {candidate_matrix.shape} "
                        f"does not match preview grid {(h_px, w_px)}"
                    ),
                    "material_matrix_shape": list(candidate_matrix.shape),
                    "expected_shape": [int(h_px), int(w_px)],
                },
            )

    changed = 0
    per_shape_diag: list[dict] = []
    for shape_idx, shape in enumerate(analysis.matched_shapes):
        geom = shape.get("geometry")
        if geom is None or getattr(geom, "is_empty", False):
            continue
        shape_mask = _shape_mask(geom)
        if shape_mask is None:
            continue
        effective_mask = np.logical_and(shape_mask, mask_arr)
        if not np.any(effective_mask):
            continue

        pixels = matched_arr[effective_mask]
        codes = (
            pixels[:, 0].astype(np.uint32) * np.uint32(65536)
            + pixels[:, 1].astype(np.uint32) * np.uint32(256)
            + pixels[:, 2].astype(np.uint32)
        )
        uniq, counts = np.unique(codes, return_counts=True)
        dominant_code = int(uniq[int(np.argmax(counts))])
        dominant_rgb = (
            (dominant_code >> 16) & 0xFF,
            (dominant_code >> 8) & 0xFF,
            dominant_code & 0xFF,
        )

        query_lab = img_processor._rgb_to_lab(np.array([dominant_rgb], dtype=np.uint8))
        _, index = img_processor.kdtree.query(query_lab)
        try:
            lut_idx = int(np.atleast_1d(index)[0])
        except (TypeError, ValueError, IndexError):
            continue
        new_matched_rgb = tuple(int(c) for c in lut_rgb[lut_idx])

        stack_source = "ref_stacks_fallback"
        stack_top_alternatives: list[list[int]] = []
        if matrix_arr is not None:
            stacks = np.asarray(matrix_arr[effective_mask], dtype=np.int32)
            if stacks.ndim == 2 and stacks.shape[1] > 0:
                uniq_stacks, stack_counts = np.unique(stacks, axis=0, return_counts=True)
                stack = uniq_stacks[int(np.argmax(stack_counts))]
                stack_source = "material_matrix_majority"
                top_n = min(3, len(stack_counts))
                top_indices = np.argsort(-stack_counts)[:top_n]
                for ti in top_indices:
                    stack_top_alternatives.append(
                        [int(c) for c in uniq_stacks[ti].tolist()[:6]]
                        + [int(stack_counts[ti])]
                    )
            else:
                stack = ref_stacks[lut_idx]
        else:
            stack = ref_stacks[lut_idx]
        new_recipe = _normalise_cached_stack_for_vector_recipe(
            stack,
            target_layers=num_layers,
            num_channels=num_channels,
        )

        prev_rgb = shape.get("matched_rgb")
        prev_recipe = [int(v) for v in shape.get("recipe", [])]

        if len(per_shape_diag) < 24:
            try:
                area = float(geom.area) if geom is not None else 0.0
            except (AttributeError, TypeError, ValueError):
                area = 0.0
            per_shape_diag.append(
                {
                    "shape_idx": int(shape_idx),
                    "area": round(area, 3),
                    "effective_pixels": int(np.count_nonzero(effective_mask)),
                    "dominant_rgb": list(dominant_rgb),
                    "lut_idx": int(lut_idx),
                    "matched_rgb": list(new_matched_rgb),
                    "stack_source": stack_source,
                    "stack_first6": [int(c) for c in stack[:6].tolist()] if hasattr(stack, "tolist") else list(stack[:6]),
                    "stack_top_alternatives_first6_with_count": stack_top_alternatives,
                    "new_recipe_first6": new_recipe[:6],
                    "prev_recipe_first6": prev_recipe[:6],
                }
            )

        if (
            isinstance(prev_rgb, tuple)
            and tuple(int(c) for c in prev_rgb) == new_matched_rgb
            and prev_recipe == new_recipe
        ):
            continue

        shape["matched_rgb"] = new_matched_rgb
        shape["lut_idx"] = lut_idx
        shape["recipe"] = new_recipe
        changed += 1

    # Diagnostic: emit per-shape majority vote details.
    if per_shape_diag:
        _log.debug(
            "Vector per-shape majority vote diagnostics",
            extra={
                "event": "vector_diag_apply_matched_rgb_per_shape",
                "stage": "apply_matched_rgb_overrides_per_shape",
                "per_shape_diag": per_shape_diag,
            },
        )

    if changed:
        _log.debug(
            "Vector matched RGB overrides applied",
            extra={
                "event": "vector_overrides_applied",
                "shape_count": len(analysis.matched_shapes),
                "rewritten_count": int(changed),
            },
        )
    return changed


def _normalise_cached_stack_for_vector_recipe(
    stack: np.ndarray,
    *,
    target_layers: int,
    num_channels: int,
) -> list[int]:
    """Return a full-length vector recipe from a cached material stack."""
    if target_layers <= 0 or num_channels <= 0:
        return []

    flat = np.asarray(stack, dtype=np.int32).reshape(-1)
    clamped_values = [
        min(int(value), int(num_channels) - 1)
        for value in flat[:target_layers].tolist()
        if int(value) >= 0
    ]
    filler = int(clamped_values[-1]) if clamped_values else 0

    recipe: list[int] = []
    for raw_value in flat[:target_layers]:
        value = int(raw_value)
        if value < 0:
            recipe.append(filler)
        else:
            recipe.append(min(value, int(num_channels) - 1))

    if len(recipe) < target_layers:
        recipe.extend([filler] * (target_layers - len(recipe)))
    return recipe


class VectorProcessor:
    """
    Native vector processing engine for SVG files.

    Converts SVG directly to 3D meshes without rasterization,
    preserving vector precision.  Uses ChromaPrint3D-style
    occlusion clipping and run-length layer extrusion.

    Attributes:
        color_mode: Color system mode string forwarded to ColorSystem.
        img_processor: LuminaImageProcessor instance for LUT / KDTree access.
        sampling_precision: Curve approximation precision in mm.
    """

    def __init__(
        self,
        lut_path: str,
        color_mode: str,
        *,
        hue_weight: float = 0.0,
        chroma_gate: float = 15.0,
    ):
        """Initialize the LUT-backed SVG vector processor.

        初始化基于 LUT 的 SVG 矢量处理器。

        Args:
            lut_path: LUT file path used for color-to-recipe matching.
                用于颜色匹配到配方的 LUT 文件路径。
            color_mode: Canonical color mode label for this conversion.
                本次转换使用的标准颜色模式名称。
            hue_weight: Hue-protection strength forwarded to the shared
                image processor. 色相保护强度，传给共用图像处理器。
            chroma_gate: Chroma threshold for dark-color protection.
                暗色保护的彩度门槛。
        """
        self.color_mode = color_mode
        _log.debug("Initializing Native Vector Engine (%s)...", color_mode)

        ImageProcessor = _get_image_processor_class()
        self.img_processor = ImageProcessor(
            lut_path,
            color_mode,
            hue_weight=hue_weight,
            chroma_gate=chroma_gate,
        )
        self._init_runtime_defaults()

        _log.debug("Initialized with %s LUT colors", len(self.img_processor.ref_stacks))

    def _init_runtime_defaults(self) -> None:
        """Set the non-color-matching runtime fields shared by both
        constructors (LUT path and material-archive path).

        Centralised so :meth:`from_img_processor` does not drift if new
        runtime defaults are added later. ``__init__`` and the factory
        both call this immediately after wiring ``img_processor``.

        集中初始化与匹配器无关的运行时默认值，避免 LUT/耗材两条
        构造路径走偏。
        """
        self.sampling_precision = 0.02  # mm
        self.last_stage_timings = {}
        self.parse_warnings: list[str] = []
        self.enable_fridge_magnet = False
        self.fridge_magnets: list = []
        self.enable_coating = False
        self.coating_height_mm = 0.08
        self.expand_stroke_to_fill = False

    @classmethod
    def from_img_processor(
        cls, img_processor, color_mode: str
    ) -> "VectorProcessor":
        """Build a ``VectorProcessor`` around a pre-built color matcher.

        Used by the material-archive branch which constructs a
        :class:`core.vector_matchers.MaterialVectorMatcher` instead of
        loading a LUT from disk. The matcher must duck-type the small
        slice of :class:`core.image_processing.LuminaImageProcessor`
        that ``analyze_svg`` / ``_match_colors`` consume (see
        :mod:`core.vector_matchers` module docstring for the full
        contract).

        从已构造的颜色匹配器构造 VectorProcessor；耗材档案分支用
        此入口，避免触发 LUT 文件解析。

        Args:
            img_processor: Object exposing the LuminaImageProcessor
                duck surface required by the vector pipeline.
            color_mode: Display string forwarded to logs and exports.

        Returns:
            A configured ``VectorProcessor`` ready for ``analyze_svg``.
        """
        instance = cls.__new__(cls)
        instance.color_mode = color_mode
        instance.img_processor = img_processor
        instance._init_runtime_defaults()
        _log.debug(
            "Initialized Vector Engine via injected matcher (%s)",
            color_mode,
        )
        return instance

    def _build_small_shape_match_overrides(self, clipped_shapes, scale_factor):
        max_area_ratio = float(
            getattr(VectorConfig, "MATERIAL_VECTOR_SMALL_SHAPE_SNAP_MAX_AREA_RATIO", 0.0)
        )
        min_anchor_ratio = float(
            getattr(VectorConfig, "MATERIAL_VECTOR_SMALL_SHAPE_SNAP_MIN_ANCHOR_AREA_RATIO", 0.0)
        )
        delta_e_threshold = float(
            getattr(VectorConfig, "MATERIAL_VECTOR_SMALL_SHAPE_SNAP_DELTA_E", 0.0)
        )
        if not clipped_shapes or max_area_ratio <= 0.0 or delta_e_threshold <= 0.0:
            return {}

        area_by_color = {}
        total_area_mm2 = 0.0
        mm2_scale = float(scale_factor) * float(scale_factor)
        for item in clipped_shapes:
            color = item.get("color")
            geom = item.get("geometry")
            if color is None or geom is None or geom.is_empty:
                continue
            try:
                key = (int(color[0]), int(color[1]), int(color[2]))
            except (TypeError, IndexError, ValueError):
                continue
            area_mm2 = max(0.0, float(geom.area) * mm2_scale)
            total_area_mm2 += area_mm2
            area_by_color[key] = area_by_color.get(key, 0.0) + area_mm2

        if total_area_mm2 <= 0.0 or len(area_by_color) < 2:
            return {}

        source_colors = sorted(area_by_color)
        src_rgb = np.array(source_colors, dtype=np.uint8)
        src_lab = self.img_processor._rgb_to_lab(src_rgb).reshape(-1, 3).astype(np.float64)
        _, lut_indices = self.img_processor.kdtree.query(src_lab)
        lut_indices = np.asarray(lut_indices).reshape(-1)
        matched_rgb = self.img_processor.lut_rgb[lut_indices].astype(np.uint8, copy=False)
        matched_lab = self.img_processor._rgb_to_lab(matched_rgb).reshape(-1, 3).astype(np.float64)
        delta_e = np.linalg.norm(src_lab - matched_lab, axis=1)

        area_ratio_by_color = {
            rgb: (float(area_by_color[rgb]) / total_area_mm2)
            for rgb in source_colors
        }
        anchor_colors = [
            rgb for rgb in source_colors
            if area_ratio_by_color[rgb] >= min_anchor_ratio
        ]
        if not anchor_colors:
            anchor_colors = [max(source_colors, key=lambda rgb: area_by_color[rgb])]

        lab_by_color = {
            rgb: src_lab[idx]
            for idx, rgb in enumerate(source_colors)
        }
        matched_by_color = {
            rgb: tuple(int(c) for c in matched_rgb[idx])
            for idx, rgb in enumerate(source_colors)
        }

        overrides = {}
        snapped_shape_count = 0
        snapped_source_colors = set()
        delta_e_by_color = {
            rgb: float(delta_e[idx])
            for idx, rgb in enumerate(source_colors)
        }
        for shape_idx, item in enumerate(clipped_shapes):
            color = item.get("color")
            geom = item.get("geometry")
            if color is None or geom is None or geom.is_empty:
                continue
            try:
                rgb = (int(color[0]), int(color[1]), int(color[2]))
            except (TypeError, IndexError, ValueError):
                continue
            shape_area_ratio = (max(0.0, float(geom.area) * mm2_scale) / total_area_mm2)
            if shape_area_ratio > max_area_ratio or delta_e_by_color[rgb] <= delta_e_threshold:
                continue
            candidate_anchors = [anchor for anchor in anchor_colors if anchor != rgb]
            if not candidate_anchors:
                continue
            src_vec = lab_by_color[rgb]
            chosen_anchor = min(
                candidate_anchors,
                key=lambda anchor: float(np.linalg.norm(src_vec - lab_by_color[anchor])),
            )
            if chosen_anchor == rgb:
                continue
            overrides[shape_idx] = chosen_anchor
            snapped_shape_count += 1
            snapped_source_colors.add(rgb)
            _log.debug(
                "Vector small-shape snap: %s -> %s shape_area_ratio=%.4f color_area_ratio=%.4f dE=%.2f matched=%s anchor_matched=%s",
                _rgb_to_hex(rgb),
                _rgb_to_hex(chosen_anchor),
                shape_area_ratio,
                area_ratio_by_color[rgb],
                delta_e_by_color[rgb],
                _rgb_to_hex(matched_by_color[rgb]),
                _rgb_to_hex(matched_by_color[chosen_anchor]),
            )

        if overrides:
            _log.info(
                "Vector small-shape snap applied: colors=%d shapes=%d max_area_ratio=%.4f min_anchor_ratio=%.4f delta_e=%.1f",
                len(snapped_source_colors),
                snapped_shape_count,
                max_area_ratio,
                min_anchor_ratio,
                delta_e_threshold,
                extra={
                    "event": "vector_material_small_shape_snap_applied",
                    "snapped_color_count": len(snapped_source_colors),
                    "snapped_shape_count": snapped_shape_count,
                    "max_area_ratio": max_area_ratio,
                    "min_anchor_area_ratio": min_anchor_ratio,
                    "delta_e_threshold": delta_e_threshold,
                },
            )

        return overrides

    # ── Geometry pre-processing helpers ─────────────────────────────────

    @staticmethod
    def _normalize_contours(geom, close_delta_mm=0.03):
        """Morphological close: inflate -> deflate to fill micro-gaps.

        Mirrors ``ChromaPrint3D::NormalizeContours`` (Clipper2 inflate/deflate).
        Uses Shapely ``buffer`` as an equivalent operation.
        """
        if geom is None or geom.is_empty:
            return geom
        try:
            inflated = geom.buffer(close_delta_mm, join_style="mitre", mitre_limit=2.0)
            if inflated.is_empty:
                return geom
            deflated = inflated.buffer(-close_delta_mm, join_style="mitre", mitre_limit=2.0)
            if deflated.is_empty:
                return geom
            result = make_valid(deflated)
            # If make_valid returned GeometryCollection with non-polygon
            # elements only (e.g. LineString, Point from degenerate geometry),
            # fall back to pre-make_valid state to avoid downstream errors.
            # 若 make_valid 返回含非多边形退化元素的 GeometryCollection，
            # 退回 make_valid 之前的状态，避免下游类型错误。
            if result is not None and result.geom_type == "GeometryCollection":
                polys = [g for g in result.geoms if g.geom_type in ("Polygon", "MultiPolygon")]
                if polys:
                    result = MultiPolygon(polys) if len(polys) > 1 else polys[0]
                else:
                    return deflated
            return result
        except Exception:
            return geom

    @staticmethod
    def _filter_backing_holes(geom, min_hole_area_mm2=1.0):
        """Remove small holes from the backing plate polygon.

        Mirrors ``ChromaPrint3D``'s ``base_min_hole_area_mm2`` filtering.
        """
        if geom is None or geom.is_empty:
            return geom
        if geom.geom_type == "Polygon":
            kept = [h for h in geom.interiors if Polygon(h).area >= min_hole_area_mm2]
            return Polygon(geom.exterior, kept)
        if geom.geom_type == "MultiPolygon":
            polys = []
            for p in geom.geoms:
                kept = [h for h in p.interiors if Polygon(h).area >= min_hole_area_mm2]
                polys.append(Polygon(p.exterior, kept))
            return MultiPolygon(polys)
        return geom

    @staticmethod
    def _filter_slits(geom, min_slit_width_mm=0.1):
        """Filter sub-threshold slit-like features from polygonal geometry."""
        if geom is None or geom.is_empty:
            return geom

        try:
            distance = float(min_slit_width_mm) / 2.0 + 1e-9
        except (TypeError, ValueError):
            distance = 0.05 + 1e-9
        if distance <= 0:
            return geom

        try:
            expanded = geom.buffer(distance)
            closed = expanded.buffer(-distance)
            if closed.is_empty:
                return geom

            opened = geom.buffer(-distance).buffer(distance)
            result = closed
            if (
                not opened.is_empty
                and VectorProcessor._polygon_component_count(opened)
                > VectorProcessor._polygon_component_count(closed)
            ):
                result = opened

            result = VectorProcessor._extract_polygonal_geometry(make_valid(result))
            return result if result is not None and not result.is_empty else geom
        except VECTOR_HANDLED_ERRORS:
            return geom

    @staticmethod
    def _polygon_component_count(geom) -> int:
        if geom is None or geom.is_empty:
            return 0
        if geom.geom_type == "Polygon":
            return 1
        if geom.geom_type == "MultiPolygon":
            return len(geom.geoms)
        return 0

    @staticmethod
    def _centered_mm_to_vector_coords(center_x_mm, center_y_mm, bbox, scale_factor):
        """Convert centered preview-space mm into normalized vector coordinates."""
        if scale_factor <= 0:
            raise ValueError("scale_factor must be positive")

        min_x = float(bbox[0])
        min_y = float(bbox[1])
        width = float(bbox[2])
        height = float(bbox[3])
        center_x_svg = min_x + (width / 2.0) + (float(center_x_mm) / float(scale_factor))
        center_y_svg = min_y + (height / 2.0) - (float(center_y_mm) / float(scale_factor))
        return (center_x_svg, center_y_svg)

    @staticmethod
    def _build_vector_fridge_magnet_outline(magnet, bbox, scale_factor):
        """Build one fridge-magnet footprint in normalized vector polygon space."""
        center_x, center_y = VectorProcessor._centered_mm_to_vector_coords(
            magnet.get("center_x_mm", 0.0),
            magnet.get("center_y_mm", 0.0),
            bbox,
            scale_factor,
        )

        shape = str(magnet.get("shape", "") or "").lower()
        if shape == "round":
            diameter_mm = float(magnet.get("diameter_mm") or 0.0)
            if diameter_mm <= 0:
                return None
            radius_svg = (diameter_mm / 2.0) / float(scale_factor)
            return Point(center_x, center_y).buffer(radius_svg, resolution=32)

        if shape == "rect":
            width_mm = float(magnet.get("width_mm") or 0.0)
            height_mm = float(magnet.get("height_mm") or 0.0)
            if width_mm <= 0 or height_mm <= 0:
                return None
            half_width_svg = (width_mm / 2.0) / float(scale_factor)
            half_height_svg = (height_mm / 2.0) / float(scale_factor)
            return box(
                center_x - half_width_svg,
                center_y - half_height_svg,
                center_x + half_width_svg,
                center_y + half_height_svg,
            )

        return None

    @staticmethod
    def _build_vector_fridge_cavity_specs(
        backing_sil,
        fridge_magnets,
        bbox,
        scale_factor,
        backing_height,
        shell_thickness_mm=0.4,
    ):
        """Build clipped cavity footprint geometries with per-magnet depths."""
        if not fridge_magnets or backing_sil is None or backing_sil.is_empty:
            return []

        specs = []
        backing_bounds = backing_sil.bounds
        backing_bbox = (
            float(backing_bounds[0]),
            float(backing_bounds[1]),
            float(backing_bounds[2] - backing_bounds[0]),
            float(backing_bounds[3] - backing_bounds[1]),
        )
        for magnet in fridge_magnets:
            depth_mm = float(magnet.get("thickness_mm") or 0.0)
            if depth_mm <= 0 or depth_mm + shell_thickness_mm > backing_height + 1e-9:
                continue

            footprint = VectorProcessor._build_vector_fridge_magnet_outline(magnet, backing_bbox, scale_factor)
            if footprint is None or footprint.is_empty:
                continue

            try:
                clipped = backing_sil.intersection(footprint)
            except VECTOR_HANDLED_ERRORS:
                clipped = footprint

            clipped = VectorProcessor._extract_polygonal_geometry(make_valid(clipped))
            if clipped is None or clipped.is_empty:
                continue
            specs.append({"geometry": clipped, "depth_mm": depth_mm})

        return specs

    @staticmethod
    def _build_backing_cavity_slabs(
        backing_sil,
        backing_z_start,
        backing_height,
        cavity_specs,
        outer_side="high",
        shell_thickness_mm=0.4,
    ):
        """Split backing into full-shell, cavity, and inner slabs without mesh booleans."""
        if backing_sil is None or backing_sil.is_empty or backing_height <= 0:
            return []

        if shell_thickness_mm <= 0 or shell_thickness_mm >= backing_height:
            return [{"geometry": backing_sil, "z_offset": backing_z_start, "height": backing_height, "kind": "full"}]

        valid_specs = [
            spec
            for spec in (cavity_specs or [])
            if spec.get("geometry") is not None
            and not spec["geometry"].is_empty
            and float(spec.get("depth_mm", 0.0) or 0.0) > 0.0
            and float(spec.get("depth_mm", 0.0) or 0.0) + shell_thickness_mm <= backing_height + 1e-9
        ]
        if not valid_specs:
            return [{"geometry": backing_sil, "z_offset": backing_z_start, "height": backing_height, "kind": "full"}]

        cut_positions = [0.0, shell_thickness_mm, backing_height]
        for spec in valid_specs:
            cut_positions.append(min(backing_height, shell_thickness_mm + float(spec["depth_mm"])))
        cut_positions = sorted({round(pos, 6) for pos in cut_positions})

        slabs = []
        for inward_start, inward_end in zip(cut_positions, cut_positions[1:]):
            band_height = inward_end - inward_start
            if band_height <= 1e-9:
                continue

            if inward_start < shell_thickness_mm - 1e-9:
                band_geom = backing_sil
                band_kind = "outer_shell"
            else:
                active_geoms = [
                    spec["geometry"]
                    for spec in valid_specs
                    if shell_thickness_mm + float(spec["depth_mm"]) > inward_start + 1e-9
                ]
                if active_geoms:
                    cavity_union = unary_union(active_geoms)
                    cavity_union = VectorProcessor._extract_polygonal_geometry(make_valid(cavity_union))
                    band_geom = backing_sil.difference(cavity_union) if cavity_union is not None else backing_sil
                    band_kind = "cavity_band"
                else:
                    band_geom = backing_sil
                    band_kind = "inner_backing"

                band_geom = VectorProcessor._extract_polygonal_geometry(make_valid(band_geom))
                if band_geom is None or band_geom.is_empty:
                    continue

            if outer_side == "high":
                z_offset = backing_z_start + (backing_height - inward_end)
            else:
                z_offset = backing_z_start + inward_start

            slabs.append({"geometry": band_geom, "z_offset": z_offset, "height": band_height, "kind": band_kind})

        slabs.sort(key=lambda slab: slab["z_offset"])
        return slabs

    @staticmethod
    def _split_disconnected_shapes(shape_data):
        """Split MultiPolygon / GeometryCollection shapes into individual Polygons.

        Mirrors ``ChromaPrint3D::SplitDisconnectedShapes``.  Shapely already
        distinguishes exterior rings from holes inside ``Polygon`` objects, so
        no explicit containment-depth analysis is needed.
        """
        result = []
        for item in shape_data:
            geom = item["poly"]
            if geom is None or geom.is_empty:
                continue
            if geom.geom_type == "Polygon":
                if geom.area >= MIN_SHAPE_AREA_MM2:
                    result.append(item)
            elif geom.geom_type == "MultiPolygon":
                for poly in geom.geoms:
                    if not poly.is_empty and poly.area >= MIN_SHAPE_AREA_MM2:
                        result.append({**item, "poly": poly})
            elif geom.geom_type == "GeometryCollection":
                for g in geom.geoms:
                    if g.is_empty or not hasattr(g, "area") or g.area < MIN_SHAPE_AREA_MM2:
                        continue
                    if g.geom_type == "Polygon":
                        result.append({**item, "poly": g})
                    elif g.geom_type == "MultiPolygon":
                        for poly in g.geoms:
                            if not poly.is_empty and poly.area >= MIN_SHAPE_AREA_MM2:
                                result.append({**item, "poly": poly})
        return result

    @staticmethod
    def _extract_polygonal_geometry(geom):
        """Return only polygonal parts from arbitrary Shapely geometry.

        ``make_valid()`` can turn self-intersecting filled SVG paths into a
        ``GeometryCollection`` containing a ``MultiPolygon`` plus stray line
        segments.  The vector parser must preserve those polygonal parts
        instead of dropping the whole element.
        """
        if geom is None or geom.is_empty:
            return None
        if geom.geom_type in ("Polygon", "MultiPolygon"):
            return geom
        if geom.geom_type != "GeometryCollection":
            return None

        polygon_parts = []
        for child in geom.geoms:
            extracted = VectorProcessor._extract_polygonal_geometry(child)
            if extracted is None or extracted.is_empty:
                continue
            if extracted.geom_type == "Polygon":
                polygon_parts.append(extracted)
            elif extracted.geom_type == "MultiPolygon":
                polygon_parts.extend([poly for poly in extracted.geoms if not poly.is_empty])

        if not polygon_parts:
            return None
        if len(polygon_parts) == 1:
            return polygon_parts[0]

        try:
            merged = unary_union(polygon_parts)
            return merged if merged is not None and not merged.is_empty else MultiPolygon(polygon_parts)
        except Exception:
            return MultiPolygon(polygon_parts)

    @staticmethod
    def _parse_gradient_defs(svg_path):
        """Pre-parse SVG XML to extract gradient definitions.

        Returns ``{gradient_id: {type, stops, units, transform, ...}}``
        for linear and radial gradients.

        Handles ``gradientUnits``, ``gradientTransform``,
        ``xlink:href`` / ``href`` inheritance, percentage coordinate
        values, and ``stop-color`` defined via the ``style`` attribute.

        解析 SVG XML 提取渐变定义，支持坐标变换、单位、继承、
        百分比值和 style 属性中的 stop-color。
        """
        _SVG_NS = {"svg": "http://www.w3.org/2000/svg"}
        _XLINK_HREF = "{http://www.w3.org/1999/xlink}href"
        gradients = {}
        try:
            tree = ET.parse(svg_path)
            root = tree.getroot()
        except Exception:
            return gradients

        def _parse_stops(parent):
            stops = []
            for s in parent.findall("svg:stop", _SVG_NS):
                raw_off = s.get("offset", "0")
                offset = float(raw_off.rstrip("%")) / (100.0 if "%" in raw_off else 1.0)
                raw_c = s.get("stop-color")
                if not raw_c:
                    style = s.get("style", "")
                    m = re.search(r"stop-color\s*:\s*([^;]+)", style)
                    if m:
                        raw_c = m.group(1).strip()
                if not raw_c:
                    raw_c = "black"
                try:
                    c = Color(raw_c)
                    rgb = (int(c.red), int(c.green), int(c.blue))
                except Exception:
                    rgb = (0, 0, 0)
                stops.append((offset, rgb))
            return stops

        elem_map = {}
        for tag in ("linearGradient", "radialGradient"):
            for elem in root.iter(f"{{http://www.w3.org/2000/svg}}{tag}"):
                gid = elem.get("id")
                if gid:
                    elem_map[gid] = elem

        def _resolve(gid, visited=None):
            if visited is None:
                visited = set()
            if gid in gradients:
                return gradients[gid]
            if gid not in elem_map or gid in visited:
                return None
            visited.add(gid)

            elem = elem_map[gid]
            tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag

            href = elem.get(_XLINK_HREF) or elem.get("href")
            href_id = href.lstrip("#") if href else None
            parent = _resolve(href_id, visited) if href_id else None

            stops = _parse_stops(elem)
            if not stops and parent:
                stops = parent.get("stops", [])

            raw_units = elem.get("gradientUnits")
            if raw_units is None and parent:
                raw_units = parent.get("units")
            units = raw_units if raw_units in ("userSpaceOnUse", "objectBoundingBox") else "objectBoundingBox"

            raw_tf = elem.get("gradientTransform")
            if raw_tf is not None:
                transform = _parse_svg_transform(raw_tf)
            elif parent is not None:
                transform = parent.get("transform", np.eye(3, dtype=np.float64))
            else:
                transform = np.eye(3, dtype=np.float64)

            def _coord(attr, default):
                val = elem.get(attr)
                if val is not None:
                    return _parse_gradient_length(val, default)
                if parent is not None:
                    return parent.get(attr, default)
                return default

            if tag == "linearGradient":
                info = {
                    "type": "linear",
                    "x1": _coord("x1", 0.0),
                    "y1": _coord("y1", 0.0),
                    "x2": _coord("x2", 1.0),
                    "y2": _coord("y2", 0.0),
                    "stops": stops,
                    "units": units,
                    "transform": transform,
                }
            elif tag == "radialGradient":
                info = {
                    "type": "radial",
                    "cx": _coord("cx", 0.5),
                    "cy": _coord("cy", 0.5),
                    "r": _coord("r", 0.5),
                    "stops": stops,
                    "units": units,
                    "transform": transform,
                }
            else:
                return None

            gradients[gid] = info
            return info

        for gid in elem_map:
            _resolve(gid)

        return gradients

    @staticmethod
    def _flatten_gradient_shape(grad_info, subpath_polys, color_bands=None):
        """Convert a gradient-filled SVG element into multiple solid-color shapes.

        Algorithm (mirrors ``ChromaPrint3D::FlattenGradientShape``):
        1. Rasterise the gradient inside the element's bounding box
        2. Quantise each pixel to the nearest gradient stop colour
        3. Extract contours per stop colour via OpenCV ``findContours``
        4. Convert pixel contours back to SVG coordinate polygons

        Correctly handles ``gradientUnits`` (``objectBoundingBox`` vs
        ``userSpaceOnUse``) and ``gradientTransform``.

        Args:
            grad_info: Gradient definition dict from ``_parse_gradient_defs``.
            subpath_polys: List of Shapely Polygon objects for the element.

        Returns list of ``{poly: Polygon, color: (r,g,b)}`` dicts.
        Falls back to sampling the gradient centre colour if extraction fails.
        """
        stops = grad_info.get("stops", [])
        if not stops:
            return []

        union_poly = unary_union(subpath_polys) if subpath_polys else None
        if union_poly is None or union_poly.is_empty:
            return []

        bx0, by0, bx1, by1 = union_poly.bounds
        bw = bx1 - bx0
        bh = by1 - by0
        if bw <= 0 or bh <= 0:
            return []

        units = grad_info.get("units", "objectBoundingBox")
        transform = grad_info.get("transform", np.eye(3, dtype=np.float64))

        def _map_point(x, y):
            """Map gradient-space coords to SVG user-space coords."""
            if units == "objectBoundingBox":
                x = bx0 + x * bw
                y = by0 + y * bh
            pt = transform @ np.array([x, y, 1.0], dtype=np.float64)
            return float(pt[0]), float(pt[1])

        def _map_radius(r):
            if units == "objectBoundingBox":
                r = r * (bw + bh) * 0.5
            sx = np.sqrt(transform[0, 0] ** 2 + transform[1, 0] ** 2)
            sy = np.sqrt(transform[0, 1] ** 2 + transform[1, 1] ** 2)
            return r * (sx + sy) * 0.5

        _MAX_GRAD_PX = 2048
        px_per_unit = min(10.0, _MAX_GRAD_PX / max(bw, bh))
        img_w = max(4, int(bw * px_per_unit))
        img_h = max(4, int(bh * px_per_unit))

        ys = np.arange(img_h)[:, None]
        xs = np.arange(img_w)[None, :]
        wx = bx0 + (xs + 0.5) / px_per_unit
        wy = by0 + (ys + 0.5) / px_per_unit

        grad_type = grad_info["type"]
        if grad_type == "linear":
            gx1, gy1 = _map_point(grad_info["x1"], grad_info["y1"])
            gx2, gy2 = _map_point(grad_info["x2"], grad_info["y2"])
            dx = gx2 - gx1
            dy = gy2 - gy1
            length_sq = dx * dx + dy * dy
            if length_sq < 1e-12:
                t_map = np.zeros((img_h, img_w), dtype=np.float32)
            else:
                t_map = ((wx - gx1) * dx + (wy - gy1) * dy) / length_sq
        elif grad_type == "radial":
            cx, cy = _map_point(grad_info["cx"], grad_info["cy"])
            r_grad = _map_radius(grad_info["r"])
            if r_grad < 1e-12:
                r_grad = max(bw, bh) / 2
            t_map = np.sqrt((wx - cx) ** 2 + (wy - cy) ** 2) / r_grad
        else:
            mid_color = _sample_gradient_stops(stops, 0.5)
            return [{"poly": union_poly, "color": mid_color}]

        t_map = np.clip(t_map, 0.0, 1.0).astype(np.float32)

        canvas = np.zeros((img_h, img_w, 3), dtype=np.uint8)
        for i in range(len(stops) - 1):
            t0, c0 = stops[i]
            t1, c1 = stops[i + 1]
            mask = (t_map >= t0) & (t_map <= t1)
            if not np.any(mask):
                continue
            if t1 - t0 < 1e-9:
                f = np.zeros_like(t_map)
            else:
                f = (t_map - t0) / (t1 - t0)
            for ch in range(3):
                canvas[:, :, ch] = np.where(
                    mask,
                    (c0[ch] + (c1[ch] - c0[ch]) * f).astype(np.uint8),
                    canvas[:, :, ch],
                )
        below = t_map < stops[0][0]
        above = t_map > stops[-1][0]
        for ch in range(3):
            canvas[:, :, ch] = np.where(below, stops[0][1][ch], canvas[:, :, ch])
            canvas[:, :, ch] = np.where(above, stops[-1][1][ch], canvas[:, :, ch])

        try:
            band_count = int(color_bands or 0)
        except (TypeError, ValueError):
            band_count = 0
        if band_count > len(stops):
            sample_t = np.linspace(0.0, 1.0, max(2, band_count))
            stop_t = np.array([float(s[0]) for s in stops], dtype=np.float64)
            sample_t = np.unique(np.concatenate([sample_t, np.clip(stop_t, 0.0, 1.0)]))
            sampled_colors = [_sample_gradient_stops(stops, float(t)) for t in sample_t]
            stop_colors = np.unique(np.array(sampled_colors, dtype=np.int16), axis=0)
        else:
            stop_colors = np.array([s[1] for s in stops], dtype=np.int16)
        flat = canvas.reshape(-1, 3).astype(np.int32)
        best_dist = np.full((flat.shape[0],), np.iinfo(np.int32).max, dtype=np.int32)
        best_idx = np.zeros((flat.shape[0],), dtype=np.int32)
        for si, scolor in enumerate(stop_colors.astype(np.int32, copy=False)):
            diff = flat - scolor
            dist = np.sum(diff * diff, axis=1, dtype=np.int32)
            better = dist < best_dist
            best_dist[better] = dist[better]
            best_idx[better] = si
        quantized_idx = best_idx.reshape(img_h, img_w)

        result_shapes = []
        for si, scolor_arr in enumerate(stop_colors):
            scolor = tuple(int(c) for c in scolor_arr)
            mask = (quantized_idx == si).astype(np.uint8) * 255
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for cnt in contours:
                if cv2.contourArea(cnt) < 4:
                    continue
                approx = cv2.approxPolyDP(cnt, 1.0, True)
                if len(approx) < 3:
                    continue
                svg_coords = [(bx0 + pt[0] / px_per_unit, by0 + pt[1] / px_per_unit) for pt in approx[:, 0, :]]
                poly = Polygon(svg_coords)
                if poly.is_valid and not poly.is_empty and poly.area > 0:
                    try:
                        clipped = poly.intersection(union_poly)
                    except Exception:
                        clipped = poly
                    if not clipped.is_empty:
                        result_shapes.append({"poly": clipped, "color": scolor})

        if not result_shapes:
            mid_color = _sample_gradient_stops(stops, 0.5)
            return [{"poly": union_poly, "color": mid_color}]

        return result_shapes

    # ── Public entry points ─────────────────────────────────────────────

    def analyze_svg(
        self,
        svg_path: str,
        target_width_mm: float,
        color_replacements: dict = None,
        progress_fn=None,
    ) -> VectorAnalysis:
        """Parse, clip, and color-match an SVG — shared by preview and mesh.
        解析、裁剪、配色 SVG — 预览与 3D 构建共享此结果。

        Args:
            svg_path:         Path to SVG file.
            target_width_mm:  Physical width in mm for the output model.
            color_replacements: Optional ``{hex: hex}`` replacement map.
            progress_fn:      Optional progress callback.

        Returns:
            A ``VectorAnalysis`` containing all intermediate data needed
            by ``build_mesh`` and ``render_preview``.
        """
        _log.debug("Analyzing: %s", svg_path)
        stage_timings = {}
        expand_stroke_to_fill = bool(getattr(self, "expand_stroke_to_fill", False))

        # === Stage 1+2: Parse & Occlusion clip (with cache) ===
        cache_key = None
        cached_entry = None
        try:
            svg_abs = os.path.abspath(svg_path)
            svg_mtime = os.path.getmtime(svg_abs)
            cache_key = (
                svg_abs,
                round(float(target_width_mm), 4),
                round(float(self.sampling_precision), 4),
                expand_stroke_to_fill,
                svg_mtime,
            )
            cached_entry = _VECTOR_PARSE_CLIP_CACHE.get(cache_key)
        except VECTOR_HANDLED_ERRORS:
            cache_key = None

        if cached_entry is not None:
            shape_data = cached_entry["shape_data"]
            clipped_shapes = cached_entry["clipped_shapes"]
            silhouette = cached_entry["silhouette"]
            image_vectorizer_bounds = cached_entry.get("image_vectorizer_bounds")
            scale_factor = cached_entry["scale_factor"]
            bbox = cached_entry["bbox"]
            stage_timings["parse_s"] = 0.0
            stage_timings["occlusion_s"] = 0.0
            _log.debug("Parse/clip cache hit: %s", os.path.basename(svg_path))
            _log.debug("Parsed %s shapes. Scale: %.4f", len(shape_data), scale_factor)
            _log.debug("After occlusion clip: %s non-overlapping shapes", len(clipped_shapes))
        else:
            t0 = time.perf_counter()
            had_parse_policy = hasattr(self, "_parse_expand_stroke_to_fill")
            previous_parse_policy = getattr(self, "_parse_expand_stroke_to_fill", None)
            self._parse_expand_stroke_to_fill = expand_stroke_to_fill
            try:
                shape_data, scale_factor, bbox = self._parse_svg(svg_path, target_width_mm)
                image_vectorizer_bounds = getattr(self, "_last_image_vectorizer_bounds", None)
            finally:
                if had_parse_policy:
                    self._parse_expand_stroke_to_fill = previous_parse_policy
                else:
                    delattr(self, "_parse_expand_stroke_to_fill")
            if not shape_data:
                raise ValueError("No valid filled shapes found in SVG.")
            stage_timings["parse_s"] = time.perf_counter() - t0
            _log.debug("Parsed %s shapes. Scale: %.4f", len(shape_data), scale_factor)

            t0 = time.perf_counter()
            _pre_area = sum(it["poly"].area for it in shape_data if it["poly"] is not None)
            clipped_shapes, silhouette = self._clip_occlusion(shape_data, return_silhouette=True)
            _clip_area = sum(it["geometry"].area for it in clipped_shapes if it["geometry"] is not None)
            _log.debug(
                "_clip_occlusion: %s -> %s shapes, area %.1f -> %.1f (%.1f%%)",
                len(shape_data),
                len(clipped_shapes),
                _pre_area,
                _clip_area,
                (_clip_area / _pre_area * 100) if _pre_area > 0 else 0.0,
            )

            post_clip = []
            for item in clipped_shapes:
                g = item["geometry"]
                g = VectorProcessor._normalize_contours(g)
                if g is not None and not g.is_empty:
                    item["geometry"] = g
                    post_clip.append(item)
            _norm_area = sum(it["geometry"].area for it in post_clip if it["geometry"] is not None)
            _log.debug(
                "post-clip normalize: %s -> %s shapes, area %.1f -> %.1f",
                len(clipped_shapes),
                len(post_clip),
                _clip_area,
                _norm_area,
            )
            clipped_shapes = post_clip

            split_input = [{"poly": it["geometry"], "color": it["color"]} for it in clipped_shapes]
            split_output = VectorProcessor._split_disconnected_shapes(split_input)
            clipped_shapes = [
                {"geometry": it["poly"], "color": it["color"], "draw_order": idx} for idx, it in enumerate(split_output)
            ]
            _split_area = sum(it["geometry"].area for it in clipped_shapes if it["geometry"] is not None)
            _log.debug(
                "split disconnected: %s -> %s shapes, area %.1f -> %.1f",
                len(post_clip),
                len(clipped_shapes),
                _norm_area,
                _split_area,
            )
            stage_timings["occlusion_s"] = time.perf_counter() - t0
            _log.debug("After occlusion clip: %s non-overlapping shapes", len(clipped_shapes))

            if cache_key is not None:
                _VECTOR_PARSE_CLIP_CACHE[cache_key] = {
                    "shape_data": shape_data,
                    "clipped_shapes": clipped_shapes,
                    "silhouette": silhouette,
                    "image_vectorizer_bounds": image_vectorizer_bounds,
                    "scale_factor": scale_factor,
                    "bbox": bbox,
                }
                while len(_VECTOR_PARSE_CLIP_CACHE) > _VECTOR_PARSE_CLIP_CACHE_MAX:
                    _VECTOR_PARSE_CLIP_CACHE.pop(next(iter(_VECTOR_PARSE_CLIP_CACHE)))

        # === Stage 3: Resolve color system config ===
        # --- Diagnostic: geometry fingerprint for 5-vs-7 layer comparison ---
        _unique_colors_in_shapes = set()
        _total_geom_area = 0.0
        for _item in clipped_shapes:
            _c = _item.get("color")
            if _c:
                try:
                    _unique_colors_in_shapes.add((int(_c[0]), int(_c[1]), int(_c[2])))
                except (TypeError, IndexError, ValueError):
                    pass
            _g = _item.get("geometry")
            if _g is not None and not _g.is_empty:
                _total_geom_area += float(_g.area)
        _log.info(
            "analyze_svg geometry fingerprint: shapes=%d unique_colors=%d total_area=%.2f "
            "gradient_bands=%s layer_count=%s cache_hit=%s",
            len(clipped_shapes),
            len(_unique_colors_in_shapes),
            _total_geom_area,
            getattr(self, "gradient_color_bands", None),
            getattr(self.img_processor, "layer_count", "?"),
            cached_entry is not None,
            extra={
                "event": "vector_diag_geometry_fingerprint",
                "shape_count": len(clipped_shapes),
                "unique_color_count": len(_unique_colors_in_shapes),
                "total_area": round(_total_geom_area, 2),
                "gradient_color_bands": getattr(self, "gradient_color_bands", None),
                "layer_count": getattr(self.img_processor, "layer_count", None),
                "cache_hit": cached_entry is not None,
            },
        )
        # In material-archive mode the matcher carries a pre-built
        # ``color_conf`` derived from the materials list. The LUT path
        # (``LuminaImageProcessor``) does not expose this attribute, so
        # we fall back to the historical ``ColorSystem.get`` lookup
        # there. ``num_layers`` from material mode is taken from the
        # matcher so the recipe length matches the user's configured
        # layer_count instead of the printer-config default.
        # 耗材档案 matcher 自带 color_conf；LUT 路径维持原行为。
        material_color_conf = getattr(self.img_processor, "color_conf", None)
        if material_color_conf is not None:
            color_conf = dict(material_color_conf)
            preview_colors = dict(getattr(self.img_processor, "preview_colors", color_conf.get("preview") or {}))
            slot_names = list(getattr(self.img_processor, "slot_names", color_conf.get("slots") or []))
            num_channels = len(slot_names)
            num_layers = int(
                getattr(self.img_processor, "layer_count", PrinterConfig.COLOR_LAYERS)
            )
        else:
            is_six_color = len(self.img_processor.lut_rgb) == 1296
            if is_six_color:
                _log.debug("Auto-detected 6-Color LUT. Forcing 6-Color mode.")
                color_conf = ColorSystem.SIX_COLOR
                self.color_mode = "6-Color"
            else:
                color_conf = ColorSystem.get(self.color_mode)

            slot_names = color_conf["slots"]
            preview_colors = dict(color_conf["preview"])
            num_channels = len(slot_names)
            num_layers = color_conf.get("layer_count", PrinterConfig.COLOR_LAYERS)

        # For any LUT that carries explicit palette metadata (Merged JSON,
        # reverse-inferred native_bundle .json / .msgpack, etc.), override
        # slot_names and preview_colors from the LUT palette so the vector
        # engine uses the LUT's own color system instead of the stale UI
        # ``color_mode`` preset. Mirrors the raster pipeline logic in S01.
        #
        # 当 LUT 自带调色板元数据（Merged JSON、反推 LUT 的 .json/.msgpack 等）
        # 时，用调色板真实条目覆盖 slot_names / preview_colors，避免继承上一次
        # UI 颜色模式（例如 4-Color CMYW）的预设槽位导致串色；同时沿用
        # ``build_palette_preview_colors`` 的规范颜色名兜底，保证 hex_color 缺省
        # 的 ColorDB 条目也能拿到正确 RGBA。
        lut_path = self.img_processor.lut_path
        if lut_path.endswith((".json", ".msgpack")):
            try:
                from utils.lut_manager import LUTManager
                from core.pipeline.preview_color_utils import build_palette_preview_colors

                _, _, lut_meta = LUTManager.load_lut_with_metadata(lut_path)
                if lut_meta.palette:
                    palette_slot_names, palette_preview_colors = build_palette_preview_colors(
                        lut_meta.palette, color_conf
                    )
                    slot_names = palette_slot_names
                    preview_colors = dict(palette_preview_colors)
                    num_channels = len(slot_names)
                    color_conf = dict(color_conf)
                    color_conf["slots"] = slot_names
                    color_conf["preview"] = preview_colors
                    _log.debug("LUT palette override: %s", slot_names)
            except Exception as e:
                _log.warning(
                    "Failed to extract vector LUT palette",
                    extra={
                        "event": "vector_lut_palette_extract_failed",
                        "error_type": type(e).__name__,
                        "error_message": str(e),
                        "path": str(lut_path),
                    },
                )

        # === Stage 4: Match fill colors to LUT recipes ===
        replacement_manager = None
        if color_replacements:
            try:
                from core.color_replacement import ColorReplacementManager

                replacement_manager = ColorReplacementManager.from_dict(color_replacements)
            except VECTOR_HANDLED_ERRORS as e:
                _log.warning(
                    "Failed to load vector color replacements",
                    extra={
                        "event": "vector_color_replacements_load_failed",
                        "error_type": type(e).__name__,
                        "error_message": str(e),
                        "replacement_count": len(color_replacements or []),
                    },
                )

        # Material-archive matcher needs to pre-solve every unique fill
        # colour before ``_match_colors`` runs its KDTree query, so the
        # KDTree is populated and ``lut_rgb`` / ``ref_stacks`` carry the
        # solver-derived rows. The hook is opt-in (``solve_for_fills``
        # is only present on :class:`MaterialVectorMatcher`); the LUT
        # path skips it transparently.
        # 耗材档案 matcher 在 _match_colors 之前批量求解填充色，保证
        # KDTree / lut_rgb / ref_stacks 已就绪；LUT 模式没有该方法，
        # 透明跳过。
        solve_for_fills = getattr(self.img_processor, "solve_for_fills", None)
        if solve_for_fills is not None and clipped_shapes:
            unique_fills_set: set = set()
            for item in clipped_shapes:
                color = item.get("color")
                if color is None:
                    continue
                try:
                    unique_fills_set.add(
                        (int(color[0]), int(color[1]), int(color[2]))
                    )
                except (TypeError, IndexError, ValueError):
                    continue
            if unique_fills_set:
                solve_for_fills(sorted(unique_fills_set))
                # NOTE: small-shape snap is disabled for material-archive mode.
                # The delta_e heuristic incorrectly triggers when the material
                # set cannot physically reproduce dark colours, causing
                # unrelated small shapes to be snapped to the dominant anchor
                # colour (e.g. black → skin tone). See PR #177 regression.
                # 耗材档案模式禁用小 shape 吸附：材料集缺少深色时 delta_e
                # 判断会误触发，把深色小碎片全部吸附到大面积锚点色。

        t0 = time.perf_counter()
        matched_shapes = self._match_colors(clipped_shapes, replacement_manager, num_channels, num_layers=num_layers)
        min_hole_area_mm2 = float(getattr(VectorConfig, "MIN_COLOR_HOLE_AREA_MM2", 1.0))
        for idx, item in enumerate(clipped_shapes):
            filtered_geometry = VectorProcessor._filter_backing_holes(
                item["geometry"],
                min_hole_area_mm2=min_hole_area_mm2,
            )
            item["geometry"] = filtered_geometry
            if idx < len(matched_shapes):
                matched_shapes[idx]["geometry"] = filtered_geometry
        stage_timings["color_match_s"] = time.perf_counter() - t0
        _log.debug("Matched %s shapes to LUT recipes", len(matched_shapes))
        legacy_stroke_only_shapes = sum(
            1 for item in shape_data if item.get("source_kind") == "stroke_only"
        )
        fill_eq_stroke_double_buffer = sum(
            1 for item in shape_data if item.get("same_color_stroke_double_buffer")
        )
        stroke_policy_message = (
            "Stroke policy: "
            f"expand={expand_stroke_to_fill} "
            f"legacy_stroke_only_shapes={legacy_stroke_only_shapes} "
            f"fill_eq_stroke_double_buffer={fill_eq_stroke_double_buffer}"
        )
        stroke_policy_extra = {
            "event": "vector_stroke_policy",
            "expand": expand_stroke_to_fill,
            "legacy_stroke_only_shapes": legacy_stroke_only_shapes,
            "fill_eq_stroke_double_buffer": fill_eq_stroke_double_buffer,
        }
        _log.info(stroke_policy_message, extra=stroke_policy_extra)

        return VectorAnalysis(
            shape_data=shape_data,
            clipped_shapes=clipped_shapes,
            matched_shapes=matched_shapes,
            silhouette=silhouette,
            scale_factor=scale_factor,
            bbox=bbox,
            color_conf=color_conf,
            slot_names=slot_names,
            num_channels=num_channels,
            num_layers=num_layers,
            preview_colors=preview_colors,
            stage_timings=stage_timings,
            image_vectorizer_bounds=image_vectorizer_bounds,
        )

    def build_mesh(
        self,
        analysis: VectorAnalysis,
        thickness_mm: float,
        structure_mode: str = "Single-sided",
        progress_fn=None,
        backing_color_id: int = 0,
    ) -> trimesh.Scene:
        """Extrude analyzed vector shapes into a trimesh Scene.
        将分析后的矢量形状挤出为 trimesh Scene。

        Args:
            analysis:       Result from ``analyze_svg``.
            thickness_mm:   Backing (spacer) thickness in mm.
            structure_mode: "Single-sided" or "Double-sided".
            progress_fn:    Optional progress callback.
            backing_color_id: Material slot index to assign to the ``Board``
                backing geometry. Defaults to ``0`` to preserve historical
                behaviour; callers driving material-archive or separate-
                backing flows pass the user-selected backing slot so the
                preview/export actually reflects the chosen material.
                （底板几何体使用的材质槽索引，默认 0 以保持历史行为；
                耗材档案或分离底板流程会传入用户选择的底板槽位，
                预览/导出才能反映实际选中的耗材颜色。）

        Returns:
            A ``trimesh.Scene`` with one geometry per material slot.
        """
        _log.debug("Building mesh: structure_mode=%s", structure_mode)
        stage_timings = dict(analysis.stage_timings)
        t_total_start = time.perf_counter()

        matched_shapes = analysis.matched_shapes
        clipped_shapes = analysis.clipped_shapes
        silhouette = analysis.silhouette
        scale_factor = analysis.scale_factor
        bbox = analysis.bbox
        slot_names = analysis.slot_names
        num_channels = analysis.num_channels
        num_layers = analysis.num_layers
        preview_colors = analysis.preview_colors
        enable_fridge_magnet = bool(getattr(self, "enable_fridge_magnet", False))
        fridge_magnets = list(getattr(self, "fridge_magnets", []) or [])
        enable_coating = bool(getattr(self, "enable_coating", False))
        coating_height_mm = getattr(self, "coating_height_mm", 0.08)
        structure_mode_value = str(getattr(structure_mode, "value", structure_mode))

        # === Stage 5: Run-length extrude per channel ===
        layer_h = PrinterConfig.LAYER_HEIGHT
        extrude_cache = {}
        is_5color = "5-Color Extended" in self.color_mode
        is_single_sided = "单面" in structure_mode_value or "Single" in structure_mode_value
        mirror_transform = None
        if is_single_sided and not is_5color:
            model_width_mm = bbox[2] * scale_factor
            mirror_transform = np.array(
                [[-1.0, 0.0, 0.0, model_width_mm], [0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 0.0, 1.0]]
            )
        backing_layer_count = max(1, int(round(thickness_mm / layer_h)))
        backing_height = backing_layer_count * layer_h

        t0 = time.perf_counter()
        if is_5color:
            meshes_by_slot = self._run_length_extrude(
                matched_shapes,
                num_layers,
                layer_h,
                num_channels,
                slot_names,
                scale_factor,
                extrude_cache=extrude_cache,
                face_up=True,
                optical_z_base=backing_height,
            )
            _log.debug(
                "5-Color face-up: %s optical layers above %.2fmm backing",
                num_layers,
                backing_height,
            )
        else:
            meshes_by_slot = self._run_length_extrude(
                matched_shapes,
                num_layers,
                layer_h,
                num_channels,
                slot_names,
                scale_factor,
                extrude_cache=extrude_cache,
            )
        stage_timings["extrude_bottom_s"] = time.perf_counter() - t0

        # === Stage 6: Backing layer from silhouette ===
        t0 = time.perf_counter()
        image_vectorizer_bounds = getattr(analysis, "image_vectorizer_bounds", None)
        if image_vectorizer_bounds is not None and not image_vectorizer_bounds.is_empty:
            silhouette = image_vectorizer_bounds
        elif silhouette is None and clipped_shapes:
            all_geoms = [
                s["geometry"] for s in clipped_shapes if s["geometry"] is not None and not s["geometry"].is_empty
            ]
            silhouette = unary_union(all_geoms) if all_geoms else None

        if is_5color:
            backing_z_start = 0
        else:
            backing_z_start = num_layers * layer_h

        backing_sil = None
        if thickness_mm > 0 and silhouette is not None and not silhouette.is_empty:
            _log.debug("Generating backing: %s layers (%smm)", backing_layer_count, thickness_mm)
            backing_sil = self._normalize_contours(silhouette, close_delta_mm=0.4)
            if backing_sil is None or backing_sil.is_empty:
                backing_sil = silhouette
            backing_sil = self._filter_backing_holes(backing_sil, min_hole_area_mm2=0.3)
            try:
                backing_sil = backing_sil.buffer(0.15, join_style="mitre", mitre_limit=2.0)
            except VECTOR_HANDLED_ERRORS:
                pass
            backing_height = backing_layer_count * layer_h
            gap_offset = BASE_COLOR_GAP_MM if not is_5color else 0.0
            outer_side = "low" if is_5color else "high"
            cavity_specs = []
            if enable_fridge_magnet:
                cavity_specs = self._build_vector_fridge_cavity_specs(
                    backing_sil=backing_sil,
                    fridge_magnets=fridge_magnets or [],
                    bbox=bbox,
                    scale_factor=scale_factor,
                    backing_height=backing_height,
                )
            backing_slabs = self._build_backing_cavity_slabs(
                backing_sil=backing_sil,
                backing_z_start=backing_z_start,
                backing_height=backing_height,
                cavity_specs=cavity_specs,
                outer_side=outer_side,
            )
            backing_meshes = []
            for slab in backing_slabs:
                backing_meshes.extend(
                    self._extrude_geometry(
                        slab["geometry"],
                        height=slab["height"],
                        z_offset=slab["z_offset"] + gap_offset,
                        scale=scale_factor,
                        extrude_cache=extrude_cache,
                    )
                )
            if backing_meshes:
                backing_name = "Board"
                # Clamp the backing material slot to a valid index; fall back
                # to 0 when slot_names is empty (legacy defensive path).
                # 钳制底板材质槽到合法索引；slot_names 为空时退回 0。
                slot_count = len(slot_names) if slot_names else 0
                resolved_backing_mat_id = 0
                if slot_count > 0:
                    try:
                        candidate = int(backing_color_id)
                    except (TypeError, ValueError):
                        candidate = 0
                    if 0 <= candidate < slot_count:
                        resolved_backing_mat_id = candidate
                if backing_name not in meshes_by_slot:
                    meshes_by_slot[backing_name] = {
                        "meshes": [],
                        "mat_id": resolved_backing_mat_id,
                    }
                meshes_by_slot[backing_name]["meshes"].extend(backing_meshes)
        stage_timings["backing_s"] = time.perf_counter() - t0

        t0 = time.perf_counter()
        if enable_coating and silhouette is not None and not silhouette.is_empty:
            coating_sil = backing_sil
            if coating_sil is None or coating_sil.is_empty:
                coating_sil = self._normalize_contours(silhouette, close_delta_mm=0.4)
                if coating_sil is None or coating_sil.is_empty:
                    coating_sil = silhouette
                coating_sil = self._filter_backing_holes(coating_sil, min_hole_area_mm2=0.3)
                try:
                    coating_sil = coating_sil.buffer(0.15, join_style="mitre", mitre_limit=2.0)
                except VECTOR_HANDLED_ERRORS:
                    pass
            try:
                requested_coating_height = float(coating_height_mm)
            except (TypeError, ValueError):
                requested_coating_height = layer_h
            if not np.isfinite(requested_coating_height) or requested_coating_height <= 0:
                requested_coating_height = layer_h
            coating_layers = max(1, int(round(requested_coating_height / layer_h)))
            coating_height = coating_layers * layer_h
            coating_meshes = self._extrude_geometry(
                coating_sil,
                height=coating_height,
                z_offset=-coating_height,
                scale=scale_factor,
                extrude_cache=extrude_cache,
            )
            if coating_meshes:
                coating_name = "Coating"
                meshes_by_slot[coating_name] = {
                    "meshes": coating_meshes,
                    "mat_id": max(num_channels, len(slot_names)),
                }
                preview_colors[coating_name] = [200, 200, 200, 80]
        stage_timings["coating_s"] = time.perf_counter() - t0

        # === Stage 7: Double-sided structure ===
        t0 = time.perf_counter()
        is_double_sided = "双面" in structure_mode_value or "Double" in structure_mode_value
        if is_double_sided:
            _log.debug("Adding mirrored color layers (double-sided mode)...")
            top_z_start = backing_z_start + backing_layer_count * layer_h
            self._add_double_sided_layers(
                matched_shapes,
                num_layers,
                layer_h,
                num_channels,
                slot_names,
                scale_factor,
                top_z_start,
                meshes_by_slot,
                extrude_cache=extrude_cache,
            )
        stage_timings["extrude_top_s"] = time.perf_counter() - t0

        # === Stage 8: Assemble scene (sorted by material ID) ===
        t0 = time.perf_counter()
        scene = trimesh.Scene()
        svg_height_mm = bbox[3] * scale_factor

        sorted_items = sorted(meshes_by_slot.items(), key=lambda x: x[1]["mat_id"])

        for name, data in sorted_items:
            mesh_list = data["meshes"]
            mat_id = data["mat_id"]
            if not mesh_list:
                continue

            _log.debug("Merging %s parts for %s...", len(mesh_list), name)
            combined = trimesh.util.concatenate(mesh_list) if len(mesh_list) > 1 else mesh_list[0]
            # Weld coincident border vertices produced by independent per-shape
            # ``_extrude_geometry`` calls so Three.js / exporters do not render
            # visible seams along shape boundaries. 对相邻 shape 独立 extrude
            # 后重合的边界顶点做焊接，避免下游 mesh 渲染/导出在形状边界出现缝隙。
            try:
                combined.merge_vertices()
            except Exception:
                pass
            self._fix_coordinates(combined, svg_height_mm)
            if mirror_transform is not None:
                combined.apply_transform(mirror_transform)

            color_val = preview_colors.get(mat_id, preview_colors.get(name, [255, 255, 255, 255]))
            combined.visual.face_colors = color_val
            combined.metadata["name"] = name
            scene.add_geometry(combined, geom_name=name)

        stage_timings["assemble_s"] = time.perf_counter() - t0
        stage_timings["total_s"] = time.perf_counter() - t_total_start
        stage_timings["extrude_cache_entries"] = len(extrude_cache)
        self.last_stage_timings = stage_timings

        _log.debug(
            "Stage timings (s): parse=%.3f, clip=%.3f, match=%.3f, "
            "extrude_bottom=%.3f, backing=%.3f, extrude_top=%.3f, assemble=%.3f, total=%.3f",
            stage_timings.get("parse_s", 0),
            stage_timings.get("occlusion_s", 0),
            stage_timings.get("color_match_s", 0),
            stage_timings["extrude_bottom_s"],
            stage_timings["backing_s"],
            stage_timings["extrude_top_s"],
            stage_timings["assemble_s"],
            stage_timings["total_s"],
        )
        _log.debug("Extrude cache entries: %s", stage_timings["extrude_cache_entries"])
        _log.debug("Scene complete: %s objects", len(scene.geometry))
        return scene

    def svg_to_mesh(
        self,
        svg_path: str,
        target_width_mm: float,
        thickness_mm: float,
        structure_mode: str = "Single-sided",
        color_replacements: dict = None,
        progress_fn=None,
    ) -> trimesh.Scene:
        """Convert an SVG file to a trimesh Scene ready for 3MF export.
        将 SVG 文件转换为可用于 3MF 导出的 trimesh Scene。

        Convenience wrapper combining ``analyze_svg`` and ``build_mesh``.

        Args:
            svg_path:         Path to SVG file.
            target_width_mm:  Physical width in mm for the output model.
            thickness_mm:     Backing (spacer) thickness in mm.
            structure_mode:   "Single-sided" or "Double-sided".
            color_replacements: Optional ``{hex: hex}`` replacement map.
            progress_fn:      Optional progress callback.

        Returns:
            A ``trimesh.Scene`` with one geometry per material slot, sorted
            by material ID.  Geometry names match slot names from the active
            ``ColorSystem`` configuration.
        """
        analysis = self.analyze_svg(svg_path, target_width_mm, color_replacements, progress_fn)
        return self.build_mesh(
            analysis,
            thickness_mm,
            structure_mode,
            progress_fn=progress_fn,
        )

    # ── 2D preview from analyzed geometry ─────────────────────────────────

    @staticmethod
    def render_preview(
        analysis: "VectorAnalysis",
        pixels_per_mm: float = 10.0,
        max_width_px: int = 1600,
    ) -> np.ndarray:
        """Render a 2D RGBA preview from analyzed vector geometry.
        从已分析的矢量几何渲染 2D RGBA 预览，与 3MF 使用同一组几何数据。

        Args:
            analysis:      Result from ``analyze_svg``.
            pixels_per_mm: Rasterization density (pixels per mm).
            max_width_px:  Maximum output width in pixels.

        Returns:
            (H, W, 4) uint8 RGBA numpy array with white background.
        """
        real_w = analysis.bbox[2]
        real_h = analysis.bbox[3]
        sf = analysis.scale_factor

        w_mm = real_w * sf
        h_mm = real_h * sf
        ppm = pixels_per_mm

        w_px = max(1, int(round(w_mm * ppm)))
        h_px = max(1, int(round(h_mm * ppm)))

        if w_px > max_width_px:
            ratio = max_width_px / w_px
            w_px = max_width_px
            h_px = max(1, int(round(h_px * ratio)))
            ppm = w_px / w_mm

        canvas = np.full((h_px, w_px, 4), 255, dtype=np.uint8)

        coord_scale = sf * ppm

        slot_names = analysis.slot_names
        preview_colors = analysis.preview_colors

        for shape in analysis.matched_shapes:
            geom = shape["geometry"]
            recipe = shape["recipe"]
            if geom is None or geom.is_empty:
                continue

            slot_idx = recipe[0] if recipe else 0
            rgba = preview_colors.get(
                slot_idx,
                preview_colors.get(slot_names[slot_idx] if slot_idx < len(slot_names) else 0, [128, 128, 128, 255]),
            )
            rgb_color = (int(rgba[0]), int(rgba[1]), int(rgba[2]))

            polys = []
            if geom.geom_type == "Polygon":
                polys = [geom]
            elif geom.geom_type == "MultiPolygon":
                polys = list(geom.geoms)
            else:
                continue

            for poly in polys:
                if poly.is_empty:
                    continue
                ext_coords = np.array(poly.exterior.coords)
                pts = np.column_stack(
                    [
                        ext_coords[:, 0] * coord_scale,
                        ext_coords[:, 1] * coord_scale,
                    ]
                ).astype(np.int32)
                cv2.fillPoly(canvas, [pts], (*rgb_color, int(rgba[3])))

                for interior in poly.interiors:
                    hole_coords = np.array(interior.coords)
                    hole_pts = np.column_stack(
                        [
                            hole_coords[:, 0] * coord_scale,
                            hole_coords[:, 1] * coord_scale,
                        ]
                    ).astype(np.int32)
                    cv2.fillPoly(canvas, [hole_pts], (255, 255, 255, 255))

        return canvas

    @staticmethod
    def build_preview_cache(
        analysis: "VectorAnalysis",
        pixels_per_mm: float = 10.0,
        max_width_px: int = 1600,
        supersample_preview: int = 2,
    ) -> dict:
        """Rasterise vector analysis into preview-cache arrays.
        将矢量分析结果光栅化为预览缓存数组，供预览/调色板/GLB 复用。

        Unlike ``render_preview()``, this method preserves separate
        ``matched_rgb`` / ``quantized_image`` / ``mask_solid`` data so the
        frontend preview cache stays aligned with the native vector pipeline.

        ``matched_rgb`` / ``mask_solid`` / ``material_matrix`` /
        ``quantized_image`` are always rasterised at ``pixels_per_mm`` with
        hard-edged ``cv2.fillPoly`` because several downstream APIs
        (color-highlight bbox, region id map, color recipe logger) rely on
        exact pixel-indexed membership.

        ``preview_rgba`` — the display-facing RGBA image read by the frontend
        preview canvas — is rasterised at ``pixels_per_mm * supersample_preview``
        and box-filter downsampled with ``cv2.INTER_AREA`` so shape boundaries
        carry an anti-aliased alpha gradient. Without this the hard-edged
        pixels composited on the page's white background produced the
        stair-stepped jaggies users saw at stroke-heavy borders. Passing
        ``supersample_preview=1`` reverts to the legacy hard-edged behaviour.

        ``preview_rgba`` 使用 supersample + INTER_AREA 降采样做边缘抗锯齿；其
        他掩膜数组保持硬边，保证下游像素索引 API 语义不变。
        """
        real_w = analysis.bbox[2]
        real_h = analysis.bbox[3]
        sf = analysis.scale_factor

        w_mm = real_w * sf
        h_mm = real_h * sf
        ppm = pixels_per_mm

        w_px = max(1, int(round(w_mm * ppm)))
        h_px = max(1, int(round(h_mm * ppm)))

        if w_px > max_width_px:
            ratio = max_width_px / w_px
            w_px = max_width_px
            h_px = max(1, int(round(h_px * ratio)))
            ppm = w_px / w_mm

        coord_scale = sf * ppm
        # Keep transparent SVG background visually white in raw matched-RGB
        # consumers. ``mask_solid`` / ``material_matrix`` still mark those
        # pixels as air, so this does not turn the exterior canvas into print
        # geometry. It only prevents unpainted SVG negative space from being
        # displayed as default black when a caller previews ``matched_rgb``
        # without compositing alpha.
        matched_rgb = np.full((h_px, w_px, 3), 255, dtype=np.uint8)
        quantized_image = np.full((h_px, w_px, 3), 255, dtype=np.uint8)
        mask_solid = np.zeros((h_px, w_px), dtype=bool)
        material_matrix = np.full((h_px, w_px, analysis.num_layers), -1, dtype=np.int16)

        ss = max(1, int(supersample_preview))
        ss_h = h_px * ss
        ss_w = w_px * ss
        ss_coord_scale = coord_scale * ss
        preview_rgba_ss = np.zeros((ss_h, ss_w, 4), dtype=np.uint8) if ss > 1 else None

        def _iter_polygons(geom):
            if geom is None or geom.is_empty:
                return []
            if geom.geom_type == "Polygon":
                return [geom]
            if geom.geom_type == "MultiPolygon":
                return list(geom.geoms)
            return []

        def _coords_to_pts(coords, scale):
            pts = np.column_stack(
                [
                    coords[:, 0] * scale,
                    coords[:, 1] * scale,
                ]
            ).astype(np.int32)
            if len(pts) < 3:
                return None
            return pts

        def _polygon_mask_plain(poly, height, width, scale):
            """Original int-truncated single-resolution fill.
            原始的整数截断、单分辨率填充。

            Retained for the ``preview_rgba`` path, which already rasterises
            on a supersampled grid and then box-filter downsamples, so its
            edges are anti-aliased and the 1px seam averages out visually.
            Re-supersampling there would multiply cost for no membership-mask
            gain (``preview_rgba`` is display-only, not a membership mask).

            保留给 ``preview_rgba`` 路径：它本身已在超采样网格上栅格化并做
            INTER_AREA 降采样，边缘已抗锯齿、缝会被视觉平均掉，无需再次
            超采样（``preview_rgba`` 仅用于显示，不作为归属掩膜）。
            """
            region = np.zeros((height, width), dtype=np.uint8)
            ext_pts = _coords_to_pts(np.array(poly.exterior.coords), scale)
            if ext_pts is None:
                return None
            cv2.fillPoly(region, [ext_pts], 255)
            for interior in poly.interiors:
                hole_pts = _coords_to_pts(np.array(interior.coords), scale)
                if hole_pts is not None:
                    cv2.fillPoly(region, [hole_pts], 0)
            return region.astype(bool)

        def _polygon_mask(poly, height, width, scale):
            """Rasterise one polygon's footprint into a boolean membership mask.
            将单个多边形栅格化为布尔归属掩膜。

            Sub-pixel-accurate: the polygon (exterior minus interior holes)
            is filled on a supersampled sub-grid restricted to the polygon's
            pixel bounding box, then downsampled by sampling each output
            pixel's *center* sub-cell. This decides ``mask_solid`` membership
            by "is the pixel center inside the geometry", which fixes the 1px
            seams that plain ``cv2.fillPoly`` left when float vertex
            coordinates were truncated to ``int32`` at the base resolution
            (a geometry-covered pixel whose center sat just inside the shape
            could be dropped, surfacing as a "background area" hole in the
            colour-adjust click flow and as air in the generated 3MF).

            Boundary safety: the supersampled fill also subtracts interior
            holes, and only the polygon's own bbox is touched, so the
            transparent SVG background outside the silhouette can never be
            over-filled. The sub-grid is confined to the bbox so cost stays
            proportional to ``shape_area * ss^2`` instead of
            ``full_grid * ss^2``.

            亚像素精度栅格化：在多边形像素 bbox 内的超采样子网格上填充
            （外环减去内洞），再按每个输出像素的"中心"子格降采样，使
            ``mask_solid`` 的判据变为"像素中心是否落在几何内"。这修复了
            原先把浮点顶点直接 ``int32`` 截断导致的 1px 缝（几何覆盖、
            但被漏填，表现为颜色调整里点击破洞被判背景、3MF 里成空气）。
            边界安全：填充同样扣除内洞，且只触碰多边形自身 bbox，绝不会
            把轮廓外的透明背景误填实。
            """
            ext_coords = np.array(poly.exterior.coords)
            if len(ext_coords) < 3:
                return None

            ss = _MASK_SUPERSAMPLE
            if ss <= 1:
                return _polygon_mask_plain(poly, height, width, scale)

            # Pixel-space bbox of the polygon, clamped to the grid. The +1
            # margin guards against boundary rounding at the bbox edge.
            # 多边形的像素 bbox（夹到网格内）；+1 余量防止 bbox 边缘取整丢边。
            xs = ext_coords[:, 0] * scale
            ys = ext_coords[:, 1] * scale
            x0 = max(0, int(np.floor(xs.min())) - 1)
            y0 = max(0, int(np.floor(ys.min())) - 1)
            x1 = min(width, int(np.ceil(xs.max())) + 1)
            y1 = min(height, int(np.ceil(ys.max())) + 1)
            if x1 <= x0 or y1 <= y0:
                return None

            bw = x1 - x0
            bh = y1 - y0
            sub = np.zeros((bh * ss, bw * ss), dtype=np.uint8)

            def _sub_pts(coords):
                # Map into the supersampled, bbox-local sub-grid.
                # 映射到 bbox 局部的超采样子网格坐标。
                p = np.column_stack(
                    [
                        (coords[:, 0] * scale - x0) * ss,
                        (coords[:, 1] * scale - y0) * ss,
                    ]
                )
                if len(p) < 3:
                    return None
                return np.round(p).astype(np.int32)

            ext_sub = _sub_pts(ext_coords)
            if ext_sub is None:
                return None
            cv2.fillPoly(sub, [ext_sub], 255)
            for interior in poly.interiors:
                hole_sub = _sub_pts(np.array(interior.coords))
                if hole_sub is not None:
                    cv2.fillPoly(sub, [hole_sub], 0)

            # Center sub-cell of each output pixel decides membership.
            # 取每个输出像素的中心子格判定归属。
            off = ss // 2
            local = sub[off::ss, off::ss][:bh, :bw].astype(bool)
            if not np.any(local):
                return None

            region = np.zeros((height, width), dtype=bool)
            region[y0:y1, x0:x1] = local
            return region

        backing_geom = getattr(analysis, "image_vectorizer_bounds", None)
        if backing_geom is None or getattr(backing_geom, "is_empty", True):
            backing_geom = analysis.silhouette
        if backing_geom is None or getattr(backing_geom, "is_empty", True):
            clipped_geoms = [
                item.get("geometry")
                for item in getattr(analysis, "clipped_shapes", []) or []
                if item.get("geometry") is not None
                and not item.get("geometry").is_empty
            ]
            if clipped_geoms:
                backing_geom = unary_union(clipped_geoms)

        backing_mask = np.zeros((h_px, w_px), dtype=bool)
        if backing_geom is not None and not getattr(backing_geom, "is_empty", True):
            try:
                normalized_backing = VectorProcessor._normalize_contours(
                    backing_geom,
                    close_delta_mm=0.4,
                )
                if normalized_backing is not None and not normalized_backing.is_empty:
                    backing_geom = normalized_backing
                filtered_backing = VectorProcessor._filter_backing_holes(
                    backing_geom,
                    min_hole_area_mm2=0.3,
                )
                if filtered_backing is not None and not filtered_backing.is_empty:
                    backing_geom = filtered_backing
                backing_geom = backing_geom.buffer(
                    0.15,
                    join_style="mitre",
                    mitre_limit=2.0,
                )
            except VECTOR_HANDLED_ERRORS:
                pass
            for poly in _iter_polygons(backing_geom):
                region_mask = _polygon_mask(poly, h_px, w_px, coord_scale)
                if region_mask is not None and np.any(region_mask):
                    backing_mask |= region_mask

        for shape in analysis.matched_shapes:
            geom = shape.get("geometry")
            if geom is None or geom.is_empty:
                continue

            matched_color = np.array(
                shape.get("matched_rgb") or shape.get("color") or (0, 0, 0),
                dtype=np.uint8,
            )
            source_color = np.array(
                shape.get("color") or shape.get("matched_rgb") or (0, 0, 0),
                dtype=np.uint8,
            )

            recipe = shape.get("recipe") or []
            recipe_full = np.full((analysis.num_layers,), -1, dtype=np.int16)
            for idx, value in enumerate(recipe[: analysis.num_layers]):
                recipe_full[idx] = int(value)

            for poly in _iter_polygons(geom):
                if poly.is_empty:
                    continue
                region_mask = _polygon_mask(poly, h_px, w_px, coord_scale)
                if region_mask is None or not np.any(region_mask):
                    continue

                matched_rgb[region_mask] = matched_color
                quantized_image[region_mask] = source_color
                mask_solid[region_mask] = True
                material_matrix[region_mask] = recipe_full

                if preview_rgba_ss is not None:
                    # preview_rgba is display-only and already supersampled +
                    # INTER_AREA downsampled, so use the plain fill here and
                    # avoid nesting another supersample pass.
                    # preview_rgba 仅用于显示且已超采样 + INTER_AREA 降采样，
                    # 这里用普通填充，避免再嵌套一层超采样。
                    ss_mask = _polygon_mask_plain(poly, ss_h, ss_w, ss_coord_scale)
                    if ss_mask is not None and np.any(ss_mask):
                        preview_rgba_ss[ss_mask, :3] = matched_color
                        preview_rgba_ss[ss_mask, 3] = 255

        if preview_rgba_ss is not None:
            preview_rgba = cv2.resize(
                preview_rgba_ss, (w_px, h_px), interpolation=cv2.INTER_AREA,
            )
            # The supersampled alpha is filled per shape, so the thin seams
            # between adjacent shapes (and the borders of occlusion-carved
            # interior holes) land on partially-covered output pixels and
            # downsample to alpha ~128 — a semi-transparent gap that shows the
            # page background through solid artwork (the "透明破洞" users saw in
            # the hair). ``mask_solid`` is the seam-free sub-pixel membership
            # mask, so force full opacity (and the seam-free colour) wherever a
            # pixel is solid. Exterior anti-aliasing is preserved because
            # ``mask_solid`` is False in the outer AA band, leaving its blended
            # alpha untouched. Boundary safety: pixels outside the silhouette
            # keep ``mask_solid == False`` and are never forced opaque.
            # 超采样 alpha 逐 shape 填充，相邻 shape 之间的细缝与遮挡洞边界落在
            # 部分覆盖的输出像素上，降采样后 alpha≈128，合成时透出页面底色，
            # 即用户看到的头发"透明破洞"。``mask_solid`` 是无缝的亚像素归属掩膜，
            # 因此在其为实体处强制不透明并取无缝颜色；轮廓外 ``mask_solid`` 为
            # False，外缘抗锯齿保留、背景不会被误填。
            seam = mask_solid & (preview_rgba[:, :, 3] < 255)
            if np.any(seam):
                preview_rgba[seam, :3] = matched_rgb[seam]
                preview_rgba[seam, 3] = 255
        else:
            preview_rgba = np.zeros((h_px, w_px, 4), dtype=np.uint8)
            preview_rgba[mask_solid, :3] = matched_rgb[mask_solid]
            preview_rgba[mask_solid, 3] = 255

        return {
            "target_w": w_px,
            "target_h": h_px,
            "target_width_mm": w_mm,
            "pixel_scale": (w_mm / w_px) if w_px > 0 else 0.0,
            "matched_rgb": matched_rgb,
            "quantized_image": quantized_image,
            "mask_solid": mask_solid,
            "backing_mask": backing_mask if np.any(backing_mask) else mask_solid.copy(),
            "material_matrix": material_matrix,
            "preview_rgba": preview_rgba,
        }

    # ── Stage 2: Occlusion clipping (Chroma-style) ───────────────────────

    @staticmethod
    def _clip_occlusion(shape_data, return_silhouette=False):
        """Clip shapes so no two overlap in XY.

        Iterates in reverse draw order (topmost first).  Each shape is
        subtracted from the accumulated union so that lower shapes only
        retain geometry not already covered by higher shapes.

        This mirrors ``ChromaPrint3D::detail::ClipOcclusion``.
        """
        n = len(shape_data)
        if n == 0:
            return ([], None) if return_silhouette else []

        valid = []
        for i, item in enumerate(shape_data):
            geom = item["poly"]
            if geom is None or geom.is_empty:
                continue
            valid.append((i, geom))

        if not valid:
            return ([], None) if return_silhouette else []

        orders = [v[0] for v in valid]
        geoms = [v[1] for v in valid]
        tree = STRtree(geoms)
        geom_id_to_idx = {id(g): idx for idx, g in enumerate(geoms)}
        result = []

        for i in range(n - 1, -1, -1):
            item = shape_data[i]
            geom = item["poly"]
            if geom is None or geom.is_empty:
                continue

            occluders = []
            try:
                candidate_refs = tree.query(geom)
            except Exception:
                candidate_refs = []

            for ref in candidate_refs:
                if isinstance(ref, (int, np.integer)):
                    idx = int(ref)
                else:
                    idx = geom_id_to_idx.get(id(ref), -1)
                if idx < 0:
                    continue
                if orders[idx] <= i:
                    continue
                cand = geoms[idx]
                try:
                    if cand.intersects(geom):
                        occluders.append(cand)
                except Exception:
                    continue

            if not occluders:
                clipped = geom
            else:
                occ = occluders[0] if len(occluders) == 1 else unary_union(occluders)
                try:
                    clipped = geom.difference(occ)
                except Exception:
                    # First attempt failed — repair both geometries and retry.
                    try:
                        fixed_geom = geom if geom.is_valid else geom.buffer(0)
                        fixed_occ = occ if occ.is_valid else occ.buffer(0)
                        clipped = fixed_geom.difference(fixed_occ)
                    except Exception:
                        # Cannot compute difference — drop shape to avoid
                        # overlapping geometry that breaks the mesh.
                        clipped = None

            if clipped is not None and not clipped.is_empty:
                if not clipped.is_valid:
                    clipped = make_valid(clipped)
                if not clipped.is_empty:
                    result.append(
                        {
                            "geometry": clipped,
                            "color": item["color"],
                            "draw_order": i,
                        }
                    )

        result.reverse()
        if return_silhouette:
            try:
                silhouette = unary_union(geoms)
            except Exception:
                silhouette = None
            return result, silhouette
        return result

    # ── Stage 4: Color matching with per-color cache ─────────────────────

    def _match_lut_index_for_rgb(self, query_rgb):
        """Return the LUT index and Lab distance for one RGB query.

        Uses the shared hue-aware matcher when it is enabled on the
        image processor, keeping SVG-native matching aligned with the
        raster/high-fidelity paths.

        使用图像处理器已启用的色相保护匹配器，让 SVG 原生矢量路径与
        栅格/高保真路径保持一致。
        """
        query_lab = self.img_processor._rgb_to_lab(
            np.array([query_rgb], dtype=np.uint8)
        )
        hue_matcher = getattr(self.img_processor, "hue_matcher", None)
        if hue_matcher is not None:
            matched_indices = hue_matcher.match_colors_batch(
                np.array([query_rgb], dtype=np.uint8)
            )
            lut_idx = int(np.asarray(matched_indices).reshape(-1)[0])
            matched_lab = np.asarray(
                self.img_processor.lut_lab[lut_idx],
                dtype=np.float64,
            )
            lab_dist = float(
                np.linalg.norm(query_lab.reshape(-1) - matched_lab.reshape(-1))
            )
            return lut_idx, lab_dist

        dist, index = self.img_processor.kdtree.query(query_lab)
        lut_idx = int(index[0])
        lab_dist = float(dist[0]) if hasattr(dist, "__len__") else float(dist)
        return lut_idx, lab_dist

    def _match_colors(self, clipped_shapes, replacement_manager, num_channels, num_layers=None):
        """Match each shape's fill colour to a LUT recipe.

        Identical fill colours share a single KDTree lookup via a cache,
        mirroring ``ChromaPrint3D::VectorRecipeMap::Match`` behaviour.

        Returns a list of dicts: ``{geometry, recipe, color}``.
        """
        if num_layers is None:
            num_layers = PrinterConfig.COLOR_LAYERS
        recipe_log_mode = os.getenv("LUMINA_VECTOR_RECIPE_LOG", "summary").strip().lower()
        color_cache = {}
        matched = []
        sample_logs = []

        for item in clipped_shapes:
            rgb = item["color"]
            query_rgb = item.get("match_color", rgb)
            try:
                query_rgb = (int(query_rgb[0]), int(query_rgb[1]), int(query_rgb[2]))
            except (TypeError, IndexError, ValueError):
                query_rgb = rgb

            if query_rgb in color_cache:
                cached = color_cache[query_rgb]
                recipe = cached["recipe"]
                matched_rgb = cached["matched_rgb"]
                lut_idx = cached["lut_idx"]
            else:
                lut_idx, lab_dist = self._match_lut_index_for_rgb(query_rgb)
                matched_rgb = tuple(int(c) for c in self.img_processor.lut_rgb[lut_idx])

                if replacement_manager is not None:
                    replacement = replacement_manager.get_replacement(matched_rgb)
                    if replacement is not None:
                        rep_lab = self.img_processor._rgb_to_lab(np.array([replacement], dtype=np.uint8))
                        _, rep_index = self.img_processor.kdtree.query(rep_lab)
                        lut_idx = int(rep_index[0])
                        matched_rgb = tuple(int(c) for c in self.img_processor.lut_rgb[lut_idx])

                stack = self.img_processor.ref_stacks[lut_idx]
                recipe = [min(int(stack[z]), num_channels - 1) for z in range(min(num_layers, len(stack)))]
                color_cache[query_rgb] = {
                    "recipe": recipe,
                    "matched_rgb": matched_rgb,
                    "lut_idx": lut_idx,
                    "lab_dist": lab_dist,
                }

                hex_c = f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"
                query_hex = f"#{query_rgb[0]:02x}{query_rgb[1]:02x}{query_rgb[2]:02x}"
                matched_hex = f"#{matched_rgb[0]:02x}{matched_rgb[1]:02x}{matched_rgb[2]:02x}"

                # Flag suspiciously large Lab distance (>25 is visually very different)
                if lab_dist > 25.0:
                    _log.warning(
                        "Large color distance in match: %s -> %s (Lab dist=%.1f)",
                        query_hex, matched_hex, lab_dist,
                        extra={
                            "event": "vector_match_color_large_distance",
                            "query_rgb": list(query_rgb),
                            "matched_rgb": list(matched_rgb),
                            "lab_distance": round(lab_dist, 2),
                            "lut_idx": lut_idx,
                            "kdtree_size": self.img_processor.kdtree.n if hasattr(self.img_processor.kdtree, 'n') else len(self.img_processor.lut_rgb),
                        },
                    )

                if recipe_log_mode == "full":
                    if query_rgb != rgb:
                        _log.debug("  %s => %s -> %s -> recipe %s (dist=%.2f)", hex_c, query_hex, matched_hex, recipe, lab_dist)
                    else:
                        _log.debug("  %s -> %s -> recipe %s (dist=%.2f)", hex_c, matched_hex, recipe, lab_dist)
                elif recipe_log_mode == "summary" and len(sample_logs) < 8:
                    if query_rgb != rgb:
                        sample_logs.append(f"{hex_c} => {query_hex} -> {matched_hex} -> {recipe} (dist={lab_dist:.1f})")
                    else:
                        sample_logs.append(f"{hex_c} -> {matched_hex} -> {recipe} (dist={lab_dist:.1f})")

            matched.append(
                {
                    "geometry": item["geometry"],
                    "recipe": recipe,
                    "color": rgb,
                    "match_color": query_rgb,
                    "matched_rgb": matched_rgb,
                    "lut_idx": int(lut_idx),
                }
            )

        if recipe_log_mode == "summary":
            _log.debug(
                "Recipe cache summary: unique_colors=%s, shapes=%s",
                len(color_cache),
                len(clipped_shapes),
            )
            if sample_logs:
                _log.debug("Recipe samples: %s", "; ".join(sample_logs))

        match_samples = []
        for item in matched[:8]:
            match_samples.append(
                {
                    "color": [int(c) for c in item.get("color", ())],
                    "match_color": [int(c) for c in item.get("match_color", ())],
                    "matched_rgb": [int(c) for c in item.get("matched_rgb", ())],
                    "recipe": [int(v) for v in item.get("recipe", ())],
                    "lut_idx": int(item.get("lut_idx", -1)),
                }
            )
        _log.debug(
            "Vector color match summary",
            extra={
                "event": "vector_diag_match_colors_summary",
                "shape_count": len(clipped_shapes),
                "matched_shape_count": len(matched),
                "unique_query_color_count": len(color_cache),
                "sample_first8": match_samples,
            },
        )
        return matched

    # ── Stage 5: Run-length extrusion ────────────────────────────────────

    @staticmethod
    def _build_channel_runs(recipe, layers_to_use, num_channels):
        """Build contiguous layer runs grouped by channel.

        Returns:
            dict[channel_id] -> list of (start_layer, end_layer)
        """
        runs_by_channel = {}
        if layers_to_use <= 0:
            return runs_by_channel

        run_start = 0
        run_channel = int(recipe[0])
        for z in range(1, layers_to_use + 1):
            current_channel = int(recipe[z]) if z < layers_to_use else None
            if current_channel != run_channel:
                if 0 <= run_channel < num_channels:
                    runs_by_channel.setdefault(run_channel, []).append((run_start, z - 1))
                run_start = z
                run_channel = current_channel

        return runs_by_channel

    @staticmethod
    def _run_length_extrude(
        matched_shapes,
        num_layers,
        layer_h,
        num_channels,
        slot_names,
        scale_factor,
        extrude_cache=None,
        face_up=False,
        optical_z_base=0.0,
    ):
        """Extrude each shape per channel, merging consecutive same-channel
        layers into single volumes (run-length encoding).

        Before extrusion, shapes sharing the same (channel, layer-run) are
        merged via ``unary_union`` + morphological closing to eliminate gaps
        between adjacent same-colour regions (Fix 7).

        When *face_up* is True the layer order is reversed so that
        recipe[N-1] sits at the lowest Z (just above *optical_z_base*)
        and recipe[0] at the highest Z — matching ``_build_voxel_matrix_faceup``
        semantics used by the raster path for 5-Color Extended.
        """
        # --- Fix 7: group shapes by (channel, run) and merge ---
        # Key: (channel_id, run_start, run_end)  Value: list of geometries
        run_groups: dict[tuple, list] = {}
        skipped_empty = 0
        invalid_channel_runs = 0
        invalid_slot_runs = 0
        short_recipe_shapes = 0

        for item in matched_shapes:
            geom = item["geometry"]
            recipe = item["recipe"]
            if geom is None or geom.is_empty:
                skipped_empty += 1
                continue

            layers_to_use = min(num_layers, len(recipe))
            if len(recipe) < num_layers:
                short_recipe_shapes += 1
            runs_by_channel = VectorProcessor._build_channel_runs(recipe, layers_to_use, num_channels)
            invalid_channels = [
                int(ch_raw)
                for ch_raw in recipe[:layers_to_use]
                if int(ch_raw) < 0 or int(ch_raw) >= num_channels
            ]
            if invalid_channels:
                invalid_channel_runs += len(invalid_channels)
                _log.debug(
                    "Vector run dropped by channel guard",
                    extra={
                        "event": "vector_appearance_diag_run_dropped_by_channel_guard",
                        "invalid_channels": invalid_channels[:16],
                        "num_channels": int(num_channels),
                        "recipe": [int(v) for v in recipe],
                    },
                )

            for ch, runs in runs_by_channel.items():
                if ch >= len(slot_names):
                    invalid_slot_runs += len(runs)
                    _log.debug(
                        "Vector run dropped by slot guard",
                        extra={
                            "event": "vector_appearance_diag_run_dropped_by_slot_guard",
                            "channel": int(ch),
                            "run_count": len(runs),
                            "slot_count": len(slot_names),
                        },
                    )
                    continue
                for run_start, run_end in runs:
                    key = (ch, run_start, run_end)
                    run_groups.setdefault(key, []).append(geom)

        if skipped_empty:
            _log.debug(
                "Vector empty geometry skipped before extrusion",
                extra={
                    "event": "vector_diag_extrude_skipped_empty",
                    "skipped_count": int(skipped_empty),
                    "stage": "run_group_build",
                },
            )
        if short_recipe_shapes:
            _log.debug(
                "Vector shape recipe shorter than requested layers",
                extra={
                    "event": "vector_appearance_diag_shape_recipe_short",
                    "shape_count": int(short_recipe_shapes),
                    "num_layers": int(num_layers),
                },
            )
        run_summary = {
            "run_group_count": len(run_groups),
            "skipped_empty": int(skipped_empty),
            "invalid_channel_runs": int(invalid_channel_runs),
            "invalid_slot_runs": int(invalid_slot_runs),
        }
        _log.debug(
            "Vector run summary",
            extra={
                "event": "vector_appearance_diag_run_summary",
                **run_summary,
            },
        )
        stage_c_hist: dict[int, dict[int, int]] = {}
        for (ch, run_start, run_end), geoms in run_groups.items():
            for layer_idx in range(int(run_start), int(run_end) + 1):
                layer_hist = stage_c_hist.setdefault(int(layer_idx), {})
                layer_hist[int(ch)] = layer_hist.get(int(ch), 0) + len(geoms)
        _log.debug(
            "Vector run groups per layer/channel",
            extra={
                "event": "vector_diag_stage_c_run_groups_per_layer_channel",
                "per_layer_channel_shape_count": stage_c_hist,
                **run_summary,
            },
        )

        meshes_by_slot = {}
        stage_d_hist: dict[int, dict[int, int]] = {}
        for (ch, run_start, run_end), geoms in run_groups.items():
            slot_name = slot_names[ch]
            if slot_name not in meshes_by_slot:
                meshes_by_slot[slot_name] = {"meshes": [], "mat_id": ch}

            if len(geoms) > 1:
                pre_union_area = 0.0
                for g in geoms:
                    try:
                        pre_union_area += float(g.area)
                    except (AttributeError, TypeError, ValueError):
                        pass
                # Normalize vertex coordinates to a fixed precision grid
                # before unary_union to prevent GEOS floating-point
                # precision boundary bugs that silently drop geometry.
                # set_precision 将坐标对齐到规则浮点网格，打破 bezier 展平 +
                # simplify + inflate/deflate 导致的 GEOS 精度边界（丢几何）。
                snapped_geoms = []
                for g in geoms:
                    if g is not None and not g.is_empty:
                        g_snapped = set_precision(g, grid_size=0.001)
                        if g_snapped is not None and not g_snapped.is_empty:
                            snapped_geoms.append(g_snapped)
                if snapped_geoms:
                    geoms = snapped_geoms
                try:
                    unioned = unary_union(geoms)
                    union_area = float(unioned.area) if unioned is not None and not unioned.is_empty else 0.0
                    if pre_union_area > 0 and union_area < pre_union_area * 0.98:
                        _log.debug(
                            "Vector unary union area loss",
                            extra={
                                "event": "vector_diag_unary_union_area_loss",
                                "channel": int(ch),
                                "run_start": int(run_start),
                                "run_end": int(run_end),
                                "pre_union_area": round(pre_union_area, 6),
                                "post_union_area": round(union_area, 6),
                            },
                        )
                    merged = VectorProcessor._normalize_contours(unioned, close_delta_mm=0.03)
                    if merged is None or merged.is_empty:
                        _log.debug(
                            "Vector normalize emptied geometry",
                            extra={
                                "event": "vector_appearance_diag_normalize_emptied",
                                "channel": int(ch),
                                "run_start": int(run_start),
                                "run_end": int(run_end),
                                "pre_normalize_area": round(union_area, 6),
                            },
                        )
                        merged = unioned
                    else:
                        normalized_area = float(merged.area)
                        if union_area > 0 and normalized_area < union_area * 0.98:
                            _log.debug(
                                "Vector normalize area loss",
                                extra={
                                    "event": "vector_diag_normalize_area_loss",
                                    "channel": int(ch),
                                    "run_start": int(run_start),
                                    "run_end": int(run_end),
                                    "pre_normalize_area": round(union_area, 6),
                                    "post_normalize_area": round(normalized_area, 6),
                                },
                            )
                except Exception:
                    merged = unary_union(geoms)
            else:
                merged = geoms[0]

            if face_up:
                inv_start = (num_layers - 1) - run_end
                inv_end = (num_layers - 1) - run_start
                z_bot = optical_z_base + inv_start * layer_h
                height = (inv_end - inv_start + 1) * layer_h
            else:
                z_bot = run_start * layer_h
                height = (run_end - run_start + 1) * layer_h

            new_meshes = VectorProcessor._extrude_geometry(
                merged,
                height=height,
                z_offset=z_bot,
                scale=scale_factor,
                extrude_cache=extrude_cache,
            )
            meshes_by_slot[slot_name]["meshes"].extend(new_meshes)
            for layer_idx in range(int(run_start), int(run_end) + 1):
                layer_hist = stage_d_hist.setdefault(int(layer_idx), {})
                layer_hist[int(ch)] = layer_hist.get(int(ch), 0) + len(new_meshes)

        _log.debug(
            "Vector built meshes per layer/channel",
            extra={
                "event": "vector_diag_stage_d_built_meshes_per_layer_channel",
                "per_layer_channel_mesh_count": stage_d_hist,
                "slot_count": len(meshes_by_slot),
            },
        )
        _log.debug(
            "Vector diagnostic debug dump",
            extra={
                "event": "vector_diag_debug_dump",
                "run_summary": run_summary,
                "slot_count": len(meshes_by_slot),
                "face_up": bool(face_up),
                "optical_z_base": float(optical_z_base),
            },
        )
        return meshes_by_slot

    # ── Stage 7: Double-sided helper ─────────────────────────────────────

    @staticmethod
    def _add_double_sided_layers(
        matched_shapes,
        num_layers,
        layer_h,
        num_channels,
        slot_names,
        scale_factor,
        top_z_start,
        meshes_by_slot,
        extrude_cache=None,
    ):
        """Mirror colour layers above the backing for double-sided mode.

        Layer Z order is inverted so the viewing surface faces upward on
        the top side.
        """
        for item in matched_shapes:
            geom = item["geometry"]
            recipe = item["recipe"]
            if geom is None or geom.is_empty:
                continue

            layers_to_use = min(num_layers, len(recipe))

            runs_by_channel = VectorProcessor._build_channel_runs(recipe, layers_to_use, num_channels)
            for ch, runs in runs_by_channel.items():
                if ch >= len(slot_names):
                    continue

                slot_name = slot_names[ch]
                if slot_name not in meshes_by_slot:
                    meshes_by_slot[slot_name] = {"meshes": [], "mat_id": ch}

                for run_start, run_end in runs:
                    inv_start = (num_layers - 1) - run_end
                    inv_end = (num_layers - 1) - run_start

                    z_bot = top_z_start + inv_start * layer_h
                    height = (inv_end - inv_start + 1) * layer_h
                    new_meshes = VectorProcessor._extrude_geometry(
                        geom,
                        height=height,
                        z_offset=z_bot,
                        scale=scale_factor,
                        extrude_cache=extrude_cache,
                    )
                    meshes_by_slot[slot_name]["meshes"].extend(new_meshes)

    # ── SVG parsing ──────────────────────────────────────────────────────

    def _parse_svg(self, svg_path: str, target_width_mm: float):
        """Parse SVG and return shapes in draw order with normalised coords.

        Returns:
            ``(shape_list, scale_factor, bbox_tuple)``
            where each shape item is ``{'poly': Polygon, 'color': (r,g,b)}``.
        """
        try:
            svg = SVG.parse(svg_path)
        except Exception as e:
            raise ValueError(f"Failed to parse SVG: {e}")

        image_vectorizer_origin = False
        try:
            root = ET.parse(svg_path).getroot()
            image_vectorizer_origin = root.get("data-lumina-origin") == "image-vectorizer"
        except VECTOR_HANDLED_ERRORS:
            image_vectorizer_origin = False
        self._last_image_vectorizer_bounds = None
        gradient_defs = VectorProcessor._parse_gradient_defs(svg_path)
        _url_re = re.compile(r"url\(#([^)]+)\)")

        tol_svg = self.sampling_precision / max(target_width_mm / 100.0, 0.01)
        parse_expand_stroke_to_fill = bool(getattr(self, "_parse_expand_stroke_to_fill", True))

        def _sample_path_coords(path_obj):
            try:
                segments = list(path_obj.segments())
            except Exception:
                segments = None

            if segments and len(segments) > 1:
                coords = _flatten_segments(segments, tol_svg)
            else:
                coords = _flatten_segments_fallback(path_obj, tol_svg)

            if segments:
                try:
                    last_end = segments[-1].end
                    last_pt = (last_end.x, last_end.y)
                    if coords and coords[-1] != last_pt:
                        coords.append(last_pt)
                except VECTOR_HANDLED_ERRORS:
                    pass
            return coords

        def _signed_ring_area(coords):
            if len(coords) < 3:
                return 0.0
            area = 0.0
            for (x1, y1), (x2, y2) in zip(coords, coords[1:] + coords[:1]):
                area += (float(x1) * float(y2)) - (float(x2) * float(y1))
            return area * 0.5

        def _polygon_from_coords(coords):
            if len(coords) < 3:
                return None

            poly = Polygon(coords)
            if not poly.is_valid:
                poly = make_valid(poly)
            poly = VectorProcessor._extract_polygonal_geometry(poly)

            if poly is not None and not poly.is_empty:
                return poly
            return None

        def _sample_path_to_polygon(path_obj):
            return _polygon_from_coords(_sample_path_coords(path_obj))

        def _combine_nonzero_subpaths(subpath_items):
            """Merge subpaths using SVG nonzero winding orientation.

            SVG's default ``nonzero`` fill rule uses opposite winding
            direction for holes. A plain union turns those holes into solid
            paint, which is exactly what Vector Magic output does around
            small white foot / eye details.

            按 SVG 默认 nonzero 规则合并复合路径：反向子路径是洞，不能
            简单 union，否则白色细节会被深色路径填实。
            """
            if not subpath_items:
                return None
            if len(subpath_items) == 1:
                return subpath_items[0]["poly"]

            try:
                boundaries = [
                    item["poly"].boundary
                    for item in subpath_items
                    if item.get("poly") is not None and not item["poly"].is_empty
                ]
                faces = list(polygonize(unary_union(boundaries))) if boundaries else []
                filled_faces = []
                for face in faces:
                    probe = face.representative_point()
                    winding = 0
                    for item in subpath_items:
                        poly = item["poly"]
                        if poly is None or poly.is_empty:
                            continue
                        if poly.contains(probe):
                            winding += 1 if item.get("signed_area", 0.0) >= 0 else -1
                    if winding != 0:
                        filled_faces.append(face)
                if filled_faces:
                    result = unary_union(filled_faces)
                    result = VectorProcessor._extract_polygonal_geometry(make_valid(result))
                    if result is not None and not result.is_empty:
                        return result
            except VECTOR_HANDLED_ERRORS:
                pass

            # Use the largest ring's orientation as the main paint
            # direction. Opposite-orientation rings inside it become holes;
            # disjoint opposite rings are still valid filled islands under
            # nonzero winding and are kept.
            dominant_sign = 1 if subpath_items[0]["signed_area"] >= 0 else -1
            try:
                dominant = max(
                    subpath_items,
                    key=lambda item: abs(float(item.get("signed_area", 0.0))),
                )
                dominant_sign = 1 if dominant["signed_area"] >= 0 else -1
            except (TypeError, ValueError):
                pass

            fill_polys = []
            opposite_polys = []
            for item in subpath_items:
                poly = item["poly"]
                if poly is None or poly.is_empty:
                    continue
                sign = 1 if item.get("signed_area", 0.0) >= 0 else -1
                if sign == dominant_sign:
                    fill_polys.append(poly)
                else:
                    opposite_polys.append(poly)

            if fill_polys:
                try:
                    combined = unary_union(fill_polys)
                except VECTOR_HANDLED_ERRORS:
                    combined = fill_polys[0]
            else:
                combined = None

            disjoint_opposite = []
            for hole in opposite_polys:
                if hole is None or hole.is_empty:
                    continue
                if combined is None or combined.is_empty:
                    disjoint_opposite.append(hole)
                    continue
                try:
                    if combined.intersects(hole) or combined.contains(hole):
                        combined = combined.difference(hole)
                    else:
                        disjoint_opposite.append(hole)
                except VECTOR_HANDLED_ERRORS:
                    disjoint_opposite.append(hole)

            pieces = []
            if combined is not None and not combined.is_empty:
                pieces.append(combined)
            pieces.extend(
                poly for poly in disjoint_opposite
                if poly is not None and not poly.is_empty
            )
            if not pieces:
                return None
            try:
                result = unary_union(pieces)
            except VECTOR_HANDLED_ERRORS:
                result = pieces[0]
            result = VectorProcessor._extract_polygonal_geometry(make_valid(result))
            return result if result is not None and not result.is_empty else None

        def _sample_path_to_stroke_geometry(
            path_obj, stroke_width_svg, cap_style_name="round", join_style_name="round"
        ):
            try:
                segments = list(path_obj.segments())
            except Exception:
                segments = None

            if segments and len(segments) > 1:
                coords = _flatten_segments(segments, tol_svg)
            else:
                coords = _flatten_segments_fallback(path_obj, tol_svg)

            if segments:
                try:
                    last_end = segments[-1].end
                    last_pt = (last_end.x, last_end.y)
                    if not coords or coords[-1] != last_pt:
                        coords.append(last_pt)
                except Exception:
                    pass

            if len(coords) < 2:
                return None

            try:
                stroke_geom = LineString(coords).buffer(
                    max(float(stroke_width_svg) * 0.5, 1e-6),
                    cap_style=cap_style_name,
                    join_style=join_style_name,
                    mitre_limit=2.0,
                )
            except Exception:
                return None

            stroke_geom = VectorProcessor._extract_polygonal_geometry(make_valid(stroke_geom))
            if stroke_geom is not None and not stroke_geom.is_empty:
                return stroke_geom
            return None

        def _flatten_segments(segments, tolerance):
            """Adaptive de Casteljau flattening for each segment."""
            coords = []
            for seg in segments:
                if isinstance(seg, Move):
                    continue
                if isinstance(seg, (Line, Close)):
                    coords.append((seg.start.x, seg.start.y))
                elif isinstance(seg, CubicBezier):
                    start_pt = (seg.start.x, seg.start.y)
                    if not coords or coords[-1] != start_pt:
                        coords.append(start_pt)
                    _flatten_cubic(
                        seg.start.x,
                        seg.start.y,
                        seg.control1.x,
                        seg.control1.y,
                        seg.control2.x,
                        seg.control2.y,
                        seg.end.x,
                        seg.end.y,
                        tolerance,
                        coords,
                        0,
                    )
                elif isinstance(seg, QuadraticBezier):
                    start_pt = (seg.start.x, seg.start.y)
                    if not coords or coords[-1] != start_pt:
                        coords.append(start_pt)
                    _flatten_quadratic(
                        seg.start.x,
                        seg.start.y,
                        seg.control.x,
                        seg.control.y,
                        seg.end.x,
                        seg.end.y,
                        tolerance,
                        coords,
                        0,
                    )
                else:
                    coords.append((seg.start.x, seg.start.y))
                    try:
                        for tv in np.linspace(0.1, 1.0, 10):
                            pt = seg.point(tv)
                            coords.append((pt.x, pt.y))
                    except Exception:
                        coords.append((seg.end.x, seg.end.y))
            return coords

        def _flatten_segments_fallback(path_obj, tolerance):
            """Fallback for paths that can't be decomposed into segments."""
            try:
                path_len = path_obj.length()
            except Exception:
                return []
            if path_len == 0:
                return []
            n = max(10, min(int(path_len / max(tolerance, 0.01)), 8000))
            t_vals = np.linspace(0, 1, n)
            pts = [path_obj.point(t) for t in t_vals]
            return [(p.x, p.y) for p in pts]

        raw_shapes = []
        skipped_types = {}
        skipped_gradient_count = 0
        skipped_polygon_count = 0
        _log.debug("Parsing SVG geometry...")

        def _sample_stroke_geometry(path_obj, stroke_width_svg, cap_style_name="round", join_style_name="round"):
            try:
                segments = list(path_obj.segments())
            except Exception:
                segments = None

            if segments and len(segments) > 1:
                coords = _flatten_segments(segments, tol_svg)
            else:
                coords = _flatten_segments_fallback(path_obj, tol_svg)

            if len(coords) < 2:
                return None

            try:
                stroke_geom = LineString(coords).buffer(
                    max(float(stroke_width_svg) * 0.5, 1e-6),
                    cap_style=cap_style_name,
                    join_style=join_style_name,
                    mitre_limit=2.0,
                )
                stroke_geom = VectorProcessor._extract_polygonal_geometry(make_valid(stroke_geom))
                return stroke_geom if stroke_geom is not None and not stroke_geom.is_empty else None
            except Exception:
                return None

        for element in svg.elements():
            if not isinstance(element, (Path, Shape)):
                type_name = type(element).__name__
                skipped_types[type_name] = skipped_types.get(type_name, 0) + 1
                continue

            has_fill = (
                element.fill is not None
                and element.fill.value is not None
                and str(element.fill.value).lower() != "none"
            )
            has_stroke = (
                getattr(element, "stroke", None) is not None
                and getattr(element.stroke, "value", None) is not None
                and str(element.stroke.value).lower() != "none"
            )
            stroke_rgb = None
            stroke_hex = None
            stroke_width = 0.0
            if has_stroke:
                stroke_hex = _color_object_to_hex(getattr(element, "stroke", None))
                try:
                    stroke_rgb = (element.stroke.red, element.stroke.green, element.stroke.blue)
                except (AttributeError, TypeError, ValueError):
                    stroke_rgb = None
                try:
                    stroke_width = float(getattr(element, "stroke_width", 0.0) or 0.0)
                except Exception:
                    stroke_width = 0.0
            if not has_fill:
                if has_stroke and parse_expand_stroke_to_fill:
                    stroke_modeled = False
                    if isinstance(element, Shape) and not isinstance(element, Path):
                        try:
                            element = Path(element)
                        except Exception:
                            continue

                    if stroke_rgb is not None and stroke_width > 0.0:
                        try:
                            linecap = str(getattr(element, "stroke_linecap", None) or "round").strip().lower()
                        except Exception:
                            linecap = "round"
                        try:
                            linejoin = str(getattr(element, "stroke_linejoin", None) or "round").strip().lower()
                        except Exception:
                            linejoin = "round"
                        cap_style = "flat" if linecap == "butt" else ("square" if linecap == "square" else "round")
                        join_style = "mitre" if linejoin == "miter" else linejoin
                        stroke_geom = _sample_path_to_stroke_geometry(
                            element,
                            stroke_width,
                            cap_style_name=cap_style,
                            join_style_name=join_style,
                        )
                        if stroke_geom is not None and not stroke_geom.is_empty:
                            raw_shapes.append(
                                {
                                    "poly": stroke_geom,
                                    "color": stroke_rgb,
                                    "source_kind": "stroke_only",
                                    "stroke_width_svg": float(stroke_width),
                                }
                            )
                            stroke_modeled = True
                continue

            if isinstance(element, Shape) and not isinstance(element, Path):
                try:
                    element = Path(element)
                except Exception:
                    continue

            grad_info = None
            raw_fill = None
            vals = getattr(element, "values", None)
            if isinstance(vals, dict):
                raw_fill = vals.get("fill", "")
            if raw_fill and gradient_defs:
                m = _url_re.match(str(raw_fill))
                if m:
                    grad_info = gradient_defs.get(m.group(1))
            is_gradient = grad_info is not None

            rgb = None
            if has_fill and not is_gradient:
                try:
                    rgb = (element.fill.red, element.fill.green, element.fill.blue)
                    # Skip fully transparent fills (e.g. rgba(0,0,0,0)) — they
                    # represent "no fill" / transparent background, not a black shape.
                    # If the element also has a visible stroke, fall through to the
                    # stroke-expansion path instead of discarding the element entirely.
                    # 跳过完全透明的填色（如 rgba(0,0,0,0)），它们代表"无填色"
                    # 而非黑色形状。若元素同时有可见描边，则走描边扩展路径。
                    fill_alpha = getattr(element.fill, "alpha", None)
                    if fill_alpha is not None and float(fill_alpha) < 0.01:
                        rgb = None
                        has_fill = False  # let stroke-only path handle it
                except (AttributeError, TypeError, ValueError):
                    rgb = None
            if rgb is None and not is_gradient:
                # Transparent fill with visible stroke: model as stroke-only geometry
                # 透明填色 + 可见描边：按仅描边几何处理
                if has_stroke and parse_expand_stroke_to_fill and stroke_rgb is not None and stroke_width > 0.0:
                    if isinstance(element, Shape) and not isinstance(element, Path):
                        try:
                            element = Path(element)
                        except (AttributeError, TypeError, ValueError, NotImplementedError):
                            continue
                    try:
                        linecap = str(getattr(element, "stroke_linecap", None) or "round").strip().lower()
                    except (AttributeError, TypeError, ValueError):
                        linecap = "round"
                    try:
                        linejoin = str(getattr(element, "stroke_linejoin", None) or "round").strip().lower()
                    except (AttributeError, TypeError, ValueError):
                        linejoin = "round"
                    cap_style = "flat" if linecap == "butt" else ("square" if linecap == "square" else "round")
                    join_style = "mitre" if linejoin == "miter" else linejoin
                    stroke_geom = _sample_path_to_stroke_geometry(
                        element,
                        stroke_width,
                        cap_style_name=cap_style,
                        join_style_name=join_style,
                    )
                    if stroke_geom is not None and not stroke_geom.is_empty:
                        raw_shapes.append(
                            {
                                "poly": stroke_geom,
                                "color": stroke_rgb,
                                "source_kind": "stroke_only",
                                "stroke_width_svg": float(stroke_width),
                            }
                        )
                fill_val = getattr(element.fill, "value", None) if element.fill else None
                eid = getattr(element, "id", None) or f"element#{skipped_gradient_count}"
                _log.debug(f"Skipping '{eid}' — unresolvable fill: {fill_val}")
                skipped_gradient_count += 1
                continue

            fill_hex = _rgb_to_hex(rgb)

            try:
                subpaths = list(element.as_subpaths())
            except Exception:
                subpaths = []

            subpath_items = []
            for subpath in subpaths:
                try:
                    sub_path = subpath if isinstance(subpath, Path) else Path(subpath)
                    coords = _sample_path_coords(sub_path)
                    poly = _polygon_from_coords(coords)
                except Exception:
                    continue
                if poly is None:
                    continue
                subpath_items.append(
                    {
                        "poly": poly,
                        "signed_area": _signed_ring_area(coords),
                    }
                )
            subpath_polys = [item["poly"] for item in subpath_items]

            # --- Fix 4: gradient flattening ---
            if is_gradient:
                grad_shapes = VectorProcessor._flatten_gradient_shape(
                    grad_info,
                    subpath_polys,
                    color_bands=getattr(self, "gradient_color_bands", None),
                )
                for gs in grad_shapes:
                    p = gs["poly"]
                    if p is not None and not p.is_empty:
                        p = VectorProcessor._normalize_contours(p)
                        if p is not None and not p.is_empty:
                            raw_shapes.append({"poly": p, "color": gs["color"]})
                if not grad_shapes:
                    skipped_gradient_count += 1
                continue

            # --- Fix 2: fill-rule aware subpath merging ---
            fill_rule = "nonzero"
            try:
                fr = getattr(element, "fill_rule", None)
                if fr is not None:
                    fill_rule = str(fr).strip().lower()
                if fill_rule not in ("nonzero", "evenodd") or fr is None:
                    vals = getattr(element, "values", None)
                    if isinstance(vals, dict):
                        vfr = vals.get("fill-rule", "").strip().lower()
                        if vfr in ("nonzero", "evenodd"):
                            fill_rule = vfr
                    elif hasattr(vals, "__getitem__"):
                        try:
                            vfr = str(vals["fill-rule"]).strip().lower()
                            if vfr in ("nonzero", "evenodd"):
                                fill_rule = vfr
                        except (KeyError, TypeError):
                            pass
            except Exception:
                fill_rule = "nonzero"
            if fill_rule not in ("nonzero", "evenodd"):
                fill_rule = "nonzero"

            if len(subpath_items) == 1:
                result_poly = subpath_items[0]["poly"]
            elif len(subpath_polys) > 1:
                if fill_rule == "evenodd":
                    combined = subpath_polys[0]
                    for sp in subpath_polys[1:]:
                        try:
                            combined = combined.symmetric_difference(sp)
                        except Exception:
                            pass
                else:
                    combined = _combine_nonzero_subpaths(subpath_items)

                if combined is not None and not combined.is_empty:
                    if not combined.is_valid:
                        combined = make_valid(combined)
                    result_poly = combined if not combined.is_empty else None
                else:
                    result_poly = None
            else:
                result_poly = None

            if result_poly is None:
                try:
                    result_poly = _sample_path_to_polygon(element)
                except Exception:
                    pass

            if result_poly is None:
                skipped_polygon_count += 1
                continue

            # --- Fix 3: morphological closing ---
            same_color_stroke_double_buffer = False
            if (
                parse_expand_stroke_to_fill
                and has_stroke
                and fill_hex is not None
            ):
                stroke_hex = _color_object_to_hex(getattr(element, "stroke", None))
                try:
                    stroke_width = float(getattr(element, "stroke_width", 0.0) or 0.0)
                except Exception:
                    stroke_width = 0.0
                if stroke_hex == fill_hex and stroke_width > 0.0:
                    try:
                        # SVG renders same-color stroke as additional visible area.
                        # Preserve that paint so native vector output does not leave
                        # pinholes between neighboring filled paths.
                        expanded = result_poly.buffer(
                            stroke_width * 0.5,
                            join_style="mitre",
                            mitre_limit=2.0,
                        )
                        expanded = VectorProcessor._extract_polygonal_geometry(make_valid(expanded))
                        if expanded is not None and not expanded.is_empty:
                            result_poly = expanded
                            same_color_stroke_double_buffer = True
                    except Exception:
                        pass

            result_poly = VectorProcessor._normalize_contours(result_poly)
            if result_poly is None or result_poly.is_empty:
                skipped_polygon_count += 1
                continue

            raw_shapes.append(
                {
                    "poly": result_poly,
                    "color": rgb,
                    "source_kind": "fill",
                    "same_color_stroke": bool(has_stroke and stroke_hex == fill_hex and stroke_width > 0.0),
                    "same_color_stroke_double_buffer": same_color_stroke_double_buffer,
                    "stroke_width_svg": float(stroke_width) if has_stroke else 0.0,
                }
            )

        if skipped_types:
            _log.debug(f"Skipped non-path elements: {skipped_types}")
        if skipped_gradient_count > 0:
            _log.debug(f"{skipped_gradient_count} gradient fills could not be fully resolved")
        if skipped_polygon_count > 0:
            _log.debug(f"Skipped {skipped_polygon_count} elements (invalid polygon after sampling)")
        _log.debug(f"Successfully parsed {len(raw_shapes)} shapes from SVG")

        parse_warnings = []
        if skipped_gradient_count > 0:
            parse_warnings.append(f"{skipped_gradient_count} gradient/pattern fills could not be fully resolved")
        if skipped_polygon_count > 0:
            parse_warnings.append(f"{skipped_polygon_count} elements produced invalid geometry and were skipped")
        self.parse_warnings = parse_warnings

        if not raw_shapes:
            raise ValueError("No valid shapes found in SVG")

        # Global bounding box — union of parsed shapes and SVG viewport
        min_xs, min_ys, max_xs, max_ys = [], [], [], []
        for item in raw_shapes:
            bx0, by0, bx1, by1 = item["poly"].bounds
            min_xs.append(bx0)
            min_ys.append(by0)
            max_xs.append(bx1)
            max_ys.append(by1)

        gx0, gy0 = min(min_xs), min(min_ys)
        gx1, gy1 = max(max_xs), max(max_ys)

        svg_viewport_bounds = None
        try:
            vb = getattr(svg, "viewbox", None)
            if vb is not None:
                vb_x = float(getattr(vb, "x", 0) or 0)
                vb_y = float(getattr(vb, "y", 0) or 0)
                vb_w = float(getattr(vb, "width", 0) or 0)
                vb_h = float(getattr(vb, "height", 0) or 0)
                if vb_w > 0 and vb_h > 0:
                    svg_viewport_bounds = (vb_x, vb_y, vb_w, vb_h)
                    gx0 = min(gx0, vb_x)
                    gy0 = min(gy0, vb_y)
                    gx1 = max(gx1, vb_x + vb_w)
                    gy1 = max(gy1, vb_y + vb_h)
                    _log.debug("SVG viewBox: (%s, %s, %s, %s)", vb_x, vb_y, vb_w, vb_h)
        except VECTOR_HANDLED_ERRORS:
            pass

        real_w = gx1 - gx0
        real_h = gy1 - gy0

        _log.debug("Global bounds: x=%.1f, y=%.1f, w=%.1f, h=%.1f", gx0, gy0, real_w, real_h)
        if real_w == 0:
            raise ValueError("Invalid geometry width (0)")

        if image_vectorizer_origin and svg_viewport_bounds is not None:
            vb_x, vb_y, vb_w, vb_h = svg_viewport_bounds
            self._last_image_vectorizer_bounds = box(
                vb_x - gx0,
                vb_y - gy0,
                vb_x + vb_w - gx0,
                vb_y + vb_h - gy0,
            )

        scale_factor = target_width_mm / real_w
        min_area_svg = max(0.0, (self.sampling_precision**2) / max(scale_factor**2, 1e-12) * 0.25)
        simplify_tol_svg = max(0.0, (self.sampling_precision / max(scale_factor, 1e-9)) * 0.5)
        # NOTE: a silent 'widen thin stroke to nozzle width' step (added in
        # PR #24 overhaul, 34a22dc) used to outward-buffer every sub-nozzle
        # stroke shape by ``0.5*(nozzle-stroke)`` with ``join_style='mitre',
        # mitre_limit=2.0``. On illustrated SVGs this made every fine contour
        # chunky and produced mitre spikes at sharp corners. Removed here
        # because sub-nozzle stroke handling belongs to the slicer/export
        # boundary, not the shared preview/mesh geometry stage.
        # 曾经的 "按 nozzle 宽度外扩细描边" 步骤（PR #24 overhaul 引入）会让细
        # 笔触整体变粗、尖角产生毛刺；这类打印兼容处理应放在切片/导出边界层
        # 而非预览/mesh 几何共用阶段，此处不再做。
        final_shapes = []
        for item in raw_shapes:
            shifted = affinity.translate(item["poly"], xoff=-gx0, yoff=-gy0)
            if simplify_tol_svg > 0.0:
                try:
                    shifted = shifted.simplify(simplify_tol_svg, preserve_topology=True)
                except VECTOR_HANDLED_ERRORS:
                    pass

            if not shifted.is_valid:
                shifted = make_valid(shifted)

            if shifted.is_empty or shifted.area <= min_area_svg:
                continue
            final_item = {"poly": shifted, "color": item["color"]}
            for key in (
                "source_kind",
                "same_color_stroke",
                "same_color_stroke_double_buffer",
                "stroke_width_svg",
            ):
                if key in item:
                    final_item[key] = item[key]
            final_shapes.append(final_item)

        return final_shapes, scale_factor, (gx0, gy0, real_w, real_h)

    # ── Geometry helpers ─────────────────────────────────────────────────

    @staticmethod
    def _extrude_geometry(geometry, height, z_offset, scale, extrude_cache=None):
        """Extrude 2D Shapely geometry to 3D trimesh objects."""
        meshes = []
        if geometry is None or geometry.is_empty:
            _log.debug(
                "Vector extrusion skipped empty geometry",
                extra={
                    "event": "vector_diag_extrude_skipped_empty",
                    "stage": "extrude_geometry",
                },
            )
            return meshes

        polys = geometry.geoms if hasattr(geometry, "geoms") else [geometry]

        for poly in polys:
            if poly.is_empty:
                _log.debug(
                    "Vector extrusion skipped empty polygon",
                    extra={
                        "event": "vector_diag_extrude_skipped_empty",
                        "stage": "extrude_geometry_part",
                    },
                )
                continue
            if not hasattr(poly, "exterior"):
                # Repair non-polygon geometry (LineString, Point, etc.)
                # by buffering into a Polygon before extrusion.
                # 修复非多边形几何（LineString/Point 等），buffer 成 Polygon 再挤出。
                try:
                    repaired = poly.buffer(0.01)
                    if hasattr(repaired, "geoms"):
                        for rp in repaired.geoms:
                            if hasattr(rp, "exterior") and not rp.is_empty:
                                poly = rp
                                break
                        else:
                            if hasattr(repaired, "exterior") and not repaired.is_empty:
                                poly = repaired
                            else:
                                _log.debug(
                                    "Vector extrusion skipped non-polygon geometry",
                                    extra={
                                        "event": "vector_diag_extrude_skipped_non_polygon",
                                        "geometry_type": getattr(poly, "geom_type", None),
                                    },
                                )
                                continue
                    elif hasattr(repaired, "exterior") and not repaired.is_empty:
                        poly = repaired
                    else:
                        _log.debug(
                            "Vector extrusion skipped non-polygon geometry",
                            extra={
                                "event": "vector_diag_extrude_skipped_non_polygon",
                                "geometry_type": getattr(poly, "geom_type", None),
                            },
                        )
                        continue
                except Exception:
                    _log.debug(
                        "Vector extrusion skipped non-polygon geometry",
                        extra={
                            "event": "vector_diag_extrude_skipped_non_polygon",
                            "geometry_type": getattr(poly, "geom_type", None),
                        },
                    )
                    continue
            try:
                cache_key = None
                cached_base = None
                if extrude_cache is not None:
                    # Key excludes height: cache unit-height (h=1) base mesh,
                    # then scale Z per call. Avoids re-triangulating the same
                    # polygon when it appears in multiple layers at different heights.
                    cache_key = (poly.wkb, round(float(scale), 8))
                    cached_base = extrude_cache.get(cache_key)

                if cached_base is None:
                    m_base = trimesh.creation.extrude_polygon(poly, height=1.0)
                    m_base.apply_scale([scale, scale, 1.0])
                    if extrude_cache is not None and cache_key is not None:
                        extrude_cache[cache_key] = m_base.copy()
                else:
                    m_base = cached_base

                m = m_base.copy()
                m.apply_scale([1.0, 1.0, float(height)])
                m.apply_translation([0, 0, z_offset])
                meshes.append(m)
            except VECTOR_HANDLED_ERRORS as e:
                _log.warning(
                    "Failed to extrude vector polygon",
                    extra={
                        "event": "vector_polygon_extrude_failed",
                        "error_type": type(e).__name__,
                        "error_message": str(e),
                        "geometry_type": getattr(poly, "geom_type", None),
                    },
                )
                continue

        return meshes

    @staticmethod
    def _fix_coordinates(mesh, svg_height_mm):
        """Flip Y-axis from SVG (Y-down) to printer (Y-up) coordinate system."""
        transform = np.eye(4)
        transform[1, 1] = -1
        mesh.apply_transform(transform)
        mesh.apply_translation([0, svg_height_mm, 0])
