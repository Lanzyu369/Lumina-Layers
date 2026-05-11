"""Render human-readable index.md and summary.txt for a bug ticket.

为 Bug 工单生成便于人读的 index.md 与便于 AI 读的 summary.txt。

These files sit next to ticket.json inside ``feedback/<YYYY-MM>/<ticket_id>/``
so a developer can ``cat index.md`` on the server and see the complete
repro state at a glance without parsing JSON. Templates follow
``.kiro/specs/reproducible-bug-reports/design.md`` §6 and §7.

Both functions are defensive: a malformed / partial payload never raises —
missing fields show up as literal ``(missing)`` placeholders so the ticket
is still salvageable rather than the ticket assembler crashing half-way.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

__all__ = [
    "generate_index_markdown",
    "generate_summary_text",
]


_MISSING = "(missing)"
_RECENT_ACTIONS_LIMIT = 10
_RECENT_API_ERRORS_LIMIT = 5


def _safe_str(value: Any) -> str:
    """Return a printable representation of ``value`` for markdown cells.

    安全转换为 markdown 单元格字符串；None → ``(missing)``，空串同样。
    """
    if value is None:
        return _MISSING
    text = str(value)
    if text == "":
        return _MISSING
    # Escape pipes so markdown tables don't break.
    return text.replace("|", "\\|")


def _iter_list(value: Any) -> Iterable[Any]:
    """Yield items if ``value`` is list-like, otherwise yield nothing."""
    if isinstance(value, list):
        yield from value


def _format_timestamp_ms(ts: Any) -> str:
    """Format a millisecond epoch into HH:MM:SS for brevity in tables.

    毫秒级 epoch → 短时间格式（HH:MM:SS）；非法输入返回 ``(missing)``。
    """
    if not isinstance(ts, (int, float)):
        return _MISSING
    try:
        from datetime import datetime, timezone

        dt = datetime.fromtimestamp(ts / 1000.0, tz=timezone.utc)
        return dt.strftime("%H:%M:%S")
    except (OSError, ValueError, OverflowError):
        return _MISSING


def _collect_api_errors(action_history: Any) -> list[dict[str, Any]]:
    """Extract the recent api_error entries from action history."""
    errors: list[dict[str, Any]] = []
    for entry in _iter_list(action_history):
        if not isinstance(entry, dict):
            continue
        if entry.get("action_type") != "api_error":
            continue
        errors.append(entry)
    return errors


def _format_actions_table(action_history: Any) -> str:
    """Markdown table of the most recent ``_RECENT_ACTIONS_LIMIT`` actions."""
    rows = list(_iter_list(action_history))[-_RECENT_ACTIONS_LIMIT:]
    if not rows:
        return "_(no actions recorded)_\n"
    lines = ["| time | action | changed | snapshot |", "|---|---|---|---|"]
    for entry in rows:
        if not isinstance(entry, dict):
            continue
        ts = _format_timestamp_ms(entry.get("timestamp"))
        action = _safe_str(entry.get("action_type"))
        changed_fields = entry.get("changed_fields") or {}
        if isinstance(changed_fields, dict) and changed_fields:
            parts = []
            for field_name, delta in changed_fields.items():
                if isinstance(delta, dict):
                    parts.append(
                        f"{field_name}: {delta.get('from')!r}→{delta.get('to')!r}"
                    )
            changed = ", ".join(parts) if parts else _MISSING
        else:
            changed = _MISSING
        snapshot = entry.get("snapshot") or {}
        snap_parts = []
        if isinstance(snapshot, dict):
            for key in ("source_version", "color_mode", "lut_name", "active_tab"):
                if snapshot.get(key):
                    snap_parts.append(f"{key}={snapshot[key]}")
        snap = " / ".join(snap_parts) if snap_parts else _MISSING
        lines.append(
            f"| {ts} | {action} | {_safe_str(changed)} | {_safe_str(snap)} |"
        )
    return "\n".join(lines) + "\n"


def _format_api_errors_table(action_history: Any) -> str:
    errors = _collect_api_errors(action_history)[-_RECENT_API_ERRORS_LIMIT:]
    if not errors:
        return ""
    lines = [
        "",
        "## Recent API Errors (last 5)",
        "",
        "| time | status | path | message |",
        "|---|---|---|---|",
    ]
    for entry in errors:
        if not isinstance(entry, dict):
            continue
        ts = _format_timestamp_ms(entry.get("timestamp"))
        err = entry.get("error") or {}
        status = err.get("status_code") if isinstance(err, dict) else None
        path = err.get("path") if isinstance(err, dict) else None
        msg = err.get("error_message") if isinstance(err, dict) else None
        lines.append(
            f"| {ts} | {_safe_str(status)} | "
            f"{_safe_str(path)} | {_safe_str(msg)} |"
        )
    return "\n".join(lines) + "\n"


def _format_attachments_table(attachments: Any) -> str:
    if not isinstance(attachments, dict) or not attachments:
        return "_(no attachments)_\n"
    lines = ["| kind | status | filename | size (bytes) | sha256 / detail |", "|---|---|---|---|---|"]
    known = (
        "original_image",
        "final_artifact",
        "lut",
        "materials_bundle",
        "screenshot",
    )
    for kind in known:
        entry = attachments.get(kind) if isinstance(attachments, dict) else None
        if not isinstance(entry, dict):
            lines.append(f"| {kind} | {_MISSING} | {_MISSING} | {_MISSING} | {_MISSING} |")
            continue
        status = _safe_str(entry.get("status"))
        filename = _safe_str(entry.get("filename"))
        size = entry.get("size_bytes") or entry.get("compressed_size_bytes")
        detail_parts: list[str] = []
        if entry.get("sha256"):
            detail_parts.append(f"sha256={entry['sha256'][:12]}…")
        if kind == "lut":
            if entry.get("kind"):
                detail_parts.append(f"kind={entry['kind']}")
            if entry.get("preset_relative_path"):
                detail_parts.append(f"preset={entry['preset_relative_path']}")
        if kind == "materials_bundle":
            if entry.get("entry_count"):
                detail_parts.append(f"entries={entry['entry_count']}")
            if entry.get("included_dirs"):
                detail_parts.append(
                    f"dirs={len(entry['included_dirs'])}"
                )
        detail = ", ".join(detail_parts) if detail_parts else _MISSING
        lines.append(
            f"| {kind} | {status} | {filename} | {_safe_str(size)} | {detail} |"
        )
    return "\n".join(lines) + "\n"


def _reproduction_suggestion(
    ticket_id: str, context: dict[str, Any]
) -> list[str]:
    """Build a small list of reproduction tips.

    Rules:
      * If the recent action history contains an ``api_error``, surface the
        most recent one so the developer knows where to start.
      * If ``source_version == 'material'`` AND ``material_layer_count`` is
        known, call out the high-fidelity material-archive mode.
      * Always include the ``load_bug_repro.py`` pointer.

    启发式复现建议：最近 API 错误、耗材档案高保真提醒、以及统一的
    ``load_bug_repro.py`` 入口。
    """
    lines: list[str] = []
    action_history = context.get("action_history")
    api_errors = _collect_api_errors(action_history)
    if api_errors:
        last = api_errors[-1]
        err = last.get("error") or {}
        path = err.get("path") if isinstance(err, dict) else None
        status_code = err.get("status_code") if isinstance(err, dict) else None
        if path and status_code is not None:
            lines.append(
                f"最后一次 API 错误在 `{path}` ({status_code})，从此处开始调试。"
                f" / Last API error at `{path}` ({status_code}) — start debugging there."
            )
    if (
        context.get("source_version") == "material"
        and context.get("material_layer_count") is not None
    ):
        layers = context.get("material_layer_count")
        lines.append(
            f"用户使用耗材档案高保真模式（{layers} 层）；确认档案正确加载。"
            f" / User was in material-archive high-fidelity mode ({layers} layers);"
            " verify the material archive loaded correctly."
        )
    lines.append(
        f"运行 `python scripts/load_bug_repro.py {ticket_id}` 可在本地重建 session。"
        f" / Run the command above to rebuild the session locally."
    )
    return lines


def generate_index_markdown(
    ticket_id: str,
    ticket_dir: Path,
    payload: dict[str, Any],
) -> str:
    """Render a human-readable index.md for ``ticket_id``.

    为 ``ticket_id`` 渲染人类可读的 index.md。
    Args:
        ticket_id: Short ticket id (``LUM-YYYYMMDD-NNN``).
        ticket_dir: Ticket directory (used only for relative-path hints).
        payload: Loaded ticket.json payload (best-effort parsed).
    Returns:
        str: UTF-8 markdown document; never empty.
    """
    context = payload.get("context") or {}
    received_cst = _safe_str(payload.get("received_at_cst"))
    user_email = _safe_str(payload.get("user_email"))
    description = _safe_str(payload.get("description"))
    attachments = payload.get("attachments") or {}
    session_history = context.get("session_history") or []

    snapshot_lines = []
    for key in (
        "active_tab",
        "source_version",
        "color_mode",
        "lut_name",
        "selected_material_dir_names",
        "material_layer_count",
        "material_layer_height_mm",
        "material_backing_material_dir_name",
    ):
        snapshot_lines.append(f"- {key}: {_safe_str(context.get(key))}")

    session_lines = []
    raw_sessions = list(_iter_list(session_history))
    for entry in raw_sessions[:5]:
        if not isinstance(entry, dict):
            continue
        session_lines.append(
            f"- {entry.get('workstream', 'unknown')}: "
            f"{entry.get('session_id', '(missing)')} "
            f"(last_seen_at={entry.get('last_seen_at', '?')})"
        )

    repro_tips = _reproduction_suggestion(ticket_id, context)
    repro_block = "\n".join(f"{i + 1}. {line}" for i, line in enumerate(repro_tips))

    out = [
        f"# Bug Ticket {ticket_id}",
        "",
        f"Received (Beijing): {received_cst}  ",
        f"User email: {user_email}",
        "",
        "## Description",
        "",
        description,
        "",
        "## Workflow Snapshot (at submit time)",
        "",
        *snapshot_lines,
        "",
        "## Recent Actions (last 10)",
        "",
        _format_actions_table(context.get("action_history")).rstrip(),
    ]
    api_errors_section = _format_api_errors_table(context.get("action_history"))
    if api_errors_section:
        out.append(api_errors_section.rstrip())
    out.extend(
        [
            "",
            "## Attachments",
            "",
            _format_attachments_table(attachments).rstrip(),
            "",
            "## Reproduction Suggestion",
            "",
            repro_block,
            "",
            "## Session IDs for backend log grep",
            "",
            "\n".join(session_lines) if session_lines else "_(no session history recorded)_",
            "",
            "grep recipe:",
            "",
            "```",
            "jq 'select(.session_id == \"<paste here>\")' logs/lumina_*.log",
            "```",
            "",
        ]
    )
    return "\n".join(out)


def generate_summary_text(ticket_id: str, payload: dict[str, Any]) -> str:
    """Render a compact Chinese summary for AI assistants.

    为 AI 助手渲染简洁的中文摘要。
    """
    context = payload.get("context") or {}
    received = payload.get("received_at_cst") or "(未知时间)"
    description = payload.get("description") or "(无描述)"
    active_tab = context.get("active_tab") or "unknown"
    source_version = context.get("source_version") or "legacy"
    color_mode = context.get("color_mode") or "(无)"
    lut_name = context.get("lut_name") or "(无)"
    material_dirs = context.get("selected_material_dir_names") or []
    layer_count = context.get("material_layer_count")
    layer_height = context.get("material_layer_height_mm")
    backing = context.get("material_backing_material_dir_name") or "(无)"

    action_history = context.get("action_history") or []
    recent = list(_iter_list(action_history))[-5:]
    action_lines: list[str] = []
    for entry in recent:
        if not isinstance(entry, dict):
            continue
        ts = _format_timestamp_ms(entry.get("timestamp"))
        action_lines.append(f"{ts} {entry.get('action_type', '?')}")

    api_errors = _collect_api_errors(action_history)
    error_lines: list[str] = []
    for entry in api_errors[-3:]:
        err = entry.get("error") or {}
        ts = _format_timestamp_ms(entry.get("timestamp"))
        error_lines.append(
            f"{ts} "
            f"{err.get('path', '?')} "
            f"({err.get('status_code', '?')})"
        )

    attachments = payload.get("attachments") or {}
    attachment_lines: list[str] = []
    for kind in ("original_image", "final_artifact", "lut", "materials_bundle"):
        entry = attachments.get(kind)
        if not isinstance(entry, dict):
            continue
        status = entry.get("status", "unknown")
        filename = entry.get("filename") or "(无)"
        attachment_lines.append(f"- {kind}: {status} → {filename}")

    material_block = ""
    if source_version == "material":
        material_block = (
            f"选中耗材：{', '.join(material_dirs) if material_dirs else '(未选择)'}；"
            f"层数：{layer_count}；层高：{layer_height}mm；底板：{backing}。"
        )

    summary = (
        f"工单 {ticket_id} 于 {received} 受理。用户描述：\n"
        f"\"{description}\"\n\n"
        f"提交时工作流：{active_tab} Tab / {source_version} 模式 / "
        f"颜色模式 {color_mode} / LUT {lut_name}。{material_block}\n\n"
        f"最近操作：{' → '.join(action_lines) if action_lines else '(无记录)'}。\n\n"
        f"最近 API 错误：{' / '.join(error_lines) if error_lines else '(无)'}。\n\n"
        f"复现资源：\n"
        + ("\n".join(attachment_lines) if attachment_lines else "(无附件)")
        + f"\n\n跑 `python scripts/load_bug_repro.py {ticket_id}` 可在本地重建 session。\n"
    )
    return summary
