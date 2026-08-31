# lumina-svg-core 0.1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a publishable Apache-2.0 `lumina-svg-core` 0.1 package that records LunaSVG paint commands, computes print polygons with Clipper2, and exposes an immutable NumPy buffer contract.

**Architecture:** The library lives temporarily under `native/lumina-svg-core/` so it can be split into its own repository without moving internal source paths. CMake fetches exact LunaSVG and Clipper2 revisions, applies a narrow versioned LunaSVG recorder patch, statically links LunaSVG/PlutoVG/Clipper2 into one hidden-symbol pybind11 extension, and never depends on Lumina, Shapely, printer settings, or Python geometry repair.

**Tech Stack:** C++17, LunaSVG `59690a23981489acc3f73b8db229ef57bb69c544`, bundled PlutoVG 1.3.2 tree, Clipper2 `21ebba05db8894f0c7217ad35ea518080f324946`, CMake, pybind11, scikit-build-core, NumPy, pytest, cibuildwheel.

---

### Task 1: Publishable package, dependency lock, and license boundary

**Files:**
- Create: `native/lumina-svg-core/pyproject.toml`
- Create: `native/lumina-svg-core/CMakeLists.txt`
- Create: `native/lumina-svg-core/cmake/Dependencies.cmake`
- Create: `native/lumina-svg-core/LICENSE`
- Create: `native/lumina-svg-core/THIRD_PARTY_NOTICES.md`
- Create: `native/lumina-svg-core/README.md`
- Create: `native/lumina-svg-core/python/lumina_svg_core/__init__.py`
- Create: `native/lumina-svg-core/tests/test_distribution_contract.py`

- [ ] **Step 1: Write the failing distribution-contract test**

```python
def test_distribution_pins_native_dependencies_and_licenses() -> None:
    root = Path(__file__).resolve().parents[1]
    cmake = (root / "cmake" / "Dependencies.cmake").read_text("utf-8")
    notices = (root / "THIRD_PARTY_NOTICES.md").read_text("utf-8")
    assert "59690a23981489acc3f73b8db229ef57bb69c544" in cmake
    assert "21ebba05db8894f0c7217ad35ea518080f324946" in cmake
    assert "LunaSVG" in notices and "PlutoVG" in notices and "Clipper2" in notices
```

- [ ] **Step 2: Run the test and verify RED**

Run: `/opt/homebrew/bin/python3.12 -m pytest native/lumina-svg-core/tests/test_distribution_contract.py -q`

Expected: FAIL because the package and lock files do not exist.

- [ ] **Step 3: Add the package metadata and immutable dependency pins**

Use project name `lumina-svg-core`, version `0.1.1`, `requires-python = "==3.12.*"`, build requirements `scikit-build-core`, `pybind11`, and `numpy`, and these CMake cache options:

```cmake
set(LUMINA_LUNASVG_REVISION "59690a23981489acc3f73b8db229ef57bb69c544")
set(LUMINA_CLIPPER2_REVISION "21ebba05db8894f0c7217ad35ea518080f324946")
set(BUILD_SHARED_LIBS OFF CACHE BOOL "" FORCE)
set(CLIPPER2_TESTS OFF CACHE BOOL "" FORCE)
set(CLIPPER2_EXAMPLES OFF CACHE BOOL "" FORCE)
set(CLIPPER2_UTILS OFF CACHE BOOL "" FORCE)
set(CLIPPER2_USINGZ OFF CACHE STRING "" FORCE)
```

- [ ] **Step 4: Run the distribution-contract test and verify GREEN**

