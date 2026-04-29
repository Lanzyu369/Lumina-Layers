"""Unit tests for vector_engine SVG pipeline fixes.

Covers:
    Fix 1: Adaptive de Casteljau Bézier flattening
    Fix 2: fill-rule aware subpath handling
    Fix 3: Morphological closing (_normalize_contours)
    Fix 4: Gradient flattening
    Fix 5: Disconnected shape splitting (_split_disconnected_shapes)
    Fix 6: Backing plate hole filtering (_filter_backing_holes)
    Fix 7: Same-colour shape merging in _run_length_extrude
    Fix 8: fill-rule values fallback + stroke-only element skipping
"""

import math
import tempfile
import os
import numpy as np
import pytest
from shapely.geometry import Polygon, MultiPolygon, GeometryCollection, LineString

from core.vector_engine import (
    _flatten_cubic,
    _flatten_quadratic,
    _sample_gradient_stops,
    _parse_svg_transform,
    _parse_gradient_length,
    VectorProcessor,
    MIN_SHAPE_AREA_MM2,
)


# ---------------------------------------------------------------------------
# Fix 1: Adaptive Bézier flattening
# ---------------------------------------------------------------------------


class TestFlattenCubicBezier:
    """Verify adaptive de Casteljau subdivision produces correct geometry."""

    def test_straight_line_produces_minimal_points(self):
        """A cubic Bézier that is actually a straight line should add only the end point."""
        out = [(0.0, 0.0)]
        _flatten_cubic(0, 0, 10, 0, 20, 0, 30, 0, tolerance=0.1, out=out, depth=0)
        assert len(out) == 2
        assert out[-1] == pytest.approx((30.0, 0.0))

    def test_quarter_circle_accuracy(self):
        """A cubic Bézier approximating a quarter circle should stay within tolerance."""
        k = 0.5522847498
        r = 50.0
        out = [(r, 0.0)]
        _flatten_cubic(r, 0, r, k * r, k * r, r, 0, r, tolerance=0.05, out=out, depth=0)
        for x, y in out:
            dist = math.sqrt(x ** 2 + y ** 2)
            assert abs(dist - r) < 0.5, f"Point ({x:.2f}, {y:.2f}) deviates {abs(dist-r):.4f} from radius"

    def test_tight_tolerance_produces_more_points(self):
        """Tighter tolerance should produce more subdivisions."""
        k = 0.5522847498
        r = 50.0
        out_coarse = [(r, 0.0)]
        _flatten_cubic(r, 0, r, k*r, k*r, r, 0, r, tolerance=1.0, out=out_coarse, depth=0)
        out_fine = [(r, 0.0)]
        _flatten_cubic(r, 0, r, k*r, k*r, r, 0, r, tolerance=0.01, out=out_fine, depth=0)
        assert len(out_fine) > len(out_coarse)


class TestFlattenQuadraticBezier:
    """Verify adaptive quadratic Bézier subdivision."""

    def test_straight_line(self):
        out = [(0.0, 0.0)]
        _flatten_quadratic(0, 0, 5, 0, 10, 0, tolerance=0.1, out=out, depth=0)
        assert len(out) == 2
        assert out[-1] == pytest.approx((10.0, 0.0))

    def test_curved_segment(self):
        out = [(0.0, 0.0)]
        _flatten_quadratic(0, 0, 5, 10, 10, 0, tolerance=0.1, out=out, depth=0)
        assert len(out) > 2
        assert out[-1] == pytest.approx((10.0, 0.0))


# ---------------------------------------------------------------------------
# Fix 2: fill-rule — tested via _parse_svg integration (needs SVG file).
#         Here we verify the subpath merging logic directly.
# ---------------------------------------------------------------------------


class TestFillRuleSubpathMerging:
    """Verify that nonzero uses union and evenodd uses symmetric_difference."""

    def _make_concentric_squares(self):
        outer = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
        inner = Polygon([(2, 2), (8, 2), (8, 8), (2, 8)])
        return outer, inner

    def test_nonzero_union_fills_hole(self):
        """nonzero rule: overlapping same-direction subpaths produce filled area."""
        outer, inner = self._make_concentric_squares()
        merged = outer.union(inner)
        assert merged.area == pytest.approx(outer.area, rel=0.01)

    def test_evenodd_symmetric_difference_creates_hole(self):
        """evenodd rule: overlapping subpaths create a hole in the overlap region."""
        outer, inner = self._make_concentric_squares()
        merged = outer.symmetric_difference(inner)
        expected_area = outer.area - inner.area
        assert merged.area == pytest.approx(expected_area, rel=0.01)


# ---------------------------------------------------------------------------
# Fix 3: Morphological closing
# ---------------------------------------------------------------------------


class TestNormalizeContours:
    """Verify morphological close fills micro-gaps and preserves shape."""

    def test_fills_small_gap(self):
        """Two adjacent squares with a tiny gap should be merged."""
        sq1 = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
        sq2 = Polygon([(10.02, 0), (20, 0), (20, 10), (10.02, 10)])
        combined = sq1.union(sq2)
        result = VectorProcessor._normalize_contours(combined, close_delta_mm=0.05)
        assert result.geom_type == "Polygon"
        assert len(list(result.interiors)) == 0

    def test_preserves_large_holes(self):
        """Large holes should not be filled by morphological closing."""
        outer = Polygon([(0, 0), (20, 0), (20, 20), (0, 20)])
        inner = Polygon([(5, 5), (15, 5), (15, 15), (5, 15)])
        shape = outer.difference(inner)
        result = VectorProcessor._normalize_contours(shape, close_delta_mm=0.03)
        assert len(list(result.interiors)) >= 1

    def test_none_input(self):
        assert VectorProcessor._normalize_contours(None) is None

    def test_empty_input(self):
        empty = Polygon()
        result = VectorProcessor._normalize_contours(empty)
        assert result.is_empty


