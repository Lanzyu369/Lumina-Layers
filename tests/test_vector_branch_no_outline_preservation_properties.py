"""Spec: svg-vector-outline-support / Task 2.2

Property 2 (Preservation) — Vector + ``enable_outline=False`` 路径行为不变。

Goal:
    For every ``modeling_mode=VECTOR`` invocation where ``enable_outline=False``,
    the vector branch's observable output (exported scene geometry names,
    per-mesh ``(vertex_count, face_count, len(metadata))``, ``ctx['bambu_*']``
    fields, ``vec_preview_colors``, and ``vec_slot_list``) MUST be identical
    to the canonical baseline regardless of how ``outline_width`` or other
    optional toggles vary. This locks the baseline so the upcoming Task 3 fix
    (which adds outline injection only when ``enable_outline`` is true) does
    not silently regress the unfixed ("false branch") behavior.

为何不重用 Task 1.3 的辅助函数:
    Task 1.3 的 ``_build_fake_processor`` / ``_make_base_scene`` 同样写死了
    ``matched_shapes`` / 颜色/槽位等逻辑。本测试要求"与 Task 1.3 解耦"，因此
    刻意把这两个 helper 复制（而不是 import）到本文件，保留独立演化空间。

Validates: Requirements 3.2
"""

from __future__ import annotations

import os
import sys
import tempfile
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import trimesh
from hypothesis import HealthCheck, assume, given, settings, strategies as st

# Ensure project root is importable when running the file directly via pytest.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


# ---------------------------------------------------------------------------
# Fixtures and constants
# ---------------------------------------------------------------------------

_FIXTURE_SVG = os.path.join(
    _ROOT, "tests", "fixtures", "svg_vector", "simple_rect.svg"
)

# Canonical baseline configuration — locked so the Task 3 fix cannot drift
# the unfixed ("enable_outline=False") branch.
# 锚点配置：固化 baseline，Task 3 修复时 enable_outline=False 路径不允许变。
_BASELINE_OUTLINE_WIDTH = 2.0
_BASELINE_COLOR_MODE = "4-Color RYBW"
_BASELINE_BACKING_COLOR_ID = 0
_BASELINE_STRUCTURE_MODE = "Single-sided"


# ---------------------------------------------------------------------------
# Mock helpers (copied from Task 1.3 on purpose — see module docstring)
# ---------------------------------------------------------------------------


def _build_fake_processor(
    scene: trimesh.Scene,
    color_mode: str,
    *,
    matched_shapes: list[dict] | None = None,
) -> MagicMock:
    """Return a MagicMock that behaves like ``VectorProcessor``.

    本 helper 与 ``test_vector_outline_pipeline_properties.py`` 中的同名
    helper 功能一致；为避免跨测试耦合刻意采用复制策略。
    """
    vp = MagicMock()
    vp.svg_to_mesh.return_value = scene
    vp.img_processor.lut_rgb = np.zeros((256, 3))
    vp.img_processor._load_svg.return_value = np.zeros((100, 100, 4), dtype=np.uint8)
    vp.color_mode = color_mode

    fake_analysis = MagicMock()
    fake_analysis.preview_colors = {
        0: [255, 255, 255, 255],
        1: [255, 0, 0, 255],
        2: [255, 255, 0, 255],
        3: [0, 0, 255, 255],
    }
    fake_analysis.slot_names = ["White", "Red", "Yellow", "Blue"]
    fake_analysis.stage_timings = {}
    # Outline geometry is irrelevant in the false branch — keep matched_shapes
    # empty so any future helper that derives outline ring from shapes also
    # naturally degrades to "no-op" without changing the false-branch output.
    # 关闭描边时 outline ring 不应被构造，matched_shapes 给空即可。
    fake_analysis.matched_shapes = (
        list(matched_shapes) if matched_shapes is not None else []
    )
    fake_analysis.color_conf = None
    fake_analysis.num_layers = 4
    vp.analyze_svg.return_value = fake_analysis
    vp.build_mesh.return_value = scene
    vp.render_preview = MagicMock(return_value=np.zeros((100, 100, 4), dtype=np.uint8))
    # Keep ``last_stage_timings`` falsy so the branch does not try to merge
    # vector_timing with a MagicMock's auto-generated dict-like object.
    vp.last_stage_timings = {}
    vp.parse_warnings = []
    return vp


