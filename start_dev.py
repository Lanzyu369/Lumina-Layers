#!/usr/bin/env python3
"""Lumina Studio — Dev Launcher v2

设计原则：
  1. 直接启动 node/python，不经过 cmd.exe 中间层 → Job Object 能直接管控
  2. 启动前安全清理：仅杀掉本项目的残留进程（通过命令行验证身份）
  3. 退出时同样清理：taskkill /T /F 杀进程树
  4. 不自动重启，不预检前端端口（Vite 自行顺延）
  5. Ctrl+C / 关窗口 → 干净退出

用法：
    python start_dev.py              # 前后端
    python start_dev.py --backend    # 仅后端
    python start_dev.py --frontend   # 仅前端
    python start_dev.py --kill       # 清理本项目残留后退出
    python start_dev.py --kill --force  # 强制清理所有占用端口的进程（慎用）
"""

import argparse
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

# ═══════════════════════════════════════════════════════════
#  常量
# ═══════════════════════════════════════════════════════════

ROOT = Path(__file__).parent.resolve()
FRONTEND_DIR = ROOT / "frontend"
NODE_MODULES_BIN = FRONTEND_DIR / "node_modules" / ".bin"

BACKEND_PORT = 8000
FRONTEND_PORT = 4174

# ═══════════════════════════════════════════════════════════
#  Windows Job Object（保证子进程随父进程退出）
# ═══════════════════════════════════════════════════════════

_job = None

def _init_job():
    global _job
    if os.name != "nt":
        return
    import ctypes
    from ctypes import wintypes
    k = ctypes.windll.kernel32
    k.CreateJobObjectW.restype = wintypes.HANDLE
    k.OpenProcess.restype = wintypes.HANDLE

    job = k.CreateJobObjectW(None, None)
    if not job:
        return

    class _Info(ctypes.Structure):
        _fields_ = [
            ("flags", ctypes.c_int64), ("perJob", ctypes.c_int64),
            ("limit", wintypes.DWORD),
            ("minWs", ctypes.c_size_t), ("maxWs", ctypes.c_size_t),
            ("activeProc", wintypes.DWORD), ("affinity", ctypes.c_void_p),
            ("priority", wintypes.DWORD), ("sched", wintypes.DWORD),
        ]
    class _Ext(ctypes.Structure):
        _fields_ = [
            ("basic", _Info), ("io", ctypes.c_uint64 * 6),
            ("procMem", ctypes.c_size_t), ("jobMem", ctypes.c_size_t),
            ("peakProc", ctypes.c_size_t), ("peakJob", ctypes.c_size_t),
        ]

    info = _Ext()
    info.basic.limit = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if k.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
        _job = job

def _assign(pid):
    if not _job or os.name != "nt":
        return
    import ctypes
    k = ctypes.windll.kernel32
    h = k.OpenProcess(0x0201, False, pid)
    if h:
        k.AssignProcessToJobObject(_job, h)
        k.CloseHandle(h)

def _kill_job():
    global _job
    if _job and os.name == "nt":
        import ctypes
        ctypes.windll.kernel32.TerminateJobObject(_job, 1)
        ctypes.windll.kernel32.CloseHandle(_job)
        _job = None

# ═══════════════════════════════════════════════════════════
#  日志
# ═══════════════════════════════════════════════════════════

_R = "\033[0m"; _B = "\033[1m"
_RED = "\033[31m"; _GRN = "\033[32m"; _YEL = "\033[33m"
_BLU = "\033[34m"; _CYN = "\033[36m"; _DIM = "\033[2m"

def _ts():
    return time.strftime("%H:%M:%S")

def _log(tag, c, msg):
    print(f"{_DIM}{_ts()}{_R} {c}{_B}[{tag}]{_R} {msg}", flush=True)

def _sys(m):  _log("SYS", _YEL, m)
def _ok(m):   _log(" OK", _GRN, m)
def _err(m):  _log("ERR", _RED, m)
def _be(m):   _log(" B ", _CYN, m)
def _fe(m):   _log(" F ", _BLU, m)

# ═══════════════════════════════════════════════════════════
#  进程工具
# ═══════════════════════════════════════════════════════════

def _port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0

def _kill_pid_tree(pid):
    """taskkill /T /F 杀整个进程树"""
    subprocess.run(
        ["taskkill", "/T", "/F", "/PID", str(pid)],
        capture_output=True, creationflags=0x08000000,
    )

def _get_process_cmdline(pid: int) -> str:
    """获取进程命令行（用于验证身份）"""
    try:
        out = subprocess.run(
            ["wmic", "process", "where", f"ProcessId={pid}",
             "get", "CommandLine", "/VALUE"],
            capture_output=True, text=True, creationflags=0x08000000,
        ).stdout
        for line in out.splitlines():
            if line.startswith("CommandLine="):
                return line[12:]
    except Exception:
        pass
    return ""

