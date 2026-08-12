#!/usr/bin/env python3
"""Rebuild a reproducible session from a bug-report ticket directory.

从 Bug 工单目录重建本地复现 session。

Given a ticket id like ``LUM-202605-deadbeef``, this CLI:

1. Locates ``feedback/<YYYY-MM>/<ticket_id>/`` under the repo root.
2. Copies ``original.*``, ``final.*``, ``lut.*``, ``materials.zip``,
   ``screenshot.*`` into ``repro_sessions/<ticket_id>/`` so the user can
   drop them into the running app.
3. Extracts ``materials.zip`` next to them as ``materials/`` for easy
   inspection.
4. Writes a companion ``repro_manifest.md`` that lists every attachment,
   the most recent 10 user actions, and copy-pasteable hints for opening
   the session in a running frontend via ``?repro_session=<ticket_id>``.

The script is **read-only** with respect to the repo's canonical
``materials/`` and ``lut-preset/`` directories — it never writes there.
Missing attachments never abort execution; the manifest records what was
and was not available so partial tickets are still usable.

给定工单号（如 ``LUM-202605-deadbeef``），CLI 会把工单目录下的原图 / 生成
产物 / LUT / 耗材 zip / 截图复制到 ``repro_sessions/<ticket_id>/``，同时
把 materials.zip 解压到该目录下，便于在本地运行的前端中使用。脚本以只读
方式访问仓库内的 ``materials/`` 与 ``lut-preset/``，绝不在主目录写入。
缺失的附件不会中断执行：生成的 ``repro_manifest.md`` 会如实列出哪些附件
可用、哪些缺失，确保部分工单也能用。
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_NEW_TICKET_ID_PATTERN = re.compile(r"^LUM-(\d{6})-[0-9a-f]{8}$")
_HISTORICAL_TICKET_ID_PATTERN = re.compile(
    r"^LUM-(\d{8})-(?:\d{3}|[0-9a-f]{8})$"
)


@dataclass(frozen=True)
class LoadReproResult:
    """Outcome of :func:`load_bug_repro`.

    :func:`load_bug_repro` 的返回结构。
    """

    ticket_id: str
    source_dir: Path
    repro_dir: Path
    manifest_path: Path
    attachments_copied: list[str]
    attachments_missing: list[str]


def _find_ticket_dir(feedback_root: Path, ticket_id: str) -> Path | None:
    """Locate ``feedback/<YYYY-MM>/<ticket_id>/`` via the ticket id's date."""
    # New ids are LUM-YYYYMM-xxxxxxxx; historical ids are
    # LUM-YYYYMMDD-NNN. Derive the month from either date component, then
    # walk month dirs as a fallback for manually moved tickets.
    match = _NEW_TICKET_ID_PATTERN.fullmatch(ticket_id)
    if match is None:
        match = _HISTORICAL_TICKET_ID_PATTERN.fullmatch(ticket_id)
    if match is None:
        return None

    date_component = match.group(1)
    feedback_root_resolved = feedback_root.resolve()
    month = f"{date_component[:4]}-{date_component[4:6]}"
    direct = feedback_root / month / ticket_id
    try:
        direct.resolve().relative_to(feedback_root_resolved)
    except ValueError:
        return None
    if direct.is_dir():
        return direct
    if not feedback_root.is_dir():
        return None
    for month_dir in feedback_root.iterdir():
        if not month_dir.is_dir():
            continue
        candidate = month_dir / ticket_id
        try:
            candidate.resolve().relative_to(feedback_root_resolved)
        except ValueError:
            continue
        if candidate.is_dir():
            return candidate
    return None


def _copy_attachments(
    source_dir: Path, repro_dir: Path,
) -> tuple[list[str], list[str]]:
    """Copy bulky attachments from ``source_dir`` into ``repro_dir``.

    按照 design §5 列表，把 original/final/lut/materials.zip/screenshot 复制
    到复现目录；同时把 ticket.json / index.md / summary.txt 也复制一份。
    """
    wanted_patterns = (
        "original.*",
        "final.*",
        "lut.*",
        "materials.zip",
        "screenshot.*",
        "ticket.json",
        "index.md",
        "summary.txt",
        "client_logs.jsonl",
    )
    copied: list[str] = []
    missing: list[str] = []
    seen: set[str] = set()
    for pattern in wanted_patterns:
        matches = list(source_dir.glob(pattern))
        if not matches:
            missing.append(pattern)
            continue
        for match in matches:
            if match.name in seen:
                continue
            seen.add(match.name)
            target = repro_dir / match.name
            try:
                shutil.copy2(match, target)
                copied.append(match.name)
            except OSError as exc:
                missing.append(f"{match.name} (copy failed: {exc})")
    return copied, missing


