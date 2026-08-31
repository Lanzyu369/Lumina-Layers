# Lumina Native SVG Fast Path Integration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make supported SVG documents use `lumina-svg-core` by default at Lumina's public `VectorAnalysis` boundary, with deterministic whole-document fallback and no production shadow audit.

**Architecture:** `core/native_svg_adapter.py` is the only Lumina-to-library boundary. It bulk-converts the native ragged arrays into Shapely objects, preserves normalized SVG user units and the existing `VectorAnalysis` fields, and returns structured fallback/error diagnostics; `VectorProcessor.analyze_svg` chooses native or legacy exactly once, while #585's `LayeredCoordinateDomain` remains the only downstream coordinate authority.

**Tech Stack:** Python 3.12, NumPy, Shapely 2 ragged arrays, existing `VectorProcessor`/`VectorAnalysis`, pytest/Hypothesis, trimesh/neroued-3mf, PyInstaller, Docker, GitHub Actions.

---

### Task 1: Thin adapter and bulk ragged-array conversion

**Files:**
- Create: `core/native_svg_adapter.py`
- Create: `tests/test_native_svg_adapter_unit.py`
- Modify: `core/errors.py`

- [ ] **Step 1: Write failing adapter contract tests**

```python
def test_supported_result_preserves_lumina_coordinate_contract(fake_native_result) -> None:
    result = analyze_native_svg("fixture.svg", target_width_mm=20.0, tolerance_mm=0.02)
    assert result.bbox == (10.0, 20.0, 100.0, 50.0)
    assert result.scale_factor == pytest.approx(0.2)
    assert result.shape_data[0]["poly"].bounds == pytest.approx((0.0, 0.0, 100.0, 50.0))
    assert result.geometry_backend == "native"

def test_adapter_calls_one_vectorized_shapely_constructor(monkeypatch, fake_native_result) -> None:
    calls = []
    expected = np.asarray([MultiPolygon([box(0, 0, 1, 1)])], dtype=object)
    monkeypatch.setattr(
        shapely,
        "from_ragged_array",
        lambda *args, **kwargs: calls.append(args) or expected,
    )
    analyze_native_svg("fixture.svg", 20.0, 0.02)
    assert len(calls) == 3
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python3 -m pytest tests/test_native_svg_adapter_unit.py -q`

Expected: FAIL because the adapter does not exist.

- [ ] **Step 3: Implement stable adapter outcomes**

Add `NativeSvgGeometry`, `NativeSvgFallback`, `NativeSvgInvalidError`, and `NativeSvgInternalError`. Map native `unsupported_feature` and `external_resource_unavailable` to a whole-document fallback object, `invalid_svg` to the existing invalid-SVG `ValueError` behavior, `numeric_range_error` to a deterministic core validation error, and `internal_error` to a core processing error with the native version.

- [ ] **Step 4: Convert native collections without Python coordinate loops**

Convert `int64` coordinates to `float64` once using `grid_to_svg`, then call `shapely.from_ragged_array(GeometryType.MULTIPOLYGON, ...)` once per raw/visible/silhouette collection. Build per-shape dictionaries only after geometry construction. Do not call union, `make_valid`, buffer, simplify, or per-ring repair.

- [ ] **Step 5: Run adapter tests and verify GREEN**

Run: `python3 -m pytest tests/test_native_svg_adapter_unit.py -q`

Expected: PASS for dtypes, offsets, lifetime, bounds, colors, draw order, and all error mappings.

- [ ] **Step 6: Commit the adapter**

```bash
git add core/native_svg_adapter.py core/errors.py tests/test_native_svg_adapter_unit.py
git commit -m "feat(vector): adapt native SVG results to VectorAnalysis"
```

### Task 2: Native-by-default selection, cache identity, and lightweight telemetry

**Files:**
- Modify: `core/vector_engine.py`
- Modify: `config.py`
- Create: `tests/test_vector_native_svg_selection_unit.py`
- Modify: `tests/test_vector_preview_timings_unit.py`

