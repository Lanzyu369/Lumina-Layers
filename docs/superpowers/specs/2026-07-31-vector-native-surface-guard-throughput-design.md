# Vector Native Surface Guard Throughput Design

**Date:** 2026-07-31

**Status:** approved direction, written-spec review pending

**Branch:** `MOVIBALE/feat/vector-native-mesh-throughput`

**Dependency:** PR #540 / commit `2a962c309c4f44955649586ef86d6622eea24bf5`

## 1. Outcome

Reduce the remaining SVG/vector mesh-extrusion bottleneck without changing
the current production-native model, geometry, material, recipe, layer,
visual, GLB, or 3MF semantics.

The first implementation target is deliberately narrow:

1. strengthen the compiled `clipper2_batch` module so it proves the complete
   closed-extrusion surface contract inside the native boundary;
2. advertise that proof through a versioned capability;
3. when the capability is present, avoid repeating the same expensive
   Shapely union and Trimesh surface-area calculation in Python;
4. preserve the same per-group Trimesh partitioning and append order, so the
   optimization does not rely on regrouping or retriangulating output.

If this does not reach the performance gate, the change is not declared
successful. Only then may a second, separately measured step target the
existing native-empty fallback groups. New task-local threads are not part of
the initial implementation.

## 2. Scope

### Included

- `native/clipper2_batch/clipper2_batch_module.cpp`
- the native capability contract consumed by `core/vector_native_mesh.py`
- the Python validation decision at the native boundary
- bounded native/fallback timing and counter fields on an existing completion
  event; no additional INFO event
- existing native-mesh and multicore profilers as the adoption sites
- 8-, 12-, and 15-color Material Archive verification
- matched-RGB and no-override vector generation
- Docker and desktop native-extension build-contract verification

### Excluded

- SVG parsing, path flattening, and occlusion optimization
- raster S02, S07, GLB, or 3MF optimization
- changing material matching, region replacement, recipes, layer order, or
  output naming
- changing outer worker scheduling or `LUMINA_MAX_WORKERS`
- adding an ROI/component executor or process fallback
- changing V1/V2 selection or fallback semantics
- server access, deployment, container restart, or environment mutation

This is a stacked local branch while PR #540 is open. It must not create a
follow-up PR until #540 is merged and the branch is rebased onto the resulting
`origin/dev-refactor`.

## 3. Evidence and problem statement

The ROI change in PR #540 removes the former first hotspot. On its 200 mm,
12-color reference workload, `matched_rgb_override_s` fell to roughly
`0.7 s`, leaving extrusion and assembly as the largest local stage.

Production builds already compile and enable `clipper2_batch`:

- Docker builds the extension and sets
  `LUMINA_VECTOR_NATIVE_MESH=1`;
- desktop packaging builds and bundles the same extension;
- both set `LUMINA_VECTOR_NATIVE_MESH_VALIDATE_SURFACE=1`;
- the module advertises `triangulation_area_guard`.

The new adjacent measurements show that “native” does not automatically mean
faster:

| Workload | Python reference | Current native | Observation |
|---|---:|---:|---|
| Same-analysis 4-color build | `7.080 s` | `7.382 s` | native `4.3%` slower |
| 4-color `extrude_bottom` | `5.877 s` | `6.267 s` | native `6.6%` slower |
| 12-color matched-RGB total, one cold run | `17.791 s` | `19.588 s` | native `10.1%` slower |
| 12-color matched-RGB build | `9.366 s` | `11.455 s` | native `22.3%` slower |

The 4-color native diagnostic processed 43 run groups:

- 40 groups produced native meshes;
- 3 groups used the existing native-merged Python fallback;
- native execution: `2.202 s`;
- Python surface validation: `2.547 s`;
- fallback work: `1.365 s`;
- packing: `0.120 s`;
- quality gate: PASS.

These are single-run design measurements, not final acceptance evidence.
They are sufficient to select the next experiment because the duplicate
surface validation alone is larger than the observed native regression.

The current Python validation is valuable: it independently reconstructs the
merged 2D reference geometry and compares its expected closed-extrusion
surface area with `mesh.area`. It must not simply be removed or replaced with
trust in the old `triangulation_area_guard`, which checks only the top/bottom
triangulation area.

