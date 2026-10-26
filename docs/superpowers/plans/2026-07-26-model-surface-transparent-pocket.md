# Model Surface Transparent Pocket Fix Implementation Plan

> **Issue:** LUM-20260725-003
>
> **Goal:** Preserve the original model surface under transparent artwork
> while cutting a pocket only below printable raster or native-SVG geometry.

## Task 1: Lock the regression with a failing raster assembly test

**Files:**

- Modify: `tests/test_model_surface_assembly_unit.py`

**Steps:**

1. Build a `20 x 10` logical raster canvas whose only printable region is a
   `4 x 2` rectangle.
2. Assemble it into a `20 x 10` plate with the boolean path enabled.
3. Measure upward horizontal faces on the exported base mesh.
4. Assert that `192 mm²` remains at the original surface Z and only `8 mm²`
   becomes pocket floor.
5. Run:

   ```bash
   python -m pytest \
     tests/test_model_surface_assembly_unit.py \
     -k transparent_canvas -q
   ```

6. Confirm the test fails because the current implementation removes the
   entire original top plane.

## Task 2: Introduce a typed prepared-pattern boundary

**Files:**

- Modify: `core/model_surface/assembly.py`
- Modify: `core/model_surface/pipeline.py`
- Modify: `tests/test_model_surface_slot_meshing_unit.py`

**Steps:**

1. Add `PreparedSurfacePattern(scene, printable_footprint)` with bilingual
   public documentation.
2. Preserve compatibility properties needed by existing private tests while
   making the converter path consume the typed value.
3. Add validation for empty or invalid printable footprints.
4. Keep the existing `build_embedded_overlay_scene()` parameter names and
   the existing `cut_surface_pocket()` signature.
5. Run the focused slot-meshing and assembly tests.

## Task 3: Build the raster footprint from final printable voxels

**Files:**

- Modify: `core/model_surface/slot_meshing.py`
- Modify: `core/model_surface/pipeline.py`
- Modify: `tests/test_model_surface_slot_meshing_unit.py`

**Steps:**

1. Add a focused helper that marks a pixel printable only when at least one
   displayed Z layer contains a valid material slot.
2. Partition the mask with the same greedy rectangle coordinates used by the
   box mesher.
3. Convert rectangles to pixel-corner Shapely geometry using the same Y flip
   and `pixel_scale`.
4. Test transparent margins, disconnected islands, invalid material IDs and
   one-pixel-wide features.
5. Run:

   ```bash
   python -m pytest tests/test_model_surface_slot_meshing_unit.py -q
   ```

## Task 4: Build the native-SVG footprint from final printable meshes

**Files:**

- Modify: `core/model_surface/pipeline.py`
- Modify: `tests/test_model_surface_assembly_unit.py`

**Steps:**

1. Read the final normalized material meshes rather than the pre-extrusion
   SVG silhouette.
2. Select their upward horizontal cap triangles and project them to XY.
3. Build polygons with Shapely's vectorized API and union them across slots.
4. Verify the footprint agrees with the normalized native vector pattern
   scene for face-up and face-down orientation.
5. Add a test proving an all-Air shape does not expand the pocket and a
   post-normalization mesh change is reflected in the pocket.

## Task 5: Cut only the transformed printable footprint

**Files:**

- Modify: `core/model_surface/assembly.py`
- Modify: `tests/test_model_surface_boolean_unit.py`
- Modify: `tests/test_model_surface_assembly_unit.py`

**Steps:**

1. Extract the current boolean operation into a private polygon-cut helper.
2. Keep `cut_surface_pocket()` as the full-surface compatibility wrapper.
3. Add a pattern-aware cutter that maps the pattern footprint through the
   same logical-canvas scale and translation used by the 3D pattern.
4. Intersect the mapped polygon with the selected surface polygon so model
   holes and irregular boundaries remain untouched.
5. Make `build_embedded_overlay_scene()` use this path for
   `PreparedSurfacePattern`.
6. Re-run the new regression and all focused model-surface tests.

## Task 6: Cover transparent PNG and SVG generation paths

**Files:**

- Modify: `tests/test_model_surface_generate_unit.py`
- Modify: `tests/test_model_surface_assembly_unit.py`

**Steps:**

1. Add a transparent-PNG converter context test that reaches the prepared
   raster pattern and assembly boundary.
2. Add a sparse native-SVG converter context test with valid and Air recipes.
3. Assert both paths pass the prepared footprint rather than the full canvas.
4. Run:

   ```bash
   python -m pytest \
     tests/test_model_surface_generate_unit.py \
     tests/test_model_surface_assembly_unit.py -q
   ```

## Task 7: Reproduce the user workflow with the real attachments

**Files:**

- Read only:
  - `/Users/min/Library/Containers/com.tencent.qq/Data/Downloads/svg敷面bug.zip`
  - ticket LUT attachment or the exact corresponding local RYBW LUT
- Temporary output only: a directory created with `mktemp -d`

**Steps:**

1. Extract the ZIP into a unique temporary directory without modifying the
   original attachment.
2. Load `MSkadis_160.stl`, select its largest upward planar surface, and use
   the same placement/rendering path as the UI.
3. Generate an overlay from `vectorized.svg` through the actual converter and
   worker/export path.
4. Repeat with a transparent PNG rendered from the same artwork.
5. Parse the resulting 3MF objects and compare:
   - overall bounds against the original model;
   - original-surface horizontal area under transparent regions;
   - pocket-floor area against printable artwork coverage;
   - color object names, material count and top Z.
6. Keep compact evidence in test output, then move temporary extracted input
   and generated artifacts to Trash or remove the unique temporary directory.

## Task 8: Final regression and hygiene verification

**Files:**

- Review all modified files.

**Steps:**

1. Run:

   ```bash
   python -m pytest \
     tests/test_model_surface_boolean_unit.py \
     tests/test_model_surface_slot_meshing_unit.py \
     tests/test_model_surface_assembly_unit.py \
     tests/test_model_surface_generate_unit.py \
     tests/test_model_surface_preview_integration_unit.py -q
   ```

2. Run the broader model-surface family:

   ```bash
   python -m pytest tests/test_model_surface_*.py -q
   ```

3. Inspect `git diff --check`, `git diff --stat`, and `git status --short`.
4. Re-open all edited bilingual source files as UTF-8 and scan them for common
   mojibake markers.
5. Confirm no server, Vite, Vitest or worker process was left running.
