"""Integration contracts for the shared raster and native-Vector mesh cores."""

from __future__ import annotations

import numpy as np
import pytest
from shapely.geometry import box

import core.mesh_generators as mesh_generators
import core.vector_engine as vector_engine
from config import ModelingMode
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


def test_native_svg_runs_use_canonical_direct_extrusion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_geometries = [
        box(0.0, 0.0, 10.0, 10.0),
        box(10.0, 0.0, 20.0, 10.0),
        box(30.0, 0.0, 35.0, 5.0),
    ]
    prepare_calls = 0
    extrude_calls = 0
    real_prepare = vector_engine.prepare_vector_run_group
    real_extrude = vector_engine.extrude_prepared_vector_run_group

    def recording_prepare(*args, **kwargs):
        nonlocal prepare_calls
        prepare_calls += 1
        return real_prepare(*args, **kwargs)

    def recording_extrude(*args, **kwargs):
        nonlocal extrude_calls
        extrude_calls += 1
        return real_extrude(*args, **kwargs)

    monkeypatch.setattr(vector_engine, "prepare_vector_run_group", recording_prepare)
    monkeypatch.setattr(
        vector_engine,
        "extrude_prepared_vector_run_group",
        recording_extrude,
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
    stats = mesh.metadata["vector_layer_geometry"]
    assert prepare_calls == 1
    assert extrude_calls == 1
    assert stats["source_geometry_count"] == 3
    assert stats["output_component_count"] == 2
    assert stats["source_area_mm2"] == pytest.approx(225.0)
    assert stats["output_area_mm2"] == pytest.approx(225.0)
    assert mesh.is_watertight
    assert np.all(_edge_incidence(mesh) == 2)
    assert float(mesh.volume) == pytest.approx(225.0 * 0.16)


def test_native_svg_relief_uses_direct_canonical_stepped_surface(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    real_builder = vector_engine.build_vector_stepped_volume

    def recording_builder(*args, **kwargs):
        nonlocal calls
        calls += 1
        return real_builder(*args, **kwargs)

    monkeypatch.setattr(
        vector_engine,
        "build_vector_stepped_volume",
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
    assert calls == 1
    assert board.metadata["vector_stepped_geometry"]["component_count"] == 1
    assert board.is_watertight
    assert np.all(_edge_incidence(board) == 2)
