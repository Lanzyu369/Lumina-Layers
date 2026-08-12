# Lossless Dense SVG Normalization Design

**Date:** 2026-08-10

**Status:** approved delegated direction

**Branch:** `codex/fix/lossless-dense-svg-normalization`

## 1. Outcome

Reduce the first-run contour-normalization cost of unusually fragmented SVGs
without changing any material region or layer semantics.

This specification is the first independently testable sub-project of the
broader first-preview goal:

1. reduce dense contour normalization from about `171 s` to at most `5 s` on
   `IMG_7254.svg` at `300 mm`;
2. preserve each material's XY region, holes, layer/Z order, and final solid
   exactly in the product-semantic sense;
3. retain the current Shapely/GEOS implementation as a deterministic fallback;
4. keep peak RSS no higher than `1.20x` the current first-run baseline;
5. after this sub-project passes, profile and optimize the remaining parse,
   occlusion, color-match, and mesh stages toward a `30 s` complete first
   preview, with `15 s` as the stretch target.

Triangle ordering, vertex ordering, archive member ordering, and equivalent
polygon component ordering may differ. Filled material regions may not.

## 2. User-visible contract

Lumina creates additional colors by stacking consumables. Geometry therefore
defines color, not merely appearance. The optimization must preserve:

- the union of polygons assigned to every material slot at every Z interval;
- exterior boundaries and holes;
- material and recipe identity;
- layer order, thickness, and Z offsets;
- backing, coating, and auxiliary-structure footprints;
- final solid bounds and occupied volume.

For every material/Z pair, the legacy and candidate polygon sets must have an
empty symmetric difference. An area tolerance alone is not sufficient.

## 3. Scope decomposition

### Included in this specification

- the `+0.03 mm` then `-0.03 mm` contour-close operation used after SVG
  occlusion clipping;
- a proof-first GEOS 3.13.1 native accelerator for extremely fragmented valid
  `MultiPolygon` inputs;
- the already-proven independent negative-buffer optimization after a global
  positive buffer;
- native capability checks, kill switch, deterministic fallback, build and
  packaging integration;
- focused unit, differential, real-sample, memory, and performance validation.

### Explicitly excluded

- changing the `0.03 mm` close distance or buffer parameters;
- Clipper2, rasterization, precision grids, coordinate snapping, approximate
  tiling, or component grouping that changes geometry;
- SVG parsing, color matching, triangulation, GLB, or 3MF optimization;
- UI, API, cache-schema, material-recipe, or model-format changes;
- publishing an upstream GEOS pull request or changing external deployment
  state without separate authorization.

The excluded performance stages remain part of the active overall goal, but
each receives its own specification after this kernel is verified.

## 4. Reproduced evidence

The correct production parse policy (`expand_stroke_to_fill=False`) on
`IMG_7254.svg` at `300 mm` produced:

| Stage | Observed wall time |
|---|---:|
| SVG parse | `8.2 s` |
| occlusion clip | `17.1 s` |
| contour normalization | `171.3 s` |
| disconnected-shape split | `0.54 s` |
| color match | `8.4 s` |
| full geometry analysis | `206.1 s` |

The dominant normalized item is one valid `MultiPolygon` containing `74,162`
components and `302,787` coordinates. Its global positive buffer produced
`70,588` components and took `78-88 s`; its global negative buffer produced
`72,045` components and took `81.8 s`.

The following experiments establish the semantic boundary:

- negative-buffering the already-disconnected global positive result by
  component took `0.7 s`; the result was valid, topologically equal to the
  legacy result, and had an empty symmetric difference;
- independent positive buffering plus disjoint-subset union took about `1 s`
  but changed area by `-2.1865 mm2` and changed component count by `316`;
- a hybrid interaction-core approach reduced the numerical area delta to
  about `-0.00000164 mm2` but still changed component count by `42`;
- tolerance, feature-complexity, and iterative interaction-core expansions did
  not remove those differences.

Therefore only the negative pass may be decomposed at the application layer.
The positive pass must retain GEOS's global graph construction.

## 5. Native root cause

Two five-second samples of the live arm64 GEOS 3.13.1 call showed the positive
buffer spending most sampled time in:

- `BufferBuilder::buildSubgraphs`;
- `PolygonBuilder::add`;
- `SubgraphDepthLocater::getDepth` and `findStabbedSegments`.

The current GEOS main branch still has two avoidable repeated scans:

1. `PolygonBuilder::add` rebuilds point-in-area locators for every accumulated
   shell before calling `placeFreeHoles`, even when the current subgraph has no
   free holes.
2. `SubgraphDepthLocater` scans every previously processed subgraph and only
   then filters it by envelope.

