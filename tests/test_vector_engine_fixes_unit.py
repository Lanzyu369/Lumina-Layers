"""Unit tests for vector_engine SVG pipeline fixes.

Covers:
    Fix 1: Adaptive de Casteljau Bézier flattening
    Fix 2: fill-rule aware subpath handling
    Fix 3: Morphological closing (_normalize_contours)
    Fix 4: Gradient flattening
    Regression: Hue-aware SVG color matching
    Fix 5: Disconnected shape splitting (_split_disconnected_shapes)
    Fix 6: Backing plate hole filtering (_filter_backing_holes)
    Fix 7: Same-colour shape merging in _run_length_extrude
    Fix 8: fill-rule values fallback + stroke-only element skipping
"""

import math
import tempfile
import os
import io
import threading
import warnings
import xml.etree.ElementTree as ET
from types import SimpleNamespace
from unittest import mock
import numpy as np
import pytest
import shapely
from PIL import Image
from svgelements import Arc, Path as SvgPath
from shapely.geometry import (
    Polygon,
    MultiPolygon,
    GeometryCollection,
    LineString,
    box,
)
from shapely.ops import unary_union as shapely_unary_union

import core.vector_engine as vector_engine
from core.vector_engine import (
    _flatten_cubic,
    _flatten_quadratic,
    _sample_gradient_stops,
    _parse_svg_transform,
    _parse_gradient_length,
    _union_run_group_geometries,
    _combine_evenodd_polygons,
    VectorProcessor,
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


class TestNativeVectorRelief:
    """Relief changes per-shape backing height without rasterizing SVG colors."""

    @staticmethod
    def _analysis():
        left = box(0, 0, 10, 10)
        right = box(10, 0, 20, 10)
        shapes = [
            {
                "geometry": left,
                "recipe": [0, 0],
                "color": (255, 0, 0),
                "matched_rgb": (255, 0, 0),
            },
            {
                "geometry": right,
                "recipe": [1, 1],
                "color": (255, 255, 255),
                "matched_rgb": (255, 255, 255),
            },
        ]
        return SimpleNamespace(
            matched_shapes=shapes,
            clipped_shapes=[
                {"geometry": left, "color": (255, 0, 0)},
                {"geometry": right, "color": (255, 255, 255)},
            ],
            silhouette=left.union(right),
            image_vectorizer_bounds=None,
            scale_factor=1.0,
            bbox=(0.0, 0.0, 20.0, 10.0),
            slot_names=["Red", "White"],
            num_channels=2,
            num_layers=2,
            preview_colors={
                0: [255, 0, 0, 255],
                1: [255, 255, 255, 255],
            },
            stage_timings={},
        )

    @staticmethod
    def _processor():
        processor = object.__new__(VectorProcessor)
        processor.color_mode = "4-Color RYBW"
        processor.enable_native_vector_mesh = False
        processor.enable_fridge_magnet = False
        processor.enable_coating = False
        processor.enable_outline = False
        return processor

    def test_color_relief_keeps_optical_thickness_and_xy_geometry(self):
        flat_scene = self._processor().build_mesh(
            self._analysis(),
            thickness_mm=1.0,
            structure_mode="Single-sided",
        )
        relief_scene = self._processor().build_mesh(
            self._analysis(),
            thickness_mm=1.0,
            structure_mode="Single-sided",
            enable_relief=True,
            height_mode="color",
            color_height_map={"#ff0000": 1.04, "#ffffff": 2.0},
        )

        for slot_name in ("Red", "White"):
            flat = flat_scene.geometry[slot_name]
            relief = relief_scene.geometry[slot_name]
            assert relief.extents[:2] == pytest.approx(flat.extents[:2])
            assert relief.extents[2] == pytest.approx(flat.extents[2])

        assert relief_scene.geometry["Red"].bounds[:, 2] == pytest.approx(
            [0.88, 1.04]
        )
        assert relief_scene.geometry["White"].bounds[:, 2] == pytest.approx(
            [1.84, 2.0]
        )
        assert relief_scene.geometry["Board"].bounds[:, 2] == pytest.approx(
            [0.0, 1.84]
        )

    def test_relief_optical_union_loss_rebuilds_original_shells(self, monkeypatch):
        """Relief optical layers retain all source coverage when union is lossy."""

        analysis = self._analysis()
        original_union = vector_engine._union_run_group_geometries

        def lossy_union(geometries):
            items = tuple(geometries)
            if len(items) == 2:
                return items[0]
            return original_union(items)

        monkeypatch.setattr(
            vector_engine,
            "_union_run_group_geometries",
            lossy_union,
        )

        result = VectorProcessor._build_relief_meshes(
            matched_shapes=analysis.matched_shapes,
            num_layers=analysis.num_layers,
            layer_h=0.08,
            num_channels=analysis.num_channels,
            slot_names=analysis.slot_names,
            scale_factor=analysis.scale_factor,
            backing_color_id=0,
            default_height_mm=1.0,
            height_mode="color",
            color_height_map={"#ff0000": 1.04, "#ffffff": 1.04},
            heightmap_path=None,
            heightmap_max_height=None,
            bbox=analysis.bbox,
        )

        expected_optical_volume = sum(
            float(shape["geometry"].area) for shape in analysis.matched_shapes
        ) * 0.16
        actual_optical_volume = sum(
            abs(float(mesh.volume))
            for slot_name in ("Red", "White")
            for mesh in result[slot_name]["meshes"]
        )
        assert actual_optical_volume == pytest.approx(expected_optical_volume)

    @pytest.mark.parametrize(
        ("color_mode", "structure_mode"),
        [
            ("5-Color Extended", "Single-sided"),
            ("4-Color RYBW", "Double-sided"),
        ],
    )
    def test_unsupported_vector_relief_combinations_raise_deterministically(
        self,
        color_mode,
        structure_mode,
    ):
        processor = self._processor()
        processor.color_mode = color_mode

        with pytest.raises(ValueError, match="Native SVG relief supports only"):
            processor.build_mesh(
                self._analysis(),
                thickness_mm=1.0,
                structure_mode=structure_mode,
                enable_relief=True,
                height_mode="color",
                color_height_map={"#ff0000": 1.04, "#ffffff": 2.0},
            )

    def test_heightmap_assigns_height_to_existing_svg_regions(self, tmp_path):
        heightmap = np.full((10, 20), 255, dtype=np.uint8)
        heightmap[:, :10] = 0
        heightmap_path = tmp_path / "heightmap.png"
        Image.fromarray(heightmap).save(heightmap_path)

        scene = self._processor().build_mesh(
            self._analysis(),
            thickness_mm=1.0,
            structure_mode="Single-sided",
            enable_relief=True,
            height_mode="heightmap",
            heightmap_path=str(heightmap_path),
            heightmap_max_height=2.0,
        )

        assert scene.geometry["Red"].bounds[:, 2] == pytest.approx([0.88, 1.04])
        assert scene.geometry["White"].bounds[:, 2] == pytest.approx([1.84, 2.0])
        assert scene.geometry["Red"].extents[2] == pytest.approx(
            scene.geometry["White"].extents[2]
        )

    def test_unmapped_color_preserves_default_backing_depth(self):
        scene = self._processor().build_mesh(
            self._analysis(),
            thickness_mm=1.2,
            structure_mode="Single-sided",
            enable_relief=True,
            height_mode="color",
            color_height_map={"#ff0000": 1.04},
        )

        assert scene.geometry["White"].bounds[:, 2] == pytest.approx(
            [1.2, 1.36]
        )
        assert scene.geometry["Board"].bounds[:, 2] == pytest.approx(
            [0.0, 1.2]
        )

    def test_color_relief_uses_stable_identity_after_display_color_collision(self):
        analysis = self._analysis()
        for shape in analysis.matched_shapes:
            shape["height_identity_rgb"] = shape["matched_rgb"]
            shape["matched_rgb"] = (64, 64, 64)

        scene = self._processor().build_mesh(
            analysis,
            thickness_mm=1.0,
            structure_mode="Single-sided",
            enable_relief=True,
            height_mode="color",
            color_height_map={"#ff0000": 1.04, "#ffffff": 2.0},
        )

        assert scene.geometry["Red"].bounds[:, 2] == pytest.approx(
            [0.88, 1.04]
        )
        assert scene.geometry["White"].bounds[:, 2] == pytest.approx(
            [1.84, 2.0]
        )

    def test_heightmap_sampling_caps_extreme_svg_height(self):
        analysis = self._analysis()
        analysis.bbox = (0.0, 0.0, 1.0, 100_000.0)

        with mock.patch(
            "core.heightmap_loader.HeightmapLoader.load_and_process",
            return_value={
                "success": True,
                "height_matrix": np.ones((2, 2), dtype=np.float32),
            },
        ) as load_heightmap:
            self._processor().build_mesh(
                analysis,
                thickness_mm=1.0,
                structure_mode="Single-sided",
                enable_relief=True,
                height_mode="heightmap",
                heightmap_path="heightmap.png",
                heightmap_max_height=2.0,
            )

        assert load_heightmap.call_args.kwargs["target_w"] <= 1600
        assert load_heightmap.call_args.kwargs["target_h"] <= 1600

    @pytest.mark.parametrize("layer_count", [2, 4, 5, 7])
    def test_material_archive_global_layer_count_preserves_optical_stack(
        self,
        layer_count,
    ):
        recipe = [index % 2 for index in range(layer_count)]
        target_height = 2.0
        layer_h = 0.08
        matched_shapes = [
            {
                "geometry": box(0, 0, 10, 10),
                "recipe": recipe,
                "color": (255, 0, 0),
                "matched_rgb": (255, 0, 0),
            }
        ]
        result = VectorProcessor._build_relief_meshes(
            matched_shapes=matched_shapes,
            num_layers=layer_count,
            layer_h=layer_h,
            num_channels=2,
            slot_names=["Material A", "Material B"],
            scale_factor=1.0,
            backing_color_id=1,
            default_height_mm=1.2,
            height_mode="color",
            color_height_map={"#ff0000": target_height},
            heightmap_path=None,
            heightmap_max_height=None,
            bbox=(0.0, 0.0, 10.0, 10.0),
        )
        flat_result = VectorProcessor._run_length_extrude(
            matched_shapes=matched_shapes,
            num_layers=layer_count,
            layer_h=layer_h,
            num_channels=2,
            slot_names=["Material A", "Material B"],
            scale_factor=1.0,
        )

        for slot_name in ("Material A", "Material B"):
            flat_meshes = [
                component
                for mesh in flat_result[slot_name]["meshes"]
                for component in mesh.split(only_watertight=False)
            ]
            relief_meshes = [
                component
                for mesh in result[slot_name]["meshes"]
                for component in mesh.split(only_watertight=False)
            ]
            flat_front_intervals = sorted(
                (float(mesh.bounds[0, 2]), float(mesh.bounds[1, 2]))
                for mesh in flat_meshes
            )
            relief_front_intervals = sorted(
                (
                    target_height - float(mesh.bounds[1, 2]),
                    target_height - float(mesh.bounds[0, 2]),
                )
                for mesh in relief_meshes
            )
            assert np.allclose(relief_front_intervals, flat_front_intervals)
            assert sum(abs(float(mesh.volume)) for mesh in relief_meshes) == pytest.approx(
                sum(abs(float(mesh.volume)) for mesh in flat_meshes)
            )
            assert np.vstack([mesh.bounds[:, :2] for mesh in relief_meshes]) == pytest.approx(
                np.vstack([mesh.bounds[:, :2] for mesh in flat_meshes])
            )

        board = result["Board"]
        assert board["mat_id"] == 1
        assert board["meshes"][0].bounds[:, 2] == pytest.approx(
            [0.0, target_height - layer_count * layer_h]
        )


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


class TestFlattenArcSegments:
    """Verify SVG arc sampling keeps the fast paths intentional."""

    def test_nondefault_arc_sampling_uses_single_vectorized_npoint_call(self, monkeypatch):
        path = SvgPath("M 10,50 A 40,40 0 0 1 90,50")
        arc = next(seg for seg in path.segments() if isinstance(seg, Arc))
        calls = []
        real_npoint = Arc.npoint

        def spy_npoint(self, positions):
            calls.append(len(positions))
            return real_npoint(self, positions)

        def fail_point(self, _position):
            raise AssertionError("arc sampling should not call Arc.point per sample")

        monkeypatch.setattr(Arc, "npoint", spy_npoint)
        monkeypatch.setattr(Arc, "point", fail_point)

        points = vector_engine._sample_arc_segment_points(arc, sample_count=7)

        assert calls == [7]
        assert len(points) == 7
        assert points[-1] == pytest.approx((arc.end.x, arc.end.y))

    def test_default_arc_sampling_uses_scalar_fast_path(self, monkeypatch):
        path = SvgPath("M 10,50 A 40,40 0 0 1 90,50")
        arc = next(seg for seg in path.segments() if isinstance(seg, Arc))
        expected = [
            (float(x), float(y))
            for x, y in np.asarray(arc.npoint(vector_engine._ARC_SAMPLE_POSITIONS_10), dtype=float)
        ]

        def fail_linspace(*_args, **_kwargs):
            raise RuntimeError("default arc sampling should not allocate linspace")

        def fail_npoint(self, _positions):
            raise AssertionError("default arc sampling should not allocate through Arc.npoint")

        monkeypatch.setattr(vector_engine.np, "linspace", fail_linspace)
        monkeypatch.setattr(Arc, "npoint", fail_npoint)

        points = vector_engine._sample_arc_segment_points(arc, sample_count=10)

        assert points == pytest.approx(expected)
        assert points[-1] == pytest.approx((arc.end.x, arc.end.y))

    def test_default_arc_sampling_reuses_start_t_without_rotation_wrapper(self):
        class FakePoint:
            def __init__(self, x, y):
                self.x = x
                self.y = y

            def __eq__(self, other):
                return False

        class FakeArc:
            start = FakePoint(1.0, 0.0)
            end = FakePoint(0.0, 1.0)
            center = FakePoint(0.0, 0.0)
            prx = FakePoint(1.0, 0.0)
            pry = FakePoint(0.0, 1.0)
            sweep = np.pi / 2.0

            @property
            def rx(self):
                raise AssertionError("default arc sampling should not read Arc.rx after get_start_t")

            @property
            def ry(self):
                raise AssertionError("default arc sampling should not read Arc.ry after get_start_t")

            def get_start_t(self):
                return 0.0

            def get_rotation(self):
                raise AssertionError("default arc sampling should not call Arc.get_rotation after get_start_t")

        points = vector_engine._sample_arc_segment_points(FakeArc(), sample_count=10)

        assert len(points) == 10
        assert points[0] == pytest.approx((np.cos(np.pi * 0.05), np.sin(np.pi * 0.05)))
        assert points[-1] == pytest.approx((0.0, 1.0))


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

    def test_disjoint_nonzero_compound_path_skips_polygonize(
        self,
        tmp_path,
        monkeypatch,
    ):
        svg_path = tmp_path / "disjoint-nonzero.svg"
        svg_path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
            '<path fill="#f00" fill-rule="nonzero" '
            'd="M0 0 H10 V10 H0 Z M20 0 H30 V10 H20 Z"/></svg>',
            encoding="utf-8",
        )

        def fail_polygonize(_boundaries):
            raise AssertionError(
                "disjoint nonzero subpaths must use the sparse fast path"
            )

        monkeypatch.setattr(vector_engine, "polygonize", fail_polygonize)
        processor = VectorProcessor.__new__(VectorProcessor)
        processor.sampling_precision = 0.02
        processor._parse_expand_stroke_to_fill = False
        processor._parse_direct_top_level_paths_fast_path = False
        shapes, _scale, _bbox = processor._parse_svg(
            str(svg_path),
            target_width_mm=100.0,
        )

        geometry = shapely_unary_union([shape["poly"] for shape in shapes])
        assert geometry.bounds == pytest.approx((0.0, 0.0, 30.0, 10.0), abs=0.1)
        assert geometry.area == pytest.approx(200.0, rel=0.01)

    def test_intersecting_nonzero_compound_path_has_complexity_guardrail(
        self,
        tmp_path,
        monkeypatch,
    ):
        svg_path = tmp_path / "intersecting-nonzero.svg"
        svg_path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
            '<path fill="#f00" fill-rule="nonzero" '
            'd="M0 0 H20 V20 H0 Z M10 0 H30 V20 H10 Z"/></svg>',
            encoding="utf-8",
        )
        monkeypatch.setattr(vector_engine.VectorConfig, "MAX_POLYGONS", 1)
        processor = VectorProcessor.__new__(VectorProcessor)
        processor.sampling_precision = 0.02
        processor._parse_expand_stroke_to_fill = False
        processor._parse_direct_top_level_paths_fast_path = False

        with pytest.raises(
            ValueError,
            match="SVG compound path exceeds supported intersecting subpath complexity",
        ):
            processor._parse_svg(str(svg_path), target_width_mm=100.0)

    def test_evenodd_symmetric_difference_creates_hole(self):
        """evenodd rule: overlapping subpaths create a hole in the overlap region."""
        outer, inner = self._make_concentric_squares()
        merged = outer.symmetric_difference(inner)
        expected_area = outer.area - inner.area
        assert merged.area == pytest.approx(expected_area, rel=0.01)

    def test_evenodd_helper_matches_sequential_symmetric_difference(self):
        """Batch evenodd merge must preserve the existing sequential semantics."""
        outer, inner = self._make_concentric_squares()
        island = Polygon([(20, 0), (24, 0), (24, 4), (20, 4)])
        expected = outer.symmetric_difference(inner).symmetric_difference(island)

        merged = _combine_evenodd_polygons([outer, inner, island])

        assert merged is not None
        assert merged.area == pytest.approx(expected.area)
        assert merged.symmetric_difference(expected).area == pytest.approx(0.0)

    def test_evenodd_helper_skips_symmetric_difference_for_disjoint_subpaths(self, monkeypatch):
        """Disjoint evenodd subpaths are equivalent to a simple polygonal union."""
        left = Polygon([(0, 0), (2, 0), (2, 2), (0, 2)])
        right = Polygon([(4, 0), (6, 0), (6, 2), (4, 2)])
        calls = []

        def fail_symmetric_difference_all(_items):
            calls.append("called")
            raise AssertionError("disjoint evenodd subpaths should use the fast path")

        monkeypatch.setattr(
            vector_engine,
            "symmetric_difference_all",
            fail_symmetric_difference_all,
        )

        merged = _combine_evenodd_polygons([left, right])

        assert calls == []
        assert merged is not None
        assert merged.area == pytest.approx(left.area + right.area)
        assert merged.symmetric_difference(MultiPolygon([left, right])).area == pytest.approx(0.0)

    def test_evenodd_helper_skips_symmetric_difference_for_disjoint_holes(self, monkeypatch):
        """Contained disjoint holes are equivalent to sequential differences."""
        outer = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
        hole_a = Polygon([(1, 1), (3, 1), (3, 3), (1, 3)])
        hole_b = Polygon([(6, 6), (8, 6), (8, 8), (6, 8)])
        calls = []

        def fail_symmetric_difference_all(_items):
            calls.append("called")
            raise AssertionError("contained disjoint evenodd holes should use the fast path")

        monkeypatch.setattr(
            vector_engine,
            "symmetric_difference_all",
            fail_symmetric_difference_all,
        )

        merged = _combine_evenodd_polygons([outer, hole_a, hole_b])

        expected = outer.difference(hole_a).difference(hole_b)
        assert calls == []
        assert merged is not None
        assert merged.area == pytest.approx(expected.area)
        assert merged.symmetric_difference(expected).area == pytest.approx(0.0)

    def test_evenodd_helper_subtracts_disjoint_holes_in_one_geos_call(
        self,
        monkeypatch,
    ):
        """Verified independent holes should be subtracted as one GEOS batch."""
        outer = box(0, 0, 100, 100)
        holes = [box(x, 10, x + 4, 14) for x in range(10, 70, 10)]
        expected = outer.difference(shapely_unary_union(holes))
        real_difference = shapely.difference
        calls = []

        def recording_difference(left, right, **kwargs):
            calls.append((left, right))
            return real_difference(left, right, **kwargs)

        monkeypatch.setattr(shapely, "difference", recording_difference)

        merged = _combine_evenodd_polygons([outer, *holes])

        assert len(calls) == 1
        assert merged is not None
        assert merged.symmetric_difference(expected).is_empty

    def test_evenodd_helper_uses_prepared_container_for_multiple_holes(self, monkeypatch):
        """Contained disjoint holes should reuse a prepared outer contour for contains checks."""
        outer = Polygon([(0, 0), (20, 0), (20, 20), (0, 20)])
        holes = [
            Polygon([(1, 1), (3, 1), (3, 3), (1, 3)]),
            Polygon([(5, 5), (7, 5), (7, 7), (5, 7)]),
            Polygon([(12, 12), (16, 12), (16, 16), (12, 16)]),
        ]
        prepared_inputs = []
        contains_inputs = []

        class PreparedGeometry:
            def __init__(self, geom):
                self._geom = geom

            def contains(self, child):
                contains_inputs.append(child)
                return self._geom.contains(child)

        def fake_prep(geom):
            prepared_inputs.append(geom)
            return PreparedGeometry(geom)

        monkeypatch.setattr(vector_engine, "prep", fake_prep, raising=False)

        merged = _combine_evenodd_polygons([outer, *holes])

        expected = outer
        for hole in holes:
            expected = expected.difference(hole)
        assert prepared_inputs == [outer]
        assert contains_inputs == holes
        assert merged is not None
        assert merged.symmetric_difference(expected).area == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Fix 3: Morphological closing
