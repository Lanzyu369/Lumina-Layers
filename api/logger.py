"""Lumina Studio file logger.
Lumina Studio 文件日志模块。

Selects the shared JSON Lines log file path for API and worker processes.
为 API 与 worker 进程选择共享的 JSON Lines 日志文件路径。
"""

import os
import sys
import tempfile
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_logging_initialized = False


def setup_file_logging(log_path=None) -> Path | None:
    """Configure a shared structured log file.
    配置共享结构化日志文件。

    Safe to call multiple times: only the first successful call initializes.
    多次调用是安全的：只有第一次成功调用会初始化。

    If log_path is provided, append to that existing file path instead of
    creating a new timestamped file. Returns the log file path, or None if
    already initialized or if no candidate can be prepared.
    如果提供 log_path，则复用该路径追加写入；返回日志路径，若已初始化或无可用候选则返回 None。
    """
    global _logging_initialized

    if _logging_initialized:
        return None

    selected_path: Path | None = None
    for candidate_path in _resolve_log_candidates(Path(log_path) if log_path is not None else None):
        try:
            _prepare_log_path(candidate_path)
            selected_path = candidate_path
            break
        except OSError as exc:
            _emit_log_setup_warning(candidate_path, exc)

    if selected_path is None:
        _logging_initialized = False
        return None

    resolved_path = selected_path.resolve()
    os.environ["LUMINA_LOG_PATH"] = str(resolved_path)
    _logging_initialized = True

    from api.structured_logging import configure_structured_logging, get_logger

    configure_structured_logging()
    get_logger(__name__).info(
        "Log file configured",
        extra={"event": "log_file_configured", "path": str(resolved_path)},
    )
    return selected_path


def _resolve_log_candidates(explicit_path: Path | None) -> list[Path]:
    """Return candidate log paths in preference order.
    返回按优先级排序的日志路径候选列表。

    Args:
        explicit_path: Preferred path supplied by the caller. (调用方提供的优先路径)

    Returns:
        list[Path]: Candidate log paths. (候选日志路径列表)
    """

    filename = explicit_path.name if explicit_path is not None else f"lumina_{time.strftime('%Y%m%d_%H%M%S')}.log"
    candidates: list[Path] = []

    if explicit_path is not None:
        candidates.append(explicit_path)
    else:
        env_dir = os.environ.get("LUMINA_LOG_DIR")
        if env_dir:
            candidates.append(Path(env_dir) / filename)
        candidates.append(_REPO_ROOT / "logs" / filename)

    candidates.append(Path(tempfile.gettempdir()) / "lumina-logs" / filename)

    deduped: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key not in seen:
            seen.add(key)
            deduped.append(candidate)
    return deduped


def _prepare_log_path(log_path: Path) -> None:
    """Create parent directories and verify append access.
    创建父目录并验证追加写入权限。

    Args:
        log_path: Candidate log path. (候选日志路径)
    """

    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8"):
        pass


def _emit_log_setup_warning(log_path: Path, exc: OSError) -> None:
    """Emit a stderr warning when one log target cannot be opened.
    当某个日志目标无法打开时向 stderr 输出警告。

    Args:
        log_path: Failing log path. (失败的日志路径)
        exc: Raised OS error. (触发的系统错误)
    """

    try:
        sys.__stderr__.write(
            f"[LOG][WARNING] File logging disabled for '{log_path}': {type(exc).__name__}: {exc}\n"
        )
        sys.__stderr__.flush()
    except Exception:
        pass
