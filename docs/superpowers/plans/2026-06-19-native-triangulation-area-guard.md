# Native Triangulation Area Guard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a cheap native-side triangulation area guard so complex Clipper2 triangulation overfills fall back to the Python mesh path without requiring expensive Python surface validation for every group.

**Architecture:** Keep the production Python native-hybrid fallback contract unchanged: if the optional native module returns an empty/invalid mesh for a run group, `core/vector_native_mesh.py` already falls back to the reference Python extrusion. Add the guard inside the scratch C++ spike before faces are accepted: compare summed triangle area against the signed ring area for each polygon-with-holes, and abort the native mesh for that group when the relative/absolute drift exceeds tolerance.

**Tech Stack:** Python 3.12, pytest/selftest, Clipper2 C++17, existing `.scratch/vector_cpp_spike/clipper2_batch`.

---

### Task 1: Capture The Triangulation Overfill Reproduction

**Files:**
- Modify: `.scratch/vector_cpp_spike/native_batch_selftest.py`

- [x] **Step 1: Add a 68-point regression fixture**

Add a simplified path reproduced from `2434029652_20260618_201500_vector.svg` Red run `2-2`, poly `68`. It has no holes but currently Clipper2 triangulation overfills the top/bottom area.

- [x] **Step 2: Add a failing selftest assertion**

Assert that `clipper2_batch.merge_run_groups_to_meshes([[path]], close_delta_mm=0, ...)` returns an empty mesh for this path. Before the guard exists, the current C++ module returns a non-empty overfilled mesh, so the test must fail.

Run:
`PYTHONPATH=.scratch/vector_cpp_spike .venv/bin/python .scratch/vector_cpp_spike/native_batch_selftest.py`

Expected before implementation: FAIL with an assertion showing the overfilled native mesh was accepted.

### Task 2: Add Native Triangulation Area Validation

**Files:**
- Modify: `.scratch/vector_cpp_spike/clipper2_batch_module.cpp`

- [x] **Step 1: Add area helpers**

Add helpers that compute:
- signed path area using Clipper2 integer coordinates
- expected polygon area from the signed sum of outer/hole rings
- triangle area sum from `Triangulate(...)`

- [x] **Step 2: Validate before emitting top/bottom faces**

Update the per-polygon triangulation path to reject a polygon when:
- `Triangulate(...)` fails
- triangle area differs from expected filled area beyond a small absolute/relative tolerance

Return an empty `MeshOutput` for the whole run group if any polygon fails. This preserves the Python fallback contract.

- [x] **Step 3: Rebuild and verify the selftest passes**

Run:
`.venv/bin/python .scratch/vector_cpp_spike/build_clipper2_batch.py`

Run:
`PYTHONPATH=.scratch/vector_cpp_spike .venv/bin/python .scratch/vector_cpp_spike/native_batch_selftest.py`

Expected after implementation: PASS.

### Task 3: Re-run Corpus Quality/Performance Comparison

**Files:**
- Write outputs under `.scratch/vector_native_mesh_corpus/provided_svgs_clean_fast_area_guard/`
- Write diagnostic summary under `.scratch/vector_native_mesh_corpus/area_guard_summary.md`

- [x] **Step 1: Run fast native clean corpus without Python surface validation**

Run:
`PYTHONPATH=.scratch/vector_cpp_spike .venv/bin/python scripts/profile_vector_native_mesh_corpus.py '/Volumes/personal_folder/新建文件夹' --repeats 1 --allow-failures --out-dir .scratch/vector_native_mesh_corpus/provided_svgs_clean_fast_area_guard`

Expected: fewer quality FAIL rows than the prior fast native report; target is 17/0/0 if the guard catches all overfilled groups.

- [x] **Step 2: Compare against prior reports**

Compare:
- `.scratch/vector_native_mesh_corpus/provided_svgs_clean_fast_evenodd_bulk/vector_native_mesh_corpus.json`
- `.scratch/vector_native_mesh_corpus/provided_svgs_clean_fast_area_guard/vector_native_mesh_corpus.json`
- `.scratch/vector_native_mesh_corpus/provided_svgs_clean_surface_validated/vector_native_mesh_corpus.json`

Record pass/fail/error counts, build speedup, extrude speedup, fallback group counts, and whether the area guard preserves most of the fast-native speedup.

### Task 4: Verification And Hygiene

**Files:**
- Existing tests and scripts

- [x] **Step 1: Run focused Python tests**

Run:
`.venv/bin/python -m pytest tests/test_vector_native_mesh_corpus_profile_unit.py tests/test_vector_native_mesh_unit.py tests/test_vector_engine_fixes_unit.py::TestFillRuleSubpathMerging -v`

Expected: PASS.

- [x] **Step 2: Run C++ selftest and syntax checks**

Run:
`PYTHONPATH=.scratch/vector_cpp_spike .venv/bin/python .scratch/vector_cpp_spike/native_batch_selftest.py`

Run:
`.venv/bin/python -m py_compile scripts/profile_vector_native_mesh_corpus.py tests/test_vector_native_mesh_corpus_profile_unit.py`

Expected: PASS.

- [x] **Step 3: Run diff, encoding, and process checks**

Run:
`git diff --check -- .scratch/vector_cpp_spike/clipper2_batch_module.cpp .scratch/vector_cpp_spike/native_batch_selftest.py docs/superpowers/plans/2026-06-19-native-triangulation-area-guard.md`

Run a common mojibake-marker scan across touched tracked files.

Run:
`ps -axo pid,command | rg '/Users/min/CascadeProjects/Lumina-studio|api_server.py|start_all.py|vite|vitest|esbuild' | rg -v 'rg '`

Expected: no diff/encoding issues and no local Lumina processes left running.

### Acceptance Gate

- The 68-point overfill fixture fails before the guard and passes after it.
- Fast native clean corpus quality improves without enabling Python surface validation.
- Any remaining failures are explicitly diagnosed with a next action.
- The production Python fallback contract remains unchanged.
