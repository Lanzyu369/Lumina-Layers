# Material Hybrid Candidate Cache Design

## Goal

Replace Lumina's large material-archive solver-cache construction path with a bounded, target-aware cache strategy that avoids scanning every `M ** N` recipe for large palettes while preserving the existing preview, vector, replacement, region-requantize, download, and export contracts.

The new strategy is:

```text
small palette/layer count -> keep exact exhaustive cache
large palette/layer count -> bounded candidate coverage cache + target-aware inverse refinement
```

This document is a design and feasibility assessment only. It does not authorize implementation until the planned change is registered in the online tracking spreadsheet and the implementation plan is reviewed.

## Current Evidence

Lumina's current disk-backed material solver cache is explicitly exhaustive:

- `core/material_cache.py` says the cache is built by enumerating every `M**N` ordered layer sequence and bucketing the result into a 3-D Lab grid.
- `build_material_solver_cache()` still enumerates bottom and top half affine tables and combines them chunk by chunk to produce every final recipe color.
- `core/pipeline/p03_core_processing.py` currently falls back to building a temporary 64-grid cache when no persisted cache exists. Lowering the grid only reduces retained buckets; it does not remove the full `M**N` scan.

For a 22-material palette:

```text
22 ** 8  = 54,875,873,536 recipes
22 ** 10 = 26,559,922,791,424 recipes
```

No cache builder that scans that space is acceptable in an interactive server path.

## Non-Goals

- Do not change the Beer-Lambert physical formula in this phase.
- Do not change generated 3MF material identity, slot ordering, or layer image semantics.
- Do not rewrite the frontend material selection flow.
- Do not remove support for existing exact and bucketed cache files.
- Do not force the LUT-backed predictive runtime to use the material-archive cache.
- Do not make ChromaPrint3D's package format a direct dependency of Lumina's material archives.

## Physical Model

Lumina's material model already has the mathematical structure needed for smarter search.

One layer is:

```text
C_new = E + (C_prev - E) * exp(-k * t)
```

Equivalently:

```text
C_new = a_i * C_prev + b_i
a_i = exp(-k_i * t)
b_i = E_i * (1 - a_i)
```

Composing layers keeps the recipe affine:

```text
C_final = alpha_total * C0 + beta_total
```

For a split recipe:

```text
C_final = alpha_top * C_bottom + beta_top
```

Given a target linear RGB `T` and a top suffix, an approximate required bottom color is:

```text
C_bottom_required = (T - beta_top) / alpha_top
```

This is the key: large-palette lookup can search likely top suffixes and query a bottom-prefix index instead of pairing every top with every bottom.

## Recommended Architecture

### Summary

Introduce a new runtime beside `MaterialSolverCache`:

```text
MaterialCandidateRuntime
```

It provides the same lookup surface as `MaterialSolverCache.lookup()`:

```python
lookup(
    target_srgb: np.ndarray,
    user_materials: list[MaterialParams],
    *,
    hue_weight: float = 0.0,
    neighbor_coherence: float = 0.5,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]
```

Existing consumers should receive:

```text
matched_rgb: (C, 3) uint8
recipes_user_order: (C, N) int32
delta_e: (C,) float64
```

This duck-typed compatibility is the central containment boundary. The pipeline, vector matcher, region re-quantize helper, and replacement code should not need to know whether the runtime came from an exact cache, a bucketed cache, or the new hybrid candidate cache.

### Runtime Selection

Add a resolver instead of changing old functions in place:

```text
core.material_lut_provider.load_solver_runtime(...)
```

Resolution order:

1. Load existing exact or bucketed `MaterialSolverCache` when available.
2. Use exact exhaustive build only when the current exact thresholds allow it.
3. For large unsafe cases, build or load `MaterialCandidateRuntime`.
4. Return a deterministic 4xx/409-style error only if both cache loading and bounded candidate runtime construction fail.

Keep the existing `load_solver_cache(...)` pass-through unchanged for current tests and API routes until each caller is explicitly migrated.

## New Modules

### `core/material_candidate_cache.py`

Responsibility:

- Own the new runtime dataclass.
- Save and load candidate cache files.
- Build KD-tree indexes over `achieved_lab`.
- Implement `lookup()` and optional `lookup_top_k()`.
- Hold metadata and compatibility properties used by existing diagnostics.