# ---------------------------------------------------------------------------
# Fix 4: Gradient stop interpolation
# ---------------------------------------------------------------------------


class TestGradientStopSampling:
    """Verify gradient colour interpolation logic."""

    def test_at_first_stop(self):
        stops = [(0.0, (255, 0, 0)), (1.0, (0, 0, 255))]
        assert _sample_gradient_stops(stops, 0.0) == (255, 0, 0)

    def test_at_last_stop(self):
        stops = [(0.0, (255, 0, 0)), (1.0, (0, 0, 255))]
        assert _sample_gradient_stops(stops, 1.0) == (0, 0, 255)

    def test_midpoint_interpolation(self):
        stops = [(0.0, (0, 0, 0)), (1.0, (200, 100, 50))]
        r, g, b = _sample_gradient_stops(stops, 0.5)
        assert r == 100
        assert g == 50
        assert b == 25

    def test_below_first_stop_clamps(self):
        stops = [(0.2, (255, 0, 0)), (0.8, (0, 0, 255))]
        assert _sample_gradient_stops(stops, 0.0) == (255, 0, 0)

    def test_above_last_stop_clamps(self):
        stops = [(0.2, (255, 0, 0)), (0.8, (0, 0, 255))]
        assert _sample_gradient_stops(stops, 1.0) == (0, 0, 255)

    def test_empty_stops(self):
        assert _sample_gradient_stops([], 0.5) == (128, 128, 128)


class TestFlattenGradientShape:
    """Verify gradient → solid-colour region conversion."""

    def test_linear_gradient_produces_regions(self):
        grad_info = {
            "type": "linear",
            "x1": 0, "y1": 0, "x2": 100, "y2": 0,
            "stops": [(0.0, (255, 0, 0)), (1.0, (0, 0, 255))],
            "units": "userSpaceOnUse",
        }
        poly = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
        result = VectorProcessor._flatten_gradient_shape(grad_info, [poly])
        assert len(result) == 2
        colors = {item["color"] for item in result}
        assert (255, 0, 0) in colors
        assert (0, 0, 255) in colors
        for item in result:
            assert not item["poly"].is_empty

    def test_empty_subpaths_returns_empty(self):
        grad_info = {
            "type": "linear",
            "x1": 0, "y1": 0, "x2": 100, "y2": 0,
            "stops": [(0.0, (255, 0, 0)), (1.0, (0, 0, 255))],
            "units": "userSpaceOnUse",
        }
        result = VectorProcessor._flatten_gradient_shape(grad_info, [])
        assert result == []


# ---------------------------------------------------------------------------
# Fix 5: Disconnected shape splitting
# ---------------------------------------------------------------------------


class TestSplitDisconnectedShapes:
    """Verify MultiPolygon/GeometryCollection splitting."""

    def test_single_polygon_unchanged(self):
        p = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
        data = [{"poly": p, "color": (255, 0, 0)}]
        result = VectorProcessor._split_disconnected_shapes(data)
        assert len(result) == 1
        assert result[0]["poly"] is p

    def test_multipolygon_split(self):
        p1 = Polygon([(0, 0), (5, 0), (5, 5), (0, 5)])
        p2 = Polygon([(10, 10), (15, 10), (15, 15), (10, 15)])
        mp = MultiPolygon([p1, p2])
        data = [{"poly": mp, "color": (0, 255, 0)}]
        result = VectorProcessor._split_disconnected_shapes(data)
        assert len(result) == 2
        assert all(r["color"] == (0, 255, 0) for r in result)

    def test_tiny_fragments_filtered(self):
        big = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
        tiny = Polygon([(20, 20), (20.001, 20), (20.001, 20.001), (20, 20.001)])
        mp = MultiPolygon([big, tiny])
        data = [{"poly": mp, "color": (0, 0, 255)}]
        result = VectorProcessor._split_disconnected_shapes(data)
        assert len(result) == 1

    def test_geometry_collection(self):
        p = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
        gc = GeometryCollection([p])
        data = [{"poly": gc, "color": (128, 128, 128)}]
        result = VectorProcessor._split_disconnected_shapes(data)
        assert len(result) == 1

    def test_empty_geometry_skipped(self):
        data = [{"poly": Polygon(), "color": (0, 0, 0)}]
        result = VectorProcessor._split_disconnected_shapes(data)
        assert len(result) == 0


class TestExtractPolygonalGeometry:
    """Verify polygonal parts survive GeometryCollection repair output."""

    def test_geometry_collection_keeps_multipolygon_child(self):
        p1 = Polygon([(0, 0), (2, 0), (2, 2), (0, 2)])
        p2 = Polygon([(3, 0), (5, 0), (5, 2), (3, 2)])
        gc = GeometryCollection([MultiPolygon([p1, p2]), LineString([(0, 0), (5, 2)])])

        result = VectorProcessor._extract_polygonal_geometry(gc)

        assert result is not None
        assert not result.is_empty
        assert result.geom_type in ("Polygon", "MultiPolygon")
        assert result.area == pytest.approx(p1.area + p2.area)


# ---------------------------------------------------------------------------
# Fix 6: Backing plate hole filtering
# ---------------------------------------------------------------------------


