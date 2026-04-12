"""
Unit tests for pipeline step modules.
管道步骤模块的单元测试。

覆盖范围：S01, S03, S06, S12, P01, P04, P05
测试边界情况：空输入、缺失键、无效参数

_需求: 9.3_
"""

import numpy as np
import pytest
from unittest.mock import MagicMock, patch

from config import ModelingMode, ColorSystem, PrinterConfig

# ===========================================================================
# S01 — s01_input_validation 单元测试
# ===========================================================================


class TestS01InputValidation:
    """S01 输入验证步骤的单元测试。"""

    def _make_valid_ctx(self) -> dict:
        """构造 S01 的最小有效 PipelineContext。"""
        return {
            "image_path": "/tmp/test.png",
            "lut_path": "/tmp/test.npy",
            "color_mode": "4-Color",
            "modeling_mode": ModelingMode.HIGH_FIDELITY,
            "backing_color_id": 0,
            "separate_backing": False,
        }

    def test_valid_input_produces_expected_keys(self):
        """有效输入应产生所有声明的输出键。"""
        from core.pipeline.s01_input_validation import run

        ctx = self._make_valid_ctx()
        result = run(ctx)

        assert "actual_lut_path" in result
        assert result["actual_lut_path"] == "/tmp/test.npy"
        assert "color_conf" in result
        assert "slot_names" in result
        assert "preview_colors" in result
        assert "is_svg_vector" in result
        assert result["is_svg_vector"] is False

    def test_none_lut_path_sets_error(self):
        """lut_path 为 None 时应设置 error 键。"""
        from core.pipeline.s01_input_validation import run

        ctx = self._make_valid_ctx()
        ctx["lut_path"] = None
        result = run(ctx)

        assert "error" in result
        assert "calibration" in result["error"].lower() or "npy" in result["error"].lower()

    def test_none_image_path_sets_error(self):
        """image_path 为 None 时应设置 error 键。"""
        from core.pipeline.s01_input_validation import run

        ctx = self._make_valid_ctx()
        ctx["image_path"] = None
        result = run(ctx)

        assert "error" in result
        assert "image" in result["error"].lower()

    def test_missing_image_path_raises_key_error(self):
        """缺失 image_path 键应抛出 KeyError。"""
        from core.pipeline.s01_input_validation import run

        ctx = self._make_valid_ctx()
        del ctx["image_path"]
        with pytest.raises(KeyError):
            run(ctx)

    def test_file_like_object_lut_path(self):
        """file-like 对象的 lut_path 应正确解析 .name 属性。"""
        from core.pipeline.s01_input_validation import run

        mock_file = MagicMock()
        mock_file.name = "/tmp/uploaded_lut.npy"

        ctx = self._make_valid_ctx()
        ctx["lut_path"] = mock_file
        result = run(ctx)

        assert result["actual_lut_path"] == "/tmp/uploaded_lut.npy"

    def test_invalid_lut_path_type_sets_error(self):
        """非字符串且无 .name 属性的 lut_path 应设置 error。"""
        from core.pipeline.s01_input_validation import run

        ctx = self._make_valid_ctx()
        ctx["lut_path"] = 12345  # 无效类型
        result = run(ctx)

        assert "error" in result

    def test_svg_vector_mode_detection(self):
        """SVG 文件 + VECTOR 模式应设置 is_svg_vector=True。"""
        from core.pipeline.s01_input_validation import run

        ctx = self._make_valid_ctx()
        ctx["image_path"] = "/tmp/test.svg"
        ctx["modeling_mode"] = ModelingMode.VECTOR
        result = run(ctx)

        assert result["is_svg_vector"] is True

    def test_empty_dict_raises_key_error(self):
        """空 dict 应抛出 KeyError。"""
        from core.pipeline.s01_input_validation import run

        with pytest.raises(KeyError):
            run({})


# ===========================================================================
# S03 — s03_color_replacement 单元测试
# ===========================================================================


