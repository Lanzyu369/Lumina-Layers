"""Unit tests for vector-mode region-replacement propagation.
矢量模式区域替换在生成阶段是否正确回写到 ``VectorAnalysis``。

These tests cover the public helper ``apply_matched_rgb_overrides_to_analysis``
which is the bridge between (a) ``cache.matched_rgb`` mutated by
``/region-replace`` and ``/region-replace-batch`` and (b) the SVG-native
``_run_vector_branch``. Without this helper, region/multi-select edits
made through ColorWorkstation only show up in 2D / GLB previews and are
silently dropped from the generated 3MF.

测试覆盖 ``apply_matched_rgb_overrides_to_analysis``：当用户在 2D 预览
里通过 ``/region-replace`` 把某个像素区域改色后，生成阶段必须把那段
改色回写到 ``VectorAnalysis.matched_shapes``，否则 3MF 不会反映用户改动。
"""

from __future__ import annotations

import importlib.util
import os
import sys
import types

import numpy as np
import pytest
from scipy.spatial import cKDTree
from shapely.geometry import box

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

# Same isolated-load trick used by other vector_engine unit tests so we
# don't pull in core/__init__'s heavy import chain.
# 复用其它 vector_engine 单元测试的隔离加载技巧，避免引入 core/__init__
# 的重型导入链。
_spec = importlib.util.spec_from_file_location(
    "core.vector_engine",
    os.path.join(_ROOT, "core", "vector_engine.py"),
)
_ve = importlib.util.module_from_spec(_spec)
if "core" not in sys.modules:
    _pkg = types.ModuleType("core")
    _pkg.__path__ = [os.path.join(_ROOT, "core")]
    sys.modules["core"] = _pkg
sys.modules["core.vector_engine"] = _ve
_spec.loader.exec_module(_ve)

VectorAnalysis = _ve.VectorAnalysis
apply_matched_rgb_overrides_to_analysis = getattr(
    _ve, "apply_matched_rgb_overrides_to_analysis", None
)


# ---------------------------------------------------------------------------
# Minimal LUT fixture: 4 RGB anchors mapped to 4 distinct channel ids so the
# generated recipe makes the active channel obvious.
# ---------------------------------------------------------------------------


def _build_fake_img_processor() -> object:
    """Construct a SimpleNamespace-style stub providing the attributes
    ``_match_colors`` and the new override helper need.

    构造 ``_match_colors`` 与新增 helper 需要的最小 LUT 接口：
    ``lut_rgb``、``ref_stacks``、``kdtree`` 与 ``_rgb_to_lab``。
    """

    lut_rgb = np.array(
        [
            [255, 255, 255],  # idx 0 (white / backing)
            [255, 0, 0],      # idx 1 (red)
            [0, 255, 0],      # idx 2 (green)
            [0, 0, 255],      # idx 3 (blue)
        ],
        dtype=np.uint8,
    )

    # Each LUT entry's ref_stacks[idx] gives a per-layer channel id. Five
    # layers per entry, all pointing at that LUT row, so a recipe lookup
    # for matched_rgb == lut_rgb[i] yields a recipe of [i, i, i, i, i].
    # 每条 LUT 的 ref_stacks 行让所有层都用同一个通道，方便测试断言。
    ref_stacks = np.array(
        [[0, 0, 0, 0, 0], [1, 1, 1, 1, 1], [2, 2, 2, 2, 2], [3, 3, 3, 3, 3]],
        dtype=np.int16,
    )

    rgb_for_lab = np.expand_dims(lut_rgb, axis=0)  # (1, N, 3)
    import cv2

    bgr = cv2.cvtColor(rgb_for_lab, cv2.COLOR_RGB2BGR)
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2Lab).astype(np.float64).reshape(-1, 3)
    kdtree = cKDTree(lab)

    class _StubProcessor:
        def __init__(self) -> None:
            self.lut_rgb = lut_rgb
            self.ref_stacks = ref_stacks
            self.kdtree = kdtree

        @staticmethod
        def _rgb_to_lab(rgb_array: np.ndarray) -> np.ndarray:
            arr = np.asarray(rgb_array, dtype=np.uint8)
            if arr.ndim == 1:
                arr = arr.reshape(1, -1)
            arr_3d = arr.reshape(1, -1, 3)
            bgr = cv2.cvtColor(arr_3d, cv2.COLOR_RGB2BGR)
            return cv2.cvtColor(bgr, cv2.COLOR_BGR2Lab).astype(np.float64).reshape(-1, 3)

    return _StubProcessor()