The offset curves, global noding, graph edges, and coordinates are not the
dominant sampled work. This permits an optimization that changes lookup cost
without changing geometry construction.

Upstream references:

- <https://raw.githubusercontent.com/libgeos/geos/main/src/operation/buffer/BufferBuilder.cpp>
- <https://raw.githubusercontent.com/libgeos/geos/main/src/operation/buffer/PolygonBuilder.cpp>
- <https://raw.githubusercontent.com/libgeos/geos/main/src/operation/buffer/SubgraphDepthLocater.cpp>

## 6. Alternatives

### A. Indexed GEOS 3.13.1 fast kernel plus decomposed negative pass — selected

Keep GEOS's offset curves, noding, graph construction, subgraph order, depth
semantics, and polygon construction. Make only two behavior-preserving lookup
changes:

- skip shell-locator construction when `freeHoleList` is empty;
- index processed subgraph Y envelopes, query candidates for the stabbing
  coordinate, apply the existing X/Y envelope predicates, and restore original
  processed order before the existing depth calculation.

After the exact global positive buffer, negative-buffer disconnected positive
components independently and reassemble them.

This is the only route supported by current evidence that can approach the
performance target while retaining current geometry semantics.

### B. Application-layer negative-pass optimization only — safe fallback plan

Keep the stock `78-88 s` global positive buffer and replace only the `81.8 s`
negative pass with the verified `0.7 s` decomposed pass.

This is strictly useful and low risk, but it leaves geometry analysis near two
minutes and does not satisfy the selected target. It may ship independently
only if the native proof fails and the user accepts the smaller gain.

### C. Clipper2, partitioned positive buffers, or precision-grid morphology — rejected

These approaches can finish near one second, but the real sample already
demonstrated changed filled regions or connectivity. They violate the material
stacking contract and are not guarded fast paths for this feature.

## 7. Architecture

### 7.1 Proof gate

Before production integration, build a local GEOS 3.13.1 proof kernel with the
two lookup-only patches. The proof must run the exact global positive buffer on
the extracted `74,162`-component geometry and compare it with stock Shapely.

The proof passes only if all are true:

- native positive result is topologically equal to stock positive;
- symmetric difference is empty;
- normalized WKB is equal, unless the only difference is component/ring order
  and the empty-symmetric-difference product oracle passes;
- component count, area, bounds, validity, and hole count match;
- positive-buffer wall time is at most `4 s` on the current 10-core arm64 test
  machine;
- peak RSS is at most `1.20x` stock.

If any geometry condition fails, production integration stops. If geometry
passes but timing is above `4 s`, profile the proof once and revise the indexed
lookup; do not weaken the target or semantic oracle silently.

### 7.2 Product native module

Add an optional `geos_buffer_fast` Python extension backed by a separately
named, dynamically linked GEOS 3.13.1 LGPL library. The extension exposes:

```python
def native_buffer_capabilities() -> dict[str, object]: ...

def positive_buffer_wkb(
    geometry_wkb: bytes,
    distance: float,
    *,
    quad_segs: int,
    join_style: str,
    mitre_limit: float,
) -> bytes: ...
```

The capability payload declares the pinned GEOS semantic version and the two
lookup optimizations. Python enables the module only when the complete
capability contract matches.

The dedicated shared library avoids replacing or interposing on Shapely's
private GEOS library. This prevents two-level namespace, ABI, and process-wide
symbol risks. GEOS source, license, patch, and build metadata are versioned so
the distributed LGPL library remains reproducible and replaceable.

### 7.3 Python adapter

Create a focused adapter in `core/vector_dense_normalizer.py`. It owns:

- native module discovery and capability validation;
- dense-input eligibility;
- WKB serialization/deserialization;
- global positive native call;
- vectorized negative buffering of positive-result components using the
  existing Shapely parameters;
- output validity checks and typed fallback reasons.

`core/vector_engine.py` remains the call-site owner. Its public methods and
return structures do not change. `_normalize_contours_many` delegates only a
dense valid `MultiPolygon` to the adapter and processes all other inputs through
the current implementation.

Initial automatic eligibility is intentionally narrow:

- geometry type is `MultiPolygon`;
- input is valid and non-empty;
- component count is at least `2,048`;
- close distance is positive and finite;
- `quad_segs=1`, `join_style="mitre"`, and `mitre_limit=2.0`;
- native capability contract matches exactly;
- `LUMINA_VECTOR_DENSE_BUFFER_NATIVE` is not `0`/`false`/`off`.

The threshold affects route selection only, never output semantics.

### 7.4 Data flow

