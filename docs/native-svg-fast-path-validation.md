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
| Proxy identity | SHA-256 `d078cf4293623d934759c2688e13a00491e525055e7595069a0ecc4f078842fb`, 3,767,519 bytes |
| Complete warm runs | 0.523136875 s, 0.524795583 s, 0.525613333 s |
| Warm median / gate | 0.524795583 s / 1.0 s — PASS |
| Warm p95 / gate | 0.525531558 s / 1.25 s — PASS |
| Native recorder | 0.043934375 s median |
| Native kernel | 0.325129125 s median |
| Binding conversion | 0.000003041 s median |
| Shapely adapter conversion | 0.026693917 s median |
| LUT color matching | 0.119133583 s median |
| Peak process RSS | 243,712,000 bytes |
| Measured swap growth | 0 bytes |
| Complete output | 3,097 raw shapes, 4,676 visible/matched shapes, 128,354 coordinates |
| Stable output fingerprint | `e5e5e4472f0470e5a8506304e94d2a1455566c61dad06e5e9f57ba5ce925aafb` |

The proxy is not the real R4C1 document and is not the previously described
55 MB regression document. The real R4C1 fixture was recovered separately:

- SHA-256: `da52ef12bdd37a0bd47970649a70582862331a606c151bff05bfb2f6e265f160`
- Size: 14,467,678 bytes
- Structure: 6,820 paths, including 3,410 stroke-only paths with
  `vector-effect="non-scaling-stroke"`
- Result: `unsupported_vector_effect`, whole-document fallback
- Native-by-default R4C1 release gate: **not ready**

No SVG at or above 50 MiB was found under the local Codex worktrees,
Downloads, Desktop, or Documents roots. The 2 GiB RSS and 256 MiB swap gates
for that separate regression fixture therefore remain pending; neither the
3.77 MB proxy nor the 14.47 MB R4C1 file is substituted for it.

## Packaging evidence

The standalone package built and installed as a clean CPython 3.12 macOS arm64
wheel. Its 52 package tests passed against the installed extension. The sdist
and wheel both contain the complete LunaSVG, PlutoVG, Clipper2, FreeType, and
stb license texts in addition to the Apache-2.0 project license.

A real macOS arm64 PyInstaller onefile binary was built at a temporary output
path and invoked through Lumina's `--native-svg-self-test` public probe. The
probe returned native version `0.1.0`, result schema `1`, one raw geometry, two
visible geometries, two silhouette components, and fingerprint
`692e760e5fc54a88f2844fd6702c2ee940691bdef675a8a23de4ff1963197ae8`.
Cold onefile extraction and execution took 19.80 seconds with peak RSS
51,347,456 bytes and no swap growth.

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
| Bambu Studio 02.07.01.62 | 6 objects, 252 triangles, 5 materials | PASS, exit 0 | 6,249 motion commands, 5,162 extrusion moves, 13 tool changes, fingerprint `28eaadb260b9eaf5a5140db4e62f9f5e0a2f30b210a32a9b5aea828e379105c1` |
| OrcaSlicer 2.4.0 | 6 objects, 252 triangles, 5 materials | PASS, exit 0 | 6,724 motion commands, 5,358 extrusion moves, 13 tool changes, fingerprint `2c8886b64c794555715b99be6a00afba3d4dbee68cd55b3f69363b76b2756c00` |

Toolpath fingerprints exclude comments and blank lines, then hash normalized
motion and tool-change commands. A zero exit without emitted extrusion is a
failure. Each slicer ran twice in separate fresh directories; both Bambu runs
produced the same fingerprint and both Orca runs produced the same fingerprint.
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
- CSS reference semantics, existing legacy stroke policy, unsupported paint
  semantics, and the real R4C1 `non-scaling-stroke` case fall back once for the
  whole document. Production does not run a full shadow audit.
- Publishing the standalone package to a separate GitHub repository and wheel
  index requires an owner/namespace decision. Until then,
  `requirements-native-svg.txt` installs the exact in-tree package. If split,
  publish the standalone library first, replace the workspace requirement with
  `lumina-svg-core==0.1.0`, then land the Lumina integration PR.
- The branch must remain unmerged until PR #585 is available on
  `dev-refactor`, all configured CI reality jobs pass, and blocking independent
  review findings are resolved.
