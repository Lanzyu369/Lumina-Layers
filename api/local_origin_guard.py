"""Request origin guards for stateful local-only API endpoints."""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

from fastapi import HTTPException, Request

LOCAL_APP_ONLY_DETAIL = (
    "This endpoint is only available from the local Lumina Studio app."
)


def _is_local_browser_url(value: str) -> bool:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"}:
        return False

    host = parsed.hostname
    if host is None:
        return False
    if host.lower() == "localhost":
        return True

    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def require_local_app_origin(request: Request) -> None:
    """Reject browser requests that did not originate from the local app.
    拒绝不是由本地 Lumina Studio 应用发起的浏览器请求。

    Direct CLI/TestClient calls often have neither ``Origin`` nor ``Referer``;
    those remain allowed so local diagnostics and log-quality workflows keep
    working. Browser-originated requests must come from loopback hosts.
    """
    origin = request.headers.get("origin")
    referer = request.headers.get("referer")
    if origin is not None and not _is_local_browser_url(origin):
        raise HTTPException(status_code=403, detail=LOCAL_APP_ONLY_DETAIL)
    if referer is not None and not _is_local_browser_url(referer):
        raise HTTPException(status_code=403, detail=LOCAL_APP_ONLY_DETAIL)
