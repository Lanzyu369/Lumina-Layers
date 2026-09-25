"""SVG vector outline support / Tasks 1.3 + 1.4

Archived context: ``progress/svg-vector-outline-counterexamples.md`` and
``progress/svg-vector-outline-fix-verification.md``.

Property 1: vector / SVG 模式下 enable_outline=true 时，最终 generate 必须
生成可导出的 ``Outline`` 几何；quick preview 则不得缓存或内嵌这份导出几何，
由前端实时 Outline overlay 单一负责预览。

Bug condition methodology:
    * generate/export 的 Outline 使用 3MF writer-local 坐标，不能直接混入
      正坐标的 segmented quick-preview GLB。
    * quick preview 已有参数驱动的前端 OutlineFrame3D；再嵌入实体会形成重复
      ownership，并让旧导出坐标参与场景居中。

工单引用：LUM-20260527-001 ("svg 加不了描边")。

Validates: Requirements 1.2, 1.3, 2.2, 2.3
"""

from __future__ import annotations

import os
import sys
import tempfile
from typing import Iterable
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import trimesh
from hypothesis import given, settings, strategies as st
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

# Ensure project root is importable when running the file directly via pytest.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


# ---------------------------------------------------------------------------
# Fixture paths and SVG content
# ---------------------------------------------------------------------------

_FIXTURE_SVG = os.path.join(
    _ROOT, "tests", "fixtures", "svg_vector", "simple_rect.svg"
)


# ---------------------------------------------------------------------------
# Synthetic geometry helpers
# ---------------------------------------------------------------------------


def _matched_shapes_for_fixture() -> list[dict]:
    """Return shapely-backed ``matched_shapes`` mirroring ``simple_rect.svg``.

    These polygons are the ground truth for the 'ring vs fill' assertion in
    Task 1.3. The fixed vector branch (Task 3.3) will derive the outline ring
    from ``unary_union(matched_shapes)``; the test verifies the resulting ring
    does not overlap that union.

    返回与 ``simple_rect.svg`` 对应的 shapely 几何，作为 "ring 不是 fill"
    断言的真值。Task 3.3 修复后 vector 分支将从 ``matched_shapes union`` 派生
    outline ring，本测试据此校验 ring 不应覆盖 union 内部。
    """
    rect = box(10.0, 10.0, 50.0, 50.0)  # x,y,w,h = 10,10,40,40
    circle = Polygon(
        [
            (
                70.0 + 15.0 * np.cos(theta),
                30.0 + 15.0 * np.sin(theta),
            )
            for theta in np.linspace(0.0, 2.0 * np.pi, 64, endpoint=False)
        ]
    )
    return [
        {
            "geometry": rect,
            "color": (255, 0, 0),
            "matched_rgb": (255, 0, 0),
            "recipe": [1, 0, 0, 0],
            "draw_order": 0,
        },
        {
            "geometry": circle,
            "color": (0, 0, 255),
            "matched_rgb": (0, 0, 255),
            "recipe": [2, 0, 0, 0],
            "draw_order": 1,
        },
    ]


def _build_fake_processor(
    scene: trimesh.Scene,
    color_mode: str,
    *,
    matched_shapes: list[dict] | None = None,
) -> MagicMock:
    """Return a MagicMock that behaves like ``VectorProcessor``.

    Mirrors ``tests/test_converter_vector_export_unit.py::_build_fake_processor``
    so the two suites stay in lock-step. Copied (not imported) on purpose to
    avoid cross-test coupling.
    复刻 vector export 单测里的假处理器，刻意不直接 import 以避免跨文件耦合。
    """
    vp = MagicMock()
    vp.svg_to_mesh.return_value = scene
    vp.img_processor.lut_rgb = np.zeros((256, 3))
    vp.img_processor._load_svg.return_value = np.zeros((100, 100, 4), dtype=np.uint8)
    vp.color_mode = color_mode
    vp.sampling_precision = 1.0
    vp.expand_stroke_to_fill = False
    vp.gradient_color_bands = None

    fake_analysis = SimpleNamespace()
    fake_analysis.preview_colors = {
        0: [255, 255, 255, 255],
        1: [255, 0, 0, 255],
        2: [0, 0, 255, 255],
        3: [0, 0, 0, 255],
    }
    fake_analysis.slot_names = ["White", "Red", "Blue", "Black"]
    fake_analysis.stage_timings = {}
    fake_analysis.matched_shapes = (
        list(matched_shapes) if matched_shapes is not None else []
    )
    fake_analysis.clipped_shapes = list(fake_analysis.matched_shapes)
    fake_analysis.shape_data = list(fake_analysis.matched_shapes)
    fake_analysis.silhouette = (
        unary_union(
            [shape["geometry"] for shape in fake_analysis.matched_shapes]
        )
        if fake_analysis.matched_shapes
        else Polygon()
    )
    fake_analysis.image_vectorizer_bounds = None
    fake_analysis.scale_factor = 1.0
    fake_analysis.bbox = (0.0, 0.0, 100.0, 100.0)
    fake_analysis.color_conf = None
    fake_analysis.num_layers = 4
    fake_analysis.scale_factor = 1.0
    fake_analysis.clipped_shapes = fake_analysis.matched_shapes
    fake_analysis.silhouette = unary_union([s["geometry"] for s in fake_analysis.matched_shapes])
    fake_analysis.image_vectorizer_bounds = None
    vp.analyze_svg.return_value = fake_analysis
    vp.build_mesh.return_value = scene
    vp.render_preview = MagicMock(return_value=np.zeros((100, 100, 4), dtype=np.uint8))
    return vp


def _make_base_scene() -> trimesh.Scene:
    """Build a minimal scene that has base material slots but no Outline.

    构造仅含底色 slot、不含 Outline 节点的最小 scene，模拟当前 main 的
    vector 分支输出。
    """
    scene = trimesh.Scene()
    for name in ("White", "Red", "Blue"):
        mesh = trimesh.creation.box(extents=[5.0, 5.0, 0.5])
        mesh.metadata["name"] = name
        scene.add_geometry(mesh, geom_name=name)
    return scene


def _build_material_archive_outline_bridge_fixture() -> tuple[MagicMock, trimesh.Scene]:
    """Build a fake material-archive vector processor for bridge tests."""
    shape = box(10.0, 15.0, 70.0, 60.0)
    matched_shapes = [
        {
            "geometry": shape,
            "color": (255, 0, 0),
            "matched_rgb": (255, 0, 0),
            "recipe": [1, 0, 0, 0, 0, 0],
            "draw_order": 0,
        }
    ]

    scene = trimesh.Scene()
    body_mesh = trimesh.creation.box(extents=[10.0, 10.0, 0.5])
    body_mesh.metadata["name"] = "Red"
    body_mesh.visual.face_colors = [255, 0, 0, 255]
    scene.add_geometry(body_mesh, geom_name="Red")

    analysis = SimpleNamespace()
    analysis.preview_colors = {
        0: [255, 255, 255, 255],
        1: [255, 0, 0, 255],
        2: [0, 0, 255, 255],
        3: [0, 0, 0, 255],
        4: [0, 255, 0, 255],
    }
    analysis.slot_names = ["White", "Red", "Blue", "Black", "Green"]
    analysis.stage_timings = {}
    analysis.matched_shapes = matched_shapes
    analysis.clipped_shapes = matched_shapes
    analysis.silhouette = shape
    analysis.color_conf = None
    analysis.num_layers = 6
    analysis.scale_factor = 1.0
    analysis.bbox = (0.0, 0.0, 100.0, 80.0)
    analysis.shape_data = matched_shapes
    analysis.image_vectorizer_bounds = None

    processor = MagicMock()
    processor.color_mode = "Material Archive"
    processor.parse_warnings = []
    processor.last_stage_timings = {}
    processor.sampling_precision = 1.0
    processor.expand_stroke_to_fill = False
    processor.gradient_color_bands = None
    processor.img_processor = MagicMock()
    processor.analyze_svg.return_value = analysis
    processor.build_mesh.return_value = scene
    return processor, scene


