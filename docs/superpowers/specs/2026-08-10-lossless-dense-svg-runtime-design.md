# Lossless Dense SVG Runtime Integration Design

**Status:** Approved by delegated implementation authority

**Date:** 2026-08-10

## Outcome

Integrate the proven GEOS 3.13.1 lookup-only acceleration into the server SVG
pipeline without changing material regions, layer order, model surfaces, holes,
or dimensions. The optimized positive-buffer path is optional and capability
guarded. Missing libraries, an invalid manifest, load failures, null C API
results, or invalid polygonal output all fall back to the current Shapely path.

The first server target is Docker/Linux, where the pinned library can be built
from source for the image architecture. Desktop packaging remains on the
existing Shapely fallback until replacement-library and corresponding-source
distribution are explicitly wired and verified.

## Evidence behind the decision

On `IMG_7254.svg` at 300 mm, the patched positive buffer reduced stock GEOS
from 71.392526 seconds to 3.765247 seconds. The symmetric difference was empty,
area and bounds were equal, component/hole counts matched, and normalized WKB
hashes were identical. Three additional runs had a 3.698161-second median and
identical fingerprints.

Thirteen upstream GEOS buffer tests and six synthetic differential families
passed. Full evidence is recorded in
`2026-08-10-lossless-dense-svg-geos-proof-results.md`.

## Product invariants

Acceptance is based on the user's material-color construction workflow, not
on internal triangle ordering:

1. every material region has the same XY set;
2. material identity and draw/layer order are unchanged;
3. the final solid surfaces, holes, and external dimensions are unchanged;
4. no valid geometry is silently dropped;
5. model/mesh serialization may reorder equivalent components only;
6. a fast-path failure must produce the stock result, not a partial result.

## Chosen architecture

### 1. Isolated WKB-only GEOS adapter

Add `core/geos_buffer_fast.py` as the only runtime boundary for the modified
library. It loads `libgeos_c` by absolute path, uses a re-entrant context, and
passes WKB bytes across the boundary. Shapely-owned geometry pointers never
enter the modified library.

The adapter binds only the re-entrant context, WKB reader/writer, buffer
parameter, buffer, destroy, and free functions needed by the operation. Each
call creates and destroys its own context. A typed exception represents every
load, symbol, setter, null-pointer, or serialization failure.

### 2. Verified runtime manifest

The runtime is enabled through `LUMINA_GEOS_BUFFER_FAST_MANIFEST`. The manifest
must name:

- official GEOS 3.13.1;
- upstream commit `431568d6e311e0bbfb057b4ec3d44d0d3ba3335f`;
- patch SHA-256
  `f0f0b940a25d11df50548dad4838ad8197588304b20e983274158d23c8da96c5`;
- an existing absolute `libgeos_c` path.

An explicit unverified library path is permitted only when
`LUMINA_GEOS_BUFFER_FAST_ALLOW_UNVERIFIED=1`, for local development and proof
work. Production Docker uses the verified manifest.

### 3. Dense-only routing

The modified positive buffer is attempted only for valid `MultiPolygon`
inputs with at least 2,048 top-level components and the exact production
parameters:

- distance `+0.03 mm`;
- quadrant segments `1`;
- mitre join;
- mitre limit `2.0`.

Small and ordinary shapes keep the current in-process Shapely call. This avoids
the WKB/context overhead observed on the second supplied sample, where stock
buffering took 0.000425 seconds and the isolated proof boundary took 0.004049
seconds.

### 4. Exact disconnected negative buffer

After the positive buffer, top-level output polygons are mutually disjoint.
Shrinking one polygon cannot make it interact with another. For dense valid
`MultiPolygon` output, run the negative buffer independently for each top-level
polygon through Shapely's vector API, flatten polygonal results, and reconstruct
the polygon collection.

This changes operation scheduling only. Each polygon still uses stock GEOS and
the same distance, quadrant, join, and mitre parameters. Any exception, empty
unexpected result, non-polygon output, or invalid reconstructed geometry falls
back to the existing global negative buffer.

