"""Unit tests for ``api.feedback_ticket`` — ticket id generation.

验证 ``api.feedback_ticket``：格式、当日序号递增、跨日重置、并发安全、
序号耗尽降级为 UUID 尾缀。
"""

from __future__ import annotations

import re
import threading
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from api.feedback_ticket import (
    MAX_DAILY_SEQUENCE,
    TICKET_ID_PATTERN,
    generate_ticket_id,
    month_partition,
    ticket_dir_for,
)
from api.feedback_time import BEIJING_TZ


def _beijing(year: int, month: int, day: int, hour: int = 12) -> datetime:
    return datetime(year, month, day, hour, 0, 0, tzinfo=BEIJING_TZ)


def test_generate_first_ticket_of_day_is_serial_001(tmp_path: Path) -> None:
    """When the month directory is missing the next id is always 001."""
    dt = _beijing(2026, 5, 11)
    ticket_id = generate_ticket_id(tmp_path, now=dt)
    assert ticket_id == "LUM-20260511-001"
    assert TICKET_ID_PATTERN.match(ticket_id)


def test_serial_advances_when_existing_tickets_present(tmp_path: Path) -> None:
    """Pre-existing ``002`` directory produces ``003`` next."""
    dt = _beijing(2026, 5, 11)
    month_dir = tmp_path / "2026-05"
    month_dir.mkdir(parents=True)
    (month_dir / "LUM-20260511-001").mkdir()
    (month_dir / "LUM-20260511-002").mkdir()

    ticket_id = generate_ticket_id(tmp_path, now=dt)

    assert ticket_id == "LUM-20260511-003"


def test_serial_resets_on_new_calendar_day(tmp_path: Path) -> None:
    """Yesterday's ``005`` does not inflate today's counter back to ``006``."""
    yesterday = _beijing(2026, 5, 10)
    month_dir = tmp_path / month_partition(yesterday)
    month_dir.mkdir(parents=True)
    for serial in range(1, 6):
        (month_dir / f"LUM-20260510-{serial:03d}").mkdir()

    today = _beijing(2026, 5, 11)
    ticket_id = generate_ticket_id(tmp_path, now=today)

    assert ticket_id == "LUM-20260511-001"


def test_month_partition_honours_beijing_day_flip(tmp_path: Path) -> None:
    """A UTC datetime near midnight is normalized to the Beijing calendar day.

    Test both the partition helper and the full id: UTC 16:30 equals Beijing
    00:30 the following day, so the id and the month directory must both
    reflect the next day.
    """
    from datetime import timezone

    dt = datetime(2026, 5, 11, 16, 30, 0, tzinfo=timezone.utc)
    # Beijing wall clock for that moment is 2026-05-12 00:30.
    assert month_partition(dt) == "2026-05"
    ticket_id = generate_ticket_id(tmp_path, now=dt)
    assert ticket_id == "LUM-20260512-001"


def test_unrecognized_directory_names_are_ignored(tmp_path: Path) -> None:
    """UUID-tail fallbacks and legacy flat files do not inflate the serial."""
    dt = _beijing(2026, 5, 11)
    month_dir = tmp_path / "2026-05"
    month_dir.mkdir(parents=True)
    (month_dir / "LUM-20260511-001").mkdir()
    # Simulated UUID-tail ticket from a previous overflow event.
    (month_dir / "LUM-20260511-deadbeef").mkdir()
    # Legacy flat JSON style filename from the old dump path.
    (month_dir / "20260511T120000Z_session_abcdef.json").touch()

    ticket_id = generate_ticket_id(tmp_path, now=dt)

    # Expect 002, not 003 or the UUID collision.
    assert ticket_id == "LUM-20260511-002"


def test_ticket_dir_for_uses_month_partition(tmp_path: Path) -> None:
    """Ticket directory lives under ``feedback_root/<YYYY-MM>/<ticket_id>/``."""
    dt = _beijing(2026, 5, 11)
    ticket_id = "LUM-20260511-042"
    expected = tmp_path / "2026-05" / "LUM-20260511-042"
    assert ticket_dir_for(tmp_path, ticket_id, dt) == expected