def _assert_material_archive_outline_mirrored(outline_mesh: trimesh.Trimesh) -> None:
    """Assert Outline uses the body's translation-free axis flips."""
    assert outline_mesh is not None
    assert float(outline_mesh.bounds[0, 0]) == pytest.approx(-75.15)
    assert float(outline_mesh.bounds[1, 0]) == pytest.approx(-4.85)
    assert float(outline_mesh.bounds[0, 1]) == pytest.approx(-65.15)
    assert float(outline_mesh.bounds[1, 1]) == pytest.approx(-9.85)


def _outline_xy_footprint(mesh: trimesh.Trimesh) -> object:
    """Return the XY footprint of an outline mesh as a shapely geometry.

    Triangulates each face onto the XY plane and unions them. This matches
    how raster ``_generate_outline_mesh`` builds rings out of dilated /
    subtracted masks: the mesh shadow on z=0 is the actual ring, not the
    convex hull.

    取每个三角面的 XY 投影并求并集，得到 outline mesh 在 z=0 平面上的真实
    投影面积（即 ring 形状），不是 convex hull。
    """
    if mesh is None or len(getattr(mesh, "faces", [])) == 0:
        return Polygon()
    triangles = []
    verts = np.asarray(mesh.vertices)
    for face in np.asarray(mesh.faces):
        pts = verts[face][:, :2]
        try:
            poly = Polygon(pts)
        except (ValueError, TypeError):
            continue
        if poly.is_valid and not poly.is_empty:
            triangles.append(poly)
    if not triangles:
        return Polygon()
    # ``buffer(0)`` heals self-intersecting unions caused by floating-point
    # vertex coincidences across adjacent triangles.
    return unary_union(triangles).buffer(0)


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------


_OUTLINE_WIDTH = st.floats(
    min_value=0.5, max_value=10.0, allow_nan=False, allow_infinity=False
)
# The canonical color-mode strings recognised by ``ColorSystem.get_color_system``.
# 与 ColorSystem.get_color_system 接受的标识保持一致。
_COLOR_MODE = st.sampled_from(["BW", "4-Color RYBW", "8-Color Max"])
_BASE_CHANNEL_IDX = st.sampled_from([0, 1, 2])  # exercise both 0 and non-zero


# ---------------------------------------------------------------------------
# Task 1.3 — Generate path must contain `Outline` geometry
# ---------------------------------------------------------------------------


def _run_generate_with_mocks(
    *,
    svg_path: str,
    lut_path: str,
    outline_width: float,
    color_mode: str,
    base_channel_idx: int,
) -> trimesh.Scene:
    """Drive ``convert_image_to_3d`` through the vector branch and return the
    scene that would be exported as 3MF.

    通过 vector 分支跑一遍 ``convert_image_to_3d``，返回被 Bambu 导出的 scene。
    """
    from config import ModelingMode
    from core.converter import convert_image_to_3d

    fake_scene = _make_base_scene()
    matched_shapes = _matched_shapes_for_fixture()

    with patch(
        "utils.bambu_3mf_writer.export_scene_with_bambu_metadata"
    ) as mock_bambu_export, patch(
        "core.vector_engine.VectorProcessor"
    ) as MockVP:
        MockVP.return_value = _build_fake_processor(
            fake_scene, color_mode, matched_shapes=matched_shapes
        )
        # ``MaterialVectorMatcher`` is only consulted when material_source ==
        # "material_archive"; we stay on the LUT path here so the additional
        # patch is unnecessary.

        convert_image_to_3d(
            image_path=svg_path,
            lut_path=lut_path,
            target_width_mm=100.0,
            spacer_thick=1.6,
            structure_mode="Single-sided",
            color_mode=color_mode,
            add_loop=False,
            loop_width=5,
            loop_length=20,
            loop_hole=3,
            loop_pos="Top",
            modeling_mode=ModelingMode.VECTOR,
            backing_color_id=int(base_channel_idx),
            enable_outline=True,
            outline_width=float(outline_width),
        )

        if mock_bambu_export.call_count == 0:
            pytest.fail(
                "vector branch should reach export_scene_with_bambu_metadata; "
                "did the pipeline error out earlier?"
            )
        return mock_bambu_export.call_args.kwargs["scene"]


def _assert_outline_geometry_properties(
    exported_scene: trimesh.Scene,
    matched_shapes: Iterable[dict],
    *,
    outline_width: float,
    color_mode: str,
    base_channel_idx: int,
) -> None:
    """Assert all three Task 1.3 properties on a vector-exported scene.

    一次性校验 Task 1.3 中三条断言：节点存在、material 元数据非空、ring
    与 matched_shapes union 不重叠。
    """
    # (1) Outline node is present.
    assert "Outline" in exported_scene.geometry, (
        f"Expected 'Outline' geometry in vector scene "
        f"(outline_width={outline_width}, color_mode={color_mode}, "
        f"base_channel_idx={base_channel_idx}); "
        f"got {sorted(exported_scene.geometry.keys())}"
    )
    outline_geom = exported_scene.geometry["Outline"]

    # (2) Outline carries a non-empty bambu_material_name.
    bambu_name = outline_geom.metadata.get("bambu_material_name")
    assert bambu_name, (
        "Outline mesh must carry a non-empty bambu_material_name "
        f"(got {bambu_name!r})"
    )

    # (3) Ring vs matched_shapes union: intersection area ~= 0 (ring, not fill).
    union = unary_union(
        [s["geometry"] for s in matched_shapes if s.get("geometry") is not None]
    )
    if union.is_empty:
        pytest.fail(
            "matched_shapes union is empty — fixture is misconfigured; "
            "cannot evaluate ring-vs-union property"
        )

    outline_footprint = _outline_xy_footprint(outline_geom)
    if outline_footprint.is_empty:
        pytest.fail(
            "Outline mesh has empty XY footprint — cannot evaluate ring "
            "property; mesh has "
            f"{len(outline_geom.vertices)} verts / {len(outline_geom.faces)} faces"
        )

    inter_area = outline_footprint.intersection(union).area
    union_area = float(union.area)
    # A real ring should overlap with the union by at most a thin sliver
    # introduced by floating-point rasterisation. 10% of union.area is a
    # generous tolerance — a "fill" outline would show ~100%.
    # 真正的 ring 与 union 的相交面积应该接近 0；10% 的 union 面积已经是
    # 非常宽松的容差，"fill" 形状会接近 100%。
    assert inter_area <= 0.1 * union_area, (
        f"Outline must be a ring, not a fill: intersection_area={inter_area:.3f} "
        f"vs union_area={union_area:.3f} (ratio={inter_area / union_area:.3f}); "
        f"outline_width={outline_width}, color_mode={color_mode}, "
        f"base_channel_idx={base_channel_idx}"
    )


