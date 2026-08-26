# Unified Layered Meshing Engine Design

**Date:** 2026-08-26  
**Status:** Approved in conversation; pending written-spec review  
**Target:** One pull request to `dev-refactor`, followed by direct gray-server testing

## Summary

Replace the internals of Lumina's native Vector and raster mesh generators
without changing their public pipeline contracts. The replacement must produce
smaller, closed, slicer-safe material meshes by construction, rather than first
building many independent solids and repairing, copying, or rejecting them
afterward.

The existing preview, generation, large-format, auxiliary-feature, and 3MF
interfaces remain stable. The final pull request removes superseded repair and
fallback paths from PRs #562, #570, #577, and #578 while preserving their user
contracts as regression tests and final assertions. PR #575's float32 round-trip
contract remains required.

## Problem

Lumina currently turns its two fundamentally layered input forms into general
triangle meshes too early:

- Native Vector mode extrudes many independently processed polygons and then
  unions, concatenates, repairs, or falls back to source shells.
- High-Fidelity and Pixel modes compress masks into rectangles but make every
  rectangle an independently closed box with eight vertices and twelve faces.

This creates avoidable vertices, internal walls, coincident surfaces, full-mesh
copies, and repair ladders. Dense SVGs can exhaust memory or be rejected by a
coarse admission guard. Near-equal coordinates can collapse at float32 export,
causing non-manifold geometry or missing slicer paths. Raster inputs remain
topologically regular but still pay for redundant closed boxes.

## Goals

1. Keep current route, worker, staged-pipeline, preview, and writer call
   contracts stable.
2. Replace Vector extrusion with canonical physical-coordinate preparation,
   bounded shared-boundary simplification, and direct indexed extrusion.
3. Replace raster closed-box emission with lossless greedy surface meshing of
   the existing labeled voxel matrix.
4. Bound peak memory during mesh accumulation and 3MF serialization.
5. Preserve every printable region, material identity, optical stack, hole,
   independent shell, and effective slicer toolpath.
6. Cover native SVG, rasterized SVG, bitmap High-Fidelity, Pixel, Single- and
   Double-sided, relief, heightmap, cloisonne, fridge-magnet cavities, outlines,
   coatings, backing, model-surface overlays, and large-format tiles in one
   delivery.
7. Remove obsolete production repair/fallback implementations instead of
   retaining two automatic generation engines.

## Non-goals

- Do not redesign the converter UI, persisted settings, recipe model, color
  solver, material archive, or printer profiles.
- Do not rasterize native Vector geometry.
- Do not apply generic 3D decimation or STEP conversion.
- Do not silently remove islands or holes based only on nozzle diameter.
- Do not automatically fall back to the retired engine when the replacement
  rejects invalid input.
- Do not rewrite arbitrary model-surface geometry; preserve the existing
  surface-placement adapter and validate its input/output contract.

## Stable External Contracts

The following boundaries remain compatible:

- `VectorProcessor.analyze()` and `VectorProcessor.build_mesh()` inputs and
  result structure.
- `HighFidelityMesher.generate_mesh()` and `VoxelMesher.generate_mesh()` inputs
  and returned `trimesh.Trimesh | None` value.
- Staged pipeline context keys including `material_matrix`, `full_matrix`,
  `scene`, `transform`, backing metadata, relief metadata, and slot names.
- Preview GLB and final 3MF API responses, download behavior, material slot
  mapping, and slicer profiles.
- Current feature parameters and share-card recipes.

Internal helpers may expose chunk iterators, but existing callers continue to
receive the same logical results.

## Architecture

### 1. Vector replacement

Keep SVG parsing, visibility/occlusion clipping, color matching, recipe
selection, and run grouping. Replace the body of the current extrusion hot path
with these stages:

1. Convert post-occlusion geometry into physical millimeters before any
   precision operation.
2. Snap coordinates to one fixed physical grid. The initial policy is
   `0.0001 mm`, with coordinates kept as integer grid units inside the new
   preparation module.
3. Partition the XY linework into spatially connected groups, then node and
   polygonize each group once. Label each resulting cell from the already
   resolved source visibility/material ownership and recipe. Shared edges are
   canonicalized once, not independently rounded per polygon. The recipe is
   mapped to Z runs afterwards; XY preparation is not repeated per print layer.
4. Simplify canonical shared boundary chains with a maximum physical deviation
   of `0.005 mm`.
