"""Shared, revisioned selection-mask state for converter editing tools.

颜色工作站各选择工具共享的、带版本号的服务端选区 mask。
"""

from __future__ import annotations

import threading
import weakref
from typing import Any

import cv2
import numpy as np

from api.session_store import SessionStore
from api.visible_region_cache import (
    component_labels_for_color,
    component_labels_for_mask,
    component_metadata,
    component_union_mask,
    get_component_at,
    union_mask_contours,
)

SELECTION_MASK_KEY = "editor_selection_mask"
SELECTION_REVISION_KEY = "editor_selection_revision"
SELECTION_CONTENT_GENERATION_KEY = "editor_selection_content_generation"
SELECTION_REGION_PREFIX = "__editor_selection__:"

_LOCKS_GUARD = threading.Lock()
_LOCKS: weakref.WeakValueDictionary[str, threading.RLock] = weakref.WeakValueDictionary()


def selection_lock(session_id: str) -> threading.RLock:
    """Return the lock serialising selection revisions for one session."""
    with _LOCKS_GUARD:
        lock = _LOCKS.get(session_id)
        if lock is None:
            lock = threading.RLock()
            _LOCKS[session_id] = lock
        return lock


def get_selection_revision(session_data: dict[str, Any]) -> int:
    try:
        return max(0, int(session_data.get(SELECTION_REVISION_KEY) or 0))
    except (TypeError, ValueError):
        return 0


def get_selection_mask(
    session_data: dict[str, Any],
    shape: tuple[int, int],
) -> np.ndarray:
    """Return a copy of the current selection, or an empty mask for this image."""
    value = session_data.get(SELECTION_MASK_KEY)
    if not isinstance(value, np.ndarray) or value.shape != shape:
        return np.zeros(shape, dtype=bool)
    return np.asarray(value, dtype=bool).copy()


def persist_selection_mask(
    session_id: str,
    store: SessionStore,
    session_data: dict[str, Any],
    mask: np.ndarray,
    *,
    content_generation: int,
    revision: int | None = None,
) -> int:
    """Persist one authoritative selection and publish its compatibility token."""
    normalized = np.asarray(mask, dtype=bool).copy()
    next_revision = (
        get_selection_revision(session_data) + 1
        if revision is None
        else max(0, int(revision))
    )
    session_data[SELECTION_MASK_KEY] = normalized
    session_data[SELECTION_REVISION_KEY] = next_revision
    session_data[SELECTION_CONTENT_GENERATION_KEY] = int(content_generation)
    store.put(session_id, SELECTION_MASK_KEY, normalized)
    store.put(session_id, SELECTION_REVISION_KEY, next_revision)
    store.put(session_id, SELECTION_CONTENT_GENERATION_KEY, int(content_generation))

    # Existing recipe APIs consume region ids. Publish one synthetic region whose
    # mask is exactly the shared union, so old callers remain spatially precise.
    region_masks = session_data.get("selected_region_masks")
    if not isinstance(region_masks, dict):
        region_masks = {}
    for key in list(region_masks):
        if isinstance(key, str) and key.startswith(SELECTION_REGION_PREFIX):
            region_masks.pop(key, None)
    if np.any(normalized):
        region_masks[selection_region_id(next_revision)] = normalized
    session_data["selected_region_masks"] = region_masks
    store.put(session_id, "selected_region_masks", region_masks)
    return next_revision


def selection_region_id(revision: int) -> str:
    return f"{SELECTION_REGION_PREFIX}{int(revision)}"


def resolve_selection_mask(
    session_data: dict[str, Any],
    shape: tuple[int, int],
    expected_revision: int | None,
) -> np.ndarray:
    """Resolve a non-empty shared selection and reject stale content actions."""
    revision = get_selection_revision(session_data)
    if expected_revision is not None and int(expected_revision) != revision:
        raise ValueError(
            f"Selection revision changed (expected {expected_revision}, current {revision})."
        )
    mask = get_selection_mask(session_data, shape)
    if not np.any(mask):
        raise KeyError("No shared selection is active.")
    return mask


def mutate_point_toggle(
    component_cache: dict[str, Any],
    current: np.ndarray,
    x: int,
    y: int,
) -> np.ndarray:
    label, _component = get_component_at(component_cache, x, y)
    component = component_union_mask(component_cache, [label])
    next_mask = current.copy()
    if np.all(next_mask[component]):
        next_mask[component] = False
    else:
        next_mask[component] = True
    return next_mask


