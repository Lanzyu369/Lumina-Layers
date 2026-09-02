# lumina-svg-core

`lumina-svg-core` is an Apache-2.0, print-oriented native SVG geometry engine.
It uses a fixed LunaSVG/PlutoVG layout front end and Clipper2 integer polygon
kernel, then exposes immutable NumPy-compatible buffers through pybind11.

The package is developed temporarily inside the Lumina Studio workspace. Its
directory is deliberately self-contained so it can become an independent repository
without importing application, printer, mesh, or UI code.

Version 0.2 supports static solid fills, solid strokes, affine transforms,
fill rules, vector clips, CSS selectors, same-document `<use>` references,
basic shapes (including circles, ellipses, and rounded rectangles), SVG path
arcs, nested SVG viewports, root layout/transform semantics, marker paint and
marker viewport clipping, and source-order occlusion. It preserves exact
resolved RGBA plus stable paint/source identity in schema 3. Ambiguous document
semantics return a stable whole-document unsupported result; no element is
silently dropped.

`analyze_svg()` and `analyze_svg_svg()` accept an optional `allow_strokes`
boolean (default `True`). Callers that must preserve a separate legacy stroke
policy can pass `False`; the core then removes stroke paint operations while
preserving fills from the same document.
Dash arrays containing a zero-length entry return
`unsupported_zero_length_dash` in 0.2 because exact zero-interval cap and
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
identity, without failing unrelated paint operations.

The recorder resolves non-zero root viewBox origins, root positions and
transforms, percentage lengths, inherited `clip-rule`, nested viewport
transforms/clips, and marker overflow before emitting paint commands. Features
that still need raster compositing or external resources, such as partial
alpha, masks, gradients/patterns, text, and images, return a stable
`unsupported_*` result for the complete document.

`PaintStrokeStyle.line_cap` and `.line_join` are stable lowercase strings.
`NativeResult.result_conversion_seconds` measures only creation of the Python
wrapper around the owned C++ result; NumPy view creation and Lumina's one
bulk int64-to-float64/Shapely conversion are measured by the Lumina adapter.

## Fail-closed resource and precision policy

Version 0.2 keeps only hard resource boundaries needed to avoid unbounded
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

The geometry kernel checks integer overflow, curve-generation work, and the
measured candidates plus actual input/output size of Clipper operations.
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

## Build

```bash
python -m build --wheel
python -m pytest tests -q
```

The first release targets CPython 3.12 wheels for Windows amd64, macOS arm64
and x86_64, and manylinux x86_64.
