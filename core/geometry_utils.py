"""
Lumina Studio - Geometry Utilities
Geometry utilities module - Pure functional geometry calculation tools
"""

import numpy as np
from shapely.geometry import Polygon
import trimesh
from trimesh.creation import extrude_polygon

from api.structured_logging import get_logger

log = get_logger(__name__)


def _keychain_loop_profile(
    width_mm: float,
    length_mm: float,
    hole_dia_mm: float,
) -> tuple[float, float, float]:
    """Return (circle_radius, rect_height, hole_radius) for a loop."""
    circle_radius = width_mm / 2
    rect_height = max(0.2, length_mm - circle_radius)
    hole_radius = min(hole_dia_mm / 2, circle_radius * 0.8, rect_height * 0.8)
    return circle_radius, rect_height, hole_radius


def keychain_loop_hole_clearance(
    width_mm: float,
    length_mm: float,
    hole_dia_mm: float,
) -> float:
    """Return the distance from an unrotated loop's bottom edge to its hole.
    返回未旋转挂环底边到挂孔最低点的距离。

    A loop may sink into the model body by at most this depth before the
    hole starts to overlap the body.
    挂环最多可向模型本体内嵌入该深度，超过后挂孔会与本体重叠。

    Args:
        width_mm (float): Loop width in millimeters. (环宽度，毫米)
        length_mm (float): Loop length in millimeters. (环长度，毫米)
        hole_dia_mm (float): Hole diameter in millimeters. (孔径，毫米)

    Returns:
        float: Bottom-to-hole clearance in millimeters. (底边到孔的距离，毫米)
    """
    _circle_radius, rect_height, hole_radius = _keychain_loop_profile(
        width_mm, length_mm, hole_dia_mm
    )
    return max(0.0, rect_height - hole_radius)


def resolve_keychain_contact_anchor_y(
    lowest_top_y: float,
    highest_top_y: float,
    hole_clearance_mm: float,
) -> float:
    """Return the loop bottom Y that keeps a full-width, hole-safe connection.
    返回既保证整段接触、又不让挂孔压入本体的挂环底边 Y。

    The loop bottom drops to the lowest contour point under the contact band,
    so a sloped or curved edge overlaps the loop across the band instead of
    touching one corner. It never drops further than the hole clearance below
    the highest contour point, so the hole stays outside the body.
    挂环底边下沉到接触带下方轮廓的最低点，使斜边或曲边与挂环在整段宽度上
    重叠，而不是只在一个角点相切；但相对轮廓最高点的下沉深度不超过挂孔
    余量，保证挂孔始终在本体之外。

    Args:
        lowest_top_y (float): Lowest top-contour Y inside the band. (接触带内轮廓最低点 Y)
        highest_top_y (float): Highest top-contour Y inside the band. (接触带内轮廓最高点 Y)
        hole_clearance_mm (float): Result of ``keychain_loop_hole_clearance``.
            (``keychain_loop_hole_clearance`` 的结果)

    Returns:
        float: Loop bottom Y before any outward user offset. (未叠加向外偏移的挂环底边 Y)
    """
    return max(lowest_top_y, highest_top_y - max(0.0, hole_clearance_mm))


