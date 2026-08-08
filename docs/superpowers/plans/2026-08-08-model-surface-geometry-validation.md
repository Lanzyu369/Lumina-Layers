# Model Surface Geometry Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent model-surface uploads and generation from ending in opaque 500 errors when the STL is not boolean-ready, safely normalize valid multi-body meshes, and show localized actionable errors.

**Architecture:** Add a UI-agnostic validation module under `core/model_surface/` as the only source of truth for boolean readiness. The upload route uses it before registering files, the assembly path uses it before Manifold difference, and the generate route converts stable domain-error prefixes into structured HTTP 422 responses. The existing frontend API error translator maps those codes to regular bilingual strings without adding converter state or request parameters.

**Tech Stack:** Python 3.12, FastAPI, Trimesh, Manifold3D, pytest, React/TypeScript, Zustand i18n, Vitest, Chrome, Electron.

---

### Task 0: Prepare the isolated worktree toolchain

**Files:**
- Runtime-only: `.venv/`
- Runtime-only: `frontend/node_modules/`
- Runtime-only: `electron/node_modules/`

- [ ] **Step 1: Create the worktree-local Python environment**

Run:

```bash
python3.12 -m venv .venv
```

Expected: `.venv/bin/python` exists and reports Python 3.12.

- [ ] **Step 2: Install locked project requirements including Manifold**

Run:

```bash
.venv/bin/python -m pip install -r requirements.txt -r requirements-glb-v2.txt
```

Expected: exit 0; `pytest`, `cryptography`, `trimesh`, `shapely`, and `manifold3d` import successfully.

- [ ] **Step 3: Install frontend dependencies with the pinned pnpm version**

Run:

```bash
pnpm dlx pnpm@10.33.2 --dir frontend install --frozen-lockfile
```

Expected: exit 0 and `frontend/node_modules/` exists; no `package.json` or lockfile diff.

- [ ] **Step 4: Install Electron dependencies with the pinned pnpm version**

Run:

```bash
pnpm dlx pnpm@10.33.2 --dir electron install --frozen-lockfile
```

Expected: exit 0 and `electron/node_modules/` exists; no `package.json` or lockfile diff.

### Task 1: Establish the core boolean-readiness contract

**Files:**
- Create: `core/model_surface/validation.py`
- Create: `tests/test_model_surface_validation_unit.py`
- Modify: `core/model_surface/assembly.py`
- Test: `tests/test_model_surface_boolean_unit.py`

- [ ] **Step 1: Write failing validation tests**

Create tests that use real `trimesh.Trimesh` objects:

```python
def test_validate_rejects_open_mesh():
    mesh = trimesh.creation.box(extents=(20.0, 20.0, 2.0))
    mesh.update_faces(mesh.face_normals[:, 2] < 0.9)
    mesh.remove_unreferenced_vertices()

    with pytest.raises(
        ModelSurfaceError,
        match=r"^model_surface_mesh_not_watertight$",
    ):
        validate_model_surface_mesh_for_boolean(mesh)


def test_prepare_unions_overlapping_watertight_bodies():
    primary = trimesh.creation.box(extents=(20.0, 20.0, 2.0))
    detail = trimesh.creation.box(extents=(8.0, 8.0, 2.0))
    detail.apply_translation((6.0, 0.0, 0.0))
    source = trimesh.util.concatenate((primary, detail))
    source.metadata["name"] = "surface-source"

    prepared = prepare_model_surface_mesh_for_boolean(source)

    assert prepared.is_volume
    assert len(prepared.split(only_watertight=False)) == 1
    assert prepared.metadata["name"] == "surface-source"
    assert prepared.volume < primary.volume + detail.volume
```

- [ ] **Step 2: Run the new tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_model_surface_validation_unit.py -v
```

Expected: collection fails because `core.model_surface.validation` does not exist.

- [ ] **Step 3: Implement the validation module**

Implement these stable constants and public functions with explicit type hints and bilingual Google-style docstrings:

```python
MODEL_SURFACE_MESH_NOT_WATERTIGHT = "model_surface_mesh_not_watertight"
MODEL_SURFACE_MESH_NOT_VOLUME = "model_surface_mesh_not_volume"
MODEL_SURFACE_BOOLEAN_FAILED = "model_surface_boolean_failed"


