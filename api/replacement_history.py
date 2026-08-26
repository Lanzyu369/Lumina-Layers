"""Replacement-history checkpoints for color adjustment tools.

颜色调整工具的替换历史 checkpoint。
"""

from __future__ import annotations

from copy import deepcopy
import os
import threading
import weakref
import time
from typing import Any, Literal

import numpy as np

from api.preview_cache_artifacts import is_preview_cache_artifact_ref
from api.selection_state import (
    RECIPE_OVERRIDE_APPLIED_MASKS_KEY,
    SELECTION_REGION_PREFIX,
    selection_region_id,
)
from api.session_store import SessionStore

REPLACEMENT_UNDO_STACK_KEY = "replacement_undo_stack"
REPLACEMENT_REDO_STACK_KEY = "replacement_redo_stack"

_DEFAULT_MAX_DEPTH = 20
_DEFAULT_MAX_BYTES = 512 * 1024 * 1024

_SESSION_FIELD_KEYS: tuple[str, ...] = (
    "replacement_regions",
    "recipe_overrides",
    "recipe_override_count",
    "region_replacement_count",
    "global_replacement_base_matched_rgb",
    "global_replacement_base_material_matrix",
    "gradient_groups",
    "gradient_region_id_map",
    "merge_map",
    "editor_selection_mask",
    "editor_selection_revision",
    "editor_selection_content_generation",
    "free_color_set",
    # Applied-override mask snapshots ride with recipe_overrides so undo/redo
    # keeps /generate able to re-apply historical overrides whose editor
    # selection ids no longer exist in the live selection state.
    # 已应用覆盖的掩码快照随 recipe_overrides 一起进出历史，保证撤销/重做后
    # /generate 仍能重新套用那些选区 id 已不存在的覆盖。
    "recipe_override_applied_masks",
)

_HISTORY_LOCK = threading.Lock()
_SESSION_LOCKS: weakref.WeakValueDictionary[str, threading.RLock] = weakref.WeakValueDictionary()


def replacement_history_lock(session_id: str) -> threading.RLock:
    """Return a per-session lock for history restoration.
    返回用于历史恢复的 per-session 锁。
    """
    with _HISTORY_LOCK:
        lock = _SESSION_LOCKS.get(session_id)
        if lock is None:
            lock = threading.RLock()
            _SESSION_LOCKS[session_id] = lock
        return lock


def history_counts(session_data: dict[str, Any] | None) -> tuple[int, int]:
    """Return ``(undo_count, redo_count)`` for a session.
    返回 session 的 ``(undo_count, redo_count)``。
    """
    if not session_data:
        return 0, 0
    return (
        len(_stack(session_data, REPLACEMENT_UNDO_STACK_KEY)),
        len(_stack(session_data, REPLACEMENT_REDO_STACK_KEY)),
    )


def can_undo(session_data: dict[str, Any] | None) -> bool:
    return history_counts(session_data)[0] > 0


def can_redo(session_data: dict[str, Any] | None) -> bool:
    return history_counts(session_data)[1] > 0


def clear_replacement_history(session_id: str, store: SessionStore) -> None:
    """Clear replacement undo/redo stacks for a new preview.
    为新的预览清空替换撤销/重做栈。
    """
    store.put(session_id, REPLACEMENT_UNDO_STACK_KEY, [])
    store.put(session_id, REPLACEMENT_REDO_STACK_KEY, [])
    store.put(session_id, "editor_selection_mask", None)
    store.put(session_id, "editor_selection_revision", 0)
    store.put(session_id, "editor_selection_content_generation", 0)
    # A fresh preview invalidates every replacement artefact. Accumulated
    # recipe overrides and their applied-mask snapshots must go too, or
    # /generate would silently re-apply stale footprints onto new content
    # (same-size images are common with standard LUT sizes).
    # 新预览使所有替换产物失效。累积的配方覆盖与掩码快照也必须一并清空，
    # 否则 /generate 会把过期足迹静默套到新内容上（标准 LUT 尺寸下同尺寸
    # 图片非常常见）。
    store.put(session_id, "recipe_overrides", [])
    store.put(session_id, "recipe_override_count", 0)
    store.put(session_id, RECIPE_OVERRIDE_APPLIED_MASKS_KEY, {})


