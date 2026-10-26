# Pipeline Refactor — Design Document (Master Plan)

> **Status**: Diagnosis + master plan + Phase 1 detailed spec. Phases 2-4 sketched only; each will be written as its own design doc when started.
> **Author**: Cascade (planning).
> **Trigger**: Team feedback that a newly-prototyped calibration method only works for "high-fidelity pixel/voxel mode at 5 layers", and adding 10-layer / SVG support requires bespoke per-mode rewrites — i.e. the calibration-method × input-mode × layer-count surface is N×M×K hard-coupled instead of N+M+K composable.
> **Scope**: Backend `core/` (calibration, pipeline stages, LUT loader, mesh/vector/output renderers). Frontend, API, and tests on the consumer side change only where the canonical color-mode object becomes the new contract.
> **Constraint** (hard): Lossless refactoring per `AGENTS.md` L48-51. All current behavior must be preserved bit-exact for existing color modes; tests written first, then implementation, then verification.

---

## 1. Mission & Scope

### 1.1 The actual pain point

The team is researching new calibration methods (think: improved color-selection algorithms, alternate measurement strategies, multi-page kits with novel geometry). With the current architecture, the work to ship a single new method to all existing input modes (high-fidelity pixel / voxel / SVG / multi-page) and color counts (BW / 4-Color / 6-Color / 8-Color / 5-Color Extended) is **N × M × K bespoke implementations**, where:

- **N** = number of calibration methods (currently 1 mature one across multiple modes; team is adding 1+ new).
- **M** = number of output target shapes (voxel/3MF, SVG/vector, future: multi-layer-count exports, large-format tiled).
- **K** = number of color modes (currently 5: BW, 4-Color (RYBW & CMYW), 6-Color (CMYW & RYBW), 8-Color, 5-Color Extended).

The target is **N + M + K composable** code: any (method, output, color-mode) combination should work without writing new code per cell of the matrix.

### 1.2 What this document is

A diagnosis + a 4-phase plan + Phase 1 detailed spec. **Phase 1 is the prerequisite for every other phase**; without unifying the color-mode taxonomy first, the deeper abstractions (CalibrationMethod ABC, BoardLayout IR, Renderer pluggability) cannot land cleanly.

### 1.3 What this document is NOT

- It is not a final implementation spec for Phases 2-4 (each gets its own design doc when started).
- It does not propose any user-facing feature change. The end state must be **bit-exact** with current output for all existing modes.
- It does not change API endpoints, frontend contracts, or persistent file formats (LUT `.npz` / `.json`, 3MF, calibration board files).
- It does not invent a new calibration method. New methods are downstream consumers of the new abstractions.

---

## 2. Diagnosis

### 2.1 Color-mode dispatch is duplicated across 6+ files

Color mode is a string (e.g. `"6-Color (CMYWGK 1296)"`) that flows through a string-matching `if/elif` cascade in **at least six** places, each with subtly different rules:

1. **`config.py::ColorSystem.get()`** — string lookup → returns config dict.

```@e:/Lumina-Layers/LL-1296/Lumina-Layers/config.py:289-326
        if mode is None:
            return ColorSystem.RYBW  # Default fallback

        # 4-Color CMYW variant
        if mode in ("4-Color (CMYW)", "CMYW"):
            return ColorSystem.CMYW

        # 4-Color RYBW variant (also handles legacy "4-Color" string)
        if mode in ("4-Color (RYBW)", "4-Color", "RYBW") or "4-Color" in mode:
            return ColorSystem.RYBW

        # Check specific patterns
        if "8-Color" in mode:
            return ColorSystem.EIGHT_COLOR
        if mode in ("6-Color (RYBWGK 1296)",):
            return ColorSystem.SIX_COLOR_RYBW
        if "6-Color" in mode:
            return ColorSystem.SIX_COLOR
```

2. **`core/calibration.py`** — one dedicated `generate_*_board()` function per mode, each with its own hardcoded grid dim, layer count, corner-marker logic, and preview-palette selection (`generate_calibration_board` for 4-Color, `generate_smart_board` for 6-Color CMYW, `generate_smart_board_rybw` for 6-Color RYBW, `_generate_5color_base_page` for 5C-Ext page 1, `_generate_5color_extended_page` for 5C-Ext page 2, plus 8-color variants).

3. **`core/extractor.py::_generate_recipes()`** — another `if/elif color_mode` tree, generating per-mode recipe stacks:

```@e:/Lumina-Layers/LL-1296/Lumina-Layers/core/extractor.py:267-342
    if color_mode == "BW (Black & White)" or color_mode == "BW":
        # 2^5 = 32 combinations, 5 layers
        ...
    if "8-Color" in color_mode:
        ...
    if "6-Color" in color_mode:
        from core.calibration import get_top_1296_colors
        ...
    if "5-Color Extended" in color_mode:
        ...
    # Default: 4-Color (RYBW/CMYW) — 4^5 = 1024 combinations, 5 layers
    stacks = []
    for i in range(total_cells):
        ...
```

4. **`core/pipeline/processing_ops/lut_loader.py`** — yet another `if/elif color_mode` tree, this time with a third independent set of branches selecting which calibration helper to call:

```@e:/Lumina-Layers/LL-1296/Lumina-Layers/core/pipeline/processing_ops/lut_loader.py:339-441
    # Branch 1: 8-Color Max (2738)
    elif "8-Color" in color_mode or total_colors == 2738:
        ...
        smart_stacks = np.load(stacks_path).tolist()
        ...
    # Branch 2: 6-Color Smart 1296
    elif "6-Color" in color_mode or total_colors == 1296:
        from core.calibration import get_top_1296_colors
        smart_stacks = get_top_1296_colors()
        ...
    # Branch 3: 5-Color Extended (2468)
    elif "5-Color Extended" in color_mode or total_colors == 2468:
        ...
```

5. **`core/lut_merger.py`** — three parallel dicts that re-encode mode info in yet another shape:

```@e:/Lumina-Layers/LL-1296/Lumina-Layers/core/lut_merger.py:50-98
_SIZE_TO_MODE = {
    32: "BW",
    1024: "4-Color",
    1296: "6-Color",
    2468: "5-Color Extended",
    2738: "8-Color",
}
...
_MODE_PRIORITY = {
    "Merged": -1,
    "BW": 0,
    "4-Color": 1,
    ...
}
_MODE_MAX_MATERIAL = {
    "BW": 1,
    "4-Color": 3,
    "6-Color": 5,
    "5-Color Extended": 4,
    "8-Color": 7,
    "Merged": 7,
}
```

6. **`core/pipeline/pipeline_utils.py::detect_lut_color_mode()`** — size-based detection thresholds (yet another encoding of the same taxonomy):

```@e:/Lumina-Layers/LL-1296/Lumina-Layers/core/pipeline/pipeline_utils.py:424-458
                if (
                    total_colors >= 2400
                    and total_colors < 2600
                    and layer_count == 6
                    and (max_mat is None or max_mat <= 4)
                ):
                    ...
                    return "5-Color Extended"
                if total_colors >= 2600 and total_colors <= 2800:
                    ...
                    return "8-Color Max"
                if total_colors >= 1200 and total_colors < 1400:
                    ...
                    return "6-Color (CMYWGK 1296)"
```

**Each of these six sites has slightly different matching rules**. Adding a new color mode (e.g. a hypothetical 10-Color or new layer-count) requires touching all six, with high risk of inconsistency.

### 2.2 Layer count is hardcoded throughout

