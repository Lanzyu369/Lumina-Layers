"""Property-Based tests for the Vectorizer feature.
Vectorizer 功能的 Property-Based 测试。

Uses Hypothesis to verify universal properties across all valid inputs.
使用 Hypothesis 验证跨所有有效输入的通用属性。
"""

import os
import sys
import tempfile
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st
from pydantic import ValidationError

from api.schemas.vectorizer import VectorizeParams
from api.file_bridge import _guess_media_type


# ---------------------------------------------------------------------------
# Field metadata derived from the actual VectorizeParams schema
# ---------------------------------------------------------------------------

# Map of field_name -> (type, default, ge, le) for fields with BOTH ge and le
CONSTRAINED_FIELDS: dict[str, tuple[str, float, float, float]] = {
    "num_colors":              ("int",   0,       0,      256),
    "smoothness":              ("float", 0.5,     0.0,    1.0),
    "detail_level":            ("float", -1.0,    -1.0,   1.0),
    "svg_stroke_width":        ("float", 0.5,     0.0,    20.0),
    "thin_line_max_radius":    ("float", 2.5,     0.5,    10.0),
    "min_coverage_ratio":      ("float", 0.998,   0.0,    1.0),
    "smoothing_spatial":       ("float", 15.0,    0.0,    50.0),
    "smoothing_color":         ("float", 25.0,    0.0,    80.0),
    "max_working_pixels":      ("int",   3000000, 100000, 100000000),
    "slic_region_size":        ("int",   20,      5,      100),
    "edge_sensitivity":        ("float", 0.8,     0.0,    1.0),
    "refine_passes":           ("int",   6,       0,      20),
    "aa_tolerance":            ("float", 10.0,    1.0,    50.0),
    "curve_fit_error":         ("float", 0.8,     0.1,    5.0),
    "contour_simplify":        ("float", 0.45,    0.0,    2.0),
    "merge_segment_tolerance": ("float", 0.05,    0.0,    0.5),
    "min_region_area":         ("int",   50,      0,      1000000),
    "max_merge_color_dist":    ("float", 200.0,   0.0,    2000.0),
    "min_contour_area":        ("float", 10.0,    0.0,    1000000.0),
    "min_hole_area":           ("float", 4.0,     0.0,    100000.0),
}

# Snapshot of all defaults from a fresh VectorizeParams instance
ALL_DEFAULTS: dict = VectorizeParams().model_dump()


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

field_subset_st = st.lists(
    st.sampled_from(sorted(ALL_DEFAULTS.keys())),
    min_size=0,
    max_size=len(ALL_DEFAULTS),
    unique=True,
)



# =========================================================================
# Property 1: Schema 参数默认值完整性
# =========================================================================


class TestProperty1DefaultCompleteness:
    """Feature: vectorizer-tab, Property 1: Schema 参数默认值完整性"""

    @given(subset=field_subset_st)
    @settings(max_examples=100)
    def test_unprovided_fields_equal_defaults(self, subset: list[str]) -> None:
        """For any subset of fields provided, unprovided fields equal defaults.
        对于任意提供的字段子集，未提供的字段应等于其默认值。

        **Validates: Requirements 2.2**
        """
        # Build kwargs using each field's known default (always valid)
        kwargs: dict = {}
        for name in subset:
            kwargs[name] = ALL_DEFAULTS[name]

        params = VectorizeParams(**kwargs)
        result = params.model_dump()

        for name, default_value in ALL_DEFAULTS.items():
            if name not in subset:
                assert result[name] == default_value, (
                    f"Field '{name}' should be {default_value!r}, got {result[name]!r}"
                )


# =========================================================================
# Property 2: Schema 参数范围验证
# =========================================================================


class TestProperty2RangeValidation:
    """Feature: vectorizer-tab, Property 2: Schema 参数范围验证"""

    @given(
        field_name=st.sampled_from(sorted(CONSTRAINED_FIELDS.keys())),
        data=st.data(),
    )
    @settings(max_examples=100)
    def test_out_of_range_raises_validation_error(
        self, field_name: str, data: st.DataObject
    ) -> None:
        """Out-of-range values must trigger ValidationError naming the field.
        超出范围的值必须触发包含字段名的 ValidationError。

        **Validates: Requirements 2.3**
        """
        typ, _default, lo, hi = CONSTRAINED_FIELDS[field_name]

        if typ == "int":
            lo_int, hi_int = int(lo), int(hi)
            out_value = data.draw(
                st.one_of(
                    st.integers(max_value=lo_int - 1),
                    st.integers(min_value=hi_int + 1),
                )
            )
        else:
            # For float fields, generate values clearly outside the range
            out_value = data.draw(
                st.one_of(
                    st.floats(
                        max_value=lo - 0.01,
                        allow_nan=False,
                        allow_infinity=False,
                    ),
                    st.floats(
                        min_value=hi + 0.01,
                        allow_nan=False,
                        allow_infinity=False,
                    ),
                )
            )

        with pytest.raises(ValidationError) as exc_info:
            VectorizeParams(**{field_name: out_value})

        error_fields = [
            e["loc"][0] for e in exc_info.value.errors() if e.get("loc")
        ]
        assert field_name in error_fields, (
            f"ValidationError should mention '{field_name}', got {error_fields}"
        )


