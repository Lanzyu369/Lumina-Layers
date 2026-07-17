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

Prefer the project's existing optional `manifold3d` kernel for the expensive
solid-union step:

1. Normalize the existing backing and cavity slab records and group them by
   area-connected XY footprint. Point-touching footprints stay separate.
2. Convert every already-merged polygon (including interior rings) to a
   `CrossSection`, extrude it at its existing Z offset, and union the solids in
   each group with `Manifold.batch_boolean(..., OpType.Add)`.
3. Validate the complete result against the source slabs: finite coordinates,
   watertight topology, expected bounds, and analytical union volume.
4. If `manifold3d` is missing, cannot load on the host, raises at runtime, or
   returns an invalid result, discard the complete native result and rebuild
   the whole Board with the current exact Python atomic-prism algorithm.

The preferred path asks the native kernel to construct the union boundary
directly, avoiding hundreds of temporary closed prisms and Python tuple-based
internal-face deletion. The exact fallback preserves correctness on base installs
and platforms without a compatible wheel; neither path rasterizes vector outlines.

## Validation

- A two-region, different-height relief must produce a watertight board with no
  boundary or non-manifold edges.
- A same-height control must preserve bounds and volume.
- A cavity profile that removes and later restores an interior footprint must
  remain watertight and preserve the cavity volume.
- The fast and forced-fallback kernels must agree for non-zero Z offsets, XY
  scaling, cavities, and point-touching independent shells.
- Import failures, native runtime failures, and invalid native results must use
  the exact whole-Board fallback without losing geometry.
- Exporting and loading the minimal relief as GLB must preserve watertightness.
- Windows CI must install the optional kernel requirements and run both the fast
  and forced-fallback regression paths.
- Existing vector relief, mesh welding, GLB orientation, and converter tests must
  remain green.

## Desktop release contract

Source and basic development installs may omit `requirements-glb-v2.txt`; the
exact Python fallback remains available there for compatibility. The formal
Windows desktop release is different: `python scripts/build_desktop.py` is the
single supported Electron packaging entry point and must run with both
`rasterio.features` and `manifold3d` installed and importable.

The release workflow builds through that entry point, not the legacy standalone
`main.py` PyInstaller command. Both `build_desktop.py` and direct execution of
`lumina_studio.spec` fail before producing a release when either required module
cannot load. After PyInstaller and Electron packaging, CI executes the frozen
`lumina-backend.exe --desktop-native-kernel-smoke` command. The command imports
both native packages from the frozen application, forbids the Python relief
fallback, constructs a two-height vector relief Board, and reports water-tight
bounds and volume evidence. The Windows installer, frozen backend, and JSON
smoke report are uploaded together as the release-gate artifact.

## Non-goals

- No move of native wheels into the base `requirements.txt`; they remain optional
  for source installs but mandatory for formal Electron desktop releases.
- No frontend rendering changes.
- No redesign of optical layer geometry or relief height sampling.
