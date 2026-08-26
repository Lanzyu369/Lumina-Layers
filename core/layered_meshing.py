"""Exact indexed surfaces for labeled Z/Y/X voxel volumes.

This module deliberately keeps topology on an integer lattice until the final
Trimesh materialization.  It emits only exposed material faces, while retaining
separate index domains for volumes that merely touch at an edge or a point.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import numpy as np
import trimesh
from scipy import ndimage


@dataclass(frozen=True)
class LayeredMeshPolicy:
    """Validation policy for labeled surface construction.
    标签表面构建的验证策略。
    """

    validate_output: bool = True


@dataclass(frozen=True)
class LayeredMeshStats:
    """Observable size counters for one material mesh.
    单个材料网格的可观测规模统计。
    """

    source_voxel_count: int
    component_count: int
    exposed_unit_face_count: int
    merged_patch_count: int
    component_chunk_count: int
    peak_component_patch_count: int
    vertex_count: int
    face_count: int
    lattice_float32_bytes: int
    materialized_bytes: int
    source_contact_edge_pair_count: int
    source_contact_point_pair_count: int
    source_contact_normalized_edge_count: int


@dataclass(frozen=True)
class _CompactPatches:
    shell_ids: np.ndarray
    normals: np.ndarray
    corners: np.ndarray

    def __len__(self) -> int:
        return int(len(self.shell_ids))


def _pack_grid_key(
    fields: tuple[np.ndarray, ...],
    *,
    coordinate_base: int,
) -> np.ndarray:
    """Pack small non-negative grid fields into one sortable uint64 key."""

    if coordinate_base <= 0:
        raise ValueError("Layered mesh coordinate base must be positive")
    maximum_key = 3 * (coordinate_base ** (len(fields) - 1))
    if maximum_key > np.iinfo(np.uint64).max:
        raise ValueError("Layered mesh grid is too large for compact topology keys")
    packed = np.asarray(fields[0], dtype=np.uint64)
    base = np.uint64(coordinate_base)
    for field in fields[1:]:
        values = np.asarray(field)
        if bool(np.any(values < 0)) or bool(np.any(values >= coordinate_base)):
            raise ValueError("Layered mesh compact topology key is out of range")
        packed = packed * base + values.astype(np.uint64, copy=False)
    return packed


def _rank_packed_keys(
    keys: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Sort compact keys with explicit, bounded intermediate arrays."""

    order = np.argsort(keys, kind="quicksort")
    sorted_keys = keys[order]
    change = np.empty(len(keys), dtype=bool)
    change[0] = True
    change[1:] = sorted_keys[1:] != sorted_keys[:-1]
    sorted_rank = np.cumsum(change, dtype=np.uint32) - np.uint32(1)
    inverse = np.empty(len(keys), dtype=np.uint32)
    inverse[order] = sorted_rank
    group_counts = np.bincount(sorted_rank).astype(np.int32, copy=False)
    unique_keys = sorted_keys[change]
    return unique_keys, inverse, group_counts, order


def _component_membership(
    component_labels: np.ndarray,
    shell_id: int,
    x: np.ndarray,
    y: np.ndarray,
    z: np.ndarray,
) -> np.ndarray:
    """Sample one component without allocating a full per-component volume."""

    inside = (
        (x >= 0)
        & (x < component_labels.shape[2])
        & (y >= 0)
        & (y < component_labels.shape[1])
        & (z >= 0)
        & (z < component_labels.shape[0])
    )
    occupied = np.zeros(len(x), dtype=bool)
    if bool(np.any(inside)):
        occupied[inside] = (
            component_labels[z[inside], y[inside], x[inside]] == shell_id
        )
    return occupied


def _diagonal_edge_contact_mask(
    starts: np.ndarray,
    ends: np.ndarray,
    *,
    component_labels: np.ndarray,
    shell_id: int,
) -> np.ndarray:
    """Locate voxel-diagonal boundary edges within one six-connected shell."""

    low = np.minimum(starts, ends)
    axis = np.argmax(starts != ends, axis=1)
    result = np.zeros(len(starts), dtype=bool)
    for current_axis in range(3):
        selected = np.flatnonzero(axis == current_axis)
        if len(selected) == 0:
            continue
        x = low[selected, 0]
        y = low[selected, 1]
        z = low[selected, 2]
        if current_axis == 0:
            samples = (
                (x, y - 1, z - 1),
                (x, y, z - 1),
                (x, y - 1, z),
                (x, y, z),
            )
        elif current_axis == 1:
            samples = (
                (x - 1, y, z - 1),
                (x, y, z - 1),
                (x - 1, y, z),
                (x, y, z),
            )
        else:
            samples = (
                (x - 1, y - 1, z),
                (x, y - 1, z),
                (x - 1, y, z),
                (x, y, z),
            )
        first, second, third, fourth = (
            _component_membership(
                component_labels,
                shell_id,
                sample_x,
                sample_y,
                sample_z,
            )
            for sample_x, sample_y, sample_z in samples
        )
        result[selected] = (
            (first & fourth & ~second & ~third)
            | (second & third & ~first & ~fourth)
        )
    return result