@pytest.mark.parametrize(
    ("structure_mode", "color_passes"),
    [("Single-sided", 1), ("Double-sided", 2)],
)
def test_vector_outline_height_matches_structure_mode(
    structure_mode: str, color_passes: int
) -> None:
    """Vector Outline must span the full model height for single/double side.

    Regression anchor for manual finding after Task 4: double-sided SVG output
    showed an Outline mesh shorter than the overall model because the helper
    used only ``spacer_thick``. Expected height mirrors ``build_mesh``:
    backing height + one colour stack for single-sided, backing height + two
    colour stacks for double-sided.

    双面 SVG 手测发现 Outline 高度只等于底板厚度，低于整体模型高度。本测试
    锁定：单面为底板 + 1 组彩色层，双面为底板 + 2 组彩色层。
    """
    from config import PrinterConfig
    from core.pipeline.vector_branch import _generate_vector_outline_mesh

    analysis = SimpleNamespace()
    analysis.matched_shapes = _matched_shapes_for_fixture()
    analysis.scale_factor = 1.0
    analysis.num_layers = 4
    ctx = {
        "spacer_thick": 1.6,
        "structure_mode": structure_mode,
        "color_mode": "8-Color Max",
        "enable_coating": False,
    }

    outline_mesh = _generate_vector_outline_mesh(
        analysis=analysis,
        outline_width_mm=2.0,
        base_aux_color=[255, 255, 255, 255],
        base_aux_material_name="White",
        ctx=ctx,
    )

    assert outline_mesh is not None
    layer_h = float(PrinterConfig.LAYER_HEIGHT)
    backing_height = max(1, int(round(1.6 / layer_h))) * layer_h
    expected_height = backing_height + color_passes * analysis.num_layers * layer_h

    assert float(outline_mesh.bounds[0, 2]) == pytest.approx(0.0)
    assert float(outline_mesh.bounds[1, 2]) == pytest.approx(expected_height)


def test_vector_outline_uses_one_canonical_build_and_runtime_guards() -> None:
    """Outline preparation stays on the unified physical-grid path."""

    from core.pipeline import vector_branch
    from core.pipeline.vector_branch import _generate_vector_outline_mesh

    analysis = MagicMock()
    analysis.matched_shapes = _matched_shapes_for_fixture()
    analysis.scale_factor = 1.0
    analysis.num_layers = 4
    analysis.bbox = (0.0, 0.0, 100.0, 80.0)
    ctx = {
        "spacer_thick": 1.6,
        "structure_mode": "Single-sided",
        "color_mode": "8-Color Max",
        "enable_coating": False,
    }

    with (
        patch(
            "core.vector_engine._enforce_vector_mesh_runtime_headroom",
        ) as guard_mock,
        patch(
            "core.pipeline.vector_branch.build_vector_layered_volume",
            wraps=vector_branch.build_vector_layered_volume,
        ) as build_mock,
    ):
        outline_mesh = _generate_vector_outline_mesh(
            analysis=analysis,
            outline_width_mm=2.0,
            base_aux_color=[255, 255, 255, 255],
            base_aux_material_name="White",
            ctx=ctx,
        )

    assert outline_mesh is not None
    build_mock.assert_called_once()
    stages = {call.kwargs["stage"] for call in guard_mock.call_args_list}
    assert "vector_outline_union" in stages
    assert "vector_outline_ring" in stages
    assert "vector_outline_canonical_geometry" in stages


def test_double_sided_vector_outline_stays_between_coating_faces() -> None:
    """Material vector outlines must use export mode and effective layer height."""
    from core.pipeline.vector_branch import _generate_vector_outline_mesh

    analysis = MagicMock()
    analysis.matched_shapes = _matched_shapes_for_fixture()
    analysis.scale_factor = 1.0
    analysis.num_layers = 4
    layer_height = 0.10
    coating_height = layer_height * 2
    ctx = {
        "spacer_thick": 1.6,
        "structure_mode": "Double-sided",
        "color_mode": "5-Color Extended",
        "material_source": "material_archive",
        "layer_height_mm": layer_height,
        "enable_coating": True,
        "coating_height_mm": coating_height,
    }

    outline_mesh = _generate_vector_outline_mesh(
        analysis=analysis,
        outline_width_mm=2.0,
        base_aux_color=[255, 255, 255, 255],
        base_aux_material_name="White",
        ctx=ctx,
        export_color_mode="Material Archive",
    )

    assert outline_mesh is not None
    backing_height = max(1, int(round(1.6 / layer_height))) * layer_height
    model_height = backing_height + 2 * analysis.num_layers * layer_height
    assert float(outline_mesh.bounds[0, 2]) == pytest.approx(0.0)
    assert float(outline_mesh.bounds[1, 2]) == pytest.approx(
        model_height
    )


def test_vector_outline_miter_spikes_stay_within_requested_width() -> None:
    """Acute SVG corners must not create outline tabs wider than requested.

    Manual regression: a Vector Magic SVG produced a white tab near the
    top-right border because Shapely's miter buffer extended past the normal
    ``outline_width`` envelope. The visible outline should stay inside
    ``source_bounds + outline_width`` even when the source has acute corners.

    手测回归：Vector Magic SVG 的尖角经 miter buffer 后在右上角多出白色凸块。
    这里锁定 outline 不能超过 ``源 bounds + outline_width``。
    """
    from core.pipeline.vector_branch import _generate_vector_outline_mesh

    source = Polygon([(0.0, 0.0), (100.0, 50.0), (0.0, 100.0)])
    analysis = SimpleNamespace()
    analysis.matched_shapes = [
        {
            "geometry": source,
            "color": (255, 0, 0),
            "matched_rgb": (255, 0, 0),
            "recipe": [1, 0, 0, 0],
            "draw_order": 0,
        }
    ]
    analysis.scale_factor = 1.0
    analysis.num_layers = 1
    outline_width = 10.0

    outline_mesh = _generate_vector_outline_mesh(
        analysis=analysis,
        outline_width_mm=outline_width,
        base_aux_color=[255, 255, 255, 255],
        base_aux_material_name="White",
        ctx={
            "spacer_thick": 1.6,
            "structure_mode": "Single-sided",
            "color_mode": "8-Color Max",
            "enable_coating": False,
        },
    )

    assert outline_mesh is not None
    from core.vector_structure import resolve_structure_plan

    min_x, min_y, max_x, max_y = resolve_structure_plan(analysis).body.bounds
    mesh_min_x, mesh_min_y = outline_mesh.bounds[0, :2]
    mesh_max_x, mesh_max_y = outline_mesh.bounds[1, :2]
    eps = 1e-6

    assert float(mesh_min_x) >= min_x - outline_width - eps
    assert float(mesh_min_y) >= min_y - outline_width - eps
    assert float(mesh_max_x) <= max_x + outline_width + eps
    assert float(mesh_max_y) <= max_y + outline_width + eps


