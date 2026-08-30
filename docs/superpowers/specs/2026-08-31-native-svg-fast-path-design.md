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
rules, clipping, and effective alpha values of zero or one. Unsupported
document-level semantics will cause the whole document to use the existing
Python path during the transition. The native path must never skip an
individual element and then claim success.

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

### 1. LunaSVG integration and native document front end

The initial implementation pins a maintained LunaSVG fork starting from
upstream commit `59690a23981489acc3f73b8db229ef57bb69c544`. The fork adds one
narrow, versioned paint-command recorder at LunaSVG's actual render traversal
boundary; `lumina-svg-core` does not reach directly into unversioned private
classes from its main conversion code. The recorder emits computed fill,
stroke, transform, clip push/pop, group boundaries, paint order, and source
element identity after LunaSVG has resolved viewport/viewBox, inheritance,
references, and layout.

The fork also records every unknown or unsupported element, property, CSS
rule, paint server, and external resource while parsing/layout occurs. The
adapter completes this capability scan before returning any geometry. A
feature that LunaSVG would otherwise ignore therefore makes the whole native
document `Unsupported` instead of disappearing silently. Upgrade contract
tests run the same capability and paint-command fixtures whenever the pinned
LunaSVG revision changes. The recorder is kept as a small upstreamable patch;
if upstream accepts an equivalent stable API, the fork is retired.

The adapter turns the recorded static display list into print paint
operations in exact source order. Basic SVG elements are represented as paths
after layout. Fill and stroke are distinct paint operations rather than one
combined shape.

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
error is within their allocated physical error budget. Arcs are converted
without fixed point-count sampling. The conversion from a global physical
tolerance to a local path tolerance includes the largest singular value of
the accumulated affine transform, so non-uniform scale and shear cannot
silently loosen the model-space error bound.

Fill paths retain their nonzero/even-odd rule. Stroke width, dashes, joins,
caps, and miter limits are expanded in the path's local coordinate system,
then the completed outline receives the full affine transform. Explicit
`vector-effect`, marker geometry, unsupported `paint-order`, partial effective
alpha, and group opacity that produces partial alpha cause whole-document
fallback in version 0.1. Effective alpha zero is invisible; effective alpha
one is accepted. This keeps reverse draw-order occlusion valid for the first
release.

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
not a second user-visible simplification setting. One document-level physical
error budget is divided as follows: at most 40% for curve flattening, at most
20% for integer quantization, and at least 40% reserved for the existing
post-analysis normalization/simplification stages. The measured end-to-end
boundary displacement must remain within the original requested physical
tolerance. Topology tests additionally reject any budget allocation that
collapses a component, hole, or separating gap which survives the current
reference implementation.

Draw-order occlusion uses a spatial index so a shape is compared only with
later shapes whose bounding boxes overlap. Geometry is processed and released
in bounded batches; the implementation does not retain a complete alternate
copy of every intermediate representation.

### 4. Native result contract

The public C++ result is a compact structure-of-arrays representation with
three explicit geometry collections: raw paint geometry before occlusion,
visible geometry after occlusion, and the final silhouette. It contains:

- original document bounds, analysis origin, and source-to-mm scale;
- flat `int64` internal-grid coordinates plus grid-to-source-unit scale;
- ring, polygon, component, and color-layer offsets;
- outer/hole parent relationships;
- RGBA fill/stroke identity and source draw order;
- source-element index and source-kind diagnostics;
- capability and warning reason codes.

All exported geometry is converted back to the same normalized SVG analysis
domain used by the current parser: `bbox` remains `(gx0, gy0, real_w,
real_h)` in original SVG user units, geometry is shifted by `(-gx0, -gy0)`,
and `scale_factor` remains `target_width_mm / real_w`. The internal millimetre
grid is never exposed as a competing Lumina coordinate authority. In
particular, PR #585's `LayeredCoordinateDomain` remains the only authoritative
post-analysis grid; large-format tiling continues to use
`tile_mm / scale_factor` exactly once.

The C++ API owns no Python objects. Its public contract is independent of
Lumina, Shapely, 3MF, and printer settings.

### 5. Python binding and Lumina adapter

The Python package `lumina_svg_core` exposes read-only NumPy-compatible buffers
through an in-process pybind11 extension. Coordinates use `int64`, offsets use
`uint64`, colors use `uint8`, and draw/source indices use `int32`. Ring closure,
empty collections, parent indices, and collection offsets are part of the
versioned schema. Each zero-copy view retains a shared native result through a
pybind capsule; it cannot outlive or mutate its backing storage. Checked size
arithmetic precedes every allocation. The extension releases the GIL during
parsing and geometry work.

