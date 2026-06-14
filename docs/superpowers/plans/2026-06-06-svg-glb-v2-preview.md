# SVG GLB V2 Preview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 SVG 预览 GLB 在本地可选择走 V2 mesh 生成链路，提高常规 SVG 3D 预览模型生成速度，同时保留描边、拼图、钥匙扣、冰箱贴、单双面、5 色扩展、底板和前端命名契约，并在任何不确定情况整次回退 V1。

**Architecture:** 新增一个聚焦模块 `core/pipeline/vector_glb_preview.py`，承载 SVG GLB kernel 选择、`VectorPreviewPart` 描述层、V1 exporter、V2 exporter 和 fallback 调度；`core/pipeline/vector_branch.py` 只负责把现有业务规则处理后的 `analysis/scene/ctx` 交给该模块。第一版 V2 只处理能从业务后 2D footprint 无损表达的颜色层、普通底板和普通 Outline；冰箱贴凹槽、涂层、未知辅助 mesh 或 parity 失败时整次回退 V1。

**Tech Stack:** Python, `dataclasses`, `trimesh`, `numpy`, `shapely`, existing `core.pipeline.s11_glb_preview._build_color_extruded_mesh_v2`, pytest, optional Vitest contract tests through `python scripts/run_vitest.py`.

---

## Scope And Safety

Before implementation, remind the user to register this planned change in the online tracking spreadsheet for traceability.

Do not touch:

- `materials/**`
- local runtime material volume, including the configured `<runtime-root>`
- Docker volumes or image pruning
- protected branches `dev-refactor` / `main`

The stale draft `tests/test_vector_glb_v2_kernel_unit.py` currently describes a cached segmented-GLB direction. Replace those tests with descriptor-layer tests; do not keep the old "use cached segmented pipeline directly" assertion because it bypasses SVG vector business rules.

## File Structure

- Create: `core/pipeline/vector_glb_preview.py`
  - Owns vector GLB preview descriptors, resolver, V1 exporter, V2 exporter, V1 fallback, and profile metadata.
- Modify: `core/pipeline/vector_branch.py`
  - Replaces the inline GLB export block with a call into `vector_glb_preview.export_vector_glb_preview`.
  - Passes `analysis`, `scene`, `ctx`, `structure_mode`, `color_mode`, `preview_colors`, and `slot_list`.
- Rewrite: `tests/test_vector_glb_v2_kernel_unit.py`
  - Focused unit tests for resolver, descriptor building, V1 parity, V2 success, V2 fallback, unsupported mode fallback.
- Add: `tests/test_vector_glb_v2_parity_unit.py`
  - Synthetic parity tests for single-sided, double-sided, 5-color, backing, Outline, duplicate colors, and unsupported fridge fallback.
- Modify only if needed: `frontend/src/__tests__/Scene3D.test.tsx`
  - Contract guard that `previewGlbUrl` remains the model source and overlay props still flow through.
- Modify only after backend tests pass: `scripts/docker_local_deploy.ps1`
  - Preserve existing runtime bind mounts and add local-only `LUMINA_VECTOR_GLB_KERNEL=v2`.

---

### Task 1: Cleanly Replace The Old Test Draft With Kernel Resolver Tests

**Files:**
- Rewrite: `tests/test_vector_glb_v2_kernel_unit.py`
- Create: `core/pipeline/vector_glb_preview.py`

- [ ] **Step 1: Replace the test draft with resolver-focused failing tests**

Write this initial file:

```python
"""Unit tests for SVG/vector GLB preview V2 descriptor dispatch."""

from __future__ import annotations

import logging

from core.pipeline import vector_glb_preview


def _record_events(caplog) -> list[str | None]:
    return [getattr(record, "event", None) for record in caplog.records]


def test_vector_glb_kernel_defaults_to_v1(monkeypatch) -> None:
    monkeypatch.delenv("LUMINA_VECTOR_GLB_KERNEL", raising=False)

    assert vector_glb_preview.resolve_vector_glb_kernel_choice() == "trimesh_v1"


def test_vector_glb_kernel_accepts_v2_aliases(monkeypatch) -> None:
    for value in ("v2", "V2", "rasterio_manifold3d", "rasterio+manifold3d"):
        monkeypatch.setenv("LUMINA_VECTOR_GLB_KERNEL", value)

        assert (
            vector_glb_preview.resolve_vector_glb_kernel_choice()
            == "rasterio_manifold3d"
        )


def test_vector_glb_kernel_unknown_value_warns_and_falls_back(
    monkeypatch,
    caplog,
) -> None:
    caplog.set_level(logging.WARNING, logger="lumina.core.pipeline.vector_glb_preview")
    monkeypatch.setenv("LUMINA_VECTOR_GLB_KERNEL", "bad-value")

    assert vector_glb_preview.resolve_vector_glb_kernel_choice() == "trimesh_v1"

    assert "vector_glb_kernel_unknown_value" in _record_events(caplog)
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```powershell
python -m pytest tests/test_vector_glb_v2_kernel_unit.py -v
```

Expected: FAIL with `ImportError: cannot import name 'vector_glb_preview'`.

- [ ] **Step 3: Create the module with the resolver only**

Create `core/pipeline/vector_glb_preview.py`:

```python
"""SVG/vector GLB preview exporters.

This module keeps vector GLB preview export separate from the large
``vector_branch`` orchestration file. V1 remains the default exporter; V2 is
an opt-in local path selected by ``LUMINA_VECTOR_GLB_KERNEL``.

SVG/vector GLB 预览导出模块。V1 默认保持不变；V2 通过
``LUMINA_VECTOR_GLB_KERNEL`` 本地开启，并且必须能回退 V1。
"""

from __future__ import annotations

import os

from api.structured_logging import get_logger


log = get_logger(__name__)

_VECTOR_GLB_KERNEL_ENV_VAR = "LUMINA_VECTOR_GLB_KERNEL"


def resolve_vector_glb_kernel_choice() -> str:
    """Return the requested SVG GLB kernel.

    Returns:
        ``"trimesh_v1"`` for the current default path, or
        ``"rasterio_manifold3d"`` for the opt-in V2 path.

    返回当前 SVG GLB kernel 选择：默认 ``trimesh_v1``，本地开启时返回
    ``rasterio_manifold3d``。
    """

    raw = (os.environ.get(_VECTOR_GLB_KERNEL_ENV_VAR) or "").strip().lower()
    if raw in {"", "v1", "trimesh", "trimesh_v1"}:
        return "trimesh_v1"
    if raw in {"v2", "rasterio_manifold3d", "rasterio+manifold3d"}:
        return "rasterio_manifold3d"
    log.warning(
        "Unknown LUMINA_VECTOR_GLB_KERNEL value, falling back to V1",
        extra={
            "event": "vector_glb_kernel_unknown_value",
            "value": raw,
            "error_type": "ValueError",
            "fallback_kernel": "trimesh_v1",
        },
    )
    return "trimesh_v1"
```

- [ ] **Step 4: Run the resolver tests**

Run:

```powershell
python -m pytest tests/test_vector_glb_v2_kernel_unit.py -v
```

Expected: PASS.

---

### Task 2: Define The Descriptor Data Model And Naming Contract

**Files:**
- Modify: `core/pipeline/vector_glb_preview.py`
- Modify: `tests/test_vector_glb_v2_kernel_unit.py`

- [ ] **Step 1: Add failing descriptor naming tests**

Append these tests:

```python
import numpy as np
import pytest
import trimesh
from shapely.geometry import box


