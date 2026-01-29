"""
Lumina Studio - Calibration Generator Module
校准板生成模块
"""

import os
import tempfile
from typing import Optional, List, Tuple, Generator

import numpy as np
import trimesh
from PIL import Image

from config import PrinterConfig, ThinModeConfig, ColorSystem
from utils import Stats, safe_fix_3mf_names


# ═══════════════════════════════════════════════════════════════════════════════
# 341 Sequence Generator for W+CMYK Mode
# ═══════════════════════════════════════════════════════════════════════════════

def generate_341_sequences() -> List[List[int]]:
    """
    Generate 341 color sequences for W+CMYK mode.
    
    Sequences are variable length (0-4 layers):
    - L=0: [] (empty, just white base) -> 1 sequence
    - L=1: [C], [M], [Y], [K] -> 4 sequences  
    - L=2: [C,C], [C,M], ..., [K,K] -> 16 sequences
    - L=3: [C,C,C], ..., [K,K,K] -> 64 sequences
    - L=4: [C,C,C,C], ..., [K,K,K,K] -> 256 sequences
    
    Total: 1 + 4 + 16 + 64 + 256 = 341
    
    Material indices: C=0, M=1, Y=2, K=3 (for color layers)
    In the final 3MF: White=0, C=1, M=2, Y=3, K=4
    
    Returns:
        List of sequences, each sequence is a list of material indices (0-3)
    """
    sequences = []
    
    # L=0: empty sequence (just white base)
    sequences.append([])
    
    # L=1 to L=4
    for length in range(1, 5):
        # Generate all 4^length combinations
        for i in range(4 ** length):
            seq = []
            temp = i
            for _ in range(length):
                seq.append(temp % 4)
                temp //= 4
            sequences.append(seq[::-1])  # Reverse to get MSB first
    
    return sequences


def get_sequence_by_id(seq_id: int) -> List[int]:
    """Get a specific sequence by its ID (0-340)."""
    if seq_id == 0:
        return []
    
    # Calculate which length group and offset within that group
    remaining = seq_id - 1
    for length in range(1, 5):
        group_size = 4 ** length
        if remaining < group_size:
            # Generate this specific sequence
            seq = []
            temp = remaining
            for _ in range(length):
                seq.append(temp % 4)
                temp //= 4
            return seq[::-1]
        remaining -= group_size
    
    return []


def sequence_id_from_sequence(seq: List[int]) -> int:
    """Convert a sequence back to its ID."""
    if len(seq) == 0:
        return 0
    
    # Calculate offset for this length group
    offset = sum(4 ** l for l in range(len(seq)))  # 1 + 4 + 16 + ... before this length
    
    # Calculate position within the group
    position = 0
    for i, val in enumerate(seq):
        position = position * 4 + val
    
    return offset + position


def _generate_voxel_mesh(voxel_matrix: np.ndarray, material_index: int,
                          grid_h: int, grid_w: int) -> Optional[trimesh.Trimesh]:
    """Generate mesh for a specific material from voxel data."""
    scale_x = PrinterConfig.NOZZLE_WIDTH
    scale_y = PrinterConfig.NOZZLE_WIDTH
    scale_z = PrinterConfig.LAYER_HEIGHT
    shrink = PrinterConfig.SHRINK_OFFSET

    vertices, faces = [], []
    total_z_layers = voxel_matrix.shape[0]

    for z in range(total_z_layers):
        z_bottom, z_top = z * scale_z, (z + 1) * scale_z
        layer_mask = (voxel_matrix[z] == material_index)
        if not np.any(layer_mask):
            continue

        for y in range(grid_h):
            world_y = y * scale_y
            row = layer_mask[y]
            padded_row = np.pad(row, (1, 1), mode='constant')
            diff = np.diff(padded_row.astype(int))
            starts, ends = np.where(diff == 1)[0], np.where(diff == -1)[0]

            for start, end in zip(starts, ends):
                x0, x1 = start * scale_x + shrink, end * scale_x - shrink
                y0, y1 = world_y + shrink, world_y + scale_y - shrink

                base_idx = len(vertices)
                vertices.extend([
                    [x0, y0, z_bottom], [x1, y0, z_bottom], [x1, y1, z_bottom], [x0, y1, z_bottom],
                    [x0, y0, z_top], [x1, y0, z_top], [x1, y1, z_top], [x0, y1, z_top]
                ])
                cube_faces = [
                    [0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7],
                    [0, 1, 5], [0, 5, 4], [1, 2, 6], [1, 6, 5],
                    [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7]
                ]
                faces.extend([[v + base_idx for v in f] for f in cube_faces])

    if not vertices:
        return None

    mesh = trimesh.Trimesh(vertices=vertices, faces=faces)
    mesh.merge_vertices()
    mesh.update_faces(mesh.unique_faces())
    return mesh


