"""Feedback router for manual bug report intake.

用于手动 Bug 反馈接收的反馈路由。
"""

from __future__ import annotations

import base64
import json
import os
import re
import time
from collections import deque
from datetime import datetime, timezone
from math import isfinite
from pathlib import Path
from typing import Any, Literal

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator

from api.dependencies import get_file_registry, get_session_store
from api.feedback_assembler import collect_sync_attachments, finalize_ticket_async
from api.feedback_email import is_email_configured, send_bug_report_email_async
from api.feedback_store import dump_bug_report, to_dump_path_string
from api.feedback_ticket import generate_ticket_id, ticket_dir_for
from api.feedback_time import format_received_cst, now_beijing
from api.structured_logging import get_logger

router = APIRouter(prefix="/api/feedback", tags=["feedback"])
log = get_logger(__name__)

_MAX_SCREENSHOT_DATA_URL_LENGTH = 7_000_000
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_DEFAULT_RATE_LIMIT_MAX = 30
_DEFAULT_RATE_LIMIT_WINDOW_S = 300.0
_MAX_RECENT_CLIENT_LOGS = 50
_MAX_ACTION_HISTORY_ENTRIES = 100
_MAX_SESSION_HISTORY_ENTRIES = 5
_MAX_CLIENT_LOG_DEPTH = 4
_MAX_CLIENT_LOG_ARRAY_ITEMS = 20
_MAX_CLIENT_LOG_OBJECT_KEYS = 24
_MAX_CLIENT_LOG_STRING_LENGTH = 1200
_RATE_LIMIT_HITS: dict[str, deque[float]] = {}


def _truncate_feedback_text(value: str, limit: int = _MAX_CLIENT_LOG_STRING_LENGTH) -> str:
    if len(value) <= limit:
        return value
    return f"{value[:limit]}...<truncated>"