def _packed_segment_keys(
    token_coordinates: np.ndarray,
    segment_start: np.ndarray,
    segment_end: np.ndarray,
    *,
    coordinate_base: int,
) -> np.ndarray:
    """Pack boundary segments without full advanced-index coordinate copies."""

    keys = np.empty(len(segment_start), dtype=np.uint64)
    for block_start in range(0, len(keys), 65_536):
        block_end = min(block_start + 65_536, len(keys))
        first = token_coordinates[segment_start[block_start:block_end]]
        second = token_coordinates[segment_end[block_start:block_end]]
        axis = np.argmax(first != second, axis=1).astype(np.int32)
        low = np.minimum(first, second)
        high = np.maximum(first, second)
        rows = np.arange(len(first))
        fixed_first = np.where(axis == 0, low[:, 1], low[:, 0])
        fixed_second = np.where(axis == 2, low[:, 1], low[:, 2])
        keys[block_start:block_end] = _pack_grid_key(
            (
                axis,
                fixed_first,
                fixed_second,
                low[rows, axis],
                high[rows, axis],
            ),
            coordinate_base=coordinate_base,
        )
    return keys


class _LatticeFloat32Audit:
    """Audit the pre-transform lattice float32 materialization.

    This is not the final 3MF writer-domain audit.  The writer must separately
    validate coordinates after S07 scale and object translation are applied.
    """

    _MAX_EXACT_DOUBLED_COORDINATE = 1 << 24

    def __init__(self) -> None:
        self._unsafe_float32_coordinates: dict[
            tuple[int, int, int], tuple[int, int, int]
        ] = {}
        self.source_contact_normalized_edge_count = 0

    def observe(
        self,
        exact_world_doubled: np.ndarray,
        float32_vertices: np.ndarray,
    ) -> None:
        unsafe = np.any(
            np.abs(exact_world_doubled)
            >= self._MAX_EXACT_DOUBLED_COORDINATE,
            axis=1,
        )
        if not bool(np.any(unsafe)):
            return

        float32_bits = np.ascontiguousarray(float32_vertices).view(np.uint32)
        for index in np.flatnonzero(unsafe):
            float32_key = tuple(int(value) for value in float32_bits[index])
            exact_key = tuple(int(value) for value in exact_world_doubled[index])
            previous = self._unsafe_float32_coordinates.get(float32_key)
            if previous is not None and previous != exact_key:
                raise ValueError(
                    "Distinct exact lattice vertices collide in the float32 "
                    "lattice float32 collision audit"
                )
            self._unsafe_float32_coordinates[float32_key] = exact_key


def _greedy_rectangles(mask: np.ndarray) -> list[tuple[int, int, int, int]]:
    """Cover a boolean plane with non-overlapping axis-aligned rectangles."""

    rows, columns = mask.shape
    used = np.zeros_like(mask, dtype=bool)
    rectangles: list[tuple[int, int, int, int]] = []
    for row in range(rows):
        column = 0
        while column < columns:
            if not mask[row, column] or used[row, column]:
                column += 1
                continue

            column_end = column + 1
            while (
                column_end < columns
                and mask[row, column_end]
                and not used[row, column_end]
            ):
                column_end += 1

            row_end = row + 1
            while row_end < rows:
                candidate = mask[row_end, column:column_end]
                already_used = used[row_end, column:column_end]
                if not bool(np.all(candidate)) or bool(np.any(already_used)):
                    break
                row_end += 1

            used[row:row_end, column:column_end] = True
            rectangles.append((column, row, column_end, row_end))
            column = column_end
    return rectangles


