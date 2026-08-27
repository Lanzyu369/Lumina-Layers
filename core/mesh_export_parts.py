"""Lightweight contracts for preserving independent 3MF mesh leaves.

用于在最终 3MF 写出前保留独立闭合网格分片的轻量契约。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


_EXPORT_PART_RANGES_ATTRIBUTE = "_lumina_3mf_export_part_ranges_v1"
_EXPORT_PARTS_CONDITIONAL_ATTRIBUTE = (
    "_lumina_3mf_export_parts_only_when_combined_unsafe_v1"
)


@dataclass(frozen=True, slots=True)
class MeshExportPartRange:
    """Contiguous vertex/face ranges for one independently closed mesh leaf.

    表示一个独立闭合网格分片在合并数组中的连续顶点与三角面范围。
    """

    vertex_start: int
    vertex_stop: int
    face_start: int
    face_stop: int


def _coerce_part_range(value: object) -> MeshExportPartRange:
    if isinstance(value, MeshExportPartRange):
        return value
    try:
        vertex_start, vertex_stop, face_start, face_stop = value  # type: ignore[misc]
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid 3MF mesh part range") from exc
    return MeshExportPartRange(
        int(vertex_start),
        int(vertex_stop),
        int(face_start),
        int(face_stop),
    )


def get_mesh_export_part_ranges(mesh: object) -> tuple[MeshExportPartRange, ...]:
    """Return validated contiguous export ranges attached to *mesh*.

    返回附着在网格上的、覆盖完整数组且连续有效的 3MF 分片范围。
    """

    raw_ranges = getattr(mesh, _EXPORT_PART_RANGES_ATTRIBUTE, None)
    if raw_ranges is None:
        return ()
    try:
        ranges = tuple(_coerce_part_range(value) for value in raw_ranges)
        vertex_count = len(getattr(mesh, "vertices"))
        face_count = len(getattr(mesh, "faces"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("Invalid 3MF mesh part ranges") from exc
    expected_vertex_start = 0
    expected_face_start = 0
    for part in ranges:
        if (
            part.vertex_start != expected_vertex_start
            or part.face_start != expected_face_start
            or part.vertex_stop <= part.vertex_start
            or part.face_stop <= part.face_start
            or part.vertex_stop > vertex_count
            or part.face_stop > face_count
        ):
            raise ValueError("3MF mesh part ranges must be contiguous and non-empty")
        expected_vertex_start = part.vertex_stop
        expected_face_start = part.face_stop
    if (
        not ranges
        or expected_vertex_start != vertex_count
        or expected_face_start != face_count
    ):
        raise ValueError("3MF mesh part ranges must cover the complete mesh")
    return ranges


def set_mesh_export_part_ranges(
    mesh: object,
    ranges: Iterable[MeshExportPartRange | tuple[int, int, int, int]],
    *,
    only_when_combined_unsafe: bool = False,
) -> None:
    """Attach and validate independently closed 3MF leaf ranges.

    为合并网格附加并校验独立闭合的 3MF 子网格范围。
    """

    normalized = tuple(_coerce_part_range(value) for value in ranges)
    setattr(mesh, _EXPORT_PART_RANGES_ATTRIBUTE, normalized)
    setattr(
        mesh,
        _EXPORT_PARTS_CONDITIONAL_ATTRIBUTE,
        bool(only_when_combined_unsafe),
    )
    try:
        get_mesh_export_part_ranges(mesh)
    except (AttributeError, TypeError, ValueError):
        delattr(mesh, _EXPORT_PART_RANGES_ATTRIBUTE)
        delattr(mesh, _EXPORT_PARTS_CONDITIONAL_ATTRIBUTE)
        raise


def mesh_export_parts_are_conditional(mesh: object) -> bool:
    """Return whether attached leaves are used only for an unsafe aggregate.

    返回是否仅在合并网格本身不安全时才展开已附加的叶子范围。
    """

    if not get_mesh_export_part_ranges(mesh):
        return False
    return bool(getattr(mesh, _EXPORT_PARTS_CONDITIONAL_ATTRIBUTE, False))


def copy_mesh_export_part_ranges(source: object, target: object) -> None:
    """Copy the explicit shell-range contract between equivalent meshes.

    在几何等价的网格副本之间复制显式壳体范围契约。
    """

    ranges = get_mesh_export_part_ranges(source)
    if not ranges:
        return
    set_mesh_export_part_ranges(
        target,
        ranges,
        only_when_combined_unsafe=mesh_export_parts_are_conditional(source),
    )


def set_concatenated_mesh_export_part_ranges(
    combined: object,
    sources: Iterable[object],
) -> None:
    """Attach source shell ranges after an index-preserving concatenation.

    Trimesh deliberately drops custom attributes during concatenation. This
    helper reconstructs the offset ranges. The aggregate remains conditional
    only when every source already carried that stronger canonical contract;
    otherwise the writer exposes the independent leaves unconditionally.

    Trimesh 合并时会丢弃自定义属性。本函数按顶点和三角面偏移重建范围；
    只有全部源网格都带有更强的规范条件契约时，合并结果才继续采用条件式
    写出，否则写入器会直接展开独立闭合分片。
    """

    normalized_sources = tuple(sources)
    if not normalized_sources:
        raise ValueError("Concatenated 3MF mesh sources must not be empty")

    ranges: list[MeshExportPartRange] = []
    vertex_offset = 0
    face_offset = 0
    all_conditional = True
    for source in normalized_sources:
        try:
            vertex_count = len(getattr(source, "vertices"))
            face_count = len(getattr(source, "faces"))
        except (AttributeError, TypeError) as exc:
            raise ValueError("Invalid concatenated 3MF mesh source") from exc
        if vertex_count <= 0 or face_count <= 0:
            raise ValueError("Concatenated 3MF mesh sources must be non-empty")

        source_ranges = get_mesh_export_part_ranges(source)
        if source_ranges:
            ranges.extend(
                MeshExportPartRange(
                    vertex_start=vertex_offset + part.vertex_start,
                    vertex_stop=vertex_offset + part.vertex_stop,
                    face_start=face_offset + part.face_start,
                    face_stop=face_offset + part.face_stop,
                )
                for part in source_ranges
            )
            all_conditional = (
                all_conditional and mesh_export_parts_are_conditional(source)
            )
        else:
            ranges.append(
                MeshExportPartRange(
                    vertex_start=vertex_offset,
                    vertex_stop=vertex_offset + vertex_count,
                    face_start=face_offset,
                    face_stop=face_offset + face_count,
                )
            )
            all_conditional = False
        vertex_offset += vertex_count
        face_offset += face_count

    if (
        vertex_offset != len(getattr(combined, "vertices"))
        or face_offset != len(getattr(combined, "faces"))
    ):
        raise ValueError("Concatenated 3MF mesh arrays do not match their sources")
    set_mesh_export_part_ranges(
        combined,
        ranges,
        only_when_combined_unsafe=all_conditional,
    )
