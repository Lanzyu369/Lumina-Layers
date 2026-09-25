# Vector Mesh Integrity Consolidation Plan

**Goal:** Replace the remaining patch/fallback mesh paths with one bounded,
constructive post-parse geometry pipeline that preserves printable islands,
emits closed float32-safe shells, and keeps one editable 3MF object per material.

**Scope:** SVG parsing is intentionally outside this change. The parser owned by
PR #588 supplies two-dimensional polygons; this plan starts at those polygons and
ends at GLB/3MF material meshes.

## Final architecture

1. Resolve SVG draw-order occlusion in the existing two-dimensional clipping
   stage, before material recipes are assigned.
2. Group the resulting non-overlapping source shapes by material and contiguous
   layer run, then snap each slab to one writer-safe integer XY grid.
3. Fold only byte-identical footprints in adjacent bands into maximal prisms;
   keep every other printable island as an independent closed shell.
4. Triangulate simple caps with Earcut and holed caps with constrained Delaunay;
   both use the original integer ring nodes and the same exact boundary check.
5. Build caps and walls from shared indices, then concatenate all closed shells
   into one mesh/3MF object for that material.
6. Never weld or move independent-shell coordinates during concatenation. No
   repeated material-wide Boolean union, whole-model topology audit, repair
   ladder, alternate 3D engine, or error-driven fallback runs in production.

## Implementation

- [x] Route Vector colors, board, relief, coating/auxiliary geometry, and outline
  through `build_vector_layered_volume()`.
- [x] Remove the old spatial preparation, error-driven local fallback, global
  arrangement, legacy topology service, and public prepared-extrusion entry.
- [x] Keep one output mesh per material while retaining disconnected printable
  islands as internal closed shells.
- [x] Keep area-overlap ownership in the upstream draw-order clipper and merge
  only identical adjacent runs, avoiding a second material-wide Boolean pass.
- [x] Preserve a minimum four-ULP XY grid before neroued-3mf 0.4.x receives
  arrays; concatenation preserves shell coordinates and indices verbatim.
- [x] Remove the unit-incorrect post-clip area threshold: physical-size
  filtering runs only where the SVG-to-mm scale is known.
- [x] Require Shapely 2.1.0+, matching the constrained triangulation API used
  for holed caps in source, Docker, and frozen desktop installs.
- [x] Replace stale fallback tests with constructive invariants: edge incidence
  two, no float32-degenerate triangles, preserved islands, no internal caps for
  identical adjacent runs, deterministic object/material count.

## Verification

- [x] Focused geometry/vector/outline tests.
- [x] Puzzle, keychain/fridge/board, coating, relief, model-surface, writer, and
  coordinate-domain tests (environment dependency failures recorded separately).
- [x] Generate the LUM-20260901-002 SVG; measure upstream overlap on all three
  `无走线素材` SVGs without treating them as parser fixtures.
- [x] Inspect the serialized LUM-20260901-002 3MF XML for degenerate triangles, open edges,
  non-manifold edges, duplicate writer coordinates, and material object count.
- [x] Disable the prime tower only in a verification copy; slice with Bambu
  Studio and verify the first five effective model layers contain extrusion
  paths. OrcaSlicer is intentionally not a release gate for this change.
- [x] Record matched wall time, peak RSS, 3MF size, vertices/faces, and compare
  with the pre-consolidation branch without making unsupported claims.
- [x] Run focused, creative-mode, smoke, logging-fast, compile, and diff checks.
- [x] Finish the independent final review. No reproducible merge blocker
  remains. The full repository run completed with 6164 passing tests and only
  failures reproduced on the clean HEAD plus one unrelated floating-boundary
  Hypothesis counterexample.

## Delivery

- [ ] Publish one replacement PR from a clean `origin/dev-refactor` base; squash
  the final tree state instead of retaining the stacked patch history. Do not
  merge automatically.
- [ ] State that the final implementation removes or replaces the obsolete
  geometry paths introduced by merged PRs #562, #570, #575, #577, and #578,
  and supersedes unmerged PRs #585 and #589. Keep PRs #587 and #588 separate.
- [ ] Provide the exact head, commands, test results, slicer evidence,
  performance numbers, output-size caveat, and remaining limitations.
