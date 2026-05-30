#!/usr/bin/env python3
"""Material-LUT Studio — dev launcher (backend + frontend).
Material-LUT Studio — 开发启动器（后端 + 前端）。

Starts the MLS FastAPI backend (:8100) and the Vite frontend (:5180) as child
processes and streams their logs with a small prefix. Ctrl+C stops both.

把 MLS FastAPI 后端 (:8100) 与 Vite 前端 (:5180) 作为子进程启动，带前缀汇总
日志输出，Ctrl+C 一并停止。

Usage (用法):
    python services/material-lut-studio/start_mls.py            # both / 前后端
    python services/material-lut-studio/start_mls.py --backend  # backend only / 仅后端
    python services/material-lut-studio/start_mls.py --frontend # frontend only / 仅前端
"""

from __future__ import annotations

import argparse
import signal
import subprocess
import sys
import threading
from pathlib import Path

SERVICE_DIR = Path(__file__).resolve().parent
REPO_ROOT = SERVICE_DIR.parents[1]
BACKEND_ENTRY = SERVICE_DIR / "backend" / "server.py"
FRONTEND_DIR = SERVICE_DIR / "frontend"


def _stream(proc: subprocess.Popen, prefix: str) -> None:
    """Pump a child process's stdout to ours with a prefix. (带前缀转发子进程输出)"""
    assert proc.stdout is not None
    for raw in proc.stdout:
        line = raw.rstrip("\n")
        if line:
            print(f"{prefix} {line}", flush=True)


def _spawn(cmd: list[str], cwd: Path, prefix: str) -> subprocess.Popen:
    """Launch a child process and start a log-pump thread. (启动子进程并开启日志线程)"""
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
    """Parse args and run the requested MLS processes. (解析参数并运行所需进程)"""
    parser = argparse.ArgumentParser(description="Material-LUT Studio dev launcher")
    parser.add_argument("--backend", action="store_true", help="仅启动后端")
    parser.add_argument("--frontend", action="store_true", help="仅启动前端")
    args = parser.parse_args()

    run_backend = args.backend or not (args.backend or args.frontend)
    run_frontend = args.frontend or not (args.backend or args.frontend)

    procs: list[subprocess.Popen] = []
    if run_backend:
        procs.append(_spawn([sys.executable, str(BACKEND_ENTRY)], REPO_ROOT, "[BE]"))
    if run_frontend:
        procs.append(_spawn(["pnpm", "dev"], FRONTEND_DIR, "[FE]"))

    print("Material-LUT Studio:", flush=True)
    if run_backend:
        print("  Backend  -> http://localhost:8100/api/mls/health", flush=True)
    if run_frontend:
        print("  Frontend -> http://localhost:5180", flush=True)
    print("Press Ctrl+C to stop.", flush=True)

    def _shutdown(*_args) -> None:
        for proc in procs:
            if proc.poll() is None:
                proc.terminate()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    # Exit when any child exits so a crashed backend/frontend is visible.
    while True:
        for proc in procs:
            if proc.poll() is not None:
                _shutdown()
        try:
            procs[0].wait(timeout=1)
        except subprocess.TimeoutExpired:
            continue
        except (IndexError, KeyboardInterrupt):
            _shutdown()


if __name__ == "__main__":
    main()
