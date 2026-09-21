"""Geometry and process RSS diagnostics for native Vector mesh generation."""

from __future__ import annotations

import os


def get_process_rss_bytes() -> int | None:
    """Return current process RSS without introducing an API-layer import."""

    try:
        import psutil  # type: ignore[import-not-found]
    except ImportError:
        return None
    try:
        return int(psutil.Process(os.getpid()).memory_info().rss)
    except (OSError, RuntimeError):
        return None


def get_owned_process_group_rss_bytes() -> int | None:
    """Return RSS of this process plus every process it currently owns.

    返回本进程及其当前拥有的全部子进程的 RSS 之和。

    Material workers are children of the task process, so the parent's own RSS
    alone understates what the task uses while results are recovered.
    材质 worker 是任务进程的子进程；只统计父进程 RSS 会低估任务在回收结果期间
    的真实占用。
    """

    try:
        import psutil  # type: ignore[import-not-found]
    except ImportError:
        return None
    try:
        process = psutil.Process(os.getpid())
        total = int(process.memory_info().rss)
        for child in process.children(recursive=True):
            try:
                total += int(child.memory_info().rss)
            except (OSError, RuntimeError, psutil.Error):
                continue
        return total
    except (OSError, RuntimeError, psutil.Error):
        return None


def get_owned_memory_report() -> dict[str, int | str | None]:
    """Describe the whole owned process group and the container charge.

    描述整个自有进程组以及容器计费口径。

    Returns:
        Scalar diagnostics: this process RSS, its children's RSS sum, and the
        cgroup v2 limit/current of this process's own cgroup. The container
        figures use the same path discovery as the CPU quota.
        标量诊断：本进程 RSS、子进程 RSS 之和，以及本进程所属 cgroup 的 v2
        上限与当前用量。容器数值与 CPU 配额使用同一套路径发现逻辑。
    """

    from core.system_capacity import get_effective_memory_capacity

    report: dict[str, int | str | None] = {
        "self_rss_bytes": get_process_rss_bytes(),
        "owned_group_rss_bytes": get_owned_process_group_rss_bytes(),
    }
    try:
        capacity = get_effective_memory_capacity()
    except (ImportError, AttributeError, OSError, RuntimeError, ValueError):
        report.update({
            "container_limit_bytes": None,
            "container_current_bytes": None,
            "container_source": "unavailable",
            "effective_available_bytes": None,
        })
        return report
    report.update({
        "container_limit_bytes": capacity.limit_bytes,
        "container_current_bytes": capacity.container_used_bytes,
        "container_source": capacity.source,
        "effective_available_bytes": capacity.available_bytes,
    })
    return report
