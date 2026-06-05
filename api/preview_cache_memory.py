"""Preview-cache memory diagnostics.

预览缓存内存诊断工具。
"""

from __future__ import annotations

import os
from typing import Any

import numpy as np


_INFO_FLAG = "LUMINA_PREVIEW_CACHE_MEMORY_PROFILE_INFO"
_MAX_ARRAYS_REPORTED = 12


def should_log_preview_cache_memory_profile_at_info() -> bool:
    """Return whether preview cache memory profiles should be INFO logs.

    返回预览缓存内存画像是否应以 INFO 级别输出。

    Returns:
        bool: True when the explicit diagnostic INFO flag is enabled.
        bool: 显式诊断 INFO 开关启用时返回 True。
    """
    raw = os.getenv(_INFO_FLAG, "")
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def get_process_rss_bytes() -> int | None:
    """Return current process RSS when available.

    返回当前进程 RSS；平台或依赖不支持时返回 None。

    Returns:
        int | None: Resident set size in bytes, or None when unavailable.
        int | None: 以字节为单位的 RSS；不可用时为 None。
    """
    try:
        import psutil  # type: ignore[import-not-found]
    except ImportError:
        return None
    try:
        return int(psutil.Process(os.getpid()).memory_info().rss)
    except (OSError, RuntimeError):
        return None


def build_preview_cache_memory_profile(
    cache_data: dict[str, Any] | None,
    *,
    session_id: str,
    modeling_mode: str | None,
    cache_data_bytes: int | None,
    process_rss_bytes: int | None,
) -> dict[str, Any]:
    """Build one aggregate structured-log payload for preview cache memory.

    为 preview cache 构建单条聚合结构化日志负载。

    Args:
        cache_data (dict[str, Any] | None): Preview cache dict to inspect.
            待检查的预览缓存字典。
        session_id (str): Session identifier for log correlation.
            用于日志关联的 session ID。
        modeling_mode (str | None): Preview modeling mode, if known.
            预览建模模式；未知时为 None。
        cache_data_bytes (int | None): Serialized worker cache size in bytes.
            worker 序列化缓存文件字节数。
        process_rss_bytes (int | None): Main-process RSS in bytes.
            主进程 RSS 字节数。

    Returns:
        dict[str, Any]: JSON-serializable structured log payload.
        dict[str, Any]: 可 JSON 序列化的结构化日志负载。
    """
    arrays: list[dict[str, Any]] = []
    if cache_data:
        for key, value in cache_data.items():
            if isinstance(value, np.ndarray):
                arrays.append(
                    {
                        "field": key,
                        "shape": [int(dim) for dim in value.shape],
                        "dtype": str(value.dtype),
                        "nbytes": int(value.nbytes),
                    }
                )

    arrays.sort(key=lambda item: int(item["nbytes"]), reverse=True)
    return {
        "event": "preview_cache_memory_profile",
        "session_id": session_id,
        "modeling_mode": modeling_mode,
        "cache_data_bytes": cache_data_bytes,
        "process_rss_bytes": process_rss_bytes,
        "array_count": len(arrays),
        "array_total_bytes": sum(int(item["nbytes"]) for item in arrays),
        "largest_arrays": arrays[:_MAX_ARRAYS_REPORTED],
    }
