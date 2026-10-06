# 0928 coordinate handoff validation

## Identity and scope

- Base: `cf3700307894e277d431ae28a3b3ecd10c483fcb` (`dev-refactor`).
- Implementation branch: `Min/fix/native-svg-coordinate-domain`.
- Source implementation commit: `c058847b7a6aa5eab75fa756079ce83e449943d9`.
- Windows amd64, CPython 3.12, NumPy 2.3.2, Shapely 2.1.2 / GEOS 3.13.1,
  trimesh 4.11.2, manifold3d 3.4.0.
- Native package reports 0.3.0 / result schema 4. The rebuilt extension digest
  used for successful runs is
  `78f646b8b0baaed6e519641301e6d98fc424d04b97f88930aebd27f034ac8453`.
  It was installed into an isolated task directory, not over system packages.
- A post-commit wheel rebuild produced wheel SHA-256
  `db653395119e6c9c3ee10ef01bde08b4f95daba74be10537b2d0af8a89fbd703` with the
  same native extension digest. A fresh isolated install passed the runtime
  self-test and **101** coordinate/adapter/native-projection/packaging checks,
  including a real spawned child that verifies the extension path and digest.
- The pre-fix comparison used a separately compiled current-base extension
  containing #603, digest
  `575b1dd30ce08062b0bbe48aa69b131d4d84308ddd4c670405ac19cf66351f7e`.
  The older installed extension that produced 635 invalid regions was not used
  as this comparison baseline.
- Private input, user logs, captured geometry and generated user models were not
  committed. Their local evidence directory is `.scratch/0928-investigation/`.
- The user's installed backend/native hashes and material archive bytes remain
  unverified. Tests used the supplied original SVG and the same ten named local
  archives in the recorded order. This is not an identical user installation.

## Original-input workflow

The diagnostic harness used real ASGI preview/generate routes and the production
Windows worker pool, without replacing the parser, matcher, geometry builder or
writer. A fresh preview created each session. Private commands:

```powershell
$env:PYTHONPATH = (Resolve-Path '.scratch/0928-investigation/fix-native2').Path
$env:LUMINA_DIAG_OUTPUT_DIR = Join-Path (Get-Location).Path '.scratch/0928-investigation/acceptance-final'
python .scratch/0928-investigation/repro.py
python .scratch/0928-investigation/inspect_final_3mf.py
python .scratch/0928-investigation/check_final_meshes.py
```

| Check | Current base before fix | Fixed workflow |
| --- | --- | --- |
| Original SVG preview | HTTP 200 | HTTP 200 |
| Original SVG generate | HTTP 500, same topology error and coordinate as user | HTTP 200 |
| Download after source session close | No final artifact | HTTP 200 |
| 3MF ZIP integrity / model XML | Not reached | CRC clean; model XML parsed |
| Artifact | None | 119,584,451 bytes, 11 meshes, 9,723,492 triangles |

Kept settings: 190 mm width with actual SVG aspect ratio, six 0.08 mm colour
layers, 6 mm separate backing, single-sided, ten archive materials, H2C,
BambuStudio, 0.2 mm nozzles, textured PEI, 100% backing infill. The XML contains
all ten material names with extruder slots 1–10; Board uses slot 1. Optical
width is 190 mm and overall optical depth is 0.48 mm. A material need not occupy
every colour layer; e.g. the cyan mesh spans only its used layers. Board depth
is 6 mm. Its established structural margin and separation remain present.
An independent read of the written vertices/faces finds all eleven meshes
watertight, consistently wound, finite and positive-volume. Summed optical
volume is 11,357.2542277 mm³ versus 11,357.2542619 mm³ from covered area × 0.48 mm;
the small difference is consistent with final float32 vertex encoding.

The complete recorded request is in the local `requests.json`. Hue weight 0.5
and the base-layer modifier default true follow the current UI/defaults; the
original feedback did not independently prove those full request values.

