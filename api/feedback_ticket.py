"""Bug-report ticket id generation.

Bug 报告工单号生成。

Ticket ids follow the format ``LUM-YYYYMMDD-NNN`` where:

* ``YYYYMMDD`` is the Beijing calendar date (UTC+8, no DST) that the ticket
  was received. The date component uses :func:`api.feedback_time.now_beijing`
  so no ``zoneinfo`` / ``tzdata`` dependency is introduced.
* ``NNN`` is a 1-indexed, zero-padded three-digit serial counted from the
  existing ticket directories under ``feedback/<YYYY-MM>/``. The counter
  advances to the next higher three-digit serial every call.

When the counter for a given day exceeds 999 the function degrades to the
format ``LUM-YYYYMMDD-<8-char-hex>``. This keeps the feedback pipeline open
in the extremely unlikely case of sustained high-frequency bursts, while
emitting a structured ERROR so operators notice.

工单号格式 ``LUM-YYYYMMDD-NNN``：日期来自北京时间（UTC+8，无夏令时），序号
从 1 开始，每日递增。当日序号超过 999 时降级为 ``LUM-YYYYMMDD-<8-char-hex>``
并记录 ERROR，确保反馈流程不因极端爆量而中断。
"""

from __future__ import annotations

import re
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Pattern

from api.feedback_time import format_ticket_date, now_beijing
from api.structured_logging import get_logger

__all__ = [
    "MAX_DAILY_SEQUENCE",
    "TICKET_ID_PATTERN",
    "generate_ticket_id",
    "month_partition",
    "ticket_dir_for",
]


log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


MAX_DAILY_SEQUENCE: int = 999
"""Maximum three-digit serial before falling back to the UUID tail.

每日可用的三位序号上限，超过后降级为 UUID 形式。
"""


_TICKET_SERIAL_PATTERN: Pattern[str] = re.compile(
    r"^LUM-(\d{8})-(\d{3})$",
)
"""Only canonical ``LUM-YYYYMMDD-NNN`` ids participate in the max-scan.

只有标准格式参与序号扫描；UUID 降级格式不会被回读。
"""

TICKET_ID_PATTERN: Pattern[str] = re.compile(
    r"^LUM-\d{8}-(?:\d{3}|[0-9a-f]{8})$",
)
"""Full acceptable shape for any issued ticket id, including the UUID tail.

所有合法工单号（含降级格式）的完整形状。
"""


# Module-level lock so two concurrent feedback submissions in the same process
# cannot collide on the same serial. FastAPI default deployment is single
# process; this lock is cheap and covers that case.
# 模块级锁：保护同一进程内并发生成序号。FastAPI 默认单进程，开销可忽略。
_LOCK = threading.Lock()


def month_partition(dt: datetime) -> str:
    """Return the ``YYYY-MM`` partition used for ticket directory layout.

    返回工单目录按月分层使用的 ``YYYY-MM`` 片段。

    Args:
        dt: Datetime to format. Naive datetimes are treated as Beijing-local
            by :func:`api.feedback_time.format_ticket_date`; the same
            normalization applies here via the shared ``_to_beijing`` helper
            called by :func:`format_ticket_date`.
            (待格式化的 datetime；naive 值按北京本地时间处理。)

    Returns:
        str: A ``YYYY-MM`` string, e.g. ``"2026-05"``.
    """
    yyyymmdd = format_ticket_date(dt)
    return f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}"


def ticket_dir_for(feedback_root: Path, ticket_id: str, dt: datetime) -> Path:
    """Return the directory path that should hold ``ticket_id``'s artifacts.

    返回应当承载 ``ticket_id`` 附件的目录路径。

    Args:
        feedback_root: Root directory under which ``YYYY-MM`` partitions live.
            (``YYYY-MM`` 分层之上的根目录)
        ticket_id: Ticket id as returned by :func:`generate_ticket_id`.
            (工单号)
        dt: The datetime whose Beijing-partition applies.
            (用于确定分层的 datetime)

    Returns:
        Path: ``feedback_root/<YYYY-MM>/<ticket_id>/``.
    """
    return feedback_root / month_partition(dt) / ticket_id


