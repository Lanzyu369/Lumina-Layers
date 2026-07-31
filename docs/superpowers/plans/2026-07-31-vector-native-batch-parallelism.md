# Vector Native Deterministic Batch Parallelism Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Parallelize independent native vector extrusion batches while
preserving the current Shapely cross-engine validation and exact serial
8/12/15-color artifacts.

**Architecture:** Keep the one-worker code path unchanged. For more than one
resolved worker, prepare immutable native batches sequentially, compute native
meshes and the existing surface checks in isolated thread tasks, then commit
accepted meshes and unchanged fallback decisions in original batch/group
order. Reuse the existing task-parallelism memory/fair-share policy.

**Tech Stack:** Python 3.12, ThreadPoolExecutor, Shapely 2, Trimesh, NumPy,
compiled Clipper2 extension, pytest, existing multicore semantic profiler.

---

## File map

- `core/vector_native_mesh.py`
  - prepare immutable batches;
  - resolve bounded vector workers;
  - compute native arrays and unchanged surface checks in workers;
  - commit results deterministically or rerun serial on infrastructure error.
- `core/pipeline/vector_branch.py`
  - expose bounded native batch timing fields in the existing payload.
- `tests/test_vector_native_mesh_unit.py`
  - worker policy, out-of-order completion, exact ordering, fallback, and
    compiled-extension concurrency tests.
- `tests/test_vector_branch_extraction_unit.py`
  - bounded field allowlist contract.
- `tests/test_converter_multicore_profile_unit.py`
  - profiler timing extraction contract.
- `docs/superpowers/specs/2026-07-31-vector-native-batch-parallelism-results.md`
  - exact quality, performance, memory, and adopted/rejected evidence.

No new shared module or native capability is introduced.

### Task 1: Capture the current serial oracle

**Files:**
- Read: `scripts/profile_converter_multicore.py`
- Create ignored artifacts under:
  `.scratch/vector-native-batch-parallelism/base-*`

- [ ] **Step 1: Confirm the baseline and production native module**

Run:

```bash
git status -sb
git rev-parse HEAD
.venv/bin/python scripts/build_native_extensions.py
.venv/bin/python -c \
  'import clipper2_batch; print(clipper2_batch.__file__); print(clipper2_batch.native_mesh_capabilities())'
```

Expected: branch is `MOVIBALE/feat/vector-native-mesh-throughput`, worktree is
clean after this plan is committed, and the module advertises only the
existing `triangulation_area_guard`.

- [ ] **Step 2: Run the focused pre-change native tests**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_build_native_extensions_unit.py \
  tests/test_vector_native_mesh_unit.py \
  tests/test_vector_native_mesh_corpus_profile_unit.py \
  tests/test_vector_engine_fixes_unit.py::TestFillRuleSubpathMerging \
  -q
```

Expected: PASS.

- [ ] **Step 3: Capture exact 8/12/15-color serial references**

Use the following common environment:

```bash
env \
  OMP_NUM_THREADS=1 \
  OPENBLAS_NUM_THREADS=1 \
  MKL_NUM_THREADS=1 \
  VECLIB_MAXIMUM_THREADS=1 \
  NUMEXPR_NUM_THREADS=1 \
  BLIS_NUM_THREADS=1 \
  LUMINA_MAX_WORKERS=1 \
  LUMINA_VECTOR_PARALLELISM=1 \
  LUMINA_VECTOR_NATIVE_MESH=1 \
  LUMINA_VECTOR_NATIVE_MESH_VALIDATE_SURFACE=1
