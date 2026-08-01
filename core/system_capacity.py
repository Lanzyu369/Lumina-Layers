"""Cross-platform effective CPU capacity for heavy converter work."""

from __future__ import annotations

from collections.abc import Callable, Collection
from dataclasses import dataclass
from functools import lru_cache
import ctypes
import math
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Literal

_PROC_SELF_CGROUP_PATH = Path("/proc/self/cgroup")
_PROC_SELF_MOUNTINFO_PATH = Path("/proc/self/mountinfo")
_APPLE_CPU_PROBE_TIMEOUT_SECONDS = 0.5
_MOUNTINFO_PATH_ESCAPES = {
    r"\040": " ",
    r"\011": "\t",
    r"\012": "\n",
    r"\134": "\\",
}

CpuTopology = Literal["heterogeneous", "homogeneous", "unknown"]
CpuSchedulingPolicy = Literal[
    "apple_performance_budget",
    "os_core_type_scheduler",
    "os_capacity_scheduler",
    "all_visible_cpus",
]


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
        windows_performance_cpu_count: Logical CPU sets in Windows' fastest
            reported efficiency class. Windows 报告的最高性能等级逻辑 CPU 数。
        cpu_topology: Reliably detected topology, or ``"unknown"``.
            可靠探测到的 CPU 拓扑；无法确认时为 ``"unknown"``。
        scheduling_policy: Platform scheduling policy used for heavy work.
            重计算采用的平台调度策略。
    """

    host_cpu_count: int
    affinity_cpu_count: int | None
    cgroup_quota_cpu_count: int | None
    apple_performance_cpu_count: int | None
    effective_cpu_count: int
    limiting_source: str
    windows_performance_cpu_count: int | None = None
    cpu_topology: CpuTopology = "unknown"
    scheduling_policy: CpuSchedulingPolicy = "all_visible_cpus"


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


def _normalize_windows_efficiency_classes(
    values: Collection[int] | None,
) -> tuple[int, ...] | None:
    if not values:
        return None
    normalized: list[int] = []
    try:
        for value in values:
            parsed = int(value)
            if parsed < 0 or parsed > 255:
                return None
            normalized.append(parsed)
    except (TypeError, ValueError, OverflowError):
        return None
    return tuple(normalized) or None


def _parse_windows_efficiency_classes(
    raw_records: bytes | bytearray | memoryview,
) -> tuple[int, ...] | None:
    """Parse variable-length Windows CPU-set records.

    解析 Windows ``SYSTEM_CPU_SET_INFORMATION`` 变长记录，并返回每个
    CPU set 的 ``EfficiencyClass``。无法完整解析时返回 ``None``。
    """

    payload = bytes(raw_records)
    offset = 0
    efficiency_classes: list[int] = []
    while offset < len(payload):
        if len(payload) - offset < 8:
            return None
        record_size = int.from_bytes(
            payload[offset : offset + 4],
            "little",
        )
        record_type = int.from_bytes(
            payload[offset + 4 : offset + 8],
            "little",
        )
        if record_size < 8 or offset + record_size > len(payload):
            return None
        if record_type == 0:
            if record_size <= 18:
                return None
            efficiency_classes.append(int(payload[offset + 18]))
        offset += record_size
    return tuple(efficiency_classes) or None


def discover_effective_cpu_capacity(
    *,
    host_cpu_count: int | None,
    affinity_cpu_ids: Collection[int] | None,
    cgroup_cpu_max: str | None,
    apple_performance_cpu_count: int | None,
    windows_efficiency_classes: Collection[int] | None = None,
    platform_name: str | None = None,
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
        windows_efficiency_classes: Per-CPU-set Windows efficiency classes;
            larger values represent faster core types. Windows 每个 CPU set
            的效率等级；数值越大表示性能等级越高。
        platform_name: Runtime platform label, injectable for tests.
            运行平台标签，可在测试中注入。

    Returns:
        An immutable effective-capacity description.
        不可变的有效 CPU 容量说明。
    """

    host = _positive_int_or_none(host_cpu_count) or 1
    affinity = _positive_collection_size(affinity_cpu_ids)
    quota = _parse_cgroup_v2_cpu_max(cgroup_cpu_max)
    performance = _positive_int_or_none(apple_performance_cpu_count)
    windows_classes = _normalize_windows_efficiency_classes(
        windows_efficiency_classes,
    )
    windows_performance = (
        windows_classes.count(max(windows_classes))
        if windows_classes
        else None
    )
    platform = str(platform_name or "").lower()
    if performance is not None and performance < host:
        topology: CpuTopology = "heterogeneous"
        scheduling_policy: CpuSchedulingPolicy = (
            "apple_performance_budget"
        )
    elif windows_classes is not None:
        topology = (
            "heterogeneous"
            if len(set(windows_classes)) > 1
            else "homogeneous"
        )
        scheduling_policy = (
            "os_core_type_scheduler"
            if topology == "heterogeneous"
            else "all_visible_cpus"
        )
    elif performance is not None:
        topology = "homogeneous"
        scheduling_policy = "all_visible_cpus"
    elif platform.startswith("linux"):
        topology = "unknown"
        scheduling_policy = "os_capacity_scheduler"
    else:
        topology = "unknown"
        scheduling_policy = "all_visible_cpus"
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
        windows_performance_cpu_count=windows_performance,
        cpu_topology=topology,
        scheduling_policy=scheduling_policy,
    )


