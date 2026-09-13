# SVG Compensation Product Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Ship the agreed source-SVG hole compensation as an optional 2D operation shared by preview and generation, reusing ChromaPrint3D geometry logic rather than adding backing or mesh repairs.

**Architecture:** Preserve faithful parsing and its uncompensated cache. After visible 2D regions are known, combine coverage once in Clipper2 and fill enclosed holes selected by physical area/width, using ChromaPrint3D's area and narrow-slit criteria. Assign added regions neighbouring exact source colours, then pass the same compensated geometry to existing matching, preview and generation. Keep settings in the existing API, store, recipe and diagnostics contracts. Do not adopt the measured-slower occlusion experiment or replace 2D-to-mesh/writer code.

**Tech Stack:** Existing C++17/Clipper2/pybind11 wheel; Python/NumPy and polygon containers; FastAPI; React/Zustand; pytest and Vitest.

## Scope and ownership

- Existing dirty parser work belongs to the ongoing task and must be preserved. Do not reset, replace, stage or commit it wholesale.
- `neroued_3mf` remains in use; no writer, matcher, recipe solver or mesh algorithm changes.
- Feature defaults are disabled. Public settings are `svg_hole_compensation_enabled=False`, `svg_hole_max_area_mm2=0.5`, `svg_hole_max_width_mm=0.1`. Zero disables the corresponding selection criterion. Finite non-negative values only; no arbitrary corpus-size or runner-speed gates.
- Compensation changes the SVG's derived visible 2D image, not source bytes. Added patches receive existing exact neighbouring colours and are identified as compensation, not original paint ops. Ordinary parsing keeps intentional holes unchanged when disabled.
- Reuse Chroma's hole/slit criteria, not its material-layer/base grouping. Select globally enclosed voids, including cross-colour holes; preserve islands within a void and independent outer shells. Do not expand external outlines or silently remove source-area components.

## Task 1 — Native geometry and colour adapter

**Files:** `native/lumina-svg-core/src/hole_compensation.cpp`, `native/lumina-svg-core/CMakeLists.txt`, native attribution files, `native/lumina-svg-core/tests/test_hole_compensation.py`, `core/svg_hole_compensation.py`, `tests/test_svg_hole_compensation_unit.py`.

- [x] Write red native tests: cross-colour 0.4×0.4 mm hole is selected at 0.5 mm²; 2×2 mm hole stays; nested islands remain; separate shells are not joined; area/width zero disables each rule; owned arrays survive input release.
- [x] Build separate `_lumina_svg_compensation` extension in the existing wheel; leave parser bindings/semantics unchanged. Native interface:

```python
holes, coverage = native.find_holes_mm(rings, max_hole_area_mm2, max_hole_width_mm)
```

`rings` are physical-mm float64 `(N,2)` arrays, shells CCW and holes CW. Return selected void polygons and filled coverage, each as owned `(shell, holes)` arrays. Use the existing upstream Clipper2 fixed-grid representation; preserve PolyTree nesting. Reuse the original `2 * area / perimeter` slit criterion and area threshold with attribution, without adding triangulation, offsets of the outer boundary, GEOS cleanup or component dust filters.

- [x] Write red adapter tests before implementation. Public contract:

```python
result = compensate_svg_regions(
    regions, silhouette=original_silhouette, scale_factor=0.5,
    max_hole_area_mm2=0.5, max_hole_width_mm=0.1,
)
assert result.regions[:len(regions)] == regions
assert result.filled_holes >= 0
assert result.added_area_mm2 >= 0
```

Result fields: `regions`, `silhouette`, `patches`, `filled_holes`, `added_area_mm2`, `elapsed_seconds`, `unprintable_fragments`. Keep source dictionaries and geometries unchanged. Convert coordinates to mm once and derived output back once. Use a batched spatial nearest query from each hole's interior representative point to original region geometries, deterministic draw-order/index tie-breaking. Preserve exact colour/RGBA, record contributing source index/paint ID, and do not copy recipes onto derived patches. No Python GEOS union/buffer/make_valid pass.

- [x] Run focused native and adapter tests; run package import smoke for the added extension. A missing optional native extension must be an actionable feature error when compensation is enabled, never a silent no-op. Disabled compensation must not require it.

## Task 2 — Shared preview/generation integration

**Files:** `core/vector_engine.py`, `core/pipeline/vector_branch.py`, `core/converter.py`, `api/schemas/converter.py`, `api/routers/converter*.py`, `api/workers/converter_workers.py`, relevant canonical pipeline configuration files and focused tests discovered from callers.

