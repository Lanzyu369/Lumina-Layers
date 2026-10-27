"""ABI-level result schema and NumPy lifetime contracts."""

from __future__ import annotations

import gc
from pathlib import Path

import numpy as np
import pytest

import lumina_svg_core


FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_result_buffers_are_typed_read_only_and_keep_owner_alive() -> None:
    result = lumina_svg_core.analyze_svg(
        FIXTURES / "basic_fill_stroke.svg",
        target_width_mm=20.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.schema_version == 4
    visible = result.visible
    coordinates = visible.coordinates
    ring_offsets = visible.ring_offsets
    polygon_offsets = visible.polygon_offsets
    geometry_offsets = visible.geometry_offsets
    rgba = visible.rgba
    rgba_f64 = visible.rgba_f64
    draw_indices = visible.draw_indices
    source_indices = visible.source_indices
    source_kinds = visible.source_kinds
    hole_parent = visible.hole_parent
    contributor_offsets = visible.contributor_offsets
    contributor_draw_indices = visible.contributor_draw_indices
    contributor_source_indices = visible.contributor_source_indices
    contributor_source_kinds = visible.contributor_source_kinds
    contributor_weights = visible.contributor_weights

    del visible
    del result
    gc.collect()

    assert coordinates.dtype == np.dtype(np.int64)
    assert ring_offsets.dtype == np.dtype(np.uint64)
    assert polygon_offsets.dtype == np.dtype(np.uint64)
    assert geometry_offsets.dtype == np.dtype(np.uint64)
    assert rgba.dtype == np.dtype(np.uint8)
    assert rgba_f64.dtype == np.dtype(np.float64)
    assert draw_indices.dtype == np.dtype(np.int32)
    assert source_indices.dtype == np.dtype(np.int32)
    assert source_kinds.dtype == np.dtype(np.int32)
    assert hole_parent.dtype == np.dtype(np.int64)
    assert contributor_offsets.dtype == np.dtype(np.uint64)
    assert contributor_draw_indices.dtype == np.dtype(np.int32)
    assert contributor_source_indices.dtype == np.dtype(np.int32)
    assert contributor_source_kinds.dtype == np.dtype(np.int32)
    assert contributor_weights.dtype == np.dtype(np.float64)

    for array in (
        coordinates,
        ring_offsets,
        polygon_offsets,
        geometry_offsets,
        rgba,
        rgba_f64,
        draw_indices,
        source_indices,
        source_kinds,
        hole_parent,
        contributor_offsets,
        contributor_draw_indices,
        contributor_source_indices,
        contributor_source_kinds,
        contributor_weights,
    ):
        assert not array.flags.writeable

    assert coordinates.ndim == 2
    assert coordinates.shape[1] == 2
    assert ring_offsets[0] == 0
    assert ring_offsets[-1] == len(coordinates)
    assert polygon_offsets[0] == 0
    assert polygon_offsets[-1] == len(ring_offsets) - 1
    assert geometry_offsets[0] == 0
    assert geometry_offsets[-1] == len(polygon_offsets) - 1
    for start, end in zip(ring_offsets[:-1], ring_offsets[1:], strict=True):
        assert np.array_equal(coordinates[start], coordinates[end - 1])
    assert rgba_f64.shape == (2, 4)
    assert contributor_offsets.tolist() == [0, 1, 2]
    assert contributor_draw_indices.tolist() == [0, 1]
    assert contributor_source_indices.tolist() == [2, 2]
    assert contributor_source_kinds.tolist() == [0, 1]
    assert contributor_weights.tolist() == pytest.approx([1.0, 1.0])


def test_supported_result_exposes_non_overlapping_stage_timings() -> None:
    result = lumina_svg_core.analyze_svg(
        FIXTURES / "basic_fill_stroke.svg",
        target_width_mm=20.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.recorder_seconds > 0
    assert result.kernel_seconds > 0
    assert result.result_conversion_seconds >= 0


def test_supported_result_preserves_paint_identity_census() -> None:
    result = lumina_svg_core.analyze_svg(
        FIXTURES / "basic_fill_stroke.svg",
        target_width_mm=20.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.raw.geometry_count == result.visible.geometry_count == 2
    for collection in (result.raw, result.visible):
        assert collection.rgba.tolist() == [
            [255, 0, 0, 255],
            [0, 0, 255, 255],
        ]
        assert collection.draw_indices.tolist() == [0, 1]
        assert collection.source_indices.tolist() == [2, 2]
        assert collection.source_kinds.tolist() == [0, 1]
        np.testing.assert_allclose(
            collection.rgba_f64,
            np.asarray(
                [
                    [1.0, 0.0, 0.0, 1.0],
                    [0.0, 0.0, 1.0, 1.0],
                ]
            ),
            rtol=0,
            atol=0,
        )
        assert collection.contributor_offsets.tolist() == [0, 1, 2]
        assert collection.contributor_draw_indices.tolist() == [0, 1]
        assert collection.contributor_source_indices.tolist() == [2, 2]
        assert collection.contributor_source_kinds.tolist() == [0, 1]
        assert collection.contributor_weights.tolist() == pytest.approx(
            [1.0, 1.0]
        )

    assert result.silhouette.geometry_count == 1
    assert result.silhouette.component_count == 1
    assert result.silhouette.rgba.tolist() == [[0, 0, 0, 255]]
    np.testing.assert_allclose(
        result.silhouette.rgba_f64,
        np.asarray([[0.0, 0.0, 0.0, 1.0]]),
        rtol=0,
        atol=0,
    )
    assert result.silhouette.source_kinds.tolist() == [2]
    assert result.silhouette.contributor_offsets.tolist() == [0, 0]
    assert result.silhouette.contributor_draw_indices.tolist() == []
    assert result.silhouette.contributor_weights.tolist() == []


def test_non_area_fragments_are_reported_outside_polygon_collections() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 100 100'>"
        "<rect x='10' y='10' width='80' height='80' fill='#102030'/>"
        "<path d='M20 20' fill='#405060'/>"
        "<path d='M30 30L40 40L50 50Z' fill='#708090'/>"
        "</svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.schema_version == 4
    assert result.input_paint_count == 3
    assert result.raw.geometry_count == 1
    assert result.visible.geometry_count == 1
    assert result.raw.geometry_offsets.tolist() == [0, 1]
    assert result.visible.geometry_offsets.tolist() == [0, 1]

    fragments = result.unprintable_fragments
    assert fragments.count == 2
    assert fragments.reason_codes == ("point_only", "line_only")
    assert fragments.rgba.tolist() == [
        [64, 80, 96, 255],
        [112, 128, 144, 255],
    ]
    np.testing.assert_allclose(
        fragments.rgba_f64,
        np.asarray(
            [
                [64 / 255, 80 / 255, 96 / 255, 1.0],
                [112 / 255, 128 / 255, 144 / 255, 1.0],
            ]
        ),
        rtol=0,
        atol=1e-15,
    )
    assert fragments.draw_indices.tolist() == [1, 2]
    assert fragments.source_indices.tolist() == [2, 3]
    assert fragments.source_kinds.tolist() == [0, 0]
    assert fragments.subpath_indices.tolist() == [0, 0]


def test_bad_subpath_does_not_remove_valid_component_or_hole() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 100 100'>"
        "<path fill='#123456' fill-rule='evenodd' d='"
        "M10 10H90V90H10Z M30 30H70V70H30Z "
        "M2 2L3 3L4 4Z'/></svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.input_paint_count == 1
    assert result.raw.geometry_count == 1
    assert result.raw.component_count == 1
    assert result.raw.hole_count == 1
    assert result.visible.component_count == 1
    assert result.visible.hole_count == 1
    assert result.unprintable_fragments.count == 1
    assert result.unprintable_fragments.reason_codes == ("line_only",)
    assert result.unprintable_fragments.subpath_indices.tolist() == [2]


def test_exact_small_area_is_not_reclassified_as_unprintable() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 100000000 10'>"
        "<rect width='100000000' height='10' fill='#f00'/>"
        "<path d='M99999990 0L99999991 0L99999990 1Z' fill='#00f'/>"
        "</svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.input_paint_count == 2
    assert result.raw.geometry_count == 2
    assert result.raw.rgba.tolist() == [
        [255, 0, 0, 255],
        [0, 0, 255, 255],
    ]
    assert result.raw.component_count == 2
    assert result.unprintable_fragments.count == 0


def test_document_with_only_non_area_fragments_is_a_successful_empty_parse() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 10 10'>"
        "<path d='M1 1L2 2L3 3Z' fill='#abcdef'/>"
        "</svg>",
        target_width_mm=10.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.reason_code == ""
    assert result.input_paint_count == 1
    assert result.raw.geometry_count == 0
    assert result.visible.geometry_count == 0
    assert result.silhouette.geometry_count == 0
    assert result.unprintable_fragments.reason_codes == ("line_only",)
    assert result.unprintable_fragments.rgba.tolist() == [
        [171, 205, 239, 255]
    ]


def test_empty_path_is_reported_without_affecting_valid_paint() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 10 10'>"
        "<rect width='5' height='5' fill='#112233'/>"
        "<path d='' fill='#445566'/>"
        "</svg>",
        target_width_mm=10.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.input_paint_count == 2
    assert result.raw.geometry_count == 1
    assert result.unprintable_fragments.reason_codes == ("empty_path",)
    assert result.unprintable_fragments.rgba.tolist() == [
        [68, 85, 102, 255]
    ]


def test_empty_stroke_path_preserves_paint_identity_in_diagnostics() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 10 10'>"
        "<rect width='5' height='5' fill='#112233'/>"
        "<path d='' fill='none' stroke='#778899' stroke-width='2'/>"
        "</svg>",
        target_width_mm=10.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.input_paint_count == 2
    assert result.raw.geometry_count == 1
    assert result.unprintable_fragments.reason_codes == ("empty_path",)
    assert result.unprintable_fragments.rgba.tolist() == [
        [119, 136, 153, 255]
    ]
    assert result.unprintable_fragments.source_kinds.tolist() == [1]


def test_fully_clipped_paint_does_not_fail_other_components() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 10 10'>"
        "<defs><clipPath id='clip'><rect width='1' height='1'/></clipPath>"
        "</defs>"
        "<rect width='2' height='2' fill='#ff0000'/>"
        "<rect x='5' y='5' width='2' height='2' fill='#0000ff' "
        "clip-path='url(#clip)'/>"
        "</svg>",
        target_width_mm=10.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.input_paint_count == 2
    assert result.raw.geometry_count == 1
    assert result.raw.rgba.tolist() == [[255, 0, 0, 255]]
    assert result.unprintable_fragments.reason_codes == ("clipped_out",)
    assert result.unprintable_fragments.rgba.tolist() == [
        [0, 0, 255, 255]
    ]


def test_document_with_only_fully_clipped_paint_is_a_successful_empty_parse() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 10 10'>"
        "<defs><clipPath id='clip'><rect width='1' height='1'/></clipPath>"
        "</defs>"
        "<rect x='5' y='5' width='2' height='2' fill='#0000ff' "
        "clip-path='url(#clip)'/>"
        "</svg>",
        target_width_mm=10.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.input_paint_count == 1
    assert result.raw.geometry_count == 0
    assert result.visible.geometry_count == 0
    assert result.silhouette.geometry_count == 0
    assert result.unprintable_fragments.reason_codes == ("clipped_out",)


def test_unsupported_result_has_canonical_empty_collections() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 10 10'><text>x</text></svg>",
        target_width_mm=20.0,
        tolerance_mm=0.02,
    )

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_text"
    for collection in (result.raw, result.visible, result.silhouette):
        assert collection.coordinates.shape == (0, 2)
        assert collection.ring_offsets.tolist() == [0]
        assert collection.polygon_offsets.tolist() == [0]
        assert collection.geometry_offsets.tolist() == [0]
        assert collection.geometry_count == 0
        assert collection.component_count == 0
        assert collection.hole_count == 0


@pytest.mark.parametrize(
    ("target_width_mm", "tolerance_mm"),
    [(0.0, 0.02), (-1.0, 0.02), (20.0, 0.0), (20.0, float("nan"))],
)
def test_invalid_physical_parameters_fail_deterministically(
    target_width_mm: float,
    tolerance_mm: float,
) -> None:
    result = lumina_svg_core.analyze_svg(
        FIXTURES / "basic_fill_stroke.svg",
        target_width_mm=target_width_mm,
        tolerance_mm=tolerance_mm,
    )

    assert result.status == "invalid"
    assert result.reason_code == "invalid_physical_parameters"
    assert result.visible.geometry_count == 0

def test_parser_api_does_not_expose_print_precision_contour_closing() -> None:
    with pytest.raises(TypeError):
        lumina_svg_core.analyze_svg(
            FIXTURES / "basic_fill_stroke.svg",
            target_width_mm=20.0,
            tolerance_mm=0.02,
            contour_close_delta_source_units=0.03,
        )
