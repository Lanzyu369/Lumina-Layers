from __future__ import annotations

from PIL import Image
import pytest
from shapely.ops import unary_union

from core.model_surface.artwork import SurfacePlacement, render_surface_artwork
from core.model_surface.types import EdgeMode, PlaneFrame, SurfaceFootprint
from core.vector_engine import VectorProcessor


def test_render_surface_artwork_masks_to_surface_bounds(tmp_path):
    source = tmp_path / "source.png"
    Image.new("RGB", (80, 40), (255, 0, 0)).save(source)

    result = render_surface_artwork(
        source_path=source,
        footprint=_footprint(),
        placement=SurfacePlacement(mode=EdgeMode.EDGE_TO_EDGE),
        pixels_per_mm=4,
        output_dir=tmp_path,
    )

    assert result.width_px == 80
    assert result.height_px == 40
    assert result.target_width_mm == 20.0
    assert result.output_path.exists()
    rendered = Image.open(result.output_path).convert("RGBA")
    assert rendered.getpixel((40, 20)) == (255, 0, 0, 255)


def test_render_surface_artwork_edge_to_edge_preserves_source_aspect_ratio(tmp_path):
    source = tmp_path / "wide-source.png"
    image = Image.new("RGB", (80, 40), (0, 192, 0))
    for x in range(16):
        for y in range(40):
            image.putpixel((x, y), (255, 0, 0))
            image.putpixel((79 - x, y), (0, 0, 255))
    image.save(source)

    result = render_surface_artwork(
        source_path=source,
        footprint=_square_footprint(),
        placement=SurfacePlacement(mode=EdgeMode.EDGE_TO_EDGE),
        pixels_per_mm=4,
        output_dir=tmp_path,
    )

    rendered = Image.open(result.output_path).convert("RGBA")
    assert rendered.getpixel((4, 40)) == (0, 192, 0, 255)
    assert rendered.getpixel((75, 40)) == (0, 192, 0, 255)


def test_render_surface_artwork_uses_surface_space_counter_clockwise_rotation(tmp_path):
    source = tmp_path / "asymmetric-rotation.png"
    image = Image.new("RGBA", (80, 40), (0, 0, 0, 0))
    for x in range(60, 80):
        for y in range(0, 10):
            image.putpixel((x, y), (255, 0, 0, 255))
    for x in range(0, 20):
        for y in range(30, 40):
            image.putpixel((x, y), (0, 0, 255, 255))
    image.save(source)

    result = render_surface_artwork(
        source_path=source,
        footprint=_square_footprint(),
        placement=SurfacePlacement(
            mode=EdgeMode.EDGE_TO_EDGE,
            rotation_deg=90.0,
        ),
        pixels_per_mm=4,
        output_dir=tmp_path,
    )

    rendered = Image.open(result.output_path).convert("RGBA")
    red_top_left = sum(
        1
        for pixel in rendered.crop((0, 0, 40, 40)).getdata()
        if pixel[0] > 200 and pixel[1] < 40 and pixel[3] > 0
    )
    blue_bottom_right = sum(
        1
        for pixel in rendered.crop((40, 40, 80, 80)).getdata()
        if pixel[2] > 200 and pixel[0] < 40 and pixel[3] > 0
    )
    assert red_top_left > 0
    assert blue_bottom_right > 0


def test_render_surface_artwork_inset_contains_portrait_bitmap_with_four_side_clearance(
    tmp_path,
):
    source = tmp_path / "portrait.png"
    Image.new("RGB", (40, 80), (255, 0, 0)).save(source)

    result = render_surface_artwork(
        source_path=source,
        footprint=_square_footprint(),
        placement=SurfacePlacement(mode=EdgeMode.INSET, inset_mm=2.0),
        pixels_per_mm=4,
        output_dir=tmp_path,
    )

    rendered = Image.open(result.output_path).convert("RGBA")
    assert rendered.getchannel("A").getbbox() == (24, 8, 56, 72)


def test_render_surface_artwork_inset_contains_rotated_portrait_bitmap(
    tmp_path,
):
    source = tmp_path / "rotated-portrait.png"
    Image.new("RGB", (40, 80), (255, 0, 0)).save(source)

    result = render_surface_artwork(
        source_path=source,
        footprint=_square_footprint(),
        placement=SurfacePlacement(
            mode=EdgeMode.INSET,
            inset_mm=2.0,
            rotation_deg=17.0,
        ),
        pixels_per_mm=4,
        output_dir=tmp_path,
    )

    alpha_bounds = Image.open(result.output_path).convert("RGBA").getchannel("A").getbbox()
    assert alpha_bounds is not None
    assert alpha_bounds[0] >= 8
    assert alpha_bounds[1] >= 8
    assert alpha_bounds[2] <= 72
    assert alpha_bounds[3] <= 72