def _make_base_scene() -> trimesh.Scene:
    """Build a minimal scene that has base material slots but no Outline.

    Mirrors the canonical fake scene used by other vector-branch unit tests:
    three boxes named after the first three slots in
    ``_build_fake_processor``'s palette.
    """
    scene = trimesh.Scene()
    for name in ("White", "Red", "Yellow"):
        mesh = trimesh.creation.box(extents=[5.0, 5.0, 0.5])
        mesh.metadata["name"] = name
        scene.add_geometry(mesh, geom_name=name)
    return scene


# ---------------------------------------------------------------------------
# Pipeline driver
# ---------------------------------------------------------------------------


def _run_vector_branch_capture(
    *,
    outline_width: float,
    color_mode: str,
    backing_color_id: int,
    structure_mode: str,
    enable_fridge_magnet: bool,
    enable_coating: bool,
    enable_base_layer_height_modifier: bool,
) -> dict[str, Any]:
    """Drive ``_run_vector_branch`` with ``enable_outline=False`` and capture
    every observable artefact the Task 2.2 directive enumerates.

    驱动 vector 分支并捕获所有需要保留的不变量。

    Returns:
        dict containing:
            - ``scene_geometry_names``: sorted list of scene geometry keys
            - ``per_mesh_fingerprint``: dict mapping geometry name to
              ``(vertex_count, face_count, len(metadata))``
            - ``bambu_base_height_mm`` / ``bambu_color_height_mm``
              / ``bambu_face_orientation``
            - ``preview_colors_keys`` / ``preview_colors_values``
            - ``slot_names``: list passed as ``project_slot_names`` to the
              exporter
            - ``slot_names_in_export``: actual ``slot_names`` arg (post-merge)
    """
    # Local imports keep test collection fast for unrelated tests.
    from config import ModelingMode
    from core.converter import convert_image_to_3d

    fake_scene = _make_base_scene()

    with tempfile.TemporaryDirectory() as tmp:
        svg_path = os.path.join(tmp, "case.svg")
        with open(_FIXTURE_SVG, "r", encoding="utf-8") as src, open(
            svg_path, "w", encoding="utf-8"
        ) as dst:
            dst.write(src.read())
        lut_path = os.path.join(tmp, "dummy.npy")
        np.save(lut_path, np.zeros(10))

        with patch(
            "utils.bambu_3mf_writer.export_scene_with_bambu_metadata"
        ) as mock_bambu_export, patch(
            "core.vector_engine.VectorProcessor"
        ) as MockVP:
            MockVP.return_value = _build_fake_processor(
                fake_scene, color_mode, matched_shapes=[]
            )

            convert_image_to_3d(
                image_path=svg_path,
                lut_path=lut_path,
                target_width_mm=100.0,
                spacer_thick=1.6,
                structure_mode=structure_mode,
                color_mode=color_mode,
                add_loop=False,
                loop_width=5,
                loop_length=20,
                loop_hole=3,
                loop_pos="Top",
                modeling_mode=ModelingMode.VECTOR,
                backing_color_id=int(backing_color_id),
                enable_outline=False,
                outline_width=float(outline_width),
                enable_fridge_magnet=bool(enable_fridge_magnet),
                fridge_magnets=[] if not enable_fridge_magnet else [],
                enable_coating=bool(enable_coating),
                coating_height_mm=0.08,
                enable_base_layer_height_modifier=bool(
                    enable_base_layer_height_modifier
                ),
            )

            assert mock_bambu_export.call_count == 1, (
                "vector branch must invoke export_scene_with_bambu_metadata "
                f"exactly once (got {mock_bambu_export.call_count}); "
                "preservation tests cannot run if the branch errors out early"
            )
            kwargs = mock_bambu_export.call_args.kwargs
            scene = kwargs["scene"]

    # Per-mesh fingerprint: (vertex_count, face_count, len(metadata)).
    # 每个 mesh 的体型指纹，用于结构等价性断言。
    per_mesh: dict[str, tuple[int, int, int]] = {}
    for name, geom in scene.geometry.items():
        verts = getattr(geom, "vertices", None)
        faces = getattr(geom, "faces", None)
        v_count = int(len(verts) if verts is not None else 0)
        f_count = int(len(faces) if faces is not None else 0)
        meta = dict(getattr(geom, "metadata", {}) or {})
        per_mesh[str(name)] = (v_count, f_count, len(meta))

    preview_colors = dict(kwargs.get("preview_colors") or {})
    # Normalize values to tuples-of-int so dict equality is robust against
    # numpy / list distinctions across hypothesis examples.
    # 把颜色值归一化成 int 元组，避免 numpy / list 引起的相等性误判。
    preview_colors_norm = {
        str(k): tuple(int(c) for c in v) for k, v in preview_colors.items()
    }

    return {
        "scene_geometry_names": sorted(scene.geometry.keys()),
        "per_mesh_fingerprint": per_mesh,
        "bambu_base_height_mm": float(kwargs.get("base_height_mm", 0.0)),
        "bambu_color_height_mm": float(kwargs.get("color_height_mm", 0.0)),
        "bambu_face_orientation": str(kwargs.get("face_orientation", "")),
        "enable_base_layer_height_modifier": bool(
            kwargs.get("enable_base_layer_height_modifier", True)
        ),
        "preview_colors": preview_colors_norm,
        "preview_colors_keys": sorted(preview_colors_norm.keys()),
        "slot_names_in_export": list(kwargs.get("slot_names") or []),
        "project_slot_names": list(kwargs.get("project_slot_names") or []),
        "color_mode_passed": str(kwargs.get("color_mode") or ""),
    }