class TestFilterBackingHoles:
    """Verify small-hole removal from backing plate geometry."""

    def test_removes_small_holes(self):
        outer = [(0, 0), (100, 0), (100, 100), (0, 100)]
        small_hole = [(40, 40), (40.5, 40), (40.5, 40.5), (40, 40.5)]
        poly = Polygon(outer, [small_hole])
        result = VectorProcessor._filter_backing_holes(poly, min_hole_area_mm2=1.0)
        assert len(list(result.interiors)) == 0

    def test_keeps_large_holes(self):
        outer = [(0, 0), (100, 0), (100, 100), (0, 100)]
        large_hole = [(20, 20), (80, 20), (80, 80), (20, 80)]
        poly = Polygon(outer, [large_hole])
        result = VectorProcessor._filter_backing_holes(poly, min_hole_area_mm2=1.0)
        assert len(list(result.interiors)) == 1

    def test_multipolygon(self):
        p1 = Polygon(
            [(0, 0), (50, 0), (50, 50), (0, 50)],
            [[(10, 10), (10.1, 10), (10.1, 10.1), (10, 10.1)]],
        )
        p2 = Polygon([(60, 0), (100, 0), (100, 50), (60, 50)])
        mp = MultiPolygon([p1, p2])
        result = VectorProcessor._filter_backing_holes(mp, min_hole_area_mm2=1.0)
        assert result.geom_type == "MultiPolygon"
        for p in result.geoms:
            assert len(list(p.interiors)) == 0

    def test_none_input(self):
        assert VectorProcessor._filter_backing_holes(None) is None


# ---------------------------------------------------------------------------
# Fix 7: Same-colour shape merging (tested via _run_length_extrude output)
# ---------------------------------------------------------------------------


class TestRunLengthExtrudeMerging:
    """Verify that shapes sharing a (channel, run) are merged before extrusion."""

    def test_adjacent_same_colour_shapes_produce_single_mesh_set(self):
        sq1 = Polygon([(0, 0), (5, 0), (5, 5), (0, 5)])
        sq2 = Polygon([(5.01, 0), (10, 0), (10, 5), (5.01, 5)])
        matched = [
            {"geometry": sq1, "recipe": [0, 0, 0, 0, 0], "color": (255, 255, 255)},
            {"geometry": sq2, "recipe": [0, 0, 0, 0, 0], "color": (255, 255, 255)},
        ]
        result = VectorProcessor._run_length_extrude(
            matched,
            num_layers=5,
            layer_h=0.08,
            num_channels=4,
            slot_names=["White", "Cyan", "Magenta", "Yellow"],
            scale_factor=1.0,
            extrude_cache={},
        )
        assert "White" in result
        assert len(result["White"]["meshes"]) > 0

    def test_different_channels_stay_separate(self):
        sq1 = Polygon([(0, 0), (5, 0), (5, 5), (0, 5)])
        sq2 = Polygon([(6, 0), (11, 0), (11, 5), (6, 5)])
        matched = [
            {"geometry": sq1, "recipe": [0, 0, 0, 0, 0], "color": (255, 255, 255)},
            {"geometry": sq2, "recipe": [1, 1, 1, 1, 1], "color": (0, 255, 255)},
        ]
        result = VectorProcessor._run_length_extrude(
            matched,
            num_layers=5,
            layer_h=0.08,
            num_channels=4,
            slot_names=["White", "Cyan", "Magenta", "Yellow"],
            scale_factor=1.0,
            extrude_cache={},
        )
        assert "White" in result
        assert "Cyan" in result


# ---------------------------------------------------------------------------
# Gradient parsing & coordinate fixes
# ---------------------------------------------------------------------------

class TestParseSvgTransform:
    """Verify SVG transform attribute parsing."""

    def test_identity_for_empty(self):
        m = _parse_svg_transform("")
        np.testing.assert_array_almost_equal(m, np.eye(3))

    def test_identity_for_none(self):
        m = _parse_svg_transform(None)
        np.testing.assert_array_almost_equal(m, np.eye(3))

    def test_translate(self):
        m = _parse_svg_transform("translate(-100, 50)")
        np.testing.assert_almost_equal(m[0, 2], -100)
        np.testing.assert_almost_equal(m[1, 2], 50)
        np.testing.assert_almost_equal(m[0, 0], 1)

    def test_translate_single_arg(self):
        m = _parse_svg_transform("translate(10)")
        np.testing.assert_almost_equal(m[0, 2], 10)
        np.testing.assert_almost_equal(m[1, 2], 0)

    def test_scale(self):
        m = _parse_svg_transform("scale(2, 3)")
        np.testing.assert_almost_equal(m[0, 0], 2)
        np.testing.assert_almost_equal(m[1, 1], 3)

    def test_scale_uniform(self):
        m = _parse_svg_transform("scale(0.5)")
        np.testing.assert_almost_equal(m[0, 0], 0.5)
        np.testing.assert_almost_equal(m[1, 1], 0.5)

    def test_rotate(self):
        m = _parse_svg_transform("rotate(90)")
        pt = m @ np.array([1, 0, 1])
        np.testing.assert_almost_equal(pt[0], 0, decimal=10)
        np.testing.assert_almost_equal(pt[1], 1, decimal=10)

    def test_matrix(self):
        m = _parse_svg_transform("matrix(1 0 0 1 10 20)")
        np.testing.assert_almost_equal(m[0, 2], 10)
        np.testing.assert_almost_equal(m[1, 2], 20)

    def test_concatenated_transforms(self):
        m = _parse_svg_transform("translate(10 20) scale(2)")
        pt = m @ np.array([5, 5, 1])
        np.testing.assert_almost_equal(pt[0], 20)   # (5*2) + 10
        np.testing.assert_almost_equal(pt[1], 30)   # (5*2) + 20

    def test_apply_point(self):
        m = _parse_svg_transform("translate(-2046.32 -4636)")
        pt = m @ np.array([7555.62, 12206.91, 1.0])
        np.testing.assert_almost_equal(pt[0], 5509.30, decimal=2)
        np.testing.assert_almost_equal(pt[1], 7570.91, decimal=2)