def _generate_stepped_color_mesh(height_map: np.ndarray, color_layers: np.ndarray,
                                  material_index: int, block_size_mm: float,
                                  gap_mm: float, base_height_mm: float,
                                  grid_h: int, grid_w: int) -> Optional[trimesh.Trimesh]:
    """
    Generate stepped-height mesh for a specific material in 341 mode.
    
    Each color block has variable height (0-4 layers of 0.08mm).
    The mesh surface will show staircase-like height variations.
    
    Args:
        height_map: (grid_h, grid_w) array of layer counts per block (0-4)
        color_layers: (max_layers, grid_h, grid_w) array of material indices
        material_index: The material to generate mesh for (1-4: C,M,Y,K)
        block_size_mm: Size of each color block in mm
        gap_mm: Gap between blocks in mm
        base_height_mm: Height of the white base in mm
        grid_h, grid_w: Grid dimensions
    
    Returns:
        Trimesh for this material, or None if no voxels
    """
    layer_height = PrinterConfig.LAYER_HEIGHT
    shrink = PrinterConfig.SHRINK_OFFSET
    
    vertices, faces = [], []
    
    # Iterate through each block
    for py in range(grid_h):
        for px in range(grid_w):
            block_height = int(height_map[py, px])
            if block_height == 0:
                continue
            
            # Calculate block position
            block_x = px * (block_size_mm + gap_mm)
            block_y = py * (block_size_mm + gap_mm)
            
            # Check each layer in this block
            for layer_idx in range(block_height):
                if color_layers[layer_idx, py, px] != material_index:
                    continue
                
                # Calculate Z position (on top of base)
                z_bottom = base_height_mm + layer_idx * layer_height
                z_top = z_bottom + layer_height
                
                # Block corners with shrink
                x0, x1 = block_x + shrink, block_x + block_size_mm - shrink
                y0, y1 = block_y + shrink, block_y + block_size_mm - shrink
                
                # Add cube vertices
                base_idx = len(vertices)
                vertices.extend([
                    [x0, y0, z_bottom], [x1, y0, z_bottom], [x1, y1, z_bottom], [x0, y1, z_bottom],
                    [x0, y0, z_top], [x1, y0, z_top], [x1, y1, z_top], [x0, y1, z_top]
                ])
                
                cube_faces = [
                    [0, 2, 1], [0, 3, 2],  # bottom
                    [4, 5, 6], [4, 6, 7],  # top
                    [0, 1, 5], [0, 5, 4],  # front
                    [1, 2, 6], [1, 6, 5],  # right
                    [2, 3, 7], [2, 7, 6],  # back
                    [3, 0, 4], [3, 4, 7]   # left
                ]
                faces.extend([[v + base_idx for v in f] for f in cube_faces])
    
    if not vertices:
        return None
    
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces)
    mesh.merge_vertices()
    mesh.update_faces(mesh.unique_faces())
    return mesh


def _generate_white_base_mesh(block_size_mm: float, gap_mm: float, 
                               base_height_mm: float, grid_h: int, grid_w: int,
                               padding: int = 1) -> trimesh.Trimesh:
    """
    Generate solid white base mesh for 341 mode.
    
    The base is a single solid block covering the entire calibration board.
    """
    shrink = PrinterConfig.SHRINK_OFFSET
    
    total_w = (grid_w + padding * 2)
    total_h = (grid_h + padding * 2)
    
    # Calculate total dimensions
    total_width = total_w * (block_size_mm + gap_mm) - gap_mm
    total_height = total_h * (block_size_mm + gap_mm) - gap_mm
    
    # Create base box
    x0, x1 = shrink, total_width - shrink
    y0, y1 = shrink, total_height - shrink
    z0, z1 = 0, base_height_mm
    
    vertices = [
        [x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0],
        [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]
    ]
    
    faces = [
        [0, 2, 1], [0, 3, 2],  # bottom
        [4, 5, 6], [4, 6, 7],  # top
        [0, 1, 5], [0, 5, 4],  # front
        [1, 2, 6], [1, 6, 5],  # right
        [2, 3, 7], [2, 7, 6],  # back
        [3, 0, 4], [3, 4, 7]   # left
    ]
    
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces)
    return mesh


def generate_calibration_board(color_mode: str, block_size_mm: float,
                                gap_mm: float, backing_color: str):
    """Generate calibration board as 3MF. Dispatches to appropriate mode."""
    
    # Check if this is 341 mode
    if ColorSystem.is_thin_mode(color_mode):
        return generate_calibration_board_341(color_mode, block_size_mm, gap_mm)
    else:
        return generate_calibration_board_1024(color_mode, block_size_mm, gap_mm, backing_color)


