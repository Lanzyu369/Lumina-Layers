# Vector Override ROI Parallelism Implementation Plan

> Deployment update (2026-10-06): Docker support and the public-test bypass
> are retired. This historical record preserves earlier implementation and
> validation evidence; use [Runtime support](../../runtime-support.md) for current behavior.
> 部署更新：Docker 支持及公网测试访问旁路已移除；本文保留历史实现与验证记录，当前运行方式以上述说明为准。

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `executing-plans` to implement this plan task-by-task. Keep every quality
> comparison exact and stop before push or PR creation for user review.

**Goal:** Reduce vector generation time when cached matched-RGB or recipe edits
must be projected back into native SVG shapes, while preserving model geometry,
shape/component ownership, holes, color votes, material recipes, GLB bytes, and
decompressed 3MF semantics exactly.

**Architecture:** Add explicit generate-stage timings first. Replace the
per-component full-canvas mask with an integer-coordinate, conservatively
bounded pixel ROI that uses the same OpenCV fill operations and the same stable
vote/tie rules on array slices. Measure optimized serial before considering
bounded threads; if threads do not add a repeatable 10–20% win without worse
tail latency or memory, keep the serial ROI implementation.

**Tech Stack:** Python 3.12 arm64, NumPy, OpenCV, Shapely, SciPy KD-tree,
Trimesh, pytest, psutil, existing converter profiling and structured logging.

**Execution status:** `locally_verified_on_latest_origin_with_tooling_caveat`.
Tasks 1–5 are
implemented with independent base evidence. Task 6 was measured and rejected
because 2/4/8 ROI threads were slower than optimized serial; no new ROI
executor remains. Task 7's 8/12/15-color, no-override, exact export, memory,
and staggered-concurrency matrix is complete, while the same-name/same-second
export collision is documented as an existing follow-up risk. Task 8's result
report, second independent review, and final functional gates are complete.
The Smoke wrapper's backend/frontend suites pass, but its pnpm auto-install is
blocked by the base repository's existing build-script permission
configuration; direct ESLint passes. A separate clean arm64 Python environment
installed both Docker runtime requirement files, passed the Prompt-specified
quality suite, and produced exact 8/15-color V2 GLB + 3MF artifacts. After user
approval, the single implementation commit was rebased without conflict onto
current `origin/dev-refactor@2ce7b6c9`; submission gates are rerun before
publishing the Draft PR. See
`docs/superpowers/specs/2026-07-30-vector-override-roi-parallelism-results.md`.

---

## File Map

- Modify: `core/pipeline/vector_branch.py`
  - expose `matched_rgb_override_s`, `recipe_override_s`, and `build_mesh_s`
    inside the existing `vector_generate_timings` record without adding INFO
    events.
- Modify: `core/vector_engine.py`
  - isolate integer rasterization, calculate conservative component ROIs, and
    run the existing vote/material projection against local array views.
- Modify: `scripts/profile_converter_multicore.py`
  - support cached matched-RGB override fixtures and report component count,
    full-canvas pixel work, ROI pixel work, reduction ratio, and stage time.
- Modify: `scripts/log_quality_check.py`
  - keep the fast-mode mock worker aligned with the timed submission contract.
- Modify: `tests/test_vector_matched_rgb_overrides_unit.py`
  - add a frozen full-canvas reference oracle and exact ROI parity corpus.
- Modify: `tests/test_converter_multicore_profile_unit.py`
  - cover profiler inputs, metrics, and sanitized output.
- Modify: `tests/test_log_quality_check_unit.py`
  - prove the fast logging gate can execute preview through timed submission.
- Modify: `api/worker_pool.py`,
  `api/routers/converter/preview.py`,
  `api/routers/converter/generate.py`,
  `api/schemas/responses.py`
  - split endpoint-to-enqueue, queue wait, worker execution, result delivery,
    and post-worker response time without adding INFO events.
- Modify: `tests/test_worker_pool_unit.py`,
  `tests/test_converter_preview_unit.py`,
  `tests/test_converter_generate_unit.py`,
  `tests/test_performance_timing_response_unit.py`
  - prove bounded process-pool timing metadata and DEBUG-only logging.
- Modify when threading is retained: `core/task_parallelism.py`,
  `tests/test_task_parallelism_unit.py`
  - reuse the memory/fairness policy rather than introducing an unbounded pool.
- Create:
  `docs/superpowers/specs/2026-07-30-vector-override-roi-parallelism-results.md`
  - record environment, before/after evidence, quality hashes, retained and
    rejected experiments, and remaining bottlenecks.

## Hard Quality Gates

- `matched_shapes` order, geometry WKB, compound-vs-split structure, fill,
  matched RGB, height-identity RGB, recipe, and `original_recipe` are exact.
- Polygon holes and mask/background behavior are exact.
- Dominant-color and dominant-material ties retain the current stable
  `np.unique` ordering.
- Strict validation and no-op/global-replacement behavior are unchanged.
- Preview arrays are byte-identical.
- GLB export bytes and decompressed 3MF members/metadata are exact against the
  pre-change reference report.
- Requested worker count `1` is the optimized serial oracle and creates no
  executor.