After committing the source and rebuilding/reinstalling its wheel, the original
workflow was repeated again in `verified-head`: preview/generate/download all
returned 200, including download after source close. Generation took 182.34 s
in that run and produced a 119,584,341-byte ZIP. The uncompressed geometry XML
is byte-identical to the mesh-audited artifact above (SHA-256
`ad8f66db076006f6085a0400b7f26a55ac6bbde93e897b9ca8d5fe17ffcb6502`). ZIP metadata
and timestamps can differ. The timing variation is not presented as a speedup.

Historical `test_images/benchmark.svg` also completed real preview → generate →
download after source close. Its artifact is 35,784,804 bytes with clean ZIP CRC.
Ordinary overlap, component hierarchy, point contacts, holes and adjacent-triangle
fixtures are covered by native and product regression tests.

## Geometry and material checks

The reported input produces 26,402 visible regions in the fixed working domain.
Both four-vertex adapter counterexamples fail before the change and pass after.
A separate six-vertex print-cap counterexample fails when triangulated after mm
scaling and passes when triangulated in integer print coordinates.

The print-partition audit records:

- 0 invalid output regions and 0 area-overlap pairs.
- 32,694 planar cells; initial independent rounding exposed 4,697 overlapping
  pairs, which the shared partition resolves before material run unions.
- 361 regions collapse at the existing 0.0001 mm print grid. This is recorded,
  not treated as source parsing loss or hidden behind a colour-count reduction.
- Independent integer-winding tests verify holes, islands and labels across
  multiple source scales. Negative/half-grid projection and shared contact nodes
  have explicit native tests.
- A 104,000-point original-input audit compared RGB and complete recipes.
  Of 103,913 samples more than 0.0002 mm from source boundaries, none changed.

Coverage is **not claimed byte-for-byte or exactly equal across quantization**.
An independently projected native silhouette differs by 0.000617775 mm² missing
area and zero extra area. The two largest gaps have no source-visible owner at
their interior probe; they were not automatically filled. Source-covered narrow
differences have measured maximum inscribed diameter about 0.00012904 mm at a
0.0001 mm grid, with 0.00001 mm diameter measurement tolerance.

A second reference unions authoritative visible regions in the SVG domain and
projects that union once. Against it the measured missing/extra areas are
0.00008601 / 0.000996685 mm², with the same maximum missing diameter. These
different operation orders are reported separately; small net area alone is not
used as the correctness criterion.

## Independent review follow-up: R1 ownership sampling

The independent review identified that fixed-precision `point_on_surface` may
snap an ownership probe onto a cell boundary. The former production
`project_print_regions` returned empty output for a 1-by-3 one-grid rectangle
(input area 3) and for the valid single Polygon formed by two 10 mm squares
joined with a one-grid bridge (input area 200.001 mm²). Both inputs were already
on-grid. The two-region control retained both labels. These tests failed before
the fix against the actual native projection entry point.

The fix makes only a query view with precision removed via pointwise mode, then
builds the strict-interior probe from that view. A coordinate equality test
confirms the view moves no vertices. The same probe feeds projected-region
`within` and source-domain fallback. The printed cells and projected inputs
remain integer-grid geometries; no buffer, epsilon, nearest-owner rule, or hole
fill was added. After the change, the coordinate-domain suite passed **20/20**,
and the direct native SVG → `VectorAnalysis` → material-mesh volume integration
passed **1/1**. Ring direction, ring start, negative translation, one-grid
width, the 200.001 mm² bridge, the two-label control, existing holes/islands,
and later-paint precedence are covered.

The original SVG was rerun through the real ASGI preview and generation paths
with the isolated Windows extension (`0.3.0`, schema 4, SHA-256
`78f646b8b0baaed6e519641301e6d98fc424d04b97f88930aebd27f034ac8453`). Preview
returned HTTP 200 in 87.12 s; generation returned HTTP 200 in 203.01 s. The
source session was closed before fetching the 3MF; download returned HTTP 200,
the ZIP CRC was clean, and the 119,584,451-byte artifact contains 11 objects
and 9,723,492 triangles. Its geometry XML SHA-256 is unchanged from the prior
independently audited artifact (`ad8f66db076006f6085a0400b7f26a55ac6bbde93e897b9ca8d5fe17ffcb6502`).
R1 therefore fixed the constructed failure without changing ownership or output
geometry on this original SVG.

