from __future__ import annotations

import logging
from pathlib import Path

import pytest

import core.task_parallelism as task_parallelism
from core.task_parallelism import resolve_task_parallelism
from core.system_capacity import EffectiveCpuCapacity
from core.task_parallelism_runtime import (
    OuterDemandPublisher,
    task_parallelism_runtime_scope,
)


def _set_cpu_count(monkeypatch: pytest.MonkeyPatch, count: int) -> None:
    monkeypatch.setattr(task_parallelism.os, "cpu_count", lambda: count)
    capacity = EffectiveCpuCapacity(
        host_cpu_count=count,
        affinity_cpu_count=None,
        cgroup_quota_cpu_count=None,
        apple_performance_cpu_count=None,
        effective_cpu_count=count,
        limiting_source="host_fallback",
    )
    monkeypatch.setattr(
        task_parallelism,
        "get_effective_cpu_capacity",
        lambda: capacity,
        raising=False,
    )


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


def test_tiny_work_units_stay_serial_even_with_multiple_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_cpu_count(monkeypatch, 10)
    monkeypatch.setenv("LUMINA_RASTER_PARALLELISM", "8")
    monkeypatch.setenv("LUMINA_MAX_WORKERS", "1")

    assert (
        resolve_task_parallelism(
            "raster",
            work_items=2,
            work_units=2,
            min_parallel_work_units=100,
        )
        == 1
    )


def test_available_memory_caps_worker_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gib = 1024**3
    _set_cpu_count(monkeypatch, 16)
    monkeypatch.setenv("LUMINA_RASTER_PARALLELISM", "8")
    monkeypatch.setenv("LUMINA_MAX_WORKERS", "1")

    resolved = resolve_task_parallelism(
        "raster",
        work_items=12,
        estimated_worker_bytes=512 * 1024**2,
        available_memory_bytes=2 * gib,
        hard_max_workers=8,
    )

    assert resolved == 2


def test_unknown_available_memory_fails_closed_to_serial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_cpu_count(monkeypatch, 16)
    monkeypatch.setenv("LUMINA_RASTER_PARALLELISM", "8")
    monkeypatch.setenv("LUMINA_MAX_WORKERS", "1")
    monkeypatch.setattr(
        task_parallelism,
        "_available_memory_bytes",
        lambda: None,
    )

    resolved = resolve_task_parallelism(
        "raster",
        work_items=12,
        estimated_worker_bytes=512 * 1024**2,
        hard_max_workers=8,
    )

    assert resolved == 1


def test_nested_parallel_worker_scope_forces_serial_and_restores_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_cpu_count(monkeypatch, 8)
    monkeypatch.setenv("LUMINA_VECTOR_PARALLELISM", "4")
    monkeypatch.setenv("LUMINA_MAX_WORKERS", "1")

    assert resolve_task_parallelism("vector", work_items=20) == 4
    with task_parallelism.task_parallelism_worker_scope():
        assert resolve_task_parallelism("vector", work_items=20) == 1
        with task_parallelism.task_parallelism_worker_scope():
            assert resolve_task_parallelism("vector", work_items=20) == 1
    assert resolve_task_parallelism("vector", work_items=20) == 4


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


@pytest.mark.parametrize(
    ("raw_value", "warns"),
    [
        ("0", True),
        ("-3", True),
        (" ", True),
        ("AUTO", False),
        (" auto ", False),
    ],
)
def test_non_positive_whitespace_and_auto_spellings_use_auto_policy(
    monkeypatch: pytest.MonkeyPatch,
    raw_value: str,
    warns: bool,
) -> None:
    _set_cpu_count(monkeypatch, 8)
    monkeypatch.setenv("LUMINA_RASTER_PARALLELISM", raw_value)
    monkeypatch.setenv("LUMINA_MAX_WORKERS", "2")
    task_parallelism._WARNED_INVALID_VALUES.clear()
    observed_warnings: list[tuple[str, str]] = []
    monkeypatch.setattr(
        task_parallelism,
        "_warn_invalid_once",
        lambda env_var, value: observed_warnings.append((env_var, value)),
    )

    assert resolve_task_parallelism("raster", work_items=20) == 4
    assert bool(observed_warnings) is warns


