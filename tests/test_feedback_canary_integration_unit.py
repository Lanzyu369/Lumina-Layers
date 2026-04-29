"""Integration tests for feedback router structured log canaries."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _capture_feedback_logger(
    caplog: pytest.LogCaptureFixture,
    level: int,
) -> logging.Logger:
    target_logger = logging.getLogger("lumina.api.routers.feedback")
    target_logger.addHandler(caplog.handler)
    caplog.set_level(level, logger=target_logger.name)
    return target_logger


def _client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    import api.feedback_email as feedback_email
    from api.app import create_app

    monkeypatch.setenv("LUMINA_FEEDBACK_DUMP_DIR", str(tmp_path))
    monkeypatch.delenv("LUMINA_FEEDBACK_SMTP_HOST", raising=False)
    monkeypatch.delenv("LUMINA_FEEDBACK_TO", raising=False)
    feedback_email.is_email_configured.cache_clear()
    return TestClient(create_app())


def _payload() -> dict[str, object]:
    return {
        "description": "Synthetic canary report.",
        "user_email": None,
        "context": {
            "url": "http://localhost:5174/",
            "user_agent": "pytest",
            "screen_width": 1920,
            "screen_height": 1080,
            "device_pixel_ratio": 1.0,
            "app_version": "test",
            "language": "en",
            "theme": "dark",
            "active_tab": "converter",
            "active_session_ids": {"converter": None, "single_stage": None},
            "color_mode": None,
            "lut_name": None,
            "recent_client_logs": [],
        },
        "screenshot_data_url": None,
    }


def _records_for_event(
    caplog: pytest.LogCaptureFixture,
    event_name: str,
) -> list[logging.LogRecord]:
    return [
        record for record in caplog.records
        if getattr(record, "event", None) == event_name
    ]


def test_success_path_emits_exactly_one_feedback_canary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = _client(monkeypatch, tmp_path)
    _capture_feedback_logger(caplog, logging.INFO)

    response = client.post("/api/feedback/bug-report", json=_payload())

    assert response.status_code == 200
    canaries = _records_for_event(caplog, "feedback_bug_report_submitted")
    assert len(canaries) == 1
    assert canaries[0].active_tab == "converter"


@pytest.mark.parametrize(
    "patch",
    [
        {"description": ""},
        {"screenshot_data_url": "data:image/png;base64," + ("a" * 7_000_001)},
    ],
)
def test_rejected_payloads_do_not_emit_feedback_canary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    patch: dict[str, object],
) -> None:
    client = _client(monkeypatch, tmp_path)
    payload = _payload()
    payload.update(patch)

    response = client.post("/api/feedback/bug-report", json=payload)

    assert response.status_code in {413, 422}
    assert _records_for_event(caplog, "feedback_bug_report_submitted") == []
