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
from core.mesh_export_parts import (
    get_mesh_export_part_ranges,
    mesh_export_parts_are_conditional,
)
from core.vector_mesh_topology import mesh_is_float32_safe


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


@pytest.mark.parametrize(
    "edge_lengths",
    [(1, 1, 1, 1), (2, 1, 2, 1), (3, 2, 4, 2)],
)
def test_split_rectangle_triangulation_is_minimal_and_preserves_its_boundary(
    edge_lengths: tuple[int, int, int, int],
) -> None:
    first, second, third, fourth = edge_lengths
    width = max(first, third)
    height = max(second, fourth)
    coordinates = np.asarray(
        [(index * width / first, 0.0) for index in range(first)]
        + [(float(width), index * height / second) for index in range(second)]
        + [
            (width - index * width / third, float(height))
            for index in range(third)
        ]
        + [
            (0.0, height - index * height / fourth)
            for index in range(fourth)
        ],
        dtype=np.float64,
    )

    faces = layered_meshing._rectangle_ring_triangle_offsets(
        np.asarray(edge_lengths, dtype=np.int32)
    )

    assert len(faces) == len(coordinates) - 2
    triangles = coordinates[faces]
    first_edges = triangles[:, 1] - triangles[:, 0]
    second_edges = triangles[:, 2] - triangles[:, 0]
    twice_area = (
        first_edges[:, 0] * second_edges[:, 1]
        - first_edges[:, 1] * second_edges[:, 0]
    )
    assert np.all(twice_area != 0.0)

    edges = np.concatenate(
        (faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]),
        axis=0,
    )
    edges.sort(axis=1)
    unique_edges, counts = np.unique(edges, axis=0, return_counts=True)
    boundary = {
        tuple(sorted((index, (index + 1) % len(coordinates))))
        for index in range(len(coordinates))
    }
    observed_boundary = {
        tuple(edge) for edge, count in zip(unique_edges, counts) if count == 1
    }
    assert observed_boundary == boundary
    assert np.all(np.isin(counts, [1, 2]))


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
    ranges = get_mesh_export_part_ranges(mesh)
    assert len(ranges) == 2
    assert mesh_export_parts_are_conditional(mesh)
    for part in ranges:
        part_vertices = vertices[part.vertex_start : part.vertex_stop]
        part_faces = (
            np.asarray(mesh.faces[part.face_start : part.face_stop], dtype=np.int64)
            - part.vertex_start
        )
        leaf = trimesh.Trimesh(
            vertices=part_vertices,
            faces=part_faces,
            process=False,
        )
        assert mesh_is_float32_safe(leaf)

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
    assert len(mesh.vertices) == 14
    assert len(mesh.faces) == 24
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
        == 0
    )


