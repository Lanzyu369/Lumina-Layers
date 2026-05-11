"""Unit tests for the feedback router.

测试覆盖：
- 同步路径返回 ``assembly_status == 'in_progress'``、
  ``email_status`` 为 ``'pending'`` / ``'unconfigured'``
- 工单目录 ``feedback/<YYYY-MM>/<ticket_id>/ticket.json`` 正确落地
- 失败场景（screenshot 过大 / 校验失败 / 限流 / 目录写入失败）
- 现有 relay 行为保持不变
"""

from __future__ import annotations

import json
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
            "lut_name": None,
            "source_version": "legacy",
            "selected_native_brand_key": None,
            "selected_native_db_names": [],
            "selected_material_dir_names": [],
            "material_layer_count": None,
            "material_layer_height_mm": None,
            "material_backing_material_dir_name": None,
            "recent_client_logs": [
                {
                    "timestamp": "2026-05-10T01:02:03.000Z",
                    "method": "error",
                    "label": "api: request failed",
                    "elapsed_ms": 12.346,
                    "scope": "api",
                    "phase": "request-failed",
                    "details": {"status_code": 500},
                }
            ],
            "action_history": [],
            "session_history": [],
            "active_original_image_ref": None,
            "active_final_artifact_ref": None,
        },
        "screenshot_data_url": None,
    }
    payload.update(overrides)
    return payload


def _read_ticket_json(feedback_root: Path, ticket_id: str) -> dict[str, Any]:
    """Locate ``feedback/<YYYY-MM>/<ticket_id>/ticket.json`` and decode it."""
    for month_dir in feedback_root.iterdir():
        if not month_dir.is_dir():
            continue
        candidate = month_dir / ticket_id / "ticket.json"
        if candidate.exists():
            return json.loads(candidate.read_text(encoding="utf-8"))
    raise AssertionError(f"ticket.json for {ticket_id} not found under {feedback_root}")


@pytest.fixture()
def feedback_root(tmp_path: Path) -> Path:
    root = tmp_path / "feedback_root"
    root.mkdir()
    return root


@pytest.fixture()
def client(
    monkeypatch: pytest.MonkeyPatch,
    feedback_root: Path,
) -> TestClient:
    from api.app import create_app
    import api.feedback_email as feedback_email
    import api.routers.feedback as feedback_router

    monkeypatch.setenv("LUMINA_FEEDBACK_DUMP_DIR", str(feedback_root))
    monkeypatch.setenv("LUMINA_FEEDBACK_STARTUP_CLEANUP", "false")
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
    feedback_root: Path,
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
    assert data["ticket_id"].startswith("LUM-")
    assert data["emailed"] is False
    assert data["email_status"] == "unconfigured"
    assert data["assembly_status"] in ("in_progress", "done", "partial_failed")
    assert data["relay_available"] is False
    assert data["dump_path"].endswith(data["ticket_id"])

    ticket_json = _read_ticket_json(feedback_root, data["ticket_id"])
    assert ticket_json["schema_version"] == 3
    assert ticket_json["ticket_id"] == data["ticket_id"]
    assert ticket_json["description"] == payload["description"]
    assert ticket_json["attachments"]["screenshot"]["status"] == "attached"

    canaries = [
        record for record in caplog.records
        if getattr(record, "event", None) == "feedback_bug_report_submitted"
    ]
    assert len(canaries) == 1
    assert canaries[0].ticket_id == data["ticket_id"]
    assert canaries[0].description_length == len(payload["description"])
    assert canaries[0].language == "en"
    assert canaries[0].has_screenshot is True
    assert canaries[0].email_status == "unconfigured"
    assert canaries[0].source_version == "legacy"
    assert canaries[0].recent_client_log_count == 1


def test_submit_bug_report_accepts_description_only(client: TestClient) -> None:
    response = client.post("/api/feedback/bug-report", json=_payload(description="Only text"))

    assert response.status_code == 200
    data = response.json()
    assert data["emailed"] is False
    assert data["email_status"] == "unconfigured"
    assert data["assembly_status"] in ("in_progress", "done", "partial_failed")


