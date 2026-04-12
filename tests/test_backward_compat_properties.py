"""
Property-based tests for backward compatibility.
向后兼容性属性测试。

Feature: image-pipeline-modularization
Tests: Property 4, 5, 6, 11
"""

import ast
import inspect
import os

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
    "generate_lut_color_dropdown_html",
    "detect_lut_color_mode",
    "detect_image_type",
    "_ensure_quantized_image_in_cache",
    "generate_auto_height_map",
    "_recommend_lut_colors_by_rgb",
    "_build_selection_meta",
    "_resolve_highlight_mask",
    "_build_dual_recommendations",
    "_resolve_click_selection_hexes",
    "generate_lut_grid_html",
    "generate_lut_card_grid_html",
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
    "_build_color_contour_mesh",
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
            "auto_bg",
            "bg_tol",
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
            "auto_bg",
            "bg_tol",
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


# ===========================================================================
# Property 11: 函数体行数限制
# Feature: image-pipeline-modularization, Property 11: 函数体行数限制
# **Validates: Requirements 7.5, 11.2**
# ===========================================================================


def _count_function_body_lines(node: ast.FunctionDef) -> int:
    """使用 AST 计算函数体的行数（不含 docstring）。

    Args:
        node: AST FunctionDef 节点

    Returns:
        函数体行数（排除 docstring 后的语句行数）
    """
    body = node.body
    # 跳过 docstring（第一个语句如果是字符串常量）
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]

    if not body:
        return 0

    first_line = body[0].lineno
    last_line = body[-1].end_lineno or body[-1].lineno
    return last_line - first_line + 1


# converter.py 中的 UI 辅助函数（不受 20 行限制）
_LEGACY_UI_HELPER_FUNCTIONS = {
    "update_preview_with_loop",
    "on_remove_loop",
    "generate_final_model",
    "on_preview_click_select_color",
    "generate_highlight_preview",
    "clear_highlight_preview",
    "update_preview_with_replacements",
    "update_preview_with_backing_color",
}

# converter.py 中需要检查 ≤20 行的函数
_CONVERTER_THIN_WRAPPER_FUNCTIONS = [
    "convert_image_to_3d",
    "generate_preview_cached",
]

# image_processing.py 中 LuminaImageProcessor 需要检查 ≤30 行的方法
_IMAGE_PROCESSOR_METHODS = [
    "__init__",
    "process_image",
    "_process_high_fidelity_mode",
    "_process_pixel_mode",
]


class TestProperty11FunctionBodyLineLimit:
    """使用 AST 解析验证函数体行数限制。

    - converter.py 中 convert_image_to_3d 和 generate_preview_cached 函数体不超过 20 行
    - image_processing.py 中 LuminaImageProcessor 的指定方法体不超过 30 行
    """

    @pytest.fixture(scope="class")
    def converter_ast(self):
        """解析 converter.py 的 AST。"""
        converter_path = os.path.join("core", "converter.py")
        with open(converter_path, "r", encoding="utf-8") as f:
            source = f.read()
        return ast.parse(source, filename=converter_path)

    @pytest.fixture(scope="class")
    def image_processing_ast(self):
        """解析 image_processing.py 的 AST。"""
        ip_path = os.path.join("core", "image_processing.py")
        with open(ip_path, "r", encoding="utf-8") as f:
            source = f.read()
        return ast.parse(source, filename=ip_path)

    @pytest.mark.parametrize("func_name", _CONVERTER_THIN_WRAPPER_FUNCTIONS)
    def test_converter_thin_wrapper_within_20_lines(self, converter_ast, func_name: str):
        """converter.py 中薄包装函数体不超过 20 行。"""
        found = False
        for node in ast.walk(converter_ast):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name == func_name:
                    found = True
                    body_lines = _count_function_body_lines(node)
                    assert body_lines <= 20, f"converter.py::{func_name} 函数体为 {body_lines} 行，" f"超过 20 行限制"
                    break
        assert found, f"converter.py 中未找到函数 {func_name}"

    @pytest.mark.parametrize("method_name", _IMAGE_PROCESSOR_METHODS)
    def test_image_processor_method_within_30_lines(self, image_processing_ast, method_name: str):
        """image_processing.py 中 LuminaImageProcessor 方法体不超过 30 行。"""
        found = False
        for node in ast.walk(image_processing_ast):
            if isinstance(node, ast.ClassDef) and node.name == "LuminaImageProcessor":
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if item.name == method_name:
                            found = True
                            body_lines = _count_function_body_lines(item)
                            assert body_lines <= 30, (
                                f"LuminaImageProcessor.{method_name} 方法体为 " f"{body_lines} 行，超过 30 行限制"
                            )
                            break
                break
        assert found, f"image_processing.py 中 LuminaImageProcessor 未找到方法 {method_name}"
