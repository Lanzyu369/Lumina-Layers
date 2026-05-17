"""
Lumina Studio — Material-Archive Recipe Swatch 3MF Generator.
Lumina Studio — 耗材档案配方色块 3MF 生成器。

Generates a multi-material 3MF containing one colored swatch block per
material-archive recipe, laid out in a grid with white grid lines. Also
produces a legend image mapping grid positions to recipe details.

Mirrors :mod:`core.recipe_swatch` but works with material directory names
and variable layer counts instead of fixed 5-layer LUT-based recipes.
"""

from __future__ import annotations

import logging
import math
import os
import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from config import MODELS_DIR, PrinterConfig

_log = logging.getLogger(__name__)

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
class MaterialRecipeSwatchItem:
    """Single material-archive recipe to render as a swatch block.
    单个耗材档案配方，渲染为一个色块。

    Attributes:
        directory_names: Material directory names in stacking order.
        material_names: User-facing names matching ``directory_names``.
        material_hexes: Hex colors matching ``directory_names``.
        result_hex: Predicted blended hex color.
        layer_height_mm: Per-layer thickness (mm).
        substrate: Substrate identifier.
    """
    directory_names: list[str]
    material_names: list[str]
    material_hexes: list[str]
    result_hex: str
    layer_height_mm: float = 0.08
    substrate: str = "white"


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _build_box_mesh(
    x0: float, y0: float, z0: float,
    x1: float, y1: float, z1: float,
):
    trimesh = _get_trimesh()
    vertices = np.array([
        [x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0],
        [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1],
    ], dtype=np.float64)
    faces = np.array([
        [0, 2, 1], [0, 3, 2],
        [4, 5, 6], [4, 6, 7],
        [0, 1, 5], [0, 5, 4],
        [2, 3, 7], [2, 7, 6],
        [0, 4, 7], [0, 7, 3],
        [1, 2, 6], [1, 6, 5],
    ], dtype=np.int64)
    return trimesh.Trimesh(vertices=vertices, faces=faces, process=False)


# ---------------------------------------------------------------------------
# Legend image
# ---------------------------------------------------------------------------

def _generate_legend_image(
    recipes: list[MaterialRecipeSwatchItem],
    cols: int,
    rows: int,
) -> Image.Image:
    """Generate a legend PNG mapping grid positions to material recipes.
    生成色卡图，标注网格位置与耗材配方的对应关系。
    """
    cell_w, cell_h = 220, 110
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

        draw.rounded_rectangle(
            [x0, y0, x0 + cell_w, y0 + cell_h],
            radius=6,
            fill=(255, 255, 255),
            outline=(200, 200, 200),
        )

        swatch_size = 40
        sx, sy = x0 + 8, y0 + (cell_h - swatch_size) // 2
        result_rgb = _hex_to_rgb(recipe.result_hex)
        draw.rounded_rectangle(
            [sx, sy, sx + swatch_size, sy + swatch_size],
            radius=4,
            fill=result_rgb,
            outline=(180, 180, 180),
        )

        tx = sx + swatch_size + 10
        ty = y0 + 8

        coord = f"[{r + 1},{c + 1}]"
        draw.text((tx, ty), coord, fill=(100, 100, 100), font=font_lg)
        ty += 20

        draw.text((tx, ty), recipe.result_hex, fill=(60, 60, 60), font=font)
        ty += 16

        layer_names = [n[:6] for n in reversed(recipe.material_names)]
        recipe_text = " > ".join(layer_names) if len(layer_names) <= 6 else (
            " > ".join(layer_names[:5]) + f" +{len(layer_names) - 5}"
        )
        draw.text((tx, ty), recipe_text, fill=(120, 120, 120), font=font_sm)

        dot_y = y0 + cell_h - 16
        dot_r = 5
        # Render dots in visible→substrate order to match the in-app UI list
        # (UI shows visible face first; ``material_hexes`` is substrate-first
        # per API schema, so reverse here for parity with what the user picks).
        ordered_hexes = list(reversed(recipe.material_hexes))
        max_dots = min(len(ordered_hexes), 10)
        for li in range(max_dots):
            try:
                dot_color = _hex_to_rgb(ordered_hexes[li])
            except (ValueError, IndexError):
                dot_color = (128, 128, 128)
            dx = tx + li * (dot_r * 2 + 4)
            draw.ellipse(
                [dx, dot_y, dx + dot_r * 2, dot_y + dot_r * 2],
                fill=dot_color,
                outline=(180, 180, 180),
            )

    return img


