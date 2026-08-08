# Material Color Consistency Design

**Date:** 2026-08-08
**Status:** Approved for implementation
**Scope:** LUM-20260805-001 color-calculation mismatch report only

## Goal

Make every user-facing material-archive tool report the same sRGB color for
the same material stack, layer order, layer height, and substrate. The
converter preview/generation result is the authority because it is the color
that drives the printable recipe and generated model.

## Confirmed Current Behavior

The bug report combines several views of one material recipe:

- converter preview and generation;
- gradient-banding flattening;
- the 20 achievable-color suggestions;
- custom-recipe prediction and application;
- Material Library recipe prediction.

Three independent contract differences explain the visible mismatch:

1. Converter preview and solver paths use `linear_to_srgb_uint8`, which rounds
   the converted sRGB channels. The custom-recipe prediction, application,
   and padded-pixel recalculation paths instead cast directly to `uint8`,
   truncating fractional channels.
2. Dynamic material mode may print up to `materialMaxLayerCount`, but the
   achievable-color picker keys and requests its solver using the fixed
   `materialLayerCount`. In the reported 5-8-layer workflow it searches only
   five-layer recipes, so an eight-layer color cannot appear.
3. Material Library recipe prediction starts its forward model from the first
   loaded material's measured `C0_white`. Converter solvers use a common pure
   white or pure black substrate. The result therefore changes according to
   which material happens to be adjacent to the substrate.

The repository's real `赛纳/赛纳PETG白色 by MingDee` archive provides a stable
acceptance case for an eight-layer all-white stack at 0.08 mm:

| Surface | Current result |
| --- | --- |
| Converter/canonical rounded result | `#FFFFF9` |
| Custom-recipe prediction | `#FEFEF9` |
| Material Library recipe prediction | `#FFFFF8` |
| Achievable-color picker in dynamic 5-8 mode | Searches five layers and cannot return the exact eight-layer recipe |

## Canonical Contract

The shared contract is:

1. Core recipe order is substrate-to-visible-face (`Bottom2Top`), matching
   `forward_model`. UI/API boundaries remain responsible for reversing
   `Top2Bottom` recipes exactly once.
2. A white substrate is linear RGB `[1.0, 1.0, 1.0]`; a black substrate is
   `[0.0, 0.0, 0.0]`.
3. The Beer-Lambert stack is evaluated by the existing `forward_model`.
4. Linear RGB is converted with the existing `linear_to_srgb_uint8`, including
   clipping and round-to-nearest behavior.
5. Dynamic material suggestions use the effective print layer count. For
   dynamic mode this is `materialMaxLayerCount`; otherwise it is
   `materialLayerCount`.

`C0_white` remains part of material fitting, validation, diagnostics, and
palette fingerprinting. This change only stops treating one material's
capture-specific zero-thickness observation as the shared physical substrate
for user-facing recipe prediction.

## Architecture

### Core prediction boundary

Add a focused public helper to `core/material_color_solver.py`:

```python
def predict_material_recipe_srgb(
    recipe: np.ndarray,
    materials: list[MaterialParams],
    layer_height_mm: float,
    substrate: str = "white",
) -> np.ndarray:
    ...
```

The helper accepts the core `Bottom2Top` order, resolves the canonical
substrate, calls `forward_model`, and returns one `(3,) uint8` sRGB value via
`linear_to_srgb_uint8`. It raises `ValueError` for unsupported substrates and
retains the existing validation behavior of `forward_model` for invalid
material indices. Its public docstring and type hints will be bilingual as
required by the repository.

This helper has multiple immediate adoption sites, so it is not an unused
infrastructure abstraction.

### Converter prediction and application

In `api/routers/converter/replace.py`, replace the duplicated
`linear_to_srgb_float(...).astype(np.uint8)` sequences with the core helper in:

- `/api/convert/predict-recipe` material-archive prediction;
- `/api/convert/apply-recipe-override` material-archive application;
- `_recalc_matched_rgb_for_padded_pixels` after a recipe grows in depth.

Each caller honors the request's declared `layer_order`, converts it exactly
once to the helper's `Bottom2Top` contract, and passes through the preview
session's canonical white/black substrate. Dynamic prepared recipes already
use `Top2Bottom` and are normalized from that explicit order. Applied recipes
are separately normalized to the cache's `Top2Bottom` material-matrix storage
contract. Existing fallback behavior for missing material archives remains
unchanged.

### Material Library recipe prediction

In `api/routers/single_stage.py`, remove the endpoint-local substrate resolver
and call the core prediction helper. The frontend continues reversing the
visible face-to-substrate list into backend `Bottom2Top` order. Response
schemas, logging events, layer metadata, and validation remain unchanged.

### Achievable-color suggestions

In `frontend/src/stores/converter/store.ts`, resolve one
`suggestionLayerCount` through the existing `resolveMaterialPrintLayerCount`
helper. Use that value in both the LRU cache key and the API request. This
keeps the cached answer and network request coherent and makes dynamic 5-8
mode query the printable eight-layer space.

