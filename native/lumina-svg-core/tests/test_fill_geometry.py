"""Physical error allocation and fill topology tests."""

from __future__ import annotations

from pathlib import Path
from time import perf_counter

import numpy as np
import pytest

import lumina_svg_core


FIXTURES = Path(__file__).resolve().parent / "fixtures"


def geometry_area(result, collection, geometry_index: int) -> float:
    polygon_start = collection.geometry_offsets[geometry_index]
    polygon_end = collection.geometry_offsets[geometry_index + 1]
    area = 0.0
    for polygon_index in range(polygon_start, polygon_end):
        ring_start = collection.polygon_offsets[polygon_index]
        ring_end = collection.polygon_offsets[polygon_index + 1]
        for ring_index in range(ring_start, ring_end):
            point_start = collection.ring_offsets[ring_index]
            point_end = collection.ring_offsets[ring_index + 1]
            ring = (
                collection.coordinates[point_start:point_end].astype(
                    np.float64
                )
                * result.grid_to_source_unit
            )
            area += 0.5 * np.sum(
                ring[:-1, 0] * ring[1:, 1]
                - ring[1:, 0] * ring[:-1, 1]
            )
    return abs(area)


def _normalized_coordinate_bounds(result):
    coordinates = (
        np.asarray(result.raw.coordinates, dtype=np.float64)
        * result.grid_to_source_unit
    )
    return (
        float(coordinates[:, 0].min()),
        float(coordinates[:, 1].min()),
        float(coordinates[:, 0].max()),
        float(coordinates[:, 1].max()),
    )


def _assert_same_geometry(left, right) -> None:
    assert left.status == right.status == "supported"
    assert left.bbox == pytest.approx(right.bbox, abs=1e-12)
    assert left.scale_factor == pytest.approx(right.scale_factor, abs=1e-12)
    for name in ("raw", "visible", "silhouette"):
        left_collection = getattr(left, name)
        right_collection = getattr(right, name)
        np.testing.assert_array_equal(
            left_collection.coordinates,
            right_collection.coordinates,
        )
        np.testing.assert_array_equal(
            left_collection.ring_offsets,
            right_collection.ring_offsets,
        )
        np.testing.assert_array_equal(
            left_collection.polygon_offsets,
            right_collection.polygon_offsets,
        )
        np.testing.assert_array_equal(
            left_collection.geometry_offsets,
            right_collection.geometry_offsets,
        )


@pytest.mark.parametrize(
    ("quadratic_path", "cubic_path"),
    [
        (
            "M0 0Q3 6 6 0L6 6H0Z",
            "M0 0C2 4 4 4 6 0L6 6H0Z",
        ),
        (
            "M12 10q3 6 6 0l0 6h-6z",
            "M12 10c2 4 4 4 6 0l0 6h-6z",
        ),
    ],
)
def test_quadratic_degree_elevation_matches_exact_cubic_geometry(
    quadratic_path: str,
    cubic_path: str,
) -> None:
    def analyze(path_data: str):
        return lumina_svg_core.analyze_svg_svg(
            "<svg viewBox='0 0 24 24'>"
            "<path transform='matrix(1.25 .2 -.3 .75 4 -3)' "
            f"d='{path_data}'/></svg>",
            target_width_mm=100.0,
            tolerance_mm=0.02,
        )

    _assert_same_geometry(analyze(quadratic_path), analyze(cubic_path))


def test_path_arc_stays_inside_total_physical_error_budget() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 10 10'>"
        "<path d='M1 5A4 4 0 0 1 9 5L1 5Z'/></svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    coordinates = (
        np.asarray(result.raw.coordinates, dtype=np.float64)
        * result.grid_to_source_unit
    )
    points = coordinates[:-1]
    endpoints = np.roll(points, -1, axis=0)
    segment_lengths = np.linalg.norm(endpoints - points, axis=1)
    curved = segment_lengths < 1.0
    midpoints = (points[curved] + endpoints[curved]) * 0.5
    radial_errors = np.abs(
        np.linalg.norm(midpoints - np.asarray([5.0, 5.0]), axis=1) - 4.0
    )
    assert float(radial_errors.max()) * result.scale_factor <= 0.02


