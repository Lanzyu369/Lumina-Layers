"""Canonical coordinate-domain contracts for layered printable meshes."""

from __future__ import annotations

import numpy as np
import pytest
import trimesh

from core.layered_coordinate_domain import (
    LAYERED_COORDINATE_DOMAIN_CERTIFIED_KEY,
    LayeredCoordinateDomain,
    certify_layered_pattern_scene,
    read_layered_coordinate_domain,
)


def test_domain_owns_integer_canvas_and_float32_writer_envelope() -> None:
    domain = LayeredCoordinateDomain.from_canvas_and_layers(
        width_mm=115.59999084472656,
        height_mm=947.0 * (115.59999084472656 / 814.0),
        xy_grid_mm=0.0001,
        layer_heights_mm=(0.08,) * 5,
    )

    assert domain.canvas_min_units == (0, 0)
    assert domain.canvas_max_units == (1_156_000, 1_344_880)
    assert domain.layer_heights_mm == (0.08,) * 5
    assert domain.layer_boundaries_mm == (0.0, 0.08, 0.16, 0.24, 0.32, 0.4)
    assert domain.writer_canvas_bounds_mm == (
        0.0,
        0.0,
        max(1_156_000 * 0.0001, float(np.float32(115.6))),
        max(1_344_880 * 0.0001, float(np.float32(134.488))),
    )
    assert domain.writer_z_bounds_mm == (
        0.0,
        float(np.float32(0.4)),
    )
    assert LayeredCoordinateDomain.from_metadata(domain.to_metadata()) == domain


@pytest.mark.parametrize(
    "updates",
    [
        {"version": 999},
        {"xy_grid_mm": 0.0},
        {"canvas_max_units": [0, 10]},
        {"layer_boundaries_mm": [0.0, 0.08, 0.08]},
        {"writer_z_bounds_mm": [0.0, 0.4]},
    ],
)
def test_domain_rejects_malformed_or_forged_metadata(updates: dict) -> None:
    domain = LayeredCoordinateDomain.from_canvas_and_layers(
        width_mm=10.0,
        height_mm=20.0,
        xy_grid_mm=0.0001,
        layer_heights_mm=(0.08, 0.08),
    )
    metadata = domain.to_metadata()
    metadata.update(updates)

    with pytest.raises(ValueError):
        LayeredCoordinateDomain.from_metadata(metadata)


@pytest.mark.parametrize(
    ("width_mm", "height_mm", "xy_grid_mm", "layer_heights_mm"),
    [
        (0.0, 10.0, 0.0001, (0.08,)),
        (10.0, float("nan"), 0.0001, (0.08,)),
        (10.0, 10.0, -0.0001, (0.08,)),
        (10.0, 10.0, 0.0001, ()),
        (10.0, 10.0, 0.0001, (0.08, -0.01)),
    ],
)
def test_domain_rejects_invalid_construction_inputs(
    width_mm: float,
    height_mm: float,
    xy_grid_mm: float,
    layer_heights_mm: tuple[float, ...],
) -> None:
    with pytest.raises(ValueError):
        LayeredCoordinateDomain.from_canvas_and_layers(
            width_mm=width_mm,
            height_mm=height_mm,
            xy_grid_mm=xy_grid_mm,
            layer_heights_mm=layer_heights_mm,
        )


def test_pattern_scene_is_certified_once_in_float32_writer_space() -> None:
    domain = LayeredCoordinateDomain.from_canvas_and_layers(
        width_mm=115.59999084472656,
        height_mm=947.0 * (115.59999084472656 / 814.0),
        xy_grid_mm=0.0001,
        layer_heights_mm=(0.08,) * 5,
    )
    max_x = domain.writer_canvas_bounds_mm[2]
    max_y = domain.writer_canvas_bounds_mm[3]
    max_z = domain.writer_z_bounds_mm[1]
    mesh = trimesh.creation.box(extents=(max_x, max_y, max_z))
    mesh.apply_translation((max_x / 2.0, max_y / 2.0, max_z / 2.0))
    scene = trimesh.Scene({"pattern": mesh})

    certify_layered_pattern_scene(scene, domain)

    assert read_layered_coordinate_domain(scene, require_certified=True) == domain


def test_pattern_scene_certification_rejects_one_grid_unit_overflow() -> None:
    domain = LayeredCoordinateDomain.from_canvas_and_layers(
        width_mm=10.0,
        height_mm=10.0,
        xy_grid_mm=0.0001,
        layer_heights_mm=(0.08,),
    )
    overflow_x = domain.writer_canvas_bounds_mm[2] + domain.xy_grid_mm
    mesh = trimesh.creation.box(extents=(overflow_x, 1.0, 0.08))
    mesh.apply_translation((overflow_x / 2.0, 0.5, 0.04))

    with pytest.raises(ValueError, match="XY"):
        certify_layered_pattern_scene(trimesh.Scene({"pattern": mesh}), domain)


def test_certified_domain_reader_rejects_malformed_marker() -> None:
    scene = trimesh.Scene()
    scene.metadata[LAYERED_COORDINATE_DOMAIN_CERTIFIED_KEY] = "yes"

    with pytest.raises(ValueError):
        read_layered_coordinate_domain(scene, require_certified=True)
