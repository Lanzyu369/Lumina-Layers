"""Boundary-form contracts for the canonical boundary rule.

Every exported area ring must be simple: downstream OGC consumers reject a ring
that visits a vertex twice, a vertex sitting on a non-adjacent edge, a collinear
overlap, or a genuine self-crossing. The rule that guarantees this is shared by
the geometry kernel's area output and by this compensation surface, so the
boundary forms are pinned here together with the filled region they describe.

The region checks stay independent of the rule: the expected areas are known by
hand, and the probe computes winding numbers from the emitted coordinates
themselves instead of re-using the engine's ring machinery.
"""

from __future__ import annotations

import importlib
import importlib.util

import numpy as np
import pytest


# One unit here is one integer coordinate of the area output.
GRID_MM = 1e-5


def _grid(coordinates) -> np.ndarray:
    """mm coordinates as exact integer grid units."""
    values = np.asarray(coordinates, dtype=np.float64)
    scaled = np.rint(values / GRID_MM)
    assert np.allclose(scaled * GRID_MM, values, rtol=0.0, atol=1e-12), values
    return scaled.astype(np.int64)


def _ring(points) -> np.ndarray:
    """Input ring in millimetres, as the public surface consumes them."""
    return np.asarray([[float(x), float(y)] for x, y in points],
                      dtype=np.float64)


def _as_grid(rings):
    return [_grid(ring) for ring in rings]


def _square(left, bottom, right, top, clockwise: bool = False):
    points = [(left, bottom), (right, bottom), (right, top), (left, top)]
    return points[::-1] if clockwise else points


def _find_coverage(rings):
    module_name = "lumina_svg_core._lumina_svg_compensation"
    assert importlib.util.find_spec(module_name) is not None, (
        "The separate SVG compensation extension must be built"
    )
    module = importlib.import_module(module_name)
    return module.find_holes_mm(rings, 0.0, 0.0)


def _ring_fault(grid_points) -> str | None:
    """Why this ring is not simple, decided exactly on integer coordinates."""
    points = [tuple(int(value) for value in point) for point in grid_points]
    if len(set(points)) != len(points):
        return "repeated-vertex"
    count = len(points)

    def cross(origin, first, second):
        return ((first[0] - origin[0]) * (second[1] - origin[1])
                - (first[1] - origin[1]) * (second[0] - origin[0]))

    def on_segment(point, first, second):
        return (cross(first, second, point) == 0
                and min(first[0], second[0]) <= point[0] <= max(first[0], second[0])
                and min(first[1], second[1]) <= point[1] <= max(first[1], second[1]))

    for index in range(count):
        first, second = points[index], points[(index + 1) % count]
        for other in range(index + 1, count):
            if other == index or (other + 1) % count == index \
                    or other == (index + 1) % count:
                continue
            third, fourth = points[other], points[(other + 1) % count]
            if ((cross(third, fourth, first) > 0)
                    != (cross(third, fourth, second) > 0)) and (
                        (cross(first, second, third) > 0)
                        != (cross(first, second, fourth) > 0)):
                return f"crossing {index}x{other}"
            if on_segment(first, third, fourth):
                return f"vertex-on-edge {index}x{other}"
            if on_segment(third, first, second):
                return f"vertex-on-edge {other}x{index}"
    return None


def _winding(samples: np.ndarray, rings):
    """NonZero winding number at each sample, plus an on-boundary mask."""
    winding = np.zeros(len(samples), dtype=np.int64)
    on_boundary = np.zeros(len(samples), dtype=bool)
    sample_x, sample_y = samples[:, 0], samples[:, 1]
    for points in rings:
        count = len(points)
        for index in range(count):
            start = points[index]
            end = points[(index + 1) % count]
            if start[1] == end[1]:
                continue
            left = ((end[0] - start[0]) * (sample_y - start[1])
                    - (end[1] - start[1]) * (sample_x - start[0]))
            rising = (start[1] <= sample_y) & (end[1] > sample_y)
            falling = (start[1] > sample_y) & (end[1] <= sample_y)
            winding += np.where(rising & (left > 0), 1, 0)
            winding -= np.where(falling & (left < 0), 1, 0)
            on_boundary |= (
                (left == 0)
                & (sample_x >= min(start[0], end[0]))
                & (sample_x <= max(start[0], end[0]))
                & (sample_y >= min(start[1], end[1]))
                & (sample_y <= max(start[1], end[1])))
    return winding, on_boundary