@pytest.mark.parametrize("origin", [1000000.0, -1000000.0])
def test_nonzero_root_viewbox_uses_the_recorded_coordinate_domain(
    origin: float,
) -> None:
    result = lumina_svg_core.analyze_svg_svg(
        f"<svg viewBox='{origin:g} 0 10 10'>"
        f"<rect x='{origin:g}' width='10' height='10'/></svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.bbox == pytest.approx((0.0, 0.0, 10.0, 10.0), abs=1e-9)
    assert result.scale_factor == pytest.approx(10.0, abs=1e-9)
    assert _normalized_coordinate_bounds(result) == pytest.approx(
        (0.0, 0.0, 10.0, 10.0), abs=1e-8
    )


def test_circle_primitive_stays_inside_total_physical_error_budget() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 200 200'>"
        "<circle cx='100' cy='100' r='100'/></svg>",
        target_width_mm=200.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    coordinates = (
        np.asarray(result.raw.coordinates[:-1], dtype=np.float64)
        * result.grid_to_source_unit
    )
    radial_error = np.abs(
        np.linalg.norm(coordinates - np.asarray([100.0, 100.0]), axis=1)
        - 100.0
    )
    assert float(radial_error.max()) * result.scale_factor <= 0.02


def test_extreme_arc_rotation_matches_modulo_full_turns() -> None:
    def analyze(rotation_degrees: str):
        return lumina_svg_core.analyze_svg_svg(
            "<svg viewBox='0 0 10 10'>"
            "<path d='M0 0A1000000000 1 "
            f"{rotation_degrees} 0 1 1 0L1 1H0Z'/></svg>",
            target_width_mm=100.0,
            tolerance_mm=0.02,
        )

    huge_rotation = analyze("1000000000")
    reduced_rotation = analyze("280")

    _assert_same_geometry(huge_rotation, reduced_rotation)
    assert huge_rotation.raw.geometry_count == 1
    assert geometry_area(huge_rotation, huge_rotation.raw, 0) > 0.0


def test_near_closed_large_arc_preserves_the_almost_complete_disk() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 100 100'>"
        "<path d='M50.00013 50.00013 "
        "A40 40 0 1 1 50.00213 50.00014 Z' fill='black'/>"
        "</svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.raw.geometry_count == 1
    assert geometry_area(result, result.raw, 0) == pytest.approx(
        5026.548245743669,
        abs=1.0,
    )


def test_high_eccentricity_arc_keeps_its_nonzero_area_for_downstream() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 100 100'>"
        "<path d='M50.1428117305 49.5646840912 "
        "A4.8162023429 0.0000001239 108.1628465385 0 1 "
        "51.1496945796 46.4955265175 Z'/></svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.raw.geometry_count == 1
    assert result.raw.component_count == 1
    assert result.unprintable_fragments.count == 0
    assert geometry_area(result, result.raw, 0) > 0.0


def test_large_source_coordinates_keep_area_after_exact_transform() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 100 100'>"
        "<rect x='0' y='50' width='1' height='1' fill='red'/>"
        "<path d='M0 999999975 L100 999999975 "
        "L100 1000000025 L0 1000000025 Z' "
        "transform='translate(0 -999999975)' fill='blue'/></svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.raw.geometry_count == 2
    assert result.raw.rgba.tolist() == [
        [255, 0, 0, 255],
        [0, 0, 255, 255],
    ]
    assert geometry_area(result, result.raw, 1) == pytest.approx(5000.0)
    assert result.unprintable_fragments.count == 0


def test_occlusion_uses_exact_path_endpoint_topology() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 100 100'>"
        "<rect x='0' y='0' width='100' height='50' fill='red'/>"
        "<path transform='translate(0 -500)' "
        "d='M0 499.99999 L100 500.00009 L100 550 L0 550 Z' "
        "fill='blue'/></svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.reason_code == ""
    assert result.raw.geometry_count == 2
    assert result.visible.geometry_count == 2
    assert result.silhouette.component_count == 1
    assert result.unprintable_fragments.count == 0


def test_visible_export_keeps_valid_paint_when_clip_ring_is_redundant() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 100 100'>"
        "<rect width='100' height='100' fill='#010203'/>"
        "<path fill='#eddedb' fill-rule='evenodd' "
        "d='M5 5H95V95H5Z M30 30L20 33L10 60L50 60Z'/>"
        "<path fill='#a85d67' "
        "d='M30 30Q31 30 29.5 30.5Q25 34 20.5 33.2"
        "Q20 32 20 33L30 30Z'/>"
        "</svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.reason_code == ""
    assert result.raw.draw_indices.tolist() == [0, 1, 2]
    assert result.visible.draw_indices.tolist() == [0, 1, 2]
    assert geometry_area(result, result.visible, 1) > 7000.0
    assert sum(
        geometry_area(result, result.visible, index)
        for index in range(result.visible.geometry_count)
    ) == pytest.approx(
        geometry_area(result, result.silhouette, 0),
        abs=1e-5,
    )
    assert result.unprintable_fragments.count == 0


def test_vectorizer_underpaint_remains_an_ordinary_ordered_svg_paint() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 10 10' data-lumina-origin='image-vectorizer'>"
        "<path fill='#123456' "
        "d='M0 0H10V10H0Z'/>"
        "<path fill='#abcdef' "
        "d='M0 0H4.9V10H0Z M5.1 0H10V10H5.1Z'/>"
        "</svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.image_vectorizer_origin is True
    assert result.raw.rgba.tolist() == [
        [18, 52, 86, 255],
        [171, 205, 239, 255],
    ]
    assert result.raw.draw_indices.tolist() == [0, 1]
    assert result.raw.source_indices.tolist() == [1, 2]
    assert result.visible.rgba.tolist() == result.raw.rgba.tolist()
    assert result.visible.source_indices.tolist() == [1, 2]
    assert geometry_area(result, result.visible, 0) == pytest.approx(
        2.0, abs=1e-5
    )
    assert geometry_area(result, result.visible, 1) == pytest.approx(
        98.0, abs=1e-5
    )


def test_vectorizer_origin_metadata_does_not_fill_an_authored_hole() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 10 10' data-lumina-origin='image-vectorizer'>"
        "<path fill='#123456' "
        "fill-rule='evenodd' d='M0 0H10V10H0Z M4 4H6V6H4Z'/>"
        "</svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.image_vectorizer_origin is True
    assert result.raw.geometry_count == 1
    assert result.raw.component_count == 1
    assert result.raw.hole_count == 1
    assert result.visible.hole_count == 1
    assert geometry_area(result, result.raw, 0) == pytest.approx(96.0, abs=1e-5)


@pytest.mark.parametrize(
    ("axis", "expected_geometry_count", "expected_fragment_reasons"),
    [
        ("X", 1, ()),
        ("Y", 0, ("area_collapse",)),
    ],
)
def test_near_singular_skew_respects_recorded_coordinate_precision(
    axis: str,
    expected_geometry_count: int,
    expected_fragment_reasons: tuple[str, ...],
) -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 100 100'>"
        "<rect x='10' y='0' width='1' height='.00001' "
        f"transform='skew{axis}(89.99999)' fill='black'/>"
        "</svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.reason_code == ""
    assert result.raw.geometry_count == expected_geometry_count
    assert (
        result.unprintable_fragments.reason_codes
        == expected_fragment_reasons
    )


def test_hierarchy_collapse_does_not_hide_an_independent_valid_paint() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 100 100'>"
        "<rect x='10' y='0' width='1' height='.00001' "
        "transform='skewY(89.99999)' fill='#123456'/>"
        "<rect x='20' y='20' width='10' height='10' fill='#abcdef'/>"
        "</svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.reason_code == ""
    assert result.raw.geometry_count == 1
    assert result.raw.rgba.tolist() == [[171, 205, 239, 255]]
    assert result.unprintable_fragments.reason_codes == ("area_collapse",)
    assert result.unprintable_fragments.rgba.tolist() == [
        [18, 52, 86, 255]
    ]


def test_document_viewport_remains_part_of_lumina_bbox_contract() -> None:
    result = lumina_svg_core.analyze_svg(
        FIXTURES / "basic_fill_stroke.svg", 20.0, 0.02
    )

    assert result.status == "supported"
    assert result.bbox == pytest.approx((0.0, 0.0, 20.0, 10.0), abs=1e-6)
    assert result.scale_factor == pytest.approx(1.0)


def test_parser_preserves_narrow_hole_and_notch_without_morphology() -> None:
    rectangle = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 100 100'>"
        "<path fill='red' d='M10 10H90V90H10Z'/></svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )
    narrow_hole = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 100 100'>"
        "<path fill='red' fill-rule='evenodd' "
        "d='M10 10H90V90H10Z M49.98 20H50.02V80H49.98Z'/>"
        "</svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )
    narrow_notch = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 100 100'>"
        "<path fill='red' "
        "d='M10 10H90V90H50.02V20H49.98V90H10Z'/></svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert rectangle.status == narrow_hole.status == narrow_notch.status == (
        "supported"
    )
    assert rectangle.raw.component_count == 1
    assert rectangle.raw.hole_count == 0
    assert narrow_hole.raw.hole_count == 1
    assert narrow_notch.raw.hole_count == 0


