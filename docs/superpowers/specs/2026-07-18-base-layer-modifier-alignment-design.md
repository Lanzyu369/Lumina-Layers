# Base-Layer Modifier Alignment Design

## Problem

Lumina exports a Bambu `layer_config_ranges.xml` entry for the backing plate.
The current writer always uses half the nozzle diameter (`0.4 -> 0.2 mm`,
`0.2 -> 0.1 mm`) and accepts `face="double"`. This violates the documented
double-sided skip rule and does not ensure that the selected coarse layer
height divides the backing range exactly.

Bambu Studio does not insert a remainder layer at a modifier boundary. For a
0.24 mm backing range, both 0.2 mm and 0.1 mm leave 0.04 mm unrepresented. In
a double-sided model that shifts the upper color stack and removes the final
0.04 mm of the model.

## Requirements

1. Double-sided exports never contain the base-plate layer-height modifier.
2. Other orientations retain the speed optimization only when a coarse layer
   height can divide the backing thickness exactly.
3. The resolver uses the selected printer template's layer-height limits and a
   conservative nozzle-based ceiling.
4. Candidate layer heights use 0.02 mm increments and produce at least two
   backing layers.
5. Selection stays as close as possible to the existing half-nozzle target;
   ties prefer the smaller layer height.
6. If no compatible candidate exists, omit the modifier instead of changing
   model geometry or accepting a truncated slice.
7. Existing public export call sites remain compatible; new limit parameters
   are optional keyword-only inputs.

## Design

`build_layer_config_ranges_xml` remains the convergence point for deciding
whether metadata is safe to emit. A focused resolver converts the backing
height and candidate layer heights to integer 0.02 mm ticks, eliminating
floating-point modulo errors. It filters candidates by fine-layer height,
printer minimum/maximum, a 70%-of-nozzle safety ceiling, exact divisibility,
and the two-layer minimum. It then chooses the candidate nearest the historic
50%-of-nozzle target.

`BambuStudio3MFWriter` reads `min_layer_height` and `max_layer_height` from the
same printer template used to build `project_settings.config`. For multi-nozzle
arrays it takes the strict shared interval: the largest minimum and the
smallest maximum. It also passes the actual configured fine layer height rather
than relying on the builder's 0.08 mm default.

No API, frontend state, share-card field, or geometry parameter changes. Batch
merging continues to preserve source metadata, so corrected single-item files
automatically yield corrected merged files.

## Error Handling

Invalid numeric inputs retain the existing `ValueError` behavior. Non-positive
geometry, invalid faces, double-sided faces, impossible printer bounds, and
non-divisible backing ranges return `None`, which already means "do not add
layer_config_ranges.xml" to the package.

## Verification

- Unit tests prove double-sided metadata is skipped.
- Unit tests prove 0.24 mm resolves to 0.12 mm for both 0.2 and 0.4 mm nozzles.
- Unit tests prove the historic 0.4/0.8 -> 0.2 and 0.2/0.4 -> 0.1 cases remain.
- Property tests assert every emitted layer height exactly divides the backing
  range and stays inside the supplied bounds.
- Writer integration tests assert printer-template bounds are forwarded.
- A real Bambu Studio CLI slice checks that the 0.24 mm double-sided scenario
  keeps the full 1.04 mm model height after the modifier is omitted.