class TestS03ColorReplacement:
    """S03 颜色替换步骤的单元测试。"""

    def _make_valid_ctx(self) -> dict:
        """构造 S03 的最小有效 PipelineContext。"""
        h, w = 4, 4
        matched_rgb = np.full((h, w, 3), [128, 64, 32], dtype=np.uint8)
        material_matrix = np.zeros((h, w, 5), dtype=int)
        mask_solid = np.ones((h, w), dtype=bool)

        processor = MagicMock()
        processor._rgb_to_lab = MagicMock(return_value=np.array([[50.0, 0.0, 0.0]]))
        processor.kdtree = MagicMock()
        processor.kdtree.query = MagicMock(return_value=(np.array([0.0]), np.array([0])))
        processor.ref_stacks = np.zeros((10, 5), dtype=int)
        processor.lut_rgb = np.zeros((10, 3), dtype=np.uint8)

        return {
            "matched_rgb": matched_rgb,
            "material_matrix": material_matrix,
            "mask_solid": mask_solid,
            "processor": processor,
            "color_replacements": None,
            "replacement_regions": None,
            "matched_rgb_path": None,
        }

    def test_no_replacement_preserves_matched_rgb(self):
        """无替换时 matched_rgb 应保持不变。"""
        from core.pipeline.s03_color_replacement import run

        ctx = self._make_valid_ctx()
        original_rgb = ctx["matched_rgb"].copy()
        result = run(ctx)

        np.testing.assert_array_equal(result["matched_rgb"], original_rgb)

    def test_no_replacement_preserves_material_matrix(self):
        """无替换时 material_matrix 应保持不变。"""
        from core.pipeline.s03_color_replacement import run

        ctx = self._make_valid_ctx()
        original_mat = ctx["material_matrix"].copy()
        result = run(ctx)

        np.testing.assert_array_equal(result["material_matrix"], original_mat)

    def test_missing_matched_rgb_raises_key_error(self):
        """缺失 matched_rgb 键应抛出 KeyError。"""
        from core.pipeline.s03_color_replacement import run

        ctx = self._make_valid_ctx()
        del ctx["matched_rgb"]
        with pytest.raises(KeyError):
            run(ctx)

    def test_empty_dict_raises_key_error(self):
        """空 dict 应抛出 KeyError。"""
        from core.pipeline.s03_color_replacement import run

        with pytest.raises(KeyError):
            run({})


# ===========================================================================
# S06 — s06_voxel_building 单元测试
# ===========================================================================


