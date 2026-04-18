"""
Lumina Studio — Recipe Swatch 3MF Generator.
Lumina Studio — 配方色块 3MF 生成器。

Generates a multi-material 3MF containing one colored swatch block per recipe,
laid out in a grid with white grid lines connecting blocks (like a calibration
card). Also produces a legend image mapping grid positions to recipe details.
生成一个多材质 3MF 文件，每个配方对应一个色块。色块按网格排列，用白色网格线连
接（类似校色卡）。同时生成一张色卡图标注网格位置与配方的对应关系。
"""

from __future__ import annotations

import logging
import math
import os
import time
from dataclasses import dataclass
from typing import Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from config import MODELS_DIR, PrinterConfig

_log = logging.getLogger(__name__)

# Lazy trimesh import
_trimesh = None

_GRID_MATERIAL_NAME = "White"
_GRID_MATERIAL_HEX = "#FFFFFF"


def _get_trimesh():
    global _trimesh
    if _trimesh is None:
        import trimesh as _tm
        _trimesh = _tm
    return _trimesh


@dataclass
class RecipeSwatchItem:
    """Single recipe to render as a swatch block.
    单个配方，渲染为一个色块。

    Attributes:
        selected_indices: 5-element color index sequence. (5 个颜色索引序列)
        result_hex: Blended result hex color. (混合结果 hex 颜色)
        base_color_names: Name of each base color by index. (各基础色名称)
        base_color_hexes: Hex of each base color by index. (各基础色 hex)
    """
    selected_indices: list[int]
    result_hex: str
    base_color_names: list[str]
    base_color_hexes: list[str]


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """Convert '#RRGGBB' to (R, G, B) tuple."""
    h = hex_color.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _build_box_mesh(
    x0: float, y0: float, z0: float,
    x1: float, y1: float, z1: float,
):
    """Create an axis-aligned box trimesh.
    创建一个轴对齐的长方体 trimesh。
    """
    trimesh = _get_trimesh()
    vertices = np.array([
        [x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0],
        [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1],
    ], dtype=np.float64)
    faces = np.array([
        [0, 2, 1], [0, 3, 2],  # bottom
        [4, 5, 6], [4, 6, 7],  # top
        [0, 1, 5], [0, 5, 4],  # front
        [2, 3, 7], [2, 7, 6],  # back
        [0, 4, 7], [0, 7, 3],  # left
        [1, 2, 6], [1, 6, 5],  # right
    ], dtype=np.int64)
    return trimesh.Trimesh(vertices=vertices, faces=faces, process=False)


# ---------------------------------------------------------------------------
# Preview / Legend Image
# ---------------------------------------------------------------------------

def _generate_legend_image(
    recipes: list[RecipeSwatchItem],
    cols: int,
    rows: int,
) -> Image.Image:
    """Generate a color-legend PNG mapping grid positions to recipes.
    生成一张色卡图，标注网格位置与配方的对应关系。

    Layout: each cell shows the result color swatch, grid coordinate (row, col),
    result hex, and the 5-layer recipe abbreviated as color initials.
    """
    cell_w, cell_h = 200, 100
    pad = 12
    img_w = cols * cell_w + (cols + 1) * pad
    img_h = rows * cell_h + (rows + 1) * pad

    img = Image.new("RGB", (img_w, img_h), (245, 245, 245))
    draw = ImageDraw.Draw(img)

    try:
        font = ImageFont.truetype("arial.ttf", 13)
        font_sm = ImageFont.truetype("arial.ttf", 11)
        font_lg = ImageFont.truetype("arial.ttf", 16)
    except (OSError, IOError):
        font = ImageFont.load_default()
        font_sm = font
        font_lg = font

    for idx, recipe in enumerate(recipes):
        c = idx % cols
        r = idx // cols
        x0 = pad + c * (cell_w + pad)
        y0 = pad + r * (cell_h + pad)

        # Cell background
        draw.rounded_rectangle(
            [x0, y0, x0 + cell_w, y0 + cell_h],
            radius=6,
            fill=(255, 255, 255),
            outline=(200, 200, 200),
        )

        # Result color swatch
        swatch_size = 40
        sx, sy = x0 + 8, y0 + (cell_h - swatch_size) // 2
        result_rgb = _hex_to_rgb(recipe.result_hex)
        draw.rounded_rectangle(
            [sx, sy, sx + swatch_size, sy + swatch_size],
            radius=4,
            fill=result_rgb,
            outline=(180, 180, 180),
        )

        # Text area
        tx = sx + swatch_size + 10
        ty = y0 + 8

        # Grid coordinate
        coord = f"[{r + 1},{c + 1}]"
        draw.text((tx, ty), coord, fill=(100, 100, 100), font=font_lg)
        ty += 20

        # Hex
        draw.text((tx, ty), recipe.result_hex, fill=(60, 60, 60), font=font)
        ty += 16

        # Layer recipe (abbreviated names)
        layer_names = []
        for si in recipe.selected_indices:
            if si < len(recipe.base_color_names):
                name = recipe.base_color_names[si]
                layer_names.append(name[:4])
            else:
                layer_names.append("?")
        recipe_text = " > ".join(layer_names)
        draw.text((tx, ty), recipe_text, fill=(120, 120, 120), font=font_sm)

        # Draw 5 mini color dots at bottom of cell
        dot_y = y0 + cell_h - 16
        dot_r = 5
        for li, si in enumerate(recipe.selected_indices):
            if si < len(recipe.base_color_hexes):
                dot_color = _hex_to_rgb(recipe.base_color_hexes[si])
            else:
                dot_color = (128, 128, 128)
            dx = tx + li * (dot_r * 2 + 4)
            draw.ellipse(
                [dx, dot_y, dx + dot_r * 2, dot_y + dot_r * 2],
                fill=dot_color,
                outline=(180, 180, 180),
            )

    return img