def test_make_export_name_keeps_color_prefix_and_suffixes_duplicates() -> None:
    seen: set[str] = set()

    first = vector_glb_preview.make_vector_glb_export_name(
        source_name="Red",
        role="color",
        rgba=(255, 0, 0, 255),
        seen_names=seen,
    )
    second = vector_glb_preview.make_vector_glb_export_name(
        source_name="AlsoRed",
        role="color",
        rgba=(255, 0, 0, 255),
        seen_names=seen,
    )

    assert first == "color_ff0000"
    assert second == "color_ff0000_1"


def test_make_export_name_keeps_non_color_roles_out_of_color_prefix() -> None:
    seen: set[str] = set()

    assert vector_glb_preview.make_vector_glb_export_name(
        source_name="Board",
        role="backing",
        rgba=(255, 255, 255, 255),
        seen_names=seen,
    ) == "backing_plate"

    assert vector_glb_preview.make_vector_glb_export_name(
        source_name="Outline",
        role="outline",
        rgba=(255, 255, 255, 255),
        seen_names=seen,
    ) == "Outline"
```

- [ ] **Step 2: Run the descriptor naming tests**

Run:

```powershell
python -m pytest tests/test_vector_glb_v2_kernel_unit.py::test_make_export_name_keeps_color_prefix_and_suffixes_duplicates tests/test_vector_glb_v2_kernel_unit.py::test_make_export_name_keeps_non_color_roles_out_of_color_prefix -v
```

Expected: FAIL because the descriptor helpers do not exist.

- [ ] **Step 3: Add descriptor dataclasses and naming helpers**

Add this to `core/pipeline/vector_glb_preview.py` after the resolver:

```python
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import trimesh
from shapely.geometry.base import BaseGeometry


VectorPreviewRole = Literal["color", "backing", "outline", "auxiliary"]


@dataclass(frozen=True)
class VectorPreviewExtrusion:
    """One 2D footprint extrusion in display-space millimetres.

    一段显示坐标系中的 2D footprint + Z 范围挤出描述。
    """

    footprint: BaseGeometry
    z_min: float
    z_max: float


@dataclass(frozen=True)
class VectorPreviewPart:
    """One named GLB preview part consumed by V1 and V2 exporters.

    V1 可以使用 ``fallback_mesh``；V2 优先使用 ``extrusions``。
    """

    source_name: str
    export_name: str
    role: VectorPreviewRole
    rgba: tuple[int, int, int, int]
    is_recolorable: bool
    extrusions: tuple[VectorPreviewExtrusion, ...] = field(default_factory=tuple)
    fallback_mesh: trimesh.Trimesh | None = None


def coerce_preview_rgba(value: object) -> tuple[int, int, int, int] | None:
    """Return a safe RGBA tuple, accepting 0-1 or 0-255 input."""

    if value is None:
        return None
    try:
        rgba = np.asarray(value, dtype=float).reshape(-1)
    except (TypeError, ValueError):
        return None
    if rgba.size < 3:
        return None
    if rgba.max(initial=0.0) <= 1.0:
        rgba = rgba * 255.0
    if rgba.size < 4:
        rgba = np.concatenate([rgba[:3], np.array([255.0])])
    safe = np.clip(rgba[:4], 0, 255).astype(np.uint8)
    return (int(safe[0]), int(safe[1]), int(safe[2]), int(safe[3]))


def make_vector_glb_export_name(
    *,
    source_name: str,
    role: VectorPreviewRole,
    rgba: tuple[int, int, int, int],
    seen_names: set[str],
) -> str:
    """Return a frontend-compatible GLB geometry name and reserve it."""

    if role == "color":
        base = f"color_{rgba[0]:02x}{rgba[1]:02x}{rgba[2]:02x}"
    elif role == "backing":
        base = "backing_plate"
    elif role == "outline":
        base = "Outline"
    else:
        base = str(source_name or "auxiliary")

    candidate = base
    suffix = 0
    while candidate in seen_names:
        suffix += 1
        candidate = f"{base}_{suffix}"
    seen_names.add(candidate)
    return candidate
```

- [ ] **Step 4: Run the descriptor naming tests**

Run:

```powershell
python -m pytest tests/test_vector_glb_v2_kernel_unit.py -v
```

Expected: PASS.

---

### Task 3: Extract V1 Exporter With Descriptor Parity

**Files:**
- Modify: `core/pipeline/vector_glb_preview.py`
- Modify: `tests/test_vector_glb_v2_kernel_unit.py`

- [ ] **Step 1: Add failing V1 export parity tests**

Append:

```python
from pathlib import Path


def _box_mesh(z_min: float = 0.0, z_max: float = 0.4) -> trimesh.Trimesh:
    mesh = trimesh.creation.box(extents=(2.0, 2.0, z_max - z_min))
    mesh.apply_translation((0.0, 0.0, (z_min + z_max) / 2.0))
    return mesh


def test_v1_exporter_writes_color_and_backing_names(tmp_path: Path) -> None:
    parts = [
        vector_glb_preview.VectorPreviewPart(
            source_name="Red",
            export_name="color_ff0000",
            role="color",
            rgba=(255, 0, 0, 255),
            is_recolorable=True,
            fallback_mesh=_box_mesh(),
        ),
        vector_glb_preview.VectorPreviewPart(
            source_name="Board",
            export_name="backing_plate",
            role="backing",
            rgba=(255, 255, 255, 255),
            is_recolorable=False,
            fallback_mesh=_box_mesh(-0.2, 0.0),
        ),
    ]

    out_path = tmp_path / "preview.glb"
    result = vector_glb_preview.export_vector_glb_preview_v1(
        parts,
        output_path=str(out_path),
    )

    assert result == str(out_path)
    loaded = trimesh.load(out_path, force="scene")
    names = set(loaded.geometry.keys())
    assert "color_ff0000" in names
    assert "backing_plate" in names
```

- [ ] **Step 2: Run the new V1 test**

Run:

```powershell
python -m pytest tests/test_vector_glb_v2_kernel_unit.py::test_v1_exporter_writes_color_and_backing_names -v
```

Expected: FAIL because `export_vector_glb_preview_v1` does not exist.

- [ ] **Step 3: Implement V1 exporter**

Add:

```python
def _mesh_with_rgba(mesh: trimesh.Trimesh, rgba: tuple[int, int, int, int]) -> trimesh.Trimesh:
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    geom = trimesh.Trimesh(vertices=vertices.copy(), faces=faces.copy(), process=False)
    rgba_arr = np.asarray(rgba, dtype=np.uint8)
    geom.visual = trimesh.visual.ColorVisuals(
        mesh=geom,
        face_colors=np.tile(rgba_arr, (len(faces), 1)),
    )
    return geom


def _write_glb_scene(glb_scene: trimesh.Scene, output_path: str) -> str:
    exported = glb_scene.export(output_path, file_type="glb")
    if isinstance(exported, (bytes, bytearray)):
        with open(output_path, "wb") as glb_file:
            glb_file.write(exported)
    if not os.path.exists(output_path):
        raise RuntimeError(f"Vector GLB export did not create file: {output_path}")
    return output_path


