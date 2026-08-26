# Unified Layered Meshing Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Lumina's independent-box raster meshes and repair-heavy Vector extrusion with one indexed, bounded-memory layered-meshing core that preserves printable coverage and produces closed Bambu/Orca-safe 3MF objects.

**Architecture:** Keep every public preview/generate/pipeline interface stable. First build an exact indexed surface from the existing labeled voxel volume, then prepare each spatially connected native SVG XY group once on one physical integer grid and feed the same indexed extrusion primitives. Canonical topology stays integer-valued until one final float32/uint32 materialization. Old coverage/topology repair ladders remain only until their replacement invariants pass, then are removed from the replaced main paths.

**Tech Stack:** Python 3, NumPy, SciPy ndimage, Shapely 2, Trimesh, neroued_3mf, pytest/Hypothesis, FastAPI, React/Vitest, Bambu Studio CLI, OrcaSlicer CLI.

---

## Task 1: Lock the new indexed-surface contract with failing tests

**Files:**
- Create: `tests/test_layered_surface_mesh_unit.py`
- Reference: `tests/test_mesh_generators_topology_unit.py`
- Reference: `core/mesh_generators.py`

- [ ] Add a helper that checks index range, coordinate-degenerate triangles,
      edge incidence, watertightness, volume, and connected shell count.
- [ ] Add a 1×1×1 voxel case with exact bounds and 12 triangles.
- [ ] Add a 1×1×2 same-material case and require one closed shell with no
      internal interface and no more than 12 triangles after planar merging.
- [ ] Add two face-adjacent, edge-adjacent, and point-adjacent cases. Face-
      adjacent voxels become one shell; point-only components retain independent
      vertex identities and shells.
- [ ] Add a cavity and a stepped-height case. Require closed inner walls and no
      T-junction/open edge at the height transition.
- [ ] Add two-material neighbors and require each material object's opposite
      interface surface to remain closed.

The first test should import the not-yet-created public helper:

```python
from core.layered_meshing import build_labeled_surface_mesh

mesh = build_labeled_surface_mesh(labels, material_id=0, height_px=1)
assert mesh.is_watertight
assert abs(mesh.volume - 2.0) < 1e-9
assert len(mesh.faces) == 12
```

Run RED:

```bash
KMP_DUPLICATE_LIB_OK=TRUE OMP_NUM_THREADS=1 \
  /opt/homebrew/bin/python3 -m pytest \
  tests/test_layered_surface_mesh_unit.py -q
```

Expected: FAIL because `core.layered_meshing` does not exist.

Commit after the next task turns these tests green; do not commit a permanently
red test-only state.

## Task 2: Implement exact exposed-surface meshing and planar merging

**Files:**
- Create: `core/layered_meshing.py`
- Test: `tests/test_layered_surface_mesh_unit.py`

- [ ] Add bilingual typed public dataclasses for mesh statistics and bounded
      geometry policy.
- [ ] Label six-connected components so point-only source components never get
      welded merely because coordinates match.
- [ ] For each component, derive the six exposed-face masks by comparing the
      requested material against its neighbors/outside.
- [ ] Greedily merge equal coplanar mask cells into rectangles.
- [ ] Build exact integer-grid quad boundaries, split long edges at every
      incident grid event, triangulate with shared indexed vertices, and orient
      all faces outward.
- [ ] Convert XY to the existing y-up world convention only at final array
      materialization; keep Z in existing layer-index units.
- [ ] Return `trimesh.Trimesh(process=False)` with metadata containing source
      voxel count, exposed unit-face count, merged patch count, vertex count,
      face count, and estimated/materialized bytes.
- [ ] Reject any constructed object whose actual indexed edges are not exactly
      two or whose volume differs from the occupied voxel count.

Core API:

```python
def build_labeled_surface_mesh(
    labels: np.ndarray,
    *,
    material_id: int,
    height_px: int,
    policy: LayeredMeshPolicy | None = None,
) -> trimesh.Trimesh | None:
    """Build one exact closed material surface from a Z/Y/X label volume.
    从 Z/Y/X 标签体构建一个精确闭合的材料表面。
    """
```