def snapshot_replacement_state(
    session_data: dict[str, Any],
    *,
    label: str,
    session_fields: tuple[str, ...] | None = None,
    kind: Literal["content", "selection"] = "content",
    include_preview_cache: bool = True,
) -> dict[str, Any]:
    """Capture a restorable checkpoint before a mutating operation.
    在变更操作前捕获可恢复 checkpoint。
    """
    preview_cache = session_data.get("preview_cache")
    fields = _SESSION_FIELD_KEYS if session_fields is None else session_fields
    cloned_fields = {
        key: _clone_value(session_data.get(key))
        for key in fields
        if key in session_data
    }
    checkpoint: dict[str, Any] = {
        "label": str(label),
        "kind": kind,
        "created_at": time.time(),
        "session_fields": cloned_fields,
        # Session-field arrays (e.g. packed applied-override masks) must count
        # toward the history byte budget, otherwise the configured limit never
        # sees them and stack trimming under-accounts memory.
        # 会话字段里的数组（如位压缩的覆盖掩码快照）必须计入历史字节预算，
        # 否则配置的上限看不到这部分数据，栈裁剪会低估内存。
        "session_fields_nbytes": _estimate_value_array_nbytes(cloned_fields),
        "artifact_paths": [],
        "artifact_nbytes": 0,
    }
    if not include_preview_cache:
        checkpoint["preview_cache_ref"] = None
    elif is_preview_cache_artifact_ref(preview_cache):
        ref = _copy_preview_cache_ref(preview_cache)
        checkpoint["preview_cache_ref"] = ref
        paths, nbytes = _preview_cache_ref_paths_and_bytes(ref)
        checkpoint["artifact_paths"] = sorted(paths)
        checkpoint["artifact_nbytes"] = int(nbytes)
    elif isinstance(preview_cache, dict):
        checkpoint["preview_cache_arrays"] = _clone_preview_cache_dict(preview_cache)
        checkpoint["artifact_nbytes"] = _estimate_dict_array_nbytes(preview_cache)
    else:
        checkpoint["preview_cache_ref"] = None
    return checkpoint


def push_replacement_checkpoint(
    session_id: str,
    store: SessionStore,
    session_data: dict[str, Any],
    checkpoint: dict[str, Any] | None,
    *,
    clear_redo: bool = True,
) -> None:
    """Push a checkpoint to undo stack and optionally clear redo.
    将 checkpoint 入 undo 栈，并按需清空 redo 栈。
    """
    if not checkpoint:
        return
    # Serialise with undo/redo: restore_from_history mutates the same stacks,
    # so a concurrent push during a restore could drop or duplicate entries.
    # 与 undo/redo 串行化：restore_from_history 读写同一份栈，恢复进行中并发
    # push 会丢条目或产生重复条目。
    with replacement_history_lock(session_id):
        undo_stack = [*_stack(session_data, REPLACEMENT_UNDO_STACK_KEY)]
        if checkpoint.get("kind") == "content":
            # Fold only the selection-building suffix since the previous content
            # commit. Older selection entries remain reachable when older content
            # operations are undone.
            while undo_stack and undo_stack[-1].get("kind") == "selection":
                undo_stack.pop()
            checkpoint["preserve_selection_on_restore"] = True
        undo_stack.append(checkpoint)
        undo_stack = _trim_stack(undo_stack)
        session_data[REPLACEMENT_UNDO_STACK_KEY] = undo_stack
        store.put(session_id, REPLACEMENT_UNDO_STACK_KEY, undo_stack)
        if clear_redo:
            session_data[REPLACEMENT_REDO_STACK_KEY] = []
            store.put(session_id, REPLACEMENT_REDO_STACK_KEY, [])


def restore_from_history(
    session_id: str,
    store: SessionStore,
    session_data: dict[str, Any],
    *,
    action: Literal["undo", "redo"],
) -> dict[str, Any]:
    """Restore one undo/redo checkpoint and return it.
    恢复一个撤销/重做 checkpoint 并返回该 checkpoint。
    """
    source_key = REPLACEMENT_UNDO_STACK_KEY if action == "undo" else REPLACEMENT_REDO_STACK_KEY
    target_key = REPLACEMENT_REDO_STACK_KEY if action == "undo" else REPLACEMENT_UNDO_STACK_KEY
    source = _stack(session_data, source_key)
    if not source:
        raise IndexError(f"No replacement {action} checkpoint available")

    checkpoint = source[-1]
    preserve_selection = bool(checkpoint.get("preserve_selection_on_restore"))
    current = snapshot_replacement_state(
        session_data,
        label=f"{action}_current",
        kind=checkpoint.get("kind", "content"),
        include_preview_cache=checkpoint.get("kind") != "selection",
    )
    if preserve_selection:
        current["preserve_selection_on_restore"] = True
    next_source = source[:-1]
    next_target = [*_stack(session_data, target_key), current]
    next_target = _trim_stack(next_target)

    _restore_checkpoint(
        session_id,
        store,
        session_data,
        checkpoint,
        preserve_selection=preserve_selection,
    )
    session_data[source_key] = next_source
    session_data[target_key] = next_target
    store.put(session_id, source_key, next_source)
    store.put(session_id, target_key, next_target)
    return checkpoint


