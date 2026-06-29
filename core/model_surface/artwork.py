from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import tempfile

from PIL import Image, ImageDraw

from config import TEMP_DIR
from core.model_surface.types import EdgeMode, ModelSurfaceError, SurfaceFootprint
from core.pipeline.processing_ops.svg_rasterizer import rasterize_svg


@dataclass(frozen=True)
class SurfacePlacement:
    """Artwork placement parameters in selected-surface coordinates.

    选中表面坐标系中的画面摆放参数。
    """

    mode: EdgeMode = EdgeMode.EDGE_TO_EDGE
    offset_x_mm: float = 0.0
    offset_y_mm: float = 0.0
    scale: float = 1.0
    rotation_deg: float = 0.0
    inset_mm: float = 0.0


@dataclass(frozen=True)
class RenderedSurfaceArtwork:
    """Rendered masked artwork image for model-surface preview/generation.

    用于模型覆面预览和生成的已渲染遮罩画面。
    """

    output_path: Path
    width_px: int
    height_px: int
    target_width_mm: float
    target_height_mm: float


def render_surface_artwork(
    *,
    source_path: str | Path,
    footprint: SurfaceFootprint,
    placement: SurfacePlacement,
    pixels_per_mm: int = 6,
    output_dir: str | Path = TEMP_DIR,
) -> RenderedSurfaceArtwork:
    """Render placed artwork into the selected surface bounds and mask holes.

    将画面按摆放参数渲染到选中表面范围内，并遮掉孔洞区域。

    Args:
        source_path: Source bitmap or SVG path.
            源位图或 SVG 路径。
        footprint: Selected surface footprint.
            选中表面的二维轮廓。
        placement: Scale, offset, rotation, and inset parameters.
            缩放、位移、旋转和内缩参数。
        pixels_per_mm: Output raster density.
            输出栅格密度。
        output_dir: Directory for the temporary rendered PNG.
            临时渲染 PNG 的输出目录。

    Returns:
        Rendered PNG path and physical/pixel dimensions.
        渲染 PNG 路径及物理/像素尺寸。
    """

    if pixels_per_mm <= 0:
        raise ModelSurfaceError("pixels_per_mm must be positive.")
    if placement.scale <= 0.0:
        raise ModelSurfaceError("Surface artwork scale must be positive.")

    target_width_mm = float(footprint.bounds_width_mm)
    target_height_mm = float(footprint.bounds_height_mm)
    if target_width_mm <= 0.0 or target_height_mm <= 0.0:
        raise ModelSurfaceError("Surface footprint bounds are invalid.")

    width_px = max(1, round(target_width_mm * pixels_per_mm))
    height_px = max(1, round(target_height_mm * pixels_per_mm))
    source = _load_source_rgba(Path(source_path), target_width_mm, float(pixels_per_mm))
    canvas = _place_source_on_canvas(
        source=source,
        width_px=width_px,
        height_px=height_px,
        pixels_per_mm=float(pixels_per_mm),
        placement=placement,
    )

    mask = _footprint_mask(footprint, width_px, height_px)
    canvas.putalpha(Image.composite(canvas.getchannel("A"), Image.new("L", canvas.size, 0), mask))

    output_root = Path(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    fd, output_path = tempfile.mkstemp(suffix=".png", dir=str(output_root))
    os.close(fd)
    canvas.save(output_path)
    return RenderedSurfaceArtwork(
        output_path=Path(output_path),
        width_px=width_px,
        height_px=height_px,
        target_width_mm=target_width_mm,
        target_height_mm=target_height_mm,
    )


def _load_source_rgba(source_path: Path, target_width_mm: float, pixels_per_mm: float) -> Image.Image:
    if source_path.suffix.lower() == ".svg":
        rgba = rasterize_svg(
            str(source_path),
            target_width_mm=target_width_mm,
            pixels_per_mm=pixels_per_mm,
            crop_to_content=False,
        )
        return Image.fromarray(rgba).convert("RGBA")
    return Image.open(source_path).convert("RGBA")


def _place_source_on_canvas(
    *,
    source: Image.Image,
    width_px: int,
    height_px: int,
    pixels_per_mm: float,
    placement: SurfacePlacement,
) -> Image.Image:
    canvas = Image.new("RGBA", (width_px, height_px), (0, 0, 0, 0))
    inset_px = max(0, round(placement.inset_mm * pixels_per_mm)) if placement.mode == EdgeMode.INSET else 0
    available_width = max(1, width_px - inset_px * 2)
    available_height = max(1, height_px - inset_px * 2)
    target_size = (
        max(1, round(available_width * placement.scale)),
        max(1, round(available_height * placement.scale)),
    )

    artwork = source.resize(target_size, Image.Resampling.LANCZOS)
    if placement.rotation_deg:
        artwork = artwork.rotate(
            placement.rotation_deg,
            resample=Image.Resampling.BICUBIC,
            expand=True,
        )

    x_px = round((width_px - artwork.width) / 2.0 + placement.offset_x_mm * pixels_per_mm)
    y_px = round((height_px - artwork.height) / 2.0 - placement.offset_y_mm * pixels_per_mm)
    _alpha_composite_clipped(canvas, artwork, x_px, y_px)
    return canvas


def _alpha_composite_clipped(canvas: Image.Image, overlay: Image.Image, x_px: int, y_px: int) -> None:
    src_left = max(0, -x_px)
    src_top = max(0, -y_px)
    dst_left = max(0, x_px)
    dst_top = max(0, y_px)
    width = min(overlay.width - src_left, canvas.width - dst_left)
    height = min(overlay.height - src_top, canvas.height - dst_top)
    if width <= 0 or height <= 0:
        return
    cropped = overlay.crop((src_left, src_top, src_left + width, src_top + height))
    canvas.alpha_composite(cropped, (dst_left, dst_top))


def _footprint_mask(footprint: SurfaceFootprint, width_px: int, height_px: int) -> Image.Image:
    min_x, min_y = footprint.bounds_min
    max_x, max_y = footprint.bounds_max
    scale_x = width_px / max(max_x - min_x, 1e-9)
    scale_y = height_px / max(max_y - min_y, 1e-9)

    def to_px(point: tuple[float, float]) -> tuple[int, int]:
        x_coord, y_coord = point
        return (
            round((x_coord - min_x) * scale_x),
            round((max_y - y_coord) * scale_y),
        )

    mask = Image.new("L", (width_px, height_px), 0)
    draw = ImageDraw.Draw(mask)
    draw.polygon([to_px(point) for point in footprint.outer], fill=255)
    for hole in footprint.holes:
        draw.polygon([to_px(point) for point in hole], fill=0)
    return mask
