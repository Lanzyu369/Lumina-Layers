"""Unit tests for the Chroma-aligned vector engine (core/vector_engine.py).

Covers:
    1. Occlusion clipping: reverse-order accumulative difference
    2. Run-length extrusion: consecutive same-channel layers merged
    3. Output ordering: meshes_by_slot sorted by material ID
    4. Public API: analyze_svg, build_mesh, render_preview, svg_to_mesh backward compat
"""

import sys
import os
import types
import importlib.util
import inspect
from unittest.mock import patch

import pytest
import numpy as np
from shapely.geometry import Polygon, box

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from config import PrinterConfig

# Load core.vector_engine directly from its file to avoid the heavy
# core.__init__ import chain.
_spec = importlib.util.spec_from_file_location("core.vector_engine", os.path.join(_ROOT, "core", "vector_engine.py"))
_ve = importlib.util.module_from_spec(_spec)
# Provide a minimal 'core' parent package so relative imports resolve
if "core" not in sys.modules:
    _pkg = types.ModuleType("core")
    _pkg.__path__ = [os.path.join(_ROOT, "core")]
    sys.modules["core"] = _pkg
sys.modules["core.vector_engine"] = _ve
_spec.loader.exec_module(_ve)
VectorProcessor = _ve.VectorProcessor
VectorAnalysis = _ve.VectorAnalysis


# =====================================================================
# Helpers
# =====================================================================


def _rect(x0, y0, x1, y1, color=(255, 0, 0)):
    """Create a shape_data dict compatible with _clip_occlusion input."""
    return {"poly": box(x0, y0, x1, y1), "color": color}


def _make_parse_only_processor(sampling_precision=0.05):
    """Create a VectorProcessor instance without running heavy __init__."""
    vp = object.__new__(VectorProcessor)
    vp.sampling_precision = sampling_precision
    vp.color_mode = "4-Color"
    vp.last_stage_timings = {}
    vp.parse_warnings = []
    vp.enable_fridge_magnet = False
    vp.fridge_magnets = []
    return vp


# =====================================================================
# 1. Occlusion clipping
# =====================================================================


class TestClipOcclusion:
    """Verify ChromaPrint3D-style reverse-order occlusion clipping."""

    def test_no_overlap_preserves_all(self):
        """Non-overlapping shapes should pass through unchanged."""
        shapes = [
            _rect(0, 0, 10, 10, color=(255, 0, 0)),
            _rect(20, 0, 30, 10, color=(0, 255, 0)),
        ]
        result = VectorProcessor._clip_occlusion(shapes)
        assert len(result) == 2
        for r in result:
            assert not r["geometry"].is_empty

    def test_later_shape_covers_earlier(self):
        """Later shape fully covering earlier → earlier completely removed."""
        shapes = [
            _rect(0, 0, 10, 10, color=(255, 0, 0)),  # bottom (draw order 0)
            _rect(0, 0, 10, 10, color=(0, 255, 0)),  # top    (draw order 1)
        ]
        result = VectorProcessor._clip_occlusion(shapes)
        top = [r for r in result if r["color"] == (0, 255, 0)]
        bottom = [r for r in result if r["color"] == (255, 0, 0)]
        assert len(top) == 1
        assert not top[0]["geometry"].is_empty
        assert len(bottom) == 0  # fully occluded

    def test_partial_overlap(self):
        """Partial overlap: earlier shape trimmed, later shape full."""
        shapes = [
            _rect(0, 0, 20, 10, color=(255, 0, 0)),  # bottom, wider
            _rect(5, 0, 15, 10, color=(0, 255, 0)),  # top, narrower overlap
        ]
        result = VectorProcessor._clip_occlusion(shapes)

        top = [r for r in result if r["color"] == (0, 255, 0)]
        bottom = [r for r in result if r["color"] == (255, 0, 0)]

        assert len(top) == 1
        assert len(bottom) == 1

        # Top shape should be fully preserved
        assert abs(top[0]["geometry"].area - 100.0) < 1e-6

        # Bottom shape should be trimmed: original 200 minus overlap 100
        assert abs(bottom[0]["geometry"].area - 100.0) < 1.0

    def test_draw_order_preserved(self):
        """Result list should be in original draw order (bottom → top)."""
        shapes = [
            _rect(0, 0, 10, 10, color=(1, 0, 0)),
            _rect(5, 0, 15, 10, color=(0, 1, 0)),
            _rect(10, 0, 20, 10, color=(0, 0, 1)),
        ]
        result = VectorProcessor._clip_occlusion(shapes)
        orders = [r["draw_order"] for r in result]
        assert orders == sorted(orders), "draw_order should be monotonically increasing"

    def test_empty_input(self):
        result = VectorProcessor._clip_occlusion([])
        assert result == []

    def test_return_silhouette_when_requested(self):
        """When requested, occlusion returns accumulated silhouette geometry."""
        shapes = [
            _rect(0, 0, 10, 10, color=(255, 0, 0)),
            _rect(5, 0, 15, 10, color=(0, 255, 0)),
        ]
        result, silhouette = VectorProcessor._clip_occlusion(shapes, return_silhouette=True)
        assert len(result) == 2
        assert silhouette is not None
        assert not silhouette.is_empty
        # silhouette is union of both input rectangles: 100 + 100 - 50 overlap
        assert abs(silhouette.area - 150.0) < 1e-6

    def test_three_stacked_shapes(self):
        """Three fully stacked shapes: only topmost survives."""
        shapes = [
            _rect(0, 0, 10, 10, color=(1, 0, 0)),
            _rect(0, 0, 10, 10, color=(0, 1, 0)),
            _rect(0, 0, 10, 10, color=(0, 0, 1)),
        ]
        result = VectorProcessor._clip_occlusion(shapes)
        assert len(result) == 1
        assert result[0]["color"] == (0, 0, 1)

    def test_no_small_feature_exemption(self):
        """Even tiny shapes are subject to occlusion — no special exemption."""
        shapes = [
            _rect(0, 0, 1, 1, color=(255, 0, 0)),  # tiny bottom
            _rect(0, 0, 100, 100, color=(0, 255, 0)),  # large top covering it
        ]
        result = VectorProcessor._clip_occlusion(shapes)
        reds = [r for r in result if r["color"] == (255, 0, 0)]
        assert len(reds) == 0, "small feature should be fully occluded"


