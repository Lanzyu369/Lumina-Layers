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

_PROC_MEMINFO_PATH = Path("/proc/meminfo")
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


def _cgroup_v2_file_candidates_with_mounts(
    current_path: tuple[str, ...],
    mounts: tuple[tuple[tuple[str, ...], Path], ...],
    filename: str,
) -> tuple[tuple[Path, Path], ...]:
    """Rank candidate paths for one control file, with their mount point.

    为某个控制文件排序候选路径，并带上产生该路径的挂载点。

    The mount point is returned so a caller walking up the hierarchy stays
    inside the mount that answered for this process, instead of mixing two
    cgroup2 mounts. 返回挂载点是为了让向父级遍历的调用方始终停留在为本进程
    作答的那个挂载内，而不是把两个 cgroup2 挂载混在一起。
    """

    ranked: list[tuple[bool, int, Path, Path]] = []
    for mount_root, mount_point in mounts:
        root_matches = current_path[: len(mount_root)] == mount_root
        relative_path = (
            current_path[len(mount_root) :]
            if root_matches
            else current_path
        )
        candidate = mount_point.joinpath(*relative_path, filename)
        try:
            resolved_mount = mount_point.resolve(strict=False)
            resolved_candidate = candidate.resolve(strict=False)
            resolved_candidate.relative_to(resolved_mount)
        except (OSError, RuntimeError, ValueError):
            continue
        ranked.append((root_matches, len(mount_root), resolved_candidate, resolved_mount))
    ranked.sort(key=lambda entry: (entry[0], entry[1]), reverse=True)
    unique: dict[Path, Path] = {}
    for _root_matches, _root_length, resolved_candidate, resolved_mount in ranked:
        unique.setdefault(resolved_candidate, resolved_mount)
    return tuple(unique.items())


def _cgroup_v2_file_candidates(
    current_path: tuple[str, ...],
    mounts: tuple[tuple[tuple[str, ...], Path], ...],
    filename: str,
) -> tuple[Path, ...]:
    """Rank candidate paths for one cgroup v2 control file.

    为某个 cgroup v2 控制文件排序候选路径。

    The cgroup path discovery itself is controller-independent, so CPU quota
    and memory limit read the same way; only the file name differs.
    cgroup 路径发现与控制器无关，因此 CPU 配额与内存上限用同一套逻辑读取，
    只有文件名不同。
    """

    return tuple(
        candidate
        for candidate, _mount_point in _cgroup_v2_file_candidates_with_mounts(
            current_path, mounts, filename
        )
    )


def _cgroup_cpu_max_candidates(
    current_path: tuple[str, ...],
    mounts: tuple[tuple[tuple[str, ...], Path], ...],
) -> tuple[Path, ...]:
    return _cgroup_v2_file_candidates(current_path, mounts, "cpu.max")


def _read_cgroup_v2_files(
    filenames: tuple[str, ...],
    *,
    proc_self_cgroup_path: Path = _PROC_SELF_CGROUP_PATH,
    proc_self_mountinfo_path: Path = _PROC_SELF_MOUNTINFO_PATH,
) -> dict[str, str]:
    """Read per-cgroup control files from this process's own cgroup.

    从本进程所属 cgroup 读取指定的控制文件。

    Args:
        filenames: Control file names, for example ``("memory.max",)``.
            控制文件名，例如 ``("memory.max",)``。
        proc_self_cgroup_path: Overridable ``/proc/self/cgroup`` for tests.
            测试可替换的 ``/proc/self/cgroup``。
        proc_self_mountinfo_path: Overridable ``/proc/self/mountinfo``.
            测试可替换的 ``/proc/self/mountinfo``。

    Returns:
        Raw stripped contents keyed by file name; missing/unreadable files are
        absent from the mapping. 以文件名为键的原始内容；缺失或不可读的文件
        不出现在映射中。
    """

    try:
        raw_cgroup = proc_self_cgroup_path.read_text(encoding="utf-8")
        raw_mountinfo = proc_self_mountinfo_path.read_text(encoding="utf-8")
    except (OSError, RuntimeError, UnicodeError):
        return {}
    current_path = _parse_process_cgroup_v2_path(raw_cgroup)
    mounts = _parse_cgroup2_mounts(raw_mountinfo)
    if current_path is None or mounts is None:
        return {}
    values: dict[str, str] = {}
    for filename in filenames:
        for candidate in _cgroup_v2_file_candidates(current_path, mounts, filename):
            try:
                value = candidate.read_text(encoding="utf-8").strip()
            except (OSError, RuntimeError, UnicodeError):
                continue
            if value:
                values[filename] = value
                break
    return values