def _sanitize_feedback_jsonish(value: Any, *, depth: int = 0) -> Any:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, str):
        return _truncate_feedback_text(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if isfinite(value) else str(value)
    if depth >= _MAX_CLIENT_LOG_DEPTH:
        return "<truncated:depth>"
    if isinstance(value, (list, tuple)):
        items = [
            _sanitize_feedback_jsonish(item, depth=depth + 1)
            for item in list(value)[:_MAX_CLIENT_LOG_ARRAY_ITEMS]
        ]
        remaining = len(value) - _MAX_CLIENT_LOG_ARRAY_ITEMS
        if remaining > 0:
            items.append(f"<truncated:{remaining}>")
        return items
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        items = list(value.items())
        for raw_key, raw_value in items[:_MAX_CLIENT_LOG_OBJECT_KEYS]:
            key = _truncate_feedback_text(str(raw_key), 120)
            sanitized[key] = _sanitize_feedback_jsonish(raw_value, depth=depth + 1)
        remaining = len(items) - _MAX_CLIENT_LOG_OBJECT_KEYS
        if remaining > 0:
            sanitized["__truncated_keys"] = remaining
        return sanitized
    return _truncate_feedback_text(str(value))


def _sanitize_client_log_entry(entry: Any) -> dict[str, Any]:
    if not isinstance(entry, dict):
        return {"label": "client log", "details": _sanitize_feedback_jsonish(entry)}

    sanitized: dict[str, Any] = {}
    for key in ("timestamp", "method", "label", "scope", "phase"):
        value = entry.get(key)
        if value is not None:
            sanitized[key] = _truncate_feedback_text(str(value), 256)
    elapsed_ms = entry.get("elapsed_ms")
    if isinstance(elapsed_ms, (int, float)) and isfinite(float(elapsed_ms)):
        sanitized["elapsed_ms"] = round(float(elapsed_ms), 3)
    elif elapsed_ms is None:
        sanitized["elapsed_ms"] = None
    if "details" in entry:
        sanitized["details"] = _sanitize_feedback_jsonish(entry["details"])
    if "label" not in sanitized:
        sanitized["label"] = "client log"
    return sanitized


class BugReportSessionIds(BaseModel):
    """Active session identifiers included in the report context.

    报告上下文中包含的活跃 session 标识。
    """

    converter: str | None = Field(default=None, max_length=128)
    single_stage: str | None = Field(default=None, max_length=128)


class BugReportFinalArtifactRef(BaseModel):
    """Reference to the most recent generation artifact for repro (Req 3.x).

    指向最近一次生成产物的引用，用于复现（Req 3.x）。
    """

    session_id: str | None = Field(default=None, max_length=128)
    download_url: str | None = Field(default=None, max_length=1024)
    artifact_type: Literal["3mf", "zip", "share_card"] | None = None
    disk_path: str | None = Field(default=None, max_length=2048)
    source: Literal[
        "converter", "single_stage", "puzzle", "vector", "batch"
    ] | None = None


class BugReportOriginalImageRef(BaseModel):
    """Reference to the user's original uploaded image for repro (Req 2.x).

    指向用户上传原图的引用，用于复现（Req 2.x）。
    """

    session_id: str | None = Field(default=None, max_length=128)
    filename: str | None = Field(default=None, max_length=256)
    source: Literal["converter", "single_stage"] | None = None


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
    material_backing_material_dir_name: str | None = Field(default=None, max_length=128)
    recent_client_logs: list[dict[str, Any]] = Field(default_factory=list)

    # --- Reproducible-bug-reports extensions (Req 2/3/5/6). All optional so
    #     older clients that predate this upgrade still deserialize cleanly.
    # 可重现 Bug 报告新增字段；全部可选，老客户端不传也能正常反序列化。
    action_history: list[dict[str, Any]] = Field(default_factory=list)
    session_history: list[dict[str, Any]] = Field(default_factory=list)
    active_original_image_ref: BugReportOriginalImageRef | None = None
    active_final_artifact_ref: BugReportFinalArtifactRef | None = None

    @field_validator("recent_client_logs", mode="before")
    @classmethod
    def _validate_recent_client_logs(cls, value: Any) -> list[dict[str, Any]]:
        """Keep client-side diagnostic logs bounded and JSON-safe.

        将客户端诊断日志限制在可控大小，并确保内容适合写入 JSON。
        """

        if not isinstance(value, list):
            return []
        return [
            _sanitize_client_log_entry(item)
            for item in value[-_MAX_RECENT_CLIENT_LOGS:]
        ]

    @field_validator("action_history", mode="before")
    @classmethod
    def _validate_action_history(cls, value: Any) -> list[dict[str, Any]]:
        """Bound action history and sanitize every entry.

        限制操作历史长度，并对每条记录做安全裁剪。
        """

        if not isinstance(value, list):
            return []
        tail = value[-_MAX_ACTION_HISTORY_ENTRIES:]
        sanitized: list[dict[str, Any]] = []
        for item in tail:
            if not isinstance(item, dict):
                continue
            sanitized.append(_sanitize_feedback_jsonish(item))  # type: ignore[arg-type]
        return sanitized

    @field_validator("session_history", mode="before")
    @classmethod
    def _validate_session_history(cls, value: Any) -> list[dict[str, Any]]:
        """Bound session-ring history to ``_MAX_SESSION_HISTORY_ENTRIES`` items.

        限制 session ring 历史长度。
        """

        if not isinstance(value, list):
            return []
        tail = value[-_MAX_SESSION_HISTORY_ENTRIES:]
        sanitized: list[dict[str, Any]] = []
        for item in tail:
            if not isinstance(item, dict):
                continue
            sanitized.append(_sanitize_feedback_jsonish(item))  # type: ignore[arg-type]
        return sanitized


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
    email_status: Literal["sent", "unconfigured", "failed", "pending"]
    relay_available: bool
    assembly_status: Literal["in_progress", "done", "partial_failed"] | None = None


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


_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _resolve_feedback_root() -> Path:
    """Return the on-disk root for ticket directories.

    返回工单目录的磁盘根路径。

    Honours the existing ``LUMINA_FEEDBACK_DUMP_DIR`` override (same variable
    used by legacy flat dump) and otherwise defaults to ``<repo>/feedback``.

    优先使用现有的 ``LUMINA_FEEDBACK_DUMP_DIR`` 环境变量（与旧版扁平 dump
    保持一致），未设置时回退到 ``<repo>/feedback``。

    Returns:
        Path: Resolved feedback root.
    """
    override = os.environ.get("LUMINA_FEEDBACK_DUMP_DIR")
    if override:
        return Path(override).resolve()
    return (_REPO_ROOT / "feedback").resolve()


_DATA_URL_STRICT_RE = re.compile(
    r"^data:([^;,]+);base64,(.+)$", re.DOTALL,
)
_MIME_TO_EXT: dict[str, str] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/bmp": ".bmp",
}


