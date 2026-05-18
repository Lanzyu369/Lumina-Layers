"""Integration tests for the material-archive vector branch wiring.

Pins the high-level contract that
:func:`core.pipeline.vector_branch._build_vector_processor` returns a
``VectorProcessor`` whose ``img_processor`` carries the material
solver's duck-typed surface, and that ``analyze_svg`` consumes that
matcher's pre-built ``color_conf`` instead of falling back to
``ColorSystem.get``.

锁定耗材档案矢量分支的关键集成点：``_build_vector_processor``
应注入 ``MaterialVectorMatcher``，``analyze_svg`` 必须从匹配器
取 ``color_conf``，与 LUT 路径走完全相同的解析/裁剪/预览管线。
"""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pytest
from shapely.geometry import box

from core.vector_matchers import MATERIAL_ARCHIVE_LUT_SENTINEL


def _material_archive_ctx() -> dict:
    """Minimal ctx mirroring what S01 / P01 produce for material_archive."""
    return {
        "material_source": "material_archive",
        "_material_params": [object(), object(), object()],
        "color_layers": 5,
        "layer_height_mm": 0.08,
        "material_substrate": "white",
        "slot_names": ["White", "Red", "Black"],
        "preview_colors": {
            0: (255, 255, 255, 255),
            1: (255, 0, 0, 255),
            2: (0, 0, 0, 255),
        },
        "color_conf": {
            "name": "Material",
            "slots": ["White", "Red", "Black"],
            "preview": {
                0: (255, 255, 255, 255),
                1: (255, 0, 0, 255),
                2: (0, 0, 0, 255),
            },
            "map": {"White": 0, "Red": 1, "Black": 2},
        },
        "grid_resolution": 64,
    }


def _patch_material_cache_resolution():
    """Patch the cache resolution helpers so the matcher can be built
    without touching disk or running the real Beer-Lambert solver.

    The stub :class:`_StubSolverCache` is shared with the matcher unit
    tests' philosophy: matched_rgb echoes the query, recipes encode the
    row index for observability.
    """

    class _StubSolverCache:
        metadata = {"mean_delta_e": 0.0, "max_delta_e": 0.0}

        def __init__(self, layer_count):
            self.layer_count = int(layer_count)

        def lookup(self, unique_colors, materials, *, hue_weight=0.0):
            n = unique_colors.shape[0]
            matched = unique_colors.astype(np.uint8, copy=True)
            recipes_b2t = np.zeros((n, self.layer_count), dtype=np.int32)
            for i in range(n):
                for z in range(self.layer_count):
                    recipes_b2t[i, z] = (i + z) % max(1, len(materials))
            return matched, recipes_b2t, np.zeros((n,), dtype=np.float64)

    # ``MaterialVectorMatcher.from_materials`` imports the resolver
    # lazily from ``core.material_cache``, so the patch must target the
    # source module rather than the matcher module's namespace.
    # 在 ``MaterialVectorMatcher.from_materials`` 内部按需导入，所以
    # patch 必须指向 ``core.material_cache`` 这个真正的来源模块。
    return patch(
        "core.material_cache.load_material_solver_cache_with_fallback",
        return_value=(_StubSolverCache(5), 64),
    )