def export_vector_glb_preview_v1(
    parts: list[VectorPreviewPart],
    *,
    output_path: str,
) -> str:
    """Export a GLB by copying descriptor fallback meshes.

    复制 descriptor 中的 V1 fallback mesh，保持现有 GLB 行为。
    """

    glb_scene = trimesh.Scene()
    for part in parts:
        mesh = part.fallback_mesh
        if mesh is None:
            raise RuntimeError(f"V1 export requires fallback mesh for {part.source_name}")
        vertices = getattr(mesh, "vertices", None)
        faces = getattr(mesh, "faces", None)
        if vertices is None or faces is None or len(vertices) == 0 or len(faces) == 0:
            continue
        glb_scene.add_geometry(
            _mesh_with_rgba(mesh, part.rgba),
            geom_name=part.export_name,
        )

    if not glb_scene.geometry:
        raise RuntimeError("Vector GLB export has no non-empty geometries")
    return _write_glb_scene(glb_scene, output_path)
```

- [ ] **Step 4: Run V1 export tests**

Run:

```powershell
python -m pytest tests/test_vector_glb_v2_kernel_unit.py -v
```

Expected: PASS.

---

### Task 4: Build V1 Descriptors From The Existing Display Scene

**Files:**
- Modify: `core/pipeline/vector_glb_preview.py`
- Modify: `tests/test_vector_glb_v2_kernel_unit.py`

- [ ] **Step 1: Add failing scene descriptor tests**

Append:

```python
def test_build_parts_from_display_scene_classifies_roles_and_colors() -> None:
    scene = trimesh.Scene()
    scene.add_geometry(_box_mesh(), geom_name="Red")
    scene.add_geometry(_box_mesh(), geom_name="Board")
    scene.add_geometry(_box_mesh(), geom_name="Outline")

    parts = vector_glb_preview.build_vector_preview_parts_from_scene(
        scene=scene,
        preview_colors={
            "Red": [255, 0, 0, 255],
            "Board": [255, 255, 255, 255],
            "Outline": [10, 10, 10, 255],
        },
        slot_list=["Red", "Board"],
    )

    by_source = {part.source_name: part for part in parts}
    assert by_source["Red"].role == "color"
    assert by_source["Red"].export_name == "color_ff0000"
    assert by_source["Red"].is_recolorable is True
    assert by_source["Board"].role == "backing"
    assert by_source["Board"].export_name == "backing_plate"
    assert by_source["Outline"].role == "outline"
    assert by_source["Outline"].export_name == "Outline"
```

- [ ] **Step 2: Run the descriptor scene test**

Run:

```powershell
python -m pytest tests/test_vector_glb_v2_kernel_unit.py::test_build_parts_from_display_scene_classifies_roles_and_colors -v
```

Expected: FAIL because `build_vector_preview_parts_from_scene` does not exist.

- [ ] **Step 3: Implement scene descriptor builder**

Add:

```python
def _color_for_geometry(
    geom_name: object,
    *,
    preview_colors: dict,
    slot_list: list,
) -> tuple[int, int, int, int]:
    for key in (geom_name, str(geom_name)):
        if key in preview_colors:
            rgba = coerce_preview_rgba(preview_colors.get(key))
            if rgba is not None:
                return rgba

    try:
        slot_index = list(slot_list).index(str(geom_name))
    except ValueError:
        slot_index = -1
    if slot_index >= 0:
        rgba = coerce_preview_rgba(preview_colors.get(slot_index))
        if rgba is not None:
            return rgba

    return (200, 200, 200, 255)


def _role_for_geometry(geom_name: object, slot_list: list[str]) -> VectorPreviewRole:
    name = str(geom_name)
    if name == "Board":
        return "backing"
    if name == "Outline":
        return "outline"
    if name in set(str(item) for item in slot_list):
        return "color"
    return "auxiliary"


def build_vector_preview_parts_from_scene(
    *,
    scene: trimesh.Scene,
    preview_colors: dict,
    slot_list: list,
) -> list[VectorPreviewPart]:
    """Build fallback descriptors from an already display-oriented scene."""

    seen_names: set[str] = set()
    parts: list[VectorPreviewPart] = []
    for geom_name, source_geom in scene.geometry.items():
        vertices = getattr(source_geom, "vertices", None)
        faces = getattr(source_geom, "faces", None)
        if vertices is None or faces is None or len(vertices) == 0 or len(faces) == 0:
            continue
        role = _role_for_geometry(geom_name, list(slot_list))
        rgba = _color_for_geometry(
            geom_name,
            preview_colors=preview_colors,
            slot_list=list(slot_list),
        )
        export_name = make_vector_glb_export_name(
            source_name=str(geom_name),
            role=role,
            rgba=rgba,
            seen_names=seen_names,
        )
        parts.append(
            VectorPreviewPart(
                source_name=str(geom_name),
                export_name=export_name,
                role=role,
                rgba=rgba,
                is_recolorable=(role == "color"),
                fallback_mesh=source_geom.copy(),
            )
        )
    return parts
```

- [ ] **Step 4: Run unit tests**

Run:

```powershell
python -m pytest tests/test_vector_glb_v2_kernel_unit.py -v
```

Expected: PASS.

---

### Task 5: Wire Default V1 Through The New Module Without Behavior Change

**Files:**
- Modify: `core/pipeline/vector_branch.py`
- Modify: `core/pipeline/vector_glb_preview.py`
- Test: `tests/test_vector_preview_glb_orientation_unit.py`
- Test: `tests/test_vector_cover_and_glb_naming_unit.py`

- [ ] **Step 1: Add dispatcher tests that default to V1**

Append to `tests/test_vector_glb_v2_kernel_unit.py`:

```python
def test_export_dispatch_defaults_to_v1(monkeypatch, tmp_path: Path) -> None:
    scene = trimesh.Scene()
    scene.add_geometry(_box_mesh(), geom_name="Red")
    calls: list[str] = []

    def fake_v1(parts, *, output_path):
        calls.append("v1")
        Path(output_path).write_bytes(b"glb")
        return output_path

    def fail_v2(*_args, **_kwargs):
        raise AssertionError("V2 must not run by default")

    monkeypatch.delenv("LUMINA_VECTOR_GLB_KERNEL", raising=False)
    monkeypatch.setattr(vector_glb_preview, "export_vector_glb_preview_v1", fake_v1)
    monkeypatch.setattr(vector_glb_preview, "export_vector_glb_preview_v2", fail_v2)

    result = vector_glb_preview.export_vector_glb_preview(
        scene=scene,
        output_path=str(tmp_path / "preview.glb"),
        structure_mode="Double-sided",
        color_mode="4-Color (RYBW)",
        preview_colors={"Red": [255, 0, 0, 255]},
        slot_list=["Red"],
        analysis=None,
        ctx={},
    )

    assert result.endswith("preview.glb")
    assert calls == ["v1"]
```

- [ ] **Step 2: Run the dispatcher test**

Run:

```powershell
python -m pytest tests/test_vector_glb_v2_kernel_unit.py::test_export_dispatch_defaults_to_v1 -v
```

Expected: FAIL because `export_vector_glb_preview` does not exist.

- [ ] **Step 3: Implement dispatcher with V1 only**

Add:

```python
def _make_display_scene(scene: trimesh.Scene, *, structure_mode: object, color_mode: object) -> trimesh.Scene:
    from core.pipeline.vector_branch import _make_vector_glb_preview_scene

    return _make_vector_glb_preview_scene(
        scene,
        structure_mode=structure_mode,
        color_mode=color_mode,
    )


