"""SMTP-based bug report email delivery.

基于 SMTP 的 Bug 报告邮件投递服务。
"""

from __future__ import annotations

import json
import mimetypes
import os
import re
from email.message import EmailMessage
from functools import lru_cache
from pathlib import Path, PureWindowsPath
from typing import Any

try:
    import aiosmtplib
except ImportError:  # pragma: no cover - exercised indirectly when dependency is absent.
    class _AioSmtplibFallback:
        """Fallback shim used until the optional dependency is installed.

        在依赖尚未安装时提供后备 shim。
        """

        SMTPException = RuntimeError

        @staticmethod
        async def send(*_args: object, **_kwargs: object) -> None:
            raise OSError("aiosmtplib is not installed")

    aiosmtplib = _AioSmtplibFallback()  # type: ignore[assignment]

from api.feedback_config import max_email_attachment_bytes
from api.structured_logging import get_logger

log = get_logger(__name__)

_RECIPIENT_SPLIT_RE = re.compile(r"[;,]")


def _public_dump_path_label(dump_path: str) -> str:
    """Return a non-sensitive dump path label for email bodies."""

    raw_value = str(dump_path)
    posix_path = Path(raw_value)
    windows_path = PureWindowsPath(raw_value)
    is_posix_absolute = posix_path.is_absolute()
    is_windows_absolute = windows_path.is_absolute()
    if not (is_posix_absolute or is_windows_absolute):
        return raw_value

    if is_windows_absolute and not is_posix_absolute:
        parts = [
            part
            for part in windows_path.parts
            if part not in {windows_path.anchor, ""}
        ]
    else:
        parts = [
            part
            for part in posix_path.parts
            if part not in {posix_path.anchor, ""}
        ]
    if len(parts) >= 2 and parts[-1].startswith("LUM-"):
        return f"feedback/{parts[-2]}/{parts[-1]}"
    return parts[-1] if parts else "(redacted)"


@lru_cache(maxsize=1)
def is_email_configured() -> bool:
    """Return whether the minimum SMTP configuration is present.

    返回最小 SMTP 配置是否齐全。

    Returns:
        bool: ``True`` when host and recipient are configured.
            当 host 与 recipient 都已配置时返回 ``True``。
    """

    has_host = bool(os.environ.get("LUMINA_FEEDBACK_SMTP_HOST"))
    has_to = bool(_parse_recipients(os.environ.get("LUMINA_FEEDBACK_TO", "")))
    if not (has_host and has_to):
        log.warning(
            "Bug-report email is unconfigured; reports will be dumped only.",
            extra={
                "event": "feedback_smtp_unconfigured",
                "error_type": "SmtpUnconfigured",
                "error_message": "LUMINA_FEEDBACK_SMTP_HOST or LUMINA_FEEDBACK_TO is not set",
                "missing_host": not has_host,
                "missing_to": not has_to,
            },
        )
        return False
    return True


async def send_bug_report_email_async(
    *,
    ticket_id: str,
    request_payload: dict[str, Any],
    dump_path: str,
    attachments_dir: Path | None = None,
) -> bool:
    """Send a bug report email and return whether SMTP accepted it.

    发送 Bug 报告邮件，并返回 SMTP 是否接受投递。

    Args:
        ticket_id: Short ticket id shown to the user.
            展示给用户的短工单号。
        request_payload: Full report payload.
            完整报告 payload。
        dump_path: Logical ticket location string.
            逻辑工单位置字符串。
        attachments_dir: Optional directory containing ticket attachments to
            attach (original image / final artifact / LUT / materials zip /
            screenshot / index.md / summary.txt). Files that exceed
            :func:`api.feedback_config.max_email_attachment_bytes` are listed
            in the body as "Oversized attachments" instead of being attached.
            可选的附件目录；单文件超过
            :func:`api.feedback_config.max_email_attachment_bytes` 的会以
            "Oversized attachments" 文本列表形式出现在邮件正文中。
    """

    if not is_email_configured():
        return False

    smtp_host = os.environ["LUMINA_FEEDBACK_SMTP_HOST"]
    smtp_port = int(os.environ.get("LUMINA_FEEDBACK_SMTP_PORT", "587"))
    smtp_user = os.environ.get("LUMINA_FEEDBACK_SMTP_USER")
    smtp_password = os.environ.get("LUMINA_FEEDBACK_SMTP_PASSWORD")
    smtp_from = os.environ.get("LUMINA_FEEDBACK_SMTP_FROM", smtp_user or "lumina@localhost")
    recipients = _parse_recipients(os.environ["LUMINA_FEEDBACK_TO"])
    use_tls = os.environ.get("LUMINA_FEEDBACK_SMTP_USE_TLS", "true").lower() == "true"
    timeout_s = float(os.environ.get("LUMINA_FEEDBACK_SMTP_TIMEOUT_S", "5"))

    message = _build_email_message(
        ticket_id=ticket_id,
        request_payload=request_payload,
        dump_path=dump_path,
        smtp_from=smtp_from,
        smtp_to=recipients,
        attachments_dir=attachments_dir,
    )

    try:
        await aiosmtplib.send(
            message,
            hostname=smtp_host,
            port=smtp_port,
            username=smtp_user,
            password=smtp_password,
            recipients=recipients,
            start_tls=use_tls,
            timeout=timeout_s,
        )
        return True
    except (getattr(aiosmtplib, "SMTPException", RuntimeError), TimeoutError, OSError) as exc:
        log.error(
            "Bug-report email failed.",
            extra={
                "event": "feedback_email_failed",
                "ticket_id": ticket_id,
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "dependency": "aiosmtplib",
            },
        )
        return False