# ---------------------------------------------------------------------------
# Baseline (canonical input)
# ---------------------------------------------------------------------------


def _capture_baseline() -> dict[str, Any]:
    """Capture the canonical baseline at fixed canonical input.

    canonical input: ``modeling_mode=VECTOR``, ``enable_outline=False``,
    ``outline_width=2.0``, ``color_mode='4-Color RYBW'``,
    ``backing_color_id=0``, single-sided, no fridge magnet, no coating,
    base-layer modifier enabled.
    """
    return _run_vector_branch_capture(
        outline_width=_BASELINE_OUTLINE_WIDTH,
        color_mode=_BASELINE_COLOR_MODE,
        backing_color_id=_BASELINE_BACKING_COLOR_ID,
        structure_mode=_BASELINE_STRUCTURE_MODE,
        enable_fridge_magnet=False,
        enable_coating=False,
        enable_base_layer_height_modifier=True,
    )


@pytest.fixture(scope="module")
def baseline_snapshot() -> dict[str, Any]:
    """Module-scoped baseline so each PBT example reuses the same captured
    artefact set instead of re-running the canonical pipeline.
    """
    return _capture_baseline()


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

# outline_width is allowed to vary widely — the toggle is what matters; under
# enable_outline=False the width must not affect the geometry.
# 关闭描边时宽度不应影响输出几何。
_OUTLINE_WIDTH = st.floats(
    min_value=0.5, max_value=10.0, allow_nan=False, allow_infinity=False
)
_COLOR_MODE = st.sampled_from(["BW", "4-Color RYBW", "8-Color Max"])


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
@given(outline_width=_OUTLINE_WIDTH, color_mode=_COLOR_MODE)
def test_vector_no_outline_preserves_baseline(
    baseline_snapshot: dict[str, Any],
    outline_width: float,
    color_mode: str,
) -> None:
    """Vector + ``enable_outline=False`` 下，``outline_width`` 与 ``color_mode``
    都不应改变 vector 分支可观察输出。

    Important: ``color_mode`` only flows through ``vec_processor.color_mode``
    when the *real* ``VectorProcessor`` is used; here the mock returns a
    fixed ``color_mode``. So preservation should hold for every sampled
    color_mode value (no scene-level branching). 这条保证恰好是 Task 3 修复
    必须保留的——开关关闭时无论上层传什么 color_mode，几何都不应变。

    Validates: Requirements 3.2
    """
    # ``outline_width`` exits validation only when finite and inside the
    # documented [0.5, 10.0] range; the strategy already covers that.
    assume(0.5 <= float(outline_width) <= 10.0)

    snapshot = _run_vector_branch_capture(
        outline_width=float(outline_width),
        color_mode=color_mode,
        backing_color_id=_BASELINE_BACKING_COLOR_ID,
        structure_mode=_BASELINE_STRUCTURE_MODE,
        enable_fridge_magnet=False,
        enable_coating=False,
        enable_base_layer_height_modifier=True,
    )

    # 1) Geometry name set is identical (no Outline injected).
    assert snapshot["scene_geometry_names"] == baseline_snapshot["scene_geometry_names"], (
        "vector + enable_outline=False geometry name set must equal baseline "
        f"({baseline_snapshot['scene_geometry_names']}); got "
        f"{snapshot['scene_geometry_names']} for outline_width={outline_width}, "
        f"color_mode={color_mode}"
    )
    # The canonical "no outline injected" invariant is the key Task 2.2 fact.
    assert "Outline" not in snapshot["scene_geometry_names"], (
        "Outline must NOT be present when enable_outline=False "
        f"(scene={snapshot['scene_geometry_names']}, outline_width={outline_width})"
    )

    # 2) Each mesh's (vertex_count, face_count, len(metadata)) is identical.
    assert snapshot["per_mesh_fingerprint"] == baseline_snapshot["per_mesh_fingerprint"], (
        "per-mesh fingerprint diverged from baseline; "
        f"baseline={baseline_snapshot['per_mesh_fingerprint']}; "
        f"current={snapshot['per_mesh_fingerprint']}; "
        f"outline_width={outline_width}, color_mode={color_mode}"
    )

    # 3) ctx ``bambu_*`` fields are identical.
    for key in (
        "bambu_base_height_mm",
        "bambu_color_height_mm",
        "bambu_face_orientation",
        "enable_base_layer_height_modifier",
    ):
        assert snapshot[key] == baseline_snapshot[key], (
            f"ctx field {key} diverged from baseline: "
            f"baseline={baseline_snapshot[key]!r}, current={snapshot[key]!r} "
            f"(outline_width={outline_width}, color_mode={color_mode})"
        )

    # 4) preview_colors and slot_names equivalence.
    assert snapshot["preview_colors"] == baseline_snapshot["preview_colors"], (
        "preview_colors diverged from baseline; "
        f"baseline_keys={baseline_snapshot['preview_colors_keys']}; "
        f"current_keys={snapshot['preview_colors_keys']}"
    )
    assert (
        snapshot["slot_names_in_export"] == baseline_snapshot["slot_names_in_export"]
    ), (
        "slot_names diverged from baseline: "
        f"baseline={baseline_snapshot['slot_names_in_export']}; "
        f"current={snapshot['slot_names_in_export']}"
    )
    assert (
        snapshot["project_slot_names"] == baseline_snapshot["project_slot_names"]
    ), (
        "project_slot_names diverged from baseline: "
        f"baseline={baseline_snapshot['project_slot_names']}; "
        f"current={snapshot['project_slot_names']}"
    )