def test_parser_keeps_miter_limit_boundary_shape() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 100 100'>"
        "<path d='M0 0L10 0L5 8.660254Z'/></svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.raw.geometry_count == 1
    assert result.raw.component_count == 1


def test_spacious_concave_ring_is_deterministic() -> None:
    svg = (
        "<svg viewBox='0 0 100 100'>"
        "<path d='M0 0H100V100H60V60H40V100H0Z'/></svg>"
    )
    result = lumina_svg_core.analyze_svg_svg(
        svg,
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )
    unclosed = lumina_svg_core.analyze_svg_svg(
        svg,
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    _assert_same_geometry(result, unclosed)


def test_slanted_micro_notch_remains_valid() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 100 100'><path fill='red' d='"
        "M10 10 L90 10 L90 90 L39.83308898930126 90 "
        "L39.79082728731835 82.16007974157606 "
        "L39.69503373258287 90 L10 90 Z'/></svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.raw.geometry_count == 1
    assert result.raw.component_count == 1


def test_parser_preserves_every_disconnected_component() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 100 100'><path fill='red' d='"
        "M55.52831753041504 66.3046688201546 "
        "L55.52831753041504 72.93040052353409 "
        "L47.339743941791944 73.63466187069454 "
        "L53.28877361479757 75.44200987424085 "
        "L53.2656320529904 75.07386941278561 "
        "L73.09976273935555 73.8270823593993 "
        "L73.43087174116687 79.09442869213571 "
        "L75.37109811756244 74.24712851807058 Z "
        "M33.18047101838028 57.359507658012994 "
        "L28.90746374836685 68.03483355590957 "
        "L44.810623640889176 72.86630118368933 "
        "L44.810623640889176 62.01470293567081 Z'/></svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.raw.component_count == 2


def test_parser_preserves_small_triangular_island() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 100 100'><path fill='red' d='"
        "M0 0H50V50H25V10H24.96V50H0Z "
        "M70 70L72 70L71 72Z'/></svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.raw.component_count == 2


def test_native_core_never_drops_a_subthreshold_paint() -> None:
    svg = (
        "<svg viewBox='0 0 100 100'>"
        "<rect width='50' height='50' fill='red'/>"
        "<rect x='90' y='90' width='.005' height='.005' fill='blue'/>"
        "</svg>"
    )
    result = lumina_svg_core.analyze_svg_svg(
        svg,
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.raw.geometry_count == 2
    assert result.raw.component_count == 2
    assert result.raw.rgba.tolist() == [
        [255, 0, 0, 255],
        [0, 0, 255, 255],
    ]


@pytest.mark.parametrize("width", ["0.099999", "0.100001"])
def test_components_near_the_old_area_cutoff_remain_native(
    width: str,
) -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 100 100'>"
        "<rect width='50' height='50' fill='red'/>"
        f"<rect x='90' y='90' width='{width}' height='{width}' "
        "fill='blue'/></svg>",
        target_width_mm=111.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.raw.geometry_count == 2
    assert result.visible.geometry_count == 2


def test_macro_viewbox_preserves_every_paint_without_area_filter() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 1000000000 1000000000'>"
        "<rect width='500000000' height='500000000' fill='red'/>"
        "<rect x='900000000' y='900000000' width='100000' "
        "height='50000' fill='blue'/></svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.scale_factor == pytest.approx(1.0e-7)
    assert result.raw.geometry_count == 2
    assert tuple(result.raw.rgba[1]) == (0, 0, 255, 255)


@pytest.mark.parametrize("width", ["9980", "10020"])
def test_macro_components_near_the_old_area_cutoff_remain_native(
    width: str,
) -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 1000000000 1000000000'>"
        "<rect width='500000000' height='500000000' fill='red'/>"
        f"<rect x='900000000' y='900000000' width='{width}' "
        f"height='{width}' fill='blue'/></svg>",
        target_width_mm=111.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.raw.geometry_count == 2
    assert result.visible.geometry_count == 2


@pytest.mark.parametrize(
    "degenerate_prefix",
    [
        "M1000000 1000000 ",
        "M1000000 1000000L2000000 2000000 ",
        "M1000000 1000000H2000000Z ",
        "M1000000 1000000L1500000 1500000L2000000 2000000Z ",
    ],
)
def test_non_painting_subpaths_do_not_expand_bbox_or_reduce_scale(
    degenerate_prefix: str,
) -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg xmlns='http://www.w3.org/2000/svg'>"
        f"<path d='{degenerate_prefix}M0 0H10V10H0Z'/>"
        "</svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.bbox == pytest.approx((0.0, 0.0, 10.0, 10.0), abs=1e-6)
    assert result.scale_factor == pytest.approx(10.0)
    assert result.raw.component_count == 1


def test_non_uniform_transform_uses_one_model_space_error_budget() -> None:
    result = lumina_svg_core.analyze_svg(
        FIXTURES / "fill_rules_transforms.svg",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.max_flattening_error_mm == pytest.approx(0.008)
    assert 0 < result.max_quantization_error_mm <= 0.004
    assert result.max_flattening_error_mm + result.max_quantization_error_mm < 0.02
    assert result.scale_factor == pytest.approx(100.0 / result.bbox[2])
    assert result.grid_to_source_unit > 0


@pytest.mark.parametrize(
    "transform",
    [
        "translate(100000000 0) translate(1 0) translate(-100000000 0)",
        "translate(100000000 0) translate(-99999999 0)",
    ],
)
def test_exact_transform_cancellation_preserves_geometry(
    transform: str,
) -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 10 10'>"
        f"<path transform='{transform}' d='M0 0H1V1H0Z' fill='red'/>"
        "</svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.reason_code == ""
    assert result.raw.geometry_count == 1
    assert geometry_area(result, result.raw, 0) == pytest.approx(1.0)


def test_standalone_non_painting_collinear_path_is_ignored() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 10 10'>"
        "<path d='M1 1L2 2L3 3Z' fill='#f00'/>"
        "<rect width='10' height='10' fill='#00f'/>"
        "</svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.raw.geometry_count == 1
    assert result.raw.rgba.tolist() == [[0, 0, 255, 255]]


def test_small_source_triangle_remains_an_area_component(
) -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 100000000 10'>"
        "<rect width='100000000' height='10' fill='#f00'/>"
        "<path d='M99999990 0L99999991 0L99999990 1Z' fill='#00f'/>"
        "</svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.raw.geometry_count == 2
    assert result.raw.component_count == 2
    assert result.raw.rgba.tolist() == [
        [255, 0, 0, 255],
        [0, 0, 255, 255],
    ]
    assert geometry_area(result, result.raw, 1) == pytest.approx(0.5)
    assert result.unprintable_fragments.count == 0


def test_relative_path_cancellation_preserves_exact_area() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 10 10'>"
        "<path d='m100000000 0 m1 0 m-100000000 0 "
        "h1 v1 h-1 z' fill='red'/>"
        "</svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.raw.geometry_count == 1
    assert geometry_area(result, result.raw, 0) == pytest.approx(1.0)
    assert result.unprintable_fragments.reason_codes == (
        "point_only",
        "point_only",
    )


def test_composed_transform_overflow_fails_closed_without_dropping_paint() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 10 10' overflow='visible'>"
        "<rect width='1' height='1' fill='red' "
        "transform='scale(1e20) scale(1e20)'/>"
        "<rect x='5' width='1' height='1' fill='blue'/>"
        "</svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_input_precision"
    assert result.raw.geometry_count == 0


def test_percentage_stroke_overflow_fails_closed_without_dropping_stroke() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 1e20 1e20'>"
        "<rect width='1e20' height='1e20' fill='red'/>"
        "<path d='M0 5e19H1e20' fill='none' stroke='blue' "
        "stroke-width='1%'/>"
        "</svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_input_precision"
    assert result.raw.geometry_count == 0


def test_extreme_cubic_precision_is_rejected_before_expensive_flattening() -> None:
    started = perf_counter()
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 1 20000000000'>"
        "<path d='M0 0C0 20000000000 1 -20000000000 1 0 "
        "L1 20000000000H0Z' fill='red'/>"
        "</svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )
    elapsed = perf_counter() - started

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_input_precision"
    assert result.raw.geometry_count == 0
    assert elapsed < 0.5


@pytest.mark.parametrize("unit_scale", [1e-17, 1.0, 1e17])
def test_cubic_extrema_bbox_is_invariant_across_user_unit_scales(
    unit_scale: float,
) -> None:
    result = lumina_svg_core.analyze_svg_svg(
        f"<svg viewBox='0 0 {unit_scale:g} {unit_scale:g}' "
        "overflow='visible'>"
        f"<path d='M0 0 C {unit_scale:g} 0 {-unit_scale:g} "
        f"{unit_scale:g} 0 {unit_scale:g} L {unit_scale:g} "
        f"{unit_scale:g} L {unit_scale:g} 0 Z' fill='red'/>"
        "</svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    extrema = np.sqrt(3.0) / 6.0
    expected_min_x = -extrema * unit_scale
    expected_width = (1.0 + extrema) * unit_scale
    assert result.status == "supported"
    source_abs_tolerance = abs(unit_scale) * 1e-8
    assert result.bbox[0] == pytest.approx(
        expected_min_x, rel=2e-6, abs=source_abs_tolerance
    )
    assert result.bbox[2] == pytest.approx(
        expected_width, rel=2e-6, abs=source_abs_tolerance
    )
    assert result.scale_factor == pytest.approx(
        100.0 / expected_width, rel=2e-6
    )

    physical_x = (
        np.asarray(result.raw.coordinates, dtype=np.float64)[:, 0]
        * result.grid_to_source_unit
        * result.scale_factor
    )
    assert physical_x.min() >= -0.02
    assert physical_x.max() <= 100.02
    assert physical_x.max() - physical_x.min() == pytest.approx(
        100.0, abs=0.02
    )


def test_evenodd_hole_and_disconnected_shell_survive() -> None:
    result = lumina_svg_core.analyze_svg(
        FIXTURES / "fill_rules_transforms.svg",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    visible = result.visible
    assert visible.geometry_count == 1
    assert visible.component_count == 2
    assert visible.hole_count == 1
    assert np.count_nonzero(visible.hole_parent == -1) == 2
    assert np.count_nonzero(visible.hole_parent >= 0) == 1
    assert visible.polygon_offsets.tolist() == [0, 2, 3]


@pytest.mark.parametrize("hole_width", [0.0001, 0.0002, 0.0003])
def test_precision_grid_preserves_a_small_hole(
    hole_width: float,
) -> None:
    half_width = hole_width / 2.0
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 10 10'>"
        "<path fill-rule='evenodd' "
        f"d='M0 0H10V10H0Z M{5 - half_width:.8f} 4"
        f"H{5 + half_width:.8f}V6H{5 - half_width:.8f}Z'/>"
        "</svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.raw.hole_count == 1
    assert result.visible.hole_count == 1


def test_precision_grid_preserves_a_thin_material_region() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 10 10'>"
        "<rect width='10' height='10' fill='#f00'/>"
        "<rect y='5' width='10' height='0.0001' fill='#00f'/>"
        "</svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.raw.component_count == 2
    assert result.visible.component_count == 3


def test_precision_grid_preserves_a_narrow_gap_between_paints() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 10 10'>"
        "<rect width='4.99995' height='10' fill='#f00'/>"
        "<rect x='5.00005' width='4.99995' height='10' fill='#f00'/>"
        "</svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.silhouette.component_count == 2


def test_precision_grid_preserves_a_narrow_gap_within_one_paint() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 10 10'>"
        "<path fill='#f00' d='M0 0H4.9999V10H0Z "
        "M5.0001 0H10V10H5.0001Z'/>"
        "</svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.raw.component_count == 2
    assert result.silhouette.component_count == 2


def test_precision_grid_preserves_a_visible_sliver_after_occlusion() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 10 10'>"
        "<rect width='10' height='10' fill='#f00'/>"
        "<rect x='0.0001' width='9.9999' height='10' fill='#00f'/>"
        "</svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.raw.component_count == 2
    assert result.visible.component_count == 2


def test_exact_rect_retains_large_coordinate_area_in_polygon_output() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 100000000 10'>"
        "<rect width='100000000' height='10' fill='#f00'/>"
        "<rect x='99999990' width='1' height='10' fill='#00f'/>"
        "</svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.raw.geometry_count == 2
    assert result.raw.component_count == 2
    assert result.raw.rgba.tolist() == [
        [255, 0, 0, 255],
        [0, 0, 255, 255],
    ]
    assert result.unprintable_fragments.count == 0


def test_small_quadratic_loop_preserves_its_real_area() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 1676 2238'>"
        "<rect width='100' height='100' fill='#f00'/>"
        "<g transform='scale(1.10045962 1.10029499)'>"
        "<path fill='#3a3b70' fill-rule='evenodd' d='"
        "M1015.260009765625 1215.760009765625 "
        "Q1014.8200073242188 1215.1199951171875 "
        "1014.4600219726562 1214.47998046875 "
        "Q1014.4500122070312 1214.47998046875 "
        "1014.4600219726562 1214.47998046875 "
        "Q1014.8300170898438 1215.1099853515625 "
        "1015.260009765625 1215.760009765625Z'/></g></svg>",
        target_width_mm=111.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.raw.geometry_count == 2
    assert result.raw.component_count == 2
    assert result.raw.rgba.tolist() == [
        [255, 0, 0, 255],
        [58, 59, 112, 255],
    ]
    assert geometry_area(result, result.raw, 1) > 0.0
    assert result.unprintable_fragments.count == 0


def test_small_backtracking_curve_preserves_its_real_area() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 2244 2804'>"
        "<rect width='100' height='100' fill='#f00'/>"
        "<g transform='scale(1.42476190 1.42479675)'>"
        "<path fill='#ad480e' fill-rule='evenodd' d='"
        "M1446.219970703125 1235.4000244140625 "
        "Q1445.72998046875 1235.6300048828125 "
        "1445.0699462890625 1236.260009765625 "
        "Q1445.06005859375 1236.27001953125 "
        "1445.0699462890625 1236.260009765625 "
        "Q1445.7099609375 1235.5999755859375 "
        "1446.219970703125 1235.4000244140625Z'/></g></svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.raw.geometry_count == 2
    assert result.raw.component_count == 2
    assert result.raw.rgba.tolist() == [
        [255, 0, 0, 255],
        [173, 72, 14, 255],
    ]
    assert geometry_area(result, result.raw, 1) > 0.0
    assert result.unprintable_fragments.count == 0


def test_small_curve_with_area_is_preserved_as_a_polygon() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 1572 1572'>"
        "<rect width='100' height='100' fill='#f00'/>"
        "<path fill='#91766c' d='M1265 245.9199981689453 "
        "Q1264.7900390625 245.41000366210938 "
        "1264.8599853515625 244.52000427246094 "
        "L1265 245.9199981689453Z'/></svg>",
        target_width_mm=111.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.raw.geometry_count == 2
    assert result.raw.component_count == 2
    assert result.unprintable_fragments.count == 0


def test_closed_cubic_bulge_is_refined_before_point_classification() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 100 100'>"
        "<rect width='10' height='10' fill='#f00'/>"
        "<path fill='#00f' d='M20 20 "
        "C20.004 20.004 19.996 20.004 20 20Z'/></svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.raw.geometry_count == 2
    assert result.raw.component_count == 2
    assert result.raw.rgba.tolist() == [
        [255, 0, 0, 255],
        [0, 0, 255, 255],
    ]
    assert geometry_area(result, result.raw, 1) > 0.0
    assert result.unprintable_fragments.count == 0


def test_exact_rect_retains_thin_large_coordinate_component() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 100000000 100000000'>"
        "<rect width='100000000' height='100000000' fill='#f00'/>"
        "<rect x='99999990' width='1' height='100000000' fill='#00f'/>"
        "</svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.raw.geometry_count == 2
    assert result.raw.component_count == 2
    assert result.raw.rgba.tolist() == [
        [255, 0, 0, 255],
        [0, 0, 255, 255],
    ]
    assert result.unprintable_fragments.count == 0


def test_collapsed_curved_sliver_is_refined_instead_of_rejected() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 4804 6900'>"
        "<rect width='100' height='100' fill='#f00'/>"
        "<g transform='scale(3.27025187 3.27014218)'>"
        "<path fill='#91766c' d='M159.77000427246094 951.52001953125 "
        "Q159.5500030517578 951.1799926757812 "
        "159.55999755859375 950.7100219726562 "
        "Q159.8000030517578 951.0499877929688 "
        "159.77000427246094 951.52001953125Z'/></g></svg>",
        target_width_mm=111.0,
        tolerance_mm=0.02,
        allow_strokes=False,
    )

    assert result.status == "supported"
    assert result.raw.geometry_count == 2
    assert result.raw.component_count == 2


def test_exact_line_gap_in_curved_contours_does_not_spend_curve_budget() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 20 10'>"
        "<path d='M0 0H9.997V10H0C0 7 0 3 0 0Z' fill='#f00'/>"
        "<path d='M10.003 0H20V10C16 10 14 10 10.003 10Z' fill='#00f'/>"
        "</svg>",
        target_width_mm=20.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"


def test_sub_tolerance_curve_gap_is_preserved_on_the_integer_grid() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 20 10'>"
        "<path d='M0 0H9.992C10 3 10 7 9.992 10H0Z' fill='#f00'/>"
        "<path d='M10.008 0C10 3 10 7 10.008 10H20V0Z' fill='#00f'/>"
        "</svg>",
        target_width_mm=20.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.raw.component_count == 2


@pytest.mark.parametrize("viewbox_size", [1.0, 0.001])
def test_small_user_unit_cubic_uses_the_same_physical_tolerance(
    viewbox_size: float,
) -> None:
    result = lumina_svg_core.analyze_svg_svg(
        f"<svg viewBox='0 0 {viewbox_size:g} {viewbox_size:g}'>"
        f"<path d='M0 {viewbox_size:g} C0 0 {viewbox_size / 4:g} 0 "
        f"{viewbox_size / 2:g} 0 C{viewbox_size * 3 / 4:g} 0 "
        f"{viewbox_size:g} 0 {viewbox_size:g} {viewbox_size:g}Z' "
        "fill='red'/></svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.raw.geometry_count == 1


def test_robust_non_adjacent_self_intersection_uses_svg_fill_rule() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 20 20'>"
        "<path d='M0 0L10 10L0 10L10 0L20 20L0 20Z' fill='#f00'/>"
        "</svg>",
        target_width_mm=20.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.raw.geometry_count == 1
    assert result.raw.component_count > 0


def test_non_adjacent_shared_endpoint_overlap_uses_evenodd_fill() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 100 100'>"
        "<path d='M10 10H90V90H10V10H50V50H10Z' "
        "fill='red' fill-rule='evenodd'/></svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.raw.geometry_count == 1
    assert result.raw.component_count > 0


def test_non_adjacent_collinear_self_overlap_uses_nonzero_fill() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 20 10'>"
        "<path d='M0 0H10V1L5 0H15V10H0Z' fill='#f00'/>"
        "</svg>",
        target_width_mm=20.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.raw.geometry_count == 1


def test_intersecting_subpaths_in_one_paint_are_unioned_by_fill_rule() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 20 20'>"
        "<path d='M0 0H10V10H0Z M5 -5H6V15H5Z' fill='#f00'/>"
        "</svg>",
        target_width_mm=20.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.raw.geometry_count == 1
    assert result.raw.component_count == 1


def test_relative_path_rounding_chain_uses_exact_source_coordinates() -> None:
    relative_steps = "h.03 " * 8000
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 1100000 10'>"
        f"<path d='M1000000 0 {relative_steps}v10 h-240 z' fill='#f00'/>"
        "</svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.raw.geometry_count == 1
    assert geometry_area(result, result.raw, 0) == pytest.approx(2400.0)


def test_canceling_relative_steps_do_not_consume_the_full_precision_budget(
) -> None:
    def first_ring_area(result) -> float:
        coordinates = (
            np.asarray(result.raw.coordinates, dtype=np.float64)
            * result.grid_to_source_unit
        )
        ring_end = int(result.raw.ring_offsets[0])
        ring = coordinates[:ring_end]
        return abs(
            float(
                np.sum(
                    ring[:-1, 0] * ring[1:, 1]
                    - ring[1:, 0] * ring[:-1, 1]
                )
            )
        ) * 0.5

    canceling_steps = " ".join(["h.01 h-.01"] * 40)
    noisy = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 2048 2048'>"
        f"<path d='M1960 100 {canceling_steps} "
        "c0 10 10 10 10 0 v10 h-10 z' fill='#f00'/>"
        "</svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )
    reference = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 2048 2048'>"
        "<path d='M1960 100 c0 10 10 10 10 0 v10 h-10 z' "
        "fill='#f00'/></svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert noisy.status == reference.status == "supported"
    assert first_ring_area(noisy) == pytest.approx(
        first_ring_area(reference),
        abs=2e-4,
    )


def test_transform_rounding_chain_uses_exact_composition() -> None:
    transforms = "translate(.03 0) " * 8000
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 1100000 10'>"
        f"<path transform='translate(1000000 0) {transforms}' "
        "d='M0 0H240V10H0Z' fill='#f00'/></svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.raw.geometry_count == 1
    assert geometry_area(result, result.raw, 0) == pytest.approx(2400.0)


def test_shallow_crossing_is_resolved_by_svg_paint_order() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 1 2'>"
        "<path d='M0 0H1V1H0Z' fill='#f00'/>"
        "<path d='M0 .9995L1 1.0005V2H0Z' fill='#00f'/>"
        "</svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.raw.geometry_count == 2
    assert result.visible.geometry_count == 2
    assert result.silhouette.component_count == 1


def test_collinear_transformed_paints_use_recorded_shared_boundary() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 10 10'>"
        "<rect transform='translate(.1 0)' width='5' height='5' "
        "fill='#f00'/>"
        "<rect x='5.1' width='4' height='5' fill='#00f'/>"
        "</svg>",
        target_width_mm=10.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported", result.reason_code
    assert result.raw.geometry_count == 2
    assert result.visible.geometry_count == 2
    assert result.silhouette.component_count == 1


def test_exported_grid_stays_in_normalized_svg_analysis_domain() -> None:
    result = lumina_svg_core.analyze_svg(
        FIXTURES / "fill_rules_transforms.svg",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    source_coordinates = (
        result.visible.coordinates.astype(np.float64)
        * result.grid_to_source_unit
    )
    assert source_coordinates[:, 0].min() == pytest.approx(20.0, abs=0.01)
    assert source_coordinates[:, 1].min() == pytest.approx(14.0, abs=0.01)
    assert source_coordinates[:, 0].max() == pytest.approx(146.0, abs=0.01)
    assert source_coordinates[:, 1].max() == pytest.approx(64.0, abs=0.01)
    assert np.all(source_coordinates[:, 0] >= 0.0)
    assert np.all(source_coordinates[:, 1] >= 0.0)
    assert np.all(source_coordinates[:, 0] <= result.bbox[2] + 0.01)
    assert np.all(source_coordinates[:, 1] <= result.bbox[3] + 0.01)


def test_collinear_cubic_overshoot_is_not_flattened_to_its_short_chord() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 10 10'>"
        "<path d='M0 5C100 5 -100 5 10 5' fill='none' "
        "stroke='#000' stroke-width='1'/>"
        "</svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.bbox[0] < -15.0
    assert result.bbox[2] > 40.0
    source_coordinates = (
        result.raw.coordinates.astype(np.float64)
        * result.grid_to_source_unit
    )
    assert source_coordinates[:, 0].min() == pytest.approx(0.0, abs=0.02)
    assert source_coordinates[:, 0].max() == pytest.approx(
        result.bbox[2], abs=0.02
    )


def test_close_then_draw_that_overlaps_same_paint_is_supported() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 30 10'>"
        "<path d='M0 0L10 0L0 10Z L30 0L30 10Z' fill='#f00'/>"
        "</svg>",
        target_width_mm=30.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.raw.geometry_count == 1


def test_width_and_height_without_viewbox_do_not_expand_geometry_bbox() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg width='100' height='100'>"
        "<rect x='20' y='20' width='10' height='10' fill='#f00'/>"
        "</svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.bbox == pytest.approx((20.0, 20.0, 10.0, 10.0), abs=0.02)
    assert result.scale_factor == pytest.approx(10.0, abs=0.02)