def export_vector_glb_preview(
    *,
    scene: trimesh.Scene,
    output_path: str,
    structure_mode: object,
    color_mode: object,
    preview_colors: dict,
    slot_list: list,
    analysis: object | None,
    ctx: dict,
) -> str:
    """Export vector preview GLB through selected kernel with V1 fallback."""

    display_scene = _make_display_scene(
        scene,
        structure_mode=structure_mode,
        color_mode=color_mode,
    )
    fallback_parts = build_vector_preview_parts_from_scene(
        scene=display_scene,
        preview_colors=preview_colors,
        slot_list=list(slot_list),
    )
    kernel = resolve_vector_glb_kernel_choice()
    if kernel == "trimesh_v1":
        return export_vector_glb_preview_v1(fallback_parts, output_path=output_path)

    return export_vector_glb_preview_v1(fallback_parts, output_path=output_path)
```

- [ ] **Step 4: Replace the inline GLB block in `vector_branch.py`**

In `core/pipeline/vector_branch.py`, add the import inside `_run_vector_branch` near GLB export or at module top:

```python
from core.pipeline.vector_glb_preview import export_vector_glb_preview
```

Replace the inline `# 3. GLB preview` body with:

```python
        # 3. GLB preview
        _report_progress(ctx, 0.82, "生成 3D 预览中... | Generating 3D preview...")
        glb_path = None
        glb_t0 = time.perf_counter()
        try:
            glb_path = export_vector_glb_preview(
                scene=scene,
                output_path=os.path.join(
                    OUTPUT_DIR,
                    generate_preview_filename(base_name),
                ),
                structure_mode=structure_mode,
                color_mode=vec_color_mode,
                preview_colors=vec_preview_colors,
                slot_list=list(vec_slot_list),
                analysis=analysis,
                ctx=ctx,
            )
            log.debug(
                "Vector preview GLB exported",
                extra={
                    "event": "vector_glb_exported",
                    "path": str(glb_path),
                },
            )
        except COORDINATOR_HANDLED_ERRORS as e:
            glb_path = None
            log.warning(
                "Vector preview GLB export skipped",
                extra={
                    "event": "vector_glb_exported_skipped",
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                },
            )
        vector_timing["export_glb_s"] = time.perf_counter() - glb_t0
```

- [ ] **Step 5: Run behavior-preserving tests**

Run:

```powershell
python -m pytest tests/test_vector_glb_v2_kernel_unit.py tests/test_vector_preview_glb_orientation_unit.py tests/test_vector_cover_and_glb_naming_unit.py -v
```

Expected: PASS. At this point default behavior remains V1.

---

### Task 6: Build Footprint Descriptors From Business-Processed `analysis`

**Files:**
- Modify: `core/pipeline/vector_glb_preview.py`
- Test: `tests/test_vector_glb_v2_kernel_unit.py`

- [ ] **Step 1: Add failing tests for color footprint descriptors**

Append:

```python
from types import SimpleNamespace


def test_build_parts_from_analysis_creates_color_extrusions() -> None:
    analysis = SimpleNamespace(
        matched_shapes=[
            {"geometry": box(0, 0, 10, 10), "recipe": [1, 1, 0]},
            {"geometry": box(10, 0, 20, 10), "recipe": [1, 0, 0]},
        ],
        silhouette=box(0, 0, 20, 10),
        scale_factor=2.0,
        bbox=(0, 0, 20, 10),
        slot_names=["White", "Red"],
        num_channels=2,
        num_layers=3,
        preview_colors={
            0: [255, 255, 255, 255],
            1: [255, 0, 0, 255],
            "White": [255, 255, 255, 255],
            "Red": [255, 0, 0, 255],
        },
    )

    parts = vector_glb_preview.build_vector_preview_parts_from_analysis(
        analysis=analysis,
        preview_colors=dict(analysis.preview_colors),
        slot_list=list(analysis.slot_names),
        structure_mode="Double-sided",
        color_mode="4-Color (RYBW)",
        thickness_mm=1.6,
        separate_backing=False,
        include_backing=False,
        include_outline=False,
        outline_width_mm=2.0,
    )

    red = next(part for part in parts if part.source_name == "Red")
    assert red.role == "color"
    assert red.export_name == "color_ff0000"
    assert red.extrusions
    assert all(ex.z_max > ex.z_min for ex in red.extrusions)
```

- [ ] **Step 2: Run the new descriptor test**

Run:

```powershell
python -m pytest tests/test_vector_glb_v2_kernel_unit.py::test_build_parts_from_analysis_creates_color_extrusions -v
```

Expected: FAIL because `build_vector_preview_parts_from_analysis` does not exist.

- [ ] **Step 3: Implement analysis descriptor helpers**

Add imports:

```python
from shapely import affinity
from shapely.ops import unary_union
```

Add helpers:

```python
def _iter_valid_geometries(geoms: list[BaseGeometry]) -> list[BaseGeometry]:
    return [
        geom
        for geom in geoms
        if geom is not None and not getattr(geom, "is_empty", True)
    ]


def _union_geometries(geoms: list[BaseGeometry]) -> BaseGeometry | None:
    valid = _iter_valid_geometries(geoms)
    if not valid:
        return None
    merged = unary_union(valid) if len(valid) > 1 else valid[0]
    if merged is None or getattr(merged, "is_empty", True):
        return None
    return merged


def _shape_runs_by_channel(
    *,
    recipe: list[int],
    num_layers: int,
    num_channels: int,
) -> dict[int, list[tuple[int, int]]]:
    from core.vector_engine import VectorProcessor

    return VectorProcessor._build_channel_runs(
        recipe,
        min(num_layers, len(recipe)),
        num_channels,
    )


def _to_display_footprint(
    geom: BaseGeometry,
    *,
    scale_factor: float,
    svg_height_mm: float,
    model_width_mm: float,
    mirror_x: bool,
) -> BaseGeometry:
    scaled = affinity.scale(geom, xfact=scale_factor, yfact=-scale_factor, origin=(0, 0))
    translated = affinity.translate(scaled, xoff=0.0, yoff=svg_height_mm)
    if mirror_x:
        translated = affinity.scale(translated, xfact=-1.0, yfact=1.0, origin=(0, 0))
        translated = affinity.translate(translated, xoff=model_width_mm, yoff=0.0)
    return translated
```

Add descriptor builder:

