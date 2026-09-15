"""WorkerPoolManager — ProcessPoolExecutor lifecycle manager.
WorkerPoolManager — ProcessPoolExecutor 生命周期管理器。

Provides an async-friendly interface for submitting CPU-bound tasks
to a process pool, with timeout support and graceful shutdown.
提供异步友好的接口，将 CPU 密集型任务提交到进程池，
支持超时控制和优雅关闭。
"""

from concurrent.futures import CancelledError as FutureCancelledError
from concurrent.futures import Future as ConcurrentFuture
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path
from typing import Any, Callable, Literal, TypeVar
import asyncio
import os
import sys
import threading
import time
import uuid

from api.structured_logging import get_logger
from core.errors import VectorHostMemoryAdmissionError
from core.task_parallelism_runtime import (
    OuterDemandPublisher,
    task_host_memory_budget_scope,
    task_parallelism_runtime_scope,
)
from core.vector_mesh_memory import DEFAULT_VECTOR_MESH_MEMORY_BUDGET_BYTES

T = TypeVar("T")

_log = get_logger(__name__)

_ENV_MAX_TASKS_PER_CHILD = "LUMINA_WORKER_MAX_TASKS_PER_CHILD"
_DEFAULT_MAX_TASKS_PER_CHILD = 20
_DARWIN_DEFAULT_MAX_TASKS_PER_CHILD = 1
_TERMINATE_GRACE_SECONDS = 1.0
_HOST_MEMORY_MIN_HEADROOM_BYTES = 2 * 1024**3
_HOST_MEMORY_HEADROOM_DENOMINATOR = 10
_HOST_MEMORY_SMALL_TASK_HEADROOM_BYTES = 1024**3
_HOST_MEMORY_SMALL_TASK_MAX_BYTES = 2 * 1024**3


def _available_host_memory_bytes() -> int | None:
    """Return memory this pool may still admission against.

    返回本进程池仍可用于准入的内存。

    Container-aware: a memory-limited container must not admit tasks from the
    host's available figure, which is what ``psutil`` reports inside cgroup v2.
    已计入容器上限：受限容器不能按宿主机可用内存（cgroup v2 下 psutil 的
    返回值）来准入任务。
    """

    try:
        from core.system_capacity import get_effective_memory_capacity

        return get_effective_memory_capacity().available_bytes
    except (ImportError, AttributeError, OSError, RuntimeError, ValueError):
        return None


def _usable_host_memory_bytes(available_memory_bytes: int) -> int:
    """Reserve non-worker headroom from one available-memory sample."""

    available = max(0, int(available_memory_bytes))
    headroom = max(
        _HOST_MEMORY_MIN_HEADROOM_BYTES,
        available // _HOST_MEMORY_HEADROOM_DENOMINATOR,
    )
    return max(0, available - headroom)


