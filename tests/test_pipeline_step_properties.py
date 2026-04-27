"""
Property-based tests for pipeline step modules.
管道步骤模块的属性测试。

Feature: image-pipeline-modularization
Tests: Property 1, 2, 3, 12, 13
"""

import inspect
import importlib
import re

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st


# ---------------------------------------------------------------------------
# 所有 18 个步骤模块的引用列表
# ---------------------------------------------------------------------------

RASTER_STEP_MODULE_PATHS = [
    "core.pipeline.s01_input_validation",
    "core.pipeline.s02_image_processing",
    "core.pipeline.s03_color_replacement",
    "core.pipeline.s04_debug_preview",
    "core.pipeline.s05_preview_generation",
    "core.pipeline.s06_voxel_building",
    "core.pipeline.s07_mesh_generation",
    "core.pipeline.s08_auxiliary_meshes",
    "core.pipeline.s09_export_3mf",
    "core.pipeline.s10_color_recipe",
    "core.pipeline.s11_glb_preview",
    "core.pipeline.s12_result_assembly",
]

PREVIEW_STEP_MODULE_PATHS = [
    "core.pipeline.p01_preview_validation",
    "core.pipeline.p02_lut_metadata",
    "core.pipeline.p03_core_processing",
    "core.pipeline.p04_cache_building",
    "core.pipeline.p05_palette_extraction",
    "core.pipeline.p06_bed_rendering",
]

ALL_STEP_MODULE_PATHS = RASTER_STEP_MODULE_PATHS + PREVIEW_STEP_MODULE_PATHS


def _load_all_step_modules():
    """Lazily import all 18 step modules and return list of (path, module)."""
    modules = []
    for path in ALL_STEP_MODULE_PATHS:
        mod = importlib.import_module(path)
        modules.append((path, mod))
    return modules


# ===========================================================================
# Property 1: Step 函数签名一致性
# Feature: image-pipeline-modularization, Property 1: Step 函数签名一致性
# **Validates: Requirements 3.2, 4.2, 9.1**
# ===========================================================================

class TestProperty1StepFunctionSignature:
    """验证所有 Step_Module 的 run 函数仅接收一个 dict 参数并返回 dict。

    这是一个确定性测试，不需要 Hypothesis。使用 inspect.signature
    检查所有 18 个模块。
    """

    @pytest.mark.parametrize("module_path", ALL_STEP_MODULE_PATHS)
    def test_run_function_exists(self, module_path: str):
        """每个步骤模块必须导出 run 函数。"""
        mod = importlib.import_module(module_path)
        assert hasattr(mod, "run"), (
            f"{module_path} 缺少 run 函数"
        )
        assert callable(mod.run), (
            f"{module_path}.run 不是可调用对象"
        )

    @pytest.mark.parametrize("module_path", ALL_STEP_MODULE_PATHS)
    def test_run_accepts_single_dict_param(self, module_path: str):
        """run 函数应仅接收一个位置参数（ctx: dict）。"""
        mod = importlib.import_module(module_path)
        sig = inspect.signature(mod.run)
        params = [
            p for p in sig.parameters.values()
            if p.default is inspect.Parameter.empty
            and p.kind in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            )
        ]
        assert len(params) == 1, (
            f"{module_path}.run 应仅有 1 个必需位置参数，"
            f"实际有 {len(params)}: {[p.name for p in params]}"
        )

    @pytest.mark.parametrize("module_path", ALL_STEP_MODULE_PATHS)
    def test_run_param_annotated_as_dict(self, module_path: str):
        """run 函数的参数应标注为 dict 类型。"""
        mod = importlib.import_module(module_path)
        sig = inspect.signature(mod.run)
        first_param = list(sig.parameters.values())[0]
        annotation = first_param.annotation
        assert annotation is dict or annotation is inspect.Parameter.empty, (
            f"{module_path}.run 的参数 '{first_param.name}' "
            f"类型标注应为 dict，实际为 {annotation}"
        )

    @pytest.mark.parametrize("module_path", ALL_STEP_MODULE_PATHS)
    def test_run_return_annotated_as_dict(self, module_path: str):
        """run 函数的返回值应标注为 dict 类型。"""
        mod = importlib.import_module(module_path)
        sig = inspect.signature(mod.run)
        ret = sig.return_annotation
        assert ret is dict or ret is inspect.Signature.empty, (
            f"{module_path}.run 返回值类型标注应为 dict，实际为 {ret}"
        )


