"""Shared, revisioned selection-mask state for converter editing tools.

颜色工作站各选择工具共享的、带版本号的服务端选区 mask。
"""

from __future__ import annotations

import threading
import weakref
from typing import Any, Callable

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
from core.color_similarity import colors_within_delta_e, parse_hex_color

SELECTION_MASK_KEY = "editor_selection_mask"
SELECTION_REVISION_KEY = "editor_selection_revision"
SELECTION_CONTENT_GENERATION_KEY = "editor_selection_content_generation"
SELECTION_REGION_PREFIX = "__editor_selection__:"

# Session key snapshotting the per-region masks captured when recipe overrides
# were applied. It lives beside the selection keys because these snapshots are
# what /generate falls back to once the synthetic __editor_selection__:<rev>
# entries above have been pruned by later selection gestures.
# 会话键：apply 配方覆盖时对所用区域掩码做快照。放在选区键旁边是因为：
# 上面的 __editor_selection__:<rev> 合成条目会随后续选区手势被清理，
# 生成端在实时选区缺失时回退到这份快照。
RECIPE_OVERRIDE_APPLIED_MASKS_KEY = "recipe_override_applied_masks"

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


def sync_selection_content_generation(
    session_id: str,
    store: SessionStore,
    session_data: dict[str, Any],
    content_generation: int,
) -> None:
    """Bind the current selection to a newly committed visible-content generation.
    将当前选区绑定到刚提交的可见内容版本。

    Geometry-preserving edits such as global colour replacement keep the
    selection pixels valid, but the next selection request must use the new
    visible-content revision. This helper updates only that binding; it does
    not create a new selection revision or alter the mask.
    几何不变的编辑（例如全局换色）仍可复用选区像素，但下一次选区请求必须
    携带新的可见内容版本。该辅助函数只更新绑定，不创建新的选区版本，也不
    修改选区掩码。
    """
    normalized = int(content_generation)
    session_data[SELECTION_CONTENT_GENERATION_KEY] = normalized
    store.put(session_id, SELECTION_CONTENT_GENERATION_KEY, normalized)


def resolve_recipe_override_masks(
    session_data: dict[str, Any],
    recipe_overrides: list[dict[str, Any]] | None,
    shape: tuple[int, int],
    *,
    legacy_fallback: Callable[[str], np.ndarray | None] | None = None,
) -> dict[str, np.ndarray]:
    """Resolve every recipe override to its committed spatial mask.
    将每个区域配方覆盖解析为其已提交的空间掩码。

    Sessions with ``recipe_override_applied_masks`` use the apply-time
    snapshots exclusively. Older sessions may use their live region map and an
    explicit legacy fallback (for example select-all colour recovery). Missing,
    empty, or shape-mismatched masks are rejected instead of silently widening
    an override to the whole image.
    含有 ``recipe_override_applied_masks`` 的会话只能使用 apply 时快照；旧会话
    才能使用实时区域映射和显式兼容回退（例如全选颜色恢复）。缺失、空掩码或
    形状不一致时直接拒绝，不能静默扩大成全图覆盖。

    Args:
        session_data: Session state containing live and/or committed masks.
            包含实时及/或已提交掩码的会话状态。
        recipe_overrides: Stored recipe override entries.
            已保存的区域配方覆盖条目。
        shape: Expected image mask shape ``(height, width)``.
            期望的图像掩码形状 ``(高, 宽)``。
        legacy_fallback: Optional resolver for pre-snapshot sessions.
            旧会话可选的兼容解析器。

    Returns:
        dict[str, np.ndarray]: Independent boolean masks keyed by region id.
            按区域 ID 返回相互独立的布尔掩码。

    Raises:
        ValueError: If a declared override cannot be resolved safely.
            无法安全解析声明的覆盖时抛出。
    """
    expected_shape = (int(shape[0]), int(shape[1]))
    if expected_shape[0] <= 0 or expected_shape[1] <= 0:
        raise ValueError("Recipe override mask shape is invalid")
    overrides = recipe_overrides or []
    if not overrides:
        return {}

    live_masks = session_data.get("selected_region_masks")
    if not isinstance(live_masks, dict):
        live_masks = {}
    snapshots = session_data.get(RECIPE_OVERRIDE_APPLIED_MASKS_KEY)
    has_snapshot_capability = RECIPE_OVERRIDE_APPLIED_MASKS_KEY in session_data
    if not isinstance(snapshots, dict):
        snapshots = {}

    resolved: dict[str, np.ndarray] = {}
    for item in overrides:
        if not isinstance(item, dict):
            raise ValueError("Recipe override entry is invalid")
        region_id = str(item.get("region_id") or "")
        if not region_id:
            raise ValueError("Recipe override region id is missing")

        mask: np.ndarray | None
        if has_snapshot_capability:
            mask = unpack_applied_region_mask(
                snapshots.get(region_id),
                expected_shape,
            )
        else:
            candidate = live_masks.get(region_id)
            mask = (
                np.asarray(candidate, dtype=bool).copy()
                if isinstance(candidate, np.ndarray)
                else None
            )
            if mask is None and legacy_fallback is not None:
                mask = legacy_fallback(region_id)
                if mask is not None:
                    mask = np.asarray(mask, dtype=bool).copy()

        if (
            mask is None
            or mask.shape != expected_shape
            or mask.ndim != 2
            or not np.any(mask)
        ):
            raise ValueError(
                f"Recipe override mask is missing or invalid for region {region_id}"
            )
        resolved[region_id] = np.ascontiguousarray(mask, dtype=bool)
    return resolved


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


