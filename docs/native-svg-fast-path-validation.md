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

`lumina-svg-core` 0.3.0 exposes result schema 4. A supported document returns:

- raw paint regions, source-order visible paint regions, and one silhouette;
- Polygon/MultiPolygon geometry only, in Lumina's normalized SVG user-unit
  coordinate domain;
- component boundaries and hole parents without flattening them into a union;
- authoritative `float64` straight-sRGB RGBA, compatibility `uint8` RGBA,
  draw order, source index, paint identity, and fill/stroke source kind;
- ordered premultiplied contribution weights for composited translucent
  regions; multi-source regions are explicitly `composite` and never receive
  a fabricated single paint identity;
- immutable, owner-backed NumPy views with fixed dtypes and monotonic offsets.

The result also reports `replay_worker_count` as execution telemetry. It does
not change the result schema or geometry contract; Lumina accepts older schema
4 wheels that do not expose the additive field.

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

Solid fill/stroke alpha and isolated object/group opacity are supported. The
root canvas is transparent, normal source-over is evaluated in sRGB, and group
opacity is applied once after the group's children have been composited. No
white background, filament recipe, or other physical-opacity policy is applied
inside the parser.

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

The alpha path uses a packed bounds index, balanced paint-program evaluation,
and exact internal spatial partitions to avoid all-pairs Boolean work on large
documents without imposing alpha-specific cell or operation count caps. Those
partitions use the same authoritative Clipper integer domain
and are consolidated before export; they are not print-grid snapping and do
not flatten component/hole hierarchy. Opaque documents continue through the
original reverse-occlusion fast path.

Independent fill, stroke, and clip-path normalization is scheduled across
native workers when the recorded path workload is large enough to repay thread
startup and result staging. Each worker owns its Clipper state, resource
accounting, and topology trace, while aggregate gates enforce the same document
budget and the same pre-allocation peaks for Boolean inputs, safety indexes,
offset transients, and actual Clipper engine allocations. Geometry, counters,
and topology are then committed in original command order before clipping and
compositing, so serial and parallel execution have the same byte-level output
contract. If a parallel task or aggregate gate fails, or no background worker
can be created, staged capacity is released and normalization is replayed in
document order. A partially created worker pool continues at its actual size.
That makes the serial result and failure reason authoritative.
Small or simple documents stay on the original serial path and do not allocate
the parallel staging buffer. `LUMINA_SVG_REPLAY_THREADS` can force a positive
worker count for deterministic differential testing and host-level scheduling;
forced and automatic selection are capped at 16 workers.

Clipper input and geometric point estimates are checked per operation. The
fixed Clipper patch checks actual output-point allocations, output-record
allocations, intersection-node allocations, and every processed intersection
inside the engine before accepting each allocation or event. Document counters
charge actual Boolean inputs, safety-index work, engine work, and returned
output; they do not reserve a theoretical output-ring count. Already canonical
Clipper operands are not scanned a second time by a shadow intersection
implementation. The fixed
dependency patches are validated with `git apply --check`, reverse-check an
already patched source, and are compared byte-for-byte with the complete
dependency diffs after the build.

Same-document `<use>` expansion is preflighted recursively before LunaSVG
allocates clone trees. The budget counts reparsed target attributes, nested
references, and ancestor-sensitive cycles while still allowing ordinary large
reuse. Runtime shadow children generated by a built `<use>` are tagged and are
not recopied as authored source DOM; this prevents nested wrapper reuse from
drawing the same target twice. Known unsupported semantics keep their original
whole-document fallback reason without first amplifying their clone trees.

## Local verification

Reference host: Apple M5, arm64, 16 GiB RAM, macOS 26.5.2, CPython
3.12.13, Release build, one caller thread with automatic native replay
workers.

| Gate | Result |
|---|---:|
| Fresh fixed-patch native build | PASS |
| macOS 12.0 arm64 wheel build/install/runtime verification | PASS |
| Standalone native suite from clean macOS 12 wheel | 595 passed; also 595 with 4 forced replay workers |
| Former-alpha corpus through the Lumina adapter | 31 / 31 native supported |
| Native differential/adapter/VectorAnalysis/packaging suite | 182 passed |
| Lumina workflow integration | 10 passed |
| Product smoke | backend 168 passed; frontend 168 passed; lint 0 errors |
| Structured logging fast gate | PASS |
| Independent parser review | PASS; no Critical / Important / Minor findings |
| `git diff --check` | PASS |

The pre-alpha review found that cross-operand Boolean output could exceed the
preflight ring estimate before the post-check ran. The correction moves the
hard point/record/intersection-node/processed-intersection caps inside the
pinned Clipper engine and retains document-wide actual-work accounting without
restoring a production shadow intersection pass. The independent alpha
re-review then verified the fragment RGBA, case-insensitive color functions,
raw/visible provenance reconstruction, complete raster-audit gate, and
alpha-heavy public benchmark corrections; it reported no remaining finding.

## Anonymous 508-document corpus

The checked-in report is `progress/native-svg-508-corpus-audit.json`. Every
document is identified only as `svg-NNNNNN`. The run uses a 220 mm target width
to represent the common user-selected output size, a 0.02 mm physical
tolerance, and includes stroke paint.

