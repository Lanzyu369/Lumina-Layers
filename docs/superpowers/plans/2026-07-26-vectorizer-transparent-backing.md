# Vectorizer Transparent Backing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make transparent image-to-vector inputs generate an irregular physical backing while preserving the full source canvas for puzzle-overlay coordinates.

**Architecture:** Keep `VectorAnalysis.image_vectorizer_bounds` as coordinate metadata and derive all physical backing geometry from the visible `silhouette`, with clipped-shape union as the fallback. Add the full canvas to vector GLB previews as the same transparent `preview_canvas_bounds` anchor already consumed by the frontend raster-preview path.

**Tech Stack:** Python 3, Shapely, NumPy, trimesh, pytest, FastAPI, React/Three.js, Playwright browser verification

---

## File Map

- Modify `core/vector_engine.py`: centralize physical backing geometry selection and use it for 3MF/coating and 2D preview masks.
- Modify `core/pipeline/vector_glb_preview.py`: keep descriptor backing physical and append a transparent full-canvas GLB anchor.
- Modify `core/pipeline/s11_glb_preview.py`: widen the existing private canvas-mesh helper's numeric input type so vector and raster previews can share it.
- Modify `tests/test_vector_engine_unit.py`: regress physical Board/Coating and 2D backing-mask behavior.
- Modify `tests/test_vector_glb_v2_parity_unit.py`: regress analysis-descriptor backing footprint semantics.
- Modify `tests/test_vector_glb_v2_kernel_unit.py`: regress V1/V2 dispatch of the transparent canvas anchor.
- Use `frontend/src/__tests__/PuzzleOverlay3D.test.ts` unchanged as the existing frontend contract test for preferring `previewCanvasBounds`.

### Task 1: Make all physical backing paths use visible geometry

**Files:**
- Modify: `tests/test_vector_engine_unit.py`
- Modify: `core/vector_engine.py`

- [ ] **Step 1: Change the mesh regression test so full-canvas metadata must remain non-physical**

Replace `test_image_vectorizer_bounds_make_board_and_coating_complete` with:

```python
def test_image_vectorizer_bounds_do_not_fill_transparent_board_or_coating(self):
    processor = _make_parse_only_processor()
    processor.color_mode = "4-Color"
    processor.enable_coating = True
    left = box(0, 0, 4, 20)
    right = box(16, 0, 20, 20)
    visible_silhouette = left.union(right)
    full_bounds = box(0, 0, 20, 20)
    analysis = VectorAnalysis(
        shape_data=[],
        clipped_shapes=[
            {"geometry": left, "color": (255, 0, 0), "draw_order": 0},
            {"geometry": right, "color": (0, 255, 255), "draw_order": 1},
        ],
        matched_shapes=[
            {"geometry": left, "recipe": [1, 1, 1, 1, 1], "color": (255, 0, 0)},
            {"geometry": right, "recipe": [1, 1, 1, 1, 1], "color": (0, 255, 255)},
        ],
        silhouette=visible_silhouette,
        scale_factor=1.0,
        bbox=(0.0, 0.0, 20.0, 20.0),
        color_conf={},
        slot_names=["White", "Cyan"],
        num_channels=2,
        num_layers=5,
        preview_colors={0: [255, 255, 255, 255], 1: [0, 255, 255, 255]},
        stage_timings={},
        image_vectorizer_bounds=full_bounds,
    )

    scene = processor.build_mesh(
        analysis=analysis,
        thickness_mm=1.2,
        structure_mode="Single-sided",
    )
    board = scene.geometry["Board"]
    coating = scene.geometry["Coating"]

    assert len(board.split(only_watertight=False)) == 2
    assert len(coating.split(only_watertight=False)) == 2
    assert board.volume < 250.0
    assert coating.volume < 25.0
```

- [ ] **Step 2: Change the 2D preview regression so a transparent canvas corner stays Air**

