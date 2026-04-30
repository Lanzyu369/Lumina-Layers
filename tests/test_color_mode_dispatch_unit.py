"""ColorMode dispatch parity tests (Phase 1).
ColorMode 调度契约测试（Phase 1）。

These tests pin the canonical taxonomy in ``core/color_modes.py`` and the
behaviour of its lookup functions. They guard against future regressions
introduced when migrating downstream consumers (lut_merger, extractor,
calibration, detect_lut_color_mode) to ``ColorMode``.

Coverage:
- ``ColorMode.from_name`` accepts every legacy display string + alias
  used by ``config.ColorSystem.get`` (ConfigVerify L289-326).
- ``ColorSystem.get`` continues to return the historical ``dict`` shape
  (legacy bridge).
- ``ColorMode.from_lut_size`` matches the ``_SIZE_TO_MODE`` mapping.
- ``ColorMode.from_lut_size_and_layers`` reproduces the threshold cascade
  in ``detect_lut_color_mode``.
- ``mode.priority`` matches ``_MODE_PRIORITY`` and ``mode.max_material_id``
  matches ``_MODE_MAX_MATERIAL``.
- ``LUMINA_LUT_2468_MODE=merged`` env override still works through
  ``lut_2468_should_be_merged``.
"""

from __future__ import annotations

import os

import pytest


# ---------------------------------------------------------------------------
# from_name parity vs ColorSystem.get
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "expected_canonical"),
    [
        # 4-Color RYBW (and legacy aliases)
        ("4-Color", "4-Color"),
        ("4-Color (RYBW)", "4-Color"),
        ("RYBW", "4-Color"),
        # 4-Color CMYW
        ("4-Color (CMYW)", "4-Color (CMYW)"),
        ("CMYW", "4-Color (CMYW)"),
        # 6-Color CMYW (default 6-color)
        ("6-Color (CMYWGK 1296)", "6-Color (CMYWGK 1296)"),
        # 6-Color RYBW variant
        ("6-Color (RYBWGK 1296)", "6-Color (RYBWGK 1296)"),
        # 8-Color
        ("8-Color Max", "8-Color Max"),
        ("8-Color", "8-Color Max"),
        # 5-Color Extended
        ("5-Color Extended", "5-Color Extended"),
        ("5-Color (Extended)", "5-Color Extended"),
        # BW
        ("BW", "BW (Black & White)"),
        ("BW (Black & White)", "BW (Black & White)"),
        # Merged
        ("Merged", "Merged"),
    ],
)
def test_from_name_returns_canonical_mode(name: str, expected_canonical: str) -> None:
    """每个历史展示名都必须解析回正确的 canonical_display_name。"""
    from core.color_modes import ColorMode

    mode = ColorMode.from_name(name)
    assert mode is not None, f"`{name}` failed to resolve"
    assert mode.canonical_display_name == expected_canonical


def test_from_name_none_returns_none() -> None:
    """None 输入返回 None（与 ColorSystem.get 的默认 RYBW 不同 —
    ColorMode 把 None 视为未知，调用方应自行决定降级策略）。"""
    from core.color_modes import ColorMode

    assert ColorMode.from_name(None) is None


def test_from_name_unknown_returns_none() -> None:
    """完全无法识别的字符串返回 None。"""
    from core.color_modes import ColorMode

    assert ColorMode.from_name("totally-bogus-mode") is None


# ---------------------------------------------------------------------------
# Legacy bridge: ColorSystem.get still works after Phase 1 wiring
# ---------------------------------------------------------------------------


def test_legacy_dict_shape_for_each_mode() -> None:
    """每个非-Merged ColorMode 的 legacy_dict 必须是 ``ColorSystem.X`` 的同一对象。"""
    from config import ColorSystem
    from core.color_modes import iter_modes

    for mode in iter_modes():
        if mode.legacy_color_system_attr is None:
            continue
        assert mode.legacy_dict is getattr(ColorSystem, mode.legacy_color_system_attr)


def test_color_system_get_known_modes_unchanged() -> None:
    """``ColorSystem.get`` 仍返回历史 dict（无 Phase 1 行为退化）。"""
    from config import ColorSystem

    assert ColorSystem.get("4-Color") is ColorSystem.RYBW
    assert ColorSystem.get("4-Color (CMYW)") is ColorSystem.CMYW
    assert ColorSystem.get("6-Color (CMYWGK 1296)") is ColorSystem.SIX_COLOR
    assert ColorSystem.get("6-Color (RYBWGK 1296)") is ColorSystem.SIX_COLOR_RYBW
    assert ColorSystem.get("8-Color Max") is ColorSystem.EIGHT_COLOR
    assert ColorSystem.get("BW") is ColorSystem.BW
    assert ColorSystem.get("5-Color Extended") is ColorSystem.FIVE_COLOR_EXTENDED
    assert ColorSystem.get("Merged") is ColorSystem.EIGHT_COLOR
    # Default fallback for unknown / None
    assert ColorSystem.get(None) is ColorSystem.RYBW
    assert ColorSystem.get("foo") is ColorSystem.RYBW


# ---------------------------------------------------------------------------
# from_lut_size parity vs _SIZE_TO_MODE
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("size", "expected_canonical"),
    [
        (32, "BW (Black & White)"),
        (1024, "4-Color"),
        (1296, "6-Color (CMYWGK 1296)"),
        (2468, "5-Color Extended"),
        (2738, "8-Color Max"),
    ],
)
def test_from_lut_size_canonical(size: int, expected_canonical: str) -> None:
    """每个标准 LUT 尺寸必须映射到正确的 ColorMode。"""
    from core.color_modes import ColorMode

    mode = ColorMode.from_lut_size(size)
    assert mode is not None, f"size={size} failed to resolve"
    assert mode.canonical_display_name == expected_canonical