class TestS06VoxelBuilding:
    """S06 体素构建步骤的单元测试。"""

    def _make_valid_ctx(self) -> dict:
        """构造 S06 的最小有效 PipelineContext。"""
        h, w = 4, 4
        material_matrix = np.zeros((h, w, 5), dtype=int)
        mask_solid = np.ones((h, w), dtype=bool)
        matched_rgb = np.full((h, w, 3), [128, 64, 32], dtype=np.uint8)

        return {
            "material_matrix": material_matrix,
            "mask_solid": mask_solid,
            "spacer_thick": 1.2,
            "structure_mode": "单面",
            "backing_color_id": 0,
            "color_mode": "4-Color",
            "enable_cloisonne": False,
            "enable_relief": False,
            "color_height_map": None,
            "height_mode": "color",
            "heightmap_path": None,
            "heightmap_max_height": None,
            "matched_rgb": matched_rgb,
            "pixel_scale": 0.1,
        }

    @staticmethod
    def _make_magnet(
        *,
        shape: str,
        thickness_mm: float,
        center_x_mm: float = 0.0,
        center_y_mm: float = 0.0,
        diameter_mm: float | None = None,
        width_mm: float | None = None,
        height_mm: float | None = None,
    ) -> dict:
        return {
            "id": f"magnet-{shape}",
            "shape": shape,
            "preset_key": f"{shape}-preset",
            "diameter_mm": diameter_mm,
            "width_mm": width_mm,
            "height_mm": height_mm,
            "thickness_mm": thickness_mm,
            "center_x_mm": center_x_mm,
            "center_y_mm": center_y_mm,
        }

    def test_valid_input_produces_voxel_matrix(self):
        """有效输入应产生 full_matrix、backing_metadata、total_layers。"""
        from core.pipeline.s06_voxel_building import run

        ctx = self._make_valid_ctx()
        result = run(ctx)

        assert "full_matrix" in result
        assert "backing_metadata" in result
        assert "total_layers" in result
        assert isinstance(result["full_matrix"], np.ndarray)
        assert result["full_matrix"].ndim == 3  # (Z, H, W)

    def test_missing_material_matrix_raises_key_error(self):
        """缺失 material_matrix 键应抛出 KeyError。"""
        from core.pipeline.s06_voxel_building import run

        ctx = self._make_valid_ctx()
        del ctx["material_matrix"]
        with pytest.raises(KeyError):
            run(ctx)

    def test_missing_mask_solid_raises_key_error(self):
        """缺失 mask_solid 键应抛出 KeyError。"""
        from core.pipeline.s06_voxel_building import run

        ctx = self._make_valid_ctx()
        del ctx["mask_solid"]
        with pytest.raises(KeyError):
            run(ctx)

    def test_empty_dict_raises_key_error(self):
        """空 dict 应抛出 KeyError。"""
        from core.pipeline.s06_voxel_building import run

        with pytest.raises(KeyError):
            run({})

    def test_single_sided_structure(self):
        """单面模式应产生正确的层数。"""
        from core.pipeline.s06_voxel_building import run

        ctx = self._make_valid_ctx()
        ctx["structure_mode"] = "单面"
        result = run(ctx)

        # 单面: optical_layers + spacer_layers
        assert result["total_layers"] > 5  # 至少 5 层光学 + 1 层底板

    def test_double_sided_structure(self):
        """双面模式应产生更多层数。"""
        from core.pipeline.s06_voxel_building import run

        ctx = self._make_valid_ctx()
        ctx["structure_mode"] = "双面"
        result_double = run(ctx)

        ctx2 = self._make_valid_ctx()
        ctx2["structure_mode"] = "单面"
        result_single = run(ctx2)

        assert result_double["total_layers"] > result_single["total_layers"]

    def test_resolve_fridge_cavity_z_range_handles_both_backing_orientations(self):
        """冰箱贴槽位 Z 段应根据底板外侧方向保留 0.4mm 壳层。"""
        from core.pipeline.s06_voxel_building import _resolve_fridge_cavity_z_range

        shell_layers = max(1, int(round(0.4 / PrinterConfig.LAYER_HEIGHT)))
        cavity_layers = 4

        assert _resolve_fridge_cavity_z_range((0, 14), shell_layers, cavity_layers) == (5, 8)
        assert _resolve_fridge_cavity_z_range((5, 19), shell_layers, cavity_layers) == (11, 14)

    def test_centered_fridge_coords_use_pixel_extents_for_silhouette_center(self):
        """实体轮廓中心应基于像素外沿，而不是像素中心索引。"""
        from core.pipeline.s06_voxel_building import (
            _convert_centered_fridge_coords_to_raw_mm,
            _mask_solid_bounds_mm,
        )

        mask_solid = np.ones((7, 7), dtype=bool)

        bounds = _mask_solid_bounds_mm(mask_solid, 0.1)
        center_x_mm, center_y_mm = _convert_centered_fridge_coords_to_raw_mm(mask_solid, 0.1, 0.0, 0.0)

        assert bounds == pytest.approx((0.0, 0.0, 0.7, 0.7))
        assert center_x_mm == pytest.approx(0.35)
        assert center_y_mm == pytest.approx(0.35)

    def test_fridge_quantization_auto_expands_spacer_thick_before_carving(self):
        """当毫米厚度刚好等于磁铁厚度+0.4 时，也必须考虑 0.08mm 层高量化后给 cavity 让位。"""
        from core.pipeline.s06_voxel_building import run

        h = w = 7
        material_matrix = np.stack(
            [np.full((h, w), fill_value=layer_id, dtype=int) for layer_id in range(1, 6)],
            axis=-1,
        )
        ctx = {
            **self._make_valid_ctx(),
            "material_matrix": material_matrix,
            "mask_solid": np.ones((h, w), dtype=bool),
            "matched_rgb": np.full((h, w, 3), [128, 64, 32], dtype=np.uint8),
            "backing_color_id": 7,
            "spacer_thick": 3.4,
            "enable_fridge_magnet": True,
            "fridge_magnets": [
                self._make_magnet(shape="round", diameter_mm=0.28, thickness_mm=3.0),
            ],
        }

        result = run(ctx)
        center_row = center_col = 3

        assert result["spacer_thick"] == pytest.approx(3.44)
        assert result["total_layers"] == 48
        np.testing.assert_array_equal(result["full_matrix"][:5, center_row, center_col], np.array([1, 2, 3, 4, 5]))
        assert np.all(result["full_matrix"][5:43, center_row, center_col] == -1)
        assert np.all(result["full_matrix"][43:48, center_row, center_col] == 7)

    def test_round_fridge_magnet_cavity_only_carves_backing_and_preserves_shell(self):
        """圆形磁铁槽应只在底板内部开盲槽，不得影响光学层或外侧 0.4mm 壳层。"""
        from core.pipeline.s06_voxel_building import run

        h = w = 7
        material_matrix = np.stack(
            [np.full((h, w), fill_value=layer_id, dtype=int) for layer_id in range(1, 6)],
            axis=-1,
        )
        ctx = {
            **self._make_valid_ctx(),
            "material_matrix": material_matrix,
            "mask_solid": np.ones((h, w), dtype=bool),
            "matched_rgb": np.full((h, w, 3), [128, 64, 32], dtype=np.uint8),
            "backing_color_id": 7,
            "spacer_thick": 1.2,
            "enable_fridge_magnet": True,
            "fridge_magnets": [
                self._make_magnet(shape="round", diameter_mm=0.28, thickness_mm=0.32),
            ],
        }

        result = run(ctx)
        center_row = center_col = 3
        optical_slice = result["full_matrix"][:5, center_row, center_col]
        cavity_slice = result["full_matrix"][11:15, center_row, center_col]
        shell_slice = result["full_matrix"][15:20, center_row, center_col]

        np.testing.assert_array_equal(optical_slice, np.array([1, 2, 3, 4, 5]))
        np.testing.assert_array_equal(cavity_slice, np.full(4, -1, dtype=int))
        np.testing.assert_array_equal(shell_slice, np.full(5, 7, dtype=int))

    def test_rect_fridge_magnet_cavity_carves_backing_footprint_without_touching_optical_layers(self):
        """矩形磁铁槽应在底板中形成矩形盲槽，且光学层保持原样。"""
        from core.pipeline.s06_voxel_building import run

        h = w = 9
        material_matrix = np.stack(
            [np.full((h, w), fill_value=layer_id, dtype=int) for layer_id in range(1, 6)],
            axis=-1,
        )
        ctx = {
            **self._make_valid_ctx(),
            "material_matrix": material_matrix,
            "mask_solid": np.ones((h, w), dtype=bool),
            "matched_rgb": np.full((h, w, 3), [128, 64, 32], dtype=np.uint8),
            "backing_color_id": 6,
            "spacer_thick": 1.2,
            "enable_fridge_magnet": True,
            "fridge_magnets": [
                self._make_magnet(shape="rect", width_mm=0.3, height_mm=0.1, thickness_mm=0.24),
            ],
        }

        result = run(ctx)
        cavity_band = result["full_matrix"][12:15]

        assert np.all(cavity_band[:, 4, 3:6] == -1)
        assert np.all(cavity_band[:, 3, 3:6] == 6)
        np.testing.assert_array_equal(result["full_matrix"][:5, 4, 4], np.array([1, 2, 3, 4, 5]))

    def test_fridge_magnet_cavity_preserves_relief_optical_voxels_inside_backing_range(self):
        """浮雕等可变高度底板场景下，即使光学层与底板同材质编号，也不能被磁铁槽擦除。"""
        from core.pipeline.s06_voxel_building import _carve_fridge_magnet_cavities

        full_matrix = np.full((12, 7, 7), -1, dtype=int)
        full_matrix[0:8, 2:5, 2:5] = 7
        backing_z_min_map = np.full((7, 7), -1, dtype=int)
        backing_z_max_map = np.full((7, 7), -1, dtype=int)
        backing_z_min_map[2:5, 2:5] = 0
        backing_z_max_map[2:5, 2:5] = 7
        backing_z_max_map[3, 3] = 4

        carved = _carve_fridge_magnet_cavities(
            full_matrix.copy(),
            mask_solid=np.ones((7, 7), dtype=bool),
            pixel_scale=0.1,
            backing_metadata={
                "backing_color_id": 7,
                "backing_z_range": (0, 7),
                "backing_z_min_map": backing_z_min_map,
                "backing_z_max_map": backing_z_max_map,
            },
            fridge_magnets=[
                self._make_magnet(shape="round", diameter_mm=0.28, thickness_mm=0.24),
            ],
        )

        assert carved[5, 3, 3] == 7
        assert carved[6, 3, 3] == 7
        assert carved[7, 3, 3] == 7
        assert carved[5, 3, 2] == -1
        assert carved[6, 3, 2] == -1

    def test_fridge_magnet_cavity_expands_backing_when_quantized_spacer_is_one_layer_short(self):
        """当量化后的底板仅差 1 层时，应扩展有效底板厚度并继续开槽。"""
        from core.pipeline.s06_voxel_building import run

        h = w = 7
        material_matrix = np.stack(
            [np.full((h, w), fill_value=layer_id, dtype=int) for layer_id in range(1, 6)],
            axis=-1,
        )
        ctx = {
            **self._make_valid_ctx(),
            "material_matrix": material_matrix,
            "mask_solid": np.ones((h, w), dtype=bool),
            "matched_rgb": np.full((h, w, 3), [128, 64, 32], dtype=np.uint8),
            "backing_color_id": 7,
            "spacer_thick": 3.4,
            "enable_fridge_magnet": True,
            "fridge_magnets": [
                self._make_magnet(shape="round", diameter_mm=0.28, thickness_mm=3.0),
            ],
        }

        result = run(ctx)
        center_row = center_col = 3

        assert result["total_layers"] == 48
        np.testing.assert_array_equal(result["full_matrix"][:5, center_row, center_col], np.array([1, 2, 3, 4, 5]))
        np.testing.assert_array_equal(result["full_matrix"][5:43, center_row, center_col], np.full(38, -1, dtype=int))
        np.testing.assert_array_equal(result["full_matrix"][43:48, center_row, center_col], np.full(5, 7, dtype=int))