def validate_model_surface_mesh_for_boolean(mesh: trimesh.Trimesh) -> None:
    if not isinstance(mesh, trimesh.Trimesh) or len(mesh.faces) == 0:
        raise ModelSurfaceError(MODEL_SURFACE_MESH_NOT_VOLUME)
    if not mesh.is_watertight:
        raise ModelSurfaceError(MODEL_SURFACE_MESH_NOT_WATERTIGHT)
    if not mesh.is_winding_consistent or not mesh.is_volume:
        raise ModelSurfaceError(MODEL_SURFACE_MESH_NOT_VOLUME)


def prepare_model_surface_mesh_for_boolean(
    mesh: trimesh.Trimesh,
) -> trimesh.Trimesh:
    validate_model_surface_mesh_for_boolean(mesh)
    parts = list(mesh.split(only_watertight=True))
    if len(parts) <= 1:
        return mesh.copy()
    try:
        result = trimesh.boolean.union(parts, engine="manifold")
    except Exception as exc:
        raise ModelSurfaceError(MODEL_SURFACE_BOOLEAN_FAILED) from exc
    if not isinstance(result, trimesh.Trimesh) or not result.is_volume:
        raise ModelSurfaceError(MODEL_SURFACE_BOOLEAN_FAILED)
    result.metadata.update(mesh.metadata or {})
    return result
```

- [ ] **Step 4: Verify the core tests are GREEN**

Run:

```bash
.venv/bin/python -m pytest tests/test_model_surface_validation_unit.py -v
```

Expected: all new tests pass.

- [ ] **Step 5: Integrate preparation into the actual pocket cut**

In `_cut_surface_polygon_pocket()`, call
`prepare_model_surface_mesh_for_boolean(base_mesh)` before
`trimesh.boolean.difference()` and pass the prepared mesh as the first boolean operand.
Keep cutter construction, tolerances, public function signatures, and result metadata behavior unchanged.

- [ ] **Step 6: Verify focused geometry regression coverage**

Run:

```bash
.venv/bin/python -m pytest tests/test_model_surface_validation_unit.py tests/test_model_surface_boolean_unit.py tests/test_model_surface_assembly_unit.py -v
```

Expected: all tests pass with no warning or error output from the new code.

- [ ] **Step 7: Commit the core contract**

```bash
git add core/model_surface/validation.py core/model_surface/assembly.py tests/test_model_surface_validation_unit.py
git commit -m "fix(model-surface): validate boolean-ready meshes"
```

### Task 2: Reject unsupported uploads with structured 422 errors

**Files:**
- Modify: `api/routers/converter/common.py`
- Modify: `api/routers/converter/model_surface.py`
- Modify: `tests/test_model_surface_api_unit.py`

- [ ] **Step 1: Add an upload regression test**

Add a helper that removes the top faces from a box, exports it as STL, uploads it through
`/api/convert/model-surface/upload`, and asserts:

```python
assert response.status_code == 422
assert response.json()["detail"] == {
    "error": "model_surface_mesh_not_watertight",
    "message": (
        "The model is not a closed solid and cannot be cut safely. "
        "Repair the mesh and upload it again."
    ),
}
```

Also preserve the existing successful closed-box upload test.

- [ ] **Step 2: Run the upload test and verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_model_surface_api_unit.py::test_model_surface_upload_rejects_open_mesh -v
```

Expected: FAIL because the current endpoint returns 200.

- [ ] **Step 3: Add the public error mapping**

In `api/routers/converter/common.py`, add a static allowlist and helper:

```python
MODEL_SURFACE_PUBLIC_ERROR_MESSAGES = {
    "model_surface_mesh_not_watertight": (
        "The model is not a closed solid and cannot be cut safely. "
        "Repair the mesh and upload it again."
    ),
    "model_surface_mesh_not_volume": (
        "The model has invalid solid orientation. Repair its normals and upload it again."
    ),
    "model_surface_thickness_unknown": (
        "The selected surface thickness could not be determined. "
        "Choose another surface or repair the model."
    ),
    "model_surface_insufficient_thickness": (
        "The selected surface is too thin for the current colour stack. "
        "Use fewer layers, a smaller layer height, or a thicker surface."
    ),
    "model_surface_boolean_failed": (
        "The selected surface could not be cut safely. "
        "Repair the model or choose a simpler surface."
    ),
}


def public_model_surface_error_detail(error: object) -> dict[str, str] | None:
    code = str(error or "").partition(":")[0].strip()
    message = MODEL_SURFACE_PUBLIC_ERROR_MESSAGES.get(code)
    return {"error": code, "message": message} if message else None
```

- [ ] **Step 4: Validate the uploaded mesh before registration**

After `_analyze_uploaded_model_surface()` returns but before `registry.register_path()`, call
`validate_model_surface_mesh_for_boolean(loaded.mesh)`. In the existing
`except ModelSurfaceError` block, use `public_model_surface_error_detail(exc)` when known and
fall back to the existing safe string for unrelated parser errors.

- [ ] **Step 5: Verify upload tests are GREEN**

Run:

```bash
.venv/bin/python -m pytest tests/test_model_surface_api_unit.py tests/test_model_surface_loader_unit.py -v
```

Expected: all tests pass; the closed-box upload/select path remains 200.

- [ ] **Step 6: Commit upload validation**

```bash
git add api/routers/converter/common.py api/routers/converter/model_surface.py tests/test_model_surface_api_unit.py
git commit -m "fix(model-surface): reject unsafe upload geometry"
```

### Task 3: Preserve model-surface domain errors through generation

**Files:**
- Modify: `api/routers/converter/generate.py`
- Modify: `core/model_surface/assembly.py`
- Modify: `tests/test_model_surface_preview_integration_unit.py`
- Modify: `tests/test_model_surface_generate_unit.py`
- Test: `tests/test_model_surface_assembly_unit.py`

- [ ] **Step 1: Repair the production-shaped worker-pool test fixtures**

The baseline has three stale successful fakes: two preview cases and one generate case. Change
each from `pool.submit` to `pool.submit_timed` and return:

```python
return (
    {"threemf_path": str(out_path), "glb_path": None, "status_msg": "Surface OK"},
    {"queue_wait_s": 0.0, "worker_execution_s": 0.0, "result_delivery_s": 0.0},
)
```

Assert against `pool.submit_timed.call_args.args` where the submitted arguments are inspected.
This restores the tests' intended contract without modifying production behavior.

- [ ] **Step 2: Add failing route tests for known and unknown domain errors**

Seed a valid model-surface session as the existing routing test does. Configure
`pool.submit_timed` to raise:

```python
ModelSurfaceError(
    "model_surface_insufficient_thickness: pattern=0.400000, available=0.200000"
)
```

Assert status 422 and `detail.error == "model_surface_insufficient_thickness"`. Add a separate
case for `ModelSurfaceError("private_unclassified_surface_error")` and assert the existing
generic 500 detail remains unchanged.

- [ ] **Step 3: Run route tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_model_surface_generate_unit.py -k "routes_model_surface or maps_model_surface" -v
```

Expected: the repaired success fixture passes; the known error test fails because the route
still returns 500.

- [ ] **Step 4: Give thickness failures stable prefixes**

In `build_embedded_overlay_scene()` and `_available_surface_depth_mm()`, replace free-form
user-facing failures with diagnostic strings beginning with:

```python
"model_surface_insufficient_thickness: "
"model_surface_thickness_unknown"
```

Retain actual and available depth values after the colon for structured worker logs.

- [ ] **Step 5: Map known model-surface failures before generic ValueError handling**

Import `ModelSurfaceError` and `public_model_surface_error_detail`. Add this branch before
`except ROUTER_HANDLED_ERRORS` around `pool.submit_timed()`:

```python
except ModelSurfaceError as exc:
    detail = public_model_surface_error_detail(exc)
    if detail is None:
        raise HTTPException(status_code=500, detail=MODEL_GENERATION_FAILED_DETAIL) from exc
    raise HTTPException(status_code=422, detail=detail) from exc