Run GREEN:

```bash
KMP_DUPLICATE_LIB_OK=TRUE OMP_NUM_THREADS=1 \
  /opt/homebrew/bin/python3 -m pytest \
  tests/test_layered_surface_mesh_unit.py -q
```

Expected: PASS.

Commit:

```bash
git add core/layered_meshing.py tests/test_layered_surface_mesh_unit.py
git commit -m "feat(mesh): add exact labeled surface meshing"
```

## Task 3: Replace raster box emission without changing mode behavior

**Files:**
- Modify: `core/mesh_generators.py`
- Modify: `tests/test_mesh_generators_topology_unit.py`
- Modify: `tests/test_mesh_generators_puzzle_unit.py`
- Create: `tests/test_layered_surface_mesh_properties.py`

- [ ] First replace implementation-detail expectations that require adjacent
      independent boxes with user contracts: exact occupied volume/bounds,
      correct material identity, closed shells, and no internal faces.
- [ ] Add Hypothesis cases for small label volumes and compare each material's
      output volume and horizontal section occupancy against the input matrix.
- [ ] Add regression cases for Pixel, High-Fidelity no-dilation, dilation with
      preserved holes, boundary clipping, relief/heightmap Z steps, backing,
      and two-material interfaces.
- [ ] Make `VoxelMesher.generate_mesh()` call
      `build_labeled_surface_mesh()` directly.
- [ ] Keep High-Fidelity's existing mask cleanup/dilation and boundary clipping
      semantics, but assemble its final per-material labels before calling the
      same builder.
- [ ] Delete `_VERTEX_TEMPLATE`, `_FACE_TEMPLATE`, and
      `_build_mesh_from_layer_rects()` once no production caller remains.
- [ ] Keep `_build_mesh_from_layer_polygons()` only where a genuinely
      non-grid boundary clip still needs it; record that path in metadata.

Run RED before changing production code:

```bash
KMP_DUPLICATE_LIB_OK=TRUE OMP_NUM_THREADS=1 \
  /opt/homebrew/bin/python3 -m pytest \
  tests/test_mesh_generators_topology_unit.py \
  tests/test_mesh_generators_puzzle_unit.py \
  tests/test_layered_surface_mesh_properties.py -q
```

Expected: new same-material shell/internal-face assertions FAIL on the old box
builder.

Run GREEN with the same command; expected PASS.

Commit:

```bash
git add core/mesh_generators.py \
  tests/test_mesh_generators_topology_unit.py \
  tests/test_mesh_generators_puzzle_unit.py \
  tests/test_layered_surface_mesh_properties.py
git commit -m "refactor(mesh): replace raster boxes with shared surfaces"
```

## Task 4: Canonicalize native Vector run groups in physical coordinates

**Files:**
- Create: `core/vector_layer_geometry.py`
- Create: `tests/test_vector_layer_geometry_unit.py`
- Modify: `tests/test_vector_engine_mesh_weld_unit.py`
- Reference: `core/vector_engine.py`

- [ ] Add failing cases for two polygons sharing a boundary, a 5×5 mm
      independent island beside a 200×200 mm body, holes, near-duplicate ring
      points, float32-near contacts, and the old equal-area/lost-component
      coverage regressions.
- [ ] Convert post-occlusion SVG geometries to millimeters before precision
      work and represent XY coordinates as integer units on a 0.0001 mm grid.
- [ ] Partition linework by spatial connectivity. Node and polygonize each XY
      group once, then label each cell from source ownership/recipe so a shared
      edge has one canonical coordinate; never repeat polygonization per layer.
- [ ] Simplify only canonical shared chains with a maximum 0.005 mm deviation.
      Restore the unsimplified local component whenever component count, hole
      count, ownership, or strict coverage changes.
- [ ] Return canonical Polygon/MultiPolygon geometry plus structural/coverage
      counters. Never return a partial run group.

