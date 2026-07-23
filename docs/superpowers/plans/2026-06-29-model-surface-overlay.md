# Model Surface Overlay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first usable model surface overlay workflow: upload STL/OBJ + image/SVG, select one planar model face, place artwork on that face, reuse the existing color pipeline, embed the resulting color geometry into the model surface, and export a slicer-checkable 3MF.

**Architecture:** Keep reusable geometry in `core/model_surface/`, expose thin FastAPI endpoints under `/api/convert/model-surface/*`, and add a small frontend store slice plus dedicated surface-overlay controls. The existing converter preview/generate pipeline stays the source of truth for color matching and material identity; the new workflow prepares a masked surface artwork image before preview and assembles a final overlay scene after color mesh generation.

**Tech Stack:** Python 3.12 from `./.venv/bin/python`, FastAPI, Pydantic, `trimesh`, `shapely`, `manifold3d`, React 19, Zustand, Three.js, Vitest through `python scripts/run_vitest.py`.

---

## Confirmed Inputs For Manual Verification

- STL model: `/Users/min/Downloads/IKEA++pegboard_stls/obj_10_大间隙.STEP.stl`
- SVG artwork: `/Users/min/Downloads/945695877_20260622_232544_vector.svg`
- Bitmap artwork: `/Users/min/Downloads/9DCCD9AB393A882ECB61703FF607F690.jpg`

Read-only preflight already found:

- JPG: `3834 x 2205`, RGB.
- SVG: `1024 x 1024`, `viewBox="0 0 1024 1024"`.
- STL: `200 x 200 x 5 mm`; raw `process=False` load is not watertight, but `trimesh.load_mesh(..., process=True)` produces a single watertight body with `140609` vertices and `281390` faces.

## Files And Responsibilities

- Create `core/model_surface/types.py`: dataclasses, enums, typed errors, JSON-safe DTO helpers.
- Create `core/model_surface/loader.py`: STL/OBJ validation, `trimesh` load with process summary, unit warning heuristics, GLB preview export.
- Create `core/model_surface/selection.py`: planar connected face selection from a face index or hit triangle.
- Create `core/model_surface/footprint.py`: 3D plane frame, 2D footprint polygon with holes, bounds and placement presets.
- Create `core/model_surface/artwork.py`: render placed JPG/PNG/SVG into the selected surface canvas and apply footprint mask.
- Create `core/model_surface/assembly.py`: transform existing Lumina color meshes into model coordinates, build pocket geometry, run `manifold3d` boolean where possible, and export scene slots.
- Create `core/model_surface/pipeline.py`: worker-facing orchestration that calls the existing converter scene builder and then assembles the overlay scene.
- Modify `core/converter.py`: add a context-returning helper so overlay generation can reuse the existing raster scene without copying pipeline logic.
- Modify `core/pipeline/coordinator.py`: support a controlled `stop_after_step="S08"` for raster-only overlay scene generation.
- Create `api/schemas/model_surface.py`: request/response models for upload, selection, placement, and generate config.
- Create `api/routers/converter/model_surface.py`: upload/analyze/select endpoints and shared session attachment helpers.
- Modify `api/routers/converter/__init__.py`: include the model surface router.
- Modify `api/routers/converter/preview.py`: when a surface model + placement is supplied, render a masked surface artwork PNG and store model-surface config in session.
- Modify `api/routers/converter/generate.py`: when session has confirmed model-surface config, call the overlay worker path instead of plain model generation.
- Modify `api/workers/converter_workers.py`: add `worker_generate_model_surface_overlay`.
- Modify `api/schemas/converter.py` and `api/schemas/responses.py`: add optional model-surface generate fields and response warnings.
- Modify `frontend/src/api/types.ts`: add model surface DTOs.
- Modify `frontend/src/api/converter.ts`: add model surface upload/select API functions and optional model-surface fields to preview/generate requests.
- Modify `frontend/src/stores/converter/store.ts`: add model file, selection, placement, warnings, and actions.
- Create `frontend/src/components/modelSurface/ModelSurfacePanel.tsx`: upload status, face selection summary, placement controls, warnings.
- Create `frontend/src/components/modelSurface/ModelSurfaceViewer.tsx`: STL/OBJ Three.js viewer, raycast face selection, artwork overlay preview plane.
- Modify `frontend/src/components/sections/BasicSettings.tsx`: add model upload entry beside the existing artwork uploader.
- Modify `frontend/src/components/Scene3D.tsx`: show model-surface viewer when model-surface mode is active before standard generated GLB preview.
- Modify `frontend/src/i18n/translations.ts`: add all UI strings.
- Add backend tests under `tests/test_model_surface_*_unit.py`.
- Add frontend tests under `frontend/src/__tests__/model-surface-*.test.tsx` and `frontend/src/api/__tests__/modelSurface.test.ts`.

---

### Task 1: Core Model Loading And Quality Summary

**Files:**
- Create: `core/model_surface/__init__.py`
- Create: `core/model_surface/types.py`
- Create: `core/model_surface/loader.py`
- Test: `tests/test_model_surface_loader_unit.py`

- [ ] **Step 1: Write failing loader tests**

Add tests that create a simple box mesh, load it through the new loader, and verify dimensions, watertight status, extension rejection, and unit warning.

```python
# tests/test_model_surface_loader_unit.py
from __future__ import annotations

import pytest
import trimesh

from core.model_surface.loader import load_model_surface_mesh
from core.model_surface.types import ModelSurfaceError


def test_load_model_surface_mesh_reports_processed_box(tmp_path):
    path = tmp_path / "plate.stl"
    trimesh.creation.box(extents=(80.0, 40.0, 5.0)).export(path)

    loaded = load_model_surface_mesh(path)

    assert loaded.summary.extents_mm == pytest.approx((80.0, 40.0, 5.0))
    assert loaded.summary.face_count > 0
    assert loaded.summary.is_watertight is True
    assert loaded.summary.unit_warning is None


def test_load_model_surface_mesh_rejects_unknown_extension(tmp_path):
    path = tmp_path / "plate.step"
    path.write_text("not supported", encoding="utf-8")

    with pytest.raises(ModelSurfaceError, match="Only STL and OBJ"):
        load_model_surface_mesh(path)


def test_load_model_surface_mesh_warns_for_tiny_inch_like_model(tmp_path):
    path = tmp_path / "inch_plate.stl"
    trimesh.creation.box(extents=(8.0, 8.0, 0.2)).export(path)

    loaded = load_model_surface_mesh(path)

    assert loaded.summary.unit_warning == "model_dimensions_look_like_inches"
```

- [ ] **Step 2: Run tests and confirm failure**

Run:

```bash
./.venv/bin/python -m pytest tests/test_model_surface_loader_unit.py -v
```

Expected: tests fail because `core.model_surface.loader` does not exist.

- [ ] **Step 3: Implement loader types and errors**

Add:

```python
# core/model_surface/types.py
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any


class ModelSurfaceError(ValueError):
    """Domain error for model-surface workflow.
    模型覆面流程的领域错误。
    """


class EdgeMode(str, Enum):
    EDGE_TO_EDGE = "edge_to_edge"
    INSET = "inset"


@dataclass(frozen=True)
class MeshSummary:
    vertex_count: int
    face_count: int
    bounds_min_mm: tuple[float, float, float]
    bounds_max_mm: tuple[float, float, float]
    extents_mm: tuple[float, float, float]
    is_watertight: bool
    is_winding_consistent: bool
    body_count: int
    unit_warning: str | None

    def to_public_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LoadedSurfaceMesh:
    path: Path
    mesh: Any
    summary: MeshSummary
```

- [ ] **Step 4: Implement `load_model_surface_mesh`**

Add:

```python
# core/model_surface/loader.py
from __future__ import annotations

from pathlib import Path

import numpy as np
import trimesh

from core.model_surface.types import LoadedSurfaceMesh, MeshSummary, ModelSurfaceError

SUPPORTED_MODEL_SUFFIXES = {".stl", ".obj"}


def _unit_warning(extents: np.ndarray) -> str | None:
    longest = float(np.max(extents)) if extents.size else 0.0
    shortest = float(np.min(extents)) if extents.size else 0.0
    if 0.01 < shortest and longest <= 12.0:
        return "model_dimensions_look_like_inches"
    if longest >= 1200.0:
        return "model_dimensions_look_too_large_for_mm"
    return None


def load_model_surface_mesh(path: str | Path) -> LoadedSurfaceMesh:
    model_path = Path(path)
    suffix = model_path.suffix.lower()
    if suffix not in SUPPORTED_MODEL_SUFFIXES:
        raise ModelSurfaceError("Only STL and OBJ model files are supported.")
    if not model_path.exists():
        raise ModelSurfaceError(f"Model file does not exist: {model_path}")

    loaded = trimesh.load_mesh(str(model_path), process=True)
    if isinstance(loaded, trimesh.Scene):
        geometries = [g for g in loaded.geometry.values() if isinstance(g, trimesh.Trimesh)]
        if not geometries:
            raise ModelSurfaceError("Model contains no mesh geometry.")
        mesh = trimesh.util.concatenate(geometries)
    elif isinstance(loaded, trimesh.Trimesh):
        mesh = loaded
    else:
        raise ModelSurfaceError(f"Unsupported model payload: {type(loaded).__name__}")

    if len(mesh.faces) == 0 or len(mesh.vertices) == 0:
        raise ModelSurfaceError("Model mesh is empty.")

    bounds = np.asarray(mesh.bounds, dtype=np.float64)
    extents = np.asarray(mesh.extents, dtype=np.float64)
    body_count = len(mesh.split(only_watertight=False))
    summary = MeshSummary(
        vertex_count=int(len(mesh.vertices)),
        face_count=int(len(mesh.faces)),
        bounds_min_mm=tuple(float(v) for v in bounds[0]),
        bounds_max_mm=tuple(float(v) for v in bounds[1]),
        extents_mm=tuple(float(v) for v in extents),
        is_watertight=bool(mesh.is_watertight),
        is_winding_consistent=bool(mesh.is_winding_consistent),
        body_count=int(body_count),
        unit_warning=_unit_warning(extents),
    )
    return LoadedSurfaceMesh(path=model_path, mesh=mesh, summary=summary)
```

