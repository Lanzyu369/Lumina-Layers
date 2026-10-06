# Converter Single-Task Multicore Design

> Deployment update (2026-10-06): Docker support and the public-test bypass
> are retired. This historical record preserves earlier implementation and
> validation evidence; use [Runtime support](../../runtime-support.md) for current behavior.
> 部署更新：Docker 支持及公网测试访问旁路已移除；本文保留历史实现与验证记录，当前运行方式以上述说明为准。

**Date:** 2026-07-28

**Status:** Approved for implementation planning

**Branch:** `MOVIBALE/feat/converter-single-task-multicore`

## 1. Summary

Lumina Studio can run multiple converter requests through its outer
`ProcessPoolExecutor`, but a single complex vector or raster conversion still
contains long serial sections. This work will shorten one task's preview and
generate latency without reducing model quality.

The implementation will be profile-driven:

1. establish reproducible serial baselines;
2. remove repeated or unnecessarily scalar work;
3. add bounded threads only around independent work that releases the GIL;
4. consider a local spawn-based process stage only when measurements prove that
   threads cannot scale and serialization still leaves a material net benefit.

The highest-priority release gate is semantic output equivalence. Performance
improvements do not compensate for changed geometry, visible surfaces, colors,
material identity, layer order, holes, or export semantics.

## 2. Goals

- Reduce preview and generate latency for one complex SVG/vector task.
- Reduce preview and generate latency for one large high-fidelity raster task.
- Use the available cores inside a task while respecting the outer worker pool.
- Prefer lower algorithmic complexity, batching, indexing, and reuse over
  executor fan-out.
- Preserve a strict serial reference path through `parallelism=1`.
- Keep peak memory and process/thread counts bounded.
- Keep the implementation portable across macOS arm64, Linux x86_64, and
  Windows x86_64.
- Preserve all current V1, V2, and fallback behavior.

The preferred four-core target for complex inputs is at least 2x end-to-end.
This is an optimization target, not permission to change output quality. If the
measured serial fraction makes 2x impossible, the final report must state the
measured Amdahl limit, communication cost, achieved repeatable speedup, and the
next viable direction.

## 3. Non-Goals

- No change to sampling density, grid resolution, quantization budget, shape
  count, layer count, geometric tolerance, or material accuracy to manufacture
  a speedup.
- No removal of V1 exporters, V2 exporters, or runtime fallbacks.
- No production deployment, restart, or Ubuntu server mutation.
- No new heavy dependency such as Cython or another JIT unless the measured
  design cannot meet its goals without a separately approved follow-up.
- No broad rewrite of the converter pipeline.
- No user-facing parameter or UI unless operators must explicitly control the
  new parallelism policy.

## 4. Workload Corpus

### 4.1 Vector performance corpus

The primary vector workload is:

- `modeling_mode=VECTOR`
- `material_source=material_archive`
- target width near 299 mm
- 10 optical layers
- single-sided structure
- a balanced material palette described in section 4.3
- the supplied complex SVG with approximately 13,500 drawable elements and
  approximately 9,500 distinct style fill declarations

The two additional supplied SVG files are medium and small regression workloads.
Existing hole, overlap, clipping, outline, puzzle, backing, and native-vector
fixtures remain correctness coverage.

### 4.2 Raster performance corpus

The primary raster workload is:

- `modeling_mode=HIGH_FIDELITY`
- `material_source=material_archive`
- target width near 299 mm when the 16 GiB development host can run it without
  swapping or unsafe memory pressure
- 10 optical layers
- single-sided structure
- the same balanced material-palette policy used by the vector workload

The supplied raster images cover:

- highly detailed continuous-tone artwork;
- large smooth gradients and luminous effects;
- large flat regions with sharp graphic edges;
- repeated colors and dense local detail;
- portrait, square, and tall aspect ratios.

`PIXEL` mode is a secondary regression workload for hard edges, repeated colors,
and small-task overhead. Traditional LUT-backed high-fidelity and pixel cases
remain regression coverage even when the main optimization target is the
material-archive path.

