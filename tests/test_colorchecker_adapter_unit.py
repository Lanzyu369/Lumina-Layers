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
        with pytest.raises(ColorCheckerCalibrationError, match="Exactly 4"):
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

        mock_calibrate = MagicMock(return_value=fake_result)
        mock_module = MagicMock()
        mock_module.calibrate = mock_calibrate

        with patch.dict("sys.modules", {"colorchecker": mock_module}):
            # Need to clear the cached import so it re-imports
            import importlib
            import core.colorchecker_adapter as adapter_mod

            original_fn = adapter_mod.apply_colorchecker_calibration

            # Patch at the point of import inside the function
            with patch("builtins.__import__", side_effect=lambda name, *a, **kw: mock_module if name == "colorchecker" else __builtins__.__import__(name, *a, **kw)):
                # Direct test: mock the calibrate call
                pass

        # Simpler approach: patch the function's internal import
        with patch(
            "core.colorchecker_adapter.apply_colorchecker_calibration"
        ) as _:
            pass  # Can't easily test the internal import

        # Best approach: test via the actual function with a mock module
        fake_calibrate = MagicMock(return_value=fake_result)

        with patch.dict("sys.modules", {"colorchecker": MagicMock(calibrate=fake_calibrate)}):
            result = apply_colorchecker_calibration(img, corners)
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