Run: `/opt/homebrew/bin/python3.12 -m pytest native/lumina-svg-core/tests/test_distribution_contract.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the package boundary**

```bash
git add native/lumina-svg-core
git commit -m "build(native-svg): scaffold publishable core package"
```

### Task 2: Narrow LunaSVG paint-command recorder fork

**Files:**
- Create: `native/lumina-svg-core/patches/lunasvg-paint-recorder.patch`
- Create: `native/lumina-svg-core/include/lumina_svg_core/paint_command.h`
- Create: `native/lumina-svg-core/tests/fixtures/basic_fill_stroke.svg`
- Create: `native/lumina-svg-core/tests/fixtures/unsupported_semantics.svg`
- Create: `native/lumina-svg-core/tests/test_recorder_contract.py`
- Modify: `native/lumina-svg-core/cmake/Dependencies.cmake`

- [ ] **Step 1: Write failing recorder contract tests**

```python
def test_recorder_preserves_fill_then_stroke_order() -> None:
    commands = lumina_svg_core.record_paint_commands(FIXTURES / "basic_fill_stroke.svg")
    assert [command.kind for command in commands.commands] == ["fill", "stroke"]
    assert tuple(commands.commands[0].rgba) == (255, 0, 0, 255)
    assert tuple(commands.commands[1].rgba) == (0, 0, 255, 255)

@pytest.mark.parametrize(
    ("attribute", "reason"),
    [("vector-effect", "unsupported_vector_effect"),
     ("marker-start", "unsupported_marker"),
     ("paint-order", "unsupported_paint_order")],
)
def test_recorder_reports_ignored_semantics(attribute: str, reason: str) -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        f'<svg viewBox="0 0 10 10"><path d="M0 0H10V10Z" {attribute}="x"/></svg>'
    )
    assert result.status == "unsupported"
    assert result.reason_code == reason
    assert result.commands == ()
```

- [ ] **Step 2: Build once and verify RED**

Run: `/opt/homebrew/bin/python3.12 -m pip wheel native/lumina-svg-core -w /tmp/lumina-svg-core-red`

Expected: FAIL because the recorder API and extension are absent.

- [ ] **Step 3: Add the recorder API at LunaSVG's render traversal boundary**

The patch must add a public, versioned `Document::recordPaintCommands()` entry and internal hooks only at parser capability collection, `SVGRenderState` group/clip boundaries, and `SVGGeometryElement::render`. The public command contains copied path verbs/points, the resolved solid RGBA, full affine matrix, fill rule or stroke parameters, group opacity, source index, and source kind. It must not expose `SVGElement`, `SVGLayoutState`, or any other private LunaSVG class.

```cpp
enum class PaintCommandKind : uint8_t { Fill, Stroke, ClipBegin, ClipEnd, GroupBegin, GroupEnd };
enum class CapabilityStatus : uint8_t { Supported, Unsupported, Invalid };
struct PaintCommand {
    PaintCommandKind kind;
    std::vector<PathVerb> verbs;
    std::vector<Point> points;
    Matrix transform;
    uint32_t rgba;
    FillRule fill_rule;
    StrokeStyle stroke;
    float group_opacity;
    int32_t source_index;
};
```

- [ ] **Step 4: Make parser/layout omissions fail closed**

Record unknown elements, unknown presentation attributes, unknown CSS declarations/selectors, external resources, image/text/mask/pattern/gradient use, partial effective alpha, markers, vector effects, and unsupported paint order as stable reason codes. Return no commands whenever any document-level issue is present.

- [ ] **Step 5: Build the extension and run recorder tests**

Run: `/opt/homebrew/bin/python3.12 -m pip install --force-reinstall native/lumina-svg-core`

Run: `/opt/homebrew/bin/python3.12 -m pytest native/lumina-svg-core/tests/test_recorder_contract.py -q`

Expected: PASS with fill/stroke order preserved and all unsupported cases returning zero commands.

- [ ] **Step 6: Verify the patch applies only to the exact upstream commit**

Run: `cmake -S native/lumina-svg-core -B /tmp/lumina-svg-core-configure -DLUMINA_VERIFY_RECORDER_PATCH=ON`

Expected: configuration succeeds and prints the exact LunaSVG SHA; changing the expected SHA in a temporary build must fail before compilation.

- [ ] **Step 7: Commit the recorder fork patch**

```bash
git add native/lumina-svg-core
git commit -m "feat(native-svg): record resolved LunaSVG paint commands"
```

### Task 3: Versioned immutable result schema and buffer lifetime

**Files:**
- Create: `native/lumina-svg-core/include/lumina_svg_core/result.h`
- Create: `native/lumina-svg-core/src/result.cpp`
- Create: `native/lumina-svg-core/src/bindings.cpp`
- Create: `native/lumina-svg-core/tests/test_result_schema.py`
- Modify: `native/lumina-svg-core/CMakeLists.txt`
- Modify: `native/lumina-svg-core/python/lumina_svg_core/__init__.py`

- [ ] **Step 1: Write failing dtype, closure, offset, and lifetime tests**

```python
def test_result_buffers_are_typed_read_only_and_keep_owner_alive() -> None:
    result = lumina_svg_core.analyze_svg(FIXTURES / "basic_fill_stroke.svg", 20.0, 0.02)
    coordinates = result.visible.coordinates
    ring_offsets = result.visible.ring_offsets
    del result
    gc.collect()
    assert coordinates.dtype == np.dtype(np.int64)
    assert ring_offsets.dtype == np.dtype(np.uint64)
    assert not coordinates.flags.writeable
    assert coordinates.shape[1] == 2
    assert ring_offsets[0] == 0
    assert ring_offsets[-1] == len(coordinates)
    assert np.array_equal(coordinates[ring_offsets[1] - 1], coordinates[ring_offsets[0]])
