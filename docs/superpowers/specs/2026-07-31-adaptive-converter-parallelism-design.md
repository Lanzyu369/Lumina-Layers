# Adaptive Converter Parallelism Design

**Date:** 2026-07-31

**Status:** `approved_for_implementation`

**Branch:** `MOVIBALE/feat/adaptive-converter-parallelism`

**Stacked base:** `MOVIBALE/feat/vector-native-mesh-throughput@f01d3044`

**Upstream stack:** Draft PR #540 at `2a962c30`

## 1. Decision

Lumina will replace its current conservative, mostly static inner-worker
selection with a stage-boundary adaptive planner. The planner will select
parallelism from:

1. the CPU capacity actually available to the process;
2. the current outer worker-pool demand;
3. the number and complexity of independent work items;
4. current available memory and the existing 1 GiB headroom;
5. a stage-specific, evidence-backed maximum;
6. the existing operator-requested raster or vector ceiling.

The vector native-mesh path will also stop preparing every batch before
execution. It will keep only a bounded number of immutable batches in flight
and will commit completed batches in their original order.

This design changes scheduling only. It does not change geometry algorithms,
tolerances, recipes, material identity, layer order, fallback decisions,
surface validation, GLB construction, or 3MF construction.

## 2. Goal and hard acceptance rule

The goal is to improve single-conversion throughput on different user
machines without assuming that the development Mac's two-worker result is
universal.

The non-negotiable acceptance rule is exact model semantics:

- identical matched material and recipe arrays;
- identical material slots and bottom-to-top layer order;
- identical native acceptance and fallback decisions;
- identical canonical oriented triangles and world-space instances;
- byte-identical GLB where the existing serial-reference gate requires it;
- identical decompressed 3MF members, with only the existing generated source
  filename canonicalization;
- no relaxed tolerance, disabled validation, reordered output, or
  quality-dependent fast mode.

Any candidate that is faster but fails one of these checks is rejected.

## 3. Evidence and motivation

The current shared policy in `core/task_parallelism.py` already has the right
safety ingredients:

- CPU, work-item, work-unit, stage, and memory ceilings;
- a one-worker fallback when memory telemetry is unavailable;
- a 1 GiB available-memory reserve;
- independent raster and vector operator ceilings;
- an outer-worker fair-share ceiling;
- a nested-worker guard that forces inner calls to serial execution.

The current native-mesh implementation in `core/vector_native_mesh.py` also
preserves deterministic output by preparing shared state on the owner thread,
computing immutable batches in workers, and committing in original order.

The remaining limitations are:

- `os.cpu_count()` does not reliably express CPU affinity, cgroup quota, or
  heterogeneous Apple Silicon performance cores;
- outer fair share is based only on the configured maximum process count, not
  current pool demand;
- native mesh is permanently capped at two workers because four workers
  exceeded the prior peak-RSS gate on one 16 GiB Mac;
- more than 3,000 source geometries creates a hard serial cliff even when the
  actual packed workload would fit safely;
- the native path prepares all batches before starting the executor, which
  unnecessarily raises the live working set on extreme SVGs;
- the native per-worker memory estimate is constant and cannot distinguish
  simple geometry from path-heavy geometry.

Prior accepted measurements remain the baseline:

| Workload | Serial | Two workers | Accepted result |
| --- | ---: | ---: | --- |
| 200 mm, 12 colors, end to end | 18.536 s | 15.686 s | 15.4% faster, exact |
| 200 mm, native + validation | 6.196 s | 3.433 s | 44.6% faster, exact |
| 40 mm, 8 colors, end to end | 4.205 s | 3.715 s | 11.7% faster, exact |
| 40 mm, native + validation | 0.809 s | 0.446 s | 44.9% faster, exact |

Four workers were exact on the diagnostic case but grew peak RSS by 16.1%.
Unrestricted two-worker batching on the supplied starry SVG was exact and
faster, but grew peak RSS by 41.3%. The adaptive implementation must remove
the avoidable all-batches-live working set before reconsidering either mode.

## 4. External design references

The design follows patterns already used by maintained open-source media and
geometry software:

- PrusaSlicer treats an explicit thread count as a maximum and uses TBB's
  affinity-aware available concurrency.
- Blender leaves default scheduling to TBB and applies a global maximum only
  for an explicit override.
