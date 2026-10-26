"""Run the full backend + frontend regression suite."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from dataclasses import dataclass
from datetime import datetime
import time

ROOT = Path(__file__).resolve().parents[1]
FRONTEND_LINT_CMD = ["pnpm", "lint"]
FRONTEND_BUILD_CMD = ["pnpm", "build"]
WINDOWS_COMMAND_SHIMS = {"pnpm"}


@dataclass
class CommandResult:
    cmd: list[str]
    returncode: int
    output: str


def run(cmd: list[str], cwd: Path | None = None) -> CommandResult:
    print(f"\n>>> {' '.join(cmd)}")
    if os.name == "nt" and cmd and cmd[0] in WINDOWS_COMMAND_SHIMS:
        proc = subprocess.run(
            ["cmd", "/c", *cmd],
            cwd=cwd or ROOT,
            text=True,
            capture_output=True,
        )
    else:
        proc = subprocess.run(
            cmd,
            cwd=cwd or ROOT,
            text=True,
            capture_output=True,
        )
    output = (proc.stdout or "") + (proc.stderr or "")
    if output:
        print(output, end="" if output.endswith("\n") else "\n")
    return CommandResult(cmd=cmd, returncode=proc.returncode, output=output)


def _extract_failure_summary(output: str) -> str:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    failed_lines = [line for line in lines if line.startswith("FAILED ") or "::" in line and "FAILED" in line]
    if failed_lines:
        return failed_lines[0]
    err_lines = [line for line in lines if "Error" in line or "ERROR" in line]
    if err_lines:
        return err_lines[0]
    return "No structured failure summary found; inspect command output above."


def main() -> int:
    started_at = datetime.now()
    t0 = time.perf_counter()
    print(f"Full gate start: {started_at:%Y-%m-%d %H:%M:%S}")
    vitest_wrapper = ROOT / "scripts" / "run_vitest.py"
    steps: list[tuple[list[str], Path | None, str]] = [
        ([sys.executable, "-m", "pytest", "tests", "-q"], None, "Backend full regression failed"),
        (
            [sys.executable, "-m", "pytest", "tests", "-m", "release", "-q"],
            None,
            "Backend release-marked regression failed",
        ),
        (
            [sys.executable, str(vitest_wrapper), "run"],
            ROOT / "frontend",
            "Frontend full regression failed",
        ),
        (FRONTEND_BUILD_CMD, ROOT / "frontend", "Frontend build failed"),
        (FRONTEND_LINT_CMD, ROOT / "frontend", "Frontend lint failed"),
    ]
    try:
        for cmd, cwd, msg in steps:
            result = run(cmd, cwd=cwd)
            if result.returncode != 0:
                ended_at = datetime.now()
                print(f"\nFull gate failed: {msg}")
                print(f"Failure summary: {_extract_failure_summary(result.output)}")
                print(f"Finished: {ended_at:%Y-%m-%d %H:%M:%S} " f"(duration={time.perf_counter() - t0:.1f}s)")
                print("\nSuggested next steps:")
                print("1) Re-run the failed command only for detailed local debug.")
                print("2) Run `python scripts/run_smoke_tests.py` to restore fast green baseline.")
                print("3) After fix, re-run `python scripts/run_full_tests.py`.")
                return result.returncode
    except Exception as exc:  # noqa: BLE001 - top-level script safeguard
        ended_at = datetime.now()
        print(f"\nFull gate failed with unexpected error: {exc}")
        print(f"Finished: {ended_at:%Y-%m-%d %H:%M:%S} " f"(duration={time.perf_counter() - t0:.1f}s)")
        return 1
    ended_at = datetime.now()
    print("\nFull gate passed.")
    print(f"Finished: {ended_at:%Y-%m-%d %H:%M:%S} " f"(duration={time.perf_counter() - t0:.1f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
