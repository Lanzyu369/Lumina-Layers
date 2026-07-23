"""WorkerPoolManager — ProcessPoolExecutor lifecycle manager.
WorkerPoolManager — ProcessPoolExecutor 生命周期管理器。

Provides an async-friendly interface for submitting CPU-bound tasks
to a process pool, with timeout support and graceful shutdown.
提供异步友好的接口，将 CPU 密集型任务提交到进程池，
支持超时控制和优雅关闭。
"""

from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from typing import Any, Callable, TypeVar
import asyncio
import io
import os
import sys
import threading

from api.structured_logging import get_logger

T = TypeVar("T")

_log = get_logger(__name__)

_ENV_MAX_TASKS_PER_CHILD = "LUMINA_WORKER_MAX_TASKS_PER_CHILD"
_DEFAULT_MAX_TASKS_PER_CHILD = 20
_DARWIN_DEFAULT_MAX_TASKS_PER_CHILD = 1
_TERMINATE_GRACE_SECONDS = 1.0


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


def _worker_init() -> None:
    """Worker process initializer: force UTF-8 stdout/stderr on Windows,
    then redirect stdout to the same log file as the main process.
    工作进程初始化器：在 Windows 上强制 UTF-8 编码，并将 stdout 重定向到主进程日志文件。
    """
    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

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
    *args: Any,
) -> T:
    """Replay parent-side contextvars inside the worker process before invoking fn.

    在 worker 子进程中重放父进程的 request_id 与 session_id 后再执行 fn，
    保证 worker 内部 logger 输出的事件能溯源到发起的 HTTP 请求。
    """
    from api.structured_logging import set_request_id, set_session_id

    if request_id is not None:
        set_request_id(request_id)
    if session_id is not None:
        set_session_id(session_id)
    return fn(*args)


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


def _ensure_standard_streams_flushable() -> None:
    """Replace broken stdio streams before spawning process-pool workers.

    ``multiprocessing`` flushes ``sys.stdout`` and ``sys.stderr`` before
    spawning a child process. If the API server was launched by a parent whose
    pipe has already closed, that internal flush raises ``BrokenPipeError`` and
    prevents every preview/generate worker from starting. Replacing only broken
    streams with ``os.devnull`` keeps the process pool usable without changing
    normal interactive output.
    """

    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is None:
            continue
        try:
            stream.flush()
            continue
        except (BrokenPipeError, OSError) as exc:
            encoding = getattr(stream, "encoding", None) or "utf-8"
            errors = getattr(stream, "errors", None) or "replace"
            replacement = open(os.devnull, "w", encoding=encoding, errors=errors)
            setattr(sys, stream_name, replacement)
            _log.warning(
                "Replaced broken standard stream before worker spawn",
                extra={
                    "event": "worker_pool_stdio_replaced",
                    "stream_name": stream_name,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                },
            )


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


def _terminate_executor_workers(executor: ProcessPoolExecutor) -> int:
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
        return 0

    terminated = 0
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
            terminated += 1
        except (OSError, RuntimeError, ValueError) as exc:
            _log.warning(
                "Failed to terminate timed-out worker process",
                extra={
                    "event": "worker_pool_process_terminate_failed",
                    "pid": getattr(proc, "pid", None),
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                },
            )
    return terminated


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
    ) -> None:
        """Initialize WorkerPoolManager.
        初始化 WorkerPoolManager。

        Args:
            max_workers (int | None): Max worker processes. Defaults to min(cpu_count, 4).
                                      (最大工作进程数，默认 min(cpu_count, 4))
            default_task_timeout (float | None): Default seconds before a task
                times out. Non-positive values disable the default timeout.
                (默认任务超时秒数；非正数表示禁用默认超时)

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

    def start(self) -> None:
        """Initialize the process pool.
        初始化进程池。
        """
        with self._pool_lock:
            if self._pool is not None:
                return
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
            terminated = _terminate_executor_workers(failed_pool)
            _shutdown_executor(failed_pool, wait=False, cancel_futures=True)
            self._pool = None
            _log.warning(
                "Worker pool restarted after failed task",
                extra={
                    "event": "worker_pool_restarted",
                    "reason": reason,
                    "timeout_s": timeout,
                    "terminated_workers": terminated,
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
        _ensure_standard_streams_flushable()
        future = loop.run_in_executor(
            pool,
            _run_in_worker_with_context,
            fn,
            request_id,
            session_id,
            *args,
        )
        try:
            return await asyncio.wait_for(future, timeout=effective_timeout)
        except asyncio.TimeoutError:
            future.cancel()
            self._restart_after_failed_pool(
                pool,
                reason="task_timeout",
                timeout=effective_timeout,
            )
            raise
        except BrokenProcessPool:
            self._restart_after_failed_pool(pool, reason="broken_process_pool")
            raise

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