def _distance_to_linework(samples: np.ndarray, rings) -> np.ndarray:
    """Distance from each sample to the nearest segment, in grid units."""
    distance = np.full(len(samples), np.inf)
    for points in rings:
        count = len(points)
        for index in range(count):
            start = points[index].astype(np.float64)
            end = points[(index + 1) % count].astype(np.float64)
            direction = end - start
            length = float(direction @ direction)
            if length == 0.0:
                continue
            offset = samples - start
            parameter = np.clip(
                (offset @ direction) / length, 0.0, 1.0)
            closest = start + parameter[:, None] * direction
            distance = np.minimum(
                distance, np.linalg.norm(samples - closest, axis=1))
    return distance


def _samples(rings, step_grid: int) -> np.ndarray:
    points = np.concatenate(rings, axis=0)
    low = points.min(axis=0) - 1
    high = points.max(axis=0) + 1
    x_values = np.arange(low[0], high[0] + step_grid, step_grid) + step_grid / 2
    y_values = np.arange(low[1], high[1] + step_grid, step_grid) + step_grid / 3
    grid_x, grid_y = np.meshgrid(x_values, y_values)
    return np.stack([grid_x.ravel(), grid_y.ravel()], axis=1)


def _emitted_rings(coverage):
    """Coverage rings in grid units."""
    rings = []
    for shell, interiors in coverage:
        rings.append(_grid(shell))
        rings.extend(_grid(hole) for hole in interiors)
    return rings


def _coverage_area_mm2(coverage) -> float:
    area = 0.0
    for shell, interiors in coverage:
        area += abs(_signed_area(_grid(shell)))
        area -= sum(abs(_signed_area(_grid(hole))) for hole in interiors)
    return area * GRID_MM ** 2


def _signed_area(points) -> float:
    total = 0.0
    for index in range(len(points)):
        first = points[index]
        second = points[(index + 1) % len(points)]
        total += first[0] * second[1] - second[0] * first[1]
    return total / 2.0


def _assert_simple(coverage) -> None:
    for ring in _emitted_rings(coverage):
        assert _ring_fault(ring) is None, _ring_fault(ring)


def _assert_vertices_kept(rings, coverage) -> None:
    """Every input vertex still belongs to the emitted boundary."""
    emitted = set()
    for ring in _emitted_rings(coverage):
        emitted.update(tuple(point) for point in ring)
    for ring in _as_grid(rings):
        for point in ring:
            assert tuple(point) in emitted, f"moved vertex {point.tolist()}"


def _assert_no_invented_vertices(rings, coverage,
                                 tolerance_units: float = 1.0) -> None:
    """Reorganizing moves nothing: every emitted vertex is an input vertex or a
    node of the input linework, within the grid's own rounding distance."""
    segments = []
    vertices = set()
    for ring in _as_grid(rings):
        vertices.update(tuple(point) for point in ring)
        for index in range(len(ring)):
            segments.append((ring[index], ring[(index + 1) % len(ring)]))
    for emitted in _emitted_rings(coverage):
        for point in emitted:
            if tuple(point) in vertices:
                continue
            assert min(_segment_distance(point, a, b)
                       for a, b in segments) <= tolerance_units, (
                f"invented vertex {point.tolist()}")


def _segment_distance(point, first, second) -> float:
    point = np.asarray(point, dtype=np.float64)
    first = np.asarray(first, dtype=np.float64)
    second = np.asarray(second, dtype=np.float64)
    direction = second - first
    length = float(direction @ direction)
    if length == 0.0:
        return float(np.linalg.norm(point - first))
    parameter = float((point - first) @ direction) / length
    parameter = min(1.0, max(0.0, parameter))
    return float(np.linalg.norm(point - (first + parameter * direction)))


