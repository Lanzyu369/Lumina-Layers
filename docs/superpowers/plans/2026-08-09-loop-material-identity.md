# Loop Material Identity Repair Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent S05 keychain-loop preview failures when the selected material
ID is absent from a stale `color_conf`, while keeping the 2D preview, auxiliary
mesh, status message, and exported slicer material identity aligned.

**Architecture:** Treat `ctx["preview_colors"]` plus `ctx["slot_names"]` as the
authoritative material-ID contract established by S01/P01. Add one adopted
resolver in `preview_color_utils`, use it from S05 and S08, and carry the
resolved material name and color in `loop_info`. Exact `color_conf` and
canonical-name matches are compatibility fallbacks; an out-of-range material
ID or a completely unresolved color must emit one structured warning and stop
the loop path instead of inventing white/gray or an extra filament. Validate
recipe-override material IDs before they can enter `material_matrix`.

**Tech Stack:** Python 3.14, NumPy, Pillow, trimesh, pytest, structured logging.

---

### Task 1: Lock the authoritative material-style contract

**Files:**
- Modify: `tests/test_preview_color_utils_unit.py`
- Create: `tests/test_loop_material_identity_unit.py`

- [x] **Step 1: Add resolver tests for supported key shapes**

Cover integer keys, stringified integer keys, and slot-name keys. Assert that
`slot_names[material_id]` remains the material identity and that the returned
RGBA comes from `preview_colors` before a stale `color_conf`.

Also cover invalid RGBA and an out-of-range ID. Neither case may borrow slot 0,
clamp the ID, or return an invented material identity.

- [x] **Step 2: Add a parameterized S05 red test for 4/5/6/8-color palettes**

For each mode, place the highest valid material ID around the loop attachment
point, pass an intentionally smaller `color_conf`, and pass the complete
authoritative `preview_colors` / `slot_names` in the context. Assert that S05
finishes, preserves `color_id`, records the corresponding material name, and
draws the loop with the authoritative color.

Run:

`.venv/bin/python -m pytest tests/test_loop_material_identity_unit.py -k 's05' -v`

Expected red state: current S05 raises `KeyError` from
`color_conf['preview'][loop_info['color_id']]`.

- [x] **Step 3: Add a material-archive identity case**

Use a Chinese/custom material name with preview colors keyed by that name.
Assert the selected ID, material name, and RGBA remain aligned without assuming
English labels or `base_channel_idx == 0`.

### Task 2: Resolve and draw the loop from authoritative preview metadata

**Files:**
- Modify: `core/pipeline/preview_color_utils.py`
- Modify: `core/pipeline/s05_preview_generation.py`

- [x] **Step 1: Implement one shared material-preview resolver**

The resolver must:

1. derive the material name only from a valid `slot_names[material_id]`;
2. resolve RGBA from `preview_colors` by integer ID, string ID, then material
   name;
3. consult numeric `color_conf` entries only when its slot at the same ID has
   the exact authoritative name; an exact material-name key remains a safe
   compatibility fallback;
4. use an exact canonical material-name color only when that name has one
   unambiguous canonical match;
5. return an unresolved result when the ID has no authoritative material name
   or no usable color remains;
6. never replace or renumber the input material ID.

- [x] **Step 2: Adopt the resolver in S05**

Populate `loop_info.material_name`, `loop_info.color_rgba`, and
`loop_info.color_source`, then draw from that resolved RGBA. If identity or
color is unresolved, emit one WARNING event with fixed `event`, `error_type`,
`error_message`, `reason`, material ID, mapping counts, and resolution attempts,
then raise a clear `ValueError`. Do not include a path or user material label.
S08 must recognize the populated fields so the normal S05→S08 chain cannot log
the same resolution incident twice.

`resolution_attempts` contains fixed source labels only (for example,
`preview_int`, `preview_str`, `preview_name`, `color_conf_int`); it must not
contain attempted keys or material names.

Add a mismatch case where the authoritative slot is a custom material while
the stale `color_conf` uses the same numeric ID for another color. It must
remain unresolved instead of silently borrowing the stale color.

- [x] **Step 3: Verify S05 and resolver tests turn green**

Run:

`.venv/bin/python -m pytest tests/test_preview_color_utils_unit.py tests/test_loop_material_identity_unit.py -k 'resolver or s05' -v`

Expected: all valid cases pass; invalid cases fail deterministically without a
white/gray or slot-0 substitution.

