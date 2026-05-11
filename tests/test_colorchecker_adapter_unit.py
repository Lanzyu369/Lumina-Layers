"""Unit tests for core.colorchecker_adapter."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from core.colorchecker_adapter import (
    ColorCheckerCalibrationError,
    ColorCheckerUnavailableError,
    apply_colorchecker_calibration,
    is_colorchecker_available,
)


class TestIsColorcheckerAvailable:
    """Tests for is_colorchecker_available()."""

    def test_returns_true_when_installed(self) -> None:
        with patch.dict("sys.modules", {"colorchecker": MagicMock()}):
            assert is_colorchecker_available() is True

    def test_returns_false_when_not_installed(self) -> None:
        with patch.dict("sys.modules", {"colorchecker": None}):
            assert is_colorchecker_available() is False


class TestApplyColorcheckerCalibration:
    """Tests for apply_colorchecker_calibration()."""

    def _make_image(self, h: int = 100, w: int = 200) -> np.ndarray:
        return np.random.randint(0, 256, (h, w, 3), dtype=np.uint8)

    def _make_corners(self) -> list[list[float]]:
        return [[10, 10], [190, 10], [190, 90], [10, 90]]

    def test_raises_when_package_missing(self) -> None:
        img = self._make_image()
        corners = self._make_corners()
        with patch.dict("sys.modules", {"colorchecker": None}):
            with pytest.raises(ColorCheckerUnavailableError, match="not installed"):
                apply_colorchecker_calibration(img, corners)

    def test_raises_on_wrong_corner_count(self) -> None:
        img = self._make_image()
        with pytest.raises(ColorCheckerCalibrationError, match="(?i)exactly 4"):
            apply_colorchecker_calibration(img, [[0, 0], [1, 1]])

    def test_raises_on_invalid_image_shape(self) -> None:
        img = np.zeros((100, 200), dtype=np.uint8)  # 2D, no channels
        corners = self._make_corners()
        with pytest.raises(ColorCheckerCalibrationError, match="shape"):
            apply_colorchecker_calibration(img, corners)

    def test_success_returns_calibrated_image(self) -> None:
        img = self._make_image()
        corners = self._make_corners()

        fake_result = MagicMock()
        fake_result.calibrated_image = self._make_image()

        fake_calibrate = MagicMock(return_value=fake_result)

        with patch.dict("sys.modules", {"colorchecker": MagicMock(calibrate=fake_calibrate)}):
            result = apply_colorchecker_calibration(img, corners)
            assert hasattr(result, "calibrated_image")
            assert isinstance(result.calibrated_image, np.ndarray)
            assert result.calibrated_image.shape == fake_result.calibrated_image.shape

    def test_calibrate_exception_wraps_as_calibration_error(self) -> None:
        img = self._make_image()
        corners = self._make_corners()

        mock_calibrate = MagicMock(side_effect=RuntimeError("internal failure"))
        with patch.dict(
            "sys.modules",
            {"colorchecker": MagicMock(calibrate=mock_calibrate)},
        ):
            with pytest.raises(ColorCheckerCalibrationError, match="internal failure"):
                apply_colorchecker_calibration(img, corners)
