"""
Lumina Studio - Calibration Generator Module

Generates calibration boards for physical color testing.
"""

from __future__ import annotations

import json
import os
import logging
import math
from typing import Optional
import itertools
import zipfile

import numpy as np
from PIL import Image

# Lazy trimesh import: avoid >60s startup cost when imported via API.
_trimesh = None


def _get_trimesh():
    global _trimesh
    if _trimesh is None:
        import trimesh as _tm

        _trimesh = _tm
    return _trimesh


from colormath.color_objects import sRGBColor, LabColor
from colormath.color_conversions import convert_color
from colormath.color_diff import delta_e_cie2000

from config import PrinterConfig, ColorSystem, SmartConfig, MODELS_DIR, get_asset_path
from core.lut_card_layout import (
    EIGHT_COLOR_PAGE_CAPACITY,
    cell_for_row_index,
    localize_page_layout,
    resolve_extraction_page_layout,
    resolve_lut_layout,
)
from core.naming import generate_calibration_filename
from utils import Stats
from utils.bambu_3mf_writer import export_scene_with_bambu_metadata

_log = logging.getLogger(__name__)
CALIBRATION_HANDLED_ERRORS = (
    ValueError,
    TypeError,
    OSError,
    RuntimeError,
)
EIGHT_COLOR_DATA_DIM = 37
EIGHT_COLOR_PADDING = 1
EIGHT_COLOR_TOTAL_DIM = 39


def _generate_voxel_mesh(
    voxel_matrix: np.ndarray, material_index: int, grid_h: int, grid_w: int
) -> Optional[_get_trimesh().Trimesh]:
    """
    Generate mesh for a specific material from voxel data.

    Args:
        voxel_matrix: 3D array of material indices (Z, H, W)
        material_index: Material ID to generate mesh for
        grid_h: Grid height in voxels
        grid_w: Grid width in voxels

    Returns:
        Trimesh object or None if no voxels found
    """
    scale_x = PrinterConfig.NOZZLE_WIDTH
    scale_y = PrinterConfig.NOZZLE_WIDTH
    scale_z = PrinterConfig.LAYER_HEIGHT
    shrink = PrinterConfig.SHRINK_OFFSET

    vertices, faces = [], []
    total_z_layers = voxel_matrix.shape[0]

    for z in range(total_z_layers):
        z_bottom, z_top = z * scale_z, (z + 1) * scale_z
        layer_mask = voxel_matrix[z] == material_index
        if not np.any(layer_mask):
            continue

        for y in range(grid_h):
            world_y = y * scale_y
            row = layer_mask[y]
            padded_row = np.pad(row, (1, 1), mode="constant")
            diff = np.diff(padded_row.astype(int))
            starts, ends = np.where(diff == 1)[0], np.where(diff == -1)[0]

            for start, end in zip(starts, ends):
                x0, x1 = start * scale_x + shrink, end * scale_x - shrink
                y0, y1 = world_y + shrink, world_y + scale_y - shrink

                base_idx = len(vertices)
                vertices.extend(
                    [
                        [x0, y0, z_bottom],
                        [x1, y0, z_bottom],
                        [x1, y1, z_bottom],
                        [x0, y1, z_bottom],
                        [x0, y0, z_top],
                        [x1, y0, z_top],
                        [x1, y1, z_top],
                        [x0, y1, z_top],
                    ]
                )
                cube_faces = [
                    [0, 2, 1],
                    [0, 3, 2],
                    [4, 5, 6],
                    [4, 6, 7],
                    [0, 1, 5],
                    [0, 5, 4],
                    [1, 2, 6],
                    [1, 6, 5],
                    [2, 3, 7],
                    [2, 7, 6],
                    [3, 0, 4],
                    [3, 4, 7],
                ]
                faces.extend([[v + base_idx for v in f] for f in cube_faces])

    if not vertices:
        return None

    mesh = _get_trimesh().Trimesh(vertices=vertices, faces=faces)
    mesh.merge_vertices()
    mesh.update_faces(mesh.unique_faces())
    return mesh


def generate_calibration_board(color_mode: str, block_size_mm: float, gap_mm: float, backing_color: str):
    """
    Generate a 1024-color calibration board as 3MF.

    Args:
        color_mode: Color system mode (CMYW/RYBW)
        block_size_mm: Size of each color block in mm
        gap_mm: Gap between blocks in mm
        backing_color: Color name for backing layer

    Returns:
        Tuple of (output_path, preview_image, status_message)
    """
    color_conf = ColorSystem.get(color_mode)
    slot_names = color_conf["slots"]
    preview_colors = color_conf["preview"]
    color_map = color_conf["map"]

    backing_id = color_map.get(backing_color, 0)

    layout = resolve_lut_layout(color_mode, 1024)
    page = layout.pages[0]
    total_w = page.physical_cols
    total_h = page.physical_rows

    pixels_per_block = max(1, int(block_size_mm / PrinterConfig.NOZZLE_WIDTH))
    pixels_gap = max(1, int(gap_mm / PrinterConfig.NOZZLE_WIDTH))

    voxel_w = total_w * (pixels_per_block + pixels_gap)
    voxel_h = total_h * (pixels_per_block + pixels_gap)

    backing_layers = int(PrinterConfig.BACKING_MM / PrinterConfig.LAYER_HEIGHT)
    total_layers = PrinterConfig.COLOR_LAYERS + backing_layers

    full_matrix = np.full((total_layers, voxel_h, voxel_w), backing_id, dtype=int)

    # Generate 1024 permutations (4^5 combinations)
    for i in range(1024):
        digits = []
        temp = i
        for _ in range(5):
            digits.append(temp % 4)
            temp //= 4
        stack = digits[::-1]

        cell = cell_for_row_index(layout, i)
        row = cell.physical_row
        col = cell.physical_col
        px = col * (pixels_per_block + pixels_gap)
        py = row * (pixels_per_block + pixels_gap)

        for z in range(PrinterConfig.COLOR_LAYERS):
            full_matrix[z, py : py + pixels_per_block, px : px + pixels_per_block] = stack[z]

    # Set corner markers with mode-specific colors
    if "RYBW" in color_mode:
        corners = [
            (0, 0, 0),  # TL = White
            (0, total_w - 1, 1),  # TR = Red
            (total_h - 1, total_w - 1, 3),  # BR = Blue
            (total_h - 1, 0, 2),  # BL = Yellow
        ]
    else:  # CMYW
        corners = [
            (0, 0, 0),  # TL = White
            (0, total_w - 1, 1),  # TR = Cyan
            (total_h - 1, total_w - 1, 2),  # BR = Magenta
            (total_h - 1, 0, 3),  # BL = Yellow
        ]

    for r, c, mat_id in corners:
        px = c * (pixels_per_block + pixels_gap)
        py = r * (pixels_per_block + pixels_gap)
        for z in range(PrinterConfig.COLOR_LAYERS):
            full_matrix[z, py : py + pixels_per_block, px : px + pixels_per_block] = mat_id

    # Build 3MF scene
    scene = _get_trimesh().Scene()
    for mat_id in range(4):
        mesh = _generate_voxel_mesh(full_matrix, mat_id, voxel_h, voxel_w)
        if mesh:
            mesh.visual.face_colors = preview_colors[mat_id]
            name = slot_names[mat_id]
            mesh.metadata["name"] = name
            scene.add_geometry(mesh, node_name=name, geom_name=name)

    # Export with BambuStudio metadata
    output_path = os.path.join(MODELS_DIR, generate_calibration_filename(color_mode, "Standard"))

    export_scene_with_bambu_metadata(
        scene=scene,
        output_path=output_path,
        slot_names=slot_names,
        preview_colors=preview_colors,
        settings={
            "layer_height": "0.08",
            "initial_layer_height": "0.08",
            "wall_loops": "1",
            "top_shell_layers": "0",
            "bottom_shell_layers": "0",
            "sparse_infill_density": "100%",
            "sparse_infill_pattern": "zig-zag",
        },
        color_mode=color_mode,
    )

    # Generate preview
    bottom_layer = full_matrix[0].astype(np.uint8)
    preview_arr = np.zeros((voxel_h, voxel_w, 3), dtype=np.uint8)
    for mat_id, rgba in preview_colors.items():
        preview_arr[bottom_layer == mat_id] = rgba[:3]

    Stats.increment("calibrations")

    return (
        output_path,
        Image.fromarray(preview_arr),
        f"[OK] 校准板已生成！已组合为一个对象 | 颜色: {', '.join(slot_names)}",
    )


