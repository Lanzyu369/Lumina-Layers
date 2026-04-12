"""Unit tests for puzzle-aware mesh generation paths."""

from __future__ import annotations

import logging

import numpy as np
import pytest
from shapely.geometry import Polygon

from config import ModelingMode
from core.mesh_generators import HighFidelityMesher, get_mesher


def _make_split_voxel_matrix() -> np.ndarray:
    """Build a tiny 2-material matrix with a shared edge at x=3."""
    voxel_matrix = np.full((1, 5, 5), -1, dtype=int)
    voxel_matrix[0, 1:4, 1:3] = 0
    voxel_matrix[0, 1:4, 3:5] = 1
    return voxel_matrix


def test_high_fidelity_mesher_disable_material_dilation_keeps_shared_edge_exact() -> None:
    """No-dilation mode should preserve the exact shared material boundary."""

    voxel_matrix = _make_split_voxel_matrix()
    no_dilation_mesher = HighFidelityMesher(disable_material_dilation=True)
    default_mesher = HighFidelityMesher()

    no_dilation_left = no_dilation_mesher.generate_mesh(voxel_matrix, 0, height_px=5)
    no_dilation_right = no_dilation_mesher.generate_mesh(voxel_matrix, 1, height_px=5)
    default_left = default_mesher.generate_mesh(voxel_matrix, 0, height_px=5)
    default_right = default_mesher.generate_mesh(voxel_matrix, 1, height_px=5)

    assert no_dilation_left is not None
    assert no_dilation_right is not None
    assert default_left is not None
    assert default_right is not None

    assert no_dilation_left.bounds[1, 0] == pytest.approx(3.0)
    assert no_dilation_right.bounds[0, 0] == pytest.approx(3.0)
    assert default_left.bounds[1, 0] > 3.0
    assert default_right.bounds[0, 0] < 3.0


def test_high_fidelity_mesher_preserves_enclosed_blind_cavity_during_dilation() -> None:
    """Default dilation should thicken outward without collapsing an enclosed cavity."""

    voxel_matrix = np.full((1, 9, 9), -1, dtype=int)
    voxel_matrix[0, 2:7, 2:7] = 0
    voxel_matrix[0, 3:6, 3:6] = -1
    mesher = HighFidelityMesher()

    mesh = mesher.generate_mesh(voxel_matrix, 0, height_px=9)

    assert mesh is not None
    assert mesh.volume == pytest.approx(40.0)
    assert mesh.bounds[0, 0] == pytest.approx(1.0)
    assert mesh.bounds[1, 0] == pytest.approx(8.0)


def test_high_fidelity_mesher_boundary_geometry_clips_to_polygon() -> None:
    """Boundary geometry should clip boundary-touching rectangles instead of inflating them."""

    voxel_matrix = np.full((1, 5, 5), 0, dtype=int)
    boundary_geometry = Polygon([(0.0, 0.0), (3.0, 0.0), (0.0, 5.0)])
    mesher = HighFidelityMesher(disable_material_dilation=True, boundary_geometry=boundary_geometry)

    mesh = mesher.generate_mesh(voxel_matrix, 0, height_px=5)

    assert mesh is not None
    assert mesh.bounds[0, 0] == pytest.approx(0.0)
    assert mesh.bounds[1, 0] == pytest.approx(3.0)
    assert mesh.volume == pytest.approx(7.5, rel=1e-6)


def test_high_fidelity_mesher_keeps_interior_rects_on_fast_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fully interior rectangles should stay on rect extrusion while clipped rects use polygons."""

    voxel_matrix = np.full((1, 6, 6), -1, dtype=int)
    voxel_matrix[0, 1:3, 1:3] = 0
    voxel_matrix[0, 3:5, 3:5] = 0
    boundary_geometry = Polygon([(2.0, 2.0), (6.0, 2.0), (6.0, 6.0), (2.0, 6.0)])
    mesher = HighFidelityMesher(disable_material_dilation=True, boundary_geometry=boundary_geometry)

    recorded: dict[str, list[object]] = {"rects": [], "polygons": []}
    original_rect_builder = HighFidelityMesher._build_mesh_from_layer_rects
    original_polygon_builder = HighFidelityMesher._build_mesh_from_layer_polygons

    def _record_rects(self, layer_rectangles, height_px):
        recorded["rects"].extend(layer_rectangles)
        return original_rect_builder(self, layer_rectangles, height_px)

    def _record_polygons(self, layer_polygons, height_px):
        recorded["polygons"].extend(layer_polygons)
        return original_polygon_builder(self, layer_polygons, height_px)

    monkeypatch.setattr(HighFidelityMesher, "_build_mesh_from_layer_rects", _record_rects)
    monkeypatch.setattr(HighFidelityMesher, "_build_mesh_from_layer_polygons", _record_polygons)

    mesh = mesher.generate_mesh(voxel_matrix, 0, height_px=6)

    assert mesh is not None
    assert len(recorded["rects"]) == 1
    assert len(recorded["polygons"]) == 1
    rects = recorded["rects"][0][2]
    clipped = recorded["polygons"][0][2]
    assert rects.shape == (1, 4)
    assert tuple(rects[0]) == pytest.approx((3.0, 3.0, 5.0, 5.0))
    assert clipped.bounds == pytest.approx((2.0, 2.0, 3.0, 3.0))


def test_high_fidelity_mesher_logs_structured_boundary_clip_fallback(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Boundary clip failures should log structured fields and fall back without crashing."""

    voxel_matrix = np.full((1, 4, 4), 0, dtype=int)
    boundary_geometry = Polygon([(0.0, 0.0), (3.0, 0.0), (0.0, 4.0)])
    mesher = HighFidelityMesher(disable_material_dilation=True, boundary_geometry=boundary_geometry)

    class _BrokenRect:
        def intersection(self, _boundary):
            raise ValueError("clip exploded")

    monkeypatch.setattr("core.mesh_generators.box", lambda *args, **kwargs: _BrokenRect())
    caplog.set_level(logging.WARNING, logger="core.mesh_generators")

    mesh = mesher.generate_mesh(voxel_matrix, 0, height_px=4)

    assert mesh is not None
    assert any(
        record.__dict__.get("event") == "boundary_polygon_clip_fallback"
        and record.__dict__.get("error_type") == "ValueError"
        for record in caplog.records
    )


def test_get_mesher_forwards_puzzle_options_to_high_fidelity_mode() -> None:
    """The factory should keep the puzzle-specific mesher options intact."""

    boundary_geometry = Polygon([(0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0)])
    mesher = get_mesher(
        ModelingMode.VECTOR,
        disable_material_dilation=True,
        boundary_geometry=boundary_geometry,
    )

    assert isinstance(mesher, HighFidelityMesher)
    assert mesher.disable_material_dilation is True
    assert mesher.boundary_geometry is not None
    assert mesher.boundary_geometry.equals(boundary_geometry)