# ---------------------------------------------------------------------------


class TestNormalizeContours:
    """Verify morphological close fills micro-gaps and preserves shape."""

    def test_nearby_tiny_component_cannot_replace_a_valid_printable_component(self):
        """A real clipped SVG fragment must retain its large component."""

        source = shapely.from_wkt(
            "MULTIPOLYGON (((1210.5180151367185 1521.0342871093744, "
            "1201.4221069335936 1523.1806542968748, 1195.1013867187498 "
            "1524.3925781249998, 1190.065390625 1525.09609375, "
            "1187.0378735351565 1525.1098852539062, 1186.3080838012695 "
            "1524.7391653442382, 1186.0280468750002 1524.04, "
            "1189.6442187499997 1523.6747265625, 1192.8537292480466 "
            "1522.6420733642576, 1195.018046875 1521.03, "
            "1195.0104816576086 1521.019391304348, 1195.008046875 "
            "1521.02, 1185.0704244973765 1522.0137622377624, "
            "1185.018046875 1522.0299999999997, 1185.0069929289464 "
            "1522.02, 1184.0221481441013 1522.02, 1184.018046875 "
            "1522.03, 1183.9943088942307 1522.034747596154, "
            "1183.371806640625 1522.702998046875, 1182.47875 "
            "1523.028984375, 1179.0672802083334 1523.0201533333334, "
            "1179.018046875 1523.03, 1179.0077455973023 "
            "1523.020035444435, 1177.4327000656465 1523.2053349187474, "
            "1174.81849609375 1524.04744140625, 1169.9849804687499 "
            "1524.92626953125, 1169.3420271754742 1524.9338243532695, "
            "1169.018046875 1525.03, 1171.028046875 1528.02, "
            "1171.3132983398439 1528.0735522460936, 1171.8766500854492 "
            "1527.8371847534181, 1172.098203125 1526.3845312500002, "
            "1172.568046875 1525.97, 1181.3690844726561 "
            "1527.025126953125, 1186.0186938476563 1526.7775866699221, "
            "1191.4565942382812 1526.1443591308594, 1198.3346093750001 "
            "1524.9211718749998, 1206.5880664062502 "
            "1522.9423144531247, 1214.6949218749999 1520.556875, "
            "1224.8210713545952 1517.087444715286, 1210.5180151367185 "
            "1521.0342871093744)), ((1225.0180468749998 "
            "1517.0299999999997, 1225.008046875 1517.02, "
            "1224.8210713546036 1517.0874447152835, "
            "1225.0180468749998 1517.0299999999997)))"
        )

        scalar = VectorProcessor._normalize_contours(source)
        batch = vector_engine._normalize_contours_many([source])[0]

        for result in (scalar, batch):
            assert result.area > 100.0
            assert source.difference(result).area < 0.01

        # Closing two remote tall rectangles adds more area than the damaged
        # SVG fragment loses.  A net-area guard therefore misses the loss;
        # the source itself must remain covered by the closed result.
        compensated_source = shapely_unary_union(
            [
                source,
                box(0.0, 0.0, 1.0, 3000.0),
                box(1.04, 0.0, 2.04, 3000.0),
            ]
        )
        compensated_scalar = VectorProcessor._normalize_contours(
            compensated_source
        )
        compensated_batch = vector_engine._normalize_contours_many(
            [compensated_source]
        )[0]

        for result in (compensated_scalar, compensated_batch):
            assert compensated_source.difference(result).area < 0.01
            assert result.covers(box(1.001, 1000.0, 1.039, 2000.0))

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

    def test_cached_normalize_reuses_same_geometry_and_delta(self, monkeypatch):
        geom = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
        calls = []
        original = VectorProcessor._normalize_contours

        def spy_normalize(input_geom, close_delta_mm=0.03):
            calls.append((id(input_geom), close_delta_mm))
            return original(input_geom, close_delta_mm=close_delta_mm)

        monkeypatch.setattr(VectorProcessor, "_normalize_contours", staticmethod(spy_normalize))
        cache = {}

        first = vector_engine._normalize_contours_cached(cache, geom, close_delta_mm=0.03)
        second = vector_engine._normalize_contours_cached(cache, geom, close_delta_mm=0.03)
        third = vector_engine._normalize_contours_cached(cache, geom, close_delta_mm=0.05)

        assert first is second
        assert third is not first
        assert calls == [(id(geom), 0.03), (id(geom), 0.05)]

    def test_cached_normalize_rejects_stale_id_collision(self, monkeypatch):
        geom = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
        stale_geom = Polygon([(20, 0), (30, 0), (30, 10), (20, 10)])
        stale_result = stale_geom.buffer(0)
        calls = []
        original = VectorProcessor._normalize_contours

        def spy_normalize(input_geom, close_delta_mm=0.03):
            calls.append((id(input_geom), close_delta_mm))
            return original(input_geom, close_delta_mm=close_delta_mm)

        monkeypatch.setattr(VectorProcessor, "_normalize_contours", staticmethod(spy_normalize))
        cache = {(id(geom), 0.03): stale_result}

        result = vector_engine._normalize_contours_cached(cache, geom, close_delta_mm=0.03)

        assert result is not stale_result
        assert result.bounds == pytest.approx(geom.bounds)
        assert calls == [(id(geom), 0.03)]

    def test_clip_occlusion_preserves_normalized_flag_for_unchanged_geometry(self):
        first = Polygon([(0, 0), (5, 0), (5, 5), (0, 5)])
        second = Polygon([(10, 0), (15, 0), (15, 5), (10, 5)])
        shape_data = [
            {"poly": first, "color": (255, 255, 255), "geometry_normalized": True},
            {"poly": second, "color": (255, 0, 0), "geometry_normalized": True},
        ]

        result = VectorProcessor._clip_occlusion(shape_data)

        assert result[0]["geometry"] is first
        assert result[0]["geometry_normalized"] is True
        assert result[1]["geometry"] is second
        assert result[1]["geometry_normalized"] is True

    def test_clip_occlusion_uses_strtree_intersects_predicate_when_available(self, monkeypatch):
        bottom = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
        top = Polygon([(5, 0), (15, 0), (15, 10), (5, 10)])
        seen_predicates = []

        class FakeSTRtree:
            def __init__(self, geoms):
                self.geoms = list(geoms)

            def query(self, geom, predicate=None):
                seen_predicates.append(predicate)
                if predicate == "intersects":
                    return [
                        idx
                        for idx, candidate in enumerate(self.geoms)
                        if candidate.intersects(geom)
                    ]
                return list(range(len(self.geoms)))

        monkeypatch.setattr(vector_engine, "STRtree", FakeSTRtree)

        result = VectorProcessor._clip_occlusion(
            [
                {"poly": bottom, "color": (255, 255, 255)},
                {"poly": top, "color": (255, 0, 0)},
            ]
        )

        assert seen_predicates
        assert set(seen_predicates) == {"intersects"}
        assert sum(item["geometry"].area for item in result) == pytest.approx(150.0)

    def test_clip_occlusion_uses_disjoint_subset_union_for_multi_occluders(self, monkeypatch):
        subject = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
        left = Polygon([(1, 1), (4, 1), (4, 4), (1, 4)])
        right = Polygon([(6, 6), (9, 6), (9, 9), (6, 9)])
        calls = []

        def fake_disjoint_subset_union_all(items):
            calls.append(len(list(items)))
            return vector_engine.unary_union(items)

        monkeypatch.setattr(
            vector_engine,
            "disjoint_subset_union_all",
            fake_disjoint_subset_union_all,
        )

        result = VectorProcessor._clip_occlusion(
            [
                {"poly": subject, "color": (255, 0, 0)},
                {"poly": left, "color": (0, 255, 0)},
                {"poly": right, "color": (0, 0, 255)},
            ]
        )

        assert calls == [2]
        bottom = next(item for item in result if item["draw_order"] == 0)
        assert bottom["geometry"].area == pytest.approx(82.0)

    def test_clip_occlusion_falls_back_when_disjoint_subset_union_fails(self, monkeypatch):
        subject = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
        left = Polygon([(1, 1), (4, 1), (4, 4), (1, 4)])
        right = Polygon([(6, 6), (9, 6), (9, 9), (6, 9)])

        def fail_disjoint_subset_union_all(_items):
            raise ValueError("force unary_union fallback")

        monkeypatch.setattr(
            vector_engine,
            "disjoint_subset_union_all",
            fail_disjoint_subset_union_all,
        )

        result = VectorProcessor._clip_occlusion(
            [
                {"poly": subject, "color": (255, 0, 0)},
                {"poly": left, "color": (0, 255, 0)},
                {"poly": right, "color": (0, 0, 255)},
            ]
        )

        bottom = next(item for item in result if item["draw_order"] == 0)
        assert bottom["geometry"].area == pytest.approx(82.0)

    def test_dense_clip_occlusion_preserves_exact_results_across_workers(self, monkeypatch):
        shape_data = [
            {
                "poly": box(index * 0.05, 0.0, 10.0 + index * 0.05, 10.0),
                "color": (index % 256, (index * 3) % 256, (index * 7) % 256),
            }
            for index in range(72)
        ]
        baseline = VectorProcessor._clip_occlusion(shape_data)
        worker_threads = set()
        thread_lock = threading.Lock()
        original_union = vector_engine._union_occluder_geometries

        def recording_union(items):
            with thread_lock:
                worker_threads.add(threading.get_ident())
            return original_union(items)

        monkeypatch.setattr(
            vector_engine,
            "resolve_task_parallelism_plan",
            lambda *_args, **_kwargs: SimpleNamespace(workers=4),
            raising=False,
        )
        monkeypatch.setattr(
            vector_engine,
            "_union_occluder_geometries",
            recording_union,
        )

        candidate = VectorProcessor._clip_occlusion(shape_data)

        assert len(worker_threads) > 1
        assert len(candidate) == len(baseline)
        for stock_item, candidate_item in zip(baseline, candidate):
            assert candidate_item["draw_order"] == stock_item["draw_order"]
            assert candidate_item["color"] == stock_item["color"]
            assert (
                candidate_item["geometry"].normalize().wkb
                == stock_item["geometry"].normalize().wkb
            )

    def test_parallel_clip_does_not_hide_programmer_errors(self, monkeypatch):
        shape_data = [
            {
                "poly": box(float(index), 0.0, float(index) + 0.5, 0.5),
                "color": (index % 256, 0, 0),
            }
            for index in range(64)
        ]
        geoms = [item["poly"] for item in shape_data]

        class ExplodingExecutor:
            def __init__(self, **_kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def map(self, *_args, **_kwargs):
                raise AssertionError("programmer defect")

        monkeypatch.setattr(vector_engine, "ThreadPoolExecutor", ExplodingExecutor)
        monkeypatch.setattr(
            vector_engine,
            "resolve_task_parallelism_plan",
            lambda *_args, **_kwargs: SimpleNamespace(workers=4),
        )

        with pytest.raises(AssertionError, match="programmer defect"):
            vector_engine._try_parallel_clip_occlusion(
                shape_data,
                list(range(len(shape_data))),
                geoms,
                vector_engine.STRtree(geoms),
            )

    def test_dense_clip_occlusion_builds_silhouette_while_clipping(self, monkeypatch):
        shape_data = [
            {
                "poly": box(float(index), 0.0, float(index) + 0.5, 0.5),
                "color": (index % 256, 0, 0),
            }
            for index in range(64)
        ]
        union_started = threading.Event()
        clipping_started = threading.Event()
        union_threads = []
        reservations = []
        original_union = vector_engine.unary_union

        def recording_union(geometries):
            union_threads.append(threading.get_ident())
            union_started.set()
            assert clipping_started.wait(timeout=0.5)
            return original_union(geometries)

        def fake_parallel_clip(
            _shape_data,
            _orders,
            _geoms,
            _tree,
            *,
            reserved_workers=0,
        ):
            reservations.append(reserved_workers)
            assert union_started.wait(timeout=0.5)
            clipping_started.set()
            return []

        monkeypatch.setattr(vector_engine, "unary_union", recording_union)
        monkeypatch.setattr(
            vector_engine,
            "resolve_task_parallelism_plan",
            lambda *_args, **_kwargs: SimpleNamespace(workers=4),
        )
        monkeypatch.setattr(
            vector_engine,
            "_try_parallel_clip_occlusion",
            fake_parallel_clip,
        )

        result, silhouette = VectorProcessor._clip_occlusion(
            shape_data,
            return_silhouette=True,
        )

        assert result == []
        assert silhouette.area == pytest.approx(16.0)
        assert len(union_threads) == 1
        assert union_threads[0] != threading.get_ident()
        assert reservations == [1]

    def test_postprocess_clipped_shapes_skips_known_normalized_geometry(self, monkeypatch):
        normalized = Polygon([(0, 0), (5, 0), (5, 5), (0, 5)])
        clipped = Polygon([(10, 0), (15, 0), (15, 5), (10, 5)])
        calls = []

        def fake_normalize_many(geometries, close_delta_mm=0.03):
            calls.append(list(geometries))
            return list(geometries)

        monkeypatch.setattr(vector_engine, "_normalize_contours_many", fake_normalize_many)

        result = VectorProcessor._postprocess_clipped_shapes(
            [
                {
                    "geometry": normalized,
                    "color": (255, 255, 255),
                    "geometry_normalized": True,
                },
                {"geometry": clipped, "color": (255, 0, 0)},
            ]
        )

        assert result[0]["geometry"] is normalized
        assert calls == [[clipped]]

    def test_postprocess_clipped_shapes_batches_unnormalized_geometry(self, monkeypatch):
        normalized = Polygon([(0, 0), (5, 0), (5, 5), (0, 5)])
        first = Polygon([(10, 0), (15, 0), (15, 5), (10, 5)])
        second = Polygon([(20, 0), (25, 0), (25, 5), (20, 5)])
        calls = []

        def fake_normalize_many(geometries, close_delta_mm=0.03):
            calls.append((list(geometries), close_delta_mm))
            return [geom.buffer(0) for geom in geometries]

        monkeypatch.setattr(vector_engine, "_normalize_contours_many", fake_normalize_many, raising=False)

        result = VectorProcessor._postprocess_clipped_shapes(
            [
                {
                    "geometry": normalized,
                    "color": (255, 255, 255),
                    "geometry_normalized": True,
                },
                {"geometry": first, "color": (255, 0, 0)},
                {"geometry": second, "color": (0, 0, 255)},
            ]
        )

        assert calls == [([first, second], 0.03)]
        assert result[0]["geometry"] is normalized
        assert [item["geometry_normalized"] for item in result] == [True, True, True]

    def test_normalize_contours_many_suppresses_batch_buffer_runtime_warnings(self, monkeypatch):
        geom = Polygon([(0, 0), (5, 0), (5, 5), (0, 5)])

        def noisy_buffer(geometries, *_args, **_kwargs):
            warnings.warn("invalid value encountered in buffer", RuntimeWarning)
            return np.asarray(list(geometries), dtype=object)

        monkeypatch.setattr(vector_engine, "shapely_buffer", noisy_buffer)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = vector_engine._normalize_contours_many([geom])

        assert result == [geom]
        assert not [item for item in caught if issubclass(item.category, RuntimeWarning)]

    def test_dense_batch_uses_isolated_positive_and_disconnected_inward_helpers(
        self,
        monkeypatch,
    ):
        source = MultiPolygon([box(0, 0, 1, 1), box(3, 0, 4, 1)])
        inflated = source.buffer(0.03, quad_segs=1, join_style="mitre", mitre_limit=2.0)
        deflated = inflated.buffer(-0.03, quad_segs=1, join_style="mitre", mitre_limit=2.0)
        calls = []
        monkeypatch.setattr(vector_engine.geos_buffer_fast, "MIN_DENSE_COMPONENTS", 2)
        monkeypatch.setattr(
            vector_engine.geos_buffer_fast,
            "try_dense_positive_buffer",
            lambda geometry, settings: calls.append(("positive", geometry, settings))
            or inflated,
        )
        monkeypatch.setattr(
            vector_engine.geos_buffer_fast,
            "try_disconnected_inward_buffer",
            lambda geometry, settings, **_kwargs: calls.append(
                ("inward", geometry, settings)
            )
            or deflated,
        )

        result = vector_engine._normalize_contours_many([source])

        assert [call[0] for call in calls] == ["positive", "inward"]
        assert result[0].symmetric_difference(deflated).is_empty

    def test_small_batch_does_not_call_dense_helpers(self, monkeypatch):
        source = Polygon([(0, 0), (5, 0), (5, 5), (0, 5)])

        def unexpected(*_args, **_kwargs):
            raise AssertionError("ordinary geometry must stay on the stock batch path")

        monkeypatch.setattr(
            vector_engine.geos_buffer_fast,
            "try_dense_positive_buffer",
            unexpected,
        )
        monkeypatch.setattr(
            vector_engine.geos_buffer_fast,
            "try_disconnected_inward_buffer",
            unexpected,
        )

        result = vector_engine._normalize_contours_many([source])

        assert result[0].is_valid
        assert result[0].area == pytest.approx(source.area)

    def test_dense_batch_uses_stock_positive_when_accelerator_unavailable(
        self,
        monkeypatch,
    ):
        source = MultiPolygon([box(0, 0, 1, 1), box(3, 0, 4, 1)])
        buffer_calls = []

        def stock_buffer(geometries, distance, **kwargs):
            items = list(geometries)
            buffer_calls.append((distance, items))
            return np.asarray(
                [geometry.buffer(distance, **kwargs) for geometry in items],
                dtype=object,
            )

        monkeypatch.setattr(vector_engine.geos_buffer_fast, "MIN_DENSE_COMPONENTS", 2)
        monkeypatch.setattr(
            vector_engine.geos_buffer_fast,
            "try_dense_positive_buffer",
            lambda _geometry, _settings: None,
        )
        monkeypatch.setattr(
            vector_engine.geos_buffer_fast,
            "try_disconnected_inward_buffer",
            lambda geometry, _settings, **_kwargs: geometry.buffer(
                -0.03,
                quad_segs=1,
                join_style="mitre",
                mitre_limit=2.0,
            ),
        )
        monkeypatch.setattr(vector_engine, "shapely_buffer", stock_buffer)

        result = vector_engine._normalize_contours_many([source])

        assert [call[0] for call in buffer_calls] == [0.03]
        assert result[0] is not None

    def test_dense_batch_uses_stock_negative_when_inward_helper_fails(
        self,
        monkeypatch,
    ):
        source = MultiPolygon([box(0, 0, 1, 1), box(3, 0, 4, 1)])
        inflated = source.buffer(0.03, quad_segs=1, join_style="mitre", mitre_limit=2.0)
        buffer_calls = []

        def stock_buffer(geometries, distance, **kwargs):
            items = list(geometries)
            buffer_calls.append((distance, items))
            return np.asarray(
                [geometry.buffer(distance, **kwargs) for geometry in items],
                dtype=object,
            )

        monkeypatch.setattr(vector_engine.geos_buffer_fast, "MIN_DENSE_COMPONENTS", 2)
        monkeypatch.setattr(
            vector_engine.geos_buffer_fast,
            "try_dense_positive_buffer",
            lambda _geometry, _settings: inflated,
        )
        monkeypatch.setattr(
            vector_engine.geos_buffer_fast,
            "try_disconnected_inward_buffer",
            lambda _geometry, _settings, **_kwargs: None,
        )
        monkeypatch.setattr(vector_engine, "shapely_buffer", stock_buffer)

        result = vector_engine._normalize_contours_many([source])

        assert [call[0] for call in buffer_calls] == [-0.03]
        assert result[0].symmetric_difference(source).is_empty

    def test_dense_scalar_uses_both_helpers(self, monkeypatch):
        source = MultiPolygon([box(0, 0, 1, 1), box(3, 0, 4, 1)])
        inflated = source.buffer(0.03, quad_segs=1, join_style="mitre", mitre_limit=2.0)
        deflated = inflated.buffer(-0.03, quad_segs=1, join_style="mitre", mitre_limit=2.0)
        calls = []
        monkeypatch.setattr(vector_engine.geos_buffer_fast, "MIN_DENSE_COMPONENTS", 2)
        monkeypatch.setattr(
            vector_engine.geos_buffer_fast,
            "try_dense_positive_buffer",
            lambda geometry, settings: calls.append(("positive", geometry, settings))
            or inflated,
        )
        monkeypatch.setattr(
            vector_engine.geos_buffer_fast,
            "try_disconnected_inward_buffer",
            lambda geometry, settings, **_kwargs: calls.append(
                ("inward", geometry, settings)
            )
            or deflated,
        )

        result = VectorProcessor._normalize_contours(source, close_delta_mm=0.03)

        assert [call[0] for call in calls] == ["positive", "inward"]
        assert result.symmetric_difference(deflated).is_empty

    def test_parse_svg_preserves_normalized_marker_on_final_shapes(self):
        svg = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">'
            '  <rect x="1" y="1" width="10" height="10" fill="rgb(255,0,0)"/>'
            "</svg>"
        )
        fd, path = tempfile.mkstemp(suffix=".svg")
        try:
            with os.fdopen(fd, "w") as handle:
                handle.write(svg)
            vp = VectorProcessor.__new__(VectorProcessor)
            vp.sampling_precision = 0.02

            shapes, _scale, _bbox = vp._parse_svg(path, target_width_mm=20.0)
        finally:
            os.unlink(path)

        assert shapes
        assert shapes[0]["geometry_normalized"] is True

    def test_parse_svg_batches_fill_contour_normalization(self, monkeypatch):
        svg = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">'
            '  <rect x="1" y="1" width="4" height="4" fill="rgb(255,0,0)"/>'
            '  <rect x="10" y="1" width="4" height="4" fill="rgb(0,0,255)"/>'
            "</svg>"
        )
        calls = []

        def fake_normalize_many(geometries, close_delta_mm=0.03):
            calls.append((list(geometries), close_delta_mm))
            return list(geometries)

        monkeypatch.setattr(vector_engine, "_normalize_contours_many", fake_normalize_many)
        fd, path = tempfile.mkstemp(suffix=".svg")
        try:
            with os.fdopen(fd, "w") as handle:
                handle.write(svg)
            vp = VectorProcessor.__new__(VectorProcessor)
            vp.sampling_precision = 0.02

            shapes, _scale, _bbox = vp._parse_svg(path, target_width_mm=20.0)
        finally:
            os.unlink(path)

        assert len(calls) == 1
        assert calls[0][1] == 0.03
        assert len(calls[0][0]) == 2
        assert [shape["color"] for shape in shapes] == [(255, 0, 0), (0, 0, 255)]
        assert all(shape["geometry_normalized"] is True for shape in shapes)

    def test_parse_svg_bypasses_as_subpaths_for_single_subpath_paths(self, monkeypatch):
        svg = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">'
            '  <path fill="rgb(255,0,0)" d="M 1 1 L 10 1 L 10 10 L 1 10 Z"/>'
            "</svg>"
        )
        calls = []
        real_as_subpaths = SvgPath.as_subpaths

        def spy_as_subpaths(self):
            calls.append(self)
            return real_as_subpaths(self)

        monkeypatch.setattr(SvgPath, "as_subpaths", spy_as_subpaths)
        fd, path = tempfile.mkstemp(suffix=".svg")
        try:
            with os.fdopen(fd, "w") as handle:
                handle.write(svg)
            vp = VectorProcessor.__new__(VectorProcessor)
            vp.sampling_precision = 0.02

            shapes, _scale, _bbox = vp._parse_svg(path, target_width_mm=20.0)
        finally:
            os.unlink(path)

        assert len(shapes) == 1
        assert shapes[0]["color"] == (255, 0, 0)
        assert shapes[0]["poly"].area == pytest.approx(81.0)
        assert calls == []

    def test_parse_svg_drops_normalized_marker_when_simplify_changes_shape(self):
        svg = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">'
            '  <path fill="rgb(255,0,0)" '
            'd="M 1 1 L 10 1 L 10 10 L 5 10.001 L 1 10 Z"/>'
            "</svg>"
        )
        fd, path = tempfile.mkstemp(suffix=".svg")
        try:
            with os.fdopen(fd, "w") as handle:
                handle.write(svg)
            vp = VectorProcessor.__new__(VectorProcessor)
            vp.sampling_precision = 0.02

            shapes, _scale, _bbox = vp._parse_svg(path, target_width_mm=20.0)
        finally:
            os.unlink(path)

        assert shapes
        assert "geometry_normalized" not in shapes[0]

    def test_parse_svg_filters_ignored_stroke_only_paths_before_svg_parse(self, monkeypatch):
        svg = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">'
            '  <path d="M 0 10 L 20 10" fill="none" stroke="#0000ff" stroke-width="2"/>'
            '  <path d="M 1 1 L 10 1 L 10 10 L 1 10 Z" fill="#ff0000" stroke="none"/>'
            "</svg>"
        )
        fd, path = tempfile.mkstemp(suffix=".svg")
        original_parse = vector_engine.SVG.parse
        parsed_fill_none_counts = []

        def spy_parse(source, *args, **kwargs):
            if hasattr(source, "read"):
                payload = source.read()
                if isinstance(payload, str):
                    payload_bytes = payload.encode("utf-8")
                else:
                    payload_bytes = payload
                parse_source = io.BytesIO(payload_bytes)
            else:
                payload_bytes = open(source, "rb").read()
                parse_source = io.BytesIO(payload_bytes)
            root = ET.fromstring(payload_bytes)
            parsed_fill_none_counts.append(
                sum(
                    1
                    for elem in root.iter()
                    if elem.tag.split("}")[-1] == "path"
                    and str(elem.get("fill", "")).strip().lower() == "none"
                )
            )
            return original_parse(parse_source, *args, **kwargs)

        try:
            with os.fdopen(fd, "w") as handle:
                handle.write(svg)
            vp = VectorProcessor.__new__(VectorProcessor)
            vp.sampling_precision = 0.02
            vp._parse_expand_stroke_to_fill = False
            monkeypatch.setattr(vector_engine.SVG, "parse", spy_parse)

            shapes, _scale, _bbox = vp._parse_svg(path, target_width_mm=20.0)
        finally:
            os.unlink(path)

        assert parsed_fill_none_counts == [0]
        assert [shape["color"] for shape in shapes] == [(255, 0, 0)]

    def test_parse_svg_directly_parses_strict_top_level_paths_without_svg_parse(self, monkeypatch):
        svg = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">'
            '  <path class="qq3d-gap-filler" d="M 0 10 L 20 10" '
            'fill="none" stroke="#0000ff" stroke-width="2"/>'
            '  <path d="M 1 1 L 10 1 L 10 10 L 1 10 Z" '
            'fill="#ff0000" fill-rule="evenodd" stroke="none"/>'
            "</svg>"
        )
        fd, path = tempfile.mkstemp(suffix=".svg")

        def fail_svg_parse(*_args, **_kwargs):
            raise AssertionError("strict generated path SVG should bypass SVG.parse")

        try:
            with os.fdopen(fd, "w") as handle:
                handle.write(svg)
            vp = VectorProcessor.__new__(VectorProcessor)
            vp.sampling_precision = 0.02
            vp._parse_expand_stroke_to_fill = False
            monkeypatch.setattr(vector_engine.SVG, "parse", fail_svg_parse)

            shapes, scale, bbox = vp._parse_svg(path, target_width_mm=20.0)
        finally:
            os.unlink(path)

        assert len(shapes) == 1
        assert shapes[0]["color"] == (255, 0, 0)
        assert shapes[0]["geometry_normalized"] is True
        assert scale == pytest.approx(1.0)
        assert bbox == pytest.approx((0.0, 0.0, 20.0, 20.0))

    @pytest.mark.parametrize(
        ("case_name", "opacity_markup"),
        [
            ("fill_opacity", 'fill-opacity="0"'),
            ("opacity", 'opacity="0"'),
            ("style_opacity", 'style="opacity:0"'),
            ("visibility_hidden", 'visibility="hidden"'),
            ("style_visibility_hidden", 'style="visibility:hidden"'),
            ("style_visibility_hidden_important", 'style="visibility:hidden!important"'),
            ("display_none", 'display="none"'),
            ("style_display_none", 'style="display:none"'),
            ("style_display_none_important", 'style="display:none!important"'),
        ],
    )
    def test_direct_parser_falls_back_for_path_visibility(
        self,
        tmp_path,
        monkeypatch,
        case_name,
        opacity_markup,
    ):
        svg_path = tmp_path / f"transparent_{case_name}.svg"
        svg_path.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">'
            f'  <path d="M 0 0 L 20 0 L 20 20 L 0 20 Z" fill="#000000" '
            f'fill-rule="nonzero" {opacity_markup}/>'
            '  <path d="M 1 1 L 10 1 L 10 10 L 1 10 Z" fill="#ff0000" '
            'fill-rule="nonzero"/>'
            "</svg>",
            encoding="utf-8",
        )
        original_parse = vector_engine.SVG.parse
        parse_calls = []

        def spy_parse(source, *args, **kwargs):
            parse_calls.append(source)
            return original_parse(source, *args, **kwargs)

        vp = VectorProcessor.__new__(VectorProcessor)
        vp.sampling_precision = 0.02
        vp._parse_expand_stroke_to_fill = False
        monkeypatch.setattr(vector_engine.SVG, "parse", spy_parse)

        shapes, _scale, _bbox = vp._parse_svg(str(svg_path), target_width_mm=20.0)

        assert parse_calls
        assert [shape["color"] for shape in shapes] == [(255, 0, 0)]

    @pytest.mark.parametrize(
        ("case_name", "group_markup"),
        [
            ("group_visibility_hidden", 'visibility="hidden"'),
            ("group_style_visibility_hidden", 'style="visibility:hidden"'),
        ],
    )
    def test_svg_parser_skips_group_hidden_paths(
        self,
        tmp_path,
        case_name,
        group_markup,
    ):
        svg_path = tmp_path / f"hidden_{case_name}.svg"
        svg_path.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">'
            f'  <g {group_markup}>'
            '    <path d="M 0 0 L 20 0 L 20 20 L 0 20 Z" fill="#000000" '
            'fill-rule="nonzero"/>'
            "  </g>"
            '  <path d="M 1 1 L 10 1 L 10 10 L 1 10 Z" fill="#ff0000" '
            'fill-rule="nonzero"/>'
            "</svg>",
            encoding="utf-8",
        )

        vp = VectorProcessor.__new__(VectorProcessor)
        vp.sampling_precision = 0.02
        vp._parse_expand_stroke_to_fill = False

        shapes, _scale, _bbox = vp._parse_svg(str(svg_path), target_width_mm=20.0)

        assert [shape["color"] for shape in shapes] == [(255, 0, 0)]

    def test_root_display_none_returns_no_valid_shapes(self, tmp_path):
        svg_path = tmp_path / "root_display_none.svg"
        svg_path.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" display="none">'
            '  <path d="M 0 0 L 20 0 L 20 20 L 0 20 Z" fill="#000000" '
            'fill-rule="nonzero"/>'
            "</svg>",
            encoding="utf-8",
        )
        vp = VectorProcessor.__new__(VectorProcessor)
        vp.sampling_precision = 0.02
        vp._parse_expand_stroke_to_fill = False

        with pytest.raises(ValueError, match="No valid shapes found in SVG"):
            vp._parse_svg(str(svg_path), target_width_mm=20.0)

    def test_direct_parser_rejects_group_svg_before_gap_filter(self, tmp_path, monkeypatch):
        svg_path = tmp_path / "grouped.svg"
        svg_path.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">'
            '  <g>'
            '    <path class="qq3d-gap-filler" d="M 0 10 L 20 10" '
            'fill="none" stroke="#0000ff" stroke-width="2"/>'
            '    <path d="M 1 1 L 10 1 L 10 10 L 1 10 Z" '
            'fill="#ff0000" fill-rule="evenodd" stroke="none"/>'
            '  </g>'
            "</svg>",
            encoding="utf-8",
        )

        def fail_gap_filter(_svg_path):
            raise AssertionError("grouped SVG should be rejected before gap-filler filtering")

        vp = VectorProcessor.__new__(VectorProcessor)
        vp.sampling_precision = 0.02
        monkeypatch.setattr(vector_engine, "_fast_filtered_gap_filler_svg_source", fail_gap_filter)

        result = vector_engine._try_parse_strict_top_level_path_svg(
            vp,
            str(svg_path),
            target_width_mm=20.0,
        )

        assert result is None

    def test_parse_svg_fast_filters_simple_gap_fillers_without_xml_parse(self, monkeypatch):
        svg = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">'
            '  <path d="M 0 10 L 20 10" class="qq3d-gap-filler" '
            'fill="none" stroke="#0000ff" stroke-width="2"/>'
            '  <path d="M 1 1 L 10 1 L 10 10 L 1 10 Z" fill="#ff0000" stroke="none"/>'
            "</svg>"
        )
        fd, path = tempfile.mkstemp(suffix=".svg")
        original_parse = vector_engine.SVG.parse
        parsed_fill_none_counts = []

        def fail_et_parse(_path):
            raise AssertionError("simple gap-filler prefilter should avoid ET.parse")

        def spy_parse(source, *args, **kwargs):
            if hasattr(source, "read"):
                payload = source.read()
                if isinstance(payload, str):
                    payload_bytes = payload.encode("utf-8")
                else:
                    payload_bytes = payload
                parse_source = io.BytesIO(payload_bytes)
            else:
                payload_bytes = open(source, "rb").read()
                parse_source = io.BytesIO(payload_bytes)
            root = ET.fromstring(payload_bytes)
            parsed_fill_none_counts.append(
                sum(
                    1
                    for elem in root.iter()
                    if elem.tag.split("}")[-1] == "path"
                    and str(elem.get("fill", "")).strip().lower() == "none"
                )
            )
            return original_parse(parse_source, *args, **kwargs)

        try:
            with os.fdopen(fd, "w") as handle:
                handle.write(svg)
            vp = VectorProcessor.__new__(VectorProcessor)
            vp.sampling_precision = 0.02
            vp._parse_expand_stroke_to_fill = False
            monkeypatch.setattr(vector_engine.ET, "parse", fail_et_parse)
            monkeypatch.setattr(vector_engine.SVG, "parse", spy_parse)

            shapes, _scale, _bbox = vp._parse_svg(path, target_width_mm=20.0)
        finally:
            os.unlink(path)

        assert parsed_fill_none_counts == [0]
        assert [shape["color"] for shape in shapes] == [(255, 0, 0)]

    def test_gap_filler_fast_filter_targets_gap_paths_without_broad_path_scan(
        self,
        tmp_path,
        monkeypatch,
    ):
        svg_path = tmp_path / "gap.svg"
        svg_path.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">'
            '  <path d="M 0 10 L 20 10" class="qq3d-gap-filler" '
            'fill="none" stroke="#0000ff" stroke-width="2"/>'
            '  <path d="M 1 1 L 10 1 L 10 10 L 1 10 Z" fill="#ff0000" stroke="none"/>'
            "</svg>",
            encoding="utf-8",
        )

        class FailBroadPathScan:
            def sub(self, *_args, **_kwargs):
                raise AssertionError("gap filler filter should not scan every self-closing path")

        monkeypatch.setattr(
            vector_engine,
            "_SVG_FAST_FILTER_SELF_CLOSING_PATH_RE",
            FailBroadPathScan(),
        )

        filtered = vector_engine._fast_filtered_gap_filler_svg_source(str(svg_path))

        assert filtered is not None
        payload = filtered.getvalue()
        assert b"qq3d-gap-filler" not in payload
        assert b'fill="#ff0000"' in payload

    def test_gap_filler_common_layout_skips_per_tag_regexes(
        self,
        tmp_path,
        monkeypatch,
    ):
        svg_path = tmp_path / "common-gap.svg"
        svg_path.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">'
            '  <path class="qq3d-gap-filler" d="M 0 0 L 20 0 L 20 20 Z" '
            'fill="none" stroke="#0000ff" stroke-width="2" '
            'stroke-linejoin="round" stroke-linecap="round" '
            'vector-effect="non-scaling-stroke"/>'
            '  <path d="M 1 1 L 10 1 L 10 10 L 1 10 Z" fill="#ff0000" stroke="none"/>'
            "</svg>",
            encoding="utf-8",
        )

        class FailSearchRegex:
            def search(self, *_args, **_kwargs):
                raise AssertionError("common generated gap-filler should avoid per-tag regexes")

        class FailMatchRegex:
            def match(self, *_args, **_kwargs):
                raise AssertionError("common generated gap-filler should avoid per-tag regexes")

        monkeypatch.setattr(vector_engine, "_SVG_FAST_FILTER_PATH_TAG_PREFIX_RE", FailMatchRegex())
        monkeypatch.setattr(vector_engine, "_SVG_FAST_FILTER_GAP_FILLER_CLASS_RE", FailSearchRegex())
        monkeypatch.setattr(vector_engine, "_SVG_FAST_FILTER_FILL_NONE_RE", FailSearchRegex())
        monkeypatch.setattr(vector_engine, "_SVG_FAST_FILTER_ID_ATTR_RE", FailSearchRegex())

        filtered = vector_engine._fast_filtered_gap_filler_svg_source(str(svg_path))

        assert filtered is not None
        payload = filtered.getvalue()
        assert b"qq3d-gap-filler" not in payload
        assert b'fill="#ff0000"' in payload

    def test_gap_filler_common_layout_preserves_id_paths(self, tmp_path):
        svg_path = tmp_path / "gap-with-id.svg"
        svg_path.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">'
            '  <path class="qq3d-gap-filler" d="M 0 0 L 20 0 L 20 20 Z" '
            'id="keep-me" fill="none" stroke="#0000ff" stroke-width="2" '
            'stroke-linejoin="round" stroke-linecap="round" '
            'vector-effect="non-scaling-stroke"/>'
            "</svg>",
            encoding="utf-8",
        )

        filtered = vector_engine._fast_filtered_gap_filler_svg_source(str(svg_path))

        assert filtered is None

    def test_parse_svg_reuses_filtered_xml_root_for_gradient_defs(self, monkeypatch):
        svg = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">'
            '  <rect x="1" y="1" width="10" height="10" fill="#ff0000"/>'
            "</svg>"
        )
        fd, path = tempfile.mkstemp(suffix=".svg")
        seen_roots = []

        def spy_parse_gradient_defs(_svg_path, *, root=None):
            seen_roots.append(root)
            return {}

        try:
            with os.fdopen(fd, "w") as handle:
                handle.write(svg)
            vp = VectorProcessor.__new__(VectorProcessor)
            vp.sampling_precision = 0.02
            monkeypatch.setattr(
                VectorProcessor,
                "_parse_gradient_defs",
                staticmethod(spy_parse_gradient_defs),
            )

            shapes, _scale, _bbox = vp._parse_svg(path, target_width_mm=20.0)
        finally:
            os.unlink(path)

        assert shapes
        assert len(seen_roots) == 1
        assert seen_roots[0] is not None
        assert seen_roots[0].tag.endswith("svg")

    def test_parse_gradient_defs_uses_provided_xml_root_without_reparsing(self, monkeypatch):
        root = ET.fromstring(
            '<svg xmlns="http://www.w3.org/2000/svg">'
            '  <defs>'
            '    <linearGradient id="g">'
            '      <stop offset="0%" stop-color="#000000"/>'
            '      <stop offset="100%" stop-color="#ffffff"/>'
            "    </linearGradient>"
            "  </defs>"
            "</svg>"
        )

        def fail_parse(_path):
            raise AssertionError("provided XML root should avoid ET.parse")

        monkeypatch.setattr(vector_engine.ET, "parse", fail_parse)

        gradients = VectorProcessor._parse_gradient_defs("unused.svg", root=root)

        assert sorted(gradients) == ["g"]
        assert gradients["g"]["type"] == "linear"
        assert gradients["g"]["stops"] == [(0.0, (0, 0, 0)), (1.0, (255, 255, 255))]

    def test_normalize_contours_skips_make_valid_for_valid_polygon(self, monkeypatch):
        geom = Polygon([(0, 0), (20, 0), (20, 20), (0, 20)])
        calls = []

        def spy_make_valid(input_geom):
            calls.append(input_geom)
            return input_geom

        monkeypatch.setattr(vector_engine, "make_valid", spy_make_valid)

        result = VectorProcessor._normalize_contours(geom, close_delta_mm=0.03)

        assert result is not None
        assert result.is_valid
        assert result.geom_type == "Polygon"
        assert calls == []

    def test_normalize_contours_uses_single_segment_mitre_buffers(self):
        class _FakeGeometry:
            def __init__(self, name):
                self.name = name
                self.is_empty = False
                self.is_valid = True
                self.geom_type = "Polygon"
                self.buffer_calls = []

            def buffer(self, distance, **kwargs):
                self.buffer_calls.append((distance, kwargs))
                if self.name == "source":
                    return inflated
                return deflated

        source = _FakeGeometry("source")
        inflated = _FakeGeometry("inflated")
        deflated = _FakeGeometry("deflated")

        result = VectorProcessor._normalize_contours(source, close_delta_mm=0.03)

        assert result is deflated
        assert source.buffer_calls == [
            (
                0.03,
                {
                    "quad_segs": 1,
                    "join_style": "mitre",
                    "mitre_limit": 2.0,
                },
            )
        ]
        assert inflated.buffer_calls == [
            (
                -0.03,
                {
                    "quad_segs": 1,
                    "join_style": "mitre",
                    "mitre_limit": 2.0,
                },
            )
        ]


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
# Regression: Hue-aware SVG color matching
# ---------------------------------------------------------------------------


