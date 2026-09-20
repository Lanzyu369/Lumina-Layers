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
from shapely.errors import GEOSException
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


def _force_process_plan(
    monkeypatch: pytest.MonkeyPatch,
    materializer,
    workers: int,
    memory_budget_bytes: int | None = 16 * 1024**3,
):
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
    if memory_budget_bytes is not None:
        monkeypatch.setattr(
            materializer,
            "resolve_vector_mesh_memory_budget_bytes",
            lambda: memory_budget_bytes,
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


@pytest.mark.parametrize("failure", ["worker", "result", "cancelled"])
def test_late_failure_restores_already_released_inputs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, failure: str,
) -> None:
    """A successful material must remain retryable after a sibling fails."""
    from shapely import get_precision, get_srid, set_precision, set_srid

    slots = _slots(3)
    first = slots["material-0"]["slabs"]
    first[0]["geometry"] = set_srid(set_precision(first[0]["geometry"], 0.125), 4326)
    first[0]["kind"] = "body"
    first[0]["height"] = np.float64(first[0]["height"])
    original = [dict(slab) for slab in first]

    class LateFailurePool(_ScriptedPool):
        def _complete(self, index, future, args):
            if index != 1:
                return super()._complete(index, future, args)
            assert not first, "successful inputs should be released before the next result"
            if failure == "worker":
                future.set_exception(ValueError("late worker failure"))
            elif failure == "cancelled":
                future.cancel()
                future.set_running_or_notify_cancel()
            else:
                Path(args[1]).write_bytes(b"invalid npz")
                future.set_result((args[1], 4242, 1.5))

    pool = LateFailurePool([_BLOCKED] * 3, _expected(slots), release_schedule=[0, 1])
    expected_error = CancelledError if failure == "cancelled" else ValueError
    with pytest.raises(expected_error):
        _run(monkeypatch, tmp_path, slots, pool)

    assert slots["material-0"]["slabs"] is first
    assert len(first) == len(original)
    for restored, before in zip(first, original, strict=True):
        assert restored.keys() == before.keys()
        assert restored["kind"] == before["kind"]
        assert type(restored["height"]) is type(before["height"])
        assert restored["height"] == before["height"]
        assert restored["geometry"].wkb == before["geometry"].wkb
        assert get_precision(restored["geometry"]) == get_precision(before["geometry"])
        assert get_srid(restored["geometry"]) == get_srid(before["geometry"])
    assert all(data["slabs"] for data in slots.values())
    assert not list(tmp_path.glob("lumina-vector-material-*"))

    retry = _ScriptedPool([_BLOCKED] * 3, _expected(slots), release_schedule=[2, 0, 1])
    result, *_ = _run(monkeypatch, tmp_path, slots, retry)
    assert list(result) == list(slots)
    assert all(not data["slabs"] for data in slots.values())


def test_rollback_checkpoint_does_not_retain_completed_geometry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    import weakref

    slots = _slots(3)
    geometry = weakref.ref(slots["material-0"]["slabs"][0]["geometry"])
    pool = _ScriptedPool([_BLOCKED] * 3, _expected(slots), release_schedule=[0, 1, 2])
    checked = []

    def check_release():
        if pool.results_seen == [0]:
            assert not slots["material-0"]["slabs"]
            assert geometry() is None
            checked.append(True)

    _run(monkeypatch, tmp_path, slots, pool, on_wait=check_release)
    assert checked == [True]