- [ ] **Step 1: Write failing selection/fallback tests**

```python
def test_supported_document_uses_native_without_legacy_parse(monkeypatch, processor) -> None:
    monkeypatch.setattr(
        native_svg_adapter,
        "analyze_native_svg",
        lambda **_: native_geometry_fixture(),
    )
    monkeypatch.setattr(processor, "_parse_svg", lambda *_: pytest.fail("legacy parser ran"))
    monkeypatch.setattr(processor, "_clip_occlusion", lambda *_: pytest.fail("legacy GEOS clip ran"))
    analysis = processor.analyze_svg(FIXTURE, 20.0)
    assert analysis.stage_timings["geometry_backend"] == "native"

def test_unsupported_document_runs_one_complete_legacy_path(monkeypatch, processor) -> None:
    monkeypatch.setattr(native_svg_adapter, "analyze_native_svg", lambda **_: NativeSvgFallback("unsupported_marker"))
    legacy_calls = []
    monkeypatch.setattr(
        processor,
        "_parse_svg",
        lambda *args: legacy_calls.append(args) or legacy_geometry_fixture(),
    )
    analysis = processor.analyze_svg(FIXTURE, 20.0)
    assert len(legacy_calls) == 1
    assert analysis.stage_timings["native_fallback_reason"] == "unsupported_marker"
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python3 -m pytest tests/test_vector_native_svg_selection_unit.py -q`

Expected: FAIL because `VectorProcessor` always uses legacy parse/clip.

- [ ] **Step 3: Select one geometry backend at the parse/clip convergence point**

Native success supplies `shape_data`, `clipped_shapes`, `silhouette`, `scale_factor`, and `bbox` directly and skips `_parse_svg`, `_clip_occlusion`, `_postprocess_clipped_shapes`, disconnected repair, and every second GEOS union/make-valid operation. Fallback executes the unchanged legacy branch once. Preserve color matching, material archive matching, cache behavior, GLB/3MF consumers, and `LayeredCoordinateDomain` construction.

- [ ] **Step 4: Version the parse/clip cache key**

Include `("native", lumina_svg_core.__version__, schema_version)` or `("legacy", legacy_schema_version)` in the key so cached legacy geometry cannot masquerade as native output and package upgrades cannot reuse stale arrays.

- [ ] **Step 5: Add lightweight timings and reason codes**

Record `native_svg_s`, `native_result_conversion_s`, `geometry_backend`, and `native_fallback_reason` in existing timing diagnostics. Emit one structured debug success event or one structured fallback event; do not invoke a shadow parser or topology audit in production.

- [ ] **Step 6: Run focused tests and verify GREEN**

Run: `python3 -m pytest tests/test_vector_native_svg_selection_unit.py tests/test_vector_preview_timings_unit.py tests/test_vector_engine_part2_5_unit.py -q`

Expected: new tests PASS; the two known baseline INFO-vs-DEBUG stroke assertions remain classified separately and unchanged.

- [ ] **Step 7: Commit native selection**

```bash
git add core/vector_engine.py config.py tests/test_vector_native_svg_selection_unit.py tests/test_vector_preview_timings_unit.py
git commit -m "feat(vector): use native SVG geometry with whole-document fallback"
```

### Task 3: Lumina differential corpus and unsupported-semantics guard

**Files:**
- Create: `tests/fixtures/native_svg/`
- Create: `tests/fixtures/native_svg/golden_manifest.json`
- Create: `tests/test_native_svg_differential_unit.py`
- Create: `tests/test_native_svg_fallback_properties.py`

- [ ] **Step 1: Write failing differential tests**

For supported fixtures, call native and the preserved legacy reference explicitly, then compare ordered source colors, visible color identities, components, holes, total/per-color area, and symmetric-difference bounded by the one physical tolerance. The comparison is test-only.