# =====================================================================
# 2. Run-length extrusion
# =====================================================================


class TestRunLengthExtrude:
    """Verify consecutive same-channel layers are merged into single volumes."""

    LAYER_H = PrinterConfig.LAYER_HEIGHT  # 0.08
    SLOT_NAMES = ["White", "Cyan", "Magenta", "Yellow"]

    def _make_matched(self, geometry, recipe):
        return [{"geometry": geometry, "recipe": recipe, "color": (0, 0, 0)}]

    def test_single_channel_all_layers(self):
        """All 5 layers mapped to channel 1 → single run for channel 1."""
        geom = box(0, 0, 10, 10)
        matched = self._make_matched(geom, [1, 1, 1, 1, 1])

        result = VectorProcessor._run_length_extrude(
            matched,
            num_layers=5,
            layer_h=self.LAYER_H,
            num_channels=4,
            slot_names=self.SLOT_NAMES,
            scale_factor=1.0,
        )

        assert "Cyan" in result
        assert len(result["Cyan"]["meshes"]) == 1  # single merged volume

    def test_alternating_channels_no_merge(self):
        """Alternating recipe [0,1,0,1,0] → no channel gets consecutive layers."""
        geom = box(0, 0, 10, 10)
        matched = self._make_matched(geom, [0, 1, 0, 1, 0])

        result = VectorProcessor._run_length_extrude(
            matched,
            num_layers=5,
            layer_h=self.LAYER_H,
            num_channels=4,
            slot_names=self.SLOT_NAMES,
            scale_factor=1.0,
        )

        white_count = len(result.get("White", {}).get("meshes", []))
        cyan_count = len(result.get("Cyan", {}).get("meshes", []))
        assert white_count == 3  # layers 0, 2, 4 → three separate runs
        assert cyan_count == 2  # layers 1, 3 → two separate runs

    def test_run_merges_consecutive(self):
        """Recipe [2,2,2,0,0] → channel 2 gets one run (layers 0-2),
        channel 0 gets one run (layers 3-4)."""
        geom = box(0, 0, 10, 10)
        matched = self._make_matched(geom, [2, 2, 2, 0, 0])

        result = VectorProcessor._run_length_extrude(
            matched,
            num_layers=5,
            layer_h=self.LAYER_H,
            num_channels=4,
            slot_names=self.SLOT_NAMES,
            scale_factor=1.0,
        )

        assert len(result["Magenta"]["meshes"]) == 1
        assert len(result["White"]["meshes"]) == 1

    def test_material_id_in_result(self):
        """Each slot entry should carry correct mat_id."""
        geom = box(0, 0, 5, 5)
        matched = self._make_matched(geom, [3, 3, 3, 3, 3])

        result = VectorProcessor._run_length_extrude(
            matched,
            num_layers=5,
            layer_h=self.LAYER_H,
            num_channels=4,
            slot_names=self.SLOT_NAMES,
            scale_factor=1.0,
        )

        assert result["Yellow"]["mat_id"] == 3

    def test_empty_geometry_skipped(self):
        """Empty geometry should produce no meshes."""
        geom = Polygon()
        matched = self._make_matched(geom, [0, 0, 0, 0, 0])

        result = VectorProcessor._run_length_extrude(
            matched,
            num_layers=5,
            layer_h=self.LAYER_H,
            num_channels=4,
            slot_names=self.SLOT_NAMES,
            scale_factor=1.0,
        )

        assert len(result) == 0


