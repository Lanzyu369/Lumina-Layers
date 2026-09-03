# lumina-svg-core

`lumina-svg-core` is an Apache-2.0, print-oriented native SVG geometry engine.
It uses a fixed LunaSVG/PlutoVG layout front end and Clipper2 integer polygon
kernel, then exposes immutable NumPy-compatible buffers through pybind11.

The package is developed temporarily inside the Lumina Studio workspace. Its
directory is deliberately self-contained so it can become an independent repository
without importing application, printer, mesh, or UI code.

Version 0.3 supports static solid fills, solid strokes, affine transforms,
fill rules, vector clips, CSS selectors, same-document `<use>` references,
basic shapes (including circles, ellipses, and rounded rectangles), SVG path
arcs, nested SVG viewports, root layout/transform semantics, marker paint and
marker viewport clipping, source-order compositing, solid-paint alpha, and
isolated object/group opacity. Result schema 4 preserves authoritative
`float64` straight-sRGB RGBA, compatibility `uint8` RGBA, stable paint/source
identity, and ordered premultiplied contribution weights. The SVG root starts
transparent; no white or printer-material matte is introduced. Ambiguous
document semantics return a stable whole-document unsupported result; no
element is silently dropped.

`analyze_svg()` and `analyze_svg_svg()` accept an optional `allow_strokes`
boolean (default `True`). Callers that must preserve a separate legacy stroke
policy can pass `False`; the core then removes stroke paint operations while
preserving fills from the same document.
Dash arrays containing a zero-length entry return
`unsupported_zero_length_dash` in 0.3 because exact zero-interval cap and
phase parity is not yet proven for every open, closed, and degenerate path.
Other dash placement uses an adaptive centerline length bound; if the one
document-level physical error budget cannot be proved, the complete document
returns `unsupported_input_precision`. Individual stroke rings that collapse
on the authoritative parser grid are reported as `stroke_collapse` fragments
without discarding unrelated area-bearing paint operations.

The parser performs no morphological close, print-grid snapping, minimum-area
filter, triangulation, or mesh repair. Every area-bearing paint is exported as
Polygon/MultiPolygon data. Empty paths, point/line-only subpaths, and numeric
area collapses are excluded from those collections and reported separately in
`NativeResult.unprintable_fragments` with exact RGBA and stable paint/source
identity, without failing unrelated paint operations. A visible region formed
from several translucent paints has no fabricated single owner: its source and
draw indices are `-1`, its source kind is `composite`, and its complete ordered
contributor list is authoritative.

The recorder resolves non-zero root viewBox origins, root positions and
transforms, percentage lengths, inherited `clip-rule`, nested viewport
transforms/clips, and marker overflow before emitting paint commands. Features
that still need unimplemented raster semantics or external resources, such as
masks, gradients/patterns, text, images, non-normal blend modes, and non-sRGB
color interpolation, return a stable
`unsupported_*` result for the complete document.

`PaintStrokeStyle.line_cap` and `.line_join` are stable lowercase strings.
`NativeResult.result_conversion_seconds` measures only creation of the Python
wrapper around the owned C++ result; NumPy view creation and Lumina's one
bulk int64-to-float64/Shapely conversion are measured by the Lumina adapter.

## Fail-closed resource and precision policy

Version 0.3 keeps only hard resource boundaries needed to avoid unbounded
allocation or recursion: one input is limited to 256 MiB, 250,000 XML elements,
250,000 XML attributes, 64 MiB of attribute text, and 128 levels of XML
nesting; the recorder is limited to 250,000 paint commands, 16 million path
verbs, 16 million path points, and 1 million dash values. Streaming parser
counters stop oversized path, point-list, transform, CSS, and XML work before
large intermediate allocations. They count actual parsing work rather than
guessing whether ordinary SVG structure might be expensive. Encoding and
namespace checks are limited to XML correctness, not document identity.
Before the first same-document `<use>` expansion, the recorder totals the
attribute bytes and recursive expansion work of all statically resolvable
references. Repeated targets are cached together with their ancestor-cycle
context. Generated `<use>` shadow children are not recopied as source DOM; the
running counter remains a backstop for every actual clone. Documents already
known to use unsupported SVG semantics skip clone expansion.

The geometry kernel checks integer overflow, curve-generation work, and each
Clipper operation's input and geometric point estimate. The pinned Clipper
patch checks actual output-point allocations, output-record allocations,
intersection-node allocations, and every processed intersection inside the
engine before each allocation or event is accepted. Document counters charge
actual Boolean inputs, safety-index work, engine work, and returned output
rather than a theoretical output-ring count.
Raw paths retain a bounded self-intersection preflight; operands already
canonicalized by Clipper are not scanned again by a shadow Boolean pass.
Nested axis-aligned rectangle occluders are reduced by an exact containment
proof; all other paints retain normal SVG paint-order compositing. A genuine
resource failure returns empty native geometry with `unsupported_complexity`;
none is a partial-rendering mode and Lumina does not retry it through the
legacy parser.

Inputs whose resolved float coordinates, transforms, stroke parameters, or
operation history cannot satisfy the caller's physical tolerance return
`unsupported_input_precision`. Non-finite resolved values, transform/path
cancellation beyond the budget, and precision-sensitive dashed strokes are
handled the same way. Duplicate nonempty XML `id` values return
`unsupported_duplicate_id`, because reference selection would otherwise be
ambiguous. All three reasons preserve the same whole-document fallback
contract as other unsupported SVG semantics.

For documents containing partial alpha, the kernel partitions only intersecting
integer-grid regions, applies normal source-over compositing in premultiplied
sRGB, and applies isolated group opacity once after rendering that group. A
packed bounds index and exact internal spatial partitions keep Boolean work
local without alpha-specific cell or operation count caps; final output is
consolidated back into ordinary Polygon/MultiPolygon regions with component and
hole hierarchy intact. These partitions are an
implementation detail, not a second coordinate domain or a printer-resolution
grid. Fully opaque documents retain the existing reverse-occlusion fast path.

The implementation also incorporates the useful structural lesson from
[ChromaPrint3D](https://github.com/neroued/ChromaPrint3D): keep parsing and
Boolean geometry in C++ and spatially prune paint-order occlusion work. It does
not copy that project's opaque-only occlusion approximation or private
LunaSVG-scene-tree dependency. Lumina's recorder is versioned, includes fill
and stroke paint operations, and preserves exact RGBA, source identity,
source-over/group-opacity semantics, components, and holes.

The checked-in 508-document anonymous audit reports 508 native successes and
no unsupported or invalid documents. A separate transparent-canvas raster
differential re-renders all 31 former partial-alpha fallbacks with the pinned
LunaSVG renderer; all 31 match with zero interior RGBA error and zero interior
coverage disagreement. Private SVG inputs, source paths, and source hashes are
not stored in either report.

The public-entry benchmark also includes a synthetic alpha-heavy case with 32
source paints and 256 overlap cells. It completes the full Lumina
host application's public analysis path in a 0.017911-second warm median on the
recorded reference host; this measurement is observational and adds no
alpha-specific rejection threshold.

## Build

```bash
python -m build --wheel
python -m pytest tests -q
```

The first release targets CPython 3.12 wheels for Windows amd64, macOS arm64
and x86_64, and manylinux x86_64.
