"""Feedback dump store: serialize bug reports to disk.

Bug 反馈存储：将报告序列化到磁盘。
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

_SAFE_RE = re.compile(r"[^a-zA-Z0-9_-]")
_REPO_ROOT = Path(__file__).resolve().parent.parent


def _resolve_dump_dir() -> Path:
    """Resolve the feedback dump directory.

    解析反馈落盘目录。

    Returns:
        Path: Configured dump directory path.
            配置后的落盘目录路径。
    """

    override = os.environ.get("LUMINA_FEEDBACK_DUMP_DIR")
    if override:
        return Path(override).resolve()
    return (_REPO_ROOT / "feedback").resolve()


def _sanitize_session_candidate(value: object) -> str:
    """Sanitize a session identifier for safe filenames.

    将 session 标识净化为安全文件名片段。

    Args:
        value: Raw candidate session id.
            原始候选 session id。

    Returns:
        str: Sanitized identifier capped to 32 characters.
            已净化且长度不超过 32 的标识。
    """

    return _SAFE_RE.sub("_", str(value))[:32]


def dump_bug_report(payload: dict[str, Any]) -> tuple[Path, str]:
    """Write a bug report payload to stable UTF-8 JSON.

    将 Bug 报告 payload 写入稳定的 UTF-8 JSON 文件。

    Args:
        payload: Report payload to persist.
            需要持久化的报告内容。

    Returns:
        tuple[Path, str]: Written file path and short ticket id.
            写入后的文件路径以及短工单号。
    """

    dump_dir = _resolve_dump_dir()
    dump_dir.mkdir(parents=True, exist_ok=True)

    context = payload.get("context") or {}
    sessions = context.get("active_session_ids") or {}
    candidate = _sanitize_session_candidate(
        sessions.get("converter") or sessions.get("single_stage") or ""
    )
    if not candidate:
        candidate = uuid4().hex[:16]

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"{timestamp}_{candidate}.json"
    path = dump_dir / filename
    if path.exists():
        path = dump_dir / f"{timestamp}_{candidate}_{uuid4().hex[:8]}.json"

    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path, candidate[:8]


def to_dump_path_string(path: Path) -> str:
    """Return a stable response string for a dump path.

    为落盘路径返回稳定的响应字符串。

    Args:
        path: Written dump file path.
            已写入的落盘文件路径。

    Returns:
        str: Repo-relative POSIX path when possible, otherwise absolute POSIX path.
            若可行则返回仓库相对 POSIX 路径，否则返回绝对 POSIX 路径。
    """

    try:
        return path.resolve().relative_to(_REPO_ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()