# =====================================================================
# 3. Output ordering
# =====================================================================


class TestOutputOrdering:
    """Verify meshes_by_slot is sorted by material ID when assembling scene."""

    def test_sorted_by_mat_id(self):
        """Simulated meshes_by_slot should sort by mat_id."""
        meshes_by_slot = {
            "Yellow": {"meshes": ["m"], "mat_id": 3},
            "White": {"meshes": ["m"], "mat_id": 0},
            "Cyan": {"meshes": ["m"], "mat_id": 1},
        }
        sorted_items = sorted(meshes_by_slot.items(), key=lambda x: x[1]["mat_id"])
        names = [name for name, _ in sorted_items]
        assert names == ["White", "Cyan", "Yellow"]


# =====================================================================
# 4. Extrude geometry helper
# =====================================================================


class TestExtrudeGeometry:

    def test_polygon_produces_mesh(self):
        poly = box(0, 0, 10, 10)
        meshes = VectorProcessor._extrude_geometry(poly, height=1.0, z_offset=0, scale=1.0)
        assert len(meshes) == 1
        assert meshes[0].vertices.shape[0] > 0

    def test_multipolygon(self):
        from shapely.ops import unary_union

        mp = unary_union([box(0, 0, 5, 5), box(10, 0, 15, 5)])
        meshes = VectorProcessor._extrude_geometry(mp, height=0.5, z_offset=0, scale=1.0)
        assert len(meshes) == 2

    def test_empty_returns_empty(self):
        meshes = VectorProcessor._extrude_geometry(Polygon(), height=1.0, z_offset=0, scale=1.0)
        assert meshes == []

    def test_none_returns_empty(self):
        meshes = VectorProcessor._extrude_geometry(None, height=1.0, z_offset=0, scale=1.0)
        assert meshes == []

    def test_extrude_cache_reuses_base_mesh(self):
        """Same polygon/height/scale should hit cache and only extrude once."""
        poly = box(0, 0, 10, 10)
        cache = {}

        call_count = {"n": 0}
        real_box = _ve.trimesh.creation.box

        def fake_extrude_polygon(_poly, height):
            call_count["n"] += 1
            # return any valid mesh; dimensions are irrelevant for cache count check
            return real_box(extents=[1, 1, max(height, 1e-6)])

        with patch.object(_ve.trimesh.creation, "extrude_polygon", side_effect=fake_extrude_polygon):
            meshes1 = VectorProcessor._extrude_geometry(poly, height=1.0, z_offset=0.0, scale=1.0, extrude_cache=cache)
            meshes2 = VectorProcessor._extrude_geometry(poly, height=1.0, z_offset=2.0, scale=1.0, extrude_cache=cache)

        assert len(meshes1) == 1
        assert len(meshes2) == 1
        assert call_count["n"] == 1


# =====================================================================
# 5. Fridge magnet cavity helpers
# =====================================================================