class _HostMemoryReservationGate:
    """Atomically bound participating tasks inside one production pool."""

    def __init__(
        self,
        *,
        memory_budget_bytes: int,
        sample_live_memory: bool,
    ) -> None:
        self._memory_budget_bytes = max(1, int(memory_budget_bytes))
        self._sample_live_memory = bool(sample_live_memory)
        self._lock = threading.Lock()
        self._reservations: dict[str, tuple[int, object]] = {}

    @property
    def memory_budget_bytes(self) -> int:
        return self._memory_budget_bytes

    @property
    def reserved_bytes(self) -> int:
        with self._lock:
            return sum(amount for amount, _owner in self._reservations.values())

    def acquire(
        self,
        requested_bytes: int,
        *,
        owner: object,
        parallel_target_bytes: int | None = None,
    ) -> tuple[str, int]:
        """Reserve one full task cap or raise before it enters the pool.

        ``parallel_target_bytes`` lets the task hand over the budget its own
        stage needs to use more of the machine in parallel. The extension is
        granted atomically, inside the same capacity this gate already
        respects: only the part that is still free, never above the request,
        and never below ``requested_bytes``. A task that cannot get it keeps
        its required reservation and runs with lower parallelism instead of
        being refused, so scarce memory degrades throughput, not success.
        ``parallel_target_bytes`` 让任务交出其阶段并行所需的预算；扩展在与本闸门
        既有一致的容量内原子授予：只给仍然空闲的部分，不超过请求值，也不低于
        ``requested_bytes``。拿不到扩展的任务仍保留必需预留、以较低并行度运行而
        不是被拒绝——内存紧张降低的是吞吐，不是成功率。
        """

        requested = max(1, int(requested_bytes))
        with self._lock:
            reserved = sum(
                amount for amount, _owner in self._reservations.values()
            )
            capacity = self._memory_budget_bytes
            if self._sample_live_memory:
                available = _available_host_memory_bytes()
                if available is None:
                    raise VectorHostMemoryAdmissionError(
                        requested,
                        reserved,
                        capacity,
                        "memory_probe_unavailable",
                    )
                capacity = min(
                    capacity,
                    _usable_host_memory_bytes(available),
                )
                if reserved == 0 and requested <= _HOST_MEMORY_SMALL_TASK_MAX_BYTES:
                    # A low-memory desktop may have less than the normal 2 GiB
                    # headroom available even when no Lumina work is running.
                    # Admit exactly one fully budgeted small task while still
                    # leaving 1 GiB for the OS/UI. Any concurrent task uses the
                    # stricter normal capacity because ``reserved`` is nonzero.
                    single_small_task_capacity = min(
                        self._memory_budget_bytes,
                        max(
                            0,
                            available - _HOST_MEMORY_SMALL_TASK_HEADROOM_BYTES,
                        ),
                    )
                    capacity = max(capacity, single_small_task_capacity)
            # A reservation is also the worker-local safety budget.  Never
            # silently shrink it to whatever happens to be free: Vector work
            # performs bounded-but-nonzero parsing before the 3D mesh guard,
            # so an arbitrarily small "successful" reservation would not be a
            # meaningful admission guarantee.
            task_budget = requested
            if (
                task_budget > self._memory_budget_bytes
                or reserved + task_budget > capacity
            ):
                raise VectorHostMemoryAdmissionError(
                    requested,
                    reserved,
                    capacity,
                    "host_capacity_busy",
                )
            if parallel_target_bytes is not None:
                target = max(task_budget, int(parallel_target_bytes))
                spare = max(0, capacity - reserved - task_budget)
                extension = max(0, min(target - task_budget, spare))
                if extension:
                    _log.debug(
                        "Host memory parallel extension granted",
                        extra={
                            "event": "worker_pool_memory_extension",
                            "requested_bytes": requested,
                            "parallel_target_bytes": target,
                            "granted_bytes": task_budget + extension,
                            "extension_bytes": extension,
                            "spare_bytes": spare,
                        },
                    )
                task_budget += extension
            token = uuid.uuid4().hex
            self._reservations[token] = (task_budget, owner)
            return token, task_budget

    def release(self, token: str) -> None:
        """Idempotently release a reservation after its executor future ends."""

        with self._lock:
            self._reservations.pop(str(token), None)

    def release_owner(self, owner: object) -> None:
        """Release all reservations for an executor proven to be stopped."""

        with self._lock:
            for token, (_amount, reservation_owner) in list(
                self._reservations.items()
            ):
                if reservation_owner is owner:
                    self._reservations.pop(token, None)


def _default_max_tasks_per_child() -> int:
    return _DARWIN_DEFAULT_MAX_TASKS_PER_CHILD if sys.platform == "darwin" else _DEFAULT_MAX_TASKS_PER_CHILD


def _resolve_max_tasks_per_child() -> int | None:
    """Resolve LUMINA_WORKER_MAX_TASKS_PER_CHILD into a ProcessPoolExecutor arg.
    解析 LUMINA_WORKER_MAX_TASKS_PER_CHILD 环境变量为 ProcessPoolExecutor 参数.

    Behavior:
        - Unset / empty: returns the platform default.
        - Positive int: returns that value (custom recycle threshold).
        - 0 or negative: returns ``None`` (disable recycling, preserve old behavior).
        - Invalid (non-int): emits a structured WARNING and returns the default.

    行为:
        - 未设置或为空: 返回平台默认值.
        - 正整数: 返回该值 (自定义回收阈值).
        - 0 或负数: 返回 None (禁用回收, 保留旧行为).
        - 非法值 (非整数): 打结构化 WARNING 后回退到默认值.

    Returns:
        int | None: The ``max_tasks_per_child`` argument for ``ProcessPoolExecutor``.
                    (传给 ``ProcessPoolExecutor`` 的 ``max_tasks_per_child`` 参数)
    """
    raw = os.environ.get(_ENV_MAX_TASKS_PER_CHILD)
    fallback = _default_max_tasks_per_child()
    if raw is None or raw == "":
        return fallback
    try:
        value = int(raw)
    except ValueError:
        _log.warning(
            "Invalid LUMINA_WORKER_MAX_TASKS_PER_CHILD value; falling back to default",
            extra={
                "event": "worker_pool_max_tasks_invalid",
                "raw_value": raw,
                "error_type": "ValueError",
                "error_message": (
                    f"{_ENV_MAX_TASKS_PER_CHILD} must be an integer; got {raw!r}"
                ),
                "fallback": fallback,
            },
        )
        return fallback
    if value <= 0:
        return None
    return value