def _is_our_process(pid: int) -> bool:
    """检查进程是否属于本项目
    
    通过命令行参数判断进程是否为本项目启动的后端或前端服务。
    """
    cmdline = _get_process_cmdline(pid)
    if not cmdline:
        return False
    markers = [
        "api_server.py",
        str(ROOT),
        "Lumina-Layers",
        str(FRONTEND_DIR),
    ]
    return any(m in cmdline for m in markers)

def _kill_listening(ports, force=False):
    """杀掉所有监听指定端口的进程（进程树一起杀）
    
    Args:
        ports: 要清理的端口列表
        force: 为 True 时强制杀死所有占用端口的进程（不验证身份）
               为 False 时仅杀死属于本项目的进程
    """
    if os.name != "nt":
        return
    try:
        out = subprocess.run(
            "netstat -ano", shell=True, capture_output=True,
            encoding="gbk", errors="ignore", creationflags=0x08000000,
        ).stdout
        killed = set()
        skipped = []
        for line in out.splitlines():
            port_str = "|".join(str(p) for p in ports)
            m = re.search(
                rf"\s+TCP\s+[\d\.]+:({port_str})\s+\S+\s+LISTENING\s+(\d+)",
                line,
            )
            if m:
                pid = int(m.group(2))
                port = m.group(1)
                if pid in killed:
                    continue
                if force or _is_our_process(pid):
                    _kill_pid_tree(pid)
                    _sys(f"已终止 PID {pid} (port {port})")
                    killed.add(pid)
                else:
                    skipped.append((pid, port))
        for pid, port in skipped:
            _sys(f"跳过 PID {pid} (port {port}) — 非本项目进程")
    except Exception as e:
        _err(f"清理端口时出错: {e}")

def _wait_port_free(port, timeout=10):
    for _ in range(int(timeout / 0.3)):
        if not _port_in_use(port):
            return True
        time.sleep(0.3)
    return False

# ═══════════════════════════════════════════════════════════
#  查找可执行文件
# ═══════════════════════════════════════════════════════════

def _find_python():
    for p in (ROOT / "venv" / "Scripts" / "python.exe",
              ROOT / ".venv" / "Scripts" / "python.exe"):
        if p.exists():
            return str(p)
    return sys.executable

def _find_node():
    """找到 node.exe（Vite 需要直接用 node 跑，不走 cmd 中间层）"""
    for candidate in ("node", "node.exe"):
        try:
            r = subprocess.run(
                ["where", candidate], capture_output=True, text=True,
                creationflags=0x08000000,
            )
            if r.returncode == 0:
                return r.stdout.strip().splitlines()[0].strip()
        except Exception:
            pass
    return "node"

# ═══════════════════════════════════════════════════════════
#  子进程管理
# ═══════════════════════════════════════════════════════════

class Proc:
    def __init__(self, name, cmd, cwd, log_fn, port=None):
        self.name = name
        self.cmd = cmd
        self.cwd = cwd
        self.log_fn = log_fn
        self.port = port
        self.p = None
        self.fe_port = None
        self.fe_port_event = threading.Event()

    def start(self):
        try:
            flags = 0
            if os.name == "nt":
                flags = subprocess.CREATE_NEW_PROCESS_GROUP | 0x08000000
            self.p = subprocess.Popen(
                self.cmd, cwd=str(self.cwd),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                encoding="utf-8", errors="replace", bufsize=1,
                creationflags=flags,
            )
        except Exception as e:
            _err(f"{self.name} 启动失败: {e}")
            return False

        _assign(self.p.pid)
        threading.Thread(target=self._reader, daemon=True).start()
        self.log_fn(f"已启动 (pid={self.p.pid})")
        return True

    def _reader(self):
        try:
            for raw in self.p.stdout:
                line = raw.rstrip("\n")
                if line:
                    self.log_fn(line)
                    # 检测 Vite 实际端口
                    if "Frontend" in self.name and not self.fe_port_event.is_set():
                        m = re.search(
                            r"http://(?:localhost|127\.0\.0\.1):(\d+)",
                            re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', line),
                        )
                        if m:
                            self.fe_port = int(m.group(1))
                            self.fe_port_event.set()
        except (ValueError, OSError):
            pass

    def stop(self):
        if not self.p:
            return
        if self.p.poll() is not None:
            self.p = None
            return
        self.log_fn("停止中...")
        _kill_pid_tree(self.p.pid)
        try:
            self.p.wait(timeout=5)
        except Exception:
            pass
        self.p = None

    @property
    def alive(self):
        return self.p is not None and self.p.poll() is None

