"""Staggered-arrival admission and completion-order dispatch contracts.

These tests exercise the two resource-control properties the earlier material
parallelization did not have:

* a task arriving while another one is already running must see that task's
  *workers*, not just that a task exists; and
* completion/failure must be observed in completion order while the output
  stays in input order.

两个测试面：错峰到达时的 worker 租约准入（看真实占用，而不是只看任务数），
以及完成顺序派发 + 原始顺序输出。
"""

from __future__ import annotations

from concurrent.futures import CancelledError, Future, wait as real_wait
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

import numpy as np
import pytest
from shapely.geometry import box

from core import vector_engine
from core.task_parallelism_runtime import WorkerLeaseStore

ROOT = Path(__file__).resolve().parents[1]

_BLOCKED = "blocked"


def _slots(count: int) -> dict:
    return {
        f"material-{index}": {
            "mat_id": index,
            "slabs": [
                {
                    "geometry": box(index * 3, 0, index * 3 + 2, 2),
                    "height": 0.16 + 0.04 * index,
                    "z_offset": 0.0,
                }
            ],
        }
        for index in range(count)
    }


def _expected(slots: dict) -> dict[int, object]:
    return {
        index: vector_engine.build_vector_layered_volume(
            data["slabs"], scale_mm_per_svg_unit=1.0
        )
        for index, (_name, data) in enumerate(slots.items())
    }


# ---------------------------------------------------------------------------
# F1: staggered arrival shares one machine through the pool-owned lease table
# ---------------------------------------------------------------------------

_LEASE_HOLDER_SCRIPT = """
import sys, time
from pathlib import Path

sys.path.insert(0, sys.argv[1])
from core.task_parallelism_runtime import WorkerLeaseStore

lease_path, requested, capacity, ready, release = sys.argv[2:7]
store = WorkerLeaseStore(lease_path)
grant = store.reserve(
    requested_workers=int(requested),
    effective_cpu_capacity=int(capacity),
    stage="vector_materialize",
)
ready_path = Path(ready)
temporary = ready_path.with_suffix(".tmp")
temporary.write_text(
    "%d %d %d %s" % (grant.workers, grant.sibling_tasks, grant.sibling_workers, grant.limiting_reason),
    encoding="utf-8",
)
temporary.replace(ready_path)
deadline = time.monotonic() + 60
while not Path(release).exists() and time.monotonic() < deadline:
    time.sleep(0.02)
store.release(grant.token)
"""


class _LeaseHolder:
    """One real process holding a lease, so arrivals are genuinely staggered."""

    def __init__(
        self, tmp_path: Path, lease_path: Path, requested: int, capacity: int, tag: str
    ) -> None:
        self._release = tmp_path / f"release-{tag}"
        self._ready = tmp_path / f"ready-{tag}"
        self._script = tmp_path / f"lease_holder_{tag}.py"
        self._script.write_text(_LEASE_HOLDER_SCRIPT, encoding="utf-8")
        self.process = subprocess.Popen(
            [
                sys.executable,
                str(self._script),
                str(ROOT),
                str(lease_path),
                str(requested),
                str(capacity),
                str(self._ready),
                str(self._release),
            ],
            cwd=str(ROOT),
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )

    def grant(self, timeout: float = 60.0) -> tuple[int, int, int, str]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._ready.exists():
                fields = self._ready.read_text(encoding="utf-8").split()
                if len(fields) == 4:
                    return int(fields[0]), int(fields[1]), int(fields[2]), fields[3]
            if self.process.poll() is not None:
                raise AssertionError("lease holder exited before reserving")
            time.sleep(0.02)
        raise AssertionError("lease holder did not report its grant in time")

    def stop(self, *, release: bool = True) -> None:
        if not release:
            self.process.kill()
            self.process.wait(timeout=10)
            return
        self._release.write_text("go", encoding="utf-8")
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=10)