# ---------------------------------------------------------------------------
# 3MF generation
# ---------------------------------------------------------------------------

def _add_white_grid(
    material_meshes: dict[str, list],
    rows: int, cols: int,
    block_size_mm: float, gap_mm: float,
    board_w: float, board_h: float,
    z_base: float, z_top: float,
    backing_z0: float, backing_z1: float,
) -> None:
    material_meshes[_GRID_MATERIAL_NAME].append(
        _build_box_mesh(0, 0, backing_z0, board_w, board_h, backing_z1)
    )
    for r in range(rows + 1):
        bar_y = r * (block_size_mm + gap_mm)
        material_meshes[_GRID_MATERIAL_NAME].append(
            _build_box_mesh(0, bar_y, z_base, board_w, bar_y + gap_mm, z_top)
        )
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
    for cell_idx in range(n_recipes, total_cells):
        c = cell_idx % cols
        r = cell_idx // cols
        cx = gap_mm + c * (block_size_mm + gap_mm)
        cy = gap_mm + r * (block_size_mm + gap_mm)
        material_meshes[_GRID_MATERIAL_NAME].append(
            _build_box_mesh(cx, cy, z0, cx + block_size_mm, cy + block_size_mm, z1)
        )


def _add_material_color_layers(
    material_meshes: dict[str, list],
    recipes: list[MaterialRecipeSwatchItem],
    cols: int,
    block_size_mm: float, gap_mm: float,
    reverse: bool = False,
) -> None:
    """Stack per-recipe variable-length color layers in grid cells.
    为每个配方在网格单元格中堆叠变长颜色层。

    ``recipe.material_names`` follows the API schema convention:
    index ``0`` is the substrate-side layer, index ``-1`` is the topmost
    (viewer-facing) layer. For single-sided cards the print is X-mirrored so
    the bottom of the cell (``z = 0``) becomes the visible face after the user
    flips the card; we therefore place ``material_names[-1]`` at ``z = 0`` so
    the colour the user picked as the visible face shows on the visible face.

    With ``reverse=True`` the substrate→top mapping is inverted, used for the
    far face of double-sided cards so both faces present the same gradient
    from outside to substrate.
    """
    for recipe_idx, recipe in enumerate(recipes):
        c = recipe_idx % cols
        r = recipe_idx // cols
        cell_x = gap_mm + c * (block_size_mm + gap_mm)
        cell_y = gap_mm + r * (block_size_mm + gap_mm)

        layer_h = recipe.layer_height_mm
        num_layers = len(recipe.material_names)
        for layer_i in range(num_layers):
            mat_name = recipe.material_names[layer_i]
            # Default: substrate-first input → place top layer at z=0 so it
            # ends up on the visible face after the X-mirror flip.
            if reverse:
                inv_i = layer_i
            else:
                inv_i = (num_layers - 1) - layer_i
            z_bot = inv_i * layer_h
            z_top = z_bot + layer_h
            material_meshes[mat_name].append(
                _build_box_mesh(
                    cell_x, cell_y, z_bot,
                    cell_x + block_size_mm, cell_y + block_size_mm, z_top,
                )
            )