- libvips limits tiny images by tile count, prefers performance cores on Apple
  Silicon, and grows or shrinks its pool according to useful work and
  contention.
- FFmpeg limits automatic slice threads by both process-visible CPUs and
  available slice work.
- OpenImageIO recommends disabling inner fan-out when an application already
  has outer concurrency.
- darktable, ImageMagick, and GDAL manage memory/cache budgets separately from
  thread ceilings and reduce working-set size rather than treating thread
  count as the only memory control.

The relevant primary references are:

- <https://github.com/prusa3d/PrusaSlicer/blob/b028299c770b8380ee81c921a2867d522f288123/src/libslic3r/Thread.cpp#L237-L246>
- <https://github.com/blender/blender/blob/d13bbc114494f05716f60f9a5b63299c3ac63349/source/blender/blenlib/intern/task_scheduler.cc#L36-L54>
- <https://github.com/libvips/libvips/blob/2ff898f0a1637c45d15db532a7fbe2d30cc99aac/libvips/iofuncs/thread.c#L160-L204>
- <https://github.com/libvips/libvips/blob/2ff898f0a1637c45d15db532a7fbe2d30cc99aac/libvips/iofuncs/threadpool.c#L485-L524>
- <https://github.com/libvips/libvips/blob/2ff898f0a1637c45d15db532a7fbe2d30cc99aac/libvips/iofuncs/threadpool.c#L645-L690>
- <https://github.com/FFmpeg/FFmpeg/blob/5f832b7b3fd4cb8daf9bb64373230809c246bd84/libavcodec/pthread_slice.c#L112-L146>
- <https://openimageio.readthedocs.io/en/v3.1.14.0/imageioapi.html#global-attributes>
- <https://docs.darktable.org/usermanual/development/en/special-topics/mem-performance/>
- <https://imagemagick.org/architecture/>
- <https://gdal.org/en/stable/user/configoptions.html#performance-and-caching>

## 5. Alternatives

### A. Hardware-count formula only

Replace `os.cpu_count()` with a better CPU probe and keep the rest of the
current formula.

Advantages:

- smallest implementation;
- low regression risk;
- improves affinity and container behavior.

Disadvantages:

- does not react to current outer demand;
- retains the 3,000-geometry serial cliff;
- retains all-batches-live memory growth;
- cannot safely justify four native workers.

This is insufficient.

### B. Stage-boundary adaptive planner plus bounded in-flight work

Resolve an immutable parallelism plan at each heavy stage boundary. Feed it
machine capacity, current outer demand, workload complexity, memory, and
operator ceilings. Limit native preparation/submission to a small ordered
window.

Advantages:

- adapts to machine and workload without changing algorithms;
- reduces memory before raising worker limits;
- preserves existing serial fallback and deterministic commit;
- can be tested with injected capacity/demand snapshots;
- reacts between stages without unstable CPU-percentage polling.

Disadvantages:

- a task already inside one native call is not forcibly resized when another
  request arrives;
- worker-pool demand needs a small cross-process, read-only signal;
- native batch cost estimation requires corpus calibration.

This is selected.

### C. Fully live, cross-process worker resizing

Create a centralized broker that grants and revokes CPU and memory permits
while stages are executing.

Advantages:

- strongest instantaneous fairness;
- closest to a general operating-system scheduler.

Disadvantages:

- requires shared synchronization or an IPC control service across spawned
  worker processes;
- complicates timeout, process recycling, crash recovery, and Windows support;
- cannot safely interrupt a native call already holding external-library
  state;
- materially expands the change beyond the proven converter scheduling
  boundaries.

This is deferred. The selected design adapts only at stage and batch
boundaries.

## 6. Scope

### In scope

- hardware-aware effective CPU discovery;
- a typed immutable parallelism plan;
- current outer-pool demand as a read-only planning input;
- preservation of all existing environment ceilings;
- adoption by raster S07 mesh generation;
- adoption by vector material solving;
- adoption by vector native-mesh batches;
- bounded native batch preparation and submission;
- replacement of the global 3,000-source hard cliff with per-batch complexity
  and memory admission;
- bounded diagnostic fields in existing timing payloads;
- exact semantic, artifact, performance, RSS, fallback, and cleanup tests.

### Out of scope

