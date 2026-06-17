# Outline Coating Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix GitHub issue #251 so SVG/vector outline expands outward and transparent coating covers the outline-expanded footprint.

**Architecture:** Keep vector outline geometry sourced from `analysis.matched_shapes`. Pass outline settings into `VectorProcessor.build_mesh()` so the vector coating mesh is generated from the same expanded silhouette that the later `Outline` mesh represents. Keep preview/generate behavior aligned by testing the generated scene geometry directly.

**Tech Stack:** Python, Shapely, trimesh, pytest, Hypothesis-backed existing vector outline tests.

---

### Task 1: Capture The Coating Footprint Regression

**Files:**
- Modify: `tests/test_vector_outline_pipeline_properties.py`

- [ ] **Step 1: Write the failing test**

Add a unit test that builds a `VectorProcessor` fixture with `enable_coating=True`, `enable_outline=True`, and `outline_width_mm=5.0`. The test should compare the exported `Coating` XY footprint with the transformed outline-expanded body bounds and assert the coating reaches the same outward envelope.

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/min/CascadeProjects/Lumina-studio/.venv/bin/python -m pytest tests/test_vector_outline_pipeline_properties.py::test_vector_coating_covers_outline_expanded_footprint -q`

Expected: FAIL because current `VectorProcessor.build_mesh()` uses the backing/silhouette footprint for `Coating` and does not know outline is enabled.

### Task 2: Pass Outline Settings Into Vector Mesh Building

**Files:**
- Modify: `core/pipeline/vector_branch.py`
- Modify: `core/vector_engine.py`

- [ ] **Step 1: Implement the minimal production change**

Set `vec_processor.enable_outline` and `vec_processor.outline_width_mm` before preview/generate calls to `build_mesh()`. In `VectorProcessor._init_runtime_defaults()`, add default fields. In `VectorProcessor.build_mesh()`, when `enable_coating` and `enable_outline` are both true, buffer `coating_sil` by `outline_width_mm / scale_factor` before extrusion.

- [ ] **Step 2: Run the focused test**

Run: `/Users/min/CascadeProjects/Lumina-studio/.venv/bin/python -m pytest tests/test_vector_outline_pipeline_properties.py::test_vector_coating_covers_outline_expanded_footprint -q`

Expected: PASS.

### Task 3: Preserve Existing Outline Guarantees

**Files:**
- Test: `tests/test_vector_outline_pipeline_properties.py`
- Test: `tests/test_segmented_glb_unit.py`

- [ ] **Step 1: Run existing backend regression tests**

Run: `/Users/min/CascadeProjects/Lumina-studio/.venv/bin/python -m pytest tests/test_vector_outline_pipeline_properties.py tests/test_segmented_glb_unit.py -q`

Expected: PASS.

- [ ] **Step 2: Check whitespace and syntax**

Run: `git diff --check`

Expected: no output and exit code 0.

### Task 4: Validate With User SVG

**Files:**
- Read-only input: `/Users/min/Downloads/描边后矢量化.svg`

- [ ] **Step 1: Generate or inspect vector geometry from the provided SVG**

Use the repo virtualenv to run a small Python verification that analyzes the SVG as UTF-8, builds vector geometry with `enable_outline=True` and `enable_coating=True`, and prints `Outline`/`Coating` bounds.

- [ ] **Step 2: Verify outcome**

Expected: `Coating` XY bounds cover the `Outline` outer bounds and `Outline` Z bounds include the negative coating span. If a local browser/backend check is practical, open the model for manual or self review before PR.