## 4. Alternatives

### A. Versioned complete native surface guard — selected

Add a new native capability, for example
`closed_extrusion_surface_guard_v1`. Before returning a mesh, the C++ module
must validate the full closed extrusion:

- successful top/bottom triangulation;
- filled top/bottom triangle area matches the processed polygon area;
- side faces cover every non-degenerate processed boundary edge;
- expected side area is derived from processed boundary length and height;
- complete mesh triangle area matches
  `2 * filled_area + perimeter * height`;
- indices and generated coordinates are valid and finite;
- a failed guard returns an empty native mesh, preserving the existing Python
  fallback boundary.

Python may skip only the duplicate Shapely/Trimesh area calculation when all
of the following are true:

- surface validation is requested;
- the module advertises the new versioned capability;
- the returned arrays pass the existing dtype, shape, finite-value, and index
  checks.

Python must still build the same per-group `trimesh.Trimesh` objects and append
them in the same order. It must not switch to the existing coalesced-buffer
path in this optimization, because geometry-instance grouping is part of the
current semantic oracle.

**Why selected:** it targets the measured `2.547 s` duplicate check while
retaining an explicit, fail-closed quality boundary and preserving output
grouping.

### B. Optimize the three native-empty fallback groups — conditional second step

The 4-color sample spends `1.365 s` in three fallback groups. A later
experiment may split or natively extrude these groups, but only after approach
A is measured.

This step is allowed only if:

- approach A alone misses the accepted end-to-end target;
- profiler counters prove the fallback remains material;
- each changed group passes the current-native exact artifact oracle;
- invalid/empty native results still fall back to the reference Python path.

This is not combined with approach A by default because fallback heuristics
can change triangulation and grouping.

### C. Parallel native groups or Python validation — rejected initially

The native call releases the GIL and groups are independent, so threading is
technically possible. It is not selected because:

- PR #540 already proved that larger fan-out can increase wall time and RSS;
- production has two outer workers, so new inner workers risk
  oversubscription;
- the current regression is dominated by duplicated work, not lack of an
  executor;
- parallel validation retains the duplicated Shapely union instead of
  removing it.

A 1/2/4 experiment is allowed only after serial approaches A and B are
exhausted. No executor is retained unless complete wall time improves,
peak RSS stays bounded, p90 does not worsen, and exact quality remains green.

## 5. Architecture and data flow

### Current path

```text
Python geometries
  -> Python packs rings
  -> C++ union/close/triangulate/extrude
  -> C++ top/bottom triangulation-area guard
  -> NumPy vertices/faces
  -> Python rebuilds merged Shapely reference geometry
  -> Python builds Trimesh and calculates mesh.area
  -> Python compares complete surface area
  -> append mesh or fall back
```

### Proposed path

```text
Python geometries
  -> Python packs rings
  -> C++ union/close/triangulate/extrude
  -> C++ complete closed-extrusion surface guard
  -> NumPy vertices/faces
  -> Python validates array structure/indices/finiteness
  -> Python builds the same Trimesh object
  -> append in the same slot/group order

Any missing capability, failed guard, invalid array, or native exception
  -> unchanged Python validation/fallback path
```

### Capability contract

`native_mesh_capabilities()` remains a dictionary. The old
`triangulation_area_guard` key stays present for compatibility. The new key is
versioned and additive:

```python
{
    "triangulation_area_guard": True,
    "closed_extrusion_surface_guard_v1": True,
}
```

An older packaged extension therefore keeps the current Python validation.
Python never infers the new protection from module version, filename, or the
old capability.

### Observability

Reuse the existing vector completion/timing event and profiler output. Add
bounded scalar fields only:

- native capability used;
- run-group/native/fallback counts;
- native, packing, mesh-conversion, surface-validation, and fallback seconds;
- fallback reason counters already present in `last_native_vector_mesh_stats`.

Do not emit paths, polygon coordinates, color matrices, per-group events, or
another INFO line.

## 6. Output and quality invariants

The final oracle is the current production-native path from this branch before
the optimization, not the non-native Python fallback.

The candidate must preserve:

- matched RGB, pristine identity RGB, material matrix, masks, and recipes;
- material identifiers, slot ordering, and layer ordering;
- shape count, source/component order, and assignment count;
- per-material geometry and instance identity;
- oriented triangle records, including winding and bound face/vertex payloads;
- bounds, surface area, volume, watertightness, Euler number, and degenerate
  face count;
- scene nodes, material bindings, transforms, texture pixels, and colors;
- GLB bytes;
- every decompressed 3MF member after the existing allowed ZIP/container and
  generated-source-name normalization.

No tolerance is introduced to the final candidate-vs-current-native artifact
gate. Numeric tolerances are used only inside the native safety guard to
decide whether to fail closed to the unchanged Python path.

## 7. Error handling and rollback

- Missing new capability: run the current Python surface validator.
- Native guard failure: return an empty mesh and use the current group
  fallback.
- Invalid NumPy buffers or indices: use the current group fallback.
- Native exception: record the exception type and use the current fallback.
- Logging failure: must not change conversion success.
- Profiler mismatch: fail the performance run; do not report the timing win.

Add an emergency override
`LUMINA_VECTOR_NATIVE_MESH_FORCE_PYTHON_SURFACE_VALIDATION=1`. It forces the
legacy Python validator even when the new capability exists. Invalid values
are treated as disabled; this override does not turn native meshing on by
itself.

There is no database, cache-schema, API-request, or artifact-format migration.
Rollback is therefore the environment override or code/image rollback.

## 8. Test and measurement design

### TDD sequence

1. Add C++ self-tests where the old top/bottom-only capability is
   insufficient: missing side faces, duplicated side faces, degenerate
   boundary edges, holes, opposite winding, and invalid extrusion height.
2. Add a failing capability-contract test.
3. Implement the complete native guard and capability.
4. Add Python tests proving:
   - old/missing capability executes the current Python validator;
   - new capability skips only the duplicate area calculation;
   - the same per-group Trimesh partitioning and append order are preserved;
   - forced legacy validation restores the old path;
   - guard failure and invalid buffers retain current fallback behavior.
5. Extend existing profiler/timing output with bounded native counters.
6. Capture current-native external semantic references before measuring the
   candidate.

### Quality corpus

- 8-color Material Archive, matched-RGB override;
- 12-color Material Archive, matched-RGB override, 200 mm reference;
- 15-color Material Archive, combined override;
- 8-color no-override control;
- existing holes, winding, native-empty, native-invalid, split-retry, and
  merged-fallback unit/corpus fixtures;
- Docker/desktop native-extension build contracts.

### Performance method

- native arm64 Python 3.12;
- production-equivalent extension built from repository sources;
- `LUMINA_VECTOR_NATIVE_MESH=1`;
- `LUMINA_VECTOR_NATIVE_MESH_VALIDATE_SURFACE=1`;
- BLAS/OpenMP pools fixed to one;
- one cold plus at least three warm fresh-process samples for the 12-color
  reference;
- current-native base and candidate interleaved where practical;
- report median, p90, peak RSS, RSS increase, thread count, and child count;
- no cProfile in wall-time samples;
- profile native sub-stages separately after the wall-time run.

## 9. Acceptance and stop conditions

All quality conditions are hard requirements.

The optimization is accepted only if:

- all current-native external semantic/artifact references match exactly;
- 8-, 12-, and 15-color cases pass;
- `build_mesh` warm median improves by at least `25%`;
- 12-color end-to-end warm median improves by at least `15%`;
- p90 does not regress by more than `5%`;
- peak RSS does not increase by more than `15%`;
- small/no-override warm median does not regress by more than `5%`;
- no new child process is created;
- logging INFO budgets and existing fallback behavior remain valid;
- clean Docker/desktop build contracts still include the guarded native
  extension.

Stop and reject the candidate if any quality field differs, if the native
guard cannot be demonstrated to cover the current Python surface invariant,
or if the performance threshold requires output regrouping, tolerance
weakening, validation sampling, hidden multiprocessing, or unbounded memory.

If approach A passes quality but misses the performance threshold, record it
as an experiment rather than shipping it. Measure approach B separately. If
the combined safe serial work still misses the gate, close this target as
`no_safe_gain` and move the next optimization round to first-preview
parse/occlusion rather than forcing threads.
