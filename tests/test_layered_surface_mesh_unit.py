"""Exact-topology contracts for labeled-volume surface meshing."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap

import numpy as np
import pytest
import trimesh

import core.layered_meshing as layered_meshing
from core.layered_meshing import build_labeled_surface_mesh


def _edge_incidence(mesh: trimesh.Trimesh) -> np.ndarray:
    faces = np.asarray(mesh.faces, dtype=np.int64)
    edges = np.concatenate(
        (faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]),
        axis=0,
    )
    edges.sort(axis=1)
    return np.unique(edges, axis=0, return_counts=True)[1]


def _assert_exact_closed_mesh(
    mesh: trimesh.Trimesh,
    *,
    volume: float,
    shell_count: int,
) -> None:
    assert mesh.is_watertight
    assert np.all(_edge_incidence(mesh) == 2)
    assert float(mesh.volume) == pytest.approx(volume, abs=1e-9)
    assert len(mesh.split(only_watertight=False)) == shell_count
    triangles = np.asarray(mesh.vertices)[np.asarray(mesh.faces)]
    twice_area = np.linalg.norm(
        np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0]),
        axis=1,
    )
    assert np.all(twice_area > 0.0)


def test_single_voxel_has_exact_box_bounds_and_twelve_triangles() -> None:
    labels = np.array([[[7]]], dtype=np.int16)

    mesh = build_labeled_surface_mesh(labels, material_id=7, height_px=1)

    assert mesh is not None
    np.testing.assert_array_equal(mesh.bounds, [[0, 0, 0], [1, 1, 1]])
    assert len(mesh.faces) == 12
    _assert_exact_closed_mesh(mesh, volume=1.0, shell_count=1)

    stats = mesh.metadata["layered_mesh_stats"]
    expected_lattice_bytes = 8 * 3 * 4 + 12 * 3 * 4
    expected_mesh_bytes = mesh.vertices.nbytes + mesh.faces.nbytes
    assert stats["lattice_float32_bytes"] == expected_lattice_bytes
    assert stats["materialized_bytes"] == expected_mesh_bytes
    assert stats["materialized_bytes"] > stats["lattice_float32_bytes"]


def test_face_adjacent_voxels_merge_into_one_rectangular_shell() -> None:
    labels = np.array([[[3, 3]]], dtype=np.int16)

    mesh = build_labeled_surface_mesh(labels, material_id=3, height_px=1)

    assert mesh is not None
    np.testing.assert_array_equal(mesh.bounds, [[0, 0, 0], [2, 1, 1]])
    assert len(mesh.faces) == 12
    assert mesh.metadata["layered_mesh_stats"]["exposed_unit_face_count"] == 10
    assert mesh.metadata["layered_mesh_stats"]["merged_patch_count"] == 6
    _assert_exact_closed_mesh(mesh, volume=2.0, shell_count=1)


@pytest.mark.parametrize(
    "occupied",
    [
        ((0, 0, 0), (0, 1, 1)),  # cubes share only one edge
        ((0, 0, 0), (1, 1, 1)),  # cubes share only one point
    ],
)
def test_edge_or_point_touching_voxels_keep_independent_index_domains(
    occupied: tuple[tuple[int, int, int], tuple[int, int, int]],
) -> None:
    labels = np.full((2, 2, 2), -1, dtype=np.int16)
    labels[occupied[0]] = 4
    labels[occupied[1]] = 4

    mesh = build_labeled_surface_mesh(labels, material_id=4, height_px=2)

    assert mesh is not None
    assert len(mesh.faces) == 24
    _assert_exact_closed_mesh(mesh, volume=2.0, shell_count=2)

    vertices = np.asarray(mesh.vertices)
    assert len(vertices) > len(np.unique(vertices, axis=0))

    stats = mesh.metadata["layered_mesh_stats"]
    if occupied[0][0] == occupied[1][0]:
        assert stats["source_contact_edge_pair_count"] == 1
        assert stats["source_contact_point_pair_count"] == 0
    else:
        assert stats["source_contact_edge_pair_count"] == 0
        assert stats["source_contact_point_pair_count"] == 1


def test_enclosed_air_voxel_forms_a_closed_inward_cavity() -> None:
    labels = np.full((3, 3, 3), 2, dtype=np.int16)
    labels[1, 1, 1] = -1

    mesh = build_labeled_surface_mesh(labels, material_id=2, height_px=3)

    assert mesh is not None
    _assert_exact_closed_mesh(mesh, volume=26.0, shell_count=2)
    stats = mesh.metadata["layered_mesh_stats"]
    assert stats["merged_patch_count"] < stats["exposed_unit_face_count"]


def test_stepped_height_has_no_open_edge_or_t_junction() -> None:
    labels = np.full((2, 1, 2), -1, dtype=np.int16)
    labels[0, 0, :] = 5
    labels[1, 0, 0] = 5

    mesh = build_labeled_surface_mesh(labels, material_id=5, height_px=1)

    assert mesh is not None
    np.testing.assert_array_equal(mesh.bounds, [[0, 0, 0], [2, 1, 2]])
    _assert_exact_closed_mesh(mesh, volume=3.0, shell_count=1)
    assert mesh.metadata["layered_mesh_stats"]["merged_patch_count"] < 14


def test_face_connected_shape_does_not_weld_a_local_diagonal_edge_contact() -> None:
    """A component may contain a separate edge contact elsewhere in its body."""

    labels = np.array(
        [
            [[6, -1], [6, 6]],
            [[6, 6], [-1, -1]],
        ],
        dtype=np.int16,
    )

    mesh = build_labeled_surface_mesh(labels, material_id=6, height_px=2)

    assert mesh is not None
    _assert_exact_closed_mesh(mesh, volume=5.0, shell_count=1)
    assert (
        mesh.metadata["layered_mesh_stats"][
            "source_contact_normalized_edge_count"
        ]
        == 1
    )


def test_neighboring_materials_each_keep_a_closed_interface_surface() -> None:
    labels = np.array([[[1, 2]]], dtype=np.int16)

    left = build_labeled_surface_mesh(labels, material_id=1, height_px=1)
    right = build_labeled_surface_mesh(labels, material_id=2, height_px=1)

    assert left is not None and right is not None
    _assert_exact_closed_mesh(left, volume=1.0, shell_count=1)
    _assert_exact_closed_mesh(right, volume=1.0, shell_count=1)

    for mesh, expected_normal_x in ((left, 1.0), (right, -1.0)):
        centers = np.asarray(mesh.triangles_center)
        normals = np.asarray(mesh.face_normals)
        interface = np.isclose(centers[:, 0], 1.0)
        assert int(interface.sum()) == 2
        np.testing.assert_allclose(normals[interface, 0], expected_normal_x)


def test_face_connected_solid_does_not_report_diagonal_source_contacts() -> None:
    labels = np.ones((1, 2, 2), dtype=np.int16)

    mesh = build_labeled_surface_mesh(labels, material_id=1, height_px=2)

    assert mesh is not None
    stats = mesh.metadata["layered_mesh_stats"]
    assert stats["source_contact_edge_pair_count"] == 0
    assert stats["source_contact_point_pair_count"] == 0


def test_source_rows_are_flipped_into_y_up_world_coordinates() -> None:
    labels = np.array([[[8], [-1]]], dtype=np.int16)

    mesh = build_labeled_surface_mesh(labels, material_id=8, height_px=2)

    assert mesh is not None
    np.testing.assert_array_equal(mesh.bounds, [[0, 1, 0], [1, 2, 1]])


def test_missing_material_returns_none() -> None:
    labels = np.zeros((1, 2, 2), dtype=np.int16)

    assert build_labeled_surface_mesh(labels, material_id=9, height_px=2) is None


def test_sparse_components_are_extracted_from_local_bounding_boxes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    labels = np.full((3, 20, 30), -1, dtype=np.int16)
    labels[0, 1, 2] = 9
    labels[2, 18, 28] = 9
    observed_shapes: list[tuple[int, ...]] = []
    original = layered_meshing._component_patches

    def _record_local_shape(component: np.ndarray, **kwargs):
        observed_shapes.append(component.shape)
        return original(component, **kwargs)

    monkeypatch.setattr(layered_meshing, "_component_patches", _record_local_shape)

    mesh = build_labeled_surface_mesh(labels, material_id=9, height_px=20)

    assert mesh is not None
    assert observed_shapes == [(1, 1, 1), (1, 1, 1)]
    np.testing.assert_array_equal(mesh.bounds, [[2, 1, 0], [29, 19, 3]])
    _assert_exact_closed_mesh(mesh, volume=2.0, shell_count=2)


def test_checkerboard_materializes_each_component_as_a_bounded_chunk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    size = 128
    y, x = np.indices((size, size))
    labels = np.where((x + y) % 2 == 0, 11, -1).astype(np.int16)[None, :, :]
    patch_counts: list[int] = []
    original = layered_meshing._mesh_arrays_from_patches

    def _record_chunk(patches, **kwargs):
        patch_counts.append(len(patches))
        return original(patches, **kwargs)

    monkeypatch.setattr(layered_meshing, "_mesh_arrays_from_patches", _record_chunk)

    mesh = build_labeled_surface_mesh(labels, material_id=11, height_px=size)

    assert mesh is not None
    assert len(patch_counts) == size * size // 2
    assert max(patch_counts) == 6
    stats = mesh.metadata["layered_mesh_stats"]
    assert stats["component_chunk_count"] == size * size // 2
    assert stats["peak_component_patch_count"] == 6
    assert mesh.is_watertight
    assert float(mesh.volume) == pytest.approx(float(size * size // 2))


def test_lattice_float32_rejects_new_coordinate_collisions() -> None:
    labels = np.ones((1, 1, 1), dtype=np.int16)

    with pytest.raises(ValueError, match="lattice float32 collision"):
        build_labeled_surface_mesh(
            labels,
            material_id=1,
            height_px=33_554_432,
        )


def test_lattice_float32_audit_includes_the_exact_boundary() -> None:
    exact = np.array(
        [[2**24, 0, 0], [2**24 + 1, 0, 0]],
        dtype=np.int64,
    )
    lattice_float32 = exact.astype(np.float32) * np.float32(0.5)
    audit = layered_meshing._LatticeFloat32Audit()

    with pytest.raises(ValueError, match="lattice float32 collision"):
        audit.observe(exact, lattice_float32)


@pytest.mark.skipif(sys.platform == "win32", reason="resource peak RSS is POSIX-only")
def test_large_connected_checkerboard_relief_stays_compact_in_a_subprocess() -> None:
    script = textwrap.dedent(
        """
        import json
        import resource
        import sys

        import numpy as np

        from core.layered_meshing import build_labeled_surface_mesh

        size = 256
        y, x = np.indices((size, size))
        labels = np.full((2, size, size), -1, dtype=np.int16)
        labels[0] = 1
        labels[1] = np.where((x + y) % 2 == 0, 1, -1)
        mesh = build_labeled_surface_mesh(labels, material_id=1, height_px=size)
        peak_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if sys.platform != "darwin":
            peak_rss *= 1024
        print(json.dumps({
            "vertices": len(mesh.vertices),
            "faces": len(mesh.faces),
            "volume": float(mesh.volume),
            "watertight": bool(mesh.is_watertight),
            "peak_rss": int(peak_rss),
        }))
        """
    )
    environment = os.environ.copy()
    environment.update(KMP_DUPLICATE_LIB_OK="TRUE", OMP_NUM_THREADS="1")

    result = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    measured = json.loads(result.stdout.strip().splitlines()[-1])

    assert measured == {
        "vertices": 457_739,
        "faces": 915_474,
        "volume": 98_304.0,
        "watertight": True,
        "peak_rss": measured["peak_rss"],
    }
    assert measured["peak_rss"] < 350 * 1024 * 1024