The integers `5` (layers) and `6` (layers) appear as magic numbers in every per-mode function:

```@e:/Lumina-Layers/LL-1296/Lumina-Layers/core/calibration.py:432-435
    # Layer configuration
    color_layers = 5
    backing_layers = int(PrinterConfig.BACKING_MM / PrinterConfig.LAYER_HEIGHT)
    total_layers = color_layers + backing_layers
```

```@e:/Lumina-Layers/LL-1296/Lumina-Layers/core/calibration.py:1577-1580
    # 6 color layers + white backing (Face-Down mode, viewing surface at Z=0)
    color_layers = 6
    backing_layers = int(PrinterConfig.BACKING_MM / PrinterConfig.LAYER_HEIGHT)
    total_layers = color_layers + backing_layers
```

A 10-layer mode literally has no place to be expressed without editing every site.

### 2.3 Voxel-only mesh path; SVG path is parallel and disconnected

`_generate_voxel_mesh()` in `core/calibration.py:55-130` is the **only** mesh-generation API in the calibration module. Every existing calibration board is rendered through this voxel path. The SVG / vector path lives in `core/vector_engine.py` (124 KB) and `core/vector_large_format.py`, completely separate, with no shared intermediate representation. A calibration method's output (voxel matrix) cannot be fed to the SVG path without writing a parallel implementation.

This is what the team experienced: a new calibration method "only worked for the high-fidelity pixel/voxel mode" because that is the only mesh path the calibration module knows about.

### 2.4 Recipe-generation logic is duplicated between calibration and consumers

The 4^5 = 1024 base-stack generator appears verbatim in at least three files:

- `core/calibration.py::generate_calibration_board` (line ~168)
- `core/calibration.py::_generate_5color_base_page` (line ~1454)
- `core/extractor.py::_generate_recipes` (line ~344-352)
- `core/pipeline/processing_ops/lut_loader.py` Branch 3 (line ~413-420)

Same loop body, four copies. This is a textbook DRY violation that the new abstraction must collapse.

### 2.5 Summary of architectural smells (calibration N×M×K)

§2.1-2.4 are all faces of one underlying smell. Using Fowler's terms: this is **"Switch on Type"** with the type encoded as a string and the switch duplicated. The cure is **"Replace Conditional with Polymorphism"** — turn color mode into a first-class object with the per-mode parameters and behaviors as fields/methods, then dispatch through it. This family is solved by Phase 1 (ColorMode unification, §5).

### 2.6 s/p input-validation modules are near-duplicates

The raster pipeline's `core/pipeline/s01_input_validation.py` (333 LOC) and the preview pipeline's `core/pipeline/p01_preview_validation.py` (234 LOC) duplicate the same logic:

- Same `material_archive` branch: `load_multiple_materials` → `build_material_slot_names` → `build_material_preview_colors` → synthetic `color_conf` → `color_layers` / `layer_height_mm` / `grid_resolution`.
- Same LUT path resolution: `isinstance(lut_path, str)` ↔ `hasattr(lut_path, "name")` ↔ same error-prefix branching (only the error-message strings differ slightly).
- Same Merged-LUT palette extraction: `LUTManager.load_lut_with_metadata` → `build_palette_preview_colors` → identical try/except fallback to `color_conf` defaults.
- Same `quantize_colors` clamp (`max(8, min(256, ...))`).

The only meaningful differences are:

- s01 additionally handles `is_svg_vector` detection (vector-routing for raster path), `separate_backing` and `backing_color_id` validation.
- s01 writes timing into `_hifi_timings` and emits `s01_*` events; p01 writes `_preview_timings` and emits `p01_*` events.

This is **shotgun surgery**: adding a new color mode, changing the LUT loader, or adjusting an error message must be replicated in two files; missing one yields silent drift between preview and generate paths. The vector-mode bug fixed in v2.1 (`coordinator.py:535-549`, where ColorWorkstation region edits had to be back-written into `analysis.matched_shapes`) is the same family — the preview path's `cache.matched_rgb` and the generate path's `analysis.matched_shapes` each carried a partial copy of the replacement state.

### 2.7 `pipeline_utils.py` is a 36 KB god module + layering violation

`core/pipeline/pipeline_utils.py` (36826 bytes) mixes seven unrelated concerns:

| Section (per existing comment headers) | Approx. LOC | Concern |
|---|---|---|
| Color utility functions (L23-250) | ~230 | Pure utility (legitimate) |
| LUT utility functions (L253-610) | ~360 | Business — includes `detect_lut_color_mode` (~200 LOC, the 6th dispatch site already noted in §2.1) |
| Detection utility functions (L613-657) | ~45 | Business |
| Cache helper functions (L659-682) | ~25 | Business |
| **LUT HTML grid functions (L684-886)** | ~200 | **UI/presentation — does not belong in `core/`** |
| **Color selection helper functions (L889-994+)** | ~100+ | UI/click-handling — does not belong in `core/` |

The HTML and click-selection segments violate `AGENTS.md`'s layering invariant:

> Preserve layering: `core/` -> API/workers -> UI

Any change to LUT preview button styling currently requires editing `core/pipeline/`, and conversely any pure-domain refactor in `core/pipeline/` risks accidentally breaking UI rendering.

Companion file `core/pipeline/preview_color_utils.py` (9286 bytes) further fragments color helpers — same concept split across two files with no clear edge condition. It is unclear which file should be the home for new color utilities.

### 2.8 Vector branch lives inside `coordinator.py`

`core/pipeline/coordinator.py` (37454 bytes) contains both:

- The clean, table-driven raster/preview pipeline orchestrators (`_RASTER_STEPS` + `_PREVIEW_STEPS` loops, ~250 LOC).
- Two large vector-branch handlers (`_run_vector_preview_branch` ~70 LOC at L380-448, `_run_vector_branch` ~400+ LOC starting at L456) that completely bypass S02-S12 and directly invoke `VectorProcessor.analyze_svg`, `apply_matched_rgb_overrides_to_analysis`, 3MF export, and GLB preview generation.

The orchestrator should not know about renderer-level concerns (3MF writer specifics, GLB preview details, `apply_matched_rgb_overrides_to_analysis`). Phase 3 (BoardLayout IR + Renderer plugins) is the right long-term home for this code, but the immediate hygiene fix is to extract the vector branch from `coordinator.py` into a peer module so the orchestrator regains single responsibility.

### 2.9 `processing_ops/` contains zero-logic re-export shims

Of the 11 modules in `core/pipeline/processing_ops/`, two are pure namespace-redirect shims:

- `hue_aware_matcher.py` (371 bytes): only `from core.color_matching_hue_aware import HueAwareColorMatcher`.
- `isolated_pixel_cleanup.py` (373 bytes): only `from core.isolated_pixel_cleanup import cleanup_isolated_pixels`.

Several others (`bilateral_filter.py` 1.2 KB, `median_filter.py` 1.2 KB, `background_remover.py` 2.0 KB, `wireframe_extractor.py` 2.6 KB) need closer inspection during Phase 0 sub-PR A; some may also be thin wrappers around `core/*` real implementations. This is decorative architecture — a layer that exists only for the sake of existing.

### 2.10 Summary of architectural smells (pipeline hygiene)

§2.6-2.9 are a **different family** of smells from §2.1-2.4. They are not "Switch on Type"; they are **"over-coupling disguised as decoupling"** — files / modules / numbering schemes look separated, but the same logic is copy-pasted across them, and presentation logic has leaked into the domain layer.

