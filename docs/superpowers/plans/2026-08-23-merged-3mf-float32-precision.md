# Merged 3MF Float32 Precision Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent merged 3MF export from collapsing distinct float32 vertices while preserving current geometry, metadata, compression, and runtime behavior.

**Architecture:** Keep `neroued_3mf`'s deliberate `Vec3f` mesh boundary and make the merged writer explicitly serialize those values with the same nine-significant-digit round-trip contract as the normal writer. Prove the contract by inspecting the actual XML inside source and merged 3MF archives, then measure final ZIP size and write time on identical inputs.

**Tech Stack:** Python 3.14, NumPy, trimesh, neroued-3mf 0.3.0, pytest, 3MF/XML/ZIP

---

### Task 1: Lock the regression at the archive boundary

**Files:**
- Modify: `tests/test_merged_3mf_writer_integration.py`

- [ ] **Step 1: Allow the existing source fixture to accept an exact mesh**

Add an optional `mesh_override: trimesh.Trimesh | None` argument to `_make_source_3mf`.
When supplied, copy that mesh instead of constructing the default box. Keep all material
metadata and normal source-3MF generation unchanged.

- [ ] **Step 2: Add the adjacent-float32 archive regression**

Construct a watertight tetrahedron whose X coordinates include:

```python
x0 = np.float32(200.0)
x1 = np.nextafter(x0, np.float32(np.inf), dtype=np.float32)
```

Write it through the normal source writer and the merged writer. Parse
`3D/Objects/object_1.model` from both archives and assert that all four coordinates remain
unique and that no emitted triangle has repeated coordinates.

- [ ] **Step 3: Run the new test and confirm the existing failure**

Run:

```bash
/opt/homebrew/bin/python3 -m pytest \
  tests/test_merged_3mf_writer_integration.py::TestMergedWriterBambuCompatibility::test_per_item_model_preserves_adjacent_float32_vertices \
  -q
```

Expected before the implementation: FAIL because the merged XML contains only three unique
coordinates after `vertex_precision = 6` serializes both X values as `200`.

### Task 2: Align merged serialization with the float32 round-trip contract

**Files:**
- Modify: `utils/merged_bambu_3mf_writer.py:798`
- Test: `tests/test_merged_3mf_writer_integration.py`

- [ ] **Step 1: Make the minimal production change**

Replace the lossy override with the explicit safe value and a concise contract comment:

```python
# Match the normal 3MF writer and preserve every float32 vertex value.
opts.vertex_precision = 9
```

Do not change mesh construction, topology, compression, or vendor metadata.

- [ ] **Step 2: Run the new regression**

Run the test command from Task 1. Expected: PASS.

- [ ] **Step 3: Run the merged-writer integration suite**

Run:

```bash
/opt/homebrew/bin/python3 -m pytest tests/test_merged_3mf_writer_integration.py -q
```

Expected: all tests pass.

### Task 3: Measure size, runtime, and topology on identical inputs

**Files:**
- No production files
- Temporary benchmark artifacts: system temporary directory only

- [ ] **Step 1: Benchmark six versus nine significant digits**

Use the same `neroued_3mf.Document` for both options and write each precision at least three
times. Record median elapsed time and final compressed 3MF bytes for a simple mesh and a dense
representative mesh. Report absolute bytes and percentages; do not commit generated files.

- [ ] **Step 2: Inspect emitted XML topology**

Parse every vertex and triangle from the final representative merged archive. Report indexed
degenerates, coordinate degenerates, open edges, non-manifold edges, and maximum edge incidence.

- [ ] **Step 3: Run slicer compatibility checks**

When local Bambu Studio and OrcaSlicer command-line entry points are available, load or slice
the representative 3MF and retain only logs in temporary paths. Treat slicer-version metadata
incompatibility separately from geometry failures.

### Task 4: Run focused gates and publish the isolated change

**Files:**
- Modify: `utils/merged_bambu_3mf_writer.py`
- Modify: `tests/test_merged_3mf_writer_integration.py`
- Add: `docs/superpowers/specs/2026-08-23-merged-3mf-float32-precision-design.md`
- Add: `docs/superpowers/plans/2026-08-23-merged-3mf-float32-precision.md`

- [ ] **Step 1: Run directly related regression suites**

Run:

```bash
/opt/homebrew/bin/python3 -m pytest \
  tests/test_merged_3mf_writer_integration.py \
  tests/test_bambu_3mf_writer_unit.py \
  tests/test_puzzle_3mf_unit.py \
  tests/test_converter_batch_unit.py \
  -q
```

Expected: all environment-supported tests pass; any skip is identified by its existing optional
dependency or platform condition.

- [ ] **Step 2: Check repository hygiene**

Run:

```bash
git diff --check
git status --short
```

Expected: no whitespace errors and no generated artifacts.

- [ ] **Step 3: Commit and push the topic branch**

Stage only the four files listed for this task, commit with:

```text
fix(3mf): preserve merged float32 vertices
```

Push `MOVIBALE/fix/merged-3mf-precision` normally, never force-push, and open a PR targeting
`dev-refactor` only after the focused gates and real archive checks pass.