def test_plan_divides_cpu_and_memory_by_live_outer_demand(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LUMINA_RASTER_PARALLELISM", "8")

    plan = task_parallelism.resolve_task_parallelism_plan(
        "raster",
        work_items=12,
        hard_max_workers=8,
        estimated_worker_bytes=512 * 1024**2,
        available_memory_bytes=5 * 1024**3,
        effective_cpu_capacity=8,
        outer_demand=2,
    )

    assert plan.workers == 4
    assert plan.requested_ceiling == 8
    assert plan.effective_cpu_capacity == 8
    assert plan.cpu_fair_share_ceiling == 4
    assert plan.memory_ceiling == 4
    assert plan.outer_demand == 2
    assert plan.limiting_reason == "cpu_fair_share"
    assert plan.demand_snapshot_fallback is False


def test_work_unit_threshold_preserves_existing_parallel_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LUMINA_VECTOR_PARALLELISM", "4")

    plan = task_parallelism.resolve_task_parallelism_plan(
        "vector",
        work_items=20,
        work_units=17,
        min_parallel_work_units=8,
        hard_max_workers=4,
        effective_cpu_capacity=8,
        outer_demand=1,
    )

    assert plan.work_unit_ceiling == 4
    assert plan.workers == 4
    assert plan.limiting_reason == "requested"


@pytest.mark.parametrize(
    ("outer_demand", "expected_workers"),
    [(4, 1), (2, 2), (1, 4)],
)
def test_plan_selects_one_two_and_four_worker_tiers(
    monkeypatch: pytest.MonkeyPatch,
    outer_demand: int,
    expected_workers: int,
) -> None:
    monkeypatch.delenv("LUMINA_VECTOR_PARALLELISM", raising=False)

    plan = task_parallelism.resolve_task_parallelism_plan(
        "vector",
        work_items=20,
        hard_max_workers=4,
        effective_cpu_capacity=4,
        outer_demand=outer_demand,
    )

    assert plan.workers == expected_workers


def test_integer_api_returns_plan_workers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LUMINA_VECTOR_PARALLELISM", "4")
    kwargs = {
        "work_items": 20,
        "hard_max_workers": 4,
        "effective_cpu_capacity": 4,
        "outer_demand": 2,
    }

    plan = task_parallelism.resolve_task_parallelism_plan("vector", **kwargs)

    assert resolve_task_parallelism("vector", **kwargs) == plan.workers == 2


def test_installed_snapshot_supplies_current_outer_demand(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("LUMINA_VECTOR_PARALLELISM", raising=False)
    monkeypatch.setenv("LUMINA_MAX_WORKERS", "4")
    publisher = OuterDemandPublisher(max_workers=4, parent_dir=tmp_path)
    publisher.increment()
    publisher.increment()
    try:
        with task_parallelism_runtime_scope(publisher.snapshot_path):
            plan = task_parallelism.resolve_task_parallelism_plan(
                "vector",
                work_items=20,
                hard_max_workers=8,
                effective_cpu_capacity=8,
            )
    finally:
        publisher.cleanup()

    assert plan.outer_demand == 2
    assert plan.cpu_fair_share_ceiling == 4
    assert plan.workers == 4
    assert plan.demand_snapshot_fallback is False


def test_missing_installed_snapshot_uses_configured_outer_fair_share(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("LUMINA_RASTER_PARALLELISM", raising=False)
    monkeypatch.setenv("LUMINA_MAX_WORKERS", "3")

    with task_parallelism_runtime_scope(tmp_path / "missing.json"):
        plan = task_parallelism.resolve_task_parallelism_plan(
            "raster",
            work_items=20,
            hard_max_workers=8,
            effective_cpu_capacity=12,
        )

    assert plan.outer_demand == 3
    assert plan.cpu_fair_share_ceiling == 4
    assert plan.workers == 4
    assert plan.demand_snapshot_fallback is True


def test_nested_plan_has_stable_serial_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LUMINA_VECTOR_PARALLELISM", "4")

    with task_parallelism.task_parallelism_worker_scope():
        plan = task_parallelism.resolve_task_parallelism_plan(
            "vector",
            work_items=20,
            hard_max_workers=4,
            effective_cpu_capacity=8,
            outer_demand=1,
        )

    assert plan.workers == 1
    assert plan.limiting_reason == "nested_worker"


def test_unknown_memory_plan_is_serial_with_memory_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LUMINA_RASTER_PARALLELISM", "4")
    monkeypatch.setattr(
        task_parallelism,
        "_available_memory_bytes",
        lambda: None,
    )

    plan = task_parallelism.resolve_task_parallelism_plan(
        "raster",
        work_items=20,
        hard_max_workers=4,
        estimated_worker_bytes=256 * 1024**2,
        effective_cpu_capacity=8,
        outer_demand=1,
    )

    assert plan.workers == 1
    assert plan.memory_ceiling == 1
    assert plan.available_memory_bytes is None
    assert plan.limiting_reason == "memory"


@pytest.mark.parametrize(
    ("kwargs", "expected_reason"),
    [
        ({"work_items": 1, "min_parallel_items": 2}, "insufficient_items"),
        (
            {
                "work_items": 10,
                "work_units": 7,
                "min_parallel_work_units": 8,
            },
            "insufficient_work_units",
        ),
    ],
)
def test_early_serial_plans_have_stable_reasons(
    monkeypatch: pytest.MonkeyPatch,
    kwargs: dict[str, int],
    expected_reason: str,
) -> None:
    monkeypatch.setenv("LUMINA_VECTOR_PARALLELISM", "4")

    plan = task_parallelism.resolve_task_parallelism_plan(
        "vector",
        hard_max_workers=4,
        effective_cpu_capacity=8,
        outer_demand=1,
        **kwargs,
    )

    assert plan.workers == 1
    assert plan.limiting_reason == expected_reason
