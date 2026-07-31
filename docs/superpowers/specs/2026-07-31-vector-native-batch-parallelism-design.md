# Vector Native Deterministic Batch Parallelism Design

**Date:** 2026-07-31

**Status:** approved delegated direction; revised after semantic and memory audits

**Branch:** `MOVIBALE/feat/vector-native-mesh-throughput`

**Dependency:** PR #540 / commit `2a962c309c4f44955649586ef86d6622eea24bf5`

## 1. Outcome

Reduce the remaining SVG/vector mesh-extrusion bottleneck without changing
the current production-native model, geometry, material, recipe, layer,
visual, GLB, or 3MF semantics.

The implementation target is deliberately narrow:

1. keep the existing Shapely-versus-native surface validation unchanged;
2. isolate each existing `(height, z_offset)` native batch so its native
   extrusion and reference validation can run safely in a bounded thread;
3. collect every batch result before mutating shared meshes, caches, or stats;
4. commit results in the original insertion order, including all fallback
   decisions, then run the existing final buffer flush;
5. resolve 1–2 workers through the existing CPU/fair-share/memory policy.

The optimization changes scheduling, not geometry computation. A serial
worker count continues through the current code path.

## 2. Why the design was revised

The first written design proposed a C++ complete-surface guard and then
skipping Python surface validation. A semantic audit found that this would
weaken the quality boundary:

- the C++ guard can prove that a mesh matches the polygon set produced by
  Clipper2;
- the current Python guard independently reconstructs the expected geometry
  from the original Shapely objects;
- therefore the Python guard can detect a native union/close stage that loses
  or changes geometry, while a same-engine C++ self-check cannot.

The user's hard requirement is that model quality must not worsen. Exact
8/12/15-color corpus checks are necessary evidence, but they cannot turn a
weaker production invariant into an equivalent one for all inputs.
Consequently:

- `closed_extrusion_surface_guard_v1` is not added;
- Python validation is not skipped or sampled;
- validation tolerances are not widened;
- the emergency “force old validation” switch is unnecessary.

This rejected experiment remains documented so it is not rediscovered later
as an apparently safe shortcut.

## 3. Scope

### Included

- `core/vector_native_mesh.py`
- bounded scheduling through `core/task_parallelism.py`
- deterministic batch preparation, isolated computation, and ordered commit
- bounded native/fallback timing and worker fields on the existing timing
  payload; no additional INFO event
- existing native-mesh and multicore profilers as adoption sites
- 8-, 12-, and 15-color Material Archive verification
- matched-RGB and no-override vector generation
- current Python fallback, split-retry, and native-merged fallback behavior

### Excluded

- weakening or replacing Shapely cross-engine validation
- changing `native/clipper2_batch` geometry algorithms or capability contract
- SVG parsing, path flattening, and occlusion optimization
- raster S02/S07, GLB, or 3MF optimization
- material matching, region replacement, recipes, layer order, or naming
- changing outer worker scheduling or `LUMINA_MAX_WORKERS`
- processes, shared-memory executors, or child services
- server access, deployment, container restart, or environment mutation

This is a stacked local branch while PR #540 is open. It must not create a
follow-up PR until #540 is merged and this branch is rebased onto the merged
`origin/dev-refactor`.

## 4. Evidence and problem statement

Production builds already compile and enable `clipper2_batch` with
`LUMINA_VECTOR_NATIVE_MESH_VALIDATE_SURFACE=1`.

The adjacent 200 mm four-color diagnostic processed 43 run groups:

- 40 groups produced native meshes;
- 3 groups used the existing native-merged Python fallback;
- native execution: `2.202 s` across two measured native passes;
- Python surface validation: `2.547 s`;
- fallback work: `1.365 s`;
- packing: `0.120 s`;
- quality gate: PASS.

Component instrumentation across 80 surface checks showed:

| Surface-check component | Time |
|---|---:|
| Shapely expected geometry | `2.797 s` |
| Trimesh `mesh.area` | `0.278 s` |
| Numeric decision | `<0.001 s` |

Within the Shapely component, union and contour closing dominate. Removing
them would remove the independent quality check, so the safe lever is
concurrency.

The 43 groups are already organized into 15 independent `(height, z_offset)`
batches. The native extension releases the GIL, and read-only Shapely
operations also execute safely in independent worker threads. Exploratory
fresh computations on those exact batches produced:

| Experiment | 1 worker | 2 workers | 4 workers | Output |
|---|---:|---:|---:|---|
| Native calls only | `1.192 s` | `0.813 s` | `0.446 s` | identical SHA-256 |
| Native + unchanged surface validation | `2.610 s` | `1.553 s` | `0.990 s` | identical SHA-256 |