5. Reconstruct polygon coverage and validate it against the unsimplified
   source. Any local chain or component that would change component count, hole
   count, material ownership, or coverage beyond the existing absolute/relative
   contract retains its unsimplified canonical boundary.
6. Group geometry by the existing `(material slot, z start, z end)` contract and
   directly extrude the resulting Polygon/MultiPolygon components with indexed
   caps and walls.

No accepted region may be silently dropped. The simplifier is an optimization,
not a recovery mechanism. Invalid source topology is rejected before expensive
3D allocation with a typed, actionable error.

### 2. Raster replacement

Keep image processing, LUT matching, cleanup options, `material_matrix`, and
`full_matrix`. Replace per-rectangle closed-box output with labeled-volume
surface extraction:

1. For a requested material, compare each voxel against its six neighbors.
2. Emit a face only where the neighbor is outside the volume or has a different
   material.
3. Greedily merge adjacent coplanar faces with the same orientation, material,
   and Z/XY plane into rectangles.
4. Split merged face boundaries at every neighboring/perpendicular boundary
   event before triangulation so the final surface has no T-junctions.
5. Convert the resulting conforming faces to indexed triangles and reuse exact
   integer-grid vertices within the same material shell.
6. Preserve opposite, coincident interface surfaces for two different material
   objects so each exported material remains independently closed.

This operation is lossless relative to `full_matrix`: it does not blur,
simplify, dilate, or delete pixels. Relief, heightmap, cloisonne, double-sided
stacks, backing, and magnet cavities already appear as labels or air in
`full_matrix`, so they use the same surface extractor without separate geometry
algorithms. Pixel mode retains its block shape exactly.

### 3. Shared indexed chunk accumulator

Both replacement engines emit indexed geometry whose canonical identity remains
`int64` physical-grid XY coordinates plus integer layer Z and `shell_id` until
final materialization. A single accumulator owns:

- local-to-object index offsets;
- exact integer-grid vertex identity within one material shell, without welding
  distinct source shells merely because their float coordinates become equal;
- actual byte accounting;
- final float32-domain degenerate/contact checks;
- compact per-material final arrays for the existing Scene contract;
- material/object totals used by diagnostics and acceptance tests.

The accumulator converts once to float32/uint32 only after topology is complete,
then validates the exact writer-domain arrays. Preview and generate callers keep
the current Trimesh/Scene contract. An optional disk-spool output may be added
later only if measured final-array residency still exceeds the acceptance
budget; it is not a prerequisite for replacing the meshing cores.

### 4. 3MF serialization

Retain `neroued_3mf` and its material/profile packaging behavior. Its current
Python binding already accepts C-contiguous float32 vertices and uint32/int32
triangles through the non-owning `MeshView` path. Lumina must pass the validated
final arrays directly to `DocumentBuilder.add_mesh_object()` instead of first
calling owning `Mesh.from_arrays()`.

Shortest-round-trip float32 formatting remains a useful upstream file-size
optimization, not a prerequisite or memory-safety mechanism. A two-pass
spool-backed upstream source is considered only if measured zero-copy export
still misses the peak-memory target. A second Lumina-local 3MF implementation is
explicitly prohibited.

## Precision and Topology Policy

One core policy owns all new geometry tolerances:

- Physical XY grid: `0.0001 mm` initially.
- Shared-boundary simplification deviation: `0.005 mm` initially.
- Coverage acceptance: retain the existing strict absolute/relative contract;
  simplification must not weaken it.
- Z: existing integer print-layer indices, converted with the configured layer
  height only at output.
- Writer domain: validate the actual float32 coordinates that will be passed to
  `neroued_3mf`.

The policy applies in millimeters, never raw SVG canvas units. Build-plate/tile
local coordinates are preferred before float32 conversion so large-format
global offsets do not reduce local precision.

Required invariants for every output material object:

1. Triangle indices are in range and no triangle is index- or coordinate-
   degenerate.
2. Every edge incidence is exactly two within an independent closed shell.
3. No new contact is introduced between distinct source shells after float32
   conversion.
4. Source components, holes, material coverage, and Z runs are preserved.
5. The final mesh is watertight and slicer toolpath coverage matches the source
   contract.

## Memory and Failure Behavior

The replacement must make the common path compact enough that ordinary complex
artwork does not encounter a user-facing complexity rejection.

- Admission uses an estimate derived from canonical 2D boundaries or exposed
  voxel surfaces, not a fixed 8 GiB reservation for every Vector request.