The cures are mechanical: **"Inline Trivial Wrapper"** (delete the shims), **"Extract Common Method"** (collapse s01/p01), **"Move Method (across layers)"** (relocate HTML helpers to `api/`), and **"Move Method (within package)"** (extract vector branch from coordinator). No new abstractions are introduced.

This family is solved by Phase 0 (Pipeline Hygiene, §14), which is sequenced **before** Phase 1 because Phase 1's deliverables include modifications to `core/pipeline/pipeline_utils.py::detect_lut_color_mode` — Phase 0 first restructures that file to remove the layering violations, after which Phase 1's edits land on a cleaner target.

---

## 3. Target Architecture

### 3.1 Three new abstractions

```
+----------------------------------------------------------------+
|                  ColorMode (Phase 1)                           |
|  - name, n_materials, n_layers, slot_names, preview_palette,   |
|    corner_markers, recipe_generator, board_grid_dim, ...       |
|  Replaces 6+ string-matching dispatch sites.                   |
+--------------------------+-------------------------------------+
                           |
                           |  consumed by
                           v
+----------------------------------------------------------------+
|                  CalibrationMethod (Phase 2)                   |
|  ABC with .generate(color_mode: ColorMode,                     |
|                     params: CalibrationParams)                 |
|                  -> BoardLayout                                |
|  Each existing generate_*_board fn becomes one subclass.       |
|  New method = new subclass.                                    |
+--------------------------+-------------------------------------+
                           |
                           |  produces (output IR)
                           v
+----------------------------------------------------------------+
|                  BoardLayout (Phase 3, IR)                     |
|  - voxel_matrix (Z, H, W, dtype=int)                           |
|  - color_mode (back-reference)                                 |
|  - metadata (corner positions, slot labels, page index, ...)   |
|  Pure data; no rendering logic.                                |
+--------------------------+-------------------------------------+
                           |
                           |  rendered by
                           v
+----------------------------------------------------------------+
|                  Renderer (Phase 3, plugin)                    |
|  - VoxelMeshRenderer  -> trimesh.Scene -> 3MF                  |
|  - SVGRenderer        -> SVG string                            |
|  - PNGRenderer        -> PIL.Image                             |
|  - (future) MultiLayerCountRenderer                            |
|  N methods x M renderers via composition, not N x M code.      |
+----------------------------------------------------------------+
```

### 3.2 Why this is the right shape

- **ColorMode as a value object** removes the 6-way string-matching duplication. A typo in any one site is currently a silent inconsistency; with `ColorMode` it becomes a type error / lookup failure.
- **CalibrationMethod as Protocol/ABC** lets new methods land without touching old ones; `AGENTS.md` L38 ("clear abstractions, single responsibility, high cohesion, low coupling, and readable composition") is exactly this shape.
- **BoardLayout as IR** decouples geometry from rendering. Currently `_generate_voxel_mesh` is called inline at the bottom of every `generate_*_board` function; with IR, the same `BoardLayout` can feed both voxel and SVG renderers.
- **Renderer as plugin** lets SVG / multi-layer-count / future formats be added by writing one renderer, without re-implementing each calibration method. This is the answer to "10-layer and SVG support require single-mode rewrites".

### 3.3 What this looks like at the call site (after all four phases)

```python
# Hypothetical post-refactor flow:
mode = ColorMode.lookup("6-Color (RYBWGK 1296)")        # canonical taxonomy
method = Smart1296CalibrationMethod()                    # method = an object
layout = method.generate(mode, params=CalibrationParams(block_size_mm=5.0))
voxel_3mf = VoxelMeshRenderer().render(layout)           # current path
svg = SVGRenderer().render(layout)                       # NEW: same layout
preview = PreviewPNGRenderer().render(layout)            # current preview path
```

Adding a new method:

```python
class NewCalibrationMethod(CalibrationMethod):
    def generate(self, mode: ColorMode, params: CalibrationParams) -> BoardLayout:
        # use mode.n_layers, mode.recipe_generator, mode.preview_palette, ...
        # never branch on mode.name strings
        ...
```

Adding a new renderer (10-layer / new export format):

```python
class TenLayerRenderer(Renderer):
    def render(self, layout: BoardLayout) -> bytes:
        # works for any ColorMode and any CalibrationMethod
        ...
```

The matrix is N + M + K, not N × M × K.

---

## 4. Phased Migration Plan

The refactor lands in **five sequenced PRs** (Phase 0 + Phases 1-4), each its own design doc and round of subagent work. Each PR is **lossless** (existing tests must continue passing) and **independently revertable**.

| Phase | Goal | Estimated effort | Lands when |
|---|---|---|---|
| **Phase 0: Pipeline Hygiene** | Delete `processing_ops/` shims; split `pipeline_utils.py` (extract HTML/UI helpers to `api/`); merge s01/p01 input validation; extract vector branch from `coordinator.py`. No new abstractions. | 3-5 days (4 independent sub-PRs) | Bug Report v2.1 has shipped + 1 week of soak |
| **Phase 1: ColorMode unification** | Replace 6 string-matching dispatch sites with a single `ColorMode` value object. Existing behavior bit-exact. | 1-2 weeks | Phase 0 has shipped |
| **Phase 2: CalibrationMethod ABC** | Introduce `CalibrationMethod` Protocol; refactor existing `generate_*_board` functions to subclasses; entry points unchanged. | 3-5 days | Phase 1 has shipped |
| **Phase 3: BoardLayout IR + Renderer plugins** | Extract `BoardLayout` IR; split mesh generation into `VoxelMeshRenderer`; add `SVGRenderer` as the lighthouse adoption. Folds the Phase-0-extracted `core/pipeline/vector_branch.py` into the new Renderer abstraction. | 1-2 weeks | Phase 2 has shipped |
| **Phase 4: Adoption + cleanup** | Migrate `extractor.py`, `lut_loader.py`, `lut_merger.py`, `pipeline_utils.py` to consume `ColorMode` directly; delete dead string-matching code; team's new calibration method lands as a `CalibrationMethod` subclass. | 3-5 days | Phase 3 has shipped + team's new method is ready |

**Total**: 4-6 weeks of subagent time, ~5 PRs (Phase 0 may be 4 sub-PRs), ~7-9 weeks wall-clock (including soak windows between phases).

**Critical sequencing constraints**:

1. Do NOT start Phase 0 before Bug Report v2.1 has shipped + 1 week of real user reports. The bug-report channel is the radar during the refactor; without it, regressions go unnoticed.
2. Do NOT start Phase 1 before Phase 0 has shipped. Phase 1 modifies `pipeline_utils.py::detect_lut_color_mode`; Phase 0 first restructures `pipeline_utils.py` (extracting HTML/UI segments to `api/`), so Phase 1's edits land on a cleaner target. Running Phase 0 first also de-risks the `s01/p01` input-validation merge before Phase 1 introduces the `ColorMode` value object that both s01 and p01 will consume.
3. Phase 0's four sub-PRs (A: shims, B: pipeline_utils split, C: input-validation merge, D: vector branch extraction) are **independent** and may ship in any order or in parallel, but all four must land before Phase 1 starts.

---

## 5. Phase 1 Detailed Spec — ColorMode Unification

### 5.1 Phase 1 mission

Introduce a single canonical `ColorMode` object that holds all the per-mode parameters currently scattered across `config.py`, `calibration.py`, `extractor.py`, `lut_loader.py`, `lut_merger.py`, and `pipeline_utils.py`. Replace the six string-matching dispatch sites with `ColorMode` lookups + attribute reads. Keep all public function signatures and observable behavior unchanged.