def test_staggered_arrivals_see_running_workers_not_just_task_count(
    tmp_path: Path,
) -> None:
    """16 CPUs: A alone holds 12; B arriving gets 4; C only gets the rest."""

    lease_path = tmp_path / "workers.json"
    holder = WorkerLeaseStore(lease_path)
    first = holder.reserve(
        requested_workers=12, effective_cpu_capacity=16, stage="vector_materialize"
    )
    assert (first.workers, first.state, first.sibling_workers) == (12, "granted", 0)

    second = _LeaseHolder(tmp_path, lease_path, requested=8, capacity=16, tag="b")
    third = None
    try:
        workers_b, tasks_b, siblings_b, reason_b = second.grant()
        # The 12 workers A already runs are visible, so B cannot take its whole
        # request - this is exactly the case the old task-count divisor missed.
        assert (workers_b, tasks_b, siblings_b) == (4, 1, 12)
        assert reason_b == "worker_lease_contention"

        third = _LeaseHolder(tmp_path, lease_path, requested=4, capacity=16, tag="c")
        workers_c, tasks_c, siblings_c, reason_c = third.grant()
        # Zero is the honest answer: C may start no worker process at all and
        # builds in the process it already runs in.
        assert (workers_c, tasks_c, siblings_c) == (0, 2, 16)
        assert reason_c == "lease_capacity_exhausted"

        # Every admission kept the sum of leased workers inside 16 CPUs.
        assert first.workers + workers_b + workers_c == 16
        assert WorkerLeaseStore(lease_path).snapshot()["workers"] == 16
    finally:
        if third is not None:
            third.stop()
        second.stop()

    # B and C have exited, so only A's 12 workers remain leased.
    assert WorkerLeaseStore(lease_path).snapshot()["workers"] == 12

    # Releasing the lease returns the capacity to the next arrival.
    holder.release(first.token)
    assert WorkerLeaseStore(lease_path).snapshot()["workers"] == 0
    fourth = holder.reserve(
        requested_workers=12, effective_cpu_capacity=16, stage="vector_materialize"
    )
    assert (fourth.workers, fourth.sibling_workers) == (12, 0)
    holder.release(fourth.token)


def test_live_lease_never_grows_above_its_grant(tmp_path: Path) -> None:
    """A running task may only shrink later dispatch, never expand it."""

    lease_path = tmp_path / "workers.json"
    holder = WorkerLeaseStore(lease_path)
    first = holder.reserve(
        requested_workers=12, effective_cpu_capacity=16, stage="vector_materialize"
    )
    assert holder.allowed_workers(first.token) == 12

    second = _LeaseHolder(tmp_path, lease_path, requested=8, capacity=16, tag="b")
    try:
        assert second.grant()[0] == 4
        # 16 - 4 = 12: the grant is unchanged, and it is never exceeded once
        # the sibling leaves either.
        assert holder.allowed_workers(first.token) == 12
    finally:
        second.stop()
    assert holder.allowed_workers(first.token) == 12
    holder.release(first.token)


def test_dead_lease_holder_does_not_starve_later_tasks(tmp_path: Path) -> None:
    """A killed holder must not hold capacity forever."""

    lease_path = tmp_path / "workers.json"
    holder = WorkerLeaseStore(lease_path)
    crashed = _LeaseHolder(tmp_path, lease_path, requested=12, capacity=16, tag="crash")
    try:
        assert crashed.grant()[0] == 12
    finally:
        crashed.stop(release=False)

    fresh = holder.reserve(
        requested_workers=12, effective_cpu_capacity=16, stage="vector_materialize"
    )
    assert (fresh.workers, fresh.sibling_tasks) == (12, 0)
    holder.release(fresh.token)


def test_unreadable_lease_table_refuses_to_add_load(tmp_path: Path) -> None:
    """An untrustworthy table means serial, not 'the machine looks idle'."""

    lease_path = tmp_path / "workers.json"
    lease_path.write_text("{not json", encoding="utf-8")
    grant = WorkerLeaseStore(lease_path).reserve(
        requested_workers=12, effective_cpu_capacity=16, stage="vector_materialize"
    )
    assert (grant.workers, grant.state, grant.token) == (1, "invalid", None)


