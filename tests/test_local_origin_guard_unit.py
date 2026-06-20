"""Unit tests for local-only browser origin guards."""

from __future__ import annotations

import pytest
from fastapi import HTTPException, Request

from api.local_origin_guard import require_local_app_origin


def _request(
    headers: dict[str, str] | None = None,
    *,
    client_host: str | None = "127.0.0.1",
) -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/system/settings",
        "headers": [
            (key.lower().encode("latin-1"), value.encode("latin-1"))
            for key, value in (headers or {}).items()
        ],
    }
    if client_host is not None:
        scope["client"] = (client_host, 54321)
    return Request(scope)


@pytest.mark.parametrize(
    ("headers", "client_host"),
    [
        ({}, "127.0.0.1"),
        ({}, "::1"),
        ({}, "testclient"),
        ({"Host": "localhost:8000"}, "127.0.0.1"),
        ({"Host": "127.0.0.1:8000"}, "127.0.0.1"),
        ({"Host": "[::1]:8000"}, "::1"),
        ({"Host": "testserver"}, "testclient"),
        ({"Origin": "http://localhost:5174"}, "127.0.0.1"),
        ({"Origin": "http://127.0.0.1:4174"}, "127.0.0.1"),
        ({"Origin": "http://[::1]:8000"}, "::1"),
        ({"Referer": "http://localhost:5174/settings"}, "127.0.0.1"),
        ({"Sec-Fetch-Site": "same-origin"}, "127.0.0.1"),
        ({"Sec-Fetch-Site": "same-site"}, "127.0.0.1"),
    ],
)
def test_require_local_app_origin_allows_loopback_sources(
    headers: dict[str, str],
    client_host: str,
) -> None:
    require_local_app_origin(_request(headers, client_host=client_host))


@pytest.mark.parametrize(
    ("headers", "client_host"),
    [
        ({}, "192.168.1.50"),
        ({"Origin": "null"}, "127.0.0.1"),
        ({"Origin": "https://attacker.example"}, "127.0.0.1"),
        ({"Origin": "http://192.168.1.50:5174"}, "127.0.0.1"),
        ({"Origin": "http://localhost:bad-port"}, "127.0.0.1"),
        ({"Host": "attacker.example"}, "127.0.0.1"),
        ({"Host": "192.168.1.50:8000"}, "127.0.0.1"),
        ({"Host": "localhost:bad-port"}, "127.0.0.1"),
        ({"Host": "testserver"}, "127.0.0.1"),
        ({"Referer": "https://attacker.example/page"}, "127.0.0.1"),
        ({"Sec-Fetch-Site": "cross-site"}, "127.0.0.1"),
        (
            {
                "Origin": "http://localhost:5174",
                "Referer": "https://attacker.example/page",
            },
            "127.0.0.1",
        ),
    ],
)
def test_require_local_app_origin_rejects_untrusted_sources(
    headers: dict[str, str],
    client_host: str,
) -> None:
    with pytest.raises(HTTPException) as exc_info:
        require_local_app_origin(_request(headers, client_host=client_host))

    assert exc_info.value.status_code == 403
    assert "local Lumina Studio app" in exc_info.value.detail