```

- [ ] **Step 2: Run the test and verify RED**

Run: `/opt/homebrew/bin/python3.12 -m pytest native/lumina-svg-core/tests/test_result_schema.py -q`

Expected: FAIL because `analyze_svg` and its arrays do not exist.

- [ ] **Step 3: Implement the structure-of-arrays schema**

Define `NativeResult` with `raw`, `visible`, and `silhouette` collections. Coordinates are `int64`; ring, polygon, and geometry offsets are `uint64`; RGBA is `uint8`; draw/source indices and source kinds are `int32`. Every offset sequence starts at zero, ends at the child count, and includes empty collections. The collection also exposes scalar `geometry_count`, `component_count`, `hole_count`, and integer-grid area diagnostics used without rebuilding polygons. Use checked multiplication/addition before every vector resize.

- [ ] **Step 4: Bind zero-copy read-only arrays with shared ownership**

Each `py::array` uses the `std::shared_ptr<NativeResult>` Python wrapper as its base object, calls `setflags(write=False)`, and never owns a second vector copy. Release the GIL around parsing and geometry work.

- [ ] **Step 5: Run schema and lifetime tests and verify GREEN**

Run: `/opt/homebrew/bin/python3.12 -m pytest native/lumina-svg-core/tests/test_result_schema.py -q`

Expected: PASS under normal execution and `PYTHONMALLOC=debug`.

- [ ] **Step 6: Commit the public schema**

```bash
git add native/lumina-svg-core
git commit -m "feat(native-svg): expose immutable NumPy result schema"
```

### Task 4: Physical flattening, fixed error budget, and fill topology

**Files:**
- Create: `native/lumina-svg-core/include/lumina_svg_core/error_budget.h`
- Create: `native/lumina-svg-core/include/lumina_svg_core/geometry_kernel.h`
- Create: `native/lumina-svg-core/src/error_budget.cpp`
- Create: `native/lumina-svg-core/src/geometry_kernel.cpp`
- Create: `native/lumina-svg-core/tests/fixtures/fill_rules_transforms.svg`
- Create: `native/lumina-svg-core/tests/test_fill_geometry.py`

- [ ] **Step 1: Write failing physical-error and topology tests**

```python
def test_non_uniform_transform_uses_model_space_error_budget() -> None:
    result = analyze_svg(FIXTURES / "fill_rules_transforms.svg", 100.0, 0.02)
    assert result.status == "supported"
    assert result.max_flattening_error_mm <= 0.008
    assert result.max_quantization_error_mm <= 0.004