class TestHueAwareVectorColorMatching:
    """Verify SVG-native matching uses the shared hue-aware matcher."""

    def test_match_colors_uses_hue_aware_matcher_when_available(self):
        class _ForcedHueMatcher:
            def __init__(self):
                self.seen = None

            def match_colors_batch(self, colors):
                self.seen = np.array(colors, copy=True)
                return np.array([1], dtype=np.intp)

        class _FallbackKdtree:
            n = 2

            def query(self, lab):
                return np.array([0.0]), np.array([0])

        class _FakeImageProcessor:
            def __init__(self, hue_matcher):
                self.hue_matcher = hue_matcher
                self.kdtree = _FallbackKdtree()
                self.lut_rgb = np.array(
                    [[0, 0, 0], [80, 70, 140]],
                    dtype=np.uint8,
                )
                self.lut_lab = self.lut_rgb.astype(np.float64)
                self.ref_stacks = np.array(
                    [[0, 0, 0, 0, 0], [1, 1, 1, 1, 1]],
                    dtype=np.int32,
                )

            @staticmethod
            def _rgb_to_lab(arr):
                return np.asarray(arr, dtype=np.float64)

        hue_matcher = _ForcedHueMatcher()
        vp = VectorProcessor.from_img_processor(
            _FakeImageProcessor(hue_matcher),
            "6-Color (RYBWGK 1296)",
        )
        clipped = [
            {
                "geometry": Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]),
                "color": (46, 30, 67),
            }
        ]

        matched = vp._match_colors(
            clipped,
            replacement_manager=None,
            num_channels=2,
            num_layers=5,
        )

        assert hue_matcher.seen.tolist() == [[46, 30, 67]]
        assert matched[0]["lut_idx"] == 1
        assert matched[0]["matched_rgb"] == (80, 70, 140)
        assert matched[0]["recipe"] == [1, 1, 1, 1, 1]

    def test_match_colors_keeps_pre_replacement_identity_and_recipe(self):
        from core.color_replacement import ColorReplacementManager

        class _NearestKdtree:
            n = 2

            def query(self, lab):
                values = np.asarray(lab, dtype=np.float64).reshape(-1, 3)
                palette = np.asarray(
                    [[255, 0, 0], [0, 0, 255]],
                    dtype=np.float64,
                )
                distances = np.linalg.norm(
                    values[:, None, :] - palette[None, :, :],
                    axis=2,
                )
                indices = np.argmin(distances, axis=1)
                return distances[np.arange(len(values)), indices], indices

        processor = SimpleNamespace(
            hue_matcher=None,
            kdtree=_NearestKdtree(),
            lut_rgb=np.asarray([[255, 0, 0], [0, 0, 255]], dtype=np.uint8),
            lut_lab=np.asarray([[255, 0, 0], [0, 0, 255]], dtype=np.float64),
            ref_stacks=np.asarray(
                [[0, 0, 0, 0, 0], [1, 1, 1, 1, 1]],
                dtype=np.int16,
            ),
            _rgb_to_lab=lambda rgb: np.asarray(rgb, dtype=np.float64),
        )
        vector_processor = VectorProcessor.from_img_processor(processor, "Unit")
        replacement_manager = ColorReplacementManager.from_dict(
            {"#ff0000": "#0000ff"}
        )

        matched = vector_processor._match_colors(
            [
                {
                    "geometry": box(0, 0, 1, 1),
                    "color": (255, 0, 0),
                }
            ],
            replacement_manager=replacement_manager,
            num_channels=2,
            num_layers=5,
        )

        assert matched[0]["matched_rgb"] == (0, 0, 255)
        assert matched[0]["recipe"] == [1, 1, 1, 1, 1]
        assert matched[0]["height_identity_rgb"] == (255, 0, 0)
        assert matched[0]["original_recipe"] == [0, 0, 0, 0, 0]
        assert "original_lut_idx" not in matched[0]


