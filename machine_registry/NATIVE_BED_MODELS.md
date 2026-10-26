# Native build-plate model policy

The machine registry stores only the upstream STL **filename** in each
machine's `bed_model` field. Lumina Studio does not copy third-party slicer
models into this repository.

At runtime, the backend resolves that basename inside the matching slicer's
installed profile directory and serves it only for the corresponding slicer
and vendor. Absolute paths, parent segments, non-STL files, cross-slicer
fallbacks, and paths escaping the detected profile root are rejected. If the
selected slicer is not installed or its model is unavailable, the frontend
uses Lumina's own dimensional irregular fallback plate.

This boundary is intentional:

- users who have the selected slicer installed see that installation's native
  bed silhouette;
- packaged Lumina builds remain independent of and do not redistribute
  BambuStudio, OrcaSlicer, or vendor-fork STL assets;
- registry generation can refresh model filenames from local profile metadata
  without copying the referenced binary.

`tools.machine_adapter.sync_local_profiles` refuses to overwrite the registry
when it discovers no profile sources. Run it against a temporary output
directory first when refreshing machine metadata.