Rename `test_preview_cache_backing_mask_extends_past_visible_shapes` to
`test_preview_cache_backing_mask_excludes_transparent_canvas` and replace its
last assertions with:

```python
assert "backing_mask" in cache
assert cache["backing_mask"].shape == cache["mask_solid"].shape
assert cache["backing_mask"][100, 100]
assert not cache["backing_mask"][10, 10]
```

- [ ] **Step 3: Run the two tests and verify the current implementation fails**

Run:

```bash
python -m pytest \
  tests/test_vector_engine_unit.py::TestVectorPreviewBackingMaskRegression::test_preview_cache_backing_mask_excludes_transparent_canvas \
  tests/test_vector_engine_unit.py::TestVectorCoatingBuildMeshRegression::test_image_vectorizer_bounds_do_not_fill_transparent_board_or_coating \
  -v
```

Expected: both tests fail because `image_vectorizer_bounds` currently fills the whole 20×20 canvas.

- [ ] **Step 4: Add one physical-geometry resolver next to `VectorAnalysis`**

Add to `core/vector_engine.py`:

```python
def _physical_backing_geometry(analysis: object):
    """Return printable visible geometry, excluding coordinate-only canvas bounds.
    返回可打印的可见几何，不包含仅用于坐标定位的完整画布边界。
    """

    silhouette = getattr(analysis, "silhouette", None)
    if silhouette is not None and not getattr(silhouette, "is_empty", True):
        return silhouette

    clipped_geometries = [
        item.get("geometry")
        for item in (getattr(analysis, "clipped_shapes", None) or [])
        if isinstance(item, dict)
        and item.get("geometry") is not None
        and not item.get("geometry").is_empty
    ]
    return unary_union(clipped_geometries) if clipped_geometries else None
```

- [ ] **Step 5: Use the resolver in mesh and preview-cache generation**

In `VectorProcessor.build_mesh()`, initialize:

```python
silhouette = _physical_backing_geometry(analysis)
```

and delete the Stage 6 block that replaces it with
`analysis.image_vectorizer_bounds` or repeats the clipped-shape union.

In `VectorProcessor.render_preview()`, replace the `image_vectorizer_bounds`
backing selection and repeated clipped-shape union with:

```python
backing_geom = _physical_backing_geometry(analysis)
```

- [ ] **Step 6: Run focused engine tests and verify they pass**

Run:

```bash
python -m pytest \
  tests/test_vector_engine_unit.py::TestVectorPreviewBackingMaskRegression \
  tests/test_vector_engine_unit.py::TestVectorCoatingBuildMeshRegression \
  tests/test_vector_engine_fixes_unit.py::TestImageVectorizerViewportBounds \
  -v
```

Expected: PASS; marked SVGs still retain viewport metadata, while Board, Coating, and `backing_mask` use visible geometry.

- [ ] **Step 7: Commit the physical backing fix**

```bash
git add core/vector_engine.py tests/test_vector_engine_unit.py
git commit -m "fix(vector): keep transparent canvas out of backing"
```

### Task 2: Keep descriptor-based backing physical

**Files:**
- Modify: `tests/test_vector_glb_v2_parity_unit.py`
- Modify: `core/pipeline/vector_glb_preview.py`

- [ ] **Step 1: Change the V2 parity expectations from canvas bounds to visible bounds**

Rename `test_v2_backing_uses_image_vectorizer_bounds_for_preview_canvas_alignment`
to `test_v2_backing_uses_visible_silhouette_not_preview_canvas_bounds` and assert:

```python
assert backing.extrusions[0].footprint.bounds == pytest.approx(
    (3.85, 3.85, 16.15, 16.15)
)
```

In `test_v2_backing_expansion_matches_v1_scale_factor_order`, change the expected
bounds to:

```python
assert backing.extrusions[0].footprint.bounds == pytest.approx(
    (3.7, 3.7, 16.3, 16.3)
)
```

- [ ] **Step 2: Run the two parity tests and verify they fail**