- [ ] **Step 5: Run loader tests**

Run:

```bash
./.venv/bin/python -m pytest tests/test_model_surface_loader_unit.py -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add core/model_surface tests/test_model_surface_loader_unit.py
git commit -m "feat(model-surface): add mesh loading summary"
```

---

### Task 2: Planar Face Selection And Footprint Extraction

**Files:**
- Create: `core/model_surface/selection.py`
- Create: `core/model_surface/footprint.py`
- Test: `tests/test_model_surface_selection_unit.py`

- [ ] **Step 1: Write failing geometry tests**

Use synthetic meshes so the expected planar component and holes are deterministic.

```python
# tests/test_model_surface_selection_unit.py
from __future__ import annotations

import pytest
import trimesh

from core.model_surface.footprint import build_surface_footprint
from core.model_surface.selection import select_planar_component


def test_select_planar_component_finds_top_box_face():
    mesh = trimesh.creation.box(extents=(20.0, 10.0, 2.0))
    face_index = int(max(range(len(mesh.faces)), key=lambda i: mesh.face_normals[i][2]))

    selection = select_planar_component(mesh, face_index)

    assert selection.face_count == 2
    assert selection.area_mm2 == pytest.approx(200.0)
    assert selection.normal == pytest.approx((0.0, 0.0, 1.0))


def test_surface_footprint_preserves_rectangular_bounds():
    mesh = trimesh.creation.box(extents=(20.0, 10.0, 2.0))
    face_index = int(max(range(len(mesh.faces)), key=lambda i: mesh.face_normals[i][2]))
    selection = select_planar_component(mesh, face_index)

    footprint = build_surface_footprint(mesh, selection.face_indices)

    assert footprint.bounds_width_mm == pytest.approx(20.0)
    assert footprint.bounds_height_mm == pytest.approx(10.0)
    assert footprint.area_mm2 == pytest.approx(200.0)
    assert footprint.hole_count == 0
```

- [ ] **Step 2: Run tests and confirm failure**

Run:

```bash
./.venv/bin/python -m pytest tests/test_model_surface_selection_unit.py -v
```

Expected: imports fail because selection and footprint modules do not exist.

- [ ] **Step 3: Extend types**

Add these dataclasses to `core/model_surface/types.py`:

```python
@dataclass(frozen=True)
class PlaneFrame:
    origin: tuple[float, float, float]
    normal: tuple[float, float, float]
    u_axis: tuple[float, float, float]
    v_axis: tuple[float, float, float]


@dataclass(frozen=True)
class SurfaceSelection:
    face_indices: tuple[int, ...]
    normal: tuple[float, float, float]
    plane_origin: tuple[float, float, float]
    area_mm2: float
    face_count: int


@dataclass(frozen=True)
class SurfaceFootprint:
    frame: PlaneFrame
    outer: tuple[tuple[float, float], ...]
    holes: tuple[tuple[tuple[float, float], ...], ...]
    bounds_min: tuple[float, float]
    bounds_max: tuple[float, float]
    bounds_width_mm: float
    bounds_height_mm: float
    area_mm2: float
    hole_count: int
```

- [ ] **Step 4: Implement planar connected selection**

Implementation rule: start at the hit face, follow adjacent faces, keep faces whose normal is within `angle_tolerance_deg` and whose vertices lie within `plane_tolerance_mm` of the seed plane.

```python
# core/model_surface/selection.py
from __future__ import annotations

import math

import numpy as np
import trimesh

from core.model_surface.types import ModelSurfaceError, SurfaceSelection


def select_planar_component(
    mesh: trimesh.Trimesh,
    face_index: int,
    *,
    angle_tolerance_deg: float = 1.0,
    plane_tolerance_mm: float = 0.05,
) -> SurfaceSelection:
    if face_index < 0 or face_index >= len(mesh.faces):
        raise ModelSurfaceError("Selected face index is outside the model.")

    normals = np.asarray(mesh.face_normals, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    seed_normal = normals[face_index]
    normal_len = np.linalg.norm(seed_normal)
    if normal_len <= 0:
        raise ModelSurfaceError("Selected face has invalid normal.")
    seed_normal = seed_normal / normal_len
    seed_origin = vertices[faces[face_index]].mean(axis=0)
    min_dot = math.cos(math.radians(angle_tolerance_deg))

    adjacency: dict[int, list[int]] = {}
    for left, right in np.asarray(mesh.face_adjacency, dtype=np.int64):
        adjacency.setdefault(int(left), []).append(int(right))
        adjacency.setdefault(int(right), []).append(int(left))

    selected: set[int] = set()
    pending = [int(face_index)]
    while pending:
        current = pending.pop()
        if current in selected:
            continue
        current_normal = normals[current]
        current_len = np.linalg.norm(current_normal)
        if current_len <= 0:
            continue
        current_normal = current_normal / current_len
        if float(np.dot(current_normal, seed_normal)) < min_dot:
            continue
        tri = vertices[faces[current]]
        distances = np.abs((tri - seed_origin) @ seed_normal)
        if float(np.max(distances)) > plane_tolerance_mm:
            continue
        selected.add(current)
        pending.extend(adjacency.get(current, []))

    if not selected:
        raise ModelSurfaceError("No planar surface could be selected.")

    selected_indices = tuple(sorted(selected))
    area = float(np.asarray(mesh.area_faces)[list(selected_indices)].sum())
    return SurfaceSelection(
        face_indices=selected_indices,
        normal=tuple(float(v) for v in seed_normal),
        plane_origin=tuple(float(v) for v in seed_origin),
        area_mm2=area,
        face_count=len(selected_indices),
    )
```

- [ ] **Step 5: Implement footprint projection**

Use Shapely `polygonize` over projected triangle edges and `unary_union` to recover outer and inner boundaries.

```python
# core/model_surface/footprint.py
from __future__ import annotations

import numpy as np
import shapely.geometry as sg
import shapely.ops as so
import trimesh

from core.model_surface.types import ModelSurfaceError, PlaneFrame, SurfaceFootprint


def _frame_from_faces(mesh: trimesh.Trimesh, face_indices: tuple[int, ...]) -> PlaneFrame:
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    points = vertices[faces[list(face_indices)].reshape(-1)]
    origin = points.mean(axis=0)
    normal = np.asarray(mesh.face_normals[list(face_indices)], dtype=np.float64).mean(axis=0)
    normal = normal / np.linalg.norm(normal)
    candidate = np.array([1.0, 0.0, 0.0])
    if abs(float(np.dot(candidate, normal))) > 0.9:
        candidate = np.array([0.0, 1.0, 0.0])
    u_axis = np.cross(normal, candidate)
    u_axis = u_axis / np.linalg.norm(u_axis)
    v_axis = np.cross(normal, u_axis)
    v_axis = v_axis / np.linalg.norm(v_axis)
    return PlaneFrame(
        origin=tuple(float(v) for v in origin),
        normal=tuple(float(v) for v in normal),
        u_axis=tuple(float(v) for v in u_axis),
        v_axis=tuple(float(v) for v in v_axis),
    )


def _project(frame: PlaneFrame, points: np.ndarray) -> np.ndarray:
    origin = np.asarray(frame.origin, dtype=np.float64)
    u_axis = np.asarray(frame.u_axis, dtype=np.float64)
    v_axis = np.asarray(frame.v_axis, dtype=np.float64)
    rel = points - origin
    return np.column_stack([rel @ u_axis, rel @ v_axis])


def build_surface_footprint(mesh: trimesh.Trimesh, face_indices: tuple[int, ...]) -> SurfaceFootprint:
    if not face_indices:
        raise ModelSurfaceError("Surface selection is empty.")
    frame = _frame_from_faces(mesh, face_indices)
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    projected_triangles = _project(frame, vertices[faces[list(face_indices)].reshape(-1)]).reshape((-1, 3, 2))
    polygons = [sg.Polygon(tri) for tri in projected_triangles if sg.Polygon(tri).area > 1e-9]
    if not polygons:
        raise ModelSurfaceError("Selected surface footprint is empty.")
    merged = so.unary_union(polygons)
    if merged.geom_type == "MultiPolygon":
        merged = max(merged.geoms, key=lambda geom: geom.area)
    if not isinstance(merged, sg.Polygon) or merged.area <= 0:
        raise ModelSurfaceError("Selected surface footprint is invalid.")
    minx, miny, maxx, maxy = merged.bounds
    return SurfaceFootprint(
        frame=frame,
        outer=tuple((float(x), float(y)) for x, y in merged.exterior.coords),
        holes=tuple(
            tuple((float(x), float(y)) for x, y in ring.coords)
            for ring in merged.interiors
        ),
        bounds_min=(float(minx), float(miny)),
        bounds_max=(float(maxx), float(maxy)),
        bounds_width_mm=float(maxx - minx),
        bounds_height_mm=float(maxy - miny),
        area_mm2=float(merged.area),
        hole_count=len(merged.interiors),
    )
```

- [ ] **Step 6: Run selection tests**

Run:

```bash
./.venv/bin/python -m pytest tests/test_model_surface_selection_unit.py -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add core/model_surface tests/test_model_surface_selection_unit.py
git commit -m "feat(model-surface): select planar footprints"
```

---

### Task 3: Surface Artwork Rendering

**Files:**
- Create: `core/model_surface/artwork.py`
- Test: `tests/test_model_surface_artwork_unit.py`

- [ ] **Step 1: Write failing artwork tests**

