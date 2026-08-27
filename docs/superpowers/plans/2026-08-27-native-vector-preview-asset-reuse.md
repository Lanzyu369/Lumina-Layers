# Native Vector Preview Asset Reuse Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep ordinary planar native Vector/SVG browser previews on the lightweight segmented GLB and reuse that registered asset during generation without changing printable geometry or download lifecycle.

**Architecture:** Separate preview-asset reuse eligibility from raster analysis reuse. The generate route will validate a ready GLB against preview provenance, session ownership, current registration, and generated-surface exceptions; the Vector branch will reuse the validated path after 3MF export, while the route preserves the original URL instead of registering the same file twice. The frontend will treat a missing planar Vector quick preview as a pending state rather than falling back to the generated print GLB.

**Tech Stack:** FastAPI, Python 3.14, pytest, React 19, TypeScript, Zustand, Vitest, Three.js, Playwright browser verification.

---

### Task 1: Lock the backend routing and lifecycle contract

**Files:**
- Modify: `tests/test_converter_generate_unit.py`
- Modify: `api/routers/converter/generate.py`

- [x] **Step 1: Add failing generate-route tests**

Add endpoint tests that build a Vector preview cache with the full provenance fields and a session-owned `glb_url`, then assert:

```python
assert submitted_params["reuse_preview_analysis"] is False
assert submitted_params["preview_glb_path"] == str(preview_glb_path)
assert response.json()["preview_3d_url"] == f"/api/files/{preview_glb_id}"
assert set(_test_registry.get_session_entries(sid)) == {preview_glb_id}
```

Add separate cases for a missing file, a foreign-session registry entry, parameter mismatch, relief, coating, and model-surface overlay. Each unsafe case must pass `preview_glb_path=None` to the worker and must not return the stale preview URL.

- [x] **Step 2: Run the tests and verify RED**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/test_converter_generate_unit.py -k "vector and preview_glb" -q
```

Expected: the ready planar Vector case fails because `preview_glb_path` is `None`; lifecycle assertions fail if a reused path is registered again.

- [x] **Step 3: Separate GLB reuse eligibility from raster analysis reuse**

Implement private helpers in `api/routers/converter/generate.py` with these contracts:

```python
def _can_reuse_planar_vector_preview_glb(...) -> tuple[bool, str]:
    if core_modeling_mode != CoreModelingMode.VECTOR:
        return False, "modeling_mode_not_vector"
    if request.enable_relief:
        return False, "relief_enabled"
    if request.enable_coating:
        return False, "coating_enabled"
    if uses_model_surface_overlay:
        return False, "model_surface_overlay_enabled"
    return _preview_analysis_params_match(...)
```

Keep `_can_reuse_preview_analysis()` raster-only and add `enable_coating` to its generated-surface exclusions. Resolve a registered preview as `(url, path)` only when its file id belongs to the same session and `registry.resolve()` still succeeds.

- [x] **Step 4: Preserve the original registration on worker return**

When `result["glb_path"]` is the same real path as the validated input preview path, re-read the current session cache and return its still-current URL. Do not call `register_path()` a second time and do not delete the session-owned path if the cache changed while generation was running. Continue registering a newly generated fallback GLB normally.

- [x] **Step 5: Run the backend route tests and verify GREEN**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/test_converter_generate_unit.py -k "preview_glb or generated_download_survives" -q
```

Expected: all selected tests pass, including final 3MF download after source-session close.

### Task 2: Make the native Vector branch consume the validated asset

**Files:**
- Modify: `tests/test_converter_vector_export_unit.py`
- Modify: `core/pipeline/vector_branch.py`

- [x] **Step 1: Add failing Vector branch tests**

Add a focused test around `_run_vector_branch()` that supplies an existing `preview_glb_path`, lets the normal 3MF export complete through existing mocks, and replaces `export_vector_glb_preview()` with an assertion failure. Assert the returned `result_tuple[1]` is the input path. Add a second case with a missing path and assert the exporter is called to create the fallback GLB.

