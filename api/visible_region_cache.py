"""Visible-colour connected-component cache for click selection.

用于点击选区的当前可见颜色连通块缓存。
"""

from __future__ import annotations

import threading
import weakref
import time
from collections import defaultdict
from typing import Any

import cv2
import numpy as np

from api.session_store import SessionStore
from api.structured_logging import get_logger

VISIBLE_REGION_CACHE_KEY = "visible_region_component_cache"
VISIBLE_REGION_GENERATION_KEY = "visible_region_cache_generation"

log = get_logger(__name__)
_BUILD_LOCKS_GUARD = threading.Lock()
_BUILD_LOCKS: weakref.WeakValueDictionary[str, threading.RLock] = weakref.WeakValueDictionary()


def get_visible_region_cache_build_lock(session_id: str) -> threading.RLock:
    """Return a per-session build lock for visible-region caches.
    返回可见区域缓存构建的 per-session 锁。
    """
    with _BUILD_LOCKS_GUARD:
        lock = _BUILD_LOCKS.get(session_id)
        if lock is None:
            lock = threading.RLock()
            _BUILD_LOCKS[session_id] = lock
        return lock


def get_visible_region_generation(session_data: dict[str, Any]) -> int:
    """Return the current visible-region cache generation.
    返回当前可见区域缓存代次。
    """
    try:
        return int(session_data.get(VISIBLE_REGION_GENERATION_KEY) or 0)
    except (TypeError, ValueError):
        return 0


def invalidate_visible_region_cache(
    session_id: str,
    store: SessionStore,
    session_data: dict[str, Any],
) -> None:
    """Invalidate cached visible connected components after RGB changes.
    在 matched_rgb 发生变化后使可见连通块缓存失效。
    """
    generation = get_visible_region_generation(session_data) + 1
    session_data[VISIBLE_REGION_GENERATION_KEY] = generation
    session_data[VISIBLE_REGION_CACHE_KEY] = None
    store.put(session_id, VISIBLE_REGION_GENERATION_KEY, generation)
    store.put(session_id, VISIBLE_REGION_CACHE_KEY, None)


def get_valid_visible_region_cache(
    session_data: dict[str, Any],
) -> dict[str, Any] | None:
    """Return a valid component cache for the current generation, if present.
    若当前代次已有可用分块缓存，则返回它。
    """
    cache = session_data.get(VISIBLE_REGION_CACHE_KEY)
    if not isinstance(cache, dict):
        return None
    if int(cache.get("generation", -1)) != get_visible_region_generation(session_data):
        return None
    label_map = cache.get("label_map")
    components = cache.get("components")
    if not isinstance(label_map, np.ndarray) or not isinstance(components, dict):
        return None
    return cache


