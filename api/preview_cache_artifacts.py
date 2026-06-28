"""Private preview-cache artifact storage.

预览缓存私有工件存储。
"""

from __future__ import annotations

from collections.abc import Iterator, MutableMapping
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import os
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

from api.session_store import SessionStore
from config import TEMP_DIR


ARTIFACT_SCHEMA = "preview_cache_artifact_v1"
PREVIEW_CACHE_MAX_BYTES_ENV = "LUMINA_PREVIEW_CACHE_MAX_BYTES"
LARGE_ARRAY_FIELDS = {
    "matched_rgb",
    "material_matrix",
    "mask_solid",
    "preview_rgba",
    "quantized_image",
}
ORIGINAL_ARRAY_FIELDS = {
    "original_matched_rgb",
    "original_material_matrix",
}


class PreviewCacheRevisionConflict(RuntimeError):
    """Raised when a dirty artifact field changed during a transaction.

    当事务期间待写回的 artifact 字段 revision 已被其他请求更新时抛出。
    """


class _PreviewCacheTransaction(MutableMapping[str, Any]):
    def __init__(
        self,
        *,
        session_id: str,
        store: SessionStore,
        cache: dict[str, Any],
        start_ref: dict[str, Any] | None,
        requested_fields: set[str],
    ) -> None:
        self._session_id = session_id
        self._store = store
        self._cache = cache
        self._start_ref = _copy_ref(start_ref) if start_ref is not None else None
        self._requested_fields = set(requested_fields)
        tracked_fields = set(self._requested_fields)
        if self._start_ref is not None:
            tracked_fields.update(self._start_ref.get("fields", {}))
        self._field_revisions = {
            field_name: self._field_revision(self._start_ref, field_name)
            for field_name in tracked_fields
        }

    def __getitem__(self, key: str) -> Any:
        return self._cache[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self._cache[key] = value

    def __delitem__(self, key: str) -> None:
        del self._cache[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._cache)

    def __len__(self) -> int:
        return len(self._cache)

    def commit(
        self,
        dirty_fields: set[str],
        *,
        metadata_fields: set[str] | None = None,
    ) -> dict[str, Any]:
        """Persist selected dirty array fields.

        写回指定的脏数组字段。
        """
        if self._start_ref is None:
            self._store.put(self._session_id, "preview_cache", self._cache)
            return self._cache

        dirty_arrays: dict[str, np.ndarray] = {}
        for field_name in dirty_fields:
            value = self._cache[field_name]
            if not isinstance(value, np.ndarray):
                raise TypeError(
                    f"Preview cache field {field_name!r} must be a NumPy array"
                )
            dirty_arrays[field_name] = value

        latest_session = self._store.get(self._session_id)
        latest_ref = (latest_session or {}).get("preview_cache")
        if not is_preview_cache_artifact_ref(latest_ref):
            raise PreviewCacheRevisionConflict(
                "Preview cache artifact was replaced during transaction"
            )

        for field_name in dirty_arrays:
            expected_revision = self._field_revisions.get(field_name)
            latest_revision = self._field_revision(latest_ref, field_name)
            if latest_revision != expected_revision:
                raise PreviewCacheRevisionConflict(
                    "Preview cache field "
                    f"{field_name!r} revision changed from "
                    f"{expected_revision!r} to {latest_revision!r}"
                )

        updated_ref = (
            save_preview_cache_fields(
                self._session_id,
                self._store,
                latest_ref,
                dirty_arrays,
            )
            if dirty_arrays
            else latest_ref
        )
        if metadata_fields:
            dirty_metadata = {
                field_name: self._cache[field_name]
                for field_name in metadata_fields
                if field_name in self._cache
                and not isinstance(self._cache[field_name], np.ndarray)
            }
            if dirty_metadata:
                updated_ref = merge_preview_cache_metadata(updated_ref, dirty_metadata)
        self._store.put(self._session_id, "preview_cache", updated_ref)
        self._start_ref = _copy_ref(updated_ref)
        tracked_fields = set(self._requested_fields)
        tracked_fields.update(updated_ref.get("fields", {}))
        self._field_revisions = {
            field_name: self._field_revision(updated_ref, field_name)
            for field_name in tracked_fields
        }
        return updated_ref

    @staticmethod
    def _field_revision(
        ref: dict[str, Any] | None,
        field_name: str,
    ) -> int | None:
        if ref is None:
            return None
        field_ref = ref.get("fields", {}).get(field_name)
        if not isinstance(field_ref, dict):
            return None
        revision = field_ref.get("revision")
        return int(revision) if revision is not None else None


def is_preview_cache_artifact_ref(value: object) -> bool:
    """Return whether a value is a preview-cache artifact manifest.

    判断对象是否是 preview-cache 工件 manifest。

    Args:
        value (object): Value to inspect. 待检查的对象。

    Returns:
        bool: True when the value has the expected artifact schema.
        bool: 对象包含预期工件 schema 时返回 True。
    """
    return isinstance(value, dict) and value.get("schema") == ARTIFACT_SCHEMA


@contextmanager
def preview_cache_transaction(
    session_id: str,
    store: SessionStore,
    session_data: dict[str, Any],
    *,
    fields: set[str],
) -> Iterator[_PreviewCacheTransaction]:
    """Open a field-scoped preview-cache transaction.

    打开按字段加载和写回的 preview-cache 事务。

    Args:
        session_id (str): Owning session ID. 所属 session ID。
        store (SessionStore): Session store containing the current manifest.
            包含当前 manifest 的会话存储。
        session_data (dict[str, Any]): Session data snapshot from the route.
            路由读取到的 session 数据快照。
        fields (set[str]): Array fields to hydrate. 需要加载的数组字段。

    Yields:
        _PreviewCacheTransaction: Dict-like cache view with ``commit``.
        _PreviewCacheTransaction: 带 ``commit`` 的类 dict 缓存视图。

    Raises:
        ValueError: If no preview cache exists. 无 preview cache 时抛出。
        PreviewCacheRevisionConflict: If a dirty field changed concurrently.
        PreviewCacheRevisionConflict: 脏字段发生并发更新时抛出。
    """
    cache_or_ref = session_data.get("preview_cache")
    if cache_or_ref is None:
        raise ValueError("No preview cache available for transaction")

    if is_preview_cache_artifact_ref(cache_or_ref):
        transaction = _PreviewCacheTransaction(
            session_id=session_id,
            store=store,
            cache=hydrate_preview_cache(cache_or_ref, fields=fields),
            start_ref=cache_or_ref,
            requested_fields=fields,
        )
    else:
        if not isinstance(cache_or_ref, dict):
            raise ValueError("Invalid preview cache for transaction")
        transaction = _PreviewCacheTransaction(
            session_id=session_id,
            store=store,
            cache=cache_or_ref,
            start_ref=None,
            requested_fields=fields,
        )

    yield transaction


def externalize_preview_cache(
    session_id: str,
    store: SessionStore,
    cache: dict[str, Any],
    *,
    root_dir: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Write NumPy cache fields to private session-bound artifact files.

    将 NumPy 缓存字段写入 session 私有临时工件文件。

    Args:
        session_id (str): Owning session ID. 所属 session ID。
        store (SessionStore): Session store used for cleanup registration.
            用于清理登记的会话存储。
        cache (dict[str, Any]): Preview cache payload. 预览缓存负载。
        root_dir (str | os.PathLike[str] | None): Optional artifact directory.
            可选的工件目录。

    Returns:
        dict[str, Any]: Artifact manifest with array field references and
        non-array metadata. 包含数组字段引用和非数组元数据的工件 manifest。
    """
    ref, artifact_paths = externalize_preview_cache_to_artifacts(
        cache,
        root_dir=root_dir,
    )
    for path in artifact_paths:
        store.register_temp_file(session_id, path)
    return ref


def externalize_preview_cache_to_artifacts(
    cache: dict[str, Any],
    *,
    root_dir: str | os.PathLike[str] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Write NumPy cache fields to artifact files without session mutation.

    不修改 SessionStore，仅把 NumPy 缓存字段写入 artifact 文件。

    Args:
        cache (dict[str, Any]): Preview cache payload. 预览缓存负载。
        root_dir (str | os.PathLike[str] | None): Optional artifact directory.
            可选的工件目录。

    Returns:
        tuple[dict[str, Any], list[str]]: Artifact manifest plus unique
        paths that the caller must register or clean up.
        artifact manifest 与唯一文件路径列表；调用方负责注册或清理。
    """
    fields: dict[str, dict[str, Any]] = {}
    metadata: dict[str, Any] = {}
    artifact_paths: list[str] = []
    artifact_dir = Path(root_dir) if root_dir is not None else Path(TEMP_DIR)
    field_refs_by_array_id: dict[int, dict[str, Any]] = {}

    try:
        for key, value in cache.items():
            if isinstance(value, np.ndarray):
                array_id = id(value)
                existing_ref = field_refs_by_array_id.get(array_id)
                if existing_ref is not None:
                    fields[key] = dict(existing_ref)
                    continue
                path, field_ref = _write_new_array_field(key, value, artifact_dir)
                artifact_paths.append(path)
                fields[key] = field_ref
                field_refs_by_array_id[array_id] = dict(field_ref)
            else:
                metadata[key] = deepcopy(value)
    except Exception:
        for path in set(artifact_paths):
            _delete_if_exists(path)
        raise

    return (
        {
            "schema": ARTIFACT_SCHEMA,
            "manifest_revision": 1,
            "fields": fields,
            "metadata": metadata,
        },
        artifact_paths,
    )


def hydrate_preview_cache(
    ref: dict[str, Any],
    *,
    fields: set[str] | None = None,
    mmap_mode: str | None = None,
) -> dict[str, Any]:
    """Load selected array fields from a preview-cache artifact manifest.

    从 preview-cache 工件 manifest 加载指定数组字段。

    Args:
        ref (dict[str, Any]): Artifact manifest. 工件 manifest。
        fields (set[str] | None): Optional field names to load. If omitted,
            all array fields are loaded. 可选字段名；省略时加载全部数组字段。
        mmap_mode (str | None): Optional NumPy mmap mode for `np.load`.
            可选的 NumPy mmap 加载模式。

    Returns:
        dict[str, Any]: Hydrated cache dict containing metadata and requested
        arrays. 包含元数据和请求数组的缓存字典。
    """
    _require_artifact_ref(ref)
    hydrated = deepcopy(ref.get("metadata", {}))
    selected_fields = set(ref.get("fields", {})) if fields is None else fields
    for field_name in selected_fields:
        field_ref = ref.get("fields", {}).get(field_name)
        if field_ref is None:
            continue
        hydrated[field_name] = np.load(
            field_ref["path"],
            mmap_mode=mmap_mode,
            allow_pickle=False,
        )
    return hydrated


def hydrate_preview_cache_for_worker(
    cache_or_ref: dict[str, Any],
    *,
    mmap: bool = True,
) -> dict[str, Any]:
    """Hydrate preview cache for worker-side array reads.

    为 worker 侧数组读取加载 preview cache。

    Args:
        cache_or_ref (dict[str, Any]): Legacy cache dict or artifact manifest.
            旧缓存字典或 artifact manifest。
        mmap (bool): Use read-only NumPy mmap for artifact arrays when True.
            为 True 时 artifact 数组使用只读 NumPy mmap。

    Returns:
        dict[str, Any]: Hydrated cache for workers, or the legacy cache as-is.
        dict[str, Any]: worker 可用缓存；旧缓存原样返回。
    """
    if is_preview_cache_artifact_ref(cache_or_ref):
        return hydrate_preview_cache(
            cache_or_ref,
            mmap_mode="r" if mmap else None,
        )
    return cache_or_ref


def estimate_preview_cache_bytes(
    width: int,
    height: int,
    layers: int,
    *,
    include_original: bool,
    matrix_itemsize: int | None = None,
) -> int:
    """Estimate large preview-cache array bytes from dimensions.

    按尺寸估算 preview-cache 大数组字节数。

    Args:
        width (int): Estimated cache width in pixels. 估算像素宽度。
        height (int): Estimated cache height in pixels. 估算像素高度。
        layers (int): Estimated optical layer count. 估算叠色层数。
        include_original (bool): Include original snapshot arrays.
            是否包含原始快照数组。
        matrix_itemsize (int | None): Bytes per material-matrix cell.
            ``None`` preserves the legacy int32 estimate.
            material_matrix 每个单元的字节数；``None`` 保持旧 int32 估算。

    Returns:
        int: Estimated bytes for matched RGB, RGBA, mask, material matrix,
        and optional original snapshots. 估算字节数。
    """
    safe_width = max(1, int(width))
    safe_height = max(1, int(height))
    safe_layers = max(1, int(layers))
    pixel_count = safe_width * safe_height
    matched = pixel_count * 3
    rgba = pixel_count * 4
    mask = pixel_count
    matrix_cell_bytes = (
        int(matrix_itemsize)
        if matrix_itemsize is not None and int(matrix_itemsize) > 0
        else np.dtype(np.int32).itemsize
    )
    matrix = pixel_count * safe_layers * matrix_cell_bytes
    original = matched + matrix if include_original else 0
    return matched + rgba + mask + matrix + original


def get_preview_cache_max_bytes() -> int | None:
    """Return the configured preview-cache byte limit, or None when disabled.

    返回配置的 preview-cache 字节上限；未显式配置时返回 None，表示不启用预估拦截。

    Returns:
        int | None: Positive limit from ``LUMINA_PREVIEW_CACHE_MAX_BYTES``.
        Unset, empty, invalid, zero, or negative values disable the guardrail.
        int | None: 正数上限；未设置、空值、非法值、0 或负数表示关闭。
    """
    raw = os.getenv(PREVIEW_CACHE_MAX_BYTES_ENV)
    if raw is None or raw.strip() == "":
        return None
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def get_preview_cache_metadata(cache_or_ref: dict[str, Any]) -> dict[str, Any]:
    """Return preview-cache metadata without loading artifact arrays.

    返回 preview-cache 元数据，不加载 artifact 数组。

    Args:
        cache_or_ref (dict[str, Any]): Legacy cache dict or artifact manifest.
            旧缓存字典或工件 manifest。

    Returns:
        dict[str, Any]: Metadata-only cache view. 元数据缓存视图。
    """
    if is_preview_cache_artifact_ref(cache_or_ref):
        return deepcopy(cache_or_ref.get("metadata", {}))
    return cache_or_ref


def get_preview_cache_field_path(
    ref: dict[str, Any],
    field_name: str,
) -> str | None:
    """Return an artifact field path without loading the array.

    返回 artifact 字段路径，不加载数组。

    Args:
        ref (dict[str, Any]): Artifact manifest. 工件 manifest。
        field_name (str): Array field name. 数组字段名。

    Returns:
        str | None: Field `.npy` path when present, otherwise None.
        str | None: 字段 `.npy` 路径；不存在时返回 None。
    """
    if not is_preview_cache_artifact_ref(ref):
        return None
    field_ref = ref.get("fields", {}).get(field_name)
    if not isinstance(field_ref, dict):
        return None
    path = field_ref.get("path")
    return str(path) if path else None


def save_preview_cache_fields(
    session_id: str,
    store: SessionStore,
    ref: dict[str, Any],
    dirty_fields: dict[str, np.ndarray],
) -> dict[str, Any]:
    """Atomically save dirty NumPy fields into a cache artifact manifest.

    将修改过的 NumPy 字段原子保存回缓存工件 manifest。

    Args:
        session_id (str): Owning session ID. 所属 session ID。
        store (SessionStore): Session store used for new cleanup paths.
            用于登记新清理路径的会话存储。
        ref (dict[str, Any]): Existing artifact manifest. 现有工件 manifest。
        dirty_fields (dict[str, np.ndarray]): Array fields to write.
            需要写入的数组字段。

    Returns:
        dict[str, Any]: Updated artifact manifest. 更新后的工件 manifest。
    """
    _require_artifact_ref(ref)
    updated = _copy_ref(ref)
    updated["manifest_revision"] = int(updated.get("manifest_revision", 0)) + 1
    artifact_dir = _artifact_dir_for_ref(updated)

    for field_name, array in dirty_fields.items():
        if not isinstance(array, np.ndarray):
            raise TypeError(f"Preview cache field {field_name!r} must be a NumPy array")
        existing = updated["fields"].get(field_name)
        revision = int(existing.get("revision", 0)) + 1 if existing else 1
        path, field_ref = _write_new_array_field(
            field_name,
            array,
            artifact_dir,
            revision=revision,
        )
        store.register_temp_file(session_id, path)
        updated["fields"][field_name] = field_ref

    return updated


def persist_preview_cache(
    session_id: str,
    store: SessionStore,
    cache: dict[str, Any],
) -> dict[str, Any]:
    """Persist a preview cache without de-externalizing artifact sessions.

    保存预览缓存，同时避免 artifact-backed session 退回内存大字典。

    Args:
        session_id (str): Owning session ID. 所属 session ID。
        store (SessionStore): Session store to update. 要更新的会话存储。
        cache (dict[str, Any]): Legacy cache dict, artifact ref, or hydrated
            cache dict. 旧缓存字典、工件引用或已 hydrate 的缓存字典。

    Returns:
        dict[str, Any]: The value stored as `preview_cache`.
        dict[str, Any]: 实际写入 `preview_cache` 的值。
    """
    if is_preview_cache_artifact_ref(cache):
        store.put(session_id, "preview_cache", cache)
        return cache

    session_data = store.get(session_id) or {}
    current_cache = session_data.get("preview_cache")
    if not is_preview_cache_artifact_ref(current_cache):
        store.put(session_id, "preview_cache", cache)
        return cache

    array_fields = {
        key: value
        for key, value in cache.items()
        if isinstance(value, np.ndarray)
    }
    metadata = {
        key: value
        for key, value in cache.items()
        if not isinstance(value, np.ndarray)
    }
    updated = (
        save_preview_cache_fields(session_id, store, current_cache, array_fields)
        if array_fields
        else current_cache
    )
    updated = merge_preview_cache_metadata(updated, metadata)
    store.put(session_id, "preview_cache", updated)
    return updated


def merge_preview_cache_metadata(
    ref: dict[str, Any],
    metadata: dict[str, object],
) -> dict[str, Any]:
    """Merge small metadata into a preview-cache artifact manifest.

    将小型元数据合并进 preview-cache 工件 manifest。

    Args:
        ref (dict[str, Any]): Existing artifact manifest. 现有工件 manifest。
        metadata (dict[str, object]): Metadata values to merge. 要合并的元数据。

    Returns:
        dict[str, Any]: Updated artifact manifest. 更新后的工件 manifest。
    """
    _require_artifact_ref(ref)
    updated = _copy_ref(ref)
    updated["manifest_revision"] = int(updated.get("manifest_revision", 0)) + 1
    updated["metadata"].update(deepcopy(metadata))
    return updated


def _require_artifact_ref(ref: dict[str, Any]) -> None:
    if not is_preview_cache_artifact_ref(ref):
        raise ValueError("Invalid preview-cache artifact manifest")


def _copy_ref(ref: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": ref["schema"],
        "manifest_revision": int(ref.get("manifest_revision", 0)),
        "fields": {
            field_name: dict(field_ref)
            for field_name, field_ref in ref.get("fields", {}).items()
        },
        "metadata": deepcopy(ref.get("metadata", {})),
    }


def _artifact_dir_for_ref(ref: dict[str, Any]) -> Path:
    for field_ref in ref.get("fields", {}).values():
        path = field_ref.get("path")
        if path:
            return Path(path).parent
    return Path(TEMP_DIR)


def _safe_field_name(field_name: str) -> str:
    return "".join(
        char if char.isalnum() or char in {"-", "_"} else "_"
        for char in field_name
    )


def _write_new_array_field(
    field_name: str,
    array: np.ndarray,
    artifact_dir: Path,
    *,
    revision: int = 1,
) -> tuple[str, dict[str, Any]]:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    safe_name = _safe_field_name(field_name)
    fd, tmp_path = tempfile.mkstemp(
        prefix=f"preview_cache_{safe_name}_",
        suffix=".tmp",
        dir=str(artifact_dir),
    )
    final_path = f"{tmp_path[:-4]}.npy"
    try:
        with os.fdopen(fd, "wb") as handle:
            np.save(handle, array, allow_pickle=False)
        os.replace(tmp_path, final_path)
        field_ref = _build_field_ref(final_path, array, revision=revision)
    except BaseException:
        _delete_if_exists(tmp_path)
        _delete_if_exists(final_path)
        raise
    return final_path, field_ref


def _build_field_ref(
    path: str,
    array: np.ndarray,
    *,
    revision: int,
) -> dict[str, Any]:
    return {
        "path": path,
        "shape": [int(dim) for dim in array.shape],
        "dtype": str(array.dtype),
        "nbytes": int(array.nbytes),
        "revision": int(revision),
        "sha256": _array_sha256(array),
    }


def _array_sha256(array: np.ndarray) -> str:
    contiguous = np.ascontiguousarray(array)
    return hashlib.sha256(contiguous.tobytes()).hexdigest()


def _delete_if_exists(path: str) -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        return