```

Run `scripts/profile_converter_multicore.py` with:

| Case | Input | Width | Colors | Override | Output |
|---|---|---:|---:|---|---|
| 8 | `945695877_20260622_232544_vector.svg` | 40 | 8 | matched-rgb | `base-8-matched` |
| 12 | `945695877_20260622_232544_vector.svg` | 40 | 12 | recipe | `base-12-recipe` |
| 15 | `945695877_20260622_232544_vector.svg` | 40 | 15 | combined | `base-15-combined` |

For each case pass:

```text
--kind vector --phase generate --runs 1 --no-cprofile
```

Expected: exit 0 with complete semantic, GLB, and decompressed 3MF summaries.

- [ ] **Step 4: Capture the large 12-color serial reference**

Run the same profiler with:

```text
input: /Users/min/Downloads/mmexport1784271438721.svg
target width: 200
material count: 12
override scenario: matched-rgb
output: .scratch/vector-native-batch-parallelism/base-12-large
```

Record total, build, extrusion, peak RSS, peak threads, and children.

- [ ] **Step 5: Capture the no-override serial control**

Run with:

```text
input: /Users/min/Downloads/梵高星空款式西森猫猫.svg
target width: 136
material count: 8
override scenario: none
output: .scratch/vector-native-batch-parallelism/base-8-no-override
```

Expected: exit 0 with a complete serial reference.

- [ ] **Step 6: Confirm ignored artifacts did not dirty the worktree**

Run:

```bash
git status --short
```

Expected: no profiler artifact is tracked or untracked.

### Task 2: Expose bounded native batch evidence

**Files:**
- Modify: `core/pipeline/vector_branch.py`
- Modify: `tests/test_vector_branch_extraction_unit.py`
- Modify: `tests/test_converter_multicore_profile_unit.py`

- [ ] **Step 1: Write a failing allowlist test**

Add a test for `_native_mesh_timing_fields` with only these accepted source
fields:

```python
{
    "native_group_count": 43,
    "native_meshes": 40,
    "fallback_groups": 3,
    "pack_seconds": 0.12,
    "native_seconds": 2.2,
    "mesh_convert_seconds": 3.9,
    "surface_validation_seconds": 2.5,
    "fallback_seconds": 1.36,
    "native_parallel_workers": 3,
    "native_parallel_batch_count": 15,
    "native_parallel_wall_seconds": 1.0,
    "fallback_reason_native_merged_empty_native_mesh": 3,
    "private_polygon_payload": [[1, 2], [3, 4]],
}
```

Expected mapping keys:

```text
native_mesh_group_count
native_mesh_output_count
native_mesh_fallback_count
native_mesh_pack_s
native_mesh_compute_s
native_mesh_convert_s
native_mesh_python_surface_validation_s
native_mesh_fallback_s
native_mesh_parallel_workers
native_mesh_parallel_batch_count
native_mesh_parallel_wall_s
native_mesh_fallback_native_merged_empty_count
```

- [ ] **Step 2: Run the red test**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_vector_branch_extraction_unit.py::test_native_mesh_timing_fields_are_bounded_and_prefixed \
  -q
```

Expected: FAIL because the helper does not exist.

- [ ] **Step 3: Implement an explicit scalar allowlist**

Add `_NATIVE_MESH_TIMING_FIELDS` and `_native_mesh_timing_fields(stats)` near
the vector timing helpers. Accept only bool/int/float/string values. After
`last_stage_timings` is copied, update `vector_timing` from
`vec_processor.last_native_vector_mesh_stats`. Do not add a log event.

- [ ] **Step 4: Prove profiler extraction retains the new fields**

Extend `test_extract_vector_timings_accepts_current_pipeline_key` so
`_extract_vector_timings` returns both `parse_s` and representative native
worker/timing fields unchanged.

- [ ] **Step 5: Run the focused tests**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_vector_branch_extraction_unit.py \
  tests/test_converter_multicore_profile_unit.py \
  -q
```

Expected: PASS.

- [ ] **Step 6: Commit observability**

Run:

```bash
git add \
  core/pipeline/vector_branch.py \
  tests/test_vector_branch_extraction_unit.py \
  tests/test_converter_multicore_profile_unit.py
