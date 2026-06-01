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

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

_SERVICE_DIR = Path(__file__).resolve().parents[1]
_CONFIG_FILENAME = "config.json"
_CONFIG_PATH = _SERVICE_DIR / _CONFIG_FILENAME
_PASSWORD_HEADER = "x-mls-password"
_PASSWORD_HEADER_CANONICAL = "X-MLS-Password"


# Mutating endpoint allowlist split into two flavours:
#
#   * ``_WRITE_EXACT_PATHS`` — the request path must match exactly. Used for
#     "single-resource" routes that have no path parameter, so a sibling
#     endpoint sharing the prefix (e.g. ``/api/mls/lut/uploaded-something``)
#     can't be misclassified as a write.
#   * ``_WRITE_PATH_PREFIXES`` — the request path must start with the prefix
#     **and** the prefix must end with ``/``. This anchors every entry to a
#     proper path-segment boundary, avoiding the same sibling-prefix risk
#     for routes that legitimately take a path parameter (delete by name /
#     patch by name).
#
# Both halves remain ``(method, value)`` tuples so the comparator is uniform.
# Anything not on either list is treated as read.
#
# 把写端点白名单拆为两类：精确路径（无 path 参数的端点，必须完全相等）与路径
# 前缀（必须以 ``/`` 结尾，确保只匹配子路径，不会被同前缀的兄弟端点误命中）。
# 列表外的端点一律视为读操作。
_WRITE_EXACT_PATHS: tuple[tuple[str, str], ...] = (
    # MLS-native material-archive lifecycle (POST endpoints with no path
    # parameter). MLS 原生耗材生命周期：无路径参数的 POST 端点。
    ("POST", "/api/mls/materials/export"),
    ("POST", "/api/mls/materials/import"),
    # MLS-native LUT lifecycle (POST endpoints with no path parameter).
    # MLS 原生 LUT 生命周期：无路径参数的 POST 端点。
    ("POST", "/api/mls/lut/upload"),
    ("POST", "/api/mls/lut/merge"),
    # MLS-native solver-cache lifecycle.
    # MLS 原生求解缓存生命周期。
    ("POST", "/api/mls/solver-cache/build"),
    ("POST", "/api/mls/solver-cache/delete"),
    # Reused single-stage / extractor write POSTs without path parameters.
    # 复用的提取器写 POST：无路径参数。
    ("POST", "/api/extractor/extract-single-stage"),
    ("POST", "/api/extractor/fit-stage-a"),
    ("POST", "/api/extractor/extract-gradient-card-stage-a"),
    ("POST", "/api/extractor/save-gradient-card-material"),
    ("POST", "/api/extractor/gradient-card-materials/export"),
    ("POST", "/api/extractor/gradient-card-materials/import"),
    ("POST", "/api/extractor/generate-material-swatch"),
    ("POST", "/api/extractor/material-solver-cache/build"),
    ("POST", "/api/extractor/material-solver-cache/delete"),
    # Reused extractor image/ColorChecker helper endpoints all upload,
    # register, transform, delete, or otherwise mutate temp/session resources.
    # 复用的提取器图片 / ColorChecker 辅助端点会上传、注册、转换、删除或修改
    # 临时 / 会话资源。
    ("POST", "/api/extractor/rotate"),
    ("POST", "/api/extractor/preview-wb"),
    ("POST", "/api/extractor/colorchecker-source"),
    ("POST", "/api/extractor/colorchecker-reference-normalize"),
    ("POST", "/api/extractor/colorchecker-warp-preview"),
    ("POST", "/api/extractor/colorchecker-detect-chart"),
    ("POST", "/api/extractor/colorchecker-calibrate"),
    ("POST", "/api/extractor/colorchecker-release"),
    ("POST", "/api/extractor/colorchecker-confirm"),
    ("POST", "/api/extractor/colorchecker-touch"),
    # Reused extractor LUT persistence flow: extract/repair/merge/confirm
    # all write a LUT JSON on disk (session output or caller-supplied path).
    # 复用的提取器 LUT 持久化流程：提取、修格点、合并、确认调色板都会改写磁盘 LUT。
    ("POST", "/api/extractor/extract"),
    ("POST", "/api/extractor/manual-fix"),
    ("POST", "/api/extractor/merge-5color-extended"),
    ("POST", "/api/extractor/merge-8color"),
    ("POST", "/api/extractor/confirm-palette"),
    # Reused legacy LUT lifecycle (without ``/api/mls`` prefix).
    # 复用的旧 LUT 生命周期端点（无 ``/api/mls`` 前缀）。
    ("POST", "/api/lut/upload"),
    ("POST", "/api/lut/merge"),
    # System-wide writes.
    # 全局写操作。
    ("POST", "/api/calibration/generate"),
    ("POST", "/api/calibration/generate-single-stage-kit"),
    ("POST", "/api/system/image-preview"),
    ("POST", "/api/system/preview-resources"),
    ("POST", "/api/system/preview-artifacts"),
    ("POST", "/api/system/clear-cache"),
    ("POST", "/api/system/settings"),
)

