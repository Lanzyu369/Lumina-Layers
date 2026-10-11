# Productize Clipper2 Native Extension Implementation Plan

> Deployment update (2026-10-06): Docker support and the public-test bypass
> are retired. This historical record preserves earlier implementation and
> validation evidence; use [Runtime support](../../runtime-support.md) for current behavior.
> 部署更新：Docker 支持及公网测试访问旁路已移除；本文保留历史实现与验证记录，当前运行方式以上述说明为准。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the validated `clipper2_batch` native SVG mesh accelerator out of `.scratch` into a reproducible repository build path used by local profiling.

**Architecture:** Add a focused `native/clipper2_batch/` source tree with the C++ Python extension, the minimal Clipper2 vendor files needed to build it, and the Boost license. Add `scripts/build_native_extensions.py` using standard-library `sysconfig` plus a POSIX C++ compiler so the extension builds to the repo root as `clipper2_batch<EXT_SUFFIX>`, which `core.vector_native_mesh` can import. Keep the Python capability guard as the quality boundary.

**Tech Stack:** Python 3.12+, standard-library build script, C++17, Clipper2 Boost-licensed sources, pytest, existing corpus profiler.

---

### Task 1: Add Build Script Metadata Coverage

**Files:**
- Create: `tests/test_build_native_extensions_unit.py`

- [x] **Step 1: Write failing tests for native extension metadata**

Add tests that import `scripts.build_native_extensions`, call `get_clipper2_extension()`, and assert:
- extension name is `clipper2_batch`
- all source paths live under `native/clipper2_batch`
- source list contains `clipper2_batch_module.cpp`, `clipper.engine.cpp`, `clipper.offset.cpp`, and `clipper.triangulation.cpp`
- no source path contains `.scratch`

- [x] **Step 2: Run red test**

Run:
`.venv/bin/python -m pytest tests/test_build_native_extensions_unit.py -v`

Expected before implementation: FAIL with `ModuleNotFoundError` or missing source assertions.

### Task 2: Move Native Sources Into A Product Tree

**Files:**
- Create: `native/clipper2_batch/clipper2_batch_module.cpp`
- Create: `native/clipper2_batch/Clipper2/CPP/Clipper2Lib/include/clipper2/*.h`
- Create: `native/clipper2_batch/Clipper2/CPP/Clipper2Lib/src/*.cpp`
- Create: `native/clipper2_batch/Clipper2/LICENSE`

- [x] **Step 1: Copy validated C++ module**

Copy `.scratch/vector_cpp_spike/clipper2_batch_module.cpp` to `native/clipper2_batch/clipper2_batch_module.cpp`.

- [x] **Step 2: Copy minimal Clipper2 vendor files**

Copy only:
- `Clipper2/LICENSE`
- `CPP/Clipper2Lib/include/clipper2/*.h`
- `CPP/Clipper2Lib/src/clipper.engine.cpp`
- `CPP/Clipper2Lib/src/clipper.offset.cpp`
- `CPP/Clipper2Lib/src/clipper.triangulation.cpp`

### Task 3: Add Reproducible Build Script

**Files:**
- Create: `scripts/build_native_extensions.py`
- Modify: `tests/test_build_native_extensions_unit.py`

- [x] **Step 1: Implement `get_clipper2_extension()`**

Return build metadata configured with:
- `name="clipper2_batch"`
- C++17 compile args
- native module source
- Clipper2 engine/offset/triangulation sources
- include dir pointing to `native/clipper2_batch/Clipper2/CPP/Clipper2Lib/include`

- [x] **Step 2: Implement CLI build entry point**

Use `sysconfig` and a POSIX C++ compiler to build the extension into the repo root.

- [x] **Step 3: Run green unit test**

Run:
`.venv/bin/python -m pytest tests/test_build_native_extensions_unit.py -v`

Expected: PASS.

### Task 5: Build And Verify Product Native Module

**Files:**
- Existing reports under `.scratch/vector_native_mesh_corpus/`

- [x] **Step 1: Build the product native extension**

Run:
`.venv/bin/python scripts/build_native_extensions.py`

Expected: `clipper2_batch<EXT_SUFFIX>` exists at repo root.

- [x] **Step 2: Verify product extension capabilities**

Run:
`.venv/bin/python - <<'PY'
import clipper2_batch
print(clipper2_batch.native_mesh_capabilities())
PY`

Expected: `{'triangulation_area_guard': True}`.

- [x] **Step 3: Re-run clean corpus without `.scratch` PYTHONPATH**

Run:
`.venv/bin/python scripts/profile_vector_native_mesh_corpus.py '/Volumes/personal_folder/新建文件夹' --repeats 1 --allow-failures --out-dir .scratch/vector_native_mesh_corpus/provided_svgs_clean_fast_product_native`

Expected: 17/0/0 and native speedup above 1.0x.

### Task 6: Final Verification

**Files:**
- Existing tests and touched files

- [x] **Step 1: Run focused native/vector tests**

Run:
`.venv/bin/python -m pytest tests/test_build_native_extensions_unit.py tests/test_vector_native_mesh_unit.py tests/test_vector_native_mesh_corpus_profile_unit.py tests/test_vector_engine_fixes_unit.py::TestFillRuleSubpathMerging -v`

Expected: PASS.

- [x] **Step 2: Run wider vector/native/GLB subset**

Run:
`.venv/bin/python -m pytest tests/test_vector_native_mesh_corpus_profile_unit.py tests/test_vector_native_mesh_unit.py tests/test_vector_engine_fixes_unit.py::TestFillRuleSubpathMerging tests/test_vector_engine_unit.py tests/test_vector_engine_stroke_unit.py tests/test_vector_glb_v2_kernel_unit.py tests/test_vector_glb_v2_parity_unit.py tests/test_glb_v2_kernel_unit.py -q`

Expected: PASS, with known external-asset skips allowed.

- [x] **Step 3: Run hygiene checks**

Run:
`.venv/bin/python -m py_compile scripts/build_native_extensions.py tests/test_build_native_extensions_unit.py core/vector_native_mesh.py`

Run:
`git diff --check -- native/clipper2_batch scripts/build_native_extensions.py tests/test_build_native_extensions_unit.py Dockerfile docs/superpowers/plans/2026-06-19-productize-clipper2-native-extension.md`

Run common mojibake-marker scan over touched tracked files and check for leftover Lumina processes.

Expected: all checks clean.

### Acceptance Gate

- Product native extension builds from repository files, not `.scratch`.
- Importing `clipper2_batch` from the repo root exposes `native_mesh_capabilities()`.
- Clean SVG corpus stays 17/0/0 without `.scratch` on `PYTHONPATH`.
- Docker and desktop build paths invoke the native extension build.