```text
occlusion-clipped geometry
  -> current _normalize_contours_many
       -> ordinary geometry: unchanged Shapely +d/-d
       -> eligible dense MultiPolygon:
            serialize WKB
            -> patched GEOS global +d
            -> deserialize exact positive result
            -> split disconnected positive components
            -> Shapely vectorized -d per component
            -> reassemble valid Polygon/MultiPolygon
            -> existing post-buffer finish semantics
  -> unchanged disconnected-shape split and material matching
```

## 8. Exactness and determinism

The indexed depth lookup must evaluate exactly the candidates the stock scan
would evaluate:

1. query processed envelopes whose Y interval contains the stabbing Y;
2. apply the existing `p.x <= envelope.maxX` predicate;
3. sort candidates by original processed index;
4. call the unchanged segment stabbing and depth comparison code.

The no-free-hole shortcut is allowed only before locator allocation when
`freeHoleList.empty()`; no shell or hole mutation is skipped.

The positive output is still produced from the same GEOS graph. The negative
pass may return equivalent components in another order, so product acceptance
uses material-region topology rather than byte ordering.

## 9. Failure handling and rollback

- Module missing, stale, or capability mismatch: use stock Shapely.
- Native input validation failure: use stock Shapely.
- WKB parse, native GEOS, allocation, or output-decode failure: discard the
  candidate and use stock Shapely for that geometry.
- Empty, non-polygonal, invalid, non-finite, or structurally inconsistent
  native result: discard it and use stock Shapely.
- Negative component buffer failure: discard the entire dense candidate and
  rerun the stock two-pass operation; never mix partial candidate and stock
  components.
- Environment kill switch: bypass native discovery and use stock Shapely.

Fallback emits bounded numeric timing/fallback fields through the existing
vector timing payload. It does not add per-component logs or new INFO events.

Rollback requires only setting `LUMINA_VECTOR_DENSE_BUFFER_NATIVE=0` or
removing the optional module. No persisted cache, API, or artifact migration is
introduced.

## 10. Build, packaging, and licensing

Extend the existing native-extension build entry point rather than adding a
second unrelated build command. Product integration must cover:

- local macOS arm64 proof and build;
- Windows x64 desktop build;
- Linux x64 Docker build;
- PyInstaller binary discovery and inclusion;
- a clean-runtime import test with no `.scratch` path;
- GEOS LGPL notice, source-version record, patch file, and source-availability
  instructions.

The optimized GEOS library is dynamically linked and separately named. It must
not replace Shapely's bundled GEOS in the process.

## 11. Test design

### 11.1 TDD order

1. Add failing adapter tests for module absence, capability mismatch,
   ineligible input, native failure, invalid output, and kill switch.
2. Add failing tests proving one eligible dense geometry uses the native
   positive pass and vectorized component negative pass.
3. Add a synthetic differential corpus covering disjoint shells, close shells,
   nested shells/holes, sharp mitres, tiny components, and erosion splits.
4. Build the proof kernel and require stock-versus-native positive-buffer
   equality before wiring production discovery.
5. Add build metadata, clean-import, and packaging tests.
6. Run real SVG and final material/mesh fingerprint verification.

### 11.2 Automated semantic gates

For every stock/candidate pair verify:

- validity and polygonal type;
- empty symmetric difference;
- equal area, bounds, component count, and hole count;
- deterministic repeat fingerprints;
- unchanged fallback result and exception behavior.

For full SVG analysis, group shapes by material identity and Z interval, union
each group, and require empty symmetric difference for every group. Also compare
recipes, material slots, layer order, backing footprint, and total silhouette.

For final meshes, compare per-material bounds, watertightness, occupied volume,
surface area, and Z intervals. Triangle and vertex record order are not an
oracle.

### 11.3 Real-sample gates

Run cold first computations at `300 mm` for:

- `/Volumes/personal_folder/IMG_7254.svg`;
- `/Volumes/personal_folder/person_bd9869970839c02b0d0ac82e3756ccf1_20260725_074417_vector.svg`.

Record stock and candidate stage timings, peak RSS, shape/component counts, and
material-region fingerprints. Run candidate at least three times after one
cold-start measurement; performance decisions use the median completed run,
while first-user latency is reported separately.

## 12. Acceptance gates

This sub-project is complete only when:

- `IMG_7254.svg` dense contour normalization is at most `5 s` cold;
- full geometry analysis is at most `40 s` cold on the current machine;
- both real `300 mm` SVGs have zero per-material/Z symmetric difference;
- final model material order and Z intervals are unchanged;
- peak RSS is at most `1.20x` stock;
- forced fallback produces the stock result;
- macOS, Windows, and Linux native builds or deterministic stock fallbacks are
  verified;
- focused and wider vector/native regressions pass;
- no long-running test or preview processes remain.

Meeting these gates starts the next independent optimization specification for
the remaining complete-preview path. It does not by itself claim that the
overall `30 s`/`15 s` preview goal has been achieved.
