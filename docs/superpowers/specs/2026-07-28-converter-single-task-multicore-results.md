# Converter Single-Task Multicore Results

**Date:** 2026-07-28

**Branch:** `MOVIBALE/feat/converter-single-task-multicore`

**Reference machine:** Apple M5, 10 visible CPUs (4 performance + 6
efficiency), 16 GiB RAM, arm64, macOS 26.5.2, Python 3.12.13

## Verdict

The change satisfies the release-blocking quality condition: no selected
parallel run changed model, geometry, material, recipe, layer, visual,
scene-instance, GLB, or 3MF semantics. The final selected raster/vector
comparisons used an external serial-reference gate rather than comparing only
repeated snapshots inside one process.

The complex vector workflow exceeds the preferred 2x end-to-end target:

- preview: 2.86x warm-to-warm at the selected two-worker setting;
- generate: 2.04x warm-to-warm and 2.08x by the three-run medians at the
  selected two-worker setting.

Most of the vector gain comes from exact repeated-work elimination and bounded
memory, not executor fan-out. The two-worker setting adds a smaller, repeatable
gain and has the best complete-generation latency/tail balance.

The raster workflow already used a fixed four-thread S07 pool before this work.
The new code therefore does not claim a new end-to-end 2x raster speedup. It
replaces that unconditional pool with workload-, outer-worker-, and
memory-bounded parallelism, makes tiny work serial, prevents nested Lumina
pools, and reduces the final quality-locked S07 mesh stage from 16.765 to
12.761 seconds. The corresponding whole conversion changed from 41.209 to
38.694 seconds (1.07x), so the end-to-end result is correctly reported as
near-neutral rather than 2x.

## Quality lock

The profiler's semantic snapshot is a hard gate. A timing win is rejected when
the snapshot differs.

The following values were exact, not tolerance-relaxed:

- `matched_rgb`, `material_matrix`, and `mask_solid` shape, dtype, and SHA-256;
- material slot names, identifiers, and stable order;
- recipe rows and bottom-to-top layer order;
- retained geometry count and material-to-geometry assignment;
- transformed model-space bounds, vertex/face counts, surface area, volume,
  watertightness, Euler number, and degenerate-face count;
- canonical triangle SHA-256 for every material geometry;
- scene-node instances, geometry/material identity, and world transforms;
- face/vertex colors, UV coordinates, texture pixels, and material factors;
- exact GLB file bytes and decompressed 3MF member content.

Triangle canonicalization preserves winding: it permits only cyclic vertex
rotation, never reversal. Large meshes are hashed in bounded 250,000-face
chunks without sampling or dropping triangles. Repeated identity instances
reuse an already-computed immutable geometry summary, while non-identity
instances are summarized after applying their world transform. Face and vertex
payloads stay bound to their oriented triangles, so face reordering is accepted
but color reassignment or winding reversal is not.

GLB files are byte-exact. For 3MF, the gate ignores ZIP container order,
compression, and timestamps, then hashes every decompressed member. All members
except `Metadata/model_settings.config` are byte-exact, including the 1.56-GB
`3D/Objects/object_1.model` raster member. The settings XML is canonicalized
only for attribute/whitespace order and the generated `source_file` filename;
all other XML attributes and values remain quality-significant.

The earlier 1/2/4/8 matrix used the first-generation hard snapshot and proved
exact arrays, recipes, slots, core geometry, and world geometry. The final
selected 1/2 comparisons below used the stricter v2 snapshot, which additionally
covers visuals, geometry-instance identity, and exported artifacts:

| Workflow | Serial total | Parallel total | Effective workers | v2 semantic SHA-256 | External match |
|---|---:|---:|---:|---|---|
| Raster generate | 41.209 s | 38.694 s | 2 | `eae6af4f…5601ca1` | exact |
| Vector preview | 96.950 s | 83.501 s | 2 | `142bb383…394d3f` | exact |
| Vector generate | 159.969 s | 152.689 s | 2 | `c9f230f7…752b9a` | exact |

The pre-change vector generation's first run also used a complete
first-generation snapshot and retained all 12 expected material geometries.
Two supplemental pre-change generation runs used `--timing-only` because
post-run hashing of that very large scene exceeded the command host's wall-time
allowance. Those two runs contribute timing only and are not counted as
independent quality evidence.