def _read_cgroup_v2_cpu_max(
    *,
    proc_self_cgroup_path: Path = _PROC_SELF_CGROUP_PATH,
    proc_self_mountinfo_path: Path = _PROC_SELF_MOUNTINFO_PATH,
) -> str | None:
    return _read_cgroup_v2_files(
        ("cpu.max",),
        proc_self_cgroup_path=proc_self_cgroup_path,
        proc_self_mountinfo_path=proc_self_mountinfo_path,
    ).get("cpu.max")


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


MemoryLimitSource = Literal["cgroup_v2", "unrestricted", "unknown", "unavailable"]


@dataclass(frozen=True)
class CgroupMemoryLevel:
    """One visible cgroup v2 memory level, from this process upwards.

    从本进程向上的一个可见 cgroup v2 内存层级。

    Args:
        path: Cgroup path of this level inside the visible mount.
            该层级在可见挂载内的 cgroup 路径。
        limit_bytes: ``memory.max`` as a number, or ``None`` for both ``max``
            and "not readable" - ``limit_known`` tells the two apart.
            ``memory.max`` 的数值；``max`` 与“读不到”都为 ``None``，由
            ``limit_known`` 区分。
        used_bytes: ``memory.current`` of this level, which already includes
            its descendants. 该层级的 ``memory.current``，其中已包含其后代。
        limit_known: ``True`` when this level's ``memory.max`` was read, so
            ``limit_bytes is None`` really means "this level sets no cap".
            该层级的 ``memory.max`` 确实被读到时为 ``True``，此时
            ``limit_bytes is None`` 才真的表示“本层无上限”。
    """

    path: tuple[str, ...]
    limit_bytes: int | None
    used_bytes: int | None
    limit_known: bool


def _read_ranked_memory_file(
    level_path: tuple[str, ...],
    mounts: tuple[tuple[tuple[str, ...], Path], ...],
    filename: str,
    active_mount: Path | None,
) -> tuple[str, Path] | None:
    """Read one memory control file inside the hierarchy that answered.

    在已经作答的那个层级体系内读取一个内存控制文件。

    ``active_mount`` pins the walk to the cgroup2 mount that supplied the
    process's own file, so an ancestor is never taken from a different mount.
    父级只从为进程自身提供文件的同一挂载读取，避免跨挂载混用。
    """

    for candidate, mount_point in _cgroup_v2_file_candidates_with_mounts(
        level_path, mounts, filename
    ):
        if active_mount is not None and mount_point != active_mount:
            continue
        try:
            raw_value = candidate.read_text(encoding="utf-8").strip()
        except (OSError, RuntimeError, UnicodeError):
            continue
        if raw_value:
            return raw_value, mount_point
    return None