def _build_email_message(
    *,
    ticket_id: str,
    request_payload: dict[str, Any],
    dump_path: str,
    smtp_from: str,
    smtp_to: list[str],
    attachments_dir: Path | None = None,
) -> EmailMessage:
    """Build the bug report email message.

    构造 Bug 报告邮件对象。

    Args:
        ticket_id: Short ticket id.
            短工单号。
        request_payload: Full report payload.
            完整报告 payload。
        dump_path: Logical ticket location string.
            逻辑工单位置字符串。
        smtp_from: Sender address.
            发件地址。
        smtp_to: Recipient addresses.
            收件地址列表。
        attachments_dir: Optional directory to attach files from. When set,
            files under the directory that fit the size budget are attached;
            oversized ones are listed in the body as "Oversized attachments".
            可选附件目录；达标的文件作为附件，超限的写入正文便于手动获取。

    Returns:
        EmailMessage: Plain-text email with JSON attachment (and optional
            ticket-directory attachments when ``attachments_dir`` is provided).
            邮件对象，带 JSON 附件以及（可选的）工单目录附件。
    """

    description = str(request_payload.get("description", ""))
    short_desc = description[:50].replace("\n", " ")
    user_email = request_payload.get("user_email") or "(not provided)"
    context = request_payload.get("context", {})
    public_dump_path = _public_dump_path_label(dump_path)
    recent_logs = context.get("recent_client_logs") or []
    recent_log_labels = [
        str(item.get("label"))
        for item in recent_logs[-5:]
        if isinstance(item, dict) and item.get("label")
    ]

    body_lines = [
        f"Ticket:      {ticket_id}",
        f"User email:  {user_email}",
        f"App version: {context.get('app_version')}",
        f"Tab:         {context.get('active_tab')}",
        f"Source:      {context.get('source_version')}",
        f"Color mode:  {context.get('color_mode')}",
        f"LUT:         {context.get('lut_name')}",
        f"Native LUTs: {context.get('selected_native_db_names')}",
        f"Materials:   {context.get('selected_material_dir_names')}",
        f"Backing:     {context.get('material_backing_material_dir_name')}",
        f"Sessions:    {context.get('active_session_ids')}",
        f"Recent logs: {len(recent_logs)}",
        f"Last labels: {recent_log_labels}",
        f"UA:          {context.get('user_agent')}",
        f"URL:         {context.get('url')}",
        "",
        "Description:",
        description,
        "",
        f"Full payload (json) attached. Ticket location: {public_dump_path}",
        "Search the structured log file for these session ids to reproduce.",
    ]

    attach_files: list[Path] = []
    oversized: list[tuple[Path, int]] = []
    if attachments_dir is not None and attachments_dir.exists() and attachments_dir.is_dir():
        ceiling = max_email_attachment_bytes()
        for candidate in sorted(attachments_dir.iterdir()):
            if not candidate.is_file():
                continue
            try:
                size = candidate.stat().st_size
            except OSError:
                continue
            if ceiling > 0 and size > ceiling:
                oversized.append((candidate, size))
            else:
                attach_files.append(candidate)

    if oversized:
        body_lines.append("")
        body_lines.append("Oversized attachments (fetch from server):")
        for path, size in oversized:
            body_lines.append(f"  - {path.name} ({size} bytes)")

    message = EmailMessage()
    message["Subject"] = f"[Lumina Bug] {ticket_id} - {short_desc}"
    message["From"] = smtp_from
    message["To"] = ", ".join(smtp_to)
    message.set_content("\n".join(body_lines))
    message.add_attachment(
        json.dumps(request_payload, ensure_ascii=False, indent=2).encode("utf-8"),
        maintype="application",
        subtype="json",
        filename=f"{ticket_id}.json",
    )

    for path in attach_files:
        try:
            data = path.read_bytes()
        except OSError as exc:
            log.warning(
                "Skipping oversized or unreadable attachment.",
                extra={
                    "event": "feedback_email_attachment_skipped",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "path": str(path),
                },
            )
            continue
        mime, _ = mimetypes.guess_type(path.name)
        if mime is None:
            maintype, subtype = "application", "octet-stream"
        else:
            maintype, _, subtype = mime.partition("/")
            if not subtype:
                subtype = "octet-stream"
        message.add_attachment(
            data,
            maintype=maintype,
            subtype=subtype,
            filename=path.name,
        )
    return message


def _parse_recipients(raw_value: str) -> list[str]:
    """Parse configured recipient addresses from env text.

    从环境变量文本中解析收件地址。

    Args:
        raw_value: Comma- or semicolon-separated recipient addresses.
            逗号或分号分隔的收件地址。

    Returns:
        list[str]: Clean recipient address list, preserving order.
            清理后的收件地址列表，并保留原有顺序。
    """

    return [
        recipient
        for recipient in (
            item.strip()
            for item in _RECIPIENT_SPLIT_RE.split(raw_value)
        )
        if recipient
    ]
