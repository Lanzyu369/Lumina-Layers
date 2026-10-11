# Smooth Vector Live Preview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use `executing-plans` to implement this plan task-by-task. Follow test-driven development: every behavior change starts with a focused failing test, then the minimum production change, then the focused green run.

**Goal:** Make native SVG browser previews smooth and lightweight, keep dimensions and creative overlays live, show processed colours on model surfaces, and provide a default-on Settings switch that can fall back to the legacy segmented Vector renderer without affecting 3MF output.

**Architecture:** Keep exact print analysis and 3MF generation authoritative and unchanged. Reuse the existing session-owned Vector parse/clip artifact as the analytic preview geometry source, add a constrained loader and explicit height identity, and let the async GLB scheduler choose analytic or legacy rendering from session metadata. Separate browser asset coordinates, edit-projection coordinates, and current print parameters. Frontend generated responses never own the viewer; all asynchronous preview writes pass one captured session/revision/epoch guard.

**Tech stack:** FastAPI, Python 3.14, Shapely, trimesh/glTF, pytest, React 19, TypeScript, Zustand, Three.js, Vitest through `python scripts/run_vitest.py`, Playwright/in-app browser, Bambu Studio or OrcaSlicer for final 3MF inspection.

---

### Task 1: Lock the renderer preference and API contract

**Files:**
- Modify: `frontend/src/stores/settingsStore.ts`
- Modify: `frontend/src/components/SettingsPanel.tsx`
- Modify: `frontend/src/i18n/translations.ts`
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/converter.ts`
- Modify: `frontend/src/__tests__/settings-store.property.test.ts`
- Modify: `frontend/src/components/__tests__/SettingsPanel.layout.test.tsx`
- Modify: `frontend/src/__tests__/converter-api.test.ts`
- Modify: `tests/test_converter_preview_unit.py`

- [ ] **Step 1: Add failing persistence and UI tests**

Assert `DEFAULT_SETTINGS.enableSmoothVectorPreview === true`, Zustand persistence round-trips both boolean values, and migration of an older snapshot adopts the default. Render the Conversion settings category and assert one accessible switch named by the bilingual translation plus a standard `HelpDot` explanation that the option affects only browser 3D display.

- [ ] **Step 2: Add failing request serialization tests**

Assert `convertPreview()` writes `enable_smooth_vector_preview=true|false` into `FormData`. Add backend endpoint tests proving omitted means `true` and explicit `false` reaches the preview-session construction path without changing generation schemas.

- [ ] **Step 3: Run the focused tests and verify RED**

```bash
python scripts/run_vitest.py run \
  src/__tests__/settings-store.property.test.ts \
  src/components/__tests__/SettingsPanel.layout.test.tsx \
  src/__tests__/converter-api.test.ts
python -m pytest tests/test_converter_preview_unit.py -k "smooth_vector_preview" -q
```

- [ ] **Step 4: Implement the default-on, browser-local setting**

Add `enableSmoothVectorPreview` and `setEnableSmoothVectorPreview` to `SettingsState`, `SettingsActions`, and `DEFAULT_SETTINGS`. Keep it in the existing Zustand `persist` snapshot, but do not add it to backend `UserSettings`, generation parameters, or share-card import/export: it is a personal renderer preference, not project or print content.

Add the switch inside the existing advanced Conversion card using a divider, `HelpDot`, theme tokens, and translations. Do not add a nested card or raw colour.

Add optional `enable_smooth_vector_preview` only to `ConvertPreviewRequest`, defaulting to `true` at the FastAPI Form boundary. The converter store will supply the current setting in Task 5.

- [ ] **Step 5: Re-run and verify GREEN**

- [ ] **Step 6: Commit**

```bash
git add frontend/src/stores/settingsStore.ts frontend/src/components/SettingsPanel.tsx \
  frontend/src/i18n/translations.ts frontend/src/api/types.ts \
  frontend/src/api/converter.ts frontend/src/__tests__/settings-store.property.test.ts \
  frontend/src/components/__tests__/SettingsPanel.layout.test.tsx \
  frontend/src/__tests__/converter-api.test.ts tests/test_converter_preview_unit.py
