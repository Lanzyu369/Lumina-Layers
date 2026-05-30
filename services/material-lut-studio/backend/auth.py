"""MLS write-access authentication.
MLS 写入权限校验。

Source of truth for the write password and the request gating that turns
MLS into a "read-only by default, password-unlocks-writes" service. The
password lives in ``services/material-lut-studio/config.json`` (committed
to the repo with a default placeholder so a fresh checkout boots in a
known state) or, as an override, in the ``MLS_WRITE_PASSWORD`` environment
variable. When neither is set to a non-empty value the service stays
fully open — useful for local development and single-user deployments.

写入密码的事实来源，并提供把 MLS 切换为「默认只读、密码解锁写入」服务所需的
请求网关。密码存储在 ``services/material-lut-studio/config.json``（入库，带
默认占位值，让新克隆的仓库以已知状态启动），可通过 ``MLS_WRITE_PASSWORD``
环境变量覆盖。两者均为空时服务对外完全开放，适合本地开发与单用户部署。

Rotation policy (轮换策略):
    For real deployments, prefer setting ``MLS_WRITE_PASSWORD`` in the
    process environment so the secret never sits in a tracked file. The
    committed default is a deployment-time placeholder, not a secret.
    生产部署优先用环境变量 ``MLS_WRITE_PASSWORD`` 注入密码，避免入库；仓库
    内默认值仅作为部署占位，不是真正的机密。

Design (设计):
    - Read endpoints (GET / HEAD / OPTIONS) never require the password, so
      the frontend can be entered in read-only mode without unlocking.
    - Mutating endpoints are matched against an explicit allowlist of
      ``(method, path_prefix)`` pairs and require the
      ``X-MLS-Password`` header to be present and equal to the configured
      password. A failure returns ``401`` with a structured JSON body so
      the frontend can react (prompt for password, drop into read-only).
    - When no password is configured, mutating endpoints are accepted as
      well — protection is opt-in.
    - 读端点（GET / HEAD / OPTIONS）从不要求密码，前端可在未解锁前以只读模式进入。
    - 写端点按显式 ``(method, 路径前缀)`` 白名单匹配，必须携带
      ``X-MLS-Password`` 且与配置密码一致；失败返回结构化 ``401`` JSON。
    - 未配置密码时写端点也放行——保护是可选的。
"""

from __future__ import annotations

import hmac
import json
import os
from pathlib import Path
from typing import Iterable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

_SERVICE_DIR = Path(__file__).resolve().parents[1]
_CONFIG_FILENAME = "config.json"
_CONFIG_PATH = _SERVICE_DIR / _CONFIG_FILENAME
_PASSWORD_HEADER = "x-mls-password"
_PASSWORD_HEADER_CANONICAL = "X-MLS-Password"


# Mutating endpoint allowlist: (HTTP method, path prefix). A request matches
# when its method equals (case-insensitive) ``method`` and its path starts
# with ``prefix`` (so DELETE /api/mls/materials/brand_a/red matches
# ("DELETE", "/api/mls/materials/")). Anything not on this list is treated as
# a read operation and is never password-checked.
# 写端点白名单: (方法, 路径前缀)。请求方法相等（不区分大小写）且路径前缀匹配
# 即视为写操作；列表外的请求一律视为读操作，从不校验密码。
_WRITE_OPERATIONS: tuple[tuple[str, str], ...] = (
    # MLS-native material-archive lifecycle (delete / metadata edit / import).
    # MLS 原生耗材档案生命周期（删除/编辑元数据/导入）。
    ("DELETE", "/api/mls/materials/"),
    ("PATCH", "/api/mls/materials/"),
    ("POST", "/api/mls/materials/import"),
    # MLS-native LUT lifecycle (upload + merge are persistent writes).
    # MLS 原生 LUT 生命周期（上传 + 合并都会落盘）。
    ("POST", "/api/mls/lut/upload"),
    ("POST", "/api/mls/lut/merge"),
    ("DELETE", "/api/mls/lut/"),
    # Reused single-stage / extractor mutations: gradient-card material save,
    # delete, metadata edit, import; solver cache build & delete.
    # 复用的提取器写操作：保存/删除/改元数据/导入耗材，求解缓存的构建与删除。
    ("POST", "/api/extractor/save-gradient-card-material"),
    ("POST", "/api/extractor/gradient-card-materials/import"),
    ("DELETE", "/api/extractor/gradient-card-materials/"),
    ("PATCH", "/api/extractor/gradient-card-materials/"),
    ("POST", "/api/extractor/material-solver-cache/build"),
    ("POST", "/api/extractor/material-solver-cache/delete"),
    # Reused LUT lifecycle endpoints (the legacy unprefixed paths).
    # 复用的 LUT 生命周期端点（旧无前缀路径）。
    ("POST", "/api/lut/upload"),
    ("POST", "/api/lut/merge"),
    ("DELETE", "/api/lut/"),
    # System-wide writes: cache wipe + user settings.
    # 全局写操作：清缓存与用户设置。
    ("POST", "/api/system/clear-cache"),
    ("POST", "/api/system/settings"),
)