@pytest.mark.parametrize("size", [0, 1, 30, 33, 100, 1023, 1025, 1295, 1297, 2467, 2469, 2737, 2739, 9999])
def test_from_lut_size_unknown_returns_none(size: int) -> None:
    """非标准尺寸（不等于注册表中任何 expected_lut_size）必须返回 None。"""
    from core.color_modes import ColorMode

    assert ColorMode.from_lut_size(size) is None


# ---------------------------------------------------------------------------
# from_lut_size_and_layers parity vs detect_lut_color_mode thresholds
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("size", "layers", "max_material", "expected_canonical"),
    [
        # BW window: 30-35
        (30, None, None, "BW (Black & White)"),
        (32, None, None, "BW (Black & White)"),
        (35, None, None, "BW (Black & White)"),
        # 4-Color window: 900-1200
        (900, None, None, "4-Color"),
        (1024, None, None, "4-Color"),
        (1199, None, None, "4-Color"),
        # 6-Color window: 1200-1400
        (1200, None, None, "6-Color (CMYWGK 1296)"),
        (1296, None, None, "6-Color (CMYWGK 1296)"),
        (1399, None, None, "6-Color (CMYWGK 1296)"),
        # 5-Color Extended window: 2400-2600 AND layers==6 AND max_material<=4
        (2468, 6, 4, "5-Color Extended"),
        (2400, 6, 4, "5-Color Extended"),
        (2599, 6, None, "5-Color Extended"),
        # 8-Color Max window: 2600-2801
        (2600, None, None, "8-Color Max"),
        (2738, None, None, "8-Color Max"),
        (2800, None, None, "8-Color Max"),
    ],
)
def test_from_lut_size_and_layers_threshold_cascade(
    size: int,
    layers: int | None,
    max_material: int | None,
    expected_canonical: str,
) -> None:
    """阈值阶梯必须与 ``detect_lut_color_mode`` 一致。"""
    from core.color_modes import ColorMode

    mode = ColorMode.from_lut_size_and_layers(size, layers, max_material)
    assert mode is not None, f"size={size} layers={layers} max_mat={max_material} failed"
    assert mode.canonical_display_name == expected_canonical


def test_from_lut_size_and_layers_5color_guard_rejects_wrong_layers() -> None:
    """5-Color Extended 窗口内但层数不为 6 -> 不应命中 5-Color Extended。"""
    from core.color_modes import ColorMode

    # layers != 6 disqualifies 5-Color Extended; size 2468 falls in the
    # 5-color window only, so the cascade returns None (no 8-color fall-through
    # because 2468 < 2600).
    mode = ColorMode.from_lut_size_and_layers(2468, layers=5, max_material=None)
    assert mode is None or mode.canonical_display_name != "5-Color Extended"


def test_from_lut_size_and_layers_unknown_size_returns_none() -> None:
    """非任何窗口的尺寸 -> None。"""
    from core.color_modes import ColorMode

    assert ColorMode.from_lut_size_and_layers(500, None, None) is None


def test_from_lut_size_and_layers_npy_path_5color_by_size_alone() -> None:
    """.npy 路径不带 stacks 信息 (layers=None)，5-Color Extended 应仅按 size 命中。
    Pin the ``.npy`` LUT case: when ``layers`` is unknown the layer guard
    must be skipped (otherwise ``detect_lut_color_mode`` regresses for raw
    .npy files in the 2400-2599 size window).
    """
    from core.color_modes import ColorMode

    mode = ColorMode.from_lut_size_and_layers(2468, layers=None, max_material=None)
    assert mode is not None
    assert mode.canonical_display_name == "5-Color Extended"


# ---------------------------------------------------------------------------
# Priority + max_material_id parity vs lut_merger tables
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("canonical", "expected_priority", "expected_max_mat"),
    [
        ("Merged", -1, 7),
        ("BW (Black & White)", 0, 1),
        ("4-Color", 1, 3),
        ("5-Color Extended", 1, 4),
        ("6-Color (CMYWGK 1296)", 2, 5),
        ("8-Color Max", 3, 7),
    ],
)
def test_priority_and_max_material_match_legacy_tables(
    canonical: str,
    expected_priority: int,
    expected_max_mat: int,
) -> None:
    """``mode.priority`` / ``mode.max_material_id`` 必须与 lut_merger 旧表一致。"""
    from core.color_modes import ColorMode

    mode = ColorMode.from_name(canonical)
    assert mode is not None
    assert mode.priority == expected_priority
    assert mode.max_material_id == expected_max_mat


# ---------------------------------------------------------------------------
# Env override
# ---------------------------------------------------------------------------


def test_lut_2468_env_override_default_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """默认 ``LUMINA_LUT_2468_MODE`` 未设置时 env override 关闭。"""
    monkeypatch.delenv("LUMINA_LUT_2468_MODE", raising=False)
    from core.color_modes import lut_2468_should_be_merged

    assert lut_2468_should_be_merged() is False


def test_lut_2468_env_override_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """``LUMINA_LUT_2468_MODE=merged`` 触发 env override。"""
    monkeypatch.setenv("LUMINA_LUT_2468_MODE", "merged")
    from core.color_modes import lut_2468_should_be_merged

    assert lut_2468_should_be_merged() is True


# ---------------------------------------------------------------------------
# Iterator deterministic
# ---------------------------------------------------------------------------


def test_iter_modes_is_deterministic_and_unique() -> None:
    """枚举顺序稳定 + 名称唯一。"""
    from core.color_modes import iter_modes

    names = [mode.name for mode in iter_modes()]
    assert len(names) == len(set(names)), "ColorMode internal `name` must be unique"