# ═══════════════════════════════════════════════════════════
#  主流程
# ═══════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", action="store_true", help="仅启动后端")
    ap.add_argument("--frontend", action="store_true", help="仅启动前端")
    ap.add_argument("--kill", action="store_true", help="清理残留进程后退出")
    ap.add_argument("--force", "-f", action="store_true",
                    help="强制模式：不验证进程身份，杀掉所有占用端口的进程（慎用）")
    args = ap.parse_args()

    # Windows 颜色
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.kernel32.SetConsoleMode(
                ctypes.windll.kernel32.GetStdHandle(-11), 7
            )
        except Exception:
            pass

    print(f"\n{_B}{_CYN}  Lumina Studio — Dev Launcher v2{_R}\n")

    # ── 仅清理模式 ──
    if args.kill:
        if args.force:
            _sys("强制清理所有占用端口的进程...")
        else:
            _sys("清理本项目残留进程...")
        _kill_listening([BACKEND_PORT, FRONTEND_PORT,
                         FRONTEND_PORT + 1, FRONTEND_PORT + 2,
                         FRONTEND_PORT + 3, FRONTEND_PORT + 4],
                        force=args.force)
        _ok("完成")
        return

    run_b = args.backend or (not args.backend and not args.frontend)
    run_f = args.frontend or (not args.backend and not args.frontend)

    # ── Job Object ──
    _init_job()
    if _job:
        _ok("Job Object 已启用")

    # ── 清理残留（覆盖 Vite 可能顺延到的端口范围）──
    _sys("清理残留进程...")
    ports_to_clean = [BACKEND_PORT]
    if run_f:
        ports_to_clean += [FRONTEND_PORT + i for i in range(6)]
    _kill_listening(ports_to_clean)
    # 等后端端口释放（前端不用等，Vite 自行处理）
    if run_b:
        _wait_port_free(BACKEND_PORT, timeout=10)
    _ok("清理完成")

    # ── 构建命令 ──
    procs = []
    if run_b:
        procs.append(Proc(
            "Backend",
            [_find_python(), "api_server.py"],
            ROOT, _be, BACKEND_PORT,
        ))
    if run_f:
        # 关键：直接用 node 跑 vite.js，不走 cmd /c npm.cmd
        # 这样 Popen 进程就是 node.exe，Job Object 能直接管控
        vite_js = FRONTEND_DIR / "node_modules" / "vite" / "bin" / "vite.js"
        if vite_js.exists():
            fe_cmd = [_find_node(), str(vite_js)]
        else:
            # fallback: 用 npm.cmd（会有 cmd 中间层问题）
            _sys("未找到 vite.js，fallback 到 npm")
            fe_cmd = ["npm", "run", "dev"]
        procs.append(Proc(
            "Frontend",
            fe_cmd,
            FRONTEND_DIR, _fe, FRONTEND_PORT,
        ))

    # ── 启动 ──
    for p in procs:
        if not p.start():
            _err(f"{p.name} 启动失败")

    # ── 等前端端口 ──
    fe_proc = next((p for p in procs if "Frontend" in p.name), None)
    fe_port = FRONTEND_PORT
    if fe_proc and fe_proc.fe_port_event.wait(timeout=5.0):
        fe_port = fe_proc.fe_port

    _ok("全部启动")
    print(f"""{_DIM}────────────────────────────────────────────{_R}
  Backend:  {_CYN}http://localhost:{BACKEND_PORT}{_R}
  Frontend: {_BLU}http://localhost:{fe_port}{_R}
{_DIM}────────────────────────────────────────────{_R}
  {_GRN}r{_R}=重启  {_GRN}s{_R}=状态  {_GRN}q{_R}=退出
{_DIM}────────────────────────────────────────────{_R}
""")

    # ── 退出处理 ──
    def _shutdown():
        for p in procs:
            p.stop()
        _kill_job()

    def _on_signal(signum, frame):
        _sys("退出中...")
        _shutdown()
        os._exit(0)

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    # Windows 控制台关闭
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes
            _cb_ref = None
            _CH = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)
            def _on_console(ctrl):
                if ctrl in (2, 6):
                    _shutdown()
                    os._exit(0)
                return False
            _cb_ref = _CH(_on_console)
            ctypes.windll.kernel32.SetConsoleCtrlHandler(_cb_ref, True)
            # 防 GC
            setattr(_shutdown, '_cb', _cb_ref)
        except Exception:
            pass

    # ── 输入监听 ──
    def _input():
        while True:
            try:
                c = input().strip().lower()
            except (EOFError, KeyboardInterrupt):
                break
            if c in ("r", "restart"):
                _sys("重启...")
                for p in procs:
                    p.stop()
                time.sleep(1)
                _kill_listening(ports_to_clean)
                if run_b:
                    _wait_port_free(BACKEND_PORT, timeout=10)
                for p in procs:
                    p.start()
            elif c in ("s", "status"):
                for p in procs:
                    st = f"{_GRN}运行中{_R}" if p.alive else f"{_RED}已停止{_R}"
                    p.log_fn(st)
            elif c in ("q", "quit"):
                _on_signal(0, None)

    threading.Thread(target=_input, daemon=True).start()

    # ── 主循环 ──
    while True:
        time.sleep(1)
        dead = [p for p in procs if p.p and not p.alive]
        if dead:
            for p in dead:
                _err(f"{p.name} 已退出 (code={p.p.returncode})")
            break  # 有进程挂了就退出，不自动重启

    _shutdown()


if __name__ == "__main__":
    main()
