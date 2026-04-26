from __future__ import annotations

import json
import logging
import sys
import tempfile
import uuid
from io import StringIO
from pathlib import Path

import pytest

import api.structured_logging as structured_logging
from api.structured_logging import _HumanFormatter, _JsonFormatter


class _CaptureStream(StringIO):
    def __init__(self, tty: bool) -> None:
        super().__init__()
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


def _reset_lumina_logging(monkeypatch=None) -> None:
    logger = logging.getLogger("lumina")
    for handler in list(logger.handlers):
        handler.close()
    logger.handlers.clear()
    structured_logging._configured = False
    if monkeypatch is not None:
        monkeypatch.delenv("LUMINA_LOG_PATH", raising=False)


def _temp_log_path(name: str) -> Path:
    return Path(tempfile.gettempdir()) / "lumina-logs" / f"{name}_{uuid.uuid4().hex}.log"


@pytest.fixture(autouse=False)
def _clean_lumina_logger():
    import logging
    import api.structured_logging as sl

    logging.getLogger("lumina").handlers.clear()
    sl._configured = False
    sl.set_request_id(None)
    sl.bind_session_id(None)
    yield
    logging.getLogger("lumina").handlers.clear()
    sl._configured = False
    sl.set_request_id(None)
    sl.bind_session_id(None)


def test_json_formatter_preserves_custom_extra_fields() -> None:
    formatter = _JsonFormatter()
    record = logging.makeLogRecord(
        {
            "name": "lumina.test",
            "levelno": logging.INFO,
            "levelname": "INFO",
            "msg": "Client log received",
            "args": (),
            "event": "client_log",
            "client_label": "preview: request sent",
            "client_scope": "preview",
            "client_phase": "request-sent",
            "client_details": {
                "quantize_colors": 256,
                "selected_material_count": 4,
                "flags": ["cleanup", "preview-glb"],
            },
        }
    )

    payload = json.loads(formatter.format(record))

    assert payload["event"] == "client_log"
    assert payload["client_label"] == "preview: request sent"
    assert payload["client_scope"] == "preview"
    assert payload["client_phase"] == "request-sent"
    assert payload["client_details"] == {
        "quantize_colors": 256,
        "selected_material_count": 4,
        "flags": ["cleanup", "preview-glb"],
    }


def test_json_formatter_omits_none_fields(_clean_lumina_logger) -> None:
    formatter = _JsonFormatter()
    record = logging.makeLogRecord(
        {
            "name": "lumina.test",
            "levelno": logging.INFO,
            "levelname": "INFO",
            "msg": "Request finished",
            "args": (),
            "event": "request_completed",
            "path": None,
            "method": "GET",
            "status_code": None,
            "duration_ms": 12.5,
            "optional_detail": None,
        }
    )

    payload = json.loads(formatter.format(record))

    assert payload["event"] == "request_completed"
    assert payload["method"] == "GET"
    assert payload["duration_ms"] == 12.5
    assert "path" not in payload
    assert "status_code" not in payload
    assert "optional_detail" not in payload
    assert "request_id" not in payload
    assert "session_id" not in payload


def test_human_formatter_outputs_single_readable_line() -> None:
    formatter = _HumanFormatter()
    record = logging.makeLogRecord(
        {
            "name": "lumina.test",
            "levelno": logging.INFO,
            "levelname": "INFO",
            "msg": "Client log received",
            "args": (),
            "event": "client_log",
            "client_scope": "preview",
            "path": "/api/log/client",
        }
    )

    line = formatter.format(record)

    assert "\n" not in line
    assert "INFO" in line
    assert "client_log" in line
    assert "lumina.test" in line
    assert "Client log received" in line
    assert "client_scope=preview" in line
    assert "path=/api/log/client" in line
    assert not line.lstrip().startswith("{")