Proposed public types:

```python
@dataclass(frozen=True)
class MaterialCandidateCacheConfig:
    candidate_budget: int
    candidate_pool_multiplier: int
    lab_grid_resolution: int
    seed: int
    max_build_seconds: float | None
    enable_inverse_refinement: bool
    max_refine_materials: int
    max_refine_top_suffixes: int
    max_refine_bottom_prefixes: int

@dataclass
class MaterialCandidateRuntime:
    candidate_recipes: np.ndarray
    achieved_srgb: np.ndarray
    achieved_lab: np.ndarray
    pinned_mask: np.ndarray
    metadata: dict[str, Any]

    def lookup(...): ...
```

Required compatibility properties:

```text
mode -> "candidate_hybrid"
layer_count
layer_height_mm
substrate
palette_hash
grid_resolution -> lab_grid_resolution
valid_cell_count -> candidate_recipes.shape[0]
metadata
```

### `core/material_candidate_sampling.py`

Responsibility:

- Generate bounded candidate recipes without scanning `M ** N`.
- Keep deterministic output for a fixed palette hash and config.
- Provide pure functions that are easy to unit test.

Candidate sources:

1. **Pinned uniform recipes**
   - `[m, m, ..., m]` for every material.
   - These guarantee each material's identity color remains reachable.

2. **Two-material ramps**
   - For every ordered or unordered pair `(a, b)`, generate layer-count proportions:
     - all `a`
     - all `b`
     - one top `b`
     - two top `b`
     - half bottom `a` / half top `b`
     - alternating `a/b`
   - Cap pair ramps with deterministic ranking when `M` is very large.

3. **Base-material anchored recipes**
   - Force white/base material in bottom layers with colored top layers.
   - Force black/dark material in lower layers only when the material is actually present.
   - Base material is inferred through the existing material archive base-channel logic, not by assuming index `0`.

4. **Top-heavy visibility recipes**
   - Generate recipes where the top 1-3 viewing layers vary more aggressively than buried layers.
   - This matches the physics: top suffix transmittance often dominates visible color.

5. **Low-discrepancy random coverage**
   - Use deterministic Sobol or seeded quasi-random integer mapping when available.
   - Fall back to `np.random.default_rng(seed)` if the low-discrepancy generator is unavailable.
   - Recipes are generated in batches and deduplicated by packed recipe bytes.

6. **Historical and measured seeds**
   - Existing cache rows, if loaded.
   - User saved recipes, if available through the same material archive session.
   - Future measured calibration recipes, once a canonical source exists.

### `core/material_candidate_selection.py`

Responsibility:

- Convert generated recipes to predicted Lab.
- Keep a bounded candidate pool with broad coverage.
- Select final candidate rows.

The selector must be streaming:

```text
generate batch -> forward predict -> Lab -> update per-cell reservoir -> discard batch
```

It must not hold the full generated pool in memory.

Selection rules:

- All pinned recipes are always retained.
- Each Lab grid cell keeps a small bounded reservoir, for example 1-4 candidates.
- If the reservoir exceeds the final budget, run approximate k-center selection over cell representatives.
- Final output is capped by `candidate_budget`.

Default budgets:

```text
fast       65,536 candidates
balanced 262,144 candidates
quality  524,288 candidates
```

The default preview fallback should use `balanced` only if build time is acceptable on the deployment host; otherwise start with `fast` and enable target refinement.

### `core/material_inverse_refinement.py`

Responsibility:

- Improve matches for the actual image target colors.
- Use the affine inverse relationship instead of full Cartesian pairing.
- Return only recipes that pass final forward-model verification.

Algorithm per batch of target colors:

1. Query `MaterialCandidateRuntime` KD-tree for the top `K=64` baseline candidates.
2. Derive a target-specific material subset:
   - materials appearing in top candidates
   - nearest material identity colors
   - inferred base/white material
   - optional black/dark material
3. Cap this subset:
   - default `max_refine_materials = 8`
   - hard maximum `12`
4. Enumerate bottom prefixes and top suffixes for this subset, subject to caps:
   - `max_refine_bottom_prefixes = 65,536`
   - `max_refine_top_suffixes = 32,768`
