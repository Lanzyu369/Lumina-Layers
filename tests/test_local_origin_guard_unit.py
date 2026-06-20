"""Unit tests for local-only browser origin guards."""

from __future__ import annotations

import pytest
from fastapi import HTTPException, Request

from api.local_origin_guard import require_local_app_origin


def _request_with_headers(headers: dict[str, str]) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/extractor/material-solver-cache/delete",
            "headers": [
                (key.lower().encode("latin-1"), value.encode("latin-1"))
                for key, value in headers.items()
            ],
        }
    )


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Origin": "http://localhost:5174"},
        {"Origin": "http://127.0.0.1:4174"},
        {"Origin": "http://[::1]:5174"},
        {"Referer": "http://localhost:5174/materials"},
    ],
)
def test_require_local_app_origin_allows_local_sources(
    headers: dict[str, str],
) -> None:
    require_local_app_origin(_request_with_headers(headers))


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "null"},
        {"Origin": "https://attacker.example"},
        {"Origin": "http://192.168.1.20:5174"},
        {"Referer": "https://attacker.example/page"},
        {
            "Origin": "http://localhost:5174",
            "Referer": "https://attacker.example/page",
        },
    ],
)
def test_require_local_app_origin_rejects_untrusted_browser_sources(
    headers: dict[str, str],
) -> None:
    with pytest.raises(HTTPException) as exc_info:
        require_local_app_origin(_request_with_headers(headers))

    assert exc_info.value.status_code == 403
    assert "local Lumina Studio app" in exc_info.value.detail
