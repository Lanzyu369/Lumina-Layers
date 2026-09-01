"""Canonical physical-grid geometry for native Vector layer runs.

Native SVG coordinates are converted to millimetres and noded on one shared
integer grid before any 3D allocation.  This makes shared boundaries identical
by construction and keeps independent printable islands explicit.

原生 SVG 坐标在分配三维网格前统一转换为毫米，并在共享整数网格上节点化；
因此共享边天然一致，独立可打印小岛也不会被静默丢弃。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

import numpy as np
import shapely
import trimesh
from mapbox_earcut import triangulate_float64
from shapely import STRtree, affinity, set_precision
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.geometry.polygon import orient
from shapely.validation import make_valid


_MAX_CONTACT_TRANSLATION_GRID_UNITS = 4


@dataclass(frozen=True)
class VectorLayerGeometryPolicy:
    """Physical-grid and fidelity policy for one Vector run group.
    单个 Vector 走层组的物理网格与保真策略。
    """

    grid_mm: float = 0.0001


def resolve_vector_writer_grid_mm(
    maximum_abs_coordinate_mm: float,
    *,
    minimum_mm: float = VectorLayerGeometryPolicy().grid_mm,
) -> float:
    """Resolve the physical grid that remains distinct in float32 output.
    计算在 float32 写出域中仍能保持坐标可区分的物理网格。

    Args:
        maximum_abs_coordinate_mm: Largest absolute XY coordinate in mm.
            XY 坐标绝对值的毫米上限。
        minimum_mm: Minimum canonical grid size in mm.
            规范网格的最小毫米尺寸。

    Returns:
        Writer-safe canonical grid size in mm.
        写出安全的规范网格尺寸（毫米）。
    """

    maximum_coordinate = float(maximum_abs_coordinate_mm)
    minimum_grid = float(minimum_mm)
    if (
        not math.isfinite(maximum_coordinate)
        or maximum_coordinate < 0.0
        or not math.isfinite(minimum_grid)
        or minimum_grid <= 0.0
    ):
        raise ValueError("Vector writer grid inputs must be finite and positive")
    writer_value = np.float32(maximum_coordinate)
    writer_ulp = abs(float(np.spacing(writer_value)))
    if not math.isfinite(writer_ulp):
        raise ValueError("Vector physical coordinates exceed float32 writer range")
    return max(minimum_grid, writer_ulp * 4.0)


def snap_vector_writer_coordinate_mm(
    coordinate_mm: float,
    *,
    grid_mm: float,
) -> float:
    """Snap one coordinate with the same half-grid rule as GEOS.
    使用与 GEOS 相同的半网格规则对单个坐标取整。

    Args:
        coordinate_mm: Coordinate in physical millimetres.
            物理毫米坐标。
        grid_mm: Canonical writer grid size in millimetres.
            规范写出网格尺寸（毫米）。

    Returns:
        Coordinate snapped to the canonical writer grid.
        吸附到规范写出网格后的坐标。
    """

    coordinate = float(coordinate_mm)
    grid = float(grid_mm)
    if (
        not math.isfinite(coordinate)
        or not math.isfinite(grid)
        or grid <= 0.0
    ):
        raise ValueError("Vector writer coordinate inputs must be finite")
    scaled_coordinate = coordinate / grid
    if not math.isfinite(scaled_coordinate):
        raise ValueError("Vector writer coordinate exceeds canonical grid range")
    return float(math.floor(scaled_coordinate + 0.5) * grid)


@dataclass(frozen=True)
class _IndexedPolygon:
    """One canonical polygon stored only as compact integer rings."""

    exterior_units: np.ndarray
    hole_units: tuple[np.ndarray, ...]


@dataclass(frozen=True)
class _IndexedRunGroup:
    """Compact indexed rings for one fixed-Z printable footprint."""

    polygons: tuple[_IndexedPolygon, ...]
    grid_mm: float
    area_mm2: float
    coordinate_count: int
    hole_count: int
    separated_ring_contact_count: int


@dataclass(frozen=True)
class _PhysicalLayerSlab:
    geometry: BaseGeometry
    z_start_mm: float
    z_end_mm: float


def _polygon_parts(geometry: BaseGeometry) -> tuple[Polygon, ...]:
    """Return printable polygon parts, ignoring zero-area collection residue."""

    if isinstance(geometry, GeometryCollection):
        parts = tuple(
            polygon
            for item in geometry.geoms
            if isinstance(item, (Polygon, MultiPolygon))
            for polygon in _polygon_parts(item)
        )
        if not parts:
            raise ValueError("Vector run group requires polygonal geometry")
        return parts
    if not isinstance(geometry, (Polygon, MultiPolygon)):
        raise ValueError("Vector run group requires polygonal geometry")
    if not geometry.is_valid:
        return _polygon_parts(make_valid(geometry))
    if isinstance(geometry, Polygon):
        parts = (geometry,)
    else:
        parts = tuple(geometry.geoms)
    if not parts or any(part.is_empty or float(part.area) <= 0.0 for part in parts):
        raise ValueError("Vector run group contains empty polygonal geometry")
    return parts


def _polygon_has_ring_contact(polygon: Polygon) -> bool:
    """Return whether distinct boundary rings touch in physical space."""

    if not polygon.interiors:
        return False
    shell_boundary = Polygon(polygon.exterior).boundary
    holes = [Polygon(ring) for ring in polygon.interiors]
    tree = STRtree(holes)
    if len(tree.query(shell_boundary, predicate="intersects")) > 0:
        return True
    pairs = np.asarray(tree.query(holes, predicate="intersects"), dtype=np.int64)
    return bool(pairs.size and np.any(pairs[0] < pairs[1]))


def _bounded_lattice_translation_candidates(
    *,
    grid_mm: float,
    preferred_directions: Sequence[tuple[int, int]],
) -> list[tuple[float, float]]:
    """Return every bounded integer-grid shift in deterministic order.

    Cardinal and diagonal moves retain their historical priority.  The rest
    of each Chebyshev ring is then searched by Euclidean distance, so narrow
    contact wedges can use shifts such as two grid units by one without
    increasing the constructive displacement bound.
    """

    preferred = list(dict.fromkeys(preferred_directions))
    result: list[tuple[float, float]] = []
    for radius in range(1, _MAX_CONTACT_TRANSLATION_GRID_UNITS + 1):
        ring = {
            (dx, dy)
            for dx in range(-radius, radius + 1)
            for dy in range(-radius, radius + 1)
            if max(abs(dx), abs(dy)) == radius
        }
        ordered_units: list[tuple[int, int]] = []
        for direction_x, direction_y in preferred:
            candidate = (direction_x * radius, direction_y * radius)
            if candidate in ring:
                ordered_units.append(candidate)
                ring.remove(candidate)
        ordered_units.extend(
            sorted(
                ring,
                key=lambda offset: (
                    offset[0] * offset[0] + offset[1] * offset[1],
                    offset[0],
                    offset[1],
                ),
            )
        )
        result.extend(
            (
                float(dx) * float(grid_mm),
                float(dy) * float(grid_mm),
            )
            for dx, dy in ordered_units
        )
    return result


def _ring_translation_candidates(*, grid_mm: float) -> list[tuple[float, float]]:
    """Return deterministic sub-nozzle translations for touching holes."""

    directions = (
        (1, 0),
        (-1, 0),
        (0, 1),
        (0, -1),
        (1, 1),
        (1, -1),
        (-1, 1),
        (-1, -1),
    )
    return _bounded_lattice_translation_candidates(
        grid_mm=float(grid_mm),
        preferred_directions=directions,
    )


def _translate_on_physical_grid(
    polygon: Polygon,
    *,
    x_offset: float,
    y_offset: float,
    grid_mm: float,
) -> Polygon | None:
    """Translate and immediately restore exact physical-grid coordinates."""

    translated = affinity.translate(
        polygon,
        xoff=float(x_offset),
        yoff=float(y_offset),
    )
    snapped = set_precision(
        translated,
        grid_size=float(grid_mm),
        mode="pointwise",
    )
    if not isinstance(snapped, Polygon) or snapped.is_empty or not snapped.is_valid:
        return None
    return snapped


def _separate_polygon_ring_contacts(
    polygon: Polygon,
    *,
    grid_mm: float,
) -> tuple[Polygon, bool]:
    """Separate point-touching holes without changing their area.

    OGC-valid polygons may let a hole touch the shell or another hole at one
    point.  A closed indexed prism cannot represent that weakly-simple contact:
    the cap and the two wall rings need different indices at the same writer
    coordinate.  Translate only the touching hole by a few writer-safe grid
    units before triangulation.  The hole area is unchanged and the bounded
    displacement is orders of magnitude below supported nozzle widths.
    """

    if not _polygon_has_ring_contact(polygon):
        return polygon, False

    shell = _translate_on_physical_grid(
        Polygon(polygon.exterior),
        x_offset=0.0,
        y_offset=0.0,
        grid_mm=float(grid_mm),
    )
    if shell is None:
        raise ValueError("Vector outer ring could not enter the writer grid")
    shell_boundary = shell.boundary
    holes = []
    for ring in polygon.interiors:
        snapped_hole = _translate_on_physical_grid(
            Polygon(ring),
            x_offset=0.0,
            y_offset=0.0,
            grid_mm=float(grid_mm),
        )
        if snapped_hole is None:
            raise ValueError("Vector inner ring could not enter the writer grid")
        holes.append(snapped_hole)
    writer_area = float(shell.area) - math.fsum(float(hole.area) for hole in holes)
    translated = False
    candidates = _ring_translation_candidates(grid_mm=float(grid_mm))
    hole_tree = STRtree(holes)
    shell_contacts = {
        int(index)
        for index in np.asarray(
            hole_tree.query(shell_boundary, predicate="intersects")
        ).reshape(-1)
    }
    touching_neighbors: dict[int, set[int]] = {}
    pairs = np.asarray(
        hole_tree.query(holes, predicate="intersects"),
        dtype=np.int64,
    )
    if pairs.size:
        for first_index, second_index in pairs.T:
            first = int(first_index)
            second = int(second_index)
            if first >= second:
                continue
            touching_neighbors.setdefault(first, set()).add(second)
            touching_neighbors.setdefault(second, set()).add(first)

    pending_indices = sorted(
        shell_contacts | set(touching_neighbors),
        key=lambda index: (
            float(holes[index].area),
            *holes[index].bounds,
            int(index),
        ),
    )
    maximum_relative_motion = float(grid_mm) * 12.0
    while pending_indices:
        deferred_indices: list[int] = []
        moved_this_pass = False
        for hole_index in pending_indices:
            hole = holes[hole_index]
            neighbor_indices = {
                int(index)
                for index in np.asarray(
                    hole_tree.query(
                        hole,
                        predicate="dwithin",
                        distance=maximum_relative_motion,
                    )
                ).reshape(-1)
                if int(index) != hole_index
            }
            neighbor_indices.update(touching_neighbors.get(hole_index, ()))
            requires_separation = (
                shell_boundary.intersects(hole.boundary)
                or any(
                    hole.intersects(holes[index])
                    for index in neighbor_indices
                )
            )
            if not requires_separation:
                continue

            separated = None
            for x_offset, y_offset in candidates:
                candidate = _translate_on_physical_grid(
                    hole,
                    x_offset=x_offset,
                    y_offset=y_offset,
                    grid_mm=float(grid_mm),
                )
                if candidate is None:
                    continue
                if (
                    shell.contains(candidate)
                    and shell_boundary.disjoint(candidate)
                    and all(
                        candidate.disjoint(holes[index])
                        for index in neighbor_indices
                    )
                ):
                    separated = candidate
                    break
            if separated is None:
                # A large ring may be boxed in by smaller point contacts (or
                # vice versa).  Move every currently feasible neighbour first,
                # then retry the blocked ring against the updated geometry.
                deferred_indices.append(hole_index)
                continue
            holes[hole_index] = separated
            translated = True
            moved_this_pass = True

        if not deferred_indices:
            break
        if not moved_this_pass:
            raise ValueError(
                "Vector point-touching rings could not remain independent"
            )
        pending_indices = deferred_indices

    result = Polygon(
        shell.exterior.coords,
        [hole.exterior.coords for hole in holes],
    )
    if result.is_empty or not result.is_valid or _polygon_has_ring_contact(result):
        raise ValueError("Vector physical-grid output retains touching rings")
    area_tolerance = max(1e-12, abs(writer_area) * 1e-12)
    if abs(float(result.area) - writer_area) > area_tolerance:
        raise ValueError("Vector ring separation changed printable coverage")
    return result, translated


def _signed_twice_ring_area(coordinates: np.ndarray) -> float:
    values = np.asarray(coordinates, dtype=np.float64)
    return float(
        np.sum(
            values[:, 0] * np.roll(values[:, 1], -1)
            - values[:, 1] * np.roll(values[:, 0], -1),
            dtype=np.float64,
        )
    )


def _indexed_polygon_area_mm2(
    polygon: _IndexedPolygon,
    *,
    grid_mm: float,
) -> float:
    twice_area_units = abs(_signed_twice_ring_area(polygon.exterior_units))
    twice_area_units -= math.fsum(
        abs(_signed_twice_ring_area(ring))
        for ring in polygon.hole_units
    )
    if not math.isfinite(twice_area_units) or twice_area_units <= 0.0:
        raise ValueError("Vector canonical polygon has non-positive area")
    return twice_area_units * float(grid_mm) * float(grid_mm) * 0.5


def _oriented_polygon_rings(polygon: _IndexedPolygon) -> list[np.ndarray]:
    rings = [polygon.exterior_units, *polygon.hole_units]
    oriented_rings: list[np.ndarray] = []
    for index, ring in enumerate(rings):
        signed_area = _signed_twice_ring_area(ring)
        if signed_area == 0.0 or not math.isfinite(signed_area):
            raise ValueError("Vector canonical ring has zero signed area")
        should_be_positive = index == 0
        if (signed_area > 0.0) != should_be_positive:
            oriented_rings.append(np.ascontiguousarray(ring[::-1]))
        else:
            oriented_rings.append(ring)
    return oriented_rings


def _cap_expected_boundary_edges(ring_ends: np.ndarray) -> np.ndarray:
    ring_starts = np.concatenate((np.asarray([0]), ring_ends[:-1])).astype(np.int64)
    boundary_chunks = []
    for ring_start, ring_end in zip(ring_starts, ring_ends.astype(np.int64)):
        indices = np.arange(int(ring_start), int(ring_end), dtype=np.int64)
        boundary_chunks.append(
            np.sort(np.column_stack((indices, np.roll(indices, -1))), axis=1)
        )
    return np.vstack(boundary_chunks)


def _straight_ring_chain(
    vertices_2d: np.ndarray,
    ring_ends: np.ndarray,
    start_index: int,
    end_index: int,
    *,
    grid_mm: float,
) -> np.ndarray | None:
    """Return the noded ring arc represented by one triangulator edge."""

    integer_vertices = np.rint(
        np.asarray(vertices_2d, dtype=np.float64) / float(grid_mm)
    ).astype(np.int64)
    ring_starts = np.concatenate((np.asarray([0]), ring_ends[:-1])).astype(np.int64)
    for ring_start, ring_end in zip(ring_starts, ring_ends.astype(np.int64)):
        if not (
            int(ring_start) <= start_index < int(ring_end)
            and int(ring_start) <= end_index < int(ring_end)
        ):
            continue
        ring = np.arange(int(ring_start), int(ring_end), dtype=np.int64)
        start_position = int(np.flatnonzero(ring == start_index)[0])
        end_position = int(np.flatnonzero(ring == end_index)[0])
        forward = np.concatenate(
            (
                ring[start_position:],
                ring[: end_position + 1],
            )
        )
        if start_position <= end_position:
            forward = ring[start_position : end_position + 1]
        backward = np.concatenate(
            (
                ring[: start_position + 1][::-1],
                ring[end_position:][::-1],
            )
        )
        if start_position >= end_position:
            backward = ring[end_position : start_position + 1][::-1]

        start = integer_vertices[start_index]
        end = integer_vertices[end_index]
        delta = end - start
        squared_length = int(np.dot(delta, delta))
        for candidate in (forward, backward):
            if len(candidate) <= 2:
                continue
            coordinates = integer_vertices[candidate]
            relative = coordinates - start
            cross = relative[:, 0] * delta[1] - relative[:, 1] * delta[0]
            projection = relative @ delta
            if (
                np.all(cross == 0.0)
                and np.all(projection >= 0.0)
                and np.all(projection <= squared_length)
                and np.all(projection[1:] > projection[:-1])
            ):
                return candidate
    return None


def _restore_noded_cap_boundary(
    vertices_2d: np.ndarray,
    cap_faces: np.ndarray,
    ring_ends: np.ndarray,
    *,
    grid_mm: float,
) -> np.ndarray:
    """Split cap triangles at collinear ring nodes omitted by triangulators."""

    faces = _expand_writer_degenerate_cap_faces(
        vertices_2d,
        np.asarray(cap_faces, dtype=np.int64).reshape((-1, 3)),
        grid_mm=grid_mm,
    )
    expected_boundary = _cap_expected_boundary_edges(ring_ends)
    expected_keys = {
        (int(edge[0]), int(edge[1])) for edge in expected_boundary
    }
    for _split_index in range(len(vertices_2d)):
        cap_edges = np.sort(
            faces[:, [[0, 1], [1, 2], [2, 0]]].reshape((-1, 2)),
            axis=1,
        )
        unique_edges, counts = np.unique(cap_edges, axis=0, return_counts=True)
        boundary_edges = unique_edges[counts == 1]
        unexpected = next(
            (
                edge
                for edge in boundary_edges
                if (int(edge[0]), int(edge[1])) not in expected_keys
            ),
            None,
        )
        if unexpected is None:
            return faces

        first = int(unexpected[0])
        second = int(unexpected[1])
        chain = _straight_ring_chain(
            vertices_2d,
            ring_ends,
            first,
            second,
            grid_mm=grid_mm,
        )
        if chain is None:
            raise ValueError(
                "Vector canonical cap introduced a non-ring boundary edge"
            )
        owning_faces = np.flatnonzero(
            np.sum(np.isin(faces, [first, second]), axis=1) == 2
        )
        if len(owning_faces) != 1:
            raise ValueError(
                "Vector canonical cap boundary edge has ambiguous ownership"
            )
        face_index = int(owning_faces[0])
        opposite = next(
            int(index)
            for index in faces[face_index]
            if int(index) not in {first, second}
        )
        replacement = np.column_stack(
            (
                chain[:-1],
                chain[1:],
                np.full(len(chain) - 1, opposite, dtype=np.int64),
            )
        )
        faces = np.concatenate(
            (faces[:face_index], replacement, faces[face_index + 1 :]),
            axis=0,
        )
    raise ValueError("Vector canonical cap could not restore all ring nodes")


def _validate_cap_indices(
    vertices_2d: np.ndarray,
    cap_faces: np.ndarray,
    ring_ends: np.ndarray,
    *,
    expected_area_mm2: float,
    grid_mm: float,
) -> np.ndarray:
    """Orient and validate one Earcut cap without building a 3D fallback."""

    faces = np.asarray(cap_faces, dtype=np.int64).reshape((-1, 3))
    if len(faces) == 0 or np.any(faces < 0) or np.any(faces >= len(vertices_2d)):
        raise ValueError("Vector canonical cap triangulation has invalid indices")
    if np.any(
        (faces[:, 0] == faces[:, 1])
        | (faces[:, 1] == faces[:, 2])
        | (faces[:, 2] == faces[:, 0])
    ):
        raise ValueError("Vector canonical cap triangulation is index-degenerate")

    signed_twice_area_units = _integer_triangle_signed_twice_area(
        vertices_2d,
        faces,
        grid_mm=grid_mm,
    )
    if np.any(signed_twice_area_units == 0):
        raise ValueError("Vector canonical cap triangulation is coordinate-degenerate")
    reversed_faces = signed_twice_area_units < 0
    if bool(np.any(reversed_faces)):
        faces[reversed_faces] = faces[reversed_faces][:, [0, 2, 1]]
        signed_twice_area_units[reversed_faces] *= -1

    cap_area = (
        math.fsum(float(value) for value in signed_twice_area_units)
        * float(grid_mm)
        * float(grid_mm)
        * 0.5
    )
    area_tolerance = max(1e-9, expected_area_mm2 * 1e-9)
    if abs(cap_area - expected_area_mm2) > area_tolerance:
        raise ValueError("Vector canonical cap triangulation changed coverage")

    cap_edges = np.sort(
        faces[:, [[0, 1], [1, 2], [2, 0]]].reshape((-1, 2)),
        axis=1,
    )
    unique_edges, counts = np.unique(cap_edges, axis=0, return_counts=True)
    if np.any((counts != 1) & (counts != 2)):
        raise ValueError("Vector canonical cap has non-manifold edge incidence")
    cap_boundary = unique_edges[counts == 1]

    expected_boundary = _cap_expected_boundary_edges(ring_ends)
    if not np.array_equal(
        cap_boundary[np.lexsort((cap_boundary[:, 1], cap_boundary[:, 0]))],
        expected_boundary[
            np.lexsort((expected_boundary[:, 1], expected_boundary[:, 0]))
        ],
    ):
        raise ValueError("Vector canonical cap boundary differs from its rings")
    return faces


def _triangle_signed_twice_area(triangles: np.ndarray) -> np.ndarray:
    """Return signed doubled XY area for a ``(n, 3, 2)`` triangle batch."""

    return (
        (triangles[:, 1, 0] - triangles[:, 0, 0])
        * (triangles[:, 2, 1] - triangles[:, 0, 1])
        - (triangles[:, 1, 1] - triangles[:, 0, 1])
        * (triangles[:, 2, 0] - triangles[:, 0, 0])
    )


def _integer_triangle_signed_twice_area(
    vertices_2d: np.ndarray,
    faces: np.ndarray,
    *,
    grid_mm: float,
) -> np.ndarray:
    """Return exact signed doubled areas in canonical integer-grid units."""

    units = np.rint(
        np.asarray(vertices_2d, dtype=np.float64) / float(grid_mm)
    ).astype(np.int64)
    triangles = units[np.asarray(faces, dtype=np.int64)]
    return (
        (triangles[:, 1, 0] - triangles[:, 0, 0])
        * (triangles[:, 2, 1] - triangles[:, 0, 1])
        - (triangles[:, 1, 1] - triangles[:, 0, 1])
        * (triangles[:, 2, 0] - triangles[:, 0, 0])
    )


def _expand_writer_degenerate_cap_faces(
    vertices_2d: np.ndarray,
    faces: np.ndarray,
    *,
    grid_mm: float,
) -> np.ndarray:
    """Flip a cap ear diagonal until every triangle survives float32 output.

    A triangulator can retain a zero-area ear to keep a collinear boundary
    vertex, or emit an extremely thin positive-area ear that becomes collinear
    in float32. In both cases the ear and its positive neighbour form a local
    quadrilateral. Flipping their shared diagonal preserves the exact integer
    boundary and total area while producing two writer-representable faces.
    """

    output = np.asarray(faces, dtype=np.int64).reshape((-1, 3)).copy()
    units = np.rint(
        np.asarray(vertices_2d, dtype=np.float64) / float(grid_mm)
    ).astype(np.int64)
    maximum_repairs = max(1, len(output))
    for _repair_index in range(maximum_repairs):
        areas = _integer_triangle_signed_twice_area(
            vertices_2d,
            output,
            grid_mm=grid_mm,
        )
        writer_triangles = np.asarray(vertices_2d, dtype=np.float32)[output]
        writer_areas = _triangle_signed_twice_area(writer_triangles)
        degenerate = (areas == 0) | (writer_areas == 0.0)
        degenerate_indices = np.flatnonzero(degenerate)
        if len(degenerate_indices) == 0:
            return output
        split = None
        split_zero_index = None
        # Earcut can encode a straight boundary chain as several consecutive
        # zero-area ears. Start at the end of that chain, where a positive-area
        # neighbour exists, then work inward. Deleting the first ear eagerly
        # would remove a real boundary segment.
        for raw_zero_index in degenerate_indices[::-1]:
            zero_index = int(raw_zero_index)
            zero_face = output[zero_index]
            if len(set(int(index) for index in zero_face)) != 3:
                raise ValueError("Vector canonical cap has an index-degenerate ear")

            for middle_position in range(3):
                middle = int(zero_face[middle_position])
                endpoints = [
                    int(zero_face[position])
                    for position in range(3)
                    if position != middle_position
                ]
                first, second = endpoints
                first_to_middle = units[middle] - units[first]
                second_to_middle = units[middle] - units[second]
                if int(np.dot(first_to_middle, second_to_middle)) > 0:
                    continue
                candidate_faces = np.flatnonzero(
                    np.sum(np.isin(output, endpoints), axis=1) == 2
                )
                candidate_faces = candidate_faces[
                    (candidate_faces != zero_index)
                    & (~degenerate[candidate_faces])
                ]
                for adjacent_index in candidate_faces:
                    adjacent = output[int(adjacent_index)]
                    opposite = next(
                        int(index)
                        for index in adjacent
                        if int(index) not in {first, second}
                    )
                    replacement = np.asarray(
                        [
                            (first, middle, opposite),
                            (middle, second, opposite),
                        ],
                        dtype=np.int64,
                    )
                    replacement_areas = _integer_triangle_signed_twice_area(
                        vertices_2d,
                        replacement,
                        grid_mm=grid_mm,
                    )
                    replacement_writer_areas = _triangle_signed_twice_area(
                        np.asarray(vertices_2d, dtype=np.float32)[replacement]
                    )
                    expected_twice_area = (
                        abs(int(areas[int(adjacent_index)]))
                        + abs(int(areas[zero_index]))
                    )
                    if (
                        np.any(replacement_areas == 0)
                        or np.any(replacement_writer_areas == 0.0)
                        or int(np.sum(np.abs(replacement_areas), dtype=np.int64))
                        != expected_twice_area
                    ):
                        continue
                    split = (int(adjacent_index), replacement)
                    split_zero_index = zero_index
                    break
                if split is not None:
                    break
            if split is not None:
                break
        if split is None:
            zero_index = int(degenerate_indices[0])
            if int(areas[zero_index]) != 0:
                raise ValueError(
                    "Vector cap contains an unrepresentable float32 ear"
                )
            output = np.delete(output, zero_index, axis=0)
            if len(output) == 0:
                raise ValueError(
                    "Vector canonical cap contains no positive-area triangles"
                )
            continue
        adjacent_index, replacement = split
        assert split_zero_index is not None
        output[split_zero_index] = replacement[0]
        output[adjacent_index] = replacement[1]
    raise ValueError("Vector canonical cap has too many degenerate ears")


def _canonical_cap_faces(
    polygon: _IndexedPolygon,
    vertices_2d: np.ndarray,
    ring_ends: np.ndarray,
    *,
    grid_mm: float,
) -> np.ndarray:
    """Triangulate canonical rings with one deterministic kernel per topology."""

    if not polygon.hole_units:
        faces = np.asarray(
            triangulate_float64(vertices_2d, ring_ends),
            dtype=np.int64,
        ).reshape((-1, 3))
        if (
            len(faces) == 0
            or np.any(faces < 0)
            or np.any(faces >= len(vertices_2d))
        ):
            raise ValueError("Vector canonical cap triangulation has invalid indices")
        return faces

    ring_starts = np.concatenate(
        (np.asarray([0], dtype=np.int64), ring_ends[:-1].astype(np.int64))
    )
    ring_stops = ring_ends.astype(np.int64)
    polygon_geometry = Polygon(
        vertices_2d[ring_starts[0] : ring_stops[0]],
        [
            vertices_2d[start:stop]
            for start, stop in zip(ring_starts[1:], ring_stops[1:])
        ],
    )
    triangle_parts = shapely.get_parts(
        shapely.constrained_delaunay_triangles(polygon_geometry)
    )
    coordinate_counts = np.asarray(
        shapely.get_num_coordinates(triangle_parts),
        dtype=np.int64,
    )
    if len(coordinate_counts) == 0 or np.any(coordinate_counts != 4):
        raise ValueError("Vector holed cap triangulation did not produce triangles")
    triangle_coordinates = np.asarray(
        shapely.get_coordinates(triangle_parts),
        dtype=np.float64,
    ).reshape((-1, 4, 2))[:, :3, :]

    canonical_units = np.rint(vertices_2d / float(grid_mm)).astype(np.int64)
    triangle_units = np.rint(
        triangle_coordinates.reshape((-1, 2)) / float(grid_mm)
    ).astype(np.int64)
    key_dtype = np.dtype([("x", np.int64), ("y", np.int64)])
    canonical_keys = np.ascontiguousarray(canonical_units).view(key_dtype).reshape(-1)
    triangle_keys = np.ascontiguousarray(triangle_units).view(key_dtype).reshape(-1)
    order = np.argsort(canonical_keys, kind="quicksort")
    sorted_keys = canonical_keys[order]
    positions = np.searchsorted(sorted_keys, triangle_keys)
    if (
        np.any(positions >= len(sorted_keys))
        or not np.array_equal(sorted_keys[positions], triangle_keys)
    ):
        raise ValueError("Vector holed cap introduced a non-ring vertex")
    return order[positions].reshape((-1, 3))


def _extrude_indexed_run_group(
    prepared: _IndexedRunGroup,
    *,
    height_mm: float,
    z_offset_mm: float,
) -> trimesh.Trimesh:
    """Build one closed indexed prism mesh from canonical physical rings.
    从规范物理坐标环直接构建一个闭合索引棱柱网格。

    Caps and walls share the exact same ring indices. No geometric repair or
    alternate 3D fallback is attempted after this point. / 顶底面与侧壁复用
    完全相同的环索引；进入本步骤后不再尝试几何修补或备用三维路径。
    """

    height = float(height_mm)
    z_offset = float(z_offset_mm)
    if not math.isfinite(height) or height <= 0.0:
        raise ValueError("Vector prism height must be positive finite")
    if not math.isfinite(z_offset):
        raise ValueError("Vector prism Z offset must be finite")
    if not prepared.polygons:
        raise ValueError("Vector prism requires canonical polygons")
    if np.float32(z_offset) == np.float32(z_offset + height):
        raise ValueError("Vector prism height collapses in float32 writer space")

    polygon_rings = [_oriented_polygon_rings(polygon) for polygon in prepared.polygons]
    ring_vertex_counts = [
        sum(len(ring) for ring in rings) for rings in polygon_rings
    ]
    cap_face_counts = [
        vertex_count + 2 * (len(rings) - 1) - 2
        for vertex_count, rings in zip(ring_vertex_counts, polygon_rings)
    ]
    vertex_count = 2 * sum(ring_vertex_counts)
    face_count = sum(
        2 * cap_face_count + 2 * ring_vertex_count
        for cap_face_count, ring_vertex_count in zip(
            cap_face_counts,
            ring_vertex_counts,
        )
    )
    if vertex_count > np.iinfo(np.uint32).max:
        raise ValueError("Vector canonical mesh exceeds uint32 vertex indices")

    vertices = np.empty((vertex_count, 3), dtype=np.float64)
    faces = np.empty((face_count, 3), dtype=np.int64)
    vertex_cursor = 0
    face_cursor = 0

    for polygon, rings, local_vertex_count, expected_cap_face_count in zip(
        prepared.polygons,
        polygon_rings,
        ring_vertex_counts,
        cap_face_counts,
    ):
        vertices_2d = np.vstack(rings).astype(np.float64)
        vertices_2d *= float(prepared.grid_mm)
        ring_ends = np.cumsum([len(ring) for ring in rings], dtype=np.uint32)
        raw_cap_faces = _canonical_cap_faces(
            polygon,
            vertices_2d,
            ring_ends,
            grid_mm=float(prepared.grid_mm),
        )
        expected_area = _indexed_polygon_area_mm2(
            polygon,
            grid_mm=float(prepared.grid_mm),
        )
        cap_faces = _validate_cap_indices(
            vertices_2d,
            _restore_noded_cap_boundary(
                vertices_2d,
                raw_cap_faces,
                ring_ends,
                grid_mm=float(prepared.grid_mm),
            ),
            ring_ends,
            expected_area_mm2=expected_area,
            grid_mm=float(prepared.grid_mm),
        )
        if len(cap_faces) != expected_cap_face_count:
            raise ValueError("Vector canonical cap triangle count is inconsistent")

        bottom_start = vertex_cursor
        top_start = vertex_cursor + local_vertex_count
        vertices[bottom_start:top_start, :2] = vertices_2d
        vertices[bottom_start:top_start, 2] = z_offset
        vertices[top_start : top_start + local_vertex_count, :2] = vertices_2d
        vertices[top_start : top_start + local_vertex_count, 2] = z_offset + height

        cap_count = len(cap_faces)
        faces[face_cursor : face_cursor + cap_count] = (
            cap_faces[:, ::-1] + bottom_start
        )
        face_cursor += cap_count
        faces[face_cursor : face_cursor + cap_count] = cap_faces + top_start
        face_cursor += cap_count

        local_ring_start = 0
        for ring in rings:
            ring_indices = np.arange(
                local_ring_start,
                local_ring_start + len(ring),
                dtype=np.int64,
            )
            next_indices = np.roll(ring_indices, -1)
            side_count = len(ring) * 2
            faces[face_cursor : face_cursor + side_count : 2] = np.column_stack(
                (
                    bottom_start + ring_indices,
                    bottom_start + next_indices,
                    top_start + next_indices,
                )
            )
            faces[face_cursor + 1 : face_cursor + side_count : 2] = np.column_stack(
                (
                    bottom_start + ring_indices,
                    top_start + next_indices,
                    top_start + ring_indices,
                )
            )
            face_cursor += side_count
            local_ring_start += len(ring)
        vertex_cursor += local_vertex_count * 2

    if vertex_cursor != vertex_count or face_cursor != face_count:
        raise ValueError("Vector canonical mesh allocation count mismatch")

    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    mesh.metadata["vector_layer_geometry"] = {
        "output_component_count": int(len(prepared.polygons)),
        "output_hole_count": int(prepared.hole_count),
        "output_area_mm2": float(prepared.area_mm2),
        "output_coordinate_count": int(prepared.coordinate_count),
        "separated_ring_contact_count": int(
            prepared.separated_ring_contact_count
        ),
        "grid_mm": float(prepared.grid_mm),
        "mesh_vertex_count": int(vertex_count),
        "mesh_face_count": int(face_count),
        "mesh_array_bytes": int(vertices.nbytes + faces.nbytes),
    }
    return mesh


def _remove_redundant_ring_units(units: np.ndarray) -> np.ndarray:
    """Remove exact collinear interior nodes without changing a ring boundary."""

    output = np.asarray(units, dtype=np.int64)
    while len(output) > 3:
        previous = np.roll(output, 1, axis=0)
        following = np.roll(output, -1, axis=0)
        incoming = output - previous
        outgoing = following - output
        cross = incoming[:, 0] * outgoing[:, 1]
        cross -= incoming[:, 1] * outgoing[:, 0]
        between = np.sum(
            (output - previous) * (output - following),
            axis=1,
            dtype=np.int64,
        ) <= 0
        removable = (cross == 0) & between
        if not np.any(removable) or int(np.count_nonzero(~removable)) < 3:
            break
        output = output[~removable]
    return output


def _indexed_ring_units(coordinates, *, grid_mm: float) -> np.ndarray:
    """Convert one ring to a compact exact physical-grid representation."""

    values = np.asarray(coordinates, dtype=np.float64)
    if len(values) > 1 and np.array_equal(values[0], values[-1]):
        values = values[:-1]
    units = np.rint(values / float(grid_mm)).astype(np.int64)
    if len(units) > 1:
        keep = np.ones(len(units), dtype=bool)
        keep[1:] = np.any(units[1:] != units[:-1], axis=1)
        units = units[keep]
    if len(units) > 1 and np.array_equal(units[0], units[-1]):
        units = units[:-1]
    units = _remove_redundant_ring_units(units)
    if len(units) < 3:
        raise ValueError("Vector layered-volume ring collapsed below three points")
    return np.ascontiguousarray(units)


def _indexed_polygon(
    polygon: Polygon,
    *,
    grid_mm: float,
) -> tuple[_IndexedPolygon, list[np.ndarray]]:
    """Convert one arrangement cell without discarding shared line nodes."""

    oriented = orient(polygon, sign=1.0)
    prepared = _IndexedPolygon(
        exterior_units=_indexed_ring_units(
            oriented.exterior.coords,
            grid_mm=grid_mm,
        ),
        hole_units=tuple(
            _indexed_ring_units(ring.coords, grid_mm=grid_mm)
            for ring in oriented.interiors
        ),
    )
    return prepared, _oriented_polygon_rings(prepared)


def _physical_layer_slabs(
    slabs: Sequence[dict],
    *,
    scale_mm_per_svg_unit: float,
    policy: VectorLayerGeometryPolicy,
) -> tuple[list[_PhysicalLayerSlab], float]:
    """Validate, scale, and snap all stepped slabs on one writer-safe grid."""

    scale = float(scale_mm_per_svg_unit)
    if not math.isfinite(scale) or scale <= 0.0:
        raise ValueError("Vector layered-volume scale must be positive finite")

    maximum_abs_coordinate = 0.0
    raw_slabs: list[_PhysicalLayerSlab] = []
    for slab in slabs:
        if not isinstance(slab, dict):
            raise ValueError("Vector layered-volume slabs must be mappings")
        geometry = slab.get("geometry")
        try:
            z_start = float(slab.get("z_offset", 0.0))
            height = float(slab.get("height", 0.0))
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Vector layered-volume slab has invalid height") from exc
        if geometry is None or getattr(geometry, "is_empty", True) or height <= 1e-9:
            continue
        z_end = z_start + height
        if not all(math.isfinite(value) for value in (z_start, z_end)):
            raise ValueError("Vector layered-volume Z range must be finite")
        source_parts = _polygon_parts(geometry)
        polygonal_source: BaseGeometry = (
            source_parts[0]
            if len(source_parts) == 1
            else GeometryCollection(source_parts)
        )
        physical_geometry = affinity.scale(
            polygonal_source,
            xfact=scale,
            yfact=scale,
            origin=(0.0, 0.0),
        )
        for physical in _polygon_parts(physical_geometry):
            maximum_abs_coordinate = max(
                maximum_abs_coordinate,
                *(abs(float(value)) for value in physical.bounds),
            )
        raw_slabs.append(
            _PhysicalLayerSlab(
                geometry=physical_geometry,
                z_start_mm=round(z_start, 9),
                z_end_mm=round(z_end, 9),
            )
        )
    if not raw_slabs:
        return [], float(policy.grid_mm)

    grid_mm = resolve_vector_writer_grid_mm(
        maximum_abs_coordinate,
        minimum_mm=float(policy.grid_mm),
    )
    snapped_slabs: list[_PhysicalLayerSlab] = []
    for slab in raw_slabs:
        polygon_parts: list[Polygon] = []
        for source_part in _polygon_parts(slab.geometry):
            snapped_part = set_precision(
                source_part,
                grid_size=grid_mm,
                mode="valid_output",
            )
            if snapped_part is None or snapped_part.is_empty:
                continue
            polygon_parts.extend(_polygon_parts(snapped_part))
        if not polygon_parts:
            continue
        snapped_slabs.append(
            _PhysicalLayerSlab(
                geometry=(
                    polygon_parts[0]
                    if len(polygon_parts) == 1
                    else GeometryCollection(polygon_parts)
                ),
                z_start_mm=slab.z_start_mm,
                z_end_mm=slab.z_end_mm,
            )
        )
    return snapped_slabs, grid_mm


def _coalesced_layer_slabs(
    slabs: Sequence[_PhysicalLayerSlab],
) -> list[_PhysicalLayerSlab]:
    """Coalesce only byte-identical footprints with contiguous Z ranges.

    SVG draw-order clipping has already removed area overlaps before material
    recipes are assigned.  Meshing therefore keeps different footprints as
    independent closed shells instead of repeating a material-wide Boolean
    union for every atomic Z band.  Exact duplicates are cheap to recognize
    and safe to fold vertically, which avoids coincident internal caps without
    changing any XY boundary.
    """

    grouped: dict[bytes, tuple[BaseGeometry, list[tuple[float, float]]]] = {}
    for slab in slabs:
        geometry_key = shapely.to_wkb(
            shapely.normalize(slab.geometry),
            output_dimension=2,
            byte_order=1,
        )
        if geometry_key not in grouped:
            grouped[geometry_key] = (slab.geometry, [])
        grouped[geometry_key][1].append(
            (float(slab.z_start_mm), float(slab.z_end_mm))
        )

    result: list[_PhysicalLayerSlab] = []
    for geometry, intervals in grouped.values():
        current_start = None
        current_end = None
        for z_start, z_end in sorted(intervals):
            if current_start is None:
                current_start = float(z_start)
                current_end = float(z_end)
                continue
            assert current_end is not None
            if float(z_start) <= current_end + 1e-9:
                current_end = max(current_end, float(z_end))
                continue
            result.append(
                _PhysicalLayerSlab(
                    geometry=geometry,
                    z_start_mm=current_start,
                    z_end_mm=current_end,
                )
            )
            current_start = float(z_start)
            current_end = float(z_end)
        if current_start is not None and current_end is not None:
            result.append(
                _PhysicalLayerSlab(
                    geometry=geometry,
                    z_start_mm=current_start,
                    z_end_mm=current_end,
                )
            )
    return result


def _prepared_interval_group(
    footprints: Sequence[Polygon],
    *,
    grid_mm: float,
) -> _IndexedRunGroup:
    """Prepare every shell of one fixed-Z footprint for indexed extrusion."""

    prepared_polygons: list[_IndexedPolygon] = []
    coordinate_count = 0
    hole_count = 0
    area_mm2 = 0.0
    separated_ring_contacts = 0

    for raw_polygon in footprints:
        polygon, separated = _separate_polygon_ring_contacts(
            raw_polygon,
            grid_mm=float(grid_mm),
        )
        separated_ring_contacts += int(separated)
        for simple_polygon in _polygon_parts(polygon):
            prepared, rings = _indexed_polygon(
                simple_polygon,
                grid_mm=float(grid_mm),
            )
            prepared_polygons.append(prepared)
            coordinate_count += sum(len(ring) for ring in rings)
            hole_count += len(prepared.hole_units)
            area_mm2 += float(simple_polygon.area)

    if not prepared_polygons:
        raise ValueError("Vector interval footprint contains no printable shell")
    return _IndexedRunGroup(
        polygons=tuple(prepared_polygons),
        grid_mm=float(grid_mm),
        area_mm2=float(area_mm2),
        coordinate_count=int(coordinate_count),
        hole_count=int(hole_count),
        separated_ring_contact_count=int(separated_ring_contacts),
    )


def _concatenate_layered_components(
    meshes: Sequence[trimesh.Trimesh],
) -> trimesh.Trimesh:
    """Concatenate independently indexed closed shells without welding."""

    if not meshes:
        raise ValueError("Vector layered-volume has no component meshes")
    vertex_count = sum(len(mesh.vertices) for mesh in meshes)
    face_count = sum(len(mesh.faces) for mesh in meshes)
    vertices = np.empty((vertex_count, 3), dtype=np.float64)
    faces = np.empty((face_count, 3), dtype=np.int64)
    vertex_cursor = 0
    face_cursor = 0
    for mesh in meshes:
        next_vertex = vertex_cursor + len(mesh.vertices)
        next_face = face_cursor + len(mesh.faces)
        vertices[vertex_cursor:next_vertex] = np.asarray(
            mesh.vertices,
            dtype=np.float64,
        )
        np.add(
            np.asarray(mesh.faces, dtype=np.int64),
            vertex_cursor,
            out=faces[face_cursor:next_face],
        )
        vertex_cursor = next_vertex
        face_cursor = next_face
    return trimesh.Trimesh(vertices=vertices, faces=faces, process=False)


def build_vector_layered_volume(
    slabs: Sequence[dict],
    *,
    scale_mm_per_svg_unit: float,
    policy: VectorLayerGeometryPolicy | None = None,
) -> trimesh.Trimesh | None:
    """Build one material object from independently closed layer slabs.
    由相互独立闭合的片层构建一个材料对象。

    SVG draw-order clipping owns area-overlap resolution. This builder only
    snaps each prepared slab to a writer-safe grid, coalesces byte-identical
    contiguous slabs, and extrudes every remaining polygon with shared
    cap/wall indices. Shell coordinates are never welded or displaced during
    concatenation; disconnected islands remain internal shells of the same
    material object.

    SVG 绘制顺序裁剪负责消除有面积的重叠。本构建器只把已准备好的片层吸附
    到写出安全网格、纵向合并完全相同且连续的片层，再用顶面与侧壁共享索引
    的方式逐片封口。合并对象时既不焊接也不挪动壳体坐标；离散小岛仍属于同
    一个耗材对象内部的独立闭合壳体。
    """

    effective_policy = policy or VectorLayerGeometryPolicy()
    snapped_slabs, grid_mm = _physical_layer_slabs(
        slabs,
        scale_mm_per_svg_unit=scale_mm_per_svg_unit,
        policy=effective_policy,
    )
    if not snapped_slabs:
        return None
    coalesced_slabs = _coalesced_layer_slabs(snapped_slabs)
    slab_meshes: list[trimesh.Trimesh] = []
    for slab in coalesced_slabs:
        prepared = _prepared_interval_group(
            _polygon_parts(slab.geometry),
            grid_mm=float(grid_mm),
        )
        slab_meshes.append(
            _extrude_indexed_run_group(
                prepared,
                height_mm=float(slab.z_end_mm) - float(slab.z_start_mm),
                z_offset_mm=float(slab.z_start_mm),
            )
        )
    if not slab_meshes:
        return None
    snapped_slabs.clear()
    coalesced_slabs.clear()
    mesh = _concatenate_layered_components(slab_meshes)
    mesh.metadata["vector_layer_geometry"] = {
        "grid_mm": float(grid_mm),
        "component_count": int(len(slab_meshes)),
        "mesh_vertex_count": int(len(mesh.vertices)),
        "mesh_face_count": int(len(mesh.faces)),
    }
    return mesh


__all__ = [
    "resolve_vector_writer_grid_mm",
    "snap_vector_writer_coordinate_mm",
    "VectorLayerGeometryPolicy",
    "build_vector_layered_volume",
]
