# Lightweight Browser Preview Authority Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every single-item converter workflow keep its existing lightweight, real-time browser preview while exact generated geometry is used only for the downloadable 3MF.

**Architecture:** Preview endpoints and async GLB polling remain the only authority for `previewGlbUrl`; Generate updates download state but never promotes `preview_3d_url` into the viewer. The backend reuses a validated native Vector segmented asset for all frontend-procedural settings, stops exporting final advanced/model-surface print scenes as browser GLBs, and returns only the current registered preview URL when reuse is proven safe. Existing session ownership, stale-response rejection, preview cleanup, and final-download TTL rules remain intact.

**Tech Stack:** FastAPI, Python 3.14, pytest, React 19, TypeScript, Zustand, Three.js, Vitest through `python scripts/run_vitest.py`, Playwright/browser resource timing.

---

### Task 1: Make lightweight preview state authoritative after Generate

**Files:**
- Modify: `frontend/src/stores/__tests__/converter-native-source.test.ts`
- Modify: `frontend/src/__tests__/converter-store-relief-generate.test.ts`
- Modify: `frontend/src/stores/converter/store.ts`

- [x] **Step 1: Rewrite generated-model expectations as lightweight-preview expectations**

Change the ordinary raster timing test so Generate finishes first with a legacy
`preview_3d_url`, but the assertions are:

```ts
expect(useConverterStore.getState().modelUrl).toBeNull();
expect(useConverterStore.getState().previewGlbUrl).toBeNull();
await flushGlbPoll();
await flushGlbPoll(0);
expect(useConverterStore.getState().previewGlbUrl).toBe(
  "/api/files/preview-ready.glb",
);
expect(useConverterStore.getState().modelUrl).toBeNull();
```

For relief, coating, loop, fridge magnet, outline, cloisonne, and model surface,
return `/api/files/generated-surface.glb` from the mock Generate call but assert:

```ts
expect(useConverterStore.getState().modelUrl).toBeNull();
expect(useConverterStore.getState().previewGlbUrl).toBe(
  "/api/files/flat-preview.glb",
);
```

Change the heightmap race so the old preview poll is not cancelled by Generate:

```ts
expect(useConverterStore.getState().modelUrl).toBeNull();
await flushGlbPoll();
await flushGlbPoll(0);
expect(mocks.getGlbStatus).toHaveBeenCalledWith("session-heightmap-async");
expect(useConverterStore.getState().previewGlbUrl).toBe(
  "/api/files/flat-preview.glb",
);
```

Update relief-store tests that expect `/api/files/model.glb` so the existing
quick preview is retained and the Generate return value is `null`.

- [x] **Step 2: Run the frontend tests and verify RED**

```bash
CI=true .venv/bin/python scripts/run_vitest.py run \
  src/stores/__tests__/converter-native-source.test.ts \
  src/__tests__/converter-store-relief-generate.test.ts
```

Expected: failures show generated URLs becoming `modelUrl`, advanced settings
clearing `previewGlbUrl`, and heightmap Generate cancelling its preview poll.

- [x] **Step 3: Remove generated ownership from `submitGenerate()`**

Delete `captureGeneratedGeometryPreviewIdentity()` and its private helpers when
no caller remains. The normal single-item success state must be:

```ts
const downloadUrl = normalizeStoreResourceUrl(response.download_url);
set({
  isGenerating: false,
  modelUrl: null,
  batchPreviewItems: [],
  downloadUrl,
  threemfDiskPath: null,
  generatePerformanceTiming: response.performance_timing ?? null,
  generateWarnings: response.warnings ?? [],
  largeFormatWarnings: [],
});
```

Do not clear `previewGlbUrl`, increment `_glbPollSequence`, or select
`response.preview_3d_url`. Log it only as `response_model_url`, log
`selected_model_url: null`, and return `null` after receiving the 3MF.

- [x] **Step 4: Run Step 2 tests and verify GREEN**

Expected: both files pass and all single-item Generate cases leave `modelUrl`
null.

- [x] **Step 5: Commit**