Core API:

```python
def prepare_vector_run_group(
    geometries: Sequence[BaseGeometry],
    *,
    scale_mm_per_svg_unit: float,
    policy: VectorLayerGeometryPolicy | None = None,
) -> PreparedVectorRunGroup:
    """Prepare edge-matched printable coverage in physical millimeters.
    在物理毫米坐标中准备共享边完全一致的可打印覆盖。
    """
```

Run RED:

```bash
KMP_DUPLICATE_LIB_OK=TRUE OMP_NUM_THREADS=1 \
  /opt/homebrew/bin/python3 -m pytest \
  tests/test_vector_layer_geometry_unit.py \
  tests/test_vector_engine_mesh_weld_unit.py -q
```

Expected: the new module import/new canonical-boundary assertions FAIL.

Run GREEN after implementation; expected PASS.

Commit:

```bash
git add core/vector_layer_geometry.py \
  tests/test_vector_layer_geometry_unit.py \
  tests/test_vector_engine_mesh_weld_unit.py
git commit -m "feat(vector): canonicalize layered geometry in millimeters"
```

## Task 5: Adopt direct indexed Vector extrusion and retire repair fallback

**Files:**
- Modify: `core/vector_engine.py`
- Modify: `core/vector_mesh_topology.py`
- Modify: `core/vector_native_mesh.py`
- Modify: `tests/test_vector_engine_mesh_weld_unit.py`
- Modify: `tests/test_vector_mesh_topology_unit.py`
- Modify: `tests/test_vector_outline_manifold_unit.py`
- Modify: `tests/test_vector_native_mesh_unit.py`

- [ ] Add a failing spy test proving `_run_length_extrude()` does not call the
      old source-shell coverage fallback or multi-attempt coordinate-separation
      ladder for accepted canonical geometry.
- [ ] Feed `prepare_vector_run_group()` output to the indexed extrusion kernel
      with scale 1.0 because coordinates are already millimeters.
- [ ] Build caps and walls from the same canonical ring indices and preserve
      independent component index domains.
- [ ] Validate the actual float32 arrays after construction: no coordinate-
      degenerate triangles, every edge exactly twice, no new cross-component
      contact, and strict source coverage.
- [ ] Preserve typed topology reason codes for genuinely invalid input, but
      delete the accepted-input retry sequence (`fast/original/0.0001/0.001`),
      per-source 3D fallback retention, and obsolete automatic native/Python
      engine fallback from the main run path. Keep helpers still required by
      Outline until Outline has an independently verified replacement caller.
- [ ] Keep all existing run/material/Z ordering, single/double-sided, outline,
      coating, backing, and material-archive outputs unchanged.

Run RED/GREEN:

```bash
KMP_DUPLICATE_LIB_OK=TRUE OMP_NUM_THREADS=1 \
  /opt/homebrew/bin/python3 -m pytest \
  tests/test_vector_layer_geometry_unit.py \
  tests/test_vector_engine_mesh_weld_unit.py \
  tests/test_vector_mesh_topology_unit.py \
  tests/test_vector_outline_manifold_unit.py \
  tests/test_vector_native_mesh_unit.py -q
```

Commit:

```bash
git add core/vector_engine.py core/vector_mesh_topology.py \
  core/vector_native_mesh.py tests/test_vector_engine_mesh_weld_unit.py \
  tests/test_vector_mesh_topology_unit.py \
  tests/test_vector_outline_manifold_unit.py \
  tests/test_vector_native_mesh_unit.py
git commit -m "refactor(vector): build manifold runs by construction"
```

## Task 6: Materialize once and use neroued_3mf's zero-copy MeshView path

**Files:**
- Modify: `utils/bambu_3mf_writer.py`
- Modify: `tests/test_bambu_3mf_writer_unit.py`
- Modify: `tests/test_3mf_native_dependency_unit.py`

