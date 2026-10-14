# Materials and Lumina Box

## Public workflow

Photo-gradient archives (`stage_a`) and LUT conversion retain their existing
behavior. The only public Box workflow is single-filament black/white-backed
capture using `backed_gradient_spectral_four_flux_smooth/v3`. Historical archives
remain readable; public Box lists show current profiles.

One filament has seven overlay thicknesses: 0.08, 0.16, 0.24, 0.32, 0.64, 1.28,
2.00 mm, on both W/K backings. Each card totals 3 mm and uses its real 3-d backing.
Measure the bed-contact face. Layer height is not an acquisition form field.
Zero and finite above-100 readings are retained. Only reflection enters fitting.

A shared backing setup contains W/K material parameters and bare 3 mm anchors.
Initial capture is seven W-on-K, seven K-on-W, plus two bare references.
First use registers both filament identities with `POST /black-white-pairs` in
one transaction. With existing profiles, users can choose paired creation again
or create one filament against an existing opposite filament. Black/white fitting publishes ordinary standalone profiles together
with the backing models. `backing_material_id` binds each profile to its stable
identity; the same profile supports printing and backing selection. The library
owns record navigation and unfinished black/white captures. Creation forms never
contain a list of existing profiles. Initial paired records are materialized by
the one-time local data upgrade; runtime reads do not project legacy references.
Backing-only data are underdetermined: initial parameters seed a group, and later
individually captured filaments can jointly refine its calibration. Earlier
complete v3 results split into profiles without changing their predictions.
Established references retain the fast fixed-reference single-filament path.

## Data and execution

- `backed_gradient_store.py`: durable captures, selections, replay receipts, jobs.
- `backed_gradient_product_store.py`: single-filament identities and backing groups.
- `backed_gradient_material.py`: independent typed components and propagation.
- `backed_gradient_material_fitting.py`: material and shared calibration fitting.
- `backed_gradient_archive.py`: standalone profile persistence.
- API prefix: `/api/extractor/lumina-box/backed-gradient`.

The product uses references, material-datasets, black-white-pairs,
backing-material-datasets and their fit-runs;
existing capture/history/import/export endpoints are reused. CPU fitting runs in
file-based workers. USB ACK follows durable save; replay is deduplicated.
Switching material/backing settles pending writes and changes capture identity
without disconnecting. Detailed transport is in [USB acquisition](usb-acquisition.md).

## Model and converter contract

Material identity is separate from color category. Multiple red or white
filaments can coexist without replacing the actual calibration backings.
The fixed 95-band basis, direct/diffuse propagation, repeated returns, outer
surfaces and .003 color absorption-curvature penalty retain v3 behavior.
Touching internal layers have no air boundary. Apply the shared W/K observation
map once after the entire stack.

Product recipes are slot-index matrices ordered bottom-to-top and return percent
XYZ. The converter divides by 100 once and uses the existing versioned XYZ bridge
for matching/display. Propagate the selected physical backing and printed
thickness; the 3 mm calibration anchors remain fixed. Candidate and dynamic cache
descriptors include component/reference/backing parameters and print geometry.
Batch prediction is chunked with repeated layer-prefix reuse.

## Archives and transfer

Each profile contains material.json,
lumina_box_backed_gradient_measurements.json and
lumina_box_backed_gradient_parameters.json. Its distinct schema is 1.0,
profile_kind is lumina_box, and acquisition_source is lumina_box_backed_gradient.
Parameters include the complete backing reference. Measurements retain selected
readings, raw frames/history and capture_export for continuing on another computer.

Transfer bundles use schema 5.0. Import restores capture records and registers the
embedded reference. Old bundle readers remain. Identity edits preserve optical
sidecar bytes; replacement retains previous files under .history. Feedback uses
the same three files. Share recipes preserve actual source/model/material/backing
settings. Final exported downloads survive source-session closure.

Verification covers actual v3 split/recombine parity on both 1024 backings,
independent material fitting, replay/history, archive transfer and continuation,
raster/native-SVG previews and real 3MF generation.