5. Build a KD-tree for bottom prefix colors.
6. For each target and top suffix:
   - compute `C_bottom_required`
   - reject values far outside `[0, 1]`
   - query nearest bottom prefixes
   - compose final recipe
7. Forward-predict every composed candidate with the existing `forward_model`/affine batch path.
8. Pick best Lab ΔE, then apply existing hue-aware and neighbor-coherence reranking rules.

This search is target-aware. It spends work only around colors that appear in the current image, not around the entire theoretical recipe universe.

## Cache File Format

Do not reuse the existing `-gNNN.npz` name for hybrid caches. Use a distinct stem:

```text
<palette_hash>-N<count>-t<height>-<substrate>-hybrid-v2-b<budget>.npz
<palette_hash>-N<count>-t<height>-<substrate>-hybrid-v2-b<budget>.meta.json
```

Required `.npz` arrays:

```text
candidate_recipes   uint8/int16, shape (B, N)
achieved_srgb       uint8,       shape (B, 3)
achieved_lab        float32,     shape (B, 3)
pinned_mask         bool,        shape (B,)
```

Use `uint8` recipes while material count is <= 255. Use `uint16` only if a future workflow allows more than 255 materials. Store the recipe dtype in metadata.

Required metadata:

```json
{
  "schema_version": "2.0",
  "mode": "candidate_hybrid",
  "palette_hash": "...",
  "canonical_materials": [],
  "layer_count": 10,
  "layer_height_mm": 0.08,
  "substrate": "white",
  "candidate_budget": 262144,
  "candidate_count": 262144,
  "candidate_pool_multiplier": 8,
  "lab_grid_resolution": 96,
  "seed": 123456,
  "generator_version": "material_candidate_sampling_v1",
  "selection_version": "lab_reservoir_kcenter_v1",
  "inverse_refinement": {
    "enabled": true,
    "max_refine_materials": 8,
    "max_refine_top_suffixes": 32768,
    "max_refine_bottom_prefixes": 65536
  },
  "total_combinations": 26559922791424,
  "scanned_combinations": 0,
  "generated_candidate_count": 2097152,
  "pinned_candidate_count": 500,
  "build_time_seconds": 0.0,
  "built_at": "..."
}
```

`scanned_combinations` must be `0` for hybrid caches because they intentionally do not scan the theoretical universe.

## Existing Caller Impact

### `core/pipeline/p03_core_processing.py`

Current behavior:

- Loads persisted cache.
- If absent, builds temporary `build_material_solver_cache(... grid=64)`.

Required change:

- Replace only the absent-cache fallback with `load_solver_runtime(...)`.
- Keep existing metadata keys in `solver_meta`.
- Add optional keys:
  - `runtime_mode`
  - `candidate_budget`
  - `inverse_refinement_enabled`
  - `generated_candidate_count`

No change to:

- `matched_rgb_unique`
- `recipes_unique`
- `delta_e`
- `map_pixels_to_materials(...)`
- cache dictionary keys consumed by downstream pipeline stages.

### `core/vector_matchers.py`

Current behavior:

- Mirrors P03 cache fallback and expects `.lookup()`.

Required change:

- Resolve a runtime through the same provider as P03.
- Keep `self._solver_cache` name or rename to `self._solver_runtime` only if tests are updated together.
- Preserve `solve_for_fills()` output shapes and layer order.

No change to:

- vector fill quantization
- KD-tree over solved fill colors
- downstream vector branch metadata.

### `core/gradient_region_requantize.py`

Current behavior:

- Only calls `material_solver_cache.lookup()`.

Required change:

- Type annotation can become a protocol, but behavior can remain unchanged.
- No algorithm-specific fields should be accessed.

No change to:

- local region K-Means
- region mask handling
- rewritten pixel counting.

### `core/pipeline/s03_color_replacement.py`

Current behavior:

- Uses `load_solver_cache(...)`, then `.lookup(...)` when a cache exists.

Recommended phase:

- Do not migrate this in the first integration phase.
- Once `load_solver_runtime(...)` is stable, switch only the lookup path.
- Keep the current MITM fallback for single-color replacement until hybrid `lookup_top_k` is implemented.

### `api/routers/converter/replace.py`

Current behavior:

- Region re-quantize endpoint requires a persisted `MaterialSolverCache`.

Recommended phase:

- Do not change this endpoint in the first integration phase unless a persisted hybrid runtime loader is already implemented.
- Later, allow either exact/bucketed cache or hybrid candidate runtime.
- Preserve the current 409 behavior when no reusable runtime exists.

### `api/routers/single_stage.py`

Current behavior:

- `/material-solver-cache/build` builds the existing exact/bucketed cache.
- `/status`, `/details`, `/suggest-colors`, `/delete` assume the existing cache shape.

Recommended phase:

- Keep these endpoints stable at first.
- Add a separate hybrid build/status endpoint only after the core runtime is proven:
  - `/material-solver-runtime/status`
  - `/material-solver-runtime/build`
- Do not overload `grid_resolution` to mean candidate budget.
- Add new response fields without changing required fields in existing responses.

### `core/material_cache_visualization.py`

Current behavior:

- Visualizes Lab-grid cache details.

Recommended phase:

- Leave it exact/bucketed-only.
- Add hybrid visualization in Phase 5 with explicit labels: candidate coverage, not exhaustive grid coverage.

## Compatibility Rules

1. Existing exact and bucketed cache files must continue to load.
2. Existing `build_material_solver_cache()` semantics remain unchanged unless a caller explicitly requests hybrid through a new function.
3. Existing API endpoint request schemas remain backward compatible.
4. Material recipe layer order returned by hybrid lookup must match `MaterialSolverCache.lookup()`.
5. Palette fingerprinting remains canonical and order-independent.
6. Hybrid cache keys include algorithm version and budget so incompatible runtime files are not silently reused.
7. Hybrid fallback must never call `_enumerate_cumulative_affines()` at a depth that implies full `M ** N` scanning for unsafe palettes.
8. If hybrid lookup fails, the user receives a deterministic actionable error; raw tracebacks are not surfaced.
9. No frontend state migration is needed for the first backend-only phase.
10. Export and 3MF generation continue to consume the same `material_matrix` shape as before.

## Accuracy Strategy

The hybrid runtime is approximate for large palettes. Accuracy is controlled by:

- candidate budget
- pinned recipe coverage
- Lab-space k-center coverage
- target-aware inverse refinement
- final exact forward-model verification

Quality gates:

1. On small palettes where exhaustive brute force is feasible, exact mode remains the source of truth.
2. On small palettes with forced hybrid mode, hybrid must never return a recipe whose forward-predicted RGB disagrees with its own recipe.
3. On sampled test palettes, hybrid with refinement must be no worse than the same hybrid candidate cache without refinement for mean ΔE.
4. On representative images, hybrid preview should meet agreed thresholds before it becomes default for large palettes:
   - mean ΔE against small-subset exact baseline: <= 3.0 when the baseline is computable
   - p95 ΔE regression versus current exact/bucketed cache on safe palettes: <= 1.0 when forced hybrid is tested
   - max ΔE should be reported, not hidden, because out-of-gamut colors can legitimately remain high.

## Performance Strategy

### Build memory

For `candidate_budget = 262,144` and `N = 10`:

```text
candidate_recipes uint8  ~= 2.5 MB
achieved_srgb uint8      ~= 0.8 MB
achieved_lab float32     ~= 3.0 MB
pinned_mask bool         ~= 0.3 MB
KD-tree/runtime overhead ~= implementation-dependent, expected tens of MB
```

The streaming build may evaluate more than the final budget, for example `budget * 8`, but it must evaluate in bounded batches. A batch of 65,536 recipes stores only current recipe ids, linear RGB, sRGB, Lab, and selection bookkeeping before being discarded.

### Lookup memory

Baseline lookup:

```text
target_count * top_k * 3 float32/float64
```

For 256 unique colors and top-K 64, this is small.

Inverse refinement:

- Group targets by material subset.
- Reuse prefix/suffix tables per subset.
- Cap table sizes independently from theoretical `S ** half_depth`.
- Keep chunked final forward scoring.

Safe defaults:

```text
max_refine_materials = 8
max_refine_bottom_prefixes = 65,536
max_refine_top_suffixes = 32,768
refine_bottom_neighbors = 2
```