def pack_applied_region_mask(mask: np.ndarray) -> dict[str, object]:
    """Pack one boolean region mask for compact session/history storage.

    Applied-override masks live in session state and are deep-copied into
    every replacement-history checkpoint; storing raw ``H×W`` booleans makes
    that footprint grow with pixels × overrides × history depth. Bit-packing
    keeps the same information in ``ceil(H×W / 8)`` bytes while remaining
    JSONB-safe through the session value codec.

    已应用覆盖的掩码存放在会话状态里，并会被每份替换历史 checkpoint 深拷
    贝；直接存 H×W 布尔数组会让内存随 像素数×覆盖数×历史深度 放大。位压
    缩用 ceil(H×W/8) 字节保存同样信息，且经会话值编解码器保持 JSONB 安全。

    Args:
        mask (np.ndarray): Boolean ``(height, width)`` region mask.
            (布尔 (高, 宽) 区域掩码)

    Returns:
        dict[str, object]: ``{"shape": [height, width], "packed": uint8}``.
        ({"shape": [高, 宽], "packed": uint8 数组})
    """
    normalized = np.asarray(mask, dtype=bool)
    flat_bits = np.packbits(normalized.reshape(-1))
    return {
        "shape": [int(normalized.shape[0]), int(normalized.shape[1])],
        "packed": np.ascontiguousarray(flat_bits, dtype=np.uint8),
    }


def unpack_applied_region_mask(
    value: object,
    shape: tuple[int, int] | None = None,
) -> np.ndarray | None:
    """Restore a boolean mask from a snapshot entry (packed or legacy raw).

    Sessions created before bit-packing shipped still hold plain boolean
    arrays under the same key; accepting both formats lets a rolling deploy
    keep older sessions generatable without a migration step. Invalid entries
    (wrong shape, wrong dtype/length, or all-air masks) return ``None`` so
    callers can fall back deterministically.

    位压缩上线前创建的会话在同一键下仍是裸布尔数组；同时接受两种格式可让
    滚动发布期间旧会话无需迁移即可继续生成。非法条目（形状不符、dtype/
    长度错误或全空掩码）返回 None，让调用方可以确定性回退。

    Args:
        value (object): Snapshot entry — packed dict or legacy bool ndarray.
            (快照条目：打包 dict 或旧版布尔数组)
        shape (tuple[int, int] | None): Optional expected ``(height, width)``.
            (可选的期望 (高, 宽))

    Returns:
        np.ndarray | None: Boolean mask copy matching ``shape``, else ``None``.
        (与 shape 匹配的布尔掩码副本；否则为 None)
    """
    if isinstance(value, np.ndarray):
        mask = np.asarray(value, dtype=bool).copy()
    elif isinstance(value, dict):
        packed = value.get("packed")
        stored_shape = value.get("shape")
        if (
            not isinstance(packed, np.ndarray)
            or not isinstance(stored_shape, (list, tuple))
            or len(stored_shape) != 2
        ):
            return None
        try:
            height = int(stored_shape[0])
            width = int(stored_shape[1])
        except (TypeError, ValueError):
            return None
        if height <= 0 or width <= 0:
            return None
        expected_bytes = (height * width + 7) // 8
        packed_arr = np.asarray(packed)
        if packed_arr.dtype != np.uint8 or packed_arr.size != expected_bytes:
            return None
        bits = np.unpackbits(np.ascontiguousarray(packed_arr, dtype=np.uint8))
        mask = bits[: height * width].reshape(height, width).astype(bool)
    else:
        return None
    if shape is not None and mask.shape != tuple(int(dim) for dim in shape):
        return None
    if not np.any(mask):
        return None
    return mask


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


