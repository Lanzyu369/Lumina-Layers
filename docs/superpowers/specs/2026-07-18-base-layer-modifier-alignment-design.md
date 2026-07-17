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
   height lands exactly on the backing boundary. A backing on the build plate
   must account for Bambu's independently fixed first-layer height.
3. The resolver uses the selected printer template's layer-height limits and a
   conservative nozzle-based ceiling.
4. Candidate layer heights use 0.02 mm increments and produce at least two
   backing layers: two coarse layers above the colour stack, or one fixed first
   layer plus at least one coarse layer when the backing touches the build plate.
5. Selection stays as close as possible to the existing half-nozzle target;
   ties prefer the smaller layer height.
6. If no compatible candidate exists, omit the modifier instead of changing
   model geometry or accepting a truncated slice.
7. Existing public export call sites remain compatible; the new initial-layer
   and printer-limit parameters are optional keyword-only inputs. An omitted
   initial-layer value safely disables a `face=up` modifier.

## Design

`build_layer_config_ranges_xml` remains the convergence point for deciding
whether metadata is safe to emit. A focused resolver converts the backing
height and candidate layer heights to integer 0.02 mm ticks, eliminating
floating-point modulo errors. For `face=down`, it divides the whole backing
range. For `face=up`, it first subtracts the actual
`initial_layer_print_height`, because Bambu does not apply the modifier to that
first layer. It filters candidates by fine-layer height, printer
minimum/maximum, a 70%-of-nozzle safety ceiling, exact boundary alignment, and
the two-layer minimum. It then chooses the candidate nearest the historic
50%-of-nozzle target.

`BambuStudio3MFWriter` reads `min_layer_height` and `max_layer_height` from the
same printer template used to build `project_settings.config`. For multi-nozzle
arrays it takes the strict shared interval: the largest minimum and the
smallest maximum. It also passes the actual configured fine layer height and the
template's effective `initial_layer_print_height` rather than relying on the
builder's 0.08 mm defaults.

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
- Unit tests prove a 0.24 mm `face=down` backing resolves to 0.12 mm for both
  0.2 and 0.4 mm nozzles.
- Unit tests prove a 0.24 mm `face=up` backing with a 0.08 mm first layer uses
  0.16 mm on a 0.4 mm nozzle and safely skips on a 0.2 mm nozzle.
- Unit tests prove the historic 0.4/0.8 -> 0.2 and 0.2/0.4 -> 0.1 cases remain.
- Property tests assert every emitted layer height exactly aligns the backing
  boundary for its orientation and stays inside the supplied bounds.
- Writer integration tests assert printer-template bounds are forwarded.
- A real Bambu Studio CLI slice checks that the 0.24 mm double-sided scenario
  keeps the full 1.04 mm model height after the modifier is omitted.
- Real Bambu Studio CLI and GUI slices check a 0.24 mm `face=up` backing: the
  0.4 mm nozzle uses 0.08 + 0.16 mm backing layers and reaches 0.64 mm in seven
  layers, while the 0.2 mm nozzle safely skips the modifier and reaches the same
  height in eight layers. The five colour layers are inspected individually.