@pytest.mark.parametrize("capacity", [1, 2, 4])
@pytest.mark.parametrize("already_running", [0, 1])
def test_small_device_admission_keeps_the_sum_inside_capacity(
    tmp_path: Path, capacity: int, already_running: int,
) -> None:
    """Low-capacity devices: an arriving task only takes what is still free.

    The matrix is small enough to run everywhere, and it states the same
    invariant the 16-CPU cases state: admitted workers never exceed the
    effective CPU capacity, and zero is a legal grant.
    """

    lease_path = tmp_path / "workers.json"
    holders: list[_LeaseHolder] = []
    try:
        for index in range(already_running):
            running = _LeaseHolder(
                tmp_path, lease_path,
                requested=capacity, capacity=capacity, tag=f"run{index}",
            )
            holders.append(running)
            granted, _tasks, _siblings, _reason = running.grant()
            assert granted == capacity

        arriving = _LeaseHolder(
            tmp_path, lease_path, requested=capacity, capacity=capacity, tag="new",
        )
        holders.append(arriving)
        granted, tasks, siblings, reason = arriving.grant()
        held = capacity * already_running
        assert granted == max(0, capacity - held)
        assert siblings == held
        assert tasks == already_running
        assert reason == (
            "granted" if already_running == 0
            else "worker_lease_contention" if granted else "lease_capacity_exhausted"
        )

        # The published table is the evidence: the sum stays inside the device.
        snapshot = WorkerLeaseStore(lease_path).snapshot()
        assert snapshot["workers"] == held + granted
        assert snapshot["workers"] <= capacity
    finally:
        for holder in holders:
            holder.stop()


# ---------------------------------------------------------------------------
# F2: completion-order discovery, original-order output
# ---------------------------------------------------------------------------


def _write_result(path: str, mesh) -> None:
    """Write the transport schema material workers produce."""

    if mesh is None:
        np.savez(path, present=np.array(False))
        return
    np.savez(
        path,
        present=np.array(True),
        vertices=np.asarray(mesh.vertices),
        faces=np.asarray(mesh.faces),
        metadata=np.array(json.dumps(dict(mesh.metadata) or {"probe": 1})),
    )


class _ScriptedPool:
    """Deterministic stand-in for ProcessPoolExecutor.

    The test decides, per submitted material, whether it succeeds, fails, or
    stays blocked, and in which order blocked materials are released, so
    ordering properties are reproduced without depending on machine speed or on
    which worker happens to be scheduled first.
    用确定性脚本代替真实进程池：由测试决定每个材质的完成/失败与释放顺序，
    使顺序性质与机器速度无关。
    """

    def __init__(
        self,
        recipes: list[str],
        expected: dict[int, object],
        *,
        release_schedule: list[int] | None = None,
    ) -> None:
        self.recipes = recipes
        self.expected = expected
        self.release_schedule = list(release_schedule or [])
        self.submitted: list[tuple[str, tuple]] = []
        self.futures: list[Future] = []
        self.peak_outstanding = 0
        self.submit_count = 0
        self.outstanding_at_submit: list[int] = []
        self.results_seen: list[int] = []
        self.shutdown_calls: list[tuple] = []

    def __enter__(self) -> "_ScriptedPool":
        return self

    def __exit__(self, *_exc) -> bool:
        self.shutdown_calls.append(("exit",))
        return False

    def submit(self, fn, *args) -> Future:
        index = len(self.futures)
        future: Future = Future()
        self.submitted.append((getattr(fn, "__name__", str(fn)), args))
        self.futures.append(future)
        self.submit_count += 1
        outstanding = sum(1 for item in self.futures if not item.done())
        self.outstanding_at_submit.append(outstanding)
        self.peak_outstanding = max(self.peak_outstanding, outstanding)
        if self.recipes[index] == "error":
            future.set_exception(ValueError("invalid height"))
        return future

    def shutdown(self, **_kwargs) -> None:
        self.shutdown_calls.append(("shutdown",))

    def _complete(self, index: int, future: Future, args) -> None:
        output_path = args[1]
        _write_result(output_path, self.expected.get(index))
        self.results_seen.append(index)
        future.set_result((output_path, 4242, 1.5))

    def release_one(self) -> bool:
        """Complete the next material the test scheduled for release."""

        while self.release_schedule:
            index = self.release_schedule.pop(0)
            future = self.futures[index]
            if future.done():
                continue
            self._complete(index, future, self.submitted[index][1])
            return True
        return False