class TestBuildVectorProcessorRouting:
    def test_lut_source_uses_lut_constructor(self):
        from core.pipeline.vector_branch import _build_vector_processor

        ctx = {
            "material_source": "lut",
            "actual_lut_path": "/tmp/test.npy",
        }

        with patch(
            "core.vector_engine.VectorProcessor.__init__",
            return_value=None,
        ) as init_mock, patch(
            "core.vector_engine.VectorProcessor.from_img_processor"
        ) as factory_mock:
            _build_vector_processor(ctx, fallback_color_mode="4-Color (RYBW)")

        init_mock.assert_called_once_with("/tmp/test.npy", "4-Color (RYBW)")
        factory_mock.assert_not_called()

    def test_material_archive_source_uses_matcher(self):
        from core.pipeline.vector_branch import _build_vector_processor
        from core.vector_matchers import MaterialVectorMatcher

        ctx = _material_archive_ctx()

        with _patch_material_cache_resolution():
            vp = _build_vector_processor(ctx, fallback_color_mode="4-Color (RYBW)")

        assert isinstance(vp.img_processor, MaterialVectorMatcher)
        assert vp.color_mode == "Material Archive"
        assert vp.img_processor.lut_path == MATERIAL_ARCHIVE_LUT_SENTINEL

    def test_material_archive_source_passes_hue_weight_to_matcher(self):
        from core.pipeline.vector_branch import _build_vector_processor

        ctx = _material_archive_ctx()
        ctx["hue_weight"] = 0.5

        with _patch_material_cache_resolution():
            vp = _build_vector_processor(ctx, fallback_color_mode="4-Color (RYBW)")

        assert vp.img_processor.hue_weight == pytest.approx(0.5)

    def test_material_archive_source_enables_gradient_color_bands(self):
        from core.pipeline.vector_branch import _build_vector_processor

        ctx = _material_archive_ctx()
        ctx["quantize_colors"] = 24

        with _patch_material_cache_resolution():
            vp = _build_vector_processor(ctx, fallback_color_mode="4-Color (RYBW)")

        assert vp.gradient_color_bands == 24

    def test_material_archive_without_materials_raises(self):
        from core.pipeline.vector_branch import _build_vector_processor

        ctx = _material_archive_ctx()
        ctx["_material_params"] = []  # invalid: empty materials

        with pytest.raises(ValueError, match="non-empty _material_params"):
            _build_vector_processor(ctx, fallback_color_mode="4-Color (RYBW)")