Run:

```bash
python -m pytest \
  tests/test_vector_glb_v2_parity_unit.py::test_v2_backing_uses_visible_silhouette_not_preview_canvas_bounds \
  tests/test_vector_glb_v2_parity_unit.py::test_v2_backing_expansion_matches_v1_scale_factor_order \
  -v
```

Expected: FAIL with full-canvas bounds from `_analysis_backing_footprint()`.

- [ ] **Step 3: Remove coordinate metadata from descriptor backing selection**

Replace `_analysis_backing_footprint()` with:

```python
def _analysis_backing_footprint(
    analysis: object,
    scale_factor: float,
    fallback_silhouette: BaseGeometry | None,
) -> BaseGeometry | None:
    del analysis
    if fallback_silhouette is not None:
        return _prepare_backing_footprint(fallback_silhouette, scale_factor)
    return None
```

- [ ] **Step 4: Run parity tests and verify they pass**

Run:

```bash
python -m pytest tests/test_vector_glb_v2_parity_unit.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit descriptor parity**

```bash
git add core/pipeline/vector_glb_preview.py tests/test_vector_glb_v2_parity_unit.py
git commit -m "fix(vector): keep preview backing on visible footprint"
```

### Task 3: Preserve full-canvas puzzle coordinates with an invisible GLB anchor

**Files:**
- Modify: `tests/test_vector_glb_v2_kernel_unit.py`
- Modify: `core/pipeline/vector_glb_preview.py`
- Modify: `core/pipeline/s11_glb_preview.py`

- [ ] **Step 1: Add a V1/V2 dispatch regression for the transparent anchor**

Add to `tests/test_vector_glb_v2_kernel_unit.py`:

```python
@pytest.mark.parametrize(
    ("kernel", "exporter_name"),
    [
        ("trimesh_v1", "export_vector_glb_preview_v1"),
        ("v2", "export_vector_glb_preview_v2_scene_reuse"),
    ],
)
def test_export_dispatch_adds_transparent_preview_canvas_anchor(
    monkeypatch,
    tmp_path: Path,
    kernel: str,
    exporter_name: str,
) -> None:
    scene = trimesh.Scene()
    scene.add_geometry(_box_mesh(), geom_name="Red")
    analysis = _analysis_for_v2_test()
    analysis.image_vectorizer_bounds = box(2, 3, 18, 11)
    analysis.scale_factor = 2.0
    captured: list[vector_glb_preview.VectorPreviewPart] = []

    def capture(parts, *, output_path):
        captured.extend(parts)
        Path(output_path).write_bytes(b"glb")
        return output_path

    monkeypatch.setenv("LUMINA_VECTOR_GLB_KERNEL", kernel)
    monkeypatch.setattr(vector_glb_preview, exporter_name, capture)

    vector_glb_preview.export_vector_glb_preview(
        scene=scene,
        output_path=str(tmp_path / "preview.glb"),
        structure_mode="Single-sided",
        color_mode="4-Color (RYBW)",
        preview_colors={"Red": [255, 0, 0, 255]},
        slot_list=["Red"],
        analysis=analysis,
        ctx={},
    )

    anchor = next(
        part for part in captured if part.export_name == "preview_canvas_bounds"
    )
    assert anchor.role == "auxiliary"
    assert anchor.rgba == (0, 0, 0, 0)
    assert anchor.fallback_mesh is not None
    assert anchor.fallback_mesh.bounds == pytest.approx(
        [[4.0, 6.0, 0.0], [36.0, 22.0, 0.0]]
    )
```

- [ ] **Step 2: Run the anchor regression and verify it fails**

Run:

```bash
python -m pytest \
  tests/test_vector_glb_v2_kernel_unit.py::test_export_dispatch_adds_transparent_preview_canvas_anchor \
  -v
