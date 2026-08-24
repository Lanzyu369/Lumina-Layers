# Vector 3MF OOM Bounded-Memory Repair Plan

> **For agentic workers:** Follow systematic debugging and TDD. Preserve the
> PR #562 coverage and independent-shell contracts; do not replay user data in
> production and do not merge this PR automatically.

**Goal:** Prevent complex Vector preview/generate requests from exhausting a
worker or host while preserving complete slicer toolpath coverage and closed,
independently indexed shells.

**Architecture:** Keep geometry policy in `core/`. Decide whether the optimized
union is coverage-complete in 2D before allocating its 3D mesh, use a bounded
streaming fallback when source-shell extrusion is required, and make both
precision and extrusion caches byte-budgeted and stage-scoped. Measure cap area
in face chunks. Reject inputs whose conservative estimate cannot fit the worker
budget before large allocations, using a structured core validation error that
the generate API maps to an actionable 422. Add one aggregate diagnostic profile
for stage RSS, complexity, cache peaks, and fallback decisions.

**Evidence constraints:** The August 24 incident SVG no longer exists. Use a
deterministic synthetic high-component fixture and the related historical 55 MB
R4C1 SVG only as regression evidence; never label either as the incident file.

---

### Task 1: Lock the memory-lifetime failures with RED tests

**Files:**
- Modify: `tests/test_vector_engine_mesh_weld_unit.py`
- Modify: `tests/test_vector_engine_unit.py`
- Create: `tests/test_vector_mesh_memory_unit.py`

- [x] Prove a lossy 2D union chooses source extrusion without first retaining a
      merged 3D result.
- [x] Prove a post-extrusion coverage failure releases the primary mesh before
      constructing fallback chunks and still rejects incomplete fallback.
- [x] Prove cap-area measurement never gathers the complete face array into one
      `(faces, 3, 3)` temporary.
- [x] Prove precision and extrusion caches evict by byte budget and report peak
      bytes; verify cached output remains geometrically identical.
- [x] Prove an over-budget complexity estimate raises the public memory-budget
      domain error before extrusion or union is called.

### Task 2: Add bounded memory policy and diagnostics

**Files:**
- Create: `core/vector_mesh_memory.py`
- Modify: `core/errors.py`
- Modify: `core/vector_engine.py`

- [x] Add a deterministic complexity/RSS profile and configurable soft budget,
      with production-safe defaults and test-only explicit overrides.
- [x] Add a small LRU byte-budget cache used by both precision geometry and base
      extrusion arrays. Count actual NumPy bytes and conservative Shapely bytes.
- [x] Add one bilingual public `VectorMeshMemoryBudgetError` carrying a stable
      code, stage, estimate, budget, and recovery suggestions.
- [x] Expose one aggregate structured diagnostic record (DEBUG by default,
      opt-in INFO) without expanding normal request INFO budgets.

### Task 3: Move coverage decisions before 3D and stream fallback

**Files:**
- Modify: `core/vector_engine.py`
- Modify: `tests/test_vector_engine_mesh_weld_unit.py`

- [x] Compare the source visibility-clipped area against the normalized/unioned
      2D geometry before extrusion. If incomplete, skip merged extrusion.
- [x] If only the 3D guard detects loss, discard the complete primary result
      before fallback and verify release through the RED lifetime sentinel.
- [x] Extrude source polygons into bounded chunks, carry incremental coverage
      metadata, and never keep an unbounded list of per-source mesh objects plus
      the primary mesh at once.
- [x] Preserve every source shell's independent indices and reject any fallback
      whose summed coverage is incomplete.

### Task 4: Bound caches, cap-area temporaries, and stage lifetime

**Files:**
- Modify: `core/vector_engine.py`
- Test: `tests/test_vector_engine_unit.py`
- Test: `tests/test_vector_mesh_memory_unit.py`

- [x] Replace function-wide `precision_cache` with the byte-budget LRU.
- [x] Replace build-wide plain `extrude_cache` with the byte-budget LRU, clear it
      between bottom/backing/coating/top phases when reuse is no longer possible,
      and release it before final scene assembly.
- [x] Rewrite `_cap_planar_area_mm2` to gather and reduce bounded face chunks.
- [x] Record cache peak/resident bytes and stage RSS in `last_stage_timings`.

### Task 5: Add early recoverable rejection and API contract

**Files:**
- Modify: `core/pipeline/vector_branch.py`
- Modify: `api/routers/converter/generate.py`
- Modify: `api/errors.py` only if the typed core mapping needs extension
- Modify: relevant backend/frontend error tests and UI recovery copy

- [x] Run complexity admission before union/extrusion allocations.
- [x] Preserve the typed error through the staged pipeline and worker boundary.
- [x] Return actionable HTTP 422 with stable code rather than generic 500;
      recommend reducing model width/vector detail or simplifying the SVG.
- [x] Prove the same worker/health path accepts a normal request after rejection.

### Task 6: Restricted canary and correctness verification

**Files:**
- Create or modify only bounded test/profile tooling required for reproducibility.

- [x] Run the synthetic complex fixture in a child process with an explicit RSS
      watchdog/cgroup-style limit; capture before/after peak RSS and stage times.
- [x] Require complex accepted fixture peak RSS below 8 GiB. If a larger fixture
      is rejected, prove rejection occurs below 12 GiB without swap exhaustion,
      BrokenProcessPool, or failed follow-up health/normal task.
- [x] Run the related 55 MB R4C1 SVG and other existing vector fixtures; verify
      coverage, topology, material identity, single/double-sided, outline,
      material archive, preview/generate parity, and output size.
- [x] Slice representative outputs with Bambu Studio and OrcaSlicer with the
      prime tower disabled only in verification copies; require model toolpaths.
- [x] Run focused tests, smoke, full, logging fast, compile, UTF-8, and
      `git diff --check`.

### Task 7: Independent review and separate PR

- [x] Obtain independent code/memory-lifetime review and address only reproduced
      blockers.
- [x] Verify no generated/user fixtures are tracked and no long-running process
      remains.
- [x] Commit with a bilingual Conventional Commit body, push the topic branch
      normally, and open a PR to `dev-refactor` with exact RSS/timing/output/
      slicer/test evidence and remaining limits. Do not merge.