def test_evenodd_hole_and_disconnected_shell_survive() -> None:
    result = analyze_svg(FIXTURES / "fill_rules_transforms.svg", 100.0, 0.02)
    assert result.visible.component_count == 2
    assert result.visible.hole_parent.tolist().count(-1) == 2
    assert sum(parent >= 0 for parent in result.visible.hole_parent) == 1
```

- [ ] **Step 2: Run tests and verify RED**

Run: `/opt/homebrew/bin/python3.12 -m pytest native/lumina-svg-core/tests/test_fill_geometry.py -q`

Expected: FAIL on missing geometry kernel.

- [ ] **Step 3: Implement one document-level budget**

Validate positive finite target width and tolerance. Reserve 40% for flattening, 20% for all quantization, and 40% for Lumina post-analysis. Compute local flatten tolerance from the source-to-mm scale and largest singular value of the complete affine transform. Choose one checked document grid and reject values beyond Clipper2's safe `int64` range with `numeric_range_error`.

- [ ] **Step 4: Implement adaptive path flattening and Clipper2 fill normalization**

Flatten cubic segments recursively to the local allocation, transform once to model millimetres, quantize once to the document grid, and execute `Clipper64` with the recorded NonZero/EvenOdd rule into `PolyTree64`. Export stable outer/hole parent relationships without a second repair pass.

- [ ] **Step 5: Run fill tests and verify GREEN**

Run: `/opt/homebrew/bin/python3.12 -m pytest native/lumina-svg-core/tests/test_fill_geometry.py -q`

Expected: PASS with no component, hole, or separating-gap collapse.

- [ ] **Step 6: Commit the fill kernel**

```bash
git add native/lumina-svg-core
git commit -m "feat(native-svg): add tolerance-bounded fill kernel"
```

### Task 5: Local-coordinate strokes, clips, and reverse-order occlusion

**Files:**
- Create: `native/lumina-svg-core/src/stroke_expander.cpp`
- Create: `native/lumina-svg-core/include/lumina_svg_core/stroke_expander.h`
- Create: `native/lumina-svg-core/src/paint_compositor.cpp`
- Create: `native/lumina-svg-core/include/lumina_svg_core/paint_compositor.h`
- Create: `native/lumina-svg-core/tests/fixtures/strokes_clips_occlusion.svg`
- Create: `native/lumina-svg-core/tests/test_paint_semantics.py`

- [ ] **Step 1: Write failing stroke/clip/occlusion tests**

```python
def test_stroke_expands_before_full_affine_transform() -> None:
    result = analyze_svg(FIXTURES / "strokes_clips_occlusion.svg", 100.0, 0.02)
    stroke_indices = np.flatnonzero(result.raw.source_kinds == SOURCE_KIND_STROKE)
    assert stroke_indices.tolist() == [1]
    assert geometry_bounds_svg(result.raw, 1) == pytest.approx(
        (20.0, 10.0, 80.0, 30.0), abs=0.03
    )

def test_clip_and_later_paint_define_visible_geometry() -> None:
    result = analyze_svg(FIXTURES / "strokes_clips_occlusion.svg", 100.0, 0.02)
    assert result.raw.geometry_count > result.visible.geometry_count
    assert total_area_svg(result.visible) == pytest.approx(560.0, abs=0.05)
    assert result.silhouette.hole_count == 1
