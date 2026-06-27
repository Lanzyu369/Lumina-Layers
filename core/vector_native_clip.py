"""Optional native helpers for SVG occlusion clipping.

The functions here are intentionally standalone POC plumbing: they convert
Shapely geometry to the same path format used by the Clipper2 mesh extension
and restore native polygon output back to Shapely geometry. The main vector
pipeline can keep using Shapely until native clipping passes corpus quality
checks.
"""

from __future__ import annotations

import importlib
from typing import Any

from shapely.geometry import MultiPolygon, Polygon
from shapely.validation import make_valid

from core.vector_native_mesh import NATIVE_COORD_SCALE, _geometry_to_paths


def difference_with_native(
    subject,
    clips,
    *,
    native_module: Any | None = None,
    scale: int = NATIVE_COORD_SCALE,
):
    """Return ``subject - union(clips)`` through a Clipper2-style native module."""

    if subject is None or subject.is_empty:
        return None

    subject_paths = _geometry_to_paths(subject)
    clip_paths = []
    for clip in clips or []:
        clip_paths.extend(_geometry_to_paths(clip))
    if not subject_paths:
        return None
    if not clip_paths:
        return subject

    module = native_module if native_module is not None else importlib.import_module("clipper2_batch")
    difference_paths = getattr(module, "difference_paths", None)
    if not callable(difference_paths):
        raise RuntimeError("clipper2_batch.difference_paths is unavailable")

    native_polygons = difference_paths(subject_paths, clip_paths, scale=int(scale))
    return _geometry_from_native_polygons(native_polygons)


def _geometry_from_native_polygons(native_polygons):
    polygons = []
    for native_polygon in list(native_polygons or []):
        rings = list(native_polygon or [])
        if not rings:
            continue
        exterior = _native_ring(rings[0])
        if not exterior:
            continue
        holes = []
        for ring in rings[1:]:
            hole = _native_ring(ring)
            if hole:
                holes.append(hole)
        try:
            poly = Polygon(exterior, holes)
        except Exception:
            continue
        if poly.is_empty:
            continue
        if not poly.is_valid:
            poly = make_valid(poly)
        if poly is not None and not poly.is_empty:
            if poly.geom_type == "Polygon":
                polygons.append(poly)
            elif poly.geom_type == "MultiPolygon":
                polygons.extend(part for part in poly.geoms if not part.is_empty)

    if not polygons:
        return None
    if len(polygons) == 1:
        return polygons[0]
    return MultiPolygon(polygons)


def _native_ring(points) -> list[tuple[float, float]]:
    ring = []
    for point in list(points or []):
        try:
            x, y = point[:2]
        except (TypeError, ValueError):
            return []
        ring.append((float(x), float(y)))
    if len(ring) > 1 and ring[0] == ring[-1]:
        ring.pop()
    return ring if len(ring) >= 3 else []
