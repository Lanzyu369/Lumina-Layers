"""
Lumina Studio - Color Card SVG Generator
从调色板颜色列表生成验证色卡 SVG 文件。

Generates a validation colour-card SVG from a list of hex colours.
Layout mirrors ``color_card_36.svg``: 12 columns × N rows, 60×60 px
swatches on a white background with 10 px padding/gap, plus an
optional hex label beneath each swatch.
"""

from __future__ import annotations

import os
import tempfile
from typing import List

import numpy as np

from api.structured_logging import get_logger

log = get_logger(__name__)

# Layout constants (matching color_card_36.svg)
COLS = 12
SWATCH_SIZE = 60
GAP = 10
PADDING = 10
LABEL_HEIGHT = 14  # space for hex label below swatch


def generate_color_card_svg(
    hex_colors: List[str],
    *,
    show_labels: bool = True,
    output_dir: str | None = None,
) -> str:
    """Generate a colour-card SVG and write it to a temp file.
    生成一张验证色卡 SVG 并写入临时文件。

    Args:
        hex_colors: List of ``#RRGGBB`` hex strings (with or without ``#``).
        show_labels: If True, render the hex value below each swatch.
        output_dir: Directory for the temp file; uses system default if None.

    Returns:
        Absolute path to the generated SVG file.
    """
    if not hex_colors:
        raise ValueError("hex_colors must not be empty")

    # Normalize: ensure '#' prefix
    colors = [c if c.startswith("#") else f"#{c}" for c in hex_colors]

    n = len(colors)
    rows = (n + COLS - 1) // COLS

    cell_h = SWATCH_SIZE + (LABEL_HEIGHT if show_labels else 0)
    width = PADDING * 2 + COLS * SWATCH_SIZE + (COLS - 1) * GAP
    height = PADDING * 2 + rows * cell_h + (rows - 1) * GAP

    lines: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg"',
        f'     viewBox="0 0 {width} {height}"',
        f'     width="{width}" height="{height}"',
        f'     shape-rendering="crispEdges">',
        f'  <rect x="0" y="0" width="{width}" height="{height}" fill="#FFFFFF"/>',
    ]

    for idx, color in enumerate(colors):
        col = idx % COLS
        row = idx // COLS
        x = PADDING + col * (SWATCH_SIZE + GAP)
        y = PADDING + row * (cell_h + GAP)
        lines.append(
            f'  <rect x="{x}" y="{y}" width="{SWATCH_SIZE}" '
            f'height="{SWATCH_SIZE}" fill="{color.upper()}"/>'
        )
        if show_labels:
            lx = x + SWATCH_SIZE // 2
            ly = y + SWATCH_SIZE + LABEL_HEIGHT - 2
            lines.append(
                f'  <text x="{lx}" y="{ly}" text-anchor="middle" '
                f'font-size="8" font-family="monospace" fill="#333333">'
                f"{color.upper()}</text>"
            )

    lines.append("</svg>")

    svg_content = "\n".join(lines)

    fd, svg_path = tempfile.mkstemp(suffix=".svg", dir=output_dir)
    os.close(fd)
    with open(svg_path, "w", encoding="utf-8") as f:
        f.write(svg_content)

    log.info(
        "Color card SVG generated",
        extra={
            "event": "color_card_svg_generated",
            "color_count": n,
            "rows": rows,
            "svg_path": svg_path,
        },
    )
    return svg_path


def _hex_to_rgb(hex_str: str) -> tuple[int, int, int]:
    """Parse ``#RRGGBB`` to (R, G, B)."""
    h = hex_str.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def render_color_card_image(
    hex_colors: List[str],
    *,
    scale: float = 2.0,
) -> np.ndarray:
    """Render the colour card as a numpy RGBA image (no SVG dependency).
    将色卡渲染为 numpy RGBA 图像（无 SVG 依赖，纯像素绘制）。

    Uses the same layout constants as ``generate_color_card_svg`` so the
    preview matches the 3MF output.

    Args:
        hex_colors: ``#RRGGBB`` hex strings.
        scale: Pixel multiplier for sharper preview (default 2×).

    Returns:
        ``(H, W, 4)`` uint8 RGBA numpy array.
    """
    if not hex_colors:
        raise ValueError("hex_colors must not be empty")

    colors = [c if c.startswith("#") else f"#{c}" for c in hex_colors]
    n = len(colors)
    rows = (n + COLS - 1) // COLS

    s = scale
    sw = int(SWATCH_SIZE * s)
    gp = int(GAP * s)
    pd = int(PADDING * s)
    label_h = int(LABEL_HEIGHT * s)
    cell_h = sw + label_h

    w = int(pd * 2 + COLS * sw + (COLS - 1) * gp)
    h = int(pd * 2 + rows * cell_h + (rows - 1) * gp)

    img = np.full((h, w, 4), 255, dtype=np.uint8)  # white RGBA background

    for idx, color in enumerate(colors):
        c = idx % COLS
        r = idx // COLS
        x0 = pd + c * (sw + gp)
        y0 = pd + r * (cell_h + gp)
        rr, gg, bb = _hex_to_rgb(color)
        img[y0 : y0 + sw, x0 : x0 + sw] = [rr, gg, bb, 255]

    return img
