"""
Lumina Studio - Geometry Utilities
Geometry utilities module - Pure functional geometry calculation tools
"""

import numpy as np
import trimesh

from api.structured_logging import get_logger

log = get_logger(__name__)


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
    circle_radius = half_w
    hole_radius = min(hole_dia_mm / 2, circle_radius * 0.8)
    rect_height = max(0.2, length_mm - circle_radius)
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
    n_outer = len(outer_pts)
    
    # Generate hole points
    n_hole = 32
    hole_pts = []
    for i in range(n_hole):
        angle = 2 * np.pi * i / n_hole
        x = hole_radius * np.cos(angle)
        y = circle_center_y + hole_radius * np.sin(angle)
        hole_pts.append((x, y))
    hole_pts = np.array(hole_pts)
    n_hole_pts = len(hole_pts)
    
    # Build 3D vertices
    vertices = []
    faces = []
    
    # Bottom face outer contour
    for pt in outer_pts:
        vertices.append([pt[0], pt[1], 0])
    
    # Bottom face hole
    for pt in hole_pts:
        vertices.append([pt[0], pt[1], 0])
    
    # Top face outer contour
    for pt in outer_pts:
        vertices.append([pt[0], pt[1], thickness_mm])
    
    # Top face hole
    for pt in hole_pts:
        vertices.append([pt[0], pt[1], thickness_mm])
    
    # Index definitions
    bottom_outer_start = 0
    bottom_hole_start = n_outer
    top_outer_start = n_outer + n_hole_pts
    top_hole_start = n_outer + n_hole_pts + n_outer
    
    # Outer contour side faces
    for i in range(n_outer):
        i_next = (i + 1) % n_outer
        bi = bottom_outer_start + i
        bi_next = bottom_outer_start + i_next
        ti = top_outer_start + i
        ti_next = top_outer_start + i_next
        faces.append([bi, bi_next, ti_next])
        faces.append([bi, ti_next, ti])
    
    # Hole side faces
    for i in range(n_hole_pts):
        i_next = (i + 1) % n_hole_pts
        bi = bottom_hole_start + i
        bi_next = bottom_hole_start + i_next
        ti = top_hole_start + i
        ti_next = top_hole_start + i_next
        faces.append([bi, ti, ti_next])
        faces.append([bi, ti_next, bi_next])
    
    # Connect outer contour and hole (top and bottom faces)
    vertices_arr = np.array(vertices)
    
    bottom_outer_idx = list(range(bottom_outer_start, bottom_outer_start + n_outer))
    bottom_hole_idx = list(range(bottom_hole_start, bottom_hole_start + n_hole_pts))
    bottom_faces = _connect_rings(bottom_outer_idx, bottom_hole_idx, vertices_arr, is_top=False)
    faces.extend(bottom_faces)
    
    top_outer_idx = list(range(top_outer_start, top_outer_start + n_outer))
    top_hole_idx = list(range(top_hole_start, top_hole_start + n_hole_pts))
    top_faces = _connect_rings(top_outer_idx, top_hole_idx, vertices_arr, is_top=True)
    faces.extend(top_faces)
    
    # Build mesh at origin (no translation yet)
    vertices_arr = np.array(vertices)

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
    mesh = trimesh.Trimesh(vertices=vertices_arr, faces=np.array(faces))
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


def _connect_rings(outer_indices, hole_indices, vertices_arr, is_top=True):
    """
    Helper function to connect outer ring and inner ring
    Uses greedy algorithm to generate triangular faces
    
    Args:
        outer_indices: Outer ring vertex index list
        hole_indices: Inner ring vertex index list
        vertices_arr: Vertex array
        is_top: Whether it's the top face
    
    Returns:
        list: Face index list
    """
    ring_faces = []
    n_o = len(outer_indices)
    n_h = len(hole_indices)
    
    oi = 0  # Outer ring pointer
    hi = 0  # Inner ring pointer
    
    def get_2d(idx):
        """Get 2D coordinates of vertex"""
        return np.array([vertices_arr[idx][0], vertices_arr[idx][1]])
    
    total_steps = n_o + n_h
    for _ in range(total_steps):
        o_curr = outer_indices[oi % n_o]
        o_next = outer_indices[(oi + 1) % n_o]
        h_curr = hole_indices[hi % n_h]
        h_next = hole_indices[(hi + 1) % n_h]
        
        # Calculate distance to decide connection direction
        dist_o = np.linalg.norm(get_2d(o_next) - get_2d(h_curr))
        dist_h = np.linalg.norm(get_2d(o_curr) - get_2d(h_next))
        
        if oi >= n_o:
            # Outer ring complete, only connect inner ring
            if is_top:
                ring_faces.append([o_curr, h_next, h_curr])
            else:
                ring_faces.append([o_curr, h_curr, h_next])
            hi += 1
        elif hi >= n_h:
            # Inner ring complete, only connect outer ring
            if is_top:
                ring_faces.append([o_curr, o_next, h_curr])
            else:
                ring_faces.append([o_curr, h_curr, o_next])
            oi += 1
        elif dist_o < dist_h:
            # Connect next point of outer ring
            if is_top:
                ring_faces.append([o_curr, o_next, h_curr])
            else:
                ring_faces.append([o_curr, h_curr, o_next])
            oi += 1
        else:
            # Connect next point of inner ring
            if is_top:
                ring_faces.append([o_curr, h_next, h_curr])
            else:
                ring_faces.append([o_curr, h_curr, h_next])
            hi += 1
    
    return ring_faces
