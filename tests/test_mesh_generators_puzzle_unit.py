"""Unit tests for puzzle-aware mesh generation paths."""

from __future__ import annotations

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


def test_high_fidelity_rect_only_path_calls_layered_builder_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A raster material is assembled once by the unified surface builder."""

    voxel_matrix = np.full((2, 6, 6), -1, dtype=int)
    voxel_matrix[:, 1:5, 1:5] = 0
    mesher = HighFidelityMesher(disable_material_dilation=True)
    original_builder = mesh_generators.build_labeled_surface_mesh
    builder_calls = 0

    def _record_builder(*args, **kwargs):
        nonlocal builder_calls
        builder_calls += 1
        return original_builder(*args, **kwargs)

    monkeypatch.setattr(
        mesh_generators,
        "build_labeled_surface_mesh",
        _record_builder,
    )

    mesh = mesher.generate_mesh(voxel_matrix, 0, height_px=6)

    assert mesh is not None
    assert builder_calls == 1
    assert mesh.is_watertight
    assert mesh.volume == pytest.approx(32.0)


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
    boundary_mask = mesh_generators.rasterize_boundary_geometry(
        boundary_geometry,
        height_px=5,
        width_px=5,
    )
    assert mesh.volume == pytest.approx(float(np.count_nonzero(boundary_mask)))
    assert mesh.metadata["raster_surface_stats"] == {
        "patch_count": mesh.metadata["layered_mesh_stats"]["merged_patch_count"],
        "lattice_patch_count": mesh.metadata["layered_mesh_stats"]["merged_patch_count"],
        "boundary_rasterized": True,
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
    boundary_mask = mesh_generators.rasterize_boundary_geometry(
        boundary_geometry,
        height_px=5,
        width_px=5,
    )
    assert mesh.volume == pytest.approx(float(np.count_nonzero(boundary_mask)))
    assert mesh.metadata["raster_surface_stats"] == {
        "patch_count": mesh.metadata["layered_mesh_stats"]["merged_patch_count"],
        "lattice_patch_count": mesh.metadata["layered_mesh_stats"]["merged_patch_count"],
        "boundary_rasterized": True,
        "boundary_enabled": True,
        "material_dilation_applied": True,
    }


def test_high_fidelity_mesher_clips_all_cells_before_one_lattice_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Boundary clipping produces one effective volume and no polygon side path."""

    voxel_matrix = np.full((1, 6, 6), -1, dtype=int)
    voxel_matrix[0, 1:3, 1:3] = 0
    voxel_matrix[0, 3:5, 3:5] = 0
    boundary_geometry = Polygon([(2.0, 2.0), (6.0, 2.0), (6.0, 6.0), (2.0, 6.0)])
    mesher = HighFidelityMesher(
        disable_material_dilation=True,
        boundary_geometry=boundary_geometry,
    )

    recorded: list[np.ndarray] = []
    original_surface_builder = mesh_generators.build_labeled_surface_mesh

    def _record_surface(labels, **kwargs):
        recorded.append(np.asarray(labels).copy())
        return original_surface_builder(labels, **kwargs)

    monkeypatch.setattr(
        mesh_generators,
        "build_labeled_surface_mesh",
        _record_surface,
    )

    mesh = mesher.generate_mesh(voxel_matrix, 0, height_px=6)

    assert mesh is not None
    assert len(recorded) == 1
    effective_volume = recorded[0]
    expected_boundary = mesh_generators.rasterize_boundary_geometry(
        boundary_geometry,
        height_px=6,
        width_px=6,
    )
    expected_volume = (voxel_matrix == 0) & expected_boundary[None, :, :]
    np.testing.assert_array_equal(effective_volume, expected_volume)
    assert mesh.metadata["raster_surface_stats"] == {
        "patch_count": mesh.metadata["layered_mesh_stats"]["merged_patch_count"],
        "lattice_patch_count": mesh.metadata["layered_mesh_stats"][
            "merged_patch_count"
        ],
        "boundary_rasterized": True,
        "boundary_enabled": True,
        "material_dilation_applied": False,
    }
    ranges = get_mesh_export_part_ranges(mesh)
    assert len(ranges) >= 1
    assert mesh_export_parts_are_conditional(mesh)

    writer = BambuStudio3MFWriter(
        "hybrid-boundary.3mf",
        settings={},
        color_mode="4-Color",
        printer_id="bambu-p2s",
        slicer="BambuStudio",
    )
    writer.add_mesh(mesh, "White", (255, 255, 255))
    assert len(writer.objects) == 1
    assert len(writer.objects[0].contact_repair_ranges) == 2
    for entry in writer.objects:
        vertices, faces = writer_module._materialize_n3mf_mesh_view_arrays(
            entry.mesh,
            part_range=entry.part_range,
            contact_repair_ranges=entry.contact_repair_ranges,
        )
        assert len(vertices) > 0
        assert len(faces) > 0


def test_high_fidelity_mesher_has_no_boundary_polygon_fallback() -> None:
    """Puzzle generation exposes only the unified lattice boundary contract."""

    voxel_matrix = np.full((1, 4, 4), 0, dtype=int)
    boundary_geometry = Polygon([(0.0, 0.0), (3.0, 0.0), (0.0, 4.0)])
    mesher = HighFidelityMesher(
        disable_material_dilation=True,
        boundary_geometry=boundary_geometry,
    )

    mesh = mesher.generate_mesh(voxel_matrix, 0, height_px=4)

    assert mesh is not None
    assert mesh.metadata["integer_topology_scale"] == 2
    assert mesh.metadata["raster_surface_stats"]["boundary_rasterized"] is True
    assert mesh.metadata["raster_surface_stats"]["boundary_enabled"] is True
    assert not hasattr(HighFidelityMesher, "_build_mesh_from_layer_polygons")


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
