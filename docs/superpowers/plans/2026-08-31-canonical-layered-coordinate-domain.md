# Canonical Layered Coordinate Domain Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Vector and raster model-surface generation consume one certified integer/layer coordinate contract so float32 representation cannot create false XY/Z overflow failures.

**Architecture:** Add an immutable `LayeredCoordinateDomain` that owns XY integer canvas units, canonical Z layer boundaries, and the exact outward float32 writer envelope. Canonical producers create and certify this domain once; model-surface assembly consumes it without reconstructing `bbox * scale` or summing heights independently, while legacy scenes retain strict bounds checks.

**Tech Stack:** Python 3, dataclasses, NumPy, Trimesh, Shapely, pytest.

---

## File Structure

- Create `core/layered_coordinate_domain.py`: domain construction, metadata serialization, writer envelope, and one-time scene certification.
- Modify `core/vector_engine.py`: construct the domain before extrusion, use its XY grid as the minimum policy for all display slabs, and attach it to the scene/analysis.
- Modify `core/model_surface/pipeline.py`: consume the Vector domain, construct the raster domain, normalize with authoritative writer bounds, and certify prepared patterns once.
- Modify `core/model_surface/assembly.py`: read certified bounds/layer schedules; keep strict legacy validation for uncertified scenes.
- Modify `tests/test_model_surface_assembly_unit.py`: current real-parameter float32 regressions, true-overflow rejection, and raster parity.
- Modify `tests/test_vector_layer_geometry_unit.py`: all display runs share the domain grid.
- Modify `tests/test_model_surface_generate_unit.py`: full worker flow does not require source-model watertightness.

### Task 1: Implement the immutable coordinate contract

**Files:**
- Create: `core/layered_coordinate_domain.py`
- Create: `tests/test_layered_coordinate_domain_unit.py`

- [ ] **Step 1: Write failing construction and round-trip tests**

```python
def test_domain_owns_integer_canvas_and_float32_writer_envelope():
    domain = LayeredCoordinateDomain.from_canvas_and_layers(
        width_mm=115.59999084472656,
        height_mm=947.0 * (115.59999084472656 / 814.0),
        xy_grid_mm=0.0001,
        layer_heights_mm=(0.08,) * 5,
    )
    assert domain.canvas_max_units == (1_156_000, 1_344_880)
    assert domain.writer_canvas_bounds_mm[3] == float(np.float32(134.488))
    assert domain.writer_z_bounds_mm[1] == float(np.float32(0.4))
    assert LayeredCoordinateDomain.from_metadata(domain.to_metadata()) == domain
```

- [ ] **Step 2: Run tests and verify RED**

Run:
`PYTHONPATH=/tmp/lumina-e388-creative-deps /opt/homebrew/bin/python3 -m pytest tests/test_layered_coordinate_domain_unit.py -q`

Expected: collection fails because `core.layered_coordinate_domain` does not exist.

- [ ] **Step 3: Implement domain construction and metadata parsing**

Implement `LayeredCoordinateDomain` with:

```python
@dataclass(frozen=True)
class LayeredCoordinateDomain:
    version: int
    xy_grid_mm: float
    canvas_min_units: tuple[int, int]
    canvas_max_units: tuple[int, int]
    layer_boundaries_mm: tuple[float, ...]
    writer_canvas_bounds_mm: tuple[float, float, float, float]
    writer_z_bounds_mm: tuple[float, float]

    @classmethod
    def from_canvas_and_layers(...): ...
    def to_metadata(self) -> dict[str, object]: ...
    @classmethod
    def from_metadata(cls, value: object) -> "LayeredCoordinateDomain": ...
```

Use half-up integer snapping for canvas units. Build cumulative Z boundaries once with `math.fsum`. For each minimum bound use `min(value, float(np.float32(value)))`; for each maximum use `max(...)`. Reject non-finite, non-positive, malformed, or unsupported-version inputs.

- [ ] **Step 4: Run domain tests and verify GREEN**