# ===========================================================================
# S12 — s12_result_assembly 单元测试
# ===========================================================================


class TestS12ResultAssembly:
    """S12 结果组装步骤的单元测试。"""

    def _make_valid_ctx(self) -> dict:
        """构造 S12 的最小有效 PipelineContext。"""
        return {
            "out_path": "/tmp/output.3mf",
            "glb_path": "/tmp/output.glb",
            "preview_img": None,
            "mode_info": {"mode": ModelingMode.HIGH_FIDELITY},
            "target_w": 100,
            "target_h": 100,
            "loop_info": None,
            "loop_added": False,
            "slot_names": ["White", "Red", "Yellow", "Blue"],
            "heightmap_stats": None,
            "color_recipe_path": None,
            "_hifi_timings": {},
        }

    @patch("core.pipeline.s12_result_assembly.Stats")
    def test_valid_input_produces_result_tuple(self, mock_stats):
        """有效输入应产生 result_tuple。"""
        from core.pipeline.s12_result_assembly import run

        ctx = self._make_valid_ctx()
        result = run(ctx)

        assert "result_tuple" in result
        assert isinstance(result["result_tuple"], tuple)
        assert len(result["result_tuple"]) == 5

    @patch("core.pipeline.s12_result_assembly.Stats")
    def test_result_tuple_format(self, mock_stats):
        """result_tuple 应为 (out_path, glb_path, preview_img, msg, recipe_path)。"""
        from core.pipeline.s12_result_assembly import run

        ctx = self._make_valid_ctx()
        result = run(ctx)

        out_path, glb_path, preview_img, msg, recipe_path = result["result_tuple"]
        assert out_path == "/tmp/output.3mf"
        assert glb_path == "/tmp/output.glb"
        assert preview_img is None
        assert isinstance(msg, str)
        assert "High-Fidelity" in msg
        assert recipe_path is None

    @patch("core.pipeline.s12_result_assembly.Stats")
    def test_msg_contains_resolution(self, mock_stats):
        """状态消息应包含分辨率信息。"""
        from core.pipeline.s12_result_assembly import run

        ctx = self._make_valid_ctx()
        result = run(ctx)

        _, _, _, msg, _ = result["result_tuple"]
        assert "100x100" in msg

    def test_missing_out_path_raises_key_error(self):
        """缺失 out_path 键应抛出 KeyError。"""
        from core.pipeline.s12_result_assembly import run

        ctx = self._make_valid_ctx()
        del ctx["out_path"]
        with pytest.raises(KeyError):
            run(ctx)

    def test_empty_dict_raises_key_error(self):
        """空 dict 应抛出 KeyError。"""
        from core.pipeline.s12_result_assembly import run

        with pytest.raises(KeyError):
            run({})