def _decode_screenshot_data_url(data_url: str) -> tuple[str, bytes]:
    """Decode a ``data:image/...;base64,...`` URL into (ext, bytes).

    解码 ``data:image/...;base64,...`` URL 为 (扩展名, 字节) 元组。

    Strict validation rules:
    1. Must match ``data:<mime>;base64,<payload>`` exactly.
    2. MIME must be in ``_MIME_TO_EXT`` (no unknown MIME fallback).
    3. Base64 payload is decoded with ``validate=True``.

    严格校验规则：
    1. 必须精确匹配 ``data:<mime>;base64,<payload>``。
    2. MIME 必须在 ``_MIME_TO_EXT`` 中（不允许未知 MIME 兜底）。
    3. Base64 解码使用 ``validate=True``。

    Args:
        data_url: Raw data URL string from the request.
            请求中的原始 data URL 字符串。

    Returns:
        tuple[str, bytes]: Extension (with dot) and decoded bytes.

    Raises:
        HTTPException: 400 when the data URL is malformed, has an
            unsupported MIME type, or contains invalid base64.
    """
    match = _DATA_URL_STRICT_RE.match(data_url)
    if match is None:
        log.warning(
            "Screenshot data URL format invalid.",
            extra={
                "event": "feedback_screenshot_invalid",
                "error_type": "InvalidDataUrlFormat",
                "error_message": "data URL does not match data:<mime>;base64,<payload>",
            },
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid screenshot data URL",
        )
    mime = match.group(1).strip().lower()
    payload = match.group(2)
    ext = _MIME_TO_EXT.get(mime)
    if ext is None:
        log.warning(
            "Screenshot MIME type not supported.",
            extra={
                "event": "feedback_screenshot_invalid",
                "error_type": "UnsupportedMimeType",
                "error_message": f"MIME type '{mime}' is not in the allowed list",
                "mime_type": mime,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid screenshot data URL",
        )
    try:
        raw = base64.b64decode(payload, validate=True)
    except (ValueError, TypeError) as exc:
        log.warning(
            "Screenshot base64 payload invalid.",
            extra={
                "event": "feedback_screenshot_invalid",
                "error_type": "InvalidBase64",
                "error_message": str(exc),
                "mime_type": mime,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid screenshot data URL",
        ) from exc
    return ext, raw


def _relative_ticket_path(ticket_dir: Path) -> str:
    """Return a repo-relative POSIX path for response bodies.

    返回用于响应体的仓库相对 POSIX 路径。
    """
    try:
        return ticket_dir.resolve().relative_to(_REPO_ROOT).as_posix()
    except ValueError:
        return ticket_dir.resolve().as_posix()


@router.post("/bug-report", response_model=BugReportResponse)
async def submit_bug_report(
    request: BugReportRequest,
    http_request: Request,
    background_tasks: BackgroundTasks,
) -> BugReportResponse:
    """Receive a manual user-triggered bug report.

    接收用户手动触发的 Bug 报告。

    The handler's synchronous path writes ``ticket.json``, screenshot, and
    copies the three small attachments (original image, final artifact, LUT)
    via :func:`api.feedback_assembler.collect_sync_attachments`. The slow
    work — packing materials.zip, rendering index/summary, sending email —
    runs via :class:`fastapi.BackgroundTasks` so the HTTP response stays
    under the p95 2-second budget.

    同步路径只写 ``ticket.json``、截图、以及通过
    :func:`api.feedback_assembler.collect_sync_attachments` 复制三个小附件
    （原图、最终产物、LUT）。慢工作（打包耗材 zip、渲染索引和摘要、发送
    邮件）由 :class:`fastapi.BackgroundTasks` 调度，保证 HTTP 响应 p95 ≤ 2s。

    Args:
        request: Validated request payload.
            已校验的请求载荷。
        http_request: Raw Starlette request (used for rate-limit client key).
            原始 Starlette request（用于限流取客户端 key）。
        background_tasks: FastAPI background scheduler.
            FastAPI 后台任务调度器。

    Returns:
        BugReportResponse: Ticket id, email / assembly status, and dump path.
            工单号、邮件与装配状态、以及落盘路径。
    """

    _enforce_feedback_rate_limit(http_request)
    _raise_if_screenshot_too_large(request)

    # Validate screenshot data URL format early — reject before creating ticket.
    # 提前校验截图格式，非法时直接 400，不创建工单。
    if request.screenshot_data_url:
        _decode_screenshot_data_url(request.screenshot_data_url)

    now = now_beijing()
    feedback_root = _resolve_feedback_root()
    try:
        feedback_root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log.error(
            "Bug report feedback root creation failed.",
            extra={
                "event": "feedback_dump_failed",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "path": str(feedback_root),
            },
        )
        raise HTTPException(status_code=500, detail="Internal error storing report") from exc

    preferred_session_id = _preferred_session_id(request.context)

    try:
        ticket_id = generate_ticket_id(feedback_root, now=now, reserve=True)
    except OSError as exc:
        log.error(
            "Bug report ticket id generation failed.",
            extra={
                "event": "feedback_dump_failed",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "path": str(feedback_root),
                "session_id": preferred_session_id,
            },
        )
        raise HTTPException(status_code=500, detail="Internal error storing report") from exc

    ticket_dir = ticket_dir_for(feedback_root, ticket_id, now)

    context_dump = request.model_dump(mode="json").get("context") or {}
    received_at_utc = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    request_id = getattr(http_request.state, "request_id", None)

    payload: dict[str, Any] = {
        "schema_version": 3,
        "ticket_id": ticket_id,
        "received_at_cst": format_received_cst(now),
        "received_at_utc": received_at_utc,
        "description": request.description,
        "user_email": request.user_email,
        "context": context_dump,
        "screenshot_attached": request.screenshot_data_url is not None,
        "server": {
            "schema_version": 3,
            "request_id": request_id,
            "received_at_utc": received_at_utc,
        },
        "attachments": {
            "original_image": {
                "status": "not_applicable",
                "filename": None,
                "sha256": None,
                "size_bytes": None,
                "mime_type": None,
                "source_session_id": None,
            },
            "final_artifact": {
                "status": "not_applicable",
                "filename": None,
                "sha256": None,
                "size_bytes": None,
                "artifact_type": None,
                "source_session_id": None,
                "generated_at": None,
                "history_count": 0,
            },
            "lut": {
                "status": "not_applicable",
                "kind": None,
                "name": None,
                "preset_relative_path": None,
                "filename": None,
                "sha256": None,
                "size_bytes": None,
                "metadata": {},
            },
            "materials_bundle": {
                "status": "not_applicable",
                "filename": None,
                "sha256": None,
                "compressed_size_bytes": None,
                "entry_count": 0,
                "included_dirs": [],
                "excluded_cache_keys": [],
            },
            "screenshot": {
                "status": "not_applicable",
                "filename": None,
                "size_bytes": None,
            },
        },
        "email": {
            "status": "unconfigured",
            "oversized_skipped": [],
        },
        "assembly_status": "in_progress",
    }

    ticket_json_path = ticket_dir / "ticket.json"
    try:
        ticket_json_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError as exc:
        log.error(
            "Bug report ticket.json write failed.",
            extra={
                "event": "feedback_dump_failed",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "path": str(ticket_json_path),
                "session_id": preferred_session_id,
            },
        )
        raise HTTPException(status_code=500, detail="Internal error storing report") from exc

    # Screenshot landing — already validated by early check above.
    if request.screenshot_data_url:
        ext, raw = _decode_screenshot_data_url(request.screenshot_data_url)
        screenshot_path = ticket_dir / f"screenshot{ext}"
        try:
            screenshot_path.write_bytes(raw)
            payload["attachments"]["screenshot"] = {
                "status": "attached",
                "filename": screenshot_path.name,
                "size_bytes": screenshot_path.stat().st_size,
            }
        except OSError as exc:
            log.warning(
                "Screenshot write failed.",
                extra={
                    "event": "feedback_attachment_lookup_failed",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "path": str(screenshot_path),
                    "attachment_kind": "screenshot",
                },
            )

    # Sync attachment collection (original image / final artifact / LUT)
    file_registry = get_file_registry()
    session_store = get_session_store()
    try:
        sync_result = collect_sync_attachments(
            ticket_dir=ticket_dir,
            payload=payload,
            file_registry=file_registry,
            now=now,
            session_store=session_store,
        )
        payload["attachments"]["original_image"] = sync_result.original_image
        payload["attachments"]["final_artifact"] = sync_result.final_artifact
        payload["attachments"]["lut"] = sync_result.lut
    except Exception as exc:  # noqa: BLE001 — never let attachment collection crash submit.
        log.error(
            "Sync attachment collection raised.",
            extra={
                "event": "feedback_attachment_lookup_failed",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "ticket_id": ticket_id,
            },
        )

    # Persist the updated manifest before returning so the background task
    # starts from a complete view of sync-phase results.
    try:
        ticket_json_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError as exc:
        log.warning(
            "Ticket manifest rewrite after sync collection failed.",
            extra={
                "event": "feedback_dump_failed",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "path": str(ticket_json_path),
            },
        )

    # Schedule async finalize (materials zip + index/summary + email)
    background_tasks.add_task(
        finalize_ticket_async, ticket_dir, file_registry, session_store
    )

    email_configured = is_email_configured()
    email_status: Literal["sent", "unconfigured", "failed", "pending"]
    email_status = "pending" if email_configured else "unconfigured"

    relay_available = _is_feedback_relay_configured()

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
            "source_version": request.context.source_version,
            "color_mode": request.context.color_mode,
            "lut_name": request.context.lut_name,
            "email_status": email_status,
            "relay_available": relay_available,
            "recent_client_log_count": len(request.context.recent_client_logs),
        },
    )

    return BugReportResponse(
        ticket_id=ticket_id,
        emailed=False,
        dump_path=_relative_ticket_path(ticket_dir),
        email_status=email_status,
        relay_available=relay_available,
        assembly_status="in_progress",
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
