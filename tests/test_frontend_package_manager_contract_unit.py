"""Contracts for frontend package-manager usage in local gates."""

from __future__ import annotations

import json
from pathlib import Path

import start_all
from scripts import run_full_tests, run_realtime_tests, run_smoke_tests

ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DEV_ARGS = ["dev", "--", "--host", "0.0.0.0", "--port", "4174"]


def test_frontend_package_manager_declares_pnpm() -> None:
    package_json = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))

    assert package_json["packageManager"].startswith("pnpm@")


def test_smoke_and_full_lint_gates_use_pnpm() -> None:
    assert run_smoke_tests.FRONTEND_LINT_CMD == ["pnpm", "lint"]
    assert run_full_tests.FRONTEND_LINT_CMD == ["pnpm", "lint"]


def test_realtime_dashboard_frontend_commands_use_pnpm() -> None:
    assert run_realtime_tests.LINT_CMD == ["pnpm", "lint"]
    assert run_realtime_tests.VITEST_WATCH_CMD == ["pnpm", "test:watch:core"]


def test_windows_command_shims_cover_pnpm_only() -> None:
    assert run_smoke_tests.WINDOWS_COMMAND_SHIMS == {"pnpm"}
    assert run_full_tests.WINDOWS_COMMAND_SHIMS == {"pnpm"}
    assert run_realtime_tests.WINDOWS_COMMAND_SHIMS == {"pnpm"}
    assert start_all.WINDOWS_COMMAND_SHIMS == {"pnpm"}
    assert start_all._package_manager_cmd(*FRONTEND_DEV_ARGS, os_name="posix") == ["pnpm", *FRONTEND_DEV_ARGS]
    assert start_all._package_manager_cmd(*FRONTEND_DEV_ARGS, os_name="nt") == [
        "cmd",
        "/c",
        "pnpm",
        *FRONTEND_DEV_ARGS,
    ]


def test_start_all_frontend_fallback_uses_pnpm(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(start_all, "FRONTEND_DIR", tmp_path)

    command = start_all._frontend_cmd()

    if command[:2] == ["cmd", "/c"]:
        command = command[2:]
    assert command == ["pnpm", *FRONTEND_DEV_ARGS]
