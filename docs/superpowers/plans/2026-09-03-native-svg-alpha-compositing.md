# Native SVG Alpha Compositing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend PR #588's parser-only native SVG fast path so solid fill/stroke alpha and isolated object/group opacity produce correct, non-overlapping two-dimensional SVG color regions without passing through the legacy Python occlusion/normalization chain.

**Architecture:** The pinned LunaSVG fork records exact source paint alpha and balanced isolated-group boundaries through the existing versioned public paint-command API. `lumina-svg-core` keeps the existing optimized opaque compositor, selects a spatially indexed Clipper2 cell compositor only for documents that actually contain partial alpha, and exports raw source geometry plus composited visible cells with authoritative high-precision straight sRGB RGBA and ragged source provenance. `core/native_svg_adapter.py` validates and forwards those arrays without GEOS union, repair, opacity flattening, material matching, or mesh work. The transparent SVG canvas remains transparent; downstream code—not the parser—owns any physical/matte interpretation.

**Tech Stack:** C++17, pinned LunaSVG recorder fork, PlutoVG, Clipper2 int64 geometry, pybind11, immutable NumPy arrays, Python 3.12, Shapely ragged construction, pytest.

**Scope guard:** Do not modify `MaterialVectorMatcher`, Lab/KDTree matching, recipe selection, `build_mesh`, triangulation, 3MF writers, print-grid snapping, or source-specific filters. Gradients, patterns, masks, filters, images, non-normal blend modes, unsupported paint order, complex clips, and non-sRGB `color-interpolation` remain whole-document fallback boundaries. Do not add alpha-specific fixed complexity thresholds that reject large but valid personal SVGs; retain only numeric, memory-overflow, and result-schema correctness checks.

---

### Task 1: Freeze source-alpha and isolated-group recorder semantics

**Files:**
- Modify: `native/lumina-svg-core/tests/test_recorder_contract.py`
- Modify: `native/lumina-svg-core/patches/lunasvg-paint-recorder.patch`
- Modify in pinned patch source: `include/lunasvg.h`
- Modify in pinned patch source: `source/svglayoutstate.h`
- Modify in pinned patch source: `source/svglayoutstate.cpp`
- Modify in pinned patch source: `source/svgelement.h`
- Modify in pinned patch source: `source/svgelement.cpp`
- Modify in pinned patch source: `source/svgrenderstate.h`
- Modify in pinned patch source: `source/svgrenderstate.cpp`
- Modify in pinned patch source: `source/svgparser.cpp`

- [x] **Step 1: Add failing recorder-only contract tests**

Add tests that require:

```python
assert result.status == "supported"
assert command.paint_opacity == pytest.approx(0.99999999, rel=0, abs=1e-15)
assert command.rgba == (1, 2, 3, 255)  # compatibility bytes only
```

Cover `rgba(...)`, 4/8-digit hex alpha, `currentColor`, `fill-opacity`, `stroke-opacity`, percentages, clamping, alpha zero, alpha one, and values near both endpoints. Require effective paint alpha to be the product of color alpha and fill/stroke opacity without using the already-quantized byte alpha as the authority.

Add balanced command-stream tests for opacity on a leaf with fill+stroke, a container with overlapping children, nested groups, a group combined with `clip-path`, and `<use>`. Require `GroupBegin(opacity)` before all group paints and `GroupEnd` after them. A zero-opacity group records no contributing paint; opacity one emits no unnecessary boundary.

Add fallback tests for `color-interpolation="linearRGB"`/`auto`, while default or explicit `sRGB` remains supported. Preserve all existing fallbacks for masks, filters, gradients/patterns, blend modes, and complex clips.

Do not change the `analyze_svg*` partial-alpha fallback assertions in this task: the kernel remains intentionally RED until Task 3. Include object/group opacity values `1e-50` and `0.99999999` so the recorder proves it does not collapse near-endpoint source values through a float.

- [x] **Step 2: Build the unchanged baseline and verify RED**

Run:

```bash
/private/tmp/pr588-alpha-venv/bin/python -m pip wheel native/lumina-svg-core -w /private/tmp/pr588-alpha-red-dist
/private/tmp/pr588-alpha-venv/bin/python -m pip install --force-reinstall /private/tmp/pr588-alpha-red-dist/lumina_svg_core-*.whl
/private/tmp/pr588-alpha-venv/bin/python -m pytest native/lumina-svg-core/tests/test_recorder_contract.py -q
```

Expected: the new recorder tests fail because precise alpha is absent and partial group opacity still returns `unsupported_partial_alpha`; pre-existing recorder tests remain green. The unchanged analyze tests continue to assert whole-document fallback until Task 3.

- [x] **Step 3: Preserve resolved source alpha before byte quantization**

Extend `SVGLayoutState` and `SVGElement` with exact `double` recording values for color alpha, fill alpha, fill opacity, stroke alpha, stroke opacity, and object opacity. Parse numeric/percentage alpha with checked finite double conversion, clamp per SVG rules, and preserve inheritance/currentColor semantics. Keep LunaSVG's normal rendering floats untouched; the extra values exist only for the narrow recorder contract.

Expose `PaintCommand::paint_opacity` as a finite clamped double. Keep `rgba[3]` only as a compatibility byte; do not reconstruct `paint_opacity` from it.

- [x] **Step 4: Emit balanced isolated opacity groups**

For `0 < opacity < 1`, emit `GroupBegin` carrying exact `group_opacity`, then the element/container's fill, stroke, marker/children command stream, then `GroupEnd`. Maintain nesting, source identity, and clip ordering. Continue suppressing exactly zero-opacity subtrees. Reject an unbalanced stream at the recorder boundary.

- [x] **Step 5: Fail closed on unimplemented compositing color spaces**

Allow absent/default and explicit `sRGB`. Return `unsupported_color_interpolation` for `linearRGB`, `auto`, or another value whose blend result is not implemented. Do not silently perform sRGB arithmetic for a requested linear space.

- [x] **Step 6: Regenerate the pinned fork patch and verify the recorder GREEN**

Regenerate `lunasvg-paint-recorder.patch` from the exact pinned LunaSVG checkout, configure/build from an empty directory, install the wheel, and rerun `test_recorder_contract.py`. Verify the committed patch applies exactly to LunaSVG `59690a23981489acc3f73b8db229ef57bb69c544`. Confirm the existing analyze-level alpha tests are still green only because they retain the temporary fallback expectation.

### Task 2: Version an alpha-safe immutable native result contract

**Files:**
- Modify: `native/lumina-svg-core/include/lumina_svg_core/paint_command.h`
- Modify: `native/lumina-svg-core/include/lumina_svg_core/result.h`
- Modify: `native/lumina-svg-core/src/result.cpp`
- Modify: `native/lumina-svg-core/src/bindings.cpp`
- Modify: `native/lumina-svg-core/python/lumina_svg_core/__init__.py`
- Modify: `native/lumina-svg-core/CMakeLists.txt`
- Modify: `native/lumina-svg-core/pyproject.toml`
- Modify: `native/lumina-svg-core/tests/test_result_schema.py`
- Modify: `native/lumina-svg-core/tests/test_distribution_contract.py`
- Modify: `requirements-native-svg.txt`
- Modify: `tests/test_native_svg_packaging_contract_unit.py`

- [x] **Step 1: Write failing schema, dtype, immutability, and lifetime tests**

Bump the package to `0.3.0` and result/paint-command schema to `4`. Require every raw and visible geometry to expose:

- `rgba_f64`: C-contiguous, immutable `float64[N,4]`, straight/unassociated sRGB values in `[0,1]`;
- existing `rgba`: compatibility `uint8[N,4]`, deterministically rounded only at export;
- `contributor_offsets`: immutable `uint64[N+1]`;
- contributor draw/source/kind arrays: immutable `int32[K]`;
- `contributor_weights`: immutable `float64[K]`, the bottom-to-top premultiplied contribution weights whose sum equals output alpha within numerical tolerance.