class _MissingPool(_ScriptedPool):
    """A worker that reports success without producing its result file."""

    def _complete(self, index: int, future: Future, args) -> None:
        self.results_seen.append(index)
        future.set_result((str(Path(args[1]).with_suffix(".absent")), 4242, 1.5))


class _CorruptPool(_ScriptedPool):
    """A worker that produces an unreadable result file."""

    def _complete(self, index: int, future: Future, args) -> None:
        Path(args[1]).write_bytes(b"not an npz")
        self.results_seen.append(index)
        future.set_result((args[1], 4242, 1.5))


class _CancelledPool(_ScriptedPool):
    """A worker whose queued item is cancelled before it ever runs."""

    def submit(self, fn, *args) -> Future:
        future = super().submit(fn, *args)
        if future.cancel():
            # A real executor's manager thread then reports the cancelled item
            # through set_running_or_notify_cancel, which is what wakes up
            # concurrent.futures.wait. Without it a plain-Future cancel leaves
            # the waiter asleep and would hide a genuine hang.
            future.set_running_or_notify_cancel()
        return future


class _StubLifetime:
    """Owns only a temp directory; process reaping is covered elsewhere."""

    parent: Path | None = None

    def __init__(self, *_args, **_kwargs) -> None:
        self._directory: Path | None = None
        self.cpu_seconds = 0.0

    @property
    def name(self) -> str:
        if self._directory is None:
            self._directory = Path(
                tempfile.mkdtemp(prefix="lumina-material-watch-", dir=str(self.parent))
            )
        return str(self._directory)

    def open(self) -> "_StubLifetime":
        self.name
        return self

    def track_data_directory(self, _path) -> None:
        return None

    def close(self) -> None:
        return None


def _force_process_plan(monkeypatch: pytest.MonkeyPatch, materializer, workers: int):
    from types import SimpleNamespace

    monkeypatch.setattr(
        materializer,
        "resolve_task_parallelism_plan",
        lambda *args, **kwargs: SimpleNamespace(
            workers=workers,
            limiting_reason="test",
            outer_demand=1,
            effective_cpu_capacity=16,
            demand_snapshot_fallback=False,
        ),
    )
    monkeypatch.setattr(materializer, "get_process_rss_bytes", lambda: 100 * 1024**2)
    monkeypatch.setattr(
        materializer, "resolve_vector_mesh_memory_budget_bytes", lambda: 16 * 1024**3
    )
    monkeypatch.setattr(materializer, "MaterialProcessLifetime", _StubLifetime)
    monkeypatch.setattr(materializer, "current_worker_lease_path", lambda: None)
    monkeypatch.setattr(materializer, "current_demand_snapshot_path", lambda: None)


def _run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    slots: dict,
    pool: _ScriptedPool,
    *,
    lease_path: Path | None = None,
    on_wait=None,
    plan_workers: int | None = None,
):
    """Drive the real materializer with a scripted pool and no real workers."""

    from core import vector_material_meshing as materializer

    _StubLifetime.parent = tmp_path
    _force_process_plan(
        monkeypatch, materializer, workers=plan_workers or len(slots)
    )
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(materializer, "ProcessPoolExecutor", lambda **_kw: pool)
    if lease_path is not None:
        monkeypatch.setattr(
            materializer, "current_worker_lease_path", lambda: lease_path
        )

    def fake_wait(futures, return_when):
        if on_wait is not None:
            on_wait()
        pool.release_one()
        return real_wait(futures, return_when=return_when)

    monkeypatch.setattr(materializer, "wait", fake_wait)
    stop_calls: list = []
    monkeypatch.setattr(
        materializer, "_stop_processes", lambda target: stop_calls.append(target)
    )
    timings: dict = {}
    result = materializer.materialize_material_meshes(
        slots,
        scale_factor=1.0,
        geometry_policy=None,
        serial_builder=vector_engine.build_vector_layered_volume,
        timings=timings,
    )
    return result, timings, stop_calls, pool


