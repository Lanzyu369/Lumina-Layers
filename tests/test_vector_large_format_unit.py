from __future__ import annotations

from shapely.geometry import Polygon, box

from core.vector_engine import VectorAnalysis
from core.vector_large_format import (
    SVG_LARGE_FORMAT_PREVIEW_FALLBACK_WARNING,
    SvgLargeFormatSupportInspector,
    SvgRasterFallbackDensityPlanner,
    VectorAnalysisTiler,
    build_tile_specs,
    choose_svg_raster_fallback_density,
    format_large_format_tile_label,
    inspect_svg_large_format_support,
    slice_vector_analysis_into_tiles,
)


def _make_analysis(*, matched_shapes: list[dict], clipped_shapes: list[dict] | None = None) -> VectorAnalysis:
    silhouette = None
    if matched_shapes:
        geoms = [item["geometry"] for item in matched_shapes if item["geometry"] is not None and not item["geometry"].is_empty]
        if geoms:
            silhouette = geoms[0]
            for geom in geoms[1:]:
                silhouette = silhouette.union(geom)

    return VectorAnalysis(
        shape_data=[],
        clipped_shapes=clipped_shapes or matched_shapes,
        matched_shapes=matched_shapes,
        silhouette=silhouette,
        scale_factor=1.0,
        bbox=(0.0, 0.0, 120.0, 80.0),
        color_conf={"slots": ["White", "Red"]},
        slot_names=["White", "Red"],
        num_channels=2,
        num_layers=5,
        preview_colors={0: [255, 255, 255, 255], 1: [255, 0, 0, 255]},
        stage_timings={},
    )


def test_build_tile_specs_resolves_partial_last_row_and_column() -> None:
    specs = build_tile_specs(
        total_width_mm=120.0,
        total_height_mm=80.0,
        tile_width_mm=50.0,
        tile_height_mm=30.0,
    )

    assert len(specs) == 9
    assert specs[0].row == 1
    assert specs[0].col == 1
    assert specs[0].width_mm == 50.0
    assert specs[0].height_mm == 30.0
    assert specs[-1].row == 3
    assert specs[-1].col == 3
    assert specs[-1].width_mm == 20.0
    assert specs[-1].height_mm == 20.0


def test_slice_vector_analysis_splits_shape_across_tile_seam() -> None:
    shape = {
        "geometry": box(10.0, 10.0, 70.0, 50.0),
        "recipe": [1, 1, 1, 1, 1],
        "draw_order": 0,
        "matched_rgb": (255, 0, 0),
        "color": (255, 0, 0),
    }
    analysis = _make_analysis(matched_shapes=[shape])

    tiles = slice_vector_analysis_into_tiles(
        analysis=analysis,
        total_width_mm=120.0,
        total_height_mm=80.0,
        tile_width_mm=60.0,
        tile_height_mm=80.0,
    )

    assert [tile.label for tile in tiles] == ["R1C1", "R1C2"]
    assert len(tiles[0].analysis.matched_shapes) == 1
    assert len(tiles[1].analysis.matched_shapes) == 1
    assert tiles[0].analysis.matched_shapes[0]["geometry"].bounds == (10.0, 10.0, 60.0, 50.0)
    assert tiles[1].analysis.matched_shapes[0]["geometry"].bounds == (0.0, 10.0, 10.0, 50.0)
    assert tiles[0].analysis.bbox == (0.0, 0.0, 60.0, 80.0)
    assert tiles[1].analysis.bbox == (0.0, 0.0, 60.0, 80.0)


def test_slice_vector_analysis_omits_empty_tiles() -> None:
    shape = {
        "geometry": box(0.0, 0.0, 20.0, 20.0),
        "recipe": [0, 0, 0, 0, 0],
        "draw_order": 0,
        "matched_rgb": (255, 255, 255),
        "color": (255, 255, 255),
    }
    analysis = _make_analysis(matched_shapes=[shape])

    tiles = slice_vector_analysis_into_tiles(
        analysis=analysis,
        total_width_mm=120.0,
        total_height_mm=80.0,
        tile_width_mm=40.0,
        tile_height_mm=40.0,
    )

    assert [tile.label for tile in tiles] == ["R1C1"]