class TestVectorNearFillConsistency:
    """Nearby flat SVG fills should share one vector LUT query."""

    class _NearestKdtree:
        def __init__(self, lut_rgb):
            self.lut_rgb = np.asarray(lut_rgb, dtype=np.float64)
            self.n = len(lut_rgb)

        def query(self, lab):
            lab = np.asarray(lab, dtype=np.float64).reshape(-1, 3)
            dist = np.linalg.norm(
                lab[:, None, :] - self.lut_rgb[None, :, :],
                axis=2,
            )
            index = np.argmin(dist, axis=1)
            return dist[np.arange(len(lab)), index], index

    class _FakeImageProcessor:
        lut_path = "fake.npy"
        color_mode = "Unit"
        hue_matcher = None
        layer_count = 5
        lut_rgb = np.array(
            [
                [100, 100, 100],
                [101, 100, 100],
                [104, 100, 100],
            ],
            dtype=np.uint8,
        )
        ref_stacks = np.array(
            [
                [0, 0, 0, 0, 0],
                [1, 1, 1, 1, 1],
                [2, 2, 2, 2, 2],
            ],
            dtype=np.int32,
        )
        color_conf = {
            "slots": ["A", "B", "C"],
            "preview": {
                0: [100, 100, 100, 255],
                1: [101, 100, 100, 255],
                2: [104, 100, 100, 255],
            },
            "map": {"A": 0, "B": 1, "C": 2},
        }
        slot_names = ["A", "B", "C"]
        preview_colors = color_conf["preview"]

        def __init__(self):
            self.kdtree = TestVectorNearFillConsistency._NearestKdtree(
                self.lut_rgb
            )

        @staticmethod
        def _rgb_to_lab(arr):
            return np.asarray(arr, dtype=np.float64).reshape(-1, 3)

    def _processor(self):
        return VectorProcessor.from_img_processor(
            self._FakeImageProcessor(),
            "Unit",
        )

    def _write_svg(self, tmp_path, fills):
        rects = []
        for idx, fill in enumerate(fills):
            rects.append(
                f'<rect x="{idx * 10}" y="0" width="10" height="10" fill="{fill}"/>'
            )
        path = tmp_path / "near-fill.svg"
        path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 30 10">'
            + "".join(rects)
            + "</svg>",
            encoding="utf-8",
        )
        return path

    def test_nearby_svg_fills_share_one_matched_color(self, tmp_path):
        from core.pipeline.pipeline_utils import extract_color_palette

        svg_path = self._write_svg(tmp_path, ["#646464", "#656464"])
        analysis = self._processor().analyze_svg(str(svg_path), target_width_mm=30.0)

        assert analysis.stage_timings["contour_normalize_s"] >= 0.0
        assert analysis.stage_timings["occlusion_s"] >= analysis.stage_timings["contour_normalize_s"]
        matched_shapes = analysis.matched_shapes
        assert {tuple(item["color"]) for item in matched_shapes} == {
            (100, 100, 100),
            (101, 100, 100),
        }
        assert {tuple(item["match_color"]) for item in matched_shapes} == {
            (100, 100, 100)
        }
        assert {tuple(item["matched_rgb"]) for item in matched_shapes} == {
            (100, 100, 100)
        }
        assert {tuple(item["recipe"]) for item in matched_shapes} == {
            (0, 0, 0, 0, 0)
        }

        cache = VectorProcessor.build_preview_cache(
            analysis,
            pixels_per_mm=1.0,
            supersample_preview=1,
        )
        assert cache["matched_rgb"] is cache["original_matched_rgb"]
        assert cache["matched_rgb"] is cache["height_identity_rgb"]
        assert cache["material_matrix"] is cache["original_material_matrix"]
        solid_matched = cache["matched_rgb"][cache["mask_solid"]].reshape(-1, 3)
        assert {
            tuple(int(v) for v in row)
            for row in np.unique(solid_matched, axis=0)
        } == {(100, 100, 100)}

        palette = extract_color_palette(cache)
        assert [entry["hex"] for entry in palette] == ["#646464"]

    def test_fill_difference_above_threshold_stays_distinct(self, tmp_path):
        svg_path = self._write_svg(tmp_path, ["#646464", "#686464"])
        analysis = self._processor().analyze_svg(str(svg_path), target_width_mm=30.0)

        assert {tuple(item["match_color"]) for item in analysis.matched_shapes} == {
            (100, 100, 100),
            (104, 100, 100),
        }
        assert {tuple(item["matched_rgb"]) for item in analysis.matched_shapes} == {
            (100, 100, 100),
            (104, 100, 100),
        }

    def test_center_representative_does_not_chain_merge_distant_endpoints(self):
        processor = self._processor()
        shapes = [
            {"color": (100, 100, 100), "geometry": box(0, 0, 1, 1)},
            {"color": (102, 100, 100), "geometry": box(0, 0, 10, 10)},
            {"color": (104, 100, 100), "geometry": box(0, 0, 1, 1)},
        ]

        updated = processor._with_near_fill_match_queries(shapes)

        assert [
            tuple(item.get("match_color", item["color"]))
            for item in updated
        ] == [
            (102, 100, 100),
            (102, 100, 100),
            (104, 100, 100),
        ]
        assert "match_color" not in shapes[0]
        assert "match_color" not in shapes[2]

    def test_many_distinct_fills_do_not_scan_every_prior_group(self, monkeypatch):
        processor = self._processor()
        colors = [
            (red, green, blue)
            for red in range(0, 241, 20)
            for green in range(0, 241, 20)
            for blue in range(0, 241, 20)
        ][:216]
        shapes = [
            {"color": color, "geometry": box(0, 0, 1, 1)}
            for color in colors
        ]
        norm_calls = 0
        original_norm = vector_engine.np.linalg.norm

        def counted_norm(*args, **kwargs):
            nonlocal norm_calls
            norm_calls += 1
            return original_norm(*args, **kwargs)

        monkeypatch.setattr(vector_engine.np.linalg, "norm", counted_norm)

        updated = processor._with_near_fill_match_queries(shapes)

        assert updated is shapes
        assert norm_calls <= len(colors) * 4

    def test_spatial_grouping_matches_scalar_complete_link_reference(self):
        processor = self._processor()
        rng = np.random.default_rng(20260810)
        random_colors = [
            tuple(int(value) for value in row)
            for row in rng.integers(0, 256, size=(80, 3), dtype=np.uint8)
        ]
        colors = random_colors + [
            (100, 100, 100),
            (101, 100, 100),
            (102, 100, 100),
            (104, 100, 100),
            (200, 200, 200),
            (201, 201, 200),
        ]
        shapes = [
            {
                "color": color,
                "geometry": box(0, 0, 1 + (idx % 7), 1 + (idx % 5)),
            }
            for idx, color in enumerate(colors)
        ]

        stats_by_color = {}
        for idx, item in enumerate(shapes):
            rgb = tuple(item["color"])
            stats = stats_by_color.setdefault(
                rgb,
                {"area": 0.0, "first_index": idx},
            )
            stats["area"] += float(item["geometry"].area)
        ordered_colors = sorted(
            stats_by_color,
            key=lambda rgb: (
                -float(stats_by_color[rgb]["area"]),
                int(stats_by_color[rgb]["first_index"]),
                rgb,
            ),
        )
        representatives = []
        members = []
        expected_by_color = {}
        for rgb in ordered_colors:
            rgb_lab = np.asarray(rgb, dtype=np.float64)
            chosen = None
            for group_idx, representative in enumerate(representatives):
                if all(
                    float(
                        np.linalg.norm(
                            rgb_lab - np.asarray(member, dtype=np.float64)
                        )
                    )
                    <= 2.0
                    for member in members[group_idx]
                ):
                    chosen = representative
                    members[group_idx].append(rgb)
                    break
            if chosen is None:
                representatives.append(rgb)
                members.append([rgb])
                chosen = rgb
            expected_by_color[rgb] = chosen

        updated = processor._with_near_fill_match_queries(shapes)

        assert [
            tuple(item.get("match_color", item["color"]))
            for item in updated
        ] == [expected_by_color[tuple(item["color"])] for item in shapes]