# ========== Lumina Smart 1296 (6-Color System) ==========


def get_top_1296_colors():
    """
    Intelligent color selection algorithm for 6-color system.

    Returns 1296 most representative color combinations from 7776 possible
    combinations (6^5) to fill a 36x36 grid without gaps.

    This function is public and can be called by image_processing.py to
    reconstruct the stacking order.

    Returns:
        List of 1296 tuples, each representing a 5-layer color stack
    """
    _log.info(
        "Simulating Smart 1296 color combinations",
        extra={"event": "smart1296_combinations_started", "combination_count": 7776},
    )

    # Simulate all combinations in Lab color space
    candidates = []
    filaments = SmartConfig.FILAMENTS
    layer_h = PrinterConfig.LAYER_HEIGHT
    backing = np.array([255, 255, 255])

    # Pre-calculate single layer alpha values
    alphas = {}
    for fid, props in filaments.items():
        bd = props["td"] / 10.0
        alphas[fid] = min(1.0, layer_h / bd) if bd > 0 else 1.0

    # Generate all 6^5 combinations
    for stack in itertools.product(range(6), repeat=5):
        # Fast color mixing simulation
        curr = backing.astype(float)
        for fid in stack:
            rgb = np.array(filaments[fid]["rgb"])
            a = alphas[fid]
            curr = rgb * a + curr * (1.0 - a)

        final_rgb = curr.astype(np.uint8)

        candidates.append({"stack": stack, "rgb": final_rgb})

    _log.info(
        "Smart 1296 candidates generated; filtering top colors",
        extra={"event": "smart1296_candidates_generated", "candidate_count": len(candidates), "target_count": 1296},
    )

    # Greedy selection algorithm
    selected = []

    # Pre-select seed colors (6 pure colors)
    for i in range(6):
        stack = (i,) * 5
        for c in candidates:
            if c["stack"] == stack:
                selected.append(c)
                break

    _log.info(
        "Smart 1296 seed colors selected",
        extra={"event": "smart1296_seed_colors_selected", "selected_count": len(selected)},
    )

    # Round 1: High quality selection (RGB distance > 8)
    target = 1296
    for c in candidates:
        if len(selected) >= target:
            break
        if any(c["stack"] == s["stack"] for s in selected):
            continue

        is_distinct = True
        for s in selected:
            if np.linalg.norm(c["rgb"].astype(int) - s["rgb"].astype(int)) < 8:
                is_distinct = False
                break

        if is_distinct:
            selected.append(c)

    _log.info(
        "Smart 1296 high-quality selection completed",
        extra={"event": "smart1296_high_quality_selection_done", "selected_count": len(selected)},
    )

    # Round 2: Fill remaining slots with lower threshold
    if len(selected) < target:
        _log.info(
            "Filling remaining Smart 1296 color slots",
            extra={"event": "smart1296_remaining_slots_filled", "remaining_count": target - len(selected)},
        )
        for c in candidates:
            if len(selected) >= target:
                break
            if any(c["stack"] == s["stack"] for s in selected):
                continue
            selected.append(c)

    _log.info(
        "Smart 1296 color selection completed",
        extra={"event": "smart1296_selection_done", "selected_count": len(selected)},
    )

    return [s["stack"] for s in selected[:target]]


def generate_smart_board(
    block_size_mm=5.0,
    gap_mm=0.8,
    *,
    color_conf=None,
    corner_colors=None,
):
    """Generate Lumina Smart 1296 (6-Color) calibration board with 38x38 border layout.
    生成 Lumina Smart 1296（6色）校准板（38×38 边框布局）。

    Features:
    - 38x38 physical grid (36x36 data + 2 border protection)
    - 1296 intelligently selected color blocks
    - Corner alignment markers in outermost ring
    - Face Down printing optimization

    Args:
        block_size_mm: Size of each color block in mm. (色块边长，mm)
        gap_mm: Gap between blocks in mm. (色块间距，mm)
        color_conf: ColorSystem dict override (default: SIX_COLOR/CMYW).
                    (颜色系统配置覆盖，默认 SIX_COLOR/CMYW)
        corner_colors: Tuple of 4 material IDs for TL/TR/BR/BL corner markers
                       (default: CMYW → (0, 1, 2, 4)).
                       (四角标记的材料 ID，默认 CMYW 方案)

    Returns:
        Tuple of (output_path, preview_image, status_message)
    """
    _log.info(
        "Generating Smart 1296 calibration board",
        extra={"event": "smart1296_board_generation_started", "grid": "38x38"},
    )

    # Get 1296 intelligently selected colors
    stacks = get_top_1296_colors()

    layout = resolve_lut_layout(color_conf.get("name", "6-Color") if color_conf else "6-Color", 1296)
    page = layout.pages[0]
    total_dim = page.physical_rows
    block_w = float(block_size_mm)
    gap = float(gap_mm)
    margin = 5.0

    # Calculate board dimensions (based on 38x38)
    board_w = margin * 2 + total_dim * block_w + (total_dim - 1) * gap
    board_h = board_w

    _log.info(
        "Smart 1296 calibration board size resolved",
        extra={
            "event": "smart1296_board_size_resolved",
            "board_width_mm": round(board_w, 3),
            "board_height_mm": round(board_h, 3),
            "grid": f"{total_dim}x{total_dim}",
        },
    )

    # Get color configuration (caller may override for RYBW variant)
    if color_conf is None:
        color_conf = ColorSystem.SIX_COLOR
    preview_colors = color_conf["preview"]
    slot_names = color_conf["slots"]

    # Calculate voxel grid dimensions (based on 38x38)
    pixels_per_block = max(1, int(block_w / PrinterConfig.NOZZLE_WIDTH))
    pixels_gap = max(1, int(gap / PrinterConfig.NOZZLE_WIDTH))

    voxel_w = total_dim * (pixels_per_block + pixels_gap)
    voxel_h = total_dim * (pixels_per_block + pixels_gap)

    # Layer configuration
    color_layers = 5
    backing_layers = int(PrinterConfig.BACKING_MM / PrinterConfig.LAYER_HEIGHT)
    total_layers = color_layers + backing_layers

    # Initialize voxel matrix (filled with White Slot 0)
    full_matrix = np.full((total_layers, voxel_h, voxel_w), 0, dtype=int)

    _log.info(
        "Smart 1296 voxel matrix initialized",
        extra={
            "event": "smart1296_voxel_matrix_initialized",
            "layer_count": total_layers,
            "height_px": voxel_h,
            "width_px": voxel_w,
        },
    )

    # 约定转换：get_top_1296_colors() 返回底到顶约定 (stack[0]=背面，stack[4]=观赏面)
    # 转换为顶到底约定 (stack[0]=观赏面，stack[4]=背面)，与 4 色模式统一
    stacks = [tuple(reversed(s)) for s in stacks]

    # Fill 1296 intelligent color blocks (with padding offset)
    for idx, stack in enumerate(stacks):
        cell = cell_for_row_index(layout, idx)
        row = cell.physical_row
        col = cell.physical_col

        px = col * (pixels_per_block + pixels_gap)
        py = row * (pixels_per_block + pixels_gap)

        # Fill 5 color layers (直接映射，与 4 色模式一致)
        # Z=0 (physical first layer) = viewing surface = stack[0] (顶到底约定)
        # Z=4 (physical fifth layer) = internal layer = stack[4] (顶到底约定)
        for z in range(color_layers):
            mat_id = stack[z]
            full_matrix[z, py : py + pixels_per_block, px : px + pixels_per_block] = mat_id

    # Set corner alignment markers (in outermost ring 0 and 37)
    # Default CMYW: TL=White(0), TR=Cyan(1), BR=Magenta(2), BL=Yellow(4)
    # RYBW variant: TL=White(0), TR=Red(1), BR=Blue(3), BL=Yellow(2)
    if corner_colors is None:
        corner_colors = (0, 1, 2, 4)  # CMYW default
    tl, tr, br, bl = corner_colors
    corners = [
        (0, 0, tl),
        (0, total_dim - 1, tr),
        (total_dim - 1, total_dim - 1, br),
        (total_dim - 1, 0, bl),
    ]

    # Set corner alignment markers (in outermost ring)
    # TL: White (0), TR: Cyan (1), BR: Magenta (2), BL: Yellow (4)
    # Place markers on viewing surface (Z=0) for visual identification after printing
    # Face-Down mode: viewing surface is at Z=0 (first printed layer)
    viewing_surface_z = 0  # Z index of viewing surface (first printed layer in Face-Down mode)
    for r, c, mat_id in corners:
        px = c * (pixels_per_block + pixels_gap)
        py = r * (pixels_per_block + pixels_gap)
        full_matrix[viewing_surface_z, py : py + pixels_per_block, px : px + pixels_per_block] = mat_id

    # Generate 3MF scene
    scene = _get_trimesh().Scene()

    for mat_id in range(6):
        mesh = _generate_voxel_mesh(full_matrix, mat_id, voxel_h, voxel_w)
        if mesh:
            mesh.visual.face_colors = preview_colors[mat_id]
            name = slot_names[mat_id]
            mesh.metadata["name"] = name
            scene.add_geometry(mesh, node_name=name, geom_name=name)

    # Export — derive color_mode label from config name
    color_mode_label = color_conf.get("name", "6-Color")
    output_path = os.path.join(MODELS_DIR, generate_calibration_filename(color_mode_label, "Smart1296"))
    export_scene_with_bambu_metadata(
        scene=scene,
        output_path=output_path,
        slot_names=slot_names,
        preview_colors=preview_colors,
        settings={
            "layer_height": "0.08",
            "initial_layer_height": "0.08",
            "wall_loops": "1",
            "top_shell_layers": "0",
            "bottom_shell_layers": "0",
            "sparse_infill_density": "100%",
            "sparse_infill_pattern": "zig-zag",
        },
        color_mode=color_mode_label,
    )

    # Generate preview image
    bottom_layer = full_matrix[0].astype(np.uint8)
    preview_arr = np.zeros((voxel_h, voxel_w, 3), dtype=np.uint8)
    for mat_id, rgba in preview_colors.items():
        preview_arr[bottom_layer == mat_id] = rgba[:3]

    Stats.increment("calibrations")

    _log.info(
        "Smart 1296 board generated",
        extra={"event": "smart1296_board_generated", "output_path": output_path},
    )

    return (
        output_path,
        Image.fromarray(preview_arr),
        f"✅ Smart 1296 (38x38 边框版) 生成完毕 | 尺寸：{board_w:.1f}mm | 颜色：{', '.join(slot_names)}",
    )