class _AuthState:
    """Process-local cache for the currently configured write password.
    进程内缓存当前配置的写入密码。

    Source resolution order (优先级):
        1. ``services/material-lut-studio/config.json`` ``write_password``
           field, if the file exists and the value is a non-empty string.
        2. ``MLS_WRITE_PASSWORD`` environment variable.
        3. Otherwise: no password configured, writes are unprotected.
    """

    def __init__(self) -> None:
        self._loaded = False
        self._password: str | None = None

    def load(self) -> None:
        """Load (or reload) the password from environment + disk.
        从环境变量 + 磁盘加载（或重载）密码。

        Resolution order (优先级):
            1. ``MLS_WRITE_PASSWORD`` environment variable, when set to a
               non-empty value. Lets ops override the committed default
               without editing a tracked file.
            2. ``services/material-lut-studio/config.json`` ``write_password``
               field, when the file exists and the value is a non-empty string.
            3. Otherwise: no password, writes are unprotected.
            1. 环境变量 ``MLS_WRITE_PASSWORD``（非空）：让运维不必改入库文件即可覆盖默认。
            2. ``config.json`` 的 ``write_password`` 字段（非空字符串）。
            3. 否则未配置密码，写端点对外开放。
        """
        password: str | None = None
        env_value = os.environ.get("MLS_WRITE_PASSWORD")
        if isinstance(env_value, str) and env_value.strip():
            password = env_value
        if password is None:
            try:
                if _CONFIG_PATH.is_file():
                    raw = _CONFIG_PATH.read_text(encoding="utf-8")
                    payload = json.loads(raw)
                    value = payload.get("write_password") if isinstance(payload, dict) else None
                    if isinstance(value, str) and value.strip():
                        password = value
            except (OSError, json.JSONDecodeError, UnicodeDecodeError):
                # A broken config file must not crash startup; fall through
                # so the service boots in open mode. The operator will see
                # protection is off via ``GET /api/mls/auth/status``.
                # 配置文件损坏不应阻止启动；进入开放模式，运维通过状态端点可见。
                password = None
        self._password = password
        self._loaded = True

    @property
    def password(self) -> str | None:
        if not self._loaded:
            self.load()
        return self._password

    @property
    def password_required(self) -> bool:
        """True iff a non-empty password is configured.
        当且仅当配置了非空密码时为 True。
        """
        return bool(self.password)


_AUTH_STATE = _AuthState()


def get_auth_state() -> _AuthState:
    """Expose the singleton auth state for tests / endpoints.
    将单例 auth state 暴露给测试或端点使用。
    """
    return _AUTH_STATE


def reload_password_from_disk() -> None:
    """Re-read the password from the config file / env (testing aid).
    重新从配置文件 / 环境变量读取密码（测试用）。
    """
    _AUTH_STATE.load()


def is_write_protected_request(method: str, path: str) -> bool:
    """Return True iff (method, path) needs a write password.
    判断 (method, path) 是否需要写入密码。

    Args:
        method: HTTP method, e.g. ``"POST"``. (HTTP 方法)
        path: Absolute request path, e.g. ``"/api/mls/materials/red"``.
            (绝对请求路径)

    Returns:
        bool: True when the operation falls in the write allowlist.
    """
    method_upper = method.upper()
    if method_upper in {"GET", "HEAD", "OPTIONS"}:
        return False
    for write_method, prefix in _WRITE_OPERATIONS:
        if method_upper == write_method and path.startswith(prefix):
            return True
    return False


def header_password_matches(header_value: str | None) -> bool:
    """Compare a request's ``X-MLS-Password`` header to the configured password.
    把请求头 ``X-MLS-Password`` 与配置密码做常时比对。

    Uses :func:`hmac.compare_digest` to defeat timing attacks. Returns False
    immediately when no password is configured (callers must check
    ``password_required`` first).
    使用 :func:`hmac.compare_digest` 抵抗计时攻击；未配置密码时直接返回 False，
    调用方应先检查 ``password_required``。
    """
    expected = _AUTH_STATE.password
    if not expected:
        return False
    if not isinstance(header_value, str) or not header_value:
        return False
    return hmac.compare_digest(expected, header_value)


class MlsWriteAuthMiddleware(BaseHTTPMiddleware):
    """Reject mutating MLS requests without a valid ``X-MLS-Password`` header.
    拦截缺少有效 ``X-MLS-Password`` 头部的 MLS 写请求。

    Pure read operations (GET/HEAD/OPTIONS) and operations not in
    :data:`_WRITE_OPERATIONS` pass through unauthenticated. When no password
    is configured, this middleware is a no-op.
    纯读请求（GET/HEAD/OPTIONS）以及不在 :data:`_WRITE_OPERATIONS` 内的操作不
    需校验；未配置密码时该中间件等价空操作。
    """

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        if not _AUTH_STATE.password_required:
            return await call_next(request)
        if not is_write_protected_request(request.method, request.url.path):
            return await call_next(request)
        header_value = request.headers.get(_PASSWORD_HEADER)
        if header_password_matches(header_value):
            return await call_next(request)
        return JSONResponse(
            status_code=401,
            content={
                "status": "error",
                "error_code": "mls_write_password_required",
                "detail": "MLS is in read-only mode. A valid X-MLS-Password header is required for write operations.",
            },
            headers={"WWW-Authenticate": "MlsPassword"},
        )


def install_write_auth_middleware(app, *, write_operations: Iterable[tuple[str, str]] | None = None) -> None:
    """Mount :class:`MlsWriteAuthMiddleware` on the FastAPI ``app``.
    将 :class:`MlsWriteAuthMiddleware` 挂载到 FastAPI ``app``。

    Args:
        app: The FastAPI instance to protect. (要保护的 FastAPI 实例)
        write_operations: Reserved for tests that want to override the
            allowlist; pass ``None`` to use the default. (测试覆盖白名单用)
    """
    # ``write_operations`` is reserved for forward-compat / tests; the
    # middleware reads the module-level allowlist at request time so a
    # future override would patch the module attribute.
    # 该参数为前向兼容/测试预留；中间件在请求期读模块级白名单。
    _ = write_operations
    app.add_middleware(MlsWriteAuthMiddleware)


# Header constant exposed for response-introspection tests.
# 暴露给响应自检测试的请求头常量。
PASSWORD_HEADER = _PASSWORD_HEADER_CANONICAL
