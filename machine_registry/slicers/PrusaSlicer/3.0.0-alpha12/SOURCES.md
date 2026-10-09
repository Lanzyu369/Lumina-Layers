# Prusa printer picker artwork

These 18 PNG files are 512-pixel renders of Prusa Research printer SVGs from the
PrusaResearch FFF preset bundle **1.0.11**, bundled with
[PrusaSlicer 3.0.0-alpha12](https://github.com/prusa3d/PrusaSlicer/releases/tag/version_3.0.0-alpha12).
They are third-party artwork, not Lumina-authored images. Their original
upstream rights remain unchanged.

The acquisition used the official macOS release package with SHA-256
`bac96d86563413b97c4141d8986089a6c2b0b54d69fcf4999caa06b482097bba`.
Each filename comes from the selected native hardware configuration's
`preset.hw_config.thumbnail`, exposed in FatCat's public project result.
No printer-family guesses or alternative model pictures are introduced.

`picker-assets.json` maps the 32 currently exposed hardware selections to these
18 shared files. The existing `resvg-py` dependency renders the original artwork
without changing its contents. It stores presentation paths and provenance only; printer,
material and process settings remain owned by FatCat. Regenerate it with
`python -m tools.machine_adapter.sync_prusa_assets`, using the corresponding
native `PrusaResearch/assets` directory and installed FatCat dependency.