def test_submit_bug_report_returns_pending_email_status_when_configured(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _send(**_kwargs: Any) -> bool:
        return True

    monkeypatch.setenv("LUMINA_FEEDBACK_SMTP_HOST", "localhost")
    monkeypatch.setenv("LUMINA_FEEDBACK_TO", "dev@example.com")
    monkeypatch.setenv("LUMINA_FEEDBACK_RELAY_URL", "https://relay.example.test/feedback")
    monkeypatch.setattr("api.feedback_email.send_bug_report_email_async", _send)
    import api.feedback_email as feedback_email

    feedback_email.is_email_configured.cache_clear()

    response = client.post("/api/feedback/bug-report", json=_payload(description="Email ok"))

    assert response.status_code == 200
    data = response.json()
    # The new handler defers email to the background task; the sync response
    # should report 'pending' when SMTP is configured and relay availability.
    assert data["emailed"] is False
    assert data["email_status"] == "pending"
    assert data["relay_available"] is True


def test_submit_bug_report_assembly_marks_done_after_background_task(
    client: TestClient,
    feedback_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TestClient runs BackgroundTasks synchronously after the response body.

    Starlette TestClient 会在响应返回后同步执行 BackgroundTasks，
    因此 ``ticket.json`` 应已被装配器标记为 ``done`` 或 ``partial_failed``。
    """
    response = client.post("/api/feedback/bug-report", json=_payload(description="Assembly"))

    assert response.status_code == 200
    data = response.json()
    ticket_json = _read_ticket_json(feedback_root, data["ticket_id"])
    assert ticket_json["assembly_status"] in ("done", "partial_failed")
    # Index + summary should have been rendered by finalize_ticket_async.
    month_dir = next(
        p for p in feedback_root.iterdir() if p.is_dir() and p.name.startswith("20")
    )
    ticket_dir = month_dir / data["ticket_id"]
    assert (ticket_dir / "index.md").exists()
    assert (ticket_dir / "summary.txt").exists()


def test_submit_bug_report_preserves_material_source_context(
    client: TestClient,
    feedback_root: Path,
) -> None:
    payload = _payload()
    payload["context"] = {
        **payload["context"],
        "color_mode": None,
        "lut_name": None,
        "source_version": "material",
        "selected_material_dir_names": ["Aliz/red", "Wujing/white"],
        "material_layer_count": 10,
        "material_layer_height_mm": 0.06,
        "material_backing_material_dir_name": "Wujing/white",
    }

    response = client.post("/api/feedback/bug-report", json=payload)

    assert response.status_code == 200
    data = response.json()
    ticket_json = _read_ticket_json(feedback_root, data["ticket_id"])
    assert ticket_json["context"]["source_version"] == "material"
    assert ticket_json["context"]["lut_name"] is None
    assert ticket_json["context"]["selected_material_dir_names"] == ["Aliz/red", "Wujing/white"]
    assert ticket_json["context"]["material_layer_count"] == 10
    assert ticket_json["context"]["material_layer_height_mm"] == 0.06
    assert ticket_json["context"]["material_backing_material_dir_name"] == "Wujing/white"
    assert ticket_json["server"]["schema_version"] == 3


def test_submit_bug_report_sanitizes_recent_client_logs(
    client: TestClient,
    feedback_root: Path,
) -> None:
    payload = _payload()
    payload["context"]["recent_client_logs"] = [
        {
            "label": f"event-{index}",
            "elapsed_ms": index + 0.12345,
            "details": {
                "long": "x" * 1300,
                **{f"k{item}": item for item in range(30)},
            },
        }
        for index in range(55)
    ]

    response = client.post("/api/feedback/bug-report", json=payload)

    assert response.status_code == 200
    data = response.json()
    ticket_json = _read_ticket_json(feedback_root, data["ticket_id"])
    logs = ticket_json["context"]["recent_client_logs"]
    assert len(logs) == 50
    assert logs[0]["label"] == "event-5"
    assert logs[-1]["label"] == "event-54"
    assert logs[0]["elapsed_ms"] == 5.123
    assert logs[0]["details"]["long"].endswith("...<truncated>")
    assert logs[0]["details"]["__truncated_keys"] == 7


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


def test_submit_bug_report_returns_500_when_ticket_dir_creation_fails(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When the ticket id generator cannot create its reserved dir the handler 500s.

    工单目录保留失败时，handler 应返回 500 而不是抛原始异常。
    """

    def _raise(*_args: Any, **_kwargs: Any) -> str:
        raise OSError("disk full")

    monkeypatch.setattr("api.routers.feedback.generate_ticket_id", _raise)
    _capture_feedback_logger(caplog, logging.ERROR)

    response = client.post("/api/feedback/bug-report", json=_payload())

    assert response.status_code == 500
    failures = [
        record for record in caplog.records
        if getattr(record, "event", None) == "feedback_dump_failed"
    ]
    assert len(failures) == 1
    assert failures[0].error_type == "OSError"


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

# ---------------------------------------------------------------------------
# Screenshot data URL strict validation tests
# ---------------------------------------------------------------------------


def test_submit_bug_report_accepts_valid_png_screenshot(
    client: TestClient,
    feedback_root: Path,
) -> None:
    """A valid PNG data URL is accepted and saved as screenshot.png."""
    import base64

    valid_png_b64 = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32).decode()
    payload = _payload(screenshot_data_url=f"data:image/png;base64,{valid_png_b64}")

    response = client.post("/api/feedback/bug-report", json=payload)

    assert response.status_code == 200
    data = response.json()
    ticket_json = _read_ticket_json(feedback_root, data["ticket_id"])
    assert ticket_json["attachments"]["screenshot"]["status"] == "attached"
    assert ticket_json["attachments"]["screenshot"]["filename"] == "screenshot.png"


def test_submit_bug_report_rejects_non_image_mime_screenshot(
    client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """data:text/plain;base64,... returns 400."""
    import base64

    b64 = base64.b64encode(b"hello world").decode()
    payload = _payload(screenshot_data_url=f"data:text/plain;base64,{b64}")
    _capture_feedback_logger(caplog, logging.WARNING)

    response = client.post("/api/feedback/bug-report", json=payload)

    assert response.status_code == 400
    assert "Invalid screenshot data URL" in response.json()["detail"]
    warnings = [
        record for record in caplog.records
        if getattr(record, "event", None) == "feedback_screenshot_invalid"
    ]
    assert len(warnings) == 1
    assert warnings[0].error_type == "UnsupportedMimeType"


def test_submit_bug_report_rejects_missing_base64_marker(
    client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """data:image/png,not-base64 (no ;base64) returns 400."""
    payload = _payload(screenshot_data_url="data:image/png,not-base64-content")
    _capture_feedback_logger(caplog, logging.WARNING)

    response = client.post("/api/feedback/bug-report", json=payload)

    assert response.status_code == 400
    warnings = [
        record for record in caplog.records
        if getattr(record, "event", None) == "feedback_screenshot_invalid"
    ]
    assert len(warnings) == 1
    assert warnings[0].error_type == "InvalidDataUrlFormat"


def test_submit_bug_report_rejects_invalid_base64_payload(
    client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """data:image/png;base64,%%% returns 400."""
    payload = _payload(screenshot_data_url="data:image/png;base64,%%%")
    _capture_feedback_logger(caplog, logging.WARNING)

    response = client.post("/api/feedback/bug-report", json=payload)

    assert response.status_code == 400
    warnings = [
        record for record in caplog.records
        if getattr(record, "event", None) == "feedback_screenshot_invalid"
    ]
    assert len(warnings) == 1
    assert warnings[0].error_type == "InvalidBase64"


def test_submit_bug_report_rejects_svg_screenshot(
    client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """data:image/svg+xml;base64,... returns 400 (SVG not in allowed list)."""
    import base64

    b64 = base64.b64encode(b"<svg></svg>").decode()
    payload = _payload(screenshot_data_url=f"data:image/svg+xml;base64,{b64}")
    _capture_feedback_logger(caplog, logging.WARNING)

    response = client.post("/api/feedback/bug-report", json=payload)

    assert response.status_code == 400
    warnings = [
        record for record in caplog.records
        if getattr(record, "event", None) == "feedback_screenshot_invalid"
    ]
    assert len(warnings) == 1
    assert warnings[0].error_type == "UnsupportedMimeType"
    assert warnings[0].mime_type == "image/svg+xml"