- [ ] Add failing tests proving the writer passes C-contiguous float32 vertices
      and uint32 faces directly to `DocumentBuilder.add_mesh_object()` and never
      calls owning `Mesh.from_arrays()` on the normal export path.
- [ ] Keep integer-grid topology and `shell_id` through construction; perform
      one final conversion to writer-domain arrays and validate those exact
      arrays before queuing the object.
- [ ] Retain the converted arrays for the lifetime of the built document so the
      non-owning `MeshView` references remain valid.
- [ ] Keep ordinary external Trimesh compatibility by materializing each
      object's final arrays once, not by retaining a second owning neroued mesh.
- [ ] Prove XML parsed coordinates reproduce the exact validated float32 values
      at the existing nine-significant-digit setting.
- [ ] Prove frozen packaging imports the required NumPy-overload-capable
      `neroued_3mf` build and still includes all printer profiles.
- [ ] Measure export RSS. Open a separate upstream spool/shortest-format PR only
      if the zero-copy path still misses the agreed memory/size target.

Representative RED/GREEN command:

```bash
KMP_DUPLICATE_LIB_OK=TRUE OMP_NUM_THREADS=1 \
  /opt/homebrew/bin/python3 -m pytest \
  tests/test_bambu_3mf_writer_unit.py \
  tests/test_3mf_native_dependency_unit.py \
  tests/test_desktop_build_unit.py -q
```

```bash
git add utils/bambu_3mf_writer.py tests/test_bambu_3mf_writer_unit.py \
  tests/test_3mf_native_dependency_unit.py
git commit -m "perf(3mf): use neroued zero-copy mesh views"
```

## Task 7: Replace coarse memory admission with actual output estimates

**Files:**
- Modify: `core/vector_mesh_memory.py`
- Modify: `core/errors.py`
- Modify: `api/routers/converter/preview.py`
- Modify: `api/routers/converter/generate.py`
- Modify: `api/routers/converter/color_card.py`
- Modify: `frontend/src/i18n/translations.ts`
- Modify: `tests/test_vector_mesh_memory_unit.py`
- Modify: `tests/test_converter_preview_unit.py`
- Modify: `tests/test_converter_generate_unit.py`
- Modify: corresponding frontend error tests

- [ ] Add failing tests proving an ordinary small Vector request on a 16 GiB
      host with low free memory is not forced to reserve 8 GiB, and a genuinely
      unsafe estimated output is still rejected before 3D allocation.
- [ ] Estimate raster work from exposed faces and Vector work from canonical
      ring/cap counts plus chunk working-set size.
- [ ] Keep host-wide reservation and worker hard limits as final circuit
      breakers, including concurrent gray-server tasks, but remove the normal
      fixed-full-budget/`vector_too_complex` path.
- [ ] Include surface model, parse cache, heightmap, material matrix, and writer
      working set in the total estimate.
- [ ] Return a stable actionable 422 only when the actual conservative estimate
      cannot fit; do not suggest waiting when `reserved_bytes == 0`.
- [ ] Remove translations/tests that describe ordinary valid art as merely
      “too complex”; retain a precise resource-exhaustion message.

Run RED/GREEN:

```bash
KMP_DUPLICATE_LIB_OK=TRUE OMP_NUM_THREADS=1 \
  /opt/homebrew/bin/python3 -m pytest \
  tests/test_vector_mesh_memory_unit.py \
  tests/test_converter_preview_unit.py \
  tests/test_converter_generate_unit.py \
  tests/test_model_surface_generate_unit.py -q
python scripts/run_vitest.py run
```

Commit:

```bash
git add core/vector_mesh_memory.py core/errors.py \
  api/routers/converter/preview.py api/routers/converter/generate.py \
  api/routers/converter/color_card.py frontend/src/i18n/translations.ts \
  tests/test_vector_mesh_memory_unit.py tests/test_converter_preview_unit.py \
  tests/test_converter_generate_unit.py tests/test_model_surface_generate_unit.py
git commit -m "fix(vector): admit work from canonical mesh cost"
```

## Task 8: Prove every supported workflow still uses the replacement