### Task 3: Preserve the same identity in the generated loop mesh and result

**Files:**
- Modify: `core/pipeline/s08_auxiliary_meshes.py`
- Modify: `core/pipeline/s12_result_assembly.py`
- Modify: `tests/test_s08_material_archive_auxiliary_meshes_unit.py`
- Modify: `tests/test_loop_material_identity_unit.py`

- [x] **Step 1: Add a red S08 identity test**

Pass a loop with an authoritative material mapping that is not available by a
direct integer lookup. Assert the generated `Keychain_Loop` mesh has the same
RGBA, its `bambu_material_name` equals the selected slot, and
`preview_colors['Keychain_Loop']` is populated for the 3MF writer.

- [x] **Step 2: Adopt the resolver in S08**

Use the same resolved style for face colors and `bambu_material_name`; keep the
geometry name `Keychain_Loop`. Populate the name-keyed preview color so export
does not invent an extra visual color. A direct legacy S08 invocation may
resolve from context, but an unresolved identity/color must emit the same
structured warning and abort rather than being swallowed by the existing loop
`except` block. Geometry construction failures remain degradable: record an
actionable structured warning, leave `loop_added=False`, and continue the
otherwise valid model.

- [x] **Step 3: Make S12 status assembly bounds-safe**

Prefer `loop_info.material_name`; otherwise use a bounds-checked slot lookup
and a deterministic material-ID label. Never let status text reintroduce an
index failure after the model was generated.

- [x] **Step 4: Verify the preview-to-export identity chain**

Run S05 then S08 in one test and assert one unchanged `color_id`, one material
name, one RGBA, and the expected slicer metadata. Export an actual temporary
3MF and inspect `Metadata/model_settings.config` plus project filament arrays:

- `valid_slot_names` contains `Keychain_Loop`;
- `project_slot_names` does not contain it and retains its original order;
- `preview_colors["Keychain_Loop"]` equals the resolved RGBA;
- the mesh `bambu_material_name` equals the selected project slot;
- the `Keychain_Loop` part's extruder points to that slot and no fifth
  `Keychain_Loop` filament is created.

### Task 4: Reject material IDs that cannot belong to the active palette

**Files:**
- Modify: `api/routers/converter/replace.py`
- Modify: `tests/test_converter_recipe_override_unit.py`

- [x] **Step 1: Add a material-archive red test**

Seed a static material-archive session with three selected materials, submit a
recipe containing material ID `3` without declaring a virtual material, and
assert HTTP 422. Before the fix the endpoint returns 200 and persists `3` into
a palette containing only IDs `0..2`.

- [x] **Step 2: Validate against the runtime palette at the API boundary**

When source metadata exposes a non-empty palette, validate every recipe index
against `palette length + declared virtual material count`, regardless of
whether the request includes virtual materials. Preserve the legacy empty-LUT
metadata compatibility path, and keep dynamic-material validation semantics.

- [x] **Step 3: Run focused recipe-override tests**

`.venv/bin/python -m pytest tests/test_converter_recipe_override_unit.py -k 'out_of_range or material_archive or virtual' -v`

Expected: invalid native IDs return 422; valid native, virtual-material, and
dynamic-material cases remain green.

### Task 5: Focused verification and isolated commit

**Files:**
- Verify all files above

- [x] **Step 1: Run direct loop/color tests**

`.venv/bin/python -m pytest tests/test_preview_color_utils_unit.py tests/test_loop_material_identity_unit.py tests/test_s08_material_archive_auxiliary_meshes_unit.py tests/test_pipeline_step_modules_unit.py -v`

- [x] **Step 2: Run converter and 3MF contract tests selected by affected boundaries**

Run focused tests covering raster preview/generation, auxiliary mesh metadata,
Bambu material sharing, and S11's existing int/string/name GLB color resolution
to prove the GLB contract did not regress. Do not run unrelated release suites.

- [x] **Step 3: Run logging governance and fast log gate**

`.venv/bin/python -m pytest tests/test_logging_exception_governance_unit.py tests/test_structured_logging_unit.py tests/test_logger_unit.py -v`

`.venv/bin/python scripts/log_quality_check.py --mode fast`

- [x] **Step 4: Scan touched UTF-8 files and run `git diff --check`**

- [x] **Step 5: Request clean final review and commit separately**

Commit message:

`fix(converter): preserve keychain loop material identity`
