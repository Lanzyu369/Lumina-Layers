#!/usr/bin/env python3
"""Pre-PR self-check for the reproducible-bug-reports spec.

Pre-PR 作者自检脚本：跑一遍本 spec 涉及的关键后端 / 前端 / 治理 / 日志检查。

This is **not** wired into CI. CI already runs the individual commands via
the existing test gates (``pytest``, ``scripts/run_vitest.py``,
``scripts/log_quality_check.py``). The script exists so the author can run
everything in one shot before opening the PR.

本脚本不接入 CI（CI 已各自运行这些命令），只作为作者在本地一次性跑完的便捷
入口。退出码：

* ``0`` — 全部通过。
* ``1`` — 某一步失败；对应步骤的 stdout / stderr 已打印，可据此复现。
* ``2`` — 脚本自身错误（例如未找到 Python 解释器）。
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Step:
    """One self-check step: a human label plus the command to run.

    一个自检步骤：展示用的名字 + 实际要执行的命令。
    """

    label: str
    cmd: tuple[str, ...]
    """Command words (argv form; never shell-interpolated)."""
    cwd: Path
    """Working directory; defaults to repo root where it makes sense."""


def _python_exe() -> str:
    """Resolve the Python interpreter to use.

    Prefer the repository's ``.venv`` when present (matches AGENTS.md's
    "Python 环境：.venv 已激活" convention). Fall back to ``sys.executable``
    so the script still works for contributors without the venv.

    选用 Python 解释器：优先仓库 .venv，其次当前解释器。
    """
    candidate = REPO_ROOT / ".venv" / "bin" / "python"
    if candidate.exists():
        return str(candidate)
    return sys.executable


def _build_steps() -> list[Step]:
    """Assemble the canonical self-check workflow.

    Each step is intentionally independent so a failure halts the script at
    the offending step, and the author can re-run only that step.

    生成自检步骤列表；每步独立，失败时可单独复现。
    """
    py = _python_exe()
    return [
        Step(
            label="pytest · feedback family",
            cmd=(py, "-m", "pytest", "tests/", "-k", "feedback", "-q"),
            cwd=REPO_ROOT,
        ),
        Step(
            label="pytest · logging and errors",
            cmd=(
                py,
                "-m",
                "pytest",
                "tests/test_api_errors_unit.py",
                "tests/test_structured_logging_unit.py",
                "tests/test_logger_unit.py",
                "-q",
            ),
            cwd=REPO_ROOT,
        ),
        Step(
            label="tsc · frontend typecheck",
            cmd=("pnpm", "exec", "tsc", "--noEmit", "-p", "tsconfig.app.json"),
            cwd=REPO_ROOT / "frontend",
        ),
        Step(
            label="vitest · feedback front-end surfaces",
            cmd=(
                py,
                "scripts/run_vitest.py",
                "run",
                "src/stores/__tests__/actionHistoryStore.test.ts",
                "src/utils/__tests__/clientLog.test.ts",
                "src/utils/__tests__/bugReportContext.test.ts",
                "src/components/__tests__/BugReportModal.test.tsx",
                "src/__tests__/useReproMode.test.ts",
                "src/__tests__/useAnnouncement.test.ts",
                "src/__tests__/announcement-dialog.test.tsx",
            ),
            cwd=REPO_ROOT,
        ),
        Step(
            label="log_quality_check · fast gate",
            cmd=(py, "scripts/log_quality_check.py", "--mode", "fast"),
            cwd=REPO_ROOT,
        ),
    ]


def _print_header(idx: int, total: int, step: Step) -> None:
    """Render a consistent banner for each step.

    为每个步骤打印统一的分隔符，方便日志阅读。
    """
    divider = "=" * 72
    print(f"\n{divider}\n[{idx}/{total}] {step.label}\n  $ {' '.join(step.cmd)}\n{divider}\n")


def _run_step(step: Step) -> int:
    """Execute one step and return its exit code.

    Inherits stdio so the author sees real-time output. Streaming rather
    than capturing avoids hiding long-running progress (pytest, vitest,
    log_quality_check can all take many seconds).

    执行一个步骤并返回退出码。继承 stdio 保留实时输出。
    """
    try:
        completed = subprocess.run(
            step.cmd,
            cwd=str(step.cwd),
            check=False,
        )
    except FileNotFoundError as exc:
        print(f"missing executable for step '{step.label}': {exc}", file=sys.stderr)
        return 127
    return completed.returncode


def _iter_steps(selected: Iterable[int] | None, steps: list[Step]) -> list[tuple[int, Step]]:
    """Filter steps by 1-based ``--step`` CLI argument if provided.

    按 1-based 序号过滤步骤；无过滤则返回全部。
    """
    indexed = list(enumerate(steps, start=1))
    if selected is None:
        return indexed
    wanted = set(selected)
    return [(idx, s) for idx, s in indexed if idx in wanted]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Pre-PR self-check for reproducible-bug-reports spec.",
    )
    parser.add_argument(
        "--step",
        type=int,
        action="append",
        default=None,
        metavar="N",
        help="Run only the Nth step (1-based). Can be passed multiple times. "
             "If omitted, all steps run in order.",
    )
    args = parser.parse_args(argv)

    if shutil.which("npx") is None and any(
        step.cmd and step.cmd[0] == "npx" for step in _build_steps()
    ):
        print("error: `npx` is not on PATH; install Node.js to run the frontend steps.", file=sys.stderr)
        return 2

    os.environ.setdefault("LUMINA_FEEDBACK_STARTUP_CLEANUP", "false")

    steps = _build_steps()
    chosen = _iter_steps(args.step, steps)
    total = len(chosen)

    if total == 0:
        print("no steps selected; --step must reference a valid 1-based index.", file=sys.stderr)
        return 2

    failures: list[tuple[int, Step, int]] = []
    for position, (idx, step) in enumerate(chosen, start=1):
        _print_header(position, total, step)
        rc = _run_step(step)
        if rc != 0:
            failures.append((idx, step, rc))

    print("\n" + "=" * 72)
    if failures:
        print("FAILURES:")
        for idx, step, rc in failures:
            print(f"  step #{idx} ({step.label}): exit {rc}")
        print("=" * 72)
        return 1

    print("All self-check steps passed.")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())