```python
# tests/test_model_surface_artwork_unit.py
from __future__ import annotations

from PIL import Image

from core.model_surface.artwork import SurfacePlacement, render_surface_artwork
from core.model_surface.types import EdgeMode, PlaneFrame, SurfaceFootprint


def _footprint() -> SurfaceFootprint:
    return SurfaceFootprint(
        frame=PlaneFrame(
            origin=(0.0, 0.0, 0.0),
            normal=(0.0, 0.0, 1.0),
            u_axis=(1.0, 0.0, 0.0),
            v_axis=(0.0, 1.0, 0.0),
        ),
        outer=((-10.0, -5.0), (10.0, -5.0), (10.0, 5.0), (-10.0, 5.0), (-10.0, -5.0)),
        holes=(),
        bounds_min=(-10.0, -5.0),
        bounds_max=(10.0, 5.0),
        bounds_width_mm=20.0,
        bounds_height_mm=10.0,
        area_mm2=200.0,
        hole_count=0,
    )


def test_render_surface_artwork_masks_to_surface_bounds(tmp_path):
    source = tmp_path / "source.png"
    Image.new("RGB", (80, 40), (255, 0, 0)).save(source)

    result = render_surface_artwork(
        source_path=source,
        footprint=_footprint(),
        placement=SurfacePlacement(mode=EdgeMode.EDGE_TO_EDGE),
        pixels_per_mm=4,
        output_dir=tmp_path,
    )

    assert result.width_px == 80
    assert result.height_px == 40
    assert result.target_width_mm == 20.0
    assert result.output_path.exists()
    rendered = Image.open(result.output_path).convert("RGBA")
    assert rendered.getpixel((40, 20)) == (255, 0, 0, 255)
```

- [ ] **Step 2: Run tests and confirm failure**

Run:

```bash
./.venv/bin/python -m pytest tests/test_model_surface_artwork_unit.py -v
```

Expected: tests fail because `core.model_surface.artwork` does not exist.

- [ ] **Step 3: Implement artwork dataclasses and PNG rendering**

```python
# core/model_surface/artwork.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tempfile

from PIL import Image, ImageDraw

from config import TEMP_DIR
from core.model_surface.types import EdgeMode, SurfaceFootprint
from core.pipeline.processing_ops.svg_rasterizer import rasterize_svg


@dataclass(frozen=True)
class SurfacePlacement:
    mode: EdgeMode = EdgeMode.EDGE_TO_EDGE
    offset_x_mm: float = 0.0
    offset_y_mm: float = 0.0
    scale: float = 1.0
    rotation_deg: float = 0.0
    inset_mm: float = 0.0


@dataclass(frozen=True)
class RenderedSurfaceArtwork:
    output_path: Path
    width_px: int
    height_px: int
    target_width_mm: float
    target_height_mm: float


def _load_source_rgba(source_path: Path, width_px: int, height_px: int) -> Image.Image:
    if source_path.suffix.lower() == ".svg":
        rgba = rasterize_svg(str(source_path), width_px, height_px)
        return Image.fromarray(rgba, mode="RGBA")
    return Image.open(source_path).convert("RGBA")


def _footprint_mask(footprint: SurfaceFootprint, width_px: int, height_px: int) -> Image.Image:
    min_x, min_y = footprint.bounds_min
    max_x, max_y = footprint.bounds_max
    scale_x = width_px / max(max_x - min_x, 1e-9)
    scale_y = height_px / max(max_y - min_y, 1e-9)

    def to_px(point: tuple[float, float]) -> tuple[int, int]:
        x, y = point
        return (round((x - min_x) * scale_x), round((max_y - y) * scale_y))

    mask = Image.new("L", (width_px, height_px), 0)
    draw = ImageDraw.Draw(mask)
    draw.polygon([to_px(p) for p in footprint.outer], fill=255)
    for hole in footprint.holes:
        draw.polygon([to_px(p) for p in hole], fill=0)
    return mask


def render_surface_artwork(
    *,
    source_path: str | Path,
    footprint: SurfaceFootprint,
    placement: SurfacePlacement,
    pixels_per_mm: int = 6,
    output_dir: str | Path = TEMP_DIR,
) -> RenderedSurfaceArtwork:
    target_w = footprint.bounds_width_mm
    target_h = footprint.bounds_height_mm
    width_px = max(1, round(target_w * pixels_per_mm))
    height_px = max(1, round(target_h * pixels_per_mm))
    source = _load_source_rgba(Path(source_path), width_px, height_px)
    if placement.mode == EdgeMode.EDGE_TO_EDGE:
        fitted = source.resize((width_px, height_px), Image.Resampling.LANCZOS)
    else:
        fitted = Image.new("RGBA", (width_px, height_px), (0, 0, 0, 0))
        inset_px = max(0, round(placement.inset_mm * pixels_per_mm))
        target_size = (max(1, width_px - inset_px * 2), max(1, height_px - inset_px * 2))
        resized = source.resize(target_size, Image.Resampling.LANCZOS)
        fitted.alpha_composite(resized, (inset_px, inset_px))

    mask = _footprint_mask(footprint, width_px, height_px)
    fitted.putalpha(Image.composite(fitted.getchannel("A"), Image.new("L", fitted.size, 0), mask))
    fd, out = tempfile.mkstemp(suffix=".png", dir=str(output_dir))
    Path(out).unlink(missing_ok=True)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    fitted.save(out)
    return RenderedSurfaceArtwork(
        output_path=Path(out),
        width_px=width_px,
        height_px=height_px,
        target_width_mm=target_w,
        target_height_mm=target_h,
    )
```

- [ ] **Step 4: Run artwork tests**

Run:

```bash
./.venv/bin/python -m pytest tests/test_model_surface_artwork_unit.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add core/model_surface/artwork.py tests/test_model_surface_artwork_unit.py
git commit -m "feat(model-surface): render masked surface artwork"
```

---

### Task 4: Reusable Converter Scene Context

**Files:**
- Modify: `core/converter.py`
- Modify: `core/pipeline/coordinator.py`
- Test: `tests/test_model_surface_converter_context_unit.py`

- [ ] **Step 1: Write failing context test**

```python
# tests/test_model_surface_converter_context_unit.py
from __future__ import annotations

from core.pipeline.coordinator import run_raster_pipeline


def test_run_raster_pipeline_stop_after_s08_skips_export(monkeypatch):
    calls: list[str] = []

    class Step:
        def __init__(self, name: str) -> None:
            self.name = name

        def run(self, ctx: dict) -> dict:
            calls.append(self.name)
            ctx["scene"] = object()
            ctx["valid_slot_names"] = ["color_ff0000"]
            ctx["preview_colors"] = {"color_ff0000": (255, 0, 0)}
            return ctx

    import core.pipeline.coordinator as coordinator

    monkeypatch.setattr(coordinator.s01_input_validation, "run", Step("S01").run)
    monkeypatch.setattr(coordinator.s02_image_processing, "run", Step("S02").run)
    monkeypatch.setattr(coordinator.s03_color_replacement, "run", Step("S03").run)
    monkeypatch.setattr(coordinator.s04_debug_preview, "run", Step("S04").run)
    monkeypatch.setattr(coordinator.s05_preview_generation, "run", Step("S05").run)
    monkeypatch.setattr(coordinator.s06_voxel_building, "run", Step("S06").run)
    monkeypatch.setattr(coordinator.s07_mesh_generation, "run", Step("S07").run)
    monkeypatch.setattr(coordinator.s08_auxiliary_meshes, "run", Step("S08").run)
    monkeypatch.setattr(coordinator.s09_export_3mf, "run", Step("S09").run)

    result = run_raster_pipeline({"stop_after_step": "S08"})

    assert calls == ["S01", "S02", "S03", "S04", "S05", "S06", "S07", "S08"]
    assert result["valid_slot_names"] == ["color_ff0000"]
```

- [ ] **Step 2: Run test and confirm failure**

Run:

```bash
./.venv/bin/python -m pytest tests/test_model_surface_converter_context_unit.py -v
```

Expected: test fails because `stop_after_step` is ignored.

- [ ] **Step 3: Add stop point to coordinator**

In `core/pipeline/coordinator.py`, after each successful raster step, stop when requested:

```python
        if ctx.get("stop_after_step") == label:
            ctx["_pipeline_stopped_after"] = label
            return ctx
```

Place this immediately after the `if ctx.get("error"):` check and before `_report_progress(ctx, prog_after)`.

- [ ] **Step 4: Add context builder to `core/converter.py`**

Add a helper without changing the public `generate_final_model` signature:

```python
def build_image_model_context(
    *,
    stop_after_step: str | None = None,
    progress=None,
    **kwargs,
) -> dict:
    """Build a converter pipeline context for callers that need the scene.
    为需要复用 scene 的调用方构建转换管线上下文。
    """
    ctx = dict(kwargs)
    ctx["progress"] = progress
    ctx["need_2d_preview"] = False
    ctx["cover_source_path"] = ctx.get("cover_source_path") or ctx.get("image_path")
    if stop_after_step:
        ctx["stop_after_step"] = stop_after_step
    return run_raster_pipeline(ctx)
```

Then make `convert_image_to_3d` build `ctx` and call `run_raster_pipeline` exactly as before. Do not change its return tuple.

- [ ] **Step 5: Run context test**

Run:

```bash
./.venv/bin/python -m pytest tests/test_model_surface_converter_context_unit.py -v
```

Expected: test passes.

- [ ] **Step 6: Run existing converter generation smoke tests**

Run:

```bash
./.venv/bin/python -m pytest tests/test_converter_generate_unit.py tests/test_s09_export_3mf_unit.py -v
```

Expected: pass.

- [ ] **Step 7: Commit**

```bash
git add core/converter.py core/pipeline/coordinator.py tests/test_model_surface_converter_context_unit.py
git commit -m "feat(model-surface): expose reusable converter scene context"
```

---

### Task 5: Overlay Scene Assembly

**Files:**
- Create: `core/model_surface/assembly.py`
- Create: `core/model_surface/pipeline.py`
- Test: `tests/test_model_surface_assembly_unit.py`

- [ ] **Step 1: Write failing assembly tests**

