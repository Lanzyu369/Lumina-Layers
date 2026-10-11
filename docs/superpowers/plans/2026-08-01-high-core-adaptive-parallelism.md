# High-Core Adaptive Converter Parallelism Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove arbitrary low production worker caps so raster and vector conversion can scale continuously with topology-aware effective CPU, live outer demand, useful work, and available memory without changing output semantics.

**Architecture:** Extend the existing immutable stage-boundary planner with an optional stage cap and proportional useful-work ceiling. CPU discovery distinguishes reliable Apple/Windows heterogeneous signals from homogeneous or unknown hosts, leaves Windows/Linux core placement to their OS schedulers, and retains affinity/cgroup bounds. The raster, vector-material, and native-vector callers opt out of a fixed stage cap and retain their natural item, memory, ordering, validation, and serial-fallback boundaries.

**Tech Stack:** Python 3.12, `ThreadPoolExecutor`, NumPy, SciPy, Shapely, Trimesh, psutil, pytest, existing converter multicore profiler.

---

## File map

- `core/task_parallelism.py`: continuous CPU/work/memory worker resolution and shared dynamic memory headroom.
- `core/system_capacity.py`: process-visible CPU limits, Apple performance
  capacity, Windows CPU-set efficiency classes, and topology diagnostics.
- `core/pipeline/s07_mesh_generation.py`: raster adoption with material count as the natural maximum.
- `core/vector_matchers.py`: vector-material adoption with 16 useful colors per planned worker.
- `core/vector_native_mesh.py`: native adoption with batch count, upper-median planning cost, and dynamic memory admission.
- `tests/test_task_parallelism_unit.py`: deterministic 8/32-CPU, outer-demand, work-density, and memory tests.
- `tests/test_system_capacity_unit.py`: Apple, Windows hybrid/uniform, Linux
  fallback, affinity, cgroup, and malformed-probe coverage.
- `tests/test_s07_mesh_parallelism_unit.py`: verifies raster passes no fixed cap and accepts a 12-worker plan without changing order.
- `tests/test_vector_material_matcher_unit.py`: verifies proportional work density and exact forwarding.
- `tests/test_vector_native_mesh_unit.py`: verifies high-core scaling, representative cost, window bounds, ordering, and serial fallback.
- `docs/superpowers/specs/2026-07-31-adaptive-converter-parallelism-results.md`: replaces the obsolete fixed-two production verdict with measured current-machine and pending high-core evidence.
- `docs/superpowers/specs/2026-08-01-high-core-adaptive-parallelism-design.md`: approved design and source references.

### Topology addendum: heterogeneous and homogeneous CPUs

- [x] Confirm from primary sources that Windows exposes per-CPU-set
  `EfficiencyClass`, Linux performs capacity-aware scheduling in the kernel,
  and oneTBB normally recommends allowing the OS to use all core types.
- [x] Add deterministic tests proving a 32-CPU homogeneous/unknown host keeps
  32, a Windows 16+16 hybrid layout remains OS-managed at 32, and an Apple
  4P+6E layout receives a four-worker heavy-compute budget.
- [x] Add Windows CPU-set parsing and cross-platform process-affinity fallback
  through the formal `psutil` dependency.
- [x] Carry topology, scheduling policy, and performance-class capacity through
  stage timing/profiler diagnostics.
- [ ] Validate the probe on real Windows hybrid and homogeneous machines before
  treating Windows topology telemetry as release evidence; unit fixtures prove
  logic, not the foreign-platform API call.

### Task 1: Continuous resource planner

**Files:**
- Modify: `tests/test_task_parallelism_unit.py`
- Modify: `core/task_parallelism.py`

- [x] **Step 1: Add failing high-core and proportional-work tests**

Add deterministic tests equivalent to:

