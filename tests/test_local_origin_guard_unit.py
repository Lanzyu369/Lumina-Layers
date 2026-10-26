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


@pytest.mark.parametrize(
    ("headers", "client_host"),
    [
        ({}, "192.168.1.50"),
        ({"Origin": "https://attacker.example"}, "127.0.0.1"),
        ({"Host": "attacker.example"}, "127.0.0.1"),
        ({"Sec-Fetch-Site": "cross-site"}, "127.0.0.1"),
    ],
)
def test_require_local_app_origin_rejects_untrusted_sources_with_retired_bypass(
    monkeypatch: pytest.MonkeyPatch,
    headers: dict[str, str],
    client_host: str,
) -> None:
    monkeypatch.setenv("LUMINA_ALLOW_PUBLIC_GRAY_API", "1")
    with pytest.raises(HTTPException) as exc_info:
        require_local_app_origin(_request(headers, client_host=client_host))

    assert exc_info.value.status_code == 403


@pytest.mark.parametrize("legacy_env_value", ["1", "true", "yes", "on"])
@pytest.mark.parametrize(
    "headers",
    [
        {"Host": "localhost:8000", "Origin": "https://attacker.example"},
        {"Host": "attacker.example"},
    ],
)
def test_management_guards_reject_retired_bypass(
    monkeypatch: pytest.MonkeyPatch,
    legacy_env_value: str,
    headers: dict[str, str],
) -> None:
    from api.routers.single_stage import _enforce_material_library_request
    from api.routers.system import _enforce_clear_cache_origin

    monkeypatch.setenv("LUMINA_ALLOW_PUBLIC_GRAY_API", legacy_env_value)
    request = _request(headers)
    for guard in (_enforce_clear_cache_origin, _enforce_material_library_request):
        with pytest.raises(HTTPException) as exc_info:
            guard(request)

        assert exc_info.value.status_code == 403