```python
# tests/test_model_surface_assembly_unit.py
from __future__ import annotations

import numpy as np
import trimesh

from core.model_surface.assembly import build_embedded_overlay_scene
from core.model_surface.types import PlaneFrame, SurfaceFootprint


def test_build_embedded_overlay_scene_keeps_bounds_and_adds_base_slot(tmp_path):
    base = trimesh.creation.box(extents=(20.0, 10.0, 3.0))
    color = trimesh.creation.box(extents=(20.0, 10.0, 0.4))
    color.apply_translation((0.0, 0.0, 0.2))
    pattern = trimesh.Scene({"color_ff0000": color})
    footprint = SurfaceFootprint(
        frame=PlaneFrame(
            origin=(0.0, 0.0, 1.5),
            normal=(0.0, 0.0, 1.0),
            u_axis=(1.0, 0.0, 0.0),
            v_axis=(0.0, 1.0, 0.0),
        ),
        outer=((-10.0, -5.0), (10.0, -5.0), (10.0, 5.0), (-10.0, 5.0), (-10.0, -5.0)),
        holes=(),
        bounds_min=(-10.0, -5.0),
        bounds_max=(10.0, 5.0),
        bounds_width_mm=20.0,
        bounds_height_mm=10.0,
        area_mm2=200.0,
        hole_count=0,
    )

    result = build_embedded_overlay_scene(
        base_mesh=base,
        pattern_scene=pattern,
        footprint=footprint,
        pocket_depth_mm=0.4,
        base_slot_name="surface_base",
        base_color=(245, 245, 245),
    )

    assert "surface_base" in result.scene.geometry
    assert "color_ff0000" in result.scene.geometry
    assert result.slot_names == ["surface_base", "color_ff0000"]
    assert np.asarray(result.scene.bounds)[:, :2].tolist() == base.bounds[:, :2].tolist()
```

- [ ] **Step 2: Run tests and confirm failure**

Run:

```bash
./.venv/bin/python -m pytest tests/test_model_surface_assembly_unit.py -v
```

Expected: import fails because assembly module does not exist.

- [ ] **Step 3: Implement assembly result and transform logic**

```python
# core/model_surface/assembly.py
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import trimesh

from core.model_surface.types import ModelSurfaceError, SurfaceFootprint


@dataclass(frozen=True)
class OverlaySceneResult:
    scene: trimesh.Scene
    slot_names: list[str]
    preview_colors: dict[str, tuple[int, int, int]]


def _pattern_to_surface_transform(footprint: SurfaceFootprint, pocket_depth_mm: float) -> np.ndarray:
    u = np.asarray(footprint.frame.u_axis, dtype=np.float64)
    v = np.asarray(footprint.frame.v_axis, dtype=np.float64)
    n = np.asarray(footprint.frame.normal, dtype=np.float64)
    origin = np.asarray(footprint.frame.origin, dtype=np.float64)
    min_x, min_y = footprint.bounds_min
    transform = np.eye(4)
    transform[:3, 0] = u
    transform[:3, 1] = v
    transform[:3, 2] = n
    transform[:3, 3] = origin + u * min_x + v * min_y - n * pocket_depth_mm
    return transform


def build_embedded_overlay_scene(
    *,
    base_mesh: trimesh.Trimesh,
    pattern_scene: trimesh.Scene,
    footprint: SurfaceFootprint,
    pocket_depth_mm: float,
    base_slot_name: str,
    base_color: tuple[int, int, int],
) -> OverlaySceneResult:
    if pocket_depth_mm <= 0:
        raise ModelSurfaceError("Pocket depth must be positive.")
    result_scene = trimesh.Scene()
    base_copy = base_mesh.copy()
    base_copy.metadata["name"] = base_slot_name
    result_scene.add_geometry(base_copy, geom_name=base_slot_name)

    transform = _pattern_to_surface_transform(footprint, pocket_depth_mm)
    slot_names = [base_slot_name]
    preview_colors: dict[str, tuple[int, int, int]] = {base_slot_name: base_color}
    for name, mesh in pattern_scene.geometry.items():
        if not isinstance(mesh, trimesh.Trimesh) or len(mesh.faces) == 0:
            continue
        mesh_copy = mesh.copy()
        mesh_copy.apply_transform(transform)
        mesh_copy.metadata["name"] = str(name)
        result_scene.add_geometry(mesh_copy, geom_name=str(name))
        slot_names.append(str(name))
        rgba = getattr(mesh_copy.visual, "face_colors", None)
        if rgba is not None and len(rgba):
            preview_colors[str(name)] = tuple(int(v) for v in rgba[0][:3])
    if len(slot_names) == 1:
        raise ModelSurfaceError("Overlay pattern scene contains no printable color meshes.")
    return OverlaySceneResult(result_scene, slot_names, preview_colors)
```

- [ ] **Step 4: Implement pipeline orchestration**

`core/model_surface/pipeline.py` calls `build_image_model_context(..., stop_after_step="S08")`, loads the base model, computes `pocket_depth_mm`, and returns an `OverlaySceneResult`. Start with direct embedding; add boolean pocket in Task 6 so this task stays testable.

```python
# core/model_surface/pipeline.py
from __future__ import annotations

from core.converter import build_image_model_context
from core.model_surface.assembly import OverlaySceneResult, build_embedded_overlay_scene
from core.model_surface.loader import load_model_surface_mesh
from core.model_surface.types import SurfaceFootprint


def build_surface_overlay_scene(
    *,
    model_path: str,
    artwork_image_path: str,
    lut_path: str,
    converter_params: dict,
    footprint: SurfaceFootprint,
    pocket_depth_mm: float,
) -> OverlaySceneResult:
    loaded = load_model_surface_mesh(model_path)
    ctx = build_image_model_context(
        stop_after_step="S08",
        image_path=artwork_image_path,
        lut_path=lut_path,
        **converter_params,
    )
    if ctx.get("error"):
        raise RuntimeError(str(ctx["error"]))
    return build_embedded_overlay_scene(
        base_mesh=loaded.mesh,
        pattern_scene=ctx["scene"],
        footprint=footprint,
        pocket_depth_mm=pocket_depth_mm,
        base_slot_name="surface_base",
        base_color=(245, 245, 245),
    )
```

- [ ] **Step 5: Run assembly tests**

Run:

```bash
./.venv/bin/python -m pytest tests/test_model_surface_assembly_unit.py -v
```

Expected: tests pass.

- [ ] **Step 6: Commit**

```bash
git add core/model_surface/assembly.py core/model_surface/pipeline.py tests/test_model_surface_assembly_unit.py
git commit -m "feat(model-surface): assemble overlay scene"
```

---

### Task 6: Pocket Boolean With Safe Failure

**Files:**
- Modify: `core/model_surface/assembly.py`
- Test: `tests/test_model_surface_boolean_unit.py`

- [ ] **Step 1: Write failing boolean tests**

```python
# tests/test_model_surface_boolean_unit.py
from __future__ import annotations

import trimesh

from core.model_surface.assembly import cut_surface_pocket
from core.model_surface.types import PlaneFrame, SurfaceFootprint


def test_cut_surface_pocket_preserves_outer_extents():
    base = trimesh.creation.box(extents=(20.0, 10.0, 3.0))
    footprint = SurfaceFootprint(
        frame=PlaneFrame((0.0, 0.0, 1.5), (0.0, 0.0, 1.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
        outer=((-8.0, -3.0), (8.0, -3.0), (8.0, 3.0), (-8.0, 3.0), (-8.0, -3.0)),
        holes=(),
        bounds_min=(-8.0, -3.0),
        bounds_max=(8.0, 3.0),
        bounds_width_mm=16.0,
        bounds_height_mm=6.0,
        area_mm2=96.0,
        hole_count=0,
    )

    cut = cut_surface_pocket(base, footprint, pocket_depth_mm=0.4)

    assert cut.extents[0] == base.extents[0]
    assert cut.extents[1] == base.extents[1]
    assert cut.extents[2] == base.extents[2]
    assert len(cut.faces) > 0
```

- [ ] **Step 2: Run tests and confirm failure**

Run:

```bash
./.venv/bin/python -m pytest tests/test_model_surface_boolean_unit.py -v
```

Expected: `cut_surface_pocket` does not exist.

- [ ] **Step 3: Implement pocket cutter**

Use `trimesh.creation.extrude_polygon` for the pocket cutter and `trimesh.boolean.difference(..., engine="manifold")`. If `manifold3d` fails, raise `ModelSurfaceError("model_surface_boolean_failed")`.

```python
def cut_surface_pocket(
    base_mesh: trimesh.Trimesh,
    footprint: SurfaceFootprint,
    *,
    pocket_depth_mm: float,
) -> trimesh.Trimesh:
    import shapely.geometry as sg

    outer = sg.LinearRing(footprint.outer)
    holes = [sg.LinearRing(hole) for hole in footprint.holes]
    polygon = sg.Polygon(outer, holes)
    if polygon.is_empty or polygon.area <= 0:
        raise ModelSurfaceError("Selected surface footprint is empty.")
    cutter = trimesh.creation.extrude_polygon(polygon, height=pocket_depth_mm)
    cutter.apply_transform(_pattern_to_surface_transform(footprint, 0.0))
    try:
        result = trimesh.boolean.difference([base_mesh, cutter], engine="manifold")
    except Exception as exc:
        raise ModelSurfaceError("model_surface_boolean_failed") from exc
    if result is None or len(result.faces) == 0:
        raise ModelSurfaceError("model_surface_boolean_failed")
    return result
```

Update `build_embedded_overlay_scene` to call `cut_surface_pocket`; keep direct base copy only when a caller passes `allow_uncut_base=True` in unit tests. Production calls must not set that flag.

- [ ] **Step 4: Run boolean tests**

Run:

```bash
./.venv/bin/python -m pytest tests/test_model_surface_boolean_unit.py -v
```

Expected: pass when `manifold3d` is installed in `.venv`.

- [ ] **Step 5: Run all core model surface tests**

Run:

```bash
./.venv/bin/python -m pytest tests/test_model_surface_loader_unit.py tests/test_model_surface_selection_unit.py tests/test_model_surface_artwork_unit.py tests/test_model_surface_assembly_unit.py tests/test_model_surface_boolean_unit.py -v
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add core/model_surface tests/test_model_surface_boolean_unit.py
git commit -m "feat(model-surface): cut surface pocket with manifold"
```

---

### Task 7: Backend API Endpoints And Session Attachment

**Files:**
- Create: `api/schemas/model_surface.py`
- Create: `api/routers/converter/model_surface.py`
- Modify: `api/routers/converter/__init__.py`
- Test: `tests/test_model_surface_api_unit.py`

- [ ] **Step 1: Write failing API tests**

