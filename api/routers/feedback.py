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
from copy import deepcopy
from datetime import datetime, timezone
from math import isfinite
from pathlib import Path
from typing import Any, Literal

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from api.dependencies import get_file_registry, get_session_store
from api.feedback_assembler import collect_sync_attachments, finalize_ticket_async
from api.feedback_email import is_email_configured, send_bug_report_email_async
from api.feedback_store import dump_bug_report, to_dump_path_string
from api.feedback_ticket import generate_ticket_id, ticket_dir_for
from api.feedback_time import format_received_cst, now_beijing
from api.local_origin_guard import require_local_app_origin
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
_MAX_DESCRIPTION_STRING_LENGTH = 10_000

# Relaxed limits for the grouped ``advanced_params`` capture. They are wider
# than the generic client-log sanitizer above because the frontend builder
# already trims the shape (≤11 groups, ≤64 color_height_map entries, ≤20
# fridge magnets, ≤32 replacement regions) and emits a structured payload
# rather than an arbitrary log blob.
#
# ``advanced_params`` 分组专用的放宽限制。前端 builder 已经裁剪好结构
# （最多 11 个分组、color_height_map 最多 64 项、冰箱贴最多 20 项、颜色替换
# 最多 32 项），因此服务端可以比通用客户端日志 sanitizer 放得更宽。
_ADV_PARAMS_MAX_DEPTH = 6
_ADV_PARAMS_MAX_ARRAY_ITEMS = 64
_ADV_PARAMS_MAX_OBJECT_KEYS = 24
_ADV_PARAMS_COLOR_HEIGHT_MAP_MAX_KEYS = 64
_ADV_PARAMS_MAX_TOTAL_BYTES = 16_384

_RATE_LIMIT_HITS: dict[str, deque[float]] = {}
_LOCAL_PATH_PLACEHOLDER = "[redacted_local_path]"
_GENERIC_HTTP_STATUS_DETAIL = (
    "The server reported an error while processing this request."
)
_LOCAL_FILE_URL_RE = re.compile(
    r"file://(?:localhost/|/)(?:[A-Z]:/|(?:Users|home|private|tmp|var|Volumes|mnt|opt|etc)/)"
    r"[^\s\"'<>)]*",
    re.IGNORECASE,
)
_POSIX_LOCAL_PATH_RE = re.compile(
    r"(?<![\w:])/(?:Users|home|private|tmp|var|Volumes|mnt|opt|etc)"
    r"(?:/[^\s\"'<>)]*)?",
    re.IGNORECASE,
)
_WINDOWS_LOCAL_PATH_RE = re.compile(
    r"\b[A-Z]:[\\/](?:Users|Documents and Settings|Temp|tmp|Windows|ProgramData|"
    r"Program Files(?: \(x86\))?)(?:[\\/][^\s\"'<>|]*)*",
    re.IGNORECASE,
)
_UNC_LOCAL_PATH_RE = re.compile(
    r"\\\\[A-Za-z0-9_.-]+\\[^\s\"'<>|]+(?:\\[^\s\"'<>|]+)*"
)
_GENERIC_HTTP_STATUS_RE = re.compile(
    r"^\s*(?:Request failed with status code|HTTP(?:\s+error)?|"
    r"status(?:\s+code)?|error)\s+[45]\d{2}\s*$",
    re.IGNORECASE,
)
_GENERIC_HTTP_STATUS_WITH_REDACTED_PATH_RE = re.compile(
    r"^\s*(?:Request failed with status code|HTTP(?:\s+error)?|"
    r"status(?:\s+code)?|error)\s+[45]\d{2}"
    rf"(?:\s*(?::|at|-)\s*{re.escape(_LOCAL_PATH_PLACEHOLDER)})\s*$",
    re.IGNORECASE,
)
_GENERIC_HTTP_STATUS_WITH_CONTEXT_RE = re.compile(
    r"^\s*(?:Request failed with status code|HTTP(?:\s+error)?|"
    r"status(?:\s+code)?|error)\s+[45]\d{2}"
    r"\s*(?::|at|-)\s*(?P<context>.+?)\s*$",
    re.IGNORECASE,
)
_SAFE_API_CONTEXT_RE = re.compile(r"^/api/[A-Za-z0-9._~!$&'()*+,;=:@%/-]+$")
_GENERIC_HTTP_STATUS_FRAGMENT_RE = re.compile(
    r"(?:\b[A-Za-z]+Error:\s*)?"
    r"(?:Request failed with status code|HTTP(?:\s+error)?|"
    r"status(?:\s+code)?|error)\s+[45]\d{2}"
    r"(?:\s*(?::|at|-)\s*(?P<context>"
    rf"{re.escape(_LOCAL_PATH_PLACEHOLDER)}|"
    r"/api/[^\s\"'<>)]*"
    r"))?",
    re.IGNORECASE,
)


