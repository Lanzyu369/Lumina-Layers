#!/usr/bin/env python3
"""Material-LUT Studio — backend-only dev launcher.
Material-LUT Studio — 仅启动后端的开发引导脚本。

The MLS frontend is the second Vite entry inside the main ``frontend/``
project (Route B / option A). It shares the converter app's full panel /
component / dependency tree and runs on its own port via
``frontend/vite.mls.config.ts``. There is no separate frontend project
under ``services/material-lut-studio/`` anymore.

To launch backend + frontend together (plus the main converter), use the
repo-root ``start_all.py`` instead. This script is kept as a thin wrapper
that starts only the MLS FastAPI backend so workflows that already drive
the Vite dev server elsewhere can still spin up the API.

MLS 前端已迁移到主仓库 ``frontend/`` 内的第二个 Vite 入口（选项 A），与转换器
应用共享整套面板、组件与依赖，使用 ``frontend/vite.mls.config.ts`` 运行在独立
端口。``services/material-lut-studio/`` 下不再有独立前端工程。

如需同时启动 MLS 后端 + 前端（以及主转换器），请改用仓库根的 ``start_all.py``。
本脚本仅作为薄封装启动 MLS FastAPI 后端，便于已在别处管理 Vite 的工作流单独
拉起 API 服务。

Usage (用法):
    python services/material-lut-studio/start_mls.py
    MLS_PORT=8100 python services/material-lut-studio/start_mls.py
"""

from __future__ import annotations

import signal
import subprocess
import sys
import threading
from pathlib import Path

SERVICE_DIR = Path(__file__).resolve().parent
REPO_ROOT = SERVICE_DIR.parents[1]
BACKEND_ENTRY = SERVICE_DIR / "backend" / "server.py"


def _stream(proc: subprocess.Popen, prefix: str) -> None:
    """Pump a child process's stdout to ours with a prefix.
    带前缀转发子进程输出。
    """
    assert proc.stdout is not None
    for raw in proc.stdout:
        line = raw.rstrip("\n")
        if line:
            print(f"{prefix} {line}", flush=True)


def _spawn(cmd: list[str], cwd: Path, prefix: str) -> subprocess.Popen:
    """Launch a child process and start a log-pump thread.
    启动子进程并开启日志线程。
    """
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    threading.Thread(target=_stream, args=(proc, prefix), daemon=True).start()
    return proc


def main() -> None:
    """Run the MLS backend until Ctrl+C.
    启动 MLS 后端，按 Ctrl+C 停止。
    """
    proc = _spawn([sys.executable, str(BACKEND_ENTRY)], REPO_ROOT, "[BE]")

    print("Material-LUT Studio (backend only):", flush=True)
    print("  Backend  -> http://localhost:8100/api/mls/health", flush=True)
    print(
        "  Frontend: launch via repo-root start_all.py (or `pnpm dev:mls` "
        "inside frontend/) — :5180 by default.",
        flush=True,
    )
    print("Press Ctrl+C to stop.", flush=True)

    def _shutdown(*_args) -> None:
        if proc.poll() is None:
            proc.terminate()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        proc.wait()
    except KeyboardInterrupt:
        _shutdown()


if __name__ == "__main__":
    main()
