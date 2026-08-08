from __future__ import annotations

import pytest
import trimesh

from core.model_surface.types import ModelSurfaceError
from core.model_surface.validation import (
    prepare_model_surface_mesh_for_boolean,
    validate_model_surface_mesh_for_boolean,
)


def test_validate_rejects_open_mesh() -> None:
    mesh = trimesh.creation.box(extents=(20.0, 20.0, 2.0))
    mesh.update_faces(mesh.face_normals[:, 2] < 0.9)
    mesh.remove_unreferenced_vertices()

    with pytest.raises(
        ModelSurfaceError,
        match=r"^model_surface_mesh_not_watertight$",
    ):
        validate_model_surface_mesh_for_boolean(mesh)


def test_prepare_unions_overlapping_watertight_bodies() -> None:
    primary = trimesh.creation.box(extents=(20.0, 20.0, 2.0))
    detail = trimesh.creation.box(extents=(8.0, 8.0, 2.0))
    detail.apply_translation((6.0, 0.0, 0.0))
    source = trimesh.util.concatenate((primary, detail))
    source.metadata["name"] = "surface-source"

    prepared = prepare_model_surface_mesh_for_boolean(source)

    assert prepared.is_volume
    assert len(prepared.split(only_watertight=False)) == 1
    assert prepared.metadata["name"] == "surface-source"
    assert prepared.volume < primary.volume + detail.volume