def _normalize_windows_output_stream(stream: Any) -> Any:
    """Return a writable UTF-8 stream for a Windows worker process.

    PyInstaller windowed executables intentionally expose ``None`` for the
    standard streams.  Workers still need a harmless target because logging
    libraries may inspect or write to those streams during initialization.
    """

    if stream is None:
        return open(  # noqa: SIM115 - process-lifetime fallback stream.
            os.devnull,
            "w",
            encoding="utf-8",
            errors="replace",
        )
    reconfigure = getattr(stream, "reconfigure", None)
    if callable(reconfigure):
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass
    return stream


def _worker_smoke_task() -> int:
    """Return the worker PID for the frozen-runtime CI smoke test."""

    return os.getpid()


def _worker_init() -> None:
    """Worker process initializer: force UTF-8 stdout/stderr on Windows,
    then redirect stdout to the same log file as the main process.
    工作进程初始化器：在 Windows 上强制 UTF-8 编码，并将 stdout 重定向到主进程日志文件。
    """
    if sys.platform == "win32":
        sys.stdout = _normalize_windows_output_stream(sys.stdout)
        sys.stderr = _normalize_windows_output_stream(sys.stderr)

    log_path = os.environ.get("LUMINA_LOG_PATH")
    if log_path:
        try:
            from api.logger import setup_file_logging
            from api.structured_logging import configure_structured_logging

            setup_file_logging(log_path=log_path)
            configure_structured_logging()
        except Exception:
            pass


def _run_in_worker_with_context(
    fn: Callable[..., T],
    request_id: str | None,
    session_id: str | None,
    demand_snapshot_path: str | None,
    host_memory_budget_bytes: int | None,
    *args: Any,
    worker_lease_path: str | None = None,
) -> T:
    """Replay parent-side contextvars inside the worker process before invoking fn.

    在 worker 子进程中重放父进程的 request_id 与 session_id 后再执行 fn，
    保证 worker 内部 logger 输出的事件能溯源到发起的 HTTP 请求。

    ``worker_lease_path`` 由调用方以关键字传入：内部阶段据此登记自己实际启动的
    worker 数，使错峰到达的任务看到真实占用而不是重新静态均分。
    """
    from api.structured_logging import set_request_id, set_session_id

    if request_id is not None:
        set_request_id(request_id)
    if session_id is not None:
        set_session_id(session_id)
    if (
        demand_snapshot_path is None
        and host_memory_budget_bytes is None
        and worker_lease_path is None
    ):
        return fn(*args)
    if demand_snapshot_path is None:
        with task_host_memory_budget_scope(host_memory_budget_bytes):
            return fn(*args)
    if host_memory_budget_bytes is None:
        with task_parallelism_runtime_scope(demand_snapshot_path, worker_lease_path):
            return fn(*args)
    with (
        task_parallelism_runtime_scope(demand_snapshot_path, worker_lease_path),
        task_host_memory_budget_scope(host_memory_budget_bytes),
    ):
        return fn(*args)