def test_slice_vector_analysis_preserves_hole_geometry() -> None:
    ring = Polygon(
        [(10.0, 10.0), (70.0, 10.0), (70.0, 70.0), (10.0, 70.0)],
        holes=[[(30.0, 30.0), (50.0, 30.0), (50.0, 50.0), (30.0, 50.0)]],
    )
    shape = {
        "geometry": ring,
        "recipe": [1, 1, 1, 1, 1],
        "draw_order": 0,
        "matched_rgb": (255, 0, 0),
        "color": (255, 0, 0),
    }
    analysis = _make_analysis(matched_shapes=[shape])

    tiles = slice_vector_analysis_into_tiles(
        analysis=analysis,
        total_width_mm=120.0,
        total_height_mm=80.0,
        tile_width_mm=40.0,
        tile_height_mm=80.0,
    )

    middle = next(tile for tile in tiles if tile.label == "R1C2")
    middle_geom = middle.analysis.matched_shapes[0]["geometry"]

    assert middle_geom.area > 0.0
    assert middle_geom.bounds[0] >= 0.0
    assert middle.analysis.bbox == (0.0, 0.0, 40.0, 80.0)


def test_slice_vector_analysis_retains_thin_stroke_geometry() -> None:
    thin_shape = {
        "geometry": box(58.0, 20.0, 62.0, 22.0),
        "recipe": [1, 1, 1, 1, 1],
        "draw_order": 0,
        "matched_rgb": (255, 0, 0),
        "color": (255, 0, 0),
        "source_kind": "stroke_only",
    }
    analysis = _make_analysis(matched_shapes=[thin_shape])

    tiles = slice_vector_analysis_into_tiles(
        analysis=analysis,
        total_width_mm=120.0,
        total_height_mm=80.0,
        tile_width_mm=60.0,
        tile_height_mm=80.0,
    )

    assert [tile.label for tile in tiles] == ["R1C1", "R1C2"]
    assert all(tile.analysis.matched_shapes[0]["geometry"].area > 0.0 for tile in tiles)


def test_build_tile_specs_rejects_non_positive_dimensions() -> None:
    try:
        build_tile_specs(
            total_width_mm=120.0,
            total_height_mm=80.0,
            tile_width_mm=0.0,
            tile_height_mm=40.0,
        )
    except ValueError as exc:
        assert "positive" in str(exc).lower()
    else:
        raise AssertionError("Expected ValueError for non-positive tile width")


def test_slice_vector_analysis_keeps_backing_only_tiles() -> None:
    matched_shape = {
        "geometry": box(0.0, 0.0, 20.0, 20.0),
        "recipe": [1, 1, 1, 1, 1],
        "draw_order": 0,
        "matched_rgb": (255, 0, 0),
        "color": (255, 0, 0),
    }
    clipped_shape = {
        "geometry": box(65.0, 10.0, 80.0, 30.0),
        "color": (255, 255, 255),
        "draw_order": 1,
    }
    analysis = _make_analysis(
        matched_shapes=[matched_shape],
        clipped_shapes=[clipped_shape],
    )
    analysis = VectorAnalysis(
        shape_data=[{"poly": box(65.0, 10.0, 80.0, 30.0), "color": (255, 255, 255), "draw_order": 1}],
        clipped_shapes=analysis.clipped_shapes,
        matched_shapes=analysis.matched_shapes,
        silhouette=box(65.0, 10.0, 80.0, 30.0),
        scale_factor=analysis.scale_factor,
        bbox=analysis.bbox,
        color_conf=analysis.color_conf,
        slot_names=analysis.slot_names,
        num_channels=analysis.num_channels,
        num_layers=analysis.num_layers,
        preview_colors=analysis.preview_colors,
        stage_timings=analysis.stage_timings,
    )

    tiles = slice_vector_analysis_into_tiles(
        analysis=analysis,
        total_width_mm=120.0,
        total_height_mm=80.0,
        tile_width_mm=60.0,
        tile_height_mm=80.0,
    )

    assert [tile.label for tile in tiles] == ["R1C1", "R1C2"]
    backing_only_tile = next(tile for tile in tiles if tile.label == "R1C2")
    assert backing_only_tile.analysis.matched_shapes == []
    assert backing_only_tile.analysis.silhouette is not None


