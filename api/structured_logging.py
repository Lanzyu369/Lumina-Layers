"""Structured logging utilities for API and worker processes."""

from __future__ import annotations

import contextvars
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)
_session_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("session_id", default=None)
_standard_record = logging.makeLogRecord({})
_STANDARD_LOG_RECORD_KEYS = frozenset(_standard_record.__dict__.keys())
_EXTERNAL_NOISE_KEYS = frozenset(
    {
        "color_message",  # uvicorn ANSI render template
        "color_msg",  # uvicorn variant
    }
)
_EXTERNAL_LOGGER_PREFIXES = ("uvicorn", "fastapi", "starlette", "asyncio", "httpx", "watchfiles")

_CONSOLE_HANDLER_ATTR = "_lumina_console_handler"
_FILE_HANDLER_ATTR = "_lumina_file_handler"
_FILE_HANDLER_PATH_ATTR = "_lumina_file_path"


def set_request_id(request_id: str | None) -> contextvars.Token[str | None]:
    return _request_id_var.set(request_id)


def reset_request_id(token: contextvars.Token[str | None]) -> None:
    _request_id_var.reset(token)


def get_request_id() -> str | None:
    return _request_id_var.get()


def set_session_id(session_id: str | None) -> contextvars.Token[str | None]:
    return _session_id_var.set(session_id)


def reset_session_id(token: contextvars.Token[str | None]) -> None:
    _session_id_var.reset(token)


def get_session_id() -> str | None:
    return _session_id_var.get()


def bind_session_id(session_id: str | None) -> None:
    _session_id_var.set(session_id)


def _coerce_jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _coerce_jsonable(val) for key, val in value.items() if val is not None}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_coerce_jsonable(item) for item in value]
    return str(value)


def _without_none(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}


def _extra_fields(record: logging.LogRecord, existing_keys: set[str]) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for key, value in record.__dict__.items():
        if key in _STANDARD_LOG_RECORD_KEYS or key in existing_keys or key.startswith("_"):
            continue
        if key in _EXTERNAL_NOISE_KEYS:
            continue
        if value is None:
            continue
        fields[key] = _coerce_jsonable(value)
    return fields


def _resolve_event_label(record: logging.LogRecord) -> str:
    """Return event label for record, using logger family for external records."""

    explicit = getattr(record, "event", None)
    if explicit:
        return str(explicit)
    name = record.name or "external"
    for prefix in _EXTERNAL_LOGGER_PREFIXES:
        if name == prefix or name.startswith(prefix + "."):
            return prefix
    return "external"


class _JsonFormatter(logging.Formatter):
    """Render log records as one-line JSON."""

    def format(self, record: logging.LogRecord) -> str:  # noqa: D401
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "event": _resolve_event_label(record),
            "module": record.name,
            "request_id": get_request_id(),
            "session_id": getattr(record, "session_id", get_session_id()),
            "path": getattr(record, "path", None),
            "method": getattr(record, "method", None),
            "status_code": getattr(record, "status_code", None),
            "duration_ms": getattr(record, "duration_ms", None),
            "error_type": getattr(record, "error_type", None),
            "error_message": getattr(record, "error_message", None),
            "message": record.getMessage(),
        }
        payload = _without_none(payload)
        payload.update(_extra_fields(record, set(payload)))
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


class _HumanFormatter(logging.Formatter):
    """Render log records as readable single-line text."""

    def format(self, record: logging.LogRecord) -> str:  # noqa: D401
        payload: dict[str, Any] = {
            "request_id": get_request_id(),
            "session_id": getattr(record, "session_id", get_session_id()),
            "path": getattr(record, "path", None),
            "method": getattr(record, "method", None),
            "status_code": getattr(record, "status_code", None),
            "duration_ms": getattr(record, "duration_ms", None),
            "error_type": getattr(record, "error_type", None),
            "error_message": getattr(record, "error_message", None),
        }
        payload = _without_none(payload)
        payload.update(_extra_fields(record, set(payload) | {"event"}))
        fields = " ".join(f"{key}={_format_human_value(value)}" for key, value in payload.items())
        timestamp = datetime.now(timezone.utc).isoformat()
        event = _resolve_event_label(record)
        parts = [timestamp, record.levelname, str(event), record.name, _single_line(record.getMessage())]
        if fields:
            parts.append(fields)
        if record.exc_info:
            parts.append(f"exception={_format_human_value(self.formatException(record.exc_info))}")
        return " ".join(parts)


def _single_line(value: Any) -> str:
    return str(value).replace("\r", "\\r").replace("\n", "\\n")


def _format_human_value(value: Any) -> str:
    if isinstance(value, (dict, list, tuple, set, frozenset)):
        return json.dumps(_coerce_jsonable(value), ensure_ascii=False, separators=(",", ":"))
    text = _single_line(value)
    if not text or any(char.isspace() for char in text):
        return json.dumps(text, ensure_ascii=False)
    return text


