"""Exercise both public LUT detection entry points with real files."""

import numpy as np
import pytest

from config import ModelingMode
from core import converter
from core.pipeline import pipeline_utils


@pytest.fixture(params=[converter, pipeline_utils], ids=["compat", "pipeline"])
def detector(request):
    return request.param


@pytest.mark.parametrize(
    ("size", "expected"),
    [(32, "BW (Black & White)"), (1024, "4-Color"),
     (1296, "6-Color (CMYWGK 1296)"), (2468, "5-Color Extended"),
     (2738, "8-Color Max"), (7, "Merged")],
)
def test_npy_modes(detector, tmp_path, size, expected):
    path = tmp_path / "colors.npy"
    np.save(path, np.zeros((size, 3), dtype=np.uint8))
    assert detector.detect_lut_color_mode(str(path)) == expected


@pytest.mark.parametrize("layers,max_material,expected", [
    (None, None, "Merged"), (5, 4, "Merged"),
    (6, 4, "5-Color Extended"), (6, 5, "Merged"),
])
def test_extended_npz_requires_six_layer_recipes(
    detector, tmp_path, layers, max_material, expected,
):
    path = tmp_path / "extended.npz"
    arrays = {"rgb": np.zeros((2468, 3), dtype=np.uint8)}
    if layers is not None:
        arrays["stacks"] = np.full((2468, layers), max_material, dtype=np.int32)
    np.savez(path, **arrays)
    assert detector.detect_lut_color_mode(str(path)) == expected


@pytest.mark.parametrize("suffix,expected", [
    ("npy", None), ("npz", None), ("json", "4-Color (CMYW)"),
])
def test_invalid_lut_preserves_loader_fallback(detector, tmp_path, suffix, expected):
    path = tmp_path / f"invalid.{suffix}"
    path.write_bytes(b"invalid file")
    assert detector.detect_lut_color_mode(str(path)) == expected


def test_empty_missing_and_invalid_flat_lut(detector, tmp_path):
    assert detector.detect_lut_color_mode(None) is None
    assert detector.detect_lut_color_mode(str(tmp_path / "missing.npy")) is None
    path = tmp_path / "flat.npy"
    np.save(path, np.zeros(5, dtype=np.uint8))
    assert detector.detect_lut_color_mode(str(path)) is None


@pytest.mark.parametrize("path,expected", [
    ("art.SVG", ModelingMode.VECTOR), ("photo.png", None),
    (None, None), (17, None),
])
def test_image_recommendation(detector, path, expected):
    assert detector.detect_image_type(path) == expected
