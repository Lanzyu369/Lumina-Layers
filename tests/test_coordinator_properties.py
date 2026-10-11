"""
Property-based tests for pipeline coordinator.
管道协调器的属性测试。

Feature: image-pipeline-modularization
Tests: Property 7, 8
"""

from unittest.mock import patch, MagicMock

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st


# ---------------------------------------------------------------------------
# 需要 mock 的步骤模块路径
# ---------------------------------------------------------------------------

_RASTER_STEP_MODULES = [
    "core.pipeline.coordinator.s01_input_validation",
    "core.pipeline.coordinator.s02_image_processing",
    "core.pipeline.coordinator.s03_color_replacement",
    "core.pipeline.coordinator.s04_debug_preview",
    "core.pipeline.coordinator.s05_preview_generation",
    "core.pipeline.coordinator.s06_voxel_building",
    "core.pipeline.coordinator.s07_mesh_generation",
    "core.pipeline.coordinator.s08_auxiliary_meshes",
    "core.pipeline.coordinator.s09_export_3mf",
    "core.pipeline.coordinator.s10_color_recipe",
    "core.pipeline.coordinator.s11_glb_preview",
    "core.pipeline.coordinator.s12_result_assembly",
]

_PREVIEW_STEP_MODULES = [
    "core.pipeline.coordinator.p01_preview_validation",
    "core.pipeline.coordinator.p02_lut_metadata",
    "core.pipeline.coordinator.p03_core_processing",
    "core.pipeline.coordinator.p04_cache_building",
    "core.pipeline.coordinator.p05_palette_extraction",
    "core.pipeline.coordinator.p06_bed_rendering",
]


def _make_passthrough_run(ctx):
    """创建一个直接返回 ctx 的 mock run 函数。"""
    return ctx


def _patch_all_raster_steps():
    """为所有光栅管道步骤创建 patch 对象列表，每个步骤的 run 直接返回 ctx。"""
    patches = []
    for mod_path in _RASTER_STEP_MODULES:
        p = patch(f"{mod_path}.run", side_effect=_make_passthrough_run)
        patches.append(p)
    return patches


def _patch_all_preview_steps():
    """为所有预览管道步骤创建 patch 对象列表，每个步骤的 run 直接返回 ctx。"""
    patches = []
    for mod_path in _PREVIEW_STEP_MODULES:
        p = patch(f"{mod_path}.run", side_effect=_make_passthrough_run)
        patches.append(p)
    return patches


# ===========================================================================
# Property 7: Coordinator 异常捕获
# Feature: image-pipeline-modularization, Property 7: Coordinator 异常捕获
# **Validates: Requirements 5.3**
# ===========================================================================