@pytest.mark.parametrize("restore_failure", [MemoryError, GEOSException, KeyboardInterrupt])
def test_restore_failure_preserves_worker_error_and_restores_other_materials(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, restore_failure: type[BaseException],
) -> None:
    from core import vector_material_meshing as materializer

    slots = _slots(3)
    original_error = ValueError("original worker failure")

    class LateFailurePool(_ScriptedPool):
        def _complete(self, index, future, args):
            if index == 2:
                future.set_exception(original_error)
            else:
                super()._complete(index, future, args)

    read_input = materializer._read_material_input

    def fail_first_restore(path):
        if path.name == "0.json":
            raise restore_failure("restore unavailable")
        return read_input(path)

    monkeypatch.setattr(materializer, "_read_material_input", fail_first_restore)
    pool = LateFailurePool([_BLOCKED] * 3, _expected(slots), release_schedule=[0, 1, 2])
    with pytest.raises(ValueError, match="original worker failure") as caught:
        _run(monkeypatch, tmp_path, slots, pool)
    assert caught.value is original_error
    assert any("material-0" in note and "restore unavailable" in note
               for note in caught.value.__notes__)
    assert slots["material-1"]["slabs"]
    assert slots["material-2"]["slabs"]
    assert not list(tmp_path.glob("lumina-vector-material-*"))


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
    started = time.perf_counter()
    _result, timings, _stops, _pool = _run(monkeypatch, tmp_path, slots, pool)
    elapsed = time.perf_counter() - started

    assert timings["materialize_input_write_s"] >= 0.0
    assert timings["materialize_input_bytes"] > 0
    assert timings["materialize_result_bytes"] > 0
    assert timings["materialize_result_read_s"] >= 0.0
    assert timings["materialize_worker_wait_s"] >= 0.0
    assert timings["materialize_first_result_s"] is not None
    # Disjoint phase durations fit within the stage; their relative speeds vary.
    assert (
        timings["materialize_input_write_s"] + timings["materialize_worker_wait_s"]
        + timings["materialize_result_read_s"] <= elapsed
    )
    assert 0 <= timings["materialize_first_result_s"] <= elapsed
    # The whole owned group and the container charge are recorded, not just
    # this process's own RSS.
    assert timings["materialize_owned_group_rss_start_bytes"] is not None
    assert "materialize_container_source" in timings


# ---------------------------------------------------------------------------
# R1: the worker lease covers every exit, and is returned only after this
# task's own compute processes have stopped
# ---------------------------------------------------------------------------


class _RecordingLifetime:
    """A lifetime whose startup can fail, recording open/close ordering."""

    parent: Path | None = None
    events: list[str] = []
    fail_open = False

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

    def open(self) -> "_RecordingLifetime":
        type(self).events.append("lifetime.open")
        if type(self).fail_open:
            raise OSError("monitor process could not be started")
        self.name
        return self

    def track_data_directory(self, _path) -> None:
        return None

    def close(self) -> None:
        type(self).events.append("lifetime.close")


class _OrderPool(_ScriptedPool):
    """Records the moment the executor stops this task's workers."""

    def __init__(self, *args, order: list[str], **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._order = order

    def __exit__(self, *_exc) -> bool:
        self._order.append("pool.exit")
        return super().__exit__(*_exc)


def _reset_recording_lifetime(*, fail_open: bool) -> None:
    _RecordingLifetime.events = []
    _RecordingLifetime.fail_open = fail_open


def _drive_materializer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    slots: dict,
    *,
    lease_path: Path | None,
    plan_workers: int,
    lifetime_cls: type = _RecordingLifetime,
    pool=None,
    order: list[str] | None = None,
    release_ok: bool = True,
    budget_scope_bytes: int | None = None,
):
    """Run the real materializer with a fake lifetime and a scripted pool."""

    from core import vector_material_meshing as materializer

    lifetime_cls.parent = tmp_path
    _force_process_plan(
        monkeypatch,
        materializer,
        workers=plan_workers,
        memory_budget_bytes=(
            None if budget_scope_bytes is not None else 16 * 1024**3
        ),
    )
    monkeypatch.setattr(materializer, "MaterialProcessLifetime", lifetime_cls)
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    if lease_path is not None:
        monkeypatch.setattr(
            materializer, "current_worker_lease_path", lambda: lease_path
        )
    if order is not None:
        real_release = WorkerLeaseStore.release

        def recording_release(store, token):
            order.append("lease.release")
            return real_release(store, token)

        monkeypatch.setattr(WorkerLeaseStore, "release", recording_release)
    if not release_ok:
        monkeypatch.setattr(WorkerLeaseStore, "release", lambda _store, _token: False)
    if pool is None:
        pool = _OrderPool(
            [_BLOCKED] * len(slots),
            _expected(slots),
            release_schedule=list(range(len(slots))),
            order=order if order is not None else [],
        )
    monkeypatch.setattr(materializer, "ProcessPoolExecutor", lambda **_kw: pool)

    def scripted_wait(futures, return_when):
        pool.release_one()
        return real_wait(futures, return_when=return_when)

    from contextlib import nullcontext

    from core.task_parallelism_runtime import task_host_memory_budget_scope

    timings: dict = {}
    budget_scope = (
        nullcontext()
        if budget_scope_bytes is None
        else task_host_memory_budget_scope(budget_scope_bytes)
    )
    monkeypatch.setattr(materializer, "wait", scripted_wait)
    with budget_scope:
        result = materializer.materialize_material_meshes(
            slots,
            scale_factor=1.0,
            geometry_policy=None,
            serial_builder=vector_engine.build_vector_layered_volume,
            timings=timings,
        )
    return result, timings


