# Preview GLB And LUT K-Means Memory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent preview server stalls and LUT-constrained quantization out-of-memory failures on large images.

**Architecture:** Replace LUT-constrained dense distance matrices with KDTree nearest-neighbor queries so memory scales with pixels plus centers, not pixels times centers. Reuse the existing async segmented-GLB scheduler for the initial preview endpoint, then let the frontend poll the existing `/glb-status/{session_id}` endpoint just like replace flows.

**Tech Stack:** Python 3, FastAPI, NumPy, SciPy KDTree, pytest, React/TypeScript, Zustand, Vitest.

---

### Task 1: LUT-Constrained K-Means Dense Matrix Guard

**Files:**
- Modify: `core/pipeline/processing_ops/kmeans_quantizer.py`
- Test: `tests/test_kmeans_quantizer_lut_constrained_unit.py`

- [ ] **Step 1: Write the failing test**

Add a test that monkeypatches `kmeans_quantizer.cdist` to raise if the LUT-constrained path tries to build a dense matrix. Use a small synthetic image and LUT so the test is fast but still exercises center initialization, iterative assignment, SSE scoring, and final image mapping.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_kmeans_quantizer_lut_constrained_unit.py::TestLowLevelLutConstrained::test_uses_kdtree_not_dense_cdist -v`

Expected: FAIL with the monkeypatched `AssertionError`, proving the old path still calls `cdist`.

- [ ] **Step 3: Write minimal implementation**

In `kmeans_quantizer.py`, remove the `scipy.spatial.distance.cdist` import and add helper functions that use `KDTree(...).query(...)` for:
- nearest selected center for every work pixel,
- nearest selected center for every LUT row during K-Means++ initialization,
- final full-resolution mapping.

Keep the output contract unchanged: output shape and dtype match input, every output RGB belongs to `lut_rgb`, and the number of output colors stays at or below `effective_k`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_kmeans_quantizer_lut_constrained_unit.py::TestLowLevelLutConstrained::test_uses_kdtree_not_dense_cdist -v`

Expected: PASS.

### Task 2: Preview Endpoint Async GLB Scheduling

**Files:**
- Modify: `api/routers/converter/preview.py`
- Test: `tests/test_converter_preview_unit.py`

- [ ] **Step 1: Write the failing test**

Add a preview endpoint test that patches `api.routers.converter.preview.schedule_glb_build` and `api.routers.converter.preview.generate_segmented_glb`. The test must assert preview returns `preview_glb_url: null`, schedules one background GLB job with the current session/cache, and does not call `generate_segmented_glb` inline.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_converter_preview_unit.py::TestResponseContainsPaletteAndDimensions::test_preview_schedules_segmented_glb_asynchronously -v`

Expected: FAIL because preview currently calls `generate_segmented_glb` synchronously and has no `schedule_glb_build` import.

- [ ] **Step 3: Write minimal implementation**

Import `schedule_glb_build` from `.async_glb`. Replace the synchronous GLB block in `convert_preview` with a scheduler call after `cache_data` is stored and the preview PNG/raw URLs are registered. Log `segmented_glb_ms` as scheduler overhead, not mesh-build time.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_converter_preview_unit.py::TestResponseContainsPaletteAndDimensions::test_preview_schedules_segmented_glb_asynchronously -v`

Expected: PASS.

### Task 3: Frontend Preview Polls Async GLB Status

**Files:**
- Modify: `frontend/src/stores/converter/store.ts`
- Test: `frontend/src/stores/__tests__/converter-native-source.test.ts`

- [ ] **Step 1: Write the failing test**

Extend the converter API mock with `getGlbStatus`. Add a `submitPreview` test where backend preview returns `preview_glb_url: null`, the mocked GLB status returns `ready`, and fake timers advance until `previewGlbUrl` becomes the returned GLB URL.

- [ ] **Step 2: Run test to verify it fails**

Run: `python scripts/run_vitest.py run src/stores/__tests__/converter-native-source.test.ts -t "polls async preview GLB after preview returns no GLB URL"`

Expected: FAIL because `submitPreview` currently does not start `_pollAsyncGlb`.

- [ ] **Step 3: Write minimal implementation**

After preview state is set and the new `sessionId` is available, call `_get()._pollAsyncGlb()` when `response.preview_glb_url` is missing. Keep the existing direct `previewGlbUrl` assignment when the backend returns a URL.

- [ ] **Step 4: Run test to verify it passes**

Run: `python scripts/run_vitest.py run src/stores/__tests__/converter-native-source.test.ts -t "polls async preview GLB after preview returns no GLB URL"`

Expected: PASS.

### Task 4: Verification And Review

**Files:**
- Review: `core/pipeline/processing_ops/kmeans_quantizer.py`
- Review: `api/routers/converter/preview.py`
- Review: `frontend/src/stores/converter/store.ts`

- [ ] **Step 1: Run backend target tests**

Run: `python -m pytest tests/test_kmeans_quantizer_lut_constrained_unit.py tests/test_converter_preview_unit.py tests/test_async_glb_unit.py -v`

Expected: PASS.

- [ ] **Step 2: Run frontend target tests**

Run: `python scripts/run_vitest.py run src/__tests__/glb-async-polling.test.ts src/stores/__tests__/converter-native-source.test.ts`

Expected: PASS.

- [ ] **Step 3: Run diff review**

Review `git diff --check`, `git diff --stat`, and changed hunks. Confirm there are no dense `cdist` calls in `kmeans_quantizer.py`, no synchronous preview GLB call in `convert_preview`, and no frontend polling race where an old preview can overwrite a newer session.

### Task 5: Publish PR

**Files:**
- Commit staged changes.
- Push branch `Min/fix/preview-glb-and-lut-kmeans-memory`.
- Open PR against `dev-refactor`.

- [ ] **Step 1: Commit**

Run: `git status --short`, then stage only the plan, code, and tests for this fix. Commit using Conventional Commit:

`fix(converter): avoid preview glb stalls and lut kmeans oom`

- [ ] **Step 2: Push**

Run: `git push -u origin Min/fix/preview-glb-and-lut-kmeans-memory`

- [ ] **Step 3: Create PR**

Create a PR targeting `dev-refactor` with an English summary first and Chinese summary second. Include the tests run and note that the user should verify a large preview with `use_lut_constrained=true`.
