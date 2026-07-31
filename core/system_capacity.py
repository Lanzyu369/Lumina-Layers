"""Cross-platform effective CPU capacity for heavy converter work."""

from __future__ import annotations

from collections.abc import Callable, Collection
from dataclasses import dataclass
from functools import lru_cache
import math
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

_CGROUP_V2_CPU_MAX_PATH = Path("/sys/fs/cgroup/cpu.max")
_APPLE_CPU_PROBE_TIMEOUT_SECONDS = 0.5


@dataclass(frozen=True)
class EffectiveCpuCapacity:
    """Describe the CPU capacity visible to one Lumina process.

    描述单个 Lumina 进程实际可用于重型任务的 CPU 容量。

    Args:
        host_cpu_count: Portable logical CPU fallback.
            可移植的逻辑 CPU 回退值。
        affinity_cpu_count: CPUs allowed by process affinity, when available.
            进程亲和性允许的 CPU 数；不可用时为 ``None``。
        cgroup_quota_cpu_count: Linux cgroup v2 quota expressed as CPUs.
            Linux cgroup v2 配额折算的 CPU 数。
        apple_performance_cpu_count: Apple performance-core logical CPUs.
            Apple 性能核心的逻辑 CPU 数。
        effective_cpu_count: Smallest valid capacity, always at least one.
            所有有效容量中的最小值，至少为一。
        limiting_source: Stable label for the selected capacity source.
            选中容量来源的稳定标签。
    """

    host_cpu_count: int
    affinity_cpu_count: int | None
    cgroup_quota_cpu_count: int | None
    apple_performance_cpu_count: int | None
    effective_cpu_count: int
    limiting_source: str


def _positive_int_or_none(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if parsed > 0 else None


def _positive_collection_size(
    values: Collection[int] | None,
) -> int | None:
    if not values:
        return None
    try:
        normalized = {int(value) for value in values}
    except (TypeError, ValueError, OverflowError):
        return None
    return len(normalized) or None


def _parse_cgroup_v2_cpu_max(raw_value: str | None) -> int | None:
    if not isinstance(raw_value, str):
        return None
    parts = raw_value.strip().split()
    if len(parts) != 2 or parts[0].lower() == "max":
        return None
    try:
        quota = int(parts[0])
        period = int(parts[1])
    except (TypeError, ValueError, OverflowError):
        return None
    if quota <= 0 or period <= 0:
        return None
    return max(1, int(math.ceil(quota / period)))


def discover_effective_cpu_capacity(
    *,
    host_cpu_count: int | None,
    affinity_cpu_ids: Collection[int] | None,
    cgroup_cpu_max: str | None,
    apple_performance_cpu_count: int | None,
) -> EffectiveCpuCapacity:
    """Resolve effective CPU capacity from deterministic probe values.

    从可注入的探测值解析有效 CPU 容量，便于跨平台确定性测试。

    Args:
        host_cpu_count: Result of ``os.cpu_count()`` or an injected value.
            ``os.cpu_count()`` 的结果或测试注入值。
        affinity_cpu_ids: CPU IDs allowed for the current process.
            当前进程允许使用的 CPU ID。
        cgroup_cpu_max: Raw Linux cgroup v2 ``cpu.max`` text.
            Linux cgroup v2 ``cpu.max`` 原始文本。
        apple_performance_cpu_count: Apple performance-core logical count.
            Apple 性能核心逻辑 CPU 数。

    Returns:
        An immutable effective-capacity description.
        不可变的有效 CPU 容量说明。
    """

    host = _positive_int_or_none(host_cpu_count) or 1
    affinity = _positive_collection_size(affinity_cpu_ids)
    quota = _parse_cgroup_v2_cpu_max(cgroup_cpu_max)
    performance = _positive_int_or_none(apple_performance_cpu_count)
    candidates = [
        ("host_fallback", host),
        ("affinity", affinity),
        ("cgroup_v2", quota),
        ("apple_performance", performance),
    ]
    valid_candidates = [
        (source, int(count))
        for source, count in candidates
        if count is not None
    ]
    limiting_source, effective = min(
        valid_candidates,
        key=lambda candidate: candidate[1],
    )
    return EffectiveCpuCapacity(
        host_cpu_count=host,
        affinity_cpu_count=affinity,
        cgroup_quota_cpu_count=quota,
        apple_performance_cpu_count=performance,
        effective_cpu_count=max(1, effective),
        limiting_source=limiting_source,
    )


def _read_process_affinity() -> frozenset[int] | None:
    affinity_reader = getattr(os, "sched_getaffinity", None)
    if not callable(affinity_reader):
        return None
    try:
        affinity = frozenset(int(cpu_id) for cpu_id in affinity_reader(0))
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
        return None
    return affinity or None


def _read_cgroup_v2_cpu_max(
    *,
    cpu_max_path: Path = _CGROUP_V2_CPU_MAX_PATH,
) -> str | None:
    try:
        value = cpu_max_path.read_text(encoding="utf-8").strip()
    except (OSError, RuntimeError, UnicodeError):
        return None
    return value or None


def _read_apple_performance_cpu_count(
    *,
    platform_name: str = sys.platform,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> int | None:
    if str(platform_name).lower() != "darwin":
        return None
    command = ["sysctl", "-n", "hw.perflevel0.logicalcpu"]
    try:
        result = runner(
            command,
            capture_output=True,
            check=False,
            shell=False,
            text=True,
            timeout=_APPLE_CPU_PROBE_TIMEOUT_SECONDS,
        )
    except (
        AttributeError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
        subprocess.SubprocessError,
    ):
        return None
    if int(getattr(result, "returncode", 1)) != 0:
        return None
    return _positive_int_or_none(getattr(result, "stdout", "").strip())


def _discover_live_capacity() -> EffectiveCpuCapacity:
    return discover_effective_cpu_capacity(
        host_cpu_count=os.cpu_count(),
        affinity_cpu_ids=_read_process_affinity(),
        cgroup_cpu_max=_read_cgroup_v2_cpu_max(),
        apple_performance_cpu_count=_read_apple_performance_cpu_count(),
    )


@lru_cache(maxsize=1)
def get_effective_cpu_capacity() -> EffectiveCpuCapacity:
    """Return the process CPU capacity, cached after the first probe.

    返回当前进程的有效 CPU 容量；首次探测后在进程内缓存。

    Returns:
        An immutable capacity snapshot.
        不可变的容量快照。
    """

    return _discover_live_capacity()