git commit -m "feat(settings): add smooth vector preview toggle"
```

### Task 2: Make the existing Vector artifact safely reusable by the GLB worker

**Files:**
- Modify: `core/vector_engine.py`
- Modify: `core/pipeline/vector_branch.py`
- Modify: `core/pipeline/vector_glb_preview.py`
- Modify: `api/workers/converter_workers.py`
- Modify: `api/routers/converter/preview.py`
- Modify: `api/preview_cache_artifacts.py`
- Modify: `tests/test_vector_engine_part2_5_unit.py`
- Modify: `tests/test_vector_glb_v2_kernel_unit.py`
- Modify: `tests/test_converter_workers_unit.py`
- Modify: `tests/test_converter_preview_unit.py`

- [ ] **Step 1: Add failing provenance and resource-limit tests**

Create small parse/clip artifacts containing curved polygons, holes, disconnected components, and `image_vectorizer_bounds`. Prove the new loader accepts the current session-owned artifact only when the caller supplies the expected provenance digest. Assert rejection/fallback for:

- wrong schema or digest;
- source path/mtime, target width, sampling precision, stroke, or gradient-band mismatch;
- NaN/Inf coordinates or bounds;
- non-Polygon geometry;
- excessive shapes, rings, coordinates, or serialized bytes;
- missing or no-longer-owned temp path.

Explicitly prove that changing the artifact’s own embedded key cannot satisfy a different session-provided expected digest.

- [ ] **Step 2: Run and verify RED**

```bash
python -m pytest \
  tests/test_vector_engine_part2_5_unit.py \
  tests/test_vector_glb_v2_kernel_unit.py \
  tests/test_converter_workers_unit.py \
  tests/test_converter_preview_unit.py \
  -k "parse_clip or provenance or quick_preview_source" -q
```

- [ ] **Step 3: Add a single canonical provenance helper**

Derive a stable digest from the existing `_vector_parse_clip_cache_key()` tuple. Serialize that digest beside the entry and return it separately from the preview worker result. Store it in preview-cache metadata alongside `vector_parse_clip_cache_path`; keep the pickle registered only with `SessionStore.register_temp_file()`.

Do not create a second WKB/JSON geometry artifact and do not expose the private pickle through `FileRegistry`.

- [ ] **Step 4: Add the constrained `VectorQuickPreviewSourceV1` view**

In `vector_glb_preview.py`, load the existing artifact through a small typed view that returns copied/validated shapes, silhouette, canvas bounds, scale factor, bbox, and provenance. Keep validation and resource caps in this boundary. On validation failure return a typed unavailable result so the scheduler can choose legacy segmentation without a 500.

- [ ] **Step 5: Re-run and verify GREEN**

- [ ] **Step 6: Commit**

```bash
git add core/vector_engine.py core/pipeline/vector_branch.py \
  core/pipeline/vector_glb_preview.py api/workers/converter_workers.py \
  api/routers/converter/preview.py api/preview_cache_artifacts.py \
  tests/test_vector_engine_part2_5_unit.py tests/test_vector_glb_v2_kernel_unit.py \
  tests/test_converter_workers_unit.py tests/test_converter_preview_unit.py
