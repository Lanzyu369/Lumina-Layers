"""Feedback router for manual bug report intake.

用于手动 Bug 反馈接收的反馈路由。
"""

from __future__ import annotations

import os
import re
import time
from collections import deque
from typing import Any, Literal

import httpx
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator

from api.feedback_email import is_email_configured, send_bug_report_email_async
from api.feedback_store import dump_bug_report, to_dump_path_string
from api.structured_logging import get_logger

router = APIRouter(prefix="/api/feedback", tags=["feedback"])
log = get_logger(__name__)

_MAX_SCREENSHOT_DATA_URL_LENGTH = 7_000_000
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_DEFAULT_RATE_LIMIT_MAX = 30
_DEFAULT_RATE_LIMIT_WINDOW_S = 300.0
_RATE_LIMIT_HITS: dict[str, deque[float]] = {}


class BugReportSessionIds(BaseModel):
    """Active session identifiers included in the report context.

    报告上下文中包含的活跃 session 标识。
    """

    converter: str | None = Field(default=None, max_length=128)
    single_stage: str | None = Field(default=None, max_length=128)


class BugReportContext(BaseModel):
    """Client runtime context attached to a bug report.

    Bug 报告附带的客户端运行时上下文。
    """

    url: str = Field(max_length=2048)
    user_agent: str = Field(max_length=1024)
    screen_width: int = Field(ge=0, le=100_000)
    screen_height: int = Field(ge=0, le=100_000)
    device_pixel_ratio: float = Field(ge=0.0, le=10.0)
    app_version: str = Field(max_length=64)
    language: Literal["zh", "en"]
    theme: Literal["light", "dark"]
    active_tab: str = Field(max_length=64)
    active_session_ids: BugReportSessionIds
    color_mode: str | None = Field(default=None, max_length=64)
    lut_name: str | None = Field(default=None, max_length=256)
    source_version: Literal["legacy", "native", "material"] | None = None
    selected_native_brand_key: str | None = Field(default=None, max_length=128)
    selected_native_db_names: list[str] = Field(default_factory=list, max_length=128)
    selected_material_dir_names: list[str] = Field(default_factory=list, max_length=128)
    material_layer_count: int | None = Field(default=None, ge=0, le=1000)
    material_layer_height_mm: float | None = Field(default=None, ge=0.0, le=10.0)
    recent_client_logs: list[Any] = Field(default_factory=list, max_length=100)


class BugReportRequest(BaseModel):
    """Bug report request payload.

    Bug 报告请求载荷。
    """

    description: str = Field(min_length=1, max_length=10_000)
    user_email: str | None = Field(default=None, max_length=320)
    context: BugReportContext
    screenshot_data_url: str | None = None

    @field_validator("description")
    @classmethod
    def _validate_description(cls, value: str) -> str:
        """Reject whitespace-only descriptions.

        拒绝只包含空白字符的描述。
        """

        if not value.strip():
            raise ValueError("Description must not be blank")
        return value

    @field_validator("user_email")
    @classmethod
    def _validate_user_email(cls, value: str | None) -> str | None:
        """Validate the optional user email without extra dependencies.

        在不引入额外依赖的前提下校验可选邮箱。
        """

        if value is None or value == "":
            return None
        if len(value) > 320 or not _EMAIL_RE.match(value):
            raise ValueError("Invalid email address")
        return value


class BugReportResponse(BaseModel):
    """Bug report submission response payload.

    Bug 报告提交响应载荷。
    """

    ticket_id: str
    emailed: bool
    dump_path: str
    email_status: Literal["sent", "unconfigured", "failed"]
    relay_available: bool


class BugReportRelayRequest(BaseModel):
    """User-confirmed hosted relay request.

    用户确认后的官方转发请求。
    """

    ticket_id: str = Field(min_length=1, max_length=64)
    request_payload: BugReportRequest


class BugReportRelayResponse(BaseModel):
    """Hosted relay response.

    官方转发响应。
    """

    forwarded: bool


def _preferred_session_id(context: BugReportContext) -> str | None:
    """Choose the most useful session id for structured logging.

    为结构化日志选择最有用的 session id。
    """

    return context.active_session_ids.converter or context.active_session_ids.single_stage


def _clear_feedback_rate_limit_state() -> None:
    _RATE_LIMIT_HITS.clear()


def _feedback_rate_limit_config() -> tuple[int, float]:
    try:
        max_requests = int(
            os.environ.get("LUMINA_FEEDBACK_RATE_LIMIT_MAX", str(_DEFAULT_RATE_LIMIT_MAX))
        )
    except ValueError:
        max_requests = _DEFAULT_RATE_LIMIT_MAX
    try:
        window_s = float(
            os.environ.get(
                "LUMINA_FEEDBACK_RATE_LIMIT_WINDOW_S",
                str(_DEFAULT_RATE_LIMIT_WINDOW_S),
            )
        )
    except ValueError:
        window_s = _DEFAULT_RATE_LIMIT_WINDOW_S
    return max_requests, window_s


def _is_feedback_relay_configured() -> bool:
    return bool(os.environ.get("LUMINA_FEEDBACK_RELAY_URL"))


def _feedback_relay_timeout_s() -> float:
    try:
        return float(os.environ.get("LUMINA_FEEDBACK_RELAY_TIMEOUT_S", "8"))
    except ValueError:
        return 8.0


