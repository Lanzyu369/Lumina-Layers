"""Lossless native re-expression of already-owned integer coverage."""

import numpy as np
import pytest
import shapely
from shapely.geometry import MultiPolygon, Polygon, box

import lumina_svg_core


def _input_rings(geometry):
    oriented = shapely.orient_polygons(geometry)
    parts = [oriented] if isinstance(oriented, Polygon) else list(oriented.geoms)
    rings = []
    for part in parts:
        rings.append(np.asarray(part.exterior.coords, dtype=np.float64))
        rings.extend(
            np.asarray(hole.coords, dtype=np.float64)
            for hole in part.interiors
        )
    return rings


def _output_geometry(region):
    parts = [Polygon(shell, holes) for shell, holes in region]
    assert all(part.is_valid for part in parts)
    return parts[0] if len(parts) == 1 else MultiPolygon(parts)


def _canonicalize(geometries):
    return lumina_svg_core.canonicalize_grid_regions([
        _input_rings(geometry) for geometry in geometries
    ])


@pytest.mark.parametrize(
    "coordinates, expected_area",
    [
        ([(0, 0), (6, 5), (1, -1)], 5.5),
        ([(0, 0), (10, -25), (9, -26)], 17.5),
        ([(0, 0), (1, 0), (-369, -1063)], 531.5),
    ],
)
def test_native_canonicalizer_preserves_captured_positive_area_triangles(
    coordinates,
    expected_area,
):
    source = Polygon(coordinates)
    output = _canonicalize([source])
    canonical = _output_geometry(output[0])

    assert source.is_valid
    assert canonical.is_valid
    assert canonical.area == expected_area
    assert canonical.equals(source)


def test_native_canonicalizer_is_idempotent_and_preserves_labels():
    sources = [
        Polygon([(0, 0), (6, 5), (1, -1)]),
        Polygon([(20, 0), (30, -25), (29, -26)]),
        box(-5, -5, 5, 5),
    ]
    first = _canonicalize(sources)
    first_geometries = [_output_geometry(region) for region in first]
    second = _canonicalize(first_geometries)

    assert [geometry.area for geometry in first_geometries] == pytest.approx(
        [source.area for source in sources],
    )
    assert all(
        _output_geometry(region).equals(source)
        for region, source in zip(second, sources, strict=True)
    )


def test_native_canonicalizer_preserves_hole_island_and_point_contacts():
    shell_with_hole = Polygon(
        [(0, 0), (10, 0), (10, 10), (0, 10)],
        [[(2, 2), (2, 8), (8, 8), (8, 2)]],
    )
    island = box(4, 4, 6, 6)
    nested = MultiPolygon([shell_with_hole, island])
    nested_output = _output_geometry(_canonicalize([nested])[0])
    assert nested_output.equals(nested)
    assert nested_output.area == 68
    assert not nested_output.covers(shapely.Point(3, 3))
    assert nested_output.covers(shapely.Point(5, 5))

    touching = MultiPolygon([box(-4, -4, -2, -2), box(-2, -2, 0, 0)])
    touching_output = _output_geometry(_canonicalize([touching])[0])
    assert touching_output.equals(touching)
    assert touching_output.area == 8