def build_visible_region_component_cache(
    preview_cache: dict[str, Any],
    *,
    generation: int,
) -> dict[str, Any]:
    """Build connected components for the current visible matched RGB image.
    为当前可见 matched_rgb 图构建全图连通块索引。
    """
    started_at = time.perf_counter()
    matched_rgb = preview_cache.get("matched_rgb")
    mask_solid = preview_cache.get("mask_solid")
    if matched_rgb is None or mask_solid is None:
        raise ValueError("Preview cache missing matched_rgb or mask_solid.")

    matched_arr = np.asarray(matched_rgb)
    if matched_arr.ndim != 3 or matched_arr.shape[2] < 3:
        raise ValueError("Preview cache matched_rgb has invalid shape.")
    visible_rgb = np.asarray(matched_arr[:, :, :3], dtype=np.uint8)
    height, width = visible_rgb.shape[:2]

    solid = np.asarray(mask_solid, dtype=bool)
    if solid.shape != (height, width):
        raise ValueError(
            f"mask_solid shape {solid.shape} does not match matched_rgb {height}x{width}."
        )

    pixel_scale = _resolve_pixel_scale(preview_cache, width)
    codes = (
        (visible_rgb[:, :, 0].astype(np.uint32) << 16)
        | (visible_rgb[:, :, 1].astype(np.uint32) << 8)
        | visible_rgb[:, :, 2].astype(np.uint32)
    )
    solid_codes = codes[solid]
    unique_codes = np.unique(solid_codes) if solid_codes.size else np.array([], dtype=np.uint32)

    label_map = np.zeros((height, width), dtype=np.uint32)
    components: dict[int, dict[str, Any]] = {}
    next_label = 1

    for code_value in unique_codes:
        code = int(code_value)
        color_mask = ((codes == code_value) & solid).astype(np.uint8)
        if not np.any(color_mask):
            continue
        num_labels, local_labels, stats, _centroids = cv2.connectedComponentsWithStats(
            color_mask,
            connectivity=4,
        )
        color_hex = _code_to_hex(code)
        for local_label in range(1, int(num_labels)):
            area = int(stats[local_label, cv2.CC_STAT_AREA])
            if area <= 0:
                continue
            x0 = int(stats[local_label, cv2.CC_STAT_LEFT])
            y0 = int(stats[local_label, cv2.CC_STAT_TOP])
            bbox_w = int(stats[local_label, cv2.CC_STAT_WIDTH])
            bbox_h = int(stats[local_label, cv2.CC_STAT_HEIGHT])
            if bbox_w <= 0 or bbox_h <= 0:
                continue

            crop_labels = local_labels[y0 : y0 + bbox_h, x0 : x0 + bbox_w]
            crop_mask = crop_labels == local_label
            label_map[y0 : y0 + bbox_h, x0 : x0 + bbox_w][crop_mask] = next_label
            anchor_y, anchor_x = np.argwhere(crop_mask)[0]

            bbox = [x0, y0, bbox_w, bbox_h]
            region_id = _build_region_id(
                generation=generation,
                color_hex=color_hex,
                pixel_count=area,
                bbox=bbox,
            )
            components[next_label] = {
                "region_id": region_id,
                "color_hex": color_hex,
                "pixel_count": area,
                "bbox": bbox,
                "anchor": [x0 + int(anchor_x), y0 + int(anchor_y)],
                "contours": None,
            }
            next_label += 1

    elapsed_ms = (time.perf_counter() - started_at) * 1000
    log.debug(
        "visible-region component cache built",
        extra={
            "event": "visible_region_component_cache_built",
            "generation": generation,
            "width": width,
            "height": height,
            "component_count": len(components),
            "color_count": int(len(unique_codes)),
            "elapsed_ms": round(elapsed_ms, 2),
        },
    )
    return {
        "generation": int(generation),
        "width": int(width),
        "height": int(height),
        "pixel_scale": float(pixel_scale),
        "label_map": label_map,
        "components": components,
    }


def store_visible_region_component_cache(
    session_id: str,
    store: SessionStore,
    cache: dict[str, Any],
) -> None:
    """Persist the visible-region component cache in session memory.
    将可见区域分块缓存写入 session 内存。
    """
    store.put(session_id, VISIBLE_REGION_CACHE_KEY, cache)


def schedule_visible_region_cache_prewarm(
    session_id: str,
    store: SessionStore,
    preview_cache: dict[str, Any] | None,
    *,
    generation: int,
) -> None:
    """Build the visible-region cache in a short-lived background thread.
    用短生命周期后台线程预热可见区域分块缓存。
    """
    if preview_cache is None:
        return

    def _worker() -> None:
        try:
            with get_visible_region_cache_build_lock(session_id):
                latest_before = store.get(session_id)
                if latest_before is None:
                    return
                cached = get_valid_visible_region_cache(latest_before)
                if cached is not None and int(cached.get("generation", -1)) == int(generation):
                    return
                component_cache = build_visible_region_component_cache(
                    preview_cache,
                    generation=generation,
                )
                latest = store.get(session_id)
                if latest is None:
                    return
                if get_visible_region_generation(latest) != generation:
                    return
                store_visible_region_component_cache(session_id, store, component_cache)
                latest[VISIBLE_REGION_CACHE_KEY] = component_cache
        except Exception as exc:
            log.debug(
                "visible-region cache prewarm skipped",
                extra={
                    "event": "visible_region_component_cache_prewarm_failed",
                    "session_id": session_id,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                },
            )

    thread = threading.Thread(
        target=_worker,
        name=f"visible-region-prewarm-{session_id[:8]}",
        daemon=True,
    )
    thread.start()


