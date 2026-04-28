"""Shared LUT card layout mapping utilities.

This module is the source of truth for calibration-card page dimensions and
row-major row-index mapping used by generation, extraction, and recipe lookup.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
import re
from typing import Sequence


EIGHT_COLOR_PAGE_CAPACITY = 1369
EIGHT_COLOR_FULL_TOTAL_RECIPES = 8**5


@dataclass(frozen=True)
class LutCardPage:
    """One physical or virtual LUT card page.

    单个物理或虚拟 LUT 色卡页。
    """

    page_index: int
    page_label: str
    card_index: int
    card_label: str
    start_index: int
    item_count: int
    data_rows: int
    data_cols: int
    padding: int
    physical_rows: int
    physical_cols: int

    @property
    def capacity(self) -> int:
        return self.data_rows * self.data_cols

    @property
    def grid_size(self) -> int:
        return self.data_cols

    def to_dict(self) -> dict[str, int | str]:
        return asdict(self)


@dataclass(frozen=True)
class LutCardLayout:
    """Resolved LUT layout containing all pages/cards.

    已解析的 LUT 布局，包含所有页/色卡。
    """

    color_mode: str
    total_count: int
    pages: tuple[LutCardPage, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "color_mode": self.color_mode,
            "total_count": self.total_count,
            "pages": [page.to_dict() for page in self.pages],
        }


@dataclass(frozen=True)
class LutCardCellCoordinate:
    """Resolved coordinate for one valid LUT row.

    单个有效 LUT 行对应的色卡坐标。
    """

    card_index: int
    card_label: str
    page_index: int
    page_label: str
    grid_size: int
    data_rows: int
    data_cols: int
    row: int
    col: int
    data_row: int
    data_col: int
    display_row: int
    display_col: int
    physical_row: int
    physical_col: int
    row_index: int

    def to_dict(self) -> dict[str, int | str]:
        return asdict(self)


@dataclass(frozen=True)
class LutCardNeighborhoodCell:
    """One cell in a LUT-card neighborhood."""

    card_index: int | None
    card_label: str | None
    page_index: int | None
    page_label: str | None
    grid_size: int | None
    data_rows: int | None
    data_cols: int | None
    row: int | None
    col: int | None
    data_row: int | None
    data_col: int | None
    display_row: int | None
    display_col: int | None
    physical_row: int | None
    physical_col: int | None
    row_index: int | None
    rgb: tuple[int, int, int] | None
    hex: str | None
    is_match: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _parse_page_number(page: object, default: int = 1) -> int:
    match = re.search(r"(\d+)", str(page))
    if match is None:
        return default
    page_number = int(match.group(1))
    return page_number if page_number >= 1 else default


def _make_page(
    *,
    page_index: int,
    page_label: str,
    card_label: str,
    start_index: int,
    item_count: int,
    data_rows: int,
    data_cols: int,
    padding: int = 1,
) -> LutCardPage:
    return LutCardPage(
        page_index=page_index,
        page_label=page_label,
        card_index=page_index,
        card_label=card_label,
        start_index=start_index,
        item_count=item_count,
        data_rows=data_rows,
        data_cols=data_cols,
        padding=padding,
        physical_rows=data_rows + (padding * 2),
        physical_cols=data_cols + (padding * 2),
    )


def _square_page(total_count: int) -> LutCardPage:
    grid_size = int(math.ceil(math.sqrt(max(total_count, 1))))
    return _make_page(
        page_index=0,
        page_label="1",
        card_label="1",
        start_index=0,
        item_count=max(total_count, 0),
        data_rows=grid_size,
        data_cols=grid_size,
        padding=0,
    )


def _full_8color_pages(total_count: int) -> tuple[LutCardPage, ...]:
    total_pages = int(math.ceil(total_count / EIGHT_COLOR_PAGE_CAPACITY))
    pages: list[LutCardPage] = []
    for page_index in range(total_pages):
        start_index = page_index * EIGHT_COLOR_PAGE_CAPACITY
        item_count = min(EIGHT_COLOR_PAGE_CAPACITY, total_count - start_index)
        pages.append(
            _make_page(
                page_index=page_index,
                page_label=str(page_index + 1),
                card_label=str(page_index + 1),
                start_index=start_index,
                item_count=item_count,
                data_rows=37,
                data_cols=37,
            )
        )
    return tuple(pages)


def resolve_lut_layout(color_mode: str | None, total_count: int) -> LutCardLayout:
    """Return the canonical card layout for a LUT row count.

    根据 LUT 行数返回规范色卡布局。
    """

    count = int(total_count)
    mode = str(color_mode or "")
    if count < 0:
        raise ValueError("total_count must be non-negative")

    if count == 32:
        pages = (
            _make_page(
                page_index=0,
                page_label="1",
                card_label="1",
                start_index=0,
                item_count=32,
                data_rows=6,
                data_cols=6,
            ),
        )
    elif count == 1024:
        pages = (
            _make_page(
                page_index=0,
                page_label="1",
                card_label="1",
                start_index=0,
                item_count=1024,
                data_rows=32,
                data_cols=32,
            ),
        )
    elif count == 1296:
        pages = (
            _make_page(
                page_index=0,
                page_label="1",
                card_label="1",
                start_index=0,
                item_count=1296,
                data_rows=36,
                data_cols=36,
            ),
        )
    elif count == 2468:
        pages = (
            _make_page(
                page_index=0,
                page_label="1",
                card_label="1",
                start_index=0,
                item_count=1024,
                data_rows=32,
                data_cols=32,
            ),
            _make_page(
                page_index=1,
                page_label="2",
                card_label="2",
                start_index=1024,
                item_count=1444,
                data_rows=38,
                data_cols=38,
            ),
        )
    elif count == 2738:
        pages = (
            _make_page(
                page_index=0,
                page_label="A",
                card_label="A",
                start_index=0,
                item_count=EIGHT_COLOR_PAGE_CAPACITY,
                data_rows=37,
                data_cols=37,
            ),
            _make_page(
                page_index=1,
                page_label="B",
                card_label="B",
                start_index=EIGHT_COLOR_PAGE_CAPACITY,
                item_count=EIGHT_COLOR_PAGE_CAPACITY,
                data_rows=37,
                data_cols=37,
            ),
        )
    elif count == EIGHT_COLOR_FULL_TOTAL_RECIPES:
        pages = _full_8color_pages(count)
    else:
        pages = (_square_page(count),)

    return LutCardLayout(color_mode=mode, total_count=count, pages=pages)


def infer_total_count_for_extraction(
    color_mode: str,
    *,
    eight_color_full_export: bool = False,
) -> int:
    """Infer the whole-LUT row count for extraction mode selection.

    根据提取模式推断整套 LUT 行数。
    """

    mode = str(color_mode)
    if mode in ("BW (Black & White)", "BW"):
        return 32
    if "8-Color" in mode:
        return EIGHT_COLOR_FULL_TOTAL_RECIPES if eight_color_full_export else 2738
    if "6-Color" in mode:
        return 1296
    if "5-Color Extended" in mode:
        return 2468
    return 1024


def resolve_extraction_page_layout(
    color_mode: str,
    total_count: int | None = None,
    *,
    page: object = "Page 1",
    eight_color_full_export: bool = False,
) -> LutCardPage:
    """Return the physical extraction page for a mode/page selection.

    返回指定模式/页码对应的物理提取页布局。
    """

    resolved_total = (
        infer_total_count_for_extraction(
            color_mode,
            eight_color_full_export=eight_color_full_export,
        )
        if total_count is None
        else int(total_count)
    )
    layout = resolve_lut_layout(color_mode, resolved_total)
    page_number = _parse_page_number(page)
    page_index = min(max(page_number - 1, 0), len(layout.pages) - 1)
    return layout.pages[page_index]


def localize_page_layout(page: LutCardPage, item_count: int | None = None) -> LutCardLayout:
    """Return a one-page layout whose row indexes are local to that page file."""

    local_page = LutCardPage(
        page_index=page.page_index,
        page_label=page.page_label,
        card_index=0,
        card_label=page.card_label,
        start_index=0,
        item_count=page.item_count if item_count is None else int(item_count),
        data_rows=page.data_rows,
        data_cols=page.data_cols,
        padding=page.padding,
        physical_rows=page.physical_rows,
        physical_cols=page.physical_cols,
    )
    return LutCardLayout(
        color_mode="",
        total_count=local_page.item_count,
        pages=(local_page,),
    )


def _page_for_card(layout: LutCardLayout, card_index: int) -> LutCardPage:
    for page in layout.pages:
        if page.card_index == card_index:
            return page
    raise ValueError(f"Card index {card_index} is outside LUT card range")


def _coordinate_from_page(page: LutCardPage, data_row: int, data_col: int) -> LutCardCellCoordinate:
    local_index = data_row * page.data_cols + data_col
    row_index = page.start_index + local_index
    return LutCardCellCoordinate(
        card_index=page.card_index,
        card_label=page.card_label,
        page_index=page.page_index,
        page_label=page.page_label,
        grid_size=page.grid_size,
        data_rows=page.data_rows,
        data_cols=page.data_cols,
        row=data_row,
        col=data_col,
        data_row=data_row,
        data_col=data_col,
        display_row=data_row + 1,
        display_col=data_col + 1,
        physical_row=data_row + page.padding,
        physical_col=data_col + page.padding,
        row_index=row_index,
    )


def cell_for_row_index(layout: LutCardLayout, row_index: int) -> LutCardCellCoordinate:
    """Map a global LUT row index to a resolved card coordinate."""

    idx = int(row_index)
    for page in layout.pages:
        local_index = idx - page.start_index
        if 0 <= local_index < page.item_count:
            data_row = int(local_index // page.data_cols)
            data_col = int(local_index % page.data_cols)
            return _coordinate_from_page(page, data_row, data_col)
    raise ValueError(f"Row index {row_index} is outside LUT card range")


def row_index_for_cell(
    layout: LutCardLayout,
    card_index: int,
    data_row: int,
    data_col: int,
) -> int | None:
    """Map a card data coordinate back to a valid global row index."""

    page = _page_for_card(layout, int(card_index))
    row = int(data_row)
    col = int(data_col)
    if row < 0 or col < 0 or row >= page.data_rows or col >= page.data_cols:
        return None
    local_index = row * page.data_cols + col
    if local_index >= page.item_count:
        return None
    return page.start_index + local_index


def cell_from_normalized_point(
    layout: LutCardLayout,
    *,
    card_index: int,
    x: float,
    y: float,
) -> LutCardCellCoordinate | None:
    """Resolve an image-relative click point to a valid LUT cell.

    ``x`` and ``y`` are normalized to the rendered LUT image content, not the
    letterbox area.
    """

    if not (0.0 <= float(x) < 1.0 and 0.0 <= float(y) < 1.0):
        return None
    page = _page_for_card(layout, int(card_index))
    data_col = min(int(float(x) * page.data_cols), page.data_cols - 1)
    data_row = min(int(float(y) * page.data_rows), page.data_rows - 1)
    row_index = row_index_for_cell(layout, page.card_index, data_row, data_col)
    if row_index is None:
        return None
    return cell_for_row_index(layout, row_index)


def overlay_bbox_for_cell(cell: LutCardCellCoordinate) -> dict[str, float]:
    """Return normalized overlay bounds for a resolved LUT cell."""

    return {
        "left": cell.data_col / cell.data_cols,
        "top": cell.data_row / cell.data_rows,
        "width": 1.0 / cell.data_cols,
        "height": 1.0 / cell.data_rows,
    }


def rgb_to_hex(rgb: Sequence[int]) -> str:
    r, g, b = (int(rgb[0]), int(rgb[1]), int(rgb[2]))
    return f"#{r:02X}{g:02X}{b:02X}"


def _empty_neighborhood_cell() -> LutCardNeighborhoodCell:
    return LutCardNeighborhoodCell(
        card_index=None,
        card_label=None,
        page_index=None,
        page_label=None,
        grid_size=None,
        data_rows=None,
        data_cols=None,
        row=None,
        col=None,
        data_row=None,
        data_col=None,
        display_row=None,
        display_col=None,
        physical_row=None,
        physical_col=None,
        row_index=None,
        rgb=None,
        hex=None,
        is_match=False,
    )


def build_neighborhood(
    layout: LutCardLayout,
    lut_rgb: Sequence[Sequence[int]],
    coordinate: LutCardCellCoordinate,
    *,
    match_row_index: int,
    radius: int,
) -> list[list[LutCardNeighborhoodCell]]:
    """Build a row-major neighborhood around a resolved LUT coordinate."""

    page = _page_for_card(layout, coordinate.card_index)
    rows: list[list[LutCardNeighborhoodCell]] = []
    radius_value = max(0, int(radius))
    for data_row in range(coordinate.data_row - radius_value, coordinate.data_row + radius_value + 1):
        cells: list[LutCardNeighborhoodCell] = []
        for data_col in range(coordinate.data_col - radius_value, coordinate.data_col + radius_value + 1):
            row_index = row_index_for_cell(layout, page.card_index, data_row, data_col)
            if row_index is None:
                cells.append(_empty_neighborhood_cell())
                continue
            rgb = tuple(int(v) for v in lut_rgb[row_index])
            cell = cell_for_row_index(layout, row_index)
            cells.append(
                LutCardNeighborhoodCell(
                    card_index=cell.card_index,
                    card_label=cell.card_label,
                    page_index=cell.page_index,
                    page_label=cell.page_label,
                    grid_size=cell.grid_size,
                    data_rows=cell.data_rows,
                    data_cols=cell.data_cols,
                    row=cell.row,
                    col=cell.col,
                    data_row=cell.data_row,
                    data_col=cell.data_col,
                    display_row=cell.display_row,
                    display_col=cell.display_col,
                    physical_row=cell.physical_row,
                    physical_col=cell.physical_col,
                    row_index=row_index,
                    rgb=rgb,
                    hex=rgb_to_hex(rgb),
                    is_match=row_index == int(match_row_index),
                )
            )
        rows.append(cells)
    return rows
