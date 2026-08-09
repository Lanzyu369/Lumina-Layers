"""Unit tests for the lossless dense-buffer proof harness."""

from __future__ import annotations

from shapely.geometry import MultiPolygon, Polygon


def test_geometry_fingerprint_tracks_product_semantics() -> None:
    from scripts.profile_geos_buffer_fast_proof import geometry_fingerprint

    geometry = MultiPolygon(
        [
            Polygon(
                [(0, 0), (4, 0), (4, 4), (0, 4)],
                holes=[[(1, 1), (2, 1), (2, 2), (1, 2)]],
            ),
            Polygon([(10, 0), (12, 0), (12, 2), (10, 2)]),
        ]
    )

    result = geometry_fingerprint(geometry)

    assert result["valid"] is True
    assert result["geom_type"] == "MultiPolygon"
    assert result["components"] == 2
    assert result["holes"] == 1
    assert result["area"] == 19.0
    assert result["bounds"] == [0.0, 0.0, 12.0, 4.0]
    assert len(result["normalized_wkb_sha256"]) == 64


def test_compare_geometry_rejects_equal_area_with_changed_region() -> None:
    from scripts.profile_geos_buffer_fast_proof import compare_geometry

    stock = Polygon([(0, 0), (2, 0), (2, 2), (0, 2)])
    shifted = Polygon([(1, 0), (3, 0), (3, 2), (1, 2)])

    result = compare_geometry(stock, shifted)

    assert result["pass"] is False
    assert result["symmetric_difference_empty"] is False
    assert result["symmetric_difference_area"] == 4.0


def test_compare_geometry_accepts_component_order_only_difference() -> None:
    from scripts.profile_geos_buffer_fast_proof import compare_geometry

    first = Polygon([(0, 0), (2, 0), (2, 2), (0, 2)])
    second = Polygon([(4, 0), (6, 0), (6, 2), (4, 2)])
    stock = MultiPolygon([first, second])
    reordered = MultiPolygon([second, first])

    result = compare_geometry(stock, reordered)

    assert result["pass"] is True
    assert result["symmetric_difference_empty"] is True