- [x] **Step 2: Run the tests and verify RED**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/test_converter_vector_export_unit.py -k "preview_glb" -q
```

Expected: the reuse case fails because the Vector branch calls `export_vector_glb_preview()` unconditionally.

- [x] **Step 3: Add the minimal reuse branch**

Immediately after 3MF export and bed-centering, use an existing regular file from `ctx["preview_glb_path"]` as `glb_path`; emit the DEBUG event `vector_glb_reused`. If the path is absent by that point, execute the existing generated-GLB export unchanged.

- [x] **Step 4: Run the Vector branch tests and verify GREEN**

Run the command from Step 2 and the adjacent Vector preview/3MF tests. Expected: reuse and fallback pass without changing scene, writer, slots, or 3MF output.

### Task 3: Prevent the frontend's temporary large-GLB selection

**Files:**
- Modify: `frontend/src/stores/__tests__/converter-native-source.test.ts`
- Modify: `frontend/src/stores/converter/store.ts`

- [x] **Step 1: Change the existing race test to the required behavior**

Seed an SVG file in Vector mode, return `preview_glb_url: null`, resolve generation first with `/api/files/generated-print.glb`, and assert before advancing polling timers:

```ts
expect(useConverterStore.getState().modelUrl).toBeNull();
expect(useConverterStore.getState().previewGlbUrl).toBeNull();
```

Then deliver `/api/files/segmented-preview.glb` from GLB status and assert it becomes `previewGlbUrl` while `modelUrl` remains null. Keep ordinary raster fallback and generated heightmap/relief-surface cases as separate assertions.

- [x] **Step 2: Run the frontend test and verify RED**

Run:

```bash
CI=true .venv/bin/python scripts/run_vitest.py run src/stores/__tests__/converter-native-source.test.ts
```

Expected: the immediate Vector assertion receives the generated print GLB URL.

- [x] **Step 3: Centralize generated-model ownership**

Add a small private selector in `store.ts` that returns false for ordinary SVG + Vector when the segmented URL is pending, while preserving generated ownership for workflows whose visible surface cannot be represented by the quick preview. Use the selector in `submitGenerate()` and retain the poll-sequence cancellation guard for generated-surface ownership.

- [x] **Step 4: Run focused frontend tests and verify GREEN**

Run:

```bash
CI=true .venv/bin/python scripts/run_vitest.py run src/stores/__tests__/converter-native-source.test.ts src/__tests__/Scene3D.test.tsx src/__tests__/converter-store-relief-generate.test.ts
```

Expected: all selected files pass and the Vector race never exposes the generated URL to `Scene3D`.

### Task 4: Verify regression boundaries and artifact lifecycle

**Files:**
- Modify only if a failing boundary test reveals a defect.

- [x] **Step 1: Run focused backend coverage**

```bash
.venv/bin/python -m pytest tests/test_converter_generate_unit.py tests/test_converter_vector_export_unit.py tests/test_pipeline_step_modules_unit.py tests/test_segmented_glb_unit.py tests/test_async_glb_unit.py tests/test_converter_cleanup_integration_unit.py tests/test_s09_export_3mf_unit.py -v
```

- [x] **Step 2: Run focused frontend coverage and build**

```bash
CI=true .venv/bin/python scripts/run_vitest.py run src/stores/__tests__/converter-native-source.test.ts src/__tests__/Scene3D.test.tsx src/__tests__/glb-async-polling.test.ts src/__tests__/converter-store-cleanup.test.ts src/__tests__/converter-store-relief-generate.test.ts
pnpm dlx pnpm@10.33.2 build
```

- [x] **Step 3: Run smoke and log-quality gates**

```bash
CI=true .venv/bin/python scripts/run_smoke_tests.py
.venv/bin/python scripts/log_quality_check.py --mode fast
```

Expected: smoke and fast log quality pass without weakening thresholds.

### Task 5: Replay R4C1 in both timing orders

**Files:**
- Create untracked evidence only under `.scratch/` or `/tmp`; do not commit source material or generated user artifacts.

- [x] **Step 1: Start and observe the real application**

Use the real SVG `/Volumes/personal_folder/person_8ba86fa3823aff049badd414e7c525f2_20260814_130551_vector.svg`, start Lumina with the repository launcher, and automate the browser through the existing UI. Record resource timing entries for every `.glb`, selected model URL, file size, preview/generate wall time, and browser heap/renderer diagnostics.

- [x] **Step 2: Verify preview then immediate generate**

Trigger generation while GLB status is still pending. Assert no generated print GLB request appears in browser network entries; wait for the segmented GLB and record that it becomes the rendered source.

- [x] **Step 3: Verify wait then generate**

Wait for the segmented GLB first, generate, and assert the same URL remains authoritative, the backend reuses its file path, and no second GLB registration/download occurs.

- [x] **Step 4: Protect 3MF output**

Compare the generated 3MF package structure, material slots, object/triangle counts, coverage metadata, and extracted model payload against a baseline generated from the same `origin/dev-refactor` inputs. Escalate to Bambu Studio/Orca only if these deterministic checks differ.

- [x] **Step 5: Stop every process**

Run `python3 start_all.py --kill` and verify no `api_server.py`, `start_all.py`, Vite, Vitest, esbuild, or worktree-owned Node process remains.

### Task 6: Independent review and PR delivery

**Files:**
- Review all changed files and the plan.

- [x] **Step 1: Inspect the final diff and run fresh verification**

Check `git diff --check`, `git status --short`, the complete relevant test commands, and the R4C1 evidence. Confirm #585 files and commits are absent from the branch range.

- [ ] **Step 2: Request an independent code review**

Give the reviewer `BASE_SHA=cb736342e2d1aed382b98e45e36e44ac1287a3eb`, the final head SHA, this plan, and the user's five goals. Fix all Critical and Important findings, then re-run affected tests.

- [ ] **Step 3: Commit and publish the isolated branch**

Use Conventional Commits with English then Chinese rationale in the commit body. Push `MOVIBALE/fix/native-vector-preview-asset-reuse` normally and open a PR against `dev-refactor`; do not merge and do not force-push.

- [ ] **Step 4: Report exact delivery evidence**

Report branch, exact head, PR link, test counts, R4C1 URLs/sizes/timing/memory, 3MF comparison, and any remaining limitations.
