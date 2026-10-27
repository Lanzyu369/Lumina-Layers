# Lumina-owned build-plate selector artwork

Lumina Studio ships one shared set of six neutral build-plate images for the
settings selector. These images are app-owned, contain no slicer or printer
branding, and are generated deterministically by
`tools/machine_adapter/build_plates.py`.

The artwork is presentation-only. The registry stores picker IDs, translated
labels and image provenance. FatCat owns the 3MF project/plate/sidecar values;
they are not duplicated in the app registry. The import tool uses native plate
names only to resolve picker support and defaults from pinned machine and
nozzle profile settings, including the intersection across nozzle variants.
Anycubic Kobra S1 Engineering Plate is a narrow version-and-machine exclusion
based on a real slice that produced zero bed temperature. Replacing the artwork
does not infer or broaden a printer's build-plate support.

The following provenance fields describe only the Lumina-owned artwork:

- `source_path`: `LuminaStudio:generated/build_plates/<filename>`
- `source_version`: `lumina-neutral-v1`
- `revision`: SHA-256 of the generated PNG
- `image`: the shared `build_plates/<filename>` path

The six generated PNGs are transparent 320 x 220 RGBA images. Regenerate the
shared artwork and refresh registry provenance without changing machine
capability data with:

```bash
python -m tools.machine_adapter.update_build_plates \
  --registry-root machine_registry
```

When pinned native profiles are also available, pass the existing `--source`
arguments. The updater then recomputes per-machine support/default values and
machine/nozzle capability intersections from those profiles while writing the
same picker IDs, labels and Lumina-owned image set.