class TestFridgeMagnetCavityHelpers:

    def test_centered_mm_to_vector_coords_uses_bbox_and_flips_y(self):
        x, y = VectorProcessor._centered_mm_to_vector_coords(
            center_x_mm=10.0,
            center_y_mm=-5.0,
            bbox=(0.0, 0.0, 40.0, 20.0),
            scale_factor=2.0,
        )

        assert x == pytest.approx(25.0)
        assert y == pytest.approx(12.5)

    def test_build_backing_cavity_slabs_keeps_blind_shell_for_high_outer_side(self):
        backing = box(0, 0, 20, 10)
        cavity = box(8, 3, 12, 7)

        slabs = VectorProcessor._build_backing_cavity_slabs(
            backing_sil=backing,
            backing_z_start=1.0,
            backing_height=2.0,
            cavity_specs=[{"geometry": cavity, "depth_mm": 0.8}],
            outer_side="high",
            shell_thickness_mm=0.4,
        )

        assert [(round(s["z_offset"], 3), round(s["height"], 3)) for s in slabs] == [
            (1.0, 0.8),
            (1.8, 0.8),
            (2.6, 0.4),
        ]
        assert slabs[0]["geometry"].area == pytest.approx(backing.area)
        assert slabs[1]["geometry"].area < backing.area
        assert slabs[2]["geometry"].area == pytest.approx(backing.area)

    def test_build_backing_cavity_slabs_splits_multiple_cavity_depth_bands(self):
        backing = box(0, 0, 20, 10)
        shallow = box(2, 2, 6, 6)
        deep = box(12, 2, 18, 8)

        slabs = VectorProcessor._build_backing_cavity_slabs(
            backing_sil=backing,
            backing_z_start=0.0,
            backing_height=2.0,
            cavity_specs=[
                {"geometry": shallow, "depth_mm": 0.8},
                {"geometry": deep, "depth_mm": 1.2},
            ],
            outer_side="high",
            shell_thickness_mm=0.4,
        )

        reduced_slabs = [slab for slab in slabs if slab["geometry"].area < backing.area]
        assert len(reduced_slabs) == 2
        reduced_areas = [slab["geometry"].area for slab in reduced_slabs]
        assert reduced_areas == pytest.approx(
            [
                backing.difference(deep).area,
                backing.difference(shallow.union(deep)).area,
            ]
        )

    def test_build_vector_fridge_cavity_specs_centers_on_backing_bounds_not_svg_viewbox(self):
        backing = box(5, 5, 15, 15)

        specs = VectorProcessor._build_vector_fridge_cavity_specs(
            backing_sil=backing,
            fridge_magnets=[
                {
                    "id": "magnet-round",
                    "shape": "round",
                    "preset_key": "round-4",
                    "diameter_mm": 4.0,
                    "width_mm": None,
                    "height_mm": None,
                    "thickness_mm": 1.2,
                    "center_x_mm": 0.0,
                    "center_y_mm": 0.0,
                }
            ],
            bbox=(0.0, 0.0, 40.0, 20.0),
            scale_factor=1.0,
            backing_height=2.0,
        )

        assert len(specs) == 1
        assert specs[0]["geometry"].centroid.x == pytest.approx(10.0)
        assert specs[0]["geometry"].centroid.y == pytest.approx(10.0)


class TestVectorPublicApiCompatibility:

    def test_build_mesh_signature_remains_backward_compatible(self):
        params = inspect.signature(VectorProcessor.build_mesh).parameters
        assert list(params) == ["self", "analysis", "thickness_mm", "structure_mode", "progress_fn"]

    def test_svg_to_mesh_signature_remains_backward_compatible(self):
        params = inspect.signature(VectorProcessor.svg_to_mesh).parameters
        assert list(params) == [
            "self",
            "svg_path",
            "target_width_mm",
            "thickness_mm",
            "structure_mode",
            "color_replacements",
            "progress_fn",
        ]


