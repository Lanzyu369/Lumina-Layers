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

Independent fill, stroke, and clip normalization runs concurrently for
documents whose path workload is large enough to benefit. Results, topology
metadata, resource accounting, and failures are committed in original paint
order, so parallel and serial output is byte-for-byte identical. Set
`LUMINA_SVG_REPLAY_THREADS` to a positive integer to force a worker count for
benchmarking or host-level scheduling; requests and automatic selection are
both capped at 16 workers. Otherwise the core selects between one worker and
the available hardware threads from the recorded path workload. Parallel tasks keep shared accounting only for integer overflow and preserve
the same topology trace. If no background worker can be created, the core
replays serially in document order; this is an execution fallback rather than
an input-size admission decision. The ordered clip/composite phase uses the
same accounting. A parallel-only exception discards staged state and performs
one authoritative serial replay.
`NativeResult.replay_worker_count` reports the worker count used by the final
geometry replay.

## Integer print-grid boundaries

`project_regions_to_grid()` is the quantizing projection entry point. It scales
source rings, rounds them to the integer target grid, resolves projected
winding through Clipper2, and exports canonical faces. Use it when geometry
still needs target-grid projection or boolean cleanup.

`canonicalize_grid_regions()` accepts already-valid, integer-grid coverage with
shells oriented positive and holes negative. It does not scale or round the
coordinates, and it uses the shared `BuildFilledFaces` boundary rule without a
second Clipper2 union. This preserves the submitted fill while expressing
point contacts and pinched boundaries as canonical faces. It is intended for
coverage whose paint ownership and overlaps have already been resolved; it is
not a substitute for the projection entry point.

## Desktop resource policy

The desktop engine no longer rejects valid local SVG input because of a
configured byte, element, path, command, CSS, clone-work, or elapsed-time
quota. Parsing and geometry counters remain only to detect integer-size
overflow and invalid numeric state before a C++ container or coordinate cast
would wrap. Actual allocation failures, file errors, malformed XML, invalid
coordinates, unsupported SVG semantics, and real recursion cycles still fail
as whole-document errors.

The geometry kernel records actual Boolean inputs, Clipper work, and returned
output for diagnostics and overflow checks; these counters are not admission
budgets and do not lower CPU parallelism. Raw paths retain the exact
self-intersection and canonical-boundary algorithms, including the #603
integer geometry rules. Operands already canonicalized by Clipper are not
scanned again by a shadow Boolean pass.
Nested axis-aligned rectangle occluders are reduced by an exact containment
proof; all other paints retain normal SVG paint-order compositing. There is no
partial-rendering mode and Lumina does not retry failures through the legacy
parser.

Inputs whose resolved float coordinates, transforms, stroke parameters, or
operation history cannot satisfy the caller's physical tolerance return
`unsupported_input_precision`. Non-finite resolved values, transform/path
cancellation beyond representable numeric precision, and precision-sensitive dashed strokes are
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
host application's public analysis path in a 0.018317-second warm median on the
recorded reference host. Memory and swap are recorded for diagnosis only and
do not reject a valid run; the benchmark keeps only the public-entry time
gates.

## Build

```bash
python -m build --wheel
python -m pytest tests -q
```

The first release targets CPython 3.12 wheels for Windows amd64, macOS arm64
and x86_64, and manylinux x86_64.