def _append_plane_patch_arrays(
    shell_chunks: list[np.ndarray],
    normal_chunks: list[np.ndarray],
    corner_chunks: list[np.ndarray],
    *,
    shell_id: int,
    direction: str,
    plane: int,
    mask: np.ndarray,
    origin: tuple[int, int, int],
) -> None:
    """Append one plane as compact arrays, bounding Python objects per plane."""

    normal_by_direction = {
        "-x": (-1, 0, 0),
        "+x": (1, 0, 0),
        "-y": (0, -1, 0),
        "+y": (0, 1, 0),
        "-z": (0, 0, -1),
        "+z": (0, 0, 1),
    }
    rectangles = _greedy_rectangles(mask)
    if not rectangles:
        return
    rectangle_array = np.asarray(rectangles, dtype=np.int32)
    del rectangles
    u0, v0, u1, v1 = rectangle_array.T
    count = len(rectangle_array)
    corners = np.empty((count, 4, 3), dtype=np.int32)

    if direction in {"-x", "+x"}:
        corners[:, :, 0] = plane
        corners[:, :, 1] = np.column_stack((u0, u1, u1, u0))
        corners[:, :, 2] = np.column_stack((v0, v0, v1, v1))
        reverse = direction == "-x"
    elif direction in {"-y", "+y"}:
        corners[:, :, 0] = np.column_stack((u0, u1, u1, u0))
        corners[:, :, 1] = plane
        corners[:, :, 2] = np.column_stack((v0, v0, v1, v1))
        reverse = direction == "+y"
    elif direction in {"-z", "+z"}:
        corners[:, :, 0] = np.column_stack((u0, u1, u1, u0))
        corners[:, :, 1] = np.column_stack((v0, v0, v1, v1))
        corners[:, :, 2] = plane
        reverse = direction == "-z"
    else:
        raise ValueError(f"Unsupported face direction: {direction}")

    if reverse:
        corners = np.ascontiguousarray(corners[:, ::-1])
    corners += np.asarray(origin, dtype=np.int32)
    shell_chunks.append(np.full(count, shell_id, dtype=np.int32))
    normal_chunks.append(
        np.tile(np.asarray(normal_by_direction[direction], dtype=np.int8), (count, 1))
    )
    corner_chunks.append(corners)


def _component_patches(
    component: np.ndarray,
    *,
    shell_id: int,
    origin: tuple[int, int, int] = (0, 0, 0),
) -> tuple[_CompactPatches, int]:
    """Extract and merge the six exposed face families of one component."""

    z_size, y_size, x_size = component.shape
    shell_chunks: list[np.ndarray] = []
    normal_chunks: list[np.ndarray] = []
    corner_chunks: list[np.ndarray] = []
    exposed_count = 0

    negative_x = np.empty_like(component)
    negative_x[:, :, 0] = component[:, :, 0]
    negative_x[:, :, 1:] = component[:, :, 1:] & ~component[:, :, :-1]
    exposed_count += int(np.count_nonzero(negative_x))
    for x in range(x_size):
        _append_plane_patch_arrays(
            shell_chunks,
            normal_chunks,
            corner_chunks,
            shell_id=shell_id,
            direction="-x",
            plane=x,
            mask=negative_x[:, :, x],
            origin=origin,
        )
    del negative_x

    positive_x = np.empty_like(component)
    positive_x[:, :, -1] = component[:, :, -1]
    positive_x[:, :, :-1] = component[:, :, :-1] & ~component[:, :, 1:]
    exposed_count += int(np.count_nonzero(positive_x))
    for x in range(x_size):
        _append_plane_patch_arrays(
            shell_chunks,
            normal_chunks,
            corner_chunks,
            shell_id=shell_id,
            direction="+x",
            plane=x + 1,
            mask=positive_x[:, :, x],
            origin=origin,
        )
    del positive_x

    negative_y = np.empty_like(component)
    negative_y[:, 0, :] = component[:, 0, :]
    negative_y[:, 1:, :] = component[:, 1:, :] & ~component[:, :-1, :]
    exposed_count += int(np.count_nonzero(negative_y))
    for y in range(y_size):
        _append_plane_patch_arrays(
            shell_chunks,
            normal_chunks,
            corner_chunks,
            shell_id=shell_id,
            direction="-y",
            plane=y,
            mask=negative_y[:, y, :],
            origin=origin,
        )
    del negative_y

    positive_y = np.empty_like(component)
    positive_y[:, -1, :] = component[:, -1, :]
    positive_y[:, :-1, :] = component[:, :-1, :] & ~component[:, 1:, :]
    exposed_count += int(np.count_nonzero(positive_y))
    for y in range(y_size):
        _append_plane_patch_arrays(
            shell_chunks,
            normal_chunks,
            corner_chunks,
            shell_id=shell_id,
            direction="+y",
            plane=y + 1,
            mask=positive_y[:, y, :],
            origin=origin,
        )
    del positive_y

    negative_z = np.empty_like(component)
    negative_z[0, :, :] = component[0, :, :]
    negative_z[1:, :, :] = component[1:, :, :] & ~component[:-1, :, :]
    exposed_count += int(np.count_nonzero(negative_z))
    for z in range(z_size):
        _append_plane_patch_arrays(
            shell_chunks,
            normal_chunks,
            corner_chunks,
            shell_id=shell_id,
            direction="-z",
            plane=z,
            mask=negative_z[z, :, :],
            origin=origin,
        )
    del negative_z

    positive_z = np.empty_like(component)
    positive_z[-1, :, :] = component[-1, :, :]
    positive_z[:-1, :, :] = component[:-1, :, :] & ~component[1:, :, :]
    exposed_count += int(np.count_nonzero(positive_z))
    for z in range(z_size):
        _append_plane_patch_arrays(
            shell_chunks,
            normal_chunks,
            corner_chunks,
            shell_id=shell_id,
            direction="+z",
            plane=z + 1,
            mask=positive_z[z, :, :],
            origin=origin,
        )
    if not shell_chunks:
        raise ValueError("Layered surface component produced no exposed patches")
    return (
        _CompactPatches(
            shell_ids=np.concatenate(shell_chunks),
            normals=np.concatenate(normal_chunks, axis=0),
            corners=np.concatenate(corner_chunks, axis=0),
        ),
        exposed_count,
    )