def _reference_color_hex(
    component_cache: dict[str, Any],
    x: int | None,
    y: int | None,
    color_hex: str | None,
) -> str:
    """Use the explicit colour, else the visible colour of the clicked block."""
    if color_hex:
        return color_hex
    if x is None or y is None:
        raise ValueError("Colour selection requires a colour or point.")
    _label, component = get_component_at(component_cache, x, y)
    return str(component["color_hex"])


def _toggle_component_group(
    component_cache: dict[str, Any],
    current: np.ndarray,
    labels: list[int],
    reference_hex: str,
) -> np.ndarray:
    """Deselect the group if it is fully selected, otherwise add it."""
    group_mask = component_union_mask(component_cache, labels)
    if not np.any(group_mask):
        raise KeyError(f"No visible components found for colour {reference_hex}.")
    next_mask = current.copy()
    next_mask[group_mask] = not bool(np.all(next_mask[group_mask]))
    return next_mask


def mutate_same_color_toggle(
    component_cache: dict[str, Any],
    current: np.ndarray,
    *,
    x: int | None,
    y: int | None,
    color_hex: str | None,
) -> np.ndarray:
    reference_hex = _reference_color_hex(component_cache, x, y, color_hex)
    labels = component_labels_for_color(component_cache, reference_hex)
    return _toggle_component_group(component_cache, current, labels, reference_hex)


def _labels_within_delta_e(
    component_cache: dict[str, Any],
    reference_hex: str,
    max_delta_e00: float,
) -> list[int]:
    """Labels of visible blocks whose colour is within the ΔE00 tolerance."""
    labels_by_hex: dict[str, list[int]] = {}
    for label, component in component_cache["components"].items():
        labels_by_hex.setdefault(str(component["color_hex"]), []).append(int(label))
    hexes = list(labels_by_hex)
    if not hexes:
        return []
    candidate_rgb = np.asarray([parse_hex_color(value) for value in hexes], dtype=np.uint8)
    within = colors_within_delta_e(parse_hex_color(reference_hex), candidate_rgb, max_delta_e00)
    return [label for value, hit in zip(hexes, within, strict=True) if hit for label in labels_by_hex[value]]


def mutate_color_range_toggle(
    component_cache: dict[str, Any],
    current: np.ndarray,
    *,
    x: int | None,
    y: int | None,
    color_hex: str | None,
    tolerance: float,
) -> np.ndarray:
    """Toggle every visible block whose colour is within ``tolerance`` ΔE00.
    切换所有与参考色色差（ΔE00）不超过容差的可见色块；容差 0 等同同色选择。

    Args:
        component_cache: Visible-region component cache. (可见区域连通块缓存)
        current: Current selection mask. (当前选区掩码)
        x: Clicked pixel X, used when ``color_hex`` is absent. (点击 X)
        y: Clicked pixel Y, used when ``color_hex`` is absent. (点击 Y)
        color_hex: Optional explicit reference colour. (显式参考色)
        tolerance: Inclusive CIEDE2000 tolerance. (ΔE00 容差)

    Returns:
        np.ndarray: Next selection mask. (新的选区掩码)

    Raises:
        ValueError: No colour/point given, or invalid tolerance. (缺少颜色/坐标或容差非法)
        KeyError: No visible block matches. (没有命中的可见色块)
    """
    reference_hex = _reference_color_hex(component_cache, x, y, color_hex)
    labels = _labels_within_delta_e(component_cache, reference_hex, tolerance)
    return _toggle_component_group(component_cache, current, labels, reference_hex)


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