class TestProperty7CoordinatorExceptionCapture:
    """验证 Coordinator 捕获步骤异常并写入 ctx['error']，而非向上传播。

    使用 Hypothesis 生成随机异常消息字符串，mock 某个步骤模块的 run
    函数使其抛出异常，验证 Coordinator 捕获异常并写入 ctx['error']。
    """

    @given(
        error_msg=st.text(
            alphabet=st.characters(
                whitelist_categories=("L", "N", "P", "Z"),
            ),
            min_size=1,
            max_size=100,
        )
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow], deadline=None)
    def test_raster_pipeline_captures_s01_exception(self, error_msg: str):
        """光栅管道：S01 抛出异常时，Coordinator 捕获并写入 ctx['error']。"""
        from core.pipeline.coordinator import run_raster_pipeline

        def s01_raise(ctx):
            raise RuntimeError(error_msg)

        # Mock S01 抛出异常，其余步骤不应被调用
        with patch("core.pipeline.coordinator.s01_input_validation.run", side_effect=s01_raise):
            ctx = {"image_path": "test.png", "lut_path": "test.npy", "color_mode": "4-Color"}
            result = run_raster_pipeline(ctx)

        # 验证异常被捕获，不向上传播
        assert "error" in result, "Coordinator 应将异常写入 ctx['error']"
        assert error_msg in result["error"], (
            f"ctx['error'] 应包含异常消息 '{error_msg}'，实际为 '{result['error']}'"
        )

    @given(
        error_msg=st.text(
            alphabet=st.characters(
                whitelist_categories=("L", "N", "P", "Z"),
            ),
            min_size=1,
            max_size=100,
        )
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow], deadline=None)
    def test_raster_pipeline_captures_mid_step_exception(self, error_msg: str):
        """光栅管道：中间步骤（S02）抛出异常时，Coordinator 捕获并写入 ctx['error']。"""
        from core.pipeline.coordinator import run_raster_pipeline

        def s01_pass(ctx):
            # S01 正常返回，不设置 is_svg_vector
            return ctx

        def s02_raise(ctx):
            raise ValueError(error_msg)

        with patch("core.pipeline.coordinator.s01_input_validation.run", side_effect=s01_pass), \
             patch("core.pipeline.coordinator.s02_image_processing.run", side_effect=s02_raise):
            ctx = {}
            result = run_raster_pipeline(ctx)

        assert "error" in result
        assert error_msg in result["error"]

    @given(
        error_msg=st.text(
            alphabet=st.characters(
                whitelist_categories=("L", "N", "P", "Z"),
            ),
            min_size=1,
            max_size=100,
        )
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow], deadline=None)
    def test_preview_pipeline_captures_p01_exception(self, error_msg: str):
        """预览管道：P01 抛出异常时，Coordinator 捕获并写入 ctx['error']。"""
        from core.pipeline.coordinator import run_preview_pipeline

        def p01_raise(ctx):
            raise RuntimeError(error_msg)

        with patch("core.pipeline.coordinator.p01_preview_validation.run", side_effect=p01_raise):
            ctx = {}
            result = run_preview_pipeline(ctx)

        assert "error" in result
        assert error_msg in result["error"]

    @given(
        error_msg=st.text(
            alphabet=st.characters(
                whitelist_categories=("L", "N", "P", "Z"),
            ),
            min_size=1,
            max_size=100,
        )
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow], deadline=None)
    def test_preview_pipeline_captures_mid_step_exception(self, error_msg: str):
        """预览管道：中间步骤（P03）抛出异常时，Coordinator 捕获并写入 ctx['error']。"""
        from core.pipeline.coordinator import run_preview_pipeline

        def passthrough(ctx):
            return ctx

        def p03_raise(ctx):
            raise ValueError(error_msg)

        with patch("core.pipeline.coordinator.p01_preview_validation.run", side_effect=passthrough), \
             patch("core.pipeline.coordinator.p02_lut_metadata.run", side_effect=passthrough), \
             patch("core.pipeline.coordinator.p03_core_processing.run", side_effect=p03_raise):
            ctx = {}
            result = run_preview_pipeline(ctx)

        assert "error" in result
        assert error_msg in result["error"]

    def test_preview_pipeline_material_archive_svg_vector_routes_to_native_vector_preview(self):
        """material_archive + SVG + vector now routes to the native vector preview.

        Previously the coordinator forced this combination through the
        raster ``P02–P06`` chain (which rasterised the SVG and ran the
        material solver per-pixel, producing hard-edged previews with
        occasional 1-px misclassified colours along strokes). The
        coordinator now routes both LUT and material-archive sources
        through ``_run_vector_preview_branch``; the branch internally
        builds the right matcher (LUT KDTree vs material solver) so
        parse / clip / preview rasterisation are shared.

        耗材档案 + SVG + 矢量现在与 LUT 矢量共享原生矢量预览分支，
        分支内部按 ``material_source`` 构造对应匹配器，预览管线
        完全共线。本测试锁定该路由切换。
        """
        from config import ModelingMode
        from core.pipeline.coordinator import run_preview_pipeline

        def p01_material_archive(ctx):
            ctx = dict(ctx)
            ctx["modeling_mode"] = ModelingMode.VECTOR
            ctx["material_source"] = "material_archive"
            ctx["image_path"] = "/tmp/test.svg"
            return ctx

        vector_preview_calls: list = []

        def vector_preview_stub(ctx):
            vector_preview_calls.append(dict(ctx))
            return ctx

        def passthrough(ctx):
            return ctx

        # Each raster preview step must NOT be reached when the new
        # vector branch handles material-archive SVG inputs. We attach
        # an AssertionError side_effect so an accidental fallback is
        # caught immediately.
        # 走到任意 P02–P06 都说明路由失败，立即抛错以暴露回退。
        raster_step_should_not_run = AssertionError(
            "raster preview steps must not run for material_archive + svg + vector"
        )

        with patch(
            "core.pipeline.coordinator.p01_preview_validation.run",
            side_effect=p01_material_archive,
        ), patch(
            "core.pipeline.coordinator._run_vector_preview_branch",
            side_effect=vector_preview_stub,
        ), patch(
            "core.pipeline.coordinator.p02_lut_metadata.run",
            side_effect=raster_step_should_not_run,
        ), patch(
            "core.pipeline.coordinator.p03_core_processing.run",
            side_effect=raster_step_should_not_run,
        ), patch(
            "core.pipeline.coordinator.p04_cache_building.run",
            side_effect=raster_step_should_not_run,
        ), patch(
            "core.pipeline.coordinator.p05_palette_extraction.run",
            side_effect=raster_step_should_not_run,
        ), patch(
            "core.pipeline.coordinator.p06_bed_rendering.run",
            side_effect=raster_step_should_not_run,
        ):
            result = run_preview_pipeline({})

        assert "error" not in result
        assert len(vector_preview_calls) == 1, (
            "material_archive + svg + vector must route to "
            "_run_vector_preview_branch exactly once"
        )


