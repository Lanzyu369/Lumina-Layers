# Native SVG fast path validation

## Status

This document records evidence for the first `lumina-svg-core` integration.
It distinguishes checks that ran on the reference Mac from jobs that are only
configured and must still pass on the pull request. The fast path is enabled
only for documents whose complete semantics are supported; one unsupported
feature requests one whole-document legacy fallback.

The implementation is based on PR #585 commit
`892906a90fe4152b5af0120830254228748878d7`. It remains a separate topic branch
and must not be merged before that dependency.

## Reference-host evidence

Reference host: Apple M5 (`Mac17,3`), arm64, 16 GiB RAM, macOS 26.5.2,
CPython 3.12.13, Release build, OpenMP disabled, one caller thread.

The checked-in public-entry report is
`progress/native-svg-fast-path-benchmark.json`. It measures
`VectorProcessor.analyze_svg`, not only the C++ kernel, and clears Lumina's
parse/clip memory cache before every run. No artifact cache is configured.

| Check | Result |
|---|---:|
| Supported-scale fixture | SHA-256 `7f1fd4b2405989394c1a4fd6b59b117c4015ee2b9918b4dba5922c3e8ede472e`, 3,946,113 bytes |
| Source provenance | `test_images/benchmark.svg`, SHA-256 `d078cf4293623d934759c2688e13a00491e525055e7595069a0ecc4f078842fb` |
| Complete warm runs | 0.228076875 s, 0.224664375 s, 0.224001583 s |
| Warm median / gate | 0.224664375 s / 1.0 s — PASS |
| Warm p95 / gate | 0.227735625 s / 1.25 s — PASS |
| Native recorder | 0.056984583 s median |
| Native kernel | 0.136291709 s median |
| Binding conversion | 0.000003916 s median |
| Shapely adapter conversion | 0.011781000 s median |
| LUT color matching | 0.015268458 s median |
| Peak process RSS | 222,593,024 bytes |
| Measured swap growth | 0 bytes |
| Complete output | 1,024 raw/visible/matched shapes, 67,104 coordinates |
| Stable output fingerprint | `71de6894544ecfc02695ff33a52dfccb5bd2fd2313c41cf2312262f17f6b8f7b` |

The performance fixture is not presented as the unmodified source SVG. Its
checked-in provenance selects 64 source paths in descending serialized-size
order. A candidate is accepted only while the growing 16-repeat tiled panel
continues to pass every v0.1 fail-closed gate, and the final 1,024-path document
is verified again. The original 3,097-path source is also checked on every run;
it deterministically returns `unsupported_topology_collapse` because it
contains same-paint self-intersections/touches and legacy-close cases that
cannot be proved equivalent. This fallback is a correctness result, not a
performance pass.

The fixture verifier does not trust the checked-in 64-index tuple by itself.
Starting from the fixed source SHA, it re-sorts all paths by serialized XML
byte length and runs the complete standalone analysis plus area, contour,
curve-tolerance, precision, and topology parity gates on each candidate and
each growing compound panel. The resulting 64 indices must exactly reproduce
the checked-in selection. The standalone public-call median was 0.180260917 s
with 106,151,936 bytes peak RSS and the same 67,104-coordinate output.

## LUM-20260831-002/003 contract evidence

The user-owned SVG reported by these tickets was inspected in place and was
not copied into the repository. Its SHA-256 was independently verified as
`2a6de43cbb798ccaed4abd057f5d4cc2e5c448b98586b75cd1edbd46bdfc0d1c`
(4,797,183 bytes). At `target_width_mm=100` and `tolerance_mm=0.02`, the current
v0.1 runtime reaches the deterministic `unsupported_complexity` guard, so this
pull request does **not** claim native execution, performance, or end-to-end
colour equivalence for that document.

The ticket evidence nevertheless exposed two parser boundary contracts now
frozen by small synthetic regressions:

- Lumina's adapter retains exact `(r, g, b, a)`, source index, paint index, a
  stable `(source index, paint index)` identity, and per-paint component index
  through the parser's `shape_data` and `clipped_shapes` outputs.
- `component_hierarchy.svg` proves that a supported native result reaches
  `VectorAnalysis` without `_normalize_contours_many`, while retaining the
  large component, its hole, and an independent shell. The adjacent-triangle
  fixture is classified as one whole-document fallback rather than returning
  a partial native result.