- Materials use deterministic 8-, 12-, and 15-color archives.
- Any speed experiment that changes a hard-gate output is discarded.

## Task 1: Add exact generate-stage observability

- [x] Add a failing branch test that requires these keys on successful
  generation, including zero-valued absent stages:
  `analyze_svg_s`, `matched_rgb_override_s`, `recipe_override_s`,
  `build_mesh_s`, `mesh_total_s`, `export_3mf_s`, `export_glb_s`, and
  `vector_branch_total_s`.
- [x] Measure cached-array load plus matched-RGB projection under
  `matched_rgb_override_s`.
- [x] Measure recipe-mask load plus recipe projection under
  `recipe_override_s`.
- [x] Measure only `build_mesh(...)` under `build_mesh_s`; retain
  `mesh_total_s` as the backward-compatible aggregate.
- [x] Add the three fields to the existing DEBUG message and existing INFO
  timing payload; do not add an INFO line.
- [x] Run the focused branch test and logging governance tests.

## Task 2: Freeze full-canvas behavior as a reference

- [x] Build a test-only reference projector from the current implementation,
  using the same full `(height, width)` OpenCV mask.
- [x] Add seeded cases covering Polygon, MultiPolygon, GeometryCollection,
  holes, off-canvas/clipped coordinates, subpixel coordinates, empty masks,
  disconnected components, equal RGB counts, equal material-row counts,
  identity RGB, short recipes, no-op, global replacement, and divergent
  component splitting.
- [x] Compare the complete normalized shape record, not only the changed count.
- [x] Confirm the characterization corpus passes before changing production
  rasterization.

## Task 3: Implement exact serial ROI projection

- [x] Add a failing unit test for a private ROI rasterizer that expects:
  integer conversion identical to the legacy path, a clipped conservative
  `(y_slice, x_slice)`, and a local boolean mask matching the corresponding
  full-canvas slice byte-for-byte.
- [x] Convert exterior and hole coordinates to `int32` once using the current
  scale and Y flip.
- [x] Derive a conservative one-pixel-padded ROI from those unmodified integer
  points, clip only the ROI to canvas bounds, shift points by the ROI origin,
  and call the same `cv2.fillPoly` sequence.
- [x] Slice `mask_solid`, matched RGB, identity RGB, and material matrix to the
  ROI before boolean operations and voting.
- [x] Preserve stable component iteration, owner selection, record copying,
  and split/compound reconstruction exactly.
- [x] Expose bounded diagnostics for component count, full-canvas pixel work,
  ROI pixel work, ROI reduction ratio, and maximum ROI size without changing
  the public function return type.
- [x] Run the complete matched-RGB override test file after every semantic
  change.

## Task 4: Measure serial ROI and profile remaining work

- [x] Extend the profiler tests first so a generate case can load frozen
  matched-RGB, mask, identity, and material-matrix artifacts.
- [x] Capture an exact pre-change semantic reference report.
- [x] Run optimized serial on the same input with
  `LUMINA_VECTOR_PARALLELISM=1` and BLAS/OpenMP threads fixed at one.
- [x] Record cold, warm median, p90, peak RSS, override-stage time, component
  count, ROI pixel work, and semantic reference equality.
- [x] Retain serial ROI only if exact gates pass and the override stage is
  materially faster; target at least 3× for the production-like case.

## Task 5: Evaluate micro-optimizations one at a time

- [x] Benchmark packed `uint32` RGB voting against the retained ROI baseline.
- [x] Benchmark per-call Lab/KD-tree lookup caching against the retained ROI
  baseline.
- [x] Benchmark safe grouping/batching only if the profile still points there.
- [x] For each experiment, run the characterization corpus and record its own
  timing; revert experiments that do not produce a repeatable gain.

## Task 6: Evaluate bounded ROI threading — measured and rejected

- [x] Run identical `1/2/4/8` inputs and exact semantic comparisons.
- [x] Reject the executor path because 2/4/8 did not beat optimized serial and
  raised memory/thread pressure.
- [x] Leave worker-policy, owner-thread commit, and `auto` executor changes
  unimplemented because the measurement gate rejected threading.

## Task 7: End-to-end quality and concurrency matrix

- [x] Run 8-, 12-, and 15-material archive cases.
- [x] Run no-override, matched-RGB, recipe-only, and combined profiles; cover
  identity-RGB in the exact unit corpus.
- [x] Compare V1/V2 preview semantics, GLB bytes, canonical geometry, and
  decompressed 3MF members/metadata with the serial pre-change reference.
- [x] Run two concurrent outer conversion tasks and verify fair worker budgets,
  no nested oversubscription, bounded RSS, and unchanged outputs.
- [x] Run the existing relevant backend suite, logging gates,
  `scripts/log_quality_check.py --mode fast`, `git diff --check`, and UTF-8
  mojibake scan.

## Task 8: Report and review stop

- [x] Write the Chinese result document with exact commands, before/after
  tables, quality evidence, retained/rejected experiments, memory/tail results,
  and remaining bottlenecks.
- [x] Report whether the target was met. Label missing production-asset
  evidence as incomplete rather than inferred.
- [x] Stop for user review. Do not commit, push, open a PR, deploy, or mutate
  any server in this phase.