```python
# tests/test_model_surface_api_unit.py
from __future__ import annotations

import trimesh
from fastapi.testclient import TestClient

from api.app import app


def test_model_surface_upload_returns_summary(tmp_path):
    model_path = tmp_path / "plate.stl"
    trimesh.creation.box(extents=(20.0, 10.0, 2.0)).export(model_path)
    client = TestClient(app)

    with model_path.open("rb") as fh:
        response = client.post(
            "/api/convert/model-surface/upload",
            files={"model": ("plate.stl", fh, "application/octet-stream")},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["model_file_id"]
    assert data["summary"]["extents_mm"] == [20.0, 10.0, 2.0]


def test_model_surface_upload_rejects_step_extension(tmp_path):
    path = tmp_path / "plate.step"
    path.write_text("bad", encoding="utf-8")
    client = TestClient(app)

    with path.open("rb") as fh:
        response = client.post(
            "/api/convert/model-surface/upload",
            files={"model": ("plate.step", fh, "application/octet-stream")},
        )

    assert response.status_code == 422


def test_model_surface_select_returns_footprint(tmp_path):
    model_path = tmp_path / "plate.stl"
    trimesh.creation.box(extents=(20.0, 10.0, 2.0)).export(model_path)
    client = TestClient(app)

    with model_path.open("rb") as fh:
        upload = client.post(
            "/api/convert/model-surface/upload",
            files={"model": ("plate.stl", fh, "application/octet-stream")},
        ).json()

    response = client.post(
        "/api/convert/model-surface/select",
        json={
            "model_file_id": upload["model_file_id"],
            "hit": {"face_index": 4},
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["selection"]["face_count"] >= 1
    assert data["footprint"]["area_mm2"] > 0
```

- [ ] **Step 2: Run tests and confirm failure**

Run:

```bash
./.venv/bin/python -m pytest tests/test_model_surface_api_unit.py -v
```

Expected: route returns 404.

- [ ] **Step 3: Add schemas**

```python
# api/schemas/model_surface.py
from __future__ import annotations

from pydantic import BaseModel, Field


class ModelSurfaceUploadResponse(BaseModel):
    status: str
    model_file_id: str
    summary: dict
    preview_glb_url: str | None = None
    warnings: list[str] = Field(default_factory=list)


class ModelSurfaceHitTriangle(BaseModel):
    face_index: int | None = None
    point: tuple[float, float, float] | None = None
    normal: tuple[float, float, float] | None = None
    vertices: tuple[
        tuple[float, float, float],
        tuple[float, float, float],
        tuple[float, float, float],
    ] | None = None


class ModelSurfaceSelectRequest(BaseModel):
    model_file_id: str
    hit: ModelSurfaceHitTriangle
    include_same_plane_disconnected: bool = False


class ModelSurfaceSelectResponse(BaseModel):
    status: str
    selection_id: str
    selection: dict
    footprint: dict
    warnings: list[str] = Field(default_factory=list)
```

- [ ] **Step 4: Implement upload route**

Save the upload to `TEMP_DIR`, load it through `load_model_surface_mesh`, register it in `FileRegistry` with a one-hour TTL, and return summary.

```python
# api/routers/converter/model_surface.py
from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from api.dependencies import get_file_registry
from api.file_registry import FileRegistry
from api.schemas.model_surface import ModelSurfaceUploadResponse
from config import TEMP_DIR
from core.model_surface.loader import load_model_surface_mesh
from core.model_surface.types import ModelSurfaceError

router = APIRouter(prefix="/model-surface")


@router.post("/upload", response_model=ModelSurfaceUploadResponse)
async def upload_model_surface(
    model: UploadFile = File(...),
    registry: FileRegistry = Depends(get_file_registry),
) -> ModelSurfaceUploadResponse:
    suffix = Path(model.filename or "").suffix.lower()
    if suffix not in {".stl", ".obj"}:
        raise HTTPException(status_code=422, detail="Only STL and OBJ model files are supported.")
    fd, temp_path = tempfile.mkstemp(suffix=suffix, dir=TEMP_DIR)
    os.close(fd)
    try:
        with open(temp_path, "wb") as fh:
            fh.write(await model.read())
        loaded = load_model_surface_mesh(temp_path)
    except ModelSurfaceError as exc:
        Path(temp_path).unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    file_id = registry.register_path(str(uuid.uuid4()), temp_path, ttl_seconds=3600)
    warnings = [loaded.summary.unit_warning] if loaded.summary.unit_warning else []
    return ModelSurfaceUploadResponse(
        status="ok",
        model_file_id=file_id,
        summary=loaded.summary.to_public_dict(),
        warnings=warnings,
    )
```

- [ ] **Step 5: Implement select route**

Add this endpoint to `api/routers/converter/model_surface.py`:

```python
from dataclasses import asdict
import uuid

from api.schemas.model_surface import ModelSurfaceSelectRequest, ModelSurfaceSelectResponse
from core.model_surface.footprint import build_surface_footprint
from core.model_surface.selection import select_planar_component


@router.post("/select", response_model=ModelSurfaceSelectResponse)
def select_model_surface(
    request: ModelSurfaceSelectRequest,
    registry: FileRegistry = Depends(get_file_registry),
) -> ModelSurfaceSelectResponse:
    resolved = registry.resolve(request.model_file_id)
    if resolved is None:
        raise HTTPException(status_code=404, detail="Uploaded model file is unavailable.")
    model_path, _filename = resolved
    try:
        loaded = load_model_surface_mesh(model_path)
        face_index = request.hit.face_index
        if face_index is None:
            raise ModelSurfaceError("A face_index is required for the first model-surface selection path.")
        selection = select_planar_component(loaded.mesh, int(face_index))
        footprint = build_surface_footprint(loaded.mesh, selection.face_indices)
    except ModelSurfaceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ModelSurfaceSelectResponse(
        status="ok",
        selection_id=str(uuid.uuid4()),
        selection=asdict(selection),
        footprint=asdict(footprint),
        warnings=[],
    )
```

- [ ] **Step 6: Include router**

In `api/routers/converter/__init__.py`:

```python
from .model_surface import router as model_surface_router
router.include_router(model_surface_router)
```

- [ ] **Step 7: Run API tests**

Run:

```bash
./.venv/bin/python -m pytest tests/test_model_surface_api_unit.py -v
```

Expected: pass.

- [ ] **Step 8: Commit**

```bash
git add api/schemas/model_surface.py api/routers/converter/model_surface.py api/routers/converter/__init__.py tests/test_model_surface_api_unit.py
git commit -m "feat(api): add model surface upload endpoint"
```

---

### Task 8: Preview Integration With Surface Artwork

**Files:**
- Modify: `api/schemas/converter.py`
- Modify: `api/routers/converter/preview.py`
- Modify: `api/routers/converter/model_surface.py`
- Test: `tests/test_model_surface_preview_integration_unit.py`

- [ ] **Step 1: Write failing preview integration test**

Patch the heavy preview worker so this test only validates request/session plumbing.

```python
# tests/test_model_surface_preview_integration_unit.py
from __future__ import annotations

import json

import numpy as np
import pytest
import trimesh
from fastapi.testclient import TestClient
from PIL import Image

from api.app import app


def test_preview_attaches_model_surface_config(monkeypatch, tmp_path):
    model_path = tmp_path / "plate.stl"
    image_path = tmp_path / "art.png"
    trimesh.creation.box(extents=(20.0, 10.0, 2.0)).export(model_path)
    Image.new("RGB", (40, 20), (255, 0, 0)).save(image_path)
    client = TestClient(app)

    with model_path.open("rb") as fh:
        upload = client.post(
            "/api/convert/model-surface/upload",
            files={"model": ("plate.stl", fh, "application/octet-stream")},
        ).json()

    def fake_worker(*args, **kwargs):
        preview_path = tmp_path / "preview.png"
        Image.new("RGBA", (20, 10), (255, 0, 0, 255)).save(preview_path)
        return {
            "preview_path": str(preview_path),
            "cache": {
                "matched_rgb": np.zeros((10, 20, 3), dtype=np.uint8),
                "mask_solid": np.ones((10, 20), dtype=bool),
                "quantized_image": np.zeros((10, 20, 3), dtype=np.uint8),
                "preview_rgba": np.zeros((10, 20, 4), dtype=np.uint8),
                "color_palette": [{"hex": "#ff0000"}],
                "target_w": 20,
                "target_h": 10,
            },
            "status_msg": "ok",
        }

    monkeypatch.setattr("api.routers.converter.preview.worker_generate_preview", fake_worker)

    with image_path.open("rb") as fh:
        response = client.post(
            "/api/convert/preview",
            files={"image": ("art.png", fh, "image/png")},
            data={
                "lut_name": "default",
                "target_width_mm": "20",
                "color_mode": "4-Color (RYBW)",
                "modeling_mode": "high-fidelity",
                "quantize_colors": "8",
                "enable_cleanup": "true",
                "surface_model_file_id": upload["model_file_id"],
                "surface_selection_json": json.dumps({"face_indices": [0, 1]}),
                "surface_footprint_json": json.dumps({
                    "bounds_width_mm": 20,
                    "bounds_height_mm": 10,
                    "outer": [[-10, -5], [10, -5], [10, 5], [-10, 5], [-10, -5]],
                    "holes": [],
                    "frame": {
                        "origin": [0, 0, 1],
                        "normal": [0, 0, 1],
                        "u_axis": [1, 0, 0],
                        "v_axis": [0, 1, 0],
                    },
                }),
                "surface_placement_json": json.dumps({"mode": "edge_to_edge"}),
            },
        )

    assert response.status_code == 200
    sid = response.json()["session_id"]
    from api.dependencies import session_store
    session = session_store.get(sid)
    assert session["surface_model_path"].endswith(".stl")
    assert session["surface_overlay_enabled"] is True
```

- [ ] **Step 2: Run test and confirm failure**

Run:

```bash
./.venv/bin/python -m pytest tests/test_model_surface_preview_integration_unit.py -v
```

Expected: preview ignores model-surface fields.

- [ ] **Step 3: Add optional preview fields**

In `api/schemas/converter.py`, add optional ignored-by-default model-surface form fields to `ConvertPreviewRequest`:

```python
surface_model_file_id: str | None = Field(None, description="Uploaded model file id for surface overlay")
surface_selection_json: str | None = Field(None, description="JSON surface selection payload")
surface_footprint_json: str | None = Field(None, description="JSON surface footprint payload")
surface_placement_json: str | None = Field(None, description="JSON surface placement payload")
```