- [x] Add schema/transport and shared-analysis red tests. Check explicit false/default, native and legacy SVG inputs, cache reuse after changing strength, and a real cross-colour fixture where matched/preview and generated-source geometry both contain the patch.
- [x] Configure processor attributes from canonical request context in both material-archive and LUT construction paths. Thread the three scalar settings through existing preview/generation/large-format paths; keep APIs backward-compatible by adding optional keyword defaults.
- [x] Apply compensation immediately after restoring/storing the uncompensated parse cache and before colour configuration/matching:

```python
if self.svg_hole_compensation_enabled:
    compensated = compensate_svg_regions(
        clipped_shapes, silhouette=silhouette, scale_factor=scale_factor,
        max_hole_area_mm2=self.svg_hole_max_area_mm2,
        max_hole_width_mm=self.svg_hole_max_width_mm,
    )
    clipped_shapes = compensated.regions
    silhouette = compensated.silhouette
    stage_timings["svg_hole_compensation_s"] = compensated.elapsed_seconds
    stage_timings["svg_holes_filled"] = compensated.filled_holes
    stage_timings["svg_hole_added_area_mm2"] = compensated.added_area_mm2
```

- [x] Ensure generation does not reuse an analysis created with different compensation options. Keep pure parse-cache keys independent of compensation, but full preview/analysis compatibility keys must include it. Do not rewrite the old normalizer or add downstream repair logic.
- [x] Run affected backend suites and disabled-feature baseline tests.

## Task 3 — User controls and reproducibility

**Files:** existing converter API/types/store; a small SVG settings component adopted by the existing converter settings panel; `frontend/src/i18n/translations.ts`; existing recipe schema/export/import; `frontend/src/utils/advancedParamsBuilder.ts`; feedback schema/rendering; `frontend/src/data/announcements.ts`; corresponding tests.

- [x] Add red tests for toggle/threshold transport, preview invalidation, settings retention, share-card round trip, and diagnostics capture.
- [x] Expose an SVG-only toggle with physical area/width controls. Explain that compensation fills small holes/narrow enclosed gaps and may change details. Keep it off by default and use existing theme tokens/components.
- [x] Include the exact three public fields in both preview and generate payloads, persisted state, recipe serialization and diagnostics. Preserve old recipe compatibility through defaults. Reject enabled non-SVG requests explicitly where the normal workflow cannot apply compensation; do not silently ignore requested behavior.
- [x] Add bilingual user-visible announcement and run focused frontend tests through `python scripts/run_vitest.py run ...`; also type-check.

## Task 4 — Actual material verification and handoff

- [x] Verify the four user files from `/Volumes/personal_folder/小洞补偿/` at 220 mm. Do not hash, commit or overwrite user originals. Produce locally viewable compensated SVGs/crops to inspect actual colour ownership and holes, not backing coverage.
- [x] Re-run the available 508 anonymous corpus through the parser/compensator without a production shadow audit. Record area/holes/fragments, distinguish retained above-threshold holes from missing fills, and report total public-analysis/compensation time. Keep expensive repeated benchmarking bounded; do not mix mesh failures into parser results.
- [x] Run native differential, VectorAnalysis integration, package smoke, targeted converter/frontend, and logging fast gates. Independently review spec compliance then code quality and fix material findings.
- [x] Report what is truly implemented, tested and still external/not run. No automatic merge or force push. Preserve unrelated working changes; any publication must target a topic branch and include only intended work.

## Validation recorded on 2026-09-13

Implementation is isolated on the PR's current `cab4c5a0` baseline; unrelated dirty parser files were not folded into this change. The parser remains schema 4 / package 0.3.0. No matcher, recipe solver, mesh builder, 3MF writer or print-grid algorithm changed. The Chroma occlusion experiment that measured slower was not adopted.

