"""
Property-based tests for backward compatibility.
向后兼容性属性测试。

Feature: image-pipeline-modularization
Tests: Public imports, signatures and converter entry results
"""

import inspect

import pytest

# ===========================================================================
# Property 4: 公共导入兼容性
# Feature: image-pipeline-modularization, Property 4: 公共导入兼容性
# **Validates: Requirements 7.3, 8.3, 12.5**
# ===========================================================================

# 所有需要通过 `from core.converter import` 导入的函数名
_PUBLIC_IMPORT_NAMES = [
    # pipeline_utils
    "extract_color_palette",
    "_rgb_to_hex",
    "_hex_to_rgb_tuple",
    "calculate_luminance",
    "extract_lut_available_colors",
    "get_lut_color_choices",
    "detect_lut_color_mode",
    "detect_image_type",
    "_ensure_quantized_image_in_cache",
    "generate_auto_height_map",
    "_recommend_lut_colors_by_rgb",
    "_build_selection_meta",
    "_resolve_highlight_mask",
    "_build_dual_recommendations",
    "_resolve_click_selection_hexes",
    # s03_color_replacement
    "_normalize_color_replacements_input",
    "_apply_region_replacement",
    "_apply_regions_to_raster_outputs",
    "_compute_connected_region_mask_4n",
    # s11_glb_preview
    "generate_segmented_glb",
    "generate_realtime_glb",
    "generate_empty_bed_glb",
    "_create_preview_mesh",
    "_merge_low_frequency_colors",
    # s06_voxel_building
    "_build_voxel_matrix",
    "_build_voxel_matrix_faceup",
    "_build_relief_voxel_matrix",
    "_build_cloisonne_voxel_matrix",
    "_normalize_color_height_map",
    # s05_preview_generation
    "_calculate_loop_position",
    "_calculate_loop_info",
    "_draw_loop_on_preview",
    # s08_auxiliary_meshes
    "_generate_outline_mesh",
    "_parse_outline_slot",
    # s04_debug_preview
    "_save_debug_preview",
    # p06_bed_rendering
    "render_preview",
    "_draw_loop_on_canvas",
    "_create_bed_mesh",
    # coordinator
    "run_raster_pipeline",
    "run_preview_pipeline",
]


class TestProperty4PublicImportCompatibility:
    """验证所有公共函数可通过 `from core.converter import` 导入且为可调用对象。

    这是确定性测试，不需要 Hypothesis。逐一检查每个函数名是否可从
    core.converter 模块导入，且导入后为可调用对象。
    """

    @pytest.mark.parametrize("func_name", _PUBLIC_IMPORT_NAMES)
    def test_function_importable_from_converter(self, func_name: str):
        """函数可通过 from core.converter import 导入。"""
        import core.converter as converter_mod

        assert hasattr(converter_mod, func_name), f"core.converter 缺少导出: {func_name}"

    @pytest.mark.parametrize("func_name", _PUBLIC_IMPORT_NAMES)
    def test_function_is_callable(self, func_name: str):
        """导入的函数为可调用对象。"""
        import core.converter as converter_mod

        obj = getattr(converter_mod, func_name)
        assert callable(obj), f"core.converter.{func_name} 不是可调用对象，类型为 {type(obj)}"


# ===========================================================================
# Property 5: convert_image_to_3d 返回值格式
# Feature: image-pipeline-modularization, Property 5: convert_image_to_3d 返回值格式
# **Validates: Requirements 8.1**
# ===========================================================================


class TestProperty5ConvertImageTo3dSignature:
    """验证 convert_image_to_3d 函数存在、可调用，且签名包含所有必需参数。

    不需要真正调用（需要真实文件），只验证签名。
    """

    def test_function_exists_and_callable(self):
        """convert_image_to_3d 函数存在且可调用。"""
        from core.converter import convert_image_to_3d

        assert callable(convert_image_to_3d)

    def test_signature_contains_required_params(self):
        """convert_image_to_3d 签名包含所有必需参数。"""
        from core.converter import convert_image_to_3d

        sig = inspect.signature(convert_image_to_3d)
        param_names = list(sig.parameters.keys())

        required_params = [
            "image_path",
            "lut_path",
            "target_width_mm",
            "spacer_thick",
            "structure_mode",
            "color_mode",
            "add_loop",
            "loop_width",
            "loop_length",
            "loop_hole",
            "loop_pos",
        ]
        for param in required_params:
            assert param in param_names, f"convert_image_to_3d 签名缺少必需参数: {param}"

    def test_signature_contains_optional_params(self):
        """convert_image_to_3d 签名包含关键可选参数。"""
        from core.converter import convert_image_to_3d

        sig = inspect.signature(convert_image_to_3d)
        param_names = list(sig.parameters.keys())

        optional_params = [
            "modeling_mode",
            "quantize_colors",
            "blur_kernel",
            "smooth_sigma",
            "color_replacements",
            "replacement_regions",
            "backing_color_id",
            "separate_backing",
            "enable_relief",
            "color_height_map",
            "height_mode",
            "heightmap_path",
            "heightmap_max_height",
            "enable_cleanup",
            "enable_outline",
            "outline_width",
            "enable_cloisonne",
            "wire_width_mm",
            "wire_height_mm",
            "free_color_set",
            "enable_coating",
            "coating_height_mm",
            "hue_weight",
            "chroma_gate",
            "matched_rgb_path",
            "loop_angle",
            "loop_offset_x",
            "loop_offset_y",
            "loop_position_preset",
            "progress",
            "enable_fridge_magnet",
            "fridge_magnets",
        ]
        for param in optional_params:
            assert param in param_names, f"convert_image_to_3d 签名缺少可选参数: {param}"


