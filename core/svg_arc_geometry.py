"""Conditioned endpoint-arc parsing for the legacy SVG geometry consumers.

Keep svgelements' lexer and document semantics, but avoid its acos(dot) loss of
small sweep angles and center-plus-radius cancellation for ill-conditioned arcs.
"""

from __future__ import annotations

import math
from typing import Any

from svgelements import Arc, ClipPath, CubicBezier, Group, Image, Path, Shape, SVG, Text, Use


_MAX_CONDITIONED_ARC_SEGMENTS = 65536


class _EndpointArcPath(Path):
    """Retain endpoint parameters until smooth commands have also been parsed."""

    def __init__(self, path_data: str, *, ignore_parse_errors: bool = False) -> None:
        self.endpoint_arcs: dict[int, tuple[float, float, float, bool, bool]] = {}
        super().__init__()
        try:
            self.parse(path_data)
        except ValueError:
            # SVG.parse's default on_error='ignore' keeps a valid prefix.
            # Preserve that boundary while still conditioning its parsed arcs.
            if not ignore_parse_errors:
                raise

    def arc(self, *arc_args: Any, relative: bool = False, **kwargs: Any) -> Path:
        for index in range(0, len(arc_args), 6):
            arguments = arc_args[index:index + 6]
            segment_index = len(self)
            super().arc(*arguments, relative=relative, **kwargs)
            self.endpoint_arcs[segment_index] = (
                abs(float(arguments[0])), abs(float(arguments[1])),
                float(arguments[2]), bool(arguments[3]), bool(arguments[4]),
            )
        return self


def _conditioned_arc_cubics(
    segment: Arc,
    parameters: tuple[float, float, float, bool, bool],
    tolerance: float,
) -> list[CubicBezier] | None:
    rx, ry, rotation, large_arc, sweep = parameters
    if (
        (segment.start.x == segment.end.x and segment.start.y == segment.end.y)
        or rx == 0.0 or ry == 0.0
    ):
        # SVG omits coincident-endpoint arcs; zero radii act as a straight line.
        # The existing degenerate Arc sampler already implements both cases.
        return None

    angle = math.radians(rotation % 360.0)
    cos_rotation, sin_rotation = math.cos(angle), math.sin(angle)
    dx = (segment.start.x - segment.end.x) * 0.5
    dy = (segment.start.y - segment.end.y) * 0.5
    qx = (cos_rotation * dx + sin_rotation * dy) / rx
    qy = (-sin_rotation * dx + cos_rotation * dy) / ry
    half_chord = math.hypot(qx, qy)
    if not math.isfinite(half_chord) or half_chord == 0.0:
        raise ValueError("SVG arc radii exceed the supported floating-point precision")
    if half_chord > 1.0:
        # SVG's mandatory radii correction, without rx² * ry² overflow.
        rx *= half_chord
        ry *= half_chord
        qx /= half_chord
        qy /= half_chord
        half_chord = 1.0

    minor_sweep = 2.0 * math.asin(half_chord)
    arc_sweep = (math.tau - minor_sweep) if large_arc else minor_sweep
    if not sweep:
        arc_sweep = -arc_sweep
    radius = max(rx, ry)
    # Bound the legacy angle/center conditioning at the requested source scale.
    # Well-conditioned arcs retain their original segment and sampling behavior.
    conditioning_error = radius * (
        abs(arc_sweep - segment.sweep) + 8.0 * math.ulp(1.0) / half_chord
    )
    if conditioning_error <= tolerance:
        return None

    center_sign = -1.0 if large_arc == sweep else 1.0
    center_distance = math.sqrt(max(0.0, (1.0 - half_chord) * (1.0 + half_chord)))
    cx = center_sign * center_distance * (qy / half_chord)
    cy = -center_sign * center_distance * (qx / half_chord)
    start_x, start_y = qx - cx, qy - cy
    end_x, end_y = -qx - cx, -qy - cy

    # For a unit circular tangent cubic, with u=tan(piece_angle/4), the
    # squared radial error is u^6*v^2*(1-v^2)^2/(1+u^2)^2, v=2t-1.
    # Since v^2*(1-v^2)^2 <= 4/27, radial/Hausdorff error <= 2*u^6/27.
    # Rotation preserves it; the ellipse scales it by at most max(rx, ry).
    limit = min(math.pi / 2.0, 4.0 * math.atan((tolerance / radius * 13.5) ** (1.0 / 6.0)))
    if limit == 0.0 or not math.isfinite(limit):
        raise ValueError("SVG arc cannot be represented at the requested precision")
    piece_count = max(1, math.ceil(abs(arc_sweep) / limit))
    # Refuse an unbounded allocation explicitly instead of silently relaxing
    # the approximation budget or emitting a truncated arc.
    if piece_count > _MAX_CONDITIONED_ARC_SEGMENTS:
        raise ValueError("SVG arc requires too many segments at the requested precision")
    piece_sweep = arc_sweep / piece_count
    tangent_scale = 4.0 / 3.0 * math.tan(piece_sweep / 4.0)

    def _ellipse_vector(x: float, y: float) -> tuple[float, float]:
        return (
            rx * x * cos_rotation - ry * y * sin_rotation,
            rx * x * sin_rotation + ry * y * cos_rotation,
        )

    cubics = []
    point_start = segment.start
    radial_x, radial_y = start_x, start_y
    for index in range(piece_count):
        theta = piece_sweep * (index + 1)
        sin_theta = math.sin(theta)
        cos_minus_one = -2.0 * math.sin(theta * 0.5) ** 2
        offset_x = cos_minus_one * start_x - sin_theta * start_y
        offset_y = sin_theta * start_x + cos_minus_one * start_y
        next_x, next_y = start_x + offset_x, start_y + offset_y
        offset = _ellipse_vector(offset_x, offset_y)
        point_end = (segment.start.x + offset[0], segment.start.y + offset[1])
        if index == piece_count - 1:
            point_end = segment.end
            next_x, next_y = end_x, end_y
        derivative_start = _ellipse_vector(-radial_y, radial_x)
        derivative_end = _ellipse_vector(-next_y, next_x)
        control1 = (
            point_start[0] + tangent_scale * derivative_start[0],
            point_start[1] + tangent_scale * derivative_start[1],
        )
        control2 = (
            point_end[0] - tangent_scale * derivative_end[0],
            point_end[1] - tangent_scale * derivative_end[1],
        )
        cubics.append(CubicBezier(point_start, control1, control2, point_end))
        point_start = point_end
        radial_x, radial_y = next_x, next_y
    return cubics