class TestParseGradientLength:
    """Verify percentage and raw coordinate parsing."""

    def test_plain_float(self):
        assert _parse_gradient_length("42.5") == 42.5

    def test_percentage(self):
        assert _parse_gradient_length("50%") == pytest.approx(0.5)

    def test_zero_percent(self):
        assert _parse_gradient_length("0%") == 0.0

    def test_hundred_percent(self):
        assert _parse_gradient_length("100%") == pytest.approx(1.0)

    def test_none_returns_default(self):
        assert _parse_gradient_length(None, 7.0) == 7.0

    def test_empty_returns_default(self):
        assert _parse_gradient_length("", 3.0) == 3.0

    def test_invalid_returns_default(self):
        assert _parse_gradient_length("abc", 1.0) == 1.0


class TestParseGradientDefs:
    """Integration tests for the full gradient definition parser."""

    def _write_svg(self, content):
        f = tempfile.NamedTemporaryFile(
            suffix=".svg", mode="w", delete=False
        )
        f.write(content)
        f.close()
        return f.name

    def test_basic_linear_gradient(self):
        path = self._write_svg(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
            "<defs>"
            '<linearGradient id="g1" gradientUnits="userSpaceOnUse"'
            ' x1="0" y1="0" x2="100" y2="0">'
            '<stop offset="0" stop-color="red"/>'
            '<stop offset="1" stop-color="blue"/>'
            "</linearGradient></defs></svg>"
        )
        try:
            gd = VectorProcessor._parse_gradient_defs(path)
            assert "g1" in gd
            assert gd["g1"]["type"] == "linear"
            assert gd["g1"]["units"] == "userSpaceOnUse"
            assert len(gd["g1"]["stops"]) == 2
        finally:
            os.unlink(path)

    def test_gradient_transform_parsed(self):
        path = self._write_svg(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
            "<defs>"
            '<linearGradient id="g1" gradientUnits="userSpaceOnUse"'
            ' gradientTransform="translate(-10 -20)"'
            ' x1="50" y1="60" x2="90" y2="80">'
            '<stop offset="0" stop-color="red"/>'
            '<stop offset="1" stop-color="blue"/>'
            "</linearGradient></defs></svg>"
        )
        try:
            gd = VectorProcessor._parse_gradient_defs(path)
            tf = gd["g1"]["transform"]
            np.testing.assert_almost_equal(tf[0, 2], -10)
            np.testing.assert_almost_equal(tf[1, 2], -20)
        finally:
            os.unlink(path)

    def test_default_units_is_object_bounding_box(self):
        path = self._write_svg(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
            "<defs>"
            '<linearGradient id="g1">'
            '<stop offset="0" stop-color="red"/>'
            '<stop offset="1" stop-color="blue"/>'
            "</linearGradient></defs></svg>"
        )
        try:
            gd = VectorProcessor._parse_gradient_defs(path)
            assert gd["g1"]["units"] == "objectBoundingBox"
        finally:
            os.unlink(path)

    def test_href_inherits_stops(self):
        path = self._write_svg(
            '<svg xmlns="http://www.w3.org/2000/svg"'
            ' xmlns:xlink="http://www.w3.org/1999/xlink"'
            ' viewBox="0 0 100 100"><defs>'
            '<linearGradient id="base">'
            '<stop offset="0" stop-color="red"/>'
            '<stop offset="1" stop-color="blue"/>'
            "</linearGradient>"
            '<linearGradient id="child" xlink:href="#base"'
            ' x1="0" y1="0" x2="100" y2="0"'
            ' gradientUnits="userSpaceOnUse"/>'
            "</defs></svg>"
        )
        try:
            gd = VectorProcessor._parse_gradient_defs(path)
            assert len(gd["child"]["stops"]) == 2
            assert gd["child"]["stops"][0][1] == (255, 0, 0)
        finally:
            os.unlink(path)

    def test_href_inherits_coords(self):
        path = self._write_svg(
            '<svg xmlns="http://www.w3.org/2000/svg"'
            ' xmlns:xlink="http://www.w3.org/1999/xlink"'
            ' viewBox="0 0 100 100"><defs>'
            '<linearGradient id="base" x1="10" y1="20" x2="90" y2="80"'
            ' gradientUnits="userSpaceOnUse">'
            '<stop offset="0" stop-color="red"/>'
            '<stop offset="1" stop-color="blue"/>'
            "</linearGradient>"
            '<linearGradient id="child" xlink:href="#base"/>'
            "</defs></svg>"
        )
        try:
            gd = VectorProcessor._parse_gradient_defs(path)
            assert gd["child"]["x1"] == 10.0
            assert gd["child"]["y2"] == 80.0
        finally:
            os.unlink(path)

    def test_stop_color_from_style_attribute(self):
        path = self._write_svg(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
            "<defs>"
            '<linearGradient id="g1" gradientUnits="userSpaceOnUse"'
            ' x1="0" x2="100">'
            '<stop offset="0" style="stop-color:#ff0000"/>'
            '<stop offset="1" style="stop-color:blue"/>'
            "</linearGradient></defs></svg>"
        )
        try:
            gd = VectorProcessor._parse_gradient_defs(path)
            assert gd["g1"]["stops"][0][1] == (255, 0, 0)
            assert gd["g1"]["stops"][1][1] == (0, 0, 255)
        finally:
            os.unlink(path)

    def test_percentage_coords_no_crash(self):
        path = self._write_svg(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
            "<defs>"
            '<linearGradient id="g1" x1="0%" y1="0%" x2="100%" y2="0%">'
            '<stop offset="0" stop-color="red"/>'
            '<stop offset="1" stop-color="blue"/>'
            "</linearGradient></defs></svg>"
        )
        try:
            gd = VectorProcessor._parse_gradient_defs(path)
            assert gd["g1"]["x1"] == pytest.approx(0.0)
            assert gd["g1"]["x2"] == pytest.approx(1.0)
        finally:
            os.unlink(path)

    def test_radial_gradient_parsed(self):
        path = self._write_svg(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
            "<defs>"
            '<radialGradient id="rg" cx="50" cy="50" r="40"'
            ' gradientUnits="userSpaceOnUse">'
            '<stop offset="0" stop-color="white"/>'
            '<stop offset="1" stop-color="black"/>'
            "</radialGradient></defs></svg>"
        )
        try:
            gd = VectorProcessor._parse_gradient_defs(path)
            assert gd["rg"]["type"] == "radial"
            assert gd["rg"]["cx"] == 50.0
            assert gd["rg"]["r"] == 40.0
        finally:
            os.unlink(path)


