# Vector Native Hybrid Mesh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a guarded native SVG vector mesh acceleration path that can use a Clipper2-style batch mesh module when available, while preserving current v2 output as the default and fallback oracle.

**Architecture:** Keep `core/vector_engine.py` as the public SVG mesh entry point. Add a focused optional module in `core/vector_native_mesh.py` that lazily imports `clipper2_batch`, batches run groups by `(height, z_offset)`, converts valid native mesh buffers to `trimesh.Trimesh`, and falls back to the current Shapely/trimesh extrusion for missing, empty, invalid, or failed native groups. Enable the path only through `VectorProcessor.enable_native_vector_mesh` or `LUMINA_VECTOR_NATIVE_MESH=1`.

**Tech Stack:** Python 3.12, Shapely, trimesh, optional `clipper2_batch` native extension, pytest.

---

### Task 1: Native Hybrid Unit Tests

**Files:**
- Create: `tests/test_vector_native_mesh_unit.py`
- Create: `core/vector_native_mesh.py`

- [x] **Step 1: Write failing tests for native success and native fallback**

```python
"""Unit tests for optional native SVG vector mesh extrusion."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from shapely.geometry import Polygon

from core.vector_native_mesh import run_length_extrude_native_hybrid


def _square() -> Polygon:
    return Polygon([(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)])


def test_native_hybrid_uses_valid_native_mesh(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_merge_run_groups_to_meshes(groups, *, close_delta_mm, scale, height, z_offset, xy_scale):
        assert len(groups) == 1
        assert close_delta_mm == pytest.approx(0.03)
        assert height == pytest.approx(0.08)
        assert z_offset == pytest.approx(0.0)
        assert xy_scale == pytest.approx(2.0)
        return [
            (
                [
                    (0.0, 0.0, 0.0),
                    (4.0, 0.0, 0.0),
                    (4.0, 4.0, 0.0),
                    (0.0, 4.0, 0.0),
                    (0.0, 0.0, 0.08),
                    (4.0, 0.0, 0.08),
                    (4.0, 4.0, 0.08),
                    (0.0, 4.0, 0.08),
                ],
                [
                    (0, 2, 1),
                    (0, 3, 2),
                    (4, 5, 6),
                    (4, 6, 7),
                    (0, 1, 5),
                    (0, 5, 4),
                    (1, 2, 6),
                    (1, 6, 5),
                    (2, 3, 7),
                    (2, 7, 6),
                    (3, 0, 4),
                    (3, 4, 7),
                ],
            )
        ]

    fake_module = SimpleNamespace(merge_run_groups_to_meshes=fake_merge_run_groups_to_meshes)
    result = run_length_extrude_native_hybrid(
        matched_shapes=[{"geometry": _square(), "recipe": [0]}],
        num_layers=1,
        layer_h=0.08,
        num_channels=1,
        slot_names=["White"],
        scale_factor=2.0,
        native_module=fake_module,
    )

    assert result.stats["native_meshes"] == 1
    assert result.stats["fallback_groups"] == 0
    mesh = result.meshes_by_slot["White"]["meshes"][0]
    assert len(mesh.vertices) == 8
    assert len(mesh.faces) == 12


def test_native_hybrid_falls_back_when_native_mesh_is_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_module = SimpleNamespace(
        merge_run_groups_to_meshes=lambda *args, **kwargs: [([], [])],
    )
    result = run_length_extrude_native_hybrid(
        matched_shapes=[{"geometry": _square(), "recipe": [0]}],
        num_layers=1,
        layer_h=0.08,
        num_channels=1,
        slot_names=["White"],
        scale_factor=1.0,
        native_module=fake_module,
    )

    assert result.stats["native_empty_meshes"] == 1
    assert result.stats["fallback_groups"] == 1
    mesh = result.meshes_by_slot["White"]["meshes"][0]
    assert len(mesh.vertices) > 0
    assert len(mesh.faces) > 0
```

- [x] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_vector_native_mesh_unit.py -v`

Expected: FAIL because `core.vector_native_mesh` does not exist.

- [x] **Step 3: Implement `core/vector_native_mesh.py`**

Implement:
- `NativeVectorMeshResult`
- `is_native_vector_mesh_enabled`
- `run_length_extrude_native_hybrid`
- fallback extrusion using the same Shapely union/normalize/extrude behavior as `VectorProcessor._run_length_extrude`

- [x] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_vector_native_mesh_unit.py -v`

Expected: PASS.

### Task 2: VectorProcessor Behind-Flag Integration

**Files:**
- Modify: `core/vector_engine.py`
- Test: `tests/test_vector_native_mesh_unit.py`

- [x] **Step 1: Add a failing integration test**

Add a test that monkeypatches `core.vector_native_mesh.run_length_extrude_native_hybrid`, sets `processor.enable_native_vector_mesh = True`, runs `build_mesh`, and asserts the native helper was called.

- [x] **Step 2: Run the integration test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_vector_native_mesh_unit.py::test_build_mesh_uses_native_hybrid_when_enabled -v`

Expected: FAIL because `build_mesh` does not call the helper.

- [x] **Step 3: Wire optional native path into `VectorProcessor.build_mesh`**

Route bottom-layer run-length extrusion through the native helper when `self.enable_native_vector_mesh` or `LUMINA_VECTOR_NATIVE_MESH=1` is truthy. On helper errors, log a warning and fall back to `_run_length_extrude`.

- [x] **Step 4: Verify integration**

Run: `.venv/bin/python -m pytest tests/test_vector_native_mesh_unit.py -v`

Expected: PASS.

### Task 3: Performance/Quality Script

**Files:**
- Create: `scripts/profile_vector_native_mesh.py`

- [x] **Step 1: Add script that compares baseline vs optional native**

The script should:
- load `test_images/benchmark.svg`
- build baseline and native-enabled meshes
- report timings, native stats, geometry deltas, quality gate status, and output JSON/Markdown/PNG under `.scratch/vector_native_mesh/`
- require `PYTHONPATH` or installed `clipper2_batch` for native mode

- [x] **Step 2: Run script with the local `.scratch` Clipper2 module**

Run: `PYTHONPATH=.scratch/vector_cpp_spike .venv/bin/python scripts/profile_vector_native_mesh.py`

Expected: Produces timing/quality report; native path is faster only when the module is importable.

### Task 4: Regression Verification

**Files:**
- Existing tests only

- [x] **Step 1: Run targeted backend tests**

Run: `.venv/bin/python -m pytest tests/test_vector_native_mesh_unit.py tests/test_vector_engine_unit.py tests/test_vector_engine_stroke_unit.py tests/test_vector_glb_v2_kernel_unit.py tests/test_vector_glb_v2_parity_unit.py -v`

Expected: PASS.

- [x] **Step 2: Run formatting and process checks**

Run: `git diff --check`

Expected: PASS.

Run: `ps -axo pid,command | rg '/Users/min/CascadeProjects/Lumina-studio|api_server.py|start_all.py|vite|vitest|esbuild' | rg -v 'rg '`

Expected: no Lumina backend/frontend/test helpers left running.

### Acceptance Gate

- Default SVG vector mesh generation remains current v2 unless explicitly enabled.
- Native dependency absence never breaks generation.
- Native empty/invalid mesh groups fall back to current extrusion.
- Tests cover native success, fallback, disabled default, and build integration.
- Performance report records baseline vs native-enabled timings and quality deltas.
- Profile script fails the run when geometry is missing, watertight status changes, or configured quality thresholds are exceeded.
