"""Audit Lumina Studio log files for structured logging baseline metrics."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


DEFAULT_LATEST = 1
TOP_EVENT_LIMIT = 20


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments.

    解析命令行参数。
    """
    parser = argparse.ArgumentParser(
        description="Audit Lumina Studio log files for structured event coverage.",
    )
    parser.add_argument(
        "--logs",
        nargs="+",
        required=True,
        type=Path,
        help="Log file or directory paths to audit.",
    )
    parser.add_argument(
        "--latest",
        type=int,
        default=DEFAULT_LATEST,
        help="Use the latest N discovered log files by modification time.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Write JSON report to this path instead of stdout.",
    )
    parser.add_argument(
        "--label",
        default="baseline",
        help="Report label.",
    )
    return parser.parse_args(argv)


def discover_log_files(paths: Iterable[Path]) -> list[Path]:
    """Discover log files from input files and directories.

    从文件和目录参数中发现日志文件。
    """
    files: list[Path] = []
    for raw_path in paths:
        path = raw_path.expanduser()
        if path.is_file():
            files.append(path)
        elif path.is_dir():
            files.extend(sorted(path.rglob("lumina_*.log")))
    return sorted({file.resolve() for file in files}, key=lambda item: str(item))


def select_latest(files: list[Path], latest: int) -> list[Path]:
    """Return the newest log files by modification time.

    按修改时间选择最新日志文件。
    """
    if latest <= 0:
        return []
    return sorted(
        files,
        key=lambda file: (file.stat().st_mtime, str(file)),
        reverse=True,
    )[:latest]


def parse_json_object(line: str) -> dict[str, Any] | None:
    """Parse a JSON object from a raw log line when possible.

    尽可能从原始日志行解析 JSON 对象。
    """
    text = line.strip()
    if not text:
        return None

    candidates = [text]
    brace_index = text.find("{")
    if brace_index > 0:
        candidates.append(text[brace_index:])

    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def event_from_line(line: str) -> tuple[str, bool]:
    """Return the event name and whether the line was structured.

    返回事件名，并标记该行是否为结构化日志。
    """
    payload = parse_json_object(line)
    event = payload.get("event") if payload else None
    if isinstance(event, str) and event:
        return event, True
    return "unstructured", False


def audit_files(files: list[Path], label: str) -> dict[str, Any]:
    """Build the log audit report for selected files.

    为选中的日志文件生成审计报告。
    """
    event_counts: Counter[str] = Counter()
    total_lines = 0
    structured_lines = 0
    total_bytes = 0

    for file in files:
        total_bytes += file.stat().st_size
        with file.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                total_lines += 1
                event, structured = event_from_line(line)
                event_counts[event] += 1
                if structured:
                    structured_lines += 1

    unstructured_lines = total_lines - structured_lines
    duplicate_event_count = sum(
        count - 1 for count in event_counts.values() if count > 1
    )
    request_completed_count = event_counts.get("request_completed", 0)
    top_events = [
        {"event": event, "count": count}
        for event, count in event_counts.most_common(TOP_EVENT_LIMIT)
    ]

    return {
        "duplicate_event_count": duplicate_event_count,
        "duplicate_event_ratio": (
            duplicate_event_count / total_lines if total_lines else 0
        ),
        "event_counts": dict(sorted(event_counts.items())),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input_files": [str(file) for file in files],
        "label": label,
        "request_completed_count": request_completed_count,
        "request_completed_ratio": (
            request_completed_count / total_lines if total_lines else 0
        ),
        "structured_lines": structured_lines,
        "top_events": top_events,
        "total_bytes": total_bytes,
        "total_lines": total_lines,
        "unstructured_lines": unstructured_lines,
    }


def write_report(report: dict[str, Any], output: Path | None) -> None:
    """Write the JSON report to a file or stdout.

    将 JSON 报告写入文件或标准输出。
    """
    content = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if output is None:
        sys.stdout.write(f"{content}\n")
        return

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(f"{content}\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    """Run the audit command.

    执行审计命令。
    """
    args = parse_args(argv)
    files = select_latest(discover_log_files(args.logs), args.latest)
    report = audit_files(files, args.label)
    write_report(report, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