Run the Task 1 command. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/layered_coordinate_domain.py tests/test_layered_coordinate_domain_unit.py
git commit -m "feat(mesh): add canonical coordinate domain"
```

### Task 2: Make native Vector meshing publish and use one domain

**Files:**
- Modify: `core/vector_engine.py`
- Modify: `core/vector_layer_geometry.py`
- Modify: `tests/test_vector_layer_geometry_unit.py`
- Modify: `tests/test_vector_engine_mesh_weld_unit.py`

- [ ] **Step 1: Write a failing shared-grid test**

Create a Vector analysis whose canvas requires a `0.0001 mm` domain grid and whose material runs occupy smaller disjoint bounds. Assert every resulting mesh's `vector_stepped_geometry["grid_mm"]` equals the scene domain grid and that scene metadata round-trips to the same domain.

- [ ] **Step 2: Run focused Vector tests and verify RED**

Run:
`PYTHONPATH=/tmp/lumina-e388-creative-deps KMP_DUPLICATE_LIB_OK=TRUE OMP_NUM_THREADS=1 /opt/homebrew/bin/python3 -m pytest tests/test_vector_layer_geometry_unit.py tests/test_vector_engine_mesh_weld_unit.py -q`

Expected: the new metadata/grid assertion fails because no domain is published.

- [ ] **Step 3: Thread one policy through Vector display extrusion**

At the start of `VectorProcessor.build_mesh`, construct the domain from
`bbox[2] * scale_factor`, `bbox[3] * scale_factor`, `(layer_h,) * num_layers`,
and `resolve_vector_writer_grid_mm(max(width_mm, height_mm))`.

Pass `VectorLayerGeometryPolicy(grid_mm=domain.xy_grid_mm)` through:

```python
_run_length_extrude(..., geometry_policy=policy)
_materialize_vector_slabs(..., geometry_policy=policy)
_build_source_spatial_groups(..., geometry_policy=policy)
build_vector_stepped_volume(..., policy=policy)
prepare_vector_spatial_groups_best_effort(..., policy=policy)
```

All new parameters are optional with the current default to preserve callers.
Attach `domain.to_metadata()` to the final scene and assign the same immutable
domain to `analysis.coordinate_domain`.

- [ ] **Step 4: Run focused Vector tests and verify GREEN**

Run the Task 2 command. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/vector_engine.py core/vector_layer_geometry.py tests/test_vector_layer_geometry_unit.py tests/test_vector_engine_mesh_weld_unit.py
git commit -m "refactor(vector): publish canonical mesh domain"
```

### Task 3: Adopt the domain in both model-surface pattern producers

**Files:**
- Modify: `core/model_surface/pipeline.py`
- Modify: `tests/test_model_surface_assembly_unit.py`
- Modify: `tests/test_model_surface_slot_meshing_unit.py`

- [ ] **Step 1: Keep and run the two current failing real-parameter tests**

The tests use canvas `814 x 947`, target width `115.59999084472656 mm`, and a
five-layer `0.08 mm` schedule. They require the produced metadata and normalized
mesh to use the same float32 writer envelope.

Run:
`PYTHONPATH=/tmp/lumina-e388-creative-deps KMP_DUPLICATE_LIB_OK=TRUE OMP_NUM_THREADS=1 /opt/homebrew/bin/python3 -m pytest tests/test_model_surface_assembly_unit.py -k 'float32_writer_rounding' -q`

Expected: 2 FAIL before implementation.

- [ ] **Step 2: Consume the Vector domain instead of recomputing canvas/depth**

In `_build_vector_pattern_scene`, read the domain from `analysis.coordinate_domain`
or scene metadata. Use `writer_canvas_bounds_mm` for face-up/down normalization
and logical XY metadata. Use `writer_z_bounds_mm` and `layer_boundaries_mm`
for display depth and nominal per-layer differences.

After normalization, call one `certify_pattern_scene(scene, domain)` helper that
checks finite bounds and exact containment in the domain writer envelope, then
sets the certification marker. This is the only canonical-pattern bounds check.

- [ ] **Step 3: Construct the same domain for raster/high-fidelity patterns**

In `_build_pattern_scene`, build a domain from:

```python
width_mm = pattern_matrix.shape[2] * pixel_scale
height_mm = target_h * pixel_scale
xy_grid_mm = pixel_scale
layer_heights_mm = layer_heights_mm
```

Attach and certify it after `build_slot_surface_scene_from_voxels`. Keep the
existing nominal layer schedule unchanged.

- [ ] **Step 4: Verify producer tests are GREEN**

Run:
`PYTHONPATH=/tmp/lumina-e388-creative-deps KMP_DUPLICATE_LIB_OK=TRUE OMP_NUM_THREADS=1 /opt/homebrew/bin/python3 -m pytest tests/test_model_surface_assembly_unit.py tests/test_model_surface_slot_meshing_unit.py -q`

Expected: PASS, including the current two regressions.

- [ ] **Step 5: Commit**

```bash
git add core/model_surface/pipeline.py tests/test_model_surface_assembly_unit.py tests/test_model_surface_slot_meshing_unit.py
git commit -m "fix(model-surface): use canonical pattern domain"
```