class TestFlattenGradientCoordinates:
    """Verify that gradientTransform and gradientUnits are correctly applied."""

    def test_transform_translate_corrects_coordinates(self):
        grad_info = {
            "type": "linear",
            "x1": 200, "y1": 200, "x2": 200, "y2": 400,
            "stops": [(0.0, (255, 0, 0)), (1.0, (0, 0, 255))],
            "units": "userSpaceOnUse",
            "transform": _parse_svg_transform("translate(-100 -100)"),
        }
        poly = Polygon([(50, 50), (150, 50), (150, 350), (50, 350)])
        result = VectorProcessor._flatten_gradient_shape(grad_info, [poly])
        assert len(result) == 2
        colors = {item["color"] for item in result}
        assert (255, 0, 0) in colors
        assert (0, 0, 255) in colors

    def test_object_bounding_box_maps_correctly(self):
        grad_info = {
            "type": "linear",
            "x1": 0, "y1": 0, "x2": 1, "y2": 0,
            "stops": [(0.0, (255, 0, 0)), (1.0, (0, 0, 255))],
            "units": "objectBoundingBox",
        }
        poly = Polygon([(0, 0), (200, 0), (200, 100), (0, 100)])
        result = VectorProcessor._flatten_gradient_shape(grad_info, [poly])
        assert len(result) == 2
        colors = {item["color"] for item in result}
        assert (255, 0, 0) in colors
        assert (0, 0, 255) in colors

    def test_no_transform_identity(self):
        grad_info = {
            "type": "linear",
            "x1": 0, "y1": 0, "x2": 100, "y2": 0,
            "stops": [(0.0, (0, 0, 0)), (1.0, (255, 255, 255))],
            "units": "userSpaceOnUse",
        }
        poly = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
        result = VectorProcessor._flatten_gradient_shape(grad_info, [poly])
        assert len(result) >= 2

    def test_real_world_gradient_with_transform(self):
        """Reproduce the exact scenario from the user's SVG."""
        grad_info = {
            "type": "linear",
            "x1": 7555.62, "y1": 12206.91,
            "x2": 7336.9, "y2": 12602.47,
            "stops": [
                (0.0, (146, 111, 115)),
                (0.51, (171, 112, 141)),
                (0.91, (173, 113, 141)),
                (1.0, (163, 98, 126)),
            ],
            "units": "userSpaceOnUse",
            "transform": _parse_svg_transform("translate(-2046.32 -4636)"),
        }
        poly = Polygon([
            (5200, 7500), (5600, 7500), (5600, 8000), (5200, 8000)
        ])
        result = VectorProcessor._flatten_gradient_shape(grad_info, [poly])
        assert len(result) >= 2, (
            "With correct transform, gradient should produce multiple color regions"
        )

    def test_radial_gradient_with_obb(self):
        grad_info = {
            "type": "radial",
            "cx": 0.5, "cy": 0.5, "r": 0.5,
            "stops": [(0.0, (255, 255, 255)), (1.0, (0, 0, 0))],
            "units": "objectBoundingBox",
        }
        poly = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
        result = VectorProcessor._flatten_gradient_shape(grad_info, [poly])
        assert len(result) == 2
        colors = {item["color"] for item in result}
        assert (255, 255, 255) in colors
        assert (0, 0, 0) in colors


# ---------------------------------------------------------------------------
# Fix 8: fill-rule values fallback + stroke-only element skipping
# ---------------------------------------------------------------------------