class TestProperty5GenerateFinalModelSignature:
    """验证 generate_final_model 保持兼容签名并暴露新的冰箱贴参数。"""

    def test_function_exists_and_callable(self):
        """generate_final_model 函数存在且可调用。"""
        from core.converter import generate_final_model

        assert callable(generate_final_model)

    def test_signature_contains_fridge_magnet_params(self):
        """generate_final_model 签名包含新的冰箱贴可选参数。"""
        from core.converter import generate_final_model

        sig = inspect.signature(generate_final_model)
        param_names = list(sig.parameters.keys())

        for param in ["enable_fridge_magnet", "fridge_magnets"]:
            assert param in param_names, f"generate_final_model 签名缺少可选参数: {param}"


# ===========================================================================
# Property 6: generate_preview_cached 返回值格式
# Feature: image-pipeline-modularization, Property 6: generate_preview_cached 返回值格式
# **Validates: Requirements 8.2**
# ===========================================================================


class TestProperty6GeneratePreviewCachedSignature:
    """验证 generate_preview_cached 函数存在、可调用，且签名包含所有必需参数。

    不需要真正调用，只验证签名。
    """

    def test_function_exists_and_callable(self):
        """generate_preview_cached 函数存在且可调用。"""
        from core.converter import generate_preview_cached

        assert callable(generate_preview_cached)

    def test_signature_contains_required_params(self):
        """generate_preview_cached 签名包含所有必需参数。"""
        from core.converter import generate_preview_cached

        sig = inspect.signature(generate_preview_cached)
        param_names = list(sig.parameters.keys())

        required_params = [
            "image_path",
            "lut_path",
            "target_width_mm",
            "color_mode",
        ]
        for param in required_params:
            assert param in param_names, f"generate_preview_cached 签名缺少必需参数: {param}"

    def test_signature_contains_optional_params(self):
        """generate_preview_cached 签名包含关键可选参数。"""
        from core.converter import generate_preview_cached

        sig = inspect.signature(generate_preview_cached)
        param_names = list(sig.parameters.keys())

        optional_params = [
            "modeling_mode",
            "quantize_colors",
            "backing_color_id",
            "enable_cleanup",
            "is_dark",
            "hue_weight",
            "chroma_gate",
        ]
        for param in optional_params:
            assert param in param_names, f"generate_preview_cached 签名缺少可选参数: {param}"


_CONVERTER_THIN_WRAPPER_FUNCTIONS = [
    "convert_image_to_3d",
    "generate_preview_cached",
]


class TestConverterEntryResults:
    @pytest.mark.parametrize("func_name", _CONVERTER_THIN_WRAPPER_FUNCTIONS)
    @pytest.mark.parametrize("failed", [False, True])
    def test_delegates_once_and_preserves_success_or_failure_tuple(
        self, monkeypatch: pytest.MonkeyPatch, func_name: str, failed: bool,
    ) -> None:
        from unittest.mock import Mock
        from core import converter

        entry = getattr(converter, func_name)
        image, cache = object(), {"material_matrix": object()}
        generated = ("model.3mf", "model.glb", image, "OK", "recipe.json")
        error = "[ERROR] Requested voxel geometry failed"
        ctx = {
            "result_tuple": generated, "display_image": image,
            "cache": cache, "status_msg": "OK",
        }
        if failed:
            ctx["error"] = error
        runner = Mock(return_value=ctx)
        pipeline = (
            "build_image_model_context"
            if func_name == "convert_image_to_3d" else "run_preview_pipeline"
        )
        monkeypatch.setattr(converter, pipeline, runner)
        required = {
            name: object() for name, param in inspect.signature(entry).parameters.items()
            if param.default is inspect.Parameter.empty
        }

        result = entry(**required)

        runner.assert_called_once()
        if func_name == "convert_image_to_3d":
            if failed:
                assert result == (None, None, None, error, None)
            else:
                assert result is generated
        elif failed:
            assert result == (None, None, error)
        else:
            assert result[0] is image
            assert result[1] is cache
            assert result[2] == "OK"