def _run_in_worker_with_context_timed(
    fn: Callable[..., T],
    request_id: str | None,
    session_id: str | None,
    demand_snapshot_path: str | None,
    host_memory_budget_bytes: int | None,
    *args: Any,
    worker_lease_path: str | None = None,
) -> tuple[T, int, int]:
    """Run one contextualized task and return worker-local timing bounds."""
    worker_started_ns = time.perf_counter_ns()
    result = _run_in_worker_with_context(
        fn,
        request_id,
        session_id,
        demand_snapshot_path,
        host_memory_budget_bytes,
        *args,
        worker_lease_path=worker_lease_path,
    )
    worker_finished_ns = time.perf_counter_ns()
    return result, worker_started_ns, worker_finished_ns


def _normalize_timeout(timeout: float | None) -> float | None:
    """Normalize non-positive task timeouts to disabled.

    将非正数任务超时归一化为禁用状态。
    """
    if timeout is None:
        return None
    value = float(timeout)
    if value <= 0:
        return None
    return value


def _shutdown_executor(
    executor: ProcessPoolExecutor,
    *,
    wait: bool,
    cancel_futures: bool,
) -> None:
    """Shutdown a process executor while supporting older Python signatures."""

    try:
        executor.shutdown(wait=wait, cancel_futures=cancel_futures)
    except TypeError:
        executor.shutdown(wait=wait)


def _terminate_executor_workers(
    executor: ProcessPoolExecutor,
) -> tuple[int, int]:
    """Terminate worker processes owned by a ProcessPoolExecutor.

    ``asyncio.wait_for`` can cancel the parent-side wait, but it cannot stop
    the child process that is already executing. We intentionally use the
    executor's private process table here because Python 3.12 does not expose
    ``terminate_workers()`` / ``kill_workers()`` yet.

    ``asyncio.wait_for`` 只能取消父进程等待，不能停止已经执行中的子进程。
    Python 3.12 尚未提供公开的 terminate/kill worker API，因此这里有意
    使用 executor 的私有进程表。
    """

    processes = getattr(executor, "_processes", None)
    if not processes:
        return 0, 0

    terminated = 0
    survivors = 0
    for proc in list(processes.values()):
        if proc is None or not proc.is_alive():
            continue
        try:
            proc.terminate()
            proc.join(timeout=_TERMINATE_GRACE_SECONDS)
            if proc.is_alive():
                kill = getattr(proc, "kill", None)
                if callable(kill):
                    kill()
                    proc.join(timeout=_TERMINATE_GRACE_SECONDS)
            if proc.is_alive():
                survivors += 1
                _log.error(
                    "Worker process survived terminate and kill",
                    extra={
                        "event": "worker_pool_process_terminate_failed",
                        "pid": getattr(proc, "pid", None),
                        "error_type": "WorkerStillAlive",
                        "error_message": (
                            "Worker process is still alive after terminate/kill"
                        ),
                    },
                )
            else:
                terminated += 1
        except (OSError, RuntimeError, ValueError) as exc:
            try:
                still_alive = bool(proc.is_alive())
            except (OSError, RuntimeError, ValueError):
                still_alive = True
            survivors += int(still_alive)
            _log.warning(
                "Failed to terminate timed-out worker process",
                extra={
                    "event": "worker_pool_process_terminate_failed",
                    "pid": getattr(proc, "pid", None),
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                },
            )
    return terminated, survivors


