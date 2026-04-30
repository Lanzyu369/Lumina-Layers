"""SMTP-based bug report email delivery.

基于 SMTP 的 Bug 报告邮件投递服务。
"""

from __future__ import annotations

import json
import os
from email.message import EmailMessage
from functools import lru_cache
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

from api.structured_logging import get_logger

log = get_logger(__name__)


@lru_cache(maxsize=1)
def is_email_configured() -> bool:
    """Return whether the minimum SMTP configuration is present.

    返回最小 SMTP 配置是否齐全。

    Returns:
        bool: ``True`` when host and recipient are configured.
            当 host 与 recipient 都已配置时返回 ``True``。
    """

    has_host = bool(os.environ.get("LUMINA_FEEDBACK_SMTP_HOST"))
    has_to = bool(os.environ.get("LUMINA_FEEDBACK_TO"))
    if not (has_host and has_to):
        log.warning(
            "Bug-report email is unconfigured; reports will be dumped only.",
            extra={
                "event": "feedback_smtp_unconfigured",
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
) -> None:
    """Send a bug report email in the background.

    在后台发送 Bug 报告邮件。

    Args:
        ticket_id: Short ticket id shown to the user.
            展示给用户的短工单号。
        request_payload: Full report payload.
            完整报告 payload。
        dump_path: Stored JSON dump path string.
            已落盘 JSON 路径字符串。
    """

    if not is_email_configured():
        return

    smtp_host = os.environ["LUMINA_FEEDBACK_SMTP_HOST"]
    smtp_port = int(os.environ.get("LUMINA_FEEDBACK_SMTP_PORT", "587"))
    smtp_user = os.environ.get("LUMINA_FEEDBACK_SMTP_USER")
    smtp_password = os.environ.get("LUMINA_FEEDBACK_SMTP_PASSWORD")
    smtp_from = os.environ.get("LUMINA_FEEDBACK_SMTP_FROM", smtp_user or "lumina@localhost")
    smtp_to = os.environ["LUMINA_FEEDBACK_TO"]
    use_tls = os.environ.get("LUMINA_FEEDBACK_SMTP_USE_TLS", "true").lower() == "true"
    timeout_s = float(os.environ.get("LUMINA_FEEDBACK_SMTP_TIMEOUT_S", "5"))

    message = _build_email_message(
        ticket_id=ticket_id,
        request_payload=request_payload,
        dump_path=dump_path,
        smtp_from=smtp_from,
        smtp_to=smtp_to,
    )

    try:
        await aiosmtplib.send(
            message,
            hostname=smtp_host,
            port=smtp_port,
            username=smtp_user,
            password=smtp_password,
            start_tls=use_tls,
            timeout=timeout_s,
        )
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


def _build_email_message(
    *,
    ticket_id: str,
    request_payload: dict[str, Any],
    dump_path: str,
    smtp_from: str,
    smtp_to: str,
) -> EmailMessage:
    """Build the bug report email message.

    构造 Bug 报告邮件对象。

    Args:
        ticket_id: Short ticket id.
            短工单号。
        request_payload: Full report payload.
            完整报告 payload。
        dump_path: Stored JSON dump path string.
            已落盘 JSON 路径字符串。
        smtp_from: Sender address.
            发件地址。
        smtp_to: Recipient address.
            收件地址。

    Returns:
        EmailMessage: Plain-text email with JSON attachment.
            带 JSON 附件的纯文本邮件对象。
    """

    description = str(request_payload.get("description", ""))
    short_desc = description[:50].replace("\n", " ")
    user_email = request_payload.get("user_email") or "(not provided)"
    context = request_payload.get("context", {})

    body_lines = [
        f"Ticket:      {ticket_id}",
        f"User email:  {user_email}",
        f"App version: {context.get('app_version')}",
        f"Tab:         {context.get('active_tab')}",
        f"Color mode:  {context.get('color_mode')}",
        f"LUT:         {context.get('lut_name')}",
        f"Sessions:    {context.get('active_session_ids')}",
        f"UA:          {context.get('user_agent')}",
        f"URL:         {context.get('url')}",
        "",
        "Description:",
        description,
        "",
        f"Full payload (json) attached. Dump on disk: {dump_path}",
        "Search the structured log file for these session ids to reproduce.",
    ]

    message = EmailMessage()
    message["Subject"] = f"[Lumina Bug] {ticket_id} - {short_desc}"
    message["From"] = smtp_from
    message["To"] = smtp_to
    message.set_content("\n".join(body_lines))
    message.add_attachment(
        json.dumps(request_payload, ensure_ascii=False, indent=2).encode("utf-8"),
        maintype="application",
        subtype="json",
        filename=f"{ticket_id}.json",
    )
    return message