Because `/preview` uses form parameters rather than a Pydantic body, also add matching `Form(None)` parameters to `convert_preview`.

- [ ] **Step 4: Attach model surface config in preview route**

In `api/routers/converter/preview.py`, after `temp_path = await ensure_png_tempfile(image)` and before worker dispatch:

```python
surface_config = _resolve_surface_preview_config(
    registry=registry,
    model_file_id=surface_model_file_id,
    selection_json=surface_selection_json,
    footprint_json=surface_footprint_json,
    placement_json=surface_placement_json,
    source_path=temp_path,
    sid=session_id,
    store=store,
)
if surface_config is not None:
    temp_path = surface_config["surface_artwork_path"]
    target_width_mm = surface_config["target_width_mm"]
```

Then store `surface_model_path`, `surface_selection`, `surface_footprint`, `surface_placement`, `surface_artwork_path`, and `surface_overlay_enabled=True` in the new session before returning `PreviewResponse`.

- [ ] **Step 5: Implement `_resolve_surface_preview_config`**

In `api/routers/converter/model_surface.py`, export a helper that:

1. Resolves `model_file_id` via `FileRegistry`.
2. Parses the JSON payloads with `json.loads`.
3. Rebuilds `SurfaceFootprint` and `SurfacePlacement`.
4. Calls `render_surface_artwork`.
5. Registers the rendered PNG as a session temp file.

- [ ] **Step 6: Run preview integration test**

Run:

```bash
./.venv/bin/python -m pytest tests/test_model_surface_preview_integration_unit.py -v
```

Expected: pass.

- [ ] **Step 7: Commit**

```bash
git add api/schemas/converter.py api/routers/converter/preview.py api/routers/converter/model_surface.py tests/test_model_surface_preview_integration_unit.py
git commit -m "feat(converter): attach surface artwork during preview"
```

---

### Task 9: Generate Integration And 3MF Export

**Files:**
- Modify: `api/workers/converter_workers.py`
- Modify: `api/routers/converter/generate.py`
- Modify: `api/schemas/responses.py`
- Test: `tests/test_model_surface_generate_unit.py`

- [ ] **Step 1: Write failing generate routing test**

```python
# tests/test_model_surface_generate_unit.py
from __future__ import annotations

import pytest

from api.routers.converter.generate import _should_use_model_surface_overlay


def test_should_use_model_surface_overlay_requires_session_flag():
    assert _should_use_model_surface_overlay({"surface_overlay_enabled": True}) is True
    assert _should_use_model_surface_overlay({"surface_overlay_enabled": False}) is False
    assert _should_use_model_surface_overlay({}) is False
```

- [ ] **Step 2: Run test and confirm failure**

Run:

```bash
./.venv/bin/python -m pytest tests/test_model_surface_generate_unit.py -v
```

Expected: helper does not exist.

- [ ] **Step 3: Add worker function**

In `api/workers/converter_workers.py`, add:

```python
def worker_generate_model_surface_overlay(
    image_path: str,
    lut_path: str,
    params: dict,
) -> dict:
    import os
    import tempfile

    from config import TEMP_DIR
    from core.model_surface.pipeline import build_surface_overlay_scene
    from utils.bambu_3mf_writer import export_scene_with_bambu_metadata

    overlay = build_surface_overlay_scene(
        model_path=params["surface_model_path"],
        artwork_image_path=image_path,
        lut_path=lut_path,
        converter_params=params["converter_params"],
        footprint=params["surface_footprint"],
        pocket_depth_mm=float(params["surface_pocket_depth_mm"]),
    )
    fd, out_path = tempfile.mkstemp(suffix=".3mf", dir=TEMP_DIR)
    os.close(fd)
    export_scene_with_bambu_metadata(
        scene=overlay.scene,
        output_path=out_path,
        slot_names=overlay.slot_names,
        preview_colors=overlay.preview_colors,
        project_slot_names=overlay.slot_names,
        color_mode=str(params.get("color_mode", "4-Color")),
        printer_id=str(params.get("printer_id", "bambu-h2d")),
        slicer=str(params.get("slicer", "BambuStudio")),
        nozzle_size=str(params.get("nozzle_size", "0.4")),
        cover_source=image_path,
        enable_base_layer_height_modifier=False,
    )
    return {"threemf_path": out_path, "glb_path": None, "status_msg": "Surface overlay model generated"}
```

- [ ] **Step 4: Route generate through overlay worker**

In `api/routers/converter/generate.py`, add:

```python
def _should_use_model_surface_overlay(session_data: dict) -> bool:
    return bool(session_data.get("surface_overlay_enabled"))
```

Before calling the worker, when this returns true, build `surface_params` from session data and call `worker_generate_model_surface_overlay` through the same `pool.submit` path. Preserve the existing FileRegistry registration and `GenerateResponse` handling.

- [ ] **Step 5: Run generate unit test**

Run:

```bash
./.venv/bin/python -m pytest tests/test_model_surface_generate_unit.py -v
```

Expected: pass.

- [ ] **Step 6: Run existing generate regression tests**

Run:

```bash
./.venv/bin/python -m pytest tests/test_converter_generate_unit.py tests/test_converter_generate_integration_unit.py -v
```

Expected: pass.

- [ ] **Step 7: Commit**

```bash
git add api/workers/converter_workers.py api/routers/converter/generate.py api/schemas/responses.py tests/test_model_surface_generate_unit.py
git commit -m "feat(converter): generate model surface overlay 3mf"
```

---

### Task 10: Frontend API Types And Store Slice

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/converter.ts`
- Modify: `frontend/src/stores/converter/store.ts`
- Test: `frontend/src/api/__tests__/modelSurface.test.ts`
- Test: `frontend/src/__tests__/converter-store-model-surface.test.ts`

- [ ] **Step 1: Write failing frontend API test**

```ts
// frontend/src/api/__tests__/modelSurface.test.ts
import { describe, expect, it, vi } from "vitest";
import apiClient from "../client";
import { uploadModelSurface } from "../converter";

vi.mock("../client", () => ({
  default: {
    post: vi.fn(),
  },
}));

describe("model surface API", () => {
  it("uploads a model as multipart form data", async () => {
    vi.mocked(apiClient.post).mockResolvedValueOnce({
      data: { status: "ok", model_file_id: "file-1", summary: {}, warnings: [] },
    });
    const file = new File(["solid"], "plate.stl", { type: "application/octet-stream" });

    const response = await uploadModelSurface(file);

    expect(response.model_file_id).toBe("file-1");
    expect(apiClient.post).toHaveBeenCalledWith(
      "/convert/model-surface/upload",
      expect.any(FormData),
      { timeout: 0 },
    );
  });
});
```

- [ ] **Step 2: Write failing store test**

```ts
// frontend/src/__tests__/converter-store-model-surface.test.ts
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useConverterStore } from "../stores/converter";

vi.mock("../api/converter", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/converter")>();
  return {
    ...actual,
    uploadModelSurface: vi.fn().mockResolvedValue({
      status: "ok",
      model_file_id: "model-1",
      summary: { extents_mm: [20, 10, 2] },
      warnings: [],
    }),
  };
});

describe("converter model surface store", () => {
  beforeEach(() => {
    useConverterStore.setState(useConverterStore.getInitialState(), true);
  });

  it("stores uploaded model metadata", async () => {
    const file = new File(["solid"], "plate.stl");

    await useConverterStore.getState().setSurfaceModelFile(file);

    const state = useConverterStore.getState();
    expect(state.surfaceModelFile).toBe(file);
    expect(state.surfaceModelFileId).toBe("model-1");
    expect(state.surfaceModelSummary?.extents_mm).toEqual([20, 10, 2]);
  });
});
```

- [ ] **Step 3: Run tests and confirm failure**

Run:

```bash
python scripts/run_vitest.py run frontend/src/api/__tests__/modelSurface.test.ts frontend/src/__tests__/converter-store-model-surface.test.ts
```

Expected: tests fail because API/store actions do not exist.

- [ ] **Step 4: Add API types and functions**

Add to `frontend/src/api/types.ts`:

```ts
export type SurfaceEdgeMode = "edge_to_edge" | "inset";

export interface ModelSurfaceUploadResponse {
  status: string;
  model_file_id: string;
  summary: Record<string, unknown>;
  preview_glb_url?: string | null;
  warnings: string[];
}

export interface ModelSurfacePlacement {
  mode: SurfaceEdgeMode;
  offset_x_mm: number;
  offset_y_mm: number;
  scale: number;
  rotation_deg: number;
  inset_mm: number;
}

export interface ModelSurfaceHitTriangle {
  face_index?: number | null;
  point?: [number, number, number] | null;
  normal?: [number, number, number] | null;
  vertices?: [[number, number, number], [number, number, number], [number, number, number]] | null;
}

export interface ModelSurfaceSelectResponse {
  status: string;
  selection_id: string;
  selection: Record<string, unknown>;
  footprint: Record<string, unknown>;
  warnings: string[];
}
```

Add to `frontend/src/api/converter.ts`:

```ts
export async function uploadModelSurface(file: File): Promise<ModelSurfaceUploadResponse> {
  const fd = new FormData();
  fd.append("model", file);
  const response = await apiClient.post<ModelSurfaceUploadResponse>(
    "/convert/model-surface/upload",
    fd,
    { timeout: 0 },
  );
  return response.data;
}