## Workload and environment

The primary corpus used the supplied
`145874854_p0_master1200.jpg` and
`梵高星空款式西森猫猫.svg` assets:

- 299 mm target width;
- 12 deterministic Material Archive colors;
- 10 optical/material layers at 0.08 mm;
- material grid resolution 64 and quantization setting 64;
- BLAS/OpenMP pools fixed to one thread;
- cProfile disabled during wall-time measurement.

Boundary profiles used deterministic 8- and 15-color Material Archive palettes.
No private archive or machine-local asset path is committed.

Runtime versions were NumPy 2.4.6, SciPy 1.18.0, Shapely 2.1.2, Trimesh
4.12.2, OpenCV 5.0.0, Pillow 12.3.0, Numba 0.66.0, and psutil 7.2.2.
NumPy used Accelerate BLAS/LAPACK. The optional `clipper2_batch` extension was
not available, so these results do not depend on it. Docker, Colima, and
Rosetta were not used.

For complex cases, each `r1`/`r2`/`r3` measurement ran in a fresh Python
process to avoid retained allocator state. The table's cold value is `r1`;
warm median is the median of `r2` and `r3` after OS file caches had warmed; P90
uses all three runs. Small cases ran three times in one process.

## Raster results

The pre-change row is the original fixed four-thread implementation. The
optimized 4- and 8-worker requests safely resolved to two workers on this
16-GiB host because the live-memory cap reserved 1 GiB of headroom.

| Configuration | Effective workers | Cold | Warm median | All-run P90 | S07 median | CPU median | Peak RSS | Quality |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| Pre-change fixed pool | 4 | 41.193 s | 36.599 s | 40.338 s | 16.052 s | 154.8% | 5,529.53 MiB | oracle |
| Optimized request 1 | 1 | 43.545 s | 41.485 s | 43.153 s | 18.589 s | 101.4% | 4,572.55 MiB | exact |
| Optimized request 2 | 2 | 37.946 s | 37.561 s | 37.998 s | 11.984 s | 171.9% | 6,737.31 MiB | exact |
| Optimized request 4 | 2 | 36.512 s | 37.221 s | 37.475 s | 11.824 s | 170.9% | 7,320.53 MiB | exact |
| Optimized request 8 | 2 | 35.974 s | 36.888 s | 36.987 s | 11.838 s | 170.7% | 7,602.31 MiB | exact |

A final adjacent paired check, after the pre-change three-run measurement,
recorded 36.703 seconds total and 12.004 seconds in S07 for optimized request 2,
with 5,621.14 MiB peak RSS. This is effectively equal to the pre-change warm
end-to-end median while making the mesh hotspot about 25% faster. The remaining
time is dominated by decode/color work, export, and GLB construction.

The final v2 quality pair gives the limiting factors directly. In the serial
run, only 15.701 of 41.209 seconds was parallelizable S07 mesh compute (38.1%).
Even an infinitely fast mesh-compute section therefore has an Amdahl upper
bound of about **1.62x** for this workload. With two workers, ideal S07 time
would be about 9.00 seconds after retaining the measured
transform/application work; actual S07 was 12.761 seconds. The approximately
3.76-second gap is the measured scheduling, owner-thread aggregation,
load-imbalance, and shared-memory contention cost. Summed worker compute time
also rose from 15.701 to 22.638 seconds, confirming that memory/cache
contention—not missing executor fan-out—is the current limit.

The achieved final-pair speedups are **1.31x for S07** and **1.07x
end-to-end**. The next viable raster direction is to reduce or safely
parallelize the still-serial decode/color stage (S02), then profile 3MF export
(S09) and GLB construction (S11). Increasing S07 workers alone cannot reach 2x
and is deliberately not the production default.

The old 52.668-second one-off baseline was retained as historical evidence but
not used for the final ratio because the new three-run baseline demonstrated
that it was machine-load sensitive.

### Raster color and concurrency boundaries

| Material colors | Effective workers | Cold | Warm median | Warm P90 | Exact |
|---|---:|---:|---:|---:|---|
| 8 | 4 | 2.397 s | 1.105 s | 1.110 s | yes |
| 15 | 4 | 3.044 s | 1.965 s | 1.969 s | yes |