```bash
git add frontend/src/stores/converter/store.ts \
  frontend/src/stores/__tests__/converter-native-source.test.ts \
  frontend/src/__tests__/converter-store-relief-generate.test.ts
git commit -m "fix(preview): keep lightweight model authoritative"
```

Use an English-first, Chinese-second body explaining that Generate changes
download state only.

### Task 2: Preserve real-time viewer and model-surface interaction

**Files:**
- Modify: `frontend/src/__tests__/Scene3D.test.tsx`
- Modify: `frontend/src/components/Scene3D.tsx`
- Verify: `frontend/src/__tests__/InteractiveModelViewer.test.ts`

- [x] **Step 1: Add failing selector/helper priority tests**

With `modelSurfaceEnabled=true` and a stale/generated `modelUrl`, assert the
existing mocked `ModelSurfaceSelector3D` renders and the generated viewer does
not. Add a keychain case with a legacy `modelUrl` and valid model bounds; assert
the existing mocked procedural keychain helper still renders. Reuse current mock
test IDs rather than adding production-only IDs.

- [x] **Step 2: Run and verify RED**

```bash
CI=true .venv/bin/python scripts/run_vitest.py run src/__tests__/Scene3D.test.tsx
```

Expected: `!effectiveModelUrl` hides both the selector and keychain helper.

- [x] **Step 3: Restore preview-first rendering**

```ts
const showModelSurfaceSelector =
  modelSurfaceEnabled &&
  Boolean(modelSurfacePreviewUrl) &&
  Boolean(modelSurfaceFile) &&
  batchPreviewItems.length === 0;
```

Keep the selector before URL-driven JSX branches and remove
`!effectiveModelUrl` from the keychain helper. Do not change upload, selection,
rotation, placement, or source-model loading.

- [x] **Step 4: Verify GREEN**

```bash
CI=true .venv/bin/python scripts/run_vitest.py run \
  src/__tests__/Scene3D.test.tsx \
  src/__tests__/InteractiveModelViewer.test.ts
```

Existing tests must still prove material, dimension, relief, outline,
cloisonne, double-sided, fridge-magnet, and puzzle preview behavior.

- [x] **Step 5: Commit**

```bash
git add frontend/src/components/Scene3D.tsx \
  frontend/src/__tests__/Scene3D.test.tsx
git commit -m "fix(preview): preserve realtime surface interaction"
```

### Task 3: Reuse native Vector preview across frontend-procedural settings

**Files:**
- Modify: `tests/test_converter_generate_unit.py`
- Modify: `tests/test_converter_vector_export_unit.py`
- Modify: `api/routers/converter/generate.py`
- Verify: `core/pipeline/vector_branch.py`

- [x] **Step 1: Write failing advanced reuse tests**

For a ready same-session native Vector preview whose provenance and edit state
match, parameterize relief, coating, loop, fridge magnet, outline, and
cloisonne. Assert:

```python
submitted_params = _mock_pool.submit.call_args.args[3]
assert submitted_params["preview_glb_path"] == preview_path
assert response.json()["preview_3d_url"] == f"/api/files/{preview_id}"
assert set(_test_registry.get_session_entries(sid)) == {preview_id}
```

Keep model-surface excluded. Keep missing files, expired entries, foreign
registrations, source/parameter mismatches, and edit mismatches asserting
`preview_glb_path is None`. In the Vector branch test, make
`export_vector_glb_preview()` fail if called when an advanced request has a valid
preview path; assert reuse happens only after 3MF export succeeds.

- [x] **Step 2: Run and verify RED**

```bash
.venv/bin/python -m pytest \
  tests/test_converter_generate_unit.py \
  tests/test_converter_vector_export_unit.py \
  -k "preview_glb or generated_surface" -q
```

Expected: advanced cases are rejected with `relief_enabled`, `coating_enabled`,
or equivalent reasons.

- [x] **Step 3: Narrow reuse validation to asset identity**

Retain these `_can_reuse_planar_vector_preview_glb()` gates:

```python
if core_modeling_mode != CoreModelingMode.VECTOR:
    return False, "modeling_mode_not_vector"
if not is_native_svg:
    return False, "source_not_native_svg"
if uses_model_surface_overlay:
    return False, "model_surface_overlay_enabled"
if not preview_edit_state_matches:
    return False, preview_edit_state_reason
```