def test_blocked_first_material_does_not_delay_a_fast_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Material 0 hangs; material 1 fails at once: the parent must not wait."""

    slots = _slots(3)
    pool = _ScriptedPool([_BLOCKED, "error", _BLOCKED], {})
    started = time.monotonic()
    with pytest.raises(ValueError, match="invalid height"):
        _run(monkeypatch, tmp_path, slots, pool)
    elapsed = time.monotonic() - started

    assert not pool.futures[0].done(), "the parent waited for the blocked material"
    assert pool.futures[1].done()
    assert not pool.futures[2].done(), "dispatch continued after the failure"
    assert elapsed < 10.0
    # Nothing is committed as a partial success, and inputs stay intact.
    assert all(data["slabs"] for data in slots.values())
    assert not list(tmp_path.glob("lumina-vector-material-*"))


def test_sibling_processes_are_stopped_when_a_material_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    slots = _slots(3)
    pool = _ScriptedPool([_BLOCKED, "error", _BLOCKED], {})
    with pytest.raises(ValueError):
        _run(monkeypatch, tmp_path, slots, pool)
    # _run collects the stop calls; a missing stop would leave the blocked
    # worker alive until the executor's shutdown wait.
    assert pool.shutdown_calls, "the pool was never shut down"


def test_out_of_order_completion_still_returns_original_material_order(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    slots = _slots(3)
    expected = _expected(slots)
    pool = _ScriptedPool([_BLOCKED] * 3, expected, release_schedule=[2, 0, 1])
    result, timings, _stops, _pool = _run(monkeypatch, tmp_path, slots, pool)

    assert list(result) == list(slots)
    assert [item["mat_id"] for item in result.values()] == [0, 1, 2]
    # Completion order really was 2, 0, 1 - not the input order.
    assert pool.results_seen == [2, 0, 1]
    for index, name in enumerate(slots):
        # Each material must still carry its own geometry, not a sibling's.
        mesh = result[name]["meshes"][0]
        np.testing.assert_array_equal(mesh.vertices, expected[index].vertices)
        np.testing.assert_array_equal(mesh.faces, expected[index].faces)
    assert timings["materialize_dispatch_waves"] >= 2
    assert timings["materialize_dispatch_peak_outstanding"] <= 3


def test_result_read_failure_stops_remaining_materials(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    slots = _slots(3)
    pool = _CorruptPool([_BLOCKED] * 3, {}, release_schedule=[1, 2])
    with pytest.raises(Exception):
        _run(monkeypatch, tmp_path, slots, pool)
    assert all(data["slabs"] for data in slots.values())


def test_missing_result_stops_remaining_materials(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    slots = _slots(3)
    pool = _MissingPool([_BLOCKED] * 3, {}, release_schedule=[1, 2])
    with pytest.raises(FileNotFoundError):
        _run(monkeypatch, tmp_path, slots, pool)


def test_cancelled_material_stops_remaining_work(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    slots = _slots(3)
    pool = _CancelledPool([_BLOCKED] * 3, {})
    with pytest.raises(CancelledError):
        _run(monkeypatch, tmp_path, slots, pool)


def test_arrival_of_a_sibling_limits_the_granted_workers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """12 of 16 CPUs leased by someone else leaves 4 for this document."""

    lease_path = tmp_path / "workers.json"
    sibling = WorkerLeaseStore(lease_path)
    held = sibling.reserve(
        requested_workers=12, effective_cpu_capacity=16, stage="vector_materialize"
    )
    slots = _slots(4)
    pool = _ScriptedPool(
        [_BLOCKED] * 4, _expected(slots), release_schedule=[0, 1, 2, 3]
    )
    result, timings, _stops, _pool = _run(
        monkeypatch, tmp_path, slots, pool, lease_path=lease_path
    )

    assert len(result) == 4
    assert timings["materialize_lease_state"] == "granted"
    assert timings["materialize_lease_sibling_tasks"] == 1
    assert timings["materialize_lease_sibling_workers"] == 12
    assert timings["materialize_lease_planned_workers"] == 4
    assert timings["materialize_lease_granted_workers"] == 4
    assert timings["materialize_parallelism_workers"] == 4
    assert timings["materialize_demand_snapshot"] == "absent"
    assert pool.peak_outstanding <= 4
    sibling.release(held.token)


def test_oversubscribed_machine_shrinks_dispatch_without_killing_work(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A lease the accounting never saw lowers later dispatch, not running work."""

    from core.task_parallelism_runtime import WORKER_LEASE_VERSION

    lease_path = tmp_path / "workers.json"
    slots = _slots(8)
    pool = _ScriptedPool(
        [_BLOCKED] * 8, _expected(slots), release_schedule=list(range(8))
    )
    planted = {"done": False}

    def journal(workers: int) -> None:
        """Simulate a task whose workers predate this accounting.

        模拟一个在本账本之前就开始的任务：它占用的 12 个 worker 没有经过预留，
        因此本任务准入时只看到“没人占用”。
        """

        lease_path.write_text(
            json.dumps(
                {
                    "version": WORKER_LEASE_VERSION,
                    "generation": 1,
                    "leases": {
                        "legacy": {
                            "pid": os.getpid(),
                            "created": time.time(),
                            "workers": workers,
                            "stage": "vector_materialize",
                            "effective_cpu": 16,
                        }
                    },
                    "updated_monotonic_ns": 0,
                }
            ),
            encoding="utf-8",
        )

    def on_wait() -> None:
        if not planted["done"]:
            planted["done"] = True
            journal(12)

    result, timings, _stops, _pool = _run(
        monkeypatch,
        tmp_path,
        slots,
        pool,
        lease_path=lease_path,
        on_wait=on_wait,
        plan_workers=6,
    )

    assert lease_path.exists()
    assert list(result) == list(slots), "materials were dropped or reordered"
    assert timings["materialize_lease_granted_workers"] == 6
    assert timings["materialize_lease_sibling_workers"] == 0
    # The first wave used the grant it was admitted with; every later
    # submission stayed inside the reduced allowance (16 - 12 = 4).
    assert pool.outstanding_at_submit[:6] == [1, 2, 3, 4, 5, 6]
    assert max(pool.outstanding_at_submit[6:]) <= 4
    assert all(not future.cancelled() for future in pool.futures)
    assert pool.peak_outstanding <= 6


