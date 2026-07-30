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

from api.structured_logging import get_logger

__all__ = [
    "generate_index_markdown",
    "generate_summary_text",
]

log = get_logger(__name__)


_MISSING = "(missing)"
_RECENT_ACTIONS_LIMIT = 10
_RECENT_API_ERRORS_LIMIT = 5

# Fallback content emitted when ``context.advanced_params`` is missing, not a
# dict, or when the render path raises. The markdown fallback is used by
# ``generate_index_markdown``; the summary fallback is reserved for task 7.2.
# 高级参数渲染的兜底字符串：缺失 / 非 dict / 渲染抛异常时使用。
_ADVANCED_PARAMS_FALLBACK_MD = "## Advanced Generation Parameters\n\n_(not captured)_\n"
_ADVANCED_PARAMS_FALLBACK_SUMMARY = "高级参数：(未采集)"


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
        "| time | status | request_id | path | message |",
        "|---|---|---|---|---|",
    ]
    for entry in errors:
        if not isinstance(entry, dict):
            continue
        ts = _format_timestamp_ms(entry.get("timestamp"))
        err = entry.get("error") or {}
        status = err.get("status_code") if isinstance(err, dict) else None
        request_id = err.get("request_id") if isinstance(err, dict) else None
        path = err.get("path") if isinstance(err, dict) else None
        msg = err.get("error_message") if isinstance(err, dict) else None
        lines.append(
            f"| {ts} | {_safe_str(status)} | "
            f"{_safe_str(request_id)} | "
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
        if entry.get("error_type") or entry.get("error_message"):
            error_type = entry.get("error_type") or "AttachmentError"
            error_message = entry.get("error_message") or "Attachment failed"
            detail_parts.append(f"error={error_type}: {error_message}")
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


# Feature toggles surfaced in the index markdown. Each entry maps a top-level
# ``advanced_params`` group key to the canonical toggle field inside that
# group. The order is the display order in the rendered section.
# index.md 中列出的功能开关：组键 -> 组内开关字段名。
_INDEX_TOGGLE_GROUPS: tuple[tuple[str, str], ...] = (
    ("relief", "enable_relief"),
    ("outline", "enable_outline"),
    ("cloisonne", "enable_cloisonne"),
    ("coating", "enable_coating"),
    ("loop", "add_loop"),
    ("fridge_magnet", "enable_fridge_magnet"),
    ("puzzle", "puzzleEnabled"),
    ("large_format", "largeFormatEnabled"),
)


def _format_advanced_params_section(context: dict[str, Any]) -> str:
    """Render the Advanced Generation Parameters markdown section.

    渲染 "高级生成参数" 的 markdown 段落。

    Returns the fallback text when ``context.advanced_params`` is missing or
    not a dict. May raise for malformed inner shapes — the caller
    (``_render_advanced_params_section_safe``) owns the try/except and
    replaces any failure with the same fallback.

    Args:
        context: The ticket context dict, i.e. ``payload["context"]``.

    Returns:
        str: A markdown snippet ending in ``\\n``; either a populated section
            or ``_ADVANCED_PARAMS_FALLBACK_MD``.
    """
    ap = context.get("advanced_params")
    if not isinstance(ap, dict) or not ap:
        return _ADVANCED_PARAMS_FALLBACK_MD

    lines: list[str] = ["## Advanced Generation Parameters", ""]

    # Dimensions line.
    dims = ap.get("dimensions")
    if isinstance(dims, dict):
        width = dims.get("target_width_mm", _MISSING)
        height = dims.get("target_height_mm", _MISSING)
    else:
        width = _MISSING
        height = _MISSING
    lines.append(f"- Dimensions: {_safe_str(width)} × {_safe_str(height)} mm")

    # Generation mode fields.
    generation = ap.get("generation")
    if isinstance(generation, dict):
        structure_mode = generation.get("structure_mode")
        modeling_mode = generation.get("modeling_mode")
        svg_pixels_per_mm = generation.get("svg_pixels_per_mm")
    else:
        structure_mode = None
        modeling_mode = None
        svg_pixels_per_mm = None
    lines.append(f"- structure_mode: {_safe_str(structure_mode)}")
    lines.append(f"- modeling_mode: {_safe_str(modeling_mode)}")
    lines.append(f"- svg_pixels_per_mm: {_safe_str(svg_pixels_per_mm)}")

    # Feature toggle states.
    for group_key, toggle_key in _INDEX_TOGGLE_GROUPS:
        group = ap.get(group_key)
        if not isinstance(group, dict):
            lines.append(f"- {toggle_key}: {_MISSING}")
            continue
        value = group.get(toggle_key)
        if value is True:
            lines.append(f"- {toggle_key}: enabled")
        elif value is False:
            lines.append(f"- {toggle_key}: disabled")
        else:
            lines.append(f"- {toggle_key}: {_MISSING}")

    color_replacement = ap.get("color_replacement")
    spatial_edit_count = (
        color_replacement.get("spatial_edit_count", _MISSING)
        if isinstance(color_replacement, dict)
        else _MISSING
    )
    lines.append(f"- spatial_edit_count: {_safe_str(spatial_edit_count)}")

    return "\n".join(lines) + "\n"


def _render_advanced_params_section_safe(context: dict[str, Any]) -> str:
    """Guarded wrapper around :func:`_format_advanced_params_section`.

    局部守卫：高级参数渲染失败不应拖垮整个 index 生成；
    任何异常都会落到 WARNING 日志并返回兜底文本。

    Args:
        context: The ticket context dict.

    Returns:
        str: The rendered section or ``_ADVANCED_PARAMS_FALLBACK_MD`` on failure.
    """
    try:
        return _format_advanced_params_section(context)
    except Exception as exc:  # noqa: BLE001 - defensive boundary
        log.warning(
            "Advanced params index rendering failed.",
            extra={
                "event": "feedback_advanced_params_failed",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "surface": "index_markdown",
            },
        )
        return _ADVANCED_PARAMS_FALLBACK_MD


# Feature toggles surfaced in the one-line Chinese summary. Each entry maps a
# top-level ``advanced_params`` group key to the canonical toggle field inside
# that group and the short Chinese label to display. Order is the display
# order in the summary line. Note this list has six entries (no coating,
# no loop) per design; summary keeps only user-facing features that matter
# for quick triage.
# summary.txt 里列出的开关：组键 -> 组内开关字段名 -> 中文短标签。
_SUMMARY_TOGGLE_CHECKS: tuple[tuple[str, str, str], ...] = (
    ("relief", "enable_relief", "浮雕"),
    ("outline", "enable_outline", "描边"),
    ("cloisonne", "enable_cloisonne", "景泰蓝"),
    ("fridge_magnet", "enable_fridge_magnet", "冰箱贴"),
    ("puzzle", "puzzleEnabled", "拼图"),
    ("large_format", "largeFormatEnabled", "大幅面"),
)


def _format_advanced_params_summary_line(context: dict[str, Any]) -> str:
    """Render a single-line Chinese summary of advanced params.

    产生形如 ``"尺寸 {w}×{h} mm，已开启：{labels or 无}。"`` 的中文单行摘要。

    ``advanced_params`` 缺失、不是 dict、或带有 ``_size_trimmed`` 标记时返回
    兜底文本 ``_ADVANCED_PARAMS_FALLBACK_SUMMARY``。调用方
    （``_render_advanced_params_summary_safe``）负责 try/except。

    Args:
        context: The ticket context dict, i.e. ``payload["context"]``.

    Returns:
        str: A single line without trailing newline; either the populated
            summary or ``_ADVANCED_PARAMS_FALLBACK_SUMMARY``.
    """
    ap = context.get("advanced_params")
    if not isinstance(ap, dict) or ap.get("_size_trimmed"):
        return _ADVANCED_PARAMS_FALLBACK_SUMMARY

    dims = ap.get("dimensions") if isinstance(ap.get("dimensions"), dict) else {}
    width = dims.get("target_width_mm", "?")
    height = dims.get("target_height_mm", "?")

    active_labels: list[str] = []
    for group_key, toggle_key, label in _SUMMARY_TOGGLE_CHECKS:
        group = ap.get(group_key)
        if isinstance(group, dict) and group.get(toggle_key) is True:
            active_labels.append(label)
    toggles_str = "、".join(active_labels) if active_labels else "无"
    return f"尺寸 {width}×{height} mm，已开启：{toggles_str}。"


def _render_advanced_params_summary_safe(context: dict[str, Any]) -> str:
    """Guarded wrapper around :func:`_format_advanced_params_summary_line`.

    局部守卫：高级参数摘要渲染失败不应拖垮整个 summary 生成；
    任何异常都会落到 WARNING 日志并返回兜底文本。

    Args:
        context: The ticket context dict.

    Returns:
        str: The rendered one-line summary or
            ``_ADVANCED_PARAMS_FALLBACK_SUMMARY`` on failure.
    """
    try:
        return _format_advanced_params_summary_line(context)
    except Exception as exc:  # noqa: BLE001 - defensive boundary
        log.warning(
            "Advanced params summary rendering failed.",
            extra={
                "event": "feedback_advanced_params_failed",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "surface": "summary_text",
            },
        )
        return _ADVANCED_PARAMS_FALLBACK_SUMMARY


def _format_workshop_diagnostics_section(
    context: dict[str, Any],
) -> str:
    """Render only the allowlisted Creative Workshop diagnostic fields.

    仅渲染白名单内的创意工坊诊断字段。
    """

    workshop = context.get("workshop")
    if not isinstance(workshop, dict):
        return ""
    module_id = _safe_str(workshop.get("module_id"))
    module_version = _safe_str(workshop.get("module_version"))
    lines = [
        "## Creative Workshop Diagnostics",
        "",
        f"- module: {module_id}@{module_version}",
        f"- install_source: {_safe_str(workshop.get('install_source'))}",
        f"- audit_status: {_safe_str(workshop.get('audit_status'))}",
        f"- runtime_mode: {_safe_str(workshop.get('runtime_mode'))}",
        f"- error_code: {_safe_str(workshop.get('error_code'))}",
    ]
    return "\n".join(lines) + "\n"


def _format_workshop_diagnostics_summary(
    context: dict[str, Any],
) -> str:
    """Render a compact Chinese workshop diagnostic summary.

    渲染简短的中文创意工坊诊断摘要。
    """

    workshop = context.get("workshop")
    if not isinstance(workshop, dict):
        return ""
    module_id = _safe_str(workshop.get("module_id"))
    module_version = _safe_str(workshop.get("module_version"))
    return (
        f"创意工坊：{module_id}@{module_version}，"
        f"来源 {_safe_str(workshop.get('install_source'))}，"
        f"审核 {_safe_str(workshop.get('audit_status'))}，"
        f"运行模式 {_safe_str(workshop.get('runtime_mode'))}，"
        f"错误 {_safe_str(workshop.get('error_code'))}。"
    )


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
    workshop_section = _format_workshop_diagnostics_section(context)

    out: list[str] = [
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
    ]
    if workshop_section:
        out.extend([workshop_section.rstrip(), ""])
    out.extend(
        [
        _render_advanced_params_section_safe(context).rstrip(),
        "",
        "## Recent Actions (last 10)",
        "",
        _format_actions_table(context.get("action_history")).rstrip(),
        ]
    )
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

    advanced_line = _render_advanced_params_summary_safe(context)
    workshop_line = _format_workshop_diagnostics_summary(context)

    workshop_block = f"{workshop_line}\n\n" if workshop_line else ""
    summary = (
        f"工单 {ticket_id} 于 {received} 受理。用户描述：\n"
        f"\"{description}\"\n\n"
        f"提交时工作流：{active_tab} Tab / {source_version} 模式 / "
        f"颜色模式 {color_mode} / LUT {lut_name}。{material_block}\n\n"
        f"{workshop_block}"
        f"{advanced_line}\n\n"
        f"最近操作：{' → '.join(action_lines) if action_lines else '(无记录)'}。\n\n"
        f"最近 API 错误：{' / '.join(error_lines) if error_lines else '(无)'}。\n\n"
        f"复现资源：\n"
        + ("\n".join(attachment_lines) if attachment_lines else "(无附件)")
        + f"\n\n跑 `python scripts/load_bug_repro.py {ticket_id}` 可在本地重建 session。\n"
    )
    return summary
