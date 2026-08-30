# Native SVG Fast Path Design

## Summary

Lumina Studio will move its print-oriented SVG geometry preprocessing out of
Python and into a reusable C++ library named `lumina-svg-core`. The library
will combine LunaSVG/PlutoVG for SVG layout and path semantics with Clipper2
for integer polygon operations. Lumina will call the library in-process
through a thin Python extension and will retain the existing `VectorAnalysis`
contract at the application boundary.

The first production milestone targets R4C1-like static vector documents:
filled paths, stroke-only paths, nested transforms, inherited styles, SVG fill
rules, clipping, and ordinary opacity. Unsupported document-level semantics
will cause the whole document to use the existing Python path during the
transition. The native path must never skip an individual element and then
claim success.

## Context

The current SVG path uses `svgelements` and Shapely from Python. Profiling on
the available 55 MB regression SVG shows that time is dominated by Python path
parsing, curve flattening, per-shape polygon construction, and per-shape GEOS
operations. XML I/O is not the dominant cost. A tolerance-only prototype
improved the same file from roughly 10.66 seconds to 8.77 seconds but lost one
region, so tolerance relaxation is neither sufficient nor acceptable.

ChromaPrint3D demonstrates that LunaSVG plus native curve flattening and
Clipper2 can process the original 14.47 MB R4C1 document in roughly
0.31-0.52 seconds on the measured host. Its current conversion semantics are
not directly interchangeable with Lumina: it intentionally skips some
stroke-only and other SVG content, while Lumina-generated SVGs can depend on
stroke-only gap fillers. Lumina therefore needs its own print-layer adapter,
not a wholesale copy of ChromaPrint3D's output policy.

## Goals

1. Process R4C1-like static vector SVG geometry in one second or less for the
   warm median on the same reference host and benchmark procedure.
2. Preserve source colors, visible connected regions, holes, fill rules,
   stroke geometry, transforms, clipping, and draw-order occlusion.
3. Preserve the existing preview, material matching, creative-mode, GLB, and
   3MF behavior through the `VectorAnalysis` boundary.
4. Avoid per-coordinate Python loops and thousands of independent Shapely
   construction/boolean calls in the normal native path.
5. Publish the native geometry engine as a reusable, versioned dependency with
   prebuilt Windows, macOS, and Linux wheels.
6. Make unsupported semantics explicit and deterministic. During migration,
   the whole document falls back; no source element is silently discarded.
7. Keep parity audits and expensive topology comparisons in CI/development,
   not in the user's normal preview or generation path.

## Non-goals

1. This work does not rewrite 3MF export, mesh extrusion, LUT matching, API
   routing, or the frontend in C++.
2. The first release does not promise one-second processing for arbitrary SVG
   filters, animation, scripting, embedded raster images, or arbitrary font
   environments.
3. The first release does not remove the Python parser before the native path
   passes the compatibility corpus.
4. Performance will not be obtained by increasing physical tolerance, dropping
   small regions, deleting holes, or rasterizing an otherwise supported SVG.
5. Production requests will not run a second full parser as a shadow audit.

## Repository and licensing model

The C++ core will live in an independent public repository named
`lumina-svg-core`. Its own code will initially use Apache-2.0 so it can be used
by Lumina under the current GPLv3 license and under a future AGPLv3 license
without relicensing the dependency. LunaSVG and PlutoVG retain their MIT
notices; Clipper2 retains its Boost Software License 1.0 notice. FreeType
derived stroker files shipped by PlutoVG retain their file-level notices.

The repository will include:

- `LICENSE` for `lumina-svg-core`;
- `THIRD_PARTY_NOTICES.md` with exact upstream revisions and licenses;
- a machine-readable dependency lock or CMake revision pins;
- source distributions and platform wheels containing all required notices.

Changing Lumina itself from GPLv3 to AGPLv3 remains a separate product-license
decision. Nothing in this dependency selection blocks that later change.

## Architecture

### 1. Native document front end

LunaSVG loads the document, resolves its viewport/viewBox, inherited styles,
references, element transforms, and computed fill/stroke properties. The
adapter traverses the computed static scene in source draw order and emits a
typed display list. Basic SVG elements are represented as paths after layout.

The front end classifies document capabilities before expensive geometry work.
It returns one of:

- `Supported`: every visible element can be represented by the native print
  model;
- `Unsupported`: a stable reason code identifies a document-level feature
  that requires the legacy path;
- `Invalid`: the SVG itself cannot be parsed or laid out.

`Unsupported` is not a partial success. The caller receives no incomplete
geometry.

### 2. Physical curve flattening and stroke expansion