# ========== Lumina Smart 1296 RYBW (6-Color RYBW System) ==========


def get_top_1296_colors_rybw():
    """Return unified 6-color recipes by reusing CMYW Smart1296 selection.
    复用 CMYW Smart1296 选色结果，统一 6 色配方集合。

    Returns:
        list[tuple[int, int, int, int, int]]: 1296 stacks using the shared
        CMYW-based recipe order. (共享 CMYW 方案的 1296 个堆叠配方)
    """
    _log.info(
        "Using unified CMYW Smart1296 recipes for RYBW",
        extra={"event": "smart1296_rybw_unified_recipes_used"},
    )
    return get_top_1296_colors()


def generate_smart_board_rybw(block_size_mm=5.0, gap_mm=0.8):
    """Generate RYBW 6-Color Smart1296 board with RYBW slot names and corner markers.
    生成 RYBW 6 色 Smart1296 校准板，使用 RYBW 色槽名和角标。

    Reuses the same 1296 recipe selection as CMYW but with RYBW color
    configuration so the 3MF slot names read Red/Yellow/Blue instead of
    Cyan/Magenta/Yellow.

    Args:
        block_size_mm (float): Size of each color block in mm. (色块边长，毫米)
        gap_mm (float): Gap between blocks in mm. (色块间距，毫米)

    Returns:
        tuple: (output_path, preview_image, status_message). (输出路径、预览图、状态信息)
    """
    _log.info(
        "Generating RYBW Smart1296 board with RYBW slot names and corner markers",
        extra={"event": "smart1296_rybw_board_generation_started"},
    )
    # RYBW corners: TL=White(0), TR=Red(1), BR=Blue(3), BL=Yellow(2)
    return generate_smart_board(
        block_size_mm=block_size_mm,
        gap_mm=gap_mm,
        color_conf=ColorSystem.SIX_COLOR_RYBW,
        corner_colors=(0, 1, 3, 2),
    )


def _load_selected_8color_stacks() -> np.ndarray:
    path = get_asset_path("smart_8color_stacks.npy")
    all_stacks = np.load(path)
    _log.info(
        "Loaded selected 8-color stacks",
        extra={"event": "selected_8color_stacks_loaded", "stack_count": len(all_stacks), "path": str(path)},
    )
    all_stacks = np.array([s[::-1] for s in all_stacks])
    surface_black = sum(1 for s in all_stacks if s[0] == 5)
    _log.info(
        "Computed 8-color surface black ratio",
        extra={
            "event": "selected_8color_surface_black_ratio_computed",
            "surface_black_count": surface_black,
            "stack_count": len(all_stacks),
            "surface_black_ratio_percent": round(surface_black / len(all_stacks) * 100, 3),
        },
    )
    return all_stacks


def _build_exhaustive_8color_stacks() -> np.ndarray:
    return np.array(list(itertools.product(range(8), repeat=5)), dtype=int)


def _build_8color_preview_rgb(stacks: np.ndarray, preview_colors: dict[int, list[int]]) -> np.ndarray:
    rgb = []
    for stack in stacks:
        stack_rgb = np.array([preview_colors[int(mid)][:3] for mid in stack], dtype=np.float64)
        rgb.append(np.round(stack_rgb.mean(axis=0)).astype(np.uint8))
    if not rgb:
        return np.zeros((0, 3), dtype=np.uint8)
    return np.array(rgb, dtype=np.uint8)


def _save_8color_recipe_json(
    out_path: str,
    stacks: np.ndarray,
    color_mode: str,
    slot_names: list[str],
    preview_colors: dict[int, list[int]],
    page_index: int,
    total_pages: int,
    export_variant: str,
) -> str:
    from config import LUTMetadata, PaletteEntry
    from utils.lut_manager import LUTManager

    json_path = os.path.splitext(out_path)[0] + ".json"
    palette = []
    for idx, name in enumerate(slot_names):
        rgba = preview_colors.get(idx)
        hex_color = None
        if rgba is not None:
            hex_color = f"#{rgba[0]:02X}{rgba[1]:02X}{rgba[2]:02X}"
        palette.append(PaletteEntry(color=name, material="PLA Basic", hex_color=hex_color, color_name=name))
    metadata = LUTMetadata(
        palette=palette,
        manufacturer="Lumina Studio",
        type=f"Calibration {export_variant} Page {page_index + 1}/{total_pages}",
        color_mode=color_mode,
        max_color_layers=PrinterConfig.COLOR_LAYERS,
        layer_height_mm=PrinterConfig.LAYER_HEIGHT,
        line_width_mm=PrinterConfig.NOZZLE_WIDTH,
        base_layers=int(PrinterConfig.BACKING_MM / PrinterConfig.LAYER_HEIGHT),
        base_channel_idx=0,
        layer_order="Top2Bottom",
    )
    rgb = _build_8color_preview_rgb(stacks, preview_colors)
    LUTManager.save_keyed_json(json_path, rgb, stacks.astype(np.int32), metadata)
    payload = None
    with open(json_path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    payload["page_index"] = page_index + 1
    payload["total_pages"] = total_pages
    payload["export_variant"] = export_variant
    page_layout = resolve_extraction_page_layout(
        "8-Color Max",
        page=f"Page {page_index + 1}",
        eight_color_full_export=export_variant == "full",
    )
    payload["data_grid"] = {
        "rows": page_layout.data_rows,
        "cols": page_layout.data_cols,
        "padding": page_layout.padding,
        "physical_rows": page_layout.physical_rows,
        "physical_cols": page_layout.physical_cols,
    }
    for idx, entry in enumerate(payload.get("entries", [])):
        entry["page_recipe_index"] = idx
        entry["data_row"] = idx // page_layout.data_cols
        entry["data_col"] = idx % page_layout.data_cols
        entry["physical_row"] = entry["data_row"] + page_layout.padding
        entry["physical_col"] = entry["data_col"] + page_layout.padding
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=4)
    return json_path


