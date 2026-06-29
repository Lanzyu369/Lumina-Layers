from __future__ import annotations

from PIL import Image

from core.model_surface.artwork import SurfacePlacement, render_surface_artwork
from core.model_surface.types import EdgeMode, PlaneFrame, SurfaceFootprint


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