These defaults avoid full `12 ** 10`-style pairing while leaving room for quality improvement.

## Error Handling

New domain errors should live in core and be mapped at API boundaries:

```text
MaterialCandidateCacheError
MaterialCandidateCacheBuildBudgetError
MaterialCandidateRuntimeUnavailableError
MaterialInverseRefinementBudgetError
```

User-facing messages should state:

- material count
- layer count
- selected strategy
- candidate budget
- reason for rejection or fallback
- recommended action

No `HTTPException` should be raised from `core/*`.

## Structured Logging

Add only focused events and keep INFO budget small:

```text
material_candidate_cache_build_started   DEBUG or INFO only for explicit build endpoint
material_candidate_cache_build_done      INFO
material_candidate_cache_build_failed    WARNING/ERROR
material_candidate_runtime_used          INFO in preview path only when it materially affects matching
material_inverse_refinement_done         DEBUG by default
```

If a new mutating API endpoint is added, register its success event in logging governance tests and do not extend the default canonical workflow unless explicitly approved.

## Testing Plan

### Unit tests

Create `tests/test_material_candidate_cache_unit.py`:

- deterministic candidate generation for fixed seed
- different palette hash changes seed/key
- pinned uniform recipes are always present
- candidate count never exceeds budget
- unsafe 22-material palette does not call exhaustive builder
- runtime `.lookup()` returns the same shapes and dtypes as `MaterialSolverCache.lookup()`
- lookup validates palette fingerprint
- save/load roundtrip preserves arrays and metadata
- corrupt hybrid cache returns `None` or a domain error without crashing

Create `tests/test_material_inverse_refinement_unit.py`:

- affine inverse computes a finite required bottom color for valid top suffixes
- invalid required colors outside tolerance are rejected
- refinement candidate is forward-verified before being accepted
- refinement never worsens baseline candidate for the same target
- prefix/suffix caps are respected

Extend `tests/test_material_cache_unit.py` only for shared helpers, not to mix hybrid-specific behavior into legacy cache tests.

### Pipeline tests

Update material-archive P03 tests:

- no persisted cache + unsafe palette uses hybrid runtime, not `build_material_solver_cache`
- safe small palette still uses exact/bucketed path
- output cache keeps `matched_rgb`, `material_matrix`, `color_layers`, `layer_height_mm`
- layer order matches existing material matrix expectations

Update vector matcher tests:

- vector material matcher accepts a duck-typed hybrid runtime
- solved fill cache behavior remains stable

Update region re-quantize tests only when that endpoint is migrated.

### API tests

For first backend-only phase:

- existing `/material-solver-cache/*` tests must continue to pass unchanged.

For the Phase 5 hybrid endpoint work:

- status reports candidate runtime separately from legacy cache
- build rejects invalid candidate budgets
- build returns deterministic metadata
- delete removes only hybrid runtime files for the requested budget

### Regression gates

Required before merging implementation:

```bash
python -m pytest tests/test_material_cache_unit.py tests/test_material_solver_optimal_unit.py -v
python -m pytest tests/test_material_candidate_cache_unit.py tests/test_material_inverse_refinement_unit.py -v
python -m pytest tests/test_p03_material_archive_layer_order_unit.py tests/test_p03_material_archive_not_worse_fallback_unit.py -v
python -m pytest tests/test_vector_material_matcher_unit.py tests/test_gradient_region_requantize_unit.py -v
python -m pytest tests/test_converter_recipe_override_unit.py tests/test_converter_replace_layer_sync_unit.py -v
python scripts/log_quality_check.py --mode fast
```

If API logging changes are included:

```bash
python -m pytest tests/test_logging_exception_governance_unit.py tests/test_structured_logging_unit.py tests/test_logger_unit.py -v
```

Frontend tests are not required for the first backend-only phase unless UI controls or translations change. If UI exposes candidate budget or strategy, add:

```bash
python scripts/run_vitest.py run
```

## Feasibility Assessment

### Overall verdict

Feasible, with medium algorithmic risk and low product-surface risk if implemented in phases behind a runtime compatibility boundary.

### Why feasible

- The physical model is already affine per layer.
- Lumina already has canonical palette fingerprinting and order rebinding.
- Existing consumers mostly require `.lookup()` output, not a specific cache implementation.
- ChromaPrint3D proves a bounded candidate package is viable for runtime matching.
- Current tests already cover exact/bucketed cache contracts and can become regression guards.