def _generate_8color_board_artifacts(
    stacks: np.ndarray,
    page_index: int,
    total_pages: int,
    block_size_mm: float,
    gap_mm: float,
    calibration_type: str,
    export_variant: str,
):
    page_layout = resolve_extraction_page_layout(
        "8-Color Max",
        page=f"Page {page_index + 1}",
        eight_color_full_export=export_variant == "full",
    )
    px_blk = max(1, int(block_size_mm / PrinterConfig.NOZZLE_WIDTH))
    px_gap = max(1, int(gap_mm / PrinterConfig.NOZZLE_WIDTH))
    v_w = page_layout.physical_cols * (px_blk + px_gap)
    full_matrix = np.full((5 + int(PrinterConfig.BACKING_MM / 0.08), v_w, v_w), 0, dtype=int)
    for i, stack in enumerate(stacks):
        r = (i // page_layout.data_cols) + page_layout.padding
        c = (i % page_layout.data_cols) + page_layout.padding
        py = r * (px_blk + px_gap)
        px = c * (px_blk + px_gap)
        for z, mid in enumerate(stack):
            full_matrix[z, py : py + px_blk, px : px + px_blk] = mid
    page_mark = 1 if page_index % 2 == 0 else 2
    corners = [
        (0, 0, 0),
        (0, page_layout.physical_cols - 1, page_mark),
        (page_layout.physical_rows - 1, page_layout.physical_cols - 1, 5),
        (page_layout.physical_rows - 1, 0, 4),
    ]
    for r, c, mid in corners:
        py = r * (px_blk + px_gap)
        px = c * (px_blk + px_gap)
        for z in range(5):
            full_matrix[z, py : py + px_blk, px : px + px_blk] = mid
    scene = _get_trimesh().Scene()
    conf = ColorSystem.EIGHT_COLOR
    for mid in range(8):
        mesh = _generate_voxel_mesh(full_matrix, mid, v_w, v_w)
        if mesh:
            mesh.visual.face_colors = conf["preview"][mid]
            mesh.metadata["name"] = conf["slots"][mid]
            scene.add_geometry(mesh, geom_name=conf["slots"][mid])
    page_name = f"{page_index + 1}号"
    out_name = f"{page_name}.3mf"
    out_path = os.path.join(MODELS_DIR, out_name)
    export_scene_with_bambu_metadata(
        scene=scene,
        output_path=out_path,
        slot_names=conf["slots"],
        preview_colors=conf["preview"],
        settings={
            "layer_height": "0.08",
            "initial_layer_height": "0.08",
            "wall_loops": "1",
            "top_shell_layers": "0",
            "bottom_shell_layers": "0",
            "sparse_infill_density": "100%",
            "sparse_infill_pattern": "zig-zag",
        },
        color_mode="8-Color",
    )
    prev = np.zeros((v_w, v_w, 3), dtype=np.uint8)
    for mid, col in conf["preview"].items():
        prev[full_matrix[0] == mid] = col[:3]
    json_path = _save_8color_recipe_json(
        out_path=out_path,
        stacks=stacks,
        color_mode="8-Color Max",
        slot_names=list(conf["map"].keys()),
        preview_colors=conf["preview"],
        page_index=page_index,
        total_pages=total_pages,
        export_variant=export_variant,
    )
    return out_path, json_path, Image.fromarray(prev)


def generate_8color_full_batch_zip(block_size_mm: float = 5.0, gap_mm: float = 0.8):
    """Generate the exhaustive 8-color calibration set as a multi-page ZIP.
    将全量 8 色校准配方导出为多页 ZIP。

    Args:
        block_size_mm (float): Size of each color block in mm. (色块边长，单位 mm)
        gap_mm (float): Gap between adjacent blocks in mm. (色块间距，单位 mm)

    Returns:
        tuple: (zip_path, preview_image, status_message).
               (ZIP 路径、预览图、状态信息)
    """
    all_stacks = _build_exhaustive_8color_stacks()
    total_pages = int(math.ceil(len(all_stacks) / EIGHT_COLOR_PAGE_CAPACITY))
    artifacts = []
    preview = None
    for page_index in range(total_pages):
        start = page_index * EIGHT_COLOR_PAGE_CAPACITY
        page_stacks = all_stacks[start : start + EIGHT_COLOR_PAGE_CAPACITY]
        calibration_type = f"{page_index + 1}号"
        out_path, json_path, page_preview = _generate_8color_board_artifacts(
            stacks=page_stacks,
            page_index=page_index,
            total_pages=total_pages,
            block_size_mm=block_size_mm,
            gap_mm=gap_mm,
            calibration_type=calibration_type,
            export_variant="full",
        )
        artifacts.append((out_path, json_path))
        if preview is None:
            preview = page_preview
    zip_path = os.path.join(MODELS_DIR, generate_calibration_filename("8-Color", "FullKit", ".zip"))
    with zipfile.ZipFile(zip_path, "w") as zf:
        for out_path, json_path in artifacts:
            zf.write(out_path, os.path.basename(out_path))
            zf.write(json_path, os.path.basename(json_path))
    return zip_path, preview, f"[OK] 8-Color Full Kit ({total_pages} Pages + JSON) Generated!"


def generate_8color_board(page_index: int = 0, block_size_mm: float = 5.0, gap_mm: float = 0.8):
    """Generate 8-color calibration board page as 3MF.
    生成 8 色校准板单页 3MF 模型。

    Args:
        page_index (int): Page index (0 or 1). (页码索引，0 或 1)
        block_size_mm (float): Size of each color block in mm. (色块边长，单位 mm)
        gap_mm (float): Gap between blocks in mm. (色块间距，单位 mm)

    Returns:
        tuple: (output_path, preview_image, status_message).
               (输出路径, 预览图像, 状态消息)
    """
    try:
        all_stacks = _load_selected_8color_stacks()
    except CALIBRATION_HANDLED_ERRORS as e:
        _log.info(
            "Failed to load 8-color stack data",
            extra={"event": "selected_8color_stack_load_failed", "error_type": type(e).__name__, "error_message": str(e)},
        )
        return None, None, "[ERROR] Data not found. Run analyze_colors.py first."
    start = page_index * EIGHT_COLOR_PAGE_CAPACITY
    stacks = all_stacks[start : start + EIGHT_COLOR_PAGE_CAPACITY]
    out_path, _, preview = _generate_8color_board_artifacts(
        stacks=stacks,
        page_index=page_index,
        total_pages=2,
        block_size_mm=block_size_mm,
        gap_mm=gap_mm,
        calibration_type=f"{page_index + 1}号",
        export_variant="selected",
    )
    return out_path, preview, "OK"


def generate_8color_batch_zip(block_size_mm: float = 5.0, gap_mm: float = 0.8):
    """Generate both compact 8-color pages and zip them with recipe JSON files.
    生成两页精简 8 色校准板，并连同配方 JSON 一起打包为 ZIP。

    Args:
        block_size_mm (float): Size of each color block in mm. (色块边长，单位 mm)
        gap_mm (float): Gap between adjacent blocks in mm. (色块间距，单位 mm)

    Returns:
        tuple: (zip_path, preview_image, status_message). (ZIP 路径、预览图、状态信息)
    """
    f1, prev, _ = generate_8color_board(0, block_size_mm=block_size_mm, gap_mm=gap_mm)
    f2, _, _ = generate_8color_board(1, block_size_mm=block_size_mm, gap_mm=gap_mm)

    if not f1 or not f2:
        return None, None, "[ERROR] Generation failed"

    j1 = os.path.splitext(f1)[0] + ".json"
    j2 = os.path.splitext(f2)[0] + ".json"

    zip_path = os.path.join(MODELS_DIR, generate_calibration_filename("8-Color", "Kit", ".zip"))
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.write(f1, os.path.basename(f1))
        zf.write(f2, os.path.basename(f2))
        if os.path.exists(j1):
            zf.write(j1, os.path.basename(j1))
        if os.path.exists(j2):
            zf.write(j2, os.path.basename(j2))

    return zip_path, prev, "[OK] 8-Color Kit (Page 1 & 2 + JSON) Generated!"


def generate_bw_calibration_board(block_size_mm=5.0, gap_mm=0.8, backing_color="White"):
    """
    Generate Black & White (2-Color) calibration board with 8x8 border layout.

    Features:
    - 8x8 physical grid (6x6 data + 2 border protection)
    - 32 exhaustive color combinations (2^5 = 32)
    - Corner alignment markers in outermost ring
    - Face Down printing (same as 4-color mode)

    Args:
        block_size_mm: Size of each color block in mm
        gap_mm: Gap between blocks in mm
        backing_color: Backing layer color ("White" or "Black")

    Returns:
        Tuple of (output_path, preview_image, status_message)
    """
    _log.info(
        "Generating Black & White calibration board",
        extra={"event": "bw_calibration_board_generation_started", "grid": "8x8"},
    )

    # Get color configuration
    color_conf = ColorSystem.BW
    preview_colors = color_conf["preview"]
    slot_names = color_conf["slots"]
    color_map = color_conf["map"]

    backing_id = color_map.get(backing_color, 0)

    layout = resolve_lut_layout("BW", 32)
    page = layout.pages[0]
    total_dim = page.physical_rows
    block_w = float(block_size_mm)
    gap = float(gap_mm)
    margin = 5.0

    # Calculate board dimensions
    board_w = margin * 2 + total_dim * block_w + (total_dim - 1) * gap
    board_h = board_w

    _log.info(
        "Black & White calibration board size resolved",
        extra={
            "event": "bw_calibration_board_size_resolved",
            "board_width_mm": round(board_w, 3),
            "board_height_mm": round(board_h, 3),
            "grid": f"{total_dim}x{total_dim}",
        },
    )

    # Calculate voxel grid dimensions
    pixels_per_block = max(1, int(block_w / PrinterConfig.NOZZLE_WIDTH))
    pixels_gap = max(1, int(gap / PrinterConfig.NOZZLE_WIDTH))

    voxel_w = total_dim * (pixels_per_block + pixels_gap)
    voxel_h = total_dim * (pixels_per_block + pixels_gap)

    # Layer configuration
    color_layers = 5
    backing_layers = int(PrinterConfig.BACKING_MM / PrinterConfig.LAYER_HEIGHT)
    total_layers = color_layers + backing_layers

    # Initialize voxel matrix (filled with White Slot 0)
    full_matrix = np.full((total_layers, voxel_h, voxel_w), 0, dtype=int)

    _log.info(
        "Black & White voxel matrix initialized",
        extra={
            "event": "bw_voxel_matrix_initialized",
            "layer_count": total_layers,
            "height_px": voxel_h,
            "width_px": voxel_w,
        },
    )

    # Generate all 32 combinations (2^5 = 32)
    _log.info(
        "Generating Black & White calibration combinations",
        extra={"event": "bw_combinations_started", "combination_count": 32},
    )
    stacks = []
    for i in range(32):
        digits = []
        temp = i
        for _ in range(5):
            digits.append(temp % 2)
            temp //= 2
        stack = digits[::-1]  # [顶...底] format
        stacks.append(stack)

    # Fill 32 blocks in 6x6 data area (with padding offset)
    for idx in range(32):
        cell = cell_for_row_index(layout, idx)
        row = cell.physical_row
        col = cell.physical_col

        stack = stacks[idx]

        px = col * (pixels_per_block + pixels_gap)
        py = row * (pixels_per_block + pixels_gap)

        # Fill 5 color layers (Z=0 is viewing surface)
        # stack format is [顶...底], so stack[0] -> Z=0
        for z in range(color_layers):
            mat_id = stack[z]
            full_matrix[z, py : py + pixels_per_block, px : px + pixels_per_block] = mat_id

    # Set corner alignment markers (in outermost ring 0 and 7)
    # TL: White (0), TR: Black (1), BR: Black (1), BL: Black (1)
    corners = [
        (0, 0, 0),  # TL = White
        (0, total_dim - 1, 1),  # TR = Black
        (total_dim - 1, total_dim - 1, 1),  # BR = Black
        (total_dim - 1, 0, 1),  # BL = Black
    ]

    for r, c, mat_id in corners:
        px = c * (pixels_per_block + pixels_gap)
        py = r * (pixels_per_block + pixels_gap)
        for z in range(color_layers):
            full_matrix[z, py : py + pixels_per_block, px : px + pixels_per_block] = mat_id

    # Generate 3MF scene
    scene = _get_trimesh().Scene()

    for mat_id in range(2):
        mesh = _generate_voxel_mesh(full_matrix, mat_id, voxel_h, voxel_w)
        if mesh:
            mesh.visual.face_colors = preview_colors[mat_id]
            name = slot_names[mat_id]
            mesh.metadata["name"] = name
            scene.add_geometry(mesh, node_name=name, geom_name=name)

    # Export
    output_path = os.path.join(MODELS_DIR, generate_calibration_filename("BW", "Standard"))
    export_scene_with_bambu_metadata(
        scene=scene,
        output_path=output_path,
        slot_names=slot_names,
        preview_colors=preview_colors,
        settings={
            "layer_height": "0.08",
            "initial_layer_height": "0.08",
            "wall_loops": "1",
            "top_shell_layers": "0",
            "bottom_shell_layers": "0",
            "sparse_infill_density": "100%",
            "sparse_infill_pattern": "zig-zag",
        },
        color_mode="BW",
    )

    # Generate preview image
    bottom_layer = full_matrix[0].astype(np.uint8)
    preview_arr = np.zeros((voxel_h, voxel_w, 3), dtype=np.uint8)
    for mat_id, rgba in preview_colors.items():
        preview_arr[bottom_layer == mat_id] = rgba[:3]

    Stats.increment("calibrations")

    _log.info(
        "Black & White calibration board generated",
        extra={"event": "bw_calibration_board_generated", "output_path": output_path},
    )

    return (
        output_path,
        Image.fromarray(preview_arr),
        f"✅ BW (8x8 边框版) 生成完毕 | 尺寸：{board_w:.1f}mm | 颜色：{', '.join(slot_names)}",
    )


def select_extended_1444_colors(base_1024_stacks):
    """
    Intelligent color selection algorithm for 5-Color Extended (6-layer) system.

    Selects 1444 most representative 6-layer color combinations from 3073 possible
    combinations (3×1024 + 1 for KWWWWW) to extend the base 1024 5-layer colors.

    The 6-layer structure:
    - First 5 layers: identical to 4-color mode (RYBW combinations, 1024 total)
    - 6th layer (outermost/viewing surface): R, Y, B (3 choices), or K (only in KWWWWW)
    - Total theoretical: 3×1024 + 1 = 3073
    - Actual selection: 1443 (greedy) + 1 (KWWWWW) = 1444 colors

    Args:
        base_1024_stacks: List of 1024 base 5-layer color stacks (from 4-color mode)

    Returns:
        List of 1444 tuples, each representing a 6-layer color stack
    """
    _log.info(
        "Selecting 5-color extended colors",
        extra={"event": "five_color_extended_selection_started", "candidate_count": 3073, "target_count": 1444},
    )

    LAYER_HEIGHT = PrinterConfig.LAYER_HEIGHT
    BACKING = np.array([255, 255, 255])

    FILAMENTS = {
        0: {"name": "White", "rgb": [255, 255, 255], "td": 5.0},
        1: {"name": "Red", "rgb": [220, 20, 60], "td": 4.0},
        2: {"name": "Yellow", "rgb": [255, 230, 0], "td": 6.0},
        3: {"name": "Blue", "rgb": [0, 100, 240], "td": 2.0},
        4: {"name": "Black", "rgb": [20, 20, 20], "td": 0.6},
    }

    alphas = {}
    for fid, props in FILAMENTS.items():
        bd = props["td"] / 10.0
        alphas[fid] = min(1.0, LAYER_HEIGHT / bd) if bd > 0 else 1.0

    def simulate_color(stack):
        """Simulate final color from a stack (Bottom-to-Top alpha blending)"""
        curr = BACKING.astype(float)
        for fid in reversed(stack):  # Iterate from Bottom to Top for correct reflection simulation
            rgb = np.array(FILAMENTS[fid]["rgb"])
            a = alphas[fid]
            curr = rgb * a + curr * (1.0 - a)
        return curr.astype(np.uint8)

    candidates = []

    for base_stack in base_1024_stacks:
        for layer6 in [1, 2, 3]:  # R, Y, B (viewing surface, outermost layer)
            # stack format: [top...bottom] where top is viewing surface
            # layer6 should be at index 0 (viewing surface), base_stack follows
            stack = (layer6,) + tuple(base_stack)
            final_rgb = simulate_color(stack)
            candidates.append({"stack": stack, "rgb": final_rgb})

    kwwwww_stack = (4, 0, 0, 0, 0, 0)  # KWWWWW (K on outermost/viewing surface)
    kwwwww_rgb = simulate_color(kwwwww_stack)
    candidates.append({"stack": kwwwww_stack, "rgb": kwwwww_rgb, "is_special": True})

    _log.info(
        "5-color extended candidates generated",
        extra={"event": "five_color_extended_candidates_generated", "candidate_count": len(candidates)},
    )

    selected = []

    selected.append({"stack": kwwwww_stack, "rgb": kwwwww_rgb})
    _log.info(
        "Pre-selected KWWWWW special case",
        extra={"event": "five_color_extended_special_case_selected", "recipe": "KWWWWW"},
    )

    target = 1444

    _log.info(
        "Starting 5-color extended greedy selection",
        extra={"event": "five_color_extended_greedy_selection_started", "rgb_distance_threshold": 8},
    )
    selected_rgbs = np.array([s["rgb"] for s in selected], dtype=int)

    for c in candidates:
        if len(selected) >= target:
            break

        # Check if already selected (by stack)
        if any(c["stack"] == s["stack"] for s in selected):
            continue

        is_distinct = True
        if len(selected_rgbs) > 0:
            c_rgb = c["rgb"].astype(int)
            # Vectorized distance check
            dists = np.linalg.norm(selected_rgbs - c_rgb, axis=1)
            if np.any(dists < 8):
                is_distinct = False

        if is_distinct:
            selected.append(c)
            selected_rgbs = np.vstack([selected_rgbs, c["rgb"].astype(int)])

    _log.info(
        "5-color extended greedy selection completed",
        extra={"event": "five_color_extended_greedy_selection_done", "selected_count": len(selected)},
    )

    if len(selected) < target:
        _log.info(
            "Filling remaining 5-color extended color slots",
            extra={"event": "five_color_extended_remaining_slots_filled", "remaining_count": target - len(selected)},
        )
        for c in candidates:
            if len(selected) >= target:
                break
            if any(c["stack"] == s["stack"] for s in selected):
                continue
            selected.append(c)

    _log.info(
        "5-color extended selection completed",
        extra={"event": "five_color_extended_selection_done", "selected_count": len(selected)},
    )

    return [s["stack"] for s in selected[:target]]


def get_top_5color_extended_page2_stacks():
    """
    Intelligent color selection algorithm for 5-Color Extended Page 2.

    Returns 1444 most representative color combinations from 4096 possible
    combinations (4^5 + 4^5*3) to fill a 38x38 grid.

    This function reconstructs the Page 2 stacking order for extraction.

    Returns:
        List of 1444 tuples, each representing a 5 or 6-layer color stack
    """
    _log.info(
        "Simulating 5-color extended page 2 combinations",
        extra={"event": "five_color_extended_page2_combinations_started", "combination_count": 4096},
    )

    LAYER_HEIGHT = PrinterConfig.LAYER_HEIGHT
    BACKING = np.array([255, 255, 255])

    FILAMENTS = {
        0: {"name": "White", "rgb": [255, 255, 255], "td": 5.0},
        1: {"name": "Red", "rgb": [220, 20, 60], "td": 4.0},
        2: {"name": "Yellow", "rgb": [255, 230, 0], "td": 6.0},
        3: {"name": "Blue", "rgb": [0, 100, 240], "td": 2.0},
    }

    alphas = {}
    for fid, props in FILAMENTS.items():
        bd = props["td"] / 10.0
        alphas[fid] = min(1.0, LAYER_HEIGHT / bd) if bd > 0 else 1.0

    candidates_5layer = []
    candidates_6layer = []

    for stack in itertools.product(range(4), repeat=5):
        curr = BACKING.astype(float)
        for fid in stack:
            rgb = np.array(FILAMENTS[fid]["rgb"])
            a = alphas[fid]
            curr = rgb * a + curr * (1.0 - a)
        final_rgb = curr.astype(np.uint8)
        candidates_5layer.append({"stack": stack, "layers": 5, "rgb": final_rgb})

    for stack_5 in itertools.product(range(4), repeat=5):
        for layer6 in range(1, 4):  # R, Y, B (not White)
            stack = stack_5 + (layer6,)
            curr = BACKING.astype(float)
            for fid in stack:
                rgb = np.array(FILAMENTS[fid]["rgb"])
                a = alphas[fid]
                curr = rgb * a + curr * (1.0 - a)
            final_rgb = curr.astype(np.uint8)
            candidates_6layer.append({"stack": stack, "layers": 6, "rgb": final_rgb})

    _log.info(
        "5-color extended page 2 candidates generated",
        extra={
            "event": "five_color_extended_page2_candidates_generated",
            "five_layer_candidate_count": len(candidates_5layer),
            "six_layer_candidate_count": len(candidates_6layer),
        },
    )

    all_candidates = candidates_5layer + candidates_6layer

    selected = []

    _log.info(
        "Pre-selecting 5-color extended page 2 seed colors",
        extra={"event": "five_color_extended_page2_seed_selection_started"},
    )
    for i in range(4):
        stack = (i,) * 5
        for c in candidates_5layer:
            if c["stack"] == stack:
                selected.append(c)
                break

    _log.info(
        "5-color extended page 2 seed colors selected",
        extra={"event": "five_color_extended_page2_seed_selection_done", "selected_count": len(selected)},
    )

    target = 1444

    _log.info(
        "Starting 5-color extended page 2 high-quality selection",
        extra={"event": "five_color_extended_page2_high_quality_selection_started", "rgb_distance_threshold": 8},
    )
    for c in all_candidates:
        if len(selected) >= target:
            break
        if any(c["stack"] == s["stack"] for s in selected):
            continue

        is_distinct = True
        for s in selected:
            if np.linalg.norm(c["rgb"].astype(int) - s["rgb"].astype(int)) < 8:
                is_distinct = False
                break

        if is_distinct:
            selected.append(c)

    _log.info(
        "5-color extended page 2 high-quality selection completed",
        extra={"event": "five_color_extended_page2_high_quality_selection_done", "selected_count": len(selected)},
    )

    if len(selected) < target:
        _log.info(
            "Filling remaining 5-color extended page 2 color slots",
            extra={
                "event": "five_color_extended_page2_remaining_slots_filled",
                "remaining_count": target - len(selected),
            },
        )
        for c in all_candidates:
            if len(selected) >= target:
                break
            if any(c["stack"] == s["stack"] for s in selected):
                continue
            selected.append(c)

    _log.info(
        "5-color extended page 2 selection completed",
        extra={"event": "five_color_extended_page2_selection_done", "selected_count": len(selected)},
    )

    return [s["stack"] for s in selected[:target]]


def merge_5color_extended(base_lut_path, extended_lut_path, output_path=None):
    """
    Merge 4-Color base LUT (1024) and 5-Color Extended LUT (1444) into a single 2468-color LUT.

    Args:
        base_lut_path: Path to base 1024-color LUT (.npy file)
        extended_lut_path: Path to extended 1444-color LUT (.npy file)
        output_path: Optional output path for merged LUT (.npz file)

    Returns:
        Tuple of (rgb_array, stacks_array, output_path)
    """
    _log.info(
        "Merging 5-color extended LUT",
        extra={"event": "five_color_extended_lut_merge_started"},
    )

    # Load base LUT (1024 colors, 5-layer)
    _log.info(f"  Loading base LUT: {base_lut_path}")
    base_rgb = np.load(base_lut_path).reshape(-1, 3)
    _log.info(f"    Base RGB: {len(base_rgb)} colors")

    # Load extended LUT (1444 colors, 6-layer)
    _log.info(f"  Loading extended LUT: {extended_lut_path}")
    extended_rgb = np.load(extended_lut_path).reshape(-1, 3)
    _log.info(f"    Extended RGB: {len(extended_rgb)} colors")

    # Merge RGB arrays
    merged_rgb = np.vstack([base_rgb, extended_rgb])
    _log.info(f"  Merged RGB: {len(merged_rgb)} colors")

    # Generate stacks
    # Base 1024: 5-layer stacks, pad with air(-1) at top for 6-layer uniformity.
    # Air at position 0 keeps base/extended viewing surfaces on separate Z levels.
    base_stacks = []
    for i in range(len(base_rgb)):
        digits = []
        temp = i
        for _ in range(5):
            digits.append(temp % 4)
            temp //= 4
        stack = (-1,) + tuple(reversed(digits))
        base_stacks.append(stack)

    # Extended 1444: 6-layer stacks
    base_5layer = [tuple(reversed([i // 4**j % 4 for j in range(5)])) for i in range(1024)]
    extended_stacks = select_extended_1444_colors(base_5layer)

    # Merge stacks
    merged_stacks = base_stacks + extended_stacks
    _log.info(f"  Merged stacks: {len(merged_stacks)} stacks")

    # Convert to numpy arrays
    rgb_array = np.array(merged_rgb, dtype=np.uint8)
    stacks_array = np.array(merged_stacks, dtype=np.int32)

    # Save to .npz file
    if output_path is None:
        output_path = "output/merged_5color_extended_2468.npz"

    np.savez(output_path, rgb=rgb_array, stacks=stacks_array)
    _log.info(f"  Saved merged LUT: {output_path}")

    return rgb_array, stacks_array, output_path


def generate_5color_extended_board(block_size_mm=5.0, gap_mm=0.8, page_index=0):
    """
    Generate 5-Color Extended calibration board with dual-page support.

    Features:
    - Page 0: Base 1024 colors (5-layer, 32x32 grid)
    - Page 1: Extended 1444 colors (6-layer, 38x38 grid)
    - Corner alignment markers with page ID
    - Face Down printing for both pages (viewing surface at Z=0)

    Args:
        block_size_mm: Size of each color block in mm
        gap_mm: Gap between blocks in mm
        page_index: 0 for base 1024, 1 for extended 1444

    Returns:
        Tuple of (output_path, preview_image, status_message)
    """
    _log.info(
        "Generating 5-color extended calibration board page",
        extra={
            "event": "five_color_extended_board_page_generation_started",
            "page_index": page_index,
            "page_number": page_index + 1,
        },
    )

    # Color configuration (5 slots: W, R, Y, B, K)
    preview_colors = {
        0: [255, 255, 255, 255],  # White
        1: [220, 20, 60, 255],  # Red
        2: [255, 230, 0, 255],  # Yellow
        3: [0, 100, 240, 255],  # Blue
        4: [20, 20, 20, 255],  # Black
    }
    slot_names = ["White", "Red", "Yellow", "Blue", "Black"]

    if page_index == 0:
        # Page 1: Base 1024 colors (5-layer, similar to 4-color mode)
        return _generate_5color_base_page(block_size_mm, gap_mm, preview_colors, slot_names)
    else:
        # Page 2: Extended 1444 colors (6-layer)
        return _generate_5color_extended_page(block_size_mm, gap_mm, preview_colors, slot_names)


def _generate_5color_base_page(block_size_mm, gap_mm, preview_colors, slot_names):
    """Generate Page 1: Base 1024 colors (5-layer RYBW combinations)."""
    _log.info(
        "Generating 5-color extended base page",
        extra={"event": "five_color_extended_base_page_generation_started", "color_count": 1024, "layer_count": 5},
    )

    page_layout = resolve_extraction_page_layout(
        "5-Color Extended",
        2468,
        page="Page 1",
    )
    layout = resolve_lut_layout("5-Color Extended", 1024)
    total_dim = page_layout.physical_rows
    block_w = float(block_size_mm)
    gap = float(gap_mm)
    margin = 5.0

    board_w = margin * 2 + total_dim * block_w + (total_dim - 1) * gap

    pixels_per_block = max(1, int(block_w / PrinterConfig.NOZZLE_WIDTH))
    pixels_gap = max(1, int(gap / PrinterConfig.NOZZLE_WIDTH))

    voxel_w = total_dim * (pixels_per_block + pixels_gap)
    voxel_h = total_dim * (pixels_per_block + pixels_gap)

    # 5 color layers + white backing (Face-Down mode, same as 4-color mode)
    color_layers = 5
    backing_layers = int(PrinterConfig.BACKING_MM / PrinterConfig.LAYER_HEIGHT)
    total_layers = color_layers + backing_layers

    full_matrix = np.full((total_layers, voxel_h, voxel_w), 0, dtype=int)  # 0 = White backing

    # Generate 1024 base stacks (4^5 combinations of RYBW)
    # Face-Down mode: Z=0 is viewing surface (top), Z=4 is bottom
    for i in range(1024):
        digits = []
        temp = i
        for _ in range(5):
            digits.append(temp % 4)
            temp //= 4
        stack = digits[::-1]  # [top...bottom] for Face-Down mode (Z=0 is viewing surface)

        cell = cell_for_row_index(layout, i)
        row = cell.physical_row
        col = cell.physical_col

        px = col * (pixels_per_block + pixels_gap)
        py = row * (pixels_per_block + pixels_gap)

        # Fill 5 color layers (Face-Down mode: Z=0 is viewing surface)
        for z in range(color_layers):
            mat_id = stack[z]
            if mat_id < 4:
                full_matrix[z, py : py + pixels_per_block, px : px + pixels_per_block] = mat_id

    # Corner markers for Page 1: TL=White, TR=Red(Page1 ID), BR=Blue, BL=Yellow
    corners = [
        (0, 0, 0),  # TL = White
        (0, total_dim - 1, 1),  # TR = Red (Page 1 ID)
        (total_dim - 1, total_dim - 1, 3),  # BR = Blue
        (total_dim - 1, 0, 2),  # BL = Yellow
    ]

    for r, c, mat_id in corners:
        px = c * (pixels_per_block + pixels_gap)
        py = r * (pixels_per_block + pixels_gap)
        for z in range(color_layers):
            full_matrix[z, py : py + pixels_per_block, px : px + pixels_per_block] = mat_id

    # Generate 3MF
    scene = _get_trimesh().Scene()
    for mat_id, rgba in preview_colors.items():
        if mat_id < 4:  # Only 4 colors for base page
            mesh = _generate_voxel_mesh(full_matrix, mat_id, voxel_h, voxel_w)
            if mesh:
                mesh.visual.face_colors = rgba
                name = slot_names[mat_id]
                mesh.metadata["name"] = name
                scene.add_geometry(mesh, node_name=name, geom_name=name)

    output_path = os.path.join(MODELS_DIR, generate_calibration_filename("5-Color Extended", "Page1"))
    export_scene_with_bambu_metadata(
        scene=scene,
        output_path=output_path,
        slot_names=slot_names[:4],
        preview_colors=preview_colors,
        settings={
            "layer_height": "0.08",
            "initial_layer_height": "0.08",
            "wall_loops": "1",
            "top_shell_layers": "0",
            "bottom_shell_layers": "0",
            "sparse_infill_density": "100%",
            "sparse_infill_pattern": "zig-zag",
        },
        color_mode="5-Color Extended",
    )

    # Preview
    bottom_layer = full_matrix[0].astype(np.uint8)
    preview_arr = np.zeros((voxel_h, voxel_w, 3), dtype=np.uint8)
    for mat_id, rgba in preview_colors.items():
        if mat_id < 4:
            preview_arr[bottom_layer == mat_id] = rgba[:3]

    Stats.increment("calibrations")

    return (
        output_path,
        Image.fromarray(preview_arr),
        f"✅ 5-Color Extended Page 1 (1024 colors) 生成完毕 | 尺寸：{board_w:.1f}mm",
    )


def _generate_5color_extended_page(block_size_mm, gap_mm, preview_colors, slot_names):
    """Generate Page 2: Extended 1444 colors (6-layer with Black).

    Features:
    - 1444 extended colors (6-layer stacks)
    - 38x38 grid with padding
    - Face Down printing (viewing surface at Z=0, first printed layer)
    - Corner markers: TL=Blue, TR=Red(Page2 ID), BR=Black, BL=Yellow
    """
    _log.info(
        "Generating 5-color extended page",
        extra={"event": "five_color_extended_page_generation_started", "color_count": 1444, "layer_count": 6},
    )

    # Get base 1024 stacks for extended color selection
    base_stacks = []
    for i in range(1024):
        digits = []
        temp = i
        for _ in range(5):
            digits.append(temp % 4)
            temp //= 4
        stack = tuple(reversed(digits))
        base_stacks.append(stack)

    # Get extended 1444 stacks (6-layer)
    extended_stacks = select_extended_1444_colors(base_stacks)

    page_layout = resolve_extraction_page_layout(
        "5-Color Extended",
        2468,
        page="Page 2",
    )
    local_layout = localize_page_layout(page_layout, item_count=1444)
    total_dim = page_layout.physical_rows
    block_w = float(block_size_mm)
    gap = float(gap_mm)
    margin = 5.0

    board_w = margin * 2 + total_dim * block_w + (total_dim - 1) * gap

    pixels_per_block = max(1, int(block_w / PrinterConfig.NOZZLE_WIDTH))
    pixels_gap = max(1, int(gap / PrinterConfig.NOZZLE_WIDTH))

    voxel_w = total_dim * (pixels_per_block + pixels_gap)
    voxel_h = total_dim * (pixels_per_block + pixels_gap)

    # 6 color layers + white backing (Face-Down mode, viewing surface at Z=0)
    color_layers = 6
    backing_layers = int(PrinterConfig.BACKING_MM / PrinterConfig.LAYER_HEIGHT)
    total_layers = color_layers + backing_layers

    full_matrix = np.full((total_layers, voxel_h, voxel_w), 0, dtype=int)  # 0 = White backing

    # Fill 1444 extended colors (6-layer)
    for idx in range(1444):
        stack = extended_stacks[idx]
        cell = cell_for_row_index(local_layout, idx)
        row = cell.physical_row
        col = cell.physical_col

        px = col * (pixels_per_block + pixels_gap)
        py = row * (pixels_per_block + pixels_gap)

        # Map stack to physical layers (Face-Down mode: Z=0 is viewing surface)
        for z in range(color_layers):
            mat_id = stack[z]  # Direct mapping: stack[0] at Z=0 (viewing surface)
            if mat_id < 5:
                full_matrix[z, py : py + pixels_per_block, px : px + pixels_per_block] = mat_id

    corners = [
        (0, 0, 3),  # TL = Blue
        (0, total_dim - 1, 1),  # TR = Red (Page 2 ID)
        (total_dim - 1, total_dim - 1, 4),  # BR = Black
        (total_dim - 1, 0, 2),  # BL = Yellow
    ]

    viewing_surface_z = 0  # Face-Down mode: viewing surface is the first printed layer (Z=0)
    for r, c, mat_id in corners:
        px = c * (pixels_per_block + pixels_gap)
        py = r * (pixels_per_block + pixels_gap)
        full_matrix[viewing_surface_z, py : py + pixels_per_block, px : px + pixels_per_block] = mat_id

    # Generate 3MF
    scene = _get_trimesh().Scene()
    for mat_id, rgba in preview_colors.items():
        mesh = _generate_voxel_mesh(full_matrix, mat_id, voxel_h, voxel_w)
        if mesh:
            mesh.visual.face_colors = rgba
            name = slot_names[mat_id]
            mesh.metadata["name"] = name
            scene.add_geometry(mesh, node_name=name, geom_name=name)

    output_path = os.path.join(MODELS_DIR, generate_calibration_filename("5-Color Extended", "Page2"))
    export_scene_with_bambu_metadata(
        scene=scene,
        output_path=output_path,
        slot_names=slot_names,
        preview_colors=preview_colors,
        settings={
            "layer_height": "0.08",
            "initial_layer_height": "0.08",
            "wall_loops": "1",
            "top_shell_layers": "0",
            "bottom_shell_layers": "0",
            "sparse_infill_density": "100%",
            "sparse_infill_pattern": "zig-zag",
        },
        color_mode="5-Color Extended",
    )

    # Preview
    bottom_layer = full_matrix[0].astype(np.uint8)
    preview_arr = np.zeros((voxel_h, voxel_w, 3), dtype=np.uint8)
    for mat_id, rgba in preview_colors.items():
        preview_arr[bottom_layer == mat_id] = rgba[:3]

    Stats.increment("calibrations")

    return (
        output_path,
        Image.fromarray(preview_arr),
        f"✅ 5-Color Extended Page 2 (1444 colors) 生成完毕 | 尺寸：{board_w:.1f}mm",
    )


def generate_5color_extended_batch_zip(block_size_mm: float = 5.0, gap_mm: float = 0.8):
    """Generate both 5-color extended pages and zip them.
    生成两页 5 色扩展校准板并打包为 ZIP。

    Args:
        block_size_mm (float): Swatch block size in mm. (色块边长，单位 mm)
        gap_mm (float): Gap between swatches in mm. (色块间距，单位 mm)

    Returns:
        tuple: (zip_path, preview_image, status_message). (ZIP 路径、预览图、状态信息)
    """
    f1, _, _ = generate_5color_extended_board(block_size_mm=block_size_mm, gap_mm=gap_mm, page_index=0)
    f2, _, _ = generate_5color_extended_board(block_size_mm=block_size_mm, gap_mm=gap_mm, page_index=1)

    if not f1 or not f2:
        return None, None, "❌ Generation failed"

    zip_path = os.path.join(MODELS_DIR, generate_calibration_filename("5-Color Extended", "Kit", ".zip"))
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.write(f1, os.path.basename(f1))
        zf.write(f2, os.path.basename(f2))

    _, prev, _ = generate_5color_extended_board(
        block_size_mm=block_size_mm, gap_mm=gap_mm, page_index=0
    )  # Show Page 1 as preview
    return zip_path, prev, "✅ 5-Color Extended Kit (Page 1 & 2) Generated!"