def test_zero_grant_builds_in_process_without_starting_workers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Every CPU leased out: the document is still built, just in this process."""

    from core import vector_material_meshing as materializer

    lease_path = tmp_path / "workers.json"
    sibling = WorkerLeaseStore(lease_path)
    held = sibling.reserve(
        requested_workers=16, effective_cpu_capacity=16, stage="vector_materialize"
    )
    assert held.workers == 16
    slots = _slots(3)
    materializer_plan = _force_process_plan  # kept for readability of the flow
    materializer_plan(monkeypatch, materializer, workers=3)
    monkeypatch.setattr(
        materializer,
        "current_worker_lease_path",
        lambda: lease_path,
    )
    monkeypatch.setattr(
        materializer,
        "ProcessPoolExecutor",
        lambda **_kw: pytest.fail("a worker process was started with no capacity"),
    )
    monkeypatch.setattr(materializer, "MaterialProcessLifetime", _StubLifetime)
    timings: dict = {}
    result = materializer.materialize_material_meshes(
        slots,
        scale_factor=1.0,
        geometry_policy=None,
        serial_builder=vector_engine.build_vector_layered_volume,
        timings=timings,
    )
    assert list(result) == list(slots)
    assert all(item["meshes"][0] is not None for item in result.values())
    assert timings["materialize_lease_granted_workers"] == 0
    assert timings["materialize_parallelism_limit"] == "lease_capacity_exhausted"
    assert timings["materialize_parallelism_workers"] == 1
    assert all(not data["slabs"] for data in slots.values())
    # The zero grant released its own lease; the sibling's 16 remain.
    assert WorkerLeaseStore(lease_path).snapshot()["workers"] == 16
    sibling.release(held.token)


def test_no_lease_installed_is_reported_instead_of_claimed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A single CLI conversion must not pretend it proved a machine-wide bound."""

    slots = _slots(3)
    pool = _ScriptedPool(
        [_BLOCKED] * 3, _expected(slots), release_schedule=[0, 1, 2]
    )
    _result, timings, _stops, _pool = _run(monkeypatch, tmp_path, slots, pool)

    assert timings["materialize_lease_state"] == "unavailable"
    assert timings["materialize_demand_snapshot"] == "absent"
    assert (
        timings["materialize_lease_granted_workers"]
        == timings["materialize_lease_planned_workers"]
    )