def _parse_log_level(raw_level: str | None) -> int:
    if raw_level is None:
        return logging.INFO
    level_name = raw_level.strip().upper()
    if not level_name:
        return logging.INFO
    if level_name.isdigit():
        return int(level_name)
    parsed = logging.getLevelName(level_name)
    return parsed if isinstance(parsed, int) else logging.INFO


def _resolve_console_format(stream: Any) -> str:
    requested = os.environ.get("LUMINA_LOG_FORMAT", "auto").strip().lower()
    if requested in {"json", "human"}:
        return requested
    try:
        return "human" if stream.isatty() else "json"
    except Exception:
        return "json"


def _make_console_formatter(stream: Any) -> logging.Formatter:
    if _resolve_console_format(stream) == "human":
        return _HumanFormatter()
    return _JsonFormatter()


def _find_console_handler(logger: logging.Logger) -> logging.Handler | None:
    for handler in logger.handlers:
        if getattr(handler, _CONSOLE_HANDLER_ATTR, False):
            return handler
    return None


def _ensure_console_handler(logger: logging.Logger, level: int) -> None:
    handler = _find_console_handler(logger)
    if handler is None:
        handler = logging.StreamHandler(sys.stdout)
        setattr(handler, _CONSOLE_HANDLER_ATTR, True)
        logger.addHandler(handler)
    handler.setLevel(level)
    handler.setFormatter(_make_console_formatter(sys.stdout))


def _normalize_path(path: str) -> str:
    return str(Path(path).expanduser().resolve())


def _ensure_file_handler(logger: logging.Logger, level: int) -> None:
    raw_path = os.environ.get("LUMINA_LOG_PATH")
    file_path = _normalize_path(raw_path) if raw_path else None

    for handler in list(logger.handlers):
        if not getattr(handler, _FILE_HANDLER_ATTR, False):
            continue
        handler_path = getattr(handler, _FILE_HANDLER_PATH_ATTR, None)
        if file_path is None or handler_path != file_path:
            logger.removeHandler(handler)
            handler.close()

    if file_path is None:
        return

    for handler in logger.handlers:
        if getattr(handler, _FILE_HANDLER_ATTR, False) and getattr(handler, _FILE_HANDLER_PATH_ATTR, None) == file_path:
            handler.setLevel(level)
            handler.setFormatter(_JsonFormatter())
            return

    try:
        Path(file_path).parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(file_path, encoding="utf-8")
    except OSError as exc:
        _emit_file_handler_warning(file_path, exc)
        return
    setattr(file_handler, _FILE_HANDLER_ATTR, True)
    setattr(file_handler, _FILE_HANDLER_PATH_ATTR, file_path)
    file_handler.setLevel(level)
    file_handler.setFormatter(_JsonFormatter())
    logger.addHandler(file_handler)


def _emit_file_handler_warning(file_path: str, exc: OSError) -> None:
    try:
        sys.__stderr__.write(
            f"[LOG][WARNING] Structured file logging disabled for '{file_path}': {type(exc).__name__}: {exc}\n"
        )
        sys.__stderr__.flush()
    except Exception:
        pass


def _lumina_handlers() -> list[logging.Handler]:
    return list(logging.getLogger("lumina").handlers)


def _remove_lumina_handlers(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        if getattr(handler, _CONSOLE_HANDLER_ATTR, False) or getattr(handler, _FILE_HANDLER_ATTR, False):
            logger.removeHandler(handler)


def attach_root_logger(level: int = logging.WARNING) -> None:
    """Attach Lumina structured handlers to the root logger.
    将 Lumina 结构化 handler 挂到 root logger，统一第三方日志出口。
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    _remove_lumina_handlers(root_logger)
    for handler in _lumina_handlers():
        root_logger.addHandler(handler)


def _configure_uvicorn_loggers(level: int) -> None:
    access_logger = logging.getLogger("uvicorn.access")
    access_logger.handlers.clear()
    access_logger.setLevel(logging.WARNING)
    access_logger.propagate = False

    error_logger = logging.getLogger("uvicorn.error")
    error_logger.handlers.clear()
    error_logger.setLevel(logging.WARNING)
    for handler in _lumina_handlers():
        error_logger.addHandler(handler)
    error_logger.propagate = False


def configure_structured_logging() -> None:
    """Initialize process logging, reusing the existing Lumina handlers.
    初始化进程日志，复用已有的 Lumina 输出 handler。
    """
    logger = logging.getLogger("lumina")
    level = _parse_log_level(os.environ.get("LUMINA_LOG_LEVEL"))
    logger.setLevel(level)
    logger.propagate = False

    _ensure_console_handler(logger, level)
    _ensure_file_handler(logger, level)
    attach_root_logger()
    _configure_uvicorn_loggers(level)


def get_logger(name: str) -> logging.Logger:
    """Get a Lumina logger without configuring the host process.
    获取 Lumina 命名空间下的 logger，不改变宿主进程的日志配置。
    """
    if name.startswith("lumina."):
        return logging.getLogger(name)
    return logging.getLogger(f"lumina.{name}")
