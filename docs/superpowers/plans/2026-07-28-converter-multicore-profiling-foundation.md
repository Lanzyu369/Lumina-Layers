# Converter Multicore Profiling Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reproducible, quality-aware profiling harness and use it to identify the actual vector and raster hotspots before changing converter behavior.

**Architecture:** A standalone script constructs the same preview/generate pipeline contexts used by Lumina Studio, selects deterministic 8/12/15-material palettes, captures cProfile and bounded resource metrics, and writes only sanitized reports under `.scratch/`. A semantic snapshot is computed outside the timed region so later serial/parallel implementations can be rejected whenever core arrays or model geometry change.

**Tech Stack:** Python 3.12 arm64, cProfile, pstats, psutil, NumPy, Trimesh, Pytest, py-spy, existing Lumina pipeline coordinators.

---

## File Map

- Create `scripts/profile_converter_multicore.py`: profile case construction,
  deterministic material palettes, timed execution, resource sampling,
  semantic snapshots, sanitized JSON/Markdown output, and CLI.
- Create `tests/test_converter_multicore_profile_unit.py`: unit coverage for
  palette selection, context construction, sanitized reports, run summaries,
  and semantic snapshot stability.
- Create `.scratch/converter-multicore/`: ignored local profile output only.
- Read `scripts/profile_vector_analyze_hotspots.py`: existing vector
  function-profile reference.
- Read `scripts/profile_stage3.py`: existing raster timing reference.

### Task 1: Create the arm64 Python 3.12 profiling environment

**Files:**
- Create locally, ignored by Git: `.venv/`
- Read: `requirements.txt`
- Read: `requirements-glb-v2.txt`

- [ ] **Step 1: Confirm the selected interpreter is native arm64**

Run:

```bash
/opt/homebrew/bin/python3.12 -c "import platform,sys; print(sys.version); print(platform.machine()); print(sys.executable)"
```

Expected: Python `3.12.x`, machine `arm64`, executable below
`/opt/homebrew`.

- [ ] **Step 2: Create the isolated virtual environment**

Run:

```bash
/opt/homebrew/bin/python3.12 -m venv .venv
```

Expected: exit 0 and `.venv/bin/python` exists.

- [ ] **Step 3: Install project, V2, profiling, and resource dependencies**

Run:

```bash
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt -r requirements-glb-v2.txt psutil py-spy
```

Expected: exit 0 with no architecture or wheel incompatibility.

- [ ] **Step 4: Record exact versions and BLAS configuration**

Run:

```bash
.venv/bin/python -c "import cv2,manifold3d,numba,numpy,PIL,platform,psutil,rasterio,scipy,shapely,sys,trimesh; print(sys.version); print(platform.machine()); print('numpy',numpy.__version__); print('shapely',shapely.__version__); print('trimesh',trimesh.__version__); print('scipy',scipy.__version__); print('opencv',cv2.__version__); print('pillow',PIL.__version__); print('numba',numba.__version__); print('rasterio',rasterio.__version__); print('manifold3d',manifold3d.__version__); print('psutil',psutil.__version__); numpy.show_config()"
```

Expected: every import succeeds and `platform.machine()` is `arm64`.

- [ ] **Step 5: Run a focused environment smoke test**

Run:

```bash
.venv/bin/python -m pytest tests/test_vector_analyze_hotspots_profile_unit.py tests/test_perf_golden.py --collect-only -q
```

Expected: collection succeeds with zero errors.

### Task 2: Define deterministic profile cases and material palettes

**Files:**
- Create: `scripts/profile_converter_multicore.py`
- Create: `tests/test_converter_multicore_profile_unit.py`

- [ ] **Step 1: Write failing palette and context tests**

Create the test file with these cases:

```python
from pathlib import Path

import pytest

from config import ModelingMode
from scripts.profile_converter_multicore import (
    MATERIAL_PALETTES,
    ProfileCase,
    build_pipeline_context,
)


@pytest.mark.parametrize("size", [8, 12, 15])
def test_material_palette_has_requested_unique_archives(size: int) -> None:
    palette = MATERIAL_PALETTES[size]
    assert len(palette) == size
    assert len(set(palette)) == size
    for directory_name in palette:
        archive = Path("materials") / directory_name / "material.json"
        stage_a = Path("materials") / directory_name / "stage_A_parameters.json"
        assert archive.is_file()
        assert stage_a.is_file()


@pytest.mark.parametrize(
    ("kind", "mode"),
    [("raster", ModelingMode.HIGH_FIDELITY), ("vector", ModelingMode.VECTOR)],
)
def test_build_pipeline_context_uses_quality_locked_profile_settings(
    tmp_path: Path,
    kind: str,
    mode: ModelingMode,
) -> None:
    source = tmp_path / ("input.svg" if kind == "vector" else "input.png")
    source.write_bytes(b"<svg/>" if kind == "vector" else b"not-decoded-in-this-test")
    case = ProfileCase(
        name=f"{kind}-12",
        kind=kind,
        input_path=source,
        target_width_mm=299.0,
        material_count=12,
    )

    ctx = build_pipeline_context(case)

    assert ctx["modeling_mode"] is mode
    assert ctx["material_source"] == "material_archive"
    assert ctx["selected_materials"] == MATERIAL_PALETTES[12]
    assert ctx["material_layer_count"] == 10
    assert ctx["material_layer_height_mm"] == 0.08
    assert ctx["quantize_colors"] == 64
    assert ctx["target_width_mm"] == 299.0
    assert ctx["structure_mode"] == "single-sided"
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_converter_multicore_profile_unit.py -v
```

Expected: FAIL during import because
`scripts.profile_converter_multicore` does not exist.

- [ ] **Step 3: Implement the profile case and deterministic palettes**

Create `scripts/profile_converter_multicore.py` with:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from config import ModelingMode


_BASE_EIGHT = [
    "纵维立方/纵维立方PLA白色",
    "纵维立方/纵维立方PLA黑色",
    "纵维立方/纵维立方PLA红色",
    "纵维立方/纵维立方PLA黄色",
    "纵维立方/纵维立方PLA蓝色",
    "纵维立方/纵维立方PLA绿色",
    "纵维立方/纵维立方PLA青色",
    "纵维立方/纵维立方PLA品红色",
]
_EXTRA_SEVEN = [
    "Karvax/Karvax PLA 晴山蓝",
    "Karvax/Karvax PLA 流光蓝",
    "Karvax/Karvax PLA 烟笼紫霞",
    "Karvax/Karvax PLA 暖黄",
    "Karvax/Karvax PLA 朱砂红",
    "Karvax/Karvax PLA 拓竹绿",
    "Karvax/Karvax PLA 耀石黑",
]
MATERIAL_PALETTES = {
    8: list(_BASE_EIGHT),
    12: [*_BASE_EIGHT, *_EXTRA_SEVEN[:4]],
    15: [*_BASE_EIGHT, *_EXTRA_SEVEN],
}


@dataclass(frozen=True)
class ProfileCase:
    name: str
    kind: Literal["raster", "vector"]
    input_path: Path
    target_width_mm: float
    material_count: Literal[8, 12, 15] = 12


