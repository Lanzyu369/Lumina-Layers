# SVG Relief Watertight Preview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate watertight native SVG relief backing meshes without internal walls between adjacent height regions.

**Architecture:** Normalize existing backing/cavity slabs, prefer direct native solid union through the existing optional `manifold3d` dependency, and retain the current exact atomic-prism implementation as an all-or-nothing fallback. Public converter contracts remain unchanged.

**Tech Stack:** Python, NumPy, Shapely, Trimesh, optional manifold3d, pytest

---

### Task 1: Add topology regression coverage

**Files:**
- Modify: `tests/test_vector_engine_mesh_weld_unit.py`

- [ ] **Step 1: Write a failing different-height relief test**

Add a real `_build_relief_meshes` fixture with two edge-adjacent rectangles at
different configured heights. Assemble the `Board` exactly as `build_mesh` does
and assert `is_watertight`, expected bounds, and expected volume.

- [ ] **Step 2: Run the focused test and verify RED**

Run:
`python -m pytest tests/test_vector_engine_mesh_weld_unit.py::test_relief_backing_welds_adjacent_height_steps -v`

Expected: FAIL because the current board is non-watertight.

- [ ] **Step 3: Add a cavity-profile regression test**

Exercise the boundary builder with a full lower shell, a middle footprint with
an interior hole, and a restored upper footprint. Assert watertightness and the
analytical volume.

### Task 2: Build the exposed relief boundary

**Files:**
- Modify: `core/vector_engine.py`
- Test: `tests/test_vector_engine_mesh_weld_unit.py`

- [ ] **Step 1: Add private cap and interval helpers**

Add focused helpers that select oriented caps/side faces from the existing
polygon extrusion output and assemble a volume from active Z-interval footprints.
Keep XY scaling and physical Z units identical to `_extrude_geometry`.

- [ ] **Step 2: Adopt the helper in `_build_relief_meshes`**

Collect the existing backing/cavity slab records, build one stepped `Board` mesh,
and store that single mesh in `board_entry["meshes"]`. Do not change optical
layer generation or method signatures.

- [ ] **Step 3: Run focused tests and verify GREEN**

Run:
`python -m pytest tests/test_vector_engine_mesh_weld_unit.py -v`

Expected: all tests pass.

### Task 3: Verify serialized and integration behavior

**Files:**
- Modify: `tests/test_vector_engine_mesh_weld_unit.py`

- [ ] **Step 1: Add a GLB round-trip assertion**

Export the minimal different-height board through `trimesh.Scene`, reload it,
and assert the loaded mesh remains watertight with the expected volume.

- [ ] **Step 2: Run relevant backend suites**

Run:
`python -m pytest tests/test_vector_engine_mesh_weld_unit.py tests/test_vector_engine_fixes_unit.py tests/test_vector_preview_glb_orientation_unit.py tests/test_pipeline_step_modules_unit.py -v`

Expected: all tests pass.

- [ ] **Step 3: Run repository smoke verification**

Run `python scripts/run_smoke_tests.py` and `git diff --check`.

Expected: both commands exit successfully.

### Task 4: Review and publish

**Files:**
- Modify only files listed above plus this design and plan.

- [ ] **Step 1: Request an independent code review**

Review the branch diff against this plan, resolve all Critical and Important
findings, and rerun affected tests.

- [ ] **Step 2: Commit intentionally**

Stage only the design, plan, implementation, and regression test. Commit with:
`fix(vector): make SVG relief backing watertight`

- [ ] **Step 3: Push and open a draft PR**

Push `MOVIBALE/fix/svg-relief-nonmanifold-preview` and open a draft PR against
`dev-refactor` with root cause, user impact, and verification evidence.

### Task 5: Restore the performance contract

**Files:**
- Modify: `core/vector_engine.py`
- Modify: `tests/test_vector_engine_mesh_weld_unit.py`
- Modify: `requirements-glb-v2.txt`
- Add: `.github/workflows/relief-native-kernel.yml`

- [ ] **Step 1: Add fast-kernel and forced-fallback regressions**

Cover cavities, non-zero Z, XY scaling, point contacts, missing imports, runtime
failures, and invalid native results. Assert that fallback rebuilds the whole Board.

- [ ] **Step 2: Adopt direct native union**

Extrude each merged slab as a manifold CrossSection and batch-union each
area-connected footprint. Validate bounds, volume, finite coordinates, and
watertightness before accepting the result.

- [ ] **Step 3: Prove deployment and performance behavior**

Run the focused tests with the optional dependency installed, add a Windows CI
job that exercises both kernels, and benchmark the real UI-equivalent
Preview-to-Generate flow against the original base and the exact watertight head.