```python
def build_vector_preview_parts_from_analysis(
    *,
    analysis: object,
    preview_colors: dict,
    slot_list: list,
    structure_mode: object,
    color_mode: object,
    thickness_mm: float,
    separate_backing: bool,
    include_backing: bool,
    include_outline: bool,
    outline_width_mm: float,
) -> list[VectorPreviewPart]:
    """Build V2 candidate descriptors from business-processed VectorAnalysis."""

    del separate_backing, include_outline, outline_width_mm
    layer_h = 0.08
    try:
        from config import PrinterConfig

        layer_h = float(PrinterConfig.LAYER_HEIGHT)
    except Exception:
        layer_h = 0.08

    matched_shapes = list(getattr(analysis, "matched_shapes", []) or [])
    slot_names = [str(item) for item in slot_list]
    num_layers = int(getattr(analysis, "num_layers", 0) or 0)
    num_channels = int(getattr(analysis, "num_channels", len(slot_names)) or len(slot_names))
    scale_factor = float(getattr(analysis, "scale_factor", 1.0) or 1.0)
    bbox = getattr(analysis, "bbox", (0, 0, 0, 0))
    svg_height_mm = float(bbox[3]) * scale_factor
    model_width_mm = float(bbox[2]) * scale_factor
    color_mode_text = str(color_mode or "")
    structure_text = str(structure_mode or "")
    is_5color = "5-Color Extended" in color_mode_text
    is_single = "单面" in structure_text or "Single" in structure_text
    is_double = "双面" in structure_text or "Double" in structure_text
    mirror_x = is_single and not is_5color
    backing_layers = max(1, int(round(float(thickness_mm) / layer_h)))
    backing_height = backing_layers * layer_h

    grouped: dict[tuple[int, float, float], list[BaseGeometry]] = {}
    for item in matched_shapes:
        geom = item.get("geometry") if isinstance(item, dict) else None
        recipe = item.get("recipe") if isinstance(item, dict) else None
        if geom is None or getattr(geom, "is_empty", True) or not recipe:
            continue
        runs_by_channel = _shape_runs_by_channel(
            recipe=[int(v) for v in recipe],
            num_layers=num_layers,
            num_channels=num_channels,
        )
        for channel, runs in runs_by_channel.items():
            if channel >= len(slot_names):
                continue
            for run_start, run_end in runs:
                if is_5color:
                    inv_start = (num_layers - 1) - run_end
                    inv_end = (num_layers - 1) - run_start
                    z_min = backing_height + inv_start * layer_h
                    z_max = backing_height + (inv_end + 1) * layer_h
                else:
                    z_min = run_start * layer_h
                    z_max = (run_end + 1) * layer_h
                grouped.setdefault((channel, z_min, z_max), []).append(geom)

                if is_double:
                    top_z_start = num_layers * layer_h + backing_height
                    inv_start = (num_layers - 1) - run_end
                    inv_end = (num_layers - 1) - run_start
                    top_z_min = top_z_start + inv_start * layer_h
                    top_z_max = top_z_start + (inv_end + 1) * layer_h
                    grouped.setdefault((channel, top_z_min, top_z_max), []).append(geom)

    seen_names: set[str] = set()
    by_slot: dict[int, list[VectorPreviewExtrusion]] = {}
    for (channel, z_min, z_max), geoms in grouped.items():
        unioned = _union_geometries(geoms)
        if unioned is None:
            continue
        footprint = _to_display_footprint(
            unioned,
            scale_factor=scale_factor,
            svg_height_mm=svg_height_mm,
            model_width_mm=model_width_mm,
            mirror_x=mirror_x,
        )
        by_slot.setdefault(channel, []).append(
            VectorPreviewExtrusion(
                footprint=footprint,
                z_min=float(z_min),
                z_max=float(z_max),
            )
        )

    parts: list[VectorPreviewPart] = []
    for channel, extrusions in sorted(by_slot.items()):
        if channel >= len(slot_names):
            continue
        source_name = slot_names[channel]
        rgba = _color_for_geometry(
            source_name,
            preview_colors=preview_colors,
            slot_list=slot_names,
        )
        export_name = make_vector_glb_export_name(
            source_name=source_name,
            role="color",
            rgba=rgba,
            seen_names=seen_names,
        )
        parts.append(
            VectorPreviewPart(
                source_name=source_name,
                export_name=export_name,
                role="color",
                rgba=rgba,
                is_recolorable=True,
                extrusions=tuple(extrusions),
            )
        )

    if include_backing:
        silhouette = getattr(analysis, "silhouette", None)
        if silhouette is not None and not getattr(silhouette, "is_empty", True):
            footprint = _to_display_footprint(
                silhouette,
                scale_factor=scale_factor,
                svg_height_mm=svg_height_mm,
                model_width_mm=model_width_mm,
                mirror_x=mirror_x,
            )
            rgba = _color_for_geometry("Board", preview_colors=preview_colors, slot_list=slot_names)
            export_name = make_vector_glb_export_name(
                source_name="Board",
                role="backing",
                rgba=rgba,
                seen_names=seen_names,
            )
            z_min = 0.0 if is_5color else num_layers * layer_h
            parts.append(
                VectorPreviewPart(
                    source_name="Board",
                    export_name=export_name,
                    role="backing",
                    rgba=rgba,
                    is_recolorable=False,
                    extrusions=(
                        VectorPreviewExtrusion(
                            footprint=footprint,
                            z_min=float(z_min),
                            z_max=float(z_min + backing_height),
                        ),
                    ),
                )
            )

    return parts
```

- [ ] **Step 4: Run descriptor tests**

Run:

```powershell
python -m pytest tests/test_vector_glb_v2_kernel_unit.py -v
```

Expected: PASS.

---

### Task 7: Add V2 Exporter From Footprints And Whole-Export Fallback

**Files:**
- Modify: `core/pipeline/vector_glb_preview.py`
- Modify: `tests/test_vector_glb_v2_kernel_unit.py`

- [ ] **Step 1: Add V2 success and fallback tests**

Append:

```python
def test_v2_exporter_writes_glb_from_footprint(tmp_path: Path) -> None:
    part = vector_glb_preview.VectorPreviewPart(
        source_name="Red",
        export_name="color_ff0000",
        role="color",
        rgba=(255, 0, 0, 255),
        is_recolorable=True,
        extrusions=(
            vector_glb_preview.VectorPreviewExtrusion(
                footprint=box(0, 0, 10, 10),
                z_min=0.0,
                z_max=0.24,
            ),
        ),
    )

    out_path = tmp_path / "preview-v2.glb"
    result = vector_glb_preview.export_vector_glb_preview_v2(
        [part],
        output_path=str(out_path),
        pixels_per_mm=4.0,
    )

    assert result == str(out_path)
    loaded = trimesh.load(out_path, force="scene")
    assert "color_ff0000" in set(loaded.geometry.keys())


def test_dispatch_v2_failure_falls_back_to_v1(monkeypatch, tmp_path: Path, caplog) -> None:
    caplog.set_level(logging.WARNING, logger="lumina.core.pipeline.vector_glb_preview")
    scene = trimesh.Scene()
    scene.add_geometry(_box_mesh(), geom_name="Red")
    calls: list[str] = []

    def fail_v2(*_args, **_kwargs):
        calls.append("v2")
        raise RuntimeError("forced v2 failure")

    def fake_v1(parts, *, output_path):
        calls.append("v1")
        Path(output_path).write_bytes(b"glb")
        return output_path

    monkeypatch.setenv("LUMINA_VECTOR_GLB_KERNEL", "v2")
    monkeypatch.setattr(vector_glb_preview, "export_vector_glb_preview_v2", fail_v2)
    monkeypatch.setattr(vector_glb_preview, "export_vector_glb_preview_v1", fake_v1)

    result = vector_glb_preview.export_vector_glb_preview(
        scene=scene,
        output_path=str(tmp_path / "preview.glb"),
        structure_mode="Double-sided",
        color_mode="4-Color (RYBW)",
        preview_colors={"Red": [255, 0, 0, 255]},
        slot_list=["Red"],
        analysis=None,
        ctx={},
    )

    assert result.endswith("preview.glb")
    assert calls == ["v2", "v1"]
    assert "vector_glb_v2_runtime_fallback" in _record_events(caplog)
```

- [ ] **Step 2: Run V2 tests**

Run:

```powershell
python -m pytest tests/test_vector_glb_v2_kernel_unit.py::test_v2_exporter_writes_glb_from_footprint tests/test_vector_glb_v2_kernel_unit.py::test_dispatch_v2_failure_falls_back_to_v1 -v
```

Expected: FAIL because V2 exporter is not implemented.

- [ ] **Step 3: Implement footprint rasterization and V2 mesh creation**

Add:

```python
def _rasterize_footprint_local(
    footprint: BaseGeometry,
    *,
    pixels_per_mm: float,
) -> tuple[np.ndarray, float, float, float]:
    if footprint is None or getattr(footprint, "is_empty", True):
        raise RuntimeError("empty footprint")
    min_x, min_y, max_x, max_y = (float(v) for v in footprint.bounds)
    if max_x <= min_x or max_y <= min_y:
        raise RuntimeError("invalid footprint bounds")
    pixel_scale = 1.0 / float(pixels_per_mm)
    width = max(1, int(np.ceil((max_x - min_x) * pixels_per_mm)))
    height = max(1, int(np.ceil((max_y - min_y) * pixels_per_mm)))

    try:
        from rasterio.features import rasterize
        from rasterio.transform import from_origin
        from shapely.geometry import mapping
    except Exception as exc:
        raise RuntimeError(f"V2 footprint rasterization unavailable: {exc}") from exc

    transform = from_origin(min_x, max_y, pixel_scale, pixel_scale)
    mask = rasterize(
        [(mapping(footprint), 1)],
        out_shape=(height, width),
        transform=transform,
        fill=0,
        dtype="uint8",
    ).astype(bool)
    if not np.any(mask):
        raise RuntimeError("footprint rasterized to empty mask")
    return mask, min_x, min_y, pixel_scale


def _mesh_from_extrusion_v2(
    extrusion: VectorPreviewExtrusion,
    *,
    rgba: tuple[int, int, int, int],
    pixels_per_mm: float,
) -> trimesh.Trimesh:
    from core.pipeline import s11_glb_preview

    layer_h = 0.08
    try:
        from config import PrinterConfig

        layer_h = float(PrinterConfig.LAYER_HEIGHT)
    except Exception:
        layer_h = 0.08

    mask, min_x, min_y, pixel_scale = _rasterize_footprint_local(
        extrusion.footprint,
        pixels_per_mm=pixels_per_mm,
    )
    layer_count = max(1, int(round((float(extrusion.z_max) - float(extrusion.z_min)) / layer_h)))
    mesh = s11_glb_preview._build_color_extruded_mesh_v2(
        mask=mask,
        height=mask.shape[0],
        total_layers=layer_count,
        rgba=np.asarray(rgba, dtype=np.uint8),
    )
    if mesh is None:
        raise RuntimeError("V2 mesh kernel returned None")
    mesh.apply_scale([pixel_scale, pixel_scale, layer_h])
    mesh.apply_translation([min_x, min_y, float(extrusion.z_min)])
    return mesh


def export_vector_glb_preview_v2(
    parts: list[VectorPreviewPart],
    *,
    output_path: str,
    pixels_per_mm: float = 10.0,
) -> str:
    """Export GLB by generating meshes from descriptor footprints."""

    glb_scene = trimesh.Scene()
    for part in parts:
        if not part.extrusions:
            raise RuntimeError(f"V2 export requires footprints for {part.source_name}")
        meshes = [
            _mesh_from_extrusion_v2(
                extrusion,
                rgba=part.rgba,
                pixels_per_mm=pixels_per_mm,
            )
            for extrusion in part.extrusions
        ]
        combined = trimesh.util.concatenate(meshes) if len(meshes) > 1 else meshes[0]
        glb_scene.add_geometry(combined, geom_name=part.export_name)
    if not glb_scene.geometry:
        raise RuntimeError("V2 vector GLB export has no geometry")
    return _write_glb_scene(glb_scene, output_path)
```

- [ ] **Step 4: Update dispatcher to try V2 and fallback V1**

Replace the final part of `export_vector_glb_preview` with:

```python
    kernel = resolve_vector_glb_kernel_choice()
    if kernel == "trimesh_v1":
        return export_vector_glb_preview_v1(fallback_parts, output_path=output_path)

    try:
        v2_parts = build_vector_preview_parts_from_analysis(
            analysis=analysis,
            preview_colors=preview_colors,
            slot_list=list(slot_list),
            structure_mode=structure_mode,
            color_mode=color_mode,
            thickness_mm=float(ctx.get("spacer_thick", 1.6) or 1.6),
            separate_backing=bool(ctx.get("separate_backing", False)),
            include_backing="Board" in display_scene.geometry,
            include_outline="Outline" in display_scene.geometry,
            outline_width_mm=float(ctx.get("outline_width", 2.0) or 2.0),
        )
        if not v2_parts:
            raise RuntimeError("V2 descriptor builder returned no parts")
        return export_vector_glb_preview_v2(v2_parts, output_path=output_path)
    except Exception as exc:
        log.warning(
            "Vector GLB V2 failed; falling back to V1",
            extra={
                "event": "vector_glb_v2_runtime_fallback",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "fallback_kernel": "trimesh_v1",
            },
        )
        return export_vector_glb_preview_v1(fallback_parts, output_path=output_path)
```

- [ ] **Step 5: Run V2 unit tests**

Run:

```powershell
python -m pytest tests/test_vector_glb_v2_kernel_unit.py -v
```

Expected: PASS.

---

### Task 8: Add Parity Tests For Business Modes And Unsupported Fallback

**Files:**
- Create: `tests/test_vector_glb_v2_parity_unit.py`
- Modify: `core/pipeline/vector_glb_preview.py` if parity exposes a bug

- [ ] **Step 1: Create parity test file**

Create `tests/test_vector_glb_v2_parity_unit.py`:

```python
"""Parity tests for SVG GLB V1/V2 preview descriptors."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import trimesh
from shapely.geometry import box

from core.pipeline import vector_glb_preview


def _analysis_for_modes() -> SimpleNamespace:
    return SimpleNamespace(
        matched_shapes=[
            {"geometry": box(0, 0, 10, 10), "recipe": [1, 1, 0, 0]},
            {"geometry": box(10, 0, 20, 10), "recipe": [2, 2, 2, 0]},
        ],
        silhouette=box(0, 0, 20, 10),
        scale_factor=1.0,
        bbox=(0, 0, 20, 10),
        slot_names=["White", "Red", "Blue"],
        num_channels=3,
        num_layers=4,
        preview_colors={
            0: [255, 255, 255, 255],
            1: [255, 0, 0, 255],
            2: [0, 0, 255, 255],
            "White": [255, 255, 255, 255],
            "Red": [255, 0, 0, 255],
            "Blue": [0, 0, 255, 255],
            "Board": [255, 255, 255, 255],
        },
    )


@pytest.mark.parametrize(
    ("structure_mode", "color_mode"),
    [
        ("Single-sided", "4-Color (RYBW)"),
        ("Double-sided", "4-Color (RYBW)"),
        ("Single-sided", "5-Color Extended"),
    ],
)
def test_v2_descriptor_bounds_are_finite_for_core_modes(
    structure_mode: str,
    color_mode: str,
) -> None:
    analysis = _analysis_for_modes()
    parts = vector_glb_preview.build_vector_preview_parts_from_analysis(
        analysis=analysis,
        preview_colors=dict(analysis.preview_colors),
        slot_list=list(analysis.slot_names),
        structure_mode=structure_mode,
        color_mode=color_mode,
        thickness_mm=1.6,
        separate_backing=True,
        include_backing=True,
        include_outline=False,
        outline_width_mm=2.0,
    )

    assert parts
    for part in parts:
        assert part.export_name
        for extrusion in part.extrusions:
            assert extrusion.z_max > extrusion.z_min
            assert not extrusion.footprint.is_empty


def test_v2_descriptor_keeps_outline_non_recolorable() -> None:
    seen: set[str] = set()
    name = vector_glb_preview.make_vector_glb_export_name(
        source_name="Outline",
        role="outline",
        rgba=(10, 10, 10, 255),
        seen_names=seen,
    )

    assert name == "Outline"
    assert not name.startswith("color_")


def test_v2_exporter_rejects_part_without_footprint(tmp_path) -> None:
    part = vector_glb_preview.VectorPreviewPart(
        source_name="FridgeCavityBoard",
        export_name="backing_plate",
        role="backing",
        rgba=(255, 255, 255, 255),
        is_recolorable=False,
        extrusions=(),
        fallback_mesh=trimesh.creation.box(extents=(1, 1, 1)),
    )

    with pytest.raises(RuntimeError, match="requires footprints"):
        vector_glb_preview.export_vector_glb_preview_v2(
            [part],
            output_path=str(tmp_path / "bad.glb"),
        )
```