- a user-facing thread-count or performance setting;
- changing `LUMINA_MAX_WORKERS` semantics;
- changing geometry grouping or splitting one semantic run group;
- changing native triangulation, Shapely validation, or fallback algorithms;
- process-based inner fallback;
- GPU scheduling;
- continuous polling of CPU utilization;
- forcefully resizing an executor or interrupting a running native call;
- unrelated vector parse, occlusion, export, or UI optimization;
- server deployment or production environment changes.

## 7. Architecture

```text
WorkerPoolManager
  -> maintains bounded outstanding-task demand
  -> publishes an atomic, non-sensitive runtime demand snapshot
  -> submits the existing top-level worker with scalar/file-path context only

worker process
  -> enters task_parallelism_runtime_scope(demand_snapshot_path)
  -> heavy stage asks for AdaptiveParallelismPlan

AdaptiveParallelismPlan
  = min(
      operator-requested ceiling,
      effective CPU capacity / current outer demand,
      useful independent work,
      stage hard maximum,
      available-memory capacity,
    )

native-mesh execution
  -> owner prepares at most a bounded ordered window
  -> workers compute immutable existing batches
  -> owner consumes and commits by original index
  -> oversized individual batch drains the window and runs serially
  -> any parallel failure discards local output and reruns unchanged serial path
```

The core policy remains UI-agnostic. `api/worker_pool.py` publishes demand;
`core/task_parallelism.py` reads a narrow runtime snapshot and produces the
plan; the three existing call sites remain responsible for executor lifetime
and domain-specific work.

## 8. Effective CPU capacity

CPU capacity is discovered once per process and cached. The probe order is:

1. process CPU affinity where the platform exposes it;
2. Linux cgroup v2 CPU quota, intersected with affinity capacity;
3. Apple Silicon performance-core logical CPU count;
4. `os.cpu_count()` as the portable fallback.

The returned value is always at least one.

The implementation must:

- use direct APIs or argument-vector subprocess calls with an explicit timeout;
- never invoke a shell;
- treat probe failure as a normal fallback, not a request failure;
- expose an injection point for deterministic tests;
- avoid probing on every resolver call.

On the current development Mac, the expected snapshot is:

- 10 logical CPUs;
- 4 Apple performance-core logical CPUs;
- 16 GiB physical RAM.

The Apple performance-core result is the default CPU capacity for heavy
inner scheduling. Efficiency cores remain available to the desktop, API
process, operating system, and background work.

An explicit environment request remains a ceiling. It cannot exceed effective
CPU capacity, work, memory, or the stage maximum.

## 9. Outer-demand snapshot

`WorkerPoolManager` will maintain the number of submitted tasks that have not
yet delivered a result. This includes running and queued work.

The parent publishes only bounded control data:

- schema version;
- generation counter;
- outstanding task count;
- configured outer maximum;
- update monotonic timestamp.

The snapshot contains no request ID, session ID, filename, user parameter,
color, geometry, or secret.

The snapshot is written atomically to one pool-owned temporary path. Worker
entry context receives only that path, satisfying the existing cross-process
argument contract. Core planning reads the snapshot at each stage boundary.

Lifecycle requirements:

- create the snapshot before the process pool starts;
- update it under the existing pool lock before submission and in a `finally`
  block after success, timeout, cancellation, or failure;
- retain it across a pool restart;
- remove it during `WorkerPoolManager.shutdown()`;
- use a unique path for every manager instance so tests and multiple app
  instances do not collide.

If the installed snapshot is missing, malformed, wrong-versioned, or contains
an impossible count, planning fails closed to the existing configured
outer-worker fair share. Direct core/profile calls without an installed
snapshot also retain the existing environment-based behavior.

The design deliberately does not force a currently running native call to
shrink. A newly starting stage observes the latest demand. Transient overlap
is bounded by the existing stage hard maxima and ends at the next stage
boundary.

## 10. Parallelism plan

Add a typed immutable result while preserving the existing public
`resolve_task_parallelism(...) -> int` signature.

Conceptually the plan contains:

```text
AdaptiveParallelismPlan
  workers
  requested_ceiling
  effective_cpu_capacity
  outer_demand
  cpu_fair_share_ceiling
  work_item_ceiling
  work_unit_ceiling
  stage_ceiling
  memory_ceiling
  available_memory_bytes
  estimated_worker_bytes
  limiting_reason
```

