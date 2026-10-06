# Lossless Dense SVG Runtime Integration Plan

> Deployment update (2026-10-06): Docker support and the public-test bypass
> are retired. This historical record preserves earlier implementation and
> validation evidence; use [Runtime support](../../runtime-support.md) for current behavior.
> 部署更新：Docker 支持及公网测试访问旁路已移除；本文保留历史实现与验证记录，当前运行方式以上述说明为准。

> Execute task-by-task with TDD and fresh verification before each commit.

**Goal:** Put the proven dense GEOS positive-buffer acceleration and exact
component-wise negative buffer into the server SVG contour-normalization path,
with verified capability loading and stock fallback.

**Architecture:** A new WKB-only core adapter owns the isolated GEOS C API,
manifest validation, dense eligibility, and inward-component helper. The vector
engine adopts it only for contour normalization. Docker builds the pinned
modified shared library and supplies its verified manifest; desktop packaging
does not enable it.

**Tech stack:** Python 3.12/3.13, Shapely 2.1.2, GEOS 3.13.1 C API, `ctypes`,
CMake, Docker, pytest, existing real SVG proof corpus.

**Dirty-worktree boundary:** `core/vector_engine.py` and several cache/progress
tests contain pre-existing user work. Preserve it. Stage only integration hunks
from `core/vector_engine.py`; do not stage unrelated cache/progress changes.

---

## Task 1: Move the isolated GEOS adapter into core

**Files:**

- Create: `core/geos_buffer_fast.py`
- Create: `tests/test_geos_buffer_fast_unit.py`
- Modify: `scripts/profile_geos_buffer_fast_proof.py`
- Modify: `tests/test_geos_buffer_fast_proof_unit.py`

- [ ] Write failing tests for `BufferSettings`, `ProofLibraryError`, and
  `GEOSCBufferBackend` using a fake re-entrant C library. Assert WKB-only input,
  setter success semantics, output copying, and cleanup on both success and a
  failed setter.
- [ ] Run the new test and verify import failure.
- [ ] Move the proven adapter from the proof script into
  `core/geos_buffer_fast.py`, retaining bilingual public docstrings.
- [ ] Import/re-export the core types in the proof profiler so all existing
  proof tests remain green and there is one production implementation.
- [ ] Run:

```bash
/Users/min/.cache/lumina-studio/venv-py312/bin/python -m pytest \
  tests/test_geos_buffer_fast_unit.py \
  tests/test_geos_buffer_fast_proof_unit.py -q
/Users/min/.cache/lumina-studio/venv-py312/bin/python -m py_compile \
  core/geos_buffer_fast.py scripts/profile_geos_buffer_fast_proof.py
```

- [ ] Commit:

```bash
git add core/geos_buffer_fast.py scripts/profile_geos_buffer_fast_proof.py \
  tests/test_geos_buffer_fast_unit.py tests/test_geos_buffer_fast_proof_unit.py
git commit -m "refactor(vector): isolate dense GEOS runtime adapter"
```

## Task 2: Add verified manifest resolution and dense routing

**Files:**

- Modify: `core/geos_buffer_fast.py`
- Modify: `tests/test_geos_buffer_fast_unit.py`

- [ ] Write failing tests for:
  - disabled runtime;
  - missing manifest;
  - wrong GEOS ref, commit, or patch SHA;
  - missing/non-absolute library path;
  - verified backend caching;
  - explicit unverified path rejected unless the development override is set;
  - fewer than 2,048 components staying on stock;
  - valid dense output accepted;
  - load/call/invalid-output failure returning `None` for stock fallback.
- [ ] Implement constants for the pinned source and patch identity, a strict
  manifest parser, process-local backend cache, and
  `try_dense_positive_buffer()`.
- [ ] Use structured DEBUG for success and actionable WARNING fields for a
  failed optional invocation. Do not emit INFO.
- [ ] Run the focused test and logging governance tests.
- [ ] Commit:

```bash
git add core/geos_buffer_fast.py tests/test_geos_buffer_fast_unit.py
git commit -m "feat(vector): guard dense GEOS buffer runtime"
```

## Task 3: Add exact component-wise inward buffering

**Files:**

- Modify: `core/geos_buffer_fast.py`
- Modify: `tests/test_geos_buffer_fast_unit.py`

- [ ] Write failing tests across:
  - thousands of disjoint polygons;
  - polygons with holes;
  - a polygon that splits while shrinking;
  - tiny polygons that disappear;
  - invalid/non-polygon input;
  - forced vector-buffer exception.
- [ ] Compare every successful helper result to the stock global negative
  buffer with empty symmetric difference, matching type/component/hole count,
  area, and bounds.
- [ ] Implement `try_disconnected_inward_buffer()`: buffer each top-level
  polygon with stock Shapely vector calls, flatten polygonal output, validate,
  and return `None` on any unsafe condition.
- [ ] Run focused tests and commit:

```bash
git add core/geos_buffer_fast.py tests/test_geos_buffer_fast_unit.py
git commit -m "perf(vector): shrink disconnected contours independently"
```

## Task 4: Adopt both helpers in contour normalization

**Files:**

- Modify: `core/vector_engine.py`
- Modify: `tests/test_vector_engine_fixes_unit.py`

- [ ] Write failing tests that monkeypatch the core helpers and assert:
  - dense batch geometry uses the isolated positive buffer;
  - small batch geometry does not;
  - unavailable/failed positive acceleration executes stock buffer;
  - dense inflated output uses component-wise inward buffering;
  - failed inward buffering executes the stock global negative buffer;
  - scalar and batch results preserve existing empty/invalid/make-valid
    fallback semantics.