class TestAnalyzeSvgConsumesMatcherColorConf:
    """When the injected matcher carries ``color_conf`` /
    ``preview_colors`` / ``slot_names`` / ``layer_count``,
    ``VectorProcessor.analyze_svg`` must source ``num_layers`` and the
    color system from those instead of falling back to
    ``ColorSystem.get`` + ``PrinterConfig.COLOR_LAYERS``.

    matcher 自带的 color_conf 与 layer_count 必须被 analyze_svg
    采纳，否则材料模式会沿用 LUT 默认配置导致语义错位。
    """

    def test_color_conf_path_is_taken_when_matcher_exposes_it(self):
        # Build a fake matcher carrying the duck-typed surface.
        from core.vector_engine import VectorProcessor

        class _FakeMatcher:
            lut_path = MATERIAL_ARCHIVE_LUT_SENTINEL
            color_mode = "Material Archive"
            color_conf = {
                "name": "Material",
                "slots": ["A", "B"],
                "preview": {0: (1, 2, 3, 255), 1: (4, 5, 6, 255)},
                "map": {"A": 0, "B": 1},
            }
            slot_names = ["A", "B"]
            preview_colors = color_conf["preview"]
            layer_count = 7  # NB: differs from PrinterConfig default

            @staticmethod
            def _rgb_to_lab(arr):
                from core.vector_matchers import _rgb_to_lab_static

                return _rgb_to_lab_static(arr)

            def solve_for_fills(self, rgbs):
                # No-op: the test does not exercise the match step.
                pass

        _FakeMatcher.lut_rgb = np.zeros((0, 3), dtype=np.uint8)
        _FakeMatcher.ref_stacks = np.zeros((0, 7), dtype=np.int32)
        _FakeMatcher.kdtree = None

        vp = VectorProcessor.from_img_processor(_FakeMatcher(), "Material Archive")

        # Patch the parse + clip steps so analyze_svg returns quickly
        # with a deterministic single-shape clipped_shapes list.
        from shapely.geometry import Polygon

        fake_shape = {
            "geometry": Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]),
            "color": (255, 0, 0),
            "draw_order": 0,
        }

        with patch.object(
            vp, "_parse_svg",
            return_value=([{"poly": fake_shape["geometry"], "color": fake_shape["color"]}], 1.0, (0, 0, 1, 1)),
        ), patch.object(
            vp, "_clip_occlusion",
            return_value=([fake_shape], None),
        ), patch(
            "core.vector_engine._VECTOR_PARSE_CLIP_CACHE",
            new={},
        ), patch.object(
            vp, "_match_colors",
            return_value=[
                {
                    "geometry": fake_shape["geometry"],
                    "recipe": [0, 0, 0, 0, 0, 0, 0],
                    "color": (255, 0, 0),
                    "matched_rgb": (255, 0, 0),
                    "lut_idx": 0,
                }
            ],
        ):
            analysis = vp.analyze_svg(
                svg_path="/tmp/fake.svg",
                target_width_mm=10.0,
            )

        # color_conf / slot_names / preview_colors come straight from the matcher.
        assert analysis.slot_names == ["A", "B"]
        assert analysis.preview_colors == {0: (1, 2, 3, 255), 1: (4, 5, 6, 255)}
        assert analysis.num_channels == 2
        # num_layers must come from matcher.layer_count, NOT the
        # PrinterConfig default.
        assert analysis.num_layers == 7

    def test_lut_path_still_consults_color_system(self):
        # When the img_processor does not expose ``color_conf`` (the LUT
        # path), analyze_svg must fall back to ``ColorSystem.get``. We
        # exercise this with a stub that mimics LuminaImageProcessor's
        # minimal surface but does not advertise ``color_conf``.
        # LUT 路径应继续走 ColorSystem.get，不被 matcher 改造影响。
        from core.vector_engine import VectorProcessor

        class _FakeLutProcessor:
            lut_path = "/tmp/legacy.npy"
            lut_rgb = np.zeros((10, 3), dtype=np.uint8)  # not 1296

            @staticmethod
            def _rgb_to_lab(arr):
                from core.vector_matchers import _rgb_to_lab_static

                return _rgb_to_lab_static(arr)

        vp = VectorProcessor.from_img_processor(_FakeLutProcessor(), "4-Color (RYBW)")

        from shapely.geometry import Polygon

        fake_shape = {
            "geometry": Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]),
            "color": (255, 0, 0),
            "draw_order": 0,
        }
        with patch.object(
            vp, "_parse_svg",
            return_value=([{"poly": fake_shape["geometry"], "color": fake_shape["color"]}], 1.0, (0, 0, 1, 1)),
        ), patch.object(
            vp, "_clip_occlusion",
            return_value=([fake_shape], None),
        ), patch(
            "core.vector_engine._VECTOR_PARSE_CLIP_CACHE",
            new={},
        ), patch.object(
            vp, "_match_colors",
            return_value=[
                {
                    "geometry": fake_shape["geometry"],
                    "recipe": [0],
                    "color": (255, 0, 0),
                    "matched_rgb": (255, 0, 0),
                    "lut_idx": 0,
                }
            ],
        ):
            analysis = vp.analyze_svg(
                svg_path="/tmp/legacy.svg",
                target_width_mm=10.0,
            )

        # ColorSystem 4-Color (RYBW) ships 4 slots — sanity check that
        # the LUT path used the historical ColorSystem.get lookup
        # (otherwise we would see ``slots=["A", "B"]``).
        assert analysis.num_channels == 4

    def test_material_archive_gradient_svg_presolves_mid_green(self, tmp_path):
        from core.vector_engine import VectorProcessor
        from core.vector_matchers import _rgb_to_lab_static

        seen: list[tuple[int, int, int]] = []

        class _FakeMatcher:
            lut_path = MATERIAL_ARCHIVE_LUT_SENTINEL
            color_mode = "Material Archive"
            color_conf = {
                "name": "Material",
                "slots": ["Yellow", "Green", "Cyan"],
                "preview": {
                    0: (255, 255, 0, 255),
                    1: (0, 255, 0, 255),
                    2: (0, 255, 255, 255),
                },
                "map": {"Yellow": 0, "Green": 1, "Cyan": 2},
            }
            slot_names = ["Yellow", "Green", "Cyan"]
            preview_colors = color_conf["preview"]
            layer_count = 5
            lut_rgb = np.zeros((0, 3), dtype=np.uint8)
            ref_stacks = np.zeros((0, 5), dtype=np.int32)
            kdtree = None

            @staticmethod
            def _rgb_to_lab(arr):
                return _rgb_to_lab_static(arr)

            def solve_for_fills(self, rgbs):
                seen.extend(tuple(int(c) for c in rgb) for rgb in rgbs)

        svg_path = tmp_path / "ticket-ce7721bf-gradient.svg"
        svg_path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
            "<defs>"
            '<linearGradient id="g" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="100" y2="0">'
            '<stop offset="0" stop-color="#ffff00"/>'
            '<stop offset="1" stop-color="#00ffff"/>'
            "</linearGradient>"
            "</defs>"
            '<rect x="0" y="0" width="100" height="100" fill="url(#g)"/>'
            "</svg>",
            encoding="utf-8",
        )

        vp = VectorProcessor.from_img_processor(_FakeMatcher(), "Material Archive")
        vp.gradient_color_bands = 17
        with patch("core.vector_engine._VECTOR_PARSE_CLIP_CACHE", new={}), patch.object(
            vp,
            "_build_small_shape_match_overrides",
            return_value={},
        ), patch.object(
            vp,
            "_match_colors",
            return_value=[],
        ):
            vp.analyze_svg(str(svg_path), target_width_mm=100.0)

        assert any(
            110 <= red <= 145 and green >= 250 and 110 <= blue <= 145
            for red, green, blue in seen
        )


