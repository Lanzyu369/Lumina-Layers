# Native Module Capability Guard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent unsafe or stale native SVG mesh modules from being used unless they explicitly declare the triangulation area guard proven by the corpus benchmark.

**Architecture:** Keep `core.vector_native_mesh.run_length_extrude_native_hybrid()` as the Python safety boundary. Before batching run groups into the native module, inspect a small `native_mesh_capabilities()` declaration. If `triangulation_area_guard` is absent or false, skip the native call and route all run groups through the existing Python fallback while recording stats.

**Tech Stack:** Python 3.12, pytest, optional C++ `clipper2_batch` POC in `.scratch/vector_cpp_spike`.

---

### Task 1: Add Python Capability Guard Coverage

**Files:**
- Modify: `tests/test_vector_native_mesh_unit.py`

- [x] **Step 1: Write a failing test for unguarded native modules**

Add a test where a fake native module has `merge_run_groups_to_meshes` but no `native_mesh_capabilities`. The test should assert the native function is not called, `fallback_groups == 1`, and `native_capability_error == "triangulation_area_guard_missing"`.

- [x] **Step 2: Run the focused test to verify red**

Run:
`.venv/bin/python -m pytest tests/test_vector_native_mesh_unit.py::test_native_hybrid_falls_back_when_native_module_lacks_area_guard -v`

Expected before implementation: FAIL because the current helper still calls the unguarded native function.

### Task 2: Implement Capability Guard In Python

**Files:**
- Modify: `core/vector_native_mesh.py`
- Modify: `tests/test_vector_native_mesh_unit.py`

- [x] **Step 1: Add capability stats and helpers**

Add `_native_module_has_triangulation_area_guard(module)` and stats fields:
- `native_capability_error`
- `native_triangulation_area_guard`

- [x] **Step 2: Fallback all run groups when the guard is missing**

After run groups and height/z jobs are built, but before `_run_native_job_batch`, detect missing guard and call `_fallback_key(...)` for every group. Do not call native.

- [x] **Step 3: Update existing fake native modules**

Existing tests that expect native success should add `native_mesh_capabilities=lambda: {"triangulation_area_guard": True}`.

- [x] **Step 4: Verify focused tests**

Run:
`.venv/bin/python -m pytest tests/test_vector_native_mesh_unit.py -v`

Expected: PASS.

### Task 3: Add C++ POC Capability Declaration

**Files:**
- Modify: `.scratch/vector_cpp_spike/clipper2_batch_module.cpp`
- Modify: `.scratch/vector_cpp_spike/native_batch_selftest.py`

- [x] **Step 1: Add `native_mesh_capabilities()` to the C++ module**

Return a Python dict containing `{"triangulation_area_guard": True}`.

- [x] **Step 2: Assert the capability in selftest**

Update `native_batch_selftest.py` to assert the capability exists and is true.

- [x] **Step 3: Rebuild and run selftest**

Run:
`.venv/bin/python .scratch/vector_cpp_spike/build_clipper2_batch.py`

Run:
`PYTHONPATH=.scratch/vector_cpp_spike .venv/bin/python .scratch/vector_cpp_spike/native_batch_selftest.py`

Expected: PASS.

### Task 4: Verify Product Effect

**Files:**
- Existing tests and reports

- [x] **Step 1: Run native/vector focused tests**

Run:
`.venv/bin/python -m pytest tests/test_vector_native_mesh_unit.py tests/test_vector_native_mesh_corpus_profile_unit.py tests/test_vector_engine_fixes_unit.py::TestFillRuleSubpathMerging -v`

Expected: PASS.

- [x] **Step 2: Re-run clean corpus with the guarded C++ POC**

Run:
`PYTHONPATH=.scratch/vector_cpp_spike .venv/bin/python scripts/profile_vector_native_mesh_corpus.py '/Volumes/personal_folder/新建文件夹' --repeats 1 --allow-failures --out-dir .scratch/vector_native_mesh_corpus/provided_svgs_clean_fast_capability_guard`

Expected: 17/0/0, with native speedup still above 1.0x.

- [x] **Step 3: Run hygiene checks**

Run:
`.venv/bin/python -m py_compile core/vector_native_mesh.py tests/test_vector_native_mesh_unit.py .scratch/vector_cpp_spike/native_batch_selftest.py`

Run:
`git diff --check -- core/vector_native_mesh.py tests/test_vector_native_mesh_unit.py .scratch/vector_cpp_spike/clipper2_batch_module.cpp .scratch/vector_cpp_spike/native_batch_selftest.py docs/superpowers/plans/2026-06-19-native-module-capability-guard.md`

Run common mojibake-marker scan over touched tracked files, then check for leftover Lumina processes.

Expected: all checks clean.

### Acceptance Gate

- Unguarded native modules are not called and fall back through Python.
- Guarded native modules continue to accelerate valid groups.
- The C++ POC declares the guard capability and selftest verifies it.
- Clean SVG corpus remains 17/0/0 with the guarded POC.