- Canonical integer buffers and final writer-domain arrays have explicit byte
  accounting and deterministic lifetime boundaries.
- A hard host/worker circuit breaker remains only for genuinely unrepresentable
  or resource-exhausting input.
- Rejection occurs before large 3D allocation, uses a stable typed 422 error,
  and does not recommend retrying when no other task is running.
- One failed task must not break the worker pool, health check, or following
  normal task.

There is no automatic legacy-engine fallback. Gray rollback uses the previous
deployed revision/container.

## Superseded Code Removal

The final PR removes old production paths only after the replacement passes the
corresponding tests:

- PR #562: remove source-shell/merged-mesh coverage fallback paths and duplicate
  full-mesh retention; preserve coverage regressions.
- PRs #570 and #578: remove the multi-attempt topology repair ladder and
  coordinate-separation recovery from the replaced main Vector run path;
  preserve final topology assertions, reason codes, real regressions, and any
  helpers still used by Outline until Outline adopts the new builder.
- PR #577: remove the fixed full-budget reservation and ordinary
  `vector_too_complex` user path; preserve bounded-memory accounting, host
  health protection, and recovery tests in replacement form.
- PR #575: preserve float32-safe serialization and its tests; keep nine
  significant digits unless a separate measured upstream change proves
  shortest-round-trip formatting is smaller with identical float32 values.

Dead helpers, caches, feature flags, translations, and tests that assert an
obsolete implementation detail are deleted. Tests that assert user-visible
geometry, memory, or error contracts remain and are rerouted to the new engine.

## Mode Compatibility

The single PR must demonstrate the following before rollout. Auxiliary modes
remain on their current adapters in this delivery; they are compatibility
regressions, not additional topology rewrites.

| Workflow | Required proof |
| --- | --- |
| Native SVG Vector | Shared-edge coverage, component/hole preservation, smaller mesh, Bambu/Orca paths |
| High-Fidelity bitmap | Pixel/material matrix parity and lossless exposed-surface mesh |
| High-Fidelity rasterized SVG | Same raster matrix and geometry as the bitmap path |
| Pixel | Exact block occupancy and material parity |
| Single/Double-sided | Correct top/bottom stack order and closed material volumes |
| Relief/heightmap | Quantized height parity and closed step/top surfaces |
| Cloisonne | Wire material, width, height, and surrounding color coverage |
| Fridge magnet | Cavity dimensions, air regions, and backing closure |
| Outline/coating/backing | Independent closed shells and correct material slots |
| Model surface | Existing placement parity and no additional mesh collisions |
| Large format | Tile-edge continuity, local-coordinate precision, and per-tile slicing |

## Testing and Reality Verification

Development follows test-first red/green cycles. Tests must cover:

1. Small synthetic shared-edge SVGs, holes, islands, near-float32 contacts, and
   incomplete union regressions from prior PRs.
2. Synthetic labeled voxel volumes proving internal faces are absent and every
   material remains independently watertight.
3. Property tests comparing new raster material occupancy against `full_matrix`.
4. Preview/generate parity for Vector and raster modes.
5. Memory tests proving bounded accumulation/spill and healthy follow-up work.
6. Existing focused Vector, raster, writer, profile, packaging, logging, smoke,
   and full gates without weakening thresholds.
7. The historical R4C1 SVG and the provided bitmap corpus at small and large
   output sizes with 0.2 mm and 0.4 mm nozzle profiles.
8. Actual Bambu Studio and OrcaSlicer open/slice tests with prime tower disabled
   only in verification copies. Inspect the first five effective layers and
   machine-check per-layer/material extrusion coverage.
9. Before/after peak RSS, runtime, vertex/face count, and 3MF size using the same
   warm-run fixtures.

Acceptance requires zero coordinate-degenerate triangles, zero open edges,
zero non-manifold edges, maximum edge incidence two, no missing effective model
toolpaths, no changed material identity, and no ordinary complexity rejection
for accepted historical fixtures.

## Delivery and Rollback

All production behavior lands in one topic-branch PR from the latest
`origin/dev-refactor`. Internal commits may be small and testable, but the gray
server receives the complete replacement, not partially migrated modes.

The final branch contains no automatic legacy fallback. If gray testing finds a
blocker, deployment rolls back to the prior known revision. The PR is not merged
until focused tests, full gates, memory evidence, 3MF topology inspection, and
both slicer reality checks pass.