# ---------------------------------------------------------------------------
# 3MF Generation
# ---------------------------------------------------------------------------

def _add_white_grid(
    material_meshes: dict[str, list],
    rows: int, cols: int,
    block_size_mm: float, gap_mm: float,
    board_w: float, board_h: float,
    z_base: float, z_top: float,
    backing_z0: float, backing_z1: float,
) -> None:
    """Add white grid frame: base plate + grid walls between cells.
    添加白色网格框：底板 + 网格墙。

    Args:
        z_base/z_top: Full-height range for grid walls.
        backing_z0/backing_z1: Range for the solid base plate.
    """
    # Solid base plate
    material_meshes[_GRID_MATERIAL_NAME].append(
        _build_box_mesh(0, 0, backing_z0, board_w, board_h, backing_z1)
    )
    # Horizontal bars
    for r in range(rows + 1):
        bar_y = r * (block_size_mm + gap_mm)
        material_meshes[_GRID_MATERIAL_NAME].append(
            _build_box_mesh(0, bar_y, z_base, board_w, bar_y + gap_mm, z_top)
        )
    # Vertical bars
    for c in range(cols + 1):
        bar_x = c * (block_size_mm + gap_mm)
        material_meshes[_GRID_MATERIAL_NAME].append(
            _build_box_mesh(bar_x, 0, z_base, bar_x + gap_mm, board_h, z_top)
        )


def _fill_empty_cells_white(
    material_meshes: dict[str, list],
    n_recipes: int, total_cells: int,
    cols: int,
    block_size_mm: float, gap_mm: float,
    z0: float, z1: float,
) -> None:
    """Fill unused grid cells with white blocks so nothing floats.
    用白色填充未使用的网格单元格，防止观赏面悬空。
    """
    for cell_idx in range(n_recipes, total_cells):
        c = cell_idx % cols
        r = cell_idx // cols
        cx = gap_mm + c * (block_size_mm + gap_mm)
        cy = gap_mm + r * (block_size_mm + gap_mm)
        material_meshes[_GRID_MATERIAL_NAME].append(
            _build_box_mesh(cx, cy, z0, cx + block_size_mm, cy + block_size_mm, z1)
        )


def _add_color_layers(
    material_meshes: dict[str, list],
    recipes: list[RecipeSwatchItem],
    cols: int,
    block_size_mm: float, gap_mm: float,
    layer_h: float, z_start: float,
    reverse: bool = False,
) -> None:
    """Stack 5 color layers per recipe in grid cells.
    为每个配方在网格单元格中堆叠 5 层颜色。

    When *reverse* is True the layer order is inverted (for double-sided top).
    """
    num_layers = PrinterConfig.COLOR_LAYERS
    for recipe_idx, recipe in enumerate(recipes):
        c = recipe_idx % cols
        r = recipe_idx // cols
        cell_x = gap_mm + c * (block_size_mm + gap_mm)
        cell_y = gap_mm + r * (block_size_mm + gap_mm)

        for layer_i, color_idx in enumerate(recipe.selected_indices):
            if color_idx >= len(recipe.base_color_names):
                continue
            color_name = recipe.base_color_names[color_idx]
            if reverse:
                inv_i = (num_layers - 1) - layer_i
            else:
                inv_i = layer_i
            z_bot = z_start + inv_i * layer_h
            z_top = z_bot + layer_h
            material_meshes[color_name].append(
                _build_box_mesh(
                    cell_x, cell_y, z_bot,
                    cell_x + block_size_mm, cell_y + block_size_mm, z_top,
                )
            )