def get_component_at(
    component_cache: dict[str, Any],
    x: int,
    y: int,
) -> tuple[int, dict[str, Any]]:
    """Return ``(label, component)`` for a clicked pixel.
    返回点击像素对应的 ``(label, component)``。
    """
    label_map = component_cache["label_map"]
    height, width = label_map.shape[:2]
    if not (0 <= x < width and 0 <= y < height):
        raise IndexError(f"Coordinates ({x}, {y}) out of bounds for image {width}x{height}.")
    label = int(label_map[y, x])
    if label <= 0:
        raise KeyError("Clicked on background area.")
    component = component_cache["components"].get(label)
    if not isinstance(component, dict):
        raise KeyError(f"Component label {label} is missing.")
    return label, component


def detect_single_component_at_point(
    preview_cache: dict[str, Any],
    *,
    generation: int,
    x: int,
    y: int,
) -> dict[str, Any]:
    """Build a minimal cache holding only the clicked pixel's connected component.
    构建只含点击像素所在连通块的最小缓存（点击懒计算路径）。

    A full :func:`build_visible_region_component_cache` run scans every unique
    colour across the whole image (one ``connectedComponentsWithStats`` per
    colour), which can take ~1s on large previews. Click selection only needs
    the single component under the cursor, so this path labels just the clicked
    colour once (~300ms class) and returns a cache that contains that one
    component. The full index continues to build in the background prewarm for
    later box-select / select-all / restore flows.
    全量构建会对每种颜色做一次全图扫描，大图可耗时约 1s；点击选择只需要光标
    下那一个连通块，因此此路径只对点击色做一次标注（约 300ms 级），返回仅含
    该块的缓存。全图索引仍由后台预热构建，供后续框选/全选/恢复使用。

    Args:
        preview_cache: Preview cache with ``matched_rgb``/``mask_solid``. (含 matched_rgb/mask_solid 的预览缓存)
        generation: Visible-region cache generation. (可见区域缓存代次)
        x: Click x in pixel coords. (像素坐标 x)
        y: Click y in pixel coords. (像素坐标 y)

    Returns:
        A component cache dict shaped like ``build_visible_region_component_cache``
        but containing only the clicked component.
        结构与全量缓存一致、但只含点击连通块的缓存。

    Raises:
        ValueError: Preview cache missing fields or click out of bounds. (缓存缺字段或点击越界)
        KeyError: Clicked on background. (点击在背景上)
    """
    matched_rgb = preview_cache.get("matched_rgb")
    mask_solid = preview_cache.get("mask_solid")
    if matched_rgb is None or mask_solid is None:
        raise ValueError("Preview cache missing matched_rgb or mask_solid.")

    matched_arr = np.asarray(matched_rgb)
    if matched_arr.ndim != 3 or matched_arr.shape[2] < 3:
        raise ValueError("Preview cache matched_rgb has invalid shape.")
    visible_rgb = np.asarray(matched_arr[:, :, :3], dtype=np.uint8)
    height, width = visible_rgb.shape[:2]
    if not (0 <= x < width and 0 <= y < height):
        raise ValueError(f"Coordinates ({x}, {y}) out of bounds for image {width}x{height}.")

    solid = np.asarray(mask_solid, dtype=bool)
    if solid.shape != (height, width):
        raise ValueError(
            f"mask_solid shape {solid.shape} does not match matched_rgb {height}x{width}."
        )
    if not bool(solid[y, x]):
        raise KeyError("Clicked on background area.")

    pixel_scale = _resolve_pixel_scale(preview_cache, width)

    # Label only the clicked colour across the whole image, then keep just the
    # connected component that contains the clicked pixel.
    # 只对点击色做整图标注，再只保留包含点击像素的那个连通块。
    target_rgb = visible_rgb[y, x]
    color_mask = (np.all(visible_rgb == target_rgb, axis=-1) & solid).astype(np.uint8)
    num_labels, local_labels, stats, _centroids = cv2.connectedComponentsWithStats(
        color_mask,
        connectivity=4,
    )
    clicked_local_label = int(local_labels[y, x])
    if clicked_local_label <= 0:
        raise KeyError("Clicked on background area.")

    area = int(stats[clicked_local_label, cv2.CC_STAT_AREA])
    if area <= 0:
        raise KeyError("Clicked on background area.")
    x0 = int(stats[clicked_local_label, cv2.CC_STAT_LEFT])
    y0 = int(stats[clicked_local_label, cv2.CC_STAT_TOP])
    bbox_w = int(stats[clicked_local_label, cv2.CC_STAT_WIDTH])
    bbox_h = int(stats[clicked_local_label, cv2.CC_STAT_HEIGHT])

    code = (
        (int(target_rgb[0]) << 16)
        | (int(target_rgb[1]) << 8)
        | int(target_rgb[2])
    )
    color_hex = _code_to_hex(code)

    label_map = np.zeros((height, width), dtype=np.uint32)
    component_label = 1
    crop_labels = local_labels[y0 : y0 + bbox_h, x0 : x0 + bbox_w]
    crop_mask = crop_labels == clicked_local_label
    label_map[y0 : y0 + bbox_h, x0 : x0 + bbox_w][crop_mask] = component_label
    anchor_y, anchor_x = np.argwhere(crop_mask)[0]

    bbox = [x0, y0, bbox_w, bbox_h]
    region_id = _build_region_id(
        generation=generation,
        color_hex=color_hex,
        pixel_count=area,
        bbox=bbox,
    )
    components: dict[int, dict[str, Any]] = {
        component_label: {
            "region_id": region_id,
            "color_hex": color_hex,
            "pixel_count": area,
            "bbox": bbox,
            "anchor": [x0 + int(anchor_x), y0 + int(anchor_y)],
            "contours": None,
        }
    }
    return {
        "generation": int(generation),
        "width": int(width),
        "height": int(height),
        "pixel_scale": float(pixel_scale),
        "label_map": label_map,
        "components": components,
        # Marker so callers can tell this is a partial (click-only) cache and
        # avoid persisting it as the authoritative full index.
        # 标记这是只含点击块的部分缓存，调用方不应把它当作全图索引持久化。
        "partial": True,
    }