```

Expected: FAIL because vector GLB dispatch currently ignores `analysis`.

- [ ] **Step 3: Generalize the existing raster canvas helper for vector dimensions**

In `core/pipeline/s11_glb_preview.py`, change the private helper signature without
changing its behavior:

```python
def _build_preview_canvas_bounds_mesh(
    width: float,
    height: float,
    pixel_scale: float,
) -> Optional[trimesh.Trimesh]:
```

- [ ] **Step 4: Build a transparent vector canvas part from analysis metadata**

Import `PREVIEW_CANVAS_BOUNDS_NODE_NAME` and
`_build_preview_canvas_bounds_mesh` into `core/pipeline/vector_glb_preview.py`,
then add:

```python
def _build_preview_canvas_anchor_part(
    analysis: object | None,
) -> VectorPreviewPart | None:
    """Build coordinate-only canvas geometry for frontend overlay placement.
    构建仅用于前端叠线定位的画布坐标几何。
    """

    if analysis is None:
        return None
    canvas = _valid_geometry(getattr(analysis, "image_vectorizer_bounds", None))
    if canvas is None:
        return None
    try:
        scale_factor = float(getattr(analysis, "scale_factor", 1.0) or 1.0)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(scale_factor) or scale_factor <= 0:
        return None

    min_x, min_y, max_x, max_y = (float(value) for value in canvas.bounds)
    width = max_x - min_x
    height = max_y - min_y
    mesh = _build_preview_canvas_bounds_mesh(width, height, scale_factor)
    if mesh is None:
        return None
    mesh.apply_translation((min_x * scale_factor, min_y * scale_factor, 0.0))
    return VectorPreviewPart(
        source_name=PREVIEW_CANVAS_BOUNDS_NODE_NAME,
        export_name=PREVIEW_CANVAS_BOUNDS_NODE_NAME,
        role="auxiliary",
        rgba=(0, 0, 0, 0),
        is_recolorable=False,
        fallback_mesh=mesh,
    )
```

- [ ] **Step 5: Append the anchor after scene parts are built**

In `export_vector_glb_preview()` add:

```python
canvas_anchor = _build_preview_canvas_anchor_part(analysis)
if (
    canvas_anchor is not None
    and all(
        part.export_name != PREVIEW_CANVAS_BOUNDS_NODE_NAME
        for part in fallback_parts
    )
):
    fallback_parts.append(canvas_anchor)
```

Keep this before both the V1 branch and the default V2 scene-reuse branch so
both serializers receive the same coordinate-only part.

- [ ] **Step 6: Run backend and frontend coordinate-contract tests**

Run:

```bash
python -m pytest \
  tests/test_vector_glb_v2_kernel_unit.py \
  tests/test_vector_glb_v2_parity_unit.py \
  tests/test_segmented_glb_unit.py::TestSingleColorImage::test_vector_preview_glb_exports_canvas_bounds_anchor_for_puzzle_overlay \
  -v
python scripts/run_vitest.py run src/__tests__/PuzzleOverlay3D.test.ts
```

Expected: PASS; V1/V2 vector GLBs receive the anchor and the frontend prefers it over cropped model bounds.

- [ ] **Step 7: Commit the GLB coordinate anchor**

```bash
git add \
  core/pipeline/s11_glb_preview.py \
  core/pipeline/vector_glb_preview.py \
  tests/test_vector_glb_v2_kernel_unit.py
git commit -m "fix(preview): separate vector canvas coordinate anchor"
```

### Task 4: Regression gates and real-user verification

**Files:**
- Verify only; no source file changes expected.
- Input: `/Users/min/Downloads/Totem_of_Undying_JE2_BE2.png`

- [ ] **Step 1: Run the focused converter regression suite**

Run:

```bash
python -m pytest \
  tests/test_vector_engine_unit.py \
  tests/test_vector_engine_fixes_unit.py::TestImageVectorizerViewportBounds \
  tests/test_vector_glb_v2_kernel_unit.py \
  tests/test_vector_glb_v2_parity_unit.py \
  tests/test_vector_outline_pipeline_properties.py \
  -v