class TestVectorFridgeMagnetBuildMeshRegression:

    def test_build_mesh_reduces_board_volume_when_fridge_magnet_mode_enabled(self):
        processor = _make_parse_only_processor()
        processor.color_mode = "4-Color"
        analysis = VectorAnalysis(
            shape_data=[],
            clipped_shapes=[{"geometry": box(0, 0, 20, 20), "color": (255, 0, 0), "draw_order": 0}],
            matched_shapes=[{"geometry": box(0, 0, 20, 20), "recipe": [1, 1, 1, 1, 1], "color": (255, 0, 0)}],
            silhouette=box(0, 0, 20, 20),
            scale_factor=1.0,
            bbox=(0.0, 0.0, 20.0, 20.0),
            color_conf={},
            slot_names=["White", "Cyan"],
            num_channels=2,
            num_layers=5,
            preview_colors={0: [255, 255, 255, 255], 1: [0, 255, 255, 255]},
            stage_timings={},
        )

        processor.enable_fridge_magnet = False
        processor.fridge_magnets = []
        scene_without_cavity = processor.build_mesh(analysis=analysis, thickness_mm=1.2, structure_mode="Single-sided")
        board_without_cavity = scene_without_cavity.geometry["Board"]

        processor.enable_fridge_magnet = True
        processor.fridge_magnets = [
            {
                "id": "magnet-round",
                "shape": "round",
                "preset_key": "round-8",
                "diameter_mm": 8.0,
                "width_mm": None,
                "height_mm": None,
                "thickness_mm": 0.4,
                "center_x_mm": 0.0,
                "center_y_mm": 0.0,
            }
        ]
        scene_with_cavity = processor.build_mesh(analysis=analysis, thickness_mm=1.2, structure_mode="Single-sided")
        board_with_cavity = scene_with_cavity.geometry["Board"]

        assert board_with_cavity.volume < board_without_cavity.volume
        assert board_with_cavity.bounds[0][0] == pytest.approx(board_without_cavity.bounds[0][0])
        assert board_with_cavity.bounds[1][0] == pytest.approx(board_without_cavity.bounds[1][0])


class TestVectorSingleSidedMirrorRegression:

    def test_build_mesh_mirrors_non_5color_single_sided_x_coordinates(self):
        processor = _make_parse_only_processor()
        processor.color_mode = "8-Color Max"
        analysis = VectorAnalysis(
            shape_data=[],
            clipped_shapes=[],
            matched_shapes=[{"geometry": box(0, 0, 4, 10), "recipe": [1, 1, 1, 1, 1], "color": (0, 255, 255)}],
            silhouette=None,
            scale_factor=1.0,
            bbox=(0.0, 0.0, 10.0, 10.0),
            color_conf={},
            slot_names=["White", "Cyan"],
            num_channels=2,
            num_layers=5,
            preview_colors={0: [255, 255, 255, 255], 1: [0, 255, 255, 255]},
            stage_timings={},
        )

        scene = processor.build_mesh(analysis=analysis, thickness_mm=0.0, structure_mode="Single-sided")
        bounds = scene.geometry["Cyan"].bounds

        assert bounds[0][0] == pytest.approx(6.0)
        assert bounds[1][0] == pytest.approx(10.0)

    def test_build_mesh_does_not_mirror_5color_single_sided_x_coordinates(self):
        processor = _make_parse_only_processor()
        processor.color_mode = "5-Color Extended"
        analysis = VectorAnalysis(
            shape_data=[],
            clipped_shapes=[],
            matched_shapes=[{"geometry": box(0, 0, 4, 10), "recipe": [1, 1, 1, 1, 1, 1], "color": (0, 255, 255)}],
            silhouette=None,
            scale_factor=1.0,
            bbox=(0.0, 0.0, 10.0, 10.0),
            color_conf={},
            slot_names=["White", "Cyan"],
            num_channels=2,
            num_layers=6,
            preview_colors={0: [255, 255, 255, 255], 1: [0, 255, 255, 255]},
            stage_timings={},
        )

        scene = processor.build_mesh(analysis=analysis, thickness_mm=0.0, structure_mode="Single-sided")
        bounds = scene.geometry["Cyan"].bounds

        assert bounds[0][0] == pytest.approx(0.0)
        assert bounds[1][0] == pytest.approx(4.0)


# =====================================================================
# 5. SVG parse regression (multi-subpath)
# =====================================================================


