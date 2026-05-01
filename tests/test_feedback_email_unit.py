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


def test_send_bug_report_email_short_circuits_when_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import api.feedback_email as feedback_email

    calls: list[object] = []
    monkeypatch.delenv("LUMINA_FEEDBACK_SMTP_HOST", raising=False)
    monkeypatch.delenv("LUMINA_FEEDBACK_TO", raising=False)
    monkeypatch.setattr(feedback_email.aiosmtplib, "send", lambda *args, **kwargs: calls.append(args))

    asyncio.run(
        feedback_email.send_bug_report_email_async(
            ticket_id="abc12345",
            request_payload=_payload(),
            dump_path="feedback/report.json",
        )
    )

    assert calls == []


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

    asyncio.run(
        feedback_email.send_bug_report_email_async(
            ticket_id="abc12345",
            request_payload=_payload(),
            dump_path="feedback/report.json",
        )
    )

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
        smtp_to="to@example.com",
    )

    assert msg["Subject"].startswith("[Lumina Bug] abc12345 - Preview crashed")
    assert msg["From"] == "from@example.com"
    assert msg["To"] == "to@example.com"
    assert msg.get_body(preferencelist=("plain",)) is not None
    body = msg.get_body(preferencelist=("plain",)).get_content()
    assert "User email:  user@example.com" in body
    assert "Source:      legacy" in body
    assert "Materials:   []" in body
    attachments = list(msg.iter_attachments())
    assert len(attachments) == 1
    assert attachments[0].get_filename() == "abc12345.json"
    assert attachments[0].get_content_type() == "application/json"