export async function selectModelSurface(
  modelFileId: string,
  hit: ModelSurfaceHitTriangle,
): Promise<ModelSurfaceSelectResponse> {
  const response = await apiClient.post<ModelSurfaceSelectResponse>(
    "/convert/model-surface/select",
    { model_file_id: modelFileId, hit },
    { timeout: 0 },
  );
  return response.data;
}
```

- [ ] **Step 5: Add store state and action**

Add state fields to `ConverterState`:

```ts
surfaceModelFile: File | null;
surfaceModelFileId: string | null;
surfaceModelSummary: Record<string, unknown> | null;
surfaceModelWarnings: string[];
surfaceOverlayEnabled: boolean;
surfacePlacement: ModelSurfacePlacement;
surfaceSelection: Record<string, unknown> | null;
surfaceFootprint: Record<string, unknown> | null;
```

Add action to `ConverterActions`:

```ts
setSurfaceModelFile: (file: File | null) => Promise<void>;
selectSurfaceFace: (hit: ModelSurfaceHitTriangle) => Promise<void>;
```

Default state:

```ts
surfaceModelFile: null,
surfaceModelFileId: null,
surfaceModelSummary: null,
surfaceModelWarnings: [],
surfaceOverlayEnabled: false,
surfacePlacement: {
  mode: "edge_to_edge",
  offset_x_mm: 0,
  offset_y_mm: 0,
  scale: 1,
  rotation_deg: 0,
  inset_mm: 0.2,
},
surfaceSelection: null,
surfaceFootprint: null,
```

Action:

```ts
setSurfaceModelFile: async (file: File | null) => {
  if (!file) {
    set({
      surfaceModelFile: null,
      surfaceModelFileId: null,
      surfaceModelSummary: null,
      surfaceModelWarnings: [],
      surfaceOverlayEnabled: false,
    });
    return;
  }
  set({ surfaceModelFile: file, surfaceModelWarnings: [], error: null });
  try {
    const response = await apiUploadModelSurface(file);
    set({
      surfaceModelFileId: response.model_file_id,
      surfaceModelSummary: response.summary,
      surfaceModelWarnings: response.warnings ?? [],
      surfaceOverlayEnabled: true,
    });
  } catch (err) {
    set({
      surfaceModelFile: null,
      surfaceModelFileId: null,
      surfaceModelSummary: null,
      surfaceOverlayEnabled: false,
      error: visibleConverterError(err, "模型上传失败"),
    });
  }
},
```

Add the selection action:

```ts
selectSurfaceFace: async (hit: ModelSurfaceHitTriangle) => {
  const state = _get();
  if (!state.surfaceModelFileId) {
    set({ error: tRuntime("model_surface_error_no_model") });
    return;
  }
  try {
    const response = await apiSelectModelSurface(state.surfaceModelFileId, hit);
    set({
      surfaceSelection: response.selection,
      surfaceFootprint: response.footprint,
      surfaceModelWarnings: response.warnings ?? [],
      error: null,
    });
  } catch (err) {
    set({ error: visibleConverterError(err, tRuntime("model_surface_error_select_failed")) });
  }
},
```

- [ ] **Step 6: Run frontend tests**

Run:

```bash
python scripts/run_vitest.py run frontend/src/api/__tests__/modelSurface.test.ts frontend/src/__tests__/converter-store-model-surface.test.ts
```

Expected: pass.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/api/types.ts frontend/src/api/converter.ts frontend/src/stores/converter/store.ts frontend/src/api/__tests__/modelSurface.test.ts frontend/src/__tests__/converter-store-model-surface.test.ts
git commit -m "feat(frontend): add model surface state"
```

---

### Task 11: Frontend Upload Controls And Viewer Selection

**Files:**
- Create: `frontend/src/components/modelSurface/ModelSurfacePanel.tsx`
- Create: `frontend/src/components/modelSurface/ModelSurfaceViewer.tsx`
- Modify: `frontend/src/components/sections/BasicSettings.tsx`
- Modify: `frontend/src/components/Scene3D.tsx`
- Modify: `frontend/src/i18n/translations.ts`
- Test: `frontend/src/__tests__/model-surface-panel.test.tsx`

- [ ] **Step 1: Write failing component test**

```tsx
// frontend/src/__tests__/model-surface-panel.test.tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ModelSurfacePanel from "../components/modelSurface/ModelSurfacePanel";

describe("ModelSurfacePanel", () => {
  it("accepts STL files", () => {
    const onModelFile = vi.fn();
    render(
      <ModelSurfacePanel
        modelFile={null}
        summary={null}
        warnings={[]}
        onModelFile={onModelFile}
      />,
    );
    const input = screen.getByLabelText(/STL|OBJ/i) as HTMLInputElement;
    const file = new File(["solid"], "plate.stl");

    fireEvent.change(input, { target: { files: [file] } });

    expect(onModelFile).toHaveBeenCalledWith(file);
  });
});
```

- [ ] **Step 2: Run test and confirm failure**

Run:

```bash
python scripts/run_vitest.py run frontend/src/__tests__/model-surface-panel.test.tsx
```

Expected: component does not exist.

- [ ] **Step 3: Implement `ModelSurfacePanel`**

Use existing token classes and no raw hard-coded white/black backgrounds.

```tsx
// frontend/src/components/modelSurface/ModelSurfacePanel.tsx
import { useRef } from "react";
import { useI18n } from "../../i18n/context";

interface Props {
  modelFile: File | null;
  summary: Record<string, unknown> | null;
  warnings: string[];
  onModelFile: (file: File | null) => void;
  hasSelection?: boolean;
}

export default function ModelSurfacePanel({ modelFile, summary, warnings, onModelFile, hasSelection = false }: Props) {
  const { t } = useI18n();
  const inputRef = useRef<HTMLInputElement>(null);
  return (
    <section className="flex flex-col gap-2 rounded-2xl border border-[color:var(--surface-outline)] p-3">
      <div className="flex items-center justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-50">
            {t("model_surface_title")}
          </h3>
          <p className="text-xs text-slate-500 dark:text-slate-400">
            {modelFile?.name ?? t("model_surface_empty")}
          </p>
        </div>
        <button
          type="button"
          className="rounded-xl border border-[color:var(--surface-outline)] px-3 py-2 text-xs"
          onClick={() => inputRef.current?.click()}
        >
          {modelFile ? t("model_surface_replace") : t("model_surface_upload")}
        </button>
      </div>
      <input
        ref={inputRef}
        aria-label={t("model_surface_upload_aria")}
        type="file"
        accept=".stl,.obj"
        className="hidden"
        onChange={(event) => onModelFile(event.target.files?.[0] ?? null)}
      />
      {summary?.["extents_mm"] && (
        <p className="text-xs text-slate-500 dark:text-slate-400">
          {t("model_surface_size")}: {String(summary["extents_mm"])}
        </p>
      )}
      {warnings.map((warning) => (
        <p key={warning} className="text-xs text-yellow-600 dark:text-yellow-400">
          {t(`model_surface_warning_${warning}`)}
        </p>
      ))}
      {modelFile && (
        <p className="text-xs text-slate-500 dark:text-slate-400">
          {hasSelection ? t("model_surface_selected") : t("model_surface_select_hint")}
        </p>
      )}
    </section>
  );
}
```

- [ ] **Step 4: Add i18n keys**

Add these keys to `frontend/src/i18n/translations.ts`:

```ts
model_surface_title: { zh: "模型覆面", en: "Model Surface" },
model_surface_empty: { zh: "上传 STL/OBJ 模型后可选择覆面", en: "Upload an STL/OBJ model to select a surface" },
model_surface_upload: { zh: "上传模型", en: "Upload model" },
model_surface_replace: { zh: "替换模型", en: "Replace model" },
model_surface_upload_aria: { zh: "上传 STL 或 OBJ 模型", en: "Upload STL or OBJ model" },
model_surface_size: { zh: "模型尺寸", en: "Model size" },
model_surface_selected: { zh: "已选择覆面区域", en: "Surface selected" },
model_surface_select_hint: { zh: "在 3D 预览中点击一个平面", en: "Click a flat face in the 3D preview" },
model_surface_error_no_model: { zh: "请先上传模型。", en: "Upload a model first." },
model_surface_error_select_failed: { zh: "选面失败，请点击更大的平整区域。", en: "Surface selection failed. Click a larger flat area." },
model_surface_warning_model_dimensions_look_like_inches: { zh: "模型尺寸看起来像英寸单位，请确认是否需要缩放。", en: "The model dimensions look like inches. Check whether scaling is needed." },
model_surface_warning_model_dimensions_look_too_large_for_mm: { zh: "模型尺寸过大，请确认单位是否为毫米。", en: "The model dimensions look too large for millimeters. Check the unit." },
```

- [ ] **Step 5: Wire panel into `BasicSettings`**

Import `ModelSurfacePanel`, read store fields, and place it below `UnifiedUploader`.

```tsx
<ModelSurfacePanel
  modelFile={surfaceModelFile}
  summary={surfaceModelSummary}
  warnings={surfaceModelWarnings}
  onModelFile={(file) => void setSurfaceModelFile(file)}
/>
```

- [ ] **Step 6: Implement `ModelSurfaceViewer` selection**

Load STL/OBJ through Three.js example loaders, render the mesh with a neutral material, and call `selectSurfaceFace` on mesh click.

```tsx
// frontend/src/components/modelSurface/ModelSurfaceViewer.tsx
import { useEffect, useState } from "react";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";
import { OBJLoader } from "three/examples/jsm/loaders/OBJLoader.js";
import * as THREE from "three";

interface Props {
  file: File;
  onFaceHit: (hit: { face_index: number | null; point: [number, number, number]; normal: [number, number, number] }) => void;
}

export default function ModelSurfaceViewer({ file, onFaceHit }: Props) {
  const [object, setObject] = useState<THREE.Object3D | null>(null);

  useEffect(() => {
    let cancelled = false;
    file.arrayBuffer().then((buffer) => {
      if (cancelled) return;
      const lower = file.name.toLowerCase();
      if (lower.endsWith(".stl")) {
        const geometry = new STLLoader().parse(buffer);
        geometry.computeVertexNormals();
        const mesh = new THREE.Mesh(
          geometry,
          new THREE.MeshStandardMaterial({ color: 0xd8dbe2, roughness: 0.75 }),
        );
        setObject(mesh);
        return;
      }
      const text = new TextDecoder().decode(buffer);
      setObject(new OBJLoader().parse(text));
    });
    return () => {
      cancelled = true;
    };
  }, [file]);

  if (!object) return null;

  return (
    <primitive
      object={object}
      onClick={(event: any) => {
        event.stopPropagation();
        const normal = event.face?.normal ?? new THREE.Vector3(0, 0, 1);
        onFaceHit({
          face_index: event.faceIndex ?? null,
          point: [event.point.x, event.point.y, event.point.z],
          normal: [normal.x, normal.y, normal.z],
        });
      }}
    />
  );
}
```

