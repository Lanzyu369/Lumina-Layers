# SVG Relief Watertight Preview Design

## Problem

Native SVG relief currently extrudes every backing-height group as an independent
solid and concatenates the solids. Adjacent regions with different heights keep
their shared internal walls. Vertex welding cannot remove those overlapping
surfaces, so the resulting `Board` mesh is non-manifold. The defect survives GLB
serialization and can affect both the in-app preview and the shared 3MF scene.

## Scope

This fix is limited to native SVG relief backing geometry. Flat SVG conversion,
raster relief, optical colour layers, public API signatures, and height selection
semantics remain unchanged. Existing fridge-magnet cavity slabs must continue to
work.

## Design

Convert the existing backing and cavity slab records into one boundary mesh:

1. Collect every distinct Z boundary from the slab records.
2. For each adjacent Z interval, union all active 2D footprints.
3. Generate only the vertical walls of each interval footprint.
4. At each interface, generate an upward cap for `lower - upper` and a downward
   cap for `upper - lower`.
5. Generate the bottom and top caps at the outermost boundaries.
6. Concatenate and weld the boundary pieces into one `Board` mesh.

This constructs the boundary of the volume rather than concatenating overlapping
closed prisms. It uses the existing Shapely and Trimesh dependencies and preserves
vector outlines without rasterization.

## Validation

- A two-region, different-height relief must produce a watertight board with no
  boundary or non-manifold edges.
- A same-height control must preserve bounds and volume.
- A cavity profile that removes and later restores an interior footprint must
  remain watertight and preserve the cavity volume.
- Exporting and loading the minimal relief as GLB must preserve watertightness.
- Existing vector relief, mesh welding, GLB orientation, and converter tests must
  remain green.

## Non-goals

- No optional mesh-kernel dependency changes.
- No frontend rendering changes.
- No redesign of optical layer geometry or relief height sampling.