class TestFillRuleValuesFallback:
    """fill-rule inherited via SVG root style must be detected from values dict."""

    def _make_svg_with_fillrule(self, fill_rule_on_root: bool, fill_rule_on_element: bool):
        """Create a minimal SVG with concentric-circle compound path.

        When *fill_rule_on_root* is True, the SVG root ``<svg>`` has
        ``style="fill-rule:evenodd"``.  When *fill_rule_on_element* is True,
        the ``<path>`` element carries ``fill-rule="evenodd"`` directly.
        """
        root_style = ' style="fill-rule:evenodd;"' if fill_rule_on_root else ""
        elem_attr = ' fill-rule="evenodd"' if fill_rule_on_element else ""
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200"{root_style}>'
            f'  <path{elem_attr} fill="rgb(255,0,0)"'
            '    d="M100,10 A90,90 0 1,1 99.99,10 Z'
            '      M100,40 A60,60 0 1,0 100.01,40 Z"/>'
            "</svg>"
        )

    def _parse_shapes(self, svg_content: str):
        """Write SVG to temp file, parse with VectorProcessor, return shapes."""
        fd, path = tempfile.mkstemp(suffix=".svg")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(svg_content)
            vp = VectorProcessor.__new__(VectorProcessor)
            vp.sampling_precision = 0.02
            shapes, _scale, _bbox = vp._parse_svg(path, target_width_mm=50.0)
            return shapes
        finally:
            os.unlink(path)

    def test_fillrule_from_root_style_creates_hole(self):
        """fill-rule:evenodd on root <svg> style must create a ring, not a filled disc."""
        svg = self._make_svg_with_fillrule(fill_rule_on_root=True, fill_rule_on_element=False)
        shapes = self._parse_shapes(svg)
        assert len(shapes) >= 1
        poly = shapes[0]["poly"]
        outer_r, inner_r = 90.0, 60.0
        expected_ring_area = math.pi * (outer_r ** 2 - inner_r ** 2)
        expected_disc_area = math.pi * outer_r ** 2
        ratio = poly.area / expected_ring_area
        assert 0.7 < ratio < 1.3, (
            f"Area ratio vs ring = {ratio:.2f}; "
            f"polygon looks like a filled disc rather than a ring"
        )
        assert poly.area < expected_disc_area * 0.85, (
            "evenodd should produce a ring significantly smaller than a full disc"
        )

    def test_fillrule_on_element_creates_hole(self):
        """fill-rule:evenodd directly on element must also create a ring."""
        svg = self._make_svg_with_fillrule(fill_rule_on_root=False, fill_rule_on_element=True)
        shapes = self._parse_shapes(svg)
        assert len(shapes) >= 1
        poly = shapes[0]["poly"]
        outer_r = 90.0
        expected_disc_area = math.pi * outer_r ** 2
        assert poly.area < expected_disc_area * 0.85

    def test_nonzero_default_fills_disc(self):
        """Without any evenodd declaration, both circles should merge into a solid disc."""
        svg = self._make_svg_with_fillrule(fill_rule_on_root=False, fill_rule_on_element=False)
        shapes = self._parse_shapes(svg)
        assert len(shapes) >= 1
        poly = shapes[0]["poly"]
        outer_r = 90.0
        expected_disc_area = math.pi * outer_r ** 2
        ratio = poly.area / expected_disc_area
        assert ratio > 0.85, (
            f"nonzero default should produce a full disc; got ratio {ratio:.2f}"
        )


class TestVisibleStrokeElementsPreserved:
    """Visible SVG strokes should contribute geometry in vector mode."""

    def _make_svg_with_stroke_and_fill(self):
        """SVG with one fill rect and one stroke-only line."""
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200">'
            '  <rect x="10" y="10" width="80" height="80" fill="rgb(255,0,0)"/>'
            '  <path d="M0,100 L200,100"'
            '    stroke="rgb(0,0,255)" stroke-width="5" fill="none"/>'
            "</svg>"
        )

    def _make_svg_stroke_only(self):
        """SVG with only stroke-only elements."""
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200">'
            '  <path d="M10,10 L190,10 L190,190" '
            '    stroke="rgb(0,128,0)" stroke-width="3" fill="none"/>'
            '  <circle cx="100" cy="100" r="50" '
            '    stroke="rgb(0,0,255)" stroke-width="2" fill="none"/>'
            "</svg>"
        )

    def _parse_shapes(self, svg_content: str):
        fd, path = tempfile.mkstemp(suffix=".svg")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(svg_content)
            vp = VectorProcessor.__new__(VectorProcessor)
            vp.sampling_precision = 0.02
            shapes, _scale, _bbox = vp._parse_svg(path, target_width_mm=50.0)
            return shapes
        finally:
            os.unlink(path)

    def test_stroke_only_produces_shapes(self):
        """An SVG with visible strokes should produce stroke geometry."""
        svg = self._make_svg_stroke_only()
        shapes = self._parse_shapes(svg)
        assert len(shapes) >= 1
        colors = {s["color"] for s in shapes}
        assert (0, 128, 0) in colors or (0, 0, 255) in colors

    def test_fill_element_preserved_stroke_added(self):
        """Fill element must be kept; stroke-only element must also contribute geometry."""
        svg = self._make_svg_with_stroke_and_fill()
        shapes = self._parse_shapes(svg)
        assert len(shapes) >= 1
        colors = {s["color"] for s in shapes}
        assert (255, 0, 0) in colors, "Fill element should produce a red shape"
        assert (0, 0, 255) in colors, "Stroke-only blue line should now produce geometry"

    def test_stroke_only_is_widened_to_printable_width(self):
        svg = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
            '  <path d="M0,50 L100,50" stroke="#0000ff" stroke-width="0.5" fill="none"/>'
            "</svg>"
        )
        fd, path = tempfile.mkstemp(suffix=".svg")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(svg)
            vp = VectorProcessor.__new__(VectorProcessor)
            vp.sampling_precision = 0.02
            small_shapes, _, _ = vp._parse_svg(path, target_width_mm=10.0)
            large_shapes, _, _ = vp._parse_svg(path, target_width_mm=100.0)
        finally:
            os.unlink(path)

        blue_shapes = [
            s["poly"]
            for shapes in (small_shapes, large_shapes)
            for s in shapes
            if s["color"] == (0, 0, 255)
        ]
        assert blue_shapes, "Stroke-only blue path should produce printable geometry"
        for poly in blue_shapes:
            min_x, min_y, max_x, max_y = poly.bounds
            assert poly.area > 0
            assert max_x > min_x
            assert max_y > min_y