```python
@pytest.mark.parametrize("case", supported_cases())
def test_native_matches_legacy_reference(case, processor) -> None:
    native = analyze_geometry(processor, case.path, backend="native")
    legacy = analyze_geometry(processor, case.path, backend="legacy")
    assert fingerprint_identity(native) == fingerprint_identity(legacy)
    assert symmetric_difference_mm2(native, legacy) <= case.max_difference_mm2
```

- [ ] **Step 2: Write property tests for fail-closed semantics**

Generate partial alpha, group opacity, vector-effect, markers, paint-order, masks, patterns, gradients, text, image, filter, script, animation, external href, unknown elements, unknown attributes, and unknown CSS declarations. Assert native returns no geometry and legacy is invoked exactly once.

- [ ] **Step 3: Run tests and verify RED**

Run: `python3 -m pytest tests/test_native_svg_differential_unit.py tests/test_native_svg_fallback_properties.py -q`

Expected: FAIL on any missing fallback or parity case.

- [ ] **Step 4: Fix only demonstrated recorder/kernel/adapter gaps through TDD**

Each failure gets one reduced fixture and one root-cause note before implementation. Do not loosen the physical tolerance or delete a component/hole to make parity pass.

- [ ] **Step 5: Run tests twice and verify GREEN/stability**

Run both files twice. Expected: identical fingerprints and no intermittent ordering.

- [ ] **Step 6: Commit the Lumina golden corpus**

```bash
git add tests/fixtures/native_svg tests/test_native_svg_differential_unit.py tests/test_native_svg_fallback_properties.py
git commit -m "test(vector): cover native SVG parity and fail-closed fallback"
```

### Task 4: Existing workflows, creative modes, GLB, 3MF, and slicer identity

**Files:**
- Create: `tests/test_native_svg_workflow_integration.py`
- Modify only if a demonstrated regression requires it: `core/vector_large_format.py`
- Modify only if a demonstrated regression requires it: `core/pipeline/vector_branch.py`
- Modify only if a demonstrated regression requires it: `core/model_surface/`
- Modify only if a demonstrated regression requires it: `core/mesh_writer_domain.py`

- [ ] **Step 1: Write failing end-to-end workflow cases**

Run native analysis through single/double-sided mesh generation, outline, separate backing, coating, puzzle, keychain, fridge magnet, material archive, recipe override, large-format tiling, GLB preview, and Bambu/Orca 3MF writer fixtures. Assert material identity, independent shells/holes, auxiliary meshes, coordinate domain, and source session-independent downloads remain unchanged.

- [ ] **Step 2: Run the integration test and verify RED for uncovered workflows**

Run: `python3 -m pytest tests/test_native_svg_workflow_integration.py -q`

Expected: individual uncovered cases fail with a concrete contract mismatch, not a blanket xfail.

- [ ] **Step 3: Fix at the earliest owning boundary**

Geometry parity issues belong in `lumina-svg-core`; coordinate conversion belongs in the adapter; material identity belongs in existing VectorAnalysis metadata; downstream mesh/writer changes are allowed only when the current consumer made an undocumented legacy-parser assumption.

- [ ] **Step 4: Run downstream regression suites**

Run:

```bash
python3 -m pytest \
  tests/test_vector_large_format_unit.py \
  tests/test_vector_recipe_override_unit.py \
  tests/test_pipeline_vector_material_archive_unit.py \
  tests/test_vector_glb_v2_parity_unit.py \
  tests/test_vector_engine_mesh_weld_unit.py \
  tests/test_bambu_3mf_cross_slicer_cover_unit.py -q
```

Expected: PASS with native fixtures exercising the same consumers.

- [ ] **Step 5: Commit workflow compatibility**

```bash
git add tests/test_native_svg_workflow_integration.py core tests
git commit -m "test(vector): verify native SVG product workflows"
```