def test_vector_outline_matches_single_sided_export_transform() -> None:
    """Single-sided vector Outline must use the same XY transform as body meshes.

    Regression for LUM-20260602-001: the body meshes are flipped from SVG
    Y-down coordinates and mirrored on X for single-sided export, while the
    outline used to stay in raw SVG coordinates. Bambu Studio then showed the
    outline rotated/misaligned relative to the model.

    LUM-20260602-001 回归：单面 vector 主体会做 SVG Y 轴翻转和 X 镜像，
    Outline 也必须做同样变换，否则导出的 3MF 中外轮廓和本体错位。
    """
    from core.pipeline.vector_branch import _generate_vector_outline_mesh

    shape = box(10.0, 15.0, 70.0, 60.0)
    analysis = SimpleNamespace()
    analysis.matched_shapes = [
        {
            "geometry": shape,
            "color": (255, 0, 0),
            "matched_rgb": (255, 0, 0),
            "recipe": [1, 0, 0, 0],
            "draw_order": 0,
        }
    ]
    analysis.scale_factor = 1.0
    analysis.num_layers = 4
    analysis.bbox = (0.0, 0.0, 100.0, 80.0)
    outline_width = 5.0

    outline_mesh = _generate_vector_outline_mesh(
        analysis=analysis,
        outline_width_mm=outline_width,
        base_aux_color=[255, 255, 255, 255],
        base_aux_material_name="PLA White",
        ctx={
            "spacer_thick": 1.6,
            "structure_mode": "Single-sided",
            "color_mode": "4-Color RYBW",
            "material_source": "material_archive",
            "enable_coating": False,
        },
    )

    assert outline_mesh is not None
    # Body and Outline only flip signs in vertex space.  The 3MF build item
    # applies the common bed-placement translation after serialization.
    assert float(outline_mesh.bounds[0, 0]) == pytest.approx(-75.15)
    assert float(outline_mesh.bounds[1, 0]) == pytest.approx(-4.85)
    assert float(outline_mesh.bounds[0, 1]) == pytest.approx(-65.15)
    assert float(outline_mesh.bounds[1, 1]) == pytest.approx(-9.85)


def test_vector_outline_material_archive_uses_processor_export_color_mode() -> None:
    """Material-archive Outline must mirror exactly like body meshes.

    Material-archive vector processors expose ``color_mode == "Material Archive"``
    to ``VectorProcessor.build_mesh``. Even if the UI ctx still carries
    ``"5-Color Extended"``, the Outline helper must use the processor/export
    color mode so its X mirror decision matches the body scene.
    """
    from core.pipeline.vector_branch import _generate_vector_outline_mesh

    shape = box(10.0, 15.0, 70.0, 60.0)
    analysis = SimpleNamespace()
    analysis.matched_shapes = [
        {
            "geometry": shape,
            "color": (255, 0, 0),
            "matched_rgb": (255, 0, 0),
            "recipe": [1, 0, 0, 0, 0, 0],
            "draw_order": 0,
        }
    ]
    analysis.scale_factor = 1.0
    analysis.num_layers = 6
    analysis.bbox = (0.0, 0.0, 100.0, 80.0)

    outline_mesh = _generate_vector_outline_mesh(
        analysis=analysis,
        outline_width_mm=5.0,
        base_aux_color=[255, 255, 255, 255],
        base_aux_material_name="PLA White",
        ctx={
            "spacer_thick": 1.6,
            "structure_mode": "Single-sided",
            "color_mode": "5-Color Extended",
            "material_source": "material_archive",
            "enable_coating": False,
        },
        export_color_mode="Material Archive",
    )

    assert outline_mesh is not None
    assert float(outline_mesh.bounds[0, 0]) == pytest.approx(-75.15)
    assert float(outline_mesh.bounds[1, 0]) == pytest.approx(-4.85)
    assert float(outline_mesh.bounds[0, 1]) == pytest.approx(-65.15)
    assert float(outline_mesh.bounds[1, 1]) == pytest.approx(-9.85)


def test_vector_coating_covers_outline_expanded_footprint() -> None:
    """Vector coating must cover the same XY envelope as enabled outline.

    Regression for #251: in vector/SVG mode ``VectorProcessor.build_mesh``
    creates the transparent coating before the pipeline injects the separate
    ``Outline`` mesh. If the processor does not know outline is enabled, the
    coating footprint stays on the original backing and leaves the outward
    outline ring uncovered/misaligned.
    """
    from core.pipeline.vector_branch import _generate_vector_outline_mesh
    from core.vector_engine import VectorProcessor

    shape = box(10.0, 15.0, 70.0, 60.0)
    matched_shapes = [
        {
            "geometry": shape,
            "color": (255, 0, 0),
            "matched_rgb": (255, 0, 0),
            "recipe": [1, 0],
            "draw_order": 0,
        }
    ]
    analysis = SimpleNamespace()
    analysis.matched_shapes = matched_shapes
    analysis.clipped_shapes = matched_shapes
    analysis.silhouette = shape
    analysis.image_vectorizer_bounds = None
    analysis.scale_factor = 1.0
    analysis.bbox = (0.0, 0.0, 100.0, 80.0)
    analysis.slot_names = ["White", "Red"]
    analysis.num_channels = 2
    analysis.num_layers = 2
    analysis.preview_colors = {
        0: [255, 255, 255, 255],
        1: [255, 0, 0, 255],
    }
    analysis.stage_timings = {}

    processor = VectorProcessor.__new__(VectorProcessor)
    processor.color_mode = "Material Archive"
    processor._init_runtime_defaults()
    processor.enable_coating = True
    processor.coating_height_mm = 0.08
    processor.enable_outline = True
    processor.outline_width_mm = 5.0

    scene = processor.build_mesh(
        analysis,
        thickness_mm=1.6,
        structure_mode="Single-sided",
        backing_color_id=0,
    )
    outline_mesh = _generate_vector_outline_mesh(
        analysis=analysis,
        outline_width_mm=5.0,
        base_aux_color=[255, 255, 255, 255],
        base_aux_material_name="White",
        ctx={
            "spacer_thick": 1.6,
            "structure_mode": "Single-sided",
            "color_mode": "Material Archive",
            "enable_coating": True,
            "coating_height_mm": 0.08,
        },
        export_color_mode="Material Archive",
    )

    assert "Coating" in scene.geometry
    assert outline_mesh is not None
    coating = scene.geometry["Coating"]
    eps = 1e-6
    assert float(coating.bounds[0, 0]) <= float(outline_mesh.bounds[0, 0]) + eps
    assert float(coating.bounds[0, 1]) <= float(outline_mesh.bounds[0, 1]) + eps
    assert float(coating.bounds[1, 0]) >= float(outline_mesh.bounds[1, 0]) - eps
    assert float(coating.bounds[1, 1]) >= float(outline_mesh.bounds[1, 1]) - eps
    assert float(outline_mesh.bounds[0, 2]) == pytest.approx(float(coating.bounds[1, 2]))
    assert float(outline_mesh.bounds[1, 2]) >= float(coating.bounds[1, 2]) - eps