def _assert_region_preserved(rings, coverage, expected_area_mm2,
                             step_grid: int = 5000) -> None:
    samples = _samples(_as_grid(rings), step_grid)
    source, on_source = _winding(samples, _as_grid(rings))
    emitted, on_emitted = _winding(samples, _emitted_rings(coverage))
    compared = ~(on_source | on_emitted)
    assert compared.sum() > 0.9 * len(samples), "sampling degenerated"
    mismatch = compared & ((source != 0) != (emitted != 0))
    assert not mismatch.any(), (
        f"{int(mismatch.sum())} of {int(compared.sum())} samples disagree, "
        f"first {samples[mismatch][:4].tolist()}")
    assert _coverage_area_mm2(coverage) == pytest.approx(
        expected_area_mm2, abs=(step_grid * GRID_MM) ** 2)


def test_two_lobes_joined_at_one_vertex_become_two_rings():
    # One contour visiting its start vertex twice: two lobes meeting at a point.
    rings = [_ring([(0, 0), (10, 0), (10, 10), (0, 0), (-10, 0), (-10, -10)])]
    _, coverage = _find_coverage(rings)
    _assert_simple(coverage)
    assert len(coverage) == 2
    _assert_vertices_kept(rings, coverage)
    _assert_region_preserved(rings, coverage, 100.0)


def test_vertex_landing_on_a_non_adjacent_edge_is_split():
    # (5, 0) sits on the edge (0, 0)-(10, 0) without repeating a vertex.
    rings = [_ring([(0, 0), (10, 0), (10, 10), (5, 0), (0, 10)])]
    _, coverage = _find_coverage(rings)
    _assert_simple(coverage)
    _assert_vertices_kept(rings, coverage)
    _assert_region_preserved(rings, coverage, 50.0)


def test_collinear_out_and_back_run_is_split():
    # Out along y = 0 to x = 20, then back along the same line to x = 10.
    rings = [_ring([(0, 0), (20, 0), (10, 0), (10, 10), (0, 10)])]
    _, coverage = _find_coverage(rings)
    _assert_simple(coverage)
    # The out-and-back run encloses nothing, so its far end is not a boundary
    # vertex of the region any more.
    _assert_no_invented_vertices(rings, coverage)
    _assert_region_preserved(rings, coverage, 100.0)


def test_true_crossing_at_a_fractional_grid_point_is_snapped():
    # Edges (0, 0)-(3, 1) and (1, 0)-(0, 1) cross at (0.75, 0.25) grid units.
    assert _ring_fault([[0, 0], [3, 1], [1, 0], [0, 1]]) == "crossing 0x2"
    rings = [_ring([(0, 0), (0.0003, 0.0001), (0.0001, 0), (0, 0.0001)])]
    _, coverage = _find_coverage(rings)
    _assert_simple(coverage)
    assert len(coverage) == 2
    _assert_no_invented_vertices(rings, coverage)
    crossing = np.array([7.5, 2.5])
    emitted = np.concatenate(_emitted_rings(coverage), axis=0)
    assert np.min(np.linalg.norm(emitted - crossing, axis=1)) <= 1.0
    # A snapped node may only change the region within the grid's rounding
    # distance of the linework, so winding is compared away from it.
    samples = _samples(_as_grid(rings), 1).astype(np.float64)
    grid_rings = _as_grid(rings)
    emitted_rings = _emitted_rings(coverage)
    source, on_source = _winding(samples, grid_rings)
    emitted_winding, on_emitted = _winding(samples, emitted_rings)
    far = ((_distance_to_linework(samples, grid_rings) > 1.0)
           & (_distance_to_linework(samples, emitted_rings) > 1.0))
    compared = ~(on_source | on_emitted) & far
    assert compared.sum() > 0
    assert not (compared & ((source != 0) != (emitted_winding != 0))).any()


