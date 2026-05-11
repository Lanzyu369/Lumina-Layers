"""Beijing time (UTC+8) utilities for the feedback / bug-report subsystem.

反馈与 Bug 报告子系统使用的北京时间（UTC+8）工具函数。

This module intentionally avoids :mod:`zoneinfo` / ``tzdata`` and hard-codes a
UTC+8 offset via :class:`datetime.timezone`. Beijing time has no DST, so a
fixed offset is sufficient and keeps behavior identical across platforms
(notably Windows, where ``tzdata`` may not be installed).

本模块刻意不依赖 ``zoneinfo`` / ``tzdata``，改用 :class:`datetime.timezone`
硬编码 UTC+8 偏移。北京时间没有夏令时，固定偏移即可，同时保证跨平台行为
一致（尤其是未安装 ``tzdata`` 的 Windows）。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

__all__ = [
    "BEIJING_TZ",
    "now_beijing",
    "format_ticket_date",
    "format_received_cst",
]


BEIJING_TZ: timezone = timezone(timedelta(hours=8))
"""Fixed UTC+8 timezone used for all feedback timestamps.

用于所有反馈时间戳的固定 UTC+8 时区。
"""


def _to_beijing(dt: datetime) -> datetime:
    """Normalize ``dt`` to :data:`BEIJING_TZ`.

    将 ``dt`` 归一化到 :data:`BEIJING_TZ` 时区。

    Naive datetimes are assumed to already represent Beijing wall-clock time
    and are only tagged with :data:`BEIJING_TZ`. Aware datetimes in any other
    timezone are converted via :meth:`datetime.astimezone`.

    不带时区信息的 datetime 视为已经表示北京本地时间，仅附加
    :data:`BEIJING_TZ` 时区；其他带时区的 datetime 通过
    :meth:`datetime.astimezone` 转换到北京时区。

    Args:
        dt: Input datetime (naive or aware).

    Returns:
        datetime: A timezone-aware datetime in :data:`BEIJING_TZ`.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=BEIJING_TZ)
    if dt.utcoffset() == BEIJING_TZ.utcoffset(dt):
        return dt
    return dt.astimezone(BEIJING_TZ)


def now_beijing() -> datetime:
    """Return the current time as a timezone-aware datetime in UTC+8.

    返回当前时间，带 UTC+8 时区信息。

    Returns:
        datetime: ``datetime.now(BEIJING_TZ)``.
    """
    return datetime.now(BEIJING_TZ)


def format_ticket_date(dt: datetime) -> str:
    """Format ``dt`` as a ``YYYYMMDD`` string in Beijing time.

    将 ``dt`` 格式化为北京时间下的 ``YYYYMMDD`` 字符串。

    Used to build the date component of bug-report ticket IDs such as
    ``LUM-YYYYMMDD-NNN``. The datetime is normalized to :data:`BEIJING_TZ`
    before formatting so the date always reflects the Beijing calendar day.

    用于构造 Bug 报告工单号 ``LUM-YYYYMMDD-NNN`` 的日期部分。格式化前会把
    datetime 归一化到 :data:`BEIJING_TZ`，确保得到的是北京日历日期。

    Args:
        dt: Datetime to format (naive datetimes are treated as Beijing-local).

    Returns:
        str: An 8-character ``YYYYMMDD`` string (e.g. ``"20260511"``).
    """
    return _to_beijing(dt).strftime("%Y%m%d")


def format_received_cst(dt: datetime) -> str:
    """Format ``dt`` as an ISO 8601 string with ``+08:00`` offset.

    将 ``dt`` 格式化为带 ``+08:00`` 偏移的 ISO 8601 字符串。

    The returned string is produced by :meth:`datetime.isoformat` on a
    datetime normalized to :data:`BEIJING_TZ`, so the trailing offset is
    always ``+08:00`` (e.g. ``"2026-05-11T14:03:22.123456+08:00"``).

    返回值由归一化到 :data:`BEIJING_TZ` 的 datetime 调用
    :meth:`datetime.isoformat` 生成，尾部偏移恒为 ``+08:00``
    （例如 ``"2026-05-11T14:03:22.123456+08:00"``）。

    Args:
        dt: Datetime to format (naive datetimes are treated as Beijing-local).

    Returns:
        str: ISO 8601 string with ``+08:00`` suffix.
    """
    return _to_beijing(dt).isoformat()