```

- [ ] **Step 6: Verify route and geometry tests are GREEN**

Run:

```bash
.venv/bin/python -m pytest tests/test_model_surface_generate_unit.py tests/test_model_surface_assembly_unit.py -v
```

Expected: all tests pass, including local-depth rejection and the production-shaped fake pool.

- [ ] **Step 7: Commit generation error mapping**

```bash
git add api/routers/converter/generate.py core/model_surface/assembly.py tests/test_model_surface_preview_integration_unit.py tests/test_model_surface_generate_unit.py tests/test_model_surface_assembly_unit.py
git commit -m "fix(model-surface): expose actionable generation errors"
```

### Task 4: Localize structured model-surface errors

**Files:**
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/api/__tests__/client.test.ts`
- Modify: `frontend/src/i18n/translations.ts`

- [ ] **Step 1: Add bilingual failing API-client tests**

Add a table-driven test for English and Chinese that sends a 422 response containing:

```typescript
detail: {
  error: "model_surface_mesh_not_watertight",
  message: "The model is not a closed solid and cannot be cut safely.",
}
```

Expected English:

```text
The model is not a closed solid and cannot be cut safely. Repair the mesh and upload it again.
```

Expected Chinese:

```text
模型不是闭合实体，无法安全开槽。请先修复网格后重新上传。
```

- [ ] **Step 2: Run the client test and verify RED**

Run:

```bash
.venv/bin/python scripts/run_vitest.py run src/api/__tests__/client.test.ts
```

Expected: FAIL because the error code is not in `STRUCTURED_DETAIL_TRANSLATION_KEYS`.

- [ ] **Step 3: Add all five translation entries**

Add regular bilingual strings for not-watertight, not-volume, thickness-unknown,
insufficient-thickness, and boolean-failed errors under `api_error_model_surface_*` keys in
`frontend/src/i18n/translations.ts`.

- [ ] **Step 4: Map stable API codes to the new translation keys**

Extend `STRUCTURED_DETAIL_TRANSLATION_KEYS` in `frontend/src/api/client.ts` with the five exact
server codes. Do not change generic 500 redaction or unknown-code fallback behavior.

- [ ] **Step 5: Verify frontend error handling is GREEN**

Run:

```bash
.venv/bin/python scripts/run_vitest.py run src/api/__tests__/client.test.ts src/stores/__tests__/modelSurfaceStore.test.ts src/__tests__/BasicSettings.test.tsx
```

Expected: all selected Vitest tests pass and the wrapper reports no orphan workers.

- [ ] **Step 6: Commit localization**

```bash
git add frontend/src/api/client.ts frontend/src/api/__tests__/client.test.ts frontend/src/i18n/translations.ts
git commit -m "fix(model-surface): localize geometry failures"
```

### Task 5: Run focused automated gates

**Files:**
- Verify only; no intended edits.

- [ ] **Step 1: Run the complete model-surface backend family**

```bash
.venv/bin/python -m pytest tests/test_model_surface_loader_unit.py tests/test_model_surface_selection_unit.py tests/test_model_surface_artwork_unit.py tests/test_model_surface_boolean_unit.py tests/test_model_surface_assembly_unit.py tests/test_model_surface_api_unit.py tests/test_model_surface_preview_integration_unit.py tests/test_model_surface_generate_unit.py -v
```

Expected: all tests pass.

- [ ] **Step 2: Run logging and exception-governance tests**

```bash
.venv/bin/python -m pytest tests/test_logging_exception_governance_unit.py tests/test_structured_logging_unit.py tests/test_logger_unit.py -v
```

Expected: all tests pass; no whitelist or structured-field regression.

- [ ] **Step 3: Run frontend tests and build**

```bash
.venv/bin/python scripts/run_vitest.py run src/api/__tests__/client.test.ts src/stores/__tests__/modelSurfaceStore.test.ts src/__tests__/BasicSettings.test.tsx
```

```bash
pnpm dlx pnpm@10.33.2 --dir frontend build
```

Expected: selected tests and TypeScript/Vite production build pass.

- [ ] **Step 4: Run source-quality checks**

```bash
git diff --check origin/dev-refactor...HEAD
```

```bash
rg -n "锟|鎷|鍙|涓" core/model_surface api/routers/converter frontend/src tests
```