def _scan_existing_max_serial(
    feedback_root: Path,
    dt: datetime,
    yyyymmdd: str,
) -> int:
    """Return the highest serial used for ``yyyymmdd`` or ``0`` if none.

    扫描当日已使用的最大序号；无工单时返回 0。

    Reads directory names only — never opens any ticket files. Non-matching
    names (UUID-tail fallbacks, old flat JSON artifacts) are ignored.
    只读取目录名；UUID 降级格式和旧扁平 JSON 都不会参与扫描。
    """
    month_dir = feedback_root / month_partition(dt)
    if not month_dir.exists():
        return 0
    highest = 0
    try:
        for entry in month_dir.iterdir():
            if not entry.is_dir():
                continue
            match = _TICKET_SERIAL_PATTERN.match(entry.name)
            if match is None:
                continue
            if match.group(1) != yyyymmdd:
                continue
            try:
                serial = int(match.group(2))
            except ValueError:
                continue
            if serial > highest:
                highest = serial
    except OSError as exc:
        # Disk-level failure (permission denied, deleted mid-scan, etc.)
        # must not take down feedback submission. Log and treat as empty.
        # 磁盘层面异常不应阻塞反馈提交：记录后按无历史工单处理。
        log.warning(
            "Failed to scan existing feedback month directory.",
            extra={
                "event": "feedback_ticket_scan_failed",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "path": str(month_dir),
            },
        )
        return 0
    return highest


def generate_ticket_id(
    feedback_root: Path,
    now: datetime | None = None,
    *,
    reserve: bool = True,
) -> str:
    """Generate a new ticket id, advancing the daily serial.

    生成新工单号并递增当日序号。

    Args:
        feedback_root: Root of the ticket directory hierarchy.
            (工单目录层根路径)
        now: Optional datetime hook. Defaults to :func:`now_beijing`.
            (可选 datetime；默认取当前北京时间。)
        reserve: When True (default) the function atomically creates the
            new ticket directory inside the lock so concurrent callers get
            distinct ids without racing at the filesystem layer. Pass False
            only for read-only probe scenarios (tests / dry runs) where the
            caller does not actually want to claim the serial.
            (为 True 时在锁内原子地创建工单目录，避免并发冲突；仅在只读
            探测场景下使用 False。)

    Returns:
        str: A ticket id matching :data:`TICKET_ID_PATTERN`.
    """
    moment = now if now is not None else now_beijing()
    yyyymmdd = format_ticket_date(moment)

    with _LOCK:
        highest = _scan_existing_max_serial(feedback_root, moment, yyyymmdd)
        next_serial = highest + 1
        if next_serial > MAX_DAILY_SEQUENCE:
            fallback_suffix = uuid.uuid4().hex[:8]
            ticket_id = f"LUM-{yyyymmdd}-{fallback_suffix}"
            log.error(
                "Daily ticket serial exhausted; falling back to UUID tail.",
                extra={
                    "event": "feedback_ticket_sequence_exhausted",
                    "error_type": "TicketSequenceExhausted",
                    "error_message": (
                        f"More than {MAX_DAILY_SEQUENCE} tickets received on "
                        f"{yyyymmdd}; switched to UUID-tail format"
                    ),
                    "yyyymmdd": yyyymmdd,
                    "highest_serial": highest,
                    "fallback_suffix": fallback_suffix,
                },
            )
            if reserve:
                try:
                    ticket_dir_for(feedback_root, ticket_id, moment).mkdir(
                        parents=True, exist_ok=False,
                    )
                except FileExistsError:
                    # UUID collision is astronomically unlikely but keep the
                    # lock free of raised exceptions so the caller still
                    # receives a ticket id. Fall through — the assembler
                    # will detect the existing directory and bail out.
                    pass
            return ticket_id

        ticket_id = f"LUM-{yyyymmdd}-{next_serial:03d}"
        if reserve:
            ticket_dir_for(feedback_root, ticket_id, moment).mkdir(
                parents=True, exist_ok=False,
            )
        return ticket_id
