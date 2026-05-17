"""Integration regression for large-format raster tile cover thumbnails.

中文标题：大画幅光栅模式分片封面缩略图集成回归测试

This test drives the cover-thumbnail wiring used by the large-format raster
generation path (``api/routers/converter/generate.py::_generate_large_format_raster``)
without booting the full converter pipeline. The raster path slices the
source PNG into per-tile PNGs (each becomes the worker's ``image_path``)
and the worker forwards that ``image_path`` as ``cover_source`` into
``export_scene_with_bambu_metadata``. We exercise the same surface by:

1. Constructing an R × C source PNG with a distinct bright color per cell.
2. Slicing the source PNG ourselves, mirroring the pixel-coordinate math in
   ``_generate_large_format_raster``.
3. Driving ``BambuStudio3MFWriter`` per tile with ``cover_source=tile_path``.
4. Decoding the resulting ``Auxiliaries/.thumbnails/thumbnail_middle.png`` and
   comparing against the expected reference (the same cell letterboxed to
   680 × 510 with white border).

Identifiability is the load-bearing property: for tile ``(r, c)``, the
decoded cover must be close to the ``(r, c)`` reference (mean abs diff
≤ 5/255), and clearly distinct from every other ``(r', c') ≠ (r, c)``
reference (mean abs diff > 5/255).

**Validates: Requirements 4.1, 4.2, 4.3, 4.4, 10.3 / Property 4**
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import numpy as np
import pytest
import trimesh
from PIL import Image

from utils.bambu_3mf_cover import COVER_THUMBNAIL_SPECS, _letterbox_fit
from utils.bambu_3mf_writer import BambuStudio3MFWriter


# ---------------------------------------------------------------------------
# Identifiability threshold (R10.3): mean abs diff over [0, 255] divided by
# 255 must stay ≤ 5/255 for the matching tile, > 5/255 for any other tile.
# ---------------------------------------------------------------------------
_IDENTIFIABILITY_THRESHOLD = 5.0 / 255.0


# A small palette of bright distinct colors so that any pair of cells
# differs by far more than the threshold even after PNG quantization +
# letterbox interpolation. Keys are stable (r, c) lookups; values are RGB.
# 用一组明亮且互相差异显著的色块，保证任意两片的像素均值差远大于
# 5/255 阈值，从而让"可识别性"断言可重复触发。
_TILE_COLOR_PALETTE: dict[tuple[int, int], tuple[int, int, int]] = {
    (0, 0): (220, 30, 40),     # red
    (0, 1): (30, 200, 60),     # green
    (0, 2): (40, 80, 220),     # blue
    (1, 0): (240, 200, 30),    # yellow
    (1, 1): (200, 40, 200),    # magenta
    (1, 2): (40, 200, 200),    # cyan
    (2, 0): (160, 90, 30),     # brown
    (2, 1): (90, 30, 160),     # purple
    (2, 2): (30, 160, 90),     # teal
}


def _build_source_png(
    rows: int,
    cols: int,
    cell_w: int,
    cell_h: int,
    out_path: Path,
) -> Path:
    """Build an R × C grid PNG; each cell filled with the palette color.

    Returns the path that was written.
    """

    arr = np.zeros((rows * cell_h, cols * cell_w, 3), dtype=np.uint8)
    for r in range(rows):
        for c in range(cols):
            color = _TILE_COLOR_PALETTE[(r, c)]
            arr[r * cell_h : (r + 1) * cell_h, c * cell_w : (c + 1) * cell_w, :] = color
    Image.fromarray(arr, mode="RGB").save(out_path, format="PNG")
    return out_path


def _slice_tile_png(
    full_img: Image.Image,
    rows: int,
    cols: int,
    r: int,
    c: int,
    total_w_mm: float,
    total_h_mm: float,
    tile_w_mm: float,
    tile_h_mm: float,
    out_path: Path,
) -> Path:
    """Slice the source PNG into one tile PNG using the same math as the raster path.

    Mirrors ``api/routers/converter/generate.py::_generate_large_format_raster``:
    px_per_mm_{x,y} = source_size / total_mm; integer-rounded crop bounds.
    """

    px_w, px_h = full_img.size
    px_per_mm_x = px_w / total_w_mm
    px_per_mm_y = px_h / total_h_mm

    x0_mm = c * tile_w_mm
    y0_mm = r * tile_h_mm
    x1_mm = min(x0_mm + tile_w_mm, total_w_mm)
    y1_mm = min(y0_mm + tile_h_mm, total_h_mm)

    px_x0 = int(round(x0_mm * px_per_mm_x))
    px_y0 = int(round(y0_mm * px_per_mm_y))
    px_x1 = min(int(round(x1_mm * px_per_mm_x)), px_w)
    px_y1 = min(int(round(y1_mm * px_per_mm_y)), px_h)

    full_img.crop((px_x0, px_y0, px_x1, px_y1)).save(out_path, format="PNG")
    return out_path


def _build_minimal_writer(out_path: Path, *, cover_source: str) -> BambuStudio3MFWriter:
    """Build a minimal 2-mesh writer; mirrors the integration test fixture."""

    writer = BambuStudio3MFWriter(
        str(out_path),
        settings={},
        color_mode="4-Color",
        printer_id="bambu-p1s",
        slicer="BambuStudio",
        nozzle_size="0.4",
        cover_source=cover_source,
    )
    a = trimesh.creation.box(extents=[2, 2, 2])
    a.metadata["bambu_material_name"] = "White"
    writer.add_mesh(a, "White", (255, 255, 255))
    b = trimesh.creation.box(extents=[2, 2, 2])
    b.apply_translation([4, 0, 0])
    b.metadata["bambu_material_name"] = "Red"
    writer.add_mesh(b, "Red", (220, 30, 40))
    return writer


def _decode_thumbnail_middle(threemf_path: Path) -> np.ndarray:
    """Decode ``Auxiliaries/.thumbnails/thumbnail_middle.png`` to a uint8 array."""

    with zipfile.ZipFile(threemf_path) as zf:
        data = zf.read(COVER_THUMBNAIL_SPECS[1].zip_path)  # middle = 680×510
    img = Image.open(io.BytesIO(data))
    img.load()
    assert img.mode == "RGB", "thumbnail_middle.png must be RGB"
    assert img.size == (680, 510), f"unexpected size {img.size}"
    return np.array(img, dtype=np.uint8)


def _build_reference_thumbnail_middle(tile_png_path: Path) -> np.ndarray:
    """Build the expected reference: tile PNG → letterbox to 680 × 510 white.

    Uses the same ``_letterbox_fit`` the writer uses internally so the
    reference and the writer's output share the same scaling kernel — the
    only allowed differences are PNG round-trip quantization.
    """

    with Image.open(tile_png_path) as src:
        src_rgb = src.convert("RGB")
    fitted = _letterbox_fit(src_rgb, (COVER_THUMBNAIL_SPECS[1].width, COVER_THUMBNAIL_SPECS[1].height))
    return np.array(fitted, dtype=np.uint8)


def _mean_abs_diff_normalized(decoded: np.ndarray, reference: np.ndarray) -> float:
    """Mean abs pixel diff over [0, 255], divided by 255.

    Matches the formula in tasks.md task 8 spec text:
    ``numpy.abs((decoded - reference).astype("int16")).mean() / 255``.
    """

    return float(np.abs(decoded.astype("int16") - reference.astype("int16")).mean()) / 255.0


# ---------------------------------------------------------------------------
# R × C identifiability matrix
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("rows,cols", [(1, 1), (2, 2), (3, 3)])
def test_raster_tile_cover_thumbnail_identifies_its_tile_region(
    tmp_path: Path,
    rows: int,
    cols: int,
) -> None:
    """For R × C ∈ {(1,1), (2,2), (3,3)}, every tile cover identifies its cell.

    R4.1 / R4.2 / R4.3 / R4.4: each tile's 3MF carries a cover that comes
    from that tile's own image_path (the sliced PNG), and no other tile's.

    R10.3: matching reference mean abs diff ≤ 5/255; non-matching reference
    diff strictly greater than the same threshold.
    """

    # Use cell sizes that exercise letterbox math non-trivially: a 4:3 cell
    # so the 680×510 (= 4:3) target keeps the cell aspect-aligned (zero
    # letterbox bars), while still passing through the real scaling kernel.
    cell_w_px, cell_h_px = 200, 150
    src_w_px = cols * cell_w_px
    src_h_px = rows * cell_h_px

    total_w_mm = float(cols) * 60.0
    total_h_mm = float(rows) * 45.0
    tile_w_mm = 60.0
    tile_h_mm = 45.0

    src_path = tmp_path / f"source_{rows}x{cols}.png"
    _build_source_png(rows, cols, cell_w_px, cell_h_px, src_path)

    # Slice all tile PNGs first (matches what _generate_large_format_raster does).
    tile_paths: dict[tuple[int, int], Path] = {}
    with Image.open(src_path) as full_img:
        full_img.load()
        for r in range(rows):
            for c in range(cols):
                tile_path = tmp_path / f"tile_R{r + 1}C{c + 1}.png"
                _slice_tile_png(
                    full_img,
                    rows,
                    cols,
                    r,
                    c,
                    total_w_mm,
                    total_h_mm,
                    tile_w_mm,
                    tile_h_mm,
                    tile_path,
                )
                tile_paths[(r, c)] = tile_path

    # Drive the writer per tile, identical to what the worker does internally.
    threemf_paths: dict[tuple[int, int], Path] = {}
    for (r, c), tile_path in tile_paths.items():
        out_3mf = tmp_path / f"out_R{r + 1}C{c + 1}.3mf"
        writer = _build_minimal_writer(out_3mf, cover_source=str(tile_path))
        writer.export()
        threemf_paths[(r, c)] = out_3mf

    # Pre-compute references (one per tile) using the same letterbox kernel.
    references: dict[tuple[int, int], np.ndarray] = {
        coord: _build_reference_thumbnail_middle(path)
        for coord, path in tile_paths.items()
    }

    # ---- Matching assertions: tile (r, c) cover ≈ tile (r, c) reference ----
    decoded_by_coord: dict[tuple[int, int], np.ndarray] = {}
    for (r, c), out_3mf in threemf_paths.items():
        decoded = _decode_thumbnail_middle(out_3mf)
        decoded_by_coord[(r, c)] = decoded

        ref_match = references[(r, c)]
        diff_match = _mean_abs_diff_normalized(decoded, ref_match)
        assert diff_match <= _IDENTIFIABILITY_THRESHOLD, (
            f"tile ({r},{c}) cover differs from its own reference by "
            f"{diff_match:.5f} > {_IDENTIFIABILITY_THRESHOLD:.5f}"
        )

    # ---- Non-matching assertions: tile (r, c) cover differs from every other tile's reference ----
    if rows * cols > 1:
        for (r, c), decoded in decoded_by_coord.items():
            for (r2, c2), ref_other in references.items():
                if (r, c) == (r2, c2):
                    continue
                diff_other = _mean_abs_diff_normalized(decoded, ref_other)
                assert diff_other > _IDENTIFIABILITY_THRESHOLD, (
                    f"tile ({r},{c}) cover unexpectedly close to ({r2},{c2}) "
                    f"reference: diff={diff_other:.5f} ≤ {_IDENTIFIABILITY_THRESHOLD:.5f}; "
                    "the cover is not identifiable."
                )


# ---------------------------------------------------------------------------
# Sanity: a single distinct tile must be cleanly distinguishable from the
# default white-letterbox area used for placeholders. Guards regressions
# where the writer accidentally falls back to the placeholder bundle for
# real tile inputs.
# ---------------------------------------------------------------------------


def test_raster_tile_cover_is_not_silent_placeholder_for_valid_tile(tmp_path: Path) -> None:
    """A real tile PNG must produce a non-placeholder cover (R4.5 implicit)."""

    cell = np.full((150, 200, 3), (220, 30, 40), dtype=np.uint8)
    src_path = tmp_path / "single_tile.png"
    Image.fromarray(cell, mode="RGB").save(src_path)

    out_3mf = tmp_path / "single.3mf"
    writer = _build_minimal_writer(out_3mf, cover_source=str(src_path))
    writer.export()

    decoded = _decode_thumbnail_middle(out_3mf)

    # Pure-white placeholder reference — what the writer would emit if the
    # source resolution policy fell through to silent placeholder.
    placeholder_ref = np.full_like(decoded, 255)
    diff_to_placeholder = _mean_abs_diff_normalized(decoded, placeholder_ref)
    assert diff_to_placeholder > _IDENTIFIABILITY_THRESHOLD, (
        f"valid tile cover collapsed to placeholder; diff={diff_to_placeholder:.5f}"
    )

    # And it should match its own reference within tolerance.
    expected = _build_reference_thumbnail_middle(src_path)
    diff_match = _mean_abs_diff_normalized(decoded, expected)
    assert diff_match <= _IDENTIFIABILITY_THRESHOLD, (
        f"valid tile cover does not match its own reference; diff={diff_match:.5f}"
    )