def create_keychain_loop(
    width_mm: float,
    length_mm: float,
    hole_dia_mm: float,
    thickness_mm: float,
    attach_x_mm: float,
    attach_y_mm: float,
    angle_deg: float = 0.0,
) -> trimesh.Trimesh:
    """Create keychain loop mesh with optional Z-axis rotation.
    创建钥匙扣挂孔网格，支持绕 Z 轴旋转。

    Generates a rectangle + semicircle loop geometry with a circular hole.
    The mesh is first built at the origin, optionally rotated around its
    geometric center, then translated to the attachment point.
    生成矩形+半圆挂孔几何体（含圆孔）。网格先在原点生成，可选绕几何中心
    旋转后，再平移到吸附点。

    Args:
        width_mm (float): Loop width in millimeters. (环宽度，毫米)
        length_mm (float): Loop length in millimeters. (环长度，毫米)
        hole_dia_mm (float): Hole diameter in millimeters. (孔径，毫米)
        thickness_mm (float): Loop thickness in millimeters. (环厚度，毫米)
        attach_x_mm (float): Attachment point X coordinate in millimeters. (吸附点 X 坐标，毫米)
        attach_y_mm (float): Attachment point Y coordinate in millimeters. (吸附点 Y 坐标，毫米)
        angle_deg (float): Rotation angle around Z-axis in degrees, default 0. (绕 Z 轴旋转角度，度，默认 0)

    Returns:
        trimesh.Trimesh: Loop mesh object. (挂孔网格对象)
    """
    log.debug(
        "Creating keychain loop mesh",
        extra={
            "event": "keychain_loop_mesh_started",
            "width_mm": width_mm,
            "length_mm": length_mm,
            "hole_dia_mm": hole_dia_mm,
            "thickness_mm": thickness_mm,
            "attach_x_mm": attach_x_mm,
            "attach_y_mm": attach_y_mm,
            "angle_deg": angle_deg,
        },
    )
    
    # Calculate geometric parameters
    half_w = width_mm / 2
    circle_radius, rect_height, hole_radius = _keychain_loop_profile(
        width_mm, length_mm, hole_dia_mm
    )
    circle_center_y = rect_height
    
    # Generate outer contour points
    n_arc = 32
    outer_pts = []
    
    # Rectangle bottom
    outer_pts.append((-half_w, 0))
    outer_pts.append((half_w, 0))
    outer_pts.append((half_w, rect_height))
    
    # Semicircle top
    for i in range(1, n_arc):
        angle = np.pi * i / n_arc
        x = circle_radius * np.cos(angle)
        y = circle_center_y + circle_radius * np.sin(angle)
        outer_pts.append((x, y))
    
    # Rectangle left side
    outer_pts.append((-half_w, rect_height))
    
    outer_pts = np.array(outer_pts)
    
    # Generate hole points
    n_hole = 32
    hole_pts = []
    for i in range(n_hole):
        angle = 2 * np.pi * i / n_hole
        x = hole_radius * np.cos(angle)
        y = circle_center_y + hole_radius * np.sin(angle)
        hole_pts.append((x, y))
    hole_pts = np.array(hole_pts)
    polygon = Polygon(outer_pts, [hole_pts])
    mesh = extrude_polygon(polygon, thickness_mm, engine="earcut")
    vertices_arr = np.asarray(mesh.vertices, dtype=float).copy()
    faces_arr = np.asarray(mesh.faces, dtype=np.int64).copy()

    # Apply rotation around geometric center if angle is non-zero
    if angle_deg != 0.0:
        # Geometric center of the rectangle+semicircle shape
        # The shape spans x: [-half_w, half_w], y: [0, rect_height + circle_radius]
        center_x = 0.0
        center_y = (rect_height + circle_radius) / 2.0

        angle_rad = np.radians(angle_deg)
        cos_a = np.cos(angle_rad)
        sin_a = np.sin(angle_rad)

        # Translate to center, rotate, translate back (vectorized)
        dx = vertices_arr[:, 0] - center_x
        dy = vertices_arr[:, 1] - center_y
        vertices_arr[:, 0] = cos_a * dx - sin_a * dy + center_x
        vertices_arr[:, 1] = sin_a * dx + cos_a * dy + center_y

    # Apply position offset (translate to attach point)
    vertices_arr[:, 0] += attach_x_mm
    vertices_arr[:, 1] += attach_y_mm
    
    # Create mesh
    mesh = trimesh.Trimesh(vertices=vertices_arr, faces=faces_arr)
    mesh.fix_normals()
    
    log.debug(
        "Keychain loop mesh created",
        extra={
            "event": "keychain_loop_mesh_created",
            "vertex_count": len(mesh.vertices),
            "face_count": len(mesh.faces),
        },
    )
    
    return mesh
