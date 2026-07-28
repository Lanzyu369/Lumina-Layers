# Raster Single-Task Multicore Implementation Plan

> Execute this plan with strict test-driven development. The serial result is
> the quality oracle; a faster result is rejected if any array, material, or
> canonical geometry semantic changes.

**Goal:** Reduce the wall time of one 299 mm high-fidelity Material Archive
generation while keeping `matched_rgb`, `material_matrix`, masks, material
identity, layer order, and canonical mesh semantics unchanged.

**Architecture:** Introduce one bounded task-local parallelism resolver and
adopt it at the existing S07 per-material thread boundary. Keep scene mutation
on the owner thread. Remove one measured, idempotent second cleanup pass for
rect-only meshes before adding more concurrency. Do not parallelize P03/S02,
S09, or S11 in this change because the evidence does not justify another
executor.

**Primary files:**

- Create: `core/task_parallelism.py`
- Create: `tests/test_task_parallelism_unit.py`
- Modify: `core/mesh_generators.py`
- Modify: `core/pipeline/s07_mesh_generation.py`
- Modify: `tests/test_mesh_generators_puzzle_unit.py`
- Create: `tests/test_s07_mesh_parallelism_unit.py`
- Read/compare:
  `.scratch/converter-multicore/baseline/native-raster-generate/profile.json`
  and experiment reports below it

## Evidence and decision

The quality-locked corpus uses `145874854_p0_master1200.jpg`, 299 mm,
12 selected Material Archive colors, 10 layers, and 0.08 mm material layers.

| Stage/function | Wall time | Share of 52.668 s | Evidence | Decision |
|---|---:|---:|---|---|
| S07 mesh generation | 28.116 s | 53.4% | Native stage timing | Optimize |
| `generate_mesh` | 28.804 s sampled | dominant S07 child | Statistical sample | Keep per-material work unit |
| `np.unique` / `argsort` during mesh cleanup | 25.756 / 17.682 s sampled inclusive/exclusive | major S07 work | Statistical sample | Remove proven duplicate pass only |
| S02 material processing | 12.042 s | 22.9% | Native stage timing; task CPU already >100% | Do not wrap in another executor |
| S09 3MF export | 9.038 s | 17.2% | Native stage timing | Keep serialized archive ownership |
| S11 GLB | 2.677 s | 5.1% | Native stage timing | Below first-change threshold |

The existing hard-coded four-thread S07 experiment completed in 41.423 s,
with S07 at 16.144 s. That is a 1.74x S07 speedup and a 1.27x total speedup.
The full semantic snapshot was identical to the serial result. Peak RSS rose
from 5.65 GiB to 6.66 GiB.

Raster root cause: S07 dominates because it consumes 28.116 of 52.668 seconds
and repeats expensive face/vertex cleanup inside independent material meshes;
the smallest experiment is to skip the idempotent second rect-only cleanup and
route the already-safe per-material thread pool through a bounded worker policy.

## Acceptance criteria

- Exact equality for `matched_rgb`, `material_matrix`, `mask_solid`, slot names,
  and the complete canonical geometry snapshot.
- Requested parallelism `1` is a real serial reference.
- `auto` accounts for visible CPUs, configured outer workers, work-item count,
  and a stage hard cap.
- Invalid environment values emit one actionable structured warning and fall
  back to `auto`.
- Tiny or single-material inputs do not create a thread pool.
- Large-corpus S07 is at least 30% faster than the serial reference.
- Large-corpus total generation is at least 15% faster than serial.
- Peak RSS stays below 8 GiB on the 16 GiB reference machine.
- Requests `1/2/4/8` are measured and the report records both requested and
  effective workers; safety caps may reduce an unsafe request.

## Task 1: Add the bounded parallelism policy

**Red test**

Create `tests/test_task_parallelism_unit.py` covering:

- unset and `auto` values;
- explicit positive integers;
- invalid, zero, negative, and whitespace values;
- visible CPU and `LUMINA_MAX_WORKERS` fair-share bounds;
- work-item and hard-worker caps;
- one structured warning per invalid `(environment variable, value)`.