git commit -m "fix(vector): validate reusable preview geometry"
```

### Task 3: Export an analytic lightweight Vector GLB with stable height identity

**Files:**
- Modify: `core/pipeline/vector_glb_preview.py`
- Reuse: `core/vector_mesh_topology.py`
- Modify: `core/pipeline/s11_glb_preview.py`
- Modify: `tests/test_vector_glb_v2_kernel_unit.py`
- Modify: `tests/test_vector_glb_v2_parity_unit.py`
- Modify: `tests/test_segmented_glb_unit.py`

- [ ] **Step 1: Add failing analytic geometry tests**

Build fixtures with a Bezier-derived curved outline, a hole, overlapping SVG paint order, disconnected parts, two display colours that share one height identity, and one display colour produced by two height identities. Assert:

- vertices are not quantized to the preview pixel grid;
- polygon area and bounds remain within the topology exporter tolerance;
- hole and connected-component counts are preserved;
- parts group by `(display_rgb, height_identity_rgb)`;
- GLB stays display-only and does not emit per-print-material layers;
- output retains `color_RRGGBB`, `backing_plate`, and `preview_canvas_bounds` naming.

- [ ] **Step 2: Add failing height metadata tests**

Extend `VectorPreviewPart` with one explicit optional `height_key`, not a generic metadata bag. Export it to glTF extras on analytic colour meshes. Assert changing `display RGB` leaves `height_key` unchanged and duplicate display colours with different identities remain separate parts.

Keep existing batched material `height_segments` metadata and tests untouched.

- [ ] **Step 3: Run and verify RED**

```bash
python -m pytest \
  tests/test_vector_glb_v2_kernel_unit.py \
  tests/test_vector_glb_v2_parity_unit.py \
  tests/test_segmented_glb_unit.py \
  -k "analytic or height_key or curved or hole" -q
```

- [ ] **Step 4: Implement direct Polygon extrusion**

Use the validated parse/clip footprints and reuse the bounded triangulation/extrusion functions in `vector_mesh_topology.py`. Raster cache arrays may classify an existing component’s current display/height identity, but may not define its boundary. Do not add Shapely simplify in this PR.

Keep current GLB buffer optimization and chunking. When one logical part is chunked, copy the same `height_key` to every chunk. Preserve current 128-colour display cap behavior only as a grouping limit; do not alter print material identity.

- [ ] **Step 5: Re-run and verify GREEN**

- [ ] **Step 6: Commit**

```bash
git add core/pipeline/vector_glb_preview.py core/pipeline/s11_glb_preview.py \
  tests/test_vector_glb_v2_kernel_unit.py tests/test_vector_glb_v2_parity_unit.py \
  tests/test_segmented_glb_unit.py
git commit -m "fix(vector): extrude smooth preview polygons"
```

### Task 4: Route async GLB jobs by session renderer mode and support live switching

**Files:**
- Modify: `api/routers/converter/async_glb.py`
- Modify: `api/routers/converter/preview.py`
- Modify: `api/routers/converter/replace.py`
- Modify: `api/schemas/converter.py`
- Modify: `api/routers/converter/__init__.py` only if route registration requires it
- Modify: `tests/test_async_glb_unit.py`
- Modify: `tests/test_converter_preview_unit.py`
- Modify: `tests/test_converter_replace_integration_unit.py`

- [ ] **Step 1: Add failing renderer-selection tests**

Parameterize async jobs:

- native Vector + setting on + valid source uses analytic exporter;
- setting off uses existing `generate_segmented_glb`;
- setting on + invalid/stale source safely falls back to segmented;
- raster/high-fidelity always uses segmented;
- replacement/recipe rebuild inherits session mode;
- every job receives a unique physical filename;
- a superseded job cannot register or publish its result.

- [ ] **Step 2: Add failing live-rebuild endpoint tests**

Add a narrow request containing `session_id` and `enable_smooth_vector_preview`. Prove the endpoint rejects missing/foreign/closed sessions, updates only server-owned renderer metadata, schedules a fresh job token, and preserves preview cache arrays, 2D URLs, edits, and session id. The response should expose pending status/job token, not a generated-model URL.

- [ ] **Step 3: Run and verify RED**

```bash
python -m pytest \
  tests/test_async_glb_unit.py \
  tests/test_converter_preview_unit.py \
  tests/test_converter_replace_integration_unit.py \
  -k "renderer or smooth_vector or rebuild or superseded" -q
