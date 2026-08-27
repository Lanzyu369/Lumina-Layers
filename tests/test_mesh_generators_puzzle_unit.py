"""Unit tests for puzzle-aware mesh generation paths."""

from __future__ import annotations

import logging

import numpy as np
import pytest
from shapely.geometry import Polygon

from config import ModelingMode
from core import mesh_generators
from core.mesh_export_parts import (
    get_mesh_export_part_ranges,
    mesh_export_parts_are_conditional,
)
from core.pipeline import s07_mesh_generation
from core.mesh_generators import HighFidelityMesher, get_mesher
from utils import bambu_3mf_writer as writer_module
from utils.bambu_3mf_writer import BambuStudio3MFWriter


def _make_split_voxel_matrix() -> np.ndarray:
    """Build a tiny 2-material matrix with a shared edge at x=3."""
    voxel_matrix = np.full((1, 5, 5), -1, dtype=int)
    voxel_matrix[0, 1:4, 1:3] = 0
    voxel_matrix[0, 1:4, 3:5] = 1
    return voxel_matrix


def _oriented_triangles(mesh) -> list[tuple[float, ...]]:
    """Return face-order-independent triangles while retaining winding."""

    oriented = []
    for triangle in np.round(np.asarray(mesh.triangles), 9):
        rotations = [
            tuple(triangle[[0, 1, 2]].reshape(-1)),
            tuple(triangle[[1, 2, 0]].reshape(-1)),
            tuple(triangle[[2, 0, 1]].reshape(-1)),
        ]
        oriented.append(min(rotations))
    return sorted(oriented)


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


def test_high_fidelity_rect_only_path_skips_redundant_mesh_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A rect-only mesh is already cleaned and must not be merged a second time."""

    voxel_matrix = np.full((2, 6, 6), -1, dtype=int)
    voxel_matrix[:, 1:5, 1:5] = 0
    mesher = HighFidelityMesher(disable_material_dilation=True)
    original_merge = mesh_generators._merge_mesh_list
    merge_calls = 0

    def _record_merge(meshes):
        nonlocal merge_calls
        merge_calls += 1
        return original_merge(meshes)

    monkeypatch.setattr(mesh_generators, "_merge_mesh_list", _record_merge)

    mesh = mesher.generate_mesh(voxel_matrix, 0, height_px=6)

    assert mesh is not None
    legacy_cleaned = original_merge([mesh.copy()])
    assert legacy_cleaned is not None
    assert len(mesh.faces) > 0
    assert merge_calls == 0
    assert len(mesh.vertices) == len(legacy_cleaned.vertices)
    assert len(mesh.faces) == len(legacy_cleaned.faces)
    np.testing.assert_allclose(mesh.bounds, legacy_cleaned.bounds)
    assert mesh.is_watertight == legacy_cleaned.is_watertight
    assert mesh.euler_number == legacy_cleaned.euler_number
    assert mesh.volume == pytest.approx(legacy_cleaned.volume)
    assert _oriented_triangles(mesh) == _oriented_triangles(legacy_cleaned)


def test_s07_defaults_to_exact_material_boundaries_for_color_exports() -> None:
    """The export pipeline must not let one color mesh invade another color's voxel."""

    voxel_matrix = _make_split_voxel_matrix()
    ctx = {
        "full_matrix": voxel_matrix,
        "slot_names": ["Left", "Right"],
        "preview_colors": {
            0: (255, 0, 0, 255),
            1: (0, 255, 0, 255),
        },
        "modeling_mode": ModelingMode.HIGH_FIDELITY,
        "target_h": 5,
        "pixel_scale": 1.0,
        "_bench_enabled": False,
    }

    result = s07_mesh_generation.run(ctx)
    left = result["scene"].geometry["Left"]
    right = result["scene"].geometry["Right"]

    assert result["disable_material_dilation"] is True
    assert left.bounds[1, 0] == pytest.approx(3.0)
    assert right.bounds[0, 0] == pytest.approx(3.0)


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
    mesher = HighFidelityMesher(
        disable_material_dilation=True,
        boundary_geometry=boundary_geometry,
    )

    mesh = mesher.generate_mesh(voxel_matrix, 0, height_px=5)

    assert mesh is not None
    assert mesh.bounds[0, 0] == pytest.approx(0.0)
    assert mesh.bounds[1, 0] == pytest.approx(3.0)
    assert mesh.volume == pytest.approx(7.5, rel=1e-6)
    assert mesh.metadata["raster_surface_stats"] == {
        "patch_count": 1,
        "lattice_patch_count": 0,
        "boundary_polygon_count": 1,
        "boundary_adapter_used": True,
        "boundary_enabled": True,
        "material_dilation_applied": False,
    }


