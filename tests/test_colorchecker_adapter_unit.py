"""Unit tests for the local ColorChecker adapter."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

import core.colorchecker_adapter as adapter
from core.colorchecker.diagnostics import (
    gray_reference_delta_metrics,
    gray_reference_delta_warnings,
)
from core.colorchecker.reference import ReferenceValidationError, normalize_reference
from core.colorchecker_adapter import (
    ColorCheckerCalibrationError,
    ColorCheckerUnavailableError,
    apply_colorchecker_calibration,
    build_display_summary,
    decode_colorchecker_upload,
    is_colorchecker_available,
)


def _reference_patches_with(field: str) -> list[dict[str, object]]:
    patches: list[dict[str, object]] = []
    for index in range(1, 25):
        patch: dict[str, object] = {"index": index, "label": f"Patch {index}"}
        if field == "sRGB":
            patch["sRGB"] = [index, index + 1, index + 2]
        elif field == "Lab_d50":
            patch["Lab_d50"] = [50.0, 0.0, 0.0]
        elif field == "Lab_d65":
            patch["Lab_d65"] = [50.0, 0.0, 0.0]
        else:
            patch.update(
                {
                    "sRGB": [index, index + 1, index + 2],
                    "Lab_d50": [50.0, 0.0, 0.0],
                    "Lab_d65": [50.0, 0.0, 0.0],
                }
            )
        patches.append(patch)
    return patches


class TestColorcheckerReferenceNormalization:
    """Tests for partial ColorChecker reference normalization."""

    def test_accepts_srgb_only_and_derives_lab(self) -> None:
        result = normalize_reference(_reference_patches_with("sRGB"), {"sourceName": "Upload"})

        first = result["patches"][0]
        assert first["sRGB"] == [1, 2, 3]
        assert len(first["Lab_d50"]) == 3
        assert len(first["Lab_d65"]) == 3
        assert result["source"]["source_name"] == "Upload"
        assert "reference_hash" not in result
        assert "reference_hash" not in result["source"]

    def test_accepts_lab_only_and_derives_srgb(self) -> None:
        result = normalize_reference(_reference_patches_with("Lab_d50"))

        first = result["patches"][0]
        assert len(first["sRGB"]) == 3
        assert len(first["Lab_d65"]) == 3

    def test_preserves_complete_reference_values(self) -> None:
        result = normalize_reference(_reference_patches_with("complete"))
        first = result["patches"][0]

        assert first["sRGB"] == [1, 2, 3]
        assert first["Lab_d50"] == [50.0, 0.0, 0.0]
        assert first["Lab_d65"] == [50.0, 0.0, 0.0]

    def test_rejects_patch_without_complete_color_triplet(self) -> None:
        patches = _reference_patches_with("sRGB")
        patches[0].pop("sRGB")

        with pytest.raises(ReferenceValidationError, match="至少需要完整"):
            normalize_reference(patches)

    def test_rejects_out_of_range_srgb(self) -> None:
        patches = _reference_patches_with("sRGB")
        patches[0]["sRGB"] = [0, 0, 300]

        with pytest.raises(ReferenceValidationError, match="0-255"):
            normalize_reference(patches)

    def test_rejects_duplicate_or_missing_indices(self) -> None:
        duplicate = _reference_patches_with("sRGB")
        duplicate[1]["index"] = 1
        with pytest.raises(ReferenceValidationError, match="重复编号"):
            normalize_reference(duplicate)

        missing = _reference_patches_with("sRGB")[:-1]
        with pytest.raises(ReferenceValidationError, match="24 个色块"):
            normalize_reference(missing)

    def test_rejects_duplicate_labels(self) -> None:
        patches = _reference_patches_with("sRGB")
        patches[1]["label"] = "Patch 1"

        with pytest.raises(ReferenceValidationError, match="重复色块名称"):
            normalize_reference(patches)


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


def test_detect_chart_uses_selected_reference_patches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image = np.zeros((20, 30, 3), dtype=np.uint8)
    custom_patches = _reference_patches_with("sRGB")
    captured: dict[str, object] = {}

    class FakeDetection:
        def to_dict(self) -> dict[str, object]:
            return {
                "detected": True,
                "corners": [
                    {"x": 0.0, "y": 0.0},
                    {"x": 1.0, "y": 0.0},
                    {"x": 1.0, "y": 1.0},
                    {"x": 0.0, "y": 1.0},
                ],
                "patchOrientation": "normal",
                "confidence": 1.0,
                "score": 0.0,
                "mode": "auto",
                "reason": "",
                "candidateCount": 1,
            }

    def fake_resolve_reference(**kwargs):
        captured.update(kwargs)
        return {"patches": custom_patches}

    def fake_detect(_image, reference_patches, **_kwargs):
        captured["reference_patches_arg"] = reference_patches
        return FakeDetection()

    fake_core = SimpleNamespace(resolve_reference=fake_resolve_reference)
    monkeypatch.setattr(adapter, "_import_core", lambda: fake_core)
    monkeypatch.setattr(
        "core.colorchecker.detection.detect_colorchecker_chart",
        fake_detect,
    )

    adapter.detect_colorchecker_chart(
        image,
        reference_patches=custom_patches,
        reference_source={"sourceName": "Upload"},
    )

    assert captured["reference_patches"] == custom_patches
    assert captured["reference_source"] == {"sourceName": "Upload"}
    assert captured["reference_patches_arg"] == custom_patches


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
                    "reference_hash": "abc123",
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
            reference_id="dafan",
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
        assert captured_kwargs["reference_id"] == "dafan"
        assert result.display_summary["deltaE00"]["mean"] == 1.0
        assert result.display_summary["worstPatch"]["deltaE00"] == 3.4
        assert result.display_summary["luminanceCurve"][0]["grayPatch"] is True
        assert result.display_summary["reference"]["sourceName"] == "大凡光学"
        assert result.display_summary["reference"]["labWhitePoint"] == "D50"
        assert "referenceHash" not in result.display_summary["reference"]
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

    @pytest.mark.parametrize(
        "patch_points",
        [
            [{"x": 1.0} for _ in range(24)],
            [{"x": "bad", "y": 0.0} for _ in range(24)],
            [[1.0] for _ in range(24)],
            [{"x": float("nan"), "y": 0.0} for _ in range(24)],
        ],
    )
    def test_invalid_manual_patch_points_raise_calibration_error(
        self,
        patch_points,
    ) -> None:
        with pytest.raises(ColorCheckerCalibrationError, match="patch_points"):
            apply_colorchecker_calibration(
                self._make_image(),
                self._make_corners(),
                patch_points=patch_points,
            )

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


def test_strict_fit_delta_e_warning_skips_acceptable_values() -> None:
    from core.colorchecker.strict_pipeline import _fit_delta_e_warning

    assert _fit_delta_e_warning("mean", 3.0) is None
    assert _fit_delta_e_warning("median", 3.0) is None
    assert _fit_delta_e_warning("P95", 6.0) is None
    assert _fit_delta_e_warning("max", 6.0) is None


def test_strict_fit_delta_e_warning_reports_check_level_values() -> None:
    from core.colorchecker.strict_pipeline import _fit_delta_e_warning

    assert (
        _fit_delta_e_warning("mean", 3.1)
        == "fit mean ΔE00 3.1 exceeds suggested 3.0 threshold."
    )
    assert (
        _fit_delta_e_warning("P95", 6.1)
        == "fit P95 ΔE00 6.1 exceeds suggested 6.0 threshold."
    )


def test_gray_reference_delta_does_not_warn_on_nonzero_reference_gray() -> None:
    reference = np.asarray([[19.04, -0.05, 1.99]], dtype=np.float64)
    corrected = reference.copy()

    metrics = gray_reference_delta_metrics(corrected, reference, [24], ["N2/"])

    assert metrics["b_delta_abs_max"] == 0.0
    assert gray_reference_delta_warnings(metrics) == []


def test_gray_reference_delta_warning_names_worst_gray_patch() -> None:
    reference = np.asarray(
        [
            [99.07, -1.1, 0.88],
            [38.85, -0.82, -1.57],
        ],
        dtype=np.float64,
    )
    corrected = np.asarray(
        [
            [99.07, -1.2, 1.0],
            [38.85, -0.9, -3.2],
        ],
        dtype=np.float64,
    )

    metrics = gray_reference_delta_metrics(
        corrected,
        reference,
        [19, 23],
        ["White", "N3.5/"],
    )

    warnings = gray_reference_delta_warnings(metrics)
    assert warnings == [
        "Neutral gray Δb* patch 23 (N3.5/) is -1.6300 "
        "(corrected -3.2000 vs reference -1.5700), exceeds suggested 1.5 threshold."
    ]


def test_standard_pipeline_uses_reference_lab_for_gray_delta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import core.colorchecker.pipeline as pipeline
    from core.colorchecker.reference import get_brand

    brand = get_brand(None)
    reference_patches = brand["patches"]
    reference_color_map = brand["color_map"]
    assert isinstance(reference_patches, list)
    assert isinstance(reference_color_map, dict)

    def fake_warp(image, _corners, preview_width, preview_height):
        preview = np.zeros((int(preview_height), int(preview_width), 3), dtype=np.uint8)
        ordered = np.asarray([[0, 0], [1, 0], [1, 1], [0, 1]], dtype=np.float32)
        return preview, np.ones(preview.shape[:2], dtype=np.uint8), ordered

    def fake_build_patch_measurements(
        _preview,
        _patch_points,
        _radius,
        _method,
        reference_patches_arg,
        _sampling_filter,
    ):
        patch_colors: dict[str, dict[str, object]] = {}
        patch_details: list[dict[str, object]] = []
        for patch in reference_patches_arg:
            label = str(patch["label"])
            linear_rgb = pipeline.srgb_to_linear(
                np.asarray(patch["sRGB"], dtype=np.float64)[:3] / 255.0
            )
            patch_colors[label] = {"linear_rgb": linear_rgb.tolist()}
            patch_details.append(
                {
                    "index": int(patch["index"]),
                    "label": label,
                    "point": {"x": 0.0, "y": 0.0},
                    "exclude_reasons": [],
                    "fit_used": True,
                }
            )
        return patch_colors, patch_details

    captured: dict[str, np.ndarray] = {}

    def capture_gray_delta(_corrected_lab, reference_lab, _patch_indices, _patch_labels=None):
        captured["reference_lab"] = np.asarray(reference_lab, dtype=np.float64)
        return {
            "patches": [],
            "a_delta_abs_max": None,
            "b_delta_abs_max": None,
            "a_delta_worst": None,
            "b_delta_worst": None,
        }

    monkeypatch.setattr(pipeline, "warp_colorchecker_preview", fake_warp)
    monkeypatch.setattr(pipeline, "build_patch_measurements", fake_build_patch_measurements)
    monkeypatch.setattr(pipeline, "gray_reference_delta_metrics", capture_gray_delta)
    monkeypatch.setattr(pipeline, "gray_reference_delta_warnings", lambda _metrics: [])

    corners = [{"x": 0.0, "y": 0.0}, {"x": 1.0, "y": 0.0}, {"x": 1.0, "y": 1.0}, {"x": 0.0, "y": 1.0}]
    patch_points = [{"x": 0.0, "y": 0.0} for _ in reference_patches]
    pipeline.calibrate_image_bgr(
        np.zeros((4, 4, 3), dtype=np.uint8),
        corners,
        patch_points,
        reference_patches,
        reference_color_map,
        sample_radius=2,
    )

    expected_gray_lab = np.stack(
        [
            np.asarray(patch["Lab_d65"], dtype=np.float64)[:3]
            for patch in reference_patches
            if 19 <= int(patch["index"]) <= 24
        ],
        axis=0,
    )
    np.testing.assert_allclose(captured["reference_lab"], expected_gray_lab)