def collect_checkpoint_artifact_paths(session_data: dict[str, Any] | None) -> set[str]:
    """Return artifact paths referenced by replacement-history checkpoints.
    返回替换历史 checkpoint 引用的 artifact 文件路径。
    """
    if not session_data:
        return set()
    paths: set[str] = set()
    for key in (REPLACEMENT_UNDO_STACK_KEY, REPLACEMENT_REDO_STACK_KEY):
        for checkpoint in _stack(session_data, key):
            for path in checkpoint.get("artifact_paths") or []:
                if isinstance(path, str) and path:
                    paths.add(path)
            ref = checkpoint.get("preview_cache_ref")
            if is_preview_cache_artifact_ref(ref):
                ref_paths, _nbytes = _preview_cache_ref_paths_and_bytes(ref)
                paths.update(ref_paths)
    return paths


def _restore_checkpoint(
    session_id: str,
    store: SessionStore,
    session_data: dict[str, Any],
    checkpoint: dict[str, Any],
    *,
    preserve_selection: bool = False,
) -> None:
    if is_preview_cache_artifact_ref(checkpoint.get("preview_cache_ref")):
        preview_cache = _copy_preview_cache_ref(checkpoint["preview_cache_ref"])
    elif isinstance(checkpoint.get("preview_cache_arrays"), dict):
        preview_cache = _clone_preview_cache_dict(checkpoint["preview_cache_arrays"])
    else:
        preview_cache = None
    if preview_cache is not None:
        session_data["preview_cache"] = preview_cache
        store.put(session_id, "preview_cache", preview_cache)

    restored_fields = checkpoint.get("session_fields") or {}
    defaults: dict[str, Any] = {
        "replacement_regions": [],
        "recipe_overrides": [],
        "recipe_override_count": 0,
        "region_replacement_count": 0,
        "global_replacement_base_matched_rgb": None,
        "global_replacement_base_material_matrix": None,
        "gradient_groups": None,
        "gradient_region_id_map": None,
        "merge_map": None,
        "editor_selection_mask": None,
        "editor_selection_revision": 0,
        "editor_selection_content_generation": 0,
        "free_color_set": set(),
        "recipe_override_applied_masks": {},
    }
    restore_keys = (
        (
            "editor_selection_mask",
            "editor_selection_revision",
            "editor_selection_content_generation",
        )
        if checkpoint.get("kind") == "selection"
        else _SESSION_FIELD_KEYS
    )
    for key in restore_keys:
        if preserve_selection and key in {
            "editor_selection_mask",
            "editor_selection_revision",
            "editor_selection_content_generation",
        }:
            continue
        value = _clone_value(restored_fields[key]) if key in restored_fields else _clone_value(defaults.get(key))
        session_data[key] = value
        store.put(session_id, key, value)

    # A restored selection must re-publish its synthetic region token so legacy
    # recipe/region consumers can resolve the restored mask. The old (higher)
    # revision's token is dropped first — keep exactly one entry, matching the
    # restored revision.
    # 恢复的选区必须重新发布合成 region token，否则 recipe/region 旧流程无法
    # 从恢复后的 mask 解析（会 409 "No selected regions available"）。先清掉
    # 旧（更高）revision 的条目，只保留与恢复 revision 对应的一条。
    if checkpoint.get("kind") == "selection" and not preserve_selection:
        restored_mask = session_data.get("editor_selection_mask")
        restored_rev = max(0, int(session_data.get("editor_selection_revision") or 0))
        region_masks = session_data.get("selected_region_masks")
        if not isinstance(region_masks, dict):
            region_masks = {}
        for key in list(region_masks):
            if isinstance(key, str) and key.startswith(SELECTION_REGION_PREFIX):
                region_masks.pop(key, None)
        if (
            isinstance(restored_mask, np.ndarray)
            and restored_rev > 0
            and bool(np.any(restored_mask))
        ):
            region_masks[selection_region_id(restored_rev)] = restored_mask
        session_data["selected_region_masks"] = region_masks
        store.put(session_id, "selected_region_masks", region_masks)