- [ ] **Step 7: Run component tests and i18n completeness**

Run:

```bash
python scripts/run_vitest.py run frontend/src/__tests__/model-surface-panel.test.tsx frontend/src/__tests__/i18n-keys-completeness.test.ts
```

Expected: pass.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/modelSurface frontend/src/components/sections/BasicSettings.tsx frontend/src/components/Scene3D.tsx frontend/src/i18n/translations.ts frontend/src/__tests__/model-surface-panel.test.tsx
git commit -m "feat(frontend): add model surface controls"
```

---

### Task 12: Preview And Generate Payload Wiring

**Files:**
- Modify: `frontend/src/stores/converter/store.ts`
- Modify: `frontend/src/api/types.ts`
- Test: `frontend/src/__tests__/converter-store-model-surface-payload.test.ts`

- [ ] **Step 1: Write failing payload test**

```ts
// frontend/src/__tests__/converter-store-model-surface-payload.test.ts
import { beforeEach, describe, expect, it, vi } from "vitest";
import { convertPreview } from "../api/converter";
import { useConverterStore } from "../stores/converter";

vi.mock("../api/converter", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/converter")>();
  return {
    ...actual,
    convertPreview: vi.fn().mockResolvedValue({
      session_id: "sid-1",
      preview_url: "/api/files/preview",
      palette: [],
      dimensions: { width: 10, height: 10 },
      warnings: [],
    }),
  };
});

describe("model surface preview payload", () => {
  beforeEach(() => {
    useConverterStore.setState(useConverterStore.getInitialState(), true);
  });

  it("includes model surface fields when enabled", async () => {
    useConverterStore.setState({
      imageFile: new File(["png"], "art.png"),
      surfaceOverlayEnabled: true,
      surfaceModelFileId: "model-1",
      surfaceSelection: { face_indices: [0, 1] },
      surfaceFootprint: { bounds_width_mm: 20, bounds_height_mm: 10 },
    } as Partial<ReturnType<typeof useConverterStore.getState>>);

    await useConverterStore.getState().submitPreview();

    expect(convertPreview).toHaveBeenCalledWith(
      expect.any(File),
      expect.objectContaining({
        surface_model_file_id: "model-1",
        surface_selection_json: expect.any(String),
        surface_footprint_json: expect.any(String),
        surface_placement_json: expect.any(String),
      }),
      expect.any(AbortSignal),
    );
  });
});
```

- [ ] **Step 2: Run test and confirm failure**

Run:

```bash
python scripts/run_vitest.py run frontend/src/__tests__/converter-store-model-surface-payload.test.ts
```

Expected: store does not send model-surface fields.

- [ ] **Step 3: Add state fields**

Add:

```ts
surfaceSelection: Record<string, unknown> | null;
surfaceFootprint: Record<string, unknown> | null;
setSurfaceSelection: (selection: Record<string, unknown>, footprint: Record<string, unknown>) => void;
updateSurfacePlacement: (updates: Partial<ModelSurfacePlacement>) => void;
```

- [ ] **Step 4: Include surface fields in preview params**

In `submitPreview`, after `previewParams` is built:

```ts
const surfaceParams =
  state.surfaceOverlayEnabled &&
  state.surfaceModelFileId &&
  state.surfaceSelection &&
  state.surfaceFootprint
    ? {
        surface_model_file_id: state.surfaceModelFileId,
        surface_selection_json: JSON.stringify(state.surfaceSelection),
        surface_footprint_json: JSON.stringify(state.surfaceFootprint),
        surface_placement_json: JSON.stringify(state.surfacePlacement),
      }
    : {};
```

Pass `{ ...previewParams, ...surfaceParams }` to `apiConvertPreview`.

- [ ] **Step 5: Include surface state reset rules**

When image changes, keep model file but clear `surfaceSelection` and `surfaceFootprint` because placement must be reconfirmed for the new artwork. When model changes, clear both and set `surfaceOverlayEnabled` based on successful upload.

- [ ] **Step 6: Run payload test**

Run:

```bash
python scripts/run_vitest.py run frontend/src/__tests__/converter-store-model-surface-payload.test.ts
```

Expected: pass.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/stores/converter/store.ts frontend/src/api/types.ts frontend/src/__tests__/converter-store-model-surface-payload.test.ts
git commit -m "feat(frontend): send model surface preview payload"
```

---

### Task 13: Automated Regression Gates

**Files:**
- Modify only if tests reveal real failures in touched files.

- [ ] **Step 1: Run backend model-surface tests**

Run:

```bash
./.venv/bin/python -m pytest tests/test_model_surface_loader_unit.py tests/test_model_surface_selection_unit.py tests/test_model_surface_artwork_unit.py tests/test_model_surface_assembly_unit.py tests/test_model_surface_boolean_unit.py tests/test_model_surface_api_unit.py tests/test_model_surface_preview_integration_unit.py tests/test_model_surface_generate_unit.py -v
```

Expected: pass.

- [ ] **Step 2: Run focused converter regression tests**

Run:

```bash
./.venv/bin/python -m pytest tests/test_converter_preview_unit.py tests/test_converter_generate_unit.py tests/test_converter_generate_integration_unit.py tests/test_s09_export_3mf_unit.py tests/test_bambu_3mf_writer_unit.py -v
```

Expected: pass.

- [ ] **Step 3: Run frontend model-surface tests**

Run:

```bash
python scripts/run_vitest.py run frontend/src/api/__tests__/modelSurface.test.ts frontend/src/__tests__/converter-store-model-surface.test.ts frontend/src/__tests__/converter-store-model-surface-payload.test.ts frontend/src/__tests__/model-surface-panel.test.tsx frontend/src/__tests__/i18n-keys-completeness.test.ts
```

Expected: pass.

- [ ] **Step 4: Run frontend build**

Run:

```bash
cd frontend && pnpm build
```

Expected: TypeScript build passes.

- [ ] **Step 5: Commit fixes from regression pass**

If any test-driven fix was made:

```bash
git add <changed-files>
git commit -m "fix(model-surface): stabilize overlay regressions"
```

If no files changed, do not create an empty commit.

---

### Task 14: Real Human Workflow Verification

**Files:**
- No source edits unless a real bug is found.
- Use Chrome plugin for browser workflow.
- Use Computer Use plugin for BambuStudio and OrcaSlicer checks.

- [ ] **Step 1: Start clean Lumina servers**

Run:

```bash
./.venv/bin/python start_all.py --kill
./.venv/bin/python start_all.py
```

Expected: backend on `http://localhost:8000`, frontend on `http://localhost:5174` or the port reported by Vite. Keep the server session id so it can be stopped before final completion.

- [ ] **Step 2: Open app in Chrome**

Use Chrome automation to open the frontend URL. Verify the main converter loads, no blank page, no immediate console error blocking interaction.

- [ ] **Step 3: Run bitmap workflow like a user**

Actions:

1. Upload `/Users/min/Downloads/9DCCD9AB393A882ECB61703FF607F690.jpg`.
2. Upload `/Users/min/Downloads/IKEA++pegboard_stls/obj_10_大间隙.STEP.stl`.
3. Select the top flat face of the pegboard.
4. Click “铺满面”.
5. Run preview.
6. Keep default 4-color RYBW or a ready material source.
7. Generate 3MF.
8. Download the generated 3MF.

Expected:

- The app does not enter batch mode when one image and one model are present.
- The model upload summary reports about `200 x 200 x 5 mm`.
- Face selection is visibly highlighted.
- Preview uses the surface aspect, not the original JPG aspect.
- Generate returns a download URL.

- [ ] **Step 4: Run SVG workflow like a user**

Actions:

1. Replace artwork with `/Users/min/Downloads/945695877_20260622_232544_vector.svg`.
2. Keep the same model.
3. Select the same top face.
4. Use “完整图片”.
5. Run preview.
6. Generate 3MF.
7. Download the generated 3MF.

Expected:

- SVG is accepted as artwork.
- The rendered surface artwork is not blank.
- Generate returns a second download URL.

- [ ] **Step 5: Inspect generated 3MFs with BambuStudio**

Use Computer Use to open each 3MF in BambuStudio.

Check:

- Model dimensions stay `200 x 200 x 5 mm`.
- Holes remain open.
- Color parts are visible on the top surface.
- Material slots are present and named clearly.
- No obvious floating parts above the board.
- No import error dialog.

- [ ] **Step 6: Inspect generated 3MFs with OrcaSlicer**

Use Computer Use to open each 3MF in OrcaSlicer.

Check:

- Import succeeds.
- Object list contains base and color objects.
- Plate bounds are plausible.
- Slice preview does not show filled pegboard holes.

- [ ] **Step 7: Iterate on real bugs**

For each bug found:

1. Write the smallest reproducing automated test.
2. Run the test and confirm it fails.
3. Patch the code.
4. Run the focused test and the relevant workflow again.
5. Commit with `fix(model-surface): <specific issue>`.

Bug categories that must be fixed before completion:

- App cannot complete preview/generate with the provided STL and either provided artwork.
- Exported 3MF cannot open in BambuStudio or OrcaSlicer.
- Holes are filled.
- Top surface dimensions or model thickness change.
- UI loses the selected model or artwork unexpectedly.
- API returns raw tracebacks or ambiguous generic errors for common user mistakes.

- [ ] **Step 8: Stop local servers**

Run:

```bash
./.venv/bin/python start_all.py --kill
```

Expected: no leftover `api_server.py`, `start_all.py`, `vite`, `vitest`, or project-scoped node helper processes.

---

## Plan Self-Review

- Spec coverage: model upload, image/SVG upload, planar face selection, placement controls, fit modes, edge/inset modes, reuse of existing color pipeline, 3MF export, dependency boundaries, and Bambu/Orca manual verification are covered.
- Scope control: first implementation supports one selected planar surface. Multiple faces, 3MF model import, and curve wrapping are not part of this plan.
- Dependency boundary: no GPL/AGPL dependency is introduced. BambuStudio and OrcaSlicer are used only for output inspection.
- Risk: full pocket boolean depends on `manifold3d` and model cleanliness. The provided STL becomes watertight with `trimesh` processing, so it is a valid manual verification target.