def _safe_extract_zip(zip_path: Path, target: Path) -> bool:
    """Safely extract a zip file, rejecting entries that escape ``target``.

    安全解压 zip 文件，拒绝逃逸到 ``target`` 目录外的条目。

    Args:
        zip_path: Path to the zip file.
        target: Destination directory for extraction.

    Returns:
        bool: True if extraction succeeded (possibly with skipped entries),
            False if the zip is invalid or all entries are unsafe.
    """
    target_resolved = target.resolve()
    try:
        with zipfile.ZipFile(zip_path) as zf:
            for member in zf.infolist():
                # Skip directories — they will be created as needed.
                if member.is_dir():
                    continue
                # Compute the destination path and verify it stays inside target.
                dest = (target / member.filename).resolve()
                try:
                    dest.relative_to(target_resolved)
                except ValueError:
                    # Path escapes target — skip this entry silently.
                    continue
                # Ensure parent directories exist.
                dest.parent.mkdir(parents=True, exist_ok=True)
                # Extract the single member.
                with zf.open(member) as src, open(dest, "wb") as dst:
                    import shutil as _shutil
                    _shutil.copyfileobj(src, dst)
    except (zipfile.BadZipFile, OSError):
        return False
    return True


def _maybe_extract_materials(repro_dir: Path) -> Path | None:
    """Extract ``materials.zip`` into ``repro_dir/materials/`` if present."""
    zip_path = repro_dir / "materials.zip"
    if not zip_path.is_file():
        return None
    target = repro_dir / "materials"
    target.mkdir(exist_ok=True)
    success = _safe_extract_zip(zip_path, target)
    if not success:
        return None
    return target


def _format_recent_actions(action_history: Iterable[Any]) -> list[str]:
    """Render the most recent 10 actions as bullet lines for the manifest."""
    rows = list(action_history)[-10:] if action_history else []
    lines: list[str] = []
    for entry in rows:
        if not isinstance(entry, dict):
            continue
        ts_raw = entry.get("timestamp")
        ts = "?"
        if isinstance(ts_raw, (int, float)):
            try:
                ts = datetime.fromtimestamp(ts_raw / 1000.0).strftime("%H:%M:%S")
            except (OSError, ValueError, OverflowError):
                ts = "?"
        action = entry.get("action_type", "?")
        changed = entry.get("changed_fields")
        if isinstance(changed, dict) and changed:
            fields = ", ".join(changed.keys())
            lines.append(f"- `{ts}` {action} (changed: {fields})")
        elif entry.get("error"):
            err = entry["error"] or {}
            lines.append(
                f"- `{ts}` {action} "
                f"{err.get('path', '?')} ({err.get('status_code', '?')})"
            )
        else:
            lines.append(f"- `{ts}` {action}")
    return lines


def _write_repro_manifest(
    repro_dir: Path,
    ticket_id: str,
    payload: dict[str, Any],
    copied: list[str],
    missing: list[str],
    materials_extracted_to: Path | None,
) -> Path:
    """Write ``repro_manifest.md`` next to the copied attachments."""
    context = payload.get("context") or {}
    description = payload.get("description") or "(no description)"
    received = payload.get("received_at_cst") or "(unknown)"
    recent_lines = _format_recent_actions(context.get("action_history") or [])
    copied_block = "\n".join(f"- {name}" for name in copied) if copied else "_(none)_"
    missing_block = (
        "\n".join(f"- {name}" for name in missing) if missing else "_(none)_"
    )
    materials_block = (
        f"- extracted to `{materials_extracted_to}`"
        if materials_extracted_to
        else "_(no materials.zip)_"
    )
    lines = [
        f"# Reproduction manifest for {ticket_id}",
        "",
        f"Received (Beijing): {received}",
        "",
        "## Description",
        "",
        description,
        "",
        "## Copied attachments",
        "",
        copied_block,
        "",
        "## Missing attachments",
        "",
        missing_block,
        "",
        "## Materials bundle",
        "",
        materials_block,
        "",
        "## Most recent user actions (last 10)",
        "",
        "\n".join(recent_lines) if recent_lines else "_(no action history recorded)_",
        "",
        "## Next step",
        "",
        "1. Start the dev stack (`python start_dev.py` or your usual command).",
        f"2. Open the frontend with `?repro_session={ticket_id}` to flag the",
        "   session as a reproduction run (the UI shows a small banner).",
        "3. Upload `original.*` via the normal flow; the LUT / materials",
        "   archive shown above should match what the user had selected.",
        "",
    ]
    manifest_path = repro_dir / "repro_manifest.md"
    manifest_path.write_text("\n".join(lines), encoding="utf-8")
    return manifest_path


