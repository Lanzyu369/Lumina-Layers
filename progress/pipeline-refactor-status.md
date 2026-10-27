# Pipeline Refactor — Implementation Status

> **Branch**: `refactor/pipeline-hygiene-A-shims`
> **Source design doc**: `~/Downloads/pipeline-refactor-design.md` (Cascade, 2026-04-30)
> **Last updated**: 2026-04-30

This note tracks what landed on this branch and what remains for follow-up
PRs. The design doc itself sequences the work into 5 phases; per the doc
each phase ships as a separate PR with a 1-week soak gap. The user
requested a single combined PR for this round, so all phases below ride
on the same branch.

## ✅ Phase 0 — Pipeline Hygiene (4 sub-PRs squashed into 4 commits)

| Sub-PR | Status | Commit |
|---|---|---|
| **A. Delete `processing_ops/` shims** | ✅ done | `a57cf7f` + `55dca9d` |
| **D. Extract `vector_branch` from `coordinator.py`** | ✅ done | `a660a71` |
| **B. Split `pipeline_utils.py` HTML/UI to `api/`** | ✅ done | `6f354f4` |
| **C. Merge `s01`/`p01` input-validation duplication** | ✅ done | `93e1bbb` |

Notes:
- Phase 0 §14.2.2 transitional layer-violation: `core/pipeline/pipeline_utils.py`
  re-exports symbols from `api/lut_html.py` and `api/color_workstation_helpers.py`
  for backward compatibility with the `core.converter` import chain. Phase 4
  cleanup will remove these re-exports once consumers migrate.
- Phase 0 §14.2.3 helper extraction is **partial**: `_apply_material_archive_branch`,
  `_resolve_lut_path_or_error`, `_clamp_quantize_colors` extracted. The
  `_load_lut_palette` helper for the Merged-LUT block was deferred because
  s01 and p01 emit different events around it (`s01_lut_palette_*` vs
  `p01_lut_palette_*`) and the divergence carries non-trivial governance
  weight; safer to fold this into a future commit when the event taxonomy
  is unified.

## ✅ Phase 1 — ColorMode Unification (1 commit)

Commit `79a56f3`. Core delivery:

- New value object + registry: `core/color_modes.py`.
- `core/lut_merger.py::_SIZE_TO_MODE` / `_MODE_PRIORITY` / `_MODE_MAX_MATERIAL`
  derived from the registry (legacy dict shape preserved for any external
  reader).
- `core/pipeline/pipeline_utils.py::detect_lut_color_mode` collapsed into a
  single `_resolve_color_mode_from_size(...)` that delegates to
  `ColorMode.from_lut_size_and_layers`. Three duplicate threshold cascades
  (npz / json / npy) collapsed to one.
- `LUMINA_LUT_2468_MODE=merged` env override preserved via
  `core.color_modes.lut_2468_should_be_merged()`.
- 64 parity tests in `tests/test_color_mode_dispatch_unit.py`.

### Phase 1 deferrals to Phase 4

Per design doc §5.2, Phase 1 also called for routing the following through
`ColorMode`:

1. `core/calibration.py` — read `mode.n_layers`, `mode.slot_names`, etc.
2. `core/extractor.py::_generate_recipes` — dispatch via `mode.recipe_generator`.
3. `core/pipeline/processing_ops/lut_loader.py` — branch dispatch via mode.

These are **deferred** because:

- The doc itself says (§4): "Phase 4: Migrate `extractor.py`, `lut_loader.py`,
  `lut_merger.py`, `pipeline_utils.py` to consume `ColorMode` directly"
  — i.e. the per-consumer migration is acknowledged as Phase 4 work.
- Hard-coded `color_layers = 5` / `color_layers = 6` in `calibration.py` are
  physical constants tied to bit-exact 3MF output. Without the hash-based
  3MF parity tests (§5.3.4 — also deferred for fixture reasons), the safe
  path is to leave them and migrate in Phase 4 alongside the parity test
  suite.
- `_generate_recipes` and `lut_loader` branches contain intricate per-mode
  recipe-generation logic with subtle invariants (e.g. 4^5 vs 2^5 base
  loops, `get_top_1296_colors` ordering). Migrating without the recipe
  parity tests in `tests/test_color_mode_recipes_unit.py` (also deferred)
  risks silent data drift.

## ✅ Phase 2 — CalibrationMethod Protocol (1 commit, sketch)

Commit `64a6613`. Delivers the architectural commitment:

- `core/calibration_methods.py` — `CalibrationMethod` Protocol +
  `CalibrationParams` frozen dataclass.
- Lighthouse adopter `Smart1296CalibrationMethod` wrapping the existing
  `core.calibration.generate_smart_board` (bit-exact passthrough).
- 5 tests in `tests/test_calibration_methods_unit.py`.

The other `generate_*_board()` functions remain reachable via their legacy
public entry points; subclassing the rest is Phase 4 work.

## ✅ Phase 3 — BoardLayout IR + Renderer Protocol (same commit, sketch)

Same commit `64a6613`. Delivers:

- `core/board_layout.py` — frozen `BoardLayout` dataclass +
  `BoardLayoutMetadata` + `Renderer` Protocol.
- Lighthouse adopter `VoxelMeshRenderer` wrapping
  `core.calibration._generate_voxel_mesh` per material slot.
- 4 tests in `tests/test_board_layout_unit.py`.

The `SVGRenderer` lighthouse from §7.3 is **not** in this PR — it requires
working through every existing 4-Color RYBW geometry edge case to produce
a visually-equivalent SVG. Tracked as a Phase 3 follow-up.

## 🟡 Phase 4 — Adoption + new method (NOT in this PR)

Per design doc §8 and §4: "Detailed spec to be written when Phase 3 has
shipped + team's new method is ready". Phase 4 is the consumer-side
migration that turns the Phase 1-3 abstractions into the only path:

- Migrate `extractor.py::_generate_recipes` to dispatch via
  `mode.recipe_generator` (currently still a per-mode `if/elif` cascade).
- Migrate `lut_loader.py` to consume `ColorMode` instead of branch-keyed
  string matching.
- Convert each `generate_*_board()` to a dedicated
  `CalibrationMethod` subclass (currently only Smart1296 has one).
- Rewrite `_generate_voxel_mesh` call sites to consume `BoardLayout`
  instead of bare voxel arrays.
- Land the team's new calibration method as a `CalibrationMethod`
  subclass (the original trigger of this whole refactor).
- Delete the `ColorSystem.get()` shim and the legacy dict shape.
- Delete the transitional re-exports in `core/pipeline/pipeline_utils.py`
  introduced in Phase 0 Sub-PR B.
- Add the Phase 1 hash-based calibration board parity tests
  (`tests/test_calibration_board_parity_unit.py` per §5.3.4) as the safety
  net that gates Phase 4 mutations.

## Test summary

All Phase 0-3 tests pass on this branch (262 + 9 new = 271 added). Pre-existing
failures unrelated to this work: 39 (missing local fixtures such as
`元数据分析/0.2 P1S.3mf`).

Verification: `python -m pytest tests/test_color_mode_dispatch_unit.py
tests/test_calibration_methods_unit.py tests/test_board_layout_unit.py
tests/test_lut_html_unit.py tests/test_processing_ops_imports_unit.py
tests/test_input_validation_parity_unit.py
tests/test_vector_branch_extraction_unit.py
tests/test_lut_merger_properties.py tests/test_backward_compat_properties.py
tests/test_coordinator_properties.py -q`