def test_slice_vector_analysis_preserves_shape_data_metadata() -> None:
    shape = {
        "geometry": box(10.0, 10.0, 70.0, 50.0),
        "recipe": [1, 1, 1, 1, 1],
        "draw_order": 3,
        "matched_rgb": (255, 0, 0),
        "color": (255, 0, 0),
    }
    analysis = _make_analysis(matched_shapes=[shape])
    analysis = VectorAnalysis(
        shape_data=[{"poly": box(10.0, 10.0, 70.0, 50.0), "color": (255, 0, 0), "draw_order": 3}],
        clipped_shapes=analysis.clipped_shapes,
        matched_shapes=analysis.matched_shapes,
        silhouette=analysis.silhouette,
        scale_factor=analysis.scale_factor,
        bbox=analysis.bbox,
        color_conf=analysis.color_conf,
        slot_names=analysis.slot_names,
        num_channels=analysis.num_channels,
        num_layers=analysis.num_layers,
        preview_colors=analysis.preview_colors,
        stage_timings=analysis.stage_timings,
    )

    tiles = slice_vector_analysis_into_tiles(
        analysis=analysis,
        total_width_mm=120.0,
        total_height_mm=80.0,
        tile_width_mm=60.0,
        tile_height_mm=80.0,
    )

    assert len(tiles[0].analysis.shape_data) == 1
    assert tiles[0].analysis.shape_data[0]["draw_order"] == 3
    assert tiles[1].analysis.shape_data[0]["draw_order"] == 3


def test_choose_svg_raster_fallback_density_stays_within_pixel_budget() -> None:
    density, warnings = choose_svg_raster_fallback_density(
        total_width_mm=4000.0,
        total_height_mm=4000.0,
        desired_pixels_per_mm=10.0,
        min_pixels_per_mm=2.0,
        max_total_pixels=12_000_000,
    )

    assert density > 0.0
    assert density * density * 4000.0 * 4000.0 <= 12_000_000 * 1.001
    assert warnings


def test_svg_raster_fallback_density_planner_matches_wrapper() -> None:
    planner = SvgRasterFallbackDensityPlanner(
        total_width_mm=4000.0,
        total_height_mm=4000.0,
        desired_pixels_per_mm=10.0,
        min_pixels_per_mm=2.0,
        max_total_pixels=12_000_000,
    )

    assert planner.choose_density() == choose_svg_raster_fallback_density(
        total_width_mm=4000.0,
        total_height_mm=4000.0,
        desired_pixels_per_mm=10.0,
        min_pixels_per_mm=2.0,
        max_total_pixels=12_000_000,
    )


def test_vector_analysis_tiler_build_tile_specs_matches_wrapper() -> None:
    tiler = VectorAnalysisTiler(
        analysis=_make_analysis(matched_shapes=[]),
        total_width_mm=120.0,
        total_height_mm=80.0,
        tile_width_mm=50.0,
        tile_height_mm=30.0,
    )

    assert tiler.build_tile_specs() == build_tile_specs(
        total_width_mm=120.0,
        total_height_mm=80.0,
        tile_width_mm=50.0,
        tile_height_mm=30.0,
    )


def test_format_large_format_tile_label_uses_source_basename_when_present() -> None:
    assert (
        format_large_format_tile_label(source_basename="poster-art", tile_label="R1C2")
        == "poster-art_R1C2"
    )


def test_format_large_format_tile_label_falls_back_to_tile_id_without_basename() -> None:
    assert format_large_format_tile_label(source_basename="", tile_label="R1C2") == "R1C2"


def test_svg_large_format_support_inspector_matches_wrapper(tmp_path) -> None:
    svg_path = tmp_path / "unsupported.svg"
    svg_path.write_text(
        "<svg xmlns='http://www.w3.org/2000/svg'>"
        "<defs><clipPath id='c'><rect x='0' y='0' width='10' height='10' /></clipPath></defs>"
        "<text x='0' y='10'>Hello</text>"
        "</svg>",
        encoding="utf-8",
    )

    inspection = SvgLargeFormatSupportInspector(str(svg_path)).inspect()

    assert inspection == inspect_svg_large_format_support(str(svg_path))
    assert inspection["native_tiling_supported"] is False
    assert inspection["unsupported_features"] == ["clipPath", "text"]
    assert inspection["warnings"] == [
        f"{SVG_LARGE_FORMAT_PREVIEW_FALLBACK_WARNING} Unsupported features: clipPath, text."
    ]