If 299 mm causes the development host to swap, a smaller diagnostic size may be
used for iteration. It cannot replace the final 299 mm measurement or be
reported as production-scale acceptance.

### 4.3 Material archive palette

The main material archive palette contains approximately 12 selected colors.
It must include:

- white and black or the closest valid base/dark pair;
- red, yellow, blue, green, cyan, and magenta families where valid calibrated
  materials are available;
- at least two nearby colors that make candidate discrimination non-trivial;
- a mix of light, mid-tone, and dark materials.

Boundary measurements use 8-color and 15-color palettes. The benchmark manifest
records material identifiers and order, but it must not copy private user
archives or machine-local paths into committed artifacts.

## 5. Development Environment

The confirmed development host is:

- macOS 26.5.2, arm64
- Apple M5
- 10 visible CPU cores: 4 performance and 6 efficiency cores
- 16 GiB memory
- Docker and Colima not running during initial native-Python measurements

The project environment will use an arm64 Python 3.12 virtual environment.
Before baselining, the report records:

- exact Python executable and architecture;
- NumPy, Shapely, Trimesh, SciPy, OpenCV, Pillow, Numba, and psutil versions;
- NumPy/BLAS build information;
- visible CPU count and relevant thread environment variables;
- native V2 extension availability.

Rosetta or mixed-architecture dependencies invalidate performance results.

## 6. Parallelism Policy

### 6.1 Configuration

Two backward-compatible environment controls are introduced:

- `LUMINA_VECTOR_PARALLELISM`
- `LUMINA_RASTER_PARALLELISM`

Accepted values are a positive integer or `auto`. Unset means `auto`. Invalid
values emit one actionable structured warning and fall back to `auto`.

The effective task-local budget is bounded by:

- the requested value;
- visible CPU count;
- configured outer `LUMINA_MAX_WORKERS`;
- number of independent work items;
- the stage's estimated temporary-memory cost;
- a small-work threshold that keeps tiny tasks serial.

The auto policy reserves a fair CPU share for each possible outer worker rather
than letting every request consume all visible CPUs. Explicit benchmark values
1, 2, 4, and 8 override auto within the same safety bounds.

### 6.2 Execution rules

- `parallelism=1` runs the serial reference implementation.
- A converter task runs only one inner executor at a time.
- A stage cannot create an executor from within another inner executor.
- BLAS/OpenMP limits remain at one thread unless a separate measurement proves a
  safe alternative.
- Read-only NumPy arrays may be shared by threads; worker functions do not mutate
  shared `Scene`, Shapely, cache, or material objects.
- Tasks return `(stable_index, result)` and the coordinator restores original
  order before any scene or archive mutation.
- Scene construction, metadata assignment, export ordering, and cache commits
  remain on the owning thread.
- Executor construction is skipped when effective parallelism is one or the
  workload is below its measured break-even threshold.

### 6.3 Process fallback

A nested process stage is not the default design. It is allowed for one proven
pure-Python hotspot only when all of these are true:

- controlled threads do not scale;
- the process version materially beats the best threaded version after spawn,
  serialization, and cleanup costs;
- peak RSS remains within the documented memory budget;
- two concurrent outer tasks remain bounded;
- cancellation, timeout, worker exception, and session close leave no child
  process or temporary file behind.

Any process entry point is top-level and picklable, uses `spawn`, and receives
only compact arrays, scalars, or registered file paths. It does not receive a
Trimesh Scene, Shapely object graph, session store, or large nested dictionary.

## 7. Profile and Decision Flow

### 7.1 Evidence collection

Use both:

- a sampling profiler, launched around the target worker process; and
- a function-level profiler for cumulative time and call counts.

Add or reuse bounded stage timings to distinguish:

- source decode or SVG parse/flatten;
- clipping and geometry normalization;
- color deduplication and quantization;
- material-runtime construction and lookup;
- shape-to-material matching;
- preview rasterization;
- raster voxel and mesh construction;
- vector mesh construction;
- 3MF export;
- V1/V2 GLB export;
- cache serialization and process transfer.

The profiler report ranks cumulative wall time and percentage, not call count
alone.

### 7.2 Optimization order

For each confirmed hotspot:

1. eliminate repeated work;
2. deduplicate colors, recipes, or equivalent geometry;
3. replace Python scans with NumPy, KD-tree, STRtree, Shapely 2.x vectorized
   operations, or existing native batch APIs;
4. reuse preview analysis in generate when the full semantic cache key matches;
5. measure bounded threads around independent GIL-releasing calls;
6. measure the process fallback only if section 6.3 applies.

Each candidate change completes its own red-green-refactor cycle and quality
gate before another candidate is layered on top.

## 8. Candidate Vector Boundaries

Profiling decides which candidates are implemented. The intended boundaries are:

- group shapes by stable source-fill identity and solve each unique color once;
- batch material candidate lookup instead of scanning every material recipe for
  every shape;
- avoid repeating parse, flatten, clip, or material solve between preview and
  generate when the existing cache artifact is semantically valid;
- use existing native batch clipping/meshing before introducing Python
  executors;
- parallelize independent color groups, geometry components, or mesh chunks only
  when their native calls release the GIL;
- keep all result assembly ordered by original shape and layer identity.

Vector cache keys include at least:

- source content digest, not only mtime;
- target dimensions and SVG sampling parameters;
- material identifiers and order;
- layer count, layer height, substrate, and color mode;
- structure, flip, backing, outline, puzzle, relief, coating, and relevant
  geometry settings;
- cache schema and implementation version.

Corrupt, old, incomplete, or mismatched cache artifacts are ignored and rebuilt.

## 9. Candidate Raster Boundaries

Profiling decides which candidates are implemented. The intended boundaries are:

- keep decode, filtering, quantization, unique-color extraction, and material
  lookup batched in native or NumPy code;
- preserve bit-identical `matched_rgb`, `material_matrix`, and `mask_solid`;
- replace the existing hard-coded S07 material thread count with the bounded
  raster policy while keeping deterministic material order;
- evaluate S11 per-color or per-layer mesh construction as independent threaded
  work, but mutate `trimesh.Scene` only after ordered collection;
- reuse preview material solutions during generate only through the existing
  session/file lifecycle and a complete semantic key;
- avoid allocating one full image- or layer-sized copy per thread;
- keep tiny high-fidelity and pixel workloads serial below measured break-even
  thresholds.

OpenCV, NumPy, Numba, Rasterio, Manifold, and Shapely may already use native
code. The design will not add a Python thread around a native function unless a
controlled 1/2/4/8 experiment demonstrates wall-clock scaling without hidden
oversubscription.

## 10. Semantic Quality Gate

Quality equivalence is a release-blocking condition.

### 10.1 Exact array and identity checks

Serial and parallel paths must produce exact equality for:

- quantized colors where exposed by the workflow;
- `matched_rgb`;
- `material_matrix`;
- solid/transparent/backing masks;
- recipe rows and layer order;
- material identifiers, names, types, and slot order;
- replacement and reset state.

### 10.2 Geometry checks

Canonical semantic summaries compare:

- model-space bounds;
- connected-component and shell counts;
- hole and interior-ring preservation;
- watertightness and winding expectations;
- vertex/face degeneracy counts;
- surface area and enclosed volume where meaningful;
- backing, outline, coating, puzzle overlay, loop, and fridge-magnet identity;
- per-material geometry assignment;
- visible top/bottom orientation and layer heights.

Object, ZIP member, triangle, or compression ordering may differ. Canonicalized
geometry and material semantics may not. Numerical comparisons use the existing
pipeline precision and exporter tolerances; tolerances cannot be widened merely
to make a parallel result pass.

### 10.3 Export checks

