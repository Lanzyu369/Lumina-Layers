# Vector Evenodd Batch Difference Design

## Goal

Reduce native SVG parsing time without changing SVG fill semantics, model
precision, material identity, preview geometry, or exported toolpaths.

## Confirmed bottleneck

The R4C1 source spends about 71 seconds inside `_parse_svg`. Parsing the
filtered SVG document itself takes less than one second outside profiling.
Function-level profiling attributes about 61 seconds to 2,486 sequential GEOS
`difference` operations in `_combine_evenodd_contained_disjoint_holes`.

That branch has already established three facts before subtraction:

1. one largest geometry contains every child geometry;
2. the child geometries are pairwise non-intersecting;
3. every child therefore represents an independent evenodd hole.

Sequentially subtracting each child is semantically unnecessary and repeatedly
rebuilds an increasingly complex polygon.

## Design

Keep all existing eligibility checks. Once the branch proves the children are
contained and pairwise disjoint, build one polygonal collection from the child
geometries with the existing `_polygonal_union_for_disjoint_items` helper and
perform exactly one `container.difference(hole_collection)` operation.

If the collection cannot be represented or the single subtraction fails, the
helper returns `None` and `_combine_evenodd_polygons` retains its existing
general symmetric-difference fallback. No new rejection path or approximation
is introduced.

This design intentionally does not change SVG document parsing, curve
sampling, contour precision, clipping, mesh generation, or export.

## Verification

- A regression test records Shapely's `difference` calls for multiple
  contained disjoint holes and requires exactly one call.
- Existing evenodd tests continue to compare against sequential symmetric
  difference and cover disjoint islands, nested islands, and prepared-container
  checks.
- The R4C1 source is parsed before and after the change; shape count, bounds,
  per-shape color/area, and symmetric-difference geometry must remain equal.
- Record wall time and peak RSS for the same 111 mm input.
