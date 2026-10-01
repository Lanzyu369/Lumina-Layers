# SVG coordinate contract v1

## Domains

| Domain | Representation | Permitted consumers |
| --- | --- | --- |
| Source units | Original native bbox/viewport and source-to-mm scale | Metadata, dimensions and temporary read-only projections |
| SVG working domain | Native integers multiplied by an exact power of two; explicit binary grid | Preview/edit point queries, source operations and cache authority |
| Print domain | Integer XY coordinates on one resolved writer grid; Z remains physical millimetres | Labelled partition, run unions, canonical rings and triangulation |
| Output | Millimetres / existing float32 writer representation | Mesh output and rendering; never an inverse reconstruction of source topology |

`SvgCoordinateDomain` preserves `source_grid_size`, `source_mm_per_unit`,
`source_bbox`, optional `source_viewport_bounds`, contract version and tile frame
origin/extent. `grid_size` is the greatest power of two not exceeding the source
grid spacing. Multiplication by this power preserves representable native
integers exactly. The adapter checks the float64 exact-integer range.

Working `bbox` and `scale_factor` change together. Physical lengths are
`working_length * mm_per_unit`; physical areas use its square. The original
source bounds remain available instead of being overwritten with print sizes.
Binary encoding alone does not make arbitrary GEOS operations exact.

## Print handoff

`project_print_regions` has one adoption point before material/run grouping.
The target spacing comes from `resolve_vector_writer_grid_mm`; no nozzle-based
epsilon, colour reduction or geometry-size rejection policy is introduced.

1. Project oriented rings to that grid. The native entry uses `llround`
   (half-grid values round away from zero); negative and half-grid inputs have
   explicit regression coverage.
2. Node shared boundary linework and reuse the existing canonical area exporter.
   Region indices remain associated with their original paint/recipe records.
3. Build target-grid planar cells once using fixed-precision line operations.
   Overlaps are assigned in paint order. Cells without a projected owner are
   queried against the authoritative source; real unpainted holes remain empty.
   Ownership representatives come from a read-only pointwise view with the
   inherited precision flag removed. This preserves every integer cell vertex
   while allowing a representative to lie between print-grid points. The same
   representative is used for projected ownership and source-domain fallback;
   the printed cells themselves remain on the integer grid.
4. Re-express each already-owned integer region using the shared native
   `BuildFilledFaces` rule by passing its owned cell rings directly. Do not
   first dissolve touching cells into a potentially self-touching GEOS wrapper.
   This splits point-touching faces without a second Clipper boolean cleanup
   that might discard a positive-area short-edge triangle. The operation checks
   integer input and does not scale or round it.
   No changed grid, exception-driven retries or legacy backend rerun is used.
5. Run-group union explicitly supplies the grid. The sparse floating fast path
   is retained only for the pre-existing unqualified/legacy route.

`svg_print_grid_mm` travels with prepared slabs, including material-worker
transport. These slabs bypass the old scale-then-snap preparation. Triangulators
receive integer print coordinates; final millimetre vertices still pass existing
float32, boundary-incidence and area checks.

Auxiliary slabs are prepared on the same spacing. Their intentional overlaps at
different Z intervals are not treated as conflicting paint ownership. Existing
functional backing cleanup and optional hole filling are preserved, with their
source length/area constants converted explicitly.

## State and lifecycle

- Native geometry and `VectorAnalysis` restore declared precision on deepcopy /
  pickle. Working WKB is usable only with its explicit domain; precision hidden
  in a Shapely object is not a persistence contract.
- Parse/clip artifact schema is v5. Its key includes coordinate-contract version
  and the actual loaded extension digest, in addition to native version/schema
  and existing input/options. Provenance-only readers also verify the runtime.
- The digest is cached for the loaded extension module. Replacing a disk file
  does not relabel already-loaded native code as a new build.
- Old artifacts are rebuilt from the retained source. Edited RGB/material masks
  remain separate confirmed state; no global cache purge is performed.
- A native tiling request prepares its global print partition once. Cut lines
  use shared grid positions, and local tile translation is integral in that
  domain. Each tile retains original source bounds plus its own frame metadata.
  Build operations reuse the prepared tile partition rather than quantizing
  every tile independently.
- `VectorStructurePlan` explicitly carries its physical scale and grid, so
  backing/outline/coating operations need not first round-trip through mm views.

## Consumer audit

| Consumer | Handling |
| --- | --- |
| Preview/cache/colour area weighting | Work geometry with matching scale/bbox; source areas and physical comparisons are tested |
| Analytic/segmented GLB | Temporary physical display views; structural constants use the source mapping; these views do not replace topology authority |
| RGB/material masks and recipe overrides | Pixel grids remain unchanged; working-to-pixel scale remains paired with bounds; lifecycle tests include edits then normal/tiled generation |
| Silhouette/backing/outline/coating | Explicit structural work domain; auxiliary print slabs enter the shared writer grid |
| Relief and magnet cavities | Projected optical regions use the same grid; heights stay in mm; grid-aware intersections/differences and auxiliary slab preparation |
| Keychain geometry | Existing physical placement/mesh integration retained; source-to-mm pairing and contour regressions retained |
| Optional SVG hole compensation | Original region objects retained; new native patch coordinates return through an explicit working-domain projection |
| Large format | Shared pre-tiling print partition, integral cuts/translations, retained source/frame metadata |
| Puzzle | Existing source/cache and physical clipping paths retained; no request/schema change; backend smoke covers its API contracts |
| Model surface | Consumes physical meshes and placement. No surface/UV parameter changes; canvas-to-mm pairing is retained |
| Final file lifecycle | FileRegistry/TTL/response contracts unchanged; original-input validation fetches the 3MF after source session close |

## Quantization and evidence limits

Finite print-grid projection can collapse sub-grid features. Counters identify
collapsed regions and initial grid overlaps. Validation checks per-region
validity, inter-region overlap, holes/islands, local coverage differences and
material recipes, not only total area.

For the reported input, measured printed regions have zero invalid polygons and
zero area-overlap pairs. Visible-input samples away from the quantization
boundary preserve colour and recipe. Differences against the independently
projected silhouette are recorded in the validation report, including source
ownership checks; they are not silently described as exact equality.

The runtime diagnostic reports extension path/digest, coordinate version and
Shapely/GEOS versions. Packaging rejects an installed native library lacking the
projection entry point even when its package version still reads 0.3.0.
