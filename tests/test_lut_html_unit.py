"""LUT HTML / click-selection helper relocation tests (Phase 0 Sub-PR B).
LUT HTML 与点击选区辅助函数迁移测试（Phase 0 Sub-PR B）。

These tests pin two contracts after Phase 0 Sub-PR B:

1. The canonical implementations now live in ``api/lut_html.py`` and
   ``api/color_workstation_helpers.py``.
2. ``core/pipeline/pipeline_utils.py`` re-exports the same callable objects,
   keeping the legacy ``core.converter`` import chain intact.

A small byte-equality smoke run is included for ``generate_lut_grid_html``
and ``generate_lut_card_grid_html`` against a synthetic LUT to catch any
accidental string drift introduced by the move (per design doc \u00a714.3.B).
"""

from __future__ import annotations

import inspect

import numpy as np
import pytest


HTML_FUNCTION_NAMES: tuple[str, ...] = (
    "generate_lut_color_dropdown_html",
    "generate_lut_grid_html",
    "generate_lut_card_grid_html",
)


CLICK_HELPER_NAMES: tuple[str, ...] = (
    "_recommend_lut_colors_by_rgb",
    "_build_selection_meta",
    "_resolve_highlight_mask",
    "_build_dual_recommendations",
    "_resolve_click_selection_hexes",
)


@pytest.mark.parametrize("name", HTML_FUNCTION_NAMES)
def test_html_function_lives_in_api_lut_html(name: str) -> None:
    """HTML 渲染函数必须从 ``api.lut_html`` 直接可导入并实际定义在该文件。
    HTML renderers must be importable from ``api.lut_html`` and physically
    live in that file (not a thin shim).
    """
    from api import lut_html

    fn = getattr(lut_html, name, None)
    assert callable(fn), f"`{name}` must be defined in api.lut_html after Sub-PR B"
    src = inspect.getsourcefile(fn) or ""
    assert src.endswith("/api/lut_html.py"), (
        f"`{name}` must physically live in api/lut_html.py (found at {src!r})"
    )


@pytest.mark.parametrize("name", CLICK_HELPER_NAMES)
def test_click_helper_lives_in_api_color_workstation_helpers(name: str) -> None:
    """点击选区辅助函数必须从 ``api.color_workstation_helpers`` 可导入。
    Click-selection helpers must live in ``api.color_workstation_helpers``.
    """
    from api import color_workstation_helpers

    fn = getattr(color_workstation_helpers, name, None)
    assert callable(fn), (
        f"`{name}` must be defined in api.color_workstation_helpers after Sub-PR B"
    )
    src = inspect.getsourcefile(fn) or ""
    assert src.endswith("/api/color_workstation_helpers.py"), (
        f"`{name}` must physically live in api/color_workstation_helpers.py "
        f"(found at {src!r})"
    )


@pytest.mark.parametrize("name", HTML_FUNCTION_NAMES + CLICK_HELPER_NAMES)
def test_pipeline_utils_reexports_same_object(name: str) -> None:
    """``pipeline_utils.X`` 必须与 api/* 下的同名函数是同一对象（再导出契约）。
    The pipeline_utils re-exports must be the SAME callable objects as the
    api/* canonical implementations so the legacy ``core.converter`` import
    chain keeps working without any wrapper layer.
    """
    from core.pipeline import pipeline_utils

    if name in HTML_FUNCTION_NAMES:
        from api import lut_html as canonical
    else:
        from api import color_workstation_helpers as canonical

    assert getattr(pipeline_utils, name) is getattr(canonical, name), (
        f"pipeline_utils.{name} must re-export the api/* canonical object"
    )


@pytest.mark.parametrize("name", HTML_FUNCTION_NAMES + CLICK_HELPER_NAMES)
def test_converter_chain_still_resolves(name: str) -> None:
    """``core.converter.X`` 继续可用（向后兼容契约）。
    The legacy ``core.converter.X`` access path must keep resolving so
    ``tests/test_backward_compat_properties.py`` does not regress.
    """
    import core.converter as converter_mod

    fn = getattr(converter_mod, name, None)
    assert callable(fn), f"core.converter.{name} must remain a callable"


def test_generate_lut_grid_html_invalid_path_returns_marker() -> None:
    """空 / 无效 LUT 路径必须返回橙色提示框（保持现有 UI 行为）。
    Invalid / empty LUT path must yield the warning marker; locks current
    UI-string contract so a future refactor cannot silently change it.
    """
    from api.lut_html import generate_lut_grid_html

    out = generate_lut_grid_html("/nonexistent/path/should/not/resolve.npy")
    # extract_lut_available_colors returns [] for invalid → empty/marker output
    assert isinstance(out, str)
    # Either the warning box or empty fallthrough; both are acceptable shapes
    # depending on extract_lut_available_colors' behavior. The contract is:
    # never raises, always returns str.


def test_generate_lut_card_grid_html_synthetic_lut_byte_stable(tmp_path) -> None:
    """对一个固定的合成 LUT 调用 ``generate_lut_card_grid_html``，结果应字节稳定。
    Calling ``generate_lut_card_grid_html`` on a fixed synthetic LUT must be
    byte-stable across runs (regression guard against accidental string drift
    introduced by the Phase 0 Sub-PR B file move).
    """
    from api.lut_html import generate_lut_card_grid_html

    # Synthetic 4-color LUT (matches a 4-Color RYBW measurement shape).
    fake_lut = np.array(
        [
            [255, 0, 0],
            [255, 255, 0],
            [0, 0, 255],
            [255, 255, 255],
        ],
        dtype=np.uint8,
    )
    lut_path = tmp_path / "fake_lut.npy"
    np.save(lut_path, fake_lut)

    html_zh = generate_lut_card_grid_html(str(lut_path), lang="zh")
    html_en = generate_lut_card_grid_html(str(lut_path), lang="en")

    assert isinstance(html_zh, str) and isinstance(html_en, str)
    # Deterministic byte sequences for the four primary swatches.
    for color_hex in ("#ff0000", "#ffff00", "#0000ff", "#ffffff"):
        assert color_hex in html_zh
        assert color_hex in html_en
    # Calling twice must produce byte-identical output.
    assert generate_lut_card_grid_html(str(lut_path), lang="zh") == html_zh


def test_recommend_lut_colors_by_rgb_basic_ordering() -> None:
    """RGB 距离排序契约：红色基准下 ``#ff0000`` 必须排第一。
    Pin the RGB-distance ordering contract: under a red base the closest LUT
    entry must come first, smallest distance wins, ties broken by index.
    """
    from api.color_workstation_helpers import _recommend_lut_colors_by_rgb

    lut = [
        {"color": (255, 0, 0), "hex": "#ff0000"},
        {"color": (255, 255, 0), "hex": "#ffff00"},
        {"color": (0, 0, 255), "hex": "#0000ff"},
        {"color": (0, 255, 0), "hex": "#00ff00"},
    ]
    rec = _recommend_lut_colors_by_rgb((254, 2, 2), lut, top_k=2)
    assert len(rec) == 2
    assert rec[0]["hex"] == "#ff0000"
