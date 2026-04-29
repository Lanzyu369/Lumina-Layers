"""Unit tests for file-logger startup fallback behavior."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import api.logger as logger_module
import api.structured_logging as structured_logging


def _reset_file_logging(monkeypatch) -> None:
    monkeypatch.setattr(logger_module, "_logging_initialized", False)
    monkeypatch.delenv("LUMINA_LOG_PATH", raising=False)
    monkeypatch.delenv("LUMINA_LOG_INIT_BY_PARENT", raising=False)
    lumina_logger = structured_logging.logging.getLogger("lumina")
    for handler in list(lumina_logger.handlers):
        handler.close()
    lumina_logger.handlers.clear()
    structured_logging._configured = False


def _temp_log_path(name: str) -> Path:
    return Path(logger_module.tempfile.gettempdir()) / "lumina-logs" / f"{name}_{uuid.uuid4().hex}.log"


def test_setup_file_logging_does_not_crash_on_unwritable_log_target(monkeypatch) -> None:
    """Logger setup should degrade gracefully when the log file cannot be opened."""

    original_stdout = logger_module.sys.stdout
    original_stderr = logger_module.sys.__stderr__
    _reset_file_logging(monkeypatch)

    def _raise_permission_error(log_path: Path) -> None:
        raise PermissionError("access denied")

    monkeypatch.setattr(logger_module, "_prepare_log_path", _raise_permission_error)

    result = logger_module.setup_file_logging(log_path=Path("logs") / "blocked.log")

    assert result is None
    assert logger_module._logging_initialized is False
    assert logger_module.sys.stdout is original_stdout
    assert logger_module.sys.__stderr__ is original_stderr
    assert "LUMINA_LOG_PATH" not in os.environ


def test_setup_file_logging_falls_back_to_secondary_path(monkeypatch) -> None:
    """Logger setup should try later candidates when the preferred one fails."""

    original_stdout = logger_module.sys.stdout
    _reset_file_logging(monkeypatch)

    primary = _temp_log_path("primary")
    secondary = _temp_log_path("secondary")
    secondary.unlink(missing_ok=True)
    monkeypatch.setattr(
        logger_module,
        "_resolve_log_candidates",
        lambda explicit_path=None: [primary, secondary],
    )

    prepared_paths: list[Path] = []

    def _prepare_log_path(log_path: Path) -> None:
        if log_path == primary:
            raise PermissionError("primary blocked")
        prepared_paths.append(log_path)

    monkeypatch.setattr(logger_module, "_prepare_log_path", _prepare_log_path)

    result = logger_module.setup_file_logging()

    assert result == secondary
    assert logger_module._logging_initialized is True
    assert prepared_paths == [secondary]
    assert os.environ["LUMINA_LOG_PATH"] == str(secondary.resolve())
    assert logger_module.sys.stdout is original_stdout
    _reset_file_logging(monkeypatch)
    secondary.unlink(missing_ok=True)


def test_setup_file_logging_does_not_replace_stdout_and_writes_json_lines(monkeypatch) -> None:
    """File logging should use structured handlers instead of replacing stdout."""

    original_stdout = logger_module.sys.stdout
    _reset_file_logging(monkeypatch)
    log_path = _temp_log_path("json_lines")
    log_path.unlink(missing_ok=True)

    result = logger_module.setup_file_logging(log_path=log_path)
    structured_logging.get_logger(__name__).info(
        "custom event",
        extra={"event": "custom_event", "path": None, "status_code": 200},
    )

    assert result == log_path
    assert logger_module.sys.stdout is original_stdout
    assert os.environ["LUMINA_LOG_PATH"] == str(log_path.resolve())

    for handler in structured_logging.logging.getLogger("lumina").handlers:
        handler.flush()

    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert lines
    assert '"event":"log_file_configured"' in lines[0]
    assert any('"event":"custom_event"' in line for line in lines)
    assert all('"path":null' not in line for line in lines)
    _reset_file_logging(monkeypatch)
    log_path.unlink(missing_ok=True)


def test_setup_file_logging_reuses_inherited_path_without_configured_event(monkeypatch) -> None:
    """Spawned children should attach to the inherited log file silently."""

    _reset_file_logging(monkeypatch)
    log_path = _temp_log_path("inherited")
    log_path.unlink(missing_ok=True)
    monkeypatch.setenv("LUMINA_LOG_PATH", str(log_path))
    monkeypatch.setenv("LUMINA_LOG_INIT_BY_PARENT", "1")

    result = logger_module.setup_file_logging()
    structured_logging.get_logger(__name__).info(
        "child event",
        extra={"event": "child_event"},
    )

    assert result == log_path
    assert os.environ["LUMINA_LOG_PATH"] == str(log_path.resolve())

    for handler in structured_logging.logging.getLogger("lumina").handlers:
        handler.flush()

    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert lines
    assert all('"event":"log_file_configured"' not in line for line in lines)
    assert any('"event":"child_event"' in line for line in lines)
    _reset_file_logging(monkeypatch)
    log_path.unlink(missing_ok=True)


def test_setup_file_logging_reuses_explicit_inherited_path_without_configured_event(monkeypatch) -> None:
    """Worker initializer passes the inherited path explicitly and should stay silent."""

    _reset_file_logging(monkeypatch)
    log_path = _temp_log_path("explicit_inherited")
    log_path.unlink(missing_ok=True)
    monkeypatch.setenv("LUMINA_LOG_PATH", str(log_path))
    monkeypatch.setenv("LUMINA_LOG_INIT_BY_PARENT", "1")

    result = logger_module.setup_file_logging(log_path=log_path)
    structured_logging.get_logger(__name__).info(
        "worker event",
        extra={"event": "worker_event"},
    )

    assert result == log_path
    assert os.environ["LUMINA_LOG_PATH"] == str(log_path.resolve())

    for handler in structured_logging.logging.getLogger("lumina").handlers:
        handler.flush()

    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert lines
    assert all('"event":"log_file_configured"' not in line for line in lines)
    assert any('"event":"worker_event"' in line for line in lines)
    _reset_file_logging(monkeypatch)
    log_path.unlink(missing_ok=True)


def test_setup_file_logging_with_user_env_path_emits_configured_event(monkeypatch) -> None:
    """A user-provided log path without the parent marker is still the bootstrapping process."""

    _reset_file_logging(monkeypatch)
    log_path = _temp_log_path("user_env")
    log_path.unlink(missing_ok=True)
    monkeypatch.setenv("LUMINA_LOG_PATH", str(log_path))

    result = logger_module.setup_file_logging()

    assert result == log_path
    assert os.environ["LUMINA_LOG_PATH"] == str(log_path.resolve())
    assert os.environ["LUMINA_LOG_INIT_BY_PARENT"] == "1"

    for handler in structured_logging.logging.getLogger("lumina").handlers:
        handler.flush()

    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert lines
    assert any('"event":"log_file_configured"' in line for line in lines)
    _reset_file_logging(monkeypatch)
    log_path.unlink(missing_ok=True)