Expected: diff check exits 0 and no new mojibake marker appears in touched files.

### Task 6: Perform real Chrome and Electron acceptance

**Files:**
- Runtime-only: `/tmp/lumina-model-surface-qa/`
- Verify only; no intended tracked edits.

- [ ] **Step 1: Prepare authentic local samples**

Use these existing files without committing copies:

```text
/Users/min/Library/Mobile Documents/com~apple~CloudDocs/酷乐美/1mesh.stl
/Users/min/CascadeProjects/Lumina-studio/reference-projects/BambuStudio/resources/model/Bambu_Cube.stl
```

Select a real local SVG and the three ticket material profiles. Record SHA-256, byte size,
Trimesh watertight/volume/body-count summary, and SVG size before testing.

- [ ] **Step 2: Start the web application and verify health**

Run from this worktree in a dedicated PTY:

```bash
.venv/bin/python start_all.py
```

Wait until `http://127.0.0.1:8000/api/health` and `http://127.0.0.1:4174` both respond, then
record the actual URLs. Keep the PTY session id so the launcher can be stopped after Chrome
acceptance.

- [ ] **Step 3: Exercise Chrome failure behavior**

Upload `1mesh.stl` through the visible model-surface control. Confirm the UI shows the Chinese
closed-solid repair guidance, Network shows 422, no preview session is created for the rejected
model, and console error count remains zero.

- [ ] **Step 4: Exercise Chrome success behavior**

Upload `Bambu_Cube.stl`, choose a planar face, upload the real SVG, select the ticket materials,
set edge-to-edge, five layers and 0.08 mm, run preview, generate, and download 3MF. Record visible
state, request statuses, session id, material objects, dimensions, and console errors.

- [ ] **Step 5: Parse the downloaded 3MF independently**

Open the ZIP/XML and reconstruct object meshes. Confirm a `surface_base` object and colour slots
exist, all coordinates are finite, the base remains a volume, and the download is non-empty.

- [ ] **Step 6: Repeat failure and success paths in Electron**

Stop the web launcher with `q`, then launch Electron from a dedicated PTY with the pinned package
manager:

```bash
pnpm dlx pnpm@10.33.2 --dir electron start
```

Electron development mode resolves this worktree's `.venv/bin/python` and starts its own backend
and Vite children. Repeat the visible upload, selection, preview, generate, and download actions;
verify the same localized 422 failure and successful 3MF result with no renderer or main-process
exception. Close Electron normally and retain its PTY output as evidence.

- [ ] **Step 7: Stop every process started by the task**

Run:

```bash
.venv/bin/python start_all.py --kill
```

Then inspect process command lines for this worktree's `api_server.py`, `start_all.py`, `vite`,
`vitest`, `esbuild`, and Electron processes. Expected: none remain.

### Task 7: Final review, publish, and open the PR

**Files:**
- Review all branch changes.

- [ ] **Step 1: Inspect scope and rerun final direct gates**

Run `git status -sb`, `git diff --stat origin/dev-refactor...HEAD`, and inspect every diff hunk.
Repeat the complete model-surface test family, frontend targeted tests/build, and `git diff --check`
after the final code change.

- [ ] **Step 2: Commit any final verified adjustment**

Stage only explicit model-surface files. Use Conventional Commits and an English-first,
Chinese-second body. Do not stage runtime logs, downloaded models, generated 3MF files, `.venv`,
or `node_modules`.

- [ ] **Step 3: Push the topic branch**

```bash
git push -u origin MOVIBALE/fix/model-surface-geometry-validation
```

Expected: push succeeds without force and the upstream is the same topic branch.

- [ ] **Step 4: Open a draft PR against `dev-refactor`**

Use title:

```text
fix(model-surface): validate geometry before surface generation
```

The English-first, Chinese-second PR body must include root cause, exact product changes, RED/GREEN
evidence, Chrome/Electron results, focused gates, the missing original `UwU Ghast.stl` limitation,
and explicit reproduction steps with both real local models.

- [ ] **Step 5: Verify remote reality**

Read the created PR back from GitHub and confirm repository, base, head, Draft state, commit SHA,
changed files, and check-run state match the local branch. Report the PR URL only after this check.