class TestVectorColorDistanceLogging:
    """Verify large-distance diagnostics stay bounded for many SVG colours."""

    class _AlwaysFarKdtree:
        n = 1

        def query(self, _lab):
            return np.array([100.0]), np.array([0])

    class _FakeImageProcessor:
        lut_path = "fake.npy"
        color_mode = "Unit"
        layer_count = 5
        hue_matcher = None
        lut_rgb = np.array([[255, 255, 255]], dtype=np.uint8)
        lut_lab = np.array([[255.0, 255.0, 255.0]], dtype=np.float64)
        ref_stacks = np.array([[0, 0, 0, 0, 0]], dtype=np.int16)

        def __init__(self):
            self.kdtree = TestVectorColorDistanceLogging._AlwaysFarKdtree()

        @staticmethod
        def _rgb_to_lab(arr):
            return np.asarray(arr, dtype=np.float64)

    def test_match_colors_caps_large_distance_warning_records(self):
        vp = VectorProcessor.from_img_processor(
            self._FakeImageProcessor(),
            "Unit",
        )
        clipped = [
            {
                "geometry": Polygon([(idx, 0), (idx + 0.5, 0), (idx + 0.5, 0.5), (idx, 0.5)]),
                "color": (idx, idx + 1, idx + 2),
            }
            for idx in range(10)
        ]

        with mock.patch.object(vector_engine._log, "warning") as warning_spy:
            matched = vp._match_colors(
                clipped,
                replacement_manager=None,
                num_channels=1,
                num_layers=5,
            )

        large_distance_records = [
            call
            for call in warning_spy.call_args_list
            if (call.kwargs.get("extra") or {}).get("event") == "vector_match_color_large_distance"
        ]
        assert len(matched) == 10
        assert len(large_distance_records) == 8