def test_monitor_startup_failure_returns_the_lease(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A monitor that cannot start keeps neither workers nor a ledger entry."""

    _reset_recording_lifetime(fail_open=True)
    lease_path = tmp_path / "workers.json"
    slots = _slots(3)

    result, timings = _drive_materializer(
        monkeypatch,
        tmp_path,
        slots,
        lease_path=lease_path,
        plan_workers=8,
    )

    # The serial fallback still built every material in order.
    assert list(result) == list(slots)
    assert timings["materialize_parallelism_limit"] == "process_ownership_unavailable"
    # No residual reservation from this task...
    snapshot = WorkerLeaseStore(lease_path).snapshot()
    assert (snapshot["workers"], snapshot["tasks"]) == (0, 0)
    # ...so the next task in the same still-live outer process gets the full
    # allowance instead of being squeezed by a dead reservation.
    following = WorkerLeaseStore(lease_path).reserve(
        requested_workers=8, effective_cpu_capacity=16, stage="vector_materialize"
    )
    assert following.workers == 8
    assert following.limiting_reason == "granted"
    WorkerLeaseStore(lease_path).release(following.token)
    assert WorkerLeaseStore(lease_path).snapshot()["workers"] == 0


def test_startup_diagnostics_failure_returns_the_lease(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A failure after startup but before dispatch still releases the lease."""

    from core import vector_material_meshing as materializer

    _reset_recording_lifetime(fail_open=False)
    lease_path = tmp_path / "workers.json"
    slots = _slots(3)

    def exploding_report():
        raise RuntimeError("memory probe unavailable")

    monkeypatch.setattr(materializer, "get_owned_memory_report", exploding_report)

    with pytest.raises(RuntimeError, match="memory probe unavailable"):
        _drive_materializer(
            monkeypatch,
            tmp_path,
            slots,
            lease_path=lease_path,
            plan_workers=8,
        )

    assert WorkerLeaseStore(lease_path).snapshot()["workers"] == 0
    # The monitor this task opened is still closed on the way out.
    assert _RecordingLifetime.events == ["lifetime.open", "lifetime.close"]


def test_normal_parallel_completion_returns_the_lease(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The ordinary path gives the capacity back too."""

    _reset_recording_lifetime(fail_open=False)
    lease_path = tmp_path / "workers.json"
    slots = _slots(4)

    result, timings = _drive_materializer(
        monkeypatch,
        tmp_path,
        slots,
        lease_path=lease_path,
        plan_workers=4,
    )

    assert len(result) == 4
    assert timings["materialize_lease_state"] == "granted"
    assert timings["materialize_lease_granted_workers"] == 4
    assert WorkerLeaseStore(lease_path).snapshot()["workers"] == 0


def test_worker_failure_returns_the_lease(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A failed material gives the capacity back as well."""

    _reset_recording_lifetime(fail_open=False)
    lease_path = tmp_path / "workers.json"
    slots = _slots(3)
    pool = _OrderPool(
        [_BLOCKED, "error", _BLOCKED], {}, release_schedule=[1], order=[]
    )

    with pytest.raises(ValueError, match="invalid height"):
        _drive_materializer(
            monkeypatch,
            tmp_path,
            slots,
            lease_path=lease_path,
            plan_workers=4,
            pool=pool,
        )

    assert WorkerLeaseStore(lease_path).snapshot()["workers"] == 0


def test_lease_is_returned_only_after_this_tasks_workers_stop(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Releasing first would let a later task take capacity still in use."""

    _reset_recording_lifetime(fail_open=False)
    order: list[str] = []
    lease_path = tmp_path / "workers.json"
    slots = _slots(3)

    _drive_materializer(
        monkeypatch,
        tmp_path,
        slots,
        lease_path=lease_path,
        plan_workers=3,
        order=order,
    )

    assert "pool.exit" in order and "lease.release" in order
    assert order.index("pool.exit") < order.index("lease.release")


def test_release_failure_does_not_mask_the_material_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A ledger that cannot be updated must not hide the material failure."""

    _reset_recording_lifetime(fail_open=False)
    lease_path = tmp_path / "workers.json"
    slots = _slots(3)
    pool = _OrderPool(
        [_BLOCKED, "error", _BLOCKED], {}, release_schedule=[1], order=[]
    )

    with pytest.raises(ValueError, match="invalid height"):
        _drive_materializer(
            monkeypatch,
            tmp_path,
            slots,
            lease_path=lease_path,
            plan_workers=4,
            pool=pool,
            release_ok=False,
        )


def test_release_failure_is_visible_in_the_timings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Silently keeping the reservation is the failure mode to avoid."""

    _reset_recording_lifetime(fail_open=False)
    lease_path = tmp_path / "workers.json"
    slots = _slots(3)

    _result, timings = _drive_materializer(
        monkeypatch,
        tmp_path,
        slots,
        lease_path=lease_path,
        plan_workers=3,
        release_ok=False,
    )

    assert timings["materialize_lease_release"] == "retained"
    assert timings["materialize_lease_release_attempts"] >= 2


# ---------------------------------------------------------------------------
# R3: the default task reservation must let the material stage parallelise
#
# The product's own 3.80 MB / 12-material task measures 591,720 coordinates
# (one dominant material at 129,695, the rest a long tail) and a 282 MB parent
# RSS when the material stage decides. The reservation the generate route
# computes for such a source is sized for the serial pipeline, so the
# affordability arithmetic lands on a single builder: ten were planned and one
# was affordable, which is why every material was built in the parent process.
# Only an explicit 12 GiB override reached ten builders. These fixtures keep
# the measured coordinate profile so the arithmetic runs on the same shape of
# input, and the reservation comes from the same estimator the route calls.
# ---------------------------------------------------------------------------

_MEASURED_MATERIAL_COUNT = 12
_DOMINANT_MATERIAL_COORDINATES = 130_001
_TAIL_MATERIAL_COORDINATES = 41_973
_MEASURED_TOTAL_COORDINATES = (
    _DOMINANT_MATERIAL_COORDINATES
    + (_MEASURED_MATERIAL_COUNT - 1) * _TAIL_MATERIAL_COORDINATES
)
_MEASURED_PARENT_RSS_BYTES = 282_714_112
_MEASURED_SOURCE_BYTES = 3_803_242


def _measured_profile_slots() -> dict:
    """Twelve materials with the measured coordinate profile."""

    import shapely

    def ring(coordinates: int):
        angles = np.linspace(0.0, 2.0 * np.pi, coordinates - 1, endpoint=False)
        points = np.column_stack((np.cos(angles), np.sin(angles)))
        return shapely.Polygon(points)

    return {
        f"material-{index}": {
            "mat_id": index,
            "slabs": [
                {
                    "geometry": ring(
                        _DOMINANT_MATERIAL_COORDINATES
                        if index == 0
                        else _TAIL_MATERIAL_COORDINATES
                    ),
                    "height": 0.2,
                    "z_offset": 0.0,
                }
            ],
        }
        for index in range(_MEASURED_MATERIAL_COUNT)
    }


def _write_dense_svg(path: Path, target_bytes: int) -> Path:
    """Write a well-formed SVG whose path data is close to ``target_bytes``."""

    prefix = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">'
        '<path d="M 0 0'
    )
    suffix = ' Z"/></svg>'
    points = max(1, (target_bytes - len(prefix) - len(suffix)) // 8)
    body = "".join(f" L {index % 997} {index % 991}" for index in range(points))
    path.write_text(prefix + body + suffix, encoding="utf-8")
    return path


def _plan_wanting(workers: int):
    from types import SimpleNamespace

    return SimpleNamespace(
        workers=workers,
        limiting_reason="test",
        outer_demand=1,
        effective_cpu_capacity=16,
        demand_snapshot_fallback=False,
    )


def test_default_reservation_leaves_the_material_stage_serial(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Reproduce: a serial-pipeline reservation affords exactly one builder."""

    from core import vector_material_meshing as materializer
    from core.task_parallelism_runtime import task_host_memory_budget_scope
    from core.vector_mesh_memory import estimate_vector_task_memory_reservation_bytes

    source = _write_dense_svg(tmp_path / "dense.svg", _MEASURED_SOURCE_BYTES)
    reservation = estimate_vector_task_memory_reservation_bytes(source)
    monkeypatch.setattr(
        materializer, "get_process_rss_bytes", lambda: _MEASURED_PARENT_RSS_BYTES
    )
    monkeypatch.setattr(
        materializer,
        "resolve_task_parallelism_plan",
        lambda *args, **kwargs: _plan_wanting(10),
    )

    diagnostics: dict = {}
    with task_host_memory_budget_scope(reservation):
        workers, reason, _worker_bytes, _plan = materializer._worker_budget(
            list(_measured_profile_slots().items()),
            vector_engine.build_vector_layered_volume,
            None,
            diagnostics,
        )

    assert diagnostics["materialize_total_coordinates"] == _MEASURED_TOTAL_COORDINATES
    # The plan wants ten builders for this profile; the reservation affords one,
    # so every material is built in the process that already exists.
    assert diagnostics["materialize_memory_planned_workers"] == 10
    assert diagnostics["materialize_memory_affordable_workers"] == 1
    assert workers == 1
    assert reason == "vector_memory_budget"


def test_gate_granted_reservation_lets_the_material_stage_parallelise(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The bounded extension the gate grants turns that serial stage parallel."""

    from api.worker_pool import _HostMemoryReservationGate
    from core import vector_material_meshing as materializer
    from core.task_parallelism_runtime import task_host_memory_budget_scope
    from core.vector_mesh_memory import (
        estimate_vector_material_parallel_memory_target_bytes,
        estimate_vector_task_memory_reservation_bytes,
    )

    source = _write_dense_svg(tmp_path / "dense.svg", _MEASURED_SOURCE_BYTES)
    reservation = estimate_vector_task_memory_reservation_bytes(source)
    target = estimate_vector_material_parallel_memory_target_bytes(
        source, material_count=_MEASURED_MATERIAL_COUNT
    )
    assert target is not None and target > reservation

    gate = _HostMemoryReservationGate(
        memory_budget_bytes=32 * 1024**3, sample_live_memory=False
    )
    token, granted = gate.acquire(
        reservation, owner=object(), parallel_target_bytes=target
    )
    try:
        # The extension is bounded by what is free, and is charged to the gate
        # exactly like the required part of the reservation.
        assert granted == target
        assert gate.reserved_bytes == granted
    finally:
        gate.release(token)
    assert gate.reserved_bytes == 0

    monkeypatch.setattr(
        materializer, "get_process_rss_bytes", lambda: _MEASURED_PARENT_RSS_BYTES
    )
    monkeypatch.setattr(
        materializer,
        "resolve_task_parallelism_plan",
        lambda *args, **kwargs: _plan_wanting(10),
    )
    diagnostics: dict = {}
    with task_host_memory_budget_scope(granted):
        workers, _reason, _worker_bytes, _plan = materializer._worker_budget(
            list(_measured_profile_slots().items()),
            vector_engine.build_vector_layered_volume,
            None,
            diagnostics,
        )

    assert diagnostics["materialize_memory_affordable_workers"] > 1
    assert workers > 1


def test_material_stage_parallelism_follows_the_granted_budget(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Same task, same slots: only the granted budget decides serial or not."""

    lease_path = tmp_path / "workers.json"

    # A material's source slabs are released as soon as its mesh exists, so
    # each run needs its own slots.
    _reset_recording_lifetime(fail_open=False)
    _result, serial_timings = _drive_materializer(
        monkeypatch,
        tmp_path,
        _slots(3),
        lease_path=lease_path,
        plan_workers=3,
        budget_scope_bytes=384 * 1024**2,
    )
    assert serial_timings["materialize_parallelism_workers"] == 1
    assert serial_timings["materialize_parallelism_limit"] == "vector_memory_budget"
    assert serial_timings["materialize_process_count"] == 0

    _reset_recording_lifetime(fail_open=False)
    _result, parallel_timings = _drive_materializer(
        monkeypatch,
        tmp_path,
        _slots(3),
        lease_path=lease_path,
        plan_workers=3,
        budget_scope_bytes=4 * 1024**3,
    )
    assert parallel_timings["materialize_parallelism_workers"] == 3
    # The scripted pool reports one child process id for every material, so the
    # recorded count proves the parallel path ran and recovered real child work.
    assert parallel_timings["materialize_process_count"] > 0