### Task 5: Runtime dependency, Docker, and PyInstaller onefile probe

**Files:**
- Create: `requirements-native-svg.txt`
- Modify: `requirements.txt`
- Modify: `Dockerfile`
- Modify: `lumina_studio.spec`
- Modify: `scripts/build_desktop.py`
- Modify: `api_server.py`
- Create: `tests/test_native_svg_packaging_contract_unit.py`
- Modify: `tests/test_desktop_build_contract_unit.py`

- [ ] **Step 1: Write failing dependency and frozen-runtime tests**

Assert the local workspace dependency is exactly version 0.1.0, production Python is 3.12, PyInstaller collects `lumina_svg_core` and `_lumina_svg_core`, desktop dependency checks fail if it is absent, and `api_server.py --native-svg-self-test <small.svg>` analyzes actual geometry and prints a stable JSON fingerprint before exiting zero.

- [ ] **Step 2: Run packaging tests and verify RED**

Run: `python3 -m pytest tests/test_native_svg_packaging_contract_unit.py tests/test_desktop_build_contract_unit.py -q`

Expected: FAIL because native packaging is not declared.

- [ ] **Step 3: Wire the workspace package without pretending it is published**

`requirements-native-svg.txt` points to `./native/lumina-svg-core` and documents the replacement boundary `lumina-svg-core==0.1.0` after the external repository release. Docker copies the native source before `pip install` and uses Python 3.12. PyInstaller treats the compiled package as required, not optional.

- [ ] **Step 4: Add a real frozen probe**

The probe calls the Lumina adapter on a supplied SVG, requires `geometry_backend == "native"`, verifies non-empty raw/visible/silhouette collections and deterministic fingerprint, then exits. A bare import is insufficient.

- [ ] **Step 5: Run packaging tests and local onefile build where supported**

Run packaging tests on macOS. Run the Windows onefile build in GitHub Actions and execute the probe from the generated `.exe`, which validates `_MEIPASS` extraction.

- [ ] **Step 6: Commit packaging integration**

```bash
git add requirements-native-svg.txt requirements.txt Dockerfile lumina_studio.spec scripts/build_desktop.py api_server.py tests
git commit -m "build(vector): package native SVG runtime"
```

### Task 6: Full VectorAnalysis performance, RSS, and proxy identity gate

**Files:**
- Create: `scripts/benchmark_native_svg_analysis.py`
- Create: `progress/native-svg-fast-path-benchmark.json`
- Create: `tests/test_native_svg_benchmark_contract_unit.py`

- [ ] **Step 1: Write a failing complete-entry benchmark contract**

Require public `VectorProcessor.analyze_svg` wall time, native parse/kernel time, NumPy/Shapely conversion time, adapter time, full color-match time, warm median/p95/range, peak RSS, swap delta, input SHA/size/structure counts, host manifest, and output fingerprint. The recovered real R4C1 hash and its `unsupported_vector_effect` fallback are a separate record; the proxy cannot satisfy it.

- [ ] **Step 2: Run the contract test and verify RED**

Run: `python3 -m pytest tests/test_native_svg_benchmark_contract_unit.py -q`

Expected: FAIL until measured evidence exists.

- [ ] **Step 3: Benchmark the complete public entry**

Use target width 111 mm, tolerance 0.02 mm, one discarded warm-up, at least three measured runs, Release extension, OpenMP disabled, one caller thread, and the available proxy file with fixed SHA. Capture output correctness before accepting timing.

- [ ] **Step 4: Search for and validate the 55 MB regression file without substitution**

If found locally, record its true SHA and run the <=2 GiB RSS / <=256 MiB swap gate. If unavailable, record `unavailable` with searched paths; never relabel `test_images/benchmark.svg` as that file or as R4C1.

- [ ] **Step 5: Run the contract test and commit evidence**

Run: `python3 -m pytest tests/test_native_svg_benchmark_contract_unit.py -q`