class TestVectorNegativeSpacePreview:
    """Verify SVG transparent negative space does not display as black."""

    class _NearestKdtree:
        def __init__(self, lut_rgb):
            self.lut_rgb = lut_rgb.astype(np.float64)
            self.n = len(lut_rgb)

        def query(self, lab):
            lab = np.asarray(lab, dtype=np.float64).reshape(-1, 3)
            dist = np.linalg.norm(lab[:, None, :] - self.lut_rgb[None, :, :], axis=2)
            index = np.argmin(dist, axis=1)
            return dist[np.arange(len(lab)), index], index

    class _FakeImageProcessor:
        lut_path = "fake.npy"
        color_mode = "Unit"
        layer_count = 5
        lut_rgb = np.array([[255, 255, 255], [0, 0, 0]], dtype=np.uint8)
        lut_lab = lut_rgb.astype(np.float64)
        ref_stacks = np.array(
            [[0, 0, 0, 0, 0], [1, 1, 1, 1, 1]],
            dtype=np.int16,
        )
        color_conf = {
            "slots": ["White", "Black"],
            "preview": {0: [255, 255, 255, 255], 1: [0, 0, 0, 255]},
            "map": {"White": 0, "Black": 1},
        }
        slot_names = ["White", "Black"]
        preview_colors = color_conf["preview"]
        hue_matcher = None

        def __init__(self, kdtree):
            self.kdtree = kdtree

        @staticmethod
        def _rgb_to_lab(arr):
            return np.asarray(arr, dtype=np.float64)

    def _processor(self):
        return VectorProcessor.from_img_processor(
            self._FakeImageProcessor(self._NearestKdtree(self._FakeImageProcessor.lut_rgb)),
            "Unit",
        )

    def test_enclosed_transparent_hole_displays_white_but_stays_air(self, tmp_path):
        svg_path = tmp_path / "hole.svg"
        svg_path.write_text(
            """
            <svg width="100" height="100" viewBox="0 0 100 100"
                 xmlns="http://www.w3.org/2000/svg">
              <path fill="#000000" fill-rule="evenodd"
                    d="M10 10 H90 V90 H10 Z M40 40 H60 V60 H40 Z"/>
            </svg>
            """,
            encoding="utf-8",
        )

        analysis = self._processor().analyze_svg(str(svg_path), 10.0)
        cache = VectorProcessor.build_preview_cache(
            analysis,
            pixels_per_mm=10.0,
            supersample_preview=1,
        )
        cy = cache["mask_solid"].shape[0] // 2
        cx = cache["mask_solid"].shape[1] // 2

        assert bool(cache["mask_solid"][cy, cx]) is False
        assert cache["matched_rgb"][cy, cx].tolist() == [255, 255, 255]
        assert int(cache["material_matrix"][cy, cx, 0]) == -1

    def test_default_nonzero_reverse_winding_allows_later_white_shape(self, tmp_path):
        svg_path = tmp_path / "nonzero-hole.svg"
        svg_path.write_text(
            """
            <svg width="100" height="100" viewBox="0 0 100 100"
                 xmlns="http://www.w3.org/2000/svg">
              <path fill="#000000"
                    d="M10 10 H90 V90 H10 Z M40 40 V60 H60 V40 Z"/>
              <rect x="42" y="42" width="16" height="16" fill="#ffffff"/>
            </svg>
            """,
            encoding="utf-8",
        )

        analysis = self._processor().analyze_svg(str(svg_path), 10.0)
        cache = VectorProcessor.build_preview_cache(
            analysis,
            pixels_per_mm=10.0,
            supersample_preview=1,
        )
        cy = cache["mask_solid"].shape[0] // 2
        cx = cache["mask_solid"].shape[1] // 2

        assert bool(cache["mask_solid"][cy, cx]) is True
        assert cache["matched_rgb"][cy, cx].tolist() == [255, 255, 255]
        assert int(cache["material_matrix"][cy, cx, 0]) == 0

    def test_transparent_exterior_displays_white_but_stays_air(self, tmp_path):
        svg_path = tmp_path / "square.svg"
        svg_path.write_text(
            """
            <svg width="100" height="100" viewBox="0 0 100 100"
                 xmlns="http://www.w3.org/2000/svg">
              <rect x="40" y="40" width="20" height="20" fill="#000000"/>
            </svg>
            """,
            encoding="utf-8",
        )

        analysis = self._processor().analyze_svg(str(svg_path), 10.0)
        cache = VectorProcessor.build_preview_cache(
            analysis,
            pixels_per_mm=10.0,
            supersample_preview=1,
        )

        assert bool(cache["mask_solid"][0, 0]) is False
        assert cache["matched_rgb"][0, 0].tolist() == [255, 255, 255]
        assert int(cache["material_matrix"][0, 0, 0]) == -1


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

    def test_components_are_not_filtered_without_physical_scale_context(self):
        big = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
        tiny = Polygon([(20, 20), (20.001, 20), (20.001, 20.001), (20, 20.001)])
        mp = MultiPolygon([big, tiny])
        data = [{"poly": mp, "color": (0, 0, 255)}]
        result = VectorProcessor._split_disconnected_shapes(data)
        assert len(result) == 2

    def test_scaled_svg_component_keeps_printable_physical_area(self, tmp_path):
        svg_path = tmp_path / "small-svg-large-print.svg"
        svg_path.write_text(
            """
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1">
              <path d="M0 0H0.1V0.05H0Z" fill="#000000"/>
            </svg>
            """,
            encoding="utf-8",
        )

        processor = TestVectorNegativeSpacePreview()._processor()
        analysis = processor.analyze_svg(
            str(svg_path),
            target_width_mm=200.0,
        )

        assert analysis.scale_factor == pytest.approx(200.0)
        assert len(analysis.clipped_shapes) == 1
        physical_area_mm2 = (
            float(analysis.clipped_shapes[0]["geometry"].area)
            * analysis.scale_factor**2
        )
        assert physical_area_mm2 == pytest.approx(200.0)

        scene = processor.build_mesh(
            analysis,
            thickness_mm=0.16,
            structure_mode="Single-sided",
        )
        black_mesh = scene.geometry["Black"]
        expected_height_mm = analysis.num_layers * 0.08
        assert abs(float(black_mesh.volume)) == pytest.approx(
            200.0 * expected_height_mm
        )

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
        )
        assert "White" in result
        assert "Cyan" in result

    def test_same_run_group_becomes_one_material_with_three_components(self):
        geoms = [
            Polygon([(0, 0), (5, 0), (5, 5), (0, 5)]),
            Polygon([(10, 0), (15, 0), (15, 5), (10, 5)]),
            Polygon([(20, 0), (25, 0), (25, 5), (20, 5)]),
        ]
        matched = [
            {"geometry": geom, "recipe": [0, 0, 0, 0, 0], "color": (255, 255, 255)}
            for geom in geoms
        ]

        result = VectorProcessor._run_length_extrude(
            matched,
            num_layers=5,
            layer_h=0.08,
            num_channels=4,
            slot_names=["White", "Cyan", "Magenta", "Yellow"],
            scale_factor=1.0,
        )

        assert "White" in result
        assert len(result["White"]["meshes"]) == 1
        assert len(
            result["White"]["meshes"][0].split(only_watertight=False)
        ) == 3

    def test_run_group_does_not_create_a_point_touching_hole(self):
        left = Polygon(
            [(0, 0), (2, 0), (1, 2), (2, 2), (2, 4), (0, 4)]
        )
        right = Polygon(
            [(2, 0), (4, 0), (4, 4), (2, 4), (2, 2), (3, 2)]
        )
        matched = [
            {"geometry": left, "recipe": [0], "color": (255, 255, 255)},
            {"geometry": right, "recipe": [0], "color": (255, 255, 255)},
        ]

        result = VectorProcessor._run_length_extrude(
            matched,
            num_layers=1,
            layer_h=0.08,
            num_channels=4,
            slot_names=["White", "Cyan", "Magenta", "Yellow"],
            scale_factor=1.0,
        )

        mesh = result["White"]["meshes"][0]
        assert mesh.is_watertight
        assert abs(float(mesh.volume)) == pytest.approx(
            (left.area + right.area) * 0.08
        )
        assert len(mesh.split(only_watertight=False)) == 1

    def test_materializes_each_material_once_across_adjacent_run_groups(self):
        sq1 = Polygon([(0, 0), (5, 0), (5, 5), (0, 5)])
        sq2 = Polygon([(10, 0), (15, 0), (15, 5), (10, 5)])
        matched = [
            {"geometry": sq1, "recipe": [0, 1, 0], "color": (255, 255, 255)},
            {"geometry": sq2, "recipe": [0, 1, 0], "color": (0, 255, 255)},
        ]
        slab_counts = []
        build_layered_volume = vector_engine.build_vector_layered_volume

        def record_layered_volume(slabs, **kwargs):
            slab_counts.append(len(slabs))
            return build_layered_volume(slabs, **kwargs)

        stepped_spy = mock.Mock(side_effect=record_layered_volume)
        with mock.patch.object(
            vector_engine,
            "build_vector_layered_volume",
            stepped_spy,
        ):
            result = VectorProcessor._run_length_extrude(
                matched,
                num_layers=3,
                layer_h=0.08,
                num_channels=4,
                slot_names=["White", "Cyan", "Magenta", "Yellow"],
                scale_factor=1.0,
            )

        assert "White" in result
        assert "Cyan" in result
        assert stepped_spy.call_count == 2
        assert sorted(slab_counts) == [1, 2]
        assert len(result["White"]["meshes"]) == 1
        assert len(result["Cyan"]["meshes"]) == 1

    def test_run_group_union_falls_back_when_disjoint_subset_union_fails(self):
        geoms = [
            Polygon([(0, 0), (5, 0), (5, 5), (0, 5)]),
            Polygon([(10, 0), (15, 0), (15, 5), (10, 5)]),
        ]

        fast_union = mock.Mock(side_effect=RuntimeError("fast union failed"))
        with mock.patch.dict(
            _union_run_group_geometries.__globals__,
            {"disjoint_subset_union_all": fast_union},
        ):
            result = _union_run_group_geometries(geoms)

        assert fast_union.call_count == 1
        assert result.area == pytest.approx(50.0)


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

    def test_material_gradient_bands_preserve_mid_green(self):
        grad_info = {
            "type": "linear",
            "x1": 0, "y1": 0, "x2": 100, "y2": 0,
            "stops": [(0.0, (255, 255, 0)), (1.0, (0, 255, 255))],
            "units": "userSpaceOnUse",
        }
        poly = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
        result = VectorProcessor._flatten_gradient_shape(grad_info, [poly], color_bands=17)
        colors = {item["color"] for item in result}

        assert len(colors) > 2
        assert any(
            110 <= red <= 145 and green >= 250 and 110 <= blue <= 145
            for red, green, blue in colors
        )