```python
def test_unbounded_stage_scales_to_thirty_two_workers(monkeypatch):
    monkeypatch.delenv("LUMINA_VECTOR_PARALLELISM", raising=False)
    plan = task_parallelism.resolve_task_parallelism_plan(
        "vector",
        work_items=512,
        work_units=512,
        min_parallel_work_units=32,
        work_units_per_worker=16,
        hard_max_workers=None,
        estimated_worker_bytes=256 * 1024**2,
        available_memory_bytes=64 * 1024**3,
        effective_cpu_capacity=32,
        outer_demand=1,
    )
    assert plan.workers == 32
    assert plan.work_unit_ceiling == 32
    assert plan.stage_ceiling == 32


@pytest.mark.parametrize(
    ("kwargs", "expected_workers", "expected_reason"),
    [
        ({"outer_demand": 2}, 16, "cpu_fair_share"),
        ({"work_items": 12}, 12, "work_items"),
        ({"work_units": 128}, 8, "work_units"),
        (
            {
                "estimated_worker_bytes": 1024**3,
                "available_memory_bytes": 8 * 1024**3,
            },
            7,
            "memory",
        ),
    ],
)
def test_unbounded_stage_uses_each_dynamic_resource_ceiling(
    monkeypatch, kwargs, expected_workers, expected_reason
):
    monkeypatch.delenv("LUMINA_VECTOR_PARALLELISM", raising=False)
    inputs = {
        "work_items": 512,
        "work_units": 512,
        "min_parallel_work_units": 32,
        "work_units_per_worker": 16,
        "hard_max_workers": None,
        "effective_cpu_capacity": 32,
        "outer_demand": 1,
    }
    inputs.update(kwargs)
    plan = task_parallelism.resolve_task_parallelism_plan("vector", **inputs)
    assert plan.workers == expected_workers
    assert plan.limiting_reason == expected_reason
```

Add the exact headroom test:

```python
def test_memory_headroom_is_dynamic_without_dropping_below_one_gib() -> None:
    gib = 1024**3
    assert task_parallelism.task_memory_headroom_bytes(2 * gib) == gib
    assert (
        task_parallelism.task_memory_headroom_bytes(64 * gib)
        == (64 * gib) // 10
    )
```

- [x] **Step 2: Run the new planner tests and confirm RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_task_parallelism_unit.py \
  -k 'unbounded_stage or memory_headroom' -v
```

Expected: failure because `work_units_per_worker` and dynamic memory headroom do
not yet exist.

- [x] **Step 3: Implement optional caps, proportional work, and headroom**

In `core/task_parallelism.py`, add:

```python
_MEMORY_HEADROOM_FRACTION_DENOMINATOR = 10


def task_memory_headroom_bytes(available_memory_bytes: int) -> int:
    """Return memory reserved from task-local worker admission.
    返回任务内 worker 准入时预留的内存字节数。

    Args:
        available_memory_bytes: Current system-available memory.
            当前系统可用内存。

    Returns:
        The larger of one GiB and ten percent of available memory.
        一 GiB 与可用内存百分之十中的较大值。
    """

    available = max(0, int(available_memory_bytes))
    return max(
        _MIN_MEMORY_HEADROOM_BYTES,
        available // _MEMORY_HEADROOM_FRACTION_DENOMINATOR,
    )
```

Change both resolver signatures to:

```python
hard_max_workers: int | None = 8,
work_units_per_worker: int | None = None,
```

The shared default remains eight for compatibility. Reviewed converter stages
explicitly pass `hard_max_workers=None` to opt into continuous CPU scaling.

Resolve `stage_ceiling` after effective CPU:

```python
stage_ceiling = (
    effective_cpu
    if hard_max_workers is None
    else _positive_int(hard_max_workers)
)
```

Resolve useful-work capacity without changing the existing minimum-total-work
gate:

```python
units_per_worker = max(0, int(work_units_per_worker or 0))
if work_units is not None and unit_threshold > 0 and unit_count < unit_threshold:
    work_unit_ceiling = 1
elif work_units is not None and units_per_worker > 0:
    work_unit_ceiling = max(
        1,
        (unit_count + units_per_worker - 1) // units_per_worker,
    )
else:
    work_unit_ceiling = stage_ceiling