def build_pipeline_context(case: ProfileCase) -> dict[str, Any]:
    modeling_mode = (
        ModelingMode.VECTOR
        if case.kind == "vector"
        else ModelingMode.HIGH_FIDELITY
    )
    return {
        "image_path": str(case.input_path),
        "lut_path": "__material_archive__",
        "target_width_mm": float(case.target_width_mm),
        "spacer_thick": 1.2,
        "structure_mode": "single-sided",
        "color_mode": "4-Color (RYBW)",
        "add_loop": False,
        "loop_width": 4.0,
        "loop_length": 8.0,
        "loop_hole": 2.5,
        "loop_pos": None,
        "modeling_mode": modeling_mode,
        "color_layers": 10,
        "layer_height_mm": 0.08,
        "quantize_colors": 64,
        "color_replacements": None,
        "replacement_regions": None,
        "backing_color_id": 0,
        "separate_backing": False,
        "enable_relief": False,
        "color_height_map": None,
        "height_mode": "color",
        "heightmap_path": None,
        "heightmap_max_height": None,
        "enable_cleanup": True,
        "enable_outline": False,
        "outline_width": 2.0,
        "enable_cloisonne": False,
        "wire_width_mm": 0.4,
        "wire_height_mm": 0.4,
        "free_color_set": None,
        "enable_coating": False,
        "coating_height_mm": 0.08,
        "hue_weight": 0.5,
        "chroma_gate": 15.0,
        "matched_rgb_path": None,
        "loop_angle": 0.0,
        "loop_offset_x": 0.0,
        "loop_offset_y": 0.0,
        "loop_position_preset": "top-center",
        "printer_id": "bambu-h2d",
        "slicer": "BambuStudio",
        "nozzle_size": "0.4",
        "relief_global_max_height": None,
        "progress": None,
        "need_2d_preview": False,
        "material_source": "material_archive",
        "selected_materials": list(MATERIAL_PALETTES[case.material_count]),
        "material_layer_count": 10,
        "material_layer_height_mm": 0.08,
        "material_grid_resolution": 8,
        "material_backing_material_index": 0,
        "use_lut_constrained": False,
        "auto_dynamic_range": False,
        "high_precision_3d_preview": False,
    }
```

- [ ] **Step 4: Run the tests and verify GREEN**

Run:

```bash
.venv/bin/python -m pytest tests/test_converter_multicore_profile_unit.py -v
```

Expected: all palette and context tests PASS.

- [ ] **Step 5: Commit the case foundation**

Run:

```bash
git add scripts/profile_converter_multicore.py tests/test_converter_multicore_profile_unit.py
git commit -m "test(perf): define converter multicore profile cases"
```

Expected: one commit containing only the new script and test.

### Task 3: Add semantic quality snapshots

**Files:**
- Modify: `scripts/profile_converter_multicore.py`
- Modify: `tests/test_converter_multicore_profile_unit.py`

- [ ] **Step 1: Write failing semantic snapshot tests**

Append:

```python
import numpy as np
import trimesh

from scripts.profile_converter_multicore import semantic_snapshot


def _scene_with_geometry_order(order: tuple[str, ...]) -> trimesh.Scene:
    scene = trimesh.Scene()
    meshes = {
        "red": trimesh.creation.box(extents=(2.0, 1.0, 0.4)),
        "blue": trimesh.creation.box(extents=(1.0, 3.0, 0.8)),
    }
    for name in order:
        scene.add_geometry(meshes[name].copy(), node_name=name, geom_name=name)
    return scene


def test_semantic_snapshot_is_stable_across_array_layout_and_scene_order() -> None:
    rgb = np.arange(36, dtype=np.uint8).reshape(3, 4, 3)
    matrix = np.arange(24, dtype=np.int32).reshape(3, 4, 2)
    first = semantic_snapshot(
        {
            "matched_rgb": rgb,
            "material_matrix": matrix,
            "mask_solid": np.ones((3, 4), dtype=bool),
            "scene": _scene_with_geometry_order(("red", "blue")),
            "slot_names": ["white", "black"],
        }
    )
    second = semantic_snapshot(
        {
            "matched_rgb": np.asfortranarray(rgb),
            "material_matrix": np.asfortranarray(matrix),
            "mask_solid": np.asfortranarray(np.ones((3, 4), dtype=bool)),
            "scene": _scene_with_geometry_order(("blue", "red")),
            "slot_names": ["white", "black"],
        }
    )
    assert first == second


def test_semantic_snapshot_changes_when_geometry_or_layers_change() -> None:
    ctx = {
        "matched_rgb": np.zeros((2, 2, 3), dtype=np.uint8),
        "material_matrix": np.zeros((2, 2, 2), dtype=np.int32),
        "mask_solid": np.ones((2, 2), dtype=bool),
        "scene": _scene_with_geometry_order(("red", "blue")),
        "slot_names": ["white", "black"],
    }
    baseline = semantic_snapshot(ctx)
    changed_layers = {**ctx, "material_matrix": np.ones((2, 2, 2), dtype=np.int32)}
    changed_scene = {
        **ctx,
        "scene": trimesh.Scene(trimesh.creation.box(extents=(9.0, 1.0, 0.4))),
    }
    assert semantic_snapshot(changed_layers) != baseline
    assert semantic_snapshot(changed_scene) != baseline
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_converter_multicore_profile_unit.py -v
```

Expected: FAIL because `semantic_snapshot` is not defined.

- [ ] **Step 3: Implement deterministic array and mesh summaries**

Add imports and helpers:

```python
import hashlib