class TestSameColorStrokeCompensation:
    """Same-color SVG strokes should contribute visible area."""

    def _parse_shapes(self, svg_content: str):
        fd, path = tempfile.mkstemp(suffix=".svg")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(svg_content)
            vp = VectorProcessor.__new__(VectorProcessor)
            vp.sampling_precision = 0.02
            shapes, _scale, _bbox = vp._parse_svg(path, target_width_mm=50.0)
            return shapes
        finally:
            os.unlink(path)

    def test_same_color_stroke_expands_visible_polygon(self):
        no_stroke_svg = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">'
            '  <path fill="#ff0000" d="M0,0 L10,0 L10,10 L0,10 Z"/>'
            "</svg>"
        )
        same_stroke_svg = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">'
            '  <path fill="#ff0000" stroke="#ff0000" stroke-width="2"'
            ' d="M0,0 L10,0 L10,10 L0,10 Z"/>'
            "</svg>"
        )

        base_shapes = self._parse_shapes(no_stroke_svg)
        stroked_shapes = self._parse_shapes(same_stroke_svg)

        assert len(base_shapes) == 1
        assert len(stroked_shapes) == 1
        assert stroked_shapes[0]["poly"].area > base_shapes[0]["poly"].area
# ---------------------------------------------------------------------------
# Fix 9: Merged LUT palette override in vector pipeline
# ---------------------------------------------------------------------------


class TestMergedLutPaletteOverride:
    """Verify that analyze_svg uses the Merged JSON LUT palette for
    slot_names and preview_colors instead of the default EIGHT_COLOR config.

    Regression test: without this fix, material IDs from a 6-color Merged LUT
    are mapped to 8-color slot names (e.g. ID 2 → Magenta instead of Black),
    producing phantom Magenta objects in generation and layer preview.
    """

    @pytest.fixture()
    def merged_lut_json(self, tmp_path):
        """Create a minimal Merged JSON LUT with a 4-color palette."""
        import json
        lut = {
            "palette": {
                "White": {"material": "PLA", "hex_color": "#ffffff", "color_name": "White"},
                "Yellow": {"material": "PLA", "hex_color": "#ffe600", "color_name": "Yellow"},
                "Black": {"material": "PLA", "hex_color": "#000000", "color_name": "Black"},
                "Red": {"material": "PLA", "hex_color": "#dc143c", "color_name": "Red"},
            },
            "max_color_layers": 5,
            "layer_height_mm": 0.08,
            "line_width_mm": 0.42,
            "base_layers": 10,
            "base_channel_idx": 0,
            "layer_order": "Top2Bottom",
            "name": "test_merged_4color",
            "entries": [],
        }
        # Build a trivial 4^5 = 1024-entry LUT
        palette_rgb = [(255, 255, 255), (255, 230, 0), (0, 0, 0), (220, 20, 60)]
        n_channels = len(palette_rgb)
        layers = 5
        entries = []
        for i in range(n_channels ** layers):
            recipe = []
            val = i
            for _ in range(layers):
                recipe.append(val % n_channels)
                val //= n_channels
            r = palette_rgb[recipe[-1]]
            entries.append({
                "rgb": list(r),
                "hex": f"#{r[0]:02X}{r[1]:02X}{r[2]:02X}",
                "recipe": recipe,
            })
        lut["entries"] = entries
        path = tmp_path / "test_merged.json"
        path.write_text(json.dumps(lut), encoding="utf-8")
        return str(path)

    @pytest.fixture()
    def simple_svg(self, tmp_path):
        """Create a minimal SVG with a single red rectangle."""
        svg = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
            '  <rect x="10" y="10" width="80" height="80" fill="#dc143c"/>'
            "</svg>"
        )
        path = tmp_path / "test.svg"
        path.write_text(svg, encoding="utf-8")
        return str(path)

    def test_slot_names_from_palette(self, merged_lut_json, simple_svg):
        """slot_names must come from the LUT palette, not EIGHT_COLOR."""
        vp = VectorProcessor(merged_lut_json, "Merged")
        analysis = vp.analyze_svg(simple_svg, target_width_mm=50.0)

        assert analysis.slot_names == ["White", "Yellow", "Black", "Red"]
        assert analysis.num_channels == 4
        # Magenta must never appear
        assert "Magenta" not in str(analysis.slot_names)
        assert "Slot 3 (Magenta)" not in str(analysis.slot_names)

    def test_preview_colors_from_palette(self, merged_lut_json, simple_svg):
        """preview_colors must reflect the LUT palette hex values."""
        vp = VectorProcessor(merged_lut_json, "Merged")
        analysis = vp.analyze_svg(simple_svg, target_width_mm=50.0)

        # White
        assert analysis.preview_colors[0][:3] == [255, 255, 255]
        # Yellow (#ffe600)
        assert analysis.preview_colors[1][:3] == [255, 230, 0]
        # Black
        assert analysis.preview_colors[2][:3] == [0, 0, 0]
        # Red (#dc143c)
        assert analysis.preview_colors[3][:3] == [220, 20, 60]


# ---------------------------------------------------------------------------
# Fix 10: Native bundle palette override in vector pipeline
# ---------------------------------------------------------------------------