def _make_two_shape_analysis() -> "VectorAnalysis":
    """Build a 10×10 mm canvas with two adjacent halves: top=red, bottom=green.

    构造一个 10×10 mm 画布，上半红、下半绿；scale_factor=1.0 让 ``bbox``
    单位与毫米一致，预览网格密度为默认 10 px/mm，便于断言。
    """
    top = box(0.0, 0.0, 10.0, 5.0)
    bot = box(0.0, 5.0, 10.0, 10.0)

    # ``recipe`` and ``matched_rgb`` mirror the output _match_colors would
    # produce against the fake LUT above (red → idx 1, green → idx 2).
    matched_shapes = [
        {
            "geometry": top,
            "color": (255, 0, 0),
            "matched_rgb": (255, 0, 0),
            "lut_idx": 1,
            "recipe": [1, 1, 1, 1, 1],
        },
        {
            "geometry": bot,
            "color": (0, 255, 0),
            "matched_rgb": (0, 255, 0),
            "lut_idx": 2,
            "recipe": [2, 2, 2, 2, 2],
        },
    ]

    return VectorAnalysis(
        shape_data=[],
        clipped_shapes=[
            {"geometry": top, "color": (255, 0, 0)},
            {"geometry": bot, "color": (0, 255, 0)},
        ],
        matched_shapes=matched_shapes,
        silhouette=None,
        scale_factor=1.0,
        bbox=(0.0, 0.0, 10.0, 10.0),
        color_conf={"slots": ["W", "R", "G", "B"], "preview": {}},
        slot_names=["W", "R", "G", "B"],
        num_channels=4,
        num_layers=5,
        preview_colors={
            0: [255, 255, 255, 255],
            1: [255, 0, 0, 255],
            2: [0, 255, 0, 255],
            3: [0, 0, 255, 255],
        },
    )