For raw geometries require one contributor of weight `paint_opacity`; for visible cells allow multiple contributors. A derived cell with multiple contributors uses `SourceKind::Composite`, `source_index=-1`, `draw_index=-1`, and no fabricated single `native_paint_id`; its complete provenance is authoritative. Require contributor paint IDs to resolve to source-paint metadata, remain in bottom-to-top draw order, sum to output alpha, and reconstruct visible premultiplied sRGB within a fixed floating tolerance. Require owner lifetime after `NativeResult` deletion. Add exact-alpha fields to unprintable-fragment metadata as well.

- [x] **Step 2: Run the result tests and verify RED**

Expected: schema/version and every new array assertion fail on the installed 0.2.0/schema-3 wheel.

- [x] **Step 3: Implement checked structure-of-arrays storage and bindings**

Add the arrays with overflow-safe append helpers and layout validation. Define external semantics in comments and README: transparent initial backdrop, source-over, normal blend, sRGB component arithmetic, straight `rgba_f64` output, and contributor weights in premultiplied color space. Preserve zero-copy NumPy views and shared C++ owner lifetime.

- [x] **Step 4: Run schema/distribution tests and verify GREEN**

Run the tests both normally and with `PYTHONMALLOC=debug`; verify all arrays are read-only and no schema-3 consumer can accept schema 4 accidentally.

### Task 3: Implement source-over vector cell compositing

**Files:**
- Modify: `native/lumina-svg-core/src/geometry_kernel.cpp`
- Modify: `native/lumina-svg-core/src/complexity_budget.h`
- Modify: `native/lumina-svg-core/tests/test_paint_semantics.py`
- Modify: `native/lumina-svg-core/tests/test_fill_geometry.py`
- Modify: `native/lumina-svg-core/tests/test_complexity_limits.py`

- [x] **Step 1: Write failing geometry-oracle tests**

Use exact rectangles so area/color expectations do not depend on raster antialiasing. Cover:

1. 50% blue over opaque red: red-only, blue-only, and overlap cells; overlap straight sRGB `(1/3,0,2/3,0.75)` when both layers are 50%, or `(0.5,0,0.5,1)` when the base is opaque.
2. A partial top paint does not erase the lower paint.
3. Partial paint on transparent root retains source RGB and partial alpha; no implicit white matte.
4. Fill and stroke under element opacity are first composited together and opacity is applied once, including opacity values `1e-50` and `0.99999999`.
5. Two overlapping children under group opacity are composited internally before the group alpha is applied; assert the overlap differs from multiplying opacity into each child.
6. Nested opacity groups, even-odd holes, clips, disconnected components, and draw/source provenance.
7. Alpha-zero paints do not occlude or enter polygon collections; non-area fragments remain diagnostic-only and do not fail valid siblings.

Assert geometry equality/area, authoritative `rgba_f64`, deterministic rounded bytes, contributor IDs/order/weights, component and hole counts, and silhouette union.

- [x] **Step 2: Run the new tests and verify RED**

Expected: current kernel returns `unsupported_partial_alpha` and ignores group commands.

- [x] **Step 3: Replay clips and opacity groups into an explicit program tree**

Keep local stroke expansion, transform, flattening, quantization, fill-rule normalization, and active clip application unchanged. Build a checked nested program of normalized paints/groups. Reject stack imbalance and consume command/group/depth budgets before allocation. Raw output remains one normalized geometry per non-empty source paint with exact source metadata.

- [x] **Step 4: Preserve the opaque fast path**

If all effective paint/group alpha values are exactly one, call the existing indexed reverse-occlusion compositor byte-for-byte. This keeps the 508-document opaque majority and current performance behavior unchanged.

- [x] **Step 5: Add the alpha cell compositor**

Represent each surface as disjoint normalized Clipper2 paths with premultiplied double sRGB, alpha, bounds, and ordered contributor entries. For every new source cell, partition only intersecting destination cells into destination-only, overlap, and source-only areas using checked `Difference`/`Intersection`; apply normal source-over:

```text
out_a   = src_a + dst_a * (1 - src_a)
out_rgb_premul = src_rgb * src_a + dst_rgb_premul * (1 - src_a)
```

Scale a completed isolated group surface—including all contributor weights—by the group's opacity exactly once, then composite it onto its parent. Merge only geometrically compatible cells whose high-precision RGBA and full provenance are identical. Never flatten against white or another implicit background.

- [x] **Step 6: Avoid arbitrary alpha-specific rejection limits**

Do not cap compositor cells, pair operations, or contributor entries with policy thresholds. Use spatial indexing and tiling for ordinary performance, and keep only checked container growth/overflow plus structural result validation. Large valid documents must be allowed to finish instead of being classified as hostile input.

- [x] **Step 7: Export visible cells and relax only obsolete census assumptions**

Allow visible geometry count to exceed raw paint count because an arrangement can split a paint into several cells. Retain all structural offset/hole/closure validations. Build silhouette from the union of every positive-alpha cell, independent of color/provenance. Do not put empty, line, point, or collapsed paths into any polygon collection.

- [x] **Step 8: Run native geometry and large-valid-document tests and verify GREEN**

Run paint semantics, fill geometry, result schema, complexity, precision, stroke, clip, and recorder tests. Repeat the alpha suite twice and compare serialized fingerprints for deterministic ordering.

### Task 4: Preserve alpha/provenance through the thin Lumina adapter

**Files:**
- Modify: `core/native_svg_adapter.py`
- Modify: `tests/test_native_svg_adapter_unit.py`
- Modify: `tests/test_vector_native_svg_selection_unit.py`
- Modify: `tests/test_native_svg_differential_unit.py`
- Modify: `tests/test_native_svg_fallback_properties.py`

- [x] **Step 1: Write failing adapter-contract tests**

Require schema 4 arrays to be validated before use. `shape_data` must retain source `rgba`, `rgba_f64`, effective alpha, stable draw/source/paint identity, and one-source provenance. `clipped_shapes` must retain composited `rgba`, authoritative `rgba_f64`, final alpha, and complete ordered `native_contributors` with weights. A single-source cell may retain its paint identity; a multi-source composite cell must expose `source_kind="composite"`, `native_source_index=-1`, `native_draw_order=-1`, and `native_paint_id=None` rather than inventing ownership.

Monkeypatch every legacy parse/occlusion/normalization entry to fail and prove a native partial-alpha document reaches `VectorAnalysis` without GEOS union, `make_valid`, buffer, or per-ring repair. Require a malformed provenance layout to raise `NativeSvgInternalError`, never silent partial success.

- [x] **Step 2: Run adapter and selection tests and verify RED**

Expected: schema 3 rejects the fake schema 4 result or loses alpha/provenance.

- [x] **Step 3: Implement validation and metadata forwarding only**

Update `NATIVE_RESULT_SCHEMA_VERSION`, validate exact dtype/shape/offset/range/sum invariants, and attach high-precision RGBA/provenance to dictionaries. Keep Shapely usage limited to the existing bulk ragged constructor. Do not add matching, recipe, physical-opacity policy, or geometry repair.

- [x] **Step 4: Verify adapter and VectorAnalysis integration GREEN**

Run focused adapter/selection/differential tests. Explicitly verify the old `_normalize_contours_many` buffer chain is never called on a native result and that valid components/holes survive.

### Task 5: Validate the 508 anonymous SVG corpus and package gates

**Files:**
- Modify: `native/lumina-svg-core/tools/corpus_audit.py`
- Modify: `scripts/benchmark_native_svg_analysis.py`
- Modify: `native/lumina-svg-core/tests/test_corpus_audit.py`
- Modify: `tests/test_native_svg_benchmark_contract_unit.py`
- Modify: `progress/native-svg-508-corpus-audit.json`
- Modify: `docs/native-svg-fast-path-validation.md`
- Modify: `native/lumina-svg-core/README.md`
- Modify: packaging/golden files only when a demonstrated schema-version expectation requires it

- [x] **Step 1: Write failing audit and benchmark contract tests**