def _read_cgroup_v2_memory_levels(
    *,
    proc_self_cgroup_path: Path = _PROC_SELF_CGROUP_PATH,
    proc_self_mountinfo_path: Path = _PROC_SELF_MOUNTINFO_PATH,
) -> tuple[CgroupMemoryLevel, ...] | None:
    """Collect every memory level this process can legitimately observe.

    收集本进程有权观察到的全部内存层级。

    The process's own cgroup is not the whole story: a child that writes
    ``max`` does not lift a finite limit set on a parent. The walk therefore
    starts at the process's cgroup and moves up to the mount root, staying
    inside the one cgroup2 mount that answered, and never inventing an ancestor
    it cannot see. 进程自身 cgroup 不是全部：子级写 ``max`` 并不会解除父级设置的
    有限上限。因此遍历从进程 cgroup 开始向上到挂载根，始终停留在作答的那个
    cgroup2 挂载内，也不会臆造看不到的祖先。

    Returns:
        Levels ordered leaf first, an empty tuple when the mount table was read
        and holds no cgroup2 mount, or ``None`` when this process's cgroup
        membership or mount table could not be read at all. 返回按叶子在前的
        层级序列；读到挂载表但没有 cgroup2 挂载时返回空元组；完全读不到
        cgroup 归属或挂载表时返回 ``None``。
    """

    try:
        raw_cgroup = proc_self_cgroup_path.read_text(encoding="utf-8")
        raw_mountinfo = proc_self_mountinfo_path.read_text(encoding="utf-8")
    except (OSError, RuntimeError, UnicodeError):
        return None
    current_path = _parse_process_cgroup_v2_path(raw_cgroup)
    mounts = _parse_cgroup2_mounts(raw_mountinfo)
    if current_path is None:
        return None
    if mounts is None:
        # ``_parse_cgroup2_mounts`` reports both a malformed table and a table
        # with no cgroup2 entry as ``None``. A table that was read and simply
        # has no cgroup2 mount is a confirmed non-cgroup environment.
        # 该函数把“表格式错误”和“表里没有 cgroup2”都报为 None。表读到了、只是
        # 没有 cgroup2 挂载，属于已确认的非 cgroup 环境。
        if any(" - cgroup2 " in line for line in raw_mountinfo.splitlines()):
            return None
        return ()

    # The shallowest level this process may read is the root of a visible
    # mount. A path outside every mount root is measured from the mount point
    # itself, which is the namespace case.
    shallowest = min(
        len(mount_root) if current_path[: len(mount_root)] == mount_root else 0
        for mount_root, _mount_point in mounts
    )

    levels: list[CgroupMemoryLevel] = []
    active_mount: Path | None = None
    for depth in range(len(current_path) - shallowest + 1):
        level_path = current_path[: len(current_path) - depth]
        limit: int | None = None
        limit_known = False
        limit_file = _read_ranked_memory_file(
            level_path, mounts, "memory.max", active_mount
        )
        if limit_file is not None:
            raw_limit, mount_point = limit_file
            active_mount = active_mount or mount_point
            limit_known = _parse_cgroup_v2_memory_value(raw_limit) is not None or (
                raw_limit.strip() == "max"
            )
            limit = _parse_cgroup_v2_memory_value(raw_limit)
        used: int | None = None
        used_file = _read_ranked_memory_file(
            level_path, mounts, "memory.current", active_mount
        )
        if used_file is not None:
            raw_used, mount_point = used_file
            active_mount = active_mount or mount_point
            used = _parse_cgroup_v2_memory_value(raw_used)
        levels.append(
            CgroupMemoryLevel(
                path=level_path,
                limit_bytes=limit,
                used_bytes=used,
                limit_known=limit_known,
            )
        )
    return tuple(levels)


def _read_cgroup_v2_memory_limit_bytes(
    *,
    proc_self_cgroup_path: Path = _PROC_SELF_CGROUP_PATH,
    proc_self_mountinfo_path: Path = _PROC_SELF_MOUNTINFO_PATH,
) -> int | None:
    """Return the smallest finite memory limit this process is under.

    返回本进程所受到的最小有限内存上限。
    """

    levels = _read_cgroup_v2_memory_levels(
        proc_self_cgroup_path=proc_self_cgroup_path,
        proc_self_mountinfo_path=proc_self_mountinfo_path,
    )
    if not levels:
        return None
    finite = [level.limit_bytes for level in levels if level.limit_bytes is not None]
    return min(finite) if finite else None


@dataclass(frozen=True)
class EffectiveMemoryCapacity:
    """Describe the memory this Lumina process may actually use.

    描述单个 Lumina 进程实际可用的内存。

    ``psutil.virtual_memory().available`` reports host RAM even inside a
    memory-limited container, so a 2 GiB container can be told it has 24 GiB
    free. This snapshot is the one place that reconciles the host figure with
    the cgroup v2 limit of the process's own cgroup.

    受限容器内 ``psutil.virtual_memory().available`` 仍会报告宿主机内存，
    2 GiB 的容器可能被告知有 24 GiB 空闲。本快照是唯一把宿主数字与本进程
    所属 cgroup 的 v2 上限做了核对的地方。

    Args:
        available_bytes: Memory still usable by this process, or ``None`` when
            nothing could be probed. 本进程仍可使用的内存；完全探测不到时为
            ``None``。
        limit_bytes: Hard container cap, or ``None`` when unrestricted.
            容器硬上限；未受限时为 ``None``。
        container_used_bytes: Charge already attributed to this cgroup.
            本 cgroup 已计入的用量。
        host_available_bytes: Raw host-available figure, kept for diagnosis.
            原始宿主可用内存，保留用于诊断。
        source: ``cgroup_v2`` when a finite limit bounded the result,
            ``unrestricted`` when only the host figure was available, and
            ``unavailable`` when neither could be read.
            有限上限生效时为 ``cgroup_v2``；只有宿主数字时为
            ``unrestricted``；两者都读不到时为 ``unavailable``。
    """

    available_bytes: int | None
    limit_bytes: int | None
    container_used_bytes: int | None
    host_available_bytes: int | None
    source: MemoryLimitSource


