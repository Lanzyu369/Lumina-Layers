"""Restore materials/ files modified in the last 3 days back to their state at a target commit.

This is a one-shot helper requested by the user: it does NOT touch the live
``materials/`` working tree. It simply mirrors the file contents at
``TARGET_COMMIT`` for every path under ``materials/`` that any commit in the
last 3 days touched, writing them under ``OUT_ROOT`` while preserving the
original directory layout. Files that did not exist at ``TARGET_COMMIT``
(i.e. were newly added during the last 3 days) are listed and skipped.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

TARGET_COMMIT = "83ab6c12a984653e7c2f6272d3e4ff67eea5c337"
OUT_ROOT = Path("materials_3days_ago")
SINCE = "3 days ago"
PATHSPEC = "materials/"


def list_changed_files() -> list[str]:
    raw = subprocess.check_output(
        [
            "git",
            "-c",
            "core.quotepath=off",
            "log",
            f"--since={SINCE}",
            "--name-only",
            "--pretty=format:",
            "--",
            PATHSPEC,
        ],
        encoding="utf-8",
    )
    return sorted({line.strip() for line in raw.splitlines() if line.strip()})


def restore_one(path: str) -> bool:
    """Return True if restored, False if file did not exist at TARGET_COMMIT."""
    proc = subprocess.run(
        ["git", "show", f"{TARGET_COMMIT}:{path}"],
        capture_output=True,
    )
    if proc.returncode != 0:
        return False
    out_path = OUT_ROOT / path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(proc.stdout)
    return True


def main() -> int:
    files = list_changed_files()
    print(f"Files changed in last 3 days under {PATHSPEC}: {len(files)}")
    restored: list[str] = []
    missing: list[str] = []
    for path in files:
        (restored if restore_one(path) else missing).append(path)

    print(f"Restored from {TARGET_COMMIT[:7]} -> {OUT_ROOT}/: {len(restored)}")
    for path in restored:
        print(f"  + {path}")
    print(
        f"Did NOT exist at {TARGET_COMMIT[:7]} "
        f"(new in last 3 days, skipped): {len(missing)}"
    )
    for path in missing:
        print(f"  - {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