```

Replace the fixed headroom subtraction with
`task_memory_headroom_bytes(memory_available)`, pass the new keyword through
the integer wrapper, and update the affected public API documentation.

- [x] **Step 4: Run the complete planner suite and confirm GREEN**

Run:

```bash
.venv/bin/python -m pytest tests/test_task_parallelism_unit.py -v
```

Expected: all planner tests pass, including existing explicit hard-cap and
fail-closed behavior.

- [x] **Step 5: Commit the planner**

```bash
git add core/task_parallelism.py tests/test_task_parallelism_unit.py
git commit -m "feat(perf): scale task plans with available resources"
```

### Task 2: Raster and vector-material adoption

**Files:**
- Modify: `tests/test_s07_mesh_parallelism_unit.py`
- Modify: `tests/test_vector_material_matcher_unit.py`
- Modify: `core/pipeline/s07_mesh_generation.py`
- Modify: `core/vector_matchers.py`

- [x] **Step 1: Change adoption tests to require no fixed stage cap**

Update the raster policy-call expectation to contain:

```python
{
    "workload": "raster",
    "work_items": 4,
    "min_parallel_items": 2,
    "hard_max_workers": None,
    "work_units": 4,
    "min_parallel_work_units": 100_000,
    "estimated_worker_bytes": 64 * 1024**2,
}
```

Extend the exact-worker-limit raster test to include 12 workers and a
12-material context. Update the vector-material policy-call expectation with:

```python
{
    "hard_max_workers": None,
    "work_units_per_worker": 16,
}
```

Add a deterministic resolver test proving 512 useful colors on a 32-CPU,
64-GiB-class input produces a 32-worker plan.

- [x] **Step 2: Run the adoption tests and confirm RED**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_s07_mesh_parallelism_unit.py \
  tests/test_vector_material_matcher_unit.py -v
```

Expected: policy-call assertions fail on the old fixed value `2` and the
missing proportional-work keyword.

- [x] **Step 3: Remove both stage constants and pass continuous inputs**

In raster S07, delete `_MESH_MAX_WORKERS` and call:

```python
parallelism_plan = resolve_task_parallelism_plan(
    "raster",
    work_items=num_materials,
    min_parallel_items=2,
    hard_max_workers=None,
    work_units=int(np.asarray(full_matrix).size),
    min_parallel_work_units=_MIN_PARALLEL_MESH_WORK_UNITS,
    estimated_worker_bytes=_estimate_mesh_worker_bytes(full_matrix),
)
```

In vector matchers, replace the fixed maximum with:

```python
_VECTOR_MATERIAL_WORK_UNITS_PER_WORKER = 16
```

and call the planner with `hard_max_workers=None` plus
`work_units_per_worker=_VECTOR_MATERIAL_WORK_UNITS_PER_WORKER`. Do not change
cache lookup, result order, material recipes, or fallback behavior.

- [x] **Step 4: Run adoption and exact-output tests and confirm GREEN**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_s07_mesh_parallelism_unit.py \
  tests/test_vector_material_matcher_unit.py \
  tests/test_material_cache_unit.py \
  tests/test_material_inverse_refinement_unit.py -v
```

Expected: all pass; serial/parallel byte-identity tests remain green.

- [x] **Step 5: Commit both adoption sites**

```bash
git add core/pipeline/s07_mesh_generation.py core/vector_matchers.py \
  tests/test_s07_mesh_parallelism_unit.py \
  tests/test_vector_material_matcher_unit.py
git commit -m "feat(perf): lift fixed raster and material worker caps"
```

### Task 3: Native vector adoption and memory window

**Files:**
- Modify: `tests/test_vector_native_mesh_unit.py`
- Modify: `core/vector_native_mesh.py`

- [x] **Step 1: Add failing native high-core and cost tests**

Replace the former fixed-two expectations with one/four behavior under an
explicit four-worker ceiling, then add:

```python
def test_native_batch_plan_scales_to_thirty_two_workers(monkeypatch):
    monkeypatch.delenv("LUMINA_VECTOR_PARALLELISM", raising=False)
    monkeypatch.setenv("LUMINA_MAX_WORKERS", "1")
    monkeypatch.setattr(
        task_parallelism,
        "_available_memory_bytes",
        lambda: 64 * 1024**3,
    )
    monkeypatch.setattr(
        task_parallelism,
        "get_effective_cpu_capacity",
        lambda: EffectiveCpuCapacity(
            host_cpu_count=32,
            affinity_cpu_count=32,
            cgroup_quota_cpu_count=None,
            apple_performance_cpu_count=None,
            effective_cpu_count=32,
            limiting_source="affinity",
        ),
    )
    plan = vector_native_mesh._resolve_native_batch_plan(
        batch_count=44,
        group_count=55,
        representative_batch_bytes=384 * 1024**2,
    )
    assert plan.workers == 32
    assert plan.stage_ceiling == 32