The adapter computes one source-unit-to-millimetre transform from the resolved
SVG viewport and requested model width. Curve flattening uses the requested
physical tolerance in millimetres divided by that actual scale. It never
assumes a 100-unit SVG width.

Cubic and quadratic curves are subdivided adaptively until their geometric
error is within the physical tolerance. Arcs are converted without fixed
point-count sampling. Fill paths retain their nonzero/even-odd rule. Stroke
paths retain width, joins, caps, miter limit, dash pattern, dash offset, and
the complete accumulated transform before expansion.

### 3. Integer polygon kernel

Flattened coordinates are transformed into model millimetres and quantized to
an `int64` grid whose resolution is derived from the requested physical
tolerance. Clipper2 performs:

- path normalization under the declared fill rule;
- stroke outline cleanup;
- clip-path application;
- union, difference, and intersection operations;
- draw-order occlusion;
- final outer-ring/hole hierarchy construction.

The grid is chosen once per document and checked for overflow. Quantization is
not a second user-visible simplification setting: its maximum displacement is
bounded by the same physical tolerance already used for curve flattening.

Draw-order occlusion uses a spatial index so a shape is compared only with
later shapes whose bounding boxes overlap. Geometry is processed and released
in bounded batches; the implementation does not retain a complete alternate
copy of every intermediate representation.

### 4. Native result contract

The public C++ result is a compact structure-of-arrays representation:

- document bounds and source-to-mm scale;
- flat `int64` coordinate storage plus one document grid-to-millimetre scale;
- ring, polygon, component, and color-layer offsets;
- outer/hole parent relationships;
- RGBA fill/stroke identity and source draw order;
- source-element index and source-kind diagnostics;
- capability and warning reason codes.

The C++ API owns no Python objects. Its public contract is independent of
Lumina, Shapely, 3MF, and printer settings.

### 5. Python binding and Lumina adapter

The Python package `lumina_svg_core` exposes NumPy-compatible buffers through
an in-process pybind11 extension. It releases the GIL during parsing and
geometry work.

Lumina adds one adapter in `core/` that:

1. sends the SVG path, target width, and physical tolerance to the native
   library;
2. maps structured native errors to either legacy fallback or the existing
   invalid-SVG error;
3. bulk-constructs any Shapely objects still required by existing consumers
   using Shapely's vectorized/ragged-array boundary rather than Python loops;
4. returns the same `shape_data`, `clipped_shapes`, silhouette, scale, and
   bounds expected by `VectorAnalysis`.

The API, worker, preview, material matching, large-format, creative-mode,
mesh, and writer layers continue to consume `VectorAnalysis`. No endpoint or
frontend contract changes in the first adoption release.

## Supported semantics for version 0.1

Version 0.1 must support the common static vector semantics already present in
Lumina's generated and reported user SVGs:

- `svg`, `g`, `defs`, `symbol`, and `use` structure;
- `path`, `rect`, `circle`, `ellipse`, `line`, `polyline`, and `polygon`;
- nested affine transforms and viewBox/preserveAspectRatio layout;
- presentation attributes, inline styles, inherited styles, and supported
  stylesheet selectors used by the compatibility corpus;
- solid fill and solid stroke colors with opacity;
- nonzero and even-odd fill rules;
- stroke width, join, cap, miter limit, dash array, and dash offset;
- clip paths that resolve to vector geometry;
- hidden/display-none content and source draw order.

The first release reports `Unsupported` for features that cannot be represented
as discrete printable color regions without a documented policy, including
embedded raster images, arbitrary filters, animation, scripts, and unresolved
external resources. Gradient, mask, pattern, and text behavior must follow the
current Lumina policy: either a proven native conversion with golden coverage
or whole-document fallback. They are never silently flattened or skipped.

## Error and fallback behavior

Native outcomes use stable reason codes, not exception-message parsing:

- `unsupported_feature`: whole-document Python fallback during migration;
- `invalid_svg`: deterministic existing invalid-upload response;
- `external_resource_unavailable`: whole-document Python fallback during
  migration, followed by the existing deterministic resource error if the
  legacy path cannot resolve it;
- `numeric_range_error`: deterministic failure with document diagnostics;
- `internal_error`: logged with the native version and request context, then
  handled by the existing worker boundary.

Fallback is temporary compatibility infrastructure, not the permanent normal
path. Metrics count native success and fallback reason codes without recording
SVG contents. Once the golden corpus demonstrates that all supported product
workflows use the native implementation, a later cleanup release removes the
legacy parser and its fallback branch.

## Correctness verification

