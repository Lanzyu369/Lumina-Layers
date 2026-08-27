"""Bounded float32 preparation for canonical indexed shell meshes.

为规范索引壳体网格提供有界的 float32 写出域准备。
"""

from __future__ import annotations

import math
from typing import Sequence

import numpy as np
import trimesh

from core.mesh_export_parts import MeshExportPartRange


_FACE_CHUNK_SIZE = 65_536
_CONTACT_SHIFT_STEPS_MM = (0.0001, 0.0002, 0.0004)
_DIRECTION_EPSILON = 1e-12
_AXIS_NORMAL_TOLERANCE = 1e-6


def _axis_normal_bits(normals: np.ndarray) -> np.ndarray:
    """Encode outward axis normals without weighting triangulation diagonals."""

    dominant_axes = np.argmax(np.abs(normals), axis=1)
    dominant_values = normals[
        np.arange(len(normals), dtype=np.int64),
        dominant_axes,
    ]
    residual = normals.copy()
    residual[np.arange(len(normals), dtype=np.int64), dominant_axes] = 0.0
    if (
        np.any(np.abs(np.abs(dominant_values) - 1.0) > _AXIS_NORMAL_TOLERANCE)
        or np.any(np.abs(residual) > _AXIS_NORMAL_TOLERANCE)
    ):
        raise ValueError("Canonical contact faces are not axis aligned")
    signs = dominant_values < 0.0
    bit_indices = dominant_axes * 2 + signs.astype(np.int64)
    return np.left_shift(np.uint8(1), bit_indices.astype(np.uint8))


def _signed_volume(
    vertices: np.ndarray,
    faces: np.ndarray,
) -> float:
    terms: list[float] = []
    for start in range(0, len(faces), _FACE_CHUNK_SIZE):
        triangles = vertices[faces[start : start + _FACE_CHUNK_SIZE]].astype(
            np.float64,
            copy=False,
        )
        terms.append(
            float(
                np.einsum(
                    "ij,ij->i",
                    triangles[:, 0],
                    np.cross(triangles[:, 1], triangles[:, 2]),
                ).sum(dtype=np.float64)
            )
        )
    return math.fsum(terms) / 6.0


