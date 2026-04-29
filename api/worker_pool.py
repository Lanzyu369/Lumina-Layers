"""WorkerPoolManager — ProcessPoolExecutor lifecycle manager.
WorkerPoolManager — ProcessPoolExecutor 生命周期管理器。

Provides an async-friendly interface for submitting CPU-bound tasks
to a process pool, with timeout support and graceful shutdown.
提供异步友好的接口，将 CPU 密集型任务提交到进程池，
支持超时控制和优雅关闭。
"""

from concurrent.futures import ProcessPoolExecutor
from typing import Any, Callable, TypeVar
import asyncio
import io
import os
import sys

T = TypeVar("T")


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


class WorkerPoolManager:
    """Manage a ProcessPoolExecutor for CPU-bound tasks.
    管理用于 CPU 密集型任务的进程池。

    Attributes:
        _max_workers (int): Maximum number of worker processes. (最大工作进程数)
        _pool (ProcessPoolExecutor | None): The underlying executor. (底层执行器)
    """

    def __init__(self, max_workers: int | None = None) -> None:
        """Initialize WorkerPoolManager.
        初始化 WorkerPoolManager。

        Args:
            max_workers (int | None): Max worker processes. Defaults to min(cpu_count, 4).
                                      (最大工作进程数，默认 min(cpu_count, 4))
        """
        self._max_workers: int = max_workers or min(os.cpu_count() or 2, 4)
        self._pool: ProcessPoolExecutor | None = None

    def start(self) -> None:
        """Initialize the process pool.
        初始化进程池。
        """
        if self._pool is not None:
            return
        self._pool = ProcessPoolExecutor(
            max_workers=self._max_workers,
            initializer=_worker_init,
        )

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
            timeout (float | None): Max seconds to wait, or None for no limit.
                                    (最大等待秒数，None 表示不限时)

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
        if self._pool is None:
            raise RuntimeError("WorkerPool not started")
        from api.structured_logging import get_request_id, get_session_id

        loop = asyncio.get_running_loop()
        request_id = get_request_id()
        session_id = get_session_id()
        future = loop.run_in_executor(
            self._pool,
            _run_in_worker_with_context,
            fn,
            request_id,
            session_id,
            *args,
        )
        return await asyncio.wait_for(future, timeout=timeout)

    def shutdown(self, wait: bool = True) -> None:
        """Shutdown the pool gracefully.
        优雅关闭进程池。

        Args:
            wait (bool): Whether to wait for pending tasks to complete.
                         (是否等待待处理任务完成)
        """
        if self._pool is not None:
            self._pool.shutdown(wait=wait)
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