def test_diagonal_contact_is_normalized_only_when_validation_requires_it() -> None:
    labels = np.array(
        [
            [[6, -1, 6], [6, 6, 6]],
            [[6, 6, 6], [-1, -1, -1]],
        ],
        dtype=np.int16,
    )

    mesh = build_labeled_surface_mesh(labels, material_id=6, height_px=2)

    assert mesh is not None
    _assert_exact_closed_mesh(mesh, volume=8.0, shell_count=1)
    assert (
        mesh.metadata["layered_mesh_stats"][
            "source_contact_normalized_edge_count"
        ]
        > 0
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


def test_sparse_cuboid_components_use_only_their_local_bounds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    labels = np.full((3, 20, 30), -1, dtype=np.int16)
    labels[0, 1, 2] = 9
    labels[2, 18, 28] = 9
    observed_batches: list[tuple[np.ndarray, np.ndarray]] = []
    original = layered_meshing._cuboid_component_arrays

    def _record_bounds(origins: np.ndarray, ends: np.ndarray, **kwargs):
        observed_batches.append((origins.copy(), ends.copy()))
        return original(origins, ends, **kwargs)

    monkeypatch.setattr(
        layered_meshing,
        "_cuboid_component_arrays",
        _record_bounds,
    )

    mesh = build_labeled_surface_mesh(labels, material_id=9, height_px=20)

    assert mesh is not None
    assert len(observed_batches) == 1
    origins, ends = observed_batches[0]
    np.testing.assert_array_equal(origins, [[2, 1, 0], [28, 18, 2]])
    np.testing.assert_array_equal(ends, [[3, 2, 1], [29, 19, 3]])
    np.testing.assert_array_equal(mesh.bounds, [[2, 1, 0], [29, 19, 3]])
    _assert_exact_closed_mesh(mesh, volume=2.0, shell_count=2)


def test_checkerboard_cuboids_materialize_as_one_bounded_batch(
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
    assert patch_counts == []
    stats = mesh.metadata["layered_mesh_stats"]
    assert stats["component_count"] == size * size // 2
    assert stats["component_chunk_count"] == 1
    assert stats["peak_component_patch_count"] == 6
    assert mesh.is_watertight
    assert float(mesh.volume) == pytest.approx(float(size * size // 2))


def test_repeated_small_non_cuboid_components_share_one_topology_template(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    size = 126
    labels = np.full((1, size, size), -1, dtype=np.int16)
    for row in range(0, size, 3):
        for column in range(0, size, 3):
            labels[0, row, column] = 12
            labels[0, row + 1, column : column + 2] = 12

    topology_calls = 0
    original = layered_meshing._mesh_arrays_from_patches

    def _record_template(patches, **kwargs):
        nonlocal topology_calls
        topology_calls += 1
        return original(patches, **kwargs)

    monkeypatch.setattr(layered_meshing, "_mesh_arrays_from_patches", _record_template)

    mesh = build_labeled_surface_mesh(labels, material_id=12, height_px=size)

    component_count = (size // 3) ** 2
    assert mesh is not None
    assert topology_calls == 1
    assert mesh.metadata["layered_mesh_stats"]["component_count"] == component_count
    assert mesh.metadata["layered_mesh_stats"]["component_chunk_count"] == 1
    _assert_exact_closed_mesh(
        mesh,
        volume=float(component_count * 3),
        shell_count=component_count,
    )


@pytest.mark.parametrize("island_size", [8, 9])
def test_repeated_component_templates_have_no_bbox_size_cliff(
    monkeypatch: pytest.MonkeyPatch,
    island_size: int,
) -> None:
    repetitions = 8
    stride = island_size + 1
    size = repetitions * stride
    labels = np.full((1, size, size), -1, dtype=np.int16)
    for row in range(0, size, stride):
        for column in range(0, size, stride):
            labels[0, row : row + island_size, column] = 13
            labels[0, row + island_size - 1, column : column + island_size] = 13

    topology_calls = 0
    original = layered_meshing._mesh_arrays_from_patches

    def _record_template(patches, **kwargs):
        nonlocal topology_calls
        topology_calls += 1
        return original(patches, **kwargs)

    monkeypatch.setattr(layered_meshing, "_mesh_arrays_from_patches", _record_template)

    mesh = build_labeled_surface_mesh(labels, material_id=13, height_px=size)

    assert mesh is not None
    assert topology_calls == 1
    assert mesh.metadata["layered_mesh_stats"]["component_chunk_count"] == 1
    assert mesh.is_watertight


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

        baseline_peak_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        size = 256
        y, x = np.indices((size, size))
        labels = np.full((2, size, size), -1, dtype=np.int16)
        labels[0] = 1
        labels[1] = np.where((x + y) % 2 == 0, 1, -1)
        mesh = build_labeled_surface_mesh(labels, material_id=1, height_px=size)
        peak_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if sys.platform != "darwin":
            baseline_peak_rss *= 1024
            peak_rss *= 1024
        print(json.dumps({
            "vertices": len(mesh.vertices),
            "faces": len(mesh.faces),
            "volume": float(mesh.volume),
            "watertight": bool(mesh.is_watertight),
            "peak_rss": int(peak_rss),
            "peak_rss_increase": int(max(0, peak_rss - baseline_peak_rss)),
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
        "vertices": 197_125,
        "faces": 394_246,
        "volume": 98_304.0,
        "watertight": True,
        "peak_rss": measured["peak_rss"],
        "peak_rss_increase": measured["peak_rss_increase"],
    }
    assert measured["peak_rss_increase"] < 350 * 1024 * 1024


@pytest.mark.skipif(sys.platform == "win32", reason="resource peak RSS is POSIX-only")
def test_large_topology_retry_releases_the_rejected_first_pass() -> None:
    script = textwrap.dedent(
        """
        import json
        import resource
        import sys

        import numpy as np

        from core.layered_meshing import build_labeled_surface_mesh

        baseline_peak_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        size = 256
        y, x = np.indices((size, size))
        labels = np.full((2, size, size), -1, dtype=np.int16)
        labels[0] = np.where(
            (y % 2 == 1) | ((y % 2 == 0) & (x % 2 == 0)),
            1,
            -1,
        )
        labels[1] = np.where(y % 2 == 0, 1, -1)
        mesh = build_labeled_surface_mesh(labels, material_id=1, height_px=size)
        peak_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if sys.platform != "darwin":
            baseline_peak_rss *= 1024
            peak_rss *= 1024
        stats = mesh.metadata["layered_mesh_stats"]
        print(json.dumps({
            "vertices": len(mesh.vertices),
            "faces": len(mesh.faces),
            "volume": float(mesh.volume),
            "watertight": bool(mesh.is_watertight),
            "normalized_edges": stats["source_contact_normalized_edge_count"],
            "peak_rss": int(peak_rss),
            "peak_rss_increase": int(max(0, peak_rss - baseline_peak_rss)),
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
        "vertices": 197_889,
        "faces": 525_314,
        "volume": 81_920.0,
        "watertight": True,
        "normalized_edges": 32_640,
        "peak_rss": measured["peak_rss"],
        "peak_rss_increase": measured["peak_rss_increase"],
    }
    assert measured["peak_rss_increase"] < 350 * 1024 * 1024


@pytest.mark.skipif(sys.platform == "win32", reason="resource peak RSS is POSIX-only")
def test_large_volume_validation_accepts_only_roundoff_scale_drift() -> None:
    script = textwrap.dedent(
        """
        import json
        import resource
        import sys

        import numpy as np

        from core.layered_meshing import build_labeled_surface_mesh

        baseline_peak_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        size = 512
        y, x = np.indices((size, size))
        labels = np.full((2, size, size), -1, dtype=np.int16)
        labels[0] = 1
        labels[1] = np.where((x + y) % 2 == 0, 1, -1)
        mesh = build_labeled_surface_mesh(labels, material_id=1, height_px=size)
        peak_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if sys.platform != "darwin":
            baseline_peak_rss *= 1024
            peak_rss *= 1024
        print(json.dumps({
            "vertices": len(mesh.vertices),
            "faces": len(mesh.faces),
            "volume": float(mesh.volume),
            "watertight": bool(mesh.is_watertight),
            "peak_rss": int(peak_rss),
            "peak_rss_increase": int(max(0, peak_rss - baseline_peak_rss)),
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
        "vertices": 787_461,
        "faces": 1_574_918,
        "volume": 393_216.0,
        "watertight": True,
        "peak_rss": measured["peak_rss"],
        "peak_rss_increase": measured["peak_rss_increase"],
    }
    assert measured["peak_rss_increase"] < 1_100 * 1024 * 1024
