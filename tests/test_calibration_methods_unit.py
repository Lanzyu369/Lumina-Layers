"""Tests for the Phase 2 CalibrationMethod protocol + lighthouse adopter."""

from __future__ import annotations

from unittest.mock import patch

import pytest


def test_calibration_params_defaults() -> None:
    """``CalibrationParams`` 默认值与 ``generate_smart_board`` 历史默认对齐。"""
    from core.calibration_methods import CalibrationParams

    params = CalibrationParams()
    assert params.block_size_mm == 5.0
    assert params.gap_mm == 0.8
    assert params.backing_thickness_mm is None
    assert params.page_index == 0
    assert params.options == {}


def test_calibration_params_is_frozen() -> None:
    """``CalibrationParams`` 必须是 frozen dataclass。"""
    from core.calibration_methods import CalibrationParams

    params = CalibrationParams()
    with pytest.raises(Exception):  # FrozenInstanceError or AttributeError
        params.block_size_mm = 7.5  # type: ignore[misc]


def test_smart1296_satisfies_protocol() -> None:
    """``Smart1296CalibrationMethod`` 必须满足 ``CalibrationMethod`` 协议。"""
    from core.calibration_methods import (
        CalibrationMethod,
        Smart1296CalibrationMethod,
    )

    method = Smart1296CalibrationMethod()
    assert isinstance(method, CalibrationMethod)
    assert method.name == "smart-1296"
    assert method.description


def test_smart1296_rejects_wrong_mode() -> None:
    """Smart1296 只服务于 6-Color (CMYWGK 1296)；传入其它模式应当拒绝。"""
    from core.calibration_methods import (
        CalibrationParams,
        Smart1296CalibrationMethod,
    )
    from core.color_modes import ColorMode

    method = Smart1296CalibrationMethod()
    bw = ColorMode.from_name("BW")
    assert bw is not None
    with pytest.raises(ValueError, match="Smart1296"):
        method.generate(bw, CalibrationParams())


def test_smart1296_delegates_to_generate_smart_board() -> None:
    """传入正确模式时必须调用 ``generate_smart_board`` 并透传参数。
    Pin the bit-exact contract: Smart1296 forwards params to the legacy
    entry point untouched.
    """
    from core.calibration_methods import (
        CalibrationParams,
        Smart1296CalibrationMethod,
    )
    from core.color_modes import ColorMode

    method = Smart1296CalibrationMethod()
    mode = ColorMode.from_name("6-Color (CMYWGK 1296)")
    assert mode is not None
    params = CalibrationParams(block_size_mm=4.5, gap_mm=1.0, backing_thickness_mm=2.4)

    sentinel_result = object()
    with patch("core.calibration.generate_smart_board", return_value=sentinel_result) as fake:
        result = method.generate(mode, params)

    assert result is sentinel_result
    fake.assert_called_once_with(
        block_size_mm=4.5,
        gap_mm=1.0,
        backing_thickness_mm=2.4,
    )