# ===========================================================================
# P01 — p01_preview_validation 单元测试
# ===========================================================================


class TestP01PreviewValidation:
    """P01 预览输入验证步骤的单元测试。"""

    def _make_valid_ctx(self) -> dict:
        """构造 P01 的最小有效 PipelineContext。"""
        return {
            "image_path": "/tmp/test.png",
            "lut_path": "/tmp/test.npy",
            "modeling_mode": ModelingMode.HIGH_FIDELITY,
            "quantize_colors": 64,
        }

    def test_valid_input_produces_expected_keys(self):
        """有效输入应产生所有声明的输出键。"""
        from core.pipeline.p01_preview_validation import run

        ctx = self._make_valid_ctx()
        result = run(ctx)

        assert "actual_lut_path" in result
        assert result["actual_lut_path"] == "/tmp/test.npy"
        assert "modeling_mode" in result
        assert result["modeling_mode"] == ModelingMode.HIGH_FIDELITY
        assert "quantize_colors" in result

    def test_none_image_path_sets_error(self):
        """image_path 为 None 时应设置 error 键。"""
        from core.pipeline.p01_preview_validation import run

        ctx = self._make_valid_ctx()
        ctx["image_path"] = None
        result = run(ctx)

        assert "error" in result

    def test_none_lut_path_sets_error(self):
        """lut_path 为 None 时应设置 error 键。"""
        from core.pipeline.p01_preview_validation import run

        ctx = self._make_valid_ctx()
        ctx["lut_path"] = None
        result = run(ctx)

        assert "error" in result

    def test_missing_image_path_raises_key_error(self):
        """缺失 image_path 键应抛出 KeyError。"""
        from core.pipeline.p01_preview_validation import run

        ctx = self._make_valid_ctx()
        del ctx["image_path"]
        with pytest.raises(KeyError):
            run(ctx)

    def test_quantize_colors_clamped_to_range(self):
        """quantize_colors 应被 clamp 到 [8, 256] 范围。"""
        from core.pipeline.p01_preview_validation import run

        # 低于下限
        ctx = self._make_valid_ctx()
        ctx["quantize_colors"] = 2
        result = run(ctx)
        assert result["quantize_colors"] >= 8

        # 高于上限
        ctx2 = self._make_valid_ctx()
        ctx2["quantize_colors"] = 1000
        result2 = run(ctx2)
        assert result2["quantize_colors"] <= 256

    def test_none_modeling_mode_defaults_to_high_fidelity(self):
        """modeling_mode 为 None 时应默认为 HIGH_FIDELITY。"""
        from core.pipeline.p01_preview_validation import run

        ctx = self._make_valid_ctx()
        ctx["modeling_mode"] = None
        result = run(ctx)

        assert result["modeling_mode"] == ModelingMode.HIGH_FIDELITY

    def test_file_like_object_lut_path(self):
        """file-like 对象的 lut_path 应正确解析。"""
        from core.pipeline.p01_preview_validation import run

        mock_file = MagicMock()
        mock_file.name = "/tmp/uploaded_lut.npy"

        ctx = self._make_valid_ctx()
        ctx["lut_path"] = mock_file
        result = run(ctx)

        assert result["actual_lut_path"] == "/tmp/uploaded_lut.npy"

    def test_empty_dict_raises_key_error(self):
        """空 dict 应抛出 KeyError。"""
        from core.pipeline.p01_preview_validation import run

        with pytest.raises(KeyError):
            run({})