def _duplicate_vertex_directions(
    vertices: np.ndarray,
    faces: np.ndarray,
    inverse: np.ndarray,
    counts: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    duplicate_mask = counts[inverse] > 1
    duplicate_vertices = np.flatnonzero(duplicate_mask)
    local_index = np.full(len(vertices), -1, dtype=np.int64)
    local_index[duplicate_vertices] = np.arange(
        len(duplicate_vertices),
        dtype=np.int64,
    )
    normal_masks = np.zeros(len(duplicate_vertices), dtype=np.uint8)

    for start in range(0, len(faces), _FACE_CHUNK_SIZE):
        face_chunk = faces[start : start + _FACE_CHUNK_SIZE]
        face_chunk = face_chunk[np.any(duplicate_mask[face_chunk], axis=1)]
        if len(face_chunk) == 0:
            continue
        triangles = vertices[face_chunk].astype(np.float64, copy=False)
        normals = np.cross(
            triangles[:, 1] - triangles[:, 0],
            triangles[:, 2] - triangles[:, 0],
        )
        lengths = np.linalg.norm(normals, axis=1)
        if np.any(lengths <= 0.0):
            raise ValueError("Canonical mesh contains a degenerate contact face")
        normals /= lengths[:, None]
        normal_bits = _axis_normal_bits(normals)
        for corner in range(3):
            vertex_indices = face_chunk[:, corner]
            selected = duplicate_mask[vertex_indices]
            np.bitwise_or.at(
                normal_masks,
                local_index[vertex_indices[selected]],
                normal_bits[selected],
            )

    directions = np.zeros((len(duplicate_vertices), 3), dtype=np.float64)
    for axis in range(3):
        positive = (normal_masks & np.uint8(1 << (axis * 2))) != 0
        negative = (normal_masks & np.uint8(1 << (axis * 2 + 1))) != 0
        # A positive outward normal requires an inward negative displacement,
        # and vice versa. Opposing incident faces cancel on that axis.
        directions[:, axis] = negative.astype(np.float64) - positive.astype(
            np.float64
        )
    lengths = np.linalg.norm(directions, axis=1)
    if np.any(lengths <= _DIRECTION_EPSILON):
        raise ValueError("Canonical mesh contact has no bounded inward direction")
    directions /= lengths[:, None]
    return duplicate_vertices, directions, normal_masks


def _validate_contact_cones(
    original_vertices: np.ndarray,
    prepared_vertices: np.ndarray,
    duplicate_vertices: np.ndarray,
    inverse: np.ndarray,
    normal_masks: np.ndarray,
) -> None:
    """Prove every repaired contact retracts into its source solid.

    Canonical layered parts have disjoint interiors before export. Their faces
    are axis-aligned and each duplicate index represents one local boundary
    branch. Requiring each displacement to stay in that branch's inward
    tangent cone makes every repaired part a subset of its source solid.
    Pairwise cone exclusion then proves formerly touching branches separate
    instead of crossing into one another.
    """

    displacements = (
        prepared_vertices[duplicate_vertices].astype(np.float64)
        - original_vertices[duplicate_vertices].astype(np.float64)
    )
    displacement_lengths = np.linalg.norm(displacements, axis=1)
    if np.any(displacement_lengths <= 0.0):
        raise ValueError("Canonical mesh contact did not move in float32 domain")

    for axis in range(3):
        positive = (normal_masks & np.uint8(1 << (axis * 2))) != 0
        negative = (normal_masks & np.uint8(1 << (axis * 2 + 1))) != 0
        tolerance = np.maximum(
            displacement_lengths * _AXIS_NORMAL_TOLERANCE,
            np.finfo(np.float32).eps,
        )
        if np.any(displacements[positive, axis] > tolerance[positive]):
            raise ValueError("Canonical mesh contact moved outside its source solid")
        if np.any(displacements[negative, axis] < -tolerance[negative]):
            raise ValueError("Canonical mesh contact moved outside its source solid")

    duplicate_groups = inverse[duplicate_vertices]
    group_order = np.argsort(duplicate_groups, kind="stable")
    ordered_groups = duplicate_groups[group_order]
    group_starts = np.flatnonzero(
        np.concatenate(([True], ordered_groups[1:] != ordered_groups[:-1]))
    )
    group_stops = np.concatenate((group_starts[1:], [len(group_order)]))
    for group_start, group_stop in zip(group_starts, group_stops):
        group_indices = group_order[group_start:group_stop]
        if len(group_indices) < 2:
            continue
        for source_position, source_index in enumerate(group_indices[:-1]):
            other_indices = group_indices[source_position + 1 :]
            source_mask = int(normal_masks[source_index])
            source_other = displacements[other_indices]
            other_outside_source = np.zeros(len(other_indices), dtype=bool)
            source_outside_other = np.zeros(len(other_indices), dtype=bool)
            source_displacement = displacements[source_index]
            for axis in range(3):
                if source_mask & (1 << (axis * 2)):
                    other_outside_source |= source_other[:, axis] > 0.0
                if source_mask & (1 << (axis * 2 + 1)):
                    other_outside_source |= source_other[:, axis] < 0.0

                other_positive = (
                    normal_masks[other_indices] & np.uint8(1 << (axis * 2))
                ) != 0
                other_negative = (
                    normal_masks[other_indices]
                    & np.uint8(1 << (axis * 2 + 1))
                ) != 0
                source_outside_other |= other_positive & (
                    source_displacement[axis] > 0.0
                )
                source_outside_other |= other_negative & (
                    source_displacement[axis] < 0.0
                )
            if np.any(~other_outside_source) or np.any(~source_outside_other):
                raise ValueError(
                    "Canonical mesh contact branches do not separate in writer domain"
                )


def _validate_part_ranges(
    vertices: np.ndarray,
    faces: np.ndarray,
    part_ranges: Sequence[MeshExportPartRange],
) -> None:
    for part in part_ranges:
        part_faces = faces[part.face_start : part.face_stop]
        if (
            part.vertex_start < 0
            or part.face_start < 0
            or part.vertex_stop > len(vertices)
            or part.face_stop > len(faces)
            or part.vertex_stop <= part.vertex_start
            or part.face_stop <= part.face_start
            or np.any(part_faces < part.vertex_start)
            or np.any(part_faces >= part.vertex_stop)
        ):
            raise ValueError("Canonical mesh export part range is invalid")


def _validate_prepared_parts(
    vertices: np.ndarray,
    faces: np.ndarray,
    part_ranges: Sequence[MeshExportPartRange],
) -> None:
    for part in part_ranges:
        part_faces = np.asarray(
            faces[part.face_start : part.face_stop],
            dtype=np.int64,
        ) - part.vertex_start
        part_mesh = trimesh.Trimesh(
            vertices=vertices[part.vertex_start : part.vertex_stop],
            faces=part_faces,
            process=False,
        )
        if not part_mesh.is_watertight or not part_mesh.is_winding_consistent:
            raise ValueError(
                "Canonical mesh part is unsafe after bounded contact separation"
            )


def prepare_indexed_shells_for_float32_export(
    mesh: object,
    part_ranges: Sequence[MeshExportPartRange],
) -> tuple[np.ndarray, np.ndarray]:
    """Prepare canonical indexed shells without changing their triangles.

    The labeled mesher can represent edge/point contacts with separate vertex
    indices at the same exact coordinate.  3MF stores float32 coordinates, so
    this function separates only those coincident writer-domain vertices by at
    most 0.0004 mm, then validates every original closed shell independently.

    规范标签网格可用不同索引表达位于同一坐标的边/点接触。本函数仅在 3MF
    的 float32 写出域内对这些重合顶点做至多 0.0004 mm 的有界分离，并逐个
    校验原始闭合壳体；三角面数量、材料归属和完整覆盖保持不变。

    Args:
        mesh: Canonical mesh in final millimetre coordinates.
            已处于最终毫米坐标的规范网格。
        part_ranges: Contiguous independently closed source shell ranges.
            连续且各自闭合的源壳体范围。

    Returns:
        Read-write contiguous float32 vertices and uint32 faces. The caller may
        mark them read-only for zero-copy ownership.
        连续可写的 float32 顶点与 uint32 三角面；调用方可将其设为只读以供
        零拷贝写出。
    """

    source_vertices = np.asarray(getattr(mesh, "vertices", None))
    source_faces = np.asarray(getattr(mesh, "faces", None))
    if (
        source_vertices.ndim != 2
        or source_vertices.shape[1:] != (3,)
        or len(source_vertices) == 0
        or source_faces.ndim != 2
        or source_faces.shape[1:] != (3,)
        or len(source_faces) == 0
        or not part_ranges
    ):
        raise ValueError("Canonical mesh export arrays are invalid")

    vertices = np.ascontiguousarray(source_vertices, dtype=np.float32)
    faces = np.ascontiguousarray(source_faces, dtype=np.uint32)
    if not np.all(np.isfinite(vertices)):
        raise ValueError("Canonical mesh export coordinates are not finite")
    _validate_part_ranges(vertices, faces, part_ranges)

    _unique, inverse, counts = np.unique(
        vertices,
        axis=0,
        return_inverse=True,
        return_counts=True,
    )
    original_vertices = vertices
    prepared = original_vertices
    if bool(np.any(counts > 1)):
        duplicate_vertices, directions, normal_masks = _duplicate_vertex_directions(
            vertices,
            faces,
            inverse,
            counts,
        )
        prepared = None
        for shift_mm in _CONTACT_SHIFT_STEPS_MM:
            candidate = original_vertices.copy()
            candidate[duplicate_vertices] = np.asarray(
                original_vertices[duplicate_vertices].astype(np.float64)
                + directions * shift_mm,
                dtype=np.float32,
            )
            if len(np.unique(candidate, axis=0)) == len(candidate):
                prepared = candidate
                break
        if prepared is None:
            raise ValueError("Canonical mesh contacts exceed the bounded repair grid")
        _validate_contact_cones(
            original_vertices,
            prepared,
            duplicate_vertices,
            inverse,
            normal_masks,
        )

    for start in range(0, len(faces), _FACE_CHUNK_SIZE):
        triangles = prepared[faces[start : start + _FACE_CHUNK_SIZE]]
        cross = np.cross(
            triangles[:, 1] - triangles[:, 0],
            triangles[:, 2] - triangles[:, 0],
        )
        if np.any(np.all(cross == 0.0, axis=1)):
            raise ValueError("Canonical mesh repair produced a degenerate triangle")

    original_volume = _signed_volume(original_vertices, faces)
    prepared_volume = _signed_volume(prepared, faces)
    volume_tolerance = max(0.5, abs(original_volume) * 5e-4)
    if abs(prepared_volume - original_volume) > volume_tolerance:
        raise ValueError("Canonical mesh repair exceeded the volume tolerance")

    _validate_prepared_parts(prepared, faces, part_ranges)
    return prepared, faces


__all__ = ["prepare_indexed_shells_for_float32_export"]