Then call `_preview_analysis_params_match()` as today. Remove only relief,
coating, loop, fridge-magnet, outline, and cloisonne exclusions. Do not relax
session, FileRegistry, expiry, existence, provenance, parameter, or edit checks.

- [x] **Step 4: Run Step 2 tests and verify GREEN**

Expected: valid advanced requests reuse the one registered lightweight preview;
unsafe cases still fail closed.

- [x] **Step 5: Commit**

```bash
git add api/routers/converter/generate.py \
  tests/test_converter_generate_unit.py \
  tests/test_converter_vector_export_unit.py
git commit -m "fix(vector): reuse lightweight preview across live settings"
```

### Task 4: Stop publishing print-scene GLBs from Generate

**Files:**
- Modify: `tests/test_pipeline_step_modules_unit.py`
- Modify: `tests/test_model_surface_generate_unit.py`
- Modify: `tests/test_converter_generate_unit.py`
- Modify: `tests/test_converter_vector_export_unit.py`
- Modify: `core/pipeline/s11_glb_preview.py`
- Modify: `core/pipeline/vector_branch.py`
- Modify: `api/workers/converter_workers.py`
- Modify: `api/routers/converter/generate.py`

- [x] **Step 1: Write failing backend asset-boundary tests**

Replace S11 tests that expect final-scene export for heightmap, relief, outline,
cloisonne, loop, coating, or fridge magnet. Patch `_export_pipeline_scene_glb`
to fail and `generate_segmented_glb` to return a small fixture, then assert:

```python
result = s11_glb_preview.run(ctx)
assert result["glb_path"] == str(lightweight_path)
segmented_export.assert_called_once()
```

When `preview_glb_path` exists, assert it is reused before any surface decision
and neither exporter runs. Change model-surface worker success expectations to:

```python
assert result["threemf_path"] == str(expected_3mf)
assert result["glb_path"] is None
```

Add a route test where the worker returns a new GLB path. Assert the 3MF is
registered, `preview_3d_url is None`, the GLB is not registered, and its temp
file is removed. The separate existing-path reuse case still returns the
already registered lightweight preview URL.

For native Vector, assert a missing or invalid `preview_glb_path` still returns
the completed 3MF but `glb_path is None`, and the print-scene GLB exporter is
never called.

- [x] **Step 2: Run and verify RED**

```bash
.venv/bin/python -m pytest \
  tests/test_pipeline_step_modules_unit.py \
  tests/test_model_surface_generate_unit.py \
  tests/test_converter_generate_unit.py \
  -k "glb or model_surface" -q
```

Expected: S11 exports final scenes, model-surface worker returns a GLB, and the
route registers newly generated GLBs.

- [x] **Step 3: Make S11 preview-only and remove model-surface export**

In `s11_glb_preview.run()`, reuse a valid `preview_glb_path` before all other
decisions. Remove `_should_export_pipeline_scene_for_glb()` and
`_export_pipeline_scene_glb()` once unused. Fallback always calls
`generate_segmented_glb()` from matched colours/mask, including heightmap and
advanced print settings; it never serializes `ctx["scene"]`.

Delete `_export_optional_model_surface_preview_glb()` and return
`"glb_path": None` after model-surface 3MF completion. Remove only now-dead GLB
log fields/events; retain typed failures and 3MF behavior.

In the native Vector branch, reuse an already validated lightweight path when
provided, but remove the fallback that serializes the exact print scene when
the path is missing or stale. The async preview pipeline remains responsible
for creating/rebuilding lightweight GLBs.

- [x] **Step 4: Publish only proven reused preview URLs**

Keep `glb_reuses_preview_path` and its current-session/FileRegistry
revalidation. Remove registration of any other worker GLB. Leave
`preview_3d_url=None` and remove the temp GLB after the 3MF registration. Never
delete a reused session-owned preview. Preserve the optional response field for
schema compatibility.

- [x] **Step 5: Run Step 2 tests and verify GREEN**

Expected: no raster, model-surface, or native Vector print scene is exported as
a GLB; reused registration stays singular, and unexpected worker GLBs are
cleaned without invalidating the 3MF.