- [ ] Add a `contour_normalize_s` timing around post-clip normalization while
  retaining existing `occlusion_s` behavior.
- [ ] Implement narrow scalar/batch routing. Do not alter parsing, clipping,
  color matching, layer construction, or mesh code.
- [ ] Run:

```bash
/Users/min/.cache/lumina-studio/venv-py312/bin/python -m pytest \
  tests/test_geos_buffer_fast_unit.py \
  tests/test_vector_engine_fixes_unit.py \
  tests/test_vector_engine_unit.py \
  tests/test_vector_preview_timings_unit.py -q
```

- [ ] Stage only the new `core/vector_engine.py` hunks with `git add -p` and
  verify `git diff --cached` contains no pre-existing cache/progress edits.
- [ ] Commit:

```bash
git add tests/test_vector_engine_fixes_unit.py
git commit -m "perf(vector): route dense contour normalization safely"
```

## Task 5: Pin the runtime build and Docker capability

**Files:**

- Modify: `scripts/build_geos_buffer_fast_proof.py`
- Modify: `tests/test_geos_buffer_fast_proof_unit.py`
- Modify: `Dockerfile`
- Modify: `native/geos_buffer_fast/README.md`
- Create: `native/geos_buffer_fast/NOTICE.md`
- Create or modify: Docker/build contract tests selected by repository search

- [ ] Write failing tests that require the build manifest to contain the exact
  upstream commit and require a checkout verification command before patching.
- [ ] Make the builder fail if tag `3.13.1` does not resolve to the pinned
  commit. Include `geos_commit` in the manifest.
- [ ] Write failing Docker contract tests that require CMake installation, the
  pinned build invocation, and
  `LUMINA_GEOS_BUFFER_FAST_MANIFEST=/app/.scratch/geos_buffer_fast_proof/build_manifest.json`.
- [ ] Update Docker. Keep the complete cloned GEOS source, `COPYING`, tracked
  patch, and build scripts inside the image.
- [ ] Update notice/readme with server capability, fallback, modification, and
  desktop exclusion. Cite the official GEOS and LGPL sources in documentation.
- [ ] Rebuild clean proof runtime, re-run 13 upstream buffer tests, and run
  focused Python tests.
- [ ] If Docker is available, build the image at least through the GEOS build
  layer and verify the runtime manifest/library from the image. Do not weaken a
  failing Docker gate.
- [ ] Commit:

```bash
git add Dockerfile scripts/build_geos_buffer_fast_proof.py \
  tests/test_geos_buffer_fast_proof_unit.py \
  native/geos_buffer_fast/README.md native/geos_buffer_fast/NOTICE.md \
  <docker-contract-tests>
git commit -m "build(vector): ship verified dense GEOS server runtime"
```

## Task 6: Verify normalization on the 300 mm real sample

**Files:**

- Generated reports only under `.scratch/`
- Modify proof-results document only if measured values change materially

- [ ] Point `LUMINA_GEOS_BUFFER_FAST_MANIFEST` at the clean proof build.
- [ ] Extract `IMG_7254.svg` once at 300 mm with production parse policy.
- [ ] Run stock full inflate/deflate once and record positive, negative, and
  total normalization time.
- [ ] Run integrated normalization three times. Require:
  - total contour normalization at most 5 seconds;
  - three-run median at most 5 seconds;
  - all fingerprints identical;
  - empty symmetric difference from stock;
  - matching type, components, holes, area, and bounds.
- [ ] Run the second supplied SVG and require unchanged geometry with no
  material absolute latency regression.
- [ ] Preserve JSON/Markdown evidence under `.scratch` and update the results
  document with exact integrated values.

## Task 7: Full analysis and model-equivalence verification

**Files:**

- Generated artifacts only under `.scratch/`
- Tests only if a defect is found

- [ ] Run full `analyze_svg` for both 300 mm samples with stage timings.
- [ ] Compare stock and accelerated `post_clip`/matched material geometry by
  material identity and draw order, using empty symmetric difference for every
  region.
- [ ] Build model meshes from the same analyses and compare:
  - material/object names;
  - per-material solid volume and bounds;
  - final union bounds and watertight/solid-surface state;
  - hole/surface invariants;
  - dimensions.
- [ ] Run focused backend regression tests and the project performance guard.
- [ ] If full preview is above 30 seconds, record the next largest stage and
  continue to Task 8. Do not declare the overall goal complete yet.

## Task 8: Locate and optimize remaining first-run hotspots

**Files:** determined by measured stage, with a new focused plan before broad
changes.

- [ ] Profile the second sample, whose 10,955 clipped shapes and 9-component
  densest region prove it has a different bottleneck.
- [ ] Profile parse, occlusion, normalization, color matching, split, extrusion,
  backing, and assembly separately for both files.
- [ ] Choose the largest remaining exact hotspot. Write a failing performance/
  semantic test before changing it.
- [ ] Preserve the same material/model invariants and stock fallback policy.
- [ ] Repeat until complete first preview is at most 30 seconds, or document a
  proven external/platform blocker. The stretch goal remains 15 seconds.

## Final verification

- [ ] Focused proof/core/vector/build/logging tests pass.
- [ ] `python scripts/check_perf_regression.py --use-cold-start` passes or any
  unrelated baseline failure is demonstrated from the untouched base.
- [ ] `python scripts/log_quality_check.py --mode fast` passes for logger-touching
  changes.
- [ ] Touched Python files compile and `git diff --check` is clean.
- [ ] The worktree contains no generated native libraries, build trees, SVGs,
  model artifacts, logs, or caches staged for commit.
- [ ] Pre-existing user cache/progress changes remain preserved and unstaged.
- [ ] Stop all long-running processes started during verification.