def _truncate_feedback_text(value: str, limit: int = _MAX_CLIENT_LOG_STRING_LENGTH) -> str:
    if len(value) <= limit:
        return value
    return f"{value[:limit]}...<truncated>"


def _safe_status_context(value: str) -> str | None:
    token = value.strip().strip("\"'<>").split(maxsplit=1)[0]
    token = token.rstrip(".,;)")
    token = token.split("?", 1)[0].split("#", 1)[0]
    if not token.startswith("/api/"):
        return None
    if "\\" in token or "://" in token:
        return None
    if not _SAFE_API_CONTEXT_RE.fullmatch(token):
        return None
    if any(part in {".", ".."} for part in token.split("/")):
        return None
    return token


def _sanitize_feedback_text(
    value: str,
    limit: int = _MAX_CLIENT_LOG_STRING_LENGTH,
) -> str:
    """Redact local diagnostic strings before feedback export.

    在反馈导出前脱敏本机诊断字符串。
    """

    redacted = _LOCAL_FILE_URL_RE.sub(_LOCAL_PATH_PLACEHOLDER, value)
    redacted = _UNC_LOCAL_PATH_RE.sub(_LOCAL_PATH_PLACEHOLDER, redacted)
    redacted = _WINDOWS_LOCAL_PATH_RE.sub(_LOCAL_PATH_PLACEHOLDER, redacted)
    redacted = _POSIX_LOCAL_PATH_RE.sub(_LOCAL_PATH_PLACEHOLDER, redacted)
    if _GENERIC_HTTP_STATUS_RE.fullmatch(redacted) or (
        _GENERIC_HTTP_STATUS_WITH_REDACTED_PATH_RE.fullmatch(redacted)
    ):
        redacted = _GENERIC_HTTP_STATUS_DETAIL
    else:
        context_match = _GENERIC_HTTP_STATUS_WITH_CONTEXT_RE.fullmatch(redacted)
        if context_match is not None:
            safe_context = _safe_status_context(context_match.group("context"))
            redacted = _GENERIC_HTTP_STATUS_DETAIL
            if safe_context is not None:
                redacted = f"{redacted} Context: {safe_context}"
    return _truncate_feedback_text(redacted, limit)


def _sanitize_bug_report_description(value: str) -> str:
    """Redact diagnostics from the free-form bug-report description.

    从自由文本 Bug 描述中移除本机路径和传输层空错误文案。
    """

    redacted = _sanitize_feedback_text(value, limit=_MAX_DESCRIPTION_STRING_LENGTH)

    def _replace_http_status(match: re.Match[str]) -> str:
        context = match.group("context")
        safe_context = _safe_status_context(context) if context else None
        if safe_context is not None:
            return f"{_GENERIC_HTTP_STATUS_DETAIL} Context: {safe_context}"
        return _GENERIC_HTTP_STATUS_DETAIL

    normalized = _GENERIC_HTTP_STATUS_FRAGMENT_RE.sub(
        _replace_http_status,
        redacted,
    )
    return _truncate_feedback_text(normalized, _MAX_DESCRIPTION_STRING_LENGTH)


