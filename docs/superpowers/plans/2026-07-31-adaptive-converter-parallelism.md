# Adaptive Converter Parallelism Implementation Plan

> Deployment update (2026-10-06): Docker support and the public-test bypass
> are retired. This historical record preserves earlier implementation and
> validation evidence; use [Runtime support](../../runtime-support.md) for current behavior.
> 部署更新：Docker 支持及公网测试访问旁路已移除；本文保留历史实现与验证记录，当前运行方式以上述说明为准。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a stage-boundary adaptive inner-work scheduler that uses effective CPU capacity, live outer demand, useful work, and available memory while preserving exact raster/vector model semantics and keeping peak memory bounded.

**Architecture:** Add one focused capacity-probe module and one focused runtime-demand module. `WorkerPoolManager` publishes only a small atomic demand snapshot and installs its path in each worker task; `core.task_parallelism` turns that state into an immutable plan while preserving the existing integer resolver. Raster S07, vector material solving, and native vector mesh consume the same plan, while native mesh additionally uses a bounded ordered in-flight window so scheduling changes cannot change output order or geometry decisions.

**Tech Stack:** Python 3.12, dataclasses, `functools.lru_cache`, `subprocess`, `psutil`, JSON atomic replacement, `ProcessPoolExecutor`, `ThreadPoolExecutor`, pytest, NumPy, Shapely, Trimesh, existing Lumina semantic profiler and logging gates.

---

## File and responsibility map

| File | Responsibility |
| --- | --- |
| `core/system_capacity.py` | Cached cross-platform effective CPU discovery only. |
| `core/task_parallelism_runtime.py` | Versioned atomic outer-demand snapshot, reader fallback, and worker-local runtime path scope. |
| `core/task_parallelism.py` | Immutable adaptive plan, all safety ceilings, stable limiting reason, compatibility integer API. |
| `api/worker_pool.py` | Outstanding-task lifecycle and installation of the demand path in worker execution context. |
| `core/pipeline/s07_mesh_generation.py` | Raster adoption; mesh algorithms and owner-thread application remain unchanged. |
| `core/vector_matchers.py` | Vector material-solver adoption; recipe solving remains unchanged. |
| `core/vector_native_mesh.py` | Per-batch cost accounting, bounded preparation/submission, and ordered commit. |
| `core/pipeline/vector_branch.py` | Bounded scalar diagnostics mapping only. |
| `scripts/profile_converter_multicore.py` | Record the chosen plan and memory-window fields in existing reports. |
| `tests/test_system_capacity_unit.py` | Deterministic affinity, cgroup, Apple, fallback, and cache coverage. |
| `tests/test_task_parallelism_runtime_unit.py` | Atomic snapshot validation, fallback, concurrency, and cleanup coverage. |
| Existing focused unit tests | Adoption, failure recovery, exact ordering, and report-contract coverage. |
| `docs/superpowers/specs/2026-07-31-adaptive-converter-parallelism-results.md` | Exact-quality, timing, RSS, worker-tier decision, and rollback evidence. |

## Hard invariants

- Scheduling may change; matched colors, recipes, material identity, layer order, run groups, geometry algorithms, tolerances, validation, fallback decisions, GLB semantics, and 3MF semantics may not.
- Missing CPU, demand, or memory telemetry reduces concurrency without changing output.
- A parallel failure discards its local result and re-runs the unchanged serial path.
- Shared scenes, output lists, statistics, caches, and commits stay on the owner thread.
- No new INFO event is added. New diagnostics are bounded scalar fields on existing timing/debug records.
- Production worker tiers are `1`, `2`, and conditionally `4`; tier `4` remains enabled only if every quality, speed, and RSS gate passes.

### Task 0: Lock the stacked-branch baseline

**Files:**
- Read: `docs/superpowers/specs/2026-07-31-adaptive-converter-parallelism-design.md`
- Read: `docs/superpowers/specs/2026-07-31-vector-native-batch-parallelism-results.md`
- Test: `tests/test_task_parallelism_unit.py`
- Test: `tests/test_worker_pool_unit.py`
- Test: `tests/test_s07_mesh_parallelism_unit.py`
- Test: `tests/test_vector_material_matcher_unit.py`
- Test: `tests/test_vector_native_mesh_unit.py`
- Test: `tests/test_converter_multicore_profile_unit.py`

- [x] **Step 1: Record the exact base and working-tree state**

Run:

```bash
git status --short --branch
git rev-parse HEAD
git rev-parse MOVIBALE/feat/vector-native-mesh-throughput
```

Expected: the topic branch is `MOVIBALE/feat/adaptive-converter-parallelism`, the tree contains no uncommitted product-code edits, and the stacked base resolves to `f01d3044`.

- [x] **Step 2: Run the focused pre-change suite**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_task_parallelism_unit.py \
  tests/test_worker_pool_unit.py \
  tests/test_s07_mesh_parallelism_unit.py \
  tests/test_vector_material_matcher_unit.py \
  tests/test_vector_native_mesh_unit.py \
  tests/test_converter_multicore_profile_unit.py -q
```

Expected: PASS. Any failure must also reproduce at `f01d3044` before it is classified as a baseline failure.

- [x] **Step 3: Capture the current machine facts**

Run:

```bash
.venv/bin/python -c 'import json, os, platform, psutil, sys; print(json.dumps({"platform": platform.platform(), "machine": platform.machine(), "python": sys.version.split()[0], "logical_cpu": os.cpu_count(), "physical_cpu": psutil.cpu_count(logical=False), "ram_bytes": psutil.virtual_memory().total}, sort_keys=True))'
```

Expected: one JSON object suitable for the results document; no repository file is changed.

### Task 1: Discover effective CPU capacity once per process

**Files:**
- Create: `core/system_capacity.py`
- Create: `tests/test_system_capacity_unit.py`

- [x] **Step 1: Write failing probe tests**

Add deterministic tests that inject the host count, affinity set, cgroup text, platform, and subprocess result:

```python
def test_affinity_narrows_host_capacity() -> None:
    result = discover_effective_cpu_capacity(
        host_cpu_count=12,
        affinity_cpu_ids={2, 3, 4, 5},
        cgroup_cpu_max=None,
        apple_performance_cpu_count=None,
    )
    assert result.effective_cpu_count == 4
    assert result.limiting_source == "affinity"


def test_cgroup_quota_narrows_affinity() -> None:
    result = discover_effective_cpu_capacity(
        host_cpu_count=16,
        affinity_cpu_ids=set(range(8)),
        cgroup_cpu_max="250000 100000",
        apple_performance_cpu_count=None,
    )
    assert result.cgroup_quota_cpu_count == 3
    assert result.effective_cpu_count == 3
    assert result.limiting_source == "cgroup_v2"


