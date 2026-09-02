# Native SVG parser validation for PR #588

## Scope

PR #588 replaces the supported SVG parsing and visible-geometry path with the
native `lumina-svg-core` package. Its responsibility ends at canonical 2D
paint regions. It does not implement material matching, recipe selection,
triangulation, mesh repair, 3MF writing, or printer-grid cleanup.

The topic branch was cut from the requested PR #585 base and later received
the final PR #585 head through an ordinary merge. The native work remains on a
separate topic branch and must not be merged automatically.

Private validation inputs are not committed. The anonymous corpus report does
not record source paths, hashes, or file sizes.

## Parser contract

`lumina-svg-core` 0.2.0 exposes result schema 3. A supported document returns:

- raw paint regions, source-order visible paint regions, and one silhouette;
- Polygon/MultiPolygon geometry only, in Lumina's normalized SVG user-unit
  coordinate domain;
- component boundaries and hole parents without flattening them into a union;
- exact `uint8` RGBA, draw order, source index, paint identity, and fill/stroke
  source kind;
- immutable, owner-backed NumPy views with fixed dtypes and monotonic offsets.

The parser never sends LineString, Point, empty geometry, or an area-collapsed
ring through the polygon collections. Those cases are reported separately as
`empty_path`, `point_only`, `line_only`, `area_collapse`,
`fill_rule_cancelled`, `clipped_out`, or `stroke_collapse`. A collapsed
subpath does not discard valid area from the same SVG.

If ordinary error-bounded curve flattening reduces an area-capable closed
Bezier to coincident or collinear samples, the kernel deterministically
replays that source boundary at finer subdivision before classifying it. This
keeps mathematically non-zero regions as polygons on both macOS architectures
while true point, line, and zero-area paths remain fragment records. It is a
source-geometry recovery step, not minimum-area filtering or printer-grid
cleanup.

Unsupported document semantics still request one whole-document legacy
fallback. This is distinct from an unprintable geometric fragment: unsupported
paint semantics cannot be combined safely with a partial native rendering,
while an independently classified point/line/collapse can be omitted without
changing any area-bearing paint.

The Lumina adapter performs one ragged-array conversion to Shapely. Native
results are marked already normalized, so they do not enter the legacy
`_normalize_contours_many` close/open path, a second GEOS union, `make_valid`,
or per-ring repair. The parser and adapter do not apply print-grid snapping,
minimum-area filters, or proximity grouping.

## Native implementation

The standalone Apache-2.0 package uses a fixed LunaSVG revision and its bundled
PlutoVG, plus a fixed Clipper2 revision. The LunaSVG change is a narrow,
versioned paint-command recorder; the native package does not consume LunaSVG's
private scene tree.

Paths and basic geometry are decoded into double-precision source coordinates.
Fill rules, clips, transforms, paint order, exact colors, basic length units,
percentage axes, path arcs, markers, strokes, and component/hole hierarchy are
covered by focused regressions. Strokes expand in the required coordinate
space before the complete affine transform is applied. One physical tolerance
budget is shared across decoding, curve lowering, transforms, integer-grid
quantization, stroke expansion, and Boolean operations.

Clipper work and output limits are checked both per operation and against the
remaining document budget before result allocation. The fixed LunaSVG patch is
validated with `git apply --check`, reverse-checks an already patched source,
and compares the complete dependency diff after the build.

## Local verification

Reference host: Apple M5, arm64, 16 GiB RAM, macOS 26.5.2, CPython
3.12.13, Release build, one caller thread.

| Gate | Result |
|---|---:|
| Fresh fixed-patch native build | PASS |
| Standalone native suite | 541 passed |
| Lumina adapter/differential/workflow suite | 175 passed, 3 skipped |
| Independent parser review | Ready: Yes; no blocking findings |
| `git diff --check` | PASS |

The three skipped Lumina tests require an external diagnostic asset that is not
present in this worktree. They are not parser failures.

The independent final review re-ran the previously blocking marker precision,
`%`/`px` shared-boundary, document-output budget, non-square percentage
ellipse, canonical touching-ring export, and cross-operand Boolean cases
against a fresh extension built from the checked-in dependency patch. It also
confirmed that the diff does not touch material matching, recipes, mesh
construction, or 3MF implementation. Its final assessment is `Ready: Yes`.

## Anonymous 508-document corpus

The checked-in report is `progress/native-svg-508-corpus-audit.json`. Every
document is identified only as `svg-NNNNNN`. The run uses a 100 mm target width,
a 0.02 mm physical tolerance, and includes stroke paint.

