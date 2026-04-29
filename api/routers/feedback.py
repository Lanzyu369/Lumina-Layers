"""Feedback router for manual bug report intake.

用于手动 Bug 反馈接收的反馈路由。
"""

from __future__ import annotations

import re
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from api.feedback_email import is_email_configured, send_bug_report_email_async
from api.feedback_store import dump_bug_report, to_dump_path_string
from api.structured_logging import get_logger

router = APIRouter(prefix="/api/feedback", tags=["feedback"])
log = get_logger(__name__)

_MAX_SCREENSHOT_DATA_URL_LENGTH = 7_000_000
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


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


def _preferred_session_id(context: BugReportContext) -> str | None:
    """Choose the most useful session id for structured logging.

    为结构化日志选择最有用的 session id。
    """

    return context.active_session_ids.converter or context.active_session_ids.single_stage


@router.post("/bug-report", response_model=BugReportResponse)
async def submit_bug_report(
    request: BugReportRequest,
    background: BackgroundTasks,
) -> BugReportResponse:
    """Receive a manual user-triggered bug report.

    接收用户手动触发的 Bug 报告。

    Args:
        request: Validated request payload.
            已校验的请求载荷。
        background: FastAPI background task manager.
            FastAPI 后台任务管理器。

    Returns:
        BugReportResponse: Ticket id, email configuration status, and dump path.
            包含工单号、邮件配置状态与落盘路径的响应。
    """

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

    background.add_task(
        send_bug_report_email_async,
        ticket_id=ticket_id,
        request_payload=payload,
        dump_path=to_dump_path_string(dump_path),
    )

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
        emailed=is_email_configured(),
        dump_path=to_dump_path_string(dump_path),
    )