def _read_process_affinity(
    *,
    affinity_reader: Callable[[int], Collection[int]] | None = None,
    process_factory: Callable[[], Any] | None = None,
) -> frozenset[int] | None:
    """Read the current process CPU affinity across supported platforms.

    优先使用 POSIX ``sched_getaffinity``；不可用时通过正式运行依赖
    ``psutil`` 读取 Windows/Linux 进程亲和性。
    """

    reader = affinity_reader or getattr(os, "sched_getaffinity", None)
    if callable(reader):
        try:
            affinity = frozenset(int(cpu_id) for cpu_id in reader(0))
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
            affinity = frozenset()
        if affinity:
            return affinity

    if process_factory is None:
        try:
            import psutil

            process_factory = psutil.Process
        except (ImportError, AttributeError):
            return None
    try:
        process = process_factory()
        psutil_reader = getattr(process, "cpu_affinity", None)
        if not callable(psutil_reader):
            return None
        affinity = frozenset(int(cpu_id) for cpu_id in psutil_reader())
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
        return None
    return affinity or None


def _safe_absolute_path_parts(raw_path: str) -> tuple[str, ...] | None:
    if not raw_path.startswith("/") or "\x00" in raw_path:
        return None
    if raw_path == "/":
        return ()
    parts = raw_path[1:].split("/")
    if any(part in {"", ".", ".."} for part in parts):
        return None
    return tuple(parts)


def _decode_mountinfo_path(raw_path: str) -> str | None:
    decoded: list[str] = []
    cursor = 0
    while cursor < len(raw_path):
        if raw_path[cursor] != "\\":
            decoded.append(raw_path[cursor])
            cursor += 1
            continue
        escaped = raw_path[cursor : cursor + 4]
        replacement = _MOUNTINFO_PATH_ESCAPES.get(escaped)
        if replacement is None:
            return None
        decoded.append(replacement)
        cursor += 4
    return "".join(decoded)


def _parse_process_cgroup_v2_path(
    raw_cgroup: str,
) -> tuple[str, ...] | None:
    current_path: tuple[str, ...] | None = None
    for line in raw_cgroup.splitlines():
        fields = line.split(":", 2)
        if len(fields) != 3 or not fields[0].isdecimal():
            return None
        hierarchy_id, controllers, raw_path = fields
        if hierarchy_id != "0" or controllers:
            continue
        if current_path is not None or raw_path.endswith(" (deleted)"):
            return None
        current_path = _safe_absolute_path_parts(raw_path)
        if current_path is None:
            return None
    return current_path


def _parse_cgroup2_mounts(
    raw_mountinfo: str,
) -> tuple[tuple[tuple[str, ...], Path], ...] | None:
    mounts: list[tuple[tuple[str, ...], Path]] = []
    for line in raw_mountinfo.splitlines():
        left, separator, right = line.partition(" - ")
        left_fields = left.split()
        right_fields = right.split()
        if not separator or len(left_fields) < 6 or len(right_fields) < 3:
            return None
        if right_fields[0] != "cgroup2":
            continue
        decoded_root = _decode_mountinfo_path(left_fields[3])
        decoded_mount_point = _decode_mountinfo_path(left_fields[4])
        if decoded_root is None or decoded_mount_point is None:
            return None
        root_parts = _safe_absolute_path_parts(decoded_root)
        mount_point_parts = _safe_absolute_path_parts(decoded_mount_point)
        if root_parts is None or mount_point_parts is None:
            return None
        mounts.append((root_parts, Path("/").joinpath(*mount_point_parts)))
    return tuple(mounts) or None