class TestParseSvgSubpaths:

    def test_split_multi_subpath_path_into_multiple_polygons(self, tmp_path):
        """Single <path> with two non-overlapping subpaths: _parse_svg
        returns 1 MultiPolygon; splitting happens post-clip in svg_to_mesh."""
        svg_file = tmp_path / "multi_subpath.svg"
        svg_file.write_text(
            (
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 120">\n'
                '  <path fill="#ff0000" d="'
                "M0,0 L100,0 L100,100 L0,100 Z "
                'M200,0 L300,0 L300,100 L200,100 Z"/>\n'
                "</svg>\n"
            ),
            encoding="utf-8",
        )

        vp = _make_parse_only_processor()
        shapes, scale, bbox = vp._parse_svg(str(svg_file), target_width_mm=100.0)

        assert len(shapes) == 1
        total_area = sum(s["poly"].area for s in shapes)
        assert abs(total_area - 20000.0) < 100.0
        assert all(s["color"] == (255, 0, 0) for s in shapes)
        assert scale > 0
        assert bbox[2] > 0

    def test_parse_falls_back_when_subpath_split_unavailable(self, tmp_path):
        """If as_subpaths fails, parser should still sample whole path."""
        svg_file = tmp_path / "fallback.svg"
        svg_file.write_text(
            (
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120">\n'
                '  <path fill="#00ff00" d="M0,0 L100,0 L100,100 L0,100 Z"/>\n'
                "</svg>\n"
            ),
            encoding="utf-8",
        )

        vp = _make_parse_only_processor()
        with patch.object(_ve.Path, "as_subpaths", side_effect=RuntimeError("boom")):
            shapes, _, _ = vp._parse_svg(str(svg_file), target_width_mm=100.0)

        assert len(shapes) == 1
        assert shapes[0]["poly"].area > 0

    def test_occlusion_keeps_uncovered_large_block(self, tmp_path):
        """Top shape covering only one subpath must not erase the other block."""
        svg_file = tmp_path / "occlusion_regression.svg"
        svg_file.write_text(
            (
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 120">\n'
                '  <path fill="#ff0000" d="'
                "M0,0 L100,0 L100,100 L0,100 Z "
                'M200,0 L300,0 L300,100 L200,100 Z"/>\n'
                '  <path fill="#0000ff" d="M0,0 L100,0 L100,100 L0,100 Z"/>\n'
                "</svg>\n"
            ),
            encoding="utf-8",
        )

        vp = _make_parse_only_processor()
        shapes, _, _ = vp._parse_svg(str(svg_file), target_width_mm=100.0)
        clipped = VectorProcessor._clip_occlusion(shapes)

        red_area = sum(item["geometry"].area for item in clipped if item["color"] == (255, 0, 0))
        blue_area = sum(item["geometry"].area for item in clipped if item["color"] == (0, 0, 255))

        assert abs(red_area - 10000.0) < 5.0
        assert abs(blue_area - 10000.0) < 5.0


# =====================================================================
# 5b. SVG parse regression (Line → Bezier junction)
# =====================================================================


class TestLineToBezierJunction:
    """Regression: Line→CubicBezier/QuadraticBezier junction point must
    not be silently dropped, which would distort or destroy geometry."""

    def test_rounded_rect_preserves_area(self, tmp_path):
        """Rounded rectangle (lines + cubic-bezier corners) must keep
        nearly the full area of its bounding box."""
        # A 200×100 rounded rect with r=20 corner radii.
        # k ≈ 0.5523 is the standard cubic Bézier kappa for quarter circles.
        k = 0.5523
        r = 20
        w, h = 200, 100
        d = (
            f"M{r},0 L{w - r},0 "
            f"C{w - r + r * k},0 {w},{r - r * k} {w},{r} "
            f"L{w},{h - r} "
            f"C{w},{h - r + r * k} {w - r + r * k},{h} {w - r},{h} "
            f"L{r},{h} "
            f"C{r - r * k},{h} 0,{h - r + r * k} 0,{h - r} "
            f"L0,{r} "
            f"C0,{r - r * k} {r - r * k},0 {r},0 Z"
        )
        svg_file = tmp_path / "rounded_rect.svg"
        svg_file.write_text(
            (
                f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}">\n'
                f'  <path fill="#ff0000" d="{d}"/>\n'
                "</svg>\n"
            ),
            encoding="utf-8",
        )

        vp = _make_parse_only_processor()
        shapes, scale, bbox = vp._parse_svg(str(svg_file), target_width_mm=100.0)

        assert len(shapes) >= 1
        total_area = sum(s["poly"].area for s in shapes)
        bbox_area = w * h  # 20000
        # A rounded rect with r=20 loses about 4*(r^2 - pi*r^2/4) ≈ 343
        # from its bounding rect, so the expected area ≈ 19657.
        expected_area = w * h - 4 * (r * r - np.pi * r * r / 4.0)
        assert total_area > expected_area * 0.95, (
            f"Rounded rect area {total_area:.1f} is too small "
            f"(expected ~{expected_area:.1f}, bbox={bbox_area})"
        )

    def test_line_to_quadratic_bezier_junction(self, tmp_path):
        """Path with Line→QuadraticBezier must preserve the junction point."""
        # A shape: straight left edge, quadratic-curved right edge.
        svg_file = tmp_path / "line_quad.svg"
        svg_file.write_text(
            (
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">\n'
                '  <path fill="#00ff00" d="M0,0 L100,0 Q100,50 100,100 L0,100 Z"/>\n'
                "</svg>\n"
            ),
            encoding="utf-8",
        )

        vp = _make_parse_only_processor()
        shapes, _, _ = vp._parse_svg(str(svg_file), target_width_mm=100.0)

        assert len(shapes) >= 1
        total_area = sum(s["poly"].area for s in shapes)
        # The shape is a 100x100 square (the Q curve is actually a straight
        # line from (100,0) to (100,100) with control at (100,50)).
        assert total_area > 9000.0, (
            f"Line→QuadBezier shape area {total_area:.1f} is too small "
            "(expected ~10000)"
        )