These are route-selection measurements, not final acceptance results. They
show that the hot region has useful independent work and that ordered
threaded computation can retain exact arrays and validation decisions.

A repeated nine-variant scheduling stress experiment was intentionally not
used as evidence because the diagnostic process ended before printing its
summary, plausibly from cumulative temporary allocation pressure. The
production design therefore uses one bounded executor, a conservative memory
estimate, and an explicit peak-RSS gate rather than repeated in-process
microbenchmarks.

## 5. Alternatives

### A. Deterministic isolated batch threads — selected

Prepare native inputs sequentially with the existing shared path cache. Each
prepared batch is immutable and contains:

- original batch index;
- height and Z offset;
- keys and original Shapely geometry lists;
- packed native paths and path counts;
- any no-path jobs that must use the old fallback.

Workers perform only independent computation:

- call the existing native module;
- validate returned arrays exactly as today;
- build the same per-group `trimesh.Trimesh`;
- run the same `_native_surface_area_matches` against original Shapely
  geometries;
- return outcomes and local timings without mutating shared output or caches.

The caller waits for all results, then commits batches and groups in their
original order. Split retry and every Python fallback remain on the caller
thread with the existing shared extrusion/path caches.

### B. Batch/vectorized Shapely reconstruction — rejected

Batch precision plus four-thread unions reduced one reference pass from about
`1.4 s` to `0.92 s`, but it required restructuring the current scalar
validation. Factoring unions by recipe was slower (`1.217 s`) and changed
area/perimeter results on some groups. This adds semantic risk for less gain
than scheduling the unchanged check.

### C. Same-engine C++ complete-surface guard — rejected

It can detect malformed faces but cannot independently detect a Clipper2
union/close result that diverges from the original Shapely geometry. It is not
equivalent to the current cross-engine guard and violates the quality-first
constraint if used to skip Python validation.

### D. Native-empty fallback redesign — deferred

The three fallback groups remain measurable, but changing them can alter
triangulation and mesh grouping. They are outside this scheduling-only change.

## 6. Architecture and data flow

### Current path

```text
build run groups
  -> for each (height, z) batch in insertion order
       -> pack paths
       -> native union/close/triangulate/extrude
       -> validate arrays
       -> Shapely cross-engine surface validation
       -> append or run fallback immediately
  -> flush native buffers
```

### Proposed path when workers > 1

```text
build run groups
  -> prepare all batches sequentially with the current path cache
  -> resolve bounded workers (CPU + fair share + memory + hard max 2)
  -> one ThreadPoolExecutor
       -> batch 0: native + unchanged validation -> immutable result
       -> batch 1: native + unchanged validation -> immutable result
       -> ...
  -> consume result[0], result[1], ... in original order
       -> append accepted meshes
       -> perform unchanged retry/fallback on caller thread
       -> aggregate bounded stats
  -> existing final native-buffer flush
```

When the resolver returns one, the current serial path runs without the
executor or preparation refactor.

### Worker policy

Use `resolve_task_parallelism("vector", ...)` with:

- work items equal to prepared native batches;
- a minimum batch/work threshold so tiny models stay serial;
- hard maximum `2`;
- conservative per-worker memory estimate, initially `384 MiB`;
- existing `LUMINA_VECTOR_PARALLELISM` override and
  `LUMINA_MAX_WORKERS` fair-share cap;
- `task_parallelism_worker_scope()` inside worker entry points.

Missing memory telemetry already fails closed to one worker because `psutil`
is a formal runtime dependency on the stacked base.

An exact 8-color diagnostic with four effective workers reduced wall time
further, but increased peak RSS from `731.14 MiB` to `849.12 MiB`
(`+16.1%`). That exceeds the `15%` acceptance gate, so four effective workers
are rejected even when explicitly requested. A request for four is clamped to
the hard maximum of two.

The supplied 13,970-source-geometry SVG exposed a second memory boundary.
Although two workers remained exact and reduced wall time, whole-process peak
RSS increased from `1,925.55 MiB` to `2,719.95 MiB` (`+41.3%`). Native batch
parallelism therefore stays serial above `3,000` source geometries. This
threshold is evaluated before any parallel batch preparation or executor
creation. The timing payload records the source-geometry count and a numeric
`0/1` limited flag; timing fields remain numeric so structured timing logging
cannot fail while converting the payload to floats.

### Determinism

Completion order is never output order. Results are indexed at preparation
time and committed only in original order. Workers do not mutate:

- `meshes_by_slot`;
- `extrude_cache`;
- shared fallback state;
- global stats;
- the path cache after preparation.

No regrouping, coalescing, retriangulation, or tolerance change is allowed.

