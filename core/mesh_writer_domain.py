"""Bounded float32 preparation for canonical indexed shell meshes.

为规范索引壳体网格提供有界的 float32 写出域准备。
"""

from __future__ import annotations

from typing import Sequence

import numpy as np

from core.mesh_export_parts import MeshExportPartRange


_FACE_CHUNK_SIZE = 65_536
_CONTACT_SHIFT_STEPS_MM = (0.0001, 0.0002, 0.0004)
_DIRECTION_EPSILON = 1e-12
_FRAME_NORMAL_TOLERANCE = 1e-6


def _orthogonal_normal_bits(
    normals: np.ndarray,
    frame_axes: list[np.ndarray],
) -> np.ndarray:
    """Encode normals in their own orthogonal frame, independent of rotation."""

    normal_bits = np.zeros(len(normals), dtype=np.uint8)
    unmatched = np.ones(len(normals), dtype=bool)
    while np.any(unmatched):
        unmatched_indices = np.flatnonzero(unmatched)
        for axis_index, axis in enumerate(frame_axes):
            projections = normals[unmatched_indices] @ axis
            residuals = (
                normals[unmatched_indices]
                - projections[:, None] * axis[None, :]
            )
            matched = (
                np.abs(np.abs(projections) - 1.0) <= _FRAME_NORMAL_TOLERANCE
            ) & (
                np.max(np.abs(residuals), axis=1)
                <= _FRAME_NORMAL_TOLERANCE
            )
            if not np.any(matched):
                continue
            selected_indices = unmatched_indices[matched]
            signs = projections[matched] < 0.0
            bit_indices = axis_index * 2 + signs.astype(np.int64)
            normal_bits[selected_indices] = np.left_shift(
                np.uint8(1),
                bit_indices.astype(np.uint8),
            )
            unmatched[selected_indices] = False
            unmatched_indices = np.flatnonzero(unmatched)
            if len(unmatched_indices) == 0:
                break

        if not np.any(unmatched):
            break
        candidate = normals[int(np.flatnonzero(unmatched)[0])]
        if len(frame_axes) >= 3 or any(
            abs(float(np.dot(candidate, axis))) > _FRAME_NORMAL_TOLERANCE
            for axis in frame_axes
        ):
            raise ValueError(
                "Canonical contact faces do not share an orthogonal frame"
            )
        frame_axes.append(candidate.copy())

    return normal_bits


def _duplicate_vertex_directions(
    writer_vertices: np.ndarray,
    source_vertices: np.ndarray,
    faces: np.ndarray,
    inverse: np.ndarray,
    counts: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    duplicate_mask = counts[inverse] > 1
    duplicate_vertices = np.flatnonzero(duplicate_mask)
    local_index = np.full(len(writer_vertices), -1, dtype=np.int64)
    local_index[duplicate_vertices] = np.arange(
        len(duplicate_vertices),
        dtype=np.int64,
    )
    normal_masks = np.zeros(len(duplicate_vertices), dtype=np.uint8)
    frame_axes: list[np.ndarray] = []

    for start in range(0, len(faces), _FACE_CHUNK_SIZE):
        face_chunk = faces[start : start + _FACE_CHUNK_SIZE]
        face_chunk = face_chunk[np.any(duplicate_mask[face_chunk], axis=1)]
        if len(face_chunk) == 0:
            continue
        writer_triangles = writer_vertices[face_chunk].astype(
            np.float64,
            copy=False,
        )
        writer_normals = np.cross(
            writer_triangles[:, 1] - writer_triangles[:, 0],
            writer_triangles[:, 2] - writer_triangles[:, 0],
        )
        if np.any(np.linalg.norm(writer_normals, axis=1) <= 0.0):
            raise ValueError("Canonical mesh contains a degenerate contact face")

        triangles = source_vertices[face_chunk].astype(np.float64, copy=False)
        normals = np.cross(
            triangles[:, 1] - triangles[:, 0],
            triangles[:, 2] - triangles[:, 0],
        )
        lengths = np.linalg.norm(normals, axis=1)
        if np.any(lengths <= 0.0):
            raise ValueError("Canonical mesh contains a degenerate contact face")
        normals /= lengths[:, None]
        normal_bits = _orthogonal_normal_bits(normals, frame_axes)
        for corner in range(3):
            vertex_indices = face_chunk[:, corner]
            selected = duplicate_mask[vertex_indices]
            np.bitwise_or.at(
                normal_masks,
                local_index[vertex_indices[selected]],
                normal_bits[selected],
            )

    directions = np.zeros((len(duplicate_vertices), 3), dtype=np.float64)
    for axis_index, axis in enumerate(frame_axes):
        positive = (normal_masks & np.uint8(1 << (axis_index * 2))) != 0
        negative = (normal_masks & np.uint8(1 << (axis_index * 2 + 1))) != 0
        # A positive outward normal requires an inward negative displacement,
        # and vice versa. Opposing incident faces cancel on that axis.
        coefficients = negative.astype(np.float64) - positive.astype(np.float64)
        directions += coefficients[:, None] * axis[None, :]
    lengths = np.linalg.norm(directions, axis=1)
    if np.any(lengths <= _DIRECTION_EPSILON):
        raise ValueError("Canonical mesh contact has no bounded inward direction")
    directions /= lengths[:, None]
    return duplicate_vertices, directions


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


def prepare_indexed_shells_for_float32_export(
    mesh: object,
    part_ranges: Sequence[MeshExportPartRange],
) -> tuple[np.ndarray, np.ndarray]:
    """Prepare canonical indexed shells without changing their triangles.

    The labeled mesher can represent edge/point contacts with separate vertex
    indices at the same exact coordinate.  3MF stores float32 coordinates, so
    this function separates only those coincident writer-domain vertices by at
    most 0.0004 mm. The caller performs the one final array-domain triangle
    check immediately before handing these arrays to the native writer.

    规范标签网格可用不同索引表达位于同一坐标的边/点接触。本函数仅在 3MF
    的 float32 写出域内对这些重合顶点做至多 0.0004 mm 的有界分离，且
    保持三角面数量、材料归属和完整覆盖不变；调用方会在交给原生写入器前
    对最终数组执行一次三角面检查。

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
        duplicate_vertices, directions = _duplicate_vertex_directions(
            vertices,
            source_vertices,
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

    return prepared, faces


__all__ = ["prepare_indexed_shells_for_float32_export"]