def load_bug_repro(
    ticket_id: str,
    feedback_root: Path | None = None,
    repro_root: Path | None = None,
) -> LoadReproResult:
    """Rebuild a reproducible session directory for ``ticket_id``.

    为 ``ticket_id`` 重建复现 session 目录。

    Args:
        ticket_id: Ticket id, e.g. ``LUM-202605-deadbeef``.
        feedback_root: Optional custom feedback root directory.
            (可选的工单根目录，覆盖默认 ``<repo>/feedback``。)
        repro_root: Optional custom reproduction-session parent directory.
            (可选的复现目录根，覆盖默认 ``<repo>/repro_sessions``。)

    Returns:
        LoadReproResult: Full diagnostic record of the operation.

    Raises:
        FileNotFoundError: When the ticket directory cannot be located.
    """
    feedback_root = feedback_root or (REPO_ROOT / "feedback")
    repro_root = repro_root or (REPO_ROOT / "repro_sessions")

    source_dir = _find_ticket_dir(feedback_root, ticket_id)
    if source_dir is None:
        raise FileNotFoundError(
            f"ticket {ticket_id} not found under {feedback_root}",
        )

    repro_root_resolved = repro_root.resolve()
    repro_dir = repro_root / ticket_id
    try:
        repro_dir.resolve().relative_to(repro_root_resolved)
    except ValueError as exc:
        raise FileNotFoundError(
            f"ticket {ticket_id} has an invalid reproduction path",
        ) from exc
    repro_dir.mkdir(parents=True, exist_ok=True)

    copied, missing = _copy_attachments(source_dir, repro_dir)
    materials_dir = _maybe_extract_materials(repro_dir)

    ticket_json_path = repro_dir / "ticket.json"
    payload: dict[str, Any] = {}
    if ticket_json_path.exists():
        try:
            payload = json.loads(ticket_json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}

    manifest_path = _write_repro_manifest(
        repro_dir, ticket_id, payload, copied, missing, materials_dir,
    )
    return LoadReproResult(
        ticket_id=ticket_id,
        source_dir=source_dir,
        repro_dir=repro_dir,
        manifest_path=manifest_path,
        attachments_copied=copied,
        attachments_missing=missing,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Rebuild a reproducible session from a bug-report ticket.",
    )
    parser.add_argument("ticket_id", help="Ticket id, e.g. LUM-202605-deadbeef")
    parser.add_argument(
        "--feedback-root",
        type=Path,
        default=None,
        help="Override the feedback root directory (default: <repo>/feedback)",
    )
    parser.add_argument(
        "--repro-root",
        type=Path,
        default=None,
        help="Override the reproduction-session root (default: <repo>/repro_sessions)",
    )
    args = parser.parse_args(argv)

    try:
        result = load_bug_repro(
            args.ticket_id,
            feedback_root=args.feedback_root,
            repro_root=args.repro_root,
        )
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(f"Reproduction bundle ready: {result.repro_dir}")
    print(f"Manifest: {result.manifest_path}")
    if result.attachments_copied:
        print(f"Copied: {', '.join(result.attachments_copied)}")
    if result.attachments_missing:
        print(f"Missing: {', '.join(result.attachments_missing)}")
    print(
        "Open the frontend with "
        f"?repro_session={result.ticket_id} once the dev stack is running.",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