Lumina adds one adapter in `core/` that:

1. sends the SVG path, target width, and physical tolerance to the native
   library;
2. maps structured native errors to either legacy fallback or the existing
   invalid-SVG error;
3. bulk-constructs any Shapely objects still required by existing consumers
   using Shapely's vectorized/ragged-array boundary rather than Python loops;
4. returns raw `shape_data`, visible `clipped_shapes`, silhouette, scale, and
   bounds expected by `VectorAnalysis`.

The adapter performs at most one checked `int64`-to-`float64` conversion for
the Shapely boundary. C++ already returns disconnected components and the
silhouette, so the adapter does not run a second union, make-valid, occlusion,
or per-ring Python repair pass.

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
- solid fill and solid stroke colors whose effective alpha is zero or one;
- nonzero and even-odd fill rules;
- stroke width, join, cap, miter limit, dash array, and dash offset;
- clip paths that resolve to vector geometry;
- hidden/display-none content and source draw order.

The first release reports `Unsupported` for features that cannot be represented
as discrete printable color regions without a documented policy, including
embedded raster images, arbitrary filters, animation, scripts, and unresolved
external resources. Partial alpha, unsupported group opacity, `vector-effect`,
markers, and unsupported paint order also return `Unsupported`. Gradient,
mask, pattern, and text behavior must follow the current Lumina policy: either
a proven native conversion with golden coverage or whole-document fallback.
They are never silently flattened or skipped.

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

The reference performance environment is Apple M5 (`Mac17,3`), 16 GiB RAM,
macOS 26.5.2, Apple clang 21, arm64 Release build, OpenMP disabled, one caller
thread, target width 111 mm, physical tolerance 0.02 mm, one discarded warm-up,
and at least three measured warm runs. The benchmark report records this
manifest so results from another host are labeled rather than compared as the
same gate.

Acceptance gates are:

1. The public Lumina entry point through complete `VectorAnalysis` return is
   at or below 1.0 second warm median and 1.25 seconds warm p95 on the reference
   host. The internal allocation is 0.70 seconds for native
   parse/layout/flatten/clip, 0.20 seconds for NumPy/Shapely conversion, and
   0.10 seconds for adapter/orchestration; each segment is reported separately.
2. Before native-by-default release, the real R4C1 file with SHA-256
   `da52ef12bdd37a0bd47970649a70582862331a606c151bff05bfb2f6e265f160`
   must pass. Until it is recovered, the public proxy is explicitly labeled
   and fixed by SHA-256, byte size, canvas, path count, stroke-only count,
   transform count, clip count, and color/component/hole fingerprints.
3. Across the supported benchmark corpus, the warm median native geometry
   stage is faster than the Python reference; individual tiny fixtures are
   correctness gates rather than timing gates.
4. The available 55 MB regression SVG shows a material speedup, peak process
   RSS at or below 2.0 GiB, and no measurable swap growth above 256 MiB; no
   worker death or host instability occurs.
5. Native-to-Python result conversion is measured separately and does not
   recreate a per-coordinate Python hot loop.
6. Preview and 3MF output retain their established visual/geometry quality;
   performance is not accepted if a component, hole, or source color is lost.

The one-second gate is an engineering target for common supported static
vectors, not a promise for every legal SVG document.

## Packaging and release

`lumina-svg-core` uses CMake, pybind11, scikit-build-core, and cibuildwheel.
LunaSVG, PlutoVG, and Clipper2 are statically linked into one extension with
hidden symbols. The first release matrix is CPython 3.12 with:

- `win_amd64`, MSVC v143 and the standard Universal CRT;
- `macosx_12_0_arm64` and `macosx_12_0_x86_64`;
- `manylinux_2_28_x86_64`.

`delvewheel`, `delocate`, and `auditwheel` respectively verify and repair the
three platform wheel families. Supporting another CPython minor or platform
requires adding it to this matrix and passing the same ABI, correctness, and
packaging tests; it is not assumed from a source-only build.

The wheel contains the native extension and complete Apache, MIT, Boost, and
FreeType license texts. Lumina pins an exact released version in its dependency
and desktop/PyInstaller inputs. Clean virtual environments install and execute
the wheel before publication. The actual `lumina_studio.spec` one-file backend
is then built on Windows and processes a real small SVG through the native path
from its extracted `_MEIPASS` environment; a bare import is not sufficient.

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
   fixture is native, the same release candidate passes the Windows, macOS,
   and Linux reality suites, and 30 consecutive grey-release days record at
   least 1,000 successful native documents with no legacy parser invocation
   for a successfully generated document within the native support contract.

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