# =========================================================================
# Property 3: Worker 临时文件清理
# =========================================================================


def _make_mock_nv(*, success: bool = True) -> MagicMock:
    """Build a mock ``neroued_vectorizer`` module.
    构建 mock ``neroued_vectorizer`` 模块。
    """
    mock_nv = MagicMock()
    mock_nv.VectorizerConfig.return_value = MagicMock()

    if success:
        result = MagicMock()
        result.svg_content = "<svg></svg>"
        result.width = 100
        result.height = 100
        result.num_shapes = 1
        result.resolved_num_colors = 1
        result.palette = []
        mock_nv.vectorize.return_value = result
    else:
        mock_nv.vectorize.side_effect = RuntimeError("mock failure")

    return mock_nv


class TestProperty3TempFileCleanup:
    """Feature: vectorizer-tab, Property 3: Worker 临时文件清理"""

    @given(content=st.binary(min_size=1, max_size=1024))
    @settings(max_examples=100)
    def test_input_file_cleaned_on_success(self, content: bytes) -> None:
        """Input temp file must not exist after successful vectorization.
        成功矢量化后输入临时文件不应存在。

        **Validates: Requirements 1.5**
        """
        fd, input_path = tempfile.mkstemp(suffix=".png")
        os.write(fd, content)
        os.close(fd)

        mock_nv = _make_mock_nv(success=True)
        with patch.dict(sys.modules, {"neroued_vectorizer": mock_nv}):
            from api.workers.vectorizer_workers import worker_vectorize

            result = worker_vectorize(input_path, {})

        assert not os.path.exists(input_path), "Input file should be deleted on success"

        # Clean up generated SVG
        if os.path.exists(result["svg_path"]):
            os.unlink(result["svg_path"])

    @given(content=st.binary(min_size=1, max_size=1024))
    @settings(max_examples=100)
    def test_input_file_cleaned_on_failure(self, content: bytes) -> None:
        """Input temp file must not exist after failed vectorization.
        失败矢量化后输入临时文件不应存在。

        **Validates: Requirements 1.5**
        """
        fd, input_path = tempfile.mkstemp(suffix=".png")
        os.write(fd, content)
        os.close(fd)

        mock_nv = _make_mock_nv(success=False)
        with patch.dict(sys.modules, {"neroued_vectorizer": mock_nv}):
            from api.workers.vectorizer_workers import worker_vectorize

            with pytest.raises(RuntimeError):
                worker_vectorize(input_path, {})

        assert not os.path.exists(input_path), "Input file should be deleted on failure"


# =========================================================================
# Property 9: SVG MIME 类型映射
# =========================================================================


class TestProperty9SvgMimeType:
    """Feature: vectorizer-tab, Property 9: SVG MIME 类型映射"""

    @given(
        prefix=st.text(
            alphabet=st.characters(
                whitelist_categories=("L", "N"),
                whitelist_characters="/_-",
            ),
            min_size=0,
            max_size=50,
        ),
        stem=st.text(
            alphabet=st.characters(
                whitelist_categories=("L", "N"),
                whitelist_characters="_-",
            ),
            min_size=1,
            max_size=20,
        ),
    )
    @settings(max_examples=100)
    def test_svg_extension_always_returns_svg_mime(self, prefix: str, stem: str) -> None:
        """Any path ending in .svg must map to image/svg+xml.
        任何以 .svg 结尾的路径必须映射为 image/svg+xml。

        The stem (filename without extension) must contain at least one
        character so that ``os.path.splitext`` correctly identifies the
        ``.svg`` extension.  A bare ``/.svg`` is treated by Python as a
        hidden file with no extension, which is not a realistic file path.

        **Validates: Requirements 4.3**
        """
        path = f"{prefix}{stem}.svg"
        assert _guess_media_type(path) == "image/svg+xml"