def mutate_same_color_toggle(
    component_cache: dict[str, Any],
    current: np.ndarray,
    *,
    x: int | None,
    y: int | None,
    color_hex: str | None,
) -> np.ndarray:
    resolved_hex = color_hex
    if not resolved_hex:
        if x is None or y is None:
            raise ValueError("Same-colour selection requires a colour or point.")
        _label, component = get_component_at(component_cache, x, y)
        resolved_hex = str(component["color_hex"])
    labels = component_labels_for_color(component_cache, resolved_hex)
    group_mask = component_union_mask(component_cache, labels)
    if not np.any(group_mask):
        raise KeyError(f"No visible components found for colour {resolved_hex}.")
    next_mask = current.copy()
    if np.all(next_mask[group_mask]):
        next_mask[group_mask] = False
    else:
        next_mask[group_mask] = True
    return next_mask


def rasterize_brush_stroke(
    shape: tuple[int, int],
    points: list[tuple[float, float]],
    radius: float,
) -> np.ndarray:
    """Rasterise a round, gap-free brush polyline into image pixel space."""
    if not points:
        raise ValueError("Brush stroke requires at least one point.")
    height, width = shape
    if height <= 0 or width <= 0:
        raise ValueError("Brush target has invalid dimensions.")
    # Keep sub-pixel precision: the frontend sends image-space stroke points
    # (floats) plus an image-space radius. Rounding every point to an integer
    # pixel before rasterising shifts the stroke by up to half a pixel, which
    # makes the hit area visibly smaller than the painted draft at small radii.
    # 保留亚像素精度：前端发的是图像空间浮点坐标和半径，提前取整会让笔画中心
    # 偏移最多半像素，小笔刷下命中范围明显小于笔迹显示。
    resolved_radius = max(0.5, min(float(radius), float(max(height, width))))
    canvas = np.zeros(shape, dtype=np.uint8)
    normalized = [
        (
            min(float(width - 1), max(0.0, float(x))),
            min(float(height - 1), max(0.0, float(y))),
        )
        for x, y in points
    ]
    # Diameter matches the frontend draft lineWidth (2 * image radius).
    thickness = max(1, int(round(resolved_radius * 2)))
    if len(normalized) == 1:
        center = (int(round(normalized[0][0])), int(round(normalized[0][1])))
        cv2.circle(canvas, center, int(round(resolved_radius)), 1, thickness=-1)
    else:
        for start, end in zip(normalized, normalized[1:], strict=False):
            pt1 = (int(round(start[0])), int(round(start[1])))
            pt2 = (int(round(end[0])), int(round(end[1])))
            cv2.line(canvas, pt1, pt2, 1, thickness=thickness, lineType=cv2.LINE_8)
        first = (int(round(normalized[0][0])), int(round(normalized[0][1])))
        last = (int(round(normalized[-1][0])), int(round(normalized[-1][1])))
        cv2.circle(canvas, first, int(round(resolved_radius)), 1, thickness=-1)
        cv2.circle(canvas, last, int(round(resolved_radius)), 1, thickness=-1)
    return canvas.astype(bool)


def mutate_brush_add(
    component_cache: dict[str, Any],
    current: np.ndarray,
    points: list[tuple[float, float]],
    radius: float,
) -> tuple[np.ndarray, int]:
    stroke_mask = rasterize_brush_stroke(current.shape, points, radius)
    labels = component_labels_for_mask(component_cache, stroke_mask)
    if not labels:
        return current.copy(), 0
    next_mask = current | component_union_mask(component_cache, labels)
    return next_mask, len(labels)


def selection_summary(
    session_data: dict[str, Any],
    component_cache: dict[str, Any],
    matched_rgb: np.ndarray,
) -> dict[str, Any]:
    """Build the frontend selection document from the authoritative union mask."""
    shape = (int(component_cache["height"]), int(component_cache["width"]))
    mask = get_selection_mask(session_data, shape)
    revision = get_selection_revision(session_data)
    labels = component_labels_for_mask(component_cache, mask)
    metadata = component_metadata(component_cache, labels)
    pixels = int(np.count_nonzero(mask))
    colors: list[str] = []
    if pixels:
        rgb = np.asarray(matched_rgb, dtype=np.uint8)[mask, :3]
        unique = np.unique(rgb, axis=0)
        colors = [f"#{int(r):02x}{int(g):02x}{int(b):02x}" for r, g, b in unique]
    return {
        "selection_revision": revision,
        "content_revision": int(component_cache["generation"]),
        "selected_pixel_count": pixels,
        "selected_component_count": len(metadata),
        "selected_color_hexes": colors,
        "region_ids": [selection_region_id(revision)] if pixels else [],
        "components": metadata,
        "contours": union_mask_contours(component_cache, mask) if pixels else [],
    }