def test_vector_preview_material_archive_skips_export_outline_generation(
    tmp_path,
) -> None:
    """Quick preview must not call export-domain Outline generation."""
    from config import ModelingMode
    from core.pipeline import vector_branch

    svg_path = tmp_path / "preview-material-archive.svg"
    svg_path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="80">'
        '<rect x="10" y="15" width="60" height="45" fill="#ff0000"/>'
        "</svg>",
        encoding="utf-8",
    )
    processor, _scene = _build_material_archive_outline_bridge_fixture()
    raster_cache = {
        "target_w": 100,
        "target_h": 80,
        "pixel_scale": 1.0,
        "mask_solid": np.ones((80, 100), dtype=bool),
        "backing_mask": None,
        "material_matrix": np.zeros((80, 100, 6), dtype=np.uint8),
        "matched_rgb": np.zeros((80, 100, 3), dtype=np.uint8),
        "preview_rgba": np.zeros((80, 100, 4), dtype=np.uint8),
        "quantized_image": np.zeros((80, 100), dtype=np.int32),
    }
    ctx = {
        "image_path": str(svg_path),
        "color_mode": "5-Color Extended",
        "modeling_mode": ModelingMode.VECTOR,
        "target_width_mm": 100.0,
        "spacer_thick": 1.6,
        "structure_mode": "Single-sided",
        "is_dark": False,
        "quantize_colors": 64,
        "backing_color_id": 0,
        "lut_metadata": None,
        "material_source": "material_archive",
        "enable_outline": True,
        "outline_width": 5.0,
        "enable_coating": False,
        "coating_height_mm": 0.08,
        "auto_dynamic_range": False,
    }

    with patch.object(
        vector_branch, "_build_vector_processor", return_value=processor
    ), patch(
        "core.vector_engine.VectorProcessor.build_preview_cache",
        return_value=raster_cache,
    ), patch.object(
        vector_branch,
        "_generate_vector_outline_mesh",
        side_effect=AssertionError(
            "quick preview must not build export-domain Outline geometry"
        ),
    ) as mock_outline, patch.object(
        vector_branch,
        "p06_bed_rendering",
    ) as mock_p06:
        mock_p06.run.side_effect = lambda c: c
        result_ctx = vector_branch._run_vector_preview_branch(ctx)

    assert "error" not in result_ctx
    mock_outline.assert_not_called()
    cache = result_ctx["cache"]
    assert "outline_geometry" not in result_ctx
    assert "outline_added" not in result_ctx
    assert "outline_geometry" not in cache
    assert "outline_added" not in cache


def test_vector_generate_material_archive_passes_processor_export_color_mode(
    tmp_path,
) -> None:
    """Generate bridge must pass processor color mode to Outline generation."""
    from config import ModelingMode
    from core.pipeline import vector_branch

    svg_path = tmp_path / "generate-material-archive.svg"
    svg_path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="80">'
        '<rect x="10" y="15" width="60" height="45" fill="#ff0000"/>'
        "</svg>",
        encoding="utf-8",
    )
    output_dir = tmp_path / "output"
    models_dir = tmp_path / "models"
    output_dir.mkdir()
    models_dir.mkdir()
    processor, _scene = _build_material_archive_outline_bridge_fixture()
    ctx = {
        "image_path": str(svg_path),
        "color_mode": "5-Color Extended",
        "modeling_mode": ModelingMode.VECTOR,
        "target_width_mm": 100.0,
        "spacer_thick": 1.6,
        "structure_mode": "Single-sided",
        "material_source": "material_archive",
        "material_base_channel_idx": 0,
        "enable_outline": True,
        "outline_width": 5.0,
        "enable_coating": False,
        "coating_height_mm": 0.08,
        "enable_fridge_magnet": False,
        "fridge_magnets": [],
        "center_on_bed": False,
        "retain_scene_for_profile": True,
        "need_2d_preview": False,
        "printer_id": "bambu-h2d",
        "slicer": "BambuStudio",
        "nozzle_size": "0.4",
    }

    with patch.object(
        vector_branch, "_build_vector_processor", return_value=processor
    ), patch(
        "utils.bambu_3mf_writer.export_scene_with_bambu_metadata"
    ) as mock_bambu_export, patch(
        "config.OUTPUT_DIR", str(output_dir)
    ), patch(
        "config.MODELS_DIR", str(models_dir)
    ), patch.object(
        vector_branch,
        "rasterize_svg",
        return_value=np.zeros((80, 100, 4), dtype=np.uint8),
    ), patch(
        "trimesh.Scene.export", return_value=b"glb"
    ):
        result_ctx = vector_branch._run_vector_branch(ctx)

    assert "error" not in result_ctx
    mock_bambu_export.assert_called_once()
    exported_scene = mock_bambu_export.call_args.kwargs["scene"]
    assert result_ctx["scene"] is exported_scene
    _assert_material_archive_outline_mirrored(exported_scene.geometry["Outline"])


@settings(max_examples=200, deadline=None)
@given(
    outline_width=_OUTLINE_WIDTH,
    color_mode=_COLOR_MODE,
    base_channel_idx=_BASE_CHANNEL_IDX,
)
def test_vector_generate_includes_outline_geometry(
    outline_width: float, color_mode: str, base_channel_idx: int
) -> None:
    """vector + enable_outline=true 时 ``scene.geometry`` 必须包含 ``Outline``，
    且其 metadata 含 ``bambu_material_name``，且 outline ring 与
    ``analysis.matched_shapes`` 的 union 几乎不相交。

    当前 main 上 ``_run_vector_branch`` 完全不生成 outline，因此本测试
    **预期失败**（断言 1 即触发）。

    Validates: Requirements 1.2, 2.2
    """
    with tempfile.TemporaryDirectory() as tmp:
        # Use a copy of the on-disk fixture so different Hypothesis examples
        # cannot race on the same temp file path.
        svg_path = os.path.join(tmp, "case.svg")
        with open(_FIXTURE_SVG, "r", encoding="utf-8") as src, open(
            svg_path, "w", encoding="utf-8"
        ) as dst:
            dst.write(src.read())
        lut_path = os.path.join(tmp, "dummy.npy")
        np.save(lut_path, np.zeros(10))

        exported_scene = _run_generate_with_mocks(
            svg_path=svg_path,
            lut_path=lut_path,
            outline_width=float(outline_width),
            color_mode=color_mode,
            base_channel_idx=int(base_channel_idx),
        )

        _assert_outline_geometry_properties(
            exported_scene,
            _matched_shapes_for_fixture(),
            outline_width=float(outline_width),
            color_mode=color_mode,
            base_channel_idx=int(base_channel_idx),
        )


def test_vector_generate_includes_outline_geometry_anchor() -> None:
    """LUM-20260527-001 锚点：``outline_width=2.0`` + ``8-Color Max`` +
    ``base_channel_idx=0`` 必须落到 Outline 节点。

    工单的最小复现配置；与 PBT 共享断言但固定输入，便于 PR 描述里直接引用。
    """
    with tempfile.TemporaryDirectory() as tmp:
        svg_path = os.path.join(tmp, "anchor.svg")
        with open(_FIXTURE_SVG, "r", encoding="utf-8") as src, open(
            svg_path, "w", encoding="utf-8"
        ) as dst:
            dst.write(src.read())
        lut_path = os.path.join(tmp, "anchor.npy")
        np.save(lut_path, np.zeros(10))

        exported_scene = _run_generate_with_mocks(
            svg_path=svg_path,
            lut_path=lut_path,
            outline_width=2.0,
            color_mode="8-Color Max",
            base_channel_idx=0,
        )

        _assert_outline_geometry_properties(
            exported_scene,
            _matched_shapes_for_fixture(),
            outline_width=2.0,
            color_mode="8-Color Max",
            base_channel_idx=0,
        )


# ---------------------------------------------------------------------------
# Quick-preview ↔ generate Outline ownership contract
# ---------------------------------------------------------------------------


def _generate_outline_present(
    svg_path: str,
    lut_path: str,
    outline_width: float,
    color_mode: str,
    base_channel_idx: int,
) -> bool:
    """Run the vector generate branch and return whether the exported scene
    contains an ``Outline`` geometry.
    """
    scene = _run_generate_with_mocks(
        svg_path=svg_path,
        lut_path=lut_path,
        outline_width=float(outline_width),
        color_mode=color_mode,
        base_channel_idx=int(base_channel_idx),
    )
    return "Outline" in scene.geometry


