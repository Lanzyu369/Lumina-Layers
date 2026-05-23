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


def test_warp_preview_orients_auto_patch_points(monkeypatch: pytest.MonkeyPatch) -> None:
    """Warp preview should return auto points in detected reference order."""
    image = np.zeros((20, 30, 3), dtype=np.uint8)
    corners = [[0, 0], [29, 0], [29, 19], [0, 19]]

    from core.colorchecker.pipeline import generate_patch_points, orient_patch_points

    fake_core = SimpleNamespace(
        DEFAULT_PREVIEW_WIDTH=600,
        DEFAULT_PREVIEW_HEIGHT=400,
        warp_colorchecker_preview=lambda *_args, **_kwargs: (
            np.zeros((400, 600, 3), dtype=np.uint8),
            np.zeros((400, 600), dtype=np.uint8),
            np.zeros((4, 2), dtype=np.float32),
        ),
        generate_patch_points=generate_patch_points,
        orient_patch_points=orient_patch_points,
        encode_png_bytes=lambda _image: b"png",
    )
    monkeypatch.setattr(adapter, "_import_core", lambda: fake_core)

    result = adapter.warp_colorchecker_preview(
        image,
        corners,
        patch_orientation="flip_horizontal",
    )

    assert result.auto_patch_points[0]["x"] > result.auto_patch_points[1]["x"]


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
            preview_overlay_image=np.zeros((8, 8, 3), dtype=np.uint8),
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
                "reference_source": {
                    "source_type": "built_in",
                    "source_name": "大凡光学",
                    "serial_number": None,
                    "patch_count": 24,
                    "lab_white_point": "D50",
                },
                "method": "median",
                "selected_model": "root_polynomial",
                "gray_affine_mode": "enabled",
                "sample_radius": 9,
                "blur_radius": 1.5,
            },
        )
        captured_kwargs: dict[str, object] = {}

        def fake_calibrate(*_args, **kwargs):
            captured_kwargs.update(kwargs)
            return fake_result

        fake_core = SimpleNamespace(calibrate=fake_calibrate)
        monkeypatch.setattr(adapter, "_import_core", lambda: fake_core)

        result = apply_colorchecker_calibration(
            img,
            corners,
            sample_radius=9,
            method="median",
            calibration_mode="root_polynomial",
            gray_affine_mode="enabled",
            blur_radius=1.5,
        )

        assert result.calibrated_image is calibrated
        assert result.overlay_image.shape == (8, 8, 3)
        assert result.overlay_png == b"overlay"
        assert captured_kwargs["encode_calibrated_png"] is False
        assert captured_kwargs["sample_radius"] == 9
        assert captured_kwargs["method"] == "median"
        assert captured_kwargs["calibration_mode"] == "root_polynomial"
        assert captured_kwargs["gray_affine_mode"] == "enabled"
        assert captured_kwargs["blur_radius"] == 1.5
        assert result.display_summary["deltaE00"]["mean"] == 1.0
        assert result.display_summary["worstPatch"]["deltaE00"] == 3.4
        assert result.display_summary["luminanceCurve"][0]["grayPatch"] is True
        assert result.display_summary["reference"]["sourceName"] == "大凡光学"
        assert result.display_summary["reference"]["labWhitePoint"] == "D50"
        assert result.display_summary["settings"]["method"] == "median"
        assert result.display_summary["settings"]["calibrationMode"] == "root_polynomial"
        assert result.display_summary["settings"]["grayAffineMode"] == "enabled"

    def test_orients_generated_patch_points_when_no_manual_points(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        img = self._make_image()
        corners = self._make_corners()
        calibrated = self._make_image()
        fake_result = SimpleNamespace(
            calibrated_image=calibrated,
            preview_overlay_image=np.zeros((8, 8, 3), dtype=np.uint8),
            preview_overlay_png=b"overlay",
            patch_points=[{"x": 1.0, "y": 2.0}] * 24,
            report={},
        )
        captured_kwargs: dict[str, object] = {}

        def fake_calibrate(*_args, **kwargs):
            captured_kwargs.update(kwargs)
            return fake_result

        from core.colorchecker.pipeline import generate_patch_points, orient_patch_points

        fake_core = SimpleNamespace(
            DEFAULT_PREVIEW_WIDTH=600,
            DEFAULT_PREVIEW_HEIGHT=400,
            generate_patch_points=generate_patch_points,
            orient_patch_points=orient_patch_points,
            calibrate=fake_calibrate,
        )
        monkeypatch.setattr(adapter, "_import_core", lambda: fake_core)

        apply_colorchecker_calibration(
            img,
            corners,
            patch_orientation="flip_horizontal",
        )

        patch_points = captured_kwargs["patch_points"]
        assert isinstance(patch_points, list)
        assert patch_points[0]["x"] > patch_points[1]["x"]

    def test_manual_patch_points_are_not_oriented_twice(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        img = self._make_image()
        corners = self._make_corners()
        manual_points = [{"x": float(i), "y": 0.0} for i in range(24)]
        calibrated = self._make_image()
        fake_result = SimpleNamespace(
            calibrated_image=calibrated,
            preview_overlay_image=np.zeros((8, 8, 3), dtype=np.uint8),
            preview_overlay_png=b"overlay",
            patch_points=manual_points,
            report={},
        )
        captured_kwargs: dict[str, object] = {}

        def fake_calibrate(*_args, **kwargs):
            captured_kwargs.update(kwargs)
            return fake_result

        fake_core = SimpleNamespace(calibrate=fake_calibrate)
        monkeypatch.setattr(adapter, "_import_core", lambda: fake_core)

        apply_colorchecker_calibration(
            img,
            corners,
            patch_points=manual_points,
            patch_orientation="flip_horizontal",
        )

        assert captured_kwargs["patch_points"] == manual_points

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
