"""Run local realtime test dashboard (smoke/lint polling + vitest watch).

This script is for local developer feedback and does not replace CI gates.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / ".cache" / "test-dashboard"

SMOKE_CMD = [sys.executable, "-m", "pytest", "tests", "-m", "smoke", "-q"]
LINT_CMD = ["pnpm", "lint"]
VITEST_WATCH_CMD = ["pnpm", "test:watch:core"]
WINDOWS_COMMAND_SHIMS = {"pnpm"}


@dataclass
class CheckStatus:
    name: str
    ok: bool | None = None
    last_run_ts: float | None = None
    last_success_ts: float | None = None
    duration_s: float | None = None
    failure_count: int = 0
    last_failure: str = ""
    log_path: Path | None = None
    running: bool = False


def _run_command(cmd: list[str], cwd: Path, log_path: Path) -> tuple[int, str]:
    if os.name == "nt" and cmd and cmd[0] in WINDOWS_COMMAND_SHIMS:
        full_cmd = ["cmd", "/c", *cmd]
    else:
        full_cmd = cmd
    timeout_s = 900 if "pytest" in " ".join(cmd) else 600
    proc = subprocess.run(
        full_cmd,
        cwd=cwd,
        text=True,
        capture_output=True,
        timeout=timeout_s,
    )
    output = (proc.stdout or "") + (proc.stderr or "")
    with log_path.open("a", encoding="utf-8") as f:
        f.write(f"\n[{datetime.now().isoformat(timespec='seconds')}] $ {' '.join(cmd)}\n")
        f.write(output)
        if not output.endswith("\n"):
            f.write("\n")
    return proc.returncode, output


def _extract_failure(output: str) -> str:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    for line in lines:
        if line.startswith("FAILED "):
            return line
    for line in lines:
        if "ERROR" in line or "Error" in line:
            return line
    return "Unknown failure (check log file)"


def _periodic_runner(
    status: CheckStatus,
    cmd: list[str],
    cwd: Path,
    interval_s: int,
    stop_event: threading.Event,
) -> None:
    while not stop_event.is_set():
        started = time.perf_counter()
        status.running = True
        status.last_run_ts = time.time()
        try:
            code, output = _run_command(cmd, cwd, status.log_path or LOG_DIR / f"{status.name}.log")
            status.ok = code == 0
            if code == 0:
                status.last_success_ts = time.time()
                status.last_failure = ""
                status.failure_count = 0
            else:
                status.failure_count += 1
                status.last_failure = _extract_failure(output)
        except subprocess.TimeoutExpired as exc:
            status.ok = False
            status.failure_count += 1
            status.last_failure = f"command timeout after {exc.timeout}s: {' '.join(cmd)}"
        except Exception as exc:  # noqa: BLE001 - worker-thread safeguard
            status.ok = False
            status.failure_count += 1
            status.last_failure = f"runner crashed: {type(exc).__name__}: {exc}"
        finally:
            status.duration_s = time.perf_counter() - started
            status.running = False

        # Sleep with early-exit checks.
        for _ in range(interval_s):
            if stop_event.is_set():
                return
            time.sleep(1)


def _vitest_watch_runner(status: CheckStatus, stop_event: threading.Event) -> None:
    log_path = status.log_path or LOG_DIR / "vitest-watch.log"
    status.running = True
    if os.name == "nt" and VITEST_WATCH_CMD[0] in WINDOWS_COMMAND_SHIMS:
        cmd = ["cmd", "/c", *VITEST_WATCH_CMD]
    else:
        cmd = VITEST_WATCH_CMD

    with log_path.open("a", encoding="utf-8") as log_file:
        log_file.write(f"\n[{datetime.now().isoformat(timespec='seconds')}] $ {' '.join(VITEST_WATCH_CMD)}\n")
        proc = subprocess.Popen(
            cmd,
            cwd=ROOT / "frontend",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        try:
            while not stop_event.is_set():
                line = proc.stdout.readline() if proc.stdout is not None else ""
                if line:
                    log_file.write(line)
                    log_file.flush()
                    status.last_run_ts = time.time()
                elif proc.poll() is not None:
                    status.ok = proc.returncode == 0
                    status.running = False
                    if proc.returncode != 0:
                        status.failure_count += 1
                        status.last_failure = f"vitest watch exited with {proc.returncode}"
                    return
                else:
                    time.sleep(0.2)
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
            status.running = False


def _parse_vitest_watch_summary(log_path: Path) -> tuple[bool | None, str]:
    if not log_path.exists():
        return None, "waiting for vitest output..."
    text = log_path.read_text(encoding="utf-8", errors="ignore")
    test_files = re.findall(r"Test Files\s+([^\n]+)", text)
    if not test_files:
        return None, "running..."
    latest = test_files[-1].strip()
    is_ok = "failed" not in latest.lower()
    return is_ok, f"Test Files {latest}"


def _fmt_ts(ts: float | None) -> str:
    if ts is None:
        return "-"
    return datetime.fromtimestamp(ts).strftime("%H:%M:%S")


def _render_panel(smoke: CheckStatus, lint: CheckStatus | None, vitest: CheckStatus) -> None:
    os.system("cls" if os.name == "nt" else "clear")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("Lumina Local Realtime Test Dashboard")
    print(f"Now: {now}")
    print(f"Logs: {LOG_DIR}")
    print("-" * 72)

    vitest_ok, vitest_info = _parse_vitest_watch_summary(vitest.log_path or LOG_DIR / "vitest-watch.log")
    vitest_state = "RUNNING" if vitest.running else ("PASS" if vitest_ok else "FAIL")
    print(f"[vitest-watch] state={vitest_state}  info={vitest_info}")

    smoke_state = "RUNNING" if smoke.running else ("PASS" if smoke.ok else "FAIL" if smoke.ok is False else "INIT")
    print(
        f"[smoke]       state={smoke_state}  last_run={_fmt_ts(smoke.last_run_ts)}"
        f"  last_ok={_fmt_ts(smoke.last_success_ts)}  dur={smoke.duration_s or 0:.1f}s  fails={smoke.failure_count}"
    )
    if smoke.last_failure:
        print(f"  └─ last failure: {smoke.last_failure}")

    if lint is not None:
        lint_state = "RUNNING" if lint.running else ("PASS" if lint.ok else "FAIL" if lint.ok is False else "INIT")
        print(
            f"[lint]        state={lint_state}  last_run={_fmt_ts(lint.last_run_ts)}"
            f"  last_ok={_fmt_ts(lint.last_success_ts)}  dur={lint.duration_s or 0:.1f}s  fails={lint.failure_count}"
        )
        if lint.last_failure:
            print(f"  └─ last failure: {lint.last_failure}")

    print("-" * 72)
    print("Stop with Ctrl+C")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Local realtime dashboard for smoke/lint/vitest-watch.")
    parser.add_argument("--smoke-interval", type=int, default=60, help="Seconds between smoke checks.")
    parser.add_argument("--lint-interval", type=int, default=180, help="Seconds between lint checks.")
    parser.add_argument("--no-lint", action="store_true", help="Disable periodic lint checks.")
    parser.add_argument("--panel-interval", type=float, default=1.0, help="Seconds between panel refresh.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stop_event = threading.Event()

    smoke = CheckStatus(name="smoke", log_path=LOG_DIR / "smoke.log")
    vitest = CheckStatus(name="vitest-watch", log_path=LOG_DIR / "vitest-watch.log")
    lint = None if args.no_lint else CheckStatus(name="lint", log_path=LOG_DIR / "lint.log")

    threads: list[threading.Thread] = [
        threading.Thread(
            target=_periodic_runner,
            args=(smoke, SMOKE_CMD, ROOT, args.smoke_interval, stop_event),
            daemon=True,
        ),
        threading.Thread(
            target=_vitest_watch_runner,
            args=(vitest, stop_event),
            daemon=True,
        ),
    ]
    if lint is not None:
        threads.append(
            threading.Thread(
                target=_periodic_runner,
                args=(lint, LINT_CMD, ROOT / "frontend", args.lint_interval, stop_event),
                daemon=True,
            )
        )

    for t in threads:
        t.start()

    try:
        while True:
            _render_panel(smoke, lint, vitest)
            time.sleep(args.panel_interval)
    except KeyboardInterrupt:
        stop_event.set()
        for t in threads:
            t.join(timeout=2.0)
        print("\nRealtime dashboard stopped.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