```

Expected: PASS.

- [ ] **Step 2: Run repository smoke gates**

Run:

```bash
python scripts/run_smoke_tests.py
python scripts/log_quality_check.py --mode fast
git diff --check HEAD~3..HEAD
```

Expected: PASS with no whitespace or structured-logging regression.

- [ ] **Step 3: Start the local product and simulate the user flow**

Start the app with `python start_all.py`, then use a 1600×900 browser viewport to:

1. Open the converter as a normal user.
2. Upload `/Users/min/Downloads/Totem_of_Undying_JE2_BE2.png`.
3. Choose image-to-vector conversion using the normal UI controls.
4. Keep the reported issue's default 60 mm target width and 4-color RYBW/Bambu material flow.
5. Wait for the vector preview, enable the puzzle overlay once, and inspect the complete-canvas alignment.
6. Generate the model, wait for completion, and download the resulting 3MF through the displayed link.

Expected: no visible white rectangle around the totem; puzzle coordinates still span the original square canvas.

- [ ] **Step 4: Inspect the generated GLB and downloaded 3MF**

Load the newest generated GLB and downloaded 3MF with trimesh:

```bash
GLB_PATH="$(find output -type f -name '*.glb' -print0 | xargs -0 ls -t | head -n 1)"
THREEMF_PATH="$(find /Users/min/Downloads -type f -name '*.3mf' -print0 | xargs -0 ls -t | head -n 1)"
export GLB_PATH THREEMF_PATH
python - <<'PY'
import os
import trimesh


def world_mesh(scene: trimesh.Scene, expected_name: str) -> trimesh.Trimesh:
    for node_name in scene.graph.nodes_geometry:
        transform, geometry_name = scene.graph[node_name]
        if expected_name in {str(node_name), str(geometry_name)}:
            mesh = scene.geometry[geometry_name].copy()
            mesh.apply_transform(transform)
            return mesh
    raise AssertionError(f"missing geometry: {expected_name}")


glb_scene = trimesh.load(os.environ["GLB_PATH"], force="scene")
canvas = world_mesh(glb_scene, "preview_canvas_bounds")
backing = world_mesh(glb_scene, "backing_plate")
canvas_extents = canvas.bounds[1] - canvas.bounds[0]
backing_extents = backing.bounds[1] - backing.bounds[0]
assert 59.9 <= canvas_extents[0] <= 60.1
assert 59.9 <= canvas_extents[1] <= 60.1
assert backing_extents[0] < 59.0
assert backing_extents[1] < 59.0

model_scene = trimesh.load(os.environ["THREEMF_PATH"], force="scene")
solid_extents = [
    geometry.bounds[1] - geometry.bounds[0]
    for geometry in model_scene.geometry.values()
    if len(getattr(geometry, "vertices", ())) > 0
]
assert solid_extents
assert not any(extent[0] >= 59.0 and extent[1] >= 59.0 for extent in solid_extents)
print(
    {
        "glb_canvas_extents": canvas_extents.tolist(),
        "glb_backing_extents": backing_extents.tolist(),
        "3mf_geometry_extents": [extent.tolist() for extent in solid_extents],
    }
)
PY
```

Record the actual Board bounds, area/volume, GLB anchor bounds, downloaded file
path, and screenshots in the final verification report.

- [ ] **Step 5: Stop all processes and verify cleanup**

Run:

```bash
python start_all.py --kill
```

Then inspect process command lines for this worktree's `api_server.py`,
`start_all.py`, `vite`, `vitest`, and `esbuild`.

Expected: no process started for this verification remains alive.

- [ ] **Step 6: Commit any test-only adjustment discovered during real verification**

Only if the real flow exposes a missing deterministic assertion, add that
assertion to the nearest existing regression test and commit it with:

```bash
git add tests
git commit -m "test(vector): cover transparent image conversion"
```