def component_mask(component_cache: dict[str, Any], label: int) -> np.ndarray:
    """Return a boolean mask for one cached connected component.
    返回某个缓存连通块的布尔 mask。
    """
    label_map = component_cache["label_map"]
    return np.asarray(label_map == np.uint32(label), dtype=bool)


def component_labels_for_color(
    component_cache: dict[str, Any],
    color_hex: str,
) -> list[int]:
    """Return every component label whose visible colour matches ``color_hex``."""
    normalized = str(color_hex).replace("#", "").lower()
    return [
        int(label)
        for label, component in component_cache["components"].items()
        if str(component.get("color_hex", "")).replace("#", "").lower()
        == normalized
    ]


def component_labels_for_mask(
    component_cache: dict[str, Any],
    hit_mask: np.ndarray,
) -> list[int]:
    """Return unique positive component labels touched by a boolean mask."""
    label_map = np.asarray(component_cache["label_map"])
    mask = np.asarray(hit_mask, dtype=bool)
    if mask.shape != label_map.shape:
        raise ValueError(
            f"Hit mask shape {mask.shape} does not match label map {label_map.shape}."
        )
    labels = np.unique(label_map[mask])
    return [int(label) for label in labels if int(label) > 0]


def component_union_mask(
    component_cache: dict[str, Any],
    labels: list[int] | set[int] | tuple[int, ...],
) -> np.ndarray:
    """Return the union mask for component labels without per-label scans."""
    label_map = np.asarray(component_cache["label_map"])
    normalized = np.asarray(sorted({int(label) for label in labels if int(label) > 0}))
    if normalized.size == 0:
        return np.zeros(label_map.shape, dtype=bool)
    return np.isin(label_map, normalized)