def _build_grid_arrays(
    analysis: "VectorAnalysis",
    pixels_per_mm: float = 10.0,
) -> tuple[np.ndarray, np.ndarray, int, int]:
    """Return ``(matched_rgb, mask_solid, h_px, w_px)`` aligned with the
    grid ``apply_matched_rgb_overrides_to_analysis`` will reproduce.

    构造与 helper 内部网格一致的 ``matched_rgb`` / ``mask_solid``，
    其中上半填红、下半填绿。
    """
    real_w = float(analysis.bbox[2])
    real_h = float(analysis.bbox[3])
    sf = float(analysis.scale_factor)
    w_mm = real_w * sf
    h_mm = real_h * sf
    w_px = max(1, int(round(w_mm * pixels_per_mm)))
    h_px = max(1, int(round(h_mm * pixels_per_mm)))

    matched_rgb = np.zeros((h_px, w_px, 3), dtype=np.uint8)
    mask_solid = np.zeros((h_px, w_px), dtype=bool)

    half = h_px // 2
    matched_rgb[:half, :, :] = (255, 0, 0)
    matched_rgb[half:, :, :] = (0, 255, 0)
    mask_solid[:, :] = True

    return matched_rgb, mask_solid, h_px, w_px


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    apply_matched_rgb_overrides_to_analysis is None,
    reason="apply_matched_rgb_overrides_to_analysis not yet implemented",
)
class TestApplyMatchedRgbOverrides:
    """Verify ``apply_matched_rgb_overrides_to_analysis`` propagates a
    ``cache.matched_rgb`` mutation back into ``analysis.matched_shapes``.

    校验 helper 把 ``cache.matched_rgb`` 的修改回写到 ``matched_shapes``。
    """

    def test_region_replace_red_to_blue_updates_matched_shape(self):
        """Pixel-level red→blue swap on the top half must rewrite the
        matched shape's ``matched_rgb`` and ``recipe``.

        红→蓝的像素级覆写必须让顶部 shape 的 matched_rgb / recipe 跟着
        变成蓝色通道；否则生成的 3MF 仍按原 LUT 配方，错失用户改色。
        """
        analysis = _make_two_shape_analysis()
        img_processor = _build_fake_img_processor()
        matched_rgb, mask_solid, h_px, _ = _build_grid_arrays(analysis)

        # Simulate /region-replace: top half red → blue.
        # 模拟 /region-replace：上半红色像素整体改写为蓝色。
        half = h_px // 2
        matched_rgb[:half, :, :] = (0, 0, 255)

        changed = apply_matched_rgb_overrides_to_analysis(
            analysis,
            matched_rgb=matched_rgb,
            mask_solid=mask_solid,
            img_processor=img_processor,
        )

        assert changed == 1, "exactly one shape's colour was edited"
        top_shape = analysis.matched_shapes[0]
        bot_shape = analysis.matched_shapes[1]

        assert top_shape["matched_rgb"] == (0, 0, 255)
        assert top_shape["recipe"] == [3, 3, 3, 3, 3]
        # Untouched bottom shape stays on the green LUT entry.
        assert bot_shape["matched_rgb"] == (0, 255, 0)
        assert bot_shape["recipe"] == [2, 2, 2, 2, 2]

    def test_no_change_returns_zero_and_keeps_recipes(self):
        """When ``matched_rgb`` matches the existing shape colours the
        helper must be a no-op.

        当 ``matched_rgb`` 与现有 shape 颜色一致时，helper 应不改写任何
        shape，避免重复运算引入随机抖动。
        """
        analysis = _make_two_shape_analysis()
        img_processor = _build_fake_img_processor()
        matched_rgb, mask_solid, _, _ = _build_grid_arrays(analysis)

        changed = apply_matched_rgb_overrides_to_analysis(
            analysis,
            matched_rgb=matched_rgb,
            mask_solid=mask_solid,
            img_processor=img_processor,
        )

        assert changed == 0
        assert analysis.matched_shapes[0]["recipe"] == [1, 1, 1, 1, 1]
        assert analysis.matched_shapes[1]["recipe"] == [2, 2, 2, 2, 2]

    def test_pixels_outside_mask_solid_are_ignored(self):
        """Mutations on background pixels (``mask_solid == False``) must
        not influence the per-shape dominant colour vote.

        ``mask_solid`` 之外的像素（背景）即便被改写也不能影响 shape 的
        dominant 颜色统计；防止背景噪声误改正确的 shape 配方。
        """
        analysis = _make_two_shape_analysis()
        img_processor = _build_fake_img_processor()
        matched_rgb, mask_solid, h_px, w_px = _build_grid_arrays(analysis)

        # Carve a thin background strip across the top half but flood it
        # with blue. The shape mask still claims the strip pixels so this
        # exercises the mask_solid intersection guard.
        # 在上半挖一条细 background 条并涂蓝；shape mask 还覆盖这条带，
        # 用来检查 mask_solid 求交是否真的过滤掉了背景颜色。
        half = h_px // 2
        bg_strip = slice(0, max(1, half // 4))
        mask_solid[bg_strip, :] = False
        matched_rgb[bg_strip, :, :] = (0, 0, 255)

        changed = apply_matched_rgb_overrides_to_analysis(
            analysis,
            matched_rgb=matched_rgb,
            mask_solid=mask_solid,
            img_processor=img_processor,
        )

        assert changed == 0
        assert analysis.matched_shapes[0]["matched_rgb"] == (255, 0, 0)
        assert analysis.matched_shapes[0]["recipe"] == [1, 1, 1, 1, 1]

    def test_grid_size_mismatch_returns_zero_and_logs(self, caplog):
        """If ``matched_rgb`` shape disagrees with the helper's
        reconstructed grid, refuse silently and emit a warning rather
        than corrupting the analysis.

        当 ``matched_rgb`` 尺寸与 helper 复算的 preview 网格不一致时，
        函数应直接放弃改写并发出警告，避免破坏 ``matched_shapes``。
        """
        analysis = _make_two_shape_analysis()
        img_processor = _build_fake_img_processor()

        bogus_rgb = np.zeros((11, 11, 3), dtype=np.uint8)
        bogus_mask = np.ones((11, 11), dtype=bool)

        with caplog.at_level("WARNING"):
            changed = apply_matched_rgb_overrides_to_analysis(
                analysis,
                matched_rgb=bogus_rgb,
                mask_solid=bogus_mask,
                img_processor=img_processor,
            )

        assert changed == 0
        assert analysis.matched_shapes[0]["recipe"] == [1, 1, 1, 1, 1]
        # Warning text must mention the mismatched shape so on-call can
        # debug the upstream cache serialization quickly.
        # 警告文案需要含失配尺寸，方便排查上游缓存序列化是否走样。
        joined = " ".join(rec.message for rec in caplog.records)
        assert "shape" in joined.lower() or "grid" in joined.lower()


@pytest.mark.skipif(
    apply_matched_rgb_overrides_to_analysis is not None,
    reason=(
        "Reproducer guard: only meaningful while the helper is missing. "
        "Once apply_matched_rgb_overrides_to_analysis exists this test is "
        "auto-skipped, leaving the behavioural suite above as the regression."
    ),
)
def test_helper_must_be_exported_from_vector_engine():
    """Red-light reproducer: documents the missing public surface.

    红灯复现：在 helper 真正落地前，明确指出 ``vector_engine`` 缺少这
    个公共函数；helper 一旦实现该测试自动跳过，让上面的行为测试接管
    回归保护。
    """
    pytest.fail(
        "core.vector_engine.apply_matched_rgb_overrides_to_analysis "
        "is required so vector-mode region replacements survive "
        "into the generated 3MF."
    )


# ---------------------------------------------------------------------------
# Coordinator wiring: ensure ``_run_vector_branch`` reads the new ctx keys
# (``matched_rgb_path`` / ``mask_solid_path``) and forwards them to the
# helper. Without this hookup the helper would never run in production.
# ---------------------------------------------------------------------------


class TestRunVectorBranchWiring:
    """Verify the coordinator forwards cache snapshots to the helper.

    校验 ``_run_vector_branch`` 把 ``matched_rgb_path`` / ``mask_solid_path``
    透传给 ``apply_matched_rgb_overrides_to_analysis``，确保生产环境真的
    会调用我们的修复函数。
    """

    def _patch_dependencies(self, captured: dict, helper_call_log: list[dict]):
        """Build the patch context shared by both wiring tests.

        构造两个 wiring 测试共用的 patch 上下文，覆盖 VectorProcessor、
        3MF 导出器与 helper 调用。
        """
        from types import SimpleNamespace
        from unittest.mock import patch

        import trimesh

        from core.pipeline import coordinator

        class _FakeVectorProcessor:
            parse_warnings: list[str] = []
            last_stage_timings: dict[str, float] = {}

            def __init__(self, _lut_path: str, color_mode: str) -> None:
                self.color_mode = color_mode
                self.enable_fridge_magnet = False
                self.fridge_magnets = []
                # Non-trivial sentinel so the helper patch can confirm it
                # got the same processor object the branch used.
                # 非平凡哨兵；helper patch 用它确认收到的就是分支构造的处理器。
                self.img_processor = SimpleNamespace(tag="fake-img-processor")

            def analyze_svg(self, *, svg_path: str, target_width_mm: float, color_replacements=None):
                del svg_path, target_width_mm, color_replacements
                return SimpleNamespace(
                    matched_shapes=[],
                    num_layers=5,
                    num_channels=4,
                    preview_colors={0: [255, 0, 0, 255]},
                    slot_names=["Slot 1"],
                )

            def build_mesh(self, *, analysis, thickness_mm: float, structure_mode: str):
                del analysis, thickness_mm, structure_mode
                scene = trimesh.Scene()
                scene.add_geometry(trimesh.creation.box(extents=(1, 1, 1)), geom_name="Slot 1")
                return scene

            @staticmethod
            def render_preview(analysis, pixels_per_mm: float):
                del analysis, pixels_per_mm
                return None

        def _fake_helper(*args, **kwargs):
            helper_call_log.append({"args": args, "kwargs": kwargs})
            return 0

        def _fake_export_scene_with_bambu_metadata(**kwargs):
            captured.update(kwargs)
            return kwargs["output_path"]

        return patch.multiple(
            "core.vector_engine",
            VectorProcessor=_FakeVectorProcessor,
            apply_matched_rgb_overrides_to_analysis=_fake_helper,
        ), patch(
            "utils.bambu_3mf_writer.export_scene_with_bambu_metadata",
            side_effect=_fake_export_scene_with_bambu_metadata,
        ), patch("core.naming.generate_model_filename", lambda *_args: "vector-out.3mf"), patch(
            "core.naming.generate_preview_filename",
            lambda *_args: "vector-preview.glb",
        ), patch("utils.Stats.increment", lambda *_args, **_kwargs: None), patch.object(
            coordinator,
            "_report_progress",
            lambda *_args, **_kwargs: None,
        )

    def test_helper_invoked_when_cache_paths_are_provided(self, tmp_path):
        """Spinning up a vector branch with both ``matched_rgb_path`` and
        ``mask_solid_path`` populated must invoke the helper exactly once.

        ``_run_vector_branch`` 拿到两条缓存路径时必须正好调用 helper 一次。
        """
        from unittest.mock import patch

        from config import MODELS_DIR, OUTPUT_DIR, ModelingMode
        from core.pipeline import coordinator

        matched_rgb_path = tmp_path / "matched.npy"
        mask_solid_path = tmp_path / "mask.npy"
        np.save(matched_rgb_path, np.zeros((4, 4, 3), dtype=np.uint8))
        np.save(mask_solid_path, np.ones((4, 4), dtype=bool))

        captured: dict = {}
        helper_calls: list[dict] = []
        cms = self._patch_dependencies(captured, helper_calls)

        with cms[0], cms[1], cms[2], cms[3], cms[4], cms[5], patch(
            "config.MODELS_DIR", str(tmp_path)
        ), patch("config.OUTPUT_DIR", str(tmp_path)):
            ctx = {
                "image_path": str(tmp_path / "vector.svg"),
                "actual_lut_path": str(tmp_path / "fake.json"),
                "color_mode": "5-Color Extended",
                "modeling_mode": ModelingMode.HIGH_FIDELITY,
                "target_width_mm": 40.0,
                "spacer_thick": 1.6,
                "structure_mode": "单面",
                "need_2d_preview": False,
                "printer_id": "bambu-h2d",
                "slicer": "BambuStudio",
                "nozzle_size": "0.4",
                "matched_rgb_path": str(matched_rgb_path),
                "mask_solid_path": str(mask_solid_path),
            }

            result = coordinator._run_vector_branch(ctx)

        assert "error" not in result
        assert len(helper_calls) == 1
        kwargs = helper_calls[0]["kwargs"]
        assert "matched_rgb" in kwargs
        assert "mask_solid" in kwargs
        # img_processor must be the FakeVectorProcessor's stub attribute,
        # not some unrelated object — the helper relies on its KDTree.
        # img_processor 必须是分支构造的处理器持有的对象，否则 helper 会
        # 拿到错误的 KDTree，等于没修。
        assert kwargs["img_processor"].tag == "fake-img-processor"

    def test_helper_skipped_when_only_one_cache_path_present(self, tmp_path):
        """Either path missing (or both) must skip the helper to avoid a
        partial / inconsistent override pass.

        只缺一条路径就要整体跳过 helper，避免半套覆盖污染 ``matched_shapes``。
        """
        from unittest.mock import patch

        from config import ModelingMode
        from core.pipeline import coordinator

        matched_rgb_path = tmp_path / "matched.npy"
        np.save(matched_rgb_path, np.zeros((4, 4, 3), dtype=np.uint8))

        captured: dict = {}
        helper_calls: list[dict] = []
        cms = self._patch_dependencies(captured, helper_calls)

        with cms[0], cms[1], cms[2], cms[3], cms[4], cms[5], patch(
            "config.MODELS_DIR", str(tmp_path)
        ), patch("config.OUTPUT_DIR", str(tmp_path)):
            ctx = {
                "image_path": str(tmp_path / "vector.svg"),
                "actual_lut_path": str(tmp_path / "fake.json"),
                "color_mode": "5-Color Extended",
                "modeling_mode": ModelingMode.HIGH_FIDELITY,
                "target_width_mm": 40.0,
                "spacer_thick": 1.6,
                "structure_mode": "单面",
                "need_2d_preview": False,
                "printer_id": "bambu-h2d",
                "slicer": "BambuStudio",
                "nozzle_size": "0.4",
                "matched_rgb_path": str(matched_rgb_path),
                # mask_solid_path intentionally absent / None
                "mask_solid_path": None,
            }

            result = coordinator._run_vector_branch(ctx)

        assert "error" not in result
        assert helper_calls == []