Extend `test_corpus_audit.py` first to require all new anonymous count/area/fragment fields, an explicitly process-global RSS label, and the absence of source path/hash fields. Extend `test_native_svg_benchmark_contract_unit.py` first to require `rgba_f64` plus provenance in the analysis fingerprint and a fresh isolated child process for attributable peak RSS. Add a tiny transparent fixture/reference pair that fixes the raster-oracle transparent canvas, interior-pixel comparison, and tolerance-derived boundary exclusion rule.

Run both tests and observe failures against the unchanged tools before editing either production script.

- [x] **Step 2: Extend anonymous native-kernel audit output without source validation**

Do not hash, copy, or commit source SVG files. For each anonymous case record input paint count, raw/output color-region counts, raw/output component counts, hole counts, raw/visible/silhouette areas, area deltas with units, unprintable fragment count and reason histogram, support/fallback reason, and native elapsed time. Never record source paths or source-content hashes. Because one long-lived process exposes only a cumulative `ru_maxrss`, report one clearly labelled process-global peak RSS for the 508 native-kernel run rather than falsely presenting per-document RSS.

- [x] **Step 3: Build/install from a clean source tree and run focused gates**

Build a fresh wheel from the committed dependency patches, install into an empty Python 3.12 environment, run wheel verification and the full standalone native suite. Run Lumina adapter, selection, differential, VectorAnalysis integration, and packaging-contract tests.

- [x] **Step 4: Run the 508 corpus and classify every change**

Run all 508 anonymous SVGs. Compare each case with the previous report. The reduced exact-rectangle tests from Task 3 are the analytical color/area oracle. For each of the 31 former alpha fallbacks that becomes supported, render both the original SVG and the exported visible cells on a transparent sRGB canvas with the pinned LunaSVG renderer at a declared scale; compare interior pixels exactly or within one byte, exclude only a boundary band derived from the single physical tolerance, and record maximum/interior error plus coverage disagreement. Documents with another unsupported semantic must retain a precise whole-document fallback. No source-specific allowlist/filter is permitted.

- [x] **Step 5: Record public-entry performance and RSS separately**

Extend `scripts/benchmark_native_svg_analysis.py` to include the new alpha metadata in its deterministic fingerprint and to benchmark public-entry-to-complete-`VectorAnalysis` separately from the native-kernel corpus audit. Run each measured case in a fresh subprocess (or use the script's existing isolated child mode) so peak RSS is attributable to that case. Verify the opaque reference does not materially regress and measure at least one alpha-heavy case. Keep the existing one-second reference gate where its fixture/hardware contract applies; do not weaken it.

Rerun `test_corpus_audit.py` and `test_native_svg_benchmark_contract_unit.py` and require GREEN before generating either report.

- [ ] **Step 6: Run product packaging gates without changing 3D code**

Run smoke/logging-fast, wheel verification, native CLI probes, and the existing GLB/3MF product regression tests only as consumers. A downstream physicalization failure must be reported under its owning layer and must not be “fixed” in this parser PR.

### Task 6: Independent review, commit, push, and CI

**Files:**
- All files changed above

- [x] **Step 1: Run a clean independent code/reality review**

Give the reviewer exact branch/head, W3C compositing contract, the new alpha cases, corpus report, performance/RSS evidence, and strict parser-only scope. Resolve every Critical/Important finding with another RED/GREEN loop.

- [x] **Step 2: Verify repository hygiene and scope**

Run `git diff --check`, inspect every changed path, confirm no user SVG/source path/hash or generated build artifact is tracked, and confirm no matcher/recipe/mesh/3MF implementation file changed.

- [x] **Step 3: Commit and ordinary-push the PR branch**

Use Conventional Commits, then push normally with:

```bash
git push origin HEAD:MOVIBALE/feat/native-svg-core
```

Never force-push and never merge PR #588.

- [ ] **Step 4: Watch CI to a terminal result**

Distinguish code/test/build failures from repository Actions artifact-quota failures. Fix actual failures through TDD and ordinary-push. Do not weaken tests or alter code for an external artifact-storage quota error.