```

Add an upper-median test with estimated bytes `[10, 20, 30, 10_000]` expecting
`30`, proving one outlier does not become the global estimate and a fixed
worker count no longer chooses the sample.

- [x] **Step 2: Run the native tests and confirm RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_vector_native_mesh_unit.py \
  -k 'batch_plan or representative or worker_policy' -v
```

Expected: the old fixed-two cap and smallest-two representative logic fail.

- [x] **Step 3: Remove the native cap and align memory admission**

Delete `NATIVE_BATCH_MAX_WORKERS` and
`NATIVE_BATCH_MEMORY_HEADROOM_BYTES`. Import
`task_memory_headroom_bytes` from `core.task_parallelism`.

Implement representative cost as:

```python
estimates = sorted(
    max(1, int(cost.estimated_bytes))
    for cost in costs
    if cost.group_count > 0
)
if not estimates:
    return NATIVE_BATCH_FIXED_VALIDATION_BYTES
return estimates[len(estimates) // 2]
```

Pass `hard_max_workers=None` in `_resolve_native_batch_plan()`. In the bounded
window, compute usable memory with:

```python
available_memory_bytes = max(
    0,
    int(parallelism_plan.available_memory_bytes or 0),
)
usable_memory_bytes = max(
    0,
    available_memory_bytes
    - task_memory_headroom_bytes(available_memory_bytes),
)
```

Keep the existing owner-thread prepare/ordered-commit loop, actual live-byte
check, oversized serial execution, and full serial retry unchanged.

- [x] **Step 4: Run native exactness and failure tests and confirm GREEN**

Run:

```bash
.venv/bin/python -m pytest tests/test_vector_native_mesh_unit.py -v
```

Expected: high-core plan reaches 32, window tests remain bounded, serial and
parallel signatures remain identical, and every fallback test passes.

- [x] **Step 5: Commit native adoption**

```bash
git add core/vector_native_mesh.py tests/test_vector_native_mesh_unit.py
git commit -m "feat(perf): scale native batches without a fixed cap"
```

### Task 4: Focused integration and exact semantic gates

**Files:**
- Verify: `scripts/profile_converter_multicore.py`
- Verify: supplied 8/12/15-color raster and vector assets
- Modify: `docs/superpowers/specs/2026-07-31-adaptive-converter-parallelism-results.md`

- [x] **Step 1: Run all touched focused suites**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_task_parallelism_unit.py \
  tests/test_system_capacity_unit.py \
  tests/test_task_parallelism_runtime_unit.py \
  tests/test_worker_pool_unit.py \
  tests/test_s07_mesh_parallelism_unit.py \
  tests/test_vector_material_matcher_unit.py \
  tests/test_vector_native_mesh_unit.py \
  tests/test_vector_branch_extraction_unit.py \
  tests/test_converter_multicore_profile_unit.py -v
```

Expected: PASS with no changed quality assertions.

- [x] **Step 2: Run fresh serial and automatic semantic references**

For each accepted representative, first run with the relevant
`LUMINA_*_PARALLELISM=1`, then run automatic mode with the serial
`profile.json` supplied through `--reference-report`. Use 8, 12, and 15
materials across the corpus and `--runs 3 --no-cprofile`.

Example raster automatic command:

```bash
env OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  VECLIB_MAXIMUM_THREADS=1 NUMEXPR_NUM_THREADS=1 BLIS_NUM_THREADS=1 \
  LUMINA_MAX_WORKERS=1 \
  .venv/bin/python scripts/profile_converter_multicore.py \
  --kind raster --input /Users/min/Downloads/145874854_p0_master1200.jpg \
  --phase generate --target-width-mm 200 --material-count 8 --runs 3 \
  --no-cprofile \
  --reference-report .scratch/high-core/raster-8-serial/profile.json \
  --output-dir .scratch/high-core/raster-8-auto
