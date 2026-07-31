# High-Core Adaptive Converter Parallelism Design

**Date:** 2026-08-01

**Status:** `approved_for_implementation`

**Branch:** `MOVIBALE/feat/adaptive-converter-parallelism`

**Draft PR:** [#544](https://github.com/lumina-layer-studio/Lumina-studio/pull/544)

**Supersedes:** the fixed one/two-worker production decision in
`2026-07-31-adaptive-converter-parallelism-results.md` and the fixed native
worker tiers in `2026-07-31-adaptive-converter-parallelism-design.md`.

## 1. Decision

Lumina will not impose an arbitrary low global ceiling such as 8, 16, or 32
inner workers. Each heavy converter stage will calculate a continuous resource
plan from the machine and the current conversion workload:

```text
selected workers = min(
  operator ceiling,                 # optional, auto means effective CPU
  effective process CPU / outer demand,
  independent work-item capacity,
  useful-work capacity,
  available-memory capacity,
  optional evidence-backed stage ceiling,
)
```

The three production adoption sites will pass no fixed stage ceiling. Their
natural independent work limits remain authoritative:

- raster mesh generation is limited by the number of material meshes;
- vector material refinement is limited by useful target-color blocks and the
  refinement groups that actually exist;
- native vector mesh generation is limited by semantic batch count and its
  memory-bounded in-flight window.

An explicit environment value remains a maximum, never a forced allocation.
Unreliable CPU, demand, or memory evidence continues to reduce concurrency.

This changes scheduling only. Geometry, material matching, recipes, layer
order, tolerances, native validation, fallback behavior, GLB, and 3MF semantics
must remain unchanged.

## 2. Why the fixed cap is removed

The previous two-worker result was valid evidence for the 4-performance-core,
16-GiB development Mac and the supplied corpus. It was not evidence that a
24/32-core, 64-GiB workstation should also stop at two workers.

A stage constant turns one machine's benchmark result into a product-wide
limit. It also duplicates limits already supplied by CPU capacity, live outer
demand, work count, and memory. The result is unnecessarily conservative on a
machine that has both more cores and more memory.

The new rule retains the prior Mac evidence as a benchmark observation, not as
a universal hardware policy. The profiler will still reject a performance
claim if automatic mode regresses on that machine, but it will not encode the
machine's winning thread count as a global cap.

## 3. Open-source reference model

The selected design follows the common shape used by maintained media and
geometry applications:

- oneTBB exposes `max_allowed_parallelism`; applications may apply an explicit
  maximum without replacing the scheduler's view of available concurrency;
- PrusaSlicer uses the TBB task arena's available concurrency and clamps it
  only when the user provides a lower thread count;
- Blender lets TBB choose the default and installs a global maximum only for
  an explicit override;
- libvips starts from process-visible hardware concurrency, prefers performance
  cores on Apple Silicon, limits tiny images by tile count, and bounds live
  work in its thread pool;
- FFmpeg limits slice workers by both available CPUs and the number of useful
  slices;
- OpenImageIO recommends one inner thread when the application already runs
  many top-level image operations;
- GDAL supports all visible CPUs while treating memory/cache size as a separate
  resource budget.

Primary references:

- <https://github.com/uxlfoundation/oneTBB/blob/master/include/oneapi/tbb/global_control.h>
- <https://github.com/prusa3d/PrusaSlicer/blob/b028299c770b8380ee81c921a2867d522f288123/src/libslic3r/Thread.cpp#L237-L246>
- <https://github.com/blender/blender/blob/d13bbc114494f05716f60f9a5b63299c3ac63349/source/blender/blenlib/intern/task_scheduler.cc#L36-L54>
- <https://github.com/libvips/libvips/blob/2ff898f0a1637c45d15db532a7fbe2d30cc99aac/libvips/iofuncs/thread.c#L160-L204>
- <https://github.com/libvips/libvips/blob/2ff898f0a1637c45d15db532a7fbe2d30cc99aac/libvips/iofuncs/threadpool.c#L485-L524>
- <https://github.com/FFmpeg/FFmpeg/blob/5f832b7b3fd4cb8daf9bb64373230809c246bd84/libavcodec/pthread_slice.c#L112-L146>
- <https://openimageio.readthedocs.io/en/v3.1.14.0/imageioapi.html#global-attributes>
- <https://gdal.org/en/stable/user/configoptions.html#performance-and-caching>

## 4. Alternatives

### A. Fixed hardware tiers

Example: 8 cores -> 4 workers, 16 cores -> 8, 32 cores -> 16.

Rejected because the thresholds are arbitrary, ignore concurrent conversions,
and cannot express a 12-material raster task or a memory-constrained vector
task correctly.

### B. Full CPU count with only a fixed global maximum

Example: `min(cpu_count, 32)`.

Rejected because it oversubscribes when several outer conversions are active,
creates idle workers for small workloads, and treats 64 GiB and 8 GiB machines
as equivalent.

### C. Instantaneous CPU-percentage polling

Rejected as a worker-count correctness input. Short samples are noisy, the
first cross-platform sample is often undefined, and a stage cannot safely
revoke a Python executor thread that is already inside native code. The OS
scheduler still handles unrelated system load; Lumina handles its own load
through live outer demand.

### D. Continuous resource ceilings at stage boundaries

Selected. It uses stable capacity and workload facts, recalculates before each
heavy stage, and leaves running native calls uninterrupted. It is deterministic
and directly testable with injected CPU, demand, work, and memory values.

## 5. Planner contract

`resolve_task_parallelism_plan()` keeps one compatibility parameter:

```python
hard_max_workers: int | None = None
```

`None` means that the stage adds no extra ceiling; the resolved stage ceiling
is the effective process CPU count. A positive integer remains available for
future stages that have a documented library or correctness constraint. The
existing integer wrapper keeps the same return type.

The plan adds an optional useful-work density:

```python
work_units_per_worker: int | None = None
```

When supplied, useful-work capacity is:

```text
max(1, ceil(work_units / work_units_per_worker))
```

The existing `min_parallel_work_units` remains a separate total-work gate. This
keeps tiny inputs serial while allowing large inputs to scale continuously
instead of jumping from one worker directly to a stage maximum.

Stable resolution order remains:

1. nested Lumina worker -> one;
2. insufficient independent items -> one;
3. insufficient total useful work -> one;
4. explicit operator ceiling, if any;
5. effective CPU divided by live outer demand;
6. independent work-item count;
7. proportional useful-work capacity;
8. optional stage ceiling;
9. per-task memory capacity.

The first equal minimum in that order supplies the diagnostic limiting reason.

## 6. CPU and outer-demand behavior

Effective CPU discovery remains affinity/cgroup-aware and uses Apple
performance logical CPUs when available. This prevents a container with a
two-CPU quota from using the host's 32-CPU count and avoids treating Apple
efficiency cores as mandatory heavy-compute capacity.

Outer demand includes running and queued top-level Lumina conversions. Fair
share uses integer division with a minimum of one:

```text
cpu fair share = max(1, effective CPU // outer demand)
```

Examples before work and memory limits:

| Effective CPU | Outer demand | Per-task CPU ceiling |
| ---: | ---: | ---: |
| 8 | 1 | 8 |
| 8 | 2 | 4 |
| 32 | 1 | 32 |
| 32 | 2 | 16 |
| 32 | 4 | 8 |

If the demand snapshot is unavailable, Lumina retains the configured outer
pool size as its fail-closed fallback rather than assuming it is alone.

## 7. Memory behavior

Memory remains a first-class ceiling. When a stage supplies an incremental
worker estimate:

```text
headroom = max(1 GiB, 10% of currently available memory)
per-task memory = max(0, available - headroom) / outer demand
memory workers = max(1, per-task memory / estimated worker bytes)
```

The percentage reserve prevents a high-memory workstation from being planned
right up to its current available-memory edge. It does not block scaling: a
64-GiB machine with 50 GiB currently available still retains 45 GiB after the
10% reserve.

If reliable available-memory telemetry is absent and a stage declares a byte
estimate, the plan remains serial. `psutil` is already a formal runtime
dependency, so this is an abnormal fallback rather than the normal clean
installation path.

Native vector execution continues to enforce a second admission boundary with
actual per-batch estimates. A large outlier drains the window and runs through
the unchanged serial path; it does not force unrelated cheap batches or the
whole SVG to stay serial.

## 8. Stage adoption

### 8.1 Raster S07

- no stage worker constant;
- one independent item per material mesh;
- total-work threshold remains the current full-matrix cell gate;
- each worker receives the unchanged shared input and produces one unchanged
  mesh result;
- the owner thread still applies transforms, colors, names, and scene insertion
  in material-ID order.

With 32 effective CPUs, one outer task, ample memory, and 12 selected
materials, the natural result is 12 workers, not 2, 8, or 32.

### 8.2 Vector material matching

- no stage worker constant;
- unique target colors remain the independent work signal;
- at least 32 colors are still required before parallel refinement;
- 16 colors of useful work are required per planned worker;
- the underlying refinement and coherence helpers still clamp again to their
  actual group/block counts and fixed total temporary-memory budget;
- results remain written back by original target row.

Examples with enough CPU and memory:

| New target colors | Useful-work ceiling |
| ---: | ---: |
| 0-31 | 1 (total-work gate) |
| 32 | 2 |
| 128 | 8 |
| 512 | 32 |

### 8.3 Native vector mesh

- no stage worker constant;
- semantic `(height, z_offset)` batch count is the independent work ceiling;
- existing minimum three batches and eight run groups remain;
- representative planning bytes use the upper median of all non-empty batch
  estimates, rather than the smallest fixed number of batches;
- the actual ordered window remains limited by selected workers, batch count,
  per-task memory, and each live batch's refined estimate;
- oversized batches and any parallel failure retain the exact serial fallback.

No semantic batch or run group is split or merged by this change.

## 9. High-end behavior examples

These examples are deterministic planner expectations, not performance claims:

| Machine/task state | Raster 12 materials | Vector 512 colors | Native 44 batches |
| --- | ---: | ---: | ---: |
| 8 CPU, one task, ample RAM | 8 | 8 | 8 |
| 32 CPU, one task, 64 GiB class | 12 | 32 | 32 |
| 32 CPU, two tasks, 64 GiB class | 12 | 16 | 16 |
| 32 CPU, four tasks, 64 GiB class | 8 | 8 | 8 |
| 32 CPU, one task, memory supports 7 | 7 | 7 | 7 |

The same formula therefore serves low-, middle-, and high-end machines. There
is no hardware-name table and no product-wide low ceiling.

## 10. Exactness and safety invariants

The implementation is rejected if worker allocation changes any of:

- matched RGB, height-identity RGB, material matrix, or solid mask;
- material identity, slot order, recipe values, or layer order;
- geometry grouping, triangulation, surface validation, or fallback decision;
- canonical oriented triangles, world-space instances, visual payloads, or
  bounds;
- decompressed 3MF members or GLB semantics under the existing reference gate.

Workers may compute only independent existing units. Owner-thread ordering and
commit behavior remain unchanged. No tolerance is relaxed and no quality mode
is added.

## 11. Verification

### 11.1 Deterministic planner matrix

Unit tests inject effective CPU counts of 8 and 32, outer demand of 1/2/4,
work counts above and below the proportional threshold, and memory ceilings
including seven workers. The tests must prove that no hidden stage cap truncates
an otherwise valid 12-, 16-, or 32-worker plan.

### 11.2 Stage adoption tests

- raster proves a 12-material plan reaches a 12-worker executor and preserves
  scene/material order;
- vector material proves 32/128/512 colors resolve to 2/8/32 before the
  underlying helper's own natural clamp;
- native proves a 32-worker plan is accepted only when at least 32 batches and
  the memory window support it, while ordered commit and oversized serial
  fallback remain exact.

### 11.3 Quality corpus

Run fresh serial and automatic references for the supplied vector and raster
assets. Material-archive cases must use approximately 8, 12, and 15 colors.
Every automatic report must match its external serial semantic reference.

### 11.4 Performance and RSS

The development Mac can verify regression safety and exactness but cannot prove
32-core speedup. A high-core performance claim requires a real 24/32-core,
64-GiB-class run of the existing profiler with:

- three fresh-process serial runs;
- three fresh-process automatic runs;
- BLAS/OpenMP/Accelerate helper pools fixed to one;
- cProfile disabled for acceptance timing;
- the serial report supplied as `--reference-report`;
- worker decision, warm median, peak RSS, and semantic hash retained.

Automatic mode is accepted only when semantics are exact. Any speed statement
must name the measured machine; simulated capacity tests establish scheduling
correctness only.

## 12. Rollback

Existing operational controls remain sufficient:

```text
LUMINA_RASTER_PARALLELISM=1
LUMINA_VECTOR_PARALLELISM=1
```

Positive values remain maximums. A problematic stage can also restore a
documented positive `hard_max_workers` without changing the shared policy or
the exact serial algorithm.
