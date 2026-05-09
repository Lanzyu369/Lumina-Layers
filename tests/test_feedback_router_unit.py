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
            "source_version": "legacy",
            "selected_native_brand_key": None,
            "selected_native_db_names": [],
            "selected_material_dir_names": [],
            "material_layer_count": None,
            "material_layer_height_mm": None,
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
    import api.routers.feedback as feedback_router

    monkeypatch.setenv("LUMINA_FEEDBACK_DUMP_DIR", str(tmp_path))
    monkeypatch.delenv("LUMINA_FEEDBACK_SMTP_HOST", raising=False)
    monkeypatch.delenv("LUMINA_FEEDBACK_TO", raising=False)
    monkeypatch.delenv("LUMINA_FEEDBACK_RATE_LIMIT_MAX", raising=False)
    monkeypatch.delenv("LUMINA_FEEDBACK_RATE_LIMIT_WINDOW_S", raising=False)
    monkeypatch.delenv("LUMINA_FEEDBACK_RELAY_URL", raising=False)
    monkeypatch.delenv("LUMINA_FEEDBACK_RELAY_TOKEN", raising=False)
    monkeypatch.delenv("LUMINA_FEEDBACK_RELAY_TIMEOUT_S", raising=False)
    feedback_email.is_email_configured.cache_clear()
    feedback_router._clear_feedback_rate_limit_state()
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
    assert data["email_status"] == "unconfigured"
    assert data["relay_available"] is False
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
    assert response.json()["email_status"] == "unconfigured"