# ---------------------------------------------------------------------------
# Fix 8: fill-rule values fallback + stroke-only element skipping
# ---------------------------------------------------------------------------


class TestFillRuleValuesFallback:
    """fill-rule inherited via SVG root style must be detected from values dict."""

    def _make_svg_with_fillrule(
        self,
        fill_rule_on_root: bool,
        fill_rule_on_element: bool,
        *,
        inner_same_winding: bool = False,
    ):
        """Create a minimal SVG with concentric-circle compound path.

        When *fill_rule_on_root* is True, the SVG root ``<svg>`` has
        ``style="fill-rule:evenodd"``.  When *fill_rule_on_element* is True,
        the ``<path>`` element carries ``fill-rule="evenodd"`` directly.
        """
        root_style = ' style="fill-rule:evenodd;"' if fill_rule_on_root else ""
        elem_attr = ' fill-rule="evenodd"' if fill_rule_on_element else ""
        inner_sweep = "1" if inner_same_winding else "0"
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200"{root_style}>'
            f'  <path{elem_attr} fill="rgb(255,0,0)"'
            '    d="M100,10 A90,90 0 1,1 99.99,10 Z'
            f'      M100,40 A60,60 0 1,{inner_sweep} 100.01,40 Z"/>'
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
        """Same-winding nonzero rings should merge into a solid disc."""
        svg = self._make_svg_with_fillrule(
            fill_rule_on_root=False,
            fill_rule_on_element=False,
            inner_same_winding=True,
        )
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

    def test_transparent_rgba_fill_is_skipped(self):
        """Fully transparent SVG fills must not become black printable shapes."""
        svg = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
            '  <rect x="0" y="0" width="100" height="100" fill="rgba(0,0,0,0)"/>'
            '  <rect x="10" y="10" width="20" height="20" fill="#ff0000"/>'
            "</svg>"
        )
        shapes = self._parse_shapes(svg)
        colors = {s["color"] for s in shapes}
        assert (255, 0, 0) in colors
        assert (0, 0, 0) not in colors

    def test_transparent_rgba_fill_with_visible_stroke_keeps_stroke(self):
        """Transparent fill should be ignored while a visible stroke is still printed."""
        svg = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
            '  <rect x="10" y="10" width="80" height="80" '
            'fill="rgba(0,0,0,0)" stroke="#0000ff" stroke-width="4"/>'
            "</svg>"
        )
        shapes = self._parse_shapes(svg)
        colors = {s["color"] for s in shapes}
        assert (0, 0, 255) in colors
        assert (0, 0, 0) not in colors

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