def _axis_event_grid(
    edge_first: np.ndarray,
    edge_second: np.ndarray,
    edge_axis: np.ndarray,
    *,
    axis: int,
    coordinate_minimum: np.ndarray,
    grid_shape: tuple[int, int, int],
) -> tuple[np.ndarray, np.ndarray]:
    """Build endpoint events for one edge direction in component-local space."""

    edge_indices = np.flatnonzero(edge_axis == axis)
    events = np.zeros(grid_shape, dtype=bool)
    for endpoints in (edge_first, edge_second):
        local = endpoints[edge_indices] - coordinate_minimum
        events[local[:, 2], local[:, 1], local[:, 0]] = True
    return events, edge_indices


def _split_patch_edges(
    edge_first: np.ndarray,
    edge_second: np.ndarray,
    edge_axis: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Split patch edges at collinear endpoints with a bounded dense event grid."""

    coordinate_minimum = np.minimum(edge_first.min(axis=0), edge_second.min(axis=0))
    coordinate_maximum = np.maximum(edge_first.max(axis=0), edge_second.max(axis=0))
    grid_shape = tuple(
        int(value) for value in (coordinate_maximum - coordinate_minimum + 1)[::-1]
    )
    base_counts_by_edge = np.empty(len(edge_first), dtype=np.int32)
    axis_to_grid_dimension = (2, 1, 0)
    for axis in range(3):
        events, edge_indices = _axis_event_grid(
            edge_first,
            edge_second,
            edge_axis,
            axis=axis,
            coordinate_minimum=coordinate_minimum,
            grid_shape=grid_shape,
        )
        prefix = np.cumsum(
            events,
            axis=axis_to_grid_dimension[axis],
            dtype=np.int32,
        )
        low = np.minimum(edge_first[edge_indices], edge_second[edge_indices])
        high = np.maximum(edge_first[edge_indices], edge_second[edge_indices])
        low -= coordinate_minimum
        high -= coordinate_minimum
        base_counts_by_edge[edge_indices] = (
            prefix[high[:, 2], high[:, 1], high[:, 0]]
            - prefix[low[:, 2], low[:, 1], low[:, 0]]
        )
        del events, edge_indices, prefix, low, high

    if bool(np.any(base_counts_by_edge <= 0)):
        raise ValueError("Layered mesh patch contains a zero-length edge")
    base_offsets_by_edge = np.empty(len(edge_first) + 1, dtype=np.int64)
    base_offsets_by_edge[0] = 0
    np.cumsum(base_counts_by_edge, out=base_offsets_by_edge[1:])
    base_start = np.empty((int(base_offsets_by_edge[-1]), 3), dtype=np.int32)
    base_end = np.empty_like(base_start)

    single_segment = base_counts_by_edge == 1
    single_positions = base_offsets_by_edge[:-1][single_segment]
    base_start[single_positions] = edge_first[single_segment]
    base_end[single_positions] = edge_second[single_segment]

    for axis in range(3):
        events, edge_indices = _axis_event_grid(
            edge_first,
            edge_second,
            edge_axis,
            axis=axis,
            coordinate_minimum=coordinate_minimum,
            grid_shape=grid_shape,
        )
        for edge_index in edge_indices[~single_segment[edge_indices]]:
            low = np.minimum(edge_first[edge_index], edge_second[edge_index])
            high = np.maximum(edge_first[edge_index], edge_second[edge_index])
            local_low = low - coordinate_minimum
            local_high = high - coordinate_minimum
            if axis == 0:
                line = events[local_low[2], local_low[1], local_low[0] : local_high[0] + 1]
            elif axis == 1:
                line = events[local_low[2], local_low[1] : local_high[1] + 1, local_low[0]]
            else:
                line = events[local_low[2] : local_high[2] + 1, local_low[1], local_low[0]]
            values = np.flatnonzero(line).astype(np.int32) + low[axis]
            if edge_second[edge_index, axis] < edge_first[edge_index, axis]:
                values = values[::-1]
            output_start = int(base_offsets_by_edge[edge_index])
            for local_index in range(len(values) - 1):
                start = edge_first[edge_index].copy()
                end = edge_first[edge_index].copy()
                start[axis] = values[local_index]
                end[axis] = values[local_index + 1]
                base_start[output_start + local_index] = start
                base_end[output_start + local_index] = end
        del events, edge_indices
    return base_start, base_end, base_counts_by_edge


def _mesh_arrays_from_patches(
    patches: _CompactPatches,
    *,
    height_px: int,
    component_labels: np.ndarray,
    shell_id: int,
    lattice_audit: _LatticeFloat32Audit | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    patch_count = len(patches)
    if patch_count == 0:
        raise ValueError("Layered surface meshing received no patches")

    edge_first = patches.corners.reshape((-1, 3))
    edge_second = np.roll(patches.corners, -1, axis=1).reshape((-1, 3))
    edge_delta = edge_second - edge_first
    edge_axis = np.argmax(edge_delta != 0, axis=1).astype(np.int32)
    if not bool(np.all(patches.shell_ids == patches.shell_ids[0])):
        raise ValueError("Compact meshing accepts one six-connected component")
    base_start, base_end, base_counts_by_edge = _split_patch_edges(
        edge_first,
        edge_second,
        edge_axis,
    )

    patch_base_counts = base_counts_by_edge.reshape((patch_count, 4)).sum(axis=1)
    patch_base_offsets = np.empty(patch_count + 1, dtype=np.int64)
    patch_base_offsets[0] = 0
    np.cumsum(patch_base_counts, out=patch_base_offsets[1:])
    base_nonmanifold = _diagonal_edge_contact_mask(
        base_start,
        base_end,
        component_labels=component_labels,
        shell_id=shell_id,
    )
    if lattice_audit is not None:
        lattice_audit.source_contact_normalized_edge_count += int(
            np.count_nonzero(base_nonmanifold) // 4
        )
    del (
        edge_delta,
        edge_axis,
    )

    extra_by_patch = np.add.reduceat(
        base_nonmanifold.astype(np.int32),
        patch_base_offsets[:-1],
    )
    ring_lengths = patch_base_counts + extra_by_patch
    center_needed = ring_lengths != 4
    boundary_token_count = int(ring_lengths.sum())
    token_count = boundary_token_count + int(np.count_nonzero(center_needed))
    face_count = int(np.where(center_needed, ring_lengths, 2).sum())
    if token_count > np.iinfo(np.uint32).max:
        raise ValueError("Layered surface component exceeds uint32 lattice indices")

    token_coordinates = np.empty((token_count, 3), dtype=np.int64)
    faces_by_token = np.empty((face_count, 3), dtype=np.uint32)
    segment_start = np.empty(boundary_token_count, dtype=np.uint32)
    segment_end = np.empty(boundary_token_count, dtype=np.uint32)
    segment_normal = np.empty((boundary_token_count, 3), dtype=np.int8)

    token_cursor = 0
    face_cursor = 0
    segment_cursor = 0
    for patch_index in range(patch_count):
        base_begin = int(patch_base_offsets[patch_index])
        base_finish = int(patch_base_offsets[patch_index + 1])
        ring_length = int(ring_lengths[patch_index])
        ring_begin = token_cursor
        ring_position = 0
        for base_index in range(base_begin, base_finish):
            token_coordinates[ring_begin + ring_position] = base_start[base_index] * 2
            ring_position += 1
            if base_nonmanifold[base_index]:
                token_coordinates[ring_begin + ring_position] = (
                    base_start[base_index] + base_end[base_index]
                )
                ring_position += 1
        if ring_position != ring_length:
            raise ValueError("Layered mesh compact ring count mismatch")

        ring_indices = np.arange(
            ring_begin,
            ring_begin + ring_length,
            dtype=np.uint32,
        )
        segment_start[segment_cursor : segment_cursor + ring_length] = ring_indices
        segment_end[segment_cursor : segment_cursor + ring_length] = np.roll(
            ring_indices,
            -1,
        )
        segment_normal[segment_cursor : segment_cursor + ring_length] = (
            patches.normals[patch_index]
        )
        segment_cursor += ring_length

        if ring_length == 4:
            faces_by_token[face_cursor] = (
                ring_indices[0],
                ring_indices[2],
                ring_indices[1],
            )
            faces_by_token[face_cursor + 1] = (
                ring_indices[0],
                ring_indices[3],
                ring_indices[2],
            )
            face_cursor += 2
            token_cursor += ring_length
            continue

        center_token = ring_begin + ring_length
        corners = patches.corners[patch_index]
        token_coordinates[center_token] = corners.min(axis=0) + corners.max(axis=0)
        next_indices = np.roll(ring_indices, -1)
        faces_by_token[face_cursor : face_cursor + ring_length, 0] = center_token
        faces_by_token[face_cursor : face_cursor + ring_length, 1] = next_indices
        faces_by_token[face_cursor : face_cursor + ring_length, 2] = ring_indices
        face_cursor += ring_length
        token_cursor += ring_length + 1

    if (
        token_cursor != token_count
        or face_cursor != face_count
        or segment_cursor != boundary_token_count
    ):
        raise ValueError("Layered mesh compact allocation count mismatch")
    del (
        edge_first,
        edge_second,
        base_counts_by_edge,
        base_start,
        base_end,
        patch_base_counts,
        patch_base_offsets,
        base_nonmanifold,
        extra_by_patch,
        ring_lengths,
        center_needed,
    )

    doubled_coordinate_base = max(3, int(token_coordinates.max()) + 1)
    segment_keys = _packed_segment_keys(
        token_coordinates,
        segment_start,
        segment_end,
        coordinate_base=doubled_coordinate_base,
    )
    (
        _unique_segment_keys,
        segment_inverse,
        segment_group_counts,
        segment_order,
    ) = _rank_packed_keys(segment_keys)
    segment_group_starts = np.empty(len(segment_group_counts), dtype=np.int64)
    segment_group_starts[0] = 0
    if len(segment_group_counts) > 1:
        np.cumsum(
            segment_group_counts[:-1],
            out=segment_group_starts[1:],
        )
    segment_group_ends = np.concatenate(
        (
            segment_group_starts[1:],
            np.array([boundary_token_count], dtype=np.int64),
        )
    )
    if bool(np.any((segment_group_counts != 2) & (segment_group_counts != 4))):
        raise ValueError("Layered mesh boundary segment has unsupported incidence")
    del (
        segment_keys,
        _unique_segment_keys,
        segment_inverse,
    )

    parents = np.arange(token_count, dtype=np.uint32)

    def find(token: int) -> int:
        root = token
        while int(parents[root]) != root:
            root = int(parents[root])
        while int(parents[token]) != token:
            next_token = int(parents[token])
            parents[token] = root
            token = next_token
        return root

    def union(first: int, second: int) -> None:
        first_root = find(first)
        second_root = find(second)
        if first_root == second_root:
            return
        if not np.array_equal(
            token_coordinates[first_root],
            token_coordinates[second_root],
        ):
            raise ValueError("Layered mesh attempted to join different coordinates")
        parents[second_root] = first_root

    def join_segment_pair(first_segment: int, second_segment: int) -> None:
        first_tokens = (
            int(segment_start[first_segment]),
            int(segment_end[first_segment]),
        )
        second_tokens = (
            int(segment_start[second_segment]),
            int(segment_end[second_segment]),
        )
        if np.array_equal(
            token_coordinates[first_tokens[0]],
            token_coordinates[second_tokens[0]],
        ):
            union(first_tokens[0], second_tokens[0])
            union(first_tokens[1], second_tokens[1])
        elif np.array_equal(
            token_coordinates[first_tokens[0]],
            token_coordinates[second_tokens[1]],
        ):
            union(first_tokens[0], second_tokens[1])
            union(first_tokens[1], second_tokens[0])
        else:
            raise ValueError("Layered mesh boundary segments do not match")

    def pair_has_material(first_segment: int, second_segment: int) -> bool:
        first_normal = segment_normal[first_segment].astype(np.float64)
        second_normal = segment_normal[second_segment].astype(np.float64)
        if float(np.dot(first_normal, second_normal)) != 0.0:
            return False
        first_token = int(segment_start[first_segment])
        second_token = int(segment_end[first_segment])
        low = np.minimum(
            token_coordinates[first_token],
            token_coordinates[second_token],
        ).astype(np.float64)
        high = np.maximum(
            token_coordinates[first_token],
            token_coordinates[second_token],
        ).astype(np.float64)
        sample = (low + high) * 0.25 - first_normal * 0.25 - second_normal * 0.25
        x, y, z = (int(np.floor(value)) for value in sample)
        return bool(
            0 <= z < component_labels.shape[0]
            and 0 <= y < component_labels.shape[1]
            and 0 <= x < component_labels.shape[2]
            and component_labels[z, y, x] == shell_id
        )

    for group_start, group_end in zip(segment_group_starts, segment_group_ends):
        instances = segment_order[int(group_start) : int(group_end)]
        if len(instances) == 2:
            join_segment_pair(int(instances[0]), int(instances[1]))
            continue
        unpaired = {0, 1, 2, 3}
        for first_index in range(4):
            if first_index not in unpaired:
                continue
            matches = [
                second_index
                for second_index in sorted(unpaired)
                if second_index != first_index
                and pair_has_material(
                    int(instances[first_index]),
                    int(instances[second_index]),
                )
            ]
            if len(matches) != 1:
                raise ValueError(
                    "Layered mesh could not separate a diagonal edge contact"
                )
            second_index = matches[0]
            join_segment_pair(
                int(instances[first_index]),
                int(instances[second_index]),
            )
            unpaired.remove(first_index)
            unpaired.remove(second_index)

    del (
        segment_start,
        segment_end,
        segment_normal,
        segment_order,
        segment_group_starts,
        segment_group_ends,
        segment_group_counts,
    )

    for token in range(token_count):
        parents[token] = find(token)
    roots, token_to_vertex = np.unique(parents, return_inverse=True)
    exact_world_doubled = token_coordinates[roots]
    faces = token_to_vertex[faces_by_token].astype(np.uint32, copy=False)
    del parents, roots, token_coordinates, token_to_vertex, faces_by_token

    exact_world_doubled[:, 1] = int(height_px) * 2 - exact_world_doubled[:, 1]
    vertices = exact_world_doubled.astype(np.float32) * np.float32(0.5)
    if lattice_audit is not None:
        lattice_audit.observe(exact_world_doubled, vertices)
    return vertices, faces


def _validate_component_arrays(
    vertices: np.ndarray,
    faces: np.ndarray,
    *,
    expected_volume: int,
) -> None:
    """Validate one bounded component before its compact arrays are retained."""

    if faces.ndim != 2 or faces.shape[1] != 3 or len(faces) == 0:
        raise ValueError("Layered surface meshing produced no triangles")
    if int(faces.min()) < 0 or int(faces.max()) >= len(vertices):
        raise ValueError("Layered surface meshing produced an invalid index")
    if np.any(
        (faces[:, 0] == faces[:, 1])
        | (faces[:, 1] == faces[:, 2])
        | (faces[:, 2] == faces[:, 0])
    ):
        raise ValueError("Layered surface meshing produced an index-degenerate triangle")

    signed_volume = 0.0
    for start in range(0, len(faces), 65_536):
        face_block = faces[start : start + 65_536]
        triangles = vertices[face_block].astype(np.float64, copy=False)
        twice_area = np.linalg.norm(
            np.cross(
                triangles[:, 1] - triangles[:, 0],
                triangles[:, 2] - triangles[:, 0],
            ),
            axis=1,
        )
        if np.any(twice_area == 0.0):
            raise ValueError(
                "Layered surface meshing produced a coordinate-degenerate triangle"
            )
        signed_volume += float(
            np.einsum(
                "ij,ij->i",
                triangles[:, 0],
                np.cross(triangles[:, 1], triangles[:, 2]),
            ).sum()
            / 6.0
        )

    edge_keys = np.empty(len(faces) * 3, dtype=np.uint64)
    output_offset = 0
    for first_column, second_column in ((0, 1), (1, 2), (2, 0)):
        for start in range(0, len(faces), 65_536):
            face_block = faces[start : start + 65_536]
            first = face_block[:, first_column]
            second = face_block[:, second_column]
            low = np.minimum(first, second).astype(np.uint64)
            high = np.maximum(first, second).astype(np.uint64)
            block_length = len(face_block)
            edge_keys[output_offset : output_offset + block_length] = (
                (low << np.uint64(32)) | high
            )
            output_offset += block_length
    edge_keys.sort(kind="quicksort")
    paired = bool(
        len(edge_keys) % 2 == 0
        and np.all(edge_keys[0::2] == edge_keys[1::2])
        and np.all(edge_keys[1:-1:2] != edge_keys[2::2])
    )
    if not paired:
        raise ValueError("Layered surface meshing produced an open edge or T-junction")
    if not np.isclose(signed_volume, float(expected_volume), rtol=0.0, atol=1e-9):
        raise ValueError("Layered surface meshing changed occupied volume")


def _shifted_slices(
    shape: tuple[int, int, int],
    offset: tuple[int, int, int],
) -> tuple[tuple[slice, ...], tuple[slice, ...]]:
    source: list[slice] = []
    target: list[slice] = []
    for length, delta in zip(shape, offset):
        if delta >= 0:
            source.append(slice(0, length - delta))
            target.append(slice(delta, length))
        else:
            source.append(slice(-delta, length))
            target.append(slice(0, length + delta))
    return tuple(source), tuple(target)


def _count_source_contacts(
    selected: np.ndarray,
    component_labels: np.ndarray,
) -> tuple[int, int]:
    """Count edge/point contacts between distinct six-connected components."""

    edge_pairs = 0
    point_pairs = 0
    for dz in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                offset = (dz, dy, dx)
                if offset <= (0, 0, 0):
                    continue
                nonzero_axes = int(dz != 0) + int(dy != 0) + int(dx != 0)
                if nonzero_axes not in {2, 3}:
                    continue
                if any(abs(delta) >= length for delta, length in zip(offset, selected.shape)):
                    continue
                source, target = _shifted_slices(selected.shape, offset)
                touching = selected[source] & selected[target]
                touching &= component_labels[source] != component_labels[target]
                pair_count = int(np.count_nonzero(touching))
                if nonzero_axes == 2:
                    edge_pairs += pair_count
                else:
                    point_pairs += pair_count
    return edge_pairs, point_pairs


def build_labeled_surface_mesh(
    labels: np.ndarray,
    *,
    material_id: int,
    height_px: int,
    policy: LayeredMeshPolicy | None = None,
) -> trimesh.Trimesh | None:
    """Build one exact closed material surface from a Z/Y/X label volume.
    从 Z/Y/X 标签体构建一个精确闭合的材料表面。

    Args:
        labels: Integer-like material labels in ``(Z, Y, X)`` order.
            按 ``(Z, Y, X)`` 排列的材料标签。
        material_id: Label to extract. 要提取的材料编号。
        height_px: Source image height used for the Y-axis flip.
            用于翻转 Y 轴的源图高度。
        policy: Optional validation policy. 可选的验证策略。

    Returns:
        A closed indexed mesh, or ``None`` when the material is absent.
        闭合索引网格；材料不存在时返回 ``None``。
    """

    volume = np.asarray(labels)
    if volume.ndim != 3:
        raise ValueError("labels must have shape (Z, Y, X)")
    if int(height_px) != height_px or int(height_px) < volume.shape[1]:
        raise ValueError("height_px must be an integer covering the label rows")
    selected = volume == material_id
    voxel_count = int(np.count_nonzero(selected))
    if voxel_count == 0:
        return None
    component_labels, component_count = ndimage.label(
        selected,
        structure=ndimage.generate_binary_structure(3, 1),
    )
    source_edge_contacts, source_point_contacts = _count_source_contacts(
        selected,
        component_labels,
    )
    effective_policy = policy or LayeredMeshPolicy()
    lattice_audit = _LatticeFloat32Audit()
    vertex_chunks: list[np.ndarray] = []
    face_chunks: list[np.ndarray] = []
    exposed_count = 0
    merged_patch_count = 0
    peak_component_patch_count = 0
    component_voxel_total = 0
    vertex_offset = 0
    component_bounds = ndimage.find_objects(component_labels)
    for shell_id, bounds in enumerate(component_bounds, start=1):
        if bounds is None:
            continue
        local_labels = component_labels[bounds]
        local_component = local_labels == shell_id
        component_voxel_count = int(np.count_nonzero(local_component))
        z_origin = int(bounds[0].start or 0)
        y_origin = int(bounds[1].start or 0)
        x_origin = int(bounds[2].start or 0)
        compact_patches, component_exposed = _component_patches(
            local_component,
            shell_id=shell_id,
            origin=(x_origin, y_origin, z_origin),
        )
        component_patch_count = len(compact_patches)
        component_vertices, component_faces = _mesh_arrays_from_patches(
            compact_patches,
            height_px=int(height_px),
            component_labels=component_labels,
            shell_id=shell_id,
            lattice_audit=lattice_audit,
        )
        del compact_patches
        if effective_policy.validate_output:
            _validate_component_arrays(
                component_vertices,
                component_faces,
                expected_volume=component_voxel_count,
            )

        if vertex_offset + len(component_vertices) > np.iinfo(np.uint32).max:
            raise ValueError("Layered surface mesh exceeds uint32 lattice indices")
        vertex_chunks.append(component_vertices)
        face_chunks.append(component_faces + np.uint32(vertex_offset))
        vertex_offset += len(component_vertices)
        exposed_count += component_exposed
        merged_patch_count += component_patch_count
        peak_component_patch_count = max(
            peak_component_patch_count,
            component_patch_count,
        )
        component_voxel_total += component_voxel_count
        del component_vertices, component_faces, local_component

    if len(vertex_chunks) != int(component_count) or component_voxel_total != voxel_count:
        raise ValueError("Layered surface component assembly is incomplete")
    del component_labels, component_bounds, local_labels, selected

    if len(vertex_chunks) == 1:
        lattice_vertices = vertex_chunks[0]
        lattice_faces = face_chunks[0]
    else:
        lattice_vertices = np.concatenate(vertex_chunks, axis=0)
        lattice_faces = np.concatenate(face_chunks, axis=0)
    vertex_chunks.clear()
    face_chunks.clear()

    lattice_float32_bytes = int(lattice_vertices.nbytes + lattice_faces.nbytes)
    lattice_vertex_count = len(lattice_vertices)
    lattice_face_count = len(lattice_faces)
    mesh = trimesh.Trimesh(
        vertices=lattice_vertices,
        faces=lattice_faces,
        process=False,
    )
    del lattice_vertices, lattice_faces

    materialized_bytes = int(mesh.vertices.nbytes + mesh.faces.nbytes)

    stats = LayeredMeshStats(
        source_voxel_count=voxel_count,
        component_count=int(component_count),
        exposed_unit_face_count=exposed_count,
        merged_patch_count=merged_patch_count,
        component_chunk_count=int(component_count),
        peak_component_patch_count=peak_component_patch_count,
        vertex_count=lattice_vertex_count,
        face_count=lattice_face_count,
        lattice_float32_bytes=lattice_float32_bytes,
        materialized_bytes=materialized_bytes,
        source_contact_edge_pair_count=source_edge_contacts,
        source_contact_point_pair_count=source_point_contacts,
        source_contact_normalized_edge_count=(
            lattice_audit.source_contact_normalized_edge_count
        ),
    )
    mesh.metadata["layered_mesh_stats"] = asdict(stats)
    mesh.metadata["integer_topology_scale"] = 2

    return mesh


__all__ = [
    "LayeredMeshPolicy",
    "LayeredMeshStats",
    "build_labeled_surface_mesh",
]