3MF checks include material mapping, metadata, layer order, model bounds, and
slicer template identity. GLB checks include scene-node semantics, material
appearance, bounds, orientation, V1 fallback behavior, and V2 behavior.

Any newly missing shape, color, surface, hole, material, or metadata field fails
the quality gate regardless of timing improvement.

## 11. Error Handling and Resource Lifecycle

- A stage failure is reported through the existing domain/API error boundary.
- Expected worker exceptions are associated with the stable work item and do not
  silently drop output.
- Existing V1/V2 fallbacks remain available and observable through structured
  events.
- Timeout and cancellation stop accepting results and close the owned executor.
- A process fallback, if any, terminates and joins owned children within a
  bounded grace period.
- Temporary arrays or cache artifacts use registered paths and are deleted on
  failure, cancellation, timeout, session close, or normal lifecycle expiry.
- Preview/generate cache publication is atomic; partial or corrupt artifacts are
  never treated as valid.
- Final downloads remain ephemeral artifacts that survive source-session close
  according to the existing `FileRegistry` contract.
- No business `print(...)` statements are added.

## 12. Testing Strategy

### 12.1 TDD unit coverage

Write failing tests first for:

- environment parsing and automatic budget resolution;
- invalid configuration fallback and structured warnings;
- small-work serial thresholds;
- `parallelism=1` reference behavior;
- stable ordered aggregation from out-of-order futures;
- worker exception propagation;
- no nested executor creation;
- cache-key changes for every semantic input;
- stale, corrupt, old-version, and partial cache rejection;
- timeout/cancellation cleanup if a process fallback is adopted.

### 12.2 Equivalence coverage

Compare serial and parallel execution for:

- high-fidelity raster with Material Archive using 8, 12, and 15 materials;
- high-fidelity raster with a traditional LUT;
- pixel mode with Material Archive and a traditional LUT;
- vector Material Archive and traditional LUT;
- single-sided, double-sided, and flipped structures;
- holes, overlaps, clipping, transparency, backing, outline, and coating;
- fridge magnet and puzzle workflows;
- 5-color extended mode;
- V1 fallback and V2 exporters;
- preview-to-generate reuse and cache invalidation;
- session close before final download fetch.

Existing frozen raster/golden tests continue to require bit-identical core
arrays.

### 12.3 Performance coverage

For representative workloads, measure:

- serial baseline;
- optimized `parallelism=1`;
- `parallelism=2`;
- `parallelism=4`;
- `parallelism=8`;
- two concurrent outer tasks.

Record cold run, at least three repeated runs, warm median, p90, CPU utilization,
peak RSS, thread count, child-process count, total preview/generate time, stage
times, and export times.

Small inputs and `parallelism=1` must not show a repeatable performance
regression. A measured regression above normal run-to-run noise blocks the
candidate until explained or removed.

## 13. Verification Commands

The exact focused test paths depend on adopted hotspots, but final verification
includes:

```text
python -m pytest <new and directly related backend tests> -v
python scripts/run_vitest.py run <related frontend tests>
python scripts/run_smoke_tests.py
python scripts/log_quality_check.py --mode fast
```

Logger-touching changes additionally run:

```text
python -m pytest tests/test_logging_exception_governance_unit.py tests/test_structured_logging_unit.py tests/test_logger_unit.py -v
```

Long commands receive explicit timeouts. The Vitest wrapper is mandatory. Full
suite scope is selected from the final risk surface rather than skipped solely
for duration.

## 14. Delivery Boundary

Mac development ends with:

- hotspot ranking and profiler evidence;
- code and configuration summary;
- serial/parallel equivalence evidence;
- 1/2/4/8 performance and resource tables;
- small-input and two-task concurrency results;
- test command outputs and timeouts;
- recommended production environment values;
- known limits and remaining risk;
- a proposed Ubuntu canary and rollback procedure.

No Ubuntu canary, production server, deployment, restart, push, or pull request
is performed without separate user authorization.
