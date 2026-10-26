"""Unit tests for the Vectorizer feature.
Vectorizer 功能的单元测试。

Covers:
- VectorizeParams schema field count and defaults
- VectorizeResponse / VectorizeDefaultsResponse structure
- SVG MIME type mapping in _guess_media_type
- worker_vectorize return structure and temp-file cleanup (mocked neroued_vectorizer)
- Pydantic ValidationError on out-of-range params
"""

import os
import sys
import tempfile
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from api.schemas.vectorizer import (
    VectorizeDefaultsResponse,
    VectorizeParams,
    VectorizeResponse,
)
from api.file_bridge import _guess_media_type


# ---------------------------------------------------------------------------
# VectorizeParams schema tests
# ---------------------------------------------------------------------------

class TestVectorizeParamsSchema:
    """Tests for VectorizeParams Pydantic schema."""

    def test_field_count(self):
        """VectorizeParams should have 23 configurable fields."""
        assert len(VectorizeParams.model_fields) == 23

    def test_default_values(self):
        """Default VectorizeParams should match neroued_vectorizer defaults."""
        p = VectorizeParams()
        assert p.num_colors == 0
        assert p.smoothness == 0.5
        assert p.detail_level == -1.0
        assert p.svg_enable_stroke is True
        assert p.svg_stroke_width == 0.5
        assert p.min_region_area == 50
        assert p.curve_fit_error == 0.8

    def test_valid_params(self):
        """VectorizeParams should accept valid parameter values."""
        p = VectorizeParams(num_colors=16, smoothness=0.8, detail_level=0.5)
        assert p.num_colors == 16
        assert p.smoothness == 0.8
        assert p.detail_level == 0.5

    def test_invalid_num_colors_too_high(self):
        """num_colors > 256 should raise ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            VectorizeParams(num_colors=999)
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("num_colors",) for e in errors)

    def test_invalid_smoothness_above_range(self):
        """smoothness > 1.0 should raise ValidationError."""
        with pytest.raises(ValidationError):
            VectorizeParams(smoothness=1.5)

    def test_invalid_smoothness_below_range(self):
        """smoothness < 0.0 should raise ValidationError."""
        with pytest.raises(ValidationError):
            VectorizeParams(smoothness=-0.1)

    def test_partial_params_use_defaults(self):
        """Providing only some params should use defaults for the rest."""
        p = VectorizeParams(num_colors=32)
        assert p.num_colors == 32
        assert p.smoothness == 0.5  # default
        assert p.detail_level == -1.0  # default


# ---------------------------------------------------------------------------
# VectorizeResponse schema tests
# ---------------------------------------------------------------------------

class TestVectorizeResponse:
    """Tests for VectorizeResponse schema."""

    def test_required_fields(self):
        """VectorizeResponse should accept required fields and set defaults."""
        resp = VectorizeResponse(
            svg_url="/api/files/abc",
            width=800,
            height=600,
            num_shapes=42,
            num_colors=8,
        )
        assert resp.status == "ok"
        assert resp.message == ""
        assert resp.svg_url == "/api/files/abc"
        assert resp.width == 800
        assert resp.height == 600
        assert resp.num_shapes == 42
        assert resp.num_colors == 8
        assert resp.palette == []


# ---------------------------------------------------------------------------
# VectorizeDefaultsResponse schema tests
# ---------------------------------------------------------------------------

class TestVectorizeDefaultsResponse:
    """Tests for VectorizeDefaultsResponse schema."""

    def test_defaults_response(self):
        """VectorizeDefaultsResponse should contain default VectorizeParams."""
        resp = VectorizeDefaultsResponse()
        assert resp.defaults.num_colors == 0
        assert resp.defaults.smoothness == 0.5


# ---------------------------------------------------------------------------
# SVG MIME type mapping tests
# ---------------------------------------------------------------------------

class TestSvgMimeType:
    """Tests for SVG MIME type mapping in _guess_media_type."""

    def test_svg_extension(self):
        """_guess_media_type should return image/svg+xml for .svg files."""
        assert _guess_media_type("output.svg") == "image/svg+xml"

    def test_svg_full_path(self):
        """_guess_media_type should handle full paths with .svg extension."""
        assert _guess_media_type("/tmp/vectorizer/result.svg") == "image/svg+xml"

    def test_png_unchanged(self):
        """Existing MIME types should not be affected."""
        assert _guess_media_type("image.png") == "image/png"

    def test_glb_unchanged(self):
        assert _guess_media_type("model.glb") == "model/gltf-binary"


# ---------------------------------------------------------------------------
# Helpers: build a fake neroued_vectorizer module for sys.modules patching
# ---------------------------------------------------------------------------

def _make_mock_nv(svg_content="<svg></svg>", width=800, height=600,
                  num_shapes=10, resolved_num_colors=4,
                  palette_rgb=None):
    """Create a mock neroued_vectorizer module with configurable results.
    创建可配置结果的 mock neroued_vectorizer 模块。
    """
    if palette_rgb is None:
        palette_rgb = [(255, 0, 0)]

    mock_nv = MagicMock()
    mock_nv.VectorizerConfig.return_value = MagicMock()

    palette_objs = []
    for rgb in palette_rgb:
        obj = MagicMock()
        obj.to_rgb255.return_value = rgb
        palette_objs.append(obj)

    result = MagicMock()
    result.svg_content = svg_content
    result.width = width
    result.height = height
    result.num_shapes = num_shapes
    result.resolved_num_colors = resolved_num_colors
    result.palette = palette_objs
    mock_nv.vectorize.return_value = result
    return mock_nv


def _create_temp_input(content: bytes = b"fake image data") -> str:
    """Create a temporary input file and return its path.
    创建临时输入文件并返回路径。
    """
    fd, path = tempfile.mkstemp(suffix=".png")
    os.write(fd, content)
    os.close(fd)
    return path


# ---------------------------------------------------------------------------
# worker_vectorize tests
# ---------------------------------------------------------------------------

class TestWorkerVectorize:
    """Tests for worker_vectorize function."""

    def test_returns_expected_keys(self):
        """worker_vectorize should return dict with expected keys."""
        mock_nv = _make_mock_nv()
        input_path = _create_temp_input()

        # Patch sys.modules so the lazy import inside worker_vectorize
        # picks up our mock instead of the real C++ library.
        with patch.dict(sys.modules, {"neroued_vectorizer": mock_nv}):
            # Re-import to ensure the patched module is used
            from api.workers.vectorizer_workers import worker_vectorize
            result = worker_vectorize(input_path, {"num_colors": 8})

        assert "svg_path" in result
        assert "width" in result
        assert "height" in result
        assert "num_shapes" in result
        assert "num_colors" in result
        assert "palette" in result
        assert result["width"] == 800
        assert result["height"] == 600
        assert result["num_shapes"] == 10
        assert result["num_colors"] == 4
        assert result["palette"] == ["#ff0000"]

        # Verify SVG was written
        assert os.path.exists(result["svg_path"])
        with open(result["svg_path"]) as f:
            assert f.read() == '<svg data-lumina-origin="image-vectorizer"></svg>'

        # Clean up SVG output
        os.unlink(result["svg_path"])

    def test_cleans_up_input_file(self):
        """worker_vectorize should delete the input temp file after processing."""
        mock_nv = _make_mock_nv(num_shapes=1, resolved_num_colors=1, palette_rgb=[])
        input_path = _create_temp_input()
        assert os.path.exists(input_path)

        with patch.dict(sys.modules, {"neroued_vectorizer": mock_nv}):
            from api.workers.vectorizer_workers import worker_vectorize
            result = worker_vectorize(input_path, {})

        assert not os.path.exists(input_path)

        # Clean up SVG output
        os.unlink(result["svg_path"])

    def test_cleans_up_on_failure(self):
        """worker_vectorize should clean up input file even on failure."""
        mock_nv = MagicMock()
        mock_nv.VectorizerConfig.return_value = MagicMock()
        mock_nv.vectorize.side_effect = RuntimeError("vectorization failed")

        input_path = _create_temp_input()
        assert os.path.exists(input_path)

        with patch.dict(sys.modules, {"neroued_vectorizer": mock_nv}):
            from api.workers.vectorizer_workers import worker_vectorize
            with pytest.raises(RuntimeError, match="vectorization failed"):
                worker_vectorize(input_path, {})

        # Input file should still be cleaned up
        assert not os.path.exists(input_path)