def test_hole_touching_its_shell_at_one_vertex():
    rings = [_ring(_square(0, 0, 20, 20)),
             _ring(_square(0, 0, 6, 6, clockwise=True))]
    _, coverage = _find_coverage(rings)
    _assert_simple(coverage)
    # The shared corner is interior to the hole, so it is not on the boundary.
    _assert_no_invented_vertices(rings, coverage)
    _assert_region_preserved(rings, coverage, 364.0)


def test_hole_touching_its_shell_along_an_edge():
    rings = [_ring(_square(0, 0, 20, 20)),
             _ring(_square(0, 4, 6, 10, clockwise=True))]
    _, coverage = _find_coverage(rings)
    _assert_simple(coverage)
    _assert_vertices_kept(rings, coverage)
    _assert_region_preserved(rings, coverage, 364.0)


def test_island_inside_a_hole_is_filled_again():
    rings = [_ring(_square(0, 0, 20, 20)),
             _ring(_square(5, 5, 15, 15, clockwise=True)),
             _ring(_square(8, 8, 12, 12))]
    _, coverage = _find_coverage(rings)
    _assert_simple(coverage)
    _assert_vertices_kept(rings, coverage)
    # 400 - 100 + 16: nesting parity, not a hole count.
    _assert_region_preserved(rings, coverage, 316.0)


def test_interior_hole_stays_a_hole():
    rings = [_ring(_square(0, 0, 20, 20)),
             _ring(_square(5, 5, 15, 15, clockwise=True))]
    _, coverage = _find_coverage(rings)
    _assert_simple(coverage)
    assert len(coverage) == 1
    assert len(coverage[0][1]) == 1
    _assert_region_preserved(rings, coverage, 300.0)


# The geometry kernel renders a document at 1e12 grid cells across the target
# width, so a document that is exactly the target width puts one grid cell at
# 1e-10 mm and the millimetre path data below lands on the intended integers.
DOCUMENT_MM = 100.0
UNITS_PER_MM = 1e10
TRIANGLE_SCALE = 2048


