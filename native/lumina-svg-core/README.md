# lumina-svg-core

`lumina-svg-core` is an Apache-2.0, print-oriented native SVG geometry engine.
It uses a fixed LunaSVG/PlutoVG layout front end and Clipper2 integer polygon
kernel, then exposes immutable NumPy-compatible buffers through pybind11.

The package is developed temporarily inside the Lumina Studio workspace. Its
directory is deliberately self-contained so it can become an independent repository
without importing application, printer, mesh, or UI code.

Version 0.1 supports static solid fills, solid strokes, affine transforms,
fill rules, vector clips, and source-order occlusion. Ambiguous document
semantics return a stable whole-document unsupported result; no element is
silently dropped. SVG arc path commands, circles, ellipses, and rounded
rectangles also return `unsupported_arc` in 0.1 because LunaSVG's resolved
path currently exposes only a fixed cubic approximation rather than the
original arc parameters needed to honor Lumina's physical error budget.

`analyze_svg()` and `analyze_svg_svg()` accept an optional `allow_strokes`
boolean (default `True`). Callers that must preserve a separate legacy stroke
policy can pass `False`; the recorder then returns
`unsupported_stroke_policy` before running the geometry kernel.
Dash arrays containing a zero-length entry return
`unsupported_zero_length_dash` in 0.1 because exact zero-interval cap and
phase parity is not yet proven for every open, closed, and degenerate path.
Other dash placement uses an adaptive centerline length bound; if the one
document-level physical error budget cannot be proved, the complete document
returns `unsupported_input_precision` or `unsupported_topology_collapse`.

The optional `legacy_close_delta_source_units`,
`legacy_minimum_paint_area_factor`, and
`legacy_component_area_source_units_squared` arguments are versioned adopter
compatibility gates; zero disables the corresponding gate. Area classification
accounts for recorder/input precision, flattening, integer-grid quantization,
and downstream simplification together. If an enabled raw-paint or component
threshold cannot be classified with certainty, the complete document returns
`legacy_area_threshold_ambiguous` with empty geometry collections.

The 0.1 recorder deliberately rejects nested `<svg>`, non-zero root viewBox
origins, root transforms/positions, root `overflow="hidden"`, percentages
without a root viewBox, and inherited `clip-rule` outside a direct clip-path
geometry child. These restrictions have stable `unsupported_*` reason codes
and preserve current Lumina behavior through whole-document fallback. They
must not be interpreted as partially supported layout.

`PaintStrokeStyle.line_cap` and `.line_join` are stable lowercase strings.
`NativeResult.result_conversion_seconds` measures only creation of the Python
wrapper around the owned C++ result; NumPy view creation and Lumina's one
bulk int64-to-float64/Shapely conversion are measured by the Lumina adapter.

## Fail-closed resource and precision policy

Version 0.1 rejects a complete document with `unsupported_complexity` before
unbounded parser, path expansion, topology, Boolean-composition, or result
allocation work. The current package limits one input to 64 MiB, 250,000 XML
elements, 128 levels of XML nesting, 16 `<use>` elements, 250,000 recorded
paint commands, 4,000,000 recorded path verbs, and 8,000,000 recorded points.
The geometry kernel additionally applies cumulative limits to generated points
and rings, topology segments, Boolean input points, distinct overlap pairs, and
returned coordinates. These are safety limits rather than a partial-rendering
mode: exceeding any one of them returns no native geometry and asks Lumina to
run the existing whole-document fallback.

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