def generate_calibration_board_1024(color_mode: str, block_size_mm: float,
                                     gap_mm: float, backing_color: str):
    """Generate a 1024-color calibration board as 3MF (original mode)."""

    color_conf = ColorSystem.get(color_mode)
    slot_names = color_conf['slots']
    preview_colors = color_conf['preview']
    color_map = color_conf['map']

    backing_id = color_map.get(backing_color, 0)

    # Grid setup
    grid_dim, padding = 32, 1
    total_w = total_h = grid_dim + (padding * 2)

    pixels_per_block = max(1, int(block_size_mm / PrinterConfig.NOZZLE_WIDTH))
    pixels_gap = max(1, int(gap_mm / PrinterConfig.NOZZLE_WIDTH))

    voxel_w = total_w * (pixels_per_block + pixels_gap)
    voxel_h = total_h * (pixels_per_block + pixels_gap)

    backing_layers = int(PrinterConfig.BACKING_MM / PrinterConfig.LAYER_HEIGHT)
    total_layers = PrinterConfig.COLOR_LAYERS + backing_layers

    full_matrix = np.full((total_layers, voxel_h, voxel_w), backing_id, dtype=int)

    # Generate 1024 permutations
    for i in range(1024):
        digits = []
        temp = i
        for _ in range(5):
            digits.append(temp % 4)
            temp //= 4
        stack = digits[::-1]

        row = (i // grid_dim) + padding
        col = (i % grid_dim) + padding
        px = col * (pixels_per_block + pixels_gap)
        py = row * (pixels_per_block + pixels_gap)

        for z in range(PrinterConfig.COLOR_LAYERS):
            full_matrix[z, py:py+pixels_per_block, px:px+pixels_per_block] = stack[z]

    # Corner markers - 根据模式设置不同的角点颜色
    # 角点位置: (row, col, mat_id)
    # row=0是顶部, row=total_h-1是底部
    # col=0是左边, col=total_w-1是右边
    if "RYBW" in color_mode:
        # RYBW: slots = [White(0), Red(1), Yellow(2), Blue(3)]
        # corner_labels: TL=White, TR=Red, BR=Blue, BL=Yellow
        corners = [
            (0, 0, 0),              # TL = White
            (0, total_w-1, 1),      # TR = Red
            (total_h-1, total_w-1, 3),  # BR = Blue
            (total_h-1, 0, 2)       # BL = Yellow
        ]
    else:
        # CMYW: slots = [White(0), Cyan(1), Magenta(2), Yellow(3)]
        # corner_labels: TL=White, TR=Cyan, BR=Magenta, BL=Yellow
        corners = [
            (0, 0, 0),              # TL = White
            (0, total_w-1, 1),      # TR = Cyan
            (total_h-1, total_w-1, 2),  # BR = Magenta
            (total_h-1, 0, 3)       # BL = Yellow
        ]

    for r, c, mat_id in corners:
        px = c * (pixels_per_block + pixels_gap)
        py = r * (pixels_per_block + pixels_gap)
        for z in range(PrinterConfig.COLOR_LAYERS):
            full_matrix[z, py:py+pixels_per_block, px:px+pixels_per_block] = mat_id

    # Build 3MF
    scene = trimesh.Scene()
    for mat_id in range(4):
        mesh = _generate_voxel_mesh(full_matrix, mat_id, voxel_h, voxel_w)
        if mesh:
            mesh.visual.face_colors = preview_colors[mat_id]
            name = slot_names[mat_id]
            # Set multiple name attributes to increase compatibility
            mesh.metadata['name'] = name
            scene.add_geometry(mesh, node_name=name, geom_name=name)

    # Export
    mode_tag = color_conf['name']
    output_path = os.path.join(tempfile.gettempdir(), f"Lumina_Calibration_{mode_tag}.3mf")
    scene.export(output_path)

    # Fix object names in 3MF for better slicer compatibility
    safe_fix_3mf_names(output_path, slot_names)

    # Preview
    bottom_layer = full_matrix[0].astype(np.uint8)
    preview_arr = np.zeros((voxel_h, voxel_w, 3), dtype=np.uint8)
    for mat_id, rgba in preview_colors.items():
        preview_arr[bottom_layer == mat_id] = rgba[:3]

    Stats.increment("calibrations")

    return output_path, Image.fromarray(preview_arr), f"✅ 校准板已生成！已组合为一个对象 | 颜色: {', '.join(slot_names)}"


def generate_calibration_board_341(color_mode: str, block_size_mm: float, gap_mm: float):
    """
    Generate a 341-color calibration board for W+CMYK mode.
    
    This mode uses:
    - Fixed 1.0mm white base
    - Variable height (0-4 layers) color stacks
    - 5 materials: White (base), Cyan, Magenta, Yellow, Black
    - 19x18 data grid + corner markers
    """
    color_conf = ColorSystem.get(color_mode)
    slot_names = color_conf['slots']  # ["White", "Cyan", "Magenta", "Yellow", "Black"]
    preview_colors = color_conf['preview']
    
    # Grid parameters
    grid_w = ThinModeConfig.GRID_W  # 19
    grid_h = ThinModeConfig.GRID_H  # 18
    padding = 1
    total_w = grid_w + (padding * 2)  # 21
    total_h = grid_h + (padding * 2)  # 20
    
    base_height_mm = ThinModeConfig.BASE_MM  # 1.0mm
    max_layers = ThinModeConfig.MAX_LAYERS  # 4
    
    # Generate 341 sequences
    sequences = generate_341_sequences()
    print(f"[CALIBRATION 341] Generated {len(sequences)} sequences")
    
    # Create height map and color layer matrices
    # height_map[y, x] = number of color layers (0-4)
    # color_layers[layer, y, x] = material index (0-3 for C,M,Y,K)
    height_map = np.zeros((total_h, total_w), dtype=np.int32)
    color_layers = np.full((max_layers, total_h, total_w), -1, dtype=np.int32)
    
    # Fill data grid (19x18 = 342, but we only have 341 sequences)
    for i, seq in enumerate(sequences):
        if i >= grid_w * grid_h:
            break
        
        row = (i // grid_w) + padding
        col = (i % grid_w) + padding
        
        seq_len = len(seq)
        height_map[row, col] = seq_len
        
        for layer_idx, mat_id in enumerate(seq):
            color_layers[layer_idx, row, col] = mat_id
    
    # Corner markers (in padding area)
    # Use solid 4-layer stacks for visibility
    # TL=White (just base, no color), TR=Cyan, BR=Magenta, BL=Yellow
    corner_configs = [
        (0, 0, []),              # TL = White (no color layers)
        (0, total_w-1, [0, 0, 0, 0]),  # TR = Cyan (4 layers)
        (total_h-1, total_w-1, [1, 1, 1, 1]),  # BR = Magenta (4 layers)
        (total_h-1, 0, [2, 2, 2, 2])   # BL = Yellow (4 layers)
    ]
    
    for r, c, seq in corner_configs:
        height_map[r, c] = len(seq)
        for layer_idx, mat_id in enumerate(seq):
            color_layers[layer_idx, r, c] = mat_id
    
    # Build 3MF scene
    scene = trimesh.Scene()
    
    # 1. Generate white base (covers entire board)
    base_mesh = _generate_white_base_mesh(
        block_size_mm, gap_mm, base_height_mm, grid_h, grid_w, padding
    )
    base_mesh.visual.face_colors = preview_colors[0]  # White
    base_mesh.metadata['name'] = slot_names[0]
    scene.add_geometry(base_mesh, node_name=slot_names[0], geom_name=slot_names[0])
    print(f"[CALIBRATION 341] Added White base mesh")
    
    # 2. Generate color layer meshes (C, M, Y, K)
    for mat_id in range(4):
        mesh = _generate_stepped_color_mesh(
            height_map, color_layers, mat_id,
            block_size_mm, gap_mm, base_height_mm,
            total_h, total_w
        )
        if mesh:
            mesh.visual.face_colors = preview_colors[mat_id + 1]  # +1 because White is 0
            name = slot_names[mat_id + 1]
            mesh.metadata['name'] = name
            scene.add_geometry(mesh, node_name=name, geom_name=name)
            print(f"[CALIBRATION 341] Added {name} mesh")
    
    # Export
    output_path = os.path.join(tempfile.gettempdir(), "Lumina_Calibration_CMYK_W_341.3mf")
    scene.export(output_path)
    
    # Fix object names
    safe_fix_3mf_names(output_path, slot_names)
    
    # Generate preview image
    preview_w = total_w * 20
    preview_h = total_h * 20
    preview_arr = np.full((preview_h, preview_w, 3), 255, dtype=np.uint8)  # White background
    
    for py in range(total_h):
        for px in range(total_w):
            block_x = px * 20
            block_y = py * 20
            
            seq_len = height_map[py, px]
            if seq_len == 0:
                # White (base only)
                preview_arr[block_y:block_y+18, block_x:block_x+18] = preview_colors[0][:3]
            else:
                # Get top layer color
                top_mat = color_layers[seq_len - 1, py, px]
                if top_mat >= 0:
                    color = preview_colors[top_mat + 1][:3]
                    preview_arr[block_y:block_y+18, block_x:block_x+18] = color
    
    Stats.increment("calibrations")
    
    return (
        output_path, 
        Image.fromarray(preview_arr), 
        f"✅ W+CMYK 校准板已生成！341色块 (19×18) | 材质: {', '.join(slot_names)}"
    )