def _cgroup_cpu_max_candidates(
    current_path: tuple[str, ...],
    mounts: tuple[tuple[tuple[str, ...], Path], ...],
) -> tuple[Path, ...]:
    ranked: list[tuple[bool, int, Path]] = []
    for mount_root, mount_point in mounts:
        root_matches = current_path[: len(mount_root)] == mount_root
        relative_path = (
            current_path[len(mount_root) :]
            if root_matches
            else current_path
        )
        candidate = mount_point.joinpath(*relative_path, "cpu.max")
        try:
            resolved_mount = mount_point.resolve(strict=False)
            resolved_candidate = candidate.resolve(strict=False)
            resolved_candidate.relative_to(resolved_mount)
        except (OSError, RuntimeError, ValueError):
            continue
        ranked.append((root_matches, len(mount_root), resolved_candidate))
    ranked.sort(key=lambda entry: (entry[0], entry[1]), reverse=True)
    return tuple(dict.fromkeys(entry[2] for entry in ranked))


def _read_cgroup_v2_cpu_max(
    *,
    proc_self_cgroup_path: Path = _PROC_SELF_CGROUP_PATH,
    proc_self_mountinfo_path: Path = _PROC_SELF_MOUNTINFO_PATH,
) -> str | None:
    try:
        raw_cgroup = proc_self_cgroup_path.read_text(encoding="utf-8")
        raw_mountinfo = proc_self_mountinfo_path.read_text(encoding="utf-8")
    except (OSError, RuntimeError, UnicodeError):
        return None
    current_path = _parse_process_cgroup_v2_path(raw_cgroup)
    mounts = _parse_cgroup2_mounts(raw_mountinfo)
    if current_path is None or mounts is None:
        return None
    for cpu_max_path in _cgroup_cpu_max_candidates(current_path, mounts):
        try:
            value = cpu_max_path.read_text(encoding="utf-8").strip()
        except (OSError, RuntimeError, UnicodeError):
            continue
        if value:
            return value
    return None


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


def _read_windows_efficiency_classes(
    *,
    platform_name: str = sys.platform,
) -> tuple[int, ...] | None:
    """Read Windows CPU-set efficiency classes through the documented API.

    通过 Windows 官方 CPU Set API 读取核心性能等级。接口缺失、版本过旧
    或返回数据异常时正常回退为 ``None``，不影响转换功能。
    """

    if str(platform_name).lower() != "win32":
        return None
    try:
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        get_cpu_sets = kernel32.GetSystemCpuSetInformation
        get_cpu_sets.argtypes = [
            ctypes.c_void_p,
            wintypes.ULONG,
            ctypes.POINTER(wintypes.ULONG),
            wintypes.HANDLE,
            wintypes.ULONG,
        ]
        get_cpu_sets.restype = wintypes.BOOL

        required = wintypes.ULONG(0)
        get_cpu_sets(None, 0, ctypes.byref(required), None, 0)
        if int(required.value) <= 0:
            return None

        buffer = (ctypes.c_ubyte * int(required.value))()
        returned = wintypes.ULONG(0)
        succeeded = get_cpu_sets(
            ctypes.cast(buffer, ctypes.c_void_p),
            int(required.value),
            ctypes.byref(returned),
            None,
            0,
        )
        if not succeeded or int(returned.value) <= 0:
            return None
        payload = bytes(buffer[: int(returned.value)])
        return _parse_windows_efficiency_classes(payload)
    except (
        AttributeError,
        ctypes.ArgumentError,
        OSError,
        OverflowError,
        TypeError,
        ValueError,
    ):
        return None


def _discover_live_capacity() -> EffectiveCpuCapacity:
    return discover_effective_cpu_capacity(
        host_cpu_count=os.cpu_count(),
        affinity_cpu_ids=_read_process_affinity(),
        cgroup_cpu_max=_read_cgroup_v2_cpu_max(),
        apple_performance_cpu_count=_read_apple_performance_cpu_count(),
        windows_efficiency_classes=_read_windows_efficiency_classes(),
        platform_name=sys.platform,
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