The historical `test_images/benchmark.svg` was also rerun through the same
preview/generate/close/download harness. Preview, generate and post-close fetch
all returned HTTP 200; its 35,784,804-byte 3MF ZIP passed CRC validation.

The cell-level comparison classifies the 361 empty output labels rather than
assuming they all came from initial quantization:

- **355** labels were already empty after projecting input regions to the print
  grid, before cell ownership.
- **6** had positive projected area but empty final output. Three were fully
  covered by later paints. Three had positive cells assigned to their own
  labels, but the final native canonical export returned empty geometry for
  those tiny dissolved regions; their retained pre-export areas sum to
  **0.000005545 mm²**. This is a separate existing quantization/canonicalization
  limitation, present identically before and after R1, and is not hidden under
  the 355 initially empty labels.
- Replaying the former snapped-point query on the captured original analysis
  changed **0** cell owners and recovered **0** cells. Both old and new queries
  left 5 cells / 0.000542155 mm² without projected or source-domain owners;
  source fallback matched 1,608 cells in both runs. Those five interiors have
  no source-region owner and remain unfilled.

This was the R1-head audit: it separated the additional canonicalization loss
from the ownership fix and did not attribute the reported generation failure to
R1. The following R2 section records the subsequent repair and rerun.

## Independent review follow-up: R2 owned-grid canonicalization

The old final path sent already-owned integer coverage through
`_native_grid_regions(..., 1.0)`, which runs the projection-time Clipper2 union
again. The new contract separates those stages: `project_regions_to_grid`
continues to scale/round and clean projected input; `canonicalize_grid_regions`
accepts exact integer rings and uses the shared `NodeToGrid` / `BuildFilledFaces`
rule without a second Clipper boolean. Production passes each owner's valid
polygonized cell rings directly to that native rule, so shared interior edges
cancel there; it does not build a pinched GEOS `coverage_union_all` geometry
first. Fractional input is rejected at the canonical-only boundary.

The red-first production regression paints a 10-by-10 grid square, then a
concave later paint that covers all but one short-edge 0.5 grid² corner triangle.
The old `project_print_regions` returned per-label areas **[0, 99.5]**; the new
production output is **[0.5, 99.5]**, with exact later-paint ownership, no
overlap, and unchanged union coverage. Three compact, translated captures from
the original owned cells also fail through the old native normalizer and are
preserved by the new direct native canonicalizer: their areas are **5.5, 17.5,
and 531.5 grid²**. They retain geometry and labels under a second normalization.
The complete original coordinate values were not committed.

The original SVG was rerun through the real ASGI preview → generate → close
source session → download workflow using the rebuilt, isolated CPython 3.12
Windows wheel. Preview returned HTTP 200 in **91.96 s**, generation HTTP 200 in
**196.80 s**, and post-close download HTTP 200. The CRC-clean 3MF is **119,592,689
bytes**, with 11 objects and **9,723,488 triangles**. All 11 meshes are watertight,
winding-consistent, finite and positive-volume. Geometry XML SHA-256 is
`f138d355ede4009b04e44bbf7a0b4728dbd90d9ad2eb585560d73304c5c2bb4`, which differs
from the R1 artifact as expected after restoring cell coverage. The ten
material/extruder assignments, H2C/0.2, textured PEI, 0.08 mm layer settings,
separate Board and dimensions match the preceding artifact. The source SVG SHA
remains `6a0ed5c1ea232d270c5632abefbfb01df4506251949a767bc153b2812591cbbd`; same-name
local materials were used, not byte-matched user archives.

The captured original analysis (26,402 input labels, 32,694 cells) was compared
by label through both finalization paths:

- The old final path returned 361 empty labels. Seven labels had positive owned
  cell area that it failed to preserve, and 13 labels had area differences.
  The new path returned no empty output for any positively owned label. Across
  all labels, the old output's summed area was 0.000145035 mm² below the adopted
  cell area; the new output matches cell coverage per label with zero measured
  symmetric difference.