The backend suggestion API remains a fixed-layer solver. A new multi-depth
API is intentionally out of scope because dynamic recipes are padded to the
maximum print width and the reported failure is caused by querying the wrong
existing key. Changes to any suggestion input cancel the in-flight request,
clear its visible result, and advance a latest-request token so a transport
that ignores cancellation cannot restore a stale answer. The effective solver
grid resolution is part of the LRU key; toggling grid selection or changing
its selected tier invalidates visible and in-flight suggestions.

### Gradient-banding behavior

Gradient-banding flattening continues to select an already-computed preview
representative color. It does not run a separate forward model, so it inherits
the canonical preview value without a production-code change. Tests and real
UI verification will confirm that colors it applies are identical to the
preview representative.

If the reported two unflattened areas remain after color consistency is fixed,
that is a separate group-detection or mask-coverage bug and will not be mixed
into this pull request without its own reproducible input and root-cause proof.

## Error and Compatibility Behavior

- No request or response schema changes.
- No persisted setting, share-card, recipe import/export, or bug-report
  context changes; all required state is already captured.
- Missing material archives keep their existing deterministic fallback or API
  error behavior.
- LUT-backed, native palette, and virtual-material prediction paths are not
  changed.
- Existing material solver caches stay valid because their canonical substrate
  and rounding behavior already match the new helper.
- Black-substrate Material Library queries change from near-black `0.01` to
  the solver's canonical pure black, eliminating the same contract mismatch
  for that supported option.

## Automated Verification

Implementation follows red-green-refactor. Before production edits, add tests
that fail on the current base for the exact reasons below:

1. Core prediction rounds a deliberately fractional real-valued sRGB channel
   and uses pure white/black substrates.
2. Converter material-archive prediction returns the same rounded RGB as the
   canonical core helper.
3. Converter material-archive application writes that same RGB into the API
   response and preview cache.
4. Padded non-override pixels are recalculated through the same rounded
   contract.
5. Material Library prediction ignores a deliberately non-white first
   material `C0_white` and matches pure-white converter prediction.
6. Dynamic 5-8 mode requests and caches eight-layer suggestions, while fixed
   mode remains unchanged.
7. Converter prediction and application respect `Bottom2Top` requests, pass
   black substrate state through all three prediction sites, and retain
   `Top2Bottom` cache storage.
8. Changing the dynamic maximum clears and invalidates an in-flight result so
   an old eight-layer response cannot overwrite the new seven-layer state.
9. Default-grid, 64-grid, and 128-grid suggestion requests do not share LRU
   entries, and a response from the previous grid cannot restore stale state.

Focused gates:

```bash
.venv/bin/python -m pytest \
  tests/test_material_color_prediction_contract_unit.py \
  tests/test_material_recipe_preview_unit.py \
  tests/test_converter_recipe_override_unit.py -v

.venv/bin/python scripts/run_vitest.py run \
  src/__tests__/converter-store-material-suggest.test.ts \
  src/__tests__/material-color-picker.test.tsx

pnpm --dir frontend build
```

## Human Verification

Use separate clean base and PR worktrees and record exact commits.

1. Start the backend and frontend from each worktree.
2. Open the converter in real Chrome at the local frontend URL.
3. Use a real local SVG sample and real Saiana material archives.
4. Enable material archives and dynamic 5-8 layers at 0.08 mm.
5. Generate a preview and exercise gradient-banding flattening on a detected
   group, confirming the applied hex equals its preview representative.
6. Search achievable colors for `#FFFFF9` and inspect the returned recipe.
7. Open custom recipe editing, set eight layers to Saiana PETG white, and run
   prediction.
8. Open Material Library recipe prediction, add the same white material eight
   times in the same visible order, and compute the result.
9. On base, capture the current mismatches (`#FEFEF9`, `#FFFFF8`, and the
   five-layer suggestion request). On the PR branch, require all prediction
   surfaces to show `#FFFFF9` and the suggestion request/result to use eight
   layers.
10. Record browser console errors, failed network requests, visible loading
    states, and final screenshots. Repeat the primary path in Electron when
    the local desktop runtime is available.
11. Stop all backend, Vite, Electron, and test processes started for the
    verification.

## Release Communication

Add a bilingual, user-oriented announcement entry after reading
`docs/announcement-maintenance.md`. It will describe that converter preview,
custom recipes, achievable colors, and Material Library recipe prediction now
agree for identical material stacks. It will not mention internal helper names
or claim that unrelated gradient grouping was fixed.

The pull request description will include the human reproduction steps, base
and head commits, automated command results, Chrome/Electron evidence, and any
remaining verification gap.

## Explicit Non-Goals

- The SVG GLB handoff race already fixed by PR #549.
- Ticket-ID uniqueness across deployments.
- Material-archive SVG `chroma_gate` propagation.
- New dynamic-range suggestion endpoints or cache formats.
- Gradient-group detection or mask-coverage algorithm changes without a
  separate reproduction.
- Broad refactoring of converter routing or material solvers.