```

- [ ] **Step 4: Introduce one renderer dispatch function**

Keep `schedule_glb_build()` and job-token lifecycle as the single async authority. Add a renderer-mode value to preview-cache metadata, hydrate the validated Vector source only inside the worker, and dispatch to analytic or legacy construction. Do not duplicate schedulers in preview and replace routers.

Preserve `generate_segmented_glb_filename()` UUID semantics and existing unregistered-output cleanup.

- [ ] **Step 5: Add the narrow rebuild route and structured log event**

The route must mutate only renderer preference/job state. Emit one governed success event with `session_id`, selected renderer, and job token; add it to the relevant logging whitelist/test if required by current governance. Do not add INFO progress chatter.

- [ ] **Step 6: Re-run and verify GREEN**

- [ ] **Step 7: Commit**

```bash
git add api/routers/converter/async_glb.py api/routers/converter/preview.py \
  api/routers/converter/replace.py api/schemas/converter.py \
  tests/test_async_glb_unit.py tests/test_converter_preview_unit.py \
  tests/test_converter_replace_integration_unit.py
git commit -m "fix(preview): route vector renderer by session"
```

### Task 5: Connect the Settings switch without rebuilding the preview session

**Files:**
- Modify: `frontend/src/api/converter.ts`
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/stores/converter/types.ts` or the colocated store action interface
- Modify: `frontend/src/stores/converter/store.ts`
- Modify: `frontend/src/hooks/useAutoPreview.ts`
- Add: `frontend/src/hooks/useVectorPreviewRenderer.ts`
- Modify: `frontend/src/__tests__/autoPreview.test.ts`
- Add: `frontend/src/__tests__/vectorPreviewRenderer.test.ts`
- Modify: `frontend/src/stores/__tests__/converter-native-source.test.ts`

- [ ] **Step 1: Add failing initial-request and live-switch tests**

Assert `submitPreview()` forwards the current setting. With a ready native SVG Vector session, toggle the setting and assert:

- no `submitPreview()` call;
- session id, 2D preview, edit history, selection document, and current GLB remain intact while pending;
- exactly one quick-GLB rebuild request is sent;
- polling atomically swaps to the returned URL;
- rapid on→off→on accepts only the final job token/URL;
- raster, high-fidelity, batch, model-surface-only, and no-session states send no rebuild.

- [ ] **Step 2: Add failing auto-preview identity test**

Prove the renderer preference is not included in `useAutoPreview`’s full preview identity. Also change the existing dimension expectation in Task 8 rather than coupling the two concerns here.

- [ ] **Step 3: Run and verify RED**

```bash
python scripts/run_vitest.py run \
  src/__tests__/autoPreview.test.ts \
  src/__tests__/vectorPreviewRenderer.test.ts \
  src/stores/__tests__/converter-native-source.test.ts
```

- [ ] **Step 4: Implement a focused renderer hook/action**

Use a hook owned by the converter screen to observe `enableSmoothVectorPreview`. The settings setter only persists the preference; the converter action decides whether the current session is an eligible native SVG Vector session and invokes the rebuild endpoint. Reuse `_pollAsyncGlb()` and its sequence/token checks; do not make `settingsStore` own network orchestration.

- [ ] **Step 5: Re-run and verify GREEN**

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/converter.ts frontend/src/api/types.ts \
  frontend/src/stores/converter frontend/src/hooks/useAutoPreview.ts \
  frontend/src/hooks/useVectorPreviewRenderer.ts \
  frontend/src/__tests__/autoPreview.test.ts \
  frontend/src/__tests__/vectorPreviewRenderer.test.ts \
  frontend/src/stores/__tests__/converter-native-source.test.ts