def test_high_fidelity_mesher_combines_dilation_with_boundary_clipping() -> None:
    voxel_matrix = np.full((1, 5, 5), -1, dtype=int)
    voxel_matrix[0, 2, 2] = 0
    boundary_geometry = Polygon([(1.0, 1.0), (4.0, 1.0), (1.0, 4.0)])
    mesher = HighFidelityMesher(boundary_geometry=boundary_geometry)

    mesh = mesher.generate_mesh(voxel_matrix, 0, height_px=5)

    assert mesh is not None
    assert mesh.is_watertight
    assert mesh.volume == pytest.approx(4.5, rel=1e-6)
    assert mesh.metadata["raster_surface_stats"] == {
        "patch_count": 1,
        "lattice_patch_count": 0,
        "boundary_polygon_count": 1,
        "boundary_adapter_used": True,
        "boundary_enabled": True,
        "material_dilation_applied": True,
    }


def test_high_fidelity_mesher_keeps_interior_cells_on_lattice_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Interior cells use the exact lattice surface; clipped cells use polygons."""

    voxel_matrix = np.full((1, 6, 6), -1, dtype=int)
    voxel_matrix[0, 1:3, 1:3] = 0
    voxel_matrix[0, 3:5, 3:5] = 0
    boundary_geometry = Polygon([(2.0, 2.0), (6.0, 2.0), (6.0, 6.0), (2.0, 6.0)])
    mesher = HighFidelityMesher(
        disable_material_dilation=True,
        boundary_geometry=boundary_geometry,
    )

    recorded: dict[str, list[object]] = {"volumes": [], "polygons": []}
    original_surface_builder = mesh_generators.build_labeled_surface_mesh
    original_polygon_builder = HighFidelityMesher._build_mesh_from_layer_polygons

    def _record_surface(labels, **kwargs):
        recorded["volumes"].append(np.asarray(labels).copy())
        return original_surface_builder(labels, **kwargs)

    def _record_polygons(self, layer_polygons, height_px):
        recorded["polygons"].extend(layer_polygons)
        return original_polygon_builder(self, layer_polygons, height_px)

    monkeypatch.setattr(
        mesh_generators,
        "build_labeled_surface_mesh",
        _record_surface,
    )
    monkeypatch.setattr(HighFidelityMesher, "_build_mesh_from_layer_polygons", _record_polygons)

    mesh = mesher.generate_mesh(voxel_matrix, 0, height_px=6)

    assert mesh is not None
    assert len(recorded["volumes"]) == 1
    assert len(recorded["polygons"]) == 1
    interior_volume = recorded["volumes"][0]
    clipped = recorded["polygons"][0][2]
    assert int(np.count_nonzero(interior_volume)) == 4
    assert np.all(interior_volume[0, 3:5, 3:5])
    assert clipped.bounds == pytest.approx((2.0, 2.0, 3.0, 3.0))
    assert mesh.metadata["raster_surface_stats"] == {
        "patch_count": (
            mesh.metadata["layered_mesh_stats"]["merged_patch_count"] + 1
        ),
        "lattice_patch_count": mesh.metadata["layered_mesh_stats"][
            "merged_patch_count"
        ],
        "boundary_polygon_count": 1,
        "boundary_adapter_used": True,
        "boundary_enabled": True,
        "material_dilation_applied": False,
    }
    ranges = get_mesh_export_part_ranges(mesh)
    assert len(ranges) == 2
    assert not mesh_export_parts_are_conditional(mesh)

    writer = BambuStudio3MFWriter(
        "hybrid-boundary.3mf",
        settings={},
        color_mode="4-Color",
        printer_id="bambu-p2s",
        slicer="BambuStudio",
    )
    writer.add_mesh(mesh, "White", (255, 255, 255))
    assert len(writer.objects) == 2
    for entry in writer.objects:
        vertices, faces = writer_module._materialize_n3mf_mesh_view_arrays(
            entry.mesh,
            part_range=entry.part_range,
            contact_repair_ranges=entry.contact_repair_ranges,
            require_topology_audit=entry.require_topology_audit,
        )
        assert len(vertices) > 0
        assert len(faces) > 0


def test_high_fidelity_mesher_logs_structured_boundary_clip_fallback(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Boundary clip failures should log structured fields and fall back without crashing."""

    voxel_matrix = np.full((1, 4, 4), 0, dtype=int)
    boundary_geometry = Polygon([(0.0, 0.0), (3.0, 0.0), (0.0, 4.0)])
    mesher = HighFidelityMesher(
        disable_material_dilation=True,
        boundary_geometry=boundary_geometry,
    )

    class _BrokenRect:
        def intersection(self, _boundary):
            raise ValueError("clip exploded")

    monkeypatch.setattr("core.mesh_generators.box", lambda *args, **kwargs: _BrokenRect())
    caplog.set_level(logging.WARNING, logger="core.mesh_generators")

    mesh = mesher.generate_mesh(voxel_matrix, 0, height_px=4)

    assert mesh is not None
    assert mesh.metadata["integer_topology_scale"] == 2
    assert mesh.metadata["raster_surface_stats"]["boundary_adapter_used"] is False
    assert mesh.metadata["raster_surface_stats"]["boundary_enabled"] is True
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
