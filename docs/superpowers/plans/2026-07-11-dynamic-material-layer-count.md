# Dynamic Material Layer Count Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add exact CIEDE2000-based dynamic effective layer selection to material mode while preserving fixed-layer behavior.

**Architecture:** Build one bounded candidate catalog across the configured effective layer range, pad every short recipe with the selected backing material on the non-viewing side, and score the resulting printed colors exactly. Losslessly deduplicate identical scored RGB colors in favor of the shortest recipe, then run a full float64 CIEDE2000 scan with a Numba kernel and an exact NumPy fallback. Persist actual recipes separately from fixed-width print recipes and thread the metadata through preview, generation, editing, import/export, and the UI.

**Tech Stack:** Python, NumPy, Numba, FastAPI/Pydantic, React 19, TypeScript, Zustand, Vitest.

## Global Constraints

- The feature is available only for material mode; all other modes reject an enabled dynamic flag.
- Fixed mode continues to use `material_layer_count` and must preserve current behavior.
- Effective layer bounds are integers from 5 through 10 and `min <= max`.
- The CIEDE2000 tolerance defaults to `0.5`, accepts `0.0` through `5.0`, and the UI uses a `0.1` step.
- Dynamic matching uses standard CIEDE2000 only; it must not use CIE76 Top-K, KDTree approximation, hue weighting, custom lightness weighting, Lab-BVH, or unproven pruning.
- Exactness means exhaustive CIEDE2000 evaluation within the generated bounded candidate universe, not exhaustive enumeration of all `material_count ** layer_count` recipes.
- Missing physical layers are padded with the selected backing material on the substrate-adjacent side; the viewing surface and total printed thickness stay flat at the configured maximum.
- Identical scored RGB colors keep the shortest effective recipe; ties at the same length use stable candidate order.
- Dynamic-off requests, persisted recipes, and generated models remain backward compatible.

---

### Task 1: Exact dynamic material solver

**Files:**
- Create: `core/material_dynamic_solver.py`
- Create: `tests/test_material_dynamic_solver_unit.py`
- Reuse: `core/material_candidate_cache.py`, `core/material_color_solver.py`, `core/colorchecker/color_metrics.py`

**Interfaces:**
- Produce `DynamicMaterialSolveConfig`, `DynamicMaterialColorMatch`, `MaterialLayerBenefitPoint`, and `solve_dynamic_material_colors(...)`.
- `solve_dynamic_material_colors` consumes target RGB values, material parameters, backing-material index, layer height, substrate, min/max layers, tolerance, and candidate-runtime loader.
- It returns selected actual recipes, padded print recipes, per-color exact Delta-E00 metadata, fixed-max baselines, and the unweighted per-layer-cap results used by the pipeline to compute pixel-weighted benefits.

- [ ] Add failing tests for standard CIEDE2000 sample pairs, exact NumPy/Numba parity, stable ties, same-RGB shorter-layer deduplication, backing-prefix orientation, tolerance zero, tolerance boundary, and fixed-max reachability.
- [ ] Run the targeted test file and confirm each new behavior fails because the dynamic solver does not exist.
- [ ] Implement bounded per-layer candidate extraction, complete printed-stack simulation, packed-RGB lossless deduplication, and deterministic recipe retention.
- [ ] Implement a float64 `njit(parallel=True, fastmath=False, cache=True)` CIEDE2000 full-scan kernel that maintains per-layer-cap minima without allocating a target-by-candidate distance matrix.
- [ ] Implement an exact chunked NumPy fallback and expose typed domain failures when both engines fail.
- [ ] Add a regression fixture where CIE76 Top-4096 misses the Delta-E00 optimum; assert the exact solver returns the exhaustive optimum and does not call a Top-K helper.
- [ ] Run the targeted tests and existing material candidate/cache tests; keep all green.

### Task 2: Pipeline integration and recipe metadata

**Files:**
- Modify: `core/pipeline/p03_core_processing.py`
- Modify: pipeline cache/output stages that persist `material_matrix` and solver metadata
- Create: `tests/test_p03_material_archive_dynamic_layers_unit.py`

**Interfaces:**
- Dynamic-off continues through the current fixed solver branch.
- Dynamic-on writes a max-width Top-to-Bottom `material_matrix` plus a per-target catalog containing actual count/order, print order, padding count, Delta-E00 fields, and layer-cap values.

