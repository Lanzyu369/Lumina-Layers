"""Atomic runtime demand state for adaptive task parallelism."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from typing import Iterator
import uuid

DEMAND_SNAPSHOT_VERSION = 1
MAX_REASONABLE_OUTSTANDING_TASKS = 1_000_000

_SNAPSHOT_FIELDS = {
    "version",
    "generation",
    "outstanding",
    "outer_max_workers",
    "updated_monotonic_ns",
}
_RUNTIME_STATE = threading.local()


@dataclass(frozen=True)
class OuterDemandState:
    """Describe current outer process-pool demand for one inner stage.

    描述内部阶段可见的外层进程池当前负载。

    Args:
        outer_demand: Active outer demand used as the CPU/memory divisor.
            用作 CPU 与内存除数的外层活跃任务数。
        outer_max_workers: Configured outer process-pool capacity.
            外层进程池配置容量。
        generation: Monotonic publisher generation, or zero for fallback.
            发布器递增代次；回退状态为零。
        snapshot_fallback: Whether configured capacity replaced live state.
            是否因实时状态不可用而回退到配置容量。
    """

    outer_demand: int
    outer_max_workers: int
    generation: int
    snapshot_fallback: bool


def _positive_int(value: object, *, default: int = 1) -> int:
    if isinstance(value, bool):
        return max(1, int(default))
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return max(1, int(default))
    return parsed if parsed > 0 else max(1, int(default))


def _fallback_state(fallback_outer_workers: int) -> OuterDemandState:
    outer_workers = _positive_int(fallback_outer_workers)
    return OuterDemandState(
        outer_demand=outer_workers,
        outer_max_workers=outer_workers,
        generation=0,
        snapshot_fallback=True,
    )


def _snapshot_int(
    payload: dict[str, object],
    key: str,
    *,
    minimum: int,
    maximum: int = sys.maxsize,
) -> int:
    value = payload.get(key)
    if type(value) is not int:
        raise ValueError(f"{key} must be an integer")
    parsed = int(value)
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"{key} is outside the accepted range")
    return parsed


def read_outer_demand(
    snapshot_path: str | os.PathLike[str] | None,
    *,
    fallback_outer_workers: int,
) -> OuterDemandState:
    """Read one atomic demand snapshot or fail closed to configured demand.

    读取一次原子负载快照；文件无效时安全回退到配置的外层并发数。

    Args:
        snapshot_path: Pool-owned JSON snapshot path, when installed.
            进程池拥有的 JSON 快照路径；未安装时为 ``None``。
        fallback_outer_workers: Configured outer capacity used on read failure.
            读取失败时使用的外层配置容量。

    Returns:
        Validated live state or a conservative fallback state.
        校验后的实时状态或保守回退状态。
    """

    fallback = _fallback_state(fallback_outer_workers)
    if snapshot_path is None:
        return fallback
    try:
        path = Path(os.fspath(snapshot_path))
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, dict) or set(payload) != _SNAPSHOT_FIELDS:
            return fallback
        version = _snapshot_int(
            payload,
            "version",
            minimum=DEMAND_SNAPSHOT_VERSION,
            maximum=DEMAND_SNAPSHOT_VERSION,
        )
        if version != DEMAND_SNAPSHOT_VERSION:
            return fallback
        generation = _snapshot_int(payload, "generation", minimum=0)
        outstanding = _snapshot_int(
            payload,
            "outstanding",
            minimum=0,
            maximum=MAX_REASONABLE_OUTSTANDING_TASKS,
        )
        outer_max_workers = _snapshot_int(
            payload,
            "outer_max_workers",
            minimum=1,
            maximum=MAX_REASONABLE_OUTSTANDING_TASKS,
        )
        _snapshot_int(payload, "updated_monotonic_ns", minimum=0)
    except (
        json.JSONDecodeError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
    ):
        return fallback

    return OuterDemandState(
        outer_demand=max(1, min(outstanding, outer_max_workers)),
        outer_max_workers=outer_max_workers,
        generation=generation,
        snapshot_fallback=False,
    )


class OuterDemandPublisher:
    """Publish bounded outstanding-task state through atomic replacement.

    通过原子替换发布有界的未完成任务状态。

    Args:
        max_workers: Configured outer process-pool capacity.
            外层进程池配置容量。
        parent_dir: Optional parent directory for deterministic tests.
            测试可注入的父目录。
    """

    def __init__(
        self,
        *,
        max_workers: int,
        parent_dir: Path | None = None,
    ) -> None:
        self._max_workers = _positive_int(max_workers)
        self._lock = threading.Lock()
        self._outstanding = 0
        self._generation = 0
        self._closed = False
        self._directory = Path(
            tempfile.mkdtemp(
                prefix="lumina-parallelism-",
                dir=str(parent_dir) if parent_dir is not None else None,
            )
        )
        self._snapshot_path = self._directory / "demand.json"
        with self._lock:
            self._publish_locked()

    @property
    def snapshot_path(self) -> Path:
        """Return the unique atomic snapshot path.

        返回此发布器唯一的原子快照路径。
        """

        return self._snapshot_path

    @property
    def outstanding(self) -> int:
        """Return the in-memory submitted-but-undelivered task count.

        返回内存中的已提交但尚未交付结果的任务数。
        """

        with self._lock:
            return self._outstanding

    def increment(self) -> None:
        """Record one submitted task and publish the new generation.

        记录一个已提交任务并发布新代次。
        """

        with self._lock:
            if self._closed:
                raise RuntimeError("outer demand publisher is closed")
            self._outstanding += 1
            self._generation += 1
            self._publish_locked()

    def decrement(self) -> None:
        """Record one delivered task and publish the new generation.

        记录一个已交付任务并发布新代次。
        """

        with self._lock:
            if self._closed:
                return
            self._outstanding = max(0, self._outstanding - 1)
            self._generation += 1
            self._publish_locked()

    def cleanup(self) -> None:
        """Remove the pool-owned snapshot and temporary directory.

        删除进程池拥有的快照与临时目录；重复调用安全。
        """

        with self._lock:
            if self._closed:
                return
            self._snapshot_path.unlink(missing_ok=True)
            self._directory.rmdir()
            self._closed = True

    def _publish_locked(self) -> None:
        payload = {
            "version": int(DEMAND_SNAPSHOT_VERSION),
            "generation": int(self._generation),
            "outstanding": int(self._outstanding),
            "outer_max_workers": int(self._max_workers),
            "updated_monotonic_ns": int(time.monotonic_ns()),
        }
        temporary_path = self._directory / (
            f".demand-{self._generation}-{uuid.uuid4().hex}.tmp"
        )
        try:
            with temporary_path.open("w", encoding="utf-8") as handle:
                json.dump(
                    payload,
                    handle,
                    ensure_ascii=True,
                    separators=(",", ":"),
                    sort_keys=True,
                )
            for attempt in range(6):
                try:
                    os.replace(temporary_path, self._snapshot_path)
                    break
                except PermissionError:
                    # Windows readers can briefly deny atomic replacement.
                    # Keep the last complete snapshot until the reader closes.
                    if attempt == 5:
                        raise
                    time.sleep(0.005 * (attempt + 1))
        finally:
            temporary_path.unlink(missing_ok=True)


def current_demand_snapshot_path() -> Path | None:
    """Return the worker-local demand snapshot path when installed.

    返回当前 worker 安装的负载快照路径；未安装时为 ``None``。
    """

    return getattr(_RUNTIME_STATE, "demand_snapshot_path", None)


def current_task_host_memory_budget_bytes() -> int | None:
    """Return the host reservation assigned to the current worker task.

    返回父进程为当前 worker 任务预留的主机内存上限；普通 CLI 调用返回
    ``None``，继续使用进程级默认预算。
    """

    value = getattr(_RUNTIME_STATE, "host_memory_budget_bytes", None)
    return int(value) if value is not None else None


@contextmanager
def task_host_memory_budget_scope(
    memory_budget_bytes: int,
) -> Iterator[None]:
    """Install a parent-admitted host memory cap for one worker task.

    为单个 worker 任务安装父进程已准入的主机内存上限。

    Args:
        memory_budget_bytes: Positive bytes reserved for this task.
            为当前任务预留的正整数字节数。
    """

    budget = max(1, int(memory_budget_bytes))
    previous = getattr(_RUNTIME_STATE, "host_memory_budget_bytes", None)
    _RUNTIME_STATE.host_memory_budget_bytes = budget
    try:
        yield
    finally:
        if previous is None:
            try:
                del _RUNTIME_STATE.host_memory_budget_bytes
            except AttributeError:
                pass
        else:
            _RUNTIME_STATE.host_memory_budget_bytes = previous


@contextmanager
def task_parallelism_runtime_scope(
    snapshot_path: str | os.PathLike[str],
) -> Iterator[None]:
    """Install one demand path for a worker task and restore prior state.

    为单个 worker 任务安装负载路径，并在退出时恢复之前的状态。

    Args:
        snapshot_path: Parent-published atomic snapshot path.
            父进程发布的原子快照路径。

    Yields:
        ``None`` while the path is installed for the current thread.
        当前线程安装路径期间返回 ``None``。
    """

    previous = getattr(_RUNTIME_STATE, "demand_snapshot_path", None)
    _RUNTIME_STATE.demand_snapshot_path = Path(os.fspath(snapshot_path))
    try:
        yield
    finally:
        if previous is None:
            try:
                del _RUNTIME_STATE.demand_snapshot_path
            except AttributeError:
                pass
        else:
            _RUNTIME_STATE.demand_snapshot_path = previous
