"""Unit tests for the feedback router."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

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


def _payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "description": "Preview failed after generate.",
        "user_email": None,
        "context": {
            "url": "http://localhost:5174/",
            "user_agent": "pytest",
            "screen_width": 1280,
            "screen_height": 720,
            "device_pixel_ratio": 1.0,
            "app_version": "2.0.0",
            "language": "en",
            "theme": "light",
            "active_tab": "converter",
            "active_session_ids": {"converter": "session-abcdef", "single_stage": None},
            "color_mode": "4-Color (RYBW)",
            "lut_name": "Test LUT",
            "recent_client_logs": [],
        },
        "screenshot_data_url": None,
    }
    payload.update(overrides)
    return payload


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    from api.app import create_app
    import api.feedback_email as feedback_email

    monkeypatch.setenv("LUMINA_FEEDBACK_DUMP_DIR", str(tmp_path))
    monkeypatch.delenv("LUMINA_FEEDBACK_SMTP_HOST", raising=False)
    monkeypatch.delenv("LUMINA_FEEDBACK_TO", raising=False)
    feedback_email.is_email_configured.cache_clear()
    app = create_app()
    return TestClient(app)


def test_submit_bug_report_accepts_full_payload_and_logs_canary(
    client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _capture_feedback_logger(caplog, logging.INFO)
    payload = _payload(
        user_email="user@example.com",
        screenshot_data_url="data:image/png;base64," + ("a" * 1024),
    )

    response = client.post("/api/feedback/bug-report", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["ticket_id"] == "session-"
    assert data["emailed"] is False
    assert data["dump_path"].endswith(".json")
    canaries = [
        record for record in caplog.records
        if getattr(record, "event", None) == "feedback_bug_report_submitted"
    ]
    assert len(canaries) == 1
    assert canaries[0].ticket_id == "session-"
    assert canaries[0].description_length == len(payload["description"])
    assert canaries[0].language == "en"
    assert canaries[0].has_screenshot is True


def test_submit_bug_report_accepts_description_only(client: TestClient) -> None:
    response = client.post("/api/feedback/bug-report", json=_payload(description="Only text"))

    assert response.status_code == 200
    assert response.json()["emailed"] is False


@pytest.mark.parametrize(
    "patch",
    [
        {"description": ""},
        {"description": "x" * 10001},
        {"user_email": "not-an-email"},
    ],
)
def test_submit_bug_report_rejects_invalid_payloads(
    client: TestClient,
    patch: dict[str, object],
    caplog: pytest.LogCaptureFixture,
) -> None:
    response = client.post("/api/feedback/bug-report", json=_payload(**patch))

    assert response.status_code == 422
    assert [
        record for record in caplog.records
        if getattr(record, "event", None) == "feedback_bug_report_submitted"
    ] == []


def test_submit_bug_report_rejects_oversized_screenshot(
    client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _capture_feedback_logger(caplog, logging.WARNING)
    payload = _payload(screenshot_data_url="data:image/png;base64," + ("a" * 7_000_001))

    response = client.post("/api/feedback/bug-report", json=payload)

    assert response.status_code == 413
    warnings = [
        record for record in caplog.records
        if getattr(record, "event", None) == "feedback_screenshot_too_large"
    ]
    assert len(warnings) == 1
    assert warnings[0].error_type == "PayloadTooLarge"


def test_submit_bug_report_returns_500_when_dump_fails(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def _raise(_payload: dict[str, Any]) -> tuple[Path, str]:
        raise OSError("disk full")

    monkeypatch.setattr("api.routers.feedback.dump_bug_report", _raise)
    _capture_feedback_logger(caplog, logging.ERROR)

    response = client.post("/api/feedback/bug-report", json=_payload())

    assert response.status_code == 500
    failures = [
        record for record in caplog.records
        if getattr(record, "event", None) == "feedback_dump_failed"
    ]
    assert len(failures) == 1
    assert failures[0].error_type == "OSError"
    assert failures[0].path == "<feedback_dump_dir>"
