#!/usr/bin/env python3
"""Lumina + Material-LUT Studio — unified dev launcher.
Lumina + Material-LUT Studio — 统一开发启动器。

Starts all four dev services as child processes and streams their logs with a
colored, per-service prefix. Supports restarting any single service (or all of
them) with a single keypress, without tearing down the others.

把四个开发服务作为子进程一起启动，按服务前缀汇总彩色日志输出。支持用单个按键
重启任意一个服务（或全部），不影响其它服务。

Services (服务):
    [1] main-backend   python api_server.py                     -> :8000
    [2] main-frontend  pnpm dev (frontend/)                     -> :4174
    [3] mls-backend    python services/.../backend/server.py    -> :8100
    [4] mls-frontend   pnpm dev (services/.../frontend/)        -> :5180

Hotkeys (热键, press the key then Enter):
    1 / 2 / 3 / 4  restart that service          重启对应服务
    b              restart both backends         重启两个后端
    f              restart both frontends        重启两个前端
    r              restart everything            重启全部
    s              show status                   查看状态
    q              quit (stop all)               退出并停止全部

Usage (用法):
    python start_all.py                 # all four services / 启动全部四个服务
    python start_all.py --no-mls        # only the main app / 仅主应用
    python start_all.py --only mls      # only MLS / 仅 MLS
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
FRONTEND_DIR = ROOT / "frontend"
MLS_BACKEND_ENTRY = ROOT / "services" / "material-lut-studio" / "backend" / "server.py"
# MLS frontend is a second Vite entry inside ``frontend/`` (Route B, option A):
# it reuses the converter app's full panel + dependency tree, runs on :5180 via
# ``vite.mls.config.ts``. The old standalone scaffold under services/.../frontend
# is superseded by this entry.
# MLS 前端是 ``frontend/`` 内的第二个 Vite 入口（选项 A），复用转换器应用的完整
# 面板与依赖树，通过 ``vite.mls.config.ts`` 运行在 :5180。
MLS_FRONTEND_DIR = FRONTEND_DIR
MLS_VITE_CONFIG = "vite.mls.config.ts"

# ── ANSI colors ──────────────────────────────────────────────────────────
_R = "\033[0m"
_B = "\033[1m"
_DIM = "\033[2m"
_COLORS = {
    "main-backend": "\033[36m",   # cyan
    "main-frontend": "\033[34m",  # blue
    "mls-backend": "\033[32m",    # green
    "mls-frontend": "\033[35m",   # magenta
    "SYS": "\033[33m",            # yellow
    "ERR": "\033[31m",            # red
}


def _ts() -> str:
    return time.strftime("%H:%M:%S")


def _log(tag: str, msg: str) -> None:
    color = _COLORS.get(tag, "")
    print(f"{_DIM}{_ts()}{_R} {color}{_B}[{tag}]{_R} {msg}", flush=True)


def _sys(msg: str) -> None:
    _log("SYS", msg)


def _err(msg: str) -> None:
    _log("ERR", msg)


def _find_python() -> str:
    """Resolve the interpreter to run the Python backends.
    解析运行 Python 后端所用的解释器。

    Prefers the project virtualenvs, then the current interpreter.
    优先项目内虚拟环境，其次当前解释器。
    """
    candidates = [
        ROOT / ".venv312" / "bin" / "python",
        ROOT / ".venv" / "bin" / "python",
        ROOT / "venv" / "bin" / "python",
        ROOT / ".venv312" / "Scripts" / "python.exe",
        ROOT / ".venv" / "Scripts" / "python.exe",
        ROOT / "venv" / "Scripts" / "python.exe",
    ]
    for path in candidates:
        if path.exists():
            return str(path)
    return sys.executable


PYTHON = _find_python()


def _find_node() -> str:
    """Resolve a ``node`` executable. (解析 node 可执行文件)"""
    from shutil import which

    return which("node") or "node"


def _frontend_cmd(frontend_dir: Path, config: str | None = None) -> list[str]:
    """Resolve the command to run a Vite dev server for ``frontend_dir``.
    解析在 ``frontend_dir`` 启动 Vite 开发服务器的命令。

    Prefers running ``node node_modules/vite/bin/vite.js`` directly so the
    process we spawn *is* Vite — a single SIGTERM to its process group then
    reliably stops it. ``pnpm dev`` adds a wrapper child that can outlive a
    group signal and orphan the Vite server (leaving its port bound).
    ``config`` selects an alternate Vite config (e.g. the MLS entry).
    优先用 ``node`` 直接跑 ``vite.js``，使启动的进程本身就是 Vite，便于一次进程组
    信号可靠停止；``pnpm dev`` 会多一层包装子进程。``config`` 可指定备用 Vite 配置
    （如 MLS 入口）。
    """
    vite_js = frontend_dir / "node_modules" / "vite" / "bin" / "vite.js"
    extra = ["--config", config] if config else []
    if vite_js.exists():
        return [_find_node(), str(vite_js), *extra]
    # Fallback: pnpm wrapper (less clean shutdown, see docstring above).
    # 回退：pnpm 包装（关闭不够干净，见上文）。
    return ["pnpm", "exec", "vite", *extra] if config else ["pnpm", "dev"]


class Service:
    """A single managed dev process with restart support.
    单个受管理的开发进程，支持重启。
    """

    def __init__(self, key: str, name: str, cmd: list[str], cwd: Path, url: str | None, port: int | None = None) -> None:
        self.key = key          # hotkey digit, e.g. "1"
        self.name = name        # log tag, e.g. "main-backend"
        self.cmd = cmd
        self.cwd = cwd
        self.url = url
        self.port = port        # bound TCP port, for a stop-time sweep fallback
        self.proc: subprocess.Popen | None = None
        self._reader: threading.Thread | None = None

    def start(self) -> None:
        """Spawn the process and begin streaming its output. (启动并转发输出)"""
        if self.proc is not None and self.proc.poll() is None:
            _sys(f"{self.name} already running (pid={self.proc.pid})")
            return
        try:
            self.proc = subprocess.Popen(
                self.cmd,
                cwd=str(self.cwd),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                # New process group so we can signal the whole tree on POSIX.
                # 新建进程组，便于在 POSIX 上向整棵进程树发信号。
                start_new_session=(os.name != "nt"),
            )
        except FileNotFoundError as exc:
            _err(f"{self.name} failed to start: {exc}")
            return
        self._reader = threading.Thread(target=self._pump, daemon=True)
        self._reader.start()
        _log(self.name, f"started (pid={self.proc.pid})")

    def _pump(self) -> None:
        assert self.proc is not None and self.proc.stdout is not None
        try:
            for raw in self.proc.stdout:
                line = raw.rstrip("\n")
                if line:
                    _log(self.name, line)
        except (ValueError, OSError):
            pass

    def stop(self) -> None:
        """Terminate the process tree, then sweep the port. (终止进程树并清扫端口)"""
        if self.proc is None or self.proc.poll() is not None:
            self.proc = None
            self._sweep_port()
            return
        _log(self.name, "stopping...")

        def _signal_group(sig: int) -> None:
            try:
                if os.name == "nt":
                    self.proc.terminate() if sig == signal.SIGTERM else self.proc.kill()
                else:
                    os.killpg(os.getpgid(self.proc.pid), sig)
            except (ProcessLookupError, PermissionError, OSError):
                try:
                    self.proc.terminate() if sig == signal.SIGTERM else self.proc.kill()
                except OSError:
                    pass

        # Graceful first, then a fast hard kill — node/vite can ignore SIGTERM
        # while still booting, so we don't wait long before escalating.
        # 先优雅后强杀——node/vite 启动期可能忽略 SIGTERM，故不长等即升级。
        _signal_group(signal.SIGTERM)
        try:
            self.proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            _signal_group(signal.SIGKILL)
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                pass
        self.proc = None
        self._sweep_port()

    def _sweep_port(self) -> None:
        """Best-effort kill of any leftover process still LISTENing on our port.
        尽力清理仍在本服务端口上 LISTEN 的残留进程。

        A safety net for cases where a wrapper/grandchild (e.g. a detached
        Vite server) escapes the process-group signal and keeps the port bound,
        which would otherwise make the next restart fail with "address in use".
        Escalates straight to SIGKILL: by the time we sweep, the tracked process
        has already been waited on, so anything still LISTENing on the port is
        an orphan.

        Crucially we filter ``lsof`` to ``-sTCP:LISTEN`` so we only target
        the server-side listener — *not* established or CLOSE_WAIT connections
        from clients that happen to be talking to that port (a browser tab
        open on http://localhost:<port> shows up here as the Chrome
        NetworkService process). Without this filter we'd SIGKILL Chrome's
        NetworkService every time the user restarted the frontend, dropping
        every tab and showing a blank page after each restart.

        当包装/孙子进程（如脱离的 Vite）逃过进程组信号、仍 LISTEN 端口时兜底
        清理，避免下次重启因端口占用失败。被跟踪进程已 wait 结束，仍在 LISTEN
        的进程即为孤儿，直接 SIGKILL。

        关键：``lsof`` 必须加 ``-sTCP:LISTEN`` 过滤，只针对服务端监听，
        **不要**误杀客户端连接（浏览器里打开 http://localhost:<port> 时，
        ``lsof -ti tcp:<port>`` 会同时列出 Chrome NetworkService 进程）。
        没有该过滤会导致每次重启前端都把 Chrome NetworkService 杀掉，
        所有标签页瞬间断网、显示白屏。
        """
        if self.port is None or os.name == "nt":
            return
        for attempt in range(3):
            try:
                out = subprocess.run(
                    # ``-sTCP:LISTEN`` restricts the match to processes that
                    # have the port in LISTEN state — i.e. the dev server
                    # itself, never the browser that's connected to it.
                    # ``-sTCP:LISTEN`` 仅匹配处于 LISTEN 状态的进程，即开发
                    # 服务器本身，绝不包含连接到它的浏览器。
                    ["lsof", "-tiTCP:" + str(self.port), "-sTCP:LISTEN"],
                    capture_output=True, text=True, timeout=5,
                ).stdout
            except (OSError, subprocess.TimeoutExpired):
                return
            pids = []
            for pid_str in out.split():
                try:
                    pid = int(pid_str)
                except ValueError:
                    continue
                if pid == os.getpid():
                    continue
                pids.append(pid)
            if not pids:
                return
            for pid in pids:
                try:
                    os.kill(pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError, OSError):
                    pass
            if attempt < 2:
                time.sleep(0.4)

    def restart(self) -> None:
        """Stop then start the service. (先停后启)"""
        _log(self.name, "restarting...")
        self.stop()
        time.sleep(0.5)
        self.start()

    @property
    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None


def build_services(run_main: bool, run_mls: bool) -> list[Service]:
    """Build the service list for the requested scope. (按范围构建服务列表)"""
    services: list[Service] = []
    if run_main:
        services.append(Service(
            "1", "main-backend",
            [PYTHON, "api_server.py"], ROOT, "http://localhost:8000", port=8000,
        ))
        services.append(Service(
            "2", "main-frontend",
            _frontend_cmd(FRONTEND_DIR), FRONTEND_DIR, "http://localhost:4174", port=4174,
        ))
    if run_mls:
        services.append(Service(
            "3", "mls-backend",
            [PYTHON, str(MLS_BACKEND_ENTRY)], ROOT, "http://localhost:8100/api/mls/health", port=8100,
        ))
        services.append(Service(
            "4", "mls-frontend",
            _frontend_cmd(MLS_FRONTEND_DIR, MLS_VITE_CONFIG), MLS_FRONTEND_DIR, "http://localhost:5180", port=5180,
        ))
    return services


def print_banner(services: list[Service]) -> None:
    print(f"\n{_B}  Lumina + Material-LUT Studio — Dev Launcher{_R}")
    print(f"{_DIM}  python: {PYTHON}{_R}")
    print(f"{_DIM}  ──────────────────────────────────────────────{_R}")
    for svc in services:
        color = _COLORS.get(svc.name, "")
        url = svc.url or ""
        print(f"   {color}[{svc.key}] {svc.name:<14}{_R} {url}")
    print(f"{_DIM}  ──────────────────────────────────────────────{_R}")
    print(
        f"   {_B}1-4{_R}=restart one  {_B}b{_R}=backends  {_B}f{_R}=frontends  "
        f"{_B}r{_R}=all  {_B}s{_R}=status  {_B}q{_R}=quit"
    )
    print(f"{_DIM}  ──────────────────────────────────────────────{_R}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Unified dev launcher for Lumina + MLS")
    parser.add_argument("--no-mls", action="store_true", help="仅启动主应用前后端")
    parser.add_argument("--no-main", action="store_true", help="仅启动 MLS 前后端")
    parser.add_argument(
        "--only",
        choices=["main", "mls"],
        help="只启动指定一组（main 或 mls）",
    )
    args = parser.parse_args()

    run_main = True
    run_mls = True
    if args.only == "main" or args.no_mls:
        run_mls = False
    if args.only == "mls" or args.no_main:
        run_main = False
    if not run_main and not run_mls:
        _err("Nothing to run: both groups disabled.")
        return

    # Enable ANSI on Windows terminals.
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.kernel32.SetConsoleMode(
                ctypes.windll.kernel32.GetStdHandle(-11), 7
            )
        except Exception:
            pass

    services = build_services(run_main, run_mls)
    by_key = {svc.key: svc for svc in services}

    print_banner(services)

    for svc in services:
        svc.start()

    stopping = threading.Event()

    def shutdown() -> None:
        if stopping.is_set():
            return
        stopping.set()
        _sys("shutting down all services...")
        for svc in services:
            svc.stop()

    def on_signal(_signum, _frame) -> None:
        shutdown()
        os._exit(0)

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    def show_status() -> None:
        for svc in services:
            state = f"{_COLORS['mls-backend']}running{_R}" if svc.alive else f"{_COLORS['ERR']}stopped{_R}"
            _log(svc.name, f"[{svc.key}] {state}")

    def input_loop() -> None:
        while not stopping.is_set():
            try:
                cmd = input().strip().lower()
            except (EOFError, KeyboardInterrupt):
                break
            if not cmd:
                continue
            if cmd in by_key:
                by_key[cmd].restart()
            elif cmd == "b":
                for svc in services:
                    if svc.name.endswith("backend"):
                        svc.restart()
            elif cmd == "f":
                for svc in services:
                    if svc.name.endswith("frontend"):
                        svc.restart()
            elif cmd == "r":
                for svc in services:
                    svc.restart()
            elif cmd == "s":
                show_status()
            elif cmd in ("q", "quit", "exit"):
                shutdown()
                os._exit(0)
            else:
                _sys(f"unknown command: {cmd!r} (use 1-4 / b / f / r / s / q)")

    threading.Thread(target=input_loop, daemon=True).start()

    # Main loop: just keep the launcher alive. Crashed children are reported
    # but NOT auto-restarted, so the operator decides via the hotkeys.
    # 主循环：保持启动器存活。子进程崩溃只报告、不自动重启，由操作者按键决定。
    reported: set[str] = set()
    try:
        while not stopping.is_set():
            time.sleep(1)
            for svc in services:
                if svc.proc is not None and not svc.alive and svc.name not in reported:
                    code = svc.proc.returncode
                    _err(f"{svc.name} exited (code={code}). Press [{svc.key}] to restart.")
                    reported.add(svc.name)
                elif svc.alive and svc.name in reported:
                    reported.discard(svc.name)
    finally:
        shutdown()


if __name__ == "__main__":
    main()
