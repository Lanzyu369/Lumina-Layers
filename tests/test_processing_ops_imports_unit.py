"""processing_ops 公共符号可导入性测试 (Phase 0 Sub-PR A).
Symbol-import contract for processing_ops shim removal (Phase 0 Sub-PR A).

These tests pin the contract that every public symbol previously exposed by the
zero-logic re-export shims under ``core/pipeline/processing_ops/`` is still
reachable from its canonical ``core.*`` location after the shim is deleted.

测试目的：
- 锁定 ``HueAwareColorMatcher`` 仍可从 ``core.color_matching_hue_aware`` 导入。
- 锁定 ``cleanup_isolated_pixels`` 仍可从 ``core.isolated_pixel_cleanup`` 导入。
- 锁定保留下来的 ``processing_ops/`` 模块仍可正常导入（防止误删）。

Per design doc §14.3.A: "assert that every public symbol previously importable
from ``core.pipeline.processing_ops.<shim>`` is still importable from the new
direct path post-refactor. Catches missed call sites."
"""

from __future__ import annotations

import importlib

import pytest


# 已删除的纯 shim → 必须从下列规范路径导入。
# Pure shims that were deleted; the canonical import paths below must keep working.
CANONICAL_SYMBOL_PATHS: tuple[tuple[str, str], ...] = (
    ("core.color_matching_hue_aware", "HueAwareColorMatcher"),
    ("core.isolated_pixel_cleanup", "cleanup_isolated_pixels"),
)


# 保留的 processing_ops 子模块（含真实本地逻辑，非 shim）。
# Retained processing_ops modules (real local logic, not shims).
RETAINED_PROCESSING_OPS_MODULES: tuple[str, ...] = (
    "core.pipeline.processing_ops.bilateral_filter",
    "core.pipeline.processing_ops.median_filter",
    "core.pipeline.processing_ops.background_remover",
    "core.pipeline.processing_ops.wireframe_extractor",
    "core.pipeline.processing_ops.image_scaler",
    "core.pipeline.processing_ops.kmeans_quantizer",
    "core.pipeline.processing_ops.lut_color_matcher",
    "core.pipeline.processing_ops.lut_loader",
    "core.pipeline.processing_ops.svg_rasterizer",
)


@pytest.mark.parametrize(("module_path", "symbol_name"), CANONICAL_SYMBOL_PATHS)
def test_canonical_symbol_is_importable(module_path: str, symbol_name: str) -> None:
    """每个被 shim 暴露过的符号都必须能从规范的 ``core.*`` 路径直接导入。
    Every symbol previously exposed via a shim must remain importable from its
    canonical ``core.*`` path.
    """
    module = importlib.import_module(module_path)
    assert hasattr(module, symbol_name), (
        f"Expected `{symbol_name}` to be exported from `{module_path}` "
        f"after Phase 0 Sub-PR A shim removal"
    )


@pytest.mark.parametrize("module_path", RETAINED_PROCESSING_OPS_MODULES)
def test_retained_processing_ops_module_still_importable(module_path: str) -> None:
    """保留下来的 processing_ops 子模块（非 shim）必须仍然可导入。
    Retained processing_ops sub-modules (which carry real local logic) must
    continue to be importable — guarding against accidental deletion.
    """
    importlib.import_module(module_path)


# 已删除的纯 shim 路径；任何复活都会被这条断言挡住。
# Deleted pure-shim paths; any accidental resurrection is caught here.
DELETED_SHIM_MODULES: tuple[str, ...] = (
    "core.pipeline.processing_ops.hue_aware_matcher",
    "core.pipeline.processing_ops.isolated_pixel_cleanup",
)


@pytest.mark.parametrize("module_path", DELETED_SHIM_MODULES)
def test_deleted_shim_module_is_gone(module_path: str) -> None:
    """已删除的纯 shim 路径不得再被导入。
    Deleted pure-shim modules must no longer be importable.

    Guards against accidental re-introduction of the zero-logic re-export
    layer that was removed in Phase 0 Sub-PR A; new callers must use the
    canonical ``core.*`` paths (see :data:`CANONICAL_SYMBOL_PATHS`).
    """
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(module_path)