- Native installed-wheel suite: 622 passed. Lumina adapter/differential/VectorAnalysis/workflow/compensation suites: 207 passed. Generation/puzzle/transport/packaging/logging suites: 328 passed. These are separate runs, not a de-duplicated total.
- Frontend feature/integration gate: 20 files, 286 tests passed; the main-agent recheck of the four most directly affected files passed 115 tests. TypeScript and Vite build passed.
- Product smoke passed: 170 backend tests, 168 frontend tests, lint zero errors (existing warnings only). Logging fast passed with 14 INFO, zero WARNING and zero ERROR records.
- A fresh macOS arm64 CPython 3.12 wheel targeting macOS 12.0 passed contents, installation and runtime checks. The production PyInstaller onefile built and executed both native-parser and compensation probes; its archive contains both extensions and the ChromaPrint3D license. Other desktop architectures require the new hosted CI run; previous-head CI is not evidence for this update.
- Independent geometry, specification and product-quality reviews approved. Review counterexamples were fixed and regression-tested: touching-island planar topology; material-archive and recipe-selection spatial caches; effective artwork width on model surfaces; continuous threshold changes and trailing-edge preview debounce.

### Real inputs (220 mm, default 0.5 mm² / 0.1 mm)

Four user inputs produced 94, 103, 15,269 and 24 compensation patches respectively. Each patch and final coverage is valid; original region dictionaries/geometries are preserved. The third input uses the existing legacy parser for unsupported paint order; the compensation works on its parsed 2D regions too. Before/after whole-image and local-crop renders were inspected. Source files were neither modified nor published.

The 508 anonymous inputs were freshly parsed at 220 mm / 0.02 mm tolerance using the released schema-4 native parser: all supported. Compensation was then measured over those cached regions, without a second parser or mesh run:

| Measurement | Result |
| --- | ---: |
| Raw source regions entering the parser adapter | 1,799,360 |
| Visible components entering compensation | 1,385,149 |
| Output components, including patches | 1,412,381 |
| Source-silhouette holes / compensated-silhouette holes | 14,540 / 324 |
| Selected empty components / new patches | 27,232 |
| Added patch area | 136.053132 mm² |
| Coverage-area change versus original float geometry | 136.001808 mm² |
| Invalid patches / invalid coverage / lost original object identity | 0 / 0 / 0 |
| Non-area output / additional compensation-stage unprintable fragments | 0 / 0 |
| Compensation median / p95 / maximum | 0.0755 / 0.5696 / 16.0962 s |
| Total compensation time for 508 | 103.1321 s |

These are compensation timings, not complete public VectorAnalysis or model-generation timings. Fresh parse observations used four concurrent processes and are not a serial performance comparison. Earlier parser-stage diagnostic fragments remain documented in the existing corpus audit; zero *additional compensation-stage* fragments does not mean the source SVGs contained no non-area fragments.

Hole counts are not a one-to-one subtraction: global coverage is built on the reused 100,000-units/mm Clipper grid, which can expose separate microscopic closed voids. Original floating-point paint objects are unchanged, but derived coverage and patch boundaries have that numerical precision. Against the same native-normalized baseline, independent real-input tests found no lost source coverage, no refilled painted islands and no external expansion. One complex input has approximately 4e-9 mm² of aggregate patch area-balance noise; this is not a print-grid cleanup step.

### Product limits

Compensation is deliberately an optional image edit, not a claim that a small hole is accidental. It fills globally enclosed voids selected by area **or** narrowness, including intentional holes that meet those settings; it does not close an open gap connected to the outside. Nearest-source color assignment is deterministic, not semantic reconstruction. Zero disables each criterion. Above-threshold holes and painted islands remain.

Unsupported document semantics retain the existing whole-document fallback. Compensation requested for incompatible non-SVG/non-vector workflows is rejected explicitly. Large-format raster fallback cannot silently discard requested compensation. No guarantee about downstream watertightness, printer resolution or slicer cleanup is made by this 2D feature.

### Integration with the current development branch

The first compensation commit was pushed normally as `a9cff287`. GitHub then reported a conflict with current `dev-refactor` (`9998a7aa`), so no PR CI run was created for that head. The sole manual merge conflict is the shared `api_server.py` entry point. The resolution preserves the development branch's managed bind, windowed streams, startup diagnostics, frozen multiprocessing and worker smoke, together with both SVG self-tests. Frozen helpers are diverted before argument parsing. Existing worker signature tests now cover all three optional compensation parameters and their backward-compatible defaults.

The merged candidate passed 809 targeted backend tests, 169 directly affected frontend/startup-settings tests, the 170-backend/168-frontend product smoke, frontend production build and logging fast gate. Independent startup-integration review approved it after 74 tests and real non-frozen CLI probes. The actual rebuilt PyInstaller onefile is checked separately before publication. Upstream runtime/wipe-tower changes are inherited unchanged through the normal merge, not reimplemented by this SVG feature.