def _preview_outline_present(
    svg_path: str, color_mode: str, outline_width: float
) -> bool:
    """Return whether quick-preview ctx/cache leaks export Outline state."""
    from config import ModelingMode
    from core.pipeline import vector_branch

    fake_scene = _make_base_scene()
    matched_shapes = _matched_shapes_for_fixture()
    ctx = {
        "image_path": svg_path,
        "color_mode": color_mode,
        "modeling_mode": ModelingMode.VECTOR,
        "target_width_mm": 100.0,
        "spacer_thick": 1.6,
        "structure_mode": "Single-sided",
        "is_dark": False,
        "quantize_colors": 64,
        "backing_color_id": 0,
        "lut_metadata": None,
        "enable_outline": True,
        "outline_width": float(outline_width),
        "enable_fridge_magnet": False,
        "fridge_magnets": [],
        "enable_coating": False,
        "coating_height_mm": 0.08,
        "auto_dynamic_range": False,
    }

    with patch("core.vector_engine.VectorProcessor") as MockVP:
        MockVP.return_value = _build_fake_processor(
            fake_scene, color_mode, matched_shapes=matched_shapes
        )
        MockVP.build_preview_cache.return_value = {
            "target_w": 100,
            "target_h": 100,
            "pixel_scale": 1.0,
            "mask_solid": np.ones((100, 100), dtype=bool),
            "backing_mask": None,
            "material_matrix": np.zeros((100, 100, 4), dtype=np.uint8),
            "matched_rgb": np.zeros((100, 100, 3), dtype=np.uint8),
            "preview_rgba": np.zeros((100, 100, 4), dtype=np.uint8),
            "quantized_image": np.zeros((100, 100), dtype=np.int32),
        }

        with patch.object(vector_branch, "p06_bed_rendering") as mock_p06:
            mock_p06.run.side_effect = lambda c: c
            result_ctx = vector_branch._run_vector_preview_branch(ctx)

    assert "error" not in result_ctx, result_ctx.get("error")

    cache = result_ctx.get("cache") or {}
    candidates = (
        result_ctx.get("outline_added"),
        result_ctx.get("outline_geometry"),
        cache.get("outline_geometry"),
        cache.get("outline_added"),
        cache.get("outline_mesh"),
    )
    return any(bool(c) for c in candidates)


@settings(max_examples=200, deadline=None)
@given(outline_width=_OUTLINE_WIDTH, color_mode=_COLOR_MODE)
def test_vector_preview_generate_outline_ownership(
    outline_width: float, color_mode: str
) -> None:
    """Generate owns physical Outline; quick preview owns no export mesh.

    Validates: Requirements 1.3, 2.3
    """
    with tempfile.TemporaryDirectory() as tmp:
        svg_path = os.path.join(tmp, "parity.svg")
        with open(_FIXTURE_SVG, "r", encoding="utf-8") as src, open(
            svg_path, "w", encoding="utf-8"
        ) as dst:
            dst.write(src.read())
        lut_path = os.path.join(tmp, "parity.npy")
        np.save(lut_path, np.zeros(10))

        gen_present = _generate_outline_present(
            svg_path, lut_path, float(outline_width), color_mode, 0
        )
        prev_present = _preview_outline_present(
            svg_path, color_mode, float(outline_width)
        )

        assert gen_present is True, (
            "generate must retain the physical export Outline; "
            f"got generate={gen_present} (outline_width={outline_width}, "
            f"color_mode={color_mode})"
        )
        assert prev_present is False, (
            "quick preview must not cache export-domain Outline geometry; "
            f"got preview={prev_present} (outline_width={outline_width}, "
            f"color_mode={color_mode})"
        )


def test_vector_preview_generate_outline_ownership_anchor() -> None:
    """Anchor: generated export keeps Outline; quick preview does not embed it."""
    with tempfile.TemporaryDirectory() as tmp:
        svg_path = os.path.join(tmp, "anchor-parity.svg")
        with open(_FIXTURE_SVG, "r", encoding="utf-8") as src, open(
            svg_path, "w", encoding="utf-8"
        ) as dst:
            dst.write(src.read())
        lut_path = os.path.join(tmp, "anchor-parity.npy")
        np.save(lut_path, np.zeros(10))

        gen_present = _generate_outline_present(
            svg_path, lut_path, 2.0, "8-Color Max", 0
        )
        prev_present = _preview_outline_present(svg_path, "8-Color Max", 2.0)

        assert gen_present is True
        assert prev_present is False


# ---------------------------------------------------------------------------
# Regression guard: vector outline must NOT inflate the project palette.
# 回归守卫：矢量描边不得放大项目调色板（filament_* 数组长度）。
# ---------------------------------------------------------------------------
#
# Background: in an earlier iteration of Task 3.3 the vector branch appended
# ``"Outline"`` to ``vec_slot_list`` (which is forwarded as
# ``project_slot_names`` to ``export_scene_with_bambu_metadata``). The writer
# sizes the project-level ``filament_colour`` / ``filament_type`` /
# ``nozzle_temperature`` arrays from ``project_slot_names`` length, so an
# 8-color vector input produced a 9-filament 3MF — breaking material identity
# and downstream slicer expectations.
#
# 早期 Task 3.3 把 ``"Outline"`` 加进 ``vec_slot_list``（即 writer 的
# ``project_slot_names``），导致 8 色 vector 输出变成 9-filament 3MF，破坏
# 材料身份。下面的测试钉住正确的双轨契约：``slot_names`` 含 Outline（让 writer
# 导出对象），``project_slot_names`` 不含 Outline（项目调色板维持原长度）。
#
# Mirrors raster ``s09_export_3mf.run`` which passes
# ``slot_names=valid_slot_names, project_slot_names=slot_names``.


# 8-Color Max canonical slot names + preview colours used by the regression
# guards below. These mirror the LUT palette `LumiCard 8C Max` exposes via
# ``ColorSystem`` for the 8-Color Max color mode; we ship a self-contained
# copy so the tests do not depend on LUT loading.
# 工单 LUM-20260527-001 的 8-Color Max 调色板：与 LumiCard 8C Max 一致；
# 测试自带，不依赖 LUT 加载。
_8COLOR_MAX_SLOT_NAMES = [
    "White",
    "Cyan",
    "Magenta",
    "Yellow",
    "Red",
    "Black",
    "Blue",
    "Green",
]
_8COLOR_MAX_PREVIEW_COLORS = {
    0: [255, 255, 255, 255],
    1: [0, 134, 214, 255],
    2: [236, 0, 140, 255],
    3: [244, 238, 42, 255],
    4: [220, 20, 60, 255],
    5: [16, 16, 16, 255],
    6: [0, 100, 240, 255],
    7: [0, 168, 76, 255],
}