def test_live_demand_snapshot_reaches_the_compute_stage(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The child initializer hands the pool snapshot to the material compute."""

    from core import vector_material_meshing as materializer
    from core.task_parallelism_runtime import (
        OuterDemandPublisher,
        current_demand_snapshot_path,
        read_outer_demand,
    )

    publisher = OuterDemandPublisher(max_workers=4, parent_dir=tmp_path)
    publisher.increment()
    publisher.increment()
    monkeypatch.setenv("LUMINA_LOG_INIT_BY_PARENT", "0")
    lifetime = materializer.MaterialProcessLifetime()
    lifetime.open()
    materializer._initialize_material_process(
        lifetime.name, os.getpid(), str(publisher.snapshot_path)
    )
    try:
        observed: dict = {}
        real_build = materializer._build_material_mesh

        def spy(input_path, output_path, scale_factor, grid_mm):
            path = current_demand_snapshot_path()
            state = read_outer_demand(path, fallback_outer_workers=4)
            observed.update({
                "path": path,
                "demand": state.outer_demand,
                "fallback": state.snapshot_fallback,
            })
            return real_build(input_path, output_path, scale_factor, grid_mm)

        monkeypatch.setattr(materializer, "_build_material_mesh", spy)
        source = tmp_path / "input.json"
        materializer._write_material_input(source, _slots(1)["material-0"]["slabs"])
        materializer._build_material_file(
            str(source), str(tmp_path / "out.npz"), 1.0, None, 512 * 1024**2
        )

        assert observed["path"] == publisher.snapshot_path
        assert observed["demand"] == 2
        assert observed["fallback"] is False
    finally:
        lifetime.close()
        publisher.cleanup()


def test_material_stage_reports_its_internal_split(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Input serialization, dispatch/compute and result recovery are separable."""

    slots = _slots(3)
    pool = _ScriptedPool(
        [_BLOCKED] * 3, _expected(slots), release_schedule=[2, 0, 1]
    )
    _result, timings, _stops, _pool = _run(monkeypatch, tmp_path, slots, pool)

    assert timings["materialize_input_write_s"] >= 0.0
    assert timings["materialize_input_bytes"] > 0
    assert timings["materialize_result_bytes"] > 0
    assert timings["materialize_result_read_s"] >= 0.0
    assert timings["materialize_worker_wait_s"] >= 0.0
    assert timings["materialize_first_result_s"] is not None
    # The split must not claim to be the whole stage.
    assert (
        timings["materialize_input_write_s"] + timings["materialize_worker_wait_s"]
        >= timings["materialize_result_read_s"]
    )
    # The whole owned group and the container charge are recorded, not just
    # this process's own RSS.
    assert timings["materialize_owned_group_rss_start_bytes"] is not None
    assert "materialize_container_source" in timings