- Of 355 labels empty immediately after the first target-grid projection, four
  later acquired source-domain-owned cells and are now retained. The other 351
  remain empty. Three projected-positive labels have no owned cells because
  later paint covers them; those remain empty. These stage counts are not a
  claim that all first-stage quantization collapses are independently proven
  desirable.
- The new integer canonicalization is idempotent in the original audit: maximum
  per-label symmetric difference on a second pass is **0**. Production output
  exactly matches the direct canonical entry; there are **0** invalid output
  regions and **0** inter-label overlap pairs. The R1 old/new owner comparison
  remains unchanged: 0 changed owners and the same five source-unowned cells
  remain empty.

The historical `test_images/benchmark.svg` was also rerun with the rebuilt wheel:
preview, generate and download after source-session close returned HTTP
**200/200/200**. Its 35,788,338-byte 3MF passed ZIP CRC validation.

The rebuilt Windows wheel SHA-256 is
`1f7aa88749e330ce5b2a1fbf60a30617b373f45de4504ca81d2b30dbaace54a9`; its isolated
loaded extension path is under `.scratch/0928-investigation/r2-wheel-install`,
binary SHA-256 `2461ced54018850a7ef46acc5acc0d8b1c50ce346d105ec9fb32c986d0a9b697`.
The package self-check verified the new API, the targeted suite exercised a real
spawn worker against that identity, and system `site-packages` was not changed.

## Independent review follow-up: R3 native self-test control flow

The bdc1a8ab review found that the new `svg_coordinate_domain` checks in
`_native_svg_self_test_payload` were indented under the `empty_silhouette`
`raise`. Thus a valid silhouette skipped every new capability/probe check,
while an empty silhouette raised before reaching them. The CLI could report
`status=ok` without invoking either native capability.

The repair moves the domain block back to the same level as the silhouette
guard. The no-domain behavior is unchanged, the empty-silhouette reason remains
unchanged, and projected-region validity stays inside the domain block. No R1
or R2 geometry code changed. The independent dependency-stub experiment in the
review package is not treated as native geometry evidence; repository behavior
tests exercise the real payload and the real CLI wrapper.

Before the source correction, the new control-flow test file produced **7
failures / 1 pass**: missing APIs, a zero-area canonical probe, and an invalid
projected region all returned success, and the valid-path call counters stayed
at zero. After the correction, all **8/8** self-test control-flow tests pass,
including negative/positive CLI JSON and exit codes and the unchanged empty-
silhouette branch.

Using the isolated R2 Windows wheel (binary SHA-256
`2461ced54018850a7ef46acc5acc0d8b1c50ce346d105ec9fb32c986d0a9b697`), the real
command
`python api_server.py --native-svg-self-test tests/fixtures/native_svg/clip_inherited_fill.svg`
returned exit code **0** and JSON `status=ok`; its payload reports the loaded
extension path/digest, three raw/visible geometries and one silhouette
component. `python native/lumina-svg-core/tools/verify_wheel.py --installed`
also returned **0**. These are separate installed-wheel and app self-test paths.

The combined self-test plus R1/R2/native/adapter/workflow/tiling/material/
packaging regression command passed **214 tests**. Its first run had one
transient `MemoryError` while a material worker imported `trimesh`; that test
passed alone, and the exact combined command then passed 214/214. No process
remained afterward. This was test-host resource pressure, not an API self-test
failure.

## Automated checks

After the R3 self-test control-flow regression was added, the affected
R1/R2/native/adapter/workflow/tiling/material/packaging set passed **214 tests**
against the isolated installed wheel:

```text
python -m pytest tests/test_native_svg_self_test_control_flow_unit.py native/lumina-svg-core/tests/test_coordinate_projection.py tests/test_native_canonical_preservation.py tests/test_svg_coordinate_domain_unit.py tests/test_native_svg_adapter_unit.py tests/test_native_svg_workflow_integration.py tests/test_native_svg_fallback_properties.py tests/test_vector_large_format_unit.py tests/test_vector_layer_geometry_unit.py tests/test_vector_material_parallelism_unit.py tests/test_native_svg_packaging_contract_unit.py tests/test_desktop_build_contract_unit.py -q
214 passed in 32.41s
python api_server.py --native-svg-self-test tests/fixtures/native_svg/clip_inherited_fill.svg
python native/lumina-svg-core/tools/verify_wheel.py --installed
ctest --test-dir .scratch/0928-investigation/fix-build -C Release --output-on-failure
1 passed
```

Executed using the isolated rebuilt native runtime:

```text
python -m pytest tests/test_native_svg_adapter_unit.py -q
python -m pytest tests/test_svg_coordinate_domain_unit.py -q
python -m pytest native/lumina-svg-core/tests/test_coordinate_projection.py -q
ctest --test-dir .scratch/0928-investigation/fix-build -C Release --output-on-failure
python -m pytest tests/test_logging_exception_governance_unit.py tests/test_structured_logging_unit.py tests/test_logger_unit.py -q
python scripts/log_quality_check.py --mode fast
python scripts/log_quality_check.py --mode full
python scripts/run_vitest.py run src/__tests__/useAnnouncement.test.ts src/__tests__/announcement-dialog.test.tsx --reporter=json --outputFile=../.scratch/0928-investigation/frontend-tests.json
python scripts/run_smoke_tests.py
```

- Focused native/product/caching/editing/tiling/geometry/packaging run: **404 passed**,
  recorded in `focused-tests.xml`; later identity/lazy-layout tests also pass.
- Full backend sweep: **6,847 passed, 52 failed, 53 skipped, 3 deselected**.
  All 52 failing nodes were rerun against the clean base with the pre-fix native
  extension: **the same 52 failed**. This is not reported as a green full suite.
- Native adapter + current coordinate-domain tests: passing; both serialization
  classes retain coordinates and restore precision. A real spawned child reports
  the expected loaded extension path and SHA.
- Native CTest integer-predicate executable: **1 passed**.
- Full native Python suite: **595 passed, 1 existing failure**. The same stress
  test fails with the untouched base extension; see baseline findings below.
- Logging unit checks: **21 passed**. Fast logging gate: **PASS**, 14 INFO lines.
- Announcement tests: **34 passed**, JSON reporter confirms success.
- Smoke gate: **PASS**; backend **162 passed**, frontend smoke passed, lint
  **0 errors / 70 existing warnings**. A task-local Corepack shim selected pinned
  pnpm 10.33.2 instead of the environment's unrelated pnpm 12 shim.
- Full logging gate: not green in this environment. The fixed and clean-base
  runs both report 27 INFO, 2 rasterio/GDAL deprecation warnings and 0 errors;
  the warnings lack actionable fields. Thresholds were not relaxed.

The focused command includes adapter/differential/native-workflow/fallback,
coordinate-domain, native selection, material archives, dynamic SVG edit
lifecycle, layered geometry, material parallelism/integrity, large format,
coating partition, hole compensation, GLB v2, packaging, keychain and outline
test files. Exact command and JUnit records are in the local evidence directory.

## Baseline findings kept separate

A clean managed checkout of the stated base reproduced:

1. `test_vector_outline_uses_one_canonical_build_and_runtime_guards` tries to mock
   the already removed `_enforce_vector_mesh_runtime_headroom`.
2. Two large-format cover tests expect `tile_rasterize_timeout`, while the
   existing code reports `TimeoutError`.
3. Native `test_parallel_normalization_failure_replays_in_document_order`
   expects `unsupported` while the current base returns `invalid`.
4. The full logging gate's two GDAL `Memory`-driver deprecation warnings.

These were not fixed by reintroducing resource quotas, editing unrelated stale
tests, changing logger budgets or suppressing warnings. Local full logging needs
`NO_PROXY=127.0.0.1,localhost` to bypass this host's system proxy for its test server.
The broader full-sweep failures also include existing frozen-raster baselines,
Windows symlink privileges, old GEOS proof imports, region-preview expectations,
printer profiles and Workshop release fixtures. The complete node list and both
JUnit results are retained locally; none was silently excluded from that sweep.