git commit -m "feat(preview): switch vector renderer live"
```

### Task 6: Make processed model-surface colour and all async preview writes session-safe

**Files:**
- Modify: `frontend/src/components/Scene3D.tsx`
- Modify: `frontend/src/stores/converter/store.ts`
- Add or modify: `frontend/src/stores/converter/previewCommitGuard.ts`
- Modify: `frontend/src/__tests__/Scene3D.test.tsx`
- Modify: `frontend/src/__tests__/ModelSurfaceSelector3D.test.tsx`
- Modify: `frontend/src/__tests__/replace-preview.property.test.ts`
- Modify: gradient/multi-select/custom-recipe store tests already covering their actions

- [ ] **Step 1: Add failing model-surface source tests**

Assert the selector receives `previewBaseImageUrl` after colour preview and falls back to `imagePreviewUrl` only before a clean processed preview exists. A temporary selection/highlight `previewImageUrl` must never become the texture. Cover initial LUT result, batch replacement, custom recipe, undo, and redo.

- [ ] **Step 2: Add failing stale-response tests for every writer**

For batch replace, custom recipe, multi-select, gradient replace, `submitReplacePreview`, undo, and redo, resolve an old promise after switching session or incrementing `previewRequestRevision`. Assert it cannot update `previewBaseImageUrl`, `previewImageUrl`, `previewGlbUrl`, or loading state for the new session.

- [ ] **Step 3: Run and verify RED**

```bash
python scripts/run_vitest.py run \
  src/__tests__/Scene3D.test.tsx \
  src/__tests__/ModelSurfaceSelector3D.test.tsx \
  src/__tests__/replace-preview.property.test.ts \
  src/__tests__/converter-store-confirm-replacement-gradient-region.test.ts \
  src/__tests__/converter-store-gradient-region-pixel-replace.test.ts
```

- [ ] **Step 4: Implement one captured preview commit guard**

Capture `sessionId`, `previewRequestRevision`, and replacement epoch before each request. Route success, failure, and finally/loading commits through one pure predicate/helper. Keep endpoint-specific payload handling outside the guard.

Change only the model-surface artwork selector to `previewBaseImageUrl ?? imagePreviewUrl`; leave normal 2D highlight behavior unchanged. Preserve adaptive texture budgeting, CanvasTexture disposal, filtering, and SVG fallback.

- [ ] **Step 5: Re-run and verify GREEN**

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/Scene3D.tsx frontend/src/stores/converter \
  frontend/src/__tests__/Scene3D.test.tsx \
  frontend/src/__tests__/ModelSurfaceSelector3D.test.tsx \
  frontend/src/__tests__/replace-preview.property.test.ts \
  frontend/src/__tests__/converter-store-confirm-replacement-gradient-region.test.ts \
  frontend/src/__tests__/converter-store-gradient-region-pixel-replace.test.ts
git commit -m "fix(surface): show current processed artwork colour"
```

### Task 7: Preserve relief height identity in the viewer

**Files:**
- Modify: `frontend/src/components/InteractiveModelViewer.tsx`
- Modify: `frontend/src/__tests__/InteractiveModelViewer.test.ts`

- [ ] **Step 1: Add failing height-resolution tests**

Build an analytic `color_RRGGBB` mesh whose `userData.height_key` differs from its display colour. Assert relief resolves `colorHeightMap[height_key]`, display remapping does not change Z, old GLBs without metadata still fall back to mesh-name colour, and batched `height_segments` behavior is unchanged.

- [ ] **Step 2: Run and verify RED**

```bash
python scripts/run_vitest.py run src/__tests__/InteractiveModelViewer.test.ts
```

- [ ] **Step 3: Add one height-key resolver**

Use a pure helper that validates six-digit metadata and falls back to `extractHexFromMeshName()`. Apply it only to single-part relief height lookup; do not disturb colour material selection or batched segment deformation.

- [ ] **Step 4: Re-run and verify GREEN**

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/InteractiveModelViewer.tsx \
  frontend/src/__tests__/InteractiveModelViewer.test.ts