def _sanitize_feedback_jsonish(value: Any, *, depth: int = 0) -> Any:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, str):
        return _sanitize_feedback_text(value)
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
            key = _sanitize_feedback_text(str(raw_key), 120)
            sanitized[key] = _sanitize_feedback_jsonish(raw_value, depth=depth + 1)
        remaining = len(items) - _MAX_CLIENT_LOG_OBJECT_KEYS
        if remaining > 0:
            sanitized["__truncated_keys"] = remaining
        return sanitized
    return _sanitize_feedback_text(str(value))


def _sanitize_advanced_params(
    value: Any, *, depth: int = 0, path: str = ""
) -> Any:
    """Dedicated sanitizer for the grouped ``advanced_params`` payload.

    针对分组 ``advanced_params`` 载荷的专用 sanitizer。

    Mirrors :func:`_sanitize_feedback_jsonish` structurally (same scalar
    handling, same ``<truncated:depth>`` / ``<truncated:N>`` /
    ``__truncated_keys`` markers, same reuse of
    :func:`_truncate_feedback_text`) but uses the relaxed
    ``advanced_params`` limits: depth ≤ 6, array items ≤ 64, object keys
    ≤ 24. A path-level exception raises the object-key cap to 64 for the
    ``relief.color_height_map`` sub-object so a full frontend-trimmed color
    height map (≤ 64 entries) survives backend sanitization without losing
    keys.

    与 :func:`_sanitize_feedback_jsonish` 结构一致（相同的标量处理、相同的
    ``<truncated:depth>`` / ``<truncated:N>`` / ``__truncated_keys`` 标记、
    同样复用 :func:`_truncate_feedback_text`），但使用 ``advanced_params``
    的放宽上限：深度 ≤ 6、数组元素 ≤ 64、对象 key ≤ 24。对
    ``relief.color_height_map`` 这一路径做例外处理，将 object key 上限
    提升到 64，确保前端裁剪后的完整 color height map（最多 64 项）能被
    后端原样保留。

    Args:
        value: The value being sanitized (scalar, list, tuple, dict, or
            other). Unknown types are coerced via ``str()``.
            需要清洗的值（标量、list、tuple、dict 或其它类型）。未知类型将
            通过 ``str()`` 强制转换。
        depth: Current recursion depth. Callers pass ``0`` for the root.
            当前递归深度。调用方在根层传 ``0``。
        path: Dotted path of the current node relative to the root (for
            example ``"relief.color_height_map"``). Used only to apply the
            ``relief.color_height_map`` object-key exception.
            当前节点相对根的点号路径（例如 ``"relief.color_height_map"``），
            仅用于启用 ``relief.color_height_map`` 的 object-key 例外规则。

    Returns:
        A JSON-safe value: preserved scalars, truncated strings, or
        sanitized list/dict substructures with truncation markers when
        limits are exceeded.
        返回 JSON 友好的值：保留的标量、截断后的字符串、或者携带截断
        标记的 list/dict 子结构（超出上限时）。
    """
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, str):
        return _sanitize_feedback_text(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if isfinite(value) else str(value)
    if depth >= _ADV_PARAMS_MAX_DEPTH:
        return "<truncated:depth>"
    if isinstance(value, (list, tuple)):
        items = [
            _sanitize_advanced_params(
                item, depth=depth + 1, path=f"{path}[]"
            )
            for item in list(value)[:_ADV_PARAMS_MAX_ARRAY_ITEMS]
        ]
        remaining = len(value) - _ADV_PARAMS_MAX_ARRAY_ITEMS
        if remaining > 0:
            items.append(f"<truncated:{remaining}>")
        return items
    if isinstance(value, dict):
        # Path-level exception: relief.color_height_map allows 64 keys so
        # the frontend-trimmed color height map survives intact.
        # 路径级例外：relief.color_height_map 允许 64 个 key，保留前端
        # 已裁剪的 color height map。
        max_keys = _ADV_PARAMS_MAX_OBJECT_KEYS
        if path == "relief.color_height_map":
            max_keys = _ADV_PARAMS_COLOR_HEIGHT_MAP_MAX_KEYS

        sanitized: dict[str, Any] = {}
        items = list(value.items())
        for raw_key, raw_value in items[:max_keys]:
            key = _sanitize_feedback_text(str(raw_key), 120)
            child_path = f"{path}.{raw_key}" if path else str(raw_key)
            sanitized[key] = _sanitize_advanced_params(
                raw_value, depth=depth + 1, path=child_path
            )
        remaining = len(items) - max_keys
        if remaining > 0:
            sanitized["__truncated_keys"] = remaining
        return sanitized
    return _sanitize_feedback_text(str(value))


def _sanitize_client_log_entry(entry: Any) -> dict[str, Any]:
    if not isinstance(entry, dict):
        return {"label": "client log", "details": _sanitize_feedback_jsonish(entry)}

    sanitized: dict[str, Any] = {}
    for key in ("timestamp", "method", "label", "scope", "phase"):
        value = entry.get(key)
        if value is not None:
            sanitized[key] = _sanitize_feedback_text(str(value), 256)
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


class BugReportWorkshopContext(BaseModel):
    """Safe Creative Workshop runtime metadata for a bug report.

    Bug 报告中的安全创意工坊运行元数据。

    Project payloads, pixels, palettes, image bytes, package paths,
    credentials, signing material, and desktop tokens are intentionally
    outside this schema. Unknown keys are discarded before the report is
    persisted or relayed.

    工程载荷、像素、色板、图像字节、安装包路径、凭据、签名材料和桌面令牌
    均不属于此结构；未知字段会在工单持久化或转发前被丢弃。
    """

    model_config = ConfigDict(extra="ignore")

    module_id: str = Field(min_length=1, max_length=128)
    module_version: str = Field(min_length=1, max_length=128)
    install_source: Literal[
        "registry", "github", "local", "seed", "unknown"
    ] = "unknown"
    audit_status: Literal[
        "official",
        "verified",
        "deprecated",
        "blocked",
        "unreviewed",
        "unknown",
    ] = "unknown"
    runtime_mode: Literal[
        "desktop-secure",
        "browser-restricted",
        "unsafe-development",
        "unknown",
    ] = "unknown"
    error_code: str | None = Field(default=None, max_length=128)


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
    printer_id: str | None = Field(default=None, max_length=128)
    slicer: str | None = Field(default=None, max_length=128)
    nozzle_size: str | None = Field(default=None, max_length=16)
    device_profile_id: str | None = Field(default=None, max_length=256)
    build_plate_id: str | None = Field(default=None, max_length=128)
    color_mode: str | None = Field(default=None, max_length=64)
    lut_name: str | None = Field(default=None, max_length=256)
    lut_names: list[str] = Field(default_factory=list, max_length=32)
    source_version: Literal["legacy", "native", "material"] | None = None
    selected_native_brand_key: str | None = Field(default=None, max_length=128)
    selected_native_db_names: list[str] = Field(default_factory=list, max_length=128)
    selected_material_dir_names: list[str] = Field(default_factory=list, max_length=128)
    material_layer_count: int | None = Field(default=None, ge=0, le=1000)
    material_dynamic_layer_count_enabled: bool | None = None
    material_min_layer_count: int | None = Field(default=None, ge=5, le=10)
    material_max_layer_count: int | None = Field(default=None, ge=5, le=10)
    material_delta_e00_tolerance: float | None = Field(
        default=None,
        ge=0.0,
        le=5.0,
    )
    material_layer_height_mm: float | None = Field(default=None, ge=0.0, le=10.0)
    material_backing_material_dir_name: str | None = Field(default=None, max_length=128)
    preserve_upload_filename_for_3mf: bool | None = None
    enable_smooth_vector_preview: bool | None = None
    vector_preview_renderer: Literal["vector_analytic", "segmented"] | None = None
    recent_client_logs: list[dict[str, Any]] = Field(default_factory=list)

    # --- Reproducible-bug-reports extensions (Req 2/3/5/6). All optional so
    #     older clients that predate this upgrade still deserialize cleanly.
    # 可重现 Bug 报告新增字段；全部可选，老客户端不传也能正常反序列化。
    action_history: list[dict[str, Any]] = Field(default_factory=list)
    session_history: list[dict[str, Any]] = Field(default_factory=list)
    active_original_image_ref: BugReportOriginalImageRef | None = None
    active_final_artifact_ref: BugReportFinalArtifactRef | None = None
    workshop: BugReportWorkshopContext | None = None

    # Grouped advanced generation parameters captured from the converter store.
    # Kept as a free-form dict here; the dedicated sanitizer in
    # ``submit_bug_report`` enforces depth/size limits before it is persisted
    # to ticket.json, which keeps this validator cheap and the sanitizer
    # reusable from the ``action_history`` path.
    # 采集自 ConverterStore 的分组高级生成参数。此处仅做形状校验（dict 或 null），
    # 真正的深度/大小裁剪由 submit_bug_report 中的专用 sanitizer 完成，便于复用。
    advanced_params: dict[str, Any] | None = None

    @field_validator("lut_names", mode="before")
    @classmethod
    def _validate_lut_names(cls, value: Any) -> list[str]:
        """Bound legacy multi-LUT names captured for repro.

        限制用于复现的传统多选 LUT 名称列表。
        """

        if value is None:
            return []
        if not isinstance(value, list):
            return []
        normalized: list[str] = []
        for item in value[:32]:
            if not isinstance(item, str):
                continue
            clean = item.strip()
            if clean and len(clean) <= 256 and clean not in normalized:
                normalized.append(clean)
        return normalized

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

        Each entry's nested ``snapshot.advanced_params`` (when present) is
        extracted before the generic sanitizer runs and is then routed
        through the dedicated :func:`_sanitize_advanced_params` so the
        relaxed depth/key limits apply there. The original request payload
        is never mutated — shallow copies of the entry and snapshot are
        used for extraction.

        嵌套在 ``snapshot.advanced_params`` 下的高级参数会先被取出，避免
        受限于通用 sanitizer 的严格深度/key 上限，再通过专用
        :func:`_sanitize_advanced_params` 单独清洗。清洗过程使用 entry
        与 snapshot 的浅拷贝，原始请求载荷不会被修改。
        """

        if not isinstance(value, list):
            return []
        tail = value[-_MAX_ACTION_HISTORY_ENTRIES:]
        sanitized: list[dict[str, Any]] = []
        for item in tail:
            if not isinstance(item, dict):
                continue

            # Work on shallow copies so the incoming Pydantic payload is
            # never mutated by this pre-processing step.
            # 使用浅拷贝处理，避免污染原始请求载荷。
            item_copy: dict[str, Any] = dict(item)
            extracted_advanced_params: Any = None
            had_advanced_params = False

            raw_snapshot = item_copy.get("snapshot")
            if isinstance(raw_snapshot, dict):
                snapshot_copy = dict(raw_snapshot)
                if "advanced_params" in snapshot_copy:
                    had_advanced_params = True
                    extracted_advanced_params = snapshot_copy.pop(
                        "advanced_params"
                    )
                    item_copy["snapshot"] = snapshot_copy

            sanitized_item = _sanitize_feedback_jsonish(item_copy)  # type: ignore[arg-type]

            if had_advanced_params:
                if extracted_advanced_params is None:
                    sanitized_value: Any = None
                elif isinstance(extracted_advanced_params, dict):
                    try:
                        sanitized_value = _sanitize_advanced_params(
                            extracted_advanced_params
                        )
                    except Exception as exc:  # noqa: BLE001 - boundary guard
                        log.warning(
                            "Advanced params sanitization failed for "
                            "action_history entry.",
                            extra={
                                "event": "feedback_advanced_params_failed",
                                "error_type": type(exc).__name__,
                                "error_message": str(exc),
                                "surface": "action_history",
                            },
                        )
                        sanitized_value = None
                else:
                    log.warning(
                        "Advanced params sanitization failed for "
                        "action_history entry.",
                        extra={
                            "event": "feedback_advanced_params_failed",
                            "error_type": "TypeError",
                            "error_message": (
                                "advanced_params must be a dict or null; "
                                f"got {type(extracted_advanced_params).__name__}"
                            ),
                            "surface": "action_history",
                        },
                    )
                    sanitized_value = None

                snapshot_out = sanitized_item.get("snapshot")
                if not isinstance(snapshot_out, dict):
                    snapshot_out = {}
                snapshot_out["advanced_params"] = sanitized_value
                sanitized_item["snapshot"] = snapshot_out

            sanitized.append(sanitized_item)
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

    @field_validator("advanced_params", mode="before")
    @classmethod
    def _validate_advanced_params(cls, value: Any) -> dict[str, Any] | None:
        """Shape-check ``advanced_params`` cheaply; accept ``dict`` or ``None``.

        仅做形状校验：接受 ``dict`` 或 ``None``，其它类型以 422 拒绝。

        This validator intentionally does not recurse into the payload; the
        dedicated ``_sanitize_advanced_params`` sanitizer (called from
        ``submit_bug_report``) enforces depth/size/bytes limits before the
        value is persisted. Keeping the validator cheap lets Pydantic-time
        validation stay fast and lets the sanitizer be reused from the
        ``action_history`` snapshot pre-processing path.

        该校验器只做形状判断，不递归遍历载荷；深度/大小限制由专用
        ``_sanitize_advanced_params`` sanitizer 在 ``submit_bug_report`` 中执行，
        同时可被 ``action_history`` 中嵌套 snapshot 的预处理复用。
        """

        if value is None:
            return None
        if isinstance(value, dict):
            return value
        raise ValueError("advanced_params must be a dict or null")


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


_DYNAMIC_MATERIAL_CONTEXT_FIELDS = {
    "material_dynamic_layer_count_enabled",
    "material_min_layer_count",
    "material_max_layer_count",
    "material_delta_e00_tolerance",
}


def _dump_bug_report_request(
    request: BugReportRequest,
    *,
    include_existing_defaults: bool = True,
) -> dict[str, Any]:
    """Serialize a report without inventing absent dynamic-material fields.

    序列化报告时不为旧客户端凭空补入未提交的动态材料字段。

    Args:
        request: Validated bug-report request. / 已校验的 Bug 报告请求。
        include_existing_defaults: Preserve the historical local ticket shape.
            / 保留既有本地工单默认字段结构。

    Returns:
        JSON-compatible request payload. / JSON 兼容的请求载荷。
    """

    if not include_existing_defaults:
        return request.model_dump(mode="json", exclude_unset=True)

    absent_dynamic_fields = (
        _DYNAMIC_MATERIAL_CONTEXT_FIELDS - request.context.model_fields_set
    )
    exclude = {"context": absent_dynamic_fields} if absent_dynamic_fields else None
    return request.model_dump(mode="json", exclude=exclude)


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
    """Return a non-sensitive logical POSIX path for response bodies.

    返回用于响应体的非敏感逻辑 POSIX 路径。
    """
    try:
        return ticket_dir.resolve().relative_to(_REPO_ROOT).as_posix()
    except ValueError:
        return f"feedback/{ticket_dir.parent.name}/{ticket_dir.name}"


def _sanitize_bug_report_context_for_export(context: dict[str, Any]) -> dict[str, Any]:
    """Remove local-only fields before persisting or forwarding context.

    在持久化或转发反馈上下文前移除只应在本机使用的字段。
    """

    sanitized = deepcopy(context)
    final_ref = sanitized.get("active_final_artifact_ref")
    if isinstance(final_ref, dict):
        sanitized_ref = dict(final_ref)
        sanitized_ref.pop("disk_path", None)
        sanitized["active_final_artifact_ref"] = sanitized_ref
    return sanitized


def _sanitize_bug_report_request_payload_for_export(
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Return an export-safe bug-report request payload copy.

    返回可安全持久化或转发的 Bug 报告请求 payload 副本。
    """

    sanitized = deepcopy(payload)
    description = sanitized.get("description")
    if isinstance(description, str):
        sanitized["description"] = _sanitize_bug_report_description(description)
    context = sanitized.get("context")
    if isinstance(context, dict):
        sanitized["context"] = _sanitize_bug_report_context_for_export(context)
    return sanitized


@router.post(
    "/bug-report",
    response_model=BugReportResponse,
    dependencies=[Depends(require_local_app_origin)],
)
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

    request_dump = _dump_bug_report_request(request)
    attachment_context_dump = deepcopy(request_dump.get("context") or {})
    context_dump = _sanitize_bug_report_context_for_export(attachment_context_dump)

    # Dedicated sanitization for ``advanced_params``. Pydantic's validator only
    # shape-checks the field (dict-or-null); the real depth/size enforcement
    # runs here so it can share the same sanitizer used for action_history
    # snapshots. On overflow we fall back to the *same* shape the frontend
    # emits for its size fallback (``AdvancedParamsSizeTrimmed``): a two-key
    # object ``{"_size_trimmed": True, "_original_byte_length": N}``. We do
    # not introduce a third variant like ``{"_sanitizer_trimmed": True}``.
    #
    # 专用的 ``advanced_params`` 深度/大小裁剪。Pydantic 校验器只做 dict/None
    # 形状校验，真正的裁剪在这里完成，便于与 action_history 中的嵌套
    # snapshot 复用同一 sanitizer。超限时回落到与前端一致的 size fallback
    # 形状（``AdvancedParamsSizeTrimmed``），不引入第三种结构。
    if context_dump.get("advanced_params") is not None:
        try:
            sanitized_ap = _sanitize_advanced_params(context_dump["advanced_params"])
            ap_json = json.dumps(sanitized_ap, ensure_ascii=False)
            original_byte_length = len(ap_json.encode("utf-8"))
            if original_byte_length > _ADV_PARAMS_MAX_TOTAL_BYTES:
                sanitized_ap = {
                    "_size_trimmed": True,
                    "_original_byte_length": original_byte_length,
                }
            context_dump["advanced_params"] = sanitized_ap
        except Exception as exc:  # noqa: BLE001 — sanitizer must never crash submit.
            log.warning(
                "Advanced params sanitization failed.",
                extra={
                    "event": "feedback_advanced_params_failed",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                },
            )
            context_dump["advanced_params"] = None

    received_at_utc = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    request_id = getattr(http_request.state, "request_id", None)

    payload: dict[str, Any] = {
        "schema_version": 3,
        "ticket_id": ticket_id,
        "received_at_cst": format_received_cst(now),
        "received_at_utc": received_at_utc,
        "description": _sanitize_bug_report_description(request.description),
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
            payload["attachments"]["screenshot"] = {
                "status": "failed",
                "filename": screenshot_path.name,
                "size_bytes": None,
                "error_type": type(exc).__name__,
                "error_message": "Screenshot could not be saved.",
            }
            log.warning(
                "Screenshot write failed.",
                extra={
                    "event": "feedback_attachment_lookup_failed",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "path": str(screenshot_path),
                    "attachment_kind": "screenshot",
                    "ticket_id": ticket_id,
                },
            )

    # Sync attachment collection (original image / final artifact / LUT)
    file_registry = get_file_registry()
    session_store = get_session_store()
    try:
        attachment_payload = {**payload, "context": attachment_context_dump}
        sync_result = collect_sync_attachments(
            ticket_dir=ticket_dir,
            payload=attachment_payload,
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


@router.post(
    "/bug-report/relay",
    response_model=BugReportRelayResponse,
    dependencies=[Depends(require_local_app_origin)],
)
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
                    "request_payload": _sanitize_bug_report_request_payload_for_export(
                        _dump_bug_report_request(
                            request.request_payload,
                            include_existing_defaults=False,
                        )
                    ),
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
