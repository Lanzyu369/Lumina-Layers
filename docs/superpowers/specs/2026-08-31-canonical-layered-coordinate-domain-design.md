# Canonical Layered Coordinate Domain

## Status

Approved direction on 2026-08-31. This design replaces repeated floating-point
canvas and layer-bound calculations with one canonical coordinate contract.

## Problem

Native Vector meshing, model-surface placement, GLB preview, and 3MF export can
currently derive physical bounds independently:

1. SVG analysis computes a theoretical canvas from `bbox * scale_factor`.
2. Layer meshing snaps polygon coordinates to a writer-safe XY grid and may
   materialize independent contacts in float32 space.
3. Model-surface placement recomputes canvas width, canvas height, and display
   depth from analysis metadata.
4. The 3MF writer converts coordinates to float32 again.

Equivalent physical coordinates can therefore differ by a float32 rounding
step. A valid pattern is then rejected as outside its own logical XY or Z
bounds. Fixing one axis locally leaves the same defect available on another
axis.

## Goals

- Establish one authoritative physical coordinate domain before triangle
  generation.
- Express XY canvas bounds as integer grid units.
- Express Z as ordered layer boundaries rather than repeated float sums.
- Reuse the same domain for standalone meshes, model-surface placement, GLB,
  and 3MF export.
- Preserve transparent canvas margins, material identity, independent shells,
  topology-safe color meshes, and slicer toolpath coverage.
- Keep true out-of-domain geometry rejectable without a broad epsilon.
- Avoid repeated production topology or coverage audits for meshes already
  certified by the canonical builder.

## Non-goals

- Repairing arbitrary defects already present in an uploaded STL or OBJ.
- Requiring the source model to be watertight before model-surface generation.
- Replacing the 3MF format, the native writer, or the slicer.
- Rewriting every geometry workflow in one change.
- Changing nominal printer layer height, visual dimensions, or material count.

An imperfect source model remains usable when its selected planar surface can
be resolved and the existing pocket/assembly operation succeeds. Source-model
defects are not attributed to the generated color overlay and do not fail this
feature's acceptance tests.

## Considered Approaches

### A. Increase per-call tolerances

Smallest diff, but it leaves multiple coordinate authorities and can hide real
overflow. Rejected.

### B. Rebuild model-surface output directly from 2D polygons

This removes the intermediate 3D pattern and is attractive long term, but it
would immediately rewrite Vector, raster, relief, and creative-mode assembly.
The regression surface is too large for this production fix. Deferred.

### C. Canonical coordinate domain carried by the mesh (selected)

The existing integer XY mesher becomes the authority for physical canvas
bounds, while Z is represented by a canonical layer schedule. The resulting
immutable domain travels with the scene. Consumers transform the certified
domain and its mesh together instead of reconstructing dimensions.

## Canonical Contract

Introduce one immutable internal value object named
`LayeredCoordinateDomain`, with these fields:

- `xy_grid_mm`: the writer-safe physical XY grid.
- `canvas_min_units` and `canvas_max_units`: integer XY canvas bounds.
- `layer_boundaries_mm`: canonical cumulative Z boundaries, created once from
  the layer schedule.
- `writer_canvas_bounds_mm` and `writer_z_bounds_mm`: the exact outward physical
  envelope representable by the final float32 writer.
- a version marker identifying the certification contract.

The object owns conversions between integer units, physical float64 values,
and the final writer representation. Callers may not reimplement these
conversions.

The domain is attached to the canonical pattern scene as internal metadata.
It is also available directly while meshing so the writer and model-surface
pipeline do not need to rediscover it from triangle extrema.

## Data Flow

### Vector

1. SVG shapes are clipped and matched as today.
2. The physical XY grid and integer canvas bounds are resolved once.
3. Layer recipes are converted into one ordered Z boundary schedule.
4. Triangles are generated from those integer/layer coordinates.
5. The scene carries the same certified domain used to generate the triangles.

### Raster and high-fidelity

Their existing pixel lattice already supplies integer XY coordinates and layer
indices. The raster pattern producer creates the same domain from those
existing dimensions without changing the voxel meshing algorithm or any public
API. Vector and raster model-surface patterns therefore enter assembly through
the same coordinate contract in this change.

### Model surface

1. Read the certified domain from the prepared pattern.
2. Build the canvas-to-selected-surface transform from the domain's writer
   envelope.
3. Apply that transform to pattern geometry and its printable footprint.
4. Use the canonical Z schedule for embedding depth and slicer layer metadata.
5. Do not recalculate `bbox * scale_factor`, sum layer heights independently,
   or infer the logical canvas from mesh bounds.

Legacy or manually constructed scenes without a certified domain keep the
existing strict bounds validation path for compatibility.

### GLB and 3MF

Both consume geometry generated from the certified domain. The 3MF writer's
float32 conversion remains the final representation step. It may verify array
shape and finite values, but it does not rerun polygon coverage/topology work
already certified by the canonical builder.

## Safety Semantics

- Canvas containment is proven in integer XY units before extrusion.
- Z occupancy is proven against layer-boundary indices before extrusion.
- Independent shell contacts continue to use the bounded writer-domain
  separation policy.
- A consumer may trust the certified domain only when its version and required
  fields are valid.
- Missing or malformed certification falls back to the existing strict legacy
  checks; it never silently grants trust.
- A genuine source polygon outside the integer canvas remains an error.
- A float32 representation of an already-certified boundary is not an error.

## Error Handling

- Invalid canonical-domain construction fails before expensive 3D allocation.
- Malformed certified metadata is a deterministic domain error.
- Existing source-model defects do not trigger a new watertight/manifold gate.
- Failures must distinguish pattern-domain errors from pocket/assembly errors
  and from defects in the uploaded base model.

## Testing

### Focused regression

- Canvas `814 x 947`, target width `115.59999084472656 mm`.
- Float32-upward and float32-downward boundary rounding.
- Five-layer LUT and ten-layer material-archive schedules.
- Transparent margins, non-zero SVG origins, holes, discrete islands, edge
  shapes, and point/diagonal contacts.
- Face-up and face-down placement.
- A true one-grid-unit overflow must still fail.

### Real assets

Use the supplied `vectorized.svg` and `streamdeck.stl` locally without
committing either file. Select the reproduced 544-face, 5238.01659 mm2 planar
surface. The source model's pre-existing topology quality is recorded but is
not a pass/fail gate.

Acceptance requires:

- repeated model-surface generation succeeds;
- material objects and colors remain editable;
- generated overlay regions are not missing;
- Bambu Studio and OrcaSlicer open and slice the project;
- toolpaths exist in the generated overlay layers;
- no new performance or output-size regression beyond measurement noise.

### Regression gates

Run model-surface, vector geometry, unified meshing, writer, worker/API, smoke,
and logging fast gates. Creative modes that reuse the canonical mesher must
retain their existing object/material and auxiliary-geometry behavior.

## Rollout

Land the coordinate-domain contract and its producer/consumer adoption in the
existing topic PR. Do not merge automatically. Validate the supplied real
assets locally, then update the gray deployment for user verification.
