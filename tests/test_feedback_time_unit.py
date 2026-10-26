"""Unit tests for ``api.feedback_time`` — Beijing-time helpers.

验证 ``api.feedback_time`` 中的北京时间工具：三个公开函数的输出格式、
UTC+8 固定偏移与日历日期转换。
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from api.feedback_time import (
    BEIJING_TZ,
    format_received_cst,
    format_ticket_date,
    now_beijing,
)


def test_beijing_tz_is_utc_plus_8_fixed_offset() -> None:
    """BEIJING_TZ exposes a fixed +08:00 offset (no DST / tzdata logic)."""
    assert BEIJING_TZ.utcoffset(None) == timedelta(hours=8)


def test_now_beijing_returns_aware_datetime_in_beijing_tz() -> None:
    """now_beijing() returns a tz-aware datetime tagged with BEIJING_TZ."""
    dt = now_beijing()
    assert dt.tzinfo is BEIJING_TZ
    assert dt.utcoffset() == timedelta(hours=8)


def test_now_beijing_close_to_datetime_now_utc() -> None:
    """now_beijing() stays within 1 second of ``datetime.now(timezone.utc)``."""
    delta = now_beijing() - datetime.now(timezone.utc)
    assert abs(delta.total_seconds()) < 1.0


def test_format_ticket_date_aware_beijing() -> None:
    """An aware Beijing datetime formats to its own YYYYMMDD date."""
    dt = datetime(2026, 5, 11, 14, 3, 22, tzinfo=BEIJING_TZ)
    assert format_ticket_date(dt) == "20260511"


def test_format_ticket_date_aware_utc_converts_to_beijing() -> None:
    """A UTC datetime is converted to Beijing before extracting the date."""
    dt = datetime(2026, 5, 10, 23, 0, 0, tzinfo=timezone.utc)
    # 2026-05-10 23:00 UTC == 2026-05-11 07:00 Beijing
    assert format_ticket_date(dt) == "20260511"


def test_format_ticket_date_aware_utc_near_midnight_preserves_beijing_calendar() -> None:
    """Timezone normalization flips the calendar day when UTC is near midnight."""
    dt = datetime(2026, 5, 11, 16, 30, 0, tzinfo=timezone.utc)
    # 2026-05-11 16:30 UTC == 2026-05-12 00:30 Beijing
    assert format_ticket_date(dt) == "20260512"


def test_format_ticket_date_naive_treated_as_beijing() -> None:
    """Naive datetimes are tagged as Beijing wall-clock, not UTC."""
    dt = datetime(2026, 5, 11, 14, 0, 0)
    assert format_ticket_date(dt) == "20260511"


def test_format_received_cst_ends_with_plus_0800() -> None:
    """format_received_cst output always carries the ``+08:00`` offset suffix."""
    dt = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    assert format_received_cst(dt).endswith("+08:00")


def test_format_received_cst_iso_8601_shape() -> None:
    """Aware Beijing datetimes with microseconds produce canonical ISO 8601 text."""
    dt = datetime(2026, 5, 11, 14, 3, 22, 123456, tzinfo=BEIJING_TZ)
    out = format_received_cst(dt)
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}\+08:00$", out), out


def test_format_received_cst_converts_utc_input() -> None:
    """UTC input is normalized to Beijing before isoformat is produced."""
    dt = datetime(2026, 5, 10, 23, 0, 0, tzinfo=timezone.utc)
    assert format_received_cst(dt) == "2026-05-11T07:00:00+08:00"