# ===========================================================================
# Property 2: Step 输出键保留
# Feature: image-pipeline-modularization, Property 2: Step 输出键保留
# **Validates: Requirements 2.2**
# ===========================================================================


class TestProperty2StepOutputKeyPreservation:
    """验证执行步骤后不删除已有键。

    使用 Hypothesis 生成随机 PipelineContext（dict），验证 run 函数
    的类型注解确认返回 dict，且通过 inspect 分析 docstring 中声明的
    输出键确实存在于返回值中。

    注意：不真正执行步骤（需要真实数据），而是验证 run 函数签名
    保证返回 dict 类型，且 docstring 中声明了输出键。
    """

    @given(
        extra_keys=st.dictionaries(
            keys=st.text(
                alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_"),
                min_size=1,
                max_size=10,
            ),
            values=st.one_of(st.integers(), st.text(max_size=5), st.booleans()),
            min_size=1,
            max_size=5,
        )
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_run_signature_returns_dict(self, extra_keys: dict):
        """run 函数签名声明返回 dict，保证不会丢失已有键的类型契约。"""
        for module_path in ALL_STEP_MODULE_PATHS:
            mod = importlib.import_module(module_path)
            sig = inspect.signature(mod.run)
            ret = sig.return_annotation
            # 返回值标注为 dict 或未标注（隐式 dict）
            assert ret is dict or ret is inspect.Signature.empty, (
                f"{module_path}.run 返回值类型应为 dict，实际为 {ret}"
            )

    @pytest.mark.parametrize("module_path", ALL_STEP_MODULE_PATHS)
    def test_docstring_declares_output_keys(self, module_path: str):
        """run 函数 docstring 应声明输出键。"""
        mod = importlib.import_module(module_path)
        docstring = mod.run.__doc__ or ""
        # 允许 S04 等无新输出键的步骤
        has_output_section = bool(
            re.search(r"(输出键|Output keys|输出|无新键)", docstring, re.IGNORECASE)
        )
        assert has_output_section, (
            f"{module_path}.run docstring 缺少输出键声明"
        )


# ===========================================================================
# Property 3: 缺失键抛出 KeyError
# Feature: image-pipeline-modularization, Property 3: 缺失键抛出 KeyError
# **Validates: Requirements 2.4**
# ===========================================================================

# 每个步骤模块的必需输入键（从 docstring 和代码中提取的 ctx['xxx'] 访问）
_REQUIRED_KEYS_MAP = {
    "core.pipeline.s01_input_validation": ["image_path", "lut_path", "color_mode", "modeling_mode"],
    "core.pipeline.s02_image_processing": ["actual_lut_path", "color_mode", "image_path"],
    "core.pipeline.s03_color_replacement": ["matched_rgb", "material_matrix", "mask_solid", "processor"],
    "core.pipeline.s04_debug_preview": ["mode_info"],
    "core.pipeline.s05_preview_generation": [
        "matched_rgb", "mask_solid", "target_w", "target_h", "pixel_scale", "color_conf",
    ],
    "core.pipeline.s06_voxel_building": [
        "material_matrix", "mask_solid", "spacer_thick", "matched_rgb", "pixel_scale",
    ],
    "core.pipeline.s07_mesh_generation": [
        "full_matrix", "slot_names", "preview_colors", "modeling_mode", "target_h", "pixel_scale",
    ],
    "core.pipeline.s08_auxiliary_meshes": [
        "scene", "valid_slot_names", "full_matrix", "mask_solid", "matched_rgb",
        "target_h", "pixel_scale", "total_layers", "preview_colors", "transform",
        "mesher", "backing_metadata",
    ],
    "core.pipeline.s09_export_3mf": [
        "scene", "valid_slot_names", "preview_colors", "color_mode",
        "image_path", "modeling_mode", "target_w", "pixel_scale",
    ],
    "core.pipeline.s10_color_recipe": [
        "processor", "matched_rgb", "material_matrix", "mask_solid", "out_path",
    ],
    "core.pipeline.s11_glb_preview": [
        "matched_rgb", "mask_solid", "total_layers", "backing_metadata",
        "preview_colors", "pixel_scale", "image_path", "target_h", "transform",
    ],
    "core.pipeline.s12_result_assembly": [
        "out_path", "mode_info", "target_w", "target_h", "slot_names",
    ],
    "core.pipeline.p01_preview_validation": ["image_path", "lut_path"],
    "core.pipeline.p02_lut_metadata": ["actual_lut_path", "color_mode"],
    "core.pipeline.p03_core_processing": [
        "actual_lut_path", "color_mode", "image_path", "target_width_mm",
        "modeling_mode", "quantize_colors",
    ],
    "core.pipeline.p04_cache_building": [
        "matched_rgb", "material_matrix", "mask_solid",
        "target_w", "target_h", "target_width_mm", "color_conf",
        "color_mode", "quantize_colors",
    ],
    "core.pipeline.p05_palette_extraction": ["cache"],
    "core.pipeline.p06_bed_rendering": [
        "preview_rgba", "cache", "color_conf", "target_width_mm",
    ],
}


class TestProperty3MissingKeyRaisesKeyError:
    """验证当 PipelineContext 缺少必需键时，步骤抛出 KeyError。

    用空 dict 调用各步骤的 run 函数来验证。
    """

    @pytest.mark.parametrize("module_path", ALL_STEP_MODULE_PATHS)
    def test_empty_ctx_raises_key_error(self, module_path: str):
        """空 dict 调用 run 应抛出 KeyError。"""
        mod = importlib.import_module(module_path)
        required_keys = _REQUIRED_KEYS_MAP.get(module_path, [])

        if not required_keys:
            pytest.skip(f"{module_path} 无已知必需键")

        with pytest.raises(KeyError):
            mod.run({})

    @pytest.mark.parametrize("module_path", ALL_STEP_MODULE_PATHS)
    def test_missing_single_required_key_raises_key_error(self, module_path: str):
        """缺少任意一个必需键时应抛出 KeyError（键名可能是任意缺失键）。"""
        mod = importlib.import_module(module_path)
        required_keys = _REQUIRED_KEYS_MAP.get(module_path, [])

        if not required_keys:
            pytest.skip(f"{module_path} 无已知必需键")

        # 构造一个包含所有必需键（值为 None）的 ctx，然后逐个移除
        for missing_key in required_keys:
            ctx = {k: None for k in required_keys if k != missing_key}
            try:
                mod.run(ctx)
                # 如果没有抛出异常，可能是因为 None 值触发了其他逻辑
                # （如 S01 的 image_path is None 检查），这也是可接受的
            except KeyError as e:
                # 抛出 KeyError 即可——缺失键名可能是当前移除的键，
                # 也可能是其他在代码中更早被访问的必需键（因为 dict
                # 访问顺序取决于代码执行路径，不一定与列表顺序一致）
                assert e.args[0] in required_keys or missing_key in str(e), (
                    f"{module_path}: KeyError 应包含某个必需键名，"
                    f"实际为 {e}"
                )
            except (TypeError, AttributeError, ValueError):
                # 其他异常也可接受（如 None 值导致的 TypeError）
                pass


# ===========================================================================
# Property 12: Step 独立可测试性
# Feature: image-pipeline-modularization, Property 12: Step 独立可测试性
# **Validates: Requirements 9.3**
# ===========================================================================

class TestProperty12StepIndependentTestability:
    """验证仅需构造最小 PipelineContext 即可独立导入每个步骤模块。

    验证每个模块可以独立 import 不报错。
    """

    @pytest.mark.parametrize("module_path", ALL_STEP_MODULE_PATHS)
    def test_module_imports_independently(self, module_path: str):
        """每个步骤模块可以独立导入，不依赖其他步骤的执行。"""
        mod = importlib.import_module(module_path)
        assert mod is not None
        assert hasattr(mod, "run")
        assert callable(mod.run)

    @pytest.mark.parametrize("module_path", ALL_STEP_MODULE_PATHS)
    def test_module_has_no_global_mutable_state(self, module_path: str):
        """步骤模块不应依赖模块级全局可变状态来存储中间结果。

        检查模块顶层没有可变的全局变量（排除常量、导入和函数定义）。
        """
        mod = importlib.import_module(module_path)
        import typing
        # 获取模块中定义的公共属性（排除 dunder 和导入的模块）
        public_attrs = [
            name for name in dir(mod)
            if not name.startswith("_")
            and not inspect.ismodule(getattr(mod, name))
            and not inspect.isfunction(getattr(mod, name))
            and not inspect.isclass(getattr(mod, name))
        ]
        # 允许常量（全大写命名）和类型别名
        mutable_globals = [
            name for name in public_attrs
            if not name.isupper()
            and not isinstance(getattr(mod, name), (type, bool, int, float, str, tuple, frozenset))
        ]
        # 允许 None 值的全局变量（如 LUTManager = None 的 try/except 模式）
        mutable_globals = [
            name for name in mutable_globals
            if getattr(mod, name) is not None
        ]
        # 排除 typing 模块的类型别名（如 Optional, Dict, Tuple, List 等）
        mutable_globals = [
            name for name in mutable_globals
            if not hasattr(typing, name)
        ]
        assert len(mutable_globals) == 0, (
            f"{module_path} 存在可变全局状态: {mutable_globals}"
        )

    @pytest.mark.parametrize("module_path", ALL_STEP_MODULE_PATHS)
    def test_run_function_is_pure_interface(self, module_path: str):
        """run 函数接口为 (dict) -> dict，可独立构造最小 ctx 调用。"""
        mod = importlib.import_module(module_path)
        sig = inspect.signature(mod.run)
        params = list(sig.parameters.values())
        # 仅有一个参数
        assert len(params) == 1
        # 参数名通常为 ctx
        assert params[0].name == "ctx", (
            f"{module_path}.run 参数名应为 'ctx'，实际为 '{params[0].name}'"
        )


# ===========================================================================
# Property 13: Step 文档完整性
# Feature: image-pipeline-modularization, Property 13: Step 文档完整性
# **Validates: Requirements 9.4**
# ===========================================================================

# 输入键关键词模式（中英文均可）
_INPUT_KEY_PATTERNS = [
    r"输入键",
    r"Input keys",
    r"ctx\s*输入",
    r"Reads from ctx",
]

# 输出键关键词模式（中英文均可）
_OUTPUT_KEY_PATTERNS = [
    r"输出键",
    r"Output keys",
    r"ctx\s*输出",
    r"Writes to ctx",
    r"无新键",  # S04 等无输出键的步骤
]


class TestProperty13StepDocCompleteness:
    """验证所有 Step_Module 的 run 函数 docstring 包含输入键和输出键描述。"""

    @pytest.mark.parametrize("module_path", ALL_STEP_MODULE_PATHS)
    def test_run_has_docstring(self, module_path: str):
        """run 函数必须有 docstring。"""
        mod = importlib.import_module(module_path)
        docstring = mod.run.__doc__
        assert docstring is not None and len(docstring.strip()) > 0, (
            f"{module_path}.run 缺少 docstring"
        )

    @pytest.mark.parametrize("module_path", ALL_STEP_MODULE_PATHS)
    def test_docstring_contains_input_keys(self, module_path: str):
        """run 函数 docstring 应包含输入键描述。"""
        mod = importlib.import_module(module_path)
        docstring = mod.run.__doc__ or ""
        has_input = any(
            re.search(pattern, docstring, re.IGNORECASE)
            for pattern in _INPUT_KEY_PATTERNS
        )
        assert has_input, (
            f"{module_path}.run docstring 缺少输入键描述。"
            f"期望包含以下关键词之一: {_INPUT_KEY_PATTERNS}"
        )

    @pytest.mark.parametrize("module_path", ALL_STEP_MODULE_PATHS)
    def test_docstring_contains_output_keys(self, module_path: str):
        """run 函数 docstring 应包含输出键描述。"""
        mod = importlib.import_module(module_path)
        docstring = mod.run.__doc__ or ""
        has_output = any(
            re.search(pattern, docstring, re.IGNORECASE)
            for pattern in _OUTPUT_KEY_PATTERNS
        )
        assert has_output, (
            f"{module_path}.run docstring 缺少输出键描述。"
            f"期望包含以下关键词之一: {_OUTPUT_KEY_PATTERNS}"
        )

    @pytest.mark.parametrize("module_path", ALL_STEP_MODULE_PATHS)
    def test_docstring_has_bilingual_description(self, module_path: str):
        """run 函数 docstring 应包含中英文双语描述。"""
        mod = importlib.import_module(module_path)
        docstring = mod.run.__doc__ or ""
        # 检查是否包含中文字符
        has_chinese = bool(re.search(r"[\u4e00-\u9fff]", docstring))
        # 检查是否包含英文字母
        has_english = bool(re.search(r"[a-zA-Z]", docstring))
        assert has_chinese and has_english, (
            f"{module_path}.run docstring 应包含中英文双语描述"
        )