git diff --cached --check
git commit -m "perf(vector): expose native batch timing evidence"
```

### Task 3: Add deterministic isolated batch computation

**Files:**
- Modify: `core/vector_native_mesh.py`
- Modify: `tests/test_vector_native_mesh_unit.py`

- [ ] **Step 1: Write the worker-policy red tests**

Add tests proving:

- fewer than three useful batches resolve to one worker;
- the existing resolver receives workload `vector`, hard maximum `4`, and a
  nonzero per-worker memory estimate;
- explicit/automatic resolver output is recorded in
  `native_parallel_workers`;
- a nested `task_parallelism_worker_scope()` resolves serial through the
  shared policy.

Run the focused tests and confirm they fail before implementation.

- [ ] **Step 2: Write out-of-order exactness tests**

Create a guarded fake module whose `merge_run_groups_to_meshes` sleeps for
different durations based on `z_offset`, making later batches finish first.
Use shapes that create at least three height/Z batches.

Compare serial and two-worker results for:

- slot insertion order;
- mesh count and per-mesh vertex/face bytes;
- Z bounds and material IDs;
- native/surface/fallback counters;
- fallback reason counters.

The test must fail before the parallel path exists.

- [ ] **Step 3: Write failure and fallback tests**

Add cases where:

- one worker-side native call raises;
- one returned mesh is empty and takes split/merged fallback;
- one valid array fails the unchanged Shapely surface check;
- executor submission or a future raises unexpectedly.

Assert no partial parallel output is committed and the result equals the
serial fallback path.

- [ ] **Step 4: Write compiled-extension concurrency coverage**

Build three or more immutable prepared batches containing square, hole, and
disjoint fixtures. Run the real extension serially and through 2/4 threads.
Hash dtype, shape, and C-order bytes for every vertices/faces array and assert
exact equality.

- [ ] **Step 5: Implement immutable preparation**

Add private dataclasses for prepared jobs/batches and computed outcomes.
Preparation must:

- use the current shared path cache sequentially;
- retain original batch/group indices;
- retain original Shapely geometries for the independent validator;
- defer no-path fallbacks until ordered commit;
- avoid mutating output or extrusion caches.

- [ ] **Step 6: Implement the top-level worker**

The worker must:

- be a module-level entry point;
- enter `task_parallelism_worker_scope()`;
- call the existing native API;
- run `_native_mesh_arrays`, `_mesh_from_arrays`, and the unchanged
  `_native_surface_area_matches`;
- return immutable outcomes and local timing/error fields;
- never mutate `meshes_by_slot`, `extrude_cache`, path caches, or shared stats.

- [ ] **Step 7: Implement bounded scheduling and ordered commit**

Resolve workers through `resolve_task_parallelism` with:

```text
workload: vector
min parallel batches: 3
hard maximum workers: 4
estimated worker memory: 384 MiB
```

When workers equal one, call the existing `_run_native_job_batch` loop.
Otherwise use one `ThreadPoolExecutor`, gather indexed results, and commit in
original order. Commit retains the current retry/fallback functions and final
buffer flush. On executor infrastructure failure, discard uncommitted results
and rerun the serial loop.

- [ ] **Step 8: Run native unit tests**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_vector_native_mesh_unit.py \
  tests/test_vector_native_mesh_corpus_profile_unit.py \
  tests/test_task_parallelism_unit.py \
  tests/test_build_native_extensions_unit.py \
  -q
```

Expected: PASS.

- [ ] **Step 9: Commit the scheduling slice**

Run:

```bash
git add core/vector_native_mesh.py tests/test_vector_native_mesh_unit.py
git diff --cached --check
git commit -m "perf(vector): parallelize deterministic native batches"
```

### Task 4: Prove exact quality at 2/4 workers

**Files:**
- Read: `.scratch/vector-native-batch-parallelism/base-*/profile.json`
- Create ignored artifacts under:
  `.scratch/vector-native-batch-parallelism/candidate-*`

- [ ] **Step 1: Rebuild and run 8/12/15 exact comparisons**

Repeat Task 1's 8/12/15 commands with:

```text
LUMINA_MAX_WORKERS=1
LUMINA_VECTOR_PARALLELISM=2
--reference-report <matching base profile.json>
```

Then repeat with `LUMINA_VECTOR_PARALLELISM=4`.

Expected: every command exits 0 with external exact match.

- [ ] **Step 2: Run large and no-override exact comparisons**

Compare both accepted worker settings against:

```text
base-12-large/profile.json
base-8-no-override/profile.json
```

Expected: exact semantic, GLB, and 3MF matches.

- [ ] **Step 3: Verify fallback parity**

Run the corpus profiler/unit fixtures at 1, 2, and 4 workers. Compare all
fallback counters and output hashes. Any difference is a release blocker.

### Task 5: Measure performance and memory

