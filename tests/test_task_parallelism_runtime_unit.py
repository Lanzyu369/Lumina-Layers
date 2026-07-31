"""Unit coverage for cross-process task-parallelism runtime state."""

from __future__ import annotations

import json
from pathlib import Path
import threading

import pytest


def _runtime_module():
    from core import task_parallelism_runtime

    return task_parallelism_runtime


def test_publisher_round_trip_tracks_outstanding_tasks(
    tmp_path: Path,
) -> None:
    runtime = _runtime_module()
    publisher = runtime.OuterDemandPublisher(
        max_workers=4,
        parent_dir=tmp_path,
    )
    try:
        initial = runtime.read_outer_demand(
            publisher.snapshot_path,
            fallback_outer_workers=4,
        )
        assert initial.outer_demand == 1
        assert initial.generation == 0
        assert initial.snapshot_fallback is False

        publisher.increment()
        publisher.increment()
        state = runtime.read_outer_demand(
            publisher.snapshot_path,
            fallback_outer_workers=4,
        )
        assert state.outer_demand == 2
        assert state.outer_max_workers == 4
        assert state.generation == 2
        assert state.snapshot_fallback is False

        publisher.decrement()
        assert runtime.read_outer_demand(
            publisher.snapshot_path,
            fallback_outer_workers=4,
        ).outer_demand == 1
        assert publisher.outstanding == 1
    finally:
        publisher.cleanup()


def test_queued_demand_is_published_but_clamped_to_outer_capacity(
    tmp_path: Path,
) -> None:
    runtime = _runtime_module()
    publisher = runtime.OuterDemandPublisher(
        max_workers=2,
        parent_dir=tmp_path,
    )
    try:
        for _index in range(5):
            publisher.increment()

        payload = json.loads(
            publisher.snapshot_path.read_text(encoding="utf-8")
        )
        state = runtime.read_outer_demand(
            publisher.snapshot_path,
            fallback_outer_workers=2,
        )

        assert payload["outstanding"] == 5
        assert state.outer_demand == 2
        assert state.outer_max_workers == 2
        assert state.snapshot_fallback is False
    finally:
        publisher.cleanup()


def test_snapshot_contains_only_bounded_control_fields(tmp_path: Path) -> None:
    runtime = _runtime_module()
    publisher = runtime.OuterDemandPublisher(
        max_workers=3,
        parent_dir=tmp_path,
    )
    try:
        payload = json.loads(
            publisher.snapshot_path.read_text(encoding="utf-8")
        )
        assert set(payload) == {
            "version",
            "generation",
            "outstanding",
            "outer_max_workers",
            "updated_monotonic_ns",
        }
        assert all(
            isinstance(value, int) and not isinstance(value, bool)
            for value in payload.values()
        )
    finally:
        publisher.cleanup()


def test_missing_snapshot_uses_configured_fair_share(
    tmp_path: Path,
) -> None:
    runtime = _runtime_module()

    state = runtime.read_outer_demand(
        tmp_path / "missing.json",
        fallback_outer_workers=3,
    )

    assert state.outer_demand == 3
    assert state.outer_max_workers == 3
    assert state.generation == 0
    assert state.snapshot_fallback is True


@pytest.mark.parametrize(
    "payload",
    [
        "not-json",
        "[]",
        '{"version": 99, "generation": 1, "outstanding": 1, '
        '"outer_max_workers": 2, "updated_monotonic_ns": 1}',
        '{"version": 1, "generation": -1, "outstanding": 1, '
        '"outer_max_workers": 2, "updated_monotonic_ns": 1}',
        '{"version": 1, "generation": 1, "outstanding": -1, '
        '"outer_max_workers": 2, "updated_monotonic_ns": 1}',
        '{"version": 1, "generation": 1, "outstanding": 1000001, '
        '"outer_max_workers": 2, "updated_monotonic_ns": 1}',
        '{"version": 1, "generation": 1, "outstanding": 1, '
        '"outer_max_workers": 0, "updated_monotonic_ns": 1}',
        '{"version": 1, "generation": 1, "outstanding": 1, '
        '"outer_max_workers": 2, "updated_monotonic_ns": -1}',
        '{"version": true, "generation": 1, "outstanding": 1, '
        '"outer_max_workers": 2, "updated_monotonic_ns": 1}',
    ],
)
def test_invalid_snapshot_fails_closed_to_configured_outer_workers(
    tmp_path: Path,
    payload: str,
) -> None:
    runtime = _runtime_module()
    snapshot_path = tmp_path / "demand.json"
    snapshot_path.write_text(payload, encoding="utf-8")

    state = runtime.read_outer_demand(
        snapshot_path,
        fallback_outer_workers=4,
    )

    assert state.outer_demand == 4
    assert state.outer_max_workers == 4
    assert state.snapshot_fallback is True


def test_concurrent_atomic_updates_never_raise_or_return_invalid_demand(
    tmp_path: Path,
) -> None:
    runtime = _runtime_module()
    publisher = runtime.OuterDemandPublisher(
        max_workers=4,
        parent_dir=tmp_path,
    )
    start = threading.Event()
    failures: list[BaseException] = []

    def update_repeatedly() -> None:
        try:
            start.wait(timeout=1)
            for _index in range(100):
                publisher.increment()
                publisher.decrement()
        except BaseException as exc:  # pragma: no cover - asserted below
            failures.append(exc)

    thread = threading.Thread(target=update_repeatedly)
    thread.start()
    start.set()
    try:
        for _index in range(200):
            state = runtime.read_outer_demand(
                publisher.snapshot_path,
                fallback_outer_workers=4,
            )
            assert 1 <= state.outer_demand <= 4
            assert 1 <= state.outer_max_workers <= 4
    finally:
        thread.join(timeout=2)
        publisher.cleanup()

    assert not thread.is_alive()
    assert failures == []


def test_publishers_use_unique_paths_and_cleanup_is_idempotent(
    tmp_path: Path,
) -> None:
    runtime = _runtime_module()
    first = runtime.OuterDemandPublisher(
        max_workers=2,
        parent_dir=tmp_path,
    )
    second = runtime.OuterDemandPublisher(
        max_workers=2,
        parent_dir=tmp_path,
    )
    first_path = first.snapshot_path
    second_path = second.snapshot_path

    assert first_path != second_path
    assert first_path.is_file()
    assert second_path.is_file()

    first.cleanup()
    first.cleanup()
    second.cleanup()

    assert not first_path.exists()
    assert not second_path.exists()
    assert not first_path.parent.exists()
    assert not second_path.parent.exists()


def test_runtime_scope_restores_the_previous_path(tmp_path: Path) -> None:
    runtime = _runtime_module()
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"

    assert runtime.current_demand_snapshot_path() is None
    with runtime.task_parallelism_runtime_scope(first):
        assert runtime.current_demand_snapshot_path() == first
        with runtime.task_parallelism_runtime_scope(second):
            assert runtime.current_demand_snapshot_path() == second
        assert runtime.current_demand_snapshot_path() == first
    assert runtime.current_demand_snapshot_path() is None