git commit -m "fix(relief): preserve vector height identity"
```

### Task 8: Restore live dimensions and unify creative-feature coordinates

**Files:**
- Modify: `frontend/src/hooks/useAutoPreview.ts`
- Add: `frontend/src/components/preview/previewSpace.ts`
- Modify: `frontend/src/components/Scene3D.tsx`
- Modify: `frontend/src/components/InteractiveModelViewer.tsx`
- Modify: `frontend/src/components/KeychainLoop3D.tsx` or its actual helper component
- Modify: `frontend/src/components/FridgeMagnet3D.tsx` or current placement helper
- Modify: `frontend/src/components/OutlineFrame3D.tsx`
- Modify: `frontend/src/components/CloisonneWire3D.tsx`
- Verify: `frontend/src/components/PuzzleOverlay3D.tsx`
- Modify: `frontend/src/__tests__/autoPreview.test.ts`
- Modify: `frontend/src/__tests__/Scene3D.test.tsx`
- Modify: `frontend/src/__tests__/InteractiveModelViewer.test.ts`
- Modify existing creative-feature tests

- [ ] **Step 1: Add failing no-regeneration dimension tests**

After a successful ordinary preview, change target width/derived height and assert no invalidation, no preview request, no session/GLB clearing, and immediate scale change. Keep a separate large-format case that still refreshes its tile/layout state.

- [ ] **Step 2: Add failing world-millimetre coordinate tests**

For non-unit and slightly non-uniform XY scales assert:

- asset bounds and colour geometry scale;
- keychain anchor follows scaled bounds while ring/hole/offset remain fixed mm;
- fridge centre uses the same centre-relative mm state in preview and generate payload;
- outline width and cloisonne wire width/height remain fixed world mm;
- puzzle canvas follows scaled bounds through its existing lightweight layout update;
- camera framing and pointer/drag inverse transforms use the same coordinate conversion.

- [ ] **Step 3: Run and verify RED**

```bash
python scripts/run_vitest.py run \
  src/__tests__/autoPreview.test.ts \
  src/__tests__/Scene3D.test.tsx \
  src/__tests__/InteractiveModelViewer.test.ts \
  src/__tests__/KeychainLoop3D.test.tsx \
  src/__tests__/FridgeMagnetSettings.test.tsx
```

Use the actual existing filenames discovered in the repository; do not create duplicate test suites solely to match this plan’s illustrative names.

- [ ] **Step 4: Implement `PreviewSpace` as pure coordinate math**

Represent asset-local bounds, target/display bounds, XY scale, and local↔display transforms in one small module. Move only duplicated coordinate arithmetic into it. Remove target dimensions from the ordinary auto-preview identity; preserve the explicit large-format exception.

Keep absolute-mm creative geometry outside the scaled asset group or apply the inverse scale required to preserve its world dimensions. Do not change final generation parameter units.

- [ ] **Step 5: Re-run and verify GREEN**

- [ ] **Step 6: Commit**

```bash
git add frontend/src/hooks/useAutoPreview.ts frontend/src/components/preview \
  frontend/src/components/Scene3D.tsx frontend/src/components/InteractiveModelViewer.tsx \
  frontend/src/components/OutlineFrame3D.tsx frontend/src/components/CloisonneWire3D.tsx \
  frontend/src/__tests__ frontend/src/components/__tests__
git commit -m "fix(preview): keep dimensions and overlays live"
```

### Task 9: Replay existing edits onto fresh current-size print analysis

**Files:**
- Modify: `api/preview_cache_artifacts.py`
- Modify: `api/routers/converter/generate.py`
- Modify: `core/vector_engine.py`
- Modify: `core/pipeline/vector_branch.py`
- Modify the raster override helper in `core/pipeline/` selected after code inspection
- Modify: `tests/test_vector_matched_rgb_overrides_unit.py`
- Modify: `tests/test_converter_recipe_override_unit.py`
- Modify: `tests/test_dynamic_svg_edit_lifecycle_integration_unit.py`
- Modify: `tests/test_converter_generate_unit.py`
- Add focused raster projection tests in the closest existing generate/override suite

- [ ] **Step 1: Add failing `EditProjectionGrid` tests**

Define pixel-centre normalized mapping and cover equal size, grow, shrink, aspect-preserving rounding, and crossing the 1600 px cap. Assert shape/component votes are stable at boundaries and outside-solid pixels never claim geometry.

- [ ] **Step 2: Add failing Vector replay tests**

Preview at width A, perform spatial colour/material and recipe edits, then generate at width B. Assert:

- no width-mismatch 409 when all required artifacts are current and session-owned;
- current-size `analyze_svg()` remains the geometry authority;
- `matched_rgb`, stable `height_identity_rgb`, material recipes, custom recipe masks, appended layers, virtual materials, and dynamic material layers replay correctly;
- untouched components exactly equal a fresh width-B analysis;
- missing/stale/mismatched pristine or current artifacts fail closed with actionable 409;
- no edits requires no replay artifacts and generates normally.

- [ ] **Step 3: Add failing raster/high-fidelity replay tests**

Run fresh current-size analysis first, project only the delta between pristine and edited preview artifacts, and prove untouched pixels retain fresh analysis. Do not resize the entire old material matrix into the new print grid.

- [ ] **Step 4: Run and verify RED**

```bash
python -m pytest \
  tests/test_vector_matched_rgb_overrides_unit.py \
  tests/test_converter_recipe_override_unit.py \
  tests/test_dynamic_svg_edit_lifecycle_integration_unit.py \
  tests/test_converter_generate_unit.py \
  -k "dimension or projection or cached_edit or recipe_override" -q