# ===========================================================================
# P04 — p04_cache_building 单元测试
# ===========================================================================


class TestP04CacheBuilding:
    """P04 预览缓存构建步骤的单元测试。"""

    def _make_valid_ctx(self) -> dict:
        """构造 P04 的最小有效 PipelineContext。"""
        h, w = 4, 4
        return {
            "matched_rgb": np.full((h, w, 3), [128, 64, 32], dtype=np.uint8),
            "material_matrix": np.zeros((h, w, 5), dtype=int),
            "mask_solid": np.ones((h, w), dtype=bool),
            "target_w": w,
            "target_h": h,
            "target_width_mm": 40.0,
            "color_conf": ColorSystem.get("4-Color"),
            "color_mode": "4-Color",
            "quantize_colors": 64,
            "backing_color_id": 0,
            "is_dark": True,
            "lut_metadata": None,
            "debug_data": None,
            "quantized_image": None,
        }

    def test_valid_input_produces_cache(self):
        """有效输入应产生 preview_rgba 和 cache。"""
        from core.pipeline.p04_cache_building import run

        ctx = self._make_valid_ctx()
        result = run(ctx)

        assert "preview_rgba" in result
        assert "cache" in result
        assert isinstance(result["cache"], dict)
        assert isinstance(result["preview_rgba"], np.ndarray)

    def test_preview_rgba_shape(self):
        """preview_rgba 应为 (H, W, 4) RGBA 数组。"""
        from core.pipeline.p04_cache_building import run

        ctx = self._make_valid_ctx()
        result = run(ctx)

        assert result["preview_rgba"].shape == (4, 4, 4)
        assert result["preview_rgba"].dtype == np.uint8

    def test_cache_contains_required_keys(self):
        """cache 字典应包含必需的键。"""
        from core.pipeline.p04_cache_building import run

        ctx = self._make_valid_ctx()
        result = run(ctx)

        cache = result["cache"]
        expected_keys = [
            "target_w",
            "target_h",
            "target_width_mm",
            "mask_solid",
            "material_matrix",
            "matched_rgb",
            "preview_rgba",
            "color_conf",
            "color_mode",
            "quantize_colors",
            "quantized_image",
        ]
        for key in expected_keys:
            assert key in cache, f"cache 缺少键: {key}"

    def test_missing_matched_rgb_raises_key_error(self):
        """缺失 matched_rgb 键应抛出 KeyError。"""
        from core.pipeline.p04_cache_building import run

        ctx = self._make_valid_ctx()
        del ctx["matched_rgb"]
        with pytest.raises(KeyError):
            run(ctx)

    def test_missing_color_conf_raises_key_error(self):
        """缺失 color_conf 键应抛出 KeyError。"""
        from core.pipeline.p04_cache_building import run

        ctx = self._make_valid_ctx()
        del ctx["color_conf"]
        with pytest.raises(KeyError):
            run(ctx)

    def test_empty_dict_raises_key_error(self):
        """空 dict 应抛出 KeyError。"""
        from core.pipeline.p04_cache_building import run

        with pytest.raises(KeyError):
            run({})