### Main risks

1. **Quality risk**
   - A bounded candidate cache can miss colors that exhaustive search would find.
   - Mitigation: pinned recipes, Lab coverage selection, target-aware inverse refinement, quality gates against exact baselines.

2. **Layer-order risk**
   - Material matrix and solver recipes have strict ordering assumptions.
   - Mitigation: reuse `MaterialSolverCache.lookup()` contract exactly and add layer-order regression tests.

3. **Subtle caller assumptions**
   - Some code reads `.valid_cell_count`, `.metadata`, `.mode`, or `.grid_resolution`.
   - Mitigation: hybrid runtime exposes compatibility properties and metadata fields.

4. **Visualization semantics**
   - Existing details views assume Lab-grid exhaustive/bucketed cells.
   - Mitigation: do not route hybrid caches into existing visualization until a distinct candidate-coverage visualization exists.

5. **API expectation risk**
   - Current `/material-solver-cache/build` means exhaustive/bucketed cache.
   - Mitigation: keep the endpoint unchanged and add separate runtime endpoints in Phase 5.

6. **Performance tuning risk**
   - Candidate budget and inverse refinement caps need empirical tuning.
   - Mitigation: start with conservative defaults, structured metrics, and feature-flagged rollout.

### What cannot be guaranteed by design alone

It is not possible to honestly guarantee "no impact anywhere" without implementation and regression runs. The enforceable guarantee should be:

- no public contract changes without tests
- no existing endpoint schema removals
- no change to exact/bucketed cache behavior unless explicitly requested
- no 3MF/export layer-order change
- all listed regression gates pass before merge

## Rollout Plan

### Phase 1: Core runtime, no production integration

Create hybrid candidate modules and tests. Do not call them from P03, vector, API, or frontend yet.

Exit criteria:

- unit tests pass
- forced hybrid mode works on small palettes
- unsafe large palette build stays within candidate budget

### Phase 2: Provider integration behind opt-in flag

Add `load_solver_runtime(...)` and allow opt-in through an internal parameter or environment flag.

Exit criteria:

- old `load_solver_cache(...)` tests pass unchanged
- P03 can be tested with a mocked hybrid runtime without changing default behavior

### Phase 3: Preview and vector fallback

Replace only the no-persisted-cache fallback in P03 and vector matcher for unsafe palettes.

Exit criteria:

- safe small palettes still use exact/bucketed cache
- unsafe palettes do not call exhaustive builder
- preview returns deterministic output and metadata

### Phase 4: Persisted hybrid runtime

Save/load hybrid cache files and use them across preview sessions.

Exit criteria:

- roundtrip tests pass
- cache deletion and feedback bundle exclusion handle hybrid files
- no collision with legacy cache filenames

### Phase 5: API/UI exposure

Expose candidate budget and strategy only after backend behavior is stable.

Exit criteria:

- translations updated
- API schemas updated
- frontend settings persistence updated
- log governance updated if new endpoint events are added

## Rollback Strategy

Rollback must be simple:

- Keep old exact/bucketed builder untouched.
- Keep `load_solver_cache(...)` untouched.
- Gate production use through `load_solver_runtime(...)`.
- If hybrid has a quality or stability issue, disable hybrid selection and fall back to current cache behavior plus the existing safety rejection.
- Hybrid files have distinct filenames, so disabling the feature does not affect legacy cache files.

## Acceptance Criteria

Implementation is acceptable only when all are true:

1. A 22-material x 8-layer preview no longer attempts full `22 ** 8` scanning.
2. Exact cache behavior for small palettes is unchanged.
3. Existing persisted exact/bucketed caches remain loadable.
4. Material matrix shape and layer order are unchanged.
5. 3MF export, layer images, recipe override, region replacement, and vector material archive tests pass.
6. Hybrid runtime reports its approximate nature in metadata.
7. Hybrid lookup is deterministic for a fixed palette/config.
8. Hybrid candidate count is bounded by config.
9. The implementation has a clear feature flag or resolver switch for rollback.
10. The online tracking spreadsheet contains the planned change before code implementation begins.
