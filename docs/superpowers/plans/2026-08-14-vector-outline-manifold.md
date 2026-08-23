# Vector Outline Manifold Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure SVG Outline meshes generated from LUM-20260814-001 remain watertight in Bambu Studio and OrcaSlicer without changing ordinary outline geometry or silently dropping failed outline pieces.

**Architecture:** Keep the existing buffer/difference geometry source and fast generic extrusion for ordinary polygon pieces. Detect only Outline polygons whose rings can create ambiguous indexed edges (holes or repeated sub-resolution exterior vertices); validate those pieces, retry with a sub-resolution Shapely precision grid, and use the canonical indexed vector extrusion helper. If a piece cannot be repaired without measurable area loss, reject the entire Outline instead of exporting a partial ring.

**Tech Stack:** Python, Shapely, Trimesh, pytest, real SVG regression fixture.

---

### Task 1: Add focused failing Outline topology regressions

**Files:**
- Create: `tests/test_vector_outline_manifold_unit.py`
- Test fixture: `/Volumes/personal_folder/person_8ba86fa3823aff049badd414e7c525f2_20260814_130551_vector.svg` (used by an opt-in integration test when present)

- [ ] **Step 1: Write the failing synthetic point-touching-hole test**

  Build a `MagicMock` analysis with a rectangle containing two triangular holes sharing one point, call `_generate_vector_outline_mesh`, and assert the returned mesh has only two indexed faces per edge.

- [ ] **Step 2: Write the failing duplicate-exterior-vertex test**

  Build a polygon whose exterior repeats a coordinate at sub-resolution distance, generate an Outline, and assert the result is watertight with no indexed non-manifold edges.

- [ ] **Step 3: Write the no-partial-export test**

  Monkeypatch the canonical repair extrusion to fail for a suspicious polygon and assert `_generate_vector_outline_mesh` returns `None` rather than concatenating the remaining pieces.

- [ ] **Step 4: Run the focused tests and confirm they fail for the current implementation**

  Run:

  ```bash
  python3 -m pytest tests/test_vector_outline_manifold_unit.py -q
  ```

  Expected: the point-touching-hole case reports non-manifold indexed edges and the failure-path test observes a partial mesh/skip behavior.

### Task 2: Add the minimal Outline-only topology guard and repair

**Files:**
- Modify: `core/pipeline/vector_branch.py:20-60, 675-735, 1110-1175`
- Modify: `core/vector_engine.py:90-100, 1430-1625, 9800-9910`
- Modify: `utils/bambu_3mf_writer.py:1968-1985`

- [ ] **Step 1: Add bounded repair constants and imports**

  Import `set_precision` from Shapely and define two sub-resolution retry gaps (`0.0001` and `0.001` mm) plus the same `1e-6` relative / `0.01 mm²` absolute area-loss guard used by the native vector coverage contract.

- [ ] **Step 2: Add helpers for suspicious-ring detection and area-safe repair**

  Detect holes and repeated/quantized exterior vertices. For suspicious polygons, snap only during the retry path, preserve all polygon parts, and accept a repair only when it is valid, watertight after canonical indexed extrusion, and its physical area loss stays within the bounded tolerance.

- [ ] **Step 3: Reuse canonical indexed extrusion for repaired Outline pieces**

  Keep the existing `trimesh.creation.extrude_polygon` fast path for ordinary pieces. When a suspicious piece is not watertight, call the canonical `_extrude_polygonal_unit_height` helper from `core.vector_engine`, then apply the same XY scale, Z layer scale, Z offset, metadata, and export transforms as before.

- [ ] **Step 4: Fail closed for an unrepaired Outline piece**

  Replace the current `continue` on per-piece extrusion failure with a whole-Outline rejection (`None` plus a structured warning). This prevents a missing connected region from being silently exported as if the Outline were complete.

### Task 3: Verify synthetic and real regression behavior

**Files:**
- Modify: `tests/test_vector_outline_manifold_unit.py` for synthetic topology and real-writer regressions.

- [ ] **Step 1: Run the focused synthetic suite**

  ```bash
  python3 -m pytest tests/test_vector_outline_manifold_unit.py -q
  ```

  Expected: all synthetic cases pass; ordinary rectangle/circle Outline output remains unchanged within existing tolerances.

- [ ] **Step 2: Run the existing Outline and native topology suites**

  ```bash
  python3 -m pytest tests/test_vector_outline_pipeline_properties.py tests/test_vector_engine_mesh_weld_unit.py -q
  ```

- [ ] **Step 3: Reproduce the original SVG and inspect topology**

  Parse `/Volumes/personal_folder/person_8ba86fa3823aff049badd414e7c525f2_20260814_130551_vector.svg`, generate the 1 mm Outline at 111 mm width, and record bounds, watertight status, open-edge count, non-manifold-edge count, area delta, and generation time.

- [ ] **Step 4: Export and inspect a 3MF in Bambu Studio/OrcaSlicer**

  Confirm the original SVG has no Outline non-manifold warning and that the previously missing connected region has toolpaths. Treat severe wipe-tower/model-overlap warnings as out of scope unless they identify a missing model path.

- [ ] **Step 5: Verify the writer precision boundary**

  Confirm that six significant digits can merge bed-scale float32 vertices, while the production value of nine significant digits preserves the original Outline topology and does not add more precision than the float32 storage contract needs.

### Task 4: Release hygiene

**Files:**
- Modify: none beyond implementation/tests/plan.

- [ ] **Step 1: Run `git diff --check` and relevant logging/geometry gates**

- [ ] **Step 2: Review the diff for scope and UTF-8 integrity**

- [ ] **Step 3: Commit only after fresh verification evidence is collected**