def generate_material_recipe_swatch(
    recipes: list[MaterialRecipeSwatchItem],
    block_size_mm: float = 15.0,
    gap_mm: float = 2.0,
    cols: int = 0,
    structure_mode: str = "Single-sided",
    printer_id: str = "bambu-h2d",
    slicer: str = "BambuStudio",
    nozzle_size: str = "0.4",
) -> tuple[Optional[str], Optional[Image.Image], str]:
    """Generate a 3MF with colored swatch blocks for material-archive recipes.
    生成包含彩色色块的 3MF 文件，用于耗材档案配方验证。

    Unlike :func:`core.recipe_swatch.generate_recipe_swatch`, each recipe can
    have a variable number of layers and each layer is identified by material
    name (from the saved material archive) rather than a fixed 5-colour index.

    Args:
        recipes: List of material recipe swatch items.
        block_size_mm: Width and height of each block (mm).
        gap_mm: Width of white grid lines (mm).
        cols: Columns per row; 0 = auto.
        structure_mode: ``"Single-sided"`` or ``"Double-sided"``.
        printer_id: Printer profile identifier.
        slicer: Slicer software identifier.
        nozzle_size: Nozzle size variant.

    Returns:
        ``(output_path, legend_image, status_message)``.
    """
    if not recipes:
        return None, None, "No recipes provided"

    trimesh = _get_trimesh()
    from utils.bambu_3mf_writer import export_scene_with_bambu_metadata

    # Use the max layer count across all recipes to determine color height.
    max_layers = max(len(r.material_names) for r in recipes)
    layer_h = recipes[0].layer_height_mm
    backing_mm = PrinterConfig.BACKING_MM
    backing_layers = int(backing_mm / layer_h)
    color_h = max_layers * layer_h
    backing_h = backing_layers * layer_h

    is_double = "Double" in structure_mode or "\u53cc\u9762" in structure_mode

    # --- Material palette ---
    material_map: dict[str, tuple[int, int, int]] = {
        _GRID_MATERIAL_NAME: _hex_to_rgb(_GRID_MATERIAL_HEX),
    }
    for recipe in recipes:
        for i, mat_name in enumerate(recipe.material_names):
            if mat_name not in material_map:
                hex_c = recipe.material_hexes[i] if i < len(recipe.material_hexes) else "#808080"
                material_map[mat_name] = _hex_to_rgb(hex_c)

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
        f"Generating {n} material swatches in {rows}x{cols} grid, "
        f"block={block_size_mm}mm, gap={gap_mm}mm, mode={mode_label}, "
        f"board={board_w:.1f}x{board_h:.1f}mm"
    )

    # --- Build meshes ---
    material_meshes: dict[str, list] = {name: [] for name in slot_names}

    if is_double:
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
        _add_material_color_layers(
            material_meshes, recipes, cols,
            block_size_mm, gap_mm, reverse=False,
        )
        # Top side mirrors the bottom: ``material_names[-1]`` is the
        # outward-facing layer of this side, so we place it at the outermost
        # z (``z_total``) and stack downward toward the central backing.
        for recipe_idx, recipe in enumerate(recipes):
            c = recipe_idx % cols
            r = recipe_idx // cols
            cell_x = gap_mm + c * (block_size_mm + gap_mm)
            cell_y = gap_mm + r * (block_size_mm + gap_mm)
            num_layers = len(recipe.material_names)
            lh = recipe.layer_height_mm
            for layer_i in range(num_layers):
                mat_name = recipe.material_names[layer_i]
                # Substrate-first input → top side: place index 0 nearest the
                # central backing and index -1 at the outermost z.
                z_bot = color_h + backing_h + layer_i * lh
                z_top = z_bot + lh
                material_meshes[mat_name].append(
                    _build_box_mesh(
                        cell_x, cell_y, z_bot,
                        cell_x + block_size_mm, cell_y + block_size_mm, z_top,
                    )
                )
    else:
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
        _add_material_color_layers(
            material_meshes, recipes, cols,
            block_size_mm, gap_mm, reverse=False,
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
    output_filename = f"MaterialRecipeSwatch_{n}x_{timestamp}.3mf"
    output_path = os.path.join(MODELS_DIR, output_filename)

    try:
        # 无原图，封面走静默占位（不发 WARNING）
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
                "bottom_shell_layers": "1",
                "bottom_surface_pattern": "monotonicline",
                "elefant_foot_compensation": "0",
                "sparse_infill_density": "100%",
                "sparse_infill_pattern": "zig-zag",
            },
            color_mode="Merged",
            printer_id=printer_id,
            slicer=slicer,
            nozzle_size=nozzle_size,
            cover_source=None,
        )
    except (ValueError, TypeError, RuntimeError, OSError) as e:
        _log.exception(f"Export failed: {e}")
        return None, None, f"3MF export failed: {e}"

    legend_img = _generate_legend_image(recipes, cols, rows)

    _log.info(f"Exported material recipe swatch: {output_path}")
    return output_path, legend_img, f"Generated {n} material recipe swatch(es)"