**Phase 1 prerequisite**: Phase 0 (Pipeline Hygiene, §14) must ship first. Phase 0 restructures `core/pipeline/pipeline_utils.py` (extracts HTML/UI segments to `api/lut_html.py`) and merges the `s01_input_validation.py` / `p01_preview_validation.py` duplication into a shared helper. This Phase 1 spec assumes that restructured layout when modifying `detect_lut_color_mode` (§5.2 item 7) and when wiring `ColorMode` into the input-validation flow.

### 5.2 Phase 1 deliverables

1. New file `core/color_modes.py` (~250 LOC):
   - Frozen dataclass `ColorMode` with fields:
     - `name: str` — canonical id (e.g. `"6-color-rybw-1296"`).
     - `display_names: tuple[str, ...]` — every alias the dispatch sites currently match.
     - `n_materials: int` — max material id + 1.
     - `n_layers: int` — color layer count (5 / 6 / future).
     - `slot_names: tuple[str, ...]` — material slot names (length = n_materials).
     - `preview_palette: tuple[tuple[int, int, int, int], ...]` — RGBA per material.
     - `corner_markers: tuple[int, int, int, int]` — material ids for TL/TR/BR/BL.
     - `expected_lut_size: int | None` — 32 / 1024 / 1296 / 2468 / 2738 (None for "Merged").
     - `priority: int` — for merger conflict resolution (replaces `_MODE_PRIORITY`).
     - `data_grid_dim: int` — 32 / 36 / 38 (board grid size, excluding padding).
     - `recipe_generator_id: str` — identifies which built-in recipe generator (Phase 2 will turn this into a callable).
   - Module-level registry `_COLOR_MODE_REGISTRY: dict[str, ColorMode]` populated via constructor calls at import time.
   - Public functions:
     - `ColorMode.from_name(name: str) -> ColorMode | None` — alias-aware lookup, replaces `ColorSystem.get()`.
     - `ColorMode.from_lut_size(size: int) -> ColorMode | None` — replaces `_SIZE_TO_MODE`.
     - `ColorMode.from_lut_size_and_layers(size: int, layers: int | None) -> ColorMode | None` — covers the 5-Color Extended case where size + layer count both matter.
     - `iter_modes() -> Iterator[ColorMode]`.
   - Document the behavior of the public symbols.

2. Modified `config.py` (~50 LOC delta):
   - `ColorSystem` config dicts kept as-is (file-format compatibility for any code that imports them directly).
   - `ColorSystem.get()` becomes a thin shim that calls `ColorMode.from_name(mode).legacy_dict` (a property that returns the equivalent old dict structure).
   - **No removal** of existing keys; only deprecation comments.

3. Modified `core/calibration.py` (~150 LOC delta):
   - `generate_calibration_board`, `generate_smart_board`, `generate_smart_board_rybw`, `_generate_5color_base_page`, `_generate_5color_extended_page`, plus 8-color helpers all read `ColorMode` for `n_layers`, `slot_names`, `preview_palette`, `corner_markers`, `data_grid_dim`.
   - Hardcoded `color_layers = 5` / `color_layers = 6` lines replaced by `color_layers = mode.n_layers`.
   - Hardcoded grid dims replaced by `mode.data_grid_dim`.
   - String parameter `color_mode: str` is **kept** in public signatures (backward compat); internally converted to `ColorMode` immediately.
   - `_generate_voxel_mesh` unchanged (Phase 3 territory).

4. Modified `core/extractor.py` (~80 LOC delta):
   - `_generate_recipes` body becomes:
     ```python
     mode = ColorMode.from_name(color_mode)
     if mode is None:
         # legacy fallback: 4-color
         mode = ColorMode.from_name("4-Color")
     return mode.generate_recipes(total_cells, page_choice, eight_color_full_export)
     ```
   - `mode.generate_recipes` dispatches to one of the existing recipe generators by `recipe_generator_id`. The dispatch table lives in `core/color_modes.py` and is wired to the existing helpers (`get_top_1296_colors`, `_get_8color_page_stacks`, `select_extended_1444_colors`, plus a built-in `_default_pow_stacks` for the 4^5 / 2^5 cases).

