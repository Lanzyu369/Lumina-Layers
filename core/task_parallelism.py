"""Bounded parallelism policy for CPU-heavy work inside one conversion task."""

from __future__ import annotations

import os
import threading
from typing import Literal

from api.structured_logging import get_logger

_log = get_logger(__name__)

WorkloadKind = Literal["raster", "vector"]

_ENV_BY_WORKLOAD: dict[WorkloadKind, str] = {
    "raster": "LUMINA_RASTER_PARALLELISM",
    "vector": "LUMINA_VECTOR_PARALLELISM",
}
_WARNED_INVALID_VALUES: set[tuple[str, str]] = set()
_WARNING_LOCK = threading.Lock()


def _positive_int_or_default(raw_value: str | None, default: int) -> int:
    """Return a positive environment integer or a safe default."""

    if raw_value is None:
        return default
    try:
        parsed = int(raw_value.strip())
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _warn_invalid_once(env_var: str, raw_value: str) -> None:
    """Emit one structured warning for each distinct invalid setting."""

    warning_key = (env_var, raw_value)
    with _WARNING_LOCK:
        if warning_key in _WARNED_INVALID_VALUES:
            return
        _WARNED_INVALID_VALUES.add(warning_key)

    _log.warning(
        "Invalid task parallelism setting; falling back to automatic policy",
        extra={
            "event": "task_parallelism_invalid",
            "env_var": env_var,
            "raw_value": raw_value,
            "fallback": "auto",
        },
    )


def resolve_task_parallelism(
    workload: WorkloadKind,
    *,
    work_items: int,
    min_parallel_items: int = 2,
    hard_max_workers: int = 8,
) -> int:
    """Resolve safe inner workers for one conversion task.

    根据 CPU、公平份额、工作项数量和阶段硬上限，计算单次转换内部的安全并行度。
    显式配置仍受全部安全边界约束；无效配置会回退到自动策略。

    Args:
        workload: Workload family selecting its environment override.
            工作负载类型，用于选择对应的环境变量。
        work_items: Number of independent work items available.
            可独立执行的工作项数量。
        min_parallel_items: Minimum item count required before parallel work.
            启用并行所需的最少工作项数量。
        hard_max_workers: Stage-specific memory and stability ceiling.
            阶段基于内存与稳定性设置的最大线程数。

    Returns:
        A worker count of at least one, bounded by every safety limit.
        不小于一且满足全部安全边界的线程数。
    """

    if workload not in _ENV_BY_WORKLOAD:
        raise ValueError(f"Unsupported workload kind: {workload!r}")

    item_count = max(0, int(work_items))
    parallel_threshold = max(2, int(min_parallel_items))
    if item_count < parallel_threshold:
        return 1

    cpu_count = max(1, os.cpu_count() or 1)
    stage_ceiling = max(1, int(hard_max_workers))
    default_outer_workers = min(cpu_count, 4)
    outer_workers = _positive_int_or_default(
        os.getenv("LUMINA_MAX_WORKERS"),
        default_outer_workers,
    )
    fair_share = max(1, cpu_count // outer_workers)

    env_var = _ENV_BY_WORKLOAD[workload]
    raw_requested = os.getenv(env_var)
    normalized = raw_requested.strip().lower() if raw_requested is not None else ""

    if normalized in {"", "auto"}:
        requested = fair_share
    else:
        try:
            requested = int(normalized)
        except ValueError:
            requested = 0
        if requested <= 0:
            _warn_invalid_once(env_var, raw_requested or "")
            requested = fair_share

    return max(
        1,
        min(
            requested,
            fair_share,
            cpu_count,
            item_count,
            stage_ceiling,
        ),
    )