The reported MaterialVectorMatcher uint8 Lab collision is evidence for why the
parser must expose exact source metadata, but material selection, KDTree/Lab
matching, dynamic recipes, and recipe propagation are intentionally unchanged
here. The later canonical 2D-to-mesh repair-group redesign also remains outside
this pull request. In particular, this change does not fix writer-grid
degeneration of a repair group containing an approximately `1e-8 mm²` dust
component. Native geometry remains separated by component with hole hierarchy
intact so those follow-up changes do not need to reconstruct topology from a
flattened union.

The supported-scale fixture is not the real R4C1 document and is not the
previously described 55 MB regression document. The real R4C1 fixture was
recovered separately:

- SHA-256: `da52ef12bdd37a0bd47970649a70582862331a606c151bff05bfb2f6e265f160`
- Size: 14,467,678 bytes
- Structure: 6,820 paths, including 3,410 stroke-only paths with
  `vector-effect="non-scaling-stroke"`
- Result: `unsupported_vector_effect`, whole-document fallback
- Native-by-default R4C1 release gate: **not ready**

No SVG at or above 50 MiB was found under the workspace root recorded in the
structured benchmark report. The 2 GiB RSS and 256 MiB swap gates for that
separate regression fixture therefore remain pending; neither the smaller
supported-scale fixture, source SVG, nor real R4C1 file is substituted for it.

## Packaging evidence

The standalone package built and installed as a clean CPython 3.12 macOS arm64
wheel. Its 393 package tests passed against the installed extension from
outside the source tree. The sdist and wheel both contain the complete LunaSVG,
PlutoVG, Clipper2, FreeType, stb, and pybind11 license texts in addition to the
Apache-2.0 project license. A separate clean CPython 3.12 environment also
built the extension from that sdist and passed the same 393 tests. Release
build inputs are fixed to scikit-build-core 1.0.3, pybind11 3.1.0, NumPy
2.5.2, CMake 4.3.4, and Ninja 1.13.2; release Actions are referenced by full
commit SHA. The sdist
also contains both pinned dependency patches and the fixed supported-scale
fixture/provenance. The local wheel SHA-256 was
`6be0889e74bccbd41034c0c56095c7a7c672dd70943204c135ad7c108be4131e`;
the sdist SHA-256 was
`acbd431455c91ef25717815fe9574e0d26464e13806fa70afa8050c0d19bfc55`.

A real macOS arm64 PyInstaller onefile binary was built from the production
spec in an environment containing the complete `requirements.txt` dependency
set, then invoked through Lumina's `--native-svg-self-test` public probe. The
probe returned native version `0.1.1`, result schema `1`, one raw geometry, two
visible geometries, two silhouette components, and fingerprint
`e98dcd0f413d8ea56e59f9f2e7feee240c6d9052dbdb9b3e76248e416e47b469`.
Cold onefile extraction and execution took 19.63 seconds with peak RSS
51,576,832 bytes and no swap growth. The 205,258,720-byte binary SHA-256 was
`ffe1c742576c3bd7210907f6665f4b2ec7596c7a43ed2a8aaa5e14ec5e3d9f1f`.
Archive inspection confirmed the compiled `_lumina_svg_core` extension and the
project, LunaSVG, PlutoVG, Clipper2, FreeType, stb, and pybind11 licenses were
present.

`.github/workflows/native-svg-core.yml` must provide the remaining pull-request
evidence:

- repaired CPython 3.12 wheels installed and exercised on Windows amd64,
  macOS arm64, macOS x86_64, and manylinux x86_64;
- production Docker build plus the Lumina native self-test;
- Windows PyInstaller onefile build plus the same self-test from the frozen
  executable;
- representative native GLB, Bambu 3MF, Orca 3MF, benchmark, and hosted-runner
  dependency-boundary reports retained as `lumina-native-svg-reality`.

These platforms are configured, not yet claimed as passed. Update this section
with workflow URLs and conclusions after the topic branch is pushed.

## Real Bambu Studio and OrcaSlicer evidence

The checked-in structured report is
`progress/native-svg-slicer-reality.json`. The validator generated the GLB and
both slicer-specific 3MF projects through Lumina's production native analysis,
mesh, GLB, and 3MF writers. It then invoked each installed CLI with an isolated
working/output directory.