```

- [ ] **Step 5: Implement one explicit projection contract**

Add a small typed `EditProjectionGrid`/mapping helper consumed by both `apply_matched_rgb_overrides_to_analysis()` and `apply_recipe_overrides_to_analysis()`. Keep current public signatures compatible by adding keyword-only optional projection data with legacy defaults.

At the API boundary, distinguish no edits, replayable edits, and missing/stale replay state. Remove target width only from edit-cache compatibility; keep it in full generation identity and every 3MF computation.

- [ ] **Step 6: Re-run and verify GREEN**

- [ ] **Step 7: Commit**

```bash
git add api/preview_cache_artifacts.py api/routers/converter/generate.py \
  core/vector_engine.py core/pipeline/vector_branch.py core/pipeline \
  tests/test_vector_matched_rgb_overrides_unit.py \
  tests/test_converter_recipe_override_unit.py \
  tests/test_dynamic_svg_edit_lifecycle_integration_unit.py \
  tests/test_converter_generate_unit.py
git commit -m "fix(generate): project edits across live dimensions"
```

### Task 10: Preserve lifecycle, reporting, and release traceability

**Files:**
- Read before editing: `docs/bug-report-reproducibility.md`
- Read before editing: `docs/announcement-maintenance.md`
- Modify bug-report context/schema/tests at the existing renderer-settings capture location
- Modify: `frontend/src/data/announcements.ts`
- Modify announcement tests required by the maintenance guide
- Modify lifecycle tests in `tests/test_converter_preview_integration_unit.py`, `tests/test_converter_generate_integration_unit.py`, and `tests/test_async_glb_unit.py`

- [ ] **Step 1: Add failing lifecycle tests**

Prove concurrent renderer jobs use immutable URLs, superseded files are cleaned, the active GLB and Vector parse/clip artifact disappear after closing the preview session, and the final 3MF download still succeeds after source session close/switch.

- [ ] **Step 2: Capture the renderer preference in bug-report reproduction context**

Record the browser display preference and selected renderer mode so a report can reproduce smooth-versus-legacy preview differences. Keep it out of print parameters and share cards.

- [ ] **Step 3: Add a bilingual user-facing announcement**

Describe smooth SVG preview, live dimension scaling, accurate model-surface colours, and the Settings fallback without implementation jargon. Follow announcement history/version semantics exactly.

- [ ] **Step 4: Run focused lifecycle and maintenance tests**

```bash
python -m pytest \
  tests/test_async_glb_unit.py \
  tests/test_converter_preview_integration_unit.py \
  tests/test_converter_generate_integration_unit.py -q