def test_render_surface_artwork_edge_to_edge_rotated_bitmap_covers_corners(
    tmp_path,
):
    source = tmp_path / "rotated-cover.png"
    Image.new("RGB", (40, 40), (255, 0, 0)).save(source)

    result = render_surface_artwork(
        source_path=source,
        footprint=_square_footprint(),
        placement=SurfacePlacement(
            mode=EdgeMode.EDGE_TO_EDGE,
            rotation_deg=17.0,
        ),
        pixels_per_mm=4,
        output_dir=tmp_path,
    )

    rendered = Image.open(result.output_path).convert("RGBA")
    for point in ((0, 0), (79, 0), (0, 79), (79, 79)):
        assert rendered.getpixel(point)[3] > 0


def test_render_surface_artwork_keeps_footprint_hole_transparent(tmp_path):
    source = tmp_path / "source.png"
    Image.new("RGB", (40, 40), (0, 128, 255)).save(source)

    result = render_surface_artwork(
        source_path=source,
        footprint=_footprint_with_hole(),
        placement=SurfacePlacement(mode=EdgeMode.EDGE_TO_EDGE),
        pixels_per_mm=2,
        output_dir=tmp_path,
    )

    rendered = Image.open(result.output_path).convert("RGBA")
    assert rendered.getpixel((20, 20))[3] == 0
    assert rendered.getpixel((4, 4)) == (0, 128, 255, 255)


def test_render_surface_artwork_preserves_svg_and_clips_holes_as_vector_geometry(
    tmp_path,
):
    source = tmp_path / "source.svg"
    source.write_text(
        """
        <svg xmlns="http://www.w3.org/2000/svg"
             width="40" height="20" viewBox="0 0 40 20">
          <path d="M0 0H40V20H0Z" fill="#0080ff"/>
        </svg>
        """,
        encoding="utf-8",
    )

    result = render_surface_artwork(
        source_path=source,
        footprint=_footprint_with_hole(),
        placement=SurfacePlacement(mode=EdgeMode.EDGE_TO_EDGE),
        pixels_per_mm=2,
        output_dir=tmp_path,
    )

    assert result.output_path.suffix == ".svg"
    processor = VectorProcessor.__new__(VectorProcessor)
    processor._init_runtime_defaults()
    processor.expand_stroke_to_fill = False
    shapes, scale_factor, _bounds = processor._parse_svg(
        str(result.output_path),
        target_width_mm=20.0,
    )
    total_area_mm2 = sum(shape["poly"].area for shape in shapes) * scale_factor**2
    assert total_area_mm2 == pytest.approx(384.0, abs=0.1)


def test_render_surface_artwork_filters_generated_gap_filler_paths(
    tmp_path,
):
    source = tmp_path / "gap-filler.svg"
    source.write_text(
        """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">
          <path d="M2 2H8V8H2Z" fill="#ff0000"/>
          <path class="qq3d-gap-filler"
                d="M2 10H18"
                fill="none"
                stroke="#0000ff"
                stroke-width="2"
                stroke-linejoin="round"
                stroke-linecap="round"
                vector-effect="non-scaling-stroke"/>
        </svg>
        """,
        encoding="utf-8",
    )

    result = render_surface_artwork(
        source_path=source,
        footprint=_square_footprint(),
        placement=SurfacePlacement(mode=EdgeMode.EDGE_TO_EDGE),
        pixels_per_mm=2,
        output_dir=tmp_path,
    )

    processor = VectorProcessor.__new__(VectorProcessor)
    processor._init_runtime_defaults()
    processor._parse_expand_stroke_to_fill = False
    shapes, scale_factor, _bounds = processor._parse_svg(
        str(result.output_path),
        target_width_mm=20.0,
    )

    assert [shape["color"] for shape in shapes] == [(255, 0, 0)]
    red_area_mm2 = sum(shape["poly"].area for shape in shapes) * scale_factor**2
    assert red_area_mm2 == pytest.approx(36.0, abs=0.1)


def test_render_surface_artwork_inset_contains_portrait_svg_with_four_side_clearance(
    tmp_path,
):
    source = tmp_path / "portrait.svg"
    source.write_text(
        """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 20">
          <path d="M0 0H10V20H0Z" fill="#ff0000"/>
        </svg>
        """,
        encoding="utf-8",
    )

    result = render_surface_artwork(
        source_path=source,
        footprint=_square_footprint(),
        placement=SurfacePlacement(mode=EdgeMode.INSET, inset_mm=2.0),
        pixels_per_mm=4,
        output_dir=tmp_path,
    )

    processor = VectorProcessor.__new__(VectorProcessor)
    processor._init_runtime_defaults()
    processor._parse_expand_stroke_to_fill = False
    shapes, scale_factor, _bounds = processor._parse_svg(
        str(result.output_path),
        target_width_mm=20.0,
    )
    visible_bounds = unary_union([shape["poly"] for shape in shapes]).bounds
    assert tuple(value * scale_factor for value in visible_bounds) == pytest.approx(
        (6.0, 2.0, 14.0, 18.0),
        abs=0.01,
    )