def generate_recipe_swatch(
    recipes: list[RecipeSwatchItem],
    block_size_mm: float = 15.0,
    gap_mm: float = 2.0,
    cols: int = 0,
    structure_mode: str = "Single-sided",
    printer_id: str = "bambu-h2d",
    slicer: str = "BambuStudio",
    nozzle_size: str = "0.4",
) -> tuple[Optional[str], Optional[Image.Image], str]:
    """Generate a 3MF file with colored swatch blocks for recipe verification.
    生成包含彩色色块的 3MF 文件，用于配方验证。

    Structure modes:
    - **Single-sided (单面)**: Color layers at bottom (Z = 0), white backing on
      top. The viewing face is the print-bed side; an X-mirror is applied so
      the image appears correct when the card is flipped.
    - **Double-sided (双面)**: Color layers on both sides of a central white
      backing — viewable from top and bottom.

    Empty grid cells are filled with white so nothing floats when the viewing
    face is downward.

    Args:
        recipes: List of recipe swatch items. (配方列表)
        block_size_mm: Width and height of each block in mm. (每块尺寸 mm)
        gap_mm: Width of white grid lines between blocks in mm. (白色网格线宽 mm)
        cols: Columns per row; 0 = auto (ceil(sqrt(n))). (每行列数; 0 = 自动)
        structure_mode: "Single-sided" / "Double-sided". (结构模式)
        printer_id: Printer profile identifier. (打印机配置 ID)
        slicer: Slicer software identifier. (切片软件 ID)
        nozzle_size: Nozzle size variant for template selection. (模板选择使用的喷嘴尺寸)

    Returns:
        (output_path, preview_image, status_message).
    """
    if not recipes:
        return None, None, "No recipes provided"

    trimesh = _get_trimesh()
    from utils.bambu_3mf_writer import export_scene_with_bambu_metadata

    layer_h = PrinterConfig.LAYER_HEIGHT
    color_layers = PrinterConfig.COLOR_LAYERS
    backing_mm = PrinterConfig.BACKING_MM
    backing_layers = int(backing_mm / layer_h)
    color_h = color_layers * layer_h
    backing_h = backing_layers * layer_h

    is_double = "双面" in structure_mode or "Double" in structure_mode

    # --- Material palette ---
    material_map: dict[str, tuple[int, int, int]] = {
        _GRID_MATERIAL_NAME: _hex_to_rgb(_GRID_MATERIAL_HEX),
    }
    for recipe in recipes:
        for idx in recipe.selected_indices:
            if idx < len(recipe.base_color_names):
                name = recipe.base_color_names[idx]
                hex_c = recipe.base_color_hexes[idx] if idx < len(recipe.base_color_hexes) else "#808080"
                if name not in material_map:
                    material_map[name] = _hex_to_rgb(hex_c)

    slot_names = list(material_map.keys())
    preview_colors = {i: (*material_map[name], 255) for i, name in enumerate(slot_names)}
    slot_index_of = {name: i for i, name in enumerate(slot_names)}

    # --- Grid layout ---
    n = len(recipes)
    if cols <= 0:
        cols = min(n, max(1, int(math.ceil(math.sqrt(n)))))
    else:
        cols = min(cols, n)
    rows = int(math.ceil(n / cols))
    total_cells = rows * cols

    board_w = gap_mm + cols * (block_size_mm + gap_mm)
    board_h = gap_mm + rows * (block_size_mm + gap_mm)

    mode_label = "double-sided" if is_double else "single-sided"
    _log.info(
        f"[RECIPE_SWATCH] Generating {n} swatches in {rows}x{cols} grid, "
        f"block={block_size_mm}mm, gap={gap_mm}mm, mode={mode_label}, "
        f"board={board_w:.1f}x{board_h:.1f}mm"
    )

    # --- Build meshes ---
    material_meshes: dict[str, list] = {name: [] for name in slot_names}

    if is_double:
        # Double-sided: bottom colors | backing | top colors (reversed)
        # Z layout:
        #   [0, color_h)             bottom color layers
        #   [color_h, color_h+backing_h)  white backing
        #   [color_h+backing_h, 2*color_h+backing_h)  top color layers (reversed)
        z_total = 2 * color_h + backing_h

        _add_white_grid(
            material_meshes, rows, cols, block_size_mm, gap_mm,
            board_w, board_h,
            z_base=0, z_top=z_total,
            backing_z0=color_h, backing_z1=color_h + backing_h,
        )
        _fill_empty_cells_white(
            material_meshes, n, total_cells, cols,
            block_size_mm, gap_mm, z0=0, z1=color_h,
        )
        _fill_empty_cells_white(
            material_meshes, n, total_cells, cols,
            block_size_mm, gap_mm, z0=color_h + backing_h, z1=z_total,
        )
        _add_color_layers(
            material_meshes, recipes, cols,
            block_size_mm, gap_mm, layer_h,
            z_start=0, reverse=False,
        )
        _add_color_layers(
            material_meshes, recipes, cols,
            block_size_mm, gap_mm, layer_h,
            z_start=color_h + backing_h, reverse=True,
        )
    else:
        # Single-sided: bottom colors | white backing on top
        # Z layout:
        #   [0, color_h)             color layers (viewing face = bottom)
        #   [color_h, color_h+backing_h)  white backing
        z_total = color_h + backing_h

        _add_white_grid(
            material_meshes, rows, cols, block_size_mm, gap_mm,
            board_w, board_h,
            z_base=0, z_top=z_total,
            backing_z0=color_h, backing_z1=z_total,
        )
        _fill_empty_cells_white(
            material_meshes, n, total_cells, cols,
            block_size_mm, gap_mm, z0=0, z1=color_h,
        )
        _add_color_layers(
            material_meshes, recipes, cols,
            block_size_mm, gap_mm, layer_h,
            z_start=0, reverse=False,
        )

    # --- Assemble scene ---
    scene = trimesh.Scene()
    valid_slot_names = []

    for mat_name in slot_names:
        boxes = material_meshes[mat_name]
        if not boxes:
            continue
        merged = trimesh.util.concatenate(boxes)
        mat_idx = slot_index_of[mat_name]
        merged.visual.face_colors = preview_colors[mat_idx]
        merged.metadata["name"] = mat_name
        scene.add_geometry(merged, node_name=mat_name, geom_name=mat_name)
        valid_slot_names.append(mat_name)

    if not valid_slot_names:
        return None, None, "No valid meshes generated"

    # Single-sided: X-mirror so the viewing face (bottom) appears correct
    # when the card is flipped after printing.
    if not is_double:
        mirror = np.array([
            [-1, 0, 0, board_w],
            [0, 1, 0, 0],
            [0, 0, 1, 0],
            [0, 0, 0, 1],
        ])
        for geom_name in list(scene.geometry.keys()):
            scene.geometry[geom_name].apply_transform(mirror)

    # --- Export 3MF ---
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    output_filename = f"RecipeSwatch_{n}x_{timestamp}.3mf"
    output_path = os.path.join(MODELS_DIR, output_filename)

    try:
        export_scene_with_bambu_metadata(
            scene=scene,
            output_path=output_path,
            slot_names=valid_slot_names,
            preview_colors=preview_colors,
            settings={
                "layer_height": str(layer_h),
                "initial_layer_height": str(layer_h),
                "wall_loops": "1",
                "top_shell_layers": "0",
                "bottom_shell_layers": "0",
                "sparse_infill_density": "100%",
                "sparse_infill_pattern": "zig-zag",
            },
            color_mode="Merged",
            printer_id=printer_id,
            slicer=slicer,
            nozzle_size=nozzle_size,
        )
    except (ValueError, TypeError, RuntimeError, OSError) as e:
        _log.exception(f"[RECIPE_SWATCH] Export failed: {e}")
        return None, None, f"3MF export failed: {e}"

    # --- Generate legend image ---
    legend_img = _generate_legend_image(recipes, cols, rows)

    _log.info(f"[RECIPE_SWATCH] Exported: {output_path}")
    return output_path, legend_img, f"Generated {n} recipe swatch(es)"