`resolve_task_parallelism()` becomes a compatibility wrapper returning
`plan.workers`. Existing callers and tests that only need an integer remain
valid.

Resolution order:

1. nested worker scope returns one;
2. insufficient items or work units returns one;
3. normalize the operator request as today;
4. resolve effective CPU and outer-demand fair share;
5. sample available memory and subtract the existing 1 GiB headroom;
6. divide the remaining memory fairly across current outer demand;
7. apply the stage's per-worker estimate;
8. take the minimum of every ceiling;
9. return at least one with a stable limiting reason.

No CPU-percentage or load-average sample participates in correctness.

## 11. Native batch cost and bounded execution

### 11.1 Preserve semantic batches

The existing `(height, z_offset)` batches and run groups remain unchanged.
The scheduler may decide when a batch runs, but may not merge or split a
semantic run group.

### 11.2 Cost signal

Replace the global source-geometry cutoff with a monotonic batch cost estimate
based on data already needed by native packing:

- source geometry count;
- coordinate/path point count;
- ring and hole count;
- group count;
- expected input coordinate bytes;
- expected native vertex/face buffer bytes;
- fixed per-worker validation allowance.

All arithmetic is saturating and overflow-safe. The estimate is a safety
ceiling, not a claim of exact RSS.

Before packing, a cheap Shapely coordinate count provides the planning
estimate. After owner-thread packing, actual path/ring/point counts refine the
admission decision for that batch.

### 11.3 In-flight window

When `workers > 1`, keep at most:

```text
min(
  remaining batches,
  workers + 1,
  memory-budget-supported batches,
)
```

prepared or executing at once.

The owner thread:

1. prepares batches in original order with the existing shared path cache;
2. submits only while the window has capacity;
3. waits for the next original index;
4. commits that result through the existing commit/fallback code;
5. releases the prepared/computed batch references;
6. advances the window.

An individually oversized batch drains pending work, runs through the existing
serial path, commits, and then allows later safe batches to resume parallel
execution. One complex batch therefore does not force the whole SVG to serial.

### 11.4 Worker tiers

The scheduler supports 1, 2, and 4 native workers. Four is enabled in
production only if the final corpus proves all of the following:

- exact quality and artifact equivalence;
- at least 10% median end-to-end improvement over two workers on a workload
  large enough to select four;
- no more than 15% peak-RSS growth over the serial reference;
- no regression in fallback count or surface-rejection decisions;
- no small-workload regression beyond the accepted noise gate.

If four fails any gate, the shipped stage ceiling remains two. The adaptive
planner and bounded window still ship if they independently pass their gates.

## 12. Raster and vector material adoption

Raster S07 and vector material solving adopt the same plan without changing
their algorithms:

- raster work items remain material IDs;
- raster work units remain full-matrix cells;
- vector material work items remain unique fills/refinement groups;
- existing per-worker byte estimates remain until corpus evidence justifies a
  more precise replacement;
- existing worker scopes and owner-thread result application remain;
- existing stage hard maximum remains four;
- executor creation is still skipped for one worker.

Material-archive verification covers approximately 8, 12, and 15 selected
colors, matching the intended archive workflow range.

## 13. Determinism and failure handling

The following invariants are unchanged:

- workers receive immutable or worker-local data;
- shared caches, scenes, stats, and output lists are owner-thread state;
- completion order never becomes output order;
- fallback decisions run through the existing code;
- a parallel executor/collection/commit inconsistency discards local parallel
  output and reruns the unchanged serial path;
- missing optional telemetry reduces concurrency instead of changing output;
- nested Lumina parallelism resolves to one;
- BLAS/OpenMP pools remain one to prevent hidden fan-out.

New failure behavior:

- CPU probe failure falls back to portable CPU count;
- demand snapshot failure falls back to configured outer fair share;
- memory telemetry failure returns one when a byte estimate is required;
- batch-cost overflow classifies the batch as oversized and serial;
- demand snapshot cleanup failure is logged with actionable fields but does
  not corrupt conversion output.

No core path raises `HTTPException`; API boundaries retain existing error
translation.

## 14. Observability

Do not add a new INFO line. Reuse existing timing/debug payloads with bounded
scalar fields:

- effective CPU capacity;
- outer demand;
- selected workers;
- limiting reason;
- CPU fair-share ceiling;
- memory ceiling;
- native in-flight limit;
- largest estimated batch bytes;
- count of oversized serial batches;
- demand snapshot fallback flag;
- native parallel wall time and existing summed sub-stage times.

Do not record geometry coordinates, path data, filenames, colors, recipes,
request bodies, or per-batch records at INFO.

WARNING/ERROR events added for runtime-state or cleanup failures must include
`event`, `error_type`, `error_message`, and the non-sensitive runtime path or
probe label needed for diagnosis.

## 15. Verification and acceptance

### 15.1 Unit and property coverage

Capacity discovery:

- affinity narrower than host CPU count;
- Linux quota narrower than affinity;
- Apple performance-core preference;
- invalid or unavailable probes;
- minimum one CPU;
- cached discovery and deterministic injection.

Demand snapshot:

- increment before submit and decrement on every exit path;
- concurrent submissions;
- queued work included;
- timeout and broken-pool restart;
- unique manager paths;
- atomic reader behavior during updates;
- malformed/missing/wrong-version fallback;
- shutdown cleanup.

Planner:

- automatic and explicit ceilings;
- one/two/four tiers;
- current-demand fair share;
- work-item and work-unit thresholds;
- memory headroom and per-demand memory share;
- unknown-memory serial fallback;
- nested scopes;
- stable limiting reasons;
- compatibility integer API.

Native execution:

- bounded number of prepared/computed batches;
- original-order commit under out-of-order completion;
- path-cache behavior;
- one oversized batch surrounded by safe parallel batches;
- executor and commit failure serial recovery;
- exact native/fallback counters;
- no static global 3,000-source cliff.

### 15.2 Exact corpus

Run fresh-process serial, automatic, requested-two, and requested-four
comparisons for:

- 8-color matched-RGB override;
- 12-color recipe override;
- 15-color combined override;
- large native/fallback mix;
- no-override control;
- supplied starry extreme SVG;
- raster controls using supplied bitmap assets;
- material-archive 8/12/15-color workflows.

The external semantic/artifact reference gate is mandatory for every accepted
thread tier.

### 15.3 Performance and memory

- three fresh processes per timing mode;
- warm decision based on medians, not the fastest run;
- cProfile disabled for acceptance timing;
- BLAS/OpenMP fixed to one;
- record effective CPU, RAM, architecture, Python, NumPy, OpenCV, Shapely,
  Trimesh, psutil, and native-extension versions;
- record peak RSS and child-process count;
- retain the 15% peak-RSS growth ceiling;
- two-worker accepted workloads may not regress more than 5%;
- small serial workloads may not show a repeatable regression over 5%;
- four workers require the additional 10% end-to-end gain stated above.

### 15.4 Repository gates

Run focused task-parallelism, worker-pool, raster, vector material, native
mesh, vector branch, profiler, and exact corpus tests; logging governance;
fast log-quality workflow; Python compilation; `git diff --check`; and the
existing smoke gate appropriate to the touched backend paths.

Baseline failures must be reproduced on the stacked base and reported
separately. Thresholds and tests may not be weakened.

## 16. Rollout and rollback

Automatic planning remains the default. Existing controls retain their
meaning:

- `LUMINA_RASTER_PARALLELISM=1` disables raster inner parallelism;
- `LUMINA_VECTOR_PARALLELISM=1` disables vector inner parallelism;
- positive values are requested maxima, not guaranteed worker counts;
- `LUMINA_MAX_WORKERS` remains the outer process-pool ceiling.

No settings migration or UI persistence is required.

Rollback order:

1. set the affected workload ceiling to one;
2. if necessary, disable adaptive demand use and retain the improved hardware
   probe plus configured fair share;
3. if necessary, restore the native stage ceiling to two;
4. code rollback removes planning metadata and bounded scheduling while
   retaining the unchanged serial/native/fallback algorithms.

## 17. Implementation boundary

This specification is one focused implementation cycle because the generic
planner has three existing adoption sites and the bounded queue is required
to safely reconsider the native hard cap.

The implementation must not add a general live IPC resource broker. If
evidence later shows that stage-boundary demand adaptation is insufficient,
fully revocable cross-process leases require a separate design, plan, and
review cycle.