| Slicer | Input structure | Result | Normalized toolpath |
|---|---|---|---|
| Bambu Studio 02.07.01.62 | 6 objects, 252 triangles, 5 materials | PASS, exit 0; tools 0–4 all extrude in model features | 6,290 motion commands, 4,292 model extrusion moves, 13 tool changes, fingerprint `7f9f6915bf40d692cdeebdf8fa32c3159431a747e0e555e3ac0a6c1aa6843ec1` |
| OrcaSlicer 2.4.0 | 6 objects, 252 triangles, 5 materials | PASS, exit 0; tools 0–4 all extrude in model features | 6,697 motion commands, 4,557 model extrusion moves, 13 tool changes, fingerprint `efff1f6fc42577c4a6aba62b0f8a22d924e574012bc02e7efc7c1311c63bcf99` |

Toolpath fingerprints exclude comments and blank lines, then hash normalized
motion, positioning-mode, and tool-change commands. Material evidence counts
only positive extrusion on a command with real XY movement while the slicer
marks a model feature; pure-E priming, custom startup, support, skirt/brim,
and prime/wipe towers cannot satisfy the gate. Absolute E remains global
across tool changes unless the G-code explicitly resets it. A zero exit
without qualifying extrusion from every 3MF-declared tool (0 through 4 here)
is a failure. Each slicer ran twice
in separate fresh directories; both Bambu runs produced the same fingerprint
and both Orca runs produced the same fingerprint.
A missing slicer is reported as `reality_dependency_unavailable` with exit code
20, never as PASS.

Reproduce generation and local slicing with:

```bash
python scripts/verify_native_svg_slicer_outputs.py \
  --generate-artifacts \
  --artifact-dir /tmp/lumina-native-svg-reality \
  --bambu-executable /Applications/BambuStudio.app/Contents/MacOS/BambuStudio \
  --orca-executable /Applications/OrcaSlicer.app/Contents/MacOS/OrcaSlicer \
  --report progress/native-svg-slicer-reality.json
```

## CI and benchmark reproduction

Build and test the standalone wheel locally:

```bash
python -m build --wheel native/lumina-svg-core
(cd native/lumina-svg-core && python -m pytest tests -q)
```

Measure the complete Lumina public entry while honestly recording the missing
large fixture:

```bash
python scripts/benchmark_native_svg_analysis.py \
  --large-search-root workspace=. \
  --output progress/native-svg-fast-path-benchmark.json
```

The benchmark writes the report first and then exits non-zero when the public
entry exceeds the 1.0 s median or 1.25 s p95 limits. When an explicit 50 MiB
fixture is measured, the 2 GiB RSS and 256 MiB swap-delta limits are fatal too;
an unavailable large fixture remains recorded as unavailable rather than being
replaced by a smaller input.

Generate retained product artifacts without requiring a slicer on the runner:

```bash
python scripts/verify_native_svg_slicer_outputs.py \
  --generate-only \
  --artifact-dir native-svg-reality \
  --report native-svg-reality/generation-report.json
```

## Release boundaries

- `lumina-svg-core` is publishable in-tree under Apache-2.0. LunaSVG and
  Clipper2 are pinned; LunaSVG's bundled PlutoVG version is recorded in the
  standalone notices and dependency lock.
- The production adapter performs three vectorized Shapely ragged-array
  conversions. It does not run a second Python GEOS union, `make_valid`, or
  per-ring repair loop.
- After native composition, the C++ kernel performs a lightweight structural
  and material census over the already-built result arrays: offset monotonicity,
  closed rings, raw/visible paint identity, and a non-empty silhouette. This is
  an invariant check only; it does not compute alternate geometry or run a
  shadow parser.
- CSS reference semantics, existing legacy stroke policy, unsupported paint
  semantics, fixed-segment LunaSVG arc sources (`A`/`a`, circle, ellipse, and
  rounded rectangle), and the real R4C1 `non-scaling-stroke` case fall back
  once for the whole document. Production does not run a full shadow audit.
- Publishing the standalone package to a separate GitHub repository and wheel
  index requires an owner/namespace decision. Until then,
  `requirements-native-svg.txt` installs the exact in-tree package. If split,
  publish the standalone library first, replace the workspace requirement with
  `lumina-svg-core==0.1.1`, then land the Lumina integration PR.
- The branch must remain unmerged until PR #585 is available on
  `dev-refactor`, all configured CI reality jobs pass, and blocking independent
  review findings are resolved.
