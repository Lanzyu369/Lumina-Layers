"""Unified Vector mesh topology and memory regression tests."""

from __future__ import annotations

import numpy as np
import pytest
import trimesh
from shapely.geometry import MultiPolygon, box

import core.vector_engine as vector_engine
from core.vector_engine import (
    VectorAnalysis,
    VectorProcessor,
    _concatenate_meshes_fast,
)
from core.errors import VectorMeshMemoryBudgetError


def _edge_incidence_counts(mesh: trimesh.Trimesh) -> np.ndarray:
    faces = np.asarray(mesh.faces, dtype=np.int64)
    edges = np.concatenate(
        (faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]),
        axis=0,
    )
    edges.sort(axis=1)
    return np.unique(edges, axis=0, return_counts=True)[1]


def _assert_closed(mesh: trimesh.Trimesh, *, volume: float) -> None:
    assert mesh.is_watertight
    assert mesh.is_winding_consistent
    assert np.all(_edge_incidence_counts(mesh) == 2)
    assert abs(float(mesh.volume)) == pytest.approx(volume, abs=1e-5)


def _run_one_material(geometries, *, height: float = 0.2):
    result = VectorProcessor._run_length_extrude(
        matched_shapes=[
            {"geometry": geometry, "recipe": [0]}
            for geometry in geometries
        ],
        num_layers=1,
        layer_h=height,
        num_channels=1,
        slot_names=["White"],
        scale_factor=1.0,
    )
    return result["White"]["meshes"]


def test_run_length_keeps_large_body_and_printable_island() -> None:
    """A remote 5x5 mm island cannot disappear beside a 200x200 mm body."""

    meshes = _run_one_material(
        [
            box(0.0, 0.0, 200.0, 200.0),
            box(210.0, 0.0, 215.0, 5.0),
        ]
    )
    combined = _concatenate_meshes_fast(meshes)

    _assert_closed(combined, volume=(40_000.0 + 25.0) * 0.2)
    assert len(combined.split(only_watertight=False)) == 2


def test_run_length_keeps_point_touching_shells_independent() -> None:
    geometry = MultiPolygon(
        [
            box(0.0, 0.0, 1.0, 1.0),
            box(1.0, 1.0, 2.0, 2.0),
        ]
    )
    assert geometry.is_valid

    combined = _concatenate_meshes_fast(_run_one_material([geometry]))

    _assert_closed(combined, volume=0.4)
    assert len(combined.split(only_watertight=False)) == 2


def test_whole_run_failure_recovers_with_the_same_canonical_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Whole-run failure retries only through canonical spatial groups."""

    calls = 0
    real_prepare = vector_engine.prepare_vector_run_group

    def fail_first_prepare(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ValueError("synthetic whole-run failure")
        return real_prepare(*args, **kwargs)

    monkeypatch.setattr(
        vector_engine,
        "prepare_vector_run_group",
        fail_first_prepare,
    )

    combined = _concatenate_meshes_fast(
        _run_one_material(
            [box(0.0, 0.0, 1.0, 1.0), box(2.0, 0.0, 3.0, 1.0)]
        )
    )

    assert calls == 1
    _assert_closed(combined, volume=0.4)
    assert len(combined.split(only_watertight=False)) == 2


def test_run_length_does_not_retry_memory_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        vector_engine,
        "prepare_vector_run_group",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(MemoryError("budget")),
    )

    with pytest.raises(MemoryError, match="budget"):
        _run_one_material([box(0.0, 0.0, 1.0, 1.0)])


def test_double_sided_groups_by_material_run_not_svg_shape_count() -> None:
    matched_shapes = [
        {
            "geometry": box(float(index * 2), 0.0, float(index * 2 + 1), 1.0),
            "recipe": [0, 1],
        }
        for index in range(100)
    ]
    meshes_by_slot: dict[str, dict[str, object]] = {}

    VectorProcessor._add_double_sided_layers(
        matched_shapes=matched_shapes,
        num_layers=2,
        layer_h=0.08,
        num_channels=2,
        slot_names=["White", "Red"],
        scale_factor=1.0,
        top_z_start=1.6,
        meshes_by_slot=meshes_by_slot,
    )

    assert len(meshes_by_slot["White"]["meshes"]) == 1
    assert len(meshes_by_slot["Red"]["meshes"]) == 1
    assert all(
        mesh.is_watertight
        for data in meshes_by_slot.values()
        for mesh in data["meshes"]
    )


def test_auxiliary_islands_are_aggregated_per_material() -> None:
    geometry = MultiPolygon(
        [
            box(float(index * 2), 0.0, float(index * 2 + 1), 1.0)
            for index in range(100)
        ]
    )

    mesh = VectorProcessor._extrude_spatial_geometry_group(
        geometry,
        height=0.08,
        z_offset=-0.08,
        scale=1.0,
        stage="coating",
    )

    _assert_closed(mesh, volume=8.0)
    assert len(mesh.split(only_watertight=False)) == 100


def test_build_mesh_rejects_over_budget_before_meshing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LUMINA_VECTOR_MESH_MEMORY_BUDGET_MB", "1")
    processor = VectorProcessor.__new__(VectorProcessor)
    processor.color_mode = "4-Color (RYBW)"
    geometry = box(0.0, 0.0, 2.0, 2.0)
    analysis = VectorAnalysis(
        shape_data=[],
        clipped_shapes=[],
        matched_shapes=[{"geometry": geometry, "recipe": [0]}],
        silhouette=geometry,
        scale_factor=1.0,
        bbox=(0.0, 0.0, 2.0, 2.0),
        color_conf={},
        slot_names=["White"],
        num_channels=1,
        num_layers=1,
        preview_colors={0: [255, 255, 255, 255]},
    )

    with pytest.raises(VectorMeshMemoryBudgetError) as raised:
        processor.build_mesh(
            analysis=analysis,
            thickness_mm=0.0,
            structure_mode="Single-sided",
        )

    assert raised.value.stage == "preflight"