**Files:**
- Modify: `tests/test_vector_outline_pipeline_properties.py`
- Modify: `tests/test_model_surface_assembly_unit.py`
- Modify: `tests/test_model_surface_generate_unit.py`
- Create: `tests/test_unified_layered_meshing_integration.py`
- Modify: only directly affected preview/generate/share-card tests

- [ ] Add spies proving native SVG, rasterized SVG, bitmap High-Fidelity, and
      Pixel all reach the replacement builder and no removed fallback.
- [ ] Cover single/double-sided, 4/6/8/BW/5-color-extended, material archive,
      outline, coating, backing, relief/heightmap, cloisonne, fridge magnet,
      model surface, and large-format tile paths.
- [ ] Require preview/generate material slot, bounds, volume, layer-order, and
      effective coverage parity.
- [ ] Preserve share-card round trips for every affected parameter; no new UI
      setting is introduced.

Run:

```bash
KMP_DUPLICATE_LIB_OK=TRUE OMP_NUM_THREADS=1 \
  /opt/homebrew/bin/python3 -m pytest \
  tests/test_unified_layered_meshing_integration.py \
  tests/test_vector_outline_pipeline_properties.py \
  tests/test_model_surface_assembly_unit.py \
  tests/test_model_surface_generate_unit.py -q
```

Expected: PASS.

Commit:

```bash
git add tests/test_unified_layered_meshing_integration.py \
  tests/test_vector_outline_pipeline_properties.py \
  tests/test_model_surface_assembly_unit.py \
  tests/test_model_surface_generate_unit.py
git commit -m "test(mesh): cover unified converter workflows"
```

## Task 9: Reality, memory, and slicer acceptance

**Files:**
- Create or modify only reusable benchmark/inspection scripts needed to make
  the evidence reproducible; never commit user source assets or generated 3MFs.

- [ ] Run identical warm before/after benchmarks for R4C1 and representative
      bitmap fixtures. Record median wall time, peak RSS, vertices, faces, 3MF
      bytes, and spill bytes.
- [ ] Run the historical R4C1 SVG and all supplied bitmap fixtures at small and
      large sizes with 0.2 mm and 0.4 mm profiles.
- [ ] Generate Bambu and Orca projects; copy them for verification and disable
      only `enable_prime_tower` in those copies.
- [ ] Open and slice both formats. Machine-check every effective layer/material
      for extrusion moves, and capture first-five-layer screenshots whose line
      preview is visible.
- [ ] Require zero degenerate triangles, zero open edges, zero non-manifold
      edges, max edge incidence two, complete printable coverage, and unchanged
      material identity.
- [ ] Run focused, smoke, full, logging, packaging, and diff checks:

```bash
KMP_DUPLICATE_LIB_OK=TRUE OMP_NUM_THREADS=1 \
  /opt/homebrew/bin/python3 -m pytest tests/ -q
/opt/homebrew/bin/python3 scripts/run_smoke_tests.py
/opt/homebrew/bin/python3 scripts/run_full_tests.py
/opt/homebrew/bin/python3 scripts/log_quality_check.py --mode fast
/opt/homebrew/bin/python3 scripts/log_quality_check.py --mode full
/opt/homebrew/bin/python3 scripts/run_vitest.py run
git diff --check origin/dev-refactor...HEAD
```

- [ ] Check and stop leftover backend, Vite, slicer CLI, and benchmark workers.
- [ ] Obtain independent spec-compliance and code-quality reviews; address only
      reproducible blockers.
- [ ] Push the topic branch normally and open one Lumina PR to `dev-refactor`.
      Include exact heads, tests, benchmark table, topology/coverage evidence,
      zero-copy writer evidence, slicer evidence, limitations, and gray rollback
      revision. Link a separate upstream neroued PR only if measurement proves
      it is needed. Do not merge.

Final commit if evidence tooling changed:

```bash
git add <only-reusable-evidence-files>
git commit -m "test(mesh): add layered meshing acceptance evidence"
```