| Metric | Result |
|---|---:|
| Documents | 508 |
| Supported / unsupported / invalid | 474 / 34 / 0 |
| Input paints | 1,804,382 |
| Raw / visible output paints | 1,556,001 / 840,928 |
| Raw / visible components | 1,709,605 / 877,173 |
| Raw / visible holes | 1,325,305 / 209,395 |
| Unprintable fragments | 4,272 |
| Unprintable reasons | line-only 3,192; area-collapse 109; fill-rule-cancelled 971 |
| Unsupported reasons | partial-alpha 31; complexity 3; internal errors 0 |
| Supported documents with unexplained raw-paint loss | 0 |
| Maximum visible-partition area delta | 1.3893777 source-unit²; 4.1888571e-8 relative |
| Median / p95 / maximum document time | 1.2254 s / 13.4907 s / 87.6094 s |
| Total time / peak process RSS | 1,739.3509 s / 1,156,841,472 bytes (1,103.25 MiB) |

`raw_to_visible_area_delta` is expected to be non-zero where later paints
occlude earlier paints. The loss detector is
`visible_partition_area_delta`: the sum of source-order visible regions must
equal the exported silhouette area within the shared integer-grid error. The
largest relative delta is 4.19e-8; a direct Shapely union check of that case
matched the silhouette within 6.20e-10 mm² and showed that the reported source
area delta is sub-grid overlap, not missing coverage. Explicit unprintable
fragments remain separate from both values. All 10 documents previously
reported as `native_geometry_error` are supported after canonical export, and
no supported document loses more raw paints than its recorded unprintable
fragment count can explain.

Compared with the preceding architecture-dependent build, deterministic
collapsed-curve replay recovered 52 raw paints and 58 raw components. Of the
591 former `area_collapse` records, 541 are now correctly identified after
replay as `fill_rule_cancelled`, while the remaining net reduction of 50
fragment records corresponds to recovered area-bearing paint. Supported,
unsupported, and invalid document counts are unchanged; the worst visible
partition error is also unchanged.

Reproduce the anonymous audit with:

```bash
PYTHONPATH=/path/to/installed/package:. python \
  native/lumina-svg-core/tools/corpus_audit.py \
  --corpus /path/to/anonymous-corpus \
  --output progress/native-svg-508-corpus-audit.json \
  --target-width-mm 100 \
  --tolerance-mm 0.02
```

## Public-entry performance

`progress/native-svg-fast-path-benchmark.json` measures the complete
`VectorProcessor.analyze_svg` call through a full `VectorAnalysis`, including
native recording/kernel work, NumPy/Shapely conversion, orchestration, and
color matching. It clears the in-memory parse/clip cache before each run and
does not use an artifact cache.

| Metric | Result |
|---|---:|
| Warm median / 1.0 s gate | 0.107978 s / PASS |
| Warm p95 / 1.25 s gate | 0.111877 s / PASS |
| Native recorder / kernel | 0.048624 s / 0.043982 s |
| Native adapter conversion | 0.009439 s |
| Peak RSS / swap growth | 192,741,376 bytes (183.81 MiB) / 0 bytes |
| Raw / visible shapes | 1,024 / 1,024 |

The public 3,097-path source proxy is also supported by default; its native
capability check took 0.519444 s. No repository SVG at or above 50 MiB was
available, so the separate large-file benchmark is recorded as unavailable
instead of substituting another fixture. The anonymous 508-document run above
is the large real-world parser/RSS evidence for this revision.

The reproducible performance fixture is public and synthetic. It is not
presented as a private production source. If a private or large regression
input is not supplied, the benchmark records it as unavailable instead of
reusing an older parser result or substituting another file.

## Packaging and hosted validation

The standalone source tree contains the Apache-2.0 project license and complete
third-party notices for LunaSVG, PlutoVG, Clipper2, FreeType, stb, and pybind11.
Release wheels target CPython 3.12 on Windows amd64, macOS arm64, macOS x86_64,
and manylinux x86_64. The production workflow also verifies a Docker build and
a Windows PyInstaller onefile native self-test.

The previous published PR head completed all configured hosted checks. A fresh
workflow run is required after this parser update; its final state belongs in
the PR report rather than being predicted here.

## Explicit boundaries

- Exact SVG RGBA and source/paint identity are parser metadata; the parser does
  not infer filament recipes or call MaterialVectorMatcher/Lab/KDTree code.
- Component and hole hierarchy are SVG geometry semantics. Physical dust
  removal, writer-grid grouping, triangulation, watertight repair, and 3MF
  generation remain downstream responsibilities.
- No full production shadow audit is retained. Supported documents use the
  native result; unsupported semantics request one whole-document fallback.
- Publishing `lumina-svg-core` from a separate repository or package index
  still requires an owner/namespace decision. The in-tree package remains
  independently buildable until that publication boundary is chosen.
