"""Lumina Studio API — Server Entry Point.
Lumina Studio API — 服务启动入口。

Minimal entry script that imports the FastAPI application instance
and starts the uvicorn ASGI server. Run with ``python api_server.py``.
最小化入口脚本，导入 FastAPI 应用实例并启动 uvicorn ASGI 服务器。
通过 ``python api_server.py`` 运行。
"""

import faulthandler
import multiprocessing
import os
import re
import sys
import traceback
from collections.abc import Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, TextIO


@contextmanager
def _startup_diagnostics(env: Mapping[str, str]) -> Iterator[None]:
    """Capture a frozen-startup hang or uncaught exception when requested.

    按需捕获冻结版启动卡死时的线程堆栈或未处理异常。

    This diagnostic path is opt-in and intended for native packaging CI. A
    failure to prepare diagnostics never changes normal server startup.
    该诊断仅在原生打包 CI 显式启用；诊断自身失败不会影响正常启动。
    """

    raw_path = env.get("LUMINA_STARTUP_DIAGNOSTIC_PATH")
    if not raw_path:
        yield
        return

    stream: TextIO | None = None
    watchdog_started = False
    try:
        diagnostic_path = Path(raw_path).expanduser().resolve()
        diagnostic_path.parent.mkdir(parents=True, exist_ok=True)
        stream = diagnostic_path.open(
            "a",
            encoding="utf-8",
            buffering=1,
        )
    except OSError:
        yield
        return

    try:
        try:
            faulthandler.dump_traceback_later(
                30,
                repeat=True,
                file=stream,
            )
            watchdog_started = True
        except (OSError, RuntimeError, ValueError):
            pass

        try:
            yield
        except BaseException:
            try:
                traceback.print_exc(file=stream)
                stream.flush()
            except OSError:
                pass
            raise
    finally:
        if watchdog_started:
            try:
                faulthandler.cancel_dump_traceback_later()
            except RuntimeError:
                pass
        stream.close()


def _prepare_frozen_multiprocessing() -> None:
    """Divert PyInstaller multiprocessing helper processes.

    分流 PyInstaller 打包环境中的 multiprocessing 辅助进程。
    """

    multiprocessing.freeze_support()


def _open_null_stream() -> TextIO:
    """Open a process-lifetime text sink for a windowed executable."""

    return open(
        os.devnull,
        "w",
        encoding="utf-8",
        errors="replace",
        buffering=1,
    )


def _prepare_windowed_stdio() -> None:
    """Provide real streams when PyInstaller ``noconsole`` sets them to None.

    为 PyInstaller 无控制台进程补充可用的标准输出流。
    """

    if sys.stdout is None:
        sys.stdout = _open_null_stream()
    if sys.stderr is None:
        sys.stderr = _open_null_stream()


def _resolve_server_bind(env: Mapping[str, str]) -> tuple[str, int]:
    """Resolve and validate the API bind address.

    解析并校验 API 监听地址。

    Args:
        env: Environment mapping used by the server process.
            服务进程使用的环境变量映射。

    Returns:
        A validated ``(host, port)`` tuple. 经过校验的地址和端口。

    Raises:
        ValueError: If the host or port is unsafe or malformed.
            地址或端口不安全、格式错误时抛出。
    """

    host = env.get("LUMINA_API_HOST", "0.0.0.0")
    if host not in {"0.0.0.0", "127.0.0.1"}:
        raise ValueError("LUMINA_API_HOST must be a supported local bind")
    raw_port = env.get("LUMINA_API_PORT", "8000")
    if not re.fullmatch(r"[0-9]+", raw_port):
        raise ValueError("LUMINA_API_PORT must be an integer")
    port = int(raw_port)
    if port < 1024 or port > 65535:
        raise ValueError("LUMINA_API_PORT must be between 1024 and 65535")
    return host, port


def _run_server(env: Mapping[str, str]) -> None:
    """Start the API after initializing frozen multiprocessing safely.

    安全初始化冻结版多进程支持后启动 API。
    """

    _prepare_frozen_multiprocessing()
    _prepare_windowed_stdio()

    with _startup_diagnostics(env):
        # Keep heavyweight imports after freeze_support(). PyInstaller reuses
        # this entry point for workers and resource trackers.
        import uvicorn

        # ``api.app`` is the canonical place that calls
        # ``load_env_local()`` at module scope; importing it here populates
        # ``.env.local`` values into ``os.environ`` before uvicorn boots.
        # ``api.app`` 在模块级调用 ``load_env_local()`` 是规范入口；在这里导入
        # 它会先把 ``.env.local`` 写入 ``os.environ``，再启动 uvicorn。
        from api.app import app

        bind_host, bind_port = _resolve_server_bind(env)
        uvicorn.run(app, host=bind_host, port=bind_port)


def _run_frozen_worker_smoke() -> None:
    """Start one real process-pool worker and require a child result.

    启动一个真实进程池工作进程，并要求子进程返回结果。
    """

    _prepare_frozen_multiprocessing()

    from concurrent.futures import ProcessPoolExecutor

    from api.worker_pool import _worker_init, _worker_smoke_task

    with ProcessPoolExecutor(max_workers=1, initializer=_worker_init) as pool:
        worker_pid = pool.submit(_worker_smoke_task).result(timeout=60)
    if worker_pid == os.getpid():
        raise RuntimeError("worker smoke did not execute in a child process")


if __name__ == "__main__":
    if sys.argv[1:] == ["--worker-smoke"]:
        _run_frozen_worker_smoke()
    else:
        _run_server(os.environ)
