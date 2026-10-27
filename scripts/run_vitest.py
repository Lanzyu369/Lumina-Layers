#!/usr/bin/env python3
"""Lumina vitest wrapper / Lumina vitest 包装器.

Why this script exists / 设计目的:
  Agents (and developers) often spawn ``pnpm exec vitest run`` repeatedly. Two
  Windows-specific failure modes pile up node.exe processes until RAM
  exhausts:
    1. Each invocation spawns ``maxForks = CPU`` fork workers
       (~1 GB each); cap is enforced in ``frontend/vite.config.ts``.
    2. When the parent runner is killed (Ctrl+C, agent timeout), fork
       workers are **not** reaped; they outlive the runner forever.

  This wrapper plugs the second hole by:
    * binding the spawned vitest tree to a Windows Job Object with
      ``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`` so the wrapper dying causes
      every descendant to die, even on Ctrl+C / SIGTERM / agent abort;
    * sweeping orphan fork workers (``vitest/dist/workers/forks.js``
      whose parent process is gone) before each run;
    * skipping the ``pnpm exec`` / ``cmd /c`` indirection so the launched
      process is a single ``node.exe`` we can directly track.

Usage / 用法::

    python scripts/run_vitest.py run [vitest args...]
    python scripts/run_vitest.py --run src/__tests__/Foo.test.tsx

Behaviour is otherwise equivalent to ``pnpm exec vitest <argv>``. Multiple
wrappers can run in parallel safely; each owns its own Job Object.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = ROOT / "frontend"
VITEST_MJS = FRONTEND_DIR / "node_modules" / "vitest" / "vitest.mjs"

_DETACHED = 0x08000000  # CREATE_NO_WINDOW
_JOB_LIMIT_KILL_ON_CLOSE = 0x2000

_job_handle = None


# ════════════════════════════════════════════════════════════════════
# Windows Job Object helpers / Windows 任务对象帮助函数
# ════════════════════════════════════════════════════════════════════


def _init_job_object() -> None:
    """Create a Job Object that kills its members on close.

    创建一个在关闭时终止所有成员进程的 Job Object。
    """
    global _job_handle
    if os.name != "nt":
        return
    import ctypes
    from ctypes import wintypes

    k = ctypes.windll.kernel32
    k.CreateJobObjectW.restype = wintypes.HANDLE
    job = k.CreateJobObjectW(None, None)
    if not job:
        return

    class _BasicLimit(ctypes.Structure):
        _fields_ = [
            ("per_process_user_time", ctypes.c_int64),
            ("per_job_user_time", ctypes.c_int64),
            ("limit_flags", wintypes.DWORD),
            ("min_working_set", ctypes.c_size_t),
            ("max_working_set", ctypes.c_size_t),
            ("active_process_limit", wintypes.DWORD),
            ("affinity", ctypes.c_void_p),
            ("priority_class", wintypes.DWORD),
            ("scheduling_class", wintypes.DWORD),
        ]

    class _ExtendedLimit(ctypes.Structure):
        _fields_ = [
            ("basic_limit", _BasicLimit),
            ("io_info", ctypes.c_uint64 * 6),
            ("process_memory_limit", ctypes.c_size_t),
            ("job_memory_limit", ctypes.c_size_t),
            ("peak_process_memory", ctypes.c_size_t),
            ("peak_job_memory", ctypes.c_size_t),
        ]

    info = _ExtendedLimit()
    info.basic_limit.limit_flags = _JOB_LIMIT_KILL_ON_CLOSE
    # ExtendedLimitInformation = 9
    if k.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
        _job_handle = job
    else:
        k.CloseHandle(job)


def _assign_to_job(pid: int) -> None:
    """Attach ``pid`` to the wrapper's Job Object.

    将给定 pid 加入包装器的 Job Object。子进程会自动继承。
    """
    if not _job_handle or os.name != "nt":
        return
    import ctypes
    from ctypes import wintypes

    k = ctypes.windll.kernel32
    k.OpenProcess.restype = wintypes.HANDLE
    PROCESS_SET_QUOTA = 0x0100
    PROCESS_TERMINATE = 0x0001
    handle = k.OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, pid)
    if handle:
        k.AssignProcessToJobObject(_job_handle, handle)
        k.CloseHandle(handle)


def _terminate_job() -> None:
    """Terminate every process in the Job Object and release the handle.

    终止 Job Object 内所有进程并释放句柄。
    """
    global _job_handle
    if _job_handle and os.name == "nt":
        import ctypes

        ctypes.windll.kernel32.TerminateJobObject(_job_handle, 1)
        ctypes.windll.kernel32.CloseHandle(_job_handle)
        _job_handle = None


# ════════════════════════════════════════════════════════════════════
# Orphan vitest fork sweep / 清理孤儿 vitest fork worker
# ════════════════════════════════════════════════════════════════════


def _list_node_processes() -> list[tuple[int, int, str]]:
    """Return ``(pid, ppid, cmdline)`` for every node.exe process.

    列出所有 node.exe 进程及其父进程与命令行。
    """
    if os.name != "nt":
        return []
    ps_script = (
        "$ErrorActionPreference='SilentlyContinue';"
        "Get-CimInstance Win32_Process -Filter \"Name='node.exe'\" | "
        "ForEach-Object { \"$($_.ProcessId)|$($_.ParentProcessId)|$($_.CommandLine)\" }"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            creationflags=_DETACHED,
            timeout=10,
        )
    except Exception:
        return []
    rows: list[tuple[int, int, str]] = []
    for line in result.stdout.splitlines():
        parts = line.split("|", 2)
        if len(parts) < 3:
            continue
        try:
            pid = int(parts[0])
            ppid = int(parts[1])
        except ValueError:
            continue
        rows.append((pid, ppid, parts[2] or ""))
    return rows


def _is_pid_alive(pid: int) -> bool:
    """Return whether a given Windows pid is still running.

    判断指定 Windows pid 是否仍然存活。
    """
    if os.name != "nt" or pid <= 0:
        return False
    import ctypes
    from ctypes import wintypes

    k = ctypes.windll.kernel32
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    handle = k.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    code = wintypes.DWORD()
    ok = k.GetExitCodeProcess(handle, ctypes.byref(code))
    k.CloseHandle(handle)
    if not ok:
        return False
    return code.value == 259  # STILL_ACTIVE


def _is_vitest_worker(cmdline: str) -> bool:
    """Heuristic: the process is a vitest fork worker.

    判断进程是否为 vitest fork worker 进程。
    """
    lc = cmdline.lower()
    return ("vitest" in lc) and ("forks.js" in lc or "workers" in lc and "fork" in lc)


def _kill_pid_tree(pid: int) -> None:
    """Hard-kill a process and its descendants on Windows.

    在 Windows 上强制终止指定进程及其后代。
    """
    if os.name != "nt":
        return
    subprocess.run(
        ["taskkill", "/T", "/F", "/PID", str(pid)],
        capture_output=True,
        creationflags=_DETACHED,
    )


def _cleanup_orphan_workers() -> int:
    """Kill vitest fork workers whose parent runner is already dead.

    杀掉父运行器已死的 vitest fork worker 孤儿进程。返回清理数量。
    """
    if os.name != "nt":
        return 0
    rows = _list_node_processes()
    live_pids = {pid for pid, _, _ in rows}
    killed = 0
    for pid, ppid, cmdline in rows:
        if not _is_vitest_worker(cmdline):
            continue
        # Parent visible in our snapshot AND alive => still owned, skip.
        if ppid in live_pids and _is_pid_alive(ppid):
            continue
        _kill_pid_tree(pid)
        killed += 1
    return killed


# ════════════════════════════════════════════════════════════════════
# Main
# ════════════════════════════════════════════════════════════════════


def _resolve_node_exe() -> str:
    """Locate node.exe on Windows; fallback to PATH ``node`` elsewhere.

    定位 node 可执行文件。
    """
    if os.name == "nt":
        try:
            result = subprocess.run(
                ["where", "node"],
                capture_output=True,
                text=True,
                creationflags=_DETACHED,
            )
            if result.returncode == 0:
                first = result.stdout.strip().splitlines()[0].strip()
                if first:
                    return first
        except Exception:
            pass
    return "node"


def main(argv: list[str]) -> int:
    if not VITEST_MJS.exists():
        sys.stderr.write(
            f"[run_vitest] vitest.mjs not found at {VITEST_MJS}; "
            f"run `cd frontend && pnpm install` first.\n"
        )
        return 1

    if os.name == "nt":
        cleaned = _cleanup_orphan_workers()
        if cleaned:
            print(f"[run_vitest] swept {cleaned} orphan vitest fork worker(s)")
        _init_job_object()

    cmd = [_resolve_node_exe(), str(VITEST_MJS), *argv]
    print(f"[run_vitest] $ {' '.join(cmd)}  (cwd={FRONTEND_DIR})", flush=True)

    flags = 0
    if os.name == "nt":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | _DETACHED

    try:
        proc = subprocess.Popen(cmd, cwd=str(FRONTEND_DIR), creationflags=flags)
    except FileNotFoundError as exc:
        sys.stderr.write(f"[run_vitest] failed to spawn node: {exc}\n")
        _terminate_job()
        return 1

    if os.name == "nt":
        _assign_to_job(proc.pid)

    def _on_signal(_signum, _frame):
        _terminate_job()
        # Job termination kills proc; bail out with conventional 130.
        sys.exit(130)

    # Windows: SIGINT works at the Python layer; SIGTERM is best-effort.
    try:
        signal.signal(signal.SIGINT, _on_signal)
    except (ValueError, OSError):
        pass
    try:
        signal.signal(signal.SIGTERM, _on_signal)
    except (ValueError, OSError, AttributeError):
        pass

    try:
        return proc.wait()
    except KeyboardInterrupt:
        _terminate_job()
        return 130
    finally:
        # Normal exit path: explicitly close the job so any straggler
        # forks get reaped before the wrapper returns. The handle would
        # also close on process exit, but doing it here makes captured
        # stdout in callers (run_full_tests.py) deterministic.
        _terminate_job()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