def _parse_cgroup_v2_memory_value(raw_value: str | None) -> int | None:
    """Parse one cgroup v2 memory value, treating ``max`` as no limit.

    解析一个 cgroup v2 内存值；``max`` 视为无上限。
    """

    if raw_value is None:
        return None
    value = raw_value.strip()
    if not value or value == "max":
        return None
    try:
        parsed = int(value)
    except ValueError:
        return None
    return parsed if parsed >= 0 else None


def _read_proc_meminfo_available_bytes(
    *,
    proc_meminfo_path: Path = _PROC_MEMINFO_PATH,
) -> int | None:
    """Read ``MemAvailable`` from ``/proc/meminfo``.

    Note that ``/proc/meminfo`` is not namespaced: inside a container it still
    reports host memory, which is exactly why the cgroup limit below is
    combined with it instead of replaced by it.
    注意 ``/proc/meminfo`` 没有做命名空间隔离：容器内它仍报告宿主机内存。
    正因如此，下面的 cgroup 上限是与它取较小值，而不是被它替代。
    """

    try:
        raw_text = proc_meminfo_path.read_text(encoding="utf-8")
    except (OSError, RuntimeError, UnicodeError):
        return None
    for line in raw_text.splitlines():
        name, separator, raw_value = line.partition(":")
        if not separator or name != "MemAvailable":
            continue
        fields = raw_value.split()
        if not fields or not fields[0].isdigit():
            return None
        return int(fields[0]) * 1024
    return None


def _host_available_memory_bytes() -> int | None:
    try:
        import psutil

        return max(0, int(psutil.virtual_memory().available))
    except (ImportError, AttributeError, OSError, RuntimeError, ValueError):
        # psutil is optional for this probe; without it the host figure still
        # comes from /proc/meminfo on Linux.
        return _read_proc_meminfo_available_bytes()


