# Vector Topology Export Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve the verified LUM-20260814-001 geometry fix while replacing duplicated Outline/base-vector repair branches with one bounded, reusable vector-topology export service.

**Architecture:** Add one focused `core/vector_mesh_topology.py` module that owns indexed polygon extrusion, float32 writer-domain validation, bounded ring-contact repair, geometry precision preparation, and independent-shell separation. Both `VectorProcessor._extrude_geometry` and the Outline pipeline call that service; `vector_branch.py` remains responsible only for Outline geometry, placement, metadata, and structured rejection logging, while the 3MF writer retains the minimal nine-significant-digit serialization setting.

**Tech Stack:** Python 3.11+, NumPy, Shapely, Trimesh, mapbox-earcut, neroued_3mf, pytest, Bambu Studio CLI, OrcaSlicer CLI.

---

### Task 1: Lock the shared topology contract with failing tests

**Files:**
- Create: `tests/test_vector_mesh_topology_unit.py`
- Modify: `tests/test_vector_outline_manifold_unit.py`
- Modify: `tests/test_vector_engine_mesh_weld_unit.py`

- [x] **Step 1: Add a missing-module RED test for the desired shared API**

  Import `extrude_polygon_for_export`, `prepare_geometry_for_float32`, `mesh_is_float32_safe`, and `separate_component_coordinates` from `core.vector_mesh_topology`. Exercise a plain rectangle, a valid near-duplicate exterior ring, and two point-touching holes:

  ```python
  from core.vector_mesh_topology import extrude_polygon_for_export

  def test_export_extrusion_repairs_near_duplicate_boundary() -> None:
      meshes = extrude_polygon_for_export(
          _near_duplicate_boundary_polygon(),
          xy_scale=0.043424072501499274,
          prefer_fast=True,
      )
      assert meshes
      assert all(mesh.is_watertight for mesh in meshes)
      assert all(mesh_is_float32_safe(mesh, xy_scale=0.043424072501499274) for mesh in meshes)
  ```

- [x] **Step 2: Run the new file and verify RED**

  Run:

  ```bash
  KMP_DUPLICATE_LIB_OK=TRUE OMP_NUM_THREADS=1 /opt/homebrew/bin/python3 -m pytest tests/test_vector_mesh_topology_unit.py -q
  ```

  Expected: collection fails with `ModuleNotFoundError: core.vector_mesh_topology`.

- [x] **Step 3: Add routing tests for both existing callers**

  Monkeypatch the future imported `extrude_polygon_for_export` symbol in `core.pipeline.vector_branch` and `core.vector_engine`. Assert that Outline generation and a non-convex `VectorProcessor._extrude_geometry` input each invoke the shared service and preserve the existing result/coverage contracts.

- [x] **Step 4: Run only the routing tests and verify RED**

  Expected: both fail because the two callers do not yet expose or use the shared service.

### Task 2: Implement the focused topology service

**Files:**
- Create: `core/vector_mesh_topology.py`
- Test: `tests/test_vector_mesh_topology_unit.py`

- [x] **Step 1: Define the bounded export policy and public functions**

  Implement only these public entry points:

  ```python
  VECTOR_COVERAGE_REL_TOL = 1e-6
  VECTOR_COVERAGE_ABS_TOL_MM2 = 0.01
  VECTOR_RING_SEPARATION_RETRY_MM = (0.0001, 0.001)

  def mesh_is_float32_safe(mesh: trimesh.Trimesh, *, xy_scale: float = 1.0) -> bool: ...
  def prepare_geometry_for_float32(geometry, *, xy_scale: float): ...
  def separate_component_coordinates(meshes: list[trimesh.Trimesh], *, separation_mm: float = 1e-4) -> bool: ...
  def extrude_polygon_for_export(poly: Polygon, *, xy_scale: float, prefer_fast: bool) -> list[trimesh.Trimesh]: ...
  ```

  Internal helpers may cover indexed unit-height extrusion, ring-contact separation, and area comparison. Do not add configuration objects, plugin hooks, global caches, or unbounded retries.

- [x] **Step 2: Implement one canonical extrusion ladder**

  The service must follow one finite sequence:

  ```text
  optional ordinary-polygon fast path
      -> canonical indexed extrusion of original polygon
      -> canonical indexed extrusion after 0.0001 mm repair
      -> canonical indexed extrusion after 0.001 mm repair
      -> ValueError
  ```

  Every accepted mesh must be watertight and safe after the actual float32 XY scale. Every repaired polygon must stay within `max(0.01 mm², original_area * 1e-6)`.

- [x] **Step 3: Implement one whole-geometry precision preparation path**

  `prepare_geometry_for_float32` returns the original object when no ring coordinate collapses, returns a valid area-safe `0.0001 mm` precision result when needed, and returns `None` when the repair cannot satisfy the coverage bound.

- [x] **Step 4: Run the shared-service tests and verify GREEN**

  Run the Task 1 command. Expected: all new shared-contract tests pass with no warnings.

### Task 3: Adopt the shared service and remove duplicated patch branches

**Files:**
- Modify: `core/pipeline/vector_branch.py:35-40, 853-1183, 1430-1569`
- Modify: `core/vector_engine.py:30-100, 1434-1770, 9990-10060`
- Modify: `tests/test_vector_outline_manifold_unit.py`
- Modify: `tests/test_vector_engine_mesh_weld_unit.py`

