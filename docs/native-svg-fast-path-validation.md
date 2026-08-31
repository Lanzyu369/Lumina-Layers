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
| Supported-scale fixture | SHA-256 `aedd2705dff8a61779418ddb4574aff7d2b22e19577fa798ebc669e4b60f9070`, 4,786,900 bytes |
| Source provenance | `test_images/benchmark.svg`, SHA-256 `d078cf4293623d934759c2688e13a00491e525055e7595069a0ecc4f078842fb` |
| Complete warm runs | 0.263166208 s, 0.268387708 s, 0.257893541 s |
| Warm median / gate | 0.263166208 s / 1.0 s — PASS |
| Warm p95 / gate | 0.267865558 s / 1.25 s — PASS |
| Native recorder | 0.068439750 s median |
| Native kernel | 0.162982250 s median |
| Binding conversion | 0.000003417 s median |
| Shapely adapter conversion | 0.011380250 s median |
| LUT color matching | 0.015410041 s median |
| Peak process RSS | 218,497,024 bytes |
| Measured swap growth | 0 bytes |
| Complete output | 1,024 raw/visible/matched shapes, 76,848 coordinates |
| Stable output fingerprint | `1e22f943cb285246c9551e32e7ea1d43adec7d2c7d8587fab9376cc2e9e10838` |

The performance fixture is not presented as the unmodified source SVG. Its
checked-in provenance selects the 64 longest source paths that independently
pass every v0.1 fail-closed gate, then places 16 copies of each in disjoint
cells. The original 3,097-path source is also checked on every benchmark run;
it deterministically returns `unsupported_topology_collapse` because it
contains same-paint self-intersections/touches and legacy-close cases that
cannot be proved equivalent. This fallback is a correctness result, not a
performance pass.

The supported-scale fixture is not the real R4C1 document and is not the
previously described 55 MB regression document. The real R4C1 fixture was
recovered separately:

- SHA-256: `da52ef12bdd37a0bd47970649a70582862331a606c151bff05bfb2f6e265f160`
- Size: 14,467,678 bytes
- Structure: 6,820 paths, including 3,410 stroke-only paths with
  `vector-effect="non-scaling-stroke"`
- Result: `unsupported_vector_effect`, whole-document fallback
- Native-by-default R4C1 release gate: **not ready**

No SVG at or above 50 MiB was found under the local Codex worktrees,
Downloads, Desktop, or Documents roots. The 2 GiB RSS and 256 MiB swap gates
for that separate regression fixture therefore remain pending; neither the
4.79 MB supported-scale fixture, the 3.77 MB source SVG, nor the 14.47 MB R4C1
file is substituted for it.

## Packaging evidence

The standalone package built and installed as a clean CPython 3.12 macOS arm64
wheel. Its 373 package tests passed against the installed extension from
outside the source tree. The sdist and wheel both contain the complete LunaSVG,
PlutoVG, Clipper2, FreeType, stb, and pybind11 license texts in addition to the
Apache-2.0 project license. A separate clean CPython 3.12 environment also
built the extension from that sdist and passed the same 373 tests. The sdist
also contains both pinned dependency patches and the fixed supported-scale
fixture/provenance. The local wheel SHA-256 was
`1530c7f828e7fa3aa5e1f995cb9061e218f3fedf59c8d8f2726d7cfec1e905f1`;
the sdist SHA-256 was
`f734647deb97e71020176fd3c1fc489150d6f8cc28828ec3e4d853394c134bae`.

A real macOS arm64 PyInstaller onefile binary was built at a temporary output
path and invoked through Lumina's `--native-svg-self-test` public probe. The
probe returned native version `0.1.1`, result schema `1`, one raw geometry, two
visible geometries, two silhouette components, and fingerprint
`e98dcd0f413d8ea56e59f9f2e7feee240c6d9052dbdb9b3e76248e416e47b469`.
Cold onefile extraction and execution took 19.65 seconds with peak RSS
49,938,432 bytes and no swap growth. The binary SHA-256 was
`c220d9dbd57adba2efcca182606fe681d5cbf2048427ade48448272abab81297`.
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
| Bambu Studio 02.07.01.62 | 6 objects, 252 triangles, 5 materials | PASS, exit 0; tools 0–4 all extrude | 6,290 motion commands, 4,926 extrusion moves, 13 tool changes, fingerprint `43f8dc5f9ffb50d601ac1b5daba0d4347ff3cdb2d86458715b9ff7cb49d8ebec` |
| OrcaSlicer 2.4.0 | 6 objects, 252 triangles, 5 materials | PASS, exit 0; tools 0–4 all extrude | 6,697 motion commands, 5,154 extrusion moves, 13 tool changes, fingerprint `08b58a3d5b95295851a990b35aa11bdb0a55da5bf943980af5a096bf13380fc0` |

Toolpath fingerprints exclude comments and blank lines, then hash normalized
motion and tool-change commands. A zero exit without emitted extrusion from
every 3MF-declared tool (0 through 4 here) is a failure. Each slicer ran twice
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