_WRITE_PATH_PREFIXES: tuple[tuple[str, str], ...] = (
    # MLS-native material-archive lifecycle with ``{directory_name}`` param.
    # MLS 原生耗材按目录名删除 / 改元数据。
    ("DELETE", "/api/mls/materials/"),
    ("PATCH", "/api/mls/materials/"),
    # MLS-native LUT lifecycle with ``{lut_name}`` param.
    # MLS 原生 LUT 按名称删除。
    ("DELETE", "/api/mls/lut/"),
    # Reused extractor lifecycle with ``{directory_name}`` param.
    # 复用的提取器按目录名删除 / 改元数据。
    ("DELETE", "/api/extractor/gradient-card-materials/"),
    ("PATCH", "/api/extractor/gradient-card-materials/"),
    # Reused legacy LUT lifecycle (without ``/api/mls`` prefix).
    # 复用的旧 LUT 生命周期端点（无 ``/api/mls`` 前缀）。
    ("DELETE", "/api/lut/"),
)


class _AuthState:
    """Process-local cache for the currently configured write password.
    进程内缓存当前配置的写入密码。

    Source resolution order — see :meth:`load` for the authoritative
    implementation. Briefly: ``MLS_WRITE_PASSWORD`` env var beats
    ``services/material-lut-studio/config.json``'s ``write_password``
    field; both empty means writes are unprotected (open mode).

    具体优先级见 :meth:`load`。简言之：环境变量 ``MLS_WRITE_PASSWORD`` 高于
    ``config.json`` 中 ``write_password`` 字段；两者均空则写端点完全开放。
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
    for write_method, exact_path in _WRITE_EXACT_PATHS:
        if method_upper == write_method and path == exact_path:
            return True
    for write_method, prefix in _WRITE_PATH_PREFIXES:
        # Prefixes are required to end with "/" (asserted by the maintainers,
        # not enforced at runtime to keep the hot path branch-free); this
        # anchors matching to a path-segment boundary so a sibling endpoint
        # like ``/api/mls/lut/uploaded-something`` never gets misclassified.
        # 前缀必须以 "/" 结尾（维护契约），匹配锚定到路径分段边界，避免兄弟端点
        # 被误判。
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

    Pure read operations (GET/HEAD/OPTIONS) and operations outside the write
    allowlist (:data:`_WRITE_EXACT_PATHS` + :data:`_WRITE_PATH_PREFIXES`) pass
    through unauthenticated. When no password is configured, this middleware
    is a no-op.
    纯读请求（GET/HEAD/OPTIONS）以及不在写白名单（:data:`_WRITE_EXACT_PATHS` +
    :data:`_WRITE_PATH_PREFIXES`）内的操作不需校验；未配置密码时该中间件等价
    空操作。
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


def install_write_auth_middleware(app) -> None:
    """Mount :class:`MlsWriteAuthMiddleware` on the FastAPI ``app``.
    将 :class:`MlsWriteAuthMiddleware` 挂载到 FastAPI ``app``。

    Args:
        app: The FastAPI instance to protect. (要保护的 FastAPI 实例)
    """
    app.add_middleware(MlsWriteAuthMiddleware)


# Header constant exposed for response-introspection tests.
# 暴露给响应自检测试的请求头常量。
PASSWORD_HEADER = _PASSWORD_HEADER_CANONICAL
