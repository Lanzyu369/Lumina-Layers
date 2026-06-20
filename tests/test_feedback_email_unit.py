"""Unit tests for SMTP feedback email behavior."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import pytest


def _payload() -> dict[str, Any]:
    return {
        "description": "Preview crashed\nwhen I clicked generate.",
        "user_email": "user@example.com",
        "context": {
            "app_version": "2.0.0",
            "active_tab": "converter",
            "color_mode": "4-Color (RYBW)",
            "lut_name": "Test LUT",
            "source_version": "legacy",
            "selected_native_db_names": [],
            "selected_material_dir_names": [],
            "material_backing_material_dir_name": "Wujing/white",
            "recent_client_logs": [
                {"label": "preview: request sent"},
                {"label": "api: request failed"},
            ],
            "active_session_ids": {"converter": "abc12345", "single_stage": None},
            "user_agent": "pytest",
            "url": "http://localhost:5174/",
        },
        "screenshot_data_url": None,
    }


def _capture_feedback_email_logger(
    caplog: pytest.LogCaptureFixture,
    level: int,
) -> logging.Logger:
    target_logger = logging.getLogger("lumina.api.feedback_email")
    target_logger.addHandler(caplog.handler)
    caplog.set_level(level, logger=target_logger.name)
    return target_logger


@pytest.fixture(autouse=True)
def _clear_email_cache():
    import api.feedback_email as feedback_email

    feedback_email.is_email_configured.cache_clear()
    yield
    feedback_email.is_email_configured.cache_clear()


def test_is_email_configured_requires_host_and_recipient(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from api.feedback_email import is_email_configured

    _capture_feedback_email_logger(caplog, logging.WARNING)
    monkeypatch.delenv("LUMINA_FEEDBACK_SMTP_HOST", raising=False)
    monkeypatch.delenv("LUMINA_FEEDBACK_TO", raising=False)

    assert is_email_configured() is False
    assert is_email_configured() is False

    warnings = [
        record for record in caplog.records
        if getattr(record, "event", None) == "feedback_smtp_unconfigured"
    ]
    assert len(warnings) == 1
    assert warnings[0].missing_host is True
    assert warnings[0].missing_to is True


def test_is_email_configured_returns_true_when_minimum_env_is_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from api.feedback_email import is_email_configured

    monkeypatch.setenv("LUMINA_FEEDBACK_SMTP_HOST", "localhost")
    monkeypatch.setenv("LUMINA_FEEDBACK_TO", "dev@example.com")

    assert is_email_configured() is True


def test_parse_recipients_accepts_commas_and_semicolons() -> None:
    from api.feedback_email import _parse_recipients

    assert _parse_recipients("dev@example.com, ops@example.com; qa@example.com") == [
        "dev@example.com",
        "ops@example.com",
        "qa@example.com",
    ]


def test_send_bug_report_email_short_circuits_when_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import api.feedback_email as feedback_email

    calls: list[object] = []
    monkeypatch.delenv("LUMINA_FEEDBACK_SMTP_HOST", raising=False)
    monkeypatch.delenv("LUMINA_FEEDBACK_TO", raising=False)
    monkeypatch.setattr(feedback_email.aiosmtplib, "send", lambda *args, **kwargs: calls.append(args))

    result = asyncio.run(
        feedback_email.send_bug_report_email_async(
            ticket_id="abc12345",
            request_payload=_payload(),
            dump_path="feedback/report.json",
        )
    )

    assert result is False
    assert calls == []


def test_send_bug_report_email_passes_all_configured_recipients(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import api.feedback_email as feedback_email

    calls: list[dict[str, Any]] = []

    async def _send(*_args: object, **kwargs: Any) -> None:
        calls.append(kwargs)

    monkeypatch.setenv("LUMINA_FEEDBACK_SMTP_HOST", "localhost")
    monkeypatch.setenv("LUMINA_FEEDBACK_TO", "dev@example.com, ops@example.com")
    monkeypatch.setattr(feedback_email.aiosmtplib, "send", _send)

    result = asyncio.run(
        feedback_email.send_bug_report_email_async(
            ticket_id="abc12345",
            request_payload=_payload(),
            dump_path="feedback/report.json",
        )
    )

    assert result is True
    assert calls[0]["recipients"] == ["dev@example.com", "ops@example.com"]


@pytest.mark.parametrize("exc", [TimeoutError("slow"), OSError("offline")])
def test_send_bug_report_email_logs_failures_without_reraising(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    exc: Exception,
) -> None:
    import api.feedback_email as feedback_email

    async def _raise(*_args: object, **_kwargs: object) -> None:
        raise exc

    monkeypatch.setenv("LUMINA_FEEDBACK_SMTP_HOST", "localhost")
    monkeypatch.setenv("LUMINA_FEEDBACK_TO", "dev@example.com")
    monkeypatch.setattr(feedback_email.aiosmtplib, "send", _raise)
    _capture_feedback_email_logger(caplog, logging.ERROR)

    result = asyncio.run(
        feedback_email.send_bug_report_email_async(
            ticket_id="abc12345",
            request_payload=_payload(),
            dump_path="feedback/report.json",
        )
    )

    assert result is False
    failures = [
        record for record in caplog.records
        if getattr(record, "event", None) == "feedback_email_failed"
    ]
    assert len(failures) == 1
    assert failures[0].ticket_id == "abc12345"
    assert failures[0].dependency == "aiosmtplib"
    assert failures[0].error_type == type(exc).__name__


def test_build_email_message_uses_plain_text_body_and_json_attachment() -> None:
    from api.feedback_email import _build_email_message

    msg = _build_email_message(
        ticket_id="abc12345",
        request_payload=_payload(),
        dump_path="feedback/report.json",
        smtp_from="from@example.com",
        smtp_to=["to@example.com"],
    )

    assert msg["Subject"].startswith("[Lumina Bug] abc12345 - Preview crashed")
    assert msg["From"] == "from@example.com"
    assert msg["To"] == "to@example.com"
    assert msg.get_body(preferencelist=("plain",)) is not None
    body = msg.get_body(preferencelist=("plain",)).get_content()
    assert "User email:  user@example.com" in body
    assert "Source:      legacy" in body
    assert "Materials:   []" in body
    assert "Backing:     Wujing/white" in body
    assert "Recent logs: 2" in body
    assert "api: request failed" in body
    attachments = list(msg.iter_attachments())
    assert len(attachments) == 1
    assert attachments[0].get_filename() == "abc12345.json"
    assert attachments[0].get_content_type() == "application/json"


def test_build_email_message_attaches_small_files_from_attachments_dir(
    tmp_path,
) -> None:
    """Files smaller than the email ceiling are attached to the message.

    单附件小于邮件上限时应被附加。
    """
    from api.feedback_email import _build_email_message

    attachments_dir = tmp_path / "LUM-20260511-001"
    attachments_dir.mkdir()
    (attachments_dir / "original.png").write_bytes(b"PNGDATA")
    (attachments_dir / "index.md").write_text("# index", encoding="utf-8")

    msg = _build_email_message(
        ticket_id="LUM-20260511-001",
        request_payload=_payload(),
        dump_path=str(attachments_dir),
        smtp_from="from@example.com",
        smtp_to=["to@example.com"],
        attachments_dir=attachments_dir,
    )

    attachment_names = {a.get_filename() for a in msg.iter_attachments()}
    assert "LUM-20260511-001.json" in attachment_names  # the JSON dump
    assert "original.png" in attachment_names
    assert "index.md" in attachment_names
    body = msg.get_body(preferencelist=("plain",)).get_content()
    assert "Oversized attachments" not in body


def test_build_email_message_skips_oversized_files(
    tmp_path,
    monkeypatch,
) -> None:
    """Files larger than the email ceiling are listed in the body but not attached.

    单附件超过邮件上限时不作为附件，而是以正文提示的形式出现。
    """
    monkeypatch.setenv("LUMINA_FEEDBACK_MAX_EMAIL_ATTACHMENT_MB", "1")  # 1 MB ceiling

    from api.feedback_email import _build_email_message

    attachments_dir = tmp_path / "LUM-20260511-002"
    attachments_dir.mkdir()
    big = attachments_dir / "materials.zip"
    big.write_bytes(b"x" * (2 * 1024 * 1024))  # 2 MB
    small = attachments_dir / "summary.txt"
    small.write_text("ok", encoding="utf-8")

    msg = _build_email_message(
        ticket_id="LUM-20260511-002",
        request_payload=_payload(),
        dump_path=str(attachments_dir),
        smtp_from="from@example.com",
        smtp_to=["to@example.com"],
        attachments_dir=attachments_dir,
    )

    attachment_names = {a.get_filename() for a in msg.iter_attachments()}
    assert "materials.zip" not in attachment_names
    assert "summary.txt" in attachment_names
    body = msg.get_body(preferencelist=("plain",)).get_content()
    assert "Oversized attachments" in body
    assert "materials.zip" in body
    assert str(big) not in body
    assert tmp_path.as_posix() not in body


def test_build_email_message_redacts_windows_absolute_dump_path() -> None:
    """Windows absolute ticket paths are reduced to logical ticket labels."""
    from api.feedback_email import _build_email_message

    msg = _build_email_message(
        ticket_id="LUM-20260511-003",
        request_payload=_payload(),
        dump_path=r"C:\Users\min\feedback\2026-06\LUM-20260511-003",
        smtp_from="from@example.com",
        smtp_to=["to@example.com"],
    )

    body = msg.get_body(preferencelist=("plain",)).get_content()
    assert r"C:\Users\min" not in body
    assert "feedback/2026-06/LUM-20260511-003" in body