def test_apple_performance_cores_are_preferred() -> None:
    result = discover_effective_cpu_capacity(
        host_cpu_count=10,
        affinity_cpu_ids=None,
        cgroup_cpu_max=None,
        apple_performance_cpu_count=4,
    )
    assert result.effective_cpu_count == 4
    assert result.limiting_source == "apple_performance"


def test_invalid_probes_fall_back_to_at_least_one_cpu() -> None:
    result = discover_effective_cpu_capacity(
        host_cpu_count=None,
        affinity_cpu_ids=set(),
        cgroup_cpu_max="broken",
        apple_performance_cpu_count=0,
    )
    assert result.effective_cpu_count == 1
    assert result.limiting_source == "host_fallback"
```

Also test that two calls to `get_effective_cpu_capacity()` invoke the live probe only once until `cache_clear()` is called.

- [x] **Step 2: Run the new tests and verify the red state**

Run:

```bash
.venv/bin/python -m pytest tests/test_system_capacity_unit.py -q
```

Expected: FAIL because `core.system_capacity` does not exist.

- [x] **Step 3: Implement the capacity value and pure resolver**

Create the immutable public value and pure decision function:

```python
@dataclass(frozen=True)
class EffectiveCpuCapacity:
    host_cpu_count: int
    affinity_cpu_count: int | None
    cgroup_quota_cpu_count: int | None
    apple_performance_cpu_count: int | None
    effective_cpu_count: int
    limiting_source: str


def discover_effective_cpu_capacity(
    *,
    host_cpu_count: int | None,
    affinity_cpu_ids: Collection[int] | None,
    cgroup_cpu_max: str | None,
    apple_performance_cpu_count: int | None,
) -> EffectiveCpuCapacity:
    host = max(1, int(host_cpu_count or 1))
    affinity = len(affinity_cpu_ids) if affinity_cpu_ids else None
    quota = _parse_cgroup_v2_cpu_max(cgroup_cpu_max)
    performance = (
        int(apple_performance_cpu_count)
        if apple_performance_cpu_count
        and int(apple_performance_cpu_count) > 0
        else None
    )
    candidates = [
        ("host_fallback", host),
        ("affinity", affinity),
        ("cgroup_v2", quota),
        ("apple_performance", performance),
    ]
    valid = [(name, count) for name, count in candidates if count is not None]
    source, effective = min(valid, key=lambda item: int(item[1]))
    return EffectiveCpuCapacity(
        host_cpu_count=host,
        affinity_cpu_count=affinity,
        cgroup_quota_cpu_count=quota,
        apple_performance_cpu_count=performance,
        effective_cpu_count=max(1, int(effective)),
        limiting_source=source,
    )
```

Parse quota with `ceil(quota / period)`, treat `"max"` and invalid/non-positive values as unavailable, and clamp all returned counts to at least one.

- [x] **Step 4: Implement safe live probes and caching**

Implement:

```python
@lru_cache(maxsize=1)
def get_effective_cpu_capacity() -> EffectiveCpuCapacity:
    return discover_effective_cpu_capacity(
        host_cpu_count=os.cpu_count(),
        affinity_cpu_ids=_read_process_affinity(),
        cgroup_cpu_max=_read_cgroup_v2_cpu_max(),
        apple_performance_cpu_count=_read_apple_performance_cpu_count(),
    )
```

`_read_process_affinity()` uses `os.sched_getaffinity(0)` when callable. `_read_cgroup_v2_cpu_max()` reads `/sys/fs/cgroup/cpu.max` as UTF-8. `_read_apple_performance_cpu_count()` runs `["sysctl", "-n", "hw.perflevel0.logicalcpu"]` only on Darwin with `shell=False`, `check=False`, `capture_output=True`, `text=True`, and a `0.5` second timeout. Probe errors return `None`.

- [x] **Step 5: Run capacity tests and compile the module**

Run:

```bash
.venv/bin/python -m pytest tests/test_system_capacity_unit.py -q
.venv/bin/python -m py_compile core/system_capacity.py
```

Expected: PASS and no compiler output.

- [x] **Step 6: Commit the capacity probe**

```bash
git add core/system_capacity.py tests/test_system_capacity_unit.py
git commit -m "feat(perf): detect effective CPU capacity"
```

### Task 2: Publish and read bounded outer-demand state

**Files:**
- Create: `core/task_parallelism_runtime.py`
- Create: `tests/test_task_parallelism_runtime_unit.py`

- [x] **Step 1: Write failing snapshot and scope tests**

Cover round-trip publication, queued demand above one, malformed JSON, wrong schema, negative and unreasonably large counts, missing files, concurrent reads during atomic updates, unique publisher paths, nested runtime scopes, and cleanup:

```python
def test_publisher_round_trip_tracks_outstanding_tasks(tmp_path: Path) -> None:
    publisher = OuterDemandPublisher(max_workers=4, parent_dir=tmp_path)
    publisher.increment()
    publisher.increment()
    state = read_outer_demand(publisher.snapshot_path, fallback_outer_workers=4)
    assert state.outer_demand == 2
    assert state.outer_max_workers == 4
    assert state.snapshot_fallback is False
    publisher.decrement()
    assert read_outer_demand(
        publisher.snapshot_path,
        fallback_outer_workers=4,
    ).outer_demand == 1


def test_missing_snapshot_uses_configured_fair_share(tmp_path: Path) -> None:
    state = read_outer_demand(
        tmp_path / "missing.json",
        fallback_outer_workers=3,
    )
    assert state.outer_demand == 3
    assert state.outer_max_workers == 3
    assert state.snapshot_fallback is True


def test_runtime_scope_restores_the_previous_path(tmp_path: Path) -> None:
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    assert current_demand_snapshot_path() is None
    with task_parallelism_runtime_scope(first):
        assert current_demand_snapshot_path() == first
        with task_parallelism_runtime_scope(second):
            assert current_demand_snapshot_path() == second
        assert current_demand_snapshot_path() == first
    assert current_demand_snapshot_path() is None
```

- [x] **Step 2: Verify the snapshot tests fail**

Run:

```bash
.venv/bin/python -m pytest tests/test_task_parallelism_runtime_unit.py -q
```

Expected: FAIL because `core.task_parallelism_runtime` does not exist.

- [x] **Step 3: Implement typed state and atomic publisher**

Use the exact public shapes:

```python
DEMAND_SNAPSHOT_VERSION = 1
MAX_REASONABLE_OUTSTANDING_TASKS = 1_000_000