def _near_collinear_shared_vertex():
    """Two triangles meeting only at one vertex, and the outlines they draw.

    The edges that end at the shared vertex are long, nearly collinear with
    each other, and their far ends are 600 mm apart. A contact judged in
    floating point reads the shared endpoint as t = 0.9999999 and invents a
    node inside both edges, which is what made the kernel drop this document
    entirely; the rule decides the contact exactly and keeps the vertex.
    TRIANGLE_SCALE moves the products across the double lattice, so it is part
    of the fixture rather than a rendering detail.
    """
    scale = TRIANGLE_SCALE
    a = (-80000142 * scale, -119999829 * scale)
    p = (0, 0)
    r = (80000265 * scale, 120000014 * scale)
    reach = 20000000 * scale
    units = [[a, p, (-3 * reach, 2 * reach)],
             [r, p, (3 * reach, -2 * reach)]]

    flat = [point for ring in units for point in ring]
    width = max(x for x, _ in flat) - min(x for x, _ in flat)
    height = max(y for _, y in flat) - min(y for _, y in flat)
    shift = (int((DOCUMENT_MM * UNITS_PER_MM - width) // 2) - min(x for x, _ in flat),
             int((DOCUMENT_MM * UNITS_PER_MM - height) // 2) - min(y for _, y in flat))
    to_mm = 1.0 / UNITS_PER_MM

    def point_mm(point):
        return ((point[0] + shift[0]) * to_mm, (point[1] + shift[1]) * to_mm)

    paths = []
    for ring in units:
        data = "M" + "L".join(f"{x:.10f} {y:.10f}"
                              for x, y in (point_mm(point) for point in ring)) + "Z"
        paths.append(f"<path fill='#000000' d='{data}'/>")
    svg = (f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 "
           f"{DOCUMENT_MM} {DOCUMENT_MM}' width='{DOCUMENT_MM}' "
           f"height='{DOCUMENT_MM}'>" + "".join(paths) + "</svg>")
    return svg, [[point_mm(point) for point in ring] for ring in units]


def _collection_rings(collection, source_unit_mm: float):
    """Emitted area rings in millimetres, closing point removed."""
    rings = []
    for polygon_index in range(len(collection.polygon_offsets) - 1):
        for ring_index in range(collection.polygon_offsets[polygon_index],
                                 collection.polygon_offsets[polygon_index + 1]):
            points = collection.coordinates[
                collection.ring_offsets[ring_index]:
                collection.ring_offsets[ring_index + 1]]
            ring = [tuple(float(value) * source_unit_mm for value in point)
                    for point in points]
            if len(ring) > 1 and ring[0] == ring[-1]:
                ring.pop()
            rings.append(ring)
    return rings


def _ring_area_mm2(ring) -> float:
    total = 0.0
    for index in range(len(ring)):
        first = ring[index]
        second = ring[(index + 1) % len(ring)]
        total += first[0] * second[1] - second[0] * first[1]
    return abs(total) / 2.0


def test_shared_endpoint_of_near_collinear_edges_is_not_split():
    module_name = "lumina_svg_core"
    assert importlib.util.find_spec(module_name) is not None, (
        "The SVG geometry kernel must be built"
    )
    kernel = importlib.import_module(module_name)
    svg, expected = _near_collinear_shared_vertex()
    result = kernel.analyze_svg_svg(svg, DOCUMENT_MM, 0.02, True)

    expected_vertices = {(round(x, 9), round(y, 9))
                         for ring in expected for x, y in ring}
    expected_area = sum(_ring_area_mm2(ring) for ring in expected)
    assert expected_area > 0.0

    assert result.status == "supported", result.reason_code
    # raw, visible and silhouette describe the same two triangles.
    for name in ("raw", "visible", "silhouette"):
        rings = _collection_rings(getattr(result, name),
                                  result.grid_to_source_unit)
        assert len(rings) == 2, name
        assert all(len(ring) == 3 for ring in rings), name
        emitted = {(round(x, 9), round(y, 9)) for ring in rings for x, y in ring}
        # The shared vertex is a contact at that vertex, not a new node, so
        # reorganizing the boundary invents nothing and moves nothing.
        assert emitted == expected_vertices, name
        assert sum(_ring_area_mm2(ring) for ring in rings) == pytest.approx(
            expected_area, rel=1e-12), name


# A document authored with these integers reaches the native export exactly:
# the kernel renders the 100 mm viewBox at the 100 mm target width, so one grid
# cell is 1e-10 mm and the integers below land straight on the rule's grid.
# The scale only moves the products across the double lattice.
ENTRY_SCALE = 1000000


def _entry_document(ring_sets, scale: int = ENTRY_SCALE):
    """Author integer rings as SVG path data on the kernel's own grid."""
    scaled = [[(int(x) * scale, int(y) * scale) for x, y in ring]
              for ring in ring_sets]
    flat = [point for ring in scaled for point in ring]
    width = max(x for x, _ in flat) - min(x for x, _ in flat)
    height = max(y for _, y in flat) - min(y for _, y in flat)
    span = int(DOCUMENT_MM * UNITS_PER_MM)
    shift = (int((span - width) // 2) - min(x for x, _ in flat),
             int((span - height) // 2) - min(y for _, y in flat))
    to_mm = 1.0 / UNITS_PER_MM

    def point_mm(point):
        return ((point[0] + shift[0]) * to_mm, (point[1] + shift[1]) * to_mm)

    paths = []
    for ring in scaled:
        data = "M" + "L".join(f"{x:.10f} {y:.10f}"
                              for x, y in (point_mm(point) for point in ring)) + "Z"
        paths.append(f"<path fill='#000000' d='{data}'/>")
    svg = (f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 "
           f"{DOCUMENT_MM} {DOCUMENT_MM}' width='{DOCUMENT_MM}' "
           f"height='{DOCUMENT_MM}'>" + "".join(paths) + "</svg>")
    return svg, shift


def _kernel_entry(svg):
    module_name = "lumina_svg_core"
    assert importlib.util.find_spec(module_name) is not None, (
        "The SVG geometry kernel must be built"
    )
    return importlib.import_module(module_name).analyze_svg_svg(
        svg, DOCUMENT_MM, 0.02, True)


def _authored_rings(collection, shift, scale: int = ENTRY_SCALE):
    """Emitted rings back as the authored integers, closing point removed.

    One grid cell is 1e-10 mm here, so the raw grid coordinates that
    `_collection_rings` reads with a unit of 1.0 are the authored units before
    the centring shift and the scale.
    """
    rings = []
    for ring in _collection_rings(collection, 1.0):
        rings.append([(int(round(x)) - shift[0], int(round(y)) - shift[1])
                      for x, y in ring])
    assert all(x % scale == 0 and y % scale == 0
               for ring in rings for x, y in ring), "not on the authored lattice"
    return [[(x // scale, y // scale) for x, y in ring] for ring in rings]


def _assert_legal_rings(rings, name: str) -> None:
    for ring in rings:
        assert _ring_fault(ring) is None, (name, _ring_fault(ring), ring)


def _self_touching_pair():
    """A ring visiting its own start vertex, and a triangle sharing that vertex.

    The ring traces two lobes that meet at (0, 0), which is not a legal
    boundary expression; the triangle touches the same point. Whether the
    export notices depends on which ring the rule looks at first: the vertex
    belongs to both, and a record that only remembers the first visitor cannot
    tell a ring meeting itself from a contact between two rings.
    """
    return [[(0, 0), (20, 0), (20, 20), (0, 0), (0, -20), (20, -20)],
            [(0, 0), (-20, 10), (-20, -10)]]


@pytest.mark.parametrize("self_touching_first", [True, False])
def test_self_touching_ring_is_rebuilt_in_either_draw_order(
        self_touching_first):
    rings = _self_touching_pair()
    if not self_touching_first:
        rings = rings[::-1]
    svg, shift = _entry_document(rings)
    result = _kernel_entry(svg)
    assert result.status == "supported", result.reason_code

    expected = {(0, 0), (20, 0), (20, 20), (0, -20), (20, -20),
                (-20, 10), (-20, -10)}
    # The two lobes and the triangle are three separate triangles that share
    # only their vertices; the region is 400 + 200 in authored units.
    for name in ("raw", "visible", "silhouette"):
        emitted = _authored_rings(getattr(result, name), shift)
        _assert_legal_rings(emitted, name)
        assert len(emitted) == 3, (name, emitted)
        assert all(len(ring) == 3 for ring in emitted), (name, emitted)
        assert {(x, y) for ring in emitted for x, y in ring} == expected, name
        assert sum(_ring_area_mm2(ring) for ring in emitted) == pytest.approx(
            600.0, rel=1e-12), name


def test_vertex_resting_on_another_rings_edge_is_split():
    # (5, 0) is a vertex of the triangle and sits inside the square's bottom
    # edge. Each drawn path keeps its own boundary, but the composite coverage
    # holds both rings in one tree, and there the contact has to be noded
    # before the faces are built.
    rings = [[(0, 0), (20, 0), (20, 20), (0, 20)],
             [(5, 0), (12, -9), (19, -9)]]
    svg, shift = _entry_document(rings)
    result = _kernel_entry(svg)
    assert result.status == "supported", result.reason_code

    for name in ("raw", "visible"):
        collection = getattr(result, name)
        emitted = _authored_rings(collection, shift)
        _assert_legal_rings(emitted, name)
        # One area geometry per drawn path, each with its own simple boundary.
        assert len(collection.geometry_offsets) - 1 == 2, name
        # 400 for the square plus 7 x 9 / 2 for the triangle.
        assert sum(_ring_area_mm2(ring) for ring in emitted) == pytest.approx(
            431.5, rel=1e-12), name

    emitted = _authored_rings(result.silhouette, shift)
    _assert_legal_rings(emitted, "silhouette")
    assert len(result.silhouette.geometry_offsets) - 1 == 1
    assert len(emitted) == 2, emitted
    # Both rings of the composite carry the node this contact needs.
    assert all((5, 0) in ring for ring in emitted), emitted
    assert sum(_ring_area_mm2(ring) for ring in emitted) == pytest.approx(
        431.5, rel=1e-12)