python scripts/run_vitest.py run src/__tests__/announcements.test.ts
```

- [ ] **Step 5: Commit**

```bash
git add docs frontend/src/data/announcements.ts frontend/src api tests
git commit -m "docs(preview): publish smooth vector behavior"
```

### Task 11: Full verification and R4C1 reality check

**Files:**
- Verify only unless a real defect is found
- Use fixture: `/Volumes/personal_folder/person_8ba86fa3823aff049badd414e7c525f2_20260814_130551_vector.svg`
- Compare existing print model when needed: `/Users/min/.codex/worktrees/e388/Lumina-studio/output/person_8ba86fa3823aff049badd414e7c525f2_20260814_130551_vector_Preview_20260827_161259.glb`

- [ ] **Step 1: Run focused backend suites**

```bash
python -m pytest \
  tests/test_async_glb_unit.py \
  tests/test_segmented_glb_unit.py \
  tests/test_vector_glb_v2_kernel_unit.py \
  tests/test_vector_glb_v2_parity_unit.py \
  tests/test_vector_matched_rgb_overrides_unit.py \
  tests/test_converter_recipe_override_unit.py \
  tests/test_dynamic_svg_edit_lifecycle_integration_unit.py \
  tests/test_converter_preview_unit.py \
  tests/test_converter_generate_unit.py -v
```

- [ ] **Step 2: Run focused frontend suites through the wrapper**

```bash
python scripts/run_vitest.py run \
  src/__tests__/autoPreview.test.ts \
  src/__tests__/Scene3D.test.tsx \
  src/__tests__/InteractiveModelViewer.test.ts \
  src/__tests__/ModelSurfaceSelector3D.test.tsx \
  src/__tests__/vectorPreviewRenderer.test.ts \
  src/components/__tests__/SettingsPanel.layout.test.tsx \
  src/__tests__/settings-store.property.test.ts
```

- [ ] **Step 3: Run repository gates**

```bash
python scripts/run_smoke_tests.py
python scripts/log_quality_check.py --mode fast
```

Run the logging governance unit trio as well if any logger/event whitelist changed.

- [ ] **Step 4: Run both R4C1 timing sequences in a real browser**

Measure and record:

1. preview → immediate Generate before GLB ready;
2. wait for preview GLB → Generate;
3. replace/recipe edit → change dimensions → Generate;
4. smooth switch on/off/on in the same session;
5. relief, outline, cloisonne, keychain, fridge magnet, puzzle, coating, and model surface.

Capture selected URL, `Content-Length`, local file size, vertices/faces, load time, peak browser/backend memory, and screenshots at normal and high-DPR zoom. Verify the model-surface texture uses processed colours without visible SVG pixelation.

- [ ] **Step 5: Verify 3MF is unchanged**

Compare generated 3MF object/material/topology metadata and, if needed, open in Bambu Studio or OrcaSlicer to verify slice coverage and material identity. The browser renderer switch must not change the 3MF hash/content except for known nondeterministic package metadata.

- [ ] **Step 6: Stop all local processes**

Use `python start_all.py --kill`, then inspect for leftover `api_server.py`, Vite, Vitest, esbuild, or project-specific Node processes.

### Task 12: Independent review, push, and PR

- [ ] **Step 1: Run `verification-before-completion`**

Re-run any command needed to support every final claim. Capture exact command results, R4C1 metrics, and remaining limitations.

- [ ] **Step 2: Request independent code review**

Ask a read-only independent agent to review the final diff against the approved design, specifically checking geometry correctness, setting fallback, session/TTL ownership, async stale writes, coordinate units, edit projection, and accidental 3MF changes. Verify each finding against code before changing anything.

- [ ] **Step 3: Commit any verified review fixes and re-run affected tests**

- [ ] **Step 4: Verify branch and push normally**

```bash
git branch --show-current
git status --short
git log --oneline --decorate origin/dev-refactor..HEAD
git push -u origin MOVIBALE/fix/smooth-vector-live-preview
```

Never push to `dev-refactor`, never force-push, and do not merge.

- [ ] **Step 5: Open one independent PR against `dev-refactor`**

State explicitly in the PR description that the PR is separate from #585, preserves #586’s lightweight-preview authority, changes no 3MF geometry, and includes the default-on Settings fallback. Report exact head SHA, PR URL, test matrix, R4C1 measurements, and limitations to the user.