def discover_effective_memory_capacity(
    *,
    host_available_bytes: int | None = None,
    cgroup_values: dict[str, str] | None = None,
    proc_self_cgroup_path: Path = _PROC_SELF_CGROUP_PATH,
    proc_self_mountinfo_path: Path = _PROC_SELF_MOUNTINFO_PATH,
) -> EffectiveMemoryCapacity:
    """Reconcile host-available memory with the cgroup v2 limit.

    把宿主可用内存与 cgroup v2 上限做核对。

    Args:
        host_available_bytes: Deterministic host figure for tests. 测试用确定值。
        cgroup_values: Deterministic control-file contents, keyed by file name.
            When supplied the caller has pinned one level, so only that level is
            considered. 测试用确定值的控制文件内容，以文件名为键；提供时表示
            调用方已指定单一层级，因此只看该层级。
        proc_self_cgroup_path: Overridable ``/proc/self/cgroup`` for tests.
            测试可替换的 ``/proc/self/cgroup``。
        proc_self_mountinfo_path: Overridable ``/proc/self/mountinfo``.
            测试可替换的 ``/proc/self/mountinfo``。

    Returns:
        The effective capacity; a finite cgroup limit at any visible level caps
        the host figure, and a container that is already over its limit reports
        zero available rather than a negative number. A level whose limit could
        not be read is reported as ``unknown`` instead of being presented as
        confirmed unlimited. 返回有效容量：任一可见层级的有限 cgroup 上限都压制
        宿主数字；容器已超限时返回 0 而不是负数；读不到上限的层级记为
        ``unknown``，不会呈现为已确认无限制。
    """

    host = (
        _host_available_memory_bytes()
        if host_available_bytes is None
        else max(0, int(host_available_bytes))
    )
    if cgroup_values is not None:
        limit = _parse_cgroup_v2_memory_value(cgroup_values.get("memory.max"))
        used = _parse_cgroup_v2_memory_value(cgroup_values.get("memory.current"))
        if limit is None:
            return EffectiveMemoryCapacity(
                available_bytes=host,
                limit_bytes=None,
                container_used_bytes=used,
                host_available_bytes=host,
                source="unrestricted" if host is not None else "unavailable",
            )
        return _bounded_by_limits(
            [(limit, used)], host, container_used_bytes=used
        )

    levels = _read_cgroup_v2_memory_levels(
        proc_self_cgroup_path=proc_self_cgroup_path,
        proc_self_mountinfo_path=proc_self_mountinfo_path,
    )
    if levels is None:
        # This process's cgroup membership or mount table could not be read.
        # On a platform without cgroup v2 that is a confirmed "no container
        # limit"; on Linux it means the environment could not be inspected, and
        # an uninspected environment must not be presented as confirmation.
        # 完全读不到本进程的 cgroup 归属或挂载表。在没有 cgroup v2 的平台上这
        # 是已确认的“无容器上限”；在 Linux 上则表示环境未能被检查，而未被检查
        # 的环境不能呈现为已确认。
        unchecked_platform = sys.platform.startswith("linux")
        return EffectiveMemoryCapacity(
            available_bytes=host,
            limit_bytes=None,
            container_used_bytes=None,
            host_available_bytes=host,
            source=(
                "unavailable"
                if host is None
                else ("unknown" if unchecked_platform else "unrestricted")
            ),
        )
    used = levels[0].used_bytes if levels else None
    finite = [
        (level.limit_bytes, level.used_bytes)
        for level in levels
        if level.limit_bytes is not None
    ]
    if finite:
        return _bounded_by_limits(finite, host, container_used_bytes=used)
    # No finite limit was found. That is only a confirmed-unlimited reading if
    # every visible level's memory.max was actually read; an unreadable level
    # could be hiding one. 没有找到有限上限；只有每个可见层级的 memory.max 都
    # 确实读到了，才算已确认无限制，读不到的层级可能藏着上限。
    confirmed = bool(levels) and all(level.limit_known for level in levels)
    return EffectiveMemoryCapacity(
        available_bytes=host,
        limit_bytes=None,
        container_used_bytes=used,
        host_available_bytes=host,
        source=(
            ("unrestricted" if host is not None else "unavailable")
            if confirmed
            else "unknown"
        ),
    )


def _bounded_by_limits(
    finite_levels: list[tuple[int | None, int | None]],
    host: int | None,
    *,
    container_used_bytes: int | None = None,
) -> EffectiveMemoryCapacity:
    """Combine finite per-level limits with the host figure.

    把各层级的有限上限与宿主数字合成一个结果。

    Each level contributes ``memory.max - memory.current`` measured at that
    same level, because a parent's ``memory.current`` already includes its
    descendants and its sibling branches; subtracting a leaf's charge from a
    parent's limit would count the same bytes twice. 每个层级贡献各自
    ``memory.max - memory.current``：父级 ``memory.current`` 已包含其后代与兄弟
    分支，用父级上限减叶子用量会把同一批字节算两遍。
    """

    limits = [limit for limit, _used in finite_levels if limit is not None]
    if not limits:
        return EffectiveMemoryCapacity(
            available_bytes=host,
            limit_bytes=None,
            container_used_bytes=container_used_bytes,
            host_available_bytes=host,
            source="unrestricted" if host is not None else "unavailable",
        )
    limit = min(limits)
    remaining = min(
        max(0, level_limit - (level_used or 0))
        for level_limit, level_used in finite_levels
        if level_limit is not None
    )
    available = remaining if host is None else min(host, remaining)
    return EffectiveMemoryCapacity(
        available_bytes=available,
        limit_bytes=limit,
        container_used_bytes=container_used_bytes,
        host_available_bytes=host,
        source="cgroup_v2",
    )


def get_effective_memory_capacity() -> EffectiveMemoryCapacity:
    """Return a live memory-capacity snapshot of this process's environment.

    返回本进程环境的实时内存容量快照。

    Deliberately not cached: available memory changes while a conversion runs.
    有意不做缓存：可用内存会在转换过程中变化。
    """

    return discover_effective_memory_capacity()


@lru_cache(maxsize=1)
def get_effective_memory_limit_bytes() -> int | None:
    """Return the container memory cap, cached because it is stable.

    返回容器内存上限；该值稳定，因此在进程内缓存。可见父级的有限上限也算容器
    上限：只读叶子会漏掉父级约束。
    """

    return _read_cgroup_v2_memory_limit_bytes()