- [ ] **Step 2: Run parity tests**

Run:

```powershell
python -m pytest tests/test_vector_glb_v2_parity_unit.py -v
```

Expected: PASS after Tasks 6 and 7.

- [ ] **Step 3: Add a fallback guard for high-risk modes**

In `export_vector_glb_preview`, before building V2 descriptors, reject V2 when these ctx flags are active:

```python
        if bool(ctx.get("enable_fridge_magnet", False)):
            raise RuntimeError("V2 vector GLB does not yet support fridge magnet cavities")
        if bool(ctx.get("enable_coating", False)):
            raise RuntimeError("V2 vector GLB does not yet support coating geometry")
```

This deliberately forces V1 for fridge magnet and coating until their footprint descriptions include the missing cavity/coating geometry.

- [ ] **Step 4: Add a test for fridge fallback**

Append to `tests/test_vector_glb_v2_kernel_unit.py`:

```python
def test_dispatch_v2_fridge_magnet_forces_v1(monkeypatch, tmp_path: Path) -> None:
    scene = trimesh.Scene()
    scene.add_geometry(_box_mesh(), geom_name="Board")
    calls: list[str] = []

    def fake_v1(parts, *, output_path):
        calls.append("v1")
        Path(output_path).write_bytes(b"glb")
        return output_path

    monkeypatch.setenv("LUMINA_VECTOR_GLB_KERNEL", "v2")
    monkeypatch.setattr(vector_glb_preview, "export_vector_glb_preview_v1", fake_v1)

    result = vector_glb_preview.export_vector_glb_preview(
        scene=scene,
        output_path=str(tmp_path / "preview.glb"),
        structure_mode="Single-sided",
        color_mode="4-Color (RYBW)",
        preview_colors={"Board": [255, 255, 255, 255]},
        slot_list=["Board"],
        analysis=_analysis_for_fridge_test(),
        ctx={"enable_fridge_magnet": True, "spacer_thick": 1.6},
    )

    assert result.endswith("preview.glb")
    assert calls == ["v1"]
```

Define `_analysis_for_fridge_test()` in the same test file:

```python
def _analysis_for_fridge_test() -> SimpleNamespace:
    return SimpleNamespace(
        matched_shapes=[],
        silhouette=box(0, 0, 10, 10),
        scale_factor=1.0,
        bbox=(0, 0, 10, 10),
        slot_names=["Board"],
        num_channels=1,
        num_layers=1,
        preview_colors={"Board": [255, 255, 255, 255]},
    )
```

- [ ] **Step 5: Run targeted parity tests**

Run:

```powershell
python -m pytest tests/test_vector_glb_v2_kernel_unit.py tests/test_vector_glb_v2_parity_unit.py -v
```

Expected: PASS.

---

### Task 9: Add Timing And Fallback Observability

**Files:**
- Modify: `core/pipeline/vector_glb_preview.py`
- Modify: `tests/test_vector_glb_v2_kernel_unit.py`

- [ ] **Step 1: Add a log assertion for V2 success**

Append:

```python
def test_v2_success_logs_kernel_and_part_count(tmp_path: Path, caplog) -> None:
    caplog.set_level(logging.INFO, logger="lumina.core.pipeline.vector_glb_preview")
    part = vector_glb_preview.VectorPreviewPart(
        source_name="Red",
        export_name="color_ff0000",
        role="color",
        rgba=(255, 0, 0, 255),
        is_recolorable=True,
        extrusions=(
            vector_glb_preview.VectorPreviewExtrusion(
                footprint=box(0, 0, 5, 5),
                z_min=0.0,
                z_max=0.16,
            ),
        ),
    )

    vector_glb_preview.export_vector_glb_preview_v2(
        [part],
        output_path=str(tmp_path / "preview.glb"),
        pixels_per_mm=4.0,
    )

    assert "vector_glb_v2_exported" in _record_events(caplog)
```

- [ ] **Step 2: Run the log test**

Run:

```powershell
python -m pytest tests/test_vector_glb_v2_kernel_unit.py::test_v2_success_logs_kernel_and_part_count -v
```

Expected: FAIL because V2 exporter does not log success yet.

- [ ] **Step 3: Add structured logs**

In `export_vector_glb_preview_v2`, wrap timing:

```python
    import time

    t0 = time.perf_counter()
```

Before returning:

```python
    result = _write_glb_scene(glb_scene, output_path)
    log.info(
        "Vector GLB V2 exported",
        extra={
            "event": "vector_glb_v2_exported",
            "path": str(output_path),
            "part_count": len(parts),
            "geometry_count": len(glb_scene.geometry),
            "duration_ms": round((time.perf_counter() - t0) * 1000, 3),
        },
    )
    return result
```

Ensure `export_vector_glb_preview_v1` logs at DEBUG only, or keep the existing `vector_branch.py` `vector_glb_exported` event as the primary default-path event.

- [ ] **Step 4: Run log governance-adjacent tests**

Run:

```powershell
python -m pytest tests/test_vector_glb_v2_kernel_unit.py tests/test_logging_exception_governance_unit.py -v
```

Expected: PASS. If governance rejects the new event, add `vector_glb_v2_exported`, `vector_glb_v2_runtime_fallback`, and `vector_glb_kernel_unknown_value` to the relevant allowlist without increasing unrelated workflow budgets.

---

### Task 10: Add Frontend Contract Guard Only If Backend Output Contract Changes

**Files:**
- Modify only if needed: `frontend/src/__tests__/Scene3D.test.tsx`

- [ ] **Step 1: Inspect whether existing frontend tests already cover `previewGlbUrl` overlays**

Run:

```powershell
rg -n "previewGlbUrl|OutlineFrame3D|PuzzleOverlay3D|KeychainRing3D|FridgeMagnet3D" frontend/src/__tests__ frontend/src/components/__tests__ -S
```

- [ ] **Step 2: If no existing test covers it, add this contract test**

In `frontend/src/__tests__/Scene3D.test.tsx`, add a test using the file's existing render helpers:

```tsx
it("keeps previewGlbUrl as the 3D source while overlay controls remain enabled", async () => {
  useConverterStore.setState({
    modelUrl: null,
    previewGlbUrl: "/api/files/vector-preview.glb",
    enable_outline: true,
    enable_cloisonne: true,
    add_loop: true,
    enable_fridge_magnet: true,
    fridge_magnets: [
      {
        id: "m1",
        shape: "round",
        preset_key: "round_d6x2",
        diameter_mm: 6,
        thickness_mm: 2,
        center_x_mm: 0,
        center_y_mm: 0,
      },
    ],
  });

  render(<Scene3D />);

  expect(screen.getByTestId("interactive-model-viewer")).toBeInTheDocument();
});
```