def test_sequence_exhaustion_falls_back_to_uuid_suffix(tmp_path: Path) -> None:
    """More than ``MAX_DAILY_SEQUENCE`` tickets trigger the UUID tail path."""
    dt = _beijing(2026, 5, 11)
    month_dir = tmp_path / "2026-05"
    month_dir.mkdir(parents=True)
    (month_dir / f"LUM-20260511-{MAX_DAILY_SEQUENCE:03d}").mkdir()

    ticket_id = generate_ticket_id(tmp_path, now=dt)

    assert ticket_id.startswith("LUM-20260511-")
    suffix = ticket_id.split("-")[-1]
    # Not a three-digit serial; expect 8-char lowercase hex fallback.
    assert not re.match(r"^\d{3}$", suffix)
    assert re.match(r"^[0-9a-f]{8}$", suffix)
    assert TICKET_ID_PATTERN.match(ticket_id)


def test_generate_ticket_id_is_thread_safe(tmp_path: Path) -> None:
    """Running 30 concurrent generators yields 30 unique serials.

    The module-level lock plus atomic directory reservation ensure no
    duplicate ticket id is returned even when submissions race inside a
    single FastAPI process.
    """
    dt = _beijing(2026, 5, 11)
    results: list[str] = []
    results_lock = threading.Lock()

    def worker() -> None:
        ticket_id = generate_ticket_id(tmp_path, now=dt)
        with results_lock:
            results.append(ticket_id)

    threads = [threading.Thread(target=worker) for _ in range(30)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 30
    assert len(set(results)) == 30
    # All results should follow the canonical three-digit format since we
    # stayed well below MAX_DAILY_SEQUENCE.
    for ticket_id in results:
        assert TICKET_ID_PATTERN.match(ticket_id)


def test_ticket_format_matches_pattern(tmp_path: Path) -> None:
    """A freshly generated id conforms to :data:`TICKET_ID_PATTERN`."""
    dt = _beijing(2026, 5, 11)
    ticket_id = generate_ticket_id(tmp_path, now=dt)
    assert TICKET_ID_PATTERN.match(ticket_id)


def test_naive_datetime_treated_as_beijing(tmp_path: Path) -> None:
    """Naive datetimes do not cause day drift."""
    naive = datetime(2026, 5, 11, 9, 0, 0)  # no tz
    ticket_id = generate_ticket_id(tmp_path, now=naive)
    assert ticket_id == "LUM-20260511-001"


def test_scan_tolerates_unreadable_month_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An OSError from iterdir is swallowed and we start from serial 1.

    Simulate a permission issue on the month directory. The function must
    still return a valid ticket id rather than propagating the OSError.
    """
    import api.feedback_ticket as feedback_ticket

    dt = _beijing(2026, 5, 11)
    real_iterdir = Path.iterdir

    def boom_iterdir(self: Path):  # type: ignore[override]
        if self == tmp_path / "2026-05":
            raise OSError("simulated permission denied")
        return real_iterdir(self)

    (tmp_path / "2026-05").mkdir(parents=True)
    monkeypatch.setattr(feedback_ticket.Path, "iterdir", boom_iterdir)

    ticket_id = generate_ticket_id(tmp_path, now=dt)
    assert ticket_id == "LUM-20260511-001"


def test_generate_multiple_without_materializing_returns_same_serial(
    tmp_path: Path,
) -> None:
    """Back-to-back calls with ``reserve=False`` stay at serial 001.

    Read-only probe path: callers that only want to preview the next id
    without mutating the filesystem pass ``reserve=False``.
    """
    dt = _beijing(2026, 5, 11)
    first = generate_ticket_id(tmp_path, now=dt, reserve=False)
    second = generate_ticket_id(tmp_path, now=dt, reserve=False)
    assert first == second == "LUM-20260511-001"


def test_generate_advances_after_caller_materializes_directory(
    tmp_path: Path,
) -> None:
    """Default reservation path advances the serial automatically."""
    dt = _beijing(2026, 5, 11)
    first = generate_ticket_id(tmp_path, now=dt)
    second = generate_ticket_id(tmp_path, now=dt)
    assert first == "LUM-20260511-001"
    assert second == "LUM-20260511-002"


def test_datetime_offset_input_normalized_correctly(tmp_path: Path) -> None:
    """Accepts an aware datetime with a non-Beijing offset without drift."""
    from datetime import timezone

    # 2026-05-11 04:30 New York (EDT, -04:00) == 2026-05-11 16:30 Beijing
    eastern = timezone(timedelta(hours=-4))
    dt = datetime(2026, 5, 11, 4, 30, 0, tzinfo=eastern)
    ticket_id = generate_ticket_id(tmp_path, now=dt)
    assert ticket_id == "LUM-20260511-001"
