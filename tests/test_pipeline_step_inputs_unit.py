"""Pipeline steps reject missing inputs and skip optional recipes.
流水线步骤拒绝缺失输入，并允许跳过可选配方。
"""

import importlib

import pytest


@pytest.mark.parametrize("module_path", [
    "core.pipeline.s01_input_validation",
    "core.pipeline.s02_image_processing",
    "core.pipeline.s03_color_replacement",
    "core.pipeline.s04_debug_preview",
    "core.pipeline.s05_preview_generation",
    "core.pipeline.s06_voxel_building",
    "core.pipeline.s07_mesh_generation",
    "core.pipeline.s08_auxiliary_meshes",
    "core.pipeline.s09_export_3mf",
    "core.pipeline.s11_glb_preview",
    "core.pipeline.s12_result_assembly",
    "core.pipeline.p01_preview_validation",
    "core.pipeline.p02_lut_metadata",
    "core.pipeline.p03_core_processing",
    "core.pipeline.p04_cache_building",
    "core.pipeline.p05_palette_extraction",
    "core.pipeline.p06_bed_rendering",
])
def test_step_rejects_empty_context(module_path: str) -> None:
    """A required-input step cannot report success for an empty context.
    需要输入的步骤不能把空上下文作为成功结果返回。
    """
    step = importlib.import_module(module_path)
    with pytest.raises(KeyError):
        step.run({})


def test_recipe_step_skips_context_without_lut_processor() -> None:
    """Material archives without a LUT processor do not produce a color recipe.
    没有 LUT 处理器的耗材归档不生成配方报告。
    """
    from core.pipeline import s10_color_recipe

    context = {}
    result = s10_color_recipe.run(context)

    assert result is context
    assert result["color_recipe_path"] is None
    assert not result.get("error")