def test_submit_bug_report_reports_successful_email_and_relay_availability(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _send(**_kwargs: Any) -> bool:
        return True

    monkeypatch.setenv("LUMINA_FEEDBACK_SMTP_HOST", "localhost")
    monkeypatch.setenv("LUMINA_FEEDBACK_TO", "dev@example.com")
    monkeypatch.setenv("LUMINA_FEEDBACK_RELAY_URL", "https://relay.example.test/feedback")
    monkeypatch.setattr("api.routers.feedback.send_bug_report_email_async", _send)
    import api.feedback_email as feedback_email

    feedback_email.is_email_configured.cache_clear()

    response = client.post("/api/feedback/bug-report", json=_payload(description="Email ok"))

    assert response.status_code == 200
    data = response.json()
    assert data["emailed"] is True
    assert data["email_status"] == "sent"
    assert data["relay_available"] is True


def test_submit_bug_report_reports_failed_configured_email(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _send(**_kwargs: Any) -> bool:
        return False

    monkeypatch.setenv("LUMINA_FEEDBACK_SMTP_HOST", "localhost")
    monkeypatch.setenv("LUMINA_FEEDBACK_TO", "dev@example.com")
    monkeypatch.setattr("api.routers.feedback.send_bug_report_email_async", _send)
    import api.feedback_email as feedback_email

    feedback_email.is_email_configured.cache_clear()

    response = client.post("/api/feedback/bug-report", json=_payload(description="Email fails"))

    assert response.status_code == 200
    data = response.json()
    assert data["emailed"] is False
    assert data["email_status"] == "failed"


def test_submit_bug_report_preserves_material_source_context(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def _dump(payload: dict[str, Any]) -> tuple[Path, str]:
        captured.update(payload)
        return Path("feedback/material.json"), "material"

    monkeypatch.setattr("api.routers.feedback.dump_bug_report", _dump)
    monkeypatch.setattr(
        "api.routers.feedback.to_dump_path_string",
        lambda path: str(path),
    )
    payload = _payload()
    payload["context"] = {
        **payload["context"],
        "color_mode": None,
        "lut_name": None,
        "source_version": "material",
        "selected_material_dir_names": ["Aliz/red", "Wujing/white"],
        "material_layer_count": 10,
        "material_layer_height_mm": 0.06,
    }

    response = client.post("/api/feedback/bug-report", json=payload)

    assert response.status_code == 200
    assert captured["context"]["source_version"] == "material"
    assert captured["context"]["lut_name"] is None
    assert captured["context"]["selected_material_dir_names"] == ["Aliz/red", "Wujing/white"]
    assert captured["context"]["material_layer_count"] == 10
    assert captured["context"]["material_layer_height_mm"] == 0.06


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


def test_submit_bug_report_rate_limits_repeated_submissions(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("LUMINA_FEEDBACK_RATE_LIMIT_MAX", "1")
    monkeypatch.setenv("LUMINA_FEEDBACK_RATE_LIMIT_WINDOW_S", "60")
    _capture_feedback_logger(caplog, logging.WARNING)

    first = client.post("/api/feedback/bug-report", json=_payload(description="first"))
    second = client.post("/api/feedback/bug-report", json=_payload(description="second"))

    assert first.status_code == 200
    assert second.status_code == 429
    assert 1 <= int(second.headers["Retry-After"]) <= 60
    warnings = [
        record for record in caplog.records
        if getattr(record, "event", None) == "feedback_bug_report_rate_limited"
    ]
    assert len(warnings) == 1
    assert warnings[0].error_type == "RateLimitExceeded"
    assert warnings[0].max_requests == 1


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


def test_relay_bug_report_returns_503_when_unconfigured(
    client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _capture_feedback_logger(caplog, logging.WARNING)

    response = client.post(
        "/api/feedback/bug-report/relay",
        json={"ticket_id": "abc12345", "request_payload": _payload()},
    )

    assert response.status_code == 503
    warnings = [
        record for record in caplog.records
        if getattr(record, "event", None) == "feedback_bug_report_relay_unconfigured"
    ]
    assert len(warnings) == 1
    assert warnings[0].error_type == "RelayUnconfigured"


def test_relay_bug_report_forwards_to_configured_relay(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import httpx

    calls: list[dict[str, Any]] = []

    class _Response:
        status_code = 202

        def raise_for_status(self) -> None:
            return None

    class _Client:
        def __init__(self, *, timeout: float) -> None:
            self.timeout = timeout

        async def __aenter__(self) -> "_Client":
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def post(
            self,
            url: str,
            *,
            json: dict[str, Any],
            headers: dict[str, str],
        ) -> _Response:
            calls.append({
                "url": url,
                "json": json,
                "headers": headers,
                "timeout": self.timeout,
            })
            return _Response()

    monkeypatch.setenv("LUMINA_FEEDBACK_RELAY_URL", "https://relay.example.test/feedback")
    monkeypatch.setenv("LUMINA_FEEDBACK_RELAY_TOKEN", "secret-token")
    monkeypatch.setenv("LUMINA_FEEDBACK_RELAY_TIMEOUT_S", "3")
    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    _capture_feedback_logger(caplog, logging.INFO)

    response = client.post(
        "/api/feedback/bug-report/relay",
        json={"ticket_id": "abc12345", "request_payload": _payload(description="Relay me")},
    )

    assert response.status_code == 200
    assert response.json() == {"forwarded": True}
    assert calls == [
        {
            "url": "https://relay.example.test/feedback",
            "json": {
                "ticket_id": "abc12345",
                "request_payload": _payload(description="Relay me"),
            },
            "headers": {
                "Content-Type": "application/json",
                "X-Lumina-Feedback-Ticket": "abc12345",
                "Authorization": "Bearer secret-token",
            },
            "timeout": 3.0,
        }
    ]
    infos = [
        record for record in caplog.records
        if getattr(record, "event", None) == "feedback_bug_report_relay_done"
    ]
    assert len(infos) == 1
    assert infos[0].relay_status_code == 202


def test_relay_bug_report_returns_502_when_relay_fails(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import httpx

    class _Client:
        def __init__(self, *, timeout: float) -> None:
            self.timeout = timeout

        async def __aenter__(self) -> "_Client":
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def post(
            self,
            _url: str,
            *,
            json: dict[str, Any],
            headers: dict[str, str],
        ) -> httpx.Response:
            raise httpx.ConnectError("offline")

    monkeypatch.setenv("LUMINA_FEEDBACK_RELAY_URL", "https://relay.example.test/feedback")
    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    _capture_feedback_logger(caplog, logging.ERROR)

    response = client.post(
        "/api/feedback/bug-report/relay",
        json={"ticket_id": "abc12345", "request_payload": _payload()},
    )

    assert response.status_code == 502
    failures = [
        record for record in caplog.records
        if getattr(record, "event", None) == "feedback_bug_report_relay_failed"
    ]
    assert len(failures) == 1
    assert failures[0].dependency == "httpx"