```

Example vector automatic command:

```bash
env OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  VECLIB_MAXIMUM_THREADS=1 NUMEXPR_NUM_THREADS=1 BLIS_NUM_THREADS=1 \
  LUMINA_MAX_WORKERS=1 \
  .venv/bin/python scripts/profile_converter_multicore.py \
  --kind vector --input /Users/min/Downloads/mmexport1784271438721.svg \
  --phase generate --target-width-mm 200 --material-count 12 --runs 3 \
  --no-cprofile --override-scenario recipe \
  --reference-report .scratch/high-core/vector-12-serial/profile.json \
  --output-dir .scratch/high-core/vector-12-auto
```

Expected: every automatic report records
`quality.external_reference_match=true`. If the development Mac shows a
repeatable end-to-end regression above 5%, retain the exact evidence and fix
the work/memory model; do not restore a universal low cap.

- [x] **Step 3: Document measured versus simulated evidence**

Update the result document so it states:

```text
- current Mac: measured worker decisions, timing, peak RSS, exact semantic hash;
- 8/32-CPU matrices: deterministic scheduling tests, not speed claims;
- 24/32-core 64-GiB performance: pending until run on matching hardware;
- fixed two-worker production verdict: superseded by continuous resource caps.
```

Include exact report paths and commands. Do not present simulated capacity as a
high-end performance result.

- [x] **Step 4: Commit evidence documentation**

```bash
git add docs/superpowers/specs/2026-07-31-adaptive-converter-parallelism-results.md \
  docs/superpowers/specs/2026-08-01-high-core-adaptive-parallelism-design.md \
  docs/superpowers/plans/2026-08-01-high-core-adaptive-parallelism.md
git commit -m "docs(perf): record continuous high-core scheduling evidence"
```

### Task 5: Repository gates, review, and Draft PR update

**Files:**
- Verify all changed files
- Update Draft PR #544

- [x] **Step 1: Run repository safety gates**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_logging_exception_governance_unit.py \
  tests/test_structured_logging_unit.py \
  tests/test_logger_unit.py -v
.venv/bin/python scripts/log_quality_check.py --mode fast
.venv/bin/python -m compileall -q \
  core/task_parallelism.py \
  core/pipeline/s07_mesh_generation.py \
  core/vector_matchers.py \
  core/vector_native_mesh.py
git diff --check
```

Expected: all commands pass; log-quality thresholds are unchanged.

- [x] **Step 2: Run the backend smoke gate**

Run:

```bash
.venv/bin/python scripts/run_smoke_tests.py
```

Expected: backend and frontend smoke checks pass with the repository-pinned
pnpm runtime.

- [x] **Step 3: Perform verification-before-completion review**

Compare `git diff <stacked-base>...HEAD` against every hard invariant in the
design. Confirm there is no changed tolerance, geometry path, recipe behavior,
validation flag, or artifact construction. Check the working tree for generated
profiles, source assets, logs, and caches; none may be committed.

- [x] **Step 4: Commit any review-only corrections and push**

```bash
git status --short
git push origin MOVIBALE/feat/adaptive-converter-parallelism
```

Expected: push succeeds without force and the remote head matches local HEAD.

- [x] **Step 5: Update Draft PR #544**

Add a PR section containing:

```text
- continuous formula and removal of fixed low stage caps;
- exact quality invariants and external-reference results;
- current development-machine timing/RSS evidence;
- deterministic 8/32-CPU scheduling matrix;
- explicit note that real 24/32-core speed evidence is still pending;
- focused, logging, smoke, compile, and diff-check commands;
- stacked-base merge dependency remains unchanged.
```

Keep the PR in Draft until the stacked base is merge-ready and real-machine
evidence meets the repository's merge gate.