5. Modified `core/pipeline/processing_ops/lut_loader.py` (~120 LOC delta):
   - The four `Branch N: ...` `elif` blocks replaced by a single dispatch through `ColorMode`. Each branch becomes a tiny per-mode adapter that just calls `mode.generate_recipes(...)`.
   - "Merged" branch keeps its companion-`.npz` lookup logic (that's data-loading, not mode dispatch).

6. Modified `core/lut_merger.py` (~40 LOC delta):
   - `_SIZE_TO_MODE`, `_MODE_PRIORITY`, `_MODE_MAX_MATERIAL` deleted; queries replaced by `ColorMode.from_lut_size(...)`, `mode.priority`, `mode.n_materials - 1`.
   - The `LUMINA_LUT_2468_MODE=merged` env override stays where it is (special-case business rule).

7. Modified `core/pipeline/pipeline_utils.py::detect_lut_color_mode` (post-Phase-0 — HTML/UI segments have been extracted to `api/lut_html.py`, so the surrounding file is ~15-18 KB instead of 36 KB) (~80 LOC delta):
   - Body becomes a thin call: `mode = ColorMode.from_lut_size_and_layers(total_colors, layer_count)`. Returns `mode.display_names[0]` (or `None`) so external string consumers are unaffected.
   - The size-range thresholds (`>= 2400 and < 2600`, etc.) are codified inside `ColorMode.from_lut_size_and_layers` as one canonical implementation.

### 5.3 New tests required (write FIRST per AGENTS.md L48-51)

Before any of the above changes, the GPT subagent must:

1. **Capture current behavior in characterization tests** in `tests/test_color_mode_dispatch_unit.py` (~250 LOC):
   - For each existing display name (`"4-Color"`, `"4-Color (RYBW)"`, `"4-Color (CMYW)"`, `"6-Color (CMYWGK 1296)"`, `"6-Color (RYBWGK 1296)"`, `"8-Color"`, `"8-Color Max"`, `"5-Color Extended"`, `"5-Color (Extended)"`, `"BW"`, `"BW (Black & White)"`, `"Merged"`, `"CMYW"`, `"RYBW"`, `None`, `""`):
     - Assert `ColorSystem.get(name)` returns the existing dict (post-refactor still returns equivalent dict).
     - Assert `ColorMode.from_name(name)` returns the expected canonical mode (or None for invalid).
   - For each existing LUT size (32, 1024, 1296, 2468, 2738, plus 30, 36, 1300, 2700 boundary values):
     - Assert `ColorMode.from_lut_size(size)` matches the legacy mapping.
   - Round-trip: every mode's `display_names[0]` must round-trip through `from_name`.

2. **Recipe-generator parity tests** in `tests/test_color_mode_recipes_unit.py` (~200 LOC):
   - For each mode and a representative `total_cells`:
     - Assert `mode.generate_recipes(total_cells, page_choice="Page 1")` produces the same `np.ndarray` (shape + values) as the existing `core.extractor._generate_recipes(color_mode_str, total_cells, page_choice)`.
   - Use `numpy.testing.assert_array_equal` for bit-exactness.

3. **`detect_lut_color_mode` parity tests** in `tests/test_pipeline_utils_color_mode_detection_unit.py` (~120 LOC):
   - Synthetic `.npz` + `.json` LUT fixtures for each mode + boundary sizes; assert detected mode matches the legacy implementation.

4. **`generate_*_board` characterization tests** in `tests/test_calibration_board_parity_unit.py` (~300 LOC):
   - For each calibration entry point, run with a fixed seed / fixed parameters, hash the output 3MF / preview PNG bytes, assert the post-refactor hash matches the pre-refactor hash. **This is the core lossless guarantee.**
   - These tests must be added **before** `core/calibration.py` is touched.

### 5.4 Logging governance compliance

No new mutating endpoint is added in Phase 1 (no API surface changes), so no new `*_done` canary INFO is required. However:

- The new `ColorMode` lookups must NOT introduce any new bucket events (`*_log` / `mode_*`). Use specific event names if logging at all (e.g. `color_mode_resolved`, `color_mode_lookup_failed`).
- Per-mode resolution logs must be at DEBUG level, not INFO, to preserve the FROZEN canonical 14/30 INFO budget.
- After Phase 1 lands, run the full governance trio + `python scripts/log_quality_check.py --mode fast` and confirm no regression.

### 5.5 Phase 1 acceptance matrix

- [ ] All new tests in §5.3 pass (4 new files, ~870 LOC of tests).
- [ ] Existing test suite passes unmodified: `python -m pytest tests/ -v`.
- [ ] `python scripts/log_quality_check.py --mode fast` — INFO 14/30 PASS (UNCHANGED).
- [ ] `python scripts/log_quality_check.py --mode full` — PASS.
- [ ] Performance regression: `python scripts/profile_stage3.py --also-write-latest && python scripts/check_perf_regression.py` — within tolerance.
- [ ] `core/calibration.py` produces byte-identical 3MF outputs for all existing modes vs. baseline (verify via the parity test in §5.3.4).
- [ ] No Chinese mojibake markers (`锟` / `鎷` / `鍙` / `涓`) introduced anywhere; `Get-Content -Encoding UTF8` clean for every modified file.
- [ ] No new `_log` / `*_log` / `request_*` / `status_*` bucket events introduced.
- [ ] `python -m pytest tests/test_logging_exception_governance_unit.py tests/test_structured_logging_unit.py tests/test_logger_unit.py -v` — PASS (count unchanged from current 21 unless new whitelist entries are added).

### 5.6 Phase 1 risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Breaking change in legacy code that imports `ColorSystem.get()` directly | M | M | Keep `ColorSystem.get()` as a passthrough; never remove the function |
| Subtle behavior drift in `detect_lut_color_mode` thresholds | M | H | §5.3.3 parity tests; written first |
| 3MF output not bit-exact (mesh vertex order, slot order) | L | H | §5.3.4 hash-based parity test; if hash diverges, investigate before merging |
| Performance regression (extra dataclass allocation) | L | L | `ColorMode` is frozen / interned; lookup is O(1) dict; should be faster than current cascading `if`s |
| Missed dispatch site (some 7th `if "X-Color" in mode` somewhere) | M | M | grep gate: post-refactor, `grep -rn 'if.*\b(4-Color|6-Color|8-Color|5-Color Extended|BW.*Black)\b'` outside `tests/` and `progress/` should return zero hits in `core/`, `api/`, `frontend/` |
| Frontend reads `ColorSystem` JSON shape | L | M | Frontend reads via API, not directly; keep API shape unchanged |
| `LUMINA_LUT_2468_MODE=merged` env override breaks | L | M | Specific test in `test_color_mode_dispatch_unit.py` covering the env-override path |

### 5.7 Phase 1 hand-off TL;DR

- Branch from `dev-refactor` HEAD; branch name `refactor/color-mode-phase1`.
- ~5 commits, conventional commits:
  1. `test(core): add color-mode dispatch parity tests` (the §5.3 tests).
  2. `feat(core): introduce ColorMode value object in core/color_modes.py`.
  3. `refactor(core): migrate calibration.py + lut_merger.py to ColorMode`.
  4. `refactor(pipeline): migrate lut_loader.py + pipeline_utils.py to ColorMode`.
  5. `refactor(extractor): migrate _generate_recipes to ColorMode`.
- PR title: `refactor(core): unify color-mode dispatch via ColorMode value object (Phase 1 of 4)`.
- PR body: §5.5 acceptance matrix as a literal checklist + a paragraph linking to this design doc.

---

## 6. Phase 2 Sketch — CalibrationMethod ABC

> **Detailed spec to be written when Phase 1 has shipped + 1 week soak.**

### 6.1 Goal

Convert each existing `generate_*_board()` function into a subclass of a `CalibrationMethod` Protocol/ABC. Public entry points (`generate_calibration_board`, `generate_smart_board`, etc.) become thin wrappers that instantiate the appropriate subclass and call `.generate()`. New calibration methods plug in by implementing the protocol.

### 6.2 Sketch interface

```python
class CalibrationMethod(Protocol):
    """Protocol every calibration generator must satisfy.

    每个校准生成器都必须满足的协议。
    """
    name: str            # e.g. "smart-1296", "5color-extended-page2"
    description: str

    def generate(
        self,
        mode: ColorMode,
        params: CalibrationParams,
    ) -> BoardLayout:
        """Produce a BoardLayout (mode-independent IR).

        生成 BoardLayout（颜色模式无关的中间表示）。
        """
        ...


@dataclass(frozen=True)
class CalibrationParams:
    block_size_mm: float
    gap_mm: float
    backing_layers: int
    page_index: int = 0      # for multi-page modes (5-Color Extended)
    options: dict[str, Any] = field(default_factory=dict)
```

### 6.3 Initial subclasses

- `Smart1296CalibrationMethod` — wraps `generate_smart_board`.
- `FourColorCalibrationMethod` — wraps `generate_calibration_board`.
- `EightColorCalibrationMethod` — wraps the 8-color helpers.
- `FiveColorExtendedCalibrationMethod` — wraps `_generate_5color_*_page` (handles `page_index`).

### 6.4 Phase 2 acceptance criteria sketch

- All existing public entry points keep their signatures and behavior.
- Each subclass has its own unit test file.
- Hash parity with Phase 1 baseline preserved.

---

## 7. Phase 3 Sketch — BoardLayout IR + Renderer Plugins

> **Detailed spec to be written when Phase 2 has shipped + 1 week soak.**

### 7.1 Goal

Extract `BoardLayout` (purely data: voxel matrix + metadata) from inside each `CalibrationMethod`. Move mesh-generation code (`_generate_voxel_mesh`) into a new `VoxelMeshRenderer`. Add `SVGRenderer` as the **lighthouse adoption** of the new abstraction (per `AGENTS.md` L42 utility-adoption rule).

### 7.2 Sketch interface

```python
@dataclass(frozen=True)
class BoardLayout:
    """Mode-independent intermediate representation of a calibration board.

    校准板的中间表示，与颜色模式无关。
    """
    voxel_matrix: np.ndarray            # (Z, H, W) int
    color_mode: ColorMode
    metadata: BoardLayoutMetadata       # corner positions, slot labels, page index, ...


class Renderer(Protocol):
    """Protocol every output renderer must satisfy.

    每个输出渲染器必须满足的协议。
    """
    output_format: str                  # "3mf", "svg", "png", ...

    def render(self, layout: BoardLayout) -> bytes | str:
        ...
```

### 7.3 Initial renderers

- `VoxelMeshRenderer` — wraps `_generate_voxel_mesh` + Bambu 3MF export.
- `PreviewPNGRenderer` — wraps the existing per-mode preview-image code (currently inlined in each `generate_*_board`).
- `SVGRenderer` — **NEW**, the proof-of-value: takes the same `BoardLayout` and renders an SVG. Initially supports the 4-color RYBW path; subsequent commits extend to other modes.

### 7.4 Phase 3 acceptance criteria sketch

- Voxel + preview parity preserved (hash baseline).
- SVG output for at least 4-Color RYBW board exists, is valid SVG, and visually matches the voxel preview.
- A new calibration method can be added in Phase 4 without touching any renderer.
- A new renderer (e.g. multi-layer-count export) can be added without touching any calibration method.

---

## 8. Phase 4 Sketch — Adoption + New Method

> **Detailed spec to be written when Phase 3 has shipped + team's new method is ready.**

### 8.1 Goal

Migrate the remaining downstream consumers (`extractor.py`, `lut_loader.py`, `lut_merger.py`, `pipeline_utils.py`) to consume `ColorMode` / `BoardLayout` directly instead of through string-keyed adapters. Delete the legacy `ColorSystem.get()` shim and the dispatch tables it backs. Land the team's new calibration method as a `CalibrationMethod` subclass + add an `SVGRenderer` extension if needed.

### 8.2 Phase 4 acceptance criteria sketch

- Zero `if "X-Color" in mode` cascades remain in `core/`, `api/`, or `frontend/` outside test files.
- `_SIZE_TO_MODE`, `_MODE_PRIORITY`, `_MODE_MAX_MATERIAL` and the `ColorSystem` config dicts deleted; replaced by `ColorMode` registry.
- Team's new calibration method works for **every** existing color mode and **every** renderer, with no per-mode bespoke code in the new method.
- 10-layer hypothetical mode can be added by registering a single new `ColorMode` instance, no other code changes — verified by adding a stub 10-layer mode in tests and confirming all renderers handle it.

---

## 9. Lossless Refactoring Discipline

`AGENTS.md` L48-51 is the contract:

- **Public signatures unchanged**: `generate_calibration_board(color_mode: str, ...)` keeps its string parameter; `_generate_recipes(color_mode: str, ...)` keeps its string parameter; `detect_lut_color_mode(lut_path)` keeps its string return type. Internally these all funnel through `ColorMode`, but external callers see no change.
- **Tests first**: every phase begins by adding parity tests against the **current** behavior, and only then modifies implementation. The parity tests stay in the test suite afterward as regression guards.
- **Single responsibility per refactor**: each phase has one job. Phase 1 only unifies dispatch; it does NOT also extract the mesh generator, that is Phase 3. Mixing concerns in one PR is forbidden.
- **Independent revertability**: each phase's PR can be reverted without breaking subsequent phases that have not landed yet. Phase 2 builds on Phase 1, so reverting Phase 1 reverts Phase 2 transitively, but Phase 1 alone is revertable.

---

## 10. Cross-Phase Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Refactor introduces visual regression in calibration boards | M | H | Hash-based parity tests written FIRST per phase; CI gate on hash equality |
| Phase N depends on un-merged behavior from Phase N+1 | L | M | Each phase ships fully working in isolation; no forward dependencies |
| Subagent rushes Phase 2 before team's new method is specced | M | H | Phase 2 starts only after Phase 1 has 1-week soak AND team confirms ColorMode shape covers their new method's needs |
| Bug Report v2.1 not in production when Phase 1 starts | M | H | Hard gate: do not start Phase 1 until v2.1 PR is merged + 1 week of real reports observed |
| 5-Color Extended page-index semantic lost in unification | M | M | Page index is captured in `CalibrationParams`, not in `ColorMode`; tests cover both pages explicitly |
| `LUMINA_LUT_2468_MODE=merged` env override forgotten | L | M | Test exists in `test_color_mode_dispatch_unit.py` (Phase 1) and is preserved in every subsequent phase |
| Performance regression from new abstraction layers | L | M | Each phase runs `profile_stage3` + `check_perf_regression`; abort if regression > tolerance |
| Frontend breaks because color-mode strings change | L | H | No string changes: `display_names[0]` for each canonical mode is exactly the legacy primary string |
| Team's new calibration method does not fit `CalibrationMethod` Protocol | M | H | Phase 1 shipped + Phase 2 design pause: confirm protocol shape with team BEFORE Phase 2 PR |

---

## 11. Testing Strategy (general, all phases)

- Every public function touched gets a characterization test BEFORE modification (per `AGENTS.md` L48-51).
- Hash-based parity: pickle the deterministic byte output of `generate_*_board` for every existing mode at a fixed seed; the test fixture lives in `tests/fixtures/calibration_baselines/` and is updated only when behavior is intentionally changed (with a code review note).
- Property-based tests via Hypothesis on `ColorMode` lookups: every alias round-trips, every LUT size maps to a valid mode or `None`, no two modes claim the same `expected_lut_size`.
- Fuzzing on `detect_lut_color_mode` boundary sizes (1023, 1024, 1025, 1295, 1296, 1297, etc.) to lock in the boundary semantics.
- Performance baseline via `profile_stage3 --also-write-latest` before each phase; `check_perf_regression` after.
- Frontend integration: `cd frontend && npx vitest --run` to confirm the API contract (which returns mode strings) is unchanged.

---

## 12. Hand-off TL;DR for the GPT Subagent (Phase 1 only)

You are implementing **Phase 1 of 5** (the second of five phases — see §14 for Phase 0, which must ship first) as specified in §5 of this document.

**Read first**: `AGENTS.md` (especially Engineering Rules, Lossless Refactoring, Logging Governance, Tests sections) + this entire document, NOT just §5. Phase 2-4 sketches inform the shape of Phase 1's interfaces.

**Constraints (hard, do not violate)**:

1. **Lossless**: every existing public function signature unchanged, every existing test still passes unmodified.
2. **Tests first**: §5.3 tests are added in commit 1, BEFORE any source-code changes.
3. **Hash parity**: §5.3.4 hash-based test must pass for every existing color mode.
4. **No new INFO bucket events**; canonical 14/30 budget unchanged.
5. **Public API documentation** for `ColorMode` and new public behavior.
6. **UTF-8 encoding** on every modified file; mojibake check after each commit.
7. **Single responsibility**: Phase 1 only unifies dispatch. Do not also extract the mesh generator (that is Phase 3) and do not introduce `CalibrationMethod` Protocol (that is Phase 2).

**Branch**: cut from `dev-refactor` HEAD; branch name `refactor/color-mode-phase1`.

**Out of scope for Phase 1**:
- `_generate_voxel_mesh` is not touched.
- `core/vector_engine.py` is not touched.
- No new calibration method is added.
- No `CalibrationMethod` Protocol is introduced.
- No `BoardLayout` or `Renderer` types are introduced.

**If any item in this Phase 1 spec is ambiguous**: ask first; do not guess. Phase 1 sets the foundation; getting it wrong cascades into every later phase.

---

## 13. Estimated Effort (Phase 1)

- Tests: ~870 LOC (4 new test files). 6-8 hours.
- New file `core/color_modes.py`: ~250 LOC. 4-5 hours (most of the time is in correctly capturing the existing per-mode invariants).
- Modify `core/calibration.py`: ~150 LOC delta. 4-6 hours (high care: mesh output must be hash-identical).
- Modify `core/extractor.py`, `core/lut_merger.py`, `core/pipeline/processing_ops/lut_loader.py`, `core/pipeline/pipeline_utils.py`, `config.py`: ~370 LOC delta total. 6-8 hours.
- E2E manual verification + perf regression check + log quality gate: 1-2 hours.
- PR description / acceptance matrix: 30 minutes.

**Total**: ~22-30 hours of GPT-subagent time; comfortable as a single PR within 1-2 weeks of wall-clock time, including review.

---

## 14. Phase 0 Detailed Spec — Pipeline Hygiene

### 14.1 Phase 0 mission

Eliminate the over-coupling-disguised-as-decoupling identified in §2.6-2.9 by:

- Deleting zero-logic re-export shims in `core/pipeline/processing_ops/`.
- Extracting HTML/UI helpers from `core/pipeline/pipeline_utils.py` to `api/lut_html.py` (restoring `core/` layering invariant per `AGENTS.md`).
- Merging the duplicated logic between `s01_input_validation.py` and `p01_preview_validation.py` into a shared helper.
- Moving `_run_vector_branch` and `_run_vector_preview_branch` out of `coordinator.py` into a peer module `core/pipeline/vector_branch.py`.

Phase 0 introduces **no new abstractions** (those come in Phases 1-4). Every change is a mechanical refactor with parity tests written first per `AGENTS.md` L48-51.

### 14.2 Phase 0 deliverables (4 independent sub-PRs)

The four deliverables are **independent and parallelizable**; each is a separate PR that can ship without waiting for the others. All four must land before Phase 1 starts.

#### 14.2.1 Sub-PR A: Delete `processing_ops/` shims

- Delete `core/pipeline/processing_ops/hue_aware_matcher.py` (371 bytes, pure shim).
- Delete `core/pipeline/processing_ops/isolated_pixel_cleanup.py` (373 bytes, pure shim).
- Audit `bilateral_filter.py`, `median_filter.py`, `background_remover.py`, `wireframe_extractor.py`; delete any that are also pure shims, retain those with real local logic.
- Update every call site to import directly from the underlying `core/` module:
  ```python
  # before
  from core.pipeline.processing_ops.hue_aware_matcher import HueAwareColorMatcher
  # after
  from core.color_matching_hue_aware import HueAwareColorMatcher
  ```
- LOC: -2 to -8 files; net source LOC roughly unchanged.

#### 14.2.2 Sub-PR B: Split `pipeline_utils.py`

- Extract HTML grid generation (`generate_lut_grid_html`, `generate_lut_card_grid_html`, `generate_lut_color_dropdown_html`) → new `api/lut_html.py`.
- Extract click-selection helpers (`_build_selection_meta`, `_resolve_highlight_mask`, `_build_dual_recommendations`, `_resolve_click_selection_hexes`) → existing `api/routers/color_workstation.py` or new `api/color_workstation_helpers.py`.
- Update every call site to import from the new location.
- `core/pipeline/pipeline_utils.py` retains: color utilities (RGB↔hex, luminance), `generate_auto_height_map`, LUT metadata extraction, `detect_lut_color_mode`, `detect_image_type`, cache helpers.
- Optionally: also fold `core/pipeline/preview_color_utils.py` into `pipeline_utils.py`, OR split `pipeline_utils.py` further into `core/pipeline/color_utils.py` + `core/pipeline/lut_meta.py`. Defer this decision to sub-PR review if uncertain.
- Result: `pipeline_utils.py` shrinks from 36 KB to ~15-18 KB; `api/lut_html.py` ~200 LOC.
- LOC delta: ~-200 from `core/`, ~+200 to `api/`, net 0.

#### 14.2.3 Sub-PR C: Merge s01/p01 input validation

- New file `core/pipeline/_input_validation_common.py` (~200 LOC) with private helpers:
  - `_resolve_lut_path_or_error(ctx, *, error_prefix: str) -> tuple[str | None, str | None]`.
  - `_apply_material_archive_branch(ctx, *, log, event_prefix: str) -> dict | None` (the shared `material_archive` block; returns updated ctx fragment or None on error).
  - `_load_lut_palette(actual_lut_path, color_conf, *, event_prefix: str, log) -> tuple[list, dict]` (the shared Merged LUT palette extraction with try/except fallback).
  - `_clamp_quantize_colors(value: int) -> int`.
- `core/pipeline/s01_input_validation.py` retains: `is_svg_vector` detection, `separate_backing` + `backing_color_id` validation, writes to `_hifi_timings`, emits `s01_*` events. Reduces from 333 to ~150 LOC.
- `core/pipeline/p01_preview_validation.py` retains: writes to `_preview_timings`, emits `p01_*` events. Reduces from 234 to ~80 LOC.
- Helpers do NOT emit their own structured-logging events — they accept `event_prefix` and `log` parameters so the calling module emits with its own `s01_*` / `p01_*` prefix; this preserves the FROZEN canonical INFO budget.
- LOC delta: ~-200 net (eliminate duplication).

#### 14.2.4 Sub-PR D: Extract vector branch

- Move `_run_vector_preview_branch` (lines ~380-448) and `_run_vector_branch` (lines ~456-eof) from `core/pipeline/coordinator.py` to new `core/pipeline/vector_branch.py`.
- Move `_normalize_color_replacements_input` and any other helpers used only by the vector branch.
- `coordinator.py::run_raster_pipeline` and `coordinator.py::run_preview_pipeline` import from the new location.
- `coordinator.py` shrinks from 37 KB to ~25 KB; `vector_branch.py` becomes ~12 KB.
- This aligns with Phase 3's eventual Renderer-plugin abstraction — when Phase 3 lands, the file is replaced by a `VectorRenderer` subclass without touching `coordinator.py`.
- LOC delta: 0 (pure move).

### 14.3 New tests required (write FIRST per AGENTS.md L48-51)

For each sub-PR, write characterization tests against current behavior BEFORE modifying implementation.

#### Sub-PR A tests (~60 LOC)

- `tests/test_processing_ops_imports_unit.py`: assert that every public symbol previously importable from `core.pipeline.processing_ops.<shim>` is still importable from the new direct path post-refactor. Catches missed call sites.

#### Sub-PR B tests (~120 LOC)

- `tests/test_lut_html_unit.py`: characterization tests for HTML-grid and click-selection helpers. Run them against the **current** `pipeline_utils.py` location to capture exact byte-output of HTML strings; then re-run against the new `api/lut_html.py` location and assert the HTML is byte-identical.

#### Sub-PR C tests (~150 LOC)

- `tests/test_input_validation_parity_unit.py`:
  - For each combination of (`material_source` ∈ {"lut", "material_archive"}, `lut_path` format ∈ {.npy, .json, .msgpack, file-like}, `modeling_mode` ∈ {HIGH_FIDELITY, PIXEL_ART, VECTOR}, `color_mode` ∈ {"4-Color", "BW", "8-Color", "5-Color Extended", "6-Color (RYBWGK 1296)"}):
    - Build a synthetic ctx.
    - Run pre-refactor `s01.run(ctx)` and `p01.run(ctx)`; pickle both output ctx dicts (excluding timing keys).
    - After refactor, re-run and assert deep-equality with the pickled baselines.
- `tests/test_input_validation_event_parity_unit.py`: capture structured-logging event payloads (via a fake handler) from pre-refactor s01/p01 and assert post-refactor emits the same set of events.

#### Sub-PR D tests (~80 LOC)

- `tests/test_vector_branch_extraction_unit.py`:
  - Run a small synthetic SVG through `run_raster_pipeline` (vector branch) and `run_preview_pipeline` (vector preview branch) before refactor; pickle output ctx.
  - After refactor, re-run; assert output ctx is deep-equal.
  - Hash-based assertion on `result_tuple` bytes when present.

### 14.4 Logging governance compliance

- No new mutating endpoints introduced; no new `*_done` canary INFO required.
- All event names preserved verbatim (`s01_*`, `p01_*`, `pipeline_*`, etc.). The `_input_validation_common.py` helpers do NOT emit their own events — they accept `log` and `event_prefix` parameters so the calling module emits with its own prefix. This preserves the FROZEN canonical 14/30 INFO budget.
- Run `python scripts/log_quality_check.py --mode fast` after each sub-PR; INFO budget unchanged.
- Run `python -m pytest tests/test_logging_exception_governance_unit.py tests/test_structured_logging_unit.py tests/test_logger_unit.py -v` after each sub-PR; PASS unchanged.

### 14.5 Phase 0 acceptance matrix (per sub-PR)

For each of sub-PR A / B / C / D:

- [ ] All new parity tests in §14.3 pass.
- [ ] Existing test suite passes unmodified: `python -m pytest tests/ -v`.
- [ ] `cd frontend && npx vitest --run` — PASS.
- [ ] `python scripts/log_quality_check.py --mode fast` — INFO 14/30 PASS (UNCHANGED).
- [ ] `python scripts/log_quality_check.py --mode full` — PASS.
- [ ] No new `_log` / `*_log` / `request_*` / `status_*` bucket events introduced.
- [ ] Performance regression: `python scripts/profile_stage3.py --also-write-latest && python scripts/check_perf_regression.py` — within tolerance.
- [ ] No Chinese mojibake markers (`锟` / `鎷` / `鍙` / `涓`) in any modified file; `Get-Content -Encoding UTF8` clean per `AGENTS.md`.
- [ ] PR description includes a "before" / "after" file-tree diff for the relevant directory and a single-line scope statement ("Phase 0 sub-PR X: <summary>").

### 14.6 Phase 0 risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Missed import call site after deleting a `processing_ops/` shim | M | M | Sub-PR A tests in §14.3 enumerate every public symbol; CI grep gate `grep -rn "from core.pipeline.processing_ops" --include='*.py'` should match only the remaining (real) modules |
| HTML output byte-drift after relocating `generate_lut_grid_html` | L | M | Sub-PR B characterization tests pickle the exact HTML bytes against current behavior and assert post-refactor equality |
| s01/p01 behavioral drift after extracting common helper | M | H | Sub-PR C parity tests cover every (material_source, lut_format, modeling_mode, color_mode) combination |
| Event-name regression breaking the FROZEN log budget | L | H | Sub-PR C event-parity test asserts every `s01_*` / `p01_*` event name still emitted; `log_quality_check.py` gate run after each sub-PR |
| Vector branch extraction breaks SVG flow (raster or preview) | M | H | Sub-PR D pickle-based parity test on full vector pipeline output for raster + preview |
| Phase 0 work creates merge conflicts with Phase 1 work | L | M | Phase 0 ships strictly before Phase 1 starts; no parallel execution between phases |
| `preview_color_utils.py` consolidation accidentally rewrites color math | L | M | Optional; defer the consolidation to a later phase if uncertain |
| Removing a shim used by a test fixture | L | L | Sub-PR A test enumeration catches; if a fixture only-test-uses a shim path, update the fixture import |

### 14.7 Phase 0 hand-off TL;DR

You are implementing **Phase 0 of 5** as specified in §14 of this document. Phase 0 is hygiene: no new abstractions, no behavior change, mechanical refactor only.

**Read first**: `AGENTS.md` (Engineering Rules + Lossless Refactoring + Logging Governance + Tests sections) + this entire document, NOT just §14. Phases 1-4 inform why the §14 splits / extractions are shaped the way they are.

**Constraints (hard, do not violate)**:

1. **Lossless**: every existing public function signature unchanged; every existing test still passes unmodified.
2. **Tests first**: §14.3 tests are added in commit 1 of each sub-PR, BEFORE any source-code changes.
3. **No event-name drift**: every `s01_*` / `p01_*` / `pipeline_*` event still emitted post-refactor (Sub-PR C parity test).
4. **No INFO budget regression**: canonical 14/30 budget unchanged.
5. **No new abstractions**: Phase 0 only deletes / moves / inlines. Do NOT introduce `ColorMode`, `CalibrationMethod`, `BoardLayout`, or any other Phase 1-4 type.
6. **Public API documentation** for any new public behavior.
7. **UTF-8 encoding** on every modified file; mojibake check after each commit.

**Branch**: cut from `dev-refactor` HEAD; one branch per sub-PR (`refactor/pipeline-hygiene-A-shims`, `-B-pipeline-utils-split`, `-C-input-validation-merge`, `-D-vector-branch-extract`).

**Sub-PR ordering recommendation** (lowest-risk first):

1. Sub-PR A (delete shims) — ~10 minutes; immediately shippable; warms up the test infrastructure.
2. Sub-PR D (extract vector branch) — ~3-4 hours; pure file move with test coverage.
3. Sub-PR B (split `pipeline_utils.py`) — ~6-8 hours; touches `api/` layer.
4. Sub-PR C (merge s01/p01) — ~6-8 hours; highest-risk because it touches both pipelines simultaneously.

**Out of scope for Phase 0**:

- No behavioral changes anywhere.
- No `ColorMode` / `CalibrationMethod` / `BoardLayout` / `Renderer` types introduced.
- No `_generate_voxel_mesh` modifications.
- No `core/vector_engine.py` modifications.
- No new color modes added.
- No new logging events at INFO level.

**If any item in this Phase 0 spec is ambiguous**: ask first; do not guess. Phase 0 is the foundation that Phase 1 builds on; getting it wrong cascades.

### 14.8 Phase 0 estimated effort

| Activity | Sub-PR A | Sub-PR B | Sub-PR C | Sub-PR D |
|---|---|---|---|---|
| Tests (§14.3) | 1 hour | 2 hours | 3-4 hours | 1-2 hours |
| Implementation | 1-2 hours | 4-6 hours | 4-6 hours | 2-3 hours |
| Verification + perf gate + log gate | 30 min | 30 min | 30 min | 30 min |
| PR description + acceptance matrix | 15 min | 30 min | 30 min | 15 min |
| **Total per sub-PR** | **~3 hours** | **~7-9 hours** | **~8-11 hours** | **~4-6 hours** |

**Total Phase 0**: ~22-29 hours of GPT-subagent time across 4 PRs; ~1-2 weeks of wall-clock time including review (each sub-PR can be reviewed and merged independently, and they may execute in parallel by different subagents).

---

## 15. Long-term Vision (post-Phase 4)

After Phase 4, the architecture supports:

- Adding a new color mode = registering a new `ColorMode` instance + writing one recipe generator. ~50 LOC, no other changes.
- Adding a new calibration method = writing a `CalibrationMethod` subclass. ~150 LOC, works for every existing mode and every existing renderer immediately.
- Adding a new output format (10-layer / new SVG variant / future formats) = writing a `Renderer` subclass. ~100 LOC, works for every existing method and mode immediately.
- Replacing a calibration method with a better algorithm = swapping the subclass, no consumer changes.

The team's "new calibration method only works for 5 layers and voxel mode" pain disappears: any new method that respects `CalibrationMethod` and produces `BoardLayout` automatically works across the matrix.

---

*End of design document. Last updated: 2026-04-30 by Cascade — added Phase 0 (Pipeline Hygiene) per §2.6-2.10 + §14, revised §4 sequencing to require Phase 0 before Phase 1.*