def _build_8color_fake_processor(
    matched_shapes: list[dict] | None = None,
) -> tuple[MagicMock, trimesh.Scene]:
    """Build an 8-slot fake VectorProcessor + matching 8-slot scene.

    Used by the ``test_vector_outline_*_project_palette_*`` regression guards
    so that ``analysis.slot_names`` and ``scene.geometry`` are both exactly
    the 8-Color Max canonical palette. Combined with ``enable_outline=True``
    this is the precise shape that surfaced the original P2 regression
    (8 base slots + 1 Outline → 9-filament 3MF).

    构造 8 槽位 fake processor + scene；这是 P2 原始回归的精确形状（8 色 base
    + Outline = 9-filament 3MF），用于强化断言。
    """
    scene = trimesh.Scene()
    for name in _8COLOR_MAX_SLOT_NAMES:
        mesh = trimesh.creation.box(extents=[5.0, 5.0, 0.5])
        mesh.metadata["name"] = name
        scene.add_geometry(mesh, geom_name=name)

    vp = MagicMock()
    vp.svg_to_mesh.return_value = scene
    vp.img_processor.lut_rgb = np.zeros((256, 3))
    vp.img_processor._load_svg.return_value = np.zeros(
        (100, 100, 4), dtype=np.uint8
    )
    vp.color_mode = "8-Color Max"

    fake_analysis = SimpleNamespace()
    fake_analysis.preview_colors = dict(_8COLOR_MAX_PREVIEW_COLORS)
    fake_analysis.slot_names = list(_8COLOR_MAX_SLOT_NAMES)
    fake_analysis.stage_timings = {}
    fake_analysis.matched_shapes = (
        list(matched_shapes) if matched_shapes is not None else []
    )
    fake_analysis.color_conf = None
    fake_analysis.num_layers = 8
    fake_analysis.scale_factor = 1.0
    fake_analysis.bbox = (0.0, 0.0, 100.0, 100.0)
    vp.analyze_svg.return_value = fake_analysis
    vp.build_mesh.return_value = scene
    vp.render_preview = MagicMock(
        return_value=np.zeros((100, 100, 4), dtype=np.uint8)
    )
    return vp, scene


def test_vector_outline_does_not_inflate_project_palette() -> None:
    """``Outline`` belongs in ``slot_names`` (object export) but NOT in
    ``project_slot_names`` (project palette). Locks the dual-track contract
    raster outline already obeys.

    8 色 vector + outline 的最小复现锚点（工单 LUM-20260527-001）。

    断言强度（按 2026-05-29 review 反馈强化）:
        1. ``slot_names`` 含 Outline（writer 必须导出该对象）
        2. ``project_slot_names`` **不含** Outline（项目调色板防止 N+1）
        3. ``len(project_slot_names) == 8`` —— 这是 P2 回归的真正量化锚：
           writer 据此长度 resize ``filament_*`` 数组；8 色输入必须仍是 8 项
        4. ``len(slot_names)`` 比 ``len(project_slot_names)`` 多 1（多的是 Outline）
    """
    from config import ModelingMode
    from core.converter import convert_image_to_3d

    with tempfile.TemporaryDirectory() as tmp:
        svg_path = os.path.join(tmp, "palette-anchor.svg")
        with open(_FIXTURE_SVG, "r", encoding="utf-8") as src, open(
            svg_path, "w", encoding="utf-8"
        ) as dst:
            dst.write(src.read())
        lut_path = os.path.join(tmp, "palette-anchor.npy")
        np.save(lut_path, np.zeros(10))

        matched_shapes = _matched_shapes_for_fixture()
        fake_vp, _scene = _build_8color_fake_processor(
            matched_shapes=matched_shapes
        )

        with patch(
            "utils.bambu_3mf_writer.export_scene_with_bambu_metadata"
        ) as mock_bambu_export, patch(
            "core.vector_engine.VectorProcessor"
        ) as MockVP:
            MockVP.return_value = fake_vp
            convert_image_to_3d(
                image_path=svg_path,
                lut_path=lut_path,
                target_width_mm=100.0,
                spacer_thick=1.6,
                structure_mode="Single-sided",
                color_mode="8-Color Max",
                add_loop=False,
                loop_width=5,
                loop_length=20,
                loop_hole=3,
                loop_pos="Top",
                modeling_mode=ModelingMode.VECTOR,
                backing_color_id=0,
                enable_outline=True,
                outline_width=2.0,
            )

            assert mock_bambu_export.call_count == 1
            kwargs = mock_bambu_export.call_args.kwargs

        slot_names = list(kwargs.get("slot_names") or [])
        project_slot_names = list(kwargs.get("project_slot_names") or [])

        # (1) Object-level: writer must export the Outline mesh.
        # 对象级：Outline 必须出现在 slot_names 里。
        assert "Outline" in slot_names, (
            f"slot_names should expose Outline as an exportable object; "
            f"got {slot_names}"
        )

        # (2) Project-level palette: must NOT contain Outline.
        # 项目级调色板：不得含 Outline。
        assert "Outline" not in project_slot_names, (
            "Outline leaked into project_slot_names — this would inflate "
            f"filament_* arrays from {len(project_slot_names) - 1} to "
            f"{len(project_slot_names)} entries; raster s09_export_3mf "
            "keeps Outline out of project_slot_names by design"
        )

        # (3) Quantitative anchor for the original P2 regression:
        # 8-Color input must yield exactly 8 project-level slots, never 9.
        # 数量级锚点 —— writer 据此 resize ``filament_colour /
        # filament_type / nozzle_temperature``；8 色输入必须恰好 8 个槽位。
        assert len(project_slot_names) == len(_8COLOR_MAX_SLOT_NAMES), (
            f"project_slot_names length must equal base material count "
            f"({len(_8COLOR_MAX_SLOT_NAMES)}); got "
            f"{len(project_slot_names)}: {project_slot_names}. "
            "This is the exact P2 regression: an 8-Color Max + outline "
            "input was producing a 9-filament 3MF."
        )

        # (4) slot_names should be exactly project_slot_names + ["Outline"].
        # slot_names 应该恰好等于 project_slot_names + ["Outline"]（Outline
        # 是唯一额外的对象级 slot）。
        assert len(slot_names) == len(project_slot_names) + 1, (
            f"slot_names should add exactly one extra slot (Outline) over "
            f"project_slot_names; got slot_names={slot_names}, "
            f"project_slot_names={project_slot_names}"
        )


def test_vector_no_outline_keeps_project_palette_unchanged() -> None:
    """Sanity sibling: when outline is disabled, neither ``slot_names`` nor
    ``project_slot_names`` should contain ``Outline``, and both should equal
    the base material palette length.

    保留性兄弟测试：关闭 outline 时两个列表都不应含 Outline；且长度都等于
    base 材料数（8）。
    """
    from config import ModelingMode
    from core.converter import convert_image_to_3d

    with tempfile.TemporaryDirectory() as tmp:
        svg_path = os.path.join(tmp, "palette-disabled.svg")
        with open(_FIXTURE_SVG, "r", encoding="utf-8") as src, open(
            svg_path, "w", encoding="utf-8"
        ) as dst:
            dst.write(src.read())
        lut_path = os.path.join(tmp, "palette-disabled.npy")
        np.save(lut_path, np.zeros(10))

        matched_shapes = _matched_shapes_for_fixture()
        fake_vp, _scene = _build_8color_fake_processor(
            matched_shapes=matched_shapes
        )

        with patch(
            "utils.bambu_3mf_writer.export_scene_with_bambu_metadata"
        ) as mock_bambu_export, patch(
            "core.vector_engine.VectorProcessor"
        ) as MockVP:
            MockVP.return_value = fake_vp
            convert_image_to_3d(
                image_path=svg_path,
                lut_path=lut_path,
                target_width_mm=100.0,
                spacer_thick=1.6,
                structure_mode="Single-sided",
                color_mode="8-Color Max",
                add_loop=False,
                loop_width=5,
                loop_length=20,
                loop_hole=3,
                loop_pos="Top",
                modeling_mode=ModelingMode.VECTOR,
                backing_color_id=0,
                enable_outline=False,
                outline_width=2.0,
            )

            assert mock_bambu_export.call_count == 1
            kwargs = mock_bambu_export.call_args.kwargs

        slot_names = list(kwargs.get("slot_names") or [])
        project_slot_names = list(kwargs.get("project_slot_names") or [])

        assert "Outline" not in slot_names, (
            f"Outline must not appear in slot_names when enable_outline=False; "
            f"got {slot_names}"
        )
        assert "Outline" not in project_slot_names, (
            f"Outline must not appear in project_slot_names when "
            f"enable_outline=False; got {project_slot_names}"
        )
        assert len(project_slot_names) == len(_8COLOR_MAX_SLOT_NAMES), (
            f"project_slot_names length must equal base material count "
            f"({len(_8COLOR_MAX_SLOT_NAMES)}); got {len(project_slot_names)}"
        )
        assert len(slot_names) == len(_8COLOR_MAX_SLOT_NAMES), (
            f"slot_names length should equal base material count when "
            f"outline is disabled; got {len(slot_names)}: {slot_names}"
        )