## Performance observations

Sequential same-machine parser/adapter runs (one cold and two warm per case):

| Case | Base cold / warm mean | Fixed cold / warm mean |
| --- | --- | --- |
| Reported original | 4.945 / 5.324 s | 5.256 / 5.551 s |
| Historical benchmark | 1.142 / 1.150 s | 1.182 / 1.175 s |

Process peak RSS in that probe: 175.87 → 184.59 MiB. This probe excludes solving,
mesh construction and export; its manifests retain native/source hashes.

Original full generate was 101.31 s **before failing** on the base and 234.80 s
to a completed 3MF in the fixed run. These are not comparable completion times.
The R1 follow-up original run completed in 203.01 s after an 87.12 s preview;
the historical benchmark completed generation in 38.87 s after a 13.10 s
preview. These are single follow-up observations, not a performance comparison.
The R2 original run completed in 196.80 s after a 91.96 s preview; its benchmark
run completed generation in 38.31 s after a 12.88 s preview. These are also
single-run observations and are not compared as a speed claim.
The successful run records 29.80 s for print handoff, 82.73 s for run unions,
18.62 s for materialization with 11 child processes, and 7.80 s for 3MF export.
RSS after scene assembly is about 871.5 MiB; it is not a sampled total-process-tree
peak. Historical benchmark generation completed in 46.18 s. No end-to-end speed
improvement is claimed.

## Remaining acceptance limits

The source-commit checks on [PR #620](https://github.com/lumina-layer-studio/Lumina-studio/pull/620)
did not execute. All nine hosted jobs report that recent account payments failed
or the spending limit needs to be increased. See the
[native-wheel run](https://github.com/lumina-layer-studio/Lumina-studio/actions/runs/36353251170)
and [geometry run](https://github.com/lumina-layer-studio/Lumina-studio/actions/runs/36353251174).
This is an external execution block, not a passing CI result or a tested code failure.

After the R1 commits, the new [native-wheel run](https://github.com/lumina-layer-studio/Lumina-studio/actions/runs/36364195698)
and [geometry run](https://github.com/lumina-layer-studio/Lumina-studio/actions/runs/36364195673)
also concluded with all nine jobs marked failed before executing any steps
(`steps: []`). No hosted test or build command ran for the R1 head. These are
execution-blocked checks, not evidence that the code failed a hosted test.

After the R2 code commit, the [native-wheel run](https://github.com/lumina-layer-studio/Lumina-studio/actions/runs/36372233702)
and [geometry run](https://github.com/lumina-layer-studio/Lumina-studio/actions/runs/36372233726)
again ended with all nine jobs failed and no steps recorded. No hosted build or
test command executed for R2; the earlier explicit account payment/spending
limit annotations remain the available explanation.

On the R3 code head, the [native-wheel run](https://github.com/lumina-layer-studio/Lumina-studio/actions/runs/36517376994)
has 7 failed jobs and the [geometry run](https://github.com/lumina-layer-studio/Lumina-studio/actions/runs/36517377045)
has 1 failed and 1 queued. Every job inspected has an empty `steps` list; no
hosted build or test ran for the R3 code. The queued job had not started at this
snapshot. Earlier annotations identify the account payment/spending-limit block.

Bambu Studio 2.8.02.61 was available locally. The original-file CLI slice attempt
timed out after 600 s without a toolpath. A tiny, same-profile control generated
successfully through Lumina but also timed out after 90 s using the documented
explicit `--export-3mf` command; neither produced diagnostic output. Owned
processes were terminated. Similar Windows CLI symptoms are reported upstream
in [BambuStudio #9802](https://github.com/bambulab/BambuStudio/issues/9802), but that
does not establish the cause on this host.

Therefore **actual slicing/printing acceptance remains unverified**. No printer
command was sent. A rebuilt Windows wheel and real spawned workers were tested;
the user's installed desktop package was not replaced, and no application
installer was deployed. The PR must not be described as full release acceptance.
