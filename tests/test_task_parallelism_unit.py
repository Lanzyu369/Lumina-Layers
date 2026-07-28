from __future__ import annotations

import logging

import pytest

import core.task_parallelism as task_parallelism
from core.task_parallelism import resolve_task_parallelism


def _set_cpu_count(monkeypatch: pytest.MonkeyPatch, count: int) -> None:
    monkeypatch.setattr(task_parallelism.os, "cpu_count", lambda: count)


def test_auto_parallelism_uses_outer_worker_fair_share(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_cpu_count(monkeypatch, 10)
    monkeypatch.delenv("LUMINA_RASTER_PARALLELISM", raising=False)
    monkeypatch.setenv("LUMINA_MAX_WORKERS", "2")

    resolved = resolve_task_parallelism(
        "raster",
        work_items=12,
        hard_max_workers=8,
    )

    assert resolved == 5


@pytest.mark.parametrize(
    ("requested", "outer_workers", "work_items", "hard_max", "expected"),
    [
        ("1", "1", 12, 8, 1),
        ("8", "1", 12, 8, 8),
        ("8", "2", 12, 8, 5),
        ("4", "1", 3, 8, 3),
        ("99", "1", 12, 4, 4),
    ],
)
def test_explicit_parallelism_respects_all_safety_bounds(
    monkeypatch: pytest.MonkeyPatch,
    requested: str,
    outer_workers: str,
    work_items: int,
    hard_max: int,
    expected: int,
) -> None:
    _set_cpu_count(monkeypatch, 10)
    monkeypatch.setenv("LUMINA_VECTOR_PARALLELISM", requested)
    monkeypatch.setenv("LUMINA_MAX_WORKERS", outer_workers)

    resolved = resolve_task_parallelism(
        "vector",
        work_items=work_items,
        hard_max_workers=hard_max,
    )

    assert resolved == expected


@pytest.mark.parametrize("work_items", [0, 1])
def test_small_workload_stays_serial(
    monkeypatch: pytest.MonkeyPatch,
    work_items: int,
) -> None:
    _set_cpu_count(monkeypatch, 10)
    monkeypatch.setenv("LUMINA_RASTER_PARALLELISM", "8")
    monkeypatch.setenv("LUMINA_MAX_WORKERS", "1")

    assert (
        resolve_task_parallelism(
            "raster",
            work_items=work_items,
            min_parallel_items=2,
        )
        == 1
    )


def test_invalid_value_warns_once_and_falls_back_to_auto(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _set_cpu_count(monkeypatch, 8)
    monkeypatch.setenv("LUMINA_VECTOR_PARALLELISM", "not-a-count")
    monkeypatch.setenv("LUMINA_MAX_WORKERS", "2")
    task_parallelism._WARNED_INVALID_VALUES.clear()
    caplog.set_level(logging.WARNING)
    target_logger = logging.getLogger("lumina.core.task_parallelism")
    target_logger.addHandler(caplog.handler)
    try:
        first = resolve_task_parallelism("vector", work_items=20)
        second = resolve_task_parallelism("vector", work_items=20)
    finally:
        target_logger.removeHandler(caplog.handler)

    assert first == second == 4
    records = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "task_parallelism_invalid"
    ]
    assert len(records) == 1
    assert records[0].env_var == "LUMINA_VECTOR_PARALLELISM"
    assert records[0].raw_value == "not-a-count"


@pytest.mark.parametrize("raw_value", ["0", "-3", " ", "AUTO", " auto "])
def test_non_positive_and_auto_spellings_use_auto_policy(
    monkeypatch: pytest.MonkeyPatch,
    raw_value: str,
) -> None:
    _set_cpu_count(monkeypatch, 8)
    monkeypatch.setenv("LUMINA_RASTER_PARALLELISM", raw_value)
    monkeypatch.setenv("LUMINA_MAX_WORKERS", "2")
    task_parallelism._WARNED_INVALID_VALUES.clear()

    assert resolve_task_parallelism("raster", work_items=20) == 4