@dataclass(frozen=True)
class OuterDemandState:
    outer_demand: int
    outer_max_workers: int
    generation: int
    snapshot_fallback: bool


class OuterDemandPublisher:
    def __init__(
        self,
        *,
        max_workers: int,
        parent_dir: Path | None = None,
    ) -> None:
        self._max_workers = max(1, int(max_workers))
        self._lock = threading.Lock()
        self._outstanding = 0
        self._generation = 0
        self._closed = False
        self._directory = Path(
            tempfile.mkdtemp(
                prefix="lumina-parallelism-",
                dir=str(parent_dir) if parent_dir is not None else None,
            )
        )
        self._snapshot_path = self._directory / "demand.json"
        with self._lock:
            self._publish_locked()

    @property
    def snapshot_path(self) -> Path:
        return self._snapshot_path

    @property
    def outstanding(self) -> int:
        with self._lock:
            return self._outstanding

    def increment(self) -> None:
        with self._lock:
            if self._closed:
                raise RuntimeError("outer demand publisher is closed")
            self._outstanding += 1
            self._generation += 1
            self._publish_locked()

    def decrement(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._outstanding = max(0, self._outstanding - 1)
            self._generation += 1
            self._publish_locked()

    def cleanup(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._snapshot_path.unlink(missing_ok=True)
            self._directory.rmdir()
            self._closed = True

    def _publish_locked(self) -> None:
        payload = {
            "version": DEMAND_SNAPSHOT_VERSION,
            "generation": self._generation,
            "outstanding": self._outstanding,
            "outer_max_workers": self._max_workers,
            "updated_monotonic_ns": time.monotonic_ns(),
        }
        temporary_path = self._directory / (
            f".demand-{self._generation}-{uuid.uuid4().hex}.tmp"
        )
        try:
            with temporary_path.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle, separators=(",", ":"), sort_keys=True)
            os.replace(temporary_path, self._snapshot_path)
        finally:
            temporary_path.unlink(missing_ok=True)
```

Every update writes UTF-8 JSON containing only `version`, `generation`, `outstanding`, `outer_max_workers`, and `updated_monotonic_ns`. Close a unique temporary file in the publisher directory, then publish with `os.replace()`. This runtime-only control snapshot does not call `fsync`; it needs atomic visibility, not crash persistence. Counter changes and generation changes occur under one `threading.Lock`. Clamp the demand used by readers to `max(1, min(outstanding, outer_max_workers))`; queued work is retained in the published `outstanding` field without creating impossible inner concurrency.

- [x] **Step 4: Implement strict reader fallback and runtime scope**

`read_outer_demand()` accepts `str | os.PathLike[str] | None`. It returns fallback state when the file is absent, changes during a read, is not a JSON object, has a wrong version, or contains invalid integer bounds. The worker-local scope stores only a `Path` in `threading.local()` and restores nested state in `finally`.

- [x] **Step 5: Run snapshot tests and compile**

Run:

```bash
.venv/bin/python -m pytest tests/test_task_parallelism_runtime_unit.py -q
.venv/bin/python -m py_compile core/task_parallelism_runtime.py
```

Expected: PASS and no compiler output.

- [x] **Step 6: Commit runtime demand state**

```bash
git add core/task_parallelism_runtime.py tests/test_task_parallelism_runtime_unit.py
git commit -m "feat(perf): publish bounded outer task demand"
```

### Task 3: Wire demand lifecycle through `WorkerPoolManager`

**Files:**
- Modify: `api/worker_pool.py`
- Modify: `tests/test_worker_pool_unit.py`

- [x] **Step 1: Write failing worker-pool lifecycle tests**

Add tests proving:

```python
@pytest.mark.asyncio
async def test_submit_publishes_demand_until_result_delivery() -> None:
    pool = WorkerPoolManager(max_workers=2)
    pool.start()
    try:
        pending = asyncio.create_task(pool.submit(_slow_task, 0.15))
        await asyncio.sleep(0.03)
        state = read_outer_demand(
            pool.demand_snapshot_path,
            fallback_outer_workers=2,
        )
        assert state.outer_demand == 1
        assert await pending == "done"
        assert read_outer_demand(
            pool.demand_snapshot_path,
            fallback_outer_workers=2,
        ).outer_demand == 1
        assert pool.outstanding_tasks == 0
    finally:
        pool.shutdown()


@pytest.mark.asyncio
async def test_worker_receives_live_demand_snapshot_path() -> None:
    pool = WorkerPoolManager(max_workers=1)
    pool.start()
    try:
        assert await pool.submit(_read_runtime_demand) == (1, 1, False)
    finally:
        pool.shutdown()
```

Also assert decrement after worker exception, timeout, cancellation, and `BrokenProcessPool`; two concurrent submissions report two outstanding tasks; restart retains the same snapshot path; manager instances use different paths; shutdown removes the snapshot directory.

- [x] **Step 2: Run the targeted tests and verify failure**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_worker_pool_unit.py::TestSubmit \
  tests/test_worker_pool_unit.py::TestWorkerPoolLifecycle -q
```

Expected: FAIL because the manager exposes no demand state and workers receive no runtime path.

- [x] **Step 3: Install the snapshot path in worker entry points**

Change both top-level picklable wrappers to accept `demand_snapshot_path: str` before `*args`, and run the target function inside:

```python
with task_parallelism_runtime_scope(demand_snapshot_path):
    return fn(*args)
```

The timed wrapper delegates to the same contextualized wrapper so timing and non-timing submissions install identical runtime state.

- [x] **Step 4: Maintain outstanding demand across every exit path**

Construct one `OuterDemandPublisher` in `WorkerPoolManager.__init__()`. Add a
private manager helper that catches `OSError`, `RuntimeError`, and `ValueError`
from snapshot publication, logs
`event="worker_pool_demand_update_failed"` with `error_type`, `error_message`,
`operation`, and `path`, and continues with safe reader fallback. In
`_submit_internal()`, increment before calling `run_in_executor()` and
decrement in a `finally` that covers submission failure, success, exception,
timeout, cancellation, and pool restart:

```python
def _update_demand(self, operation: Literal["increment", "decrement"]) -> None:
    try:
        getattr(self._demand_publisher, operation)()
    except (OSError, RuntimeError, ValueError) as exc:
        _log.warning(
            "Failed to publish worker-pool demand",
            extra={
                "event": "worker_pool_demand_update_failed",
                "operation": operation,
                "path": str(self._demand_publisher.snapshot_path),
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
        )


self._update_demand("increment")
try:
    future = loop.run_in_executor(
        pool,
        worker_entry,
        fn,
        request_id,
        session_id,
        str(self._demand_publisher.snapshot_path),
        *args,
    )
    raw_result = await asyncio.wait_for(
        future,
        timeout=effective_timeout,
    )
finally:
    self._update_demand("decrement")
```

Keep the existing timing conversion and timeout/broken-pool handlers around the
shown `raw_result` assignment. Expose read-only `demand_snapshot_path` and
`outstanding_tasks` properties for diagnostics/tests. Restart only replaces the
executor; it does not replace the publisher.

- [x] **Step 5: Clean up demand state on shutdown**

After executor shutdown, call the publisher cleanup once. A cleanup failure logs one structured WARNING with `event="worker_pool_demand_cleanup_failed"`, `error_type`, `error_message`, and `path`; it must not change task results or raise from normal shutdown.

- [x] **Step 6: Run the complete worker-pool suite**

Run:

```bash
.venv/bin/python -m pytest tests/test_worker_pool_unit.py -q
```

Expected: PASS, including timeout/restart and context propagation tests.

- [x] **Step 7: Commit worker-pool integration**

```bash
git add api/worker_pool.py tests/test_worker_pool_unit.py
git commit -m "feat(perf): expose live worker demand to converters"
```

### Task 4: Resolve an immutable adaptive parallelism plan

**Files:**
- Modify: `core/task_parallelism.py`
- Modify: `tests/test_task_parallelism_unit.py`

- [x] **Step 1: Write failing plan tests**

Keep every existing integer-API test, update CPU monkeypatches to inject `EffectiveCpuCapacity`, and add:

```python
def test_plan_divides_cpu_and_memory_by_live_outer_demand(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LUMINA_RASTER_PARALLELISM", "8")
    plan = resolve_task_parallelism_plan(
        "raster",
        work_items=12,
        hard_max_workers=8,
        estimated_worker_bytes=512 * 1024**2,
        available_memory_bytes=5 * 1024**3,
        effective_cpu_capacity=8,
        outer_demand=2,
    )
    assert plan.workers == 4
    assert plan.cpu_fair_share_ceiling == 4
    assert plan.memory_ceiling == 4
    assert plan.outer_demand == 2


def test_work_unit_threshold_preserves_existing_parallel_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LUMINA_VECTOR_PARALLELISM", "4")
    plan = resolve_task_parallelism_plan(
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


def test_integer_api_returns_plan_workers() -> None:
    plan = resolve_task_parallelism_plan(
        "vector",
        work_items=20,
        effective_cpu_capacity=4,
        outer_demand=1,
    )
    assert resolve_task_parallelism(
        "vector",
        work_items=20,
        effective_cpu_capacity=4,
        outer_demand=1,
    ) == plan.workers
```

Cover nested scope, `1/2/4` tiers, requested ceiling, live-demand fair share, configured fallback demand, item ceiling, unit threshold, memory headroom, memory divided by demand, unknown-memory serial fallback, malformed snapshot fallback, and stable tie-breaking.

- [x] **Step 2: Verify the plan tests fail**

Run:

```bash
.venv/bin/python -m pytest tests/test_task_parallelism_unit.py -q
```

Expected: FAIL because `AdaptiveParallelismPlan` and `resolve_task_parallelism_plan()` do not exist.

- [x] **Step 3: Add the immutable result without removing the old API**

Use:

```python
@dataclass(frozen=True)
class AdaptiveParallelismPlan:
    workers: int
    requested_ceiling: int
    effective_cpu_capacity: int
    outer_demand: int
    cpu_fair_share_ceiling: int
    work_item_ceiling: int
    work_unit_ceiling: int
    stage_ceiling: int
    memory_ceiling: int
    available_memory_bytes: int | None
    estimated_worker_bytes: int
    limiting_reason: str
    demand_snapshot_fallback: bool
```

Add `resolve_task_parallelism_plan()` with the current parameters plus keyword-only deterministic inputs `effective_cpu_capacity: int | None = None` and `outer_demand: int | None = None`. Preserve `resolve_task_parallelism(...) -> int` and make it return `.workers`.

- [x] **Step 4: Implement all ceilings and stable reason selection**

Resolution rules:

```python
cpu_fair_share = max(1, effective_cpu // demand)
work_item_ceiling = max(1, item_count)
work_unit_ceiling = (
    stage_ceiling
    if work_units is None
    or min_parallel_work_units <= 0
    or unit_count >= unit_threshold
    else 1
)
usable_for_all_tasks = max(0, memory_available - 1024**3)
usable_for_this_task = usable_for_all_tasks // demand
memory_ceiling = max(1, usable_for_this_task // worker_bytes)
```

Take the minimum in this stable reason order: `requested`, `cpu_fair_share`, `effective_cpu`, `work_items`, `work_units`, `stage`, `memory`. Early serial outcomes use `nested_worker`, `insufficient_items`, or `insufficient_work_units`. When explicit `outer_demand` is absent, read the installed snapshot; when no valid snapshot is installed, retain the configured `LUMINA_MAX_WORKERS` fair-share behavior and set `demand_snapshot_fallback=True`.

- [x] **Step 5: Run planner and dependency-contract tests**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_task_parallelism_unit.py \
  tests/test_local_docker_deploy_contract_unit.py -q
.venv/bin/python -m py_compile \
  core/system_capacity.py \
  core/task_parallelism_runtime.py \
  core/task_parallelism.py
```

Expected: PASS; `psutil` remains present in the release dependency list.

- [x] **Step 6: Commit the adaptive plan**

```bash
git add core/task_parallelism.py tests/test_task_parallelism_unit.py
git commit -m "feat(perf): resolve adaptive inner parallelism plans"
```

### Task 5: Adopt the plan in raster and vector material solving

**Files:**
- Modify: `core/pipeline/s07_mesh_generation.py`
- Modify: `core/vector_matchers.py`
- Modify: `core/pipeline/vector_branch.py`
- Modify: `tests/test_s07_mesh_parallelism_unit.py`
- Modify: `tests/test_vector_material_matcher_unit.py`
- Modify: `tests/test_vector_branch_extraction_unit.py`

- [x] **Step 1: Write failing raster adoption tests**

Replace integer-resolver stubs with an `AdaptiveParallelismPlan` fixture and assert:

```python
assert result["_hifi_timings"]["mesh_parallelism_workers"] == 2
assert result["_hifi_timings"]["mesh_parallelism_limit"] == "cpu_fair_share"
assert result["_hifi_timings"]["mesh_parallelism_effective_cpu"] == 4
assert result["_hifi_timings"]["mesh_parallelism_outer_demand"] == 2
assert result["_hifi_timings"]["mesh_parallelism_memory_ceiling"] == 3
```

Retain byte/array/mesh signatures between requested serial and requested parallel runs. Retain the test proving `LUMINA_DISABLE_PARALLEL_MESH=1` forces execution to one without changing outputs.

- [x] **Step 2: Write failing vector material adoption tests**

Assert the solver receives `plan.workers`, the matcher retains the diagnostics for the largest worker count it actually used, legacy lookup signatures still filter the `parallelism` keyword, and serial versus parallel produces identical `matched_rgb_unique`, `recipes_b2t`, and `delta_e`.

- [x] **Step 3: Verify the adoption tests fail**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_s07_mesh_parallelism_unit.py \
  tests/test_vector_material_matcher_unit.py \
  tests/test_vector_branch_extraction_unit.py -q
```

Expected: FAIL because the sites still consume only an integer and do not expose plan fields.

- [x] **Step 4: Adopt the plan without changing executor work**

In raster S07:

```python
parallelism_plan = resolve_task_parallelism_plan(
    "raster",
    work_items=num_materials,
    min_parallel_items=2,
    hard_max_workers=4,
    work_units=int(np.asarray(full_matrix).size),
    min_parallel_work_units=_MIN_PARALLEL_MESH_WORK_UNITS,
    estimated_worker_bytes=_estimate_mesh_worker_bytes(full_matrix),
)
max_workers = parallelism_plan.workers
```

Keep the same material IDs, `_timed_generate_mesh`, `as_completed()` collection, error handling, and ascending owner-thread application.

In vector matching, retain the selected `AdaptiveParallelismPlan` next to `effective_parallelism_workers` and pass only `plan.workers` to `solver_cache.lookup()`. Do not change color sorting, cache keys, solver inputs, or returned arrays.

- [x] **Step 5: Map bounded diagnostics into existing timing payloads**

Add only scalar fields for workers, limiting reason, effective CPU, outer demand, CPU fair share, memory ceiling, and fallback flag. Keep the existing DEBUG events and add no new INFO event. `_record_material_parallelism()` must tolerate legacy processors with no plan.

- [x] **Step 6: Run focused adoption and exactness tests**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_s07_mesh_parallelism_unit.py \
  tests/test_vector_material_matcher_unit.py \
  tests/test_vector_branch_extraction_unit.py -q
```

Expected: PASS with exact serial/parallel outputs.

- [x] **Step 7: Commit raster and vector material adoption**

```bash
git add \
  core/pipeline/s07_mesh_generation.py \
  core/vector_matchers.py \
  core/pipeline/vector_branch.py \
  tests/test_s07_mesh_parallelism_unit.py \
  tests/test_vector_material_matcher_unit.py \
  tests/test_vector_branch_extraction_unit.py
git commit -m "feat(perf): adapt converter stage parallelism"
```

### Task 6: Bound native batch memory and remove the global serial cliff

**Files:**
- Modify: `core/vector_native_mesh.py`
- Modify: `tests/test_vector_native_mesh_unit.py`

- [x] **Step 1: Write failing monotonic cost tests**

Add exact assertions:

```python
def test_native_batch_cost_grows_with_points_rings_and_groups() -> None:
    small = _estimate_native_jobs_cost([_one_square_job()])
    more_points = _estimate_native_jobs_cost([_dense_polygon_job()])
    more_groups = _estimate_native_jobs_cost(
        [_one_square_job(), _second_square_job()]
    )
    assert small.estimated_bytes > 0
    assert more_points.point_count > small.point_count
    assert more_points.estimated_bytes > small.estimated_bytes
    assert more_groups.group_count > small.group_count
    assert more_groups.estimated_bytes > small.estimated_bytes


def test_native_batch_cost_saturates_instead_of_overflowing() -> None:
    value = _saturating_add_bytes(sys.maxsize, sys.maxsize)
    assert value == sys.maxsize
```

Verify Polygon, MultiPolygon, holes, empty geometries, and GeometryCollection counting without mutating geometries.

- [x] **Step 2: Write failing bounded-window and ordering tests**

Instrument preparation, compute, and commit to assert:

- at most `min(batch_count, workers + 1, memory-supported batches)` batch objects are live;
- completion may be out of order but commit indices are strictly ascending;
- an oversized middle batch is computed serially after earlier work drains;
- later safe batches resume parallel execution;
- more than 3,000 source geometries no longer forces every batch to one worker;
- executor or commit inconsistency discards local output and reproduces the serial signature;
- surface-rejection, native-error, fallback, path-cache, and output-mesh counters equal serial.

- [x] **Step 3: Run native tests and verify the red state**

Run:

```bash
.venv/bin/python -m pytest tests/test_vector_native_mesh_unit.py -q
```

Expected: FAIL on cost/window assertions and the old 3,000-geometry cliff.

- [x] **Step 4: Add immutable cost data to prepared batches**

Use:

```python
@dataclass(frozen=True)
class NativeBatchCost:
    source_geometry_count: int
    point_count: int
    ring_count: int
    hole_count: int
    group_count: int
    input_coordinate_bytes: int
    expected_mesh_buffer_bytes: int
    estimated_bytes: int


@dataclass(frozen=True)
class _PreparedNativeBatch:
    index: int
    height: float
    z_bot: float
    groups: tuple[_PreparedNativeGroup, ...]
    no_path_jobs: tuple[tuple[tuple[int, int, int], list], ...]
    cost: NativeBatchCost
```

Count coordinates through Shapely geometry interfaces without unioning or changing precision. Compute byte terms with saturating add/multiply capped at `sys.maxsize`. Include fixed validation allowance in every non-empty batch. Refine path/ring/point counts after owner-thread packing.

- [x] **Step 5: Resolve workers from useful batches, not a global geometry count**

Remove `NATIVE_BATCH_MAX_PARALLEL_SOURCE_GEOMETRIES` from worker selection and
diagnostics. Build cheap per-batch estimates first. Set the local candidate
stage ceiling to `NATIVE_BATCH_MAX_WORKERS = 4` for measurement. Use the largest
of the smallest `NATIVE_BATCH_MAX_WORKERS` estimates as the representative
per-worker memory cost, so one oversized batch does not force all safe batches
to serial. Pass that estimate to `resolve_task_parallelism_plan()`. Task 8 must
restore the production ceiling to `2` unless every four-worker gate passes.

- [x] **Step 6: Replace all-batches-live execution with an ordered window**

The loop must:

```python
window_limit = min(len(batch_items), worker_count + 1, memory_window_limit)
next_prepare_index = 0
next_commit_index = 0
in_flight: dict[int, tuple[_PreparedNativeBatch, Future | None]] = {}
```

Derive the byte budget exactly as:

```python
usable_memory_bytes = max(
    0,
    int(plan.available_memory_bytes or 0) - 1024**3,
)
per_task_memory_budget_bytes = usable_memory_bytes // max(1, plan.outer_demand)
memory_window_limit = max(
    1,
    per_task_memory_budget_bytes // max(1, representative_batch_bytes),
)
```

Prepare and submit in original order while both count and the sum of live batch
estimates fit their budgets. If the next cheap estimate cannot fit, consume the
next original future before preparing it. If a refined prepared batch exceeds
the per-task budget, stop filling, drain earlier indices, compute that batch on
the owner thread, commit it, release references, then resume filling. Commit
each future immediately when its original index is next; do not retain a
completed-results list for all batches.

- [x] **Step 7: Preserve all-or-serial failure recovery**

Keep local `meshes_by_slot`, stats, path cache, and copied extrusion cache inside the parallel attempt. Any executor, result-count, or commit invariant failure returns `(None, error_type)`; the caller then runs the unchanged serial `_run_native_job_batch()` loop from empty owner state.

- [x] **Step 8: Add bounded scalar native diagnostics**

Record:

```text
native_parallel_limit_reason
native_parallel_effective_cpu
native_parallel_outer_demand
native_parallel_cpu_fair_share
native_parallel_memory_ceiling
native_parallel_demand_fallback
native_parallel_inflight_limit
native_parallel_max_estimated_batch_bytes
native_parallel_oversized_serial_batches
```

Remove `native_parallel_source_geometry_limited`. Keep source geometry count for profiling only.

- [x] **Step 9: Run native exactness and recovery tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_vector_native_mesh_unit.py -q
.venv/bin/python -m py_compile core/vector_native_mesh.py
```

Expected: PASS; serial and parallel signatures and all fallback/surface counters are equal.

- [x] **Step 10: Commit bounded native scheduling**

```bash
git add core/vector_native_mesh.py tests/test_vector_native_mesh_unit.py
git commit -m "perf(vector): bound adaptive native batch execution"
```

### Task 7: Extend existing reports without increasing log volume

**Files:**
- Modify: `core/pipeline/vector_branch.py`
- Modify: `scripts/profile_converter_multicore.py`
- Modify: `tests/test_vector_branch_extraction_unit.py`
- Modify: `tests/test_converter_multicore_profile_unit.py`

- [x] **Step 1: Write failing report-contract tests**

Update the expected metadata object to contain:

```python
assert metrics["parallelism"] == {
    "requested": "auto",
    "observed_workers": 2,
    "effective_cpu": 4,
    "outer_demand": 2,
    "cpu_fair_share": 2,
    "memory_ceiling": 3,
    "limiting_reason": "cpu_fair_share",
    "demand_snapshot_fallback": False,
    "native_inflight_limit": 3,
    "native_max_estimated_batch_bytes": 402653184,
    "native_oversized_serial_batches": 0,
}
```

Retain the legacy report test where new fields are absent; it must emit `None` for unavailable optional diagnostics rather than fail.

- [x] **Step 2: Verify report tests fail**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_vector_branch_extraction_unit.py \
  tests/test_converter_multicore_profile_unit.py -q
```

Expected: FAIL because the mappings do not yet expose the new fields.

- [x] **Step 3: Map native stats and profiler metadata**

Add the new native timing-key mappings in `_NATIVE_MESH_TIMING_FIELDS`. Extend `_parallelism_metadata()` to read raster or vector plan fields and native window fields. Do not include filenames, colors, geometry data, recipes, or per-batch arrays.

- [x] **Step 4: Prove no new INFO event was introduced**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_converter_multicore_profile_unit.py \
  tests/test_logging_exception_governance_unit.py \
  tests/test_structured_logging_unit.py \
  tests/test_logger_unit.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit report integration**

```bash
git add \
  core/pipeline/vector_branch.py \
  scripts/profile_converter_multicore.py \
  tests/test_vector_branch_extraction_unit.py \
  tests/test_converter_multicore_profile_unit.py
git commit -m "chore(perf): report adaptive parallelism decisions"
```

### Task 8: Enforce exact quality, performance, and RSS gates

**Files:**
- Modify after measurement: `core/vector_native_mesh.py`
- Modify after measurement: `core/vector_matchers.py`
- Modify after measurement: `core/pipeline/s07_mesh_generation.py`
- Create: `docs/superpowers/specs/2026-07-31-adaptive-converter-parallelism-results.md`
- Runtime outputs only: `.scratch/adaptive-parallelism/`

- [x] **Step 1: Run the exact serial reference for the 12-color starry SVG**

Run:

```bash
env \
  OMP_NUM_THREADS=1 \
  OPENBLAS_NUM_THREADS=1 \
  MKL_NUM_THREADS=1 \
  VECLIB_MAXIMUM_THREADS=1 \
  NUMEXPR_NUM_THREADS=1 \
  LUMINA_MAX_WORKERS=1 \
  LUMINA_VECTOR_NATIVE_MESH=1 \
  LUMINA_VECTOR_PARALLELISM=1 \
  .venv/bin/python scripts/profile_converter_multicore.py \
    --kind vector \
    --input "/Users/min/Downloads/梵高星空款式西森猫猫.svg" \
    --phase generate \
    --target-width-mm 200 \
    --material-count 12 \
    --runs 3 \
    --no-cprofile \
    --override-scenario recipe \
    --output-dir .scratch/adaptive-parallelism/vector-12-serial
```

Expected: three internally equal semantic snapshots and a `profile.json` reference.

- [x] **Step 2: Run requested-two and requested-four against the external reference**

Run:

```bash
for adaptive_worker_count in 2 4; do
  env \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    VECLIB_MAXIMUM_THREADS=1 \
    NUMEXPR_NUM_THREADS=1 \
    LUMINA_MAX_WORKERS=1 \
    LUMINA_VECTOR_NATIVE_MESH=1 \
    LUMINA_VECTOR_PARALLELISM="${adaptive_worker_count}" \
    .venv/bin/python scripts/profile_converter_multicore.py \
      --kind vector \
      --input "/Users/min/Downloads/梵高星空款式西森猫猫.svg" \
      --phase generate \
      --target-width-mm 200 \
      --material-count 12 \
      --runs 3 \
      --no-cprofile \
      --override-scenario recipe \
      --reference-report \
        .scratch/adaptive-parallelism/vector-12-serial/profile.json \
      --output-dir \
        ".scratch/adaptive-parallelism/vector-12-workers-${adaptive_worker_count}"
done
```

Expected: both commands either report an exact external semantic match or the failing tier is rejected immediately.

- [x] **Step 3: Run 8/12/15-color vector archive cases**

Use the supplied `945695877_20260622_232544_vector.svg`, `mmexport1784271438721.svg`, and `梵高星空款式西森猫猫.svg` with these fixed pairs:

```text
8 colors  -> matched-rgb
12 colors -> recipe
15 colors -> combined
```

Run:

```bash
run_adaptive_vector_case() {
  local adaptive_case_name="$1"
  local adaptive_input_path="$2"
  local adaptive_material_count="$3"
  local adaptive_override_scenario="$4"
  local adaptive_case_root=".scratch/adaptive-parallelism/${adaptive_case_name}"

  env \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    VECLIB_MAXIMUM_THREADS=1 \
    NUMEXPR_NUM_THREADS=1 \
    LUMINA_MAX_WORKERS=1 \
    LUMINA_VECTOR_NATIVE_MESH=1 \
    LUMINA_VECTOR_PARALLELISM=1 \
    .venv/bin/python scripts/profile_converter_multicore.py \
      --kind vector \
      --input "${adaptive_input_path}" \
      --phase generate \
      --target-width-mm 200 \
      --material-count "${adaptive_material_count}" \
      --runs 3 \
      --no-cprofile \
      --override-scenario "${adaptive_override_scenario}" \
      --output-dir "${adaptive_case_root}-serial"

  for adaptive_worker_mode in auto 2 4; do
    if [[ "${adaptive_worker_mode}" == "auto" ]]; then
      env -u LUMINA_VECTOR_PARALLELISM \
        OMP_NUM_THREADS=1 \
        OPENBLAS_NUM_THREADS=1 \
        MKL_NUM_THREADS=1 \
        VECLIB_MAXIMUM_THREADS=1 \
        NUMEXPR_NUM_THREADS=1 \
        LUMINA_MAX_WORKERS=1 \
        LUMINA_VECTOR_NATIVE_MESH=1 \
        .venv/bin/python scripts/profile_converter_multicore.py \
          --kind vector \
          --input "${adaptive_input_path}" \
          --phase generate \
          --target-width-mm 200 \
          --material-count "${adaptive_material_count}" \
          --runs 3 \
          --no-cprofile \
          --override-scenario "${adaptive_override_scenario}" \
          --reference-report "${adaptive_case_root}-serial/profile.json" \
          --output-dir "${adaptive_case_root}-${adaptive_worker_mode}"
    else
      env \
        OMP_NUM_THREADS=1 \
        OPENBLAS_NUM_THREADS=1 \
        MKL_NUM_THREADS=1 \
        VECLIB_MAXIMUM_THREADS=1 \
        NUMEXPR_NUM_THREADS=1 \
        LUMINA_MAX_WORKERS=1 \
        LUMINA_VECTOR_NATIVE_MESH=1 \
        LUMINA_VECTOR_PARALLELISM="${adaptive_worker_mode}" \
        .venv/bin/python scripts/profile_converter_multicore.py \
          --kind vector \
          --input "${adaptive_input_path}" \
          --phase generate \
          --target-width-mm 200 \
          --material-count "${adaptive_material_count}" \
          --runs 3 \
          --no-cprofile \
          --override-scenario "${adaptive_override_scenario}" \
          --reference-report "${adaptive_case_root}-serial/profile.json" \
          --output-dir "${adaptive_case_root}-${adaptive_worker_mode}"
    fi
  done
}

run_adaptive_vector_case \
  vector-8 \
  "/Users/min/Downloads/945695877_20260622_232544_vector.svg" \
  8 \
  matched-rgb
run_adaptive_vector_case \
  vector-12 \
  "/Users/min/Downloads/mmexport1784271438721.svg" \
  12 \
  recipe
run_adaptive_vector_case \
  vector-15 \
  "/Users/min/Downloads/梵高星空款式西森猫猫.svg" \
  15 \
  combined
unset -f run_adaptive_vector_case
```

Expected: every accepted report has the same complete semantic hash, artifact
summaries, fallback count, and surface-rejection count as its serial reference.

- [x] **Step 4: Run supplied bitmap controls**

Run:

```bash
run_adaptive_raster_case() {
  local adaptive_case_name="$1"
  local adaptive_input_path="$2"
  local adaptive_material_count="$3"
  local adaptive_case_root=".scratch/adaptive-parallelism/${adaptive_case_name}"

  env \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    VECLIB_MAXIMUM_THREADS=1 \
    NUMEXPR_NUM_THREADS=1 \
    LUMINA_MAX_WORKERS=1 \
    LUMINA_RASTER_PARALLELISM=1 \
    .venv/bin/python scripts/profile_converter_multicore.py \
      --kind raster \
      --input "${adaptive_input_path}" \
      --phase generate \
      --target-width-mm 200 \
      --material-count "${adaptive_material_count}" \
      --runs 3 \
      --no-cprofile \
      --output-dir "${adaptive_case_root}-serial"

  for adaptive_worker_mode in auto 4; do
    if [[ "${adaptive_worker_mode}" == "auto" ]]; then
      env -u LUMINA_RASTER_PARALLELISM \
        OMP_NUM_THREADS=1 \
        OPENBLAS_NUM_THREADS=1 \
        MKL_NUM_THREADS=1 \
        VECLIB_MAXIMUM_THREADS=1 \
        NUMEXPR_NUM_THREADS=1 \
        LUMINA_MAX_WORKERS=1 \
        .venv/bin/python scripts/profile_converter_multicore.py \
          --kind raster \
          --input "${adaptive_input_path}" \
          --phase generate \
          --target-width-mm 200 \
          --material-count "${adaptive_material_count}" \
          --runs 3 \
          --no-cprofile \
          --reference-report "${adaptive_case_root}-serial/profile.json" \
          --output-dir "${adaptive_case_root}-${adaptive_worker_mode}"
    else
      env \
        OMP_NUM_THREADS=1 \
        OPENBLAS_NUM_THREADS=1 \
        MKL_NUM_THREADS=1 \
        VECLIB_MAXIMUM_THREADS=1 \
        NUMEXPR_NUM_THREADS=1 \
        LUMINA_MAX_WORKERS=1 \
        LUMINA_RASTER_PARALLELISM="${adaptive_worker_mode}" \
        .venv/bin/python scripts/profile_converter_multicore.py \
          --kind raster \
          --input "${adaptive_input_path}" \
          --phase generate \
          --target-width-mm 200 \
          --material-count "${adaptive_material_count}" \
          --runs 3 \
          --no-cprofile \
          --reference-report "${adaptive_case_root}-serial/profile.json" \
          --output-dir "${adaptive_case_root}-${adaptive_worker_mode}"
    fi
  done
}

run_adaptive_raster_case \
  raster-145874854 \
  "/Users/min/Downloads/145874854_p0_master1200.jpg" \
  8
run_adaptive_raster_case \
  raster-145879725 \
  "/Users/min/Downloads/145879725_p0_master1200.jpg" \
  12
run_adaptive_raster_case \
  raster-145881118 \
  "/Users/min/Downloads/145881118_p0_master1200.jpg" \
  15
run_adaptive_raster_case \
  raster-145890683 \
  "/Users/min/Downloads/145890683_p0_master1200.jpg" \
  8
run_adaptive_raster_case \
  raster-145883686 \
  "/Users/min/Downloads/145883686_p0_master1200.jpg" \
  12
run_adaptive_raster_case \
  raster-145877421 \
  "/Users/min/Downloads/145877421_p0_master1200.jpg" \
  15
unset -f run_adaptive_raster_case
```

Expected: exact matched arrays, recipes, material matrix, geometry/artifact
summaries, and no repeatable small-workload regression above 5%.

- [x] **Step 5: Run the native corpus guard**

Run:

```bash
env \
  OMP_NUM_THREADS=1 \
  OPENBLAS_NUM_THREADS=1 \
  MKL_NUM_THREADS=1 \
  VECLIB_MAXIMUM_THREADS=1 \
  NUMEXPR_NUM_THREADS=1 \
  LUMINA_MAX_WORKERS=1 \
  LUMINA_VECTOR_NATIVE_MESH=1 \
  .venv/bin/python scripts/profile_vector_native_mesh_corpus.py \
    "/Users/min/Downloads/梵高星空款式西森猫猫.svg" \
    --target-width-mm 200 \
    --repeats 3 \
    --validate-native-surface \
    --warm-native-import \
    --out-dir .scratch/adaptive-parallelism/native-corpus
```

Expected: no geometry, bounds, area, volume, native/fallback, or surface-validation failure.

- [x] **Step 6: Apply the worker-tier decision**

Keep `NATIVE_BATCH_MAX_WORKERS = 4` only when requested-four satisfies all of:

```text
exact semantic and artifact reference
median end-to-end time at least 10% below requested-two
peak RSS no more than 15% above requested-one
identical fallback and surface-rejection decisions
no repeatable small-case regression above 5%
```

If any condition fails, set `NATIVE_BATCH_MAX_WORKERS = 2` and rerun the native unit suite. This decision changes only the stage ceiling; the adaptive planner and bounded window remain.

- [x] **Step 7: Write the evidence document**

Write an English summary first and a Chinese summary second, then record the
exact branch SHA, machine/library versions, each report path, median end-to-end
seconds, peak RSS, selected workers, limiting reason, semantic hash,
fallback/surface counters, and the final `2` or `4` native ceiling. State
rejected candidates explicitly. Do not describe a tier as verified if any
reference command failed or was skipped.

- [x] **Step 8: Commit measured policy and evidence**

```bash
git add \
  docs/superpowers/plans/2026-07-31-adaptive-converter-parallelism.md \
  docs/superpowers/specs/2026-07-31-adaptive-converter-parallelism-results.md
git commit -m "docs(perf): record adaptive parallelism evidence"
```

### Task 9: Run repository gates, review the diff, and publish the PR

**Files:**
- Verify: all files changed since `f01d3044`

- [x] **Step 1: Run focused backend coverage**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_system_capacity_unit.py \
  tests/test_task_parallelism_runtime_unit.py \
  tests/test_task_parallelism_unit.py \
  tests/test_worker_pool_unit.py \
  tests/test_s07_mesh_parallelism_unit.py \
  tests/test_vector_material_matcher_unit.py \
  tests/test_vector_native_mesh_unit.py \
  tests/test_vector_branch_extraction_unit.py \
  tests/test_converter_multicore_profile_unit.py \
  tests/test_local_docker_deploy_contract_unit.py -q
```

Expected: PASS.

- [x] **Step 2: Run logging governance and workflow smoke**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_logging_exception_governance_unit.py \
  tests/test_structured_logging_unit.py \
  tests/test_logger_unit.py -q
.venv/bin/python scripts/log_quality_check.py --mode fast
.venv/bin/python scripts/run_smoke_tests.py
```

Expected: PASS without weakened thresholds.

- [x] **Step 3: Compile touched Python and check whitespace**

Run:

```bash
.venv/bin/python -m py_compile \
  core/system_capacity.py \
  core/task_parallelism_runtime.py \
  core/task_parallelism.py \
  api/worker_pool.py \
  core/pipeline/s07_mesh_generation.py \
  core/vector_matchers.py \
  core/vector_native_mesh.py \
  core/pipeline/vector_branch.py \
  scripts/profile_converter_multicore.py
git diff --check f01d3044...HEAD
```

Expected: no output from compilation or `git diff --check`.

- [x] **Step 4: Inspect scope and accidental semantic changes**

Run:

```bash
git diff --stat f01d3044...HEAD
git diff --name-status f01d3044...HEAD
git diff f01d3044...HEAD -- \
  core/pipeline/s07_mesh_generation.py \
  core/vector_matchers.py \
  core/vector_native_mesh.py
```

Expected: only scheduling, bounded diagnostics, tests, profiler support, and evidence changed; no geometry tolerance, recipe, material ordering, GLB, 3MF, or fallback algorithm changed.

- [x] **Step 5: Verify no project process remains**

Run:

```bash
ps -axo pid=,command= | rg 'api_server.py|start_all.py|vite|vitest|Lumina-studio' || true
```

Expected: no backend, frontend, watch test, or profiling child process started by this task remains.

- [x] **Step 6: Obtain final code review and address only in-scope findings**

Review the complete stacked diff against the approved design. Re-run the focused suite after every review fix. Classify any unverified environment-only gate as `partial` or `fix_not_verified`; do not convert it into a pass.

- [x] **Step 7: Push the topic branch and open a PR against the current stack**

Run:

```bash
git status --short --branch
git push -u origin MOVIBALE/feat/adaptive-converter-parallelism
gh pr create \
  --base MOVIBALE/feat/vector-native-mesh-throughput \
  --head MOVIBALE/feat/adaptive-converter-parallelism \
  --title "perf(converter): adapt inner parallelism to runtime demand" \
  --body-file \
    docs/superpowers/specs/2026-07-31-adaptive-converter-parallelism-results.md
```

Expected: the remote topic SHA equals local `HEAD`, the PR targets the unmerged stacked base, and the PR body reports exact-quality evidence, performance/RSS results, tests, rollout controls, and any honest partial gate.