```

- [ ] **Step 2: Run tests and verify RED**

Run: `/opt/homebrew/bin/python3.12 -m pytest native/lumina-svg-core/tests/test_paint_semantics.py -q`

Expected: FAIL because stroke expansion and compositor are absent.

- [ ] **Step 3: Expand strokes in local coordinates**

Flatten locally, apply dash array/offset in local arclength, use ClipperOffset with recorded join/cap/miter settings on the local integer allocation, then apply the complete affine transform to the expanded outline and quantize to the one document grid. Closed and open paths use the correct Clipper2 end type.

- [ ] **Step 4: Apply clip scopes and occlusion in source order**

Replay recorder group/clip commands as a stack. Intersect each paint with its active vector clips. Reject mask/group-opacity/partial-alpha scopes before geometry. Process paints in reverse draw order, query later overlapping bounds with an R-tree-equivalent packed bbox index, subtract only overlaps, and build the final silhouette in C++. Keep only the raw/visible/silhouette collections required by the result contract; do not compute a full alternate shadow analysis. Deduplicate exact source segments and fail closed when the topology-candidate cap is exceeded.

- [ ] **Step 5: Run semantic tests and verify GREEN**

Run: `/opt/homebrew/bin/python3.12 -m pytest native/lumina-svg-core/tests/test_paint_semantics.py -q`

Expected: PASS for dashes, joins, caps, clips, fill/stroke order, occlusion, and silhouette.

- [ ] **Step 6: Commit the compositor**

```bash
git add native/lumina-svg-core
git commit -m "feat(native-svg): preserve stroke clip and occlusion semantics"
```

### Task 6: Golden differential corpus and deterministic fingerprints

**Files:**
- Create: `native/lumina-svg-core/tests/fixtures/golden/`
- Create: `native/lumina-svg-core/tests/golden_manifest.json`
- Create: `native/lumina-svg-core/tests/test_golden_corpus.py`
- Create: `native/lumina-svg-core/tools/fingerprint.py`

- [ ] **Step 1: Add failing manifest-driven golden tests**

The manifest records SHA-256, ordered colors, component/hole counts, per-color area, bounds, and output fingerprint for filled paths, stroke-only gap fillers, transforms/viewBox percentages, both fill rules, CSS inheritance, `use`, clip paths, overlaps, and disconnected islands.

```python
@pytest.mark.parametrize("case", load_manifest())
def test_golden_case(case: GoldenCase) -> None:
    result = analyze_svg(case.path, case.target_width_mm, case.tolerance_mm)
    assert result.status == case.status
    assert fingerprint(result) == case.output_fingerprint
    assert result.visible.ordered_rgb == case.ordered_rgb
    assert result.visible.component_count == case.component_count
    assert result.visible.hole_count == case.hole_count
```

- [ ] **Step 2: Run tests and verify RED against an empty manifest**

Run: `/opt/homebrew/bin/python3.12 -m pytest native/lumina-svg-core/tests/test_golden_corpus.py -q`

Expected: FAIL because required cases and fingerprints are missing.

- [ ] **Step 3: Add reduced repository-safe fixtures and independently computed expectations**

Expectations must come from analytic geometry or the pre-change Lumina parser; do not generate and approve expectations from the new kernel in the same run. Add explicit whole-document fallback cases for every unsupported v0.1 semantic.

- [ ] **Step 4: Run the full standalone suite twice**

Run: `/opt/homebrew/bin/python3.12 -m pytest native/lumina-svg-core/tests -q`

Run the same command again and compare fingerprints.

Expected: both runs PASS and fingerprints are byte-identical.

- [ ] **Step 5: Commit the golden corpus**

```bash
git add native/lumina-svg-core
git commit -m "test(native-svg): add deterministic golden corpus"
```

### Task 7: Wheels, platform repair, and clean-environment validation

**Files:**
- Create: `native/lumina-svg-core/.github/workflows/wheels.yml`
- Create: `.github/workflows/native-svg-core.yml`
- Create: `native/lumina-svg-core/tools/verify_wheel.py`
- Modify: `native/lumina-svg-core/pyproject.toml`
- Modify: `native/lumina-svg-core/CMakeLists.txt`

- [ ] **Step 1: Write a failing wheel-content verifier**

```python
def verify_wheel(path: Path) -> None:
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
    assert any(name.endswith((".pyd", ".so")) for name in names)
    assert any(name.endswith("LICENSE") for name in names)
    assert any(name.endswith("THIRD_PARTY_NOTICES.md") for name in names)