# ===========================================================================
# Property 8: 进度回调调用
# Feature: image-pipeline-modularization, Property 8: 进度回调调用
# **Validates: Requirements 5.4**
# ===========================================================================

class TestProperty8ProgressCallbackInvocation:
    """验证包含 progress 回调的 ctx 在管道执行时至少调用一次，
    且进度值在 0.0-1.0 之间。

    使用 mock progress 函数记录调用，mock 所有步骤模块使其快速返回。
    """

    def test_raster_pipeline_calls_progress(self):
        """光栅管道执行时应至少调用一次 progress 回调，进度值在 [0.0, 1.0]。"""
        from core.pipeline.coordinator import run_raster_pipeline

        progress_calls = []

        def mock_progress(value, desc=""):
            progress_calls.append(value)

        def passthrough(ctx):
            return ctx

        patches = []
        for mod_path in _RASTER_STEP_MODULES:
            patches.append(patch(f"{mod_path}.run", side_effect=passthrough))

        for p in patches:
            p.start()
        try:
            ctx = {"progress": mock_progress}
            run_raster_pipeline(ctx)
        finally:
            for p in patches:
                p.stop()

        # 验证 progress 至少被调用一次
        assert len(progress_calls) >= 1, "progress 回调应至少被调用一次"

        # 验证所有进度值在 [0.0, 1.0] 之间
        for val in progress_calls:
            assert 0.0 <= val <= 1.0, (
                f"进度值应在 [0.0, 1.0] 之间，实际为 {val}"
            )

    def test_preview_pipeline_calls_progress(self):
        """预览管道执行时应至少调用一次 progress 回调，进度值在 [0.0, 1.0]。"""
        from core.pipeline.coordinator import run_preview_pipeline

        progress_calls = []

        def mock_progress(value, desc=""):
            progress_calls.append(value)

        def passthrough(ctx):
            return ctx

        patches = []
        for mod_path in _PREVIEW_STEP_MODULES:
            patches.append(patch(f"{mod_path}.run", side_effect=passthrough))

        for p in patches:
            p.start()
        try:
            ctx = {"progress": mock_progress}
            run_preview_pipeline(ctx)
        finally:
            for p in patches:
                p.stop()

        assert len(progress_calls) >= 1, "progress 回调应至少被调用一次"

        for val in progress_calls:
            assert 0.0 <= val <= 1.0, (
                f"进度值应在 [0.0, 1.0] 之间，实际为 {val}"
            )

    def test_no_progress_callback_does_not_crash(self):
        """ctx 中不包含 progress 回调时，管道不应崩溃。"""
        from core.pipeline.coordinator import run_raster_pipeline

        def passthrough(ctx):
            return ctx

        patches = []
        for mod_path in _RASTER_STEP_MODULES:
            patches.append(patch(f"{mod_path}.run", side_effect=passthrough))

        for p in patches:
            p.start()
        try:
            ctx = {}  # 无 progress 回调
            result = run_raster_pipeline(ctx)
        finally:
            for p in patches:
                p.stop()

        # 不应有错误
        assert "error" not in result or result.get("error") is None

    def test_progress_values_are_monotonically_nondecreasing(self):
        """光栅管道的 progress 值应单调非递减。"""
        from core.pipeline.coordinator import run_raster_pipeline

        progress_calls = []

        def mock_progress(value, desc=""):
            progress_calls.append(value)

        def passthrough(ctx):
            return ctx

        patches = []
        for mod_path in _RASTER_STEP_MODULES:
            patches.append(patch(f"{mod_path}.run", side_effect=passthrough))

        for p in patches:
            p.start()
        try:
            ctx = {"progress": mock_progress}
            run_raster_pipeline(ctx)
        finally:
            for p in patches:
                p.stop()

        assert len(progress_calls) >= 2, "progress 回调应有可比较的进度值"

        # 验证进度值单调非递减
        for i in range(1, len(progress_calls)):
            assert progress_calls[i] >= progress_calls[i - 1], (
                f"进度值应单调非递减，但 progress_calls[{i-1}]={progress_calls[i-1]} > "
                f"progress_calls[{i}]={progress_calls[i]}"
            )
