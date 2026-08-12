"""Bug-report ticket id generation.

Bug 报告工单号生成。

Ticket ids follow ``LUM-YYYYMM-xxxxxxxx``. ``YYYYMM`` is the Beijing
calendar month and ``xxxxxxxx`` is an eight-character lowercase hexadecimal
token generated independently on every device. Reserving an id atomically
creates ``feedback/<YYYY-MM>/<ticket_id>/`` and retries local collisions.

工单号格式为 ``LUM-YYYYMM-xxxxxxxx``。月份使用北京时间，八位小写十六进制
随机尾缀由每台设备独立生成。预留工单号时会原子创建对应目录，并在本机碰撞时
重试。
"""

from __future__ import annotations

import re
import secrets
from datetime import datetime
from pathlib import Path
from typing import Pattern

from api.feedback_time import format_ticket_date, now_beijing

__all__ = [
    "TICKET_ID_PATTERN",
    "generate_ticket_id",
    "month_partition",
    "ticket_dir_for",
]


_MAX_RESERVATION_ATTEMPTS = 16

TICKET_ID_PATTERN: Pattern[str] = re.compile(r"^LUM-[0-9]{6}-[0-9a-f]{8}$")
"""Full shape of newly issued random monthly ticket ids.

新生成的随机月度工单号完整格式。
"""


def month_partition(dt: datetime) -> str:
    """Return the ``YYYY-MM`` partition used for ticket directory layout.

    返回工单目录按月分层使用的 ``YYYY-MM`` 片段。

    Args:
        dt: Datetime normalized to Beijing time by the shared formatter.
            (由共享格式化器转换为北京时间的 datetime。)

    Returns:
        str: A ``YYYY-MM`` string, for example ``"2026-05"``.
    """
    yyyymmdd = format_ticket_date(dt)
    return f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}"


def ticket_dir_for(feedback_root: Path, ticket_id: str, dt: datetime) -> Path:
    """Return the directory path that should hold ``ticket_id`` artifacts.

    返回应当承载 ``ticket_id`` 附件的目录路径。

    Args:
        feedback_root: Root directory containing monthly partitions.
            (包含按月分层目录的反馈根目录。)
        ticket_id: Ticket id returned by :func:`generate_ticket_id`.
            (由 :func:`generate_ticket_id` 返回的工单号。)
        dt: Datetime used to select the Beijing month partition.
            (用于确定北京时间月份分层的 datetime。)

    Returns:
        Path: ``feedback_root/<YYYY-MM>/<ticket_id>/``.
    """
    return feedback_root / month_partition(dt) / ticket_id


def generate_ticket_id(
    feedback_root: Path,
    now: datetime | None = None,
    *,
    reserve: bool = True,
) -> str:
    """Generate a random monthly ticket id and optionally reserve it.

    生成随机月度工单号，并按需原子预留对应目录。

    Args:
        feedback_root: Root of the ticket directory hierarchy.
            (工单目录层级的根路径。)
        now: Optional datetime hook; defaults to Beijing current time.
            (可选 datetime；默认取当前北京时间。)
        reserve: Atomically create the ticket directory when true. When false,
            return one random id without touching the filesystem.
            (为 true 时原子创建工单目录；为 false 时只返回随机号，不写磁盘。)

    Returns:
        str: A ticket id matching :data:`TICKET_ID_PATTERN`.

    Raises:
        FileExistsError: All 16 local reservation attempts collided.
            (连续 16 次本地目录预留均发生碰撞。)
    """
    moment = now if now is not None else now_beijing()
    yyyymm = format_ticket_date(moment)[:6]

    if not reserve:
        return f"LUM-{yyyymm}-{secrets.token_hex(4)}"

    last_ticket_dir: Path | None = None
    for _attempt in range(_MAX_RESERVATION_ATTEMPTS):
        ticket_id = f"LUM-{yyyymm}-{secrets.token_hex(4)}"
        ticket_dir = ticket_dir_for(feedback_root, ticket_id, moment)
        last_ticket_dir = ticket_dir
        try:
            ticket_dir.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            continue
        return ticket_id

    raise FileExistsError(
        "Could not reserve a unique bug-report ticket id after "
        f"{_MAX_RESERVATION_ATTEMPTS} attempts: {last_ticket_dir}"
    )