```bash
git add scripts/benchmark_native_svg_analysis.py progress/native-svg-fast-path-benchmark.json tests/test_native_svg_benchmark_contract_unit.py
git commit -m "perf(vector): verify complete native SVG analysis path"
```

### Task 7: Cross-platform wheel, container, onefile, and slicer reality CI

**Files:**
- Modify: `.github/workflows/native-svg-core.yml`
- Create: `scripts/verify_native_svg_slicer_outputs.py`
- Create: `docs/native-svg-fast-path-validation.md`

- [ ] **Step 1: Add CI jobs for all required realities**

Jobs build and install repaired wheels on Windows amd64, macOS arm64/x86_64, and manylinux x86_64; build the production Docker image; run the Windows PyInstaller onefile probe; generate representative GLB/3MF; and retain wheel, benchmark, 3MF, and probe artifacts.

- [ ] **Step 2: Add deterministic Bambu/Orca validation**

The validation script accepts explicit Bambu Studio and OrcaSlicer executable paths, opens/slices representative outputs non-interactively where the installed version supports it, and records executable version, exit code, object/material counts, and toolpath fingerprint. When binaries are not installed, it exits with a distinct `reality_dependency_unavailable` result rather than claiming PASS.

- [ ] **Step 3: Run local validation for installed slicers**

Search standard macOS application paths. Run both if present; otherwise preserve generated 3MF fixtures and exact commands for the Windows reality job.

- [ ] **Step 4: Push the topic branch normally and wait for CI**

Run: `git push -u origin MOVIBALE/feat/native-svg-core`

Expected: no force push; all required CI jobs complete or expose an external dependency boundary with retained evidence.

- [ ] **Step 5: Commit any evidence-only CI fixes through TDD**

Do not weaken correctness, RSS, or packaging gates to turn a failure green.

### Task 8: User-facing maintenance, independent review, and PR readiness

**Files:**
- Modify if release-note criteria apply: `frontend/src/data/announcements.ts`
- Modify: `docs/native-svg-fast-path-validation.md`
- Create: `docs/superpowers/reviews/2026-08-31-native-svg-fast-path-review.md`

- [ ] **Step 1: Read announcement and bug-repro maintenance guides before any related edit**

Run: `cat docs/announcement-maintenance.md` and, only if reproduction state changes, `cat docs/bug-report-reproducibility.md`.

- [ ] **Step 2: Run focused, smoke, full, logging, and packaging gates**

```bash
python3 -m pytest native/lumina-svg-core/tests tests/test_native_svg_* -q
python3 scripts/run_smoke_tests.py
python3 scripts/run_full_tests.py
python3 scripts/log_quality_check.py --mode fast
python3 -m pytest tests/test_logging_exception_governance_unit.py tests/test_structured_logging_unit.py tests/test_logger_unit.py -v
```

Classify the two known baseline stroke log-level assertions separately and prove no new failures relative to `892906a9`.

- [ ] **Step 3: Run an independent code review**

Give the reviewer the exact base `892906a9`, design spec, both plan files, full branch diff, test evidence, and explicit review dimensions: semantic correctness, fail-closed behavior, memory/lifetime, licensing, coordinate authority, no Python repair loop, packaging, and performance validity.

- [ ] **Step 4: Resolve every blocking review finding with a failing test first**

Record disposition and verification in the review document. Do not merge.

- [ ] **Step 5: Verify clean branch and open the dependency PR**

Confirm branch name, clean status, exact ancestry from #585, conventional commits, no secrets/generated caches, and ordinary upstream tracking. Open a PR against `dev-refactor` whose English-first/Chinese-second body declares dependency on PR #585 and separately states the external-repository extraction/publish boundary.

- [ ] **Step 6: Leave the PR unmerged**

Report PR URL, CI state, verified platforms/workflows, missing real R4C1 or slicer evidence if any, and the required dependency order. Do not merge or force-push.