def snapshot_selection_state(
    session_data: dict[str, Any],
    *,
    label: str,
) -> dict[str, Any]:
    """Capture a cheap selection-only checkpoint without copying preview arrays."""
    return snapshot_replacement_state(
        session_data,
        label=label,
        session_fields=(
            "editor_selection_mask",
            "editor_selection_revision",
            "editor_selection_content_generation",
        ),
        kind="selection",
        include_preview_cache=False,
    )


def _stack(session_data: dict[str, Any], key: str) -> list[dict[str, Any]]:
    stack = session_data.get(key)
    if isinstance(stack, list):
        return [item for item in stack if isinstance(item, dict)]
    return []


def _trim_stack(stack: list[dict[str, Any]]) -> list[dict[str, Any]]:
    max_depth = _max_depth()
    max_bytes = _max_bytes()
    trimmed = list(stack[-max_depth:]) if max_depth > 0 else []
    while len(trimmed) > 1 and _stack_artifact_nbytes(trimmed) > max_bytes:
        trimmed.pop(0)
    return trimmed


def _max_depth() -> int:
    try:
        value = int(os.environ.get("LUMINA_REPLACEMENT_HISTORY_MAX_DEPTH", _DEFAULT_MAX_DEPTH))
    except (TypeError, ValueError):
        value = _DEFAULT_MAX_DEPTH
    return max(1, value)


def _max_bytes() -> int:
    try:
        value = int(os.environ.get("LUMINA_REPLACEMENT_HISTORY_MAX_BYTES", _DEFAULT_MAX_BYTES))
    except (TypeError, ValueError):
        value = _DEFAULT_MAX_BYTES
    return max(1, value)


def _stack_artifact_nbytes(stack: list[dict[str, Any]]) -> int:
    total = 0
    for checkpoint in stack:
        try:
            total += int(checkpoint.get("artifact_nbytes") or 0)
        except (TypeError, ValueError):
            continue
        try:
            total += int(checkpoint.get("session_fields_nbytes") or 0)
        except (TypeError, ValueError):
            continue
    return total


def _estimate_value_array_nbytes(value: Any) -> int:
    """Sum ``ndarray`` bytes inside an arbitrary cloned session value.
    统计任意克隆会话值内 ndarray 的字节总量。
    """
    if isinstance(value, np.ndarray):
        return int(value.nbytes)
    if isinstance(value, dict):
        return sum(_estimate_value_array_nbytes(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return sum(_estimate_value_array_nbytes(item) for item in value)
    return 0


def _copy_preview_cache_ref(ref: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": ref["schema"],
        "manifest_revision": int(ref.get("manifest_revision", 0)),
        "fields": {
            field_name: dict(field_ref)
            for field_name, field_ref in ref.get("fields", {}).items()
        },
        "metadata": deepcopy(ref.get("metadata", {})),
    }


def _preview_cache_ref_paths_and_bytes(ref: dict[str, Any]) -> tuple[set[str], int]:
    paths: set[str] = set()
    nbytes = 0
    for field_ref in ref.get("fields", {}).values():
        if not isinstance(field_ref, dict):
            continue
        path = field_ref.get("path")
        if isinstance(path, str) and path:
            paths.add(path)
        try:
            nbytes += int(field_ref.get("nbytes") or 0)
        except (TypeError, ValueError):
            continue
    return paths, nbytes


def _clone_preview_cache_dict(cache: dict[str, Any]) -> dict[str, Any]:
    return {key: _clone_value(value) for key, value in cache.items()}


def _clone_value(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.copy()
    if isinstance(value, dict):
        return {key: _clone_value(inner) for key, inner in value.items()}
    if isinstance(value, list):
        return [_clone_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_clone_value(item) for item in value)
    if isinstance(value, set):
        return {_clone_value(item) for item in value}
    return deepcopy(value)


def _estimate_dict_array_nbytes(cache: dict[str, Any]) -> int:
    total = 0
    for value in cache.values():
        if isinstance(value, np.ndarray):
            total += int(value.nbytes)
    return total
