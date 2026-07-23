from __future__ import annotations

import shapely.geometry as sg

from core.model_surface.artwork import SurfacePlacement
from core.model_surface.types import EdgeMode, PlaneFrame, SurfaceFootprint


def surface_footprint_from_payload(payload: dict) -> SurfaceFootprint:
    """Deserialize a JSON-compatible payload into a surface footprint.

    将 JSON 兼容数据反序列化为模型覆面表面轮廓。
    """

    frame_payload = payload["frame"]
    if not isinstance(frame_payload, dict):
        raise ValueError("footprint.frame must be an object")

    outer = _points_2d(payload["outer"])
    holes = tuple(_points_2d(hole) for hole in payload.get("holes", []))
    bounds_min = (
        _point_2d(payload.get("bounds_min"))
        if payload.get("bounds_min") is not None
        else _bounds_min(outer)
    )
    bounds_max = (
        _point_2d(payload.get("bounds_max"))
        if payload.get("bounds_max") is not None
        else _bounds_max(outer)
    )
    width = float(payload.get("bounds_width_mm") or (bounds_max[0] - bounds_min[0]))
    height = float(payload.get("bounds_height_mm") or (bounds_max[1] - bounds_min[1]))
    area = float(payload.get("area_mm2") or _polygon_area(outer, holes))
    return SurfaceFootprint(
        frame=PlaneFrame(
            origin=_point_3d(frame_payload["origin"]),
            normal=_point_3d(frame_payload["normal"]),
            u_axis=_point_3d(frame_payload["u_axis"]),
            v_axis=_point_3d(frame_payload["v_axis"]),
        ),
        outer=outer,
        holes=holes,
        bounds_min=bounds_min,
        bounds_max=bounds_max,
        bounds_width_mm=width,
        bounds_height_mm=height,
        area_mm2=area,
        hole_count=int(payload.get("hole_count", len(holes))),
    )


def surface_placement_from_payload(payload: dict) -> SurfacePlacement:
    """Deserialize artwork placement settings from a JSON payload.

    从 JSON 数据反序列化贴面图片摆放设置。
    """

    return SurfacePlacement(
        mode=EdgeMode(str(payload.get("mode", EdgeMode.EDGE_TO_EDGE.value))),
        offset_x_mm=float(payload.get("offset_x_mm", 0.0)),
        offset_y_mm=float(payload.get("offset_y_mm", 0.0)),
        scale=float(payload.get("scale", 1.0)),
        rotation_deg=float(payload.get("rotation_deg", 0.0)),
        inset_mm=float(payload.get("inset_mm", 0.0)),
    )


def _points_2d(raw: object) -> tuple[tuple[float, float], ...]:
    if not isinstance(raw, list | tuple):
        raise ValueError("2D point ring must be a list")
    points = tuple(_point_2d(point) for point in raw)
    if len(points) < 3:
        raise ValueError("2D point ring must contain at least three points")
    return points


def _point_2d(raw: object) -> tuple[float, float]:
    if not isinstance(raw, list | tuple) or len(raw) != 2:
        raise ValueError("2D point must have two numbers")
    return (float(raw[0]), float(raw[1]))


def _point_3d(raw: object) -> tuple[float, float, float]:
    if not isinstance(raw, list | tuple) or len(raw) != 3:
        raise ValueError("3D point must have three numbers")
    return (float(raw[0]), float(raw[1]), float(raw[2]))


def _bounds_min(points: tuple[tuple[float, float], ...]) -> tuple[float, float]:
    return (min(point[0] for point in points), min(point[1] for point in points))


def _bounds_max(points: tuple[tuple[float, float], ...]) -> tuple[float, float]:
    return (max(point[0] for point in points), max(point[1] for point in points))


def _polygon_area(
    outer: tuple[tuple[float, float], ...],
    holes: tuple[tuple[tuple[float, float], ...], ...],
) -> float:
    polygon = sg.Polygon(outer, holes)
    if not polygon.is_valid:
        polygon = polygon.buffer(0)
    return float(polygon.area)