class TestAnalyzeSvgMaterialSmallShapeSnap:
    def _build_fake_matcher(self):
        from core.vector_matchers import _rgb_to_lab_static

        lut_rgb = np.array(
            [
                [245, 89, 56],
                [87, 51, 51],
                [247, 204, 153],
            ],
            dtype=np.uint8,
        )

        class _FakeMatcher:
            lut_path = MATERIAL_ARCHIVE_LUT_SENTINEL
            color_mode = "Material Archive"
            color_conf = {
                "name": "Material",
                "slots": ["A", "B", "C"],
                "preview": {
                    0: (245, 89, 56, 255),
                    1: (87, 51, 51, 255),
                    2: (247, 204, 153, 255),
                },
                "map": {"A": 0, "B": 1, "C": 2},
            }
            slot_names = ["A", "B", "C"]
            preview_colors = color_conf["preview"]
            layer_count = 5

            @staticmethod
            def _rgb_to_lab(arr):
                return _rgb_to_lab_static(arr)

            def solve_for_fills(self, rgbs):
                return None

        _FakeMatcher.lut_rgb = lut_rgb
        _FakeMatcher.ref_stacks = np.array(
            [
                [0, 0, 0, 0, 0],
                [1, 1, 1, 1, 1],
                [2, 2, 2, 2, 2],
            ],
            dtype=np.int32,
        )
        _FakeMatcher.kdtree = _BruteForceLabTree(
            _rgb_to_lab_static(lut_rgb).reshape(-1, 3)
        )
        return _FakeMatcher()

    def test_small_shape_snaps_to_large_anchor_fill(self):
        from config import VectorConfig
        from core.vector_engine import VectorProcessor

        vp = VectorProcessor.from_img_processor(self._build_fake_matcher(), "Material Archive")
        orange = (255, 80, 35)
        dark_brown = (64, 20, 9)
        clipped_shapes = [
            {"geometry": box(0.0, 0.0, 10.0, 10.0), "color": orange, "draw_order": 0},
            {"geometry": box(11.0, 0.0, 12.0, 1.0), "color": dark_brown, "draw_order": 1},
        ]

        with patch.object(
            vp, "_parse_svg",
            return_value=([{"poly": item["geometry"], "color": item["color"]} for item in clipped_shapes], 1.0, (0, 0, 12, 10)),
        ), patch.object(
            vp, "_clip_occlusion",
            return_value=(clipped_shapes, None),
        ), patch(
            "core.vector_engine._VECTOR_PARSE_CLIP_CACHE",
            new={},
        ), patch.object(
            VectorConfig,
            "MATERIAL_VECTOR_SMALL_SHAPE_SNAP_MAX_AREA_RATIO",
            0.02,
        ), patch.object(
            VectorConfig,
            "MATERIAL_VECTOR_SMALL_SHAPE_SNAP_MIN_ANCHOR_AREA_RATIO",
            0.10,
        ), patch.object(
            VectorConfig,
            "MATERIAL_VECTOR_SMALL_SHAPE_SNAP_DELTA_E",
            20.0,
        ):
            analysis = vp.analyze_svg(
                svg_path="/tmp/fake.svg",
                target_width_mm=12.0,
            )

        by_src = {tuple(item["color"]): item for item in analysis.matched_shapes}
        # Small-shape snap is now disabled for material-archive mode
        # (PR #177 regression fix). Small shapes keep their own fill colour.
        assert by_src[dark_brown]["match_color"] == dark_brown
        assert by_src[dark_brown]["matched_rgb"] == (87, 51, 51)
        assert by_src[orange]["match_color"] == orange

    def test_large_shape_keeps_own_fill_even_with_high_delta_e(self):
        from config import VectorConfig
        from core.vector_engine import VectorProcessor

        vp = VectorProcessor.from_img_processor(self._build_fake_matcher(), "Material Archive")
        orange = (255, 80, 35)
        dark_brown = (64, 20, 9)
        clipped_shapes = [
            {"geometry": box(0.0, 0.0, 10.0, 10.0), "color": orange, "draw_order": 0},
            {"geometry": box(0.0, 11.0, 8.0, 19.0), "color": dark_brown, "draw_order": 1},
        ]

        with patch.object(
            vp, "_parse_svg",
            return_value=([{"poly": item["geometry"], "color": item["color"]} for item in clipped_shapes], 1.0, (0, 0, 10, 19)),
        ), patch.object(
            vp, "_clip_occlusion",
            return_value=(clipped_shapes, None),
        ), patch(
            "core.vector_engine._VECTOR_PARSE_CLIP_CACHE",
            new={},
        ), patch.object(
            VectorConfig,
            "MATERIAL_VECTOR_SMALL_SHAPE_SNAP_MAX_AREA_RATIO",
            0.02,
        ), patch.object(
            VectorConfig,
            "MATERIAL_VECTOR_SMALL_SHAPE_SNAP_MIN_ANCHOR_AREA_RATIO",
            0.10,
        ), patch.object(
            VectorConfig,
            "MATERIAL_VECTOR_SMALL_SHAPE_SNAP_DELTA_E",
            20.0,
        ):
            analysis = vp.analyze_svg(
                svg_path="/tmp/fake-large.svg",
                target_width_mm=10.0,
            )

        by_src = {tuple(item["color"]): item for item in analysis.matched_shapes}
        assert by_src[dark_brown]["match_color"] == dark_brown
        assert by_src[dark_brown]["matched_rgb"] == (87, 51, 51)

    def test_many_small_fragments_same_color_still_snap_per_shape(self):
        from config import VectorConfig
        from core.vector_engine import VectorProcessor

        vp = VectorProcessor.from_img_processor(self._build_fake_matcher(), "Material Archive")
        orange = (255, 80, 35)
        dark_brown = (64, 20, 9)
        clipped_shapes = [
            {"geometry": box(0.0, 0.0, 10.0, 10.0), "color": orange, "draw_order": 0},
        ]
        for idx in range(12):
            x0 = 11.0 + idx * 1.1
            clipped_shapes.append(
                {
                    "geometry": box(x0, 0.0, x0 + 1.0, 1.0),
                    "color": dark_brown,
                    "draw_order": idx + 1,
                }
            )

        with patch.object(
            vp, "_parse_svg",
            return_value=([{"poly": item["geometry"], "color": item["color"]} for item in clipped_shapes], 1.0, (0, 0, 25, 10)),
        ), patch.object(
            vp, "_clip_occlusion",
            return_value=(clipped_shapes, None),
        ), patch(
            "core.vector_engine._VECTOR_PARSE_CLIP_CACHE",
            new={},
        ), patch.object(
            VectorConfig,
            "MATERIAL_VECTOR_SMALL_SHAPE_SNAP_MAX_AREA_RATIO",
            0.02,
        ), patch.object(
            VectorConfig,
            "MATERIAL_VECTOR_SMALL_SHAPE_SNAP_MIN_ANCHOR_AREA_RATIO",
            0.10,
        ), patch.object(
            VectorConfig,
            "MATERIAL_VECTOR_SMALL_SHAPE_SNAP_DELTA_E",
            20.0,
        ):
            analysis = vp.analyze_svg(
                svg_path="/tmp/fake-fragments.svg",
                target_width_mm=25.0,
            )

        brown_shapes = [
            item for item in analysis.matched_shapes
            if tuple(item["color"]) == dark_brown
        ]
        assert brown_shapes
        # Small-shape snap is now disabled for material-archive mode.
        # Each small shape keeps its own fill and is matched independently.
        assert all(item["match_color"] == dark_brown for item in brown_shapes)
        assert all(item["matched_rgb"] == (87, 51, 51) for item in brown_shapes)


class _BruteForceLabTree:
    def __init__(self, lab_points: np.ndarray):
        self.lab_points = np.asarray(lab_points, dtype=np.float64).reshape(-1, 3)

    def query(self, query_points):
        q = np.asarray(query_points, dtype=np.float64).reshape(-1, 3)
        d = np.linalg.norm(q[:, None, :] - self.lab_points[None, :, :], axis=2)
        idx = np.argmin(d, axis=1)
        return d[np.arange(len(idx)), idx], idx
