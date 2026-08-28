"""Regression contract for the retired Vector extrusion implementation."""

from __future__ import annotations

import importlib.util
import inspect

import numpy as np

import core.errors as core_errors
import core.layered_meshing as layered_meshing
import core.model_surface.slot_meshing as slot_meshing
import core.vector_engine as vector_engine
from core.layered_meshing import LayeredMeshPolicy, build_labeled_surface_mesh
from core.vector_engine import VectorProcessor


def test_legacy_vector_topology_generation_surface_is_removed() -> None:
    """Only the canonical layered meshing implementation remains callable."""

    assert importlib.util.find_spec("core.vector_mesh_topology") is None
    assert not hasattr(core_errors, "VectorTopologyError")
    assert not hasattr(VectorProcessor, "_extrude_geometry")
    assert not hasattr(vector_engine, "_build_atomic_prism_mesh")
    assert not hasattr(vector_engine, "_finalize_prism_meshes")
    assert not hasattr(vector_engine, "_build_stepped_volume_mesh_manifold")
    assert not hasattr(vector_engine, "_build_stepped_volume_mesh_python")
    assert not hasattr(vector_engine, "_load_relief_manifold3d")
    assert not hasattr(slot_meshing, "build_slot_box_scene_from_voxels")
    assert not hasattr(slot_meshing, "_build_box_mesh_without_shared_vertices")
    assert "extrude_cache" not in inspect.signature(
        VectorProcessor._run_length_extrude
    ).parameters


def test_production_layered_meshing_does_not_run_full_output_audits(
    monkeypatch,
) -> None:
    """Expensive whole-output audits remain an explicit development option."""

    assert LayeredMeshPolicy().validate_output is False
    monkeypatch.setattr(
        layered_meshing,
        "_validate_component_arrays",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("production called the full mesh audit")
        ),
    )
    monkeypatch.setattr(
        layered_meshing,
        "_indexed_face_edges_are_paired",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("production scanned every generated edge")
        ),
    )

    labels = np.array([[[1, 1], [1, -1]]], dtype=np.int16)
    mesh = build_labeled_surface_mesh(labels, material_id=1, height_px=2)

    assert mesh is not None
    assert mesh.is_watertight