| Metric | Result |
|---|---:|
| Documents | 508 |
| Supported / unsupported / invalid | 508 / 0 / 0 |
| Input paints | 1,804,382 |
| Raw / visible output paints | 1,799,360 / 1,225,406 |
| Raw / visible components | 1,990,826 / 1,385,149 |
| Raw / visible holes | 1,584,383 / 298,899 |
| Partial-alpha raw / visible paints | 65,589 / 238,138 |
| Composite visible paints / contributors | 259,604 / 1,800,972 |
| Unprintable fragments | 16,966 |
| Unprintable reasons | line-only 3,873; area-collapse 11,944; fill-rule-cancelled 1,149 |
| Unsupported reasons | none |
| Supported documents with unexplained raw-paint loss | 0 |
| Maximum visible-partition area delta | 22.174935 source-unit²; 1.1116364e-5 relative |
| Median / p95 / maximum document time | 2.3551 s / 15.5736 s / 245.2340 s |
| Total time / observed peak process RSS | 2,648.3066 s / 1,852,047,360 bytes (1,766.25 MiB) |

`raw_to_visible_area_delta` is expected to be non-zero where later paints
occlude earlier paints. `visible_partition_area_delta` compares the sum of all
source-order visible cells with the exported silhouette and therefore exposes
partition overlap or loss instead of confusing ordinary occlusion with lost
geometry. Explicit unprintable fragments remain separate from both values. No
supported document loses more raw paints than its recorded unprintable
fragment count can explain.

All 31 documents that previously returned `unsupported_partial_alpha` now
complete natively. They were also passed through the real Lumina adapter after
the corpus run: all 31 retained non-empty raw and visible Polygon/MultiPolygon
geometry and a non-empty silhouette. Composite area-collapse diagnostics use
`source_kind="composite"` with no fabricated paint ID, so a diagnostic-only
cell cannot make an otherwise printable SVG fail at the adapter boundary.

The longest corpus case contains 69,692 paint operations and took 245.23
seconds at 220 mm. This is an explicitly recorded large-document Boolean-union
tail, not a fallback or timeout. Median and p95 show the ordinary corpus
distribution; the public-entry benchmark below is the release latency gate.

On a separate normalization-heavy fixture with 96 disjoint alternating-radius
paints and 720 points per paint, nine interleaved warm runs reduced median
replay time from 0.036597 s with one worker to 0.008315 s with automatic
10-worker selection (4.40x). The complete native call fell from 0.220182 s to
0.191597 s (13.0%). One, two, four, and automatic-worker runs retained the
same 96 paints/components and byte-identical geometry/color snapshots.
Documents dominated by ordered visibility compositing are not represented as
gaining this full speedup.

### Transparent raster differential

The checked-in `progress/native-svg-alpha-raster-audit.json` selects the same
31 anonymous documents that formerly fell back for partial alpha. For each
document, the original SVG and the native visible-region reconstruction are
rendered on a transparent sRGB canvas with the same fixed LunaSVG renderer.
Only the tolerance-derived boundary band is excluded from the strict interior
comparison.

| Metric | Result |
|---|---:|
| Selected / measured | 31 / 31 |
| Matched / mismatch / unsupported | 31 / 0 / 0 |
| Maximum interior channel error | 0 (8-bit RGBA) |
| Interior coverage disagreement | 0 pixels |
| Total audit time | 116.5336 s |

The reconstruction serializes exact alpha as `rgba(...)`. Splitting that
value into an opaque color plus `fill-opacity` would take a different 8-bit
rounding path inside LunaSVG and create a false 2–3-level raster difference.
The analytical source-over fixture independently checks exact `float64` RGBA
and ordered contributor weights, so the raster audit is not used to redefine
the parser's color contract.

Reproduce the anonymous audit with:

```bash
PYTHONPATH=/path/to/installed/package:. python \
  native/lumina-svg-core/tools/corpus_audit.py \
  --corpus /path/to/anonymous-corpus \
  --output progress/native-svg-508-corpus-audit.json \
  --target-width-mm 220 \
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
| Warm median / 1.0 s gate | 0.116923 s / PASS |
| Warm p95 / 1.25 s gate | 0.118606 s / PASS |
| Native recorder / kernel | 0.049111 s / 0.038086 s |
| Native adapter conversion | 0.024259 s |
| Observed peak RSS / swap growth | 203,882,496 bytes (194.44 MiB) / 0 bytes |
| Raw / visible shapes | 1,024 / 1,024 |

RSS and swap remain in the report for diagnosis only. They are not pass/fail
gates for this personal-device workflow; only the complete public-entry time
thresholds above are enforced.

The same report measures a separate alpha-heavy public fixture with 32 source
paints, two isolated opacity groups, 256 overlap cells, and 1,024 ordered
contributions. Its complete `VectorAnalysis` median/p95 is 0.018317/0.018362 s,
with 148,422,656 bytes observed peak RSS and zero swap growth. It exports 768
visible Polygon components, including 256 multi-source composite regions.

The public 3,097-path source proxy is also supported by default; its native
capability check took 0.409056 s. No repository SVG at or above 50 MiB was
available, so the separate large-file benchmark is recorded as unavailable
instead of substituting another fixture. The anonymous 508-document run above
is the large real-world parser evidence for this revision.

The reproducible performance fixture is public and synthetic. It is not
presented as a private production source. If a private or large regression
input is not supplied, the benchmark records it as unavailable instead of
reusing an older parser result or substituting another file.

## Native wheels and hosted validation

The standalone source tree contains the Apache-2.0 project license and complete
third-party notices for LunaSVG, PlutoVG, Clipper2, FreeType, stb, and pybind11.
Release wheels target CPython 3.12 on Windows amd64, macOS arm64, macOS x86_64,
and Linux x86_64. Linux wheels are built directly on Ubuntu 24.04 with its
system ABI; older glibc compatibility requires a source build. The production
workflow verifies host Linux product artifacts and the native SVG self-test.

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