import numpy as np
import trimesh


def _array_summary(value: object) -> dict[str, object] | None:
    if value is None:
        return None
    array = np.ascontiguousarray(np.asarray(value))
    digest = hashlib.sha256()
    digest.update(array.dtype.str.encode("ascii"))
    digest.update(repr(tuple(int(item) for item in array.shape)).encode("ascii"))
    digest.update(memoryview(array).cast("B"))
    return {
        "shape": [int(item) for item in array.shape],
        "dtype": array.dtype.str,
        "sha256": digest.hexdigest(),
    }


def _canonical_triangle_sha256(mesh: trimesh.Trimesh) -> str:
    vertices = np.round(np.asarray(mesh.vertices, dtype=np.float64), 9)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    triangles = vertices[faces]
    vertex_order = np.lexsort(
        (triangles[:, :, 2], triangles[:, :, 1], triangles[:, :, 0]),
        axis=1,
    )
    ordered_vertices = np.take_along_axis(
        triangles,
        vertex_order[:, :, np.newaxis],
        axis=1,
    )
    flattened = np.ascontiguousarray(ordered_vertices.reshape((-1, 9)))
    face_order = np.lexsort(tuple(flattened[:, index] for index in range(8, -1, -1)))
    canonical = np.ascontiguousarray(flattened[face_order])
    return hashlib.sha256(memoryview(canonical).cast("B")).hexdigest()


def _mesh_summary(mesh: trimesh.Trimesh) -> dict[str, object]:
    bounds = np.asarray(mesh.bounds, dtype=np.float64)
    return {
        "vertices": int(len(mesh.vertices)),
        "faces": int(len(mesh.faces)),
        "bounds": np.round(bounds, 9).tolist(),
        "area": round(float(mesh.area), 9),
        "volume": round(float(mesh.volume), 9),
        "watertight": bool(mesh.is_watertight),
        "euler_number": int(mesh.euler_number),
        "degenerate_faces": int(
            np.count_nonzero(np.asarray(mesh.area_faces) <= 1e-12)
        ),
        "canonical_triangle_sha256": _canonical_triangle_sha256(mesh),
    }


def semantic_snapshot(ctx: dict[str, Any]) -> dict[str, object]:
    cache = ctx.get("cache")
    payload = cache if isinstance(cache, dict) else ctx
    scene = ctx.get("scene")
    if scene is None:
        scene = payload.get("scene")
    geometry: dict[str, object] = {}
    if isinstance(scene, trimesh.Scene):
        for name in sorted(scene.geometry):
            raw = scene.geometry[name]
            if isinstance(raw, trimesh.Trimesh):
                geometry[str(name)] = _mesh_summary(raw)
    return {
        "matched_rgb": _array_summary(payload.get("matched_rgb")),
        "material_matrix": _array_summary(payload.get("material_matrix")),
        "mask_solid": _array_summary(payload.get("mask_solid")),
        "slot_names": [str(item) for item in payload.get("slot_names") or []],
        "geometry": geometry,
    }
```

- [ ] **Step 4: Run tests and verify GREEN**

Run:

```bash
.venv/bin/python -m pytest tests/test_converter_multicore_profile_unit.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit the quality snapshot**

Run:

```bash
git add scripts/profile_converter_multicore.py tests/test_converter_multicore_profile_unit.py
git commit -m "test(perf): add converter semantic profile snapshots"
```

Expected: one commit with semantic snapshot behavior and tests.

### Task 4: Add timed execution, resource sampling, and sanitized reports

**Files:**
- Modify: `scripts/profile_converter_multicore.py`
- Modify: `tests/test_converter_multicore_profile_unit.py`

- [ ] **Step 1: Write failing report sanitization and summary tests**

Append:

```python
from scripts.profile_converter_multicore import build_report, summarize_runs


def test_summarize_runs_reports_cold_warm_median_and_p90() -> None:
    summary = summarize_runs(
        [
            {"total_s": 9.0, "peak_rss_mb": 100.0},
            {"total_s": 5.0, "peak_rss_mb": 110.0},
            {"total_s": 7.0, "peak_rss_mb": 120.0},
        ]
    )
    assert summary["cold"]["total_s"] == 9.0
    assert summary["warm_median"]["total_s"] == 6.0
    assert summary["p90"]["total_s"] == pytest.approx(6.8)
    assert summary["peak"]["peak_rss_mb"] == 120.0


def test_build_report_omits_absolute_source_and_material_paths(tmp_path: Path) -> None:
    source = tmp_path / "private-user-image.jpg"
    source.write_bytes(b"image")
    case = ProfileCase(
        name="raster-12",
        kind="raster",
        input_path=source,
        target_width_mm=299.0,
        material_count=12,
    )
    report = build_report(case, runs=[{"total_s": 1.0, "peak_rss_mb": 2.0}])
    serialized = repr(report)
    assert str(tmp_path) not in serialized
    assert report["input"]["name"] == source.name
    assert report["input"]["sha256"]
    assert report["materials"]["count"] == 12
    assert "directory_names" not in report["materials"]
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_converter_multicore_profile_unit.py -v
```

Expected: FAIL because `build_report` and `summarize_runs` are not defined.

- [ ] **Step 3: Implement summaries and sanitized report metadata**

Add:

```python
import json
import math
import os
import platform
import statistics
import sys


_NUMERIC_RUN_METRICS = (
    "total_s",
    "cpu_s",
    "average_cpu_percent",
    "peak_rss_mb",
    "peak_thread_count",
    "peak_child_process_count",
)


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def summarize_runs(runs: list[dict[str, Any]]) -> dict[str, object]:
    if not runs:
        raise ValueError("runs must not be empty")
    keys = [
        key
        for key in _NUMERIC_RUN_METRICS
        if any(key in run for run in runs)
    ]
    warm = runs[1:] or runs
    return {
        "cold": dict(runs[0]),
        "warm_median": {
            key: statistics.median(float(run[key]) for run in warm if key in run)
            for key in keys
        },
        "p90": {
            key: _percentile(
                [float(run[key]) for run in warm if key in run],
                0.90,
            )
            for key in keys
        },
        "peak": {
            key: max(float(run[key]) for run in runs if key in run)
            for key in keys
        },
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_report(
    case: ProfileCase,
    runs: list[dict[str, Any]],
) -> dict[str, object]:
    return {
        "schema": "lumina_converter_multicore_profile_v1",
        "machine": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "python": sys.version.split()[0],
            "visible_cpu": os.cpu_count(),
        },
        "input": {
            "name": case.input_path.name,
            "sha256": _sha256_file(case.input_path),
            "kind": case.kind,
            "target_width_mm": case.target_width_mm,
        },
        "materials": {
            "count": case.material_count,
            "palette_sha256": hashlib.sha256(
                "\n".join(MATERIAL_PALETTES[case.material_count]).encode("utf-8")
            ).hexdigest(),
        },
        "runs": runs,
        "summary": summarize_runs(runs),
    }
```

- [ ] **Step 4: Add a cProfile execution function and CLI**

Add the following execution behavior:

```python
import argparse
import cProfile
import pstats
import threading
import time
from io import StringIO

import psutil

from core.pipeline.coordinator import run_preview_pipeline, run_raster_pipeline


class _ResourceSampler:
    def __init__(self, process: psutil.Process, interval_s: float = 0.05) -> None:
        self._process = process
        self._interval_s = interval_s
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self.peak_rss_bytes = 0
        self.peak_thread_count = 0
        self.peak_child_process_count = 0

    def _sample(self) -> None:
        try:
            children = self._process.children(recursive=True)
            processes = [self._process, *children]
            rss_bytes = 0
            thread_count = 0
            for process in processes:
                try:
                    rss_bytes += process.memory_info().rss
                    thread_count += process.num_threads()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            self.peak_rss_bytes = max(self.peak_rss_bytes, rss_bytes)
            self.peak_thread_count = max(self.peak_thread_count, thread_count)
            self.peak_child_process_count = max(
                self.peak_child_process_count,
                len(children),
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return

    def _run(self) -> None:
        while not self._stop.wait(self._interval_s):
            self._sample()

    def __enter__(self) -> "_ResourceSampler":
        self._sample()
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._stop.set()
        self._thread.join(timeout=1.0)
        self._sample()


def _cleanup_result_files(result: dict[str, Any]) -> None:
    for key in ("out_path", "glb_path", "color_recipe_path"):
        raw_path = result.get(key)
        if not raw_path:
            continue
        path = Path(str(raw_path))
        try:
            if path.is_file():
                path.unlink()
        except OSError:
            continue


def execute_case(case: ProfileCase, phase: Literal["preview", "generate"]) -> dict[str, object]:
    ctx = build_pipeline_context(case)
    profile = cProfile.Profile()
    process = psutil.Process()
    cpu_before = process.cpu_times()
    started = time.perf_counter()
    with _ResourceSampler(process) as resources:
        profile.enable()
        result = (
            run_preview_pipeline(ctx)
            if phase == "preview"
            else run_raster_pipeline(ctx)
        )
        profile.disable()
    elapsed = time.perf_counter() - started
    cpu_after = process.cpu_times()
    if result.get("error"):
        raise RuntimeError(str(result["error"]))
    stream = StringIO()
    (
        pstats.Stats(profile, stream=stream)
        .strip_dirs()
        .sort_stats("cumulative")
        .print_stats(80)
    )
    cpu_s = (
        cpu_after.user
        + cpu_after.system
        - cpu_before.user
        - cpu_before.system
    )
    snapshot = semantic_snapshot(result)
    metrics: dict[str, object] = {
        "total_s": elapsed,
        "cpu_s": cpu_s,
        "average_cpu_percent": (cpu_s / elapsed * 100.0) if elapsed else 0.0,
        "peak_rss_mb": resources.peak_rss_bytes / (1024 * 1024),
        "peak_thread_count": resources.peak_thread_count,
        "peak_child_process_count": resources.peak_child_process_count,
        "step_timings": dict(
            result.get("_preview_step_timings")
            or result.get("_step_timings")
            or {}
        ),
        "preview_timings": dict(result.get("_preview_timings") or {}),
        "vector_timings": dict(result.get("_vector_timings") or {}),
        "semantic_snapshot": snapshot,
        "cprofile": stream.getvalue(),
    }
    _cleanup_result_files(result)
    return metrics


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Profile one Lumina converter preview or generate task."
    )
    parser.add_argument("--kind", choices=("raster", "vector"), required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument(
        "--phase",
        choices=("preview", "generate"),
        required=True,
    )
    parser.add_argument("--target-width-mm", type=float, default=299.0)
    parser.add_argument(
        "--material-count",
        type=int,
        choices=(8, 12, 15),
        default=12,
    )
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(".scratch/converter-multicore"),
    )
    args = parser.parse_args(argv)
    if args.runs < 1:
        parser.error("--runs must be >= 1")
    if args.target_width_mm <= 0:
        parser.error("--target-width-mm must be > 0")
    if not args.input.is_file():
        parser.error(f"--input is not a file: {args.input}")
    expected_suffix = ".svg" if args.kind == "vector" else None
    if expected_suffix and args.input.suffix.lower() != expected_suffix:
        parser.error("--kind vector requires an SVG input")
    return args


def _render_markdown(report: dict[str, object]) -> str:
    summary = report["summary"]
    assert isinstance(summary, dict)
    cold = summary["cold"]
    assert isinstance(cold, dict)
    return "\n".join(
        [
            "# Converter Multicore Profile",
            "",
            f"- Kind: `{report['input']['kind']}`",
            f"- Input: `{report['input']['name']}`",
            f"- Input SHA-256: `{report['input']['sha256']}`",
            f"- Phase: `{report['phase']}`",
            f"- Materials: `{report['materials']['count']}`",
            f"- Target width: `{report['input']['target_width_mm']} mm`",
            f"- Cold total: `{float(cold['total_s']):.3f} s`",
            f"- Cold peak RSS: `{float(cold['peak_rss_mb']):.2f} MiB`",
            "",
        ]
    )


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    case = ProfileCase(
        name=f"{args.kind}-{args.material_count}",
        kind=args.kind,
        input_path=args.input,
        target_width_mm=args.target_width_mm,
        material_count=args.material_count,
    )
    runs: list[dict[str, Any]] = []
    for index in range(1, args.runs + 1):
        print(
            f"[profile] {case.name} {args.phase} run {index}/{args.runs}",
            flush=True,
        )
        run = execute_case(case, args.phase)
        runs.append(run)
        print(
            f"[profile] total={float(run['total_s']):.3f}s "
            f"peak_rss={float(run['peak_rss_mb']):.2f}MiB",
            flush=True,
        )
    report = build_report(case, runs)
    report["phase"] = args.phase
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "profile.json"
    markdown_path = args.output_dir / "profile.md"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    markdown_path.write_text(_render_markdown(report), encoding="utf-8")
    print(f"[profile] json={json_path}", flush=True)
    print(f"[profile] markdown={markdown_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

The resource sampler adds one constant observer thread to every run; report this
explicitly when interpreting peak thread counts. It writes JSON plus Markdown
below the requested output directory and never stores the absolute input path
or material directory names.

- [ ] **Step 5: Run unit tests and script help**

Run:

```bash
.venv/bin/python -m pytest tests/test_converter_multicore_profile_unit.py -v
.venv/bin/python scripts/profile_converter_multicore.py --help
```

Expected: all tests PASS and help lists every required argument.

- [ ] **Step 6: Commit the profiling runner**

Run:

```bash
git add scripts/profile_converter_multicore.py tests/test_converter_multicore_profile_unit.py
git commit -m "feat(perf): add converter multicore profiling harness"
```

Expected: one commit with the working CLI and tests.

### Task 5: Capture serial vector and raster evidence

**Files:**
- Create locally, ignored by Git:
  `.scratch/converter-multicore/baseline/`
- Do not modify production source.

- [ ] **Step 1: Run the focused harness tests again**

Run:

```bash
.venv/bin/python -m pytest tests/test_converter_multicore_profile_unit.py tests/test_vector_analyze_hotspots_profile_unit.py -v
```

Expected: all tests PASS.

- [ ] **Step 2: Capture the raster preview baseline**

Run with a 20-minute command timeout:

```bash
LUMINA_RASTER_PARALLELISM=1 LUMINA_DISABLE_PARALLEL_MESH=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 .venv/bin/python scripts/profile_converter_multicore.py --kind raster --input '/Users/min/Downloads/145874854_p0_master1200.jpg' --phase preview --target-width-mm 299 --material-count 12 --runs 1 --output-dir .scratch/converter-multicore/baseline/raster-preview
```

Expected: exit 0, one sanitized JSON report, one Markdown report, and no
absolute input path in either report.

- [ ] **Step 3: Capture the raster generate baseline**

Run with a 30-minute command timeout:

```bash
LUMINA_RASTER_PARALLELISM=1 LUMINA_DISABLE_PARALLEL_MESH=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 .venv/bin/python scripts/profile_converter_multicore.py --kind raster --input '/Users/min/Downloads/145874854_p0_master1200.jpg' --phase generate --target-width-mm 299 --material-count 12 --runs 1 --output-dir .scratch/converter-multicore/baseline/raster-generate
```

Expected: exit 0 with S01-S12 timings and a semantic snapshot.

- [ ] **Step 4: Capture the complex vector preview baseline**

Run with a 30-minute command timeout:

```bash
LUMINA_VECTOR_PARALLELISM=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 .venv/bin/python scripts/profile_converter_multicore.py --kind vector --input '/Users/min/Downloads/梵高星空款式西森猫猫.svg' --phase preview --target-width-mm 299 --material-count 12 --runs 1 --output-dir .scratch/converter-multicore/baseline/vector-preview
```

Expected: exit 0 with parse, clip, material match, and preview timing evidence.

- [ ] **Step 5: Capture the complex vector generate baseline**

Run with a 40-minute command timeout:

```bash
LUMINA_VECTOR_PARALLELISM=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 .venv/bin/python scripts/profile_converter_multicore.py --kind vector --input '/Users/min/Downloads/梵高星空款式西森猫猫.svg' --phase generate --target-width-mm 299 --material-count 12 --runs 1 --output-dir .scratch/converter-multicore/baseline/vector-generate
```

Expected: exit 0 with vector mesh, 3MF, GLB, and total timing evidence.

- [ ] **Step 6: Capture sampling profiles for the dominant raster and vector phases**

Launch the script through py-spy using the phase identified as dominant above:

```bash
.venv/bin/py-spy record --format speedscope --output .scratch/converter-multicore/baseline/raster.speedscope.json -- .venv/bin/python scripts/profile_converter_multicore.py --kind raster --input '/Users/min/Downloads/145874854_p0_master1200.jpg' --phase generate --target-width-mm 299 --material-count 12 --runs 1 --output-dir .scratch/converter-multicore/baseline/raster-sampling
.venv/bin/py-spy record --format speedscope --output .scratch/converter-multicore/baseline/vector.speedscope.json -- .venv/bin/python scripts/profile_converter_multicore.py --kind vector --input '/Users/min/Downloads/梵高星空款式西森猫猫.svg' --phase preview --target-width-mm 299 --material-count 12 --runs 1 --output-dir .scratch/converter-multicore/baseline/vector-sampling
```

Expected: both sampling profiles exist and the invoked benchmark completes.

- [ ] **Step 7: Check for leftover Lumina and profiling processes**

Run:

```bash
ps -axo pid=,command= | rg 'api_server.py|start_all.py|vite|vitest|profile_converter_multicore.py|py-spy' || true
```

Expected: no process from these profile runs remains.

### Task 6: Rank hotspots and write the two evidence-backed implementation plans

**Files:**
- Read: `.scratch/converter-multicore/baseline/**/*.json`
- Read: `.scratch/converter-multicore/baseline/**/*.md`
- Read: `.scratch/converter-multicore/baseline/*.speedscope.json`
- Create:
  `docs/superpowers/plans/2026-07-28-raster-single-task-multicore.md`
- Create:
  `docs/superpowers/plans/2026-07-28-vector-single-task-multicore.md`

- [ ] **Step 1: Produce a hotspot table**

For preview and generate separately, rank:

```text
stage/function | wall seconds | cumulative percent | calls | GIL/native classification | independent work unit | estimated transfer bytes
```

Expected: every proposed code change points to a measured row; no candidate is
selected by call count alone.

- [ ] **Step 2: State one root-cause hypothesis per pipeline**

Write hypotheses in the local report using this exact form:

```text
Raster root cause: <stage/function> dominates because <measured evidence>;
the smallest experiment is <one isolated change>.

Vector root cause: <stage/function> dominates because <measured evidence>;
the smallest experiment is <one isolated change>.
```

Expected: each hypothesis is specific and independently testable.

- [ ] **Step 3: Write the raster implementation plan**

The plan must name exact production and test files, start every behavior change
with a failing test, preserve the serial semantic snapshot, and include
1/2/4/8 plus small-input and two-task measurements.

- [ ] **Step 4: Write the vector implementation plan**

The plan must name exact production and test files, start every behavior change
with a failing test, preserve shape/material order and the serial semantic
snapshot, and include preview/generate reuse plus 1/2/4/8 measurements.

- [ ] **Step 5: Self-review both plans against the design**

Run:

```bash
rg -n "TBD|TODO|FIXME|PLACEHOLDER|implement later|similar to Task" docs/superpowers/plans/2026-07-28-raster-single-task-multicore.md docs/superpowers/plans/2026-07-28-vector-single-task-multicore.md
git diff --check
```

Expected: no placeholder matches and no whitespace errors.

- [ ] **Step 6: Commit the evidence-backed plans**

Run:

```bash
git add docs/superpowers/plans/2026-07-28-raster-single-task-multicore.md docs/superpowers/plans/2026-07-28-vector-single-task-multicore.md
git commit -m "docs(perf): plan evidence-backed converter parallelism"
```

Expected: one documentation-only commit. Profile artifacts remain ignored and
unstaged.