class WorkerPoolManager:
    """Manage a ProcessPoolExecutor for CPU-bound tasks.
    管理用于 CPU 密集型任务的进程池。

    Attributes:
        _max_workers (int): Maximum number of worker processes. (最大工作进程数)
        _max_tasks_per_child (int | None): Tasks each child handles before being
            recycled, or ``None`` to disable recycling.
            (每个子进程被回收前可处理的任务数，``None`` 表示禁用回收)
        _pool (ProcessPoolExecutor | None): The underlying executor. (底层执行器)
    """

    def __init__(
        self,
        max_workers: int | None = None,
        default_task_timeout: float | None = None,
        host_memory_budget_bytes: int | None = None,
    ) -> None:
        """Initialize WorkerPoolManager.
        初始化 WorkerPoolManager。

        Args:
            max_workers (int | None): Max worker processes. Defaults to min(cpu_count, 4).
                                      (最大工作进程数，默认 min(cpu_count, 4))
            default_task_timeout (float | None): Default seconds before a task
                times out. Non-positive values disable the default timeout.
                (默认任务超时秒数；非正数表示禁用默认超时)
            host_memory_budget_bytes (int | None): Optional fixed admission
                ceiling, primarily for deterministic tests. Production derives
                the ceiling from host-available memory with reserved headroom.
                (可选的固定准入上限，主要用于确定性测试；生产环境会从主机
                可用内存扣除余量后计算)

        The per-child recycle threshold is read once from
        ``LUMINA_WORKER_MAX_TASKS_PER_CHILD`` (default 20) so each pool instance
        captures its env value at construction time.
        子进程回收阈值在构造时从 ``LUMINA_WORKER_MAX_TASKS_PER_CHILD`` 读一次
        (默认 20)，保证每个 pool 实例捕获自己的环境变量快照。
        """
        self._max_workers: int = max_workers or min(os.cpu_count() or 2, 4)
        self._max_tasks_per_child: int | None = _resolve_max_tasks_per_child()
        self._default_task_timeout: float | None = _normalize_timeout(
            default_task_timeout
        )
        self._pool: ProcessPoolExecutor | None = None
        self._pool_lock = threading.RLock()
        self._demand_publisher: OuterDemandPublisher | None = (
            self._create_demand_publisher()
        )
        available_memory = (
            _available_host_memory_bytes()
            if host_memory_budget_bytes is None
            else None
        )
        resolved_host_budget = (
            max(
                DEFAULT_VECTOR_MESH_MEMORY_BUDGET_BYTES,
                _usable_host_memory_bytes(available_memory),
            )
            if available_memory is not None
            else (
                int(host_memory_budget_bytes)
                if host_memory_budget_bytes is not None
                else DEFAULT_VECTOR_MESH_MEMORY_BUDGET_BYTES
            )
        )
        self._host_memory_gate = _HostMemoryReservationGate(
            memory_budget_bytes=max(1, resolved_host_budget),
            sample_live_memory=host_memory_budget_bytes is None,
        )
        self._active_task_lock = threading.Lock()
        self._active_tasks: dict[
            str,
            tuple[object, OuterDemandPublisher | None, str | None],
        ] = {}

    def _create_demand_publisher(self) -> OuterDemandPublisher | None:
        """Create isolated demand state without making it a startup dependency."""

        try:
            return OuterDemandPublisher(max_workers=self._max_workers)
        except (OSError, RuntimeError, ValueError) as exc:
            _log.warning(
                "Failed to initialize worker-pool demand state",
                extra={
                    "event": "worker_pool_demand_init_failed",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "max_workers": self._max_workers,
                },
            )
            return None

    def _update_demand(
        self,
        publisher: OuterDemandPublisher | None,
        operation: Literal["increment", "decrement"],
    ) -> None:
        """Publish one demand transition without changing task outcomes."""

        if publisher is None:
            return
        try:
            getattr(publisher, operation)()
        except (OSError, RuntimeError, ValueError) as exc:
            _log.warning(
                "Failed to publish worker-pool demand",
                extra={
                    "event": "worker_pool_demand_update_failed",
                    "operation": operation,
                    "path": str(publisher.snapshot_path),
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                },
            )

    def _register_active_task(
        self,
        *,
        owner: object,
        publisher: OuterDemandPublisher | None,
        reservation_token: str | None,
    ) -> str:
        """Track one executor task until its underlying work is truly done."""

        token = uuid.uuid4().hex
        with self._active_task_lock:
            self._active_tasks[token] = (
                owner,
                publisher,
                reservation_token,
            )
        self._update_demand(publisher, "increment")
        return token

    def _complete_active_task(self, token: str) -> None:
        """Idempotently release demand and memory for one finished task."""

        with self._active_task_lock:
            state = self._active_tasks.pop(token, None)
        if state is None:
            return
        _owner, publisher, reservation_token = state
        if reservation_token is not None:
            self._host_memory_gate.release(reservation_token)
        self._update_demand(publisher, "decrement")

    def _complete_executor_generation(self, owner: object) -> None:
        """Complete every task owned by an executor confirmed to be stopped."""

        with self._active_task_lock:
            tokens = [
                token
                for token, (task_owner, _publisher, _reservation) in (
                    self._active_tasks.items()
                )
                if task_owner is owner
            ]
        for token in tokens:
            self._complete_active_task(token)

    def start(self) -> None:
        """Initialize the process pool.
        初始化进程池。
        """
        with self._pool_lock:
            if self._pool is not None:
                return
            if self._demand_publisher is None:
                self._demand_publisher = self._create_demand_publisher()
            self._pool = ProcessPoolExecutor(
                max_workers=self._max_workers,
                initializer=_worker_init,
                max_tasks_per_child=self._max_tasks_per_child,
            )

    def _restart_after_failed_pool(
        self,
        failed_pool: ProcessPoolExecutor,
        *,
        reason: str,
        timeout: float | None = None,
    ) -> None:
        """Replace a failed executor with a fresh process pool."""

        error_message = (
            f"Task exceeded {timeout:.3f}s timeout; worker pool restarted"
            if reason == "task_timeout" and timeout is not None
            else f"Worker pool restarted after {reason}"
        )
        with self._pool_lock:
            if self._pool is not failed_pool:
                return
            terminated, surviving_workers = _terminate_executor_workers(
                failed_pool
            )
            _shutdown_executor(failed_pool, wait=False, cancel_futures=True)
            if surviving_workers == 0:
                self._complete_executor_generation(failed_pool)
                self._host_memory_gate.release_owner(failed_pool)
            self._pool = None
            _log.warning(
                "Worker pool restarted after failed task",
                extra={
                    "event": "worker_pool_restarted",
                    "reason": reason,
                    "timeout_s": timeout,
                    "terminated_workers": terminated,
                    "surviving_workers": surviving_workers,
                    "max_workers": self._max_workers,
                    "error_type": reason,
                    "error_message": error_message,
                },
            )
            self.start()

    async def submit(
        self,
        fn: Callable[..., T],
        *args: Any,
        timeout: float | None = None,
        host_memory_reservation_bytes: int | None = None,
        host_memory_parallel_target_bytes: int | None = None,
    ) -> T:
        """Submit a CPU task to the pool and await result.
        提交 CPU 任务到进程池并等待结果。

        Args:
            fn (Callable[..., T]): Top-level function (must be picklable).
                                   (顶层函数，必须可序列化)
            *args (Any): Scalar args or file paths only.
                         (仅标量参数或文件路径)
            timeout (float | None): Max seconds to wait. ``None`` uses the
                pool default; non-positive values disable timeout for this call.
                (最大等待秒数；``None`` 使用池默认值；非正数表示本次调用不限时)
            host_memory_reservation_bytes (int | None): Optional memory cap
                reserved atomically in the parent before this task enters the
                process pool. (可选；任务入池前由父进程原子预留的内存上限)
            host_memory_parallel_target_bytes (int | None): Budget this task's
                own stage needs to use more workers; granted only up to the
                memory still free, and never below the reservation above.
                (可选；本任务阶段并行所需预算，只在空闲内存内授予，
                且不低于上面的预留)

        Returns:
            T: Function return value. (函数返回值)

        Raises:
            asyncio.TimeoutError: If task exceeds timeout. (任务超时)
            RuntimeError: If pool not started. (进程池未启动)

        Parent-side contextvars (request_id / session_id) are captured at call
        time and replayed inside the worker process, so worker-emitted log
        records carry the same correlation IDs as the originating endpoint.
        父进程当前的 request_id / session_id 会在调用时被快照，并在 worker
        子进程内重放，使得 worker 发出的日志可与 endpoint 的请求关联。
        """
        result, _timing = await self._submit_internal(
            fn,
            args,
            timeout=timeout,
            include_timing=False,
            host_memory_reservation_bytes=host_memory_reservation_bytes,
            host_memory_parallel_target_bytes=host_memory_parallel_target_bytes,
        )
        return result

    async def submit_timed(
        self,
        fn: Callable[..., T],
        *args: Any,
        timeout: float | None = None,
        host_memory_reservation_bytes: int | None = None,
        host_memory_parallel_target_bytes: int | None = None,
    ) -> tuple[T, dict[str, float]]:
        """Submit a CPU task and return separate pool timing metadata.

        提交 CPU 任务，并将进程池计时作为独立元数据返回，不修改 worker
        的原始返回值。

        Args:
            fn: Top-level picklable worker function. 顶层可序列化 worker 函数。
            *args: Scalar arguments or file paths. 标量参数或文件路径。
            timeout: Optional per-call timeout. 可选的单次调用超时。
            host_memory_reservation_bytes: Optional parent-side atomic memory
                reservation. 可选的父进程原子内存预留。
            host_memory_parallel_target_bytes: Optional budget this task's own
                stage needs to run more of its work in parallel; bounded by the
                memory still free. 可选；本任务阶段并行所需预算，受空闲内存约束。

        Returns:
            tuple: ``(worker_result, timing_seconds)``. worker 原始结果与秒级计时。
        """
        result, timing = await self._submit_internal(
            fn,
            args,
            timeout=timeout,
            include_timing=True,
            host_memory_reservation_bytes=host_memory_reservation_bytes,
            host_memory_parallel_target_bytes=host_memory_parallel_target_bytes,
        )
        if timing is None:  # Defensive invariant; timed submissions set it.
            raise RuntimeError("Timed worker submission returned no timing")
        return result, timing

    def _complete_future_task(
        self,
        completed: ConcurrentFuture[Any],
        task_token: str,
    ) -> None:
        """Complete a task unless a broken pool may still have a live worker."""

        if completed.cancelled():
            self._complete_active_task(task_token)
            return
        try:
            exception = completed.exception()
        except FutureCancelledError:
            self._complete_active_task(task_token)
            return
        if isinstance(exception, BrokenProcessPool):
            # CPython marks futures broken before it terminates every worker.
            # The restart path releases the executor generation only after all
            # known child processes are confirmed stopped.
            return
        self._complete_active_task(task_token)

    async def _submit_internal(
        self,
        fn: Callable[..., T],
        args: tuple[Any, ...],
        *,
        timeout: float | None,
        include_timing: bool,
        host_memory_reservation_bytes: int | None,
        host_memory_parallel_target_bytes: int | None = None,
    ) -> tuple[T, dict[str, float] | None]:
        """Run one task while preserving the public ``submit`` return contract."""
        pool = self._pool
        if pool is None:
            raise RuntimeError("WorkerPool not started")
        from api.structured_logging import get_request_id, get_session_id

        loop = asyncio.get_running_loop()
        request_id = get_request_id()
        session_id = get_session_id()
        effective_timeout = _normalize_timeout(
            timeout if timeout is not None else self._default_task_timeout
        )
        worker_entry = (
            _run_in_worker_with_context_timed
            if include_timing
            else _run_in_worker_with_context
        )
        demand_publisher = self._demand_publisher
        demand_snapshot_path = (
            str(demand_publisher.snapshot_path)
            if demand_publisher is not None
            else None
        )
        worker_lease_path = (
            str(demand_publisher.worker_lease_path)
            if demand_publisher is not None
            else None
        )
        reservation_token: str | None = None
        task_host_memory_budget: int | None = None
        if host_memory_reservation_bytes is not None:
            reservation_token, task_host_memory_budget = (
                self._host_memory_gate.acquire(
                    host_memory_reservation_bytes,
                    owner=pool,
                    parallel_target_bytes=host_memory_parallel_target_bytes,
                )
            )
        active_task_token = self._register_active_task(
            owner=pool,
            publisher=demand_publisher,
            reservation_token=reservation_token,
        )
        submitted_ns = time.perf_counter_ns() if include_timing else None
        executor_future = None
        try:
            executor_future = pool.submit(
                worker_entry,
                fn,
                request_id,
                session_id,
                demand_snapshot_path,
                task_host_memory_budget,
                *args,
                worker_lease_path=worker_lease_path,
            )
            executor_future.add_done_callback(
                lambda completed, token=active_task_token: (
                    self._complete_future_task(
                        completed,
                        token,
                    )
                )
            )
            future = asyncio.wrap_future(executor_future, loop=loop)
            raw_result = await asyncio.wait_for(
                asyncio.shield(future),
                timeout=effective_timeout,
            )
            if not include_timing:
                return raw_result, None
            (
                result,
                worker_started_ns,
                worker_finished_ns,
            ) = raw_result
            received_ns = time.perf_counter_ns()
            if submitted_ns is None:
                raise RuntimeError("Timed worker submission has no start time")
            timing = {
                "queue_wait_s": max(
                    0.0,
                    (worker_started_ns - submitted_ns) / 1_000_000_000,
                ),
                "worker_execution_s": max(
                    0.0,
                    (worker_finished_ns - worker_started_ns) / 1_000_000_000,
                ),
                "result_delivery_s": max(
                    0.0,
                    (received_ns - worker_finished_ns) / 1_000_000_000,
                ),
                "pool_roundtrip_s": max(
                    0.0,
                    (received_ns - submitted_ns) / 1_000_000_000,
                ),
            }
            _log.debug(
                "Worker pool task timing",
                extra={
                    "event": "worker_pool_task_timing",
                    "worker_name": getattr(fn, "__name__", type(fn).__name__),
                    **timing,
                },
            )
            return result, timing
        except asyncio.TimeoutError:
            if executor_future is not None:
                executor_future.cancel()
            self._restart_after_failed_pool(
                pool,
                reason="task_timeout",
                timeout=effective_timeout,
            )
            raise
        except BrokenProcessPool:
            self._restart_after_failed_pool(pool, reason="broken_process_pool")
            raise
        finally:
            if executor_future is None:
                self._complete_active_task(active_task_token)

    def shutdown(self, wait: bool = True) -> None:
        """Shutdown the pool gracefully.
        优雅关闭进程池。

        Args:
            wait (bool): Whether to wait for pending tasks to complete.
                         (是否等待待处理任务完成)
        """
        with self._pool_lock:
            if self._pool is not None:
                _shutdown_executor(
                    self._pool,
                    wait=wait,
                    cancel_futures=not wait,
                )
                self._pool = None
            publisher = self._demand_publisher
            if publisher is not None:
                try:
                    publisher.cleanup()
                except (OSError, RuntimeError, ValueError) as exc:
                    _log.warning(
                        "Failed to clean up worker-pool demand state",
                        extra={
                            "event": "worker_pool_demand_cleanup_failed",
                            "path": str(publisher.snapshot_path),
                            "error_type": type(exc).__name__,
                            "error_message": str(exc),
                        },
                    )
                else:
                    self._demand_publisher = None

    @property
    def is_alive(self) -> bool:
        """Check if the pool is running.
        检查进程池是否正在运行。

        Returns:
            bool: True if pool is initialized and not shut down. (进程池已初始化且未关闭)
        """
        return self._pool is not None

    @property
    def max_workers(self) -> int:
        """Get the maximum number of worker processes.
        获取最大工作进程数。

        Returns:
            int: Max workers count. (最大工作进程数)
        """
        return self._max_workers

    @property
    def demand_snapshot_path(self) -> Path | None:
        """Get the current pool-owned demand snapshot path.

        获取当前进程池拥有的负载快照路径。

        Returns:
            Path | None: Active path, or ``None`` when optional telemetry is
                unavailable. 当前有效路径；可选遥测不可用时为 ``None``。
        """

        publisher = self._demand_publisher
        return publisher.snapshot_path if publisher is not None else None

    @property
    def outstanding_tasks(self) -> int:
        """Get submitted tasks whose result has not been delivered.

        获取已提交但结果尚未交付的任务数。

        Returns:
            int: Current in-memory outstanding count.
                当前内存中的未完成任务数。
        """

        publisher = self._demand_publisher
        return publisher.outstanding if publisher is not None else 0

    @property
    def host_memory_reserved_bytes(self) -> int:
        """Return bytes promised to still-live executor futures.

        返回已承诺给仍可能运行的 executor future 的主机内存字节数。
        """

        return self._host_memory_gate.reserved_bytes

    @property
    def host_memory_budget_bytes(self) -> int:
        """Return this production pool's fixed host admission ceiling.

        返回当前生产进程池的固定主机内存准入上限。
        """

        return self._host_memory_gate.memory_budget_bytes

    @property
    def max_tasks_per_child(self) -> int | None:
        """Get the per-child task recycling threshold.
        获取每个子进程的任务回收阈值。

        Returns:
            int | None: Max tasks a worker handles before being recycled, or
                ``None`` if recycling is disabled.
                (子进程被回收前可处理的最大任务数，``None`` 表示禁用回收)
        """
        return self._max_tasks_per_child

    @property
    def default_task_timeout(self) -> float | None:
        """Get the default task timeout in seconds, or None when disabled.
        获取默认任务超时秒数；禁用时返回 None。
        """
        return self._default_task_timeout
