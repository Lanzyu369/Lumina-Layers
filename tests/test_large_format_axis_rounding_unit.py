"""Raster cache boundaries share the vector export's physical tile count."""

from api.routers.converter.generate import _validated_large_format_axis_boundaries


def test_cached_raster_boundaries_do_not_reject_a_float_phantom_tile() -> None:
    source, cache = _validated_large_format_axis_boundaries(
        total_mm=2999.9999999999955,
        tile_mm=499.9999999999992,
        source_pixels=600,
        cache_pixels=300,
    )
    assert source == [0, 100, 200, 300, 400, 500, 600]
    assert cache == [0, 50, 100, 150, 200, 250, 300]