def component_metadata(
    component_cache: dict[str, Any],
    labels: list[int] | set[int] | tuple[int, ...],
) -> list[dict[str, Any]]:
    """Return serialisable metadata for selected component labels."""
    selected: list[dict[str, Any]] = []
    for label in sorted({int(value) for value in labels if int(value) > 0}):
        component = component_cache["components"].get(label)
        if not isinstance(component, dict):
            continue
        selected.append(
            {
                "label": label,
                "region_id": str(component["region_id"]),
                "color_hex": str(component["color_hex"]),
                "pixel_count": int(component["pixel_count"]),
                "bbox": [int(value) for value in component["bbox"]],
                "anchor": [int(value) for value in component.get("anchor", component["bbox"][:2])],
            }
        )
    return selected


def union_mask_contours(
    component_cache: dict[str, Any],
    mask: np.ndarray,
) -> list[list[list[float]]]:
    """Trace the exact external and hole boundaries of a union selection mask."""
    normalized = np.asarray(mask, dtype=bool)
    expected = (int(component_cache["height"]), int(component_cache["width"]))
    if normalized.shape != expected:
        raise ValueError(
            f"Selection mask shape {normalized.shape} does not match cache {expected}."
        )
    return _component_boundary_contours_to_world(
        normalized,
        origin_x=0,
        origin_y=0,
        image_height=expected[0],
        pixel_scale=float(component_cache["pixel_scale"]),
    )


def ensure_component_contours(
    component_cache: dict[str, Any],
    label: int,
) -> list[list[list[float]]]:
    """Return contours for one component, computing them once if needed.
    返回某个连通块的轮廓；缺失时只计算一次。
    """
    component = component_cache["components"].get(label)
    if not isinstance(component, dict):
        raise KeyError(f"Component label {label} is missing.")
    contours = component.get("contours")
    if contours:
        return contours

    bbox = component.get("bbox")
    if not isinstance(bbox, list) or len(bbox) != 4:
        raise KeyError(f"Component label {label} has no valid bbox.")
    x0, y0, bbox_w, bbox_h = (int(value) for value in bbox)
    if bbox_w <= 0 or bbox_h <= 0:
        raise KeyError(f"Component label {label} has an empty bbox.")

    label_map = component_cache["label_map"]
    crop_labels = label_map[y0 : y0 + bbox_h, x0 : x0 + bbox_w]
    crop_mask = crop_labels == np.uint32(label)
    contours = _component_boundary_contours_to_world(
        crop_mask,
        origin_x=x0,
        origin_y=y0,
        image_height=int(component_cache["height"]),
        pixel_scale=float(component_cache["pixel_scale"]),
    )
    component["contours"] = contours
    return contours


def _resolve_pixel_scale(preview_cache: dict[str, Any], image_width: int) -> float:
    try:
        target_w = int(preview_cache.get("target_w") or image_width)
    except (TypeError, ValueError):
        target_w = image_width
    try:
        width_mm = (
            float(preview_cache.get("target_width_mm"))
            if preview_cache.get("target_width_mm") is not None
            else float(target_w)
        )
    except (TypeError, ValueError):
        width_mm = float(target_w)
    if target_w <= 0:
        target_w = image_width
    if width_mm <= 0:
        width_mm = float(target_w)
    return float(width_mm / max(1, target_w))