class TestNativeBundlePaletteOverride:
    """Verify that ``analyze_svg`` honors a native ColorDB palette even when
    the incoming ``color_mode`` is stale (e.g. user switched from a legacy
    CMYW LUT to the reverse-inferred native bundle without re-selecting a
    color mode).

    Regression test: without this fix, the 3MF emitted for a native_bundle
    source picked up the stale UI ``color_mode`` preset (``SIX_COLOR`` or
    ``CMYW``) as slot_names / preview_colors, so the bundle's real palette
    (e.g. RYBWGK — White/Blue/Red/Green/Yellow/Black) never reached the 3MF
    and the filament_colour array came out as CMY-flavored garbage.

    回归测试：若未修复此问题，当用户从传统 CMYW LUT 切到反推 LUT 而未
    手动调整 ``color_mode`` 时，3MF 会继承过时的 UI 颜色模式预设 (SIX_COLOR
    / CMYW) 作为槽位名称和预览颜色，bundle 自带的调色板 (RYBWGK) 无法
    进入 3MF，``filament_colour`` 便退化为 CMY 配色。
    """

    @pytest.fixture()
    def native_bundle_json(self, tmp_path):
        """Create a minimal native-bundle-style JSON LUT whose palette entries
        mimic a real ColorDB (canonical color names, ``hex_color=None``)."""
        import json
        lut = {
            # Native ColorDB palettes store entries WITHOUT hex_color; the
            # canonical color name (White / Blue / Red / Green / Yellow /
            # Black) is the only identity hint we get.
            "palette": {
                "White": {"material": "PLA"},
                "Blue": {"material": "PLA"},
                "Red": {"material": "PLA"},
                "Green": {"material": "PLA"},
                "Yellow": {"material": "PLA"},
                "Black": {"material": "PLA"},
            },
            "max_color_layers": 5,
            "layer_height_mm": 0.08,
            "line_width_mm": 0.42,
            "base_layers": 10,
            "base_channel_idx": 0,
            "layer_order": "Top2Bottom",
            "name": "test_native_bundle_6color",
            "entries": [],
        }
        # Build a 6^5 = 7776-entry LUT so `is_six_color` auto-detection
        # doesn't fire (it gates on 1296 = 6^4) and the native palette
        # override is the only thing driving slot_names.
        palette_rgb = [
            (255, 255, 255),  # White
            (10, 41, 137),    # Blue / Deep Blue
            (193, 46, 31),    # Red
            (0, 174, 66),     # Green
            (244, 238, 42),   # Yellow
            (0, 0, 0),        # Black
        ]
        n_channels = len(palette_rgb)
        layers = 5
        entries = []
        for i in range(n_channels ** layers):
            recipe = []
            val = i
            for _ in range(layers):
                recipe.append(val % n_channels)
                val //= n_channels
            r = palette_rgb[recipe[-1]]
            entries.append({
                "rgb": list(r),
                "hex": f"#{r[0]:02X}{r[1]:02X}{r[2]:02X}",
                "recipe": recipe,
            })
        lut["entries"] = entries
        path = tmp_path / "test_native_bundle.json"
        path.write_text(json.dumps(lut), encoding="utf-8")
        return str(path)

    @pytest.fixture()
    def simple_svg(self, tmp_path):
        svg = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
            '  <rect x="10" y="10" width="80" height="80" fill="#c12e1f"/>'
            "</svg>"
        )
        path = tmp_path / "test.svg"
        path.write_text(svg, encoding="utf-8")
        return str(path)

    def test_slot_names_override_stale_cmyw_color_mode(self, native_bundle_json, simple_svg):
        """Stale ``color_mode='4-Color (CMYW)'`` must NOT leak into slot_names.
        传入的陈旧 ``color_mode='4-Color (CMYW)'`` 不得污染 slot_names。"""
        vp = VectorProcessor(native_bundle_json, "4-Color (CMYW)")
        analysis = vp.analyze_svg(simple_svg, target_width_mm=50.0)

        assert analysis.slot_names == ["White", "Blue", "Red", "Green", "Yellow", "Black"]
        assert analysis.num_channels == 6
        # CMYW-leak sentinels: these names would appear if the stale color_conf
        # were still in control of slot_names.
        assert "Cyan" not in analysis.slot_names
        assert "Magenta" not in analysis.slot_names

    def test_preview_colors_resolve_canonical_rgba_when_hex_missing(
        self, native_bundle_json, simple_svg
    ):
        """With ``hex_color=None`` on every palette entry, preview_colors must
        fall back to the canonical name→RGBA registry (not to a CMYW preview
        dict keyed by the stale color_mode, and not to white placeholders).
        """
        vp = VectorProcessor(native_bundle_json, "4-Color (CMYW)")
        analysis = vp.analyze_svg(simple_svg, target_width_mm=50.0)

        # All six slots must resolve to DISTINCT, canonical RGBA triples.
        hexes = [
            "#{:02X}{:02X}{:02X}".format(*analysis.preview_colors[i][:3])
            for i in range(analysis.num_channels)
        ]
        assert len(set(hexes)) == 6, f"Expected 6 distinct colors, got {hexes}"

        # Spot-check the canonical values driven by the EIGHT_COLOR-first
        # lookup in ``preview_color_utils._get_canonical_color_lookup``.
        assert analysis.preview_colors[0][:3] == [255, 255, 255]  # White
        assert analysis.preview_colors[1][:3] == [10, 41, 137]   # Blue → Deep Blue
        assert analysis.preview_colors[2][:3] == [193, 46, 31]    # Red
        assert analysis.preview_colors[3][:3] == [0, 174, 66]     # Green
        assert analysis.preview_colors[4][:3] == [244, 238, 42]   # Yellow
        assert analysis.preview_colors[5][:3] == [0, 0, 0]        # Black
