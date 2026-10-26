"""Canonical coordinate transforms retain disk-backed buffers."""
import numpy as np
import pytest
import trimesh


@pytest.mark.parametrize("axes", [(1,), (1, 0)])
def test_layered_transform_matches_existing_coordinates_and_winding(axes):
    from core.vector_mesh_spill import transform_layered_mesh
    mesh = trimesh.creation.icosphere(subdivisions=2)
    mesh.metadata["vector_layer_geometry"] = {}
    expected = mesh.copy()
    vertices, faces = mesh.vertices, mesh.faces
    for axis in axes:
        matrix = np.eye(4)
        matrix[axis, axis] = -1
        expected.apply_transform(matrix)
        transform_layered_mesh(mesh, matrix)
    np.testing.assert_array_equal(mesh.vertices, expected.vertices)
    np.testing.assert_array_equal(mesh.faces, expected.faces)
    assert np.shares_memory(vertices, mesh.vertices)
    assert np.shares_memory(faces, mesh.faces)
    assert mesh.is_watertight


def test_cached_normals_retain_exact_export_bytes():
    from core.vector_mesh_spill import transform_layered_mesh
    mesh = trimesh.creation.icosphere(subdivisions=3)
    mesh.metadata["vector_layer_geometry"] = {}
    _ = mesh.face_normals, mesh.vertex_normals
    expected = mesh.copy(include_cache=True)
    matrix = np.diag([1., -1., 1., 1.])
    expected.apply_transform(matrix)
    transform_layered_mesh(mesh, matrix)
    for name in ("face_normals", "vertex_normals"):
        assert getattr(mesh, name).astype(np.float32).tobytes() == getattr(expected, name).astype(np.float32).tobytes()