class TestImageVectorizerViewportBounds:

    def _parse_svg(self, origin_attr: str):
        svg_content = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20"{origin_attr}>'
            '<rect x="0" y="0" width="4" height="20" fill="#ff0000"/>'
            '<rect x="16" y="0" width="4" height="20" fill="#00ffff"/>'
            "</svg>"
        )
        fd, path = tempfile.mkstemp(suffix=".svg")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(svg_content)
            vp = VectorProcessor.__new__(VectorProcessor)
            vp.sampling_precision = 0.02
            vp._parse_svg(path, target_width_mm=20.0)
            return getattr(vp, "_last_image_vectorizer_bounds", None)
        finally:
            os.unlink(path)

    def test_marked_vectorizer_svg_records_full_viewport_bounds(self):
        bounds = self._parse_svg(' data-lumina-origin="image-vectorizer"')

        assert bounds is not None
        assert bounds.bounds == pytest.approx((0.0, 0.0, 20.0, 20.0))

    def test_regular_svg_does_not_record_full_viewport_bounds(self):
        bounds = self._parse_svg("")

        assert bounds is None


def test_parse_svg_does_not_downgrade_memory_error_to_invalid_geometry(
    tmp_path,
    monkeypatch,
):
    """Allocation failure while sampling a path must abort the request."""

    svg_path = tmp_path / "memory-error.svg"
    svg_path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
        '<path d="M0,0 L10,0 L10,10 L0,10 Z" fill="#ff0000"/>'
        "</svg>",
        encoding="utf-8",
    )
    processor = VectorProcessor.__new__(VectorProcessor)
    processor.sampling_precision = 0.02
    processor._parse_expand_stroke_to_fill = True
    processor._parse_single_subpath_fast_path = True
    processor._parse_direct_top_level_paths_fast_path = False

    monkeypatch.setattr(
        vector_engine.Path,
        "segments",
        mock.Mock(side_effect=MemoryError("injected SVG path allocation failure")),
    )

    with pytest.raises(MemoryError, match="injected SVG path allocation failure"):
        processor._parse_svg(str(svg_path), target_width_mm=10.0)


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


# ---------------------------------------------------------------------------
# Degenerate geometry normalization
# ---------------------------------------------------------------------------


class TestDegenerateGeometryRepair:
    """Contour normalization keeps polygonal content deterministic."""

    def test_normalize_extracts_only_polygons_from_geometrycollection(self):
        """_normalize_contours drops non-polygon elements from GC."""
        from shapely.geometry import GeometryCollection, LineString, box

        poly = box(0, 0, 10, 10)
        line = LineString([(0, 0), (10, 10)])
        gc = GeometryCollection([poly, line])

        result = VectorProcessor._normalize_contours(gc, close_delta_mm=0.03)
        assert result is not None
        assert not result.is_empty
        # Result should be a polygon type, not a GeometryCollection
        assert hasattr(result, "exterior"), (
            f"Expected polygon type, got {getattr(result, 'geom_type', type(result).__name__)}"
        )

    def test_normalize_geometrycollection_all_non_polygon_falls_back(self):
        """_normalize_contours falls back when make_valid returns only non-polygon.

        When make_valid produces a GeometryCollection containing ONLY
        non-polygon elements (all LineString / Point), the function
        must fall back to the pre-make_valid polygon state instead of
        returning the useless GeometryCollection, which would leak into
        downstream extrusion and cause silent mesh loss.
        """
        from unittest import mock
        from shapely.geometry import GeometryCollection, LineString, Polygon

        # A valid Polygon input that would normally pass through fine.
        # We monkey-patch make_valid to simulate the degenerate GC case.
        valid_poly = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
        fake_gc = GeometryCollection([
            LineString([(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)]),
            LineString([(5, 5), (5.001, 5.001)]),
        ])

        with mock.patch("core.vector_engine.make_valid", return_value=fake_gc):
            result = VectorProcessor._normalize_contours(valid_poly, close_delta_mm=0.03)

        assert result is not None
        assert not result.is_empty
        # Must return a polygon type, not a GeometryCollection full of lines
        assert hasattr(result, "exterior"), (
            f"Expected polygon type, got {getattr(result, 'geom_type', type(result).__name__)}"
        )

    def test_run_length_extrude_handles_geometrycollection(self):
        """End-to-end: _run_length_extrude with a group containing degenerate GC."""
        from shapely.geometry import GeometryCollection, LineString, box

        # A valid polygon + a degenerate LineString sliver
        poly = box(0, 0, 10, 10)
        degenerate = GeometryCollection([poly, LineString([(5, 5), (5.001, 5.001)])])

        matched = [
            {"geometry": degenerate, "recipe": [0, 0, 0, 0, 0], "color": (255, 255, 255)},
        ]
        result = VectorProcessor._run_length_extrude(
            matched,
            num_layers=5,
            layer_h=0.08,
            num_channels=4,
            slot_names=["White", "Cyan", "Magenta", "Yellow"],
            scale_factor=1.0,
        )
        assert "White" in result
        # Should have at least 1 mesh (the repaired polygon)
        assert len(result["White"]["meshes"]) >= 1
