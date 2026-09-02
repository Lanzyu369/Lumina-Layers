"""Integration contracts for the shared raster and native-Vector mesh cores."""

from __future__ import annotations

import numpy as np
import pytest
from shapely.geometry import box

import core.mesh_generators as mesh_generators
import core.vector_engine as vector_engine
from config import ModelingMode
from core.mesh_export_parts import get_mesh_export_part_ranges
from core.mesh_generators import get_mesher
from core.vector_engine import VectorProcessor


def _edge_incidence(mesh) -> np.ndarray:
    edges = np.sort(np.asarray(mesh.edges, dtype=np.int64), axis=1)
    _unique, counts = np.unique(edges, axis=0, return_counts=True)
    return counts


@pytest.mark.parametrize(
    "mode",
    [ModelingMode.PIXEL, ModelingMode.HIGH_FIDELITY, ModelingMode.VECTOR],
)
def test_raster_and_rasterized_svg_modes_share_exact_surface_builder(
    mode: ModelingMode,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    labels = np.full((2, 4, 5), -1, dtype=np.int16)
    labels[:, 1:3, 1:4] = 2
    calls: list[tuple[tuple[int, ...], int]] = []
    real_builder = mesh_generators.build_labeled_surface_mesh

    def recording_builder(volume, *, material_id, height_px, policy=None):
        calls.append((tuple(np.asarray(volume).shape), int(height_px)))
        return real_builder(
            volume,
            material_id=material_id,
            height_px=height_px,
            policy=policy,
        )

    monkeypatch.setattr(
        mesh_generators,
        "build_labeled_surface_mesh",
        recording_builder,
    )
    mesher = get_mesher(mode, disable_material_dilation=True)

    mesh = mesher.generate_mesh(labels, mat_id=2, height_px=4)

    assert mesh is not None
    assert calls == [((2, 4, 5), 4)]
    assert mesh.is_watertight
    assert np.all(_edge_incidence(mesh) == 2)
    assert float(mesh.volume) == pytest.approx(12.0)
    assert mesh.metadata["layered_mesh_stats"]["source_voxel_count"] == 12


def test_native_svg_runs_use_one_layered_constructor_per_material(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_geometries = [
        box(0.0, 0.0, 10.0, 10.0),
        box(10.0, 0.0, 20.0, 10.0),
        box(30.0, 0.0, 35.0, 5.0),
    ]
    calls = 0
    real_builder = vector_engine.build_vector_layered_volume

    def recording_builder(*args, **kwargs):
        nonlocal calls
        calls += 1
        return real_builder(*args, **kwargs)

    monkeypatch.setattr(
        vector_engine,
        "build_vector_layered_volume",
        recording_builder,
    )

    by_slot = VectorProcessor._run_length_extrude(
        matched_shapes=[
            {"geometry": geometry, "recipe": [0, 0]}
            for geometry in source_geometries
        ],
        num_layers=2,
        layer_h=0.08,
        num_channels=1,
        slot_names=["White"],
        scale_factor=1.0,
    )

    mesh = by_slot["White"]["meshes"][0]
    assert calls == 1
    assert len(by_slot["White"]["meshes"]) == 1
    assert len(mesh.split(only_watertight=False)) == 2
    assert get_mesh_export_part_ranges(mesh) == ()
    assert mesh.is_watertight
    assert np.all(_edge_incidence(mesh) == 2)
    assert float(mesh.volume) == pytest.approx(225.0 * 0.16)


def test_native_svg_relief_uses_one_canonical_volume_per_output_material(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    real_builder = vector_engine.build_vector_layered_volume

    def recording_builder(*args, **kwargs):
        nonlocal calls
        calls += 1
        return real_builder(*args, **kwargs)

    monkeypatch.setattr(
        vector_engine,
        "build_vector_layered_volume",
        recording_builder,
    )
    by_slot = VectorProcessor._build_relief_meshes(
        matched_shapes=[
            {
                "geometry": box(0.0, 0.0, 10.0, 10.0),
                "recipe": [0, 0],
                "matched_rgb": (255, 0, 0),
            },
            {
                "geometry": box(10.0, 0.0, 20.0, 10.0),
                "recipe": [1, 1],
                "matched_rgb": (255, 255, 255),
            },
        ],
        num_layers=2,
        layer_h=0.08,
        num_channels=2,
        slot_names=["Red", "White"],
        scale_factor=1.0,
        backing_color_id=0,
        default_height_mm=1.0,
        height_mode="color",
        color_height_map={"#ff0000": 1.04, "#ffffff": 2.0},
        heightmap_path=None,
        heightmap_max_height=None,
        bbox=(0.0, 0.0, 20.0, 10.0),
    )

    board = by_slot["Board"]["meshes"][0]
    assert calls == len(by_slot) == 3
    assert len(by_slot["Board"]["meshes"]) == 1
    assert len(by_slot["Red"]["meshes"]) == 1
    assert len(by_slot["White"]["meshes"]) == 1
    assert board.is_watertight
    assert np.all(_edge_incidence(board) == 2)


def test_native_svg_relief_keeps_alternating_runs_in_one_material_object() -> None:
    by_slot = VectorProcessor._build_relief_meshes(
        matched_shapes=[
            {
                "geometry": box(0.0, 0.0, 10.0, 10.0),
                "recipe": [0, 1, 0],
                "matched_rgb": (255, 0, 0),
            }
        ],
        num_layers=3,
        layer_h=0.08,
        num_channels=2,
        slot_names=["Red", "White"],
        scale_factor=1.0,
        backing_color_id=1,
        default_height_mm=1.0,
        height_mode="color",
        color_height_map={"#ff0000": 1.04},
        heightmap_path=None,
        heightmap_max_height=None,
        bbox=(0.0, 0.0, 10.0, 10.0),
    )

    assert len(by_slot["Red"]["meshes"]) == 1
    assert len(by_slot["White"]["meshes"]) == 1
    assert get_mesh_export_part_ranges(by_slot["Red"]["meshes"][0]) == ()
    assert all(
        mesh.is_watertight
        for data in by_slot.values()
        for mesh in data["meshes"]
    )