def _path_needs_conditioning(path: Path, tolerance: float) -> bool:
    """Cheap conservative preflight; original flags are read only by the lexer."""
    for segment in path:
        if not isinstance(segment, Arc):
            continue
        if segment.start.x == segment.end.x and segment.start.y == segment.end.y:
            continue
        radius = max(segment.rx, segment.ry)
        chord = math.hypot(
            segment.start.x - segment.end.x, segment.start.y - segment.end.y,
        )
        if radius == 0.0:
            # Point.__eq__ also collapses distinct endpoints <1e-12 apart.
            # Re-read source radii before deciding whether this is degenerate.
            return True
        if not math.isfinite(radius):
            return True
        if chord / radius < 0.01 and abs(segment.sweep) in (0.0, math.tau):
            # acos(dot) may round a nonzero angle to either zero or a full
            # revolution. A lost large-arc flag is a topological error even
            # when the coordinate-scale conditioning estimate is small.
            return True
        # normalized half chord >= chord / (2 * maximum radius). This
        # overestimates the conditioning error, including eccentric ellipses.
        if radius * 16.0 * math.ulp(1.0) / max(chord / radius, math.ulp(1.0)) > tolerance:
            return True
    return False


def parse_svg_path(path_data: str, tolerance: float) -> Path:
    """Use the original path unless endpoint arcs need conditioned geometry."""
    path = Path(path_data)
    return _condition_svg_path(path, path_data, tolerance)


def _condition_svg_path(
    path: Path, path_data: str, tolerance: float, *, ignore_parse_errors: bool = False,
) -> Path:
    if "a" not in path_data and "A" not in path_data:
        return path
    if not _path_needs_conditioning(path, tolerance):
        return path
    path = _EndpointArcPath(path_data, ignore_parse_errors=ignore_parse_errors)
    # Parsing must finish first: A followed by S/T must not reflect a generated
    # cubic's control point. Work backwards so the recorded indices stay valid.
    for index, parameters in reversed(path.endpoint_arcs.items()):
        cubics = _conditioned_arc_cubics(path[index], parameters, tolerance)
        if cubics is not None:
            path[index:index + 1] = cubics
    return path


def parse_svg_document(source: Any, tolerance: float) -> SVG | None:
    """Preserve document/CSS/use semantics and condition arcs before reifying."""
    document = SVG.parse(source, reify=False)
    if document is None:
        return None
    pending = [document, *document.objects.values()]
    visited = set()
    while pending:
        element = pending.pop()
        if id(element) in visited:
            continue
        visited.add(id(element))
        if isinstance(element, (Group, Use, ClipPath)):
            pending.extend(element)
        if not isinstance(element, (Shape, Image, Text)):
            continue
        if isinstance(element, Path):
            path_data = element.values.get("d", "")
            if "a" in path_data or "A" in path_data:
                matrix = element.transform
                # Exact largest singular value of a 2D affine linear part.
                scale = (
                    math.hypot(matrix.a + matrix.d, matrix.b - matrix.c) * 0.5
                    + math.hypot(matrix.a - matrix.d, matrix.b + matrix.c) * 0.5
                )
                local_tolerance = tolerance / max(scale, math.ulp(1.0))
                path = _condition_svg_path(
                    element, path_data, local_tolerance, ignore_parse_errors=True,
                )
                if path is not element:
                    element[:] = list(path.segments(transformed=False))
        element.reify()
    return document
