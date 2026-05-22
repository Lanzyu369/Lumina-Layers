"""Unit tests for the local ColorChecker adapter."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

import core.colorchecker_adapter as adapter
from core.colorchecker_adapter import (
    ColorCheckerCalibrationError,
    ColorCheckerUnavailableError,
    apply_colorchecker_calibration,
    build_display_summary,
    decode_colorchecker_upload,
    is_colorchecker_available,
)


class TestIsColorcheckerAvailable:
    """Tests for the local core import probe."""

    def test_returns_true_for_local_package(self) -> None:
        assert is_colorchecker_available() is True

    def test_returns_false_when_local_import_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fail_import():
            raise ImportError("missing local module")

        monkeypatch.setattr(adapter, "_import_core", fail_import)
        assert is_colorchecker_available() is False


class TestDecodeColorcheckerUpload:
    """Tests for upload decoding through the local core."""

    def test_decodes_with_local_core(self, monkeypatch: pytest.MonkeyPatch) -> None:
        image = np.zeros((10, 12, 3), dtype=np.uint8)

        fake_core = SimpleNamespace(
            decode_uploaded_bytes=lambda raw, file_name, mime_type: (image, "standard")
        )
        monkeypatch.setattr(adapter, "_import_core", lambda: fake_core)

        result = decode_colorchecker_upload(
            b"fake",
            file_name="chart.png",
            mime_type="image/png",
        )

        assert result.image_bgr is image
        assert result.source_type == "standard"

    def test_wraps_decode_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fail_decode(*_args, **_kwargs):
            raise ValueError("bad image")

        fake_core = SimpleNamespace(decode_uploaded_bytes=fail_decode)
        monkeypatch.setattr(adapter, "_import_core", lambda: fake_core)

        with pytest.raises(ColorCheckerCalibrationError, match="bad image"):
            decode_colorchecker_upload(b"bad")


class TestApplyColorcheckerCalibration:
    """Tests for applying calibration through the local core."""

    def _make_image(self, h: int = 100, w: int = 200) -> np.ndarray:
        return np.random.randint(0, 256, (h, w, 3), dtype=np.uint8)

    def _make_corners(self) -> list[list[float]]:
        return [[10, 10], [190, 10], [190, 90], [10, 90]]

    def test_raises_when_local_core_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fail_import():
            raise ImportError("missing local module")

        monkeypatch.setattr(adapter, "_import_core", fail_import)

        with pytest.raises(ColorCheckerUnavailableError, match="Local core"):
            apply_colorchecker_calibration(self._make_image(), self._make_corners())

    def test_raises_on_wrong_corner_count(self) -> None:
        img = self._make_image()
        with pytest.raises(ColorCheckerCalibrationError, match="(?i)exactly 4"):
            apply_colorchecker_calibration(img, [[0, 0], [1, 1]])

    def test_raises_on_invalid_image_shape(self) -> None:
        img = np.zeros((100, 200), dtype=np.uint8)
        corners = self._make_corners()
        with pytest.raises(ColorCheckerCalibrationError, match="shape"):
            apply_colorchecker_calibration(img, corners)

    def test_success_returns_calibrated_image_and_summary(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        img = self._make_image()
        corners = self._make_corners()
        calibrated = self._make_image()

        fake_result = SimpleNamespace(
            calibrated_image=calibrated,
            calibrated_png=b"png",
            preview_overlay_png=b"overlay",
            patch_points=[{"x": 1.0, "y": 2.0}] * 24,
            report={
                "fit_metrics": {
                    "delta_e00": {
                        "mean": 1.0,
                        "median": 0.9,
                        "p95": 2.2,
                        "max": 3.4,
                    }
                },
                "patches": [
                    {
                        "index": 1,
                        "label": "Patch 1",
                        "deltaE00": 3.4,
                        "reference_sRGB": [1, 2, 3],
                        "corrected_sRGB": [3, 2, 1],
                    }
                ],
                "luminance_diagnostics": {
                    "patches": [
                        {
                            "index": 1,
                            "label": "Patch 1",
                            "reference_level": 0.4,
                            "captured_level": 0.3,
                            "normalized_level": 0.35,
                            "corrected_level": 0.39,
                            "fit_used": True,
                            "is_gray_patch": True,
                        }
                    ]
                },
                "warnings": ["notice"],
            },
        )
        fake_core = SimpleNamespace(calibrate=lambda *_args, **_kwargs: fake_result)
        monkeypatch.setattr(adapter, "_import_core", lambda: fake_core)

        result = apply_colorchecker_calibration(img, corners)

        assert result.calibrated_image is calibrated
        assert result.calibrated_png == b"png"
        assert result.overlay_png == b"overlay"
        assert result.display_summary["deltaE00"]["mean"] == 1.0
        assert result.display_summary["worstPatch"]["deltaE00"] == 3.4
        assert result.display_summary["luminanceCurve"][0]["grayPatch"] is True

    def test_calibrate_exception_wraps_as_calibration_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def fail_calibrate(*_args, **_kwargs):
            raise RuntimeError("internal failure")

        fake_core = SimpleNamespace(calibrate=fail_calibrate)
        monkeypatch.setattr(adapter, "_import_core", lambda: fake_core)

        with pytest.raises(ColorCheckerCalibrationError, match="internal failure"):
            apply_colorchecker_calibration(self._make_image(), self._make_corners())


def test_build_display_summary_falls_back_to_legacy_stats() -> None:
    summary = build_display_summary(
        {
            "stats": {
                "mean_delta_e": 1.2,
                "median_delta_e": 1.0,
                "p95_delta_e": 2.4,
                "max_delta_e": 3.0,
            }
        }
    )

    assert summary["deltaE00"] == {
        "mean": 1.2,
        "median": 1.0,
        "p95": 2.4,
        "max": 3.0,
    }
