"""MLS — write-access authentication router.
MLS — 写入权限校验路由。

Exposes two small endpoints used by the frontend gate:

提供前端入口校验所需的两个端点：

- ``GET /api/mls/auth/status``: declares whether a write password is
  configured at all and whether the current request would be granted write
  access (computed from the optional ``X-MLS-Password`` header). Read mode
  is always allowed.
- ``GET /api/mls/auth/status``: 声明是否配置了写入密码、当前请求（依据
  ``X-MLS-Password`` 头）是否拥有写入权限；只读模式始终允许。
- ``POST /api/mls/auth/verify``: validates a candidate password sent in
  the same header and returns ``{ok: bool}``. Used by the password dialog
  before unlocking write mode.
- ``POST /api/mls/auth/verify``: 校验该头中的候选密码并返回 ``{ok: bool}``，
  供密码对话框在解锁写模式前调用。

Both endpoints are public (never gated by the write-auth middleware).
两个端点均公开，不被写入鉴权中间件拦截。
"""

from __future__ import annotations

from fastapi import APIRouter, Header
from pydantic import BaseModel

from .. import bootstrap

bootstrap.ensure_repo_on_path()

from api.structured_logging import get_logger  # noqa: E402

from ..auth import get_auth_state, header_password_matches

router = APIRouter(prefix="/api/mls/auth", tags=["MLS Auth"])
log = get_logger(__name__)


class MlsAuthStatusResponse(BaseModel):
    """Public auth status snapshot. (公开的鉴权状态快照)"""

    status: str = "ok"
    # ``True`` when a non-empty write password is configured on the server.
    # ``True`` 表示服务端配置了非空写入密码。
    password_required: bool
    # ``True`` when the current request is allowed to perform writes.
    # ``True`` 表示当前请求拥有写入权限。
    write_enabled: bool


class MlsAuthVerifyResponse(BaseModel):
    """Verification result for a candidate password. (候选密码校验结果)"""

    status: str = "ok"
    ok: bool
    write_enabled: bool


@router.get("/status", response_model=MlsAuthStatusResponse)
async def get_auth_status(
    x_mls_password: str | None = Header(default=None, alias="X-MLS-Password"),
) -> MlsAuthStatusResponse:
    """Report whether MLS requires a write password and whether the caller has it.
    报告 MLS 是否需要写入密码以及调用方是否已携带正确密码。
    """
    state = get_auth_state()
    if not state.password_required:
        # Service is fully open; everyone has write access.
        # 服务完全开放；所有人均拥有写权限。
        return MlsAuthStatusResponse(password_required=False, write_enabled=True)
    return MlsAuthStatusResponse(
        password_required=True,
        write_enabled=header_password_matches(x_mls_password),
    )


@router.post("/verify", response_model=MlsAuthVerifyResponse)
async def verify_password(
    x_mls_password: str | None = Header(default=None, alias="X-MLS-Password"),
) -> MlsAuthVerifyResponse:
    """Validate a candidate password supplied in ``X-MLS-Password``.
    校验 ``X-MLS-Password`` 头中提供的候选密码。

    Returns:
        ``ok=True`` only when the password matches; ``write_enabled`` mirrors
        ``ok`` so the frontend can unlock immediately. (匹配时 ok=True，
        write_enabled 同步为 True 供前端立即解锁)
    """
    state = get_auth_state()
    if not state.password_required:
        return MlsAuthVerifyResponse(ok=True, write_enabled=True)
    matches = header_password_matches(x_mls_password)
    log.info(
        "MLS write password verification attempt",
        extra={
            "event": "mls_auth_verify_done",
            "ok": matches,
        },
    )
    return MlsAuthVerifyResponse(ok=matches, write_enabled=matches)