- [x] **Step 6: Commit**

```bash
git add core/pipeline/s11_glb_preview.py \
  core/pipeline/vector_branch.py \
  api/workers/converter_workers.py \
  api/routers/converter/generate.py \
  tests/test_pipeline_step_modules_unit.py \
  tests/test_model_surface_generate_unit.py \
  tests/test_converter_vector_export_unit.py \
  tests/test_converter_generate_unit.py
git commit -m "fix(generate): keep print geometry out of browser GLBs"
```

The native Vector fallback was additionally locked down in the follow-up
commit `fix(vector): skip print-scene preview fallback` after static review
found that an invalid reuse path still performed a discarded exact-GLB export.

### Task 5: Verify lifecycle, R4C1, and PR delivery

**Files:**
- Modify only if a failing regression identifies a defect.
- Update: `docs/superpowers/plans/2026-08-27-native-vector-preview-asset-reuse.md`
- Update: PR #586 body.

- [x] **Step 1: Run focused backend verification**

```bash
.venv/bin/python -m pytest \
  tests/test_converter_generate_unit.py \
  tests/test_converter_vector_export_unit.py \
  tests/test_pipeline_step_modules_unit.py \
  tests/test_segmented_glb_unit.py \
  tests/test_async_glb_unit.py \
  tests/test_model_surface_generate_unit.py \
  tests/test_converter_cleanup_integration_unit.py \
  tests/test_s09_export_3mf_unit.py -v
```

- [x] **Step 2: Run focused frontend verification and build**

```bash
CI=true .venv/bin/python scripts/run_vitest.py run \
  src/stores/__tests__/converter-native-source.test.ts \
  src/stores/__tests__/modelSurfaceStore.test.ts \
  src/__tests__/Scene3D.test.tsx \
  src/__tests__/InteractiveModelViewer.test.ts \
  src/__tests__/converter-store-relief-generate.test.ts \
  src/__tests__/glb-async-polling.test.ts \
  src/__tests__/converter-store-cleanup.test.ts
cd frontend && pnpm build
```

- [x] **Step 3: Run governance and smoke gates**

```bash
.venv/bin/python -m pytest \
  tests/test_logging_exception_governance_unit.py \
  tests/test_structured_logging_unit.py \
  tests/test_logger_unit.py -v
CI=true .venv/bin/python scripts/run_smoke_tests.py
.venv/bin/python scripts/log_quality_check.py --mode fast
```

- [x] **Step 4: Replay R4C1 in both timing orders**

Use
`/Volumes/personal_folder/person_8ba86fa3823aff049badd414e7c525f2_20260814_130551_vector.svg`
at 111 mm, native Vector, 4-Color RYBW, five 0.08 mm layers, double-sided.
Record selected viewer URL before/after Generate, every browser `.glb` URL and
transfer size, preview/generate elapsed time, heap samples, and backend peak RSS.
Acceptance: no print-scene GLB request; the segmented URL is the only selected
model in both immediate and wait-first orderings.

- [x] **Step 5: Prove 3MF output is unaffected**

Compare ZIP entries, CRCs, `3D/Objects/object_1.model`, project/slice metadata,
material slots, and object/triangle counts. Only local source path/timestamp
text may differ. Escalate to Bambu/Orca only if print payloads differ.

- [ ] **Step 6: Run independent review**

Provide base `cb736342e2d1aed382b98e45e36e44ac1287a3eb`, final head, design,
plan, and the lightweight-only requirement. Fix every Critical and Important
finding and re-run affected tests.

- [ ] **Step 7: Final hygiene and push**

```bash
git diff --check
git status --short --branch
python3 start_all.py --kill
```

Confirm no backend, Vite, Vitest, esbuild, or worktree-owned Node process
remains. Update the old plan status and PR #586 body, commit docs, and push
`MOVIBALE/fix/native-vector-preview-asset-reuse` normally. Do not force push,
merge, or enable auto-merge.

- [ ] **Step 8: Report exact delivery evidence**

Report final head, PR URL, exact test counts, R4C1 URLs/sizes/timing/memory, 3MF
comparison, independent review outcome, CI state, and remaining limitations.