Use the actual mock/test ids already present in `Scene3D.test.tsx`; do not invent a new component contract if the file has established mocks.

- [ ] **Step 3: Run frontend test through the wrapper**

Run:

```powershell
python scripts/run_vitest.py run frontend/src/__tests__/Scene3D.test.tsx
```

Expected: PASS.

---

### Task 11: Add A Real SVG Profile Script For V1/V2 Comparison

**Files:**
- Create: `scripts/profile_vector_glb_v2.py`
- Test manually by running the script on existing SVG fixtures.

- [ ] **Step 1: Create a small profile script**

Create `scripts/profile_vector_glb_v2.py`:

```python
"""Profile SVG/vector GLB V1 vs V2 preview export on fixture SVG files."""

from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from pathlib import Path


def _run_once(svg_path: Path, kernel: str) -> dict[str, object]:
    from config import ModelingMode
    from core.pipeline import coordinator

    os.environ["LUMINA_VECTOR_GLB_KERNEL"] = kernel
    ctx = {
        "image_path": str(svg_path),
        "actual_lut_path": "lut-preset/4color.json",
        "color_mode": "4-Color",
        "modeling_mode": ModelingMode.VECTOR,
        "target_width_mm": 80.0,
        "spacer_thick": 1.6,
        "structure_mode": "Single-sided",
        "need_2d_preview": False,
        "printer_id": "bambu-h2d",
        "slicer": "BambuStudio",
        "nozzle_size": "0.4",
    }
    started = time.perf_counter()
    result = coordinator._run_vector_branch(ctx)
    elapsed = time.perf_counter() - started
    timings = result.get("vector_timing") or {}
    return {
        "svg": str(svg_path),
        "kernel": kernel,
        "elapsed_s": elapsed,
        "export_glb_s": timings.get("export_glb_s"),
        "mesh_total_s": timings.get("mesh_total_s"),
        "error": result.get("error"),
        "glb_path": (result.get("result_tuple") or [None, None])[1],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("svg", nargs="+", help="SVG fixture paths")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--json-out", default="logs/vector_glb_v2_profile.json")
    args = parser.parse_args()

    rows: list[dict[str, object]] = []
    for svg in args.svg:
        path = Path(svg)
        for kernel in ("v1", "v2"):
            for _ in range(args.runs):
                rows.append(_run_once(path, kernel))

    Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json_out).write_text(
        json.dumps(rows, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    for kernel in ("v1", "v2"):
        values = [
            float(row["elapsed_s"])
            for row in rows
            if row["kernel"] == kernel and row.get("error") is None
        ]
        if values:
            print(f"{kernel}: median elapsed_s={statistics.median(values):.3f}")
    print(f"Wrote {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run it on small fixtures**

Run:

```powershell
python scripts/profile_vector_glb_v2.py tests/fixtures/svg_vector/simple_rect.svg --runs 1
```

Expected: completes and writes `logs/vector_glb_v2_profile.json`.

- [ ] **Step 3: Run it on at least one real complex SVG supplied by the user**

Run the same script with the real SVG path when available. Record:

- V1 `elapsed_s`
- V2 `elapsed_s`
- V1 `export_glb_s`
- V2 `export_glb_s`
- fallback events in the latest log

Do not declare the optimization successful unless V2 reduces a user-visible stage on real SVG inputs and compatibility tests still pass.

---

### Task 12: Local Docker Opt-In Without Touching User Data

**Files:**
- Modify only if needed: `scripts/docker_local_deploy.ps1`

- [ ] **Step 1: Inspect current Docker local deploy script**

Run:

```powershell
Get-Content -Encoding UTF8 scripts/docker_local_deploy.ps1
```

- [ ] **Step 2: Add local-only env var to the container run arguments**

Add this env var to the local container run command:

```powershell
--env LUMINA_VECTOR_GLB_KERNEL=v2
```

Do not change production code defaults. Do not change material/runtime volume mounts.

- [ ] **Step 3: Verify runtime bind mounts remain unchanged**

Run:

```powershell
docker inspect lumina-layers-local
```

Expected:

- Container env includes `LUMINA_VECTOR_GLB_KERNEL=v2`.
- Existing runtime bind mount still points to the user's runtime directory.
- No Docker volume prune, image prune, or material overwrite occurred.

---

### Task 13: Final Verification Before Asking For Manual Test

**Files:**
- All changed files

- [ ] **Step 1: Run targeted backend tests**

Run:

```powershell
python -m pytest tests/test_vector_glb_v2_kernel_unit.py tests/test_vector_glb_v2_parity_unit.py tests/test_vector_preview_glb_orientation_unit.py tests/test_vector_cover_and_glb_naming_unit.py tests/test_glb_v2_kernel_unit.py -v
```

Expected: PASS.

- [ ] **Step 2: Run frontend contract test if Task 10 changed frontend files**

Run:

```powershell
python scripts/run_vitest.py run frontend/src/__tests__/Scene3D.test.tsx
```

Expected: PASS. Skip this command only if no frontend file changed and existing backend output contract remains unchanged.

- [ ] **Step 3: Check for accidental material/runtime edits**

Run:

```powershell
git status --short -- core/pipeline/vector_glb_preview.py core/pipeline/vector_branch.py tests/test_vector_glb_v2_kernel_unit.py tests/test_vector_glb_v2_parity_unit.py scripts/profile_vector_glb_v2.py scripts/docker_local_deploy.ps1 materials
```

Expected:

- Changed files are limited to the planned source/test/script files.
- No intentional edits under `materials/**`.

- [ ] **Step 4: Run profile comparison**

Run:

```powershell
python scripts/profile_vector_glb_v2.py tests/fixtures/svg_vector/simple_rect.svg --runs 2
```

Expected:

- Script completes.
- V1 and V2 both produce a GLB path or V2 logs fallback and still returns a valid V1 GLB.

- [ ] **Step 5: Ask user for manual SVG test before PR**

Report:

- PR/default path still uses V1 unless `LUMINA_VECTOR_GLB_KERNEL=v2` is set.
- Local Docker can run V2 for SVG GLB testing.
- Fridge magnet/coating fallback to V1 in first implementation.
- User should manually test:普通 SVG、复杂 SVG、描边、拼图、钥匙扣、冰箱贴、单双面、5 色扩展、生成下载。

Do not create a PR until the user confirms manual testing is acceptable.

---

## Self-Review

Spec coverage:

- 提速目标: Tasks 6, 7, 11 cover footprint-based V2 and profiling.
- 完整兼容: Tasks 3, 4, 8, 10 cover V1 parity, naming, backing, Outline, bounds-sensitive overlays.
- V1 fallback: Tasks 5, 7, 8 cover default V1 and runtime fallback.
- 本地灰度: Task 12 covers `LUMINA_VECTOR_GLB_KERNEL=v2`.
- 不碰用户耗材数据: Scope And Safety plus Task 13 status guard.

Known first-implementation boundary:

- Fridge magnet cavities and coating are forced to V1 in this plan until their exact footprint/cavity descriptors are added. This is intentional because a fast but missing cavity GLB would violate the compatibility requirement.
- The generate path still builds the full vector scene for 3MF. Therefore first measurable win may show strongest in `export_glb_s` and preview-model rebuild paths; full `generate` total time improves only if GLB export was a meaningful part of that request.
