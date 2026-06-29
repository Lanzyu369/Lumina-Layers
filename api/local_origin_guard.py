"""Request origin guards for local-only API endpoints."""

from __future__ import annotations

import ipaddress
import os
from urllib.parse import urlsplit

from fastapi import HTTPException, Request

LOCAL_APP_ONLY_DETAIL = (
    "This endpoint is only available from the local Lumina Studio app."
)
PUBLIC_GRAY_API_ENV = "LUMINA_ALLOW_PUBLIC_GRAY_API"
_TRUSTED_TEST_CLIENT_HOSTS = {"testclient"}
_TRUSTED_TEST_HOST_HEADERS = {"testserver"}
_TRUTHY_ENV_VALUES = {"1", "true", "yes", "on"}


def allow_public_gray_api() -> bool:
    """Return whether the temporary public gray-server bypass is enabled.
    返回临时公网灰度服务器旁路是否开启。
    """
    return os.environ.get(PUBLIC_GRAY_API_ENV, "").strip().lower() in _TRUTHY_ENV_VALUES


def _is_loopback_host(host: str | None) -> bool:
    if not host:
        return False
    normalized = host.strip().strip("[]").lower()
    if normalized == "localhost" or normalized in _TRUSTED_TEST_CLIENT_HOSTS:
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _is_local_browser_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"}:
            return False
        _ = parsed.port
        return _is_loopback_host(parsed.hostname)
    except ValueError:
        return False


def _is_local_host_header(value: str, *, client_host: str | None) -> bool:
    try:
        parsed = urlsplit(f"//{value.strip()}")
        _ = parsed.port
    except ValueError:
        return False
    hostname = parsed.hostname
    if _is_loopback_host(hostname):
        return True
    if (
        client_host in _TRUSTED_TEST_CLIENT_HOSTS
        and hostname
        and hostname.lower() in _TRUSTED_TEST_HOST_HEADERS
    ):
        return True
    return False


def _request_client_host(request: Request) -> str | None:
    if request.client and request.client.host:
        return request.client.host
    return None


def require_local_app_origin(request: Request) -> None:
    """Reject browser or remote-client requests outside the local app.
    拒绝不是由本地 Lumina Studio 应用发起的浏览器或远程客户端请求。

    ``LUMINA_ALLOW_PUBLIC_GRAY_API=1`` is a temporary public-gray Docker bypass
    and must stay unset for packaged local builds.
    ``LUMINA_ALLOW_PUBLIC_GRAY_API=1`` 仅用于临时公网灰度 Docker，正式本地
    打包版必须保持未设置。
    """
    if allow_public_gray_api():
        return

    client_host = _request_client_host(request)
    if not _is_loopback_host(client_host):
        raise HTTPException(status_code=403, detail=LOCAL_APP_ONLY_DETAIL)

    host = request.headers.get("host")
    if host is not None and not _is_local_host_header(
        host,
        client_host=client_host,
    ):
        raise HTTPException(status_code=403, detail=LOCAL_APP_ONLY_DETAIL)

    fetch_site = request.headers.get("sec-fetch-site")
    if fetch_site and fetch_site.lower().strip() == "cross-site":
        raise HTTPException(status_code=403, detail=LOCAL_APP_ONLY_DETAIL)

    origin = request.headers.get("origin")
    referer = request.headers.get("referer")
    if origin is not None and not _is_local_browser_url(origin):
        raise HTTPException(status_code=403, detail=LOCAL_APP_ONLY_DETAIL)
    if referer is not None and not _is_local_browser_url(referer):
        raise HTTPException(status_code=403, detail=LOCAL_APP_ONLY_DETAIL)
