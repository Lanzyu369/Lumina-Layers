"""Regression coverage for API error log governance and readable failures."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from fastapi.testclient import TestClient

from api.app import create_app
from api.structured_logging import _JsonFormatter


_CATCH_ALL_PATTERN = re.compile(r"^(.*_log|status_.*|request_.*)$")
_ALLOWED_LOG_EVENTS = {"client_log", "log_file_configured"}


def _capture_api_logs(tmp_path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    log_path = tmp_path / "api-errors.jsonl"
    logger = logging.getLogger("lumina")
    previous_level = logger.level
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(_JsonFormatter())
    handler.setLevel(logging.INFO)
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)

    app = create_app()

    @app.get("/api/_audit/http-500")
    def _audit_http_exception() -> None:
        raise HTTPException(
            status_code=500,
            detail="forced server failure",
            headers={"X-Test-Error": "preserved"},
        )

    @app.get("/api/_audit/unhandled")
    def _audit_unhandled_exception() -> None:
        raise RuntimeError("unhandled boom")

    responses: dict[str, Any]
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            responses = {
                "framework_404": client.get("/api/no-such-route"),
                "validation_422": client.post(
                    "/api/convert/puzzle-layout-preview",
                    json={},
                ),
                "http_500": client.get("/api/_audit/http-500"),
                "unhandled_500": client.get("/api/_audit/unhandled"),
            }
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)
        handler.flush()
        handler.close()

    records = [
        json.loads(line)
        for line in log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return records, responses


def test_api_error_logs_use_specific_events_with_actionable_language(tmp_path: Path) -> None:
    records, responses = _capture_api_logs(tmp_path)

    assert responses["framework_404"].status_code == 404
    assert responses["framework_404"].json() == {"detail": "Not Found"}
    assert responses["framework_404"].headers.get("x-request-id")
    assert responses["validation_422"].status_code == 422
    assert responses["validation_422"].headers.get("x-request-id")
    assert responses["http_500"].status_code == 500
    assert responses["http_500"].json() == {"detail": "forced server failure"}
    assert responses["http_500"].headers.get("x-test-error") == "preserved"
    assert responses["http_500"].headers.get("x-request-id")
    assert responses["unhandled_500"].status_code == 500
    assert responses["unhandled_500"].json() == {"detail": "Internal server error"}
    assert responses["unhandled_500"].headers.get("x-request-id")

    events = [record["event"] for record in records]
    assert "request_completed" not in events
    assert "request_failed" not in events
    catch_all_events = [
        event
        for event in events
        if _CATCH_ALL_PATTERN.match(event) and event not in _ALLOWED_LOG_EVENTS
    ]
    assert catch_all_events == []

    error_events = {
        (record["event"], record["path"], record["status_code"]): record
        for record in records
        if record["event"] in {"api_http_error", "api_validation_failed", "api_unhandled_exception"}
    }

    assert ("api_http_error", "/api/no-such-route", 404) in error_events
    assert (
        "api_validation_failed",
        "/api/convert/puzzle-layout-preview",
        422,
    ) in error_events
    assert ("api_http_error", "/api/_audit/http-500", 500) in error_events
    assert ("api_unhandled_exception", "/api/_audit/unhandled", 500) in error_events

    expected_request_ids = {
        ("api_http_error", "/api/no-such-route", 404): responses[
            "framework_404"
        ].headers["x-request-id"],
        (
            "api_validation_failed",
            "/api/convert/puzzle-layout-preview",
            422,
        ): responses["validation_422"].headers["x-request-id"],
        ("api_http_error", "/api/_audit/http-500", 500): responses[
            "http_500"
        ].headers["x-request-id"],
        ("api_unhandled_exception", "/api/_audit/unhandled", 500): responses[
            "unhandled_500"
        ].headers["x-request-id"],
    }

    for record in error_events.values():
        assert record["request_id"]
        assert record["method"]
        assert record["path"].startswith("/api/")
        assert record["status_code"] >= 400
        assert record["error_type"]
        assert record["error_message"]
    for key, request_id in expected_request_ids.items():
        assert error_events[key]["request_id"] == request_id

    assert error_events[
        ("api_http_error", "/api/no-such-route", 404)
    ]["error_message"] == "Not Found"
    assert "session_id" in error_events[
        ("api_validation_failed", "/api/convert/puzzle-layout-preview", 422)
    ]["error_message"]
    assert error_events[
        ("api_http_error", "/api/_audit/http-500", 500)
    ]["error_message"] == "forced server failure"
    assert error_events[
        ("api_unhandled_exception", "/api/_audit/unhandled", 500)
    ]["error_message"] == "unhandled boom"