# ---------------------------------------------------------------------------
# Anchors — non-PBT cases nailing the canonical "outline_width does not
# matter when enable_outline=False" assumption.
# 锚点：非 PBT，固定 outline_width 在 0 / 边界 / 默认值 上各取一次。
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "outline_width",
    [0.5, 2.0, 10.0],
    ids=["min", "default", "max"],
)
def test_vector_no_outline_anchor_outline_width(
    baseline_snapshot: dict[str, Any], outline_width: float
) -> None:
    """非 PBT 锚点：``enable_outline=False`` 下 ``outline_width`` 取边界值
    与默认值时，输出仍与 baseline 等价。
    """
    snapshot = _run_vector_branch_capture(
        outline_width=float(outline_width),
        color_mode=_BASELINE_COLOR_MODE,
        backing_color_id=_BASELINE_BACKING_COLOR_ID,
        structure_mode=_BASELINE_STRUCTURE_MODE,
        enable_fridge_magnet=False,
        enable_coating=False,
        enable_base_layer_height_modifier=True,
    )
    assert snapshot["scene_geometry_names"] == baseline_snapshot["scene_geometry_names"]
    assert "Outline" not in snapshot["scene_geometry_names"]
    assert snapshot["per_mesh_fingerprint"] == baseline_snapshot["per_mesh_fingerprint"]
    for key in (
        "bambu_base_height_mm",
        "bambu_color_height_mm",
        "bambu_face_orientation",
        "enable_base_layer_height_modifier",
    ):
        assert snapshot[key] == baseline_snapshot[key]
    assert snapshot["preview_colors"] == baseline_snapshot["preview_colors"]
    assert snapshot["slot_names_in_export"] == baseline_snapshot["slot_names_in_export"]
    assert snapshot["project_slot_names"] == baseline_snapshot["project_slot_names"]