Two simultaneous small raster tasks both remained exact. Their serial totals
were 6.402 and 5.625 seconds; under overlap their conversion timers were 5.354
and 5.136 seconds. Their individual peak-RSS sum was 1,647.41 MiB, maximum
thread count was 21 per process, and neither created a child process.

## Vector preview results

The supplied complex SVG contains approximately 13,496 drawable shapes,
14,010 matched shapes, and 9,503 unique fills.

| Configuration | Effective workers | Cold | Warm median | All-run P90 | Analyze SVG median | CPU median | Peak RSS | Quality |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| Pre-change | legacy | 243.097 s | 246.062 s | 248.450 s | not instrumented | 73.7% | 6,547.92 MiB | oracle |
| Optimized request 1 | 1 | 96.813 s | 95.206 s | 96.588 s | 92.515 s | 99.5% | 5,934.39 MiB | exact |
| Optimized request 2 | 2 | 84.537 s | 85.927 s | 86.193 s | 82.348 s | 114.1% | 5,324.67 MiB | exact |
| Optimized request 4 | 4 | 83.764 s | 83.976 s | 84.034 s | 80.720 s | 126.0% | 4,872.88 MiB | exact |
| Optimized request 8 | 4 | 92.788 s | 108.180 s | 108.758 s | 103.366 s | 123.2% | 3,652.52 MiB | exact |

Four workers produce the best isolated preview median, but only by about 2%
over two workers. Request 8 is hard-capped at four and showed a much worse
tail under system memory/swap pressure. The selected cross-workflow setting is
therefore two workers.

One final instrumented sample at each requested setting split `analyze_svg`:

| Request / effective | Total | Parse | Clip/occlusion | Fill dedup | Material solve |
|---|---:|---:|---:|---:|---:|
| 1 / 1 | 102.216 s | 11.373 s | 6.313 s | 0.0026 s | 80.553 s |
| 2 / 2 | 93.368 s | 11.497 s | 6.443 s | 0.0025 s | 71.518 s |
| 4 / 4 | 90.724 s | 12.124 s | 6.660 s | 0.0020 s | 68.079 s |
| 8 / 4 | 90.230 s | 11.305 s | 6.061 s | 0.0021 s | 69.082 s |

## Vector generation results

Every optimized generation run produced a complete 12-material geometry
snapshot exactly equal to the selected serial reference.

| Configuration | Effective workers | Cold | Warm median | All-run P90 | Material solve median | Mesh/assemble median | Peak RSS | Quality |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| Pre-change | legacy | 334.380 s | 334.287 s | 359.296 s | not instrumented | not instrumented | 6,894.89 MiB | oracle + timing-only supplements |
| Optimized request 1 | 1 | 164.375 s | 168.520 s | 169.110 s | 76.129 s | 134.489 s | 6,468.73 MiB | exact |
| Optimized request 2 | 2 | 157.731 s | 163.891 s | 165.791 s | 68.947 s | 126.620 s | 6,461.52 MiB | exact |
| Optimized request 4 | 4 | 163.012 s | 164.294 s | 165.355 s | 67.267 s | 126.973 s | 6,408.50 MiB | exact |
| Optimized request 8 | 4 | 158.727 s | 182.530 s | 189.037 s | 72.792 s | 134.476 s | 6,261.02 MiB | exact |

At two workers, median 3MF export was 8.936 seconds and median GLB export was
19.847 seconds. These exports remain serialized because stable material and
scene ordering is part of the quality contract.

The final v2 external-reference pair, after bounded-neighbour streaming and
visual checks were complete, measured 159.969 seconds at one worker and
152.689 seconds at two. Its material solve changed from 72.561 to 64.198
seconds, both runs had zero child processes, and every v2 semantic/artifact
field matched. This adjacent pair is the final quality gate; the three-run
table remains the less noisy performance comparison against the pre-change
implementation.

The optimized serial path is already almost 2x faster than the pre-change
path. It groups target rows by deterministic material subset, constructs each
immutable inverse-refinement workspace once, reuses its exact KD-tree and
candidate arrays, discovers coherence neighbours with an exact-threshold
KD-tree query, and computes candidate distances in exact bounded blocks.
Threads process independent immutable workspace groups; owner-thread writeback
restores stable row order.