- [ ] Add failing pipeline tests for dynamic dispatch, mixed actual layer counts, flat max-width print matrices, backing material only at the non-viewing tail, and unchanged fixed-mode output.
- [ ] Thread dynamic configuration into the material-archive branch without altering non-material branches.
- [ ] Convert the solver's Bottom-to-Top recipes to pipeline Top-to-Bottom order exactly once and retain actual and print recipes separately.
- [ ] Preserve dynamic solver metadata through subsequent pipeline cache stages and compute pixel-weighted benefit points from quantized-color counts.
- [ ] Ensure cancellation or failure does not write partial dynamic state.
- [ ] Run the new pipeline tests plus existing material archive layer-order, pixel-mode, and fixed fallback tests.

### Task 3: API, validation, editing, and lifecycle

**Files:**
- Modify converter schemas, preview/generate workers and routers, preview response assembly, and material replacement/recipe endpoints
- Create focused API regression tests under `tests/`

**Interfaces:**
- Add request fields `material_dynamic_layer_count_enabled`, `material_min_layer_count`, `material_max_layer_count`, and `material_delta_e00_tolerance` with approved defaults and bounds.
- Add optional preview response fields for dynamic recipes and `material_layer_benefit_curve` so old clients remain compatible.

- [ ] Add failing schema/API tests for valid material requests, invalid bounds, min greater than max, non-material use, non-zero hue weight in dynamic mode, and explicit 409/503 error translation.
- [ ] Thread the four fields through preview, generation, batch and supported derivative material workflows, worker boundaries, cache keys, and reproduction metadata.
- [ ] Preserve typed dynamic failures instead of replacing them with the generic preview-generation error.
- [ ] Update automatic replacement to re-run the dynamic solver; update manual editing to validate actual length and pad with the selected backing material.
- [ ] Make region recipe reads use stored actual counts rather than infer them from backing-material tails.
- [ ] Cache the versioned dynamic catalog by palette fingerprint, backing material, height, substrate, range, candidate budget, and algorithm version using atomic replacement and corrupt-cache rebuild.
- [ ] Run focused API, worker, replacement, session cleanup, and material archive tests.

### Task 4: Frontend controls, persistence, and presentation

**Files:**
- Modify material basic settings, global Settings panel/store, converter store/API types, translations, and palette presentation
- Modify recipe/share-card import and export adapters
- Add/update Vitest tests under `frontend/src/__tests__/`

**Interfaces:**
- Material controls expose the dynamic toggle and coupled 5-10 min/max controls.
- Global Settings exposes `materialDeltaE00Tolerance` with default `0.5`, range `0-5`, and step `0.1`.
- Dynamic palette entries display actual layers, layers saved, selected/fixed/best Delta-E00, and sacrifice; the global panel displays weighted benefit points and marginal improvement.

- [ ] Add failing tests for control visibility, min/max coupling, tolerance clamping/persistence, hue-protection disabling, request serialization, response parsing, and old persisted-state compatibility.
- [ ] Implement the controls using existing theme/design components and translation keys; invalidate stale preview/generated artifacts when settings change.
- [ ] Send `hue_weight=0` when dynamic material mode is active and prevent contradictory UI state.
- [ ] Render per-color dynamic metadata and the compact layer-benefit curve without altering non-material palette presentation.
- [ ] Extend recipe/share-card schemas and round-trip adapters with optional dynamic fields, actual recipe order, print recipe order, and benefit metadata.
- [ ] Run all touched Vitest files through `python scripts/run_vitest.py run ...`.

### Task 5: End-to-end verification and performance evidence

**Files:**
- Add focused integration fixtures/tests and a reproducible benchmark script if the repository has no suitable existing profiling entry point
- Update user-facing announcement only if release policy requires it after reading `docs/announcement-maintenance.md`

- [ ] Add an integration image containing light, middle, and dark colors; assert at least two actual layer counts are selected and every print recipe has max width with backing padding on the non-viewing side.
- [ ] Verify per-color `selected_de00 <= best_de00 + tolerance` and pixel-weighted `dynamic_de00 <= fixed_max_de00 + tolerance`.
- [ ] Verify preview, generate, replacement, export, import, later editing, session switch/close, and final download behavior.
- [ ] Record cold/warm 48-, 256-, and 8192-target runs, peak memory, cancellation latency, catalog-cache behavior, and NumPy/Numba result identity; do not add a flaky wall-clock CI assertion.
- [ ] Run targeted backend suites, `python scripts/run_vitest.py run`, `python scripts/run_smoke_tests.py`, and `git diff --check`.
- [ ] Inspect process command lines and stop all Lumina backend/frontend/test helpers started during verification.
- [ ] Request a whole-branch review against the branch merge base and resolve every actionable finding before completion.