Run:

```bash
.venv/bin/python -m pytest tests/test_task_parallelism_unit.py -v
```

Expected: import failure because `core.task_parallelism` does not exist.

**Implementation**

Create `core/task_parallelism.py` with a typed public API:

```python
resolve_task_parallelism(
    workload: Literal["raster", "vector"],
    *,
    work_items: int,
    min_parallel_items: int = 2,
    hard_max_workers: int = 8,
) -> int
```

Rules:

- read `LUMINA_RASTER_PARALLELISM` or `LUMINA_VECTOR_PARALLELISM`;
- accept `auto` or a positive integer;
- bound by CPU count, outer-worker fair share, work items, and hard cap;
- return one below the small-work threshold;
- log via `api.structured_logging.get_logger`.

Run the focused test until green.

## Task 2: Remove duplicate rect-only mesh cleanup

**Red test**

In `tests/test_mesh_generators_puzzle_unit.py`, add a no-boundary,
no-dilation high-fidelity case that:

- spies on `_merge_mesh_list`;
- proves a rect-only mesh does not require the outer second merge/cleanup;
- compares canonical triangles, bounds, area, volume, and face count with the
  current reference result.

Run the new test and verify it fails because the outer cleanup is called.

**Implementation**

In `HighFidelityMesher.generate_mesh`:

- return `rect_mesh` directly when `polygon_mesh` is absent;
- return the already-cleaned `polygon_mesh` directly when `rect_mesh` is absent;
- call `_merge_mesh_list` only when both exist;
- keep all public signatures and geometry construction unchanged.

Run:

```bash
.venv/bin/python -m pytest tests/test_mesh_generators_puzzle_unit.py \
  tests/test_raster_outline_preservation_properties.py -q
```

## Task 3: Adopt the policy at S07

**Red tests**

Create `tests/test_s07_mesh_parallelism_unit.py` using a deterministic fake
mesher. Cover:

- effective one executes on the calling thread;
- effective two/four use exactly that many worker threads;
- completion order is deliberately shuffled but scene/material order remains
  the original slot order;
- worker exceptions remain attached to the correct material;
- one material and tiny work stay serial;
- `_hifi_timings` records requested/effective parallelism.

Run and verify failure because S07 still hard-codes `min(4, num_materials)`.

**Implementation**

- replace the hard-coded worker calculation with
  `resolve_task_parallelism("raster", ...)`;
- preserve `LUMINA_DISABLE_PARALLEL_MESH=1` as a compatibility serial override;
- keep `mesh_results`, scene mutation, transforms, metadata, and logging on the
  owner thread;
- add requested/effective worker metrics without increasing INFO volume.

## Task 4: Quality and performance matrix

Run focused correctness:

```bash
.venv/bin/python -m pytest \
  tests/test_task_parallelism_unit.py \
  tests/test_s07_mesh_parallelism_unit.py \
  tests/test_mesh_generators_puzzle_unit.py \
  tests/test_converter_multicore_profile_unit.py -v
```

Run requests 1/2/4/8 with `LUMINA_MAX_WORKERS=1`, the fixed 299 mm corpus, and
separate output directories. Also run a 20 mm, 8-color small-input case and one
two-task concurrency check using the normal outer worker boundary.

For every report:

- compare the full semantic snapshot with the serial reference;
- record total, S07, CPU percentage, peak RSS, requested workers, and effective
  workers;
- select the fastest safe auto cap rather than assuming the highest count wins.

## Task 5: Regression gates and commit

Run:

```bash
.venv/bin/python -m pytest tests/test_perf_golden.py -v
.venv/bin/python -m pytest tests/test_pipeline_step_properties.py \
  tests/test_puzzle_boundary_pipeline_unit.py -q
python scripts/run_vitest.py run
git diff --check
```

Scan touched UTF-8 files for mojibake markers. Commit only after fresh evidence
shows exact semantics and the acceptance thresholds pass.