During the final gate, the stricter visual validator found a pre-existing
malformed context scene after `Board` was merged into its selected backing
material: the merged mesh had fewer face-color rows than faces. The merge now
applies the selected material RGBA to every merged face. Geometry, material
slot selection, and Bambu 3MF mapping are unchanged; the in-memory visual state
is now complete and has a direct regression assertion.

### Vector color and concurrency boundaries

| Material colors | Effective workers | Cold | Warm median | Warm P90 | Exact |
|---|---:|---:|---:|---:|---|
| 8 | 1 | 2.624 s | 0.730 s | 0.748 s | yes |
| 15 | 1 | 2.859 s | 0.938 s | 0.942 s | yes |

These smaller SVG workloads deliberately remain serial because they do not
cross the 32-unique-fill threshold.

For two simultaneous vector tasks, the serial totals were 4.271 and 8.644
seconds. Under overlap, the individual conversion timers were 7.106 and
12.794 seconds; both snapshots remained exact, their peak-RSS sum was
1,015.16 MiB, and no child process was created. Aggregate completion remained
approximately equal to the serial sum rather than oversubscribing into a
failure or unbounded memory increase.

## Safety and rollback

- Raster and vector use independent overrides:
  `LUMINA_RASTER_PARALLELISM` and `LUMINA_VECTOR_PARALLELISM`.
- `auto` is bounded by visible CPUs, the outer-worker fair share, independent
  work items, a stage hard cap of four, a small-work threshold, live available
  memory, and 1 GiB reserved headroom.
- If available-memory sampling is unavailable or fails while a stage has a
  per-worker memory estimate, selection fails closed to one worker.
- A thread-local worker scope forces nested Lumina pool resolution to one.
- Invalid settings emit one actionable structured warning, once per distinct
  value, and fall back to automatic selection.
- Worker functions mutate no shared scene or output state. Results are applied
  in stable source/material order on the owner thread.
- Raster scene mutation, vector coherence cascading, 3MF export, and GLB
  export remain serialized.
- No nested process implementation was needed; every measured run reported
  zero child processes.

On this 10-core machine with the normal outer-worker cap of four, `auto`
resolves to two workers when memory permits. A production canary should keep
BLAS/OpenMP at one and use `auto` or explicitly set both task-local overrides
to `2`. Requests for 4 or 8 should not be the production default.

There are two rollback levels:

- For concurrency, memory, or tail-latency trouble, set both task-local
  overrides to `1`. `LUMINA_DISABLE_PARALLEL_MESH=1` remains an additional
  raster emergency switch.
- For any semantic or algorithmic issue, roll back this code/version. A
  one-worker override disables executor fan-out but intentionally retains the
  exact workspace reuse, streaming neighbours, and bounded top-K algorithm, so
  it is not an algorithm-version rollback.

No production host, container, service, or configuration was changed as part
of this work.

## Verification

- Final post-fix focused multicore, material, vector-export, and profiler
  regression: **240 passed**. This supersedes the earlier 211-test focused run.
- Backend full suite excluding the unavailable external performance-golden
  fixture: **4,869 passed, 37 skipped, 3 deselected, 21 failed**.
- The same 21 failures were reproduced at the unmodified base commit; they
  cover pre-existing error-copy, frozen-asset baseline, feedback relay,
  log-quality fixture, and mocked vector-preview issues. This branch adds no
  new full-suite failure.
- Frontend Vitest: **237 files passed; 2,356 tests passed and 1 skipped**.
- Smoke gate: **130 backend tests passed, 140 frontend tests passed, lint
  completed with 0 errors**. The 60 lint warnings are pre-existing warnings in
  untouched frontend files.
- Logging governance: **21 tests passed**.
- Fast structured-log workflow: **PASS**, with 14 INFO, 0 WARNING, 0 ERROR,
  no catch-all event, no unstructured line, and all endpoint budgets met.
- `tests/test_perf_golden.py` was excluded because its external
  `TCT.jpg`, `Giant_Pumpkin.png`, and `tests/golden_baseline.npz` fixtures are
  absent. No replacement baseline was generated.
- Python compilation, `git diff --check`, UTF-8 decoding, and mojibake scans
  passed for all touched source, test, and result-document files.