### Task 4: Make assembly trust certified patterns and retain strict legacy guards

**Files:**
- Modify: `core/model_surface/assembly.py`
- Modify: `tests/test_model_surface_assembly_unit.py`

- [ ] **Step 1: Write failing certified-versus-legacy behavior tests**

Add tests proving:

```python
assert _pattern_xy_bounds_mm(certified_scene) == domain.writer_canvas_bounds_mm
assert _pattern_z_bounds_mm(certified_scene) == domain.writer_z_bounds_mm
assert _pattern_layer_heights_mm(certified_scene) == (0.08,) * 5
```

Also retain an uncertified scene with one full XY grid unit of real overflow and
assert `ModelSurfaceError`. Add a malformed certification test and assert it is
rejected rather than trusted.

- [ ] **Step 2: Run and verify RED**

Run the Task 3 focused assembly command. Expected: certified accessors still
re-audit/reconstruct bounds and at least one new assertion fails.

- [ ] **Step 3: Implement certified accessors**

At the start of `_pattern_xy_bounds_mm`, `_pattern_z_bounds_mm`, and
`_pattern_layer_heights_mm`, parse a certified domain and return its authoritative
values. If certification is absent, execute the existing strict legacy code
unchanged. If certification exists but is malformed, raise `ModelSurfaceError`.

Use the certified writer canvas for printable-footprint scaling. Do not add or
widen any numeric epsilon.

- [ ] **Step 4: Run and verify GREEN**

Run the Task 3 focused assembly command. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/model_surface/assembly.py tests/test_model_surface_assembly_unit.py
git commit -m "refactor(model-surface): consume certified bounds"
```

### Task 5: Verify the real workflow without gating on source-model defects

**Files:**
- Modify: `tests/test_model_surface_generate_unit.py`
- Modify: `tests/test_model_surface_assembly_unit.py`

- [ ] **Step 1: Add a non-watertight source-model regression**

Construct a base mesh with a removable/pre-existing open face but a valid
selected planar footprint. Assert model-surface preparation does not introduce
a new watertightness rejection. Keep generated color-pattern topology and
coverage assertions separate from source-base quality.

- [ ] **Step 2: Run focused model-surface tests**

Run:
`PYTHONPATH=/tmp/lumina-e388-creative-deps KMP_DUPLICATE_LIB_OK=TRUE OMP_NUM_THREADS=1 /opt/homebrew/bin/python3 -m pytest tests/test_model_surface_assembly_unit.py tests/test_model_surface_generate_unit.py tests/test_model_surface_slot_meshing_unit.py -q`

Expected: PASS after the domain implementation; source-model watertightness is
not a new gate.

- [ ] **Step 3: Run the supplied real assets three times**

Use, without committing:

- `/Volumes/personal_folder/BUG/vectorized.svg`
- `/Volumes/personal_folder/BUG/streamdeck.stl`

Select `surface-61` (544 faces, `5238.0165896205 mm2`, 15 holes), target width
`115.59999084472656 mm`, and generate three times. Record elapsed time, peak RSS,
material objects, bounds, and output size.

- [ ] **Step 4: Verify slicer reality**

Disable the prime tower in verification copies only. Open/slice with Bambu
Studio and OrcaSlicer. Confirm overlay layers contain toolpaths and do not mark
the source STL's pre-existing defects as a regression in the color overlay.

- [ ] **Step 5: Run regression gates**

```bash
PYTHONPATH=/tmp/lumina-e388-creative-deps KMP_DUPLICATE_LIB_OK=TRUE OMP_NUM_THREADS=1 /opt/homebrew/bin/python3 -m pytest tests/test_layered_coordinate_domain_unit.py tests/test_vector_layer_geometry_unit.py tests/test_vector_engine_mesh_weld_unit.py tests/test_model_surface_assembly_unit.py tests/test_model_surface_slot_meshing_unit.py tests/test_model_surface_generate_unit.py tests/test_unified_layered_meshing_integration.py tests/test_bambu_3mf_writer_unit.py -q
python scripts/run_smoke_tests.py
python scripts/log_quality_check.py --mode fast
git diff --check
```

- [ ] **Step 6: Commit final regressions and update the PR**

```bash
git add tests/test_model_surface_generate_unit.py tests/test_model_surface_assembly_unit.py
git commit -m "test(model-surface): cover imperfect source models"
git push origin MOVIBALE/fix/unified-layered-meshing
```

Report the exact head, tests, three-run timing/RSS/output size, Bambu/Orca
results, and the explicit limitation that source-model repair is out of scope.
Do not merge automatically.