**Files:**
- Create ignored timing artifacts under:
  `.scratch/vector-native-batch-parallelism/timing-*`

- [ ] **Step 1: Run fresh-process worker sweep**

For the 200 mm / 12-color workload, run one cold and at least three warm
fresh-process timing-only samples for worker counts 1, 2, and 4. Keep
`LUMINA_MAX_WORKERS=1` for the single-task ceiling experiment.

Record:

- total, build, and extrusion wall time;
- native parallel wall and summed sub-stage times;
- resolved workers and batch count;
- peak RSS and RSS increase;
- peak threads and child processes.

- [ ] **Step 2: Run production-auto samples**

Unset the explicit vector count and run with the normal
`LUMINA_MAX_WORKERS` setting. Record the resolved fair-share worker count and
compare it with serial.

- [ ] **Step 3: Run the no-override control**

Run one cold plus three warm fresh-process timing-only samples on the
8-color no-override workload at serial and the accepted worker setting.

- [ ] **Step 4: Apply the stop gates**

Accept only if:

- exact quality is green;
- native+validation hot region improves at least 40%;
- build warm median improves at least 15%;
- end-to-end warm median improves at least 7%;
- p90 regression is no worse than 5%;
- peak RSS growth is at most 15%;
- no-override median regression is at most 5%;
- no child process appears and thread count matches the bound.

Otherwise record `no_safe_gain` and leave production behavior serial.

### Task 6: Final regression and evidence

**Files:**
- Create:
  `docs/superpowers/specs/2026-07-31-vector-native-batch-parallelism-results.md`

- [ ] **Step 1: Write the evidence document**

Include base/head SHAs, PR #540 dependency, runtime/dependency versions,
8/12/15 exact hashes, 1/2/4/auto distributions, native/fallback counters,
RSS/threads/children, rejected C++ self-guard and factored-union experiments,
remaining hotspots, and `ready_for_review` or `no_safe_gain`.

Do not commit user paths, SVGs, generated models, or profile artifacts.

- [ ] **Step 2: Run focused native/vector regression**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_build_native_extensions_unit.py \
  tests/test_vector_native_mesh_unit.py \
  tests/test_vector_native_mesh_corpus_profile_unit.py \
  tests/test_vector_engine_fixes_unit.py::TestFillRuleSubpathMerging \
  tests/test_vector_engine_unit.py \
  tests/test_vector_engine_stroke_unit.py \
  tests/test_vector_glb_v2_kernel_unit.py \
  tests/test_vector_glb_v2_parity_unit.py \
  tests/test_vector_branch_extraction_unit.py \
  tests/test_converter_multicore_profile_unit.py \
  tests/test_task_parallelism_unit.py \
  -q
```

- [ ] **Step 3: Run logging governance**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_logging_exception_governance_unit.py \
  tests/test_structured_logging_unit.py \
  tests/test_logger_unit.py \
  -q
.venv/bin/python scripts/log_quality_check.py \
  --mode fast \
  --output .scratch/vector-native-batch-parallelism/final-log-quality.json
```

- [ ] **Step 4: Run hygiene checks**

Run:

```bash
.venv/bin/python -m py_compile \
  core/vector_native_mesh.py \
  core/pipeline/vector_branch.py \
  tests/test_vector_native_mesh_unit.py \
  tests/test_vector_branch_extraction_unit.py
git diff --check
rg -n '锟|鎷|鍙|涓' \
  core/vector_native_mesh.py \
  core/pipeline/vector_branch.py \
  tests/test_vector_native_mesh_unit.py \
  tests/test_vector_branch_extraction_unit.py \
  docs/superpowers/specs/2026-07-31-vector-native-batch-parallelism-results.md
ps -axo pid=,command= | \
  rg '/Users/min/.codex/worktrees/5fe8/Lumina-studio/.+(api_server.py|start_all.py|vite|vitest|esbuild|profile_)' || true
```

- [ ] **Step 5: Commit final evidence**

Run:

```bash
git add \
  docs/superpowers/specs/2026-07-31-vector-native-batch-parallelism-results.md
git diff --cached --check
git commit -m "docs(perf): record native batch parallelism results"
```

Do not push or create a PR without explicit user authorization.