- [x] **Step 1: Route Outline through the shared service**

  Import the four public functions at module scope. Replace `_outline_geometry_needs_float32_snap` plus `_snap_outline_geometry_for_float32` with one `prepare_geometry_for_float32` call. Replace `_extrude_vector_outline_polygon` with `extrude_polygon_for_export(..., prefer_fast=True)`, then apply the existing XY/Z scale, placement, metadata, and logging.

- [x] **Step 2: Route base vector extrusion through the shared service**

  Keep `_direct_convex_extrusion_base` and the existing coverage/cache handling. For the non-direct case call:

  ```python
  topology_meshes = extrude_polygon_for_export(
      poly,
      xy_scale=float(scale),
      prefer_fast=False,
  )
  m_base = topology_meshes[0] if len(topology_meshes) == 1 else trimesh.util.concatenate(topology_meshes)
  ```

  Preserve the existing fail-closed `ValueError`, physical planar-coverage check, cache payload, and structured warning.

- [x] **Step 3: Remove superseded local/private helpers**

  Delete the six Outline topology helpers from `vector_branch.py` and the repair/indexed-extrusion block moved out of `vector_engine.py`. Update tests to patch `core.vector_mesh_topology` or each caller's imported public function instead of private `core.vector_engine` helpers.

- [x] **Step 4: Verify both routing tests now pass**

  Run the two exact routing tests from Task 1. Expected: GREEN and exactly one canonical topology entry point per caller.

- [x] **Step 5: Verify the production diff actually contracts**

  Run:

  ```bash
  git diff --numstat origin/dev-refactor...HEAD -- core/pipeline/vector_branch.py core/vector_engine.py core/vector_mesh_topology.py utils/bambu_3mf_writer.py
  rg -n "def _outline_mesh_is_|def _outline_geometry_needs_|def _snap_outline_|def _extrude_vector_outline_polygon" core/pipeline/vector_branch.py
  ```

  Expected: the `rg` command finds nothing; `vector_branch.py` loses the 333-line topology helper island. Judge success by ownership and duplicate removal, not an arbitrary total-line target.

### Task 4: Run automated geometry, profile, and packaging gates

**Files:**
- Modify only if a regression demonstrates a defect in the consolidation.

- [x] **Step 1: Run focused topology and writer tests**

  ```bash
  KMP_DUPLICATE_LIB_OK=TRUE OMP_NUM_THREADS=1 /opt/homebrew/bin/python3 -m pytest \
    tests/test_vector_mesh_topology_unit.py \
    tests/test_vector_outline_manifold_unit.py \
    tests/test_vector_engine_mesh_weld_unit.py \
    tests/test_vector_branch_no_outline_preservation_properties.py \
    tests/test_bambu_3mf_writer_unit.py -q
  ```

- [x] **Step 2: Run the broader related suites and compare only against known baseline failures**

  Run the vector Outline pipeline/property, printer-profile, wipe-tower placement, logging-governance, compile, UTF-8, and `git diff --check` gates already recorded in PR #570.

- [x] **Step 3: Measure the ordinary SVG fast path three times**

  Use `test_images/1.svg` with the same width/settings as the prior 0.343784 s warm baseline. Record run 2/3 mean and reject a material regression that cannot be explained by measurement noise.

- [x] **Step 4: Run the supplied bitmap corpus without treating it as vector evidence**

  Confirm all 18 JPEGs decode. Run all 18 through a bounded raster preview smoke at one standard width, then choose representatives for small/medium/large full generation based on complexity: flat limited palette, pale low-contrast, dense high-frequency detail, dark gradients, and wide landscape. Record success/failure, elapsed time, output existence, and any structured warning; do not copy user images into the repository.

### Task 5: Re-run the real customer geometry and slicers

**Files:**
- Runtime input: `/Volumes/personal_folder/person_8ba86fa3823aff049badd414e7c525f2_20260814_130551_vector.svg`
- Generated artifacts: temporary/output locations only; do not commit.

- [x] **Step 1: Generate the exact 111 mm Bambu and Orca projects**

  Preserve the original SHA-256, vector parameters, 0.08 mm layer height, P2S compatibility, and prime-tower-only verification-copy rule from PR #570.

- [x] **Step 2: Inspect the actual 3MF XML topology**

  Require index-degenerate triangles `0`, coordinate-degenerate triangles `0`, open edges `0`, non-manifold edges `0`, and maximum edge incidence `2` for the Outline object in both projects.

- [x] **Step 3: Slice with both desktop slicer CLIs**

  Require Bambu `error_string = "Success."`, Orca exit code `0`, and non-empty outer-wall/toolpath segments on every effective model layer. Wipe-tower overlap remains out of scope; geometry warnings and missing model paths are blockers.

### Task 6: Review and update the existing PR without merging

**Files:**
- Update: PR #570 description/evidence after commit.

- [ ] **Step 1: Fetch and normally merge the latest `origin/dev-refactor`**

  Verify a clean worktree first. Do not rebase or force-push. Resolve only actual overlapping changes and rerun focused tests after the merge.

- [ ] **Step 2: Run final hygiene and clean review**

  Check `git status --short`, `git diff --check`, generated/untracked artifacts, UTF-8, logging events, and exact diff ownership. A clean reviewer must verify behavior preservation and absence of duplicated topology policy when capacity is available.

- [ ] **Step 3: Commit and push normally**

  Use a Conventional Commit message, push `MOVIBALE/fix/vector-outline-manifold` without force, update draft PR #570, and report the exact new head. Do not merge unless the user explicitly asks after reviewing the consolidated result.
