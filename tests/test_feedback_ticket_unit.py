"""Unit tests for random monthly bug-report ticket ids.

验证 Bug 报告工单号使用北京时间月份与随机十六进制后缀，并通过原子目录
预留处理本机碰撞。
"""

from __future__ import annotations

import itertools
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from api.feedback_ticket import (
    TICKET_ID_PATTERN,
    generate_ticket_id,
    month_partition,
    ticket_dir_for,
)
from api.feedback_time import BEIJING_TZ


def _beijing(year: int, month: int, day: int, hour: int = 12) -> datetime:
    return datetime(year, month, day, hour, 0, 0, tzinfo=BEIJING_TZ)


def test_generate_ticket_uses_beijing_month_and_random_hex(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("api.feedback_ticket.secrets.token_hex", lambda _: "deadbeef")

    moment = _beijing(2026, 5, 11)
    ticket_id = generate_ticket_id(tmp_path, now=moment)

    assert ticket_id == "LUM-202605-deadbeef"
    assert TICKET_ID_PATTERN.fullmatch(ticket_id)
    assert (tmp_path / "2026-05" / ticket_id).is_dir()


@pytest.mark.parametrize(
    "ticket_id",
    [
        "LUM-20260511-001",
        "LUM-202605-DEADBEEF",
        "LUM-202605-deadbee",
        "LUM-202605-deadbeef0",
        "LUM-٢٠٢٦٠٥-deadbeef",
        "LUM-202613-deadbeef/child",
    ],
)
def test_new_ticket_pattern_rejects_noncanonical_ids(ticket_id: str) -> None:
    assert TICKET_ID_PATTERN.fullmatch(ticket_id) is None


def test_independent_devices_do_not_reuse_local_serial(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two empty device roots at the same instant receive distinct ids."""
    suffixes = iter(("0123abcd", "89abcdef"))
    monkeypatch.setattr(
        "api.feedback_ticket.secrets.token_hex",
        lambda _: next(suffixes),
    )
    moment = _beijing(2026, 8, 12)

    first = generate_ticket_id(tmp_path / "device-a", now=moment)
    second = generate_ticket_id(tmp_path / "device-b", now=moment)

    assert first == "LUM-202608-0123abcd"
    assert second == "LUM-202608-89abcdef"
    assert first != second


def test_local_random_collision_retries_with_atomic_reservation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    moment = _beijing(2026, 5, 11)
    collision_id = "LUM-202605-deadbeef"
    (tmp_path / "2026-05" / collision_id).mkdir(parents=True)
    suffixes = iter(("deadbeef", "c0ffee00"))
    monkeypatch.setattr(
        "api.feedback_ticket.secrets.token_hex",
        lambda _: next(suffixes),
    )

    ticket_id = generate_ticket_id(tmp_path, now=moment)

    assert ticket_id == "LUM-202605-c0ffee00"
    assert (tmp_path / "2026-05" / ticket_id).is_dir()


def test_collision_retry_budget_is_bounded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    moment = _beijing(2026, 5, 11)
    collision_id = "LUM-202605-deadbeef"
    (tmp_path / "2026-05" / collision_id).mkdir(parents=True)
    monkeypatch.setattr("api.feedback_ticket.secrets.token_hex", lambda _: "deadbeef")

    with pytest.raises(FileExistsError, match="16 attempts"):
        generate_ticket_id(tmp_path, now=moment)


def test_generate_ticket_id_is_thread_safe(tmp_path: Path) -> None:
    moment = _beijing(2026, 5, 11)
    results: list[str] = []
    results_lock = threading.Lock()

    def worker() -> None:
        ticket_id = generate_ticket_id(tmp_path, now=moment)
        with results_lock:
            results.append(ticket_id)

    threads = [threading.Thread(target=worker) for _ in range(30)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(results) == 30
    assert len(set(results)) == 30
    assert all(TICKET_ID_PATTERN.fullmatch(ticket_id) for ticket_id in results)


def test_reserve_false_does_not_materialize_ticket_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suffixes = itertools.cycle(("0123abcd", "89abcdef"))
    monkeypatch.setattr(
        "api.feedback_ticket.secrets.token_hex",
        lambda _: next(suffixes),
    )
    moment = _beijing(2026, 5, 11)

    first = generate_ticket_id(tmp_path, now=moment, reserve=False)
    second = generate_ticket_id(tmp_path, now=moment, reserve=False)

    assert first == "LUM-202605-0123abcd"
    assert second == "LUM-202605-89abcdef"
    assert list(tmp_path.iterdir()) == []


def test_month_partition_honours_beijing_month_flip() -> None:
    utc_moment = datetime(2026, 5, 31, 16, 30, tzinfo=timezone.utc)

    assert month_partition(utc_moment) == "2026-06"


def test_naive_datetime_is_treated_as_beijing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("api.feedback_ticket.secrets.token_hex", lambda _: "0123abcd")

    ticket_id = generate_ticket_id(
        tmp_path,
        now=datetime(2026, 5, 11, 9, 0, 0),
    )

    assert ticket_id == "LUM-202605-0123abcd"


def test_datetime_offset_input_is_normalized_to_beijing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("api.feedback_ticket.secrets.token_hex", lambda _: "0123abcd")
    eastern = timezone(timedelta(hours=-4))
    moment = datetime(2026, 5, 31, 12, 30, tzinfo=eastern)

    ticket_id = generate_ticket_id(tmp_path, now=moment)

    assert ticket_id == "LUM-202606-0123abcd"


def test_ticket_dir_for_keeps_month_partition(tmp_path: Path) -> None:
    moment = _beijing(2026, 5, 11)
    ticket_id = "LUM-202605-0123abcd"

    assert ticket_dir_for(tmp_path, ticket_id, moment) == (
        tmp_path / "2026-05" / ticket_id
    )