def _component_boundary_contours_to_world(
    crop_mask: np.ndarray,
    *,
    origin_x: int,
    origin_y: int,
    image_height: int,
    pixel_scale: float,
) -> list[list[list[float]]]:
    """Trace exact pixel-grid boundaries for a component mask.
    沿像素网格追踪组件真实边界。

    OpenCV contours report points on pixel centres, so using them directly
    shrinks an N-pixel rectangle to roughly N-1 pixels.  Here each solid
    pixel contributes only the edges that touch background/outside pixels,
    producing boundaries on pixel *outer* edges.  If boundary tracing fails,
    callers must treat that as a missing contour instead of showing the bbox
    as a fake selection shape.
    OpenCV 轮廓点落在像素中心，会把 N 像素矩形缩成约 N-1 像素。这里
    只收集实心像素与背景/外部相邻的边，边界落在像素外边缘。若轮廓追踪
    失败，调用方应视为缺失轮廓，不能用 bbox 冒充选区形状。
    """
    mask = np.asarray(crop_mask, dtype=bool)
    height, width = mask.shape[:2]
    if height <= 0 or width <= 0 or not np.any(mask):
        return []

    edges: dict[tuple[int, int], list[tuple[int, int]]] = defaultdict(list)
    padded = np.pad(mask, ((1, 1), (1, 1)), mode="constant", constant_values=False)
    top_edges = mask & ~padded[:-2, 1:-1]
    right_edges = mask & ~padded[1:-1, 2:]
    bottom_edges = mask & ~padded[2:, 1:-1]
    left_edges = mask & ~padded[1:-1, :-2]
    _append_directed_grid_edges(edges, top_edges, 0, 0, 1, 0)
    _append_directed_grid_edges(edges, right_edges, 1, 0, 1, 1)
    _append_directed_grid_edges(edges, bottom_edges, 1, 1, 0, 1)
    _append_directed_grid_edges(edges, left_edges, 0, 1, 0, 0)

    loops: list[list[tuple[int, int]]] = []
    while edges:
        start = min(edges)
        loop = [start]
        current = start
        guard = 0
        while True:
            next_values = edges.get(current)
            if not next_values:
                break
            next_point = next_values.pop()
            if not next_values:
                edges.pop(current, None)
            current = next_point
            guard += 1
            if current == start:
                break
            loop.append(current)
            if guard > (height * width * 8 + 16):
                break
        simplified = _simplify_grid_loop(loop)
        if len(simplified) >= 3:
            loops.append(simplified)

    if not loops:
        return []

    return [
        [
            [
                float((origin_x + x) * pixel_scale),
                float((image_height - (origin_y + y)) * pixel_scale),
            ]
            for x, y in loop
        ]
        for loop in loops
    ]


def _append_directed_grid_edges(
    edges: dict[tuple[int, int], list[tuple[int, int]]],
    edge_mask: np.ndarray,
    start_dx: int,
    start_dy: int,
    end_dx: int,
    end_dy: int,
) -> None:
    ys, xs = np.where(edge_mask)
    for y_raw, x_raw in zip(ys, xs, strict=False):
        x = int(x_raw)
        y = int(y_raw)
        edges[(x + start_dx, y + start_dy)].append((x + end_dx, y + end_dy))


def _simplify_grid_loop(loop: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if len(loop) < 3:
        return loop
    simplified: list[tuple[int, int]] = []
    for point in loop:
        if simplified and simplified[-1] == point:
            continue
        simplified.append(point)
    changed = True
    while changed and len(simplified) >= 3:
        changed = False
        next_points: list[tuple[int, int]] = []
        count = len(simplified)
        for idx, point in enumerate(simplified):
            prev_point = simplified[(idx - 1) % count]
            next_point = simplified[(idx + 1) % count]
            if _are_collinear(prev_point, point, next_point):
                changed = True
                continue
            next_points.append(point)
        simplified = next_points
    return simplified


def _are_collinear(
    a: tuple[int, int],
    b: tuple[int, int],
    c: tuple[int, int],
) -> bool:
    return (b[0] - a[0]) * (c[1] - b[1]) == (b[1] - a[1]) * (c[0] - b[0])


def _build_region_id(
    *,
    generation: int,
    color_hex: str,
    pixel_count: int,
    bbox: list[int],
) -> str:
    # The cache-local numeric label depends on component enumeration order and
    # differs between click-lazy and full-index builds. Geometry + colour is the
    # stable identity the frontend can safely reconcile without visual jumps.
    return (
        f"region-{generation}:{color_hex}:"
        f"{pixel_count}:{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}"
    )


def _code_to_hex(code: int) -> str:
    r = (code >> 16) & 0xFF
    g = (code >> 8) & 0xFF
    b = code & 0xFF
    return f"#{r:02x}{g:02x}{b:02x}"