def test_vector_outline_real_3mf_filament_arrays_match_base_palette() -> None:
    """End-to-end real-3MF zip parse: 8-Color Max + outline export must
    produce a 3MF whose ``Metadata/project_settings.config`` filament arrays
    are exactly 8 entries, AND whose ``Metadata/model_settings.config``
    object list contains an ``Outline`` entry alongside the 8 base slots.

    端到端 zip 解析：8 色 + outline 导出的真 3MF，``filament_*`` 必须 8 项，
    ``model_settings.config`` 对象列表必须含 Outline + 8 base slots。

    This is the strict quantitative shape the user-visible Bambu Studio open
    sees; it complements the upstream mock-based guard above by exercising
    the full ``BambuStudio3MFWriter._build_project_settings_bytes`` and
    ``_build_model_settings_bytes`` paths.
    """
    import json
    import zipfile
    import xml.etree.ElementTree as ET

    from utils.bambu_3mf_writer import export_scene_with_bambu_metadata

    matched_shapes = _matched_shapes_for_fixture()
    _fake_vp, base_scene = _build_8color_fake_processor(
        matched_shapes=matched_shapes
    )

    # Inject an Outline mesh manually — the regression we're guarding lives in
    # how vector_branch wires the Outline mesh into ``slot_names`` /
    # ``project_slot_names``, and we mirror that wiring here so the writer
    # observes the post-fix state and emits a real zip.
    # 手动注入 Outline mesh 以镜像 vector_branch 修复后的对象 / 调色板分流
    # 写法，让 writer 跑一次真 zip 输出。
    outline_mesh = trimesh.creation.box(extents=[6.0, 6.0, 0.5])
    outline_mesh.visual.face_colors = np.tile(
        np.asarray([255, 255, 255, 255], dtype=np.uint8),
        (len(outline_mesh.faces), 1),
    )
    outline_mesh.metadata["name"] = "Outline"
    outline_mesh.metadata["bambu_material_name"] = _8COLOR_MAX_SLOT_NAMES[0]
    base_scene.add_geometry(
        outline_mesh, node_name="Outline", geom_name="Outline"
    )

    # slot_names mirrors what vector_branch emits post-fix:
    # 8 base slots + ``Outline`` (as an exportable object).
    slot_names = list(_8COLOR_MAX_SLOT_NAMES) + ["Outline"]
    # project_slot_names is the project-level palette: ONLY base materials,
    # ``Outline`` deliberately excluded.
    project_slot_names = list(_8COLOR_MAX_SLOT_NAMES)
    preview_colors = dict(_8COLOR_MAX_PREVIEW_COLORS)
    preview_colors["Outline"] = preview_colors[0]

    settings = {
        "nozzle_temperature": ["220"] * 8,
        "bed_temperature": ["60"] * 8,
        "filament_type": ["PLA"] * 8,
    }

    with tempfile.TemporaryDirectory() as tmp:
        out_path = os.path.join(tmp, "palette-real-3mf.3mf")
        export_scene_with_bambu_metadata(
            scene=base_scene,
            output_path=out_path,
            slot_names=slot_names,
            preview_colors=preview_colors,
            settings=settings,
            color_mode="8-Color Max",
            printer_id="bambu-h2d",
            slicer="BambuStudio",
            nozzle_size="0.4",
            project_slot_names=project_slot_names,
            enable_base_layer_height_modifier=True,
            base_height_mm=1.6,
            color_height_mm=1.6,
            face_orientation="down",
        )

        assert os.path.exists(out_path), "writer must produce the 3MF file"

        with zipfile.ZipFile(out_path, "r") as zf:
            project_settings_raw = zf.read(
                "Metadata/project_settings.config"
            ).decode("utf-8")
            model_settings_raw = zf.read(
                "Metadata/model_settings.config"
            ).decode("utf-8")

    # (a) project_settings.config — filament arrays must be exactly 8 entries.
    # 项目设置 — filament_* 必须正好 8 项。Bed temperature key shape varies
    # across printer templates so we keep this guard focused on the three
    # filament-aligned arrays the original P2 review called out.
    # bed temperature 字段在不同机型模板里 shape 不一致，这里只断言 review
    # 明确点名的三个 filament 对齐数组。
    project_settings = json.loads(project_settings_raw)
    for filament_key in (
        "filament_colour",
        "filament_type",
        "nozzle_temperature",
    ):
        actual = project_settings.get(filament_key)
        assert isinstance(actual, list), (
            f"project_settings.{filament_key} should be a list, got {actual!r}"
        )
        assert len(actual) == len(_8COLOR_MAX_SLOT_NAMES), (
            f"project_settings.{filament_key} length must equal base "
            f"material count ({len(_8COLOR_MAX_SLOT_NAMES)}); "
            f"got {len(actual)} entries: {actual}. This is the exact P2 "
            f"regression shape — the writer was emitting 9 entries."
        )

    # (b) model_settings.config — object list should contain Outline AND
    # all 8 base slots. Bambu Studio reads this XML to populate the object
    # tree; verifying ``Outline`` is here proves the dual-track design is
    # working (Outline is exported as an object even though it's not in
    # the project palette).
    # 模型设置 — 对象列表必须含 Outline + 8 个 base slots。
    model_root = ET.fromstring(model_settings_raw)
    object_part_names: list[str] = []
    for part in model_root.iter("part"):
        for meta in part.findall("metadata"):
            if meta.attrib.get("key") == "name":
                value = meta.attrib.get("value", "")
                if value:
                    object_part_names.append(value)
    assert "Outline" in object_part_names, (
        f"model_settings.config should list Outline as an exported object; "
        f"got parts={object_part_names}"
    )
    for base_name in _8COLOR_MAX_SLOT_NAMES:
        assert base_name in object_part_names, (
            f"model_settings.config missing base slot '{base_name}'; "
            f"got parts={object_part_names}"
        )


# ---------------------------------------------------------------------------
# Quick-preview cache ownership guard.
# ---------------------------------------------------------------------------
#
# Vector quick preview intentionally excludes the SVG-derived export mesh.
# The UI owns the live Outline overlay; the generate branch remains responsible
# for the physical Outline exported to GLB/3MF.


def test_preview_cache_excludes_export_outline_geometry() -> None:
    """Vector quick-preview cache never exposes export-domain Outline state."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        svg_path = os.path.join(tmp, "preview-meta-anchor.svg")
        with open(_FIXTURE_SVG, "r", encoding="utf-8") as src, open(
            svg_path, "w", encoding="utf-8"
        ) as dst:
            dst.write(src.read())

        prev_present = _preview_outline_present(svg_path, "8-Color Max", 2.0)

        assert prev_present is False, (
            "quick preview must not expose outline_geometry/outline_added; "
            "the live UI overlay owns preview Outline rendering"
        )