## 7. Observability

Reuse the existing vector timing payload and profiler extraction. Add bounded
scalar fields only:

- resolved native batch workers;
- prepared/native/fallback batch and group counts;
- parallel compute wall seconds;
- summed native, mesh-conversion, surface-validation, and fallback seconds;
- existing fallback reason counters.

Do not emit paths, coordinates, color matrices, per-group records, or a new
INFO line. Summed worker CPU/wall components and outer parallel wall time must
have distinct names.

## 8. Output and quality invariants

The oracle is the current production-native path with
`LUMINA_VECTOR_PARALLELISM=1`.

The candidate must preserve exactly:

- matched RGB, pristine identity RGB, material matrix, masks, and recipes;
- material identifiers, slot ordering, and layer ordering;
- shape count, source/component order, and assignment count;
- per-material geometry and instance identity;
- oriented triangle records, winding, and bound face/vertex payloads;
- bounds, surface area, volume, watertightness, Euler number, and degenerate
  face count;
- scene nodes, material bindings, transforms, texture pixels, and colors;
- GLB bytes;
- every decompressed 3MF member after existing allowed ZIP/container and
  generated-source-name normalization;
- fallback reason, split-retry, and native-invalid decisions.

There is no tolerance in candidate-versus-serial artifact comparison.

## 9. Error handling and rollback

- Worker count one: current serial path.
- Executor creation/submission failure: discard uncommitted parallel results
  and run the current serial path.
- Unexpected worker failure: do not commit a partial result; rerun serial.
- Native exception inside a completed batch: preserve the current per-group
  native-call fallback.
- Invalid/empty native mesh: preserve split retry and merged/Python fallback.
- Surface mismatch: preserve current Python fallback.
- Profiler mismatch: fail the performance run and reject the candidate.

There is no database, cache-schema, API, artifact-format, or native-binary
migration. Rollback is `LUMINA_VECTOR_PARALLELISM=1` or code rollback.

## 10. Test and measurement design

### TDD sequence

1. Capture current serial 8/12/15-color external references before code edits.
2. Add failing tests for worker policy and bounded timing extraction.
3. Add a delayed fake native module that completes batches out of order.
4. Prove parallel output order, mesh arrays, validation decisions, fallback
   decisions, and stats equal the serial path.
5. Add exception and pool-failure tests proving no partial output is committed.
6. Add compiled-extension concurrency coverage with exact output hashes.
7. Implement isolated prepare/compute/commit and serial fallback.
8. Run exact serial-versus-two-worker checks and prove that a four-worker
   request is safely clamped to two.
9. Disable native batch parallelism above 3,000 source geometries and record
   the decision as numeric timing fields.

### Quality corpus

- 8-color Material Archive, matched-RGB override;
- 12-color Material Archive, recipe override and 200 mm matched-RGB reference;
- 15-color Material Archive, combined override;
- 8-color no-override control;
- holes, winding, native-empty, native-invalid, split-retry, merged-fallback,
  worker-error, and out-of-order fixtures.

### Performance method

- arm64 Python 3.12 and repository-built native extension;
- native and surface validation enabled;
- BLAS/OpenMP pools fixed to one;
- compare `LUMINA_VECTOR_PARALLELISM=1`, `2`, and the resolved production
  auto/maximum setting;
- set `LUMINA_MAX_WORKERS=1` only for the explicit single-task ceiling test;
- one cold plus at least three warm fresh-process samples;
- serial base and candidate interleaved where practical;
- report median, p90, RSS, RSS increase, threads, and children;
- no cProfile in wall-time samples.

## 11. Acceptance and stop conditions

All quality conditions are hard requirements.

Accept only if:

- all serial external semantic/artifact references match exactly at 2 workers
  and the accepted auto/maximum worker setting;
- 8-, 12-, and 15-color cases all pass;
- native+validation hot-region warm median improves by at least `40%`;
- `build_mesh` warm median improves by at least `15%`;
- 12-color end-to-end warm median improves by at least `7%`;
- p90 does not regress by more than `5%`;
- peak RSS does not increase by more than `15%`;
- small/no-override warm median does not regress by more than `5%`;
- no child process is created;
- peak thread count stays within the resolved executor bound;
- logging budgets and all fallback behavior remain valid.

Reject the candidate if any quality field differs, if ordered commit cannot
be proven, if memory exceeds the gate, or if the speedup requires validation
sampling, weakened tolerances, output regrouping, hidden multiprocessing, or
unbounded fan-out.

If the safe threaded path misses its measured gates, record `no_safe_gain`
and leave the serial path unchanged. The next design round should move to
first-preview parse/occlusion rather than weakening model validation.