def _feedback_client_key(request: Request) -> str:
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _enforce_feedback_rate_limit(request: Request) -> None:
    max_requests, window_s = _feedback_rate_limit_config()
    if max_requests <= 0 or window_s <= 0:
        return

    now = time.monotonic()
    client_key = _feedback_client_key(request)
    hits = _RATE_LIMIT_HITS.setdefault(client_key, deque())
    cutoff = now - window_s
    while hits and hits[0] <= cutoff:
        hits.popleft()

    if len(hits) >= max_requests:
        retry_after = max(1, int(window_s - (now - hits[0])))
        log.warning(
            "Bug report rate limit exceeded.",
            extra={
                "event": "feedback_bug_report_rate_limited",
                "error_type": "RateLimitExceeded",
                "error_message": "Too many bug reports submitted by one client.",
                "client_key": client_key,
                "max_requests": max_requests,
                "window_s": window_s,
                "retry_after_s": retry_after,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many bug reports. Please wait and retry.",
            headers={"Retry-After": str(retry_after)},
        )

    hits.append(now)


def _raise_if_screenshot_too_large(request: BugReportRequest) -> None:
    if request.screenshot_data_url and len(request.screenshot_data_url) > _MAX_SCREENSHOT_DATA_URL_LENGTH:
        log.warning(
            "Bug report screenshot exceeded size limit.",
            extra={
                "event": "feedback_screenshot_too_large",
                "error_type": "PayloadTooLarge",
                "error_message": "Screenshot data URL exceeded 7,000,000 characters.",
                "payload_size": len(request.screenshot_data_url),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Screenshot too large",
        )


@router.post("/bug-report", response_model=BugReportResponse)
async def submit_bug_report(
    request: BugReportRequest,
    http_request: Request,
) -> BugReportResponse:
    """Receive a manual user-triggered bug report.

    接收用户手动触发的 Bug 报告。

    Args:
        request: Validated request payload.
            已校验的请求载荷。
    Returns:
        BugReportResponse: Ticket id, email configuration status, and dump path.
            包含工单号、邮件配置状态与落盘路径的响应。
    """

    _enforce_feedback_rate_limit(http_request)
    _raise_if_screenshot_too_large(request)

    payload = request.model_dump(mode="json")
    preferred_session_id = _preferred_session_id(request.context)

    try:
        dump_path, ticket_id = dump_bug_report(payload)
    except OSError as exc:
        log.error(
            "Bug report dump failed.",
            extra={
                "event": "feedback_dump_failed",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "path": "<feedback_dump_dir>",
                "session_id": preferred_session_id,
            },
        )
        raise HTTPException(status_code=500, detail="Internal error storing report") from exc

    email_configured = is_email_configured()
    emailed = False
    if email_configured:
        emailed = await send_bug_report_email_async(
            ticket_id=ticket_id,
            request_payload=payload,
            dump_path=to_dump_path_string(dump_path),
        )
    email_status: Literal["sent", "unconfigured", "failed"]
    if emailed:
        email_status = "sent"
    elif email_configured:
        email_status = "failed"
    else:
        email_status = "unconfigured"

    log.info(
        "Bug report submitted.",
        extra={
            "event": "feedback_bug_report_submitted",
            "ticket_id": ticket_id,
            "session_id": preferred_session_id,
            "session_id_converter": request.context.active_session_ids.converter,
            "session_id_single_stage": request.context.active_session_ids.single_stage,
            "description_length": len(request.description),
            "has_screenshot": request.screenshot_data_url is not None,
            "language": request.context.language,
            "active_tab": request.context.active_tab,
        },
    )

    return BugReportResponse(
        ticket_id=ticket_id,
        emailed=emailed,
        dump_path=to_dump_path_string(dump_path),
        email_status=email_status,
        relay_available=_is_feedback_relay_configured(),
    )


@router.post("/bug-report/relay", response_model=BugReportRelayResponse)
async def relay_bug_report(
    request: BugReportRelayRequest,
    http_request: Request,
) -> BugReportRelayResponse:
    """Forward a user-confirmed bug report to the hosted relay.

    将用户确认后的 Bug 反馈转发到官方收集服务。
    """

    _enforce_feedback_rate_limit(http_request)
    _raise_if_screenshot_too_large(request.request_payload)
    relay_url = os.environ.get("LUMINA_FEEDBACK_RELAY_URL")
    if not relay_url:
        log.warning(
            "Bug report relay is unconfigured.",
            extra={
                "event": "feedback_bug_report_relay_unconfigured",
                "error_type": "RelayUnconfigured",
                "error_message": "LUMINA_FEEDBACK_RELAY_URL is not set.",
                "ticket_id": request.ticket_id,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Feedback relay is not configured",
        )

    headers = {
        "Content-Type": "application/json",
        "X-Lumina-Feedback-Ticket": request.ticket_id,
    }
    relay_token = os.environ.get("LUMINA_FEEDBACK_RELAY_TOKEN")
    if relay_token:
        headers["Authorization"] = f"Bearer {relay_token}"

    try:
        async with httpx.AsyncClient(timeout=_feedback_relay_timeout_s()) as client:
            response = await client.post(
                relay_url,
                json={
                    "ticket_id": request.ticket_id,
                    "request_payload": request.request_payload.model_dump(mode="json"),
                },
                headers=headers,
            )
            response.raise_for_status()
    except httpx.HTTPError as exc:
        log.error(
            "Bug report relay failed.",
            extra={
                "event": "feedback_bug_report_relay_failed",
                "ticket_id": request.ticket_id,
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "dependency": "httpx",
            },
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Feedback relay failed",
        ) from exc

    log.info(
        "Bug report relayed.",
        extra={
            "event": "feedback_bug_report_relay_done",
            "ticket_id": request.ticket_id,
            "relay_status_code": response.status_code,
        },
    )
    return BugReportRelayResponse(forwarded=True)