def test_json_formatter_labels_uvicorn_records_without_noise() -> None:
    formatter = _JsonFormatter()
    record = logging.makeLogRecord(
        {
            "name": "uvicorn.error",
            "levelno": logging.INFO,
            "levelname": "INFO",
            "msg": "Started server process [%d]",
            "args": (26600,),
            "color_message": "Started server process [\u001b[36m%d\u001b[0m]",
        }
    )

    payload = json.loads(formatter.format(record))

    assert payload["event"] == "uvicorn"
    assert payload["module"] == "uvicorn.error"
    assert payload["message"] == "Started server process [26600]"
    assert "color_message" not in payload


def test_human_formatter_labels_uvicorn_records_without_repeating_message() -> None:
    formatter = _HumanFormatter()
    record = logging.makeLogRecord(
        {
            "name": "uvicorn.error",
            "levelno": logging.INFO,
            "levelname": "INFO",
            "msg": "Started server process [%d]",
            "args": (26600,),
            "color_message": "Started server process [\u001b[36m%d\u001b[0m]",
        }
    )

    line = formatter.format(record)

    assert "INFO uvicorn uvicorn.error Started server process [26600]" in line
    assert line.count("Started server process [26600]") == 1
    assert "color_message" not in line


def test_configure_structured_logging_honors_explicit_json_format(monkeypatch) -> None:
    _reset_lumina_logging(monkeypatch)
    stream = _CaptureStream(tty=True)
    monkeypatch.setattr(sys, "stdout", stream)
    monkeypatch.setenv("LUMINA_LOG_FORMAT", "json")

    structured_logging.configure_structured_logging()
    logging.getLogger("lumina.test").info("hello", extra={"event": "explicit_json"})

    payload = json.loads(stream.getvalue())
    assert payload["event"] == "explicit_json"


def test_configure_structured_logging_honors_explicit_human_format(monkeypatch) -> None:
    _reset_lumina_logging(monkeypatch)
    stream = _CaptureStream(tty=False)
    monkeypatch.setattr(sys, "stdout", stream)
    monkeypatch.setenv("LUMINA_LOG_FORMAT", "human")

    structured_logging.configure_structured_logging()
    logging.getLogger("lumina.test").info("hello", extra={"event": "explicit_human"})

    output = stream.getvalue()
    assert "explicit_human" in output
    assert not output.lstrip().startswith("{")


def test_configure_structured_logging_auto_uses_tty_to_select_format(monkeypatch) -> None:
    _reset_lumina_logging(monkeypatch)
    tty_stream = _CaptureStream(tty=True)
    monkeypatch.setattr(sys, "stdout", tty_stream)
    monkeypatch.setenv("LUMINA_LOG_FORMAT", "auto")

    structured_logging.configure_structured_logging()
    logging.getLogger("lumina.test").info("hello", extra={"event": "auto_human"})

    assert "auto_human" in tty_stream.getvalue()
    assert not tty_stream.getvalue().lstrip().startswith("{")

    _reset_lumina_logging(monkeypatch)
    pipe_stream = _CaptureStream(tty=False)
    monkeypatch.setattr(sys, "stdout", pipe_stream)

    structured_logging.configure_structured_logging()
    logging.getLogger("lumina.test").info("hello", extra={"event": "auto_json"})

    payload = json.loads(pipe_stream.getvalue())
    assert payload["event"] == "auto_json"


def test_configure_structured_logging_adds_one_json_file_handler(monkeypatch) -> None:
    _reset_lumina_logging(monkeypatch)
    stream = _CaptureStream(tty=True)
    log_path = _temp_log_path("structured_logging")
    log_path.unlink(missing_ok=True)
    monkeypatch.setattr(sys, "stdout", stream)
    monkeypatch.setenv("LUMINA_LOG_PATH", str(log_path))

    structured_logging.configure_structured_logging()
    structured_logging.configure_structured_logging()
    logging.getLogger("lumina.test").info("file event", extra={"event": "file_event"})

    file_handlers = [
        handler
        for handler in logging.getLogger("lumina").handlers
        if isinstance(handler, logging.FileHandler)
    ]
    assert len(file_handlers) == 1
    for handler in file_handlers:
        handler.flush()

    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["event"] == "file_event"
    _reset_lumina_logging()
    log_path.unlink(missing_ok=True)
