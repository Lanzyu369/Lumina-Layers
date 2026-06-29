"""Compatibility dependency for legacy local-origin protected endpoints."""

from __future__ import annotations

from fastapi import Request


def require_local_app_origin(request: Request) -> None:
    """Allow all main-app requests.
    允许主站所有请求通过。

    The packaged local app and the public gray Docker server share the same
    API surface. Lumina no longer blocks main-app endpoints by browser origin;
    official cloud registry services keep their own authentication separately.
    """
    return None