# =====================================================================
# 6. VectorAnalysis dataclass
# =====================================================================

class TestVectorAnalysis:
    """Verify VectorAnalysis dataclass construction and defaults."""

    def test_dataclass_fields(self):
        a = VectorAnalysis(
            shape_data=[],
            clipped_shapes=[],
            matched_shapes=[],
            silhouette=None,
            scale_factor=0.5,
            bbox=(0, 0, 100, 100),
            color_conf={},
            slot_names=["White"],
            num_channels=1,
            num_layers=4,
            preview_colors={0: [255, 255, 255, 255]},
        )
        assert a.scale_factor == 0.5
        assert a.num_channels == 1
        assert a.stage_timings == {}

    def test_stage_timings_default(self):
        a = VectorAnalysis(
            shape_data=[], clipped_shapes=[], matched_shapes=[], silhouette=None,
            scale_factor=1.0, bbox=(0, 0, 10, 10), color_conf={},
            slot_names=[], num_channels=0, num_layers=0, preview_colors={},
        )
        a.stage_timings["test"] = 1.23
        assert a.stage_timings == {"test": 1.23}


# =====================================================================
# 7. render_preview
# =====================================================================

class TestRenderPreview:
    """Verify render_preview produces correct output."""

    def _make_analysis(self, shapes, silhouette=None, w=100, h=100, sf=1.0):
        return VectorAnalysis(
            shape_data=[],
            clipped_shapes=[],
            matched_shapes=shapes,
            silhouette=silhouette,
            scale_factor=sf,
            bbox=(0, 0, w, h),
            color_conf={},
            slot_names=["White", "Red"],
            num_channels=2,
            num_layers=4,
            preview_colors={0: [255, 255, 255, 255], 1: [255, 0, 0, 255]},
        )

    def test_empty_shapes_returns_white(self):
        analysis = self._make_analysis([], w=10, h=10)
        img = VectorProcessor.render_preview(analysis, pixels_per_mm=1.0)
        assert img.shape[2] == 4
        assert img.dtype == np.uint8
        assert np.all(img[:, :, :3] == 255)

    def test_basic_shape_rendered(self):
        shape = {
            "geometry": box(2, 2, 8, 8),
            "recipe": [1, 1, 0, 0],
            "color": (255, 0, 0),
        }
        analysis = self._make_analysis([shape], w=10, h=10, sf=1.0)
        img = VectorProcessor.render_preview(analysis, pixels_per_mm=10.0)
        assert img.shape == (100, 100, 4)
        center = img[50, 50, :3]
        assert not np.all(center == 255), "Center should be colored, not white"

    def test_max_width_clamping(self):
        shape = {
            "geometry": box(0, 0, 200, 100),
            "recipe": [1, 1, 0, 0],
            "color": (255, 0, 0),
        }
        analysis = self._make_analysis([shape], w=200, h=100, sf=1.0)
        img = VectorProcessor.render_preview(analysis, pixels_per_mm=20.0, max_width_px=500)
        assert img.shape[1] <= 500

    def test_rgba_output_dtype(self):
        analysis = self._make_analysis([], w=5, h=5, sf=1.0)
        img = VectorProcessor.render_preview(analysis, pixels_per_mm=2.0)
        assert img.dtype == np.uint8
        assert img.shape[2] == 4