### 5. Narrow vector-engine adoption

Adopt the helpers only in contour normalization:

- the scalar `_normalize_contours` path;
- the batch `_normalize_contours_many` path used after occlusion clipping.

No parsing, occlusion, color matching, mesh construction, backing, coating,
outline, or model-layer logic changes in this integration.

### 6. Docker build and fallback

The existing pinned proof builder already validates the exact source revision,
applies the tracked patch, builds shared Release libraries, and emits a
manifest. Docker installs CMake, runs that builder after copying the source,
and exports the manifest path for runtime discovery.

The Docker image intentionally retains the cloned corresponding GEOS source,
the tracked modification patch, build scripts, and upstream `COPYING` file.
This provides the complete modified-library source inside the distributed
image. Desktop/PyInstaller builds do not include or enable the modified library
in this change.

## Failure and fallback behavior

The runtime fast path is best effort:

1. check geometry and parameter eligibility;
2. resolve and validate the manifest once per process;
3. invoke the isolated WKB adapter;
4. require non-empty, valid `Polygon`/`MultiPolygon` output;
5. on any failure, log one actionable warning and execute stock Shapely;
6. if the component-wise negative result is not valid polygonal geometry,
   execute the existing global negative buffer.

No exception from the optional accelerator may escape solely because the
accelerator is unavailable.

## Observability

Use structured logging from `api.structured_logging`. Fast-path success is
DEBUG only. A fallback warning includes an event name, failure type, error
message, library/manifest path when applicable, and input component count.
This avoids consuming normal INFO budgets while leaving deployment failures
diagnosable.

Add a `contour_normalize_s` stage timing while retaining the existing
`occlusion_s` field for compatibility. The stage timing is evidence for the
remaining end-to-end 30-second target.

## Licensing boundary

GEOS identifies itself as LGPL software and documents the stable C API and
re-entrant API used here. The modified Docker library remains dynamically
loaded. The image retains the license, complete pinned source, tracked patch,
and build scripts.

Desktop distribution is deliberately excluded until packaging also provides
prominent notice, the LGPL license, replacement of the shared library, and
equivalent access to corresponding modified source. This design is an
engineering boundary, not a substitute for release counsel review.

## Rejected alternatives

### Per-fragment approximation or simplification

Rejected because material boundaries can change. The user explicitly requires
the final material-color model to stay unchanged.

### Envelope-partitioned stock GEOS

A conservative grouping experiment ran the buffer kernel in 0.930 seconds and
produced valid output with equal component/hole counts. It still had a
non-empty symmetric difference of `0.000845282646586032 mm²`, a small area
change, and different bounds/hash. It is therefore rejected despite its speed.

### Always use the isolated library

Rejected because the WKB/context boundary adds milliseconds to tiny inputs and
provides no benefit. Dense-only routing keeps ordinary SVG behavior and
latency unchanged.

### Replace Shapely's bundled GEOS globally

Rejected because it risks ABI/symbol conflicts and broadens the change to every
geometry operation. The isolated library performs one proven operation only.

## Acceptance gates

The runtime integration is complete only when:

1. unit tests cover manifest validation, C API cleanup, dense routing, and
   every fallback;
2. scalar and batch contour normalization remain topologically equal to stock
   across synthetic cases;
3. the real `IMG_7254.svg` 300 mm normalization result has empty symmetric
   difference and matching structure;
4. positive plus negative contour normalization is at most 5 seconds on the
   proof machine;
5. both supplied SVGs complete full analysis and model generation without
   material/surface/hole/dimension changes;
6. Docker builds and loads the verified runtime manifest;
7. no custom library is accidentally enabled in desktop packaging;
8. focused vector, logging, build-contract, and performance tests pass.

After these gates, profile parse, occlusion, color matching, and mesh stages and
continue toward a first-preview target of 30 seconds, with 15 seconds as the
stretch goal.