def test_render_surface_artwork_inset_contains_rotated_svg_bounding_box(
    tmp_path,
):
    source = tmp_path / "rotated-square.svg"
    source.write_text(
        """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">
          <path d="M0 0H20V20H0Z" fill="#ff0000"/>
        </svg>
        """,
        encoding="utf-8",
    )

    result = render_surface_artwork(
        source_path=source,
        footprint=_square_footprint(),
        placement=SurfacePlacement(
            mode=EdgeMode.INSET,
            inset_mm=2.0,
            rotation_deg=17.0,
        ),
        pixels_per_mm=4,
        output_dir=tmp_path,
    )

    processor = VectorProcessor.__new__(VectorProcessor)
    processor._init_runtime_defaults()
    processor._parse_expand_stroke_to_fill = False
    shapes, scale_factor, _bounds = processor._parse_svg(
        str(result.output_path),
        target_width_mm=20.0,
    )
    visible_bounds = unary_union([shape["poly"] for shape in shapes]).bounds
    assert tuple(value * scale_factor for value in visible_bounds) == pytest.approx(
        (2.0, 2.0, 18.0, 18.0),
        abs=0.01,
    )


def test_render_surface_artwork_edge_to_edge_covers_rotated_surface_corners(
    tmp_path,
):
    source = tmp_path / "rotated-cover-square.svg"
    source.write_text(
        """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">
          <path d="M0 0H20V20H0Z" fill="#ff0000"/>
        </svg>
        """,
        encoding="utf-8",
    )

    result = render_surface_artwork(
        source_path=source,
        footprint=_square_footprint(),
        placement=SurfacePlacement(
            mode=EdgeMode.EDGE_TO_EDGE,
            rotation_deg=17.0,
        ),
        pixels_per_mm=4,
        output_dir=tmp_path,
    )

    processor = VectorProcessor.__new__(VectorProcessor)
    processor._init_runtime_defaults()
    processor._parse_expand_stroke_to_fill = False
    shapes, scale_factor, _bounds = processor._parse_svg(
        str(result.output_path),
        target_width_mm=20.0,
    )
    visible_area_mm2 = unary_union(
        [shape["poly"] for shape in shapes]
    ).area * scale_factor**2
    assert visible_area_mm2 == pytest.approx(400.0, abs=0.01)


def _footprint() -> SurfaceFootprint:
    return SurfaceFootprint(
        frame=PlaneFrame(
            origin=(0.0, 0.0, 0.0),
            normal=(0.0, 0.0, 1.0),
            u_axis=(1.0, 0.0, 0.0),
            v_axis=(0.0, 1.0, 0.0),
        ),
        outer=((-10.0, -5.0), (10.0, -5.0), (10.0, 5.0), (-10.0, 5.0), (-10.0, -5.0)),
        holes=(),
        bounds_min=(-10.0, -5.0),
        bounds_max=(10.0, 5.0),
        bounds_width_mm=20.0,
        bounds_height_mm=10.0,
        area_mm2=200.0,
        hole_count=0,
    )


def _footprint_with_hole() -> SurfaceFootprint:
    footprint = _footprint()
    return SurfaceFootprint(
        frame=footprint.frame,
        outer=((-10.0, -10.0), (10.0, -10.0), (10.0, 10.0), (-10.0, 10.0), (-10.0, -10.0)),
        holes=(((-2.0, -2.0), (2.0, -2.0), (2.0, 2.0), (-2.0, 2.0), (-2.0, -2.0)),),
        bounds_min=(-10.0, -10.0),
        bounds_max=(10.0, 10.0),
        bounds_width_mm=20.0,
        bounds_height_mm=20.0,
        area_mm2=384.0,
        hole_count=1,
    )


def _square_footprint() -> SurfaceFootprint:
    footprint = _footprint()
    return SurfaceFootprint(
        frame=footprint.frame,
        outer=((-10.0, -10.0), (10.0, -10.0), (10.0, 10.0), (-10.0, 10.0), (-10.0, -10.0)),
        holes=(),
        bounds_min=(-10.0, -10.0),
        bounds_max=(10.0, 10.0),
        bounds_width_mm=20.0,
        bounds_height_mm=20.0,
        area_mm2=400.0,
        hole_count=0,
    )
