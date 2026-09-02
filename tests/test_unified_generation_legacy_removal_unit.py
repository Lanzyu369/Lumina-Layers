"""Regression contract for the retired Vector extrusion implementation."""

from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path

import numpy as np
from packaging.requirements import Requirement
from packaging.version import Version

import core.errors as core_errors
import core.layered_meshing as layered_meshing
import core.model_surface.slot_meshing as slot_meshing
import core.vector_engine as vector_engine
import core.vector_layer_geometry as vector_layer_geometry
from core.layered_meshing import LayeredMeshPolicy, build_labeled_surface_mesh
from core.vector_engine import VectorProcessor


_REPO_ROOT = Path(__file__).resolve().parents[1]


def test_shapely_runtime_contract_supports_constrained_cap_triangulation() -> None:
    """Frozen/local installs must include the holed-cap API used in production."""

    requirements = [
        Requirement(line.strip())
        for line in (_REPO_ROOT / "requirements.txt")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
        and not line.lstrip().startswith(("#", "-r ", "--requirement "))
    ]
    shapely_requirement = next(
        requirement
        for requirement in requirements
        if requirement.name.lower() == "shapely"
    )

    assert Version("2.1.0") in shapely_requirement.specifier
    assert Version("2.0.9") not in shapely_requirement.specifier


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
    assert not hasattr(vector_engine, "_build_source_spatial_groups")
    assert not hasattr(vector_layer_geometry, "PreparedVectorSpatialGroups")
    assert not hasattr(vector_layer_geometry, "prepare_vector_spatial_groups")
    assert not hasattr(vector_layer_geometry, "prepare_vector_run_group")
    assert not hasattr(vector_layer_geometry, "extrude_prepared_vector_run_group")
    assert not hasattr(vector_layer_geometry, "build_vector_stepped_volume")
    assert not hasattr(vector_layer_geometry, "_build_single_slab_component")
    assert not hasattr(vector_layer_geometry, "_build_layered_component")
    assert not hasattr(vector_layer_geometry, "_stepped_arrangement_cells")
    assert not hasattr(vector_layer_geometry, "_validate_float32_triangle_domain")
    assert "local_stepped_fallback" not in inspect.getsource(vector_engine)
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