# ===========================================================================
# P05 — p05_palette_extraction 单元测试
# ===========================================================================


class TestP05PaletteExtraction:
    """P05 调色板提取步骤的单元测试。"""

    def _make_valid_ctx(self) -> dict:
        """构造 P05 的最小有效 PipelineContext。"""
        h, w = 4, 4
        matched_rgb = np.full((h, w, 3), [128, 64, 32], dtype=np.uint8)
        mask_solid = np.ones((h, w), dtype=bool)

        cache = {
            "matched_rgb": matched_rgb,
            "mask_solid": mask_solid,
        }
        return {"cache": cache}

    def test_valid_input_adds_color_palette(self):
        """有效输入应在 cache 中添加 color_palette 键。"""
        from core.pipeline.p05_palette_extraction import run

        ctx = self._make_valid_ctx()
        result = run(ctx)

        assert "color_palette" in result["cache"]
        assert isinstance(result["cache"]["color_palette"], list)

    def test_single_color_palette(self):
        """单色图像应提取出 1 个调色板条目。"""
        from core.pipeline.p05_palette_extraction import run

        ctx = self._make_valid_ctx()
        result = run(ctx)

        palette = result["cache"]["color_palette"]
        assert len(palette) == 1
        assert palette[0]["color"] == (128, 64, 32)
        assert palette[0]["percentage"] == 100.0

    def test_missing_cache_raises_key_error(self):
        """缺失 cache 键应抛出 KeyError。"""
        from core.pipeline.p05_palette_extraction import run

        with pytest.raises(KeyError):
            run({})

    def test_cache_missing_matched_rgb_returns_empty_palette(self):
        """cache 中缺失 matched_rgb 时 extract_color_palette 返回空列表。"""
        from core.pipeline.p05_palette_extraction import run

        ctx = {"cache": {"mask_solid": np.ones((4, 4), dtype=bool)}}
        result = run(ctx)
        # extract_color_palette 使用 .get() 访问，缺失时返回空列表
        assert result["cache"]["color_palette"] == []

    def test_empty_dict_raises_key_error(self):
        """空 dict 应抛出 KeyError。"""
        from core.pipeline.p05_palette_extraction import run

        with pytest.raises(KeyError):
            run({})

    def test_multi_color_palette(self):
        """多色图像应提取出多个调色板条目。"""
        from core.pipeline.p05_palette_extraction import run

        h, w = 4, 4
        matched_rgb = np.zeros((h, w, 3), dtype=np.uint8)
        # 上半部分红色，下半部分蓝色
        matched_rgb[:2, :] = [255, 0, 0]
        matched_rgb[2:, :] = [0, 0, 255]
        mask_solid = np.ones((h, w), dtype=bool)

        ctx = {"cache": {"matched_rgb": matched_rgb, "mask_solid": mask_solid}}
        result = run(ctx)

        palette = result["cache"]["color_palette"]
        assert len(palette) == 2
        # 两种颜色各占 50%
        for entry in palette:
            assert entry["percentage"] == 50.0