The compatibility corpus will contain only repository-safe fixtures or
synthetic reductions. Private user originals remain outside version control.
For each fixture, development/CI checks compare the native and current
reference paths for:

- ordered source color identities;
- visible printable color-layer identities;
- connected component count;
- outer-ring and hole count per component;
- total and per-color physical area;
- symmetric-difference area bounded by the declared physical tolerance;
- no missing component or hole above that same tolerance-derived bound;
- stable results across repeated runs and supported platforms.

Required workflow fixtures cover:

- ordinary filled paths;
- stroke-only gap fillers;
- nested transforms and percentage dimensions with viewBox;
- even-odd and nonzero compound paths;
- clip paths and CSS inheritance;
- overlapping colors and disconnected islands;
- Single/Double-sided generation;
- outline, separate backing, coating, puzzle, keychain, and fridge-magnet
  creative modes;
- material archive and recipe overrides;
- large-format tiling;
- Bambu Studio and OrcaSlicer opening/slicing of representative 3MF outputs.

The original R4C1 file is currently unavailable locally. It must not be
replaced or mislabeled by another fixture. Development proceeds with the
available 55 MB related SVG, `test_images/benchmark.svg`, and synthetic
R4C1-shaped fixtures; the original file is added to private reality validation
when recovered.

## Performance and resource acceptance

Benchmarks separate cold import/build cost from warm document processing.
Results report three or more warm runs, median and range, peak RSS, coordinate
count, region count, and output fingerprint.

Acceptance gates are:

1. R4C1 or an explicitly labeled equivalent 14-15 MB static-path fixture:
   warm median native parse/layout/flatten/clip at or below 1.0 second on the
   reference host used for the comparison report.
2. Across the supported benchmark corpus, the warm median native geometry
   stage is faster than the Python reference; individual tiny fixtures are
   correctness gates rather than timing gates.
3. The available 55 MB regression SVG shows a material speedup and bounded
   peak RSS; no swap exhaustion, worker death, or host instability occurs.
4. Native-to-Python result conversion is measured separately and does not
   recreate a per-coordinate Python hot loop.
5. Preview and 3MF output retain their established visual/geometry quality;
   performance is not accepted if a component, hole, or source color is lost.

The one-second gate is an engineering target for common supported static
vectors, not a promise for every legal SVG document.

## Packaging and release

`lumina-svg-core` uses CMake, pybind11, scikit-build-core, and cibuildwheel.
CI builds and tests:

- Windows x86-64;
- macOS arm64 and x86-64 where the product supports them;
- Linux x86-64 with the product's manylinux baseline;
- supported CPython versions used by Lumina packaging.

The wheel contains the native extension and license notices. Lumina pins an
exact released version in its dependency and desktop/PyInstaller inputs. A
frozen-runtime contract test imports the native extension and processes a
small SVG from the actual `_MEIPASS`-style environment.

## Rollout sequence

1. Build and publish `lumina-svg-core` 0.1 with its standalone C++ and Python
   contract, correctness corpus, benchmarks, and wheels.
2. Integrate the pinned package into Lumina behind one internal adapter while
   retaining whole-document fallback.
3. Run focused, smoke, full, logging, desktop packaging, and real slicer
   validation; publish benchmark and parity evidence.
4. Enable the native path as the default for supported documents without a
   production shadow audit.
5. Expand supported semantics only with a failing golden fixture first.
6. Remove the Python parser only after every legacy fallback reason is either
   implemented natively or routed to the existing raster policy, every golden
   fixture is native, and 30 consecutive grey-release days record no legacy
   parser invocation for a successfully generated document.

## Risks and controls

- **Semantic mismatch:** capability classification and whole-document fallback
  prevent partial native success; golden fixtures precede new support.
- **False performance wins:** benchmarks retain region/hole/color fingerprints
  and physical error bounds.
- **ABI and packaging drift:** exact dependency pins, platform wheels, and
  frozen-runtime tests are release gates.
- **License drift:** pinned third-party revisions and generated notices are
  reviewed with every dependency update.
- **Permanent duplicate implementations:** fallback reasons are measured and
  legacy removal is an explicit rollout stage, not an indefinite architecture.
- **Runtime audit overhead:** parity comparison is confined to development and
  CI; users execute one geometry path.

## Success definition

The work is complete when a released native package is consumed by Lumina,
supported real SVGs use the native path by default, the reference common-case
benchmark reaches the stated target, the correctness corpus and creative-mode
tests pass, representative Bambu/Orca toolpaths remain complete, and no normal
request performs a duplicate parser audit. Legacy removal is complete only
after every fallback reason has a native or raster owner and the 30-day
grey-release gate above passes.