```

- [ ] **Step 2: Build the local CPython 3.12 wheel and verify RED**

Run: `/opt/homebrew/bin/python3.12 -m build --wheel native/lumina-svg-core`

Expected before packaging configuration: verifier FAILS because notice files are absent from the wheel.

- [ ] **Step 3: Configure the exact cibuildwheel matrix**

Build only `cp312-win_amd64`, `cp312-macosx_arm64`, `cp312-macosx_x86_64`, and `cp312-manylinux_x86_64`; use `delvewheel`, `delocate`, and `auditwheel` repair commands respectively. Run standalone tests from the installed wheel in a clean environment, not from the source tree.

- [ ] **Step 4: Validate the local wheel from a fresh venv**

Run: `/opt/homebrew/bin/python3.12 -m venv /tmp/lumina-svg-core-wheel-venv`

Run: `/tmp/lumina-svg-core-wheel-venv/bin/python -m pip install native/lumina-svg-core/dist/*.whl pytest numpy`

Run: `/tmp/lumina-svg-core-wheel-venv/bin/python native/lumina-svg-core/tools/verify_wheel.py native/lumina-svg-core/dist/*.whl`

Expected: extension imports, fixture analysis succeeds, and all notices are present.

- [ ] **Step 5: Commit release automation**

```bash
git add native/lumina-svg-core .github/workflows/native-svg-core.yml
git commit -m "ci(native-svg): build and verify platform wheels"
```

### Task 8: Standalone performance and RSS evidence

**Files:**
- Create: `native/lumina-svg-core/tools/benchmark.py`
- Create: `native/lumina-svg-core/benchmarks/proxy_manifest.json`
- Create: `native/lumina-svg-core/benchmarks/supported_scale_fixture.svg`
- Create: `native/lumina-svg-core/benchmarks/supported_scale_fixture_provenance.json`
- Create: `native/lumina-svg-core/benchmarks/README.md`
- Create: `native/lumina-svg-core/tests/test_benchmark_manifest.py`

- [ ] **Step 1: Write a failing benchmark-manifest contract**

Require fixture SHA-256, byte size, canvas, path/stroke/transform/clip counts, host manifest, at least three warm runs, median/range, peak RSS, swap delta, region count, coordinate count, and output fingerprint. Record the recovered real R4C1 SHA `da52ef12bdd37a0bd47970649a70582862331a606c151bff05bfb2f6e265f160` separately, including its fail-closed `unsupported_vector_effect` outcome, without claiming the proxy is that file.

- [ ] **Step 2: Run the manifest test and verify RED**

Run: `/opt/homebrew/bin/python3.12 -m pytest native/lumina-svg-core/tests/test_benchmark_manifest.py -q`

Expected: FAIL until measured evidence is present.

- [ ] **Step 3: Implement a bounded benchmark runner**

The runner discards one warm-up, measures at least three runs, samples process peak RSS and swap, fingerprints output, and reports recorder/kernel/result-conversion timing separately. It refuses to label a file R4C1 unless its SHA matches the real hash.

- [ ] **Step 4: Record local Apple M5 evidence**

Run: `/opt/homebrew/bin/python3.12 native/lumina-svg-core/tools/benchmark.py --svg native/lumina-svg-core/benchmarks/supported_scale_fixture.svg --target-width-mm 111 --tolerance-mm 0.02 --warm-runs 3 --output native/lumina-svg-core/benchmarks/proxy_manifest.json`

Expected: deterministic fingerprint, measured median/range/RSS, an explicit
`derived_supported_scale` label, and separate fail-closed records for the
unmodified source proxy and real R4C1.

- [ ] **Step 5: Run the benchmark-manifest test and commit**

Run: `/opt/homebrew/bin/python3.12 -m pytest native/lumina-svg-core/tests/test_benchmark_manifest.py -q`

```bash
git add native/lumina-svg-core
git commit -m "perf(native-svg): record proxy geometry benchmark"
```
