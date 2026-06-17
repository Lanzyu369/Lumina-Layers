import pytest

from core.lut_card_layout import (
    cell_for_row_index,
    build_neighborhood,
    cell_from_normalized_point,
    overlay_bbox_for_cell,
    localize_page_layout,
    resolve_extraction_page_layout,
    resolve_lut_layout,
    row_index_for_cell,
)


def test_resolve_standard_single_page_layouts() -> None:
    cases = [
        (32, 6, 6, 8, 8, 31, (5, 1), (6, 2)),
        (1024, 32, 32, 34, 34, 1023, (31, 31), (32, 32)),
        (1296, 36, 36, 38, 38, 1295, (35, 35), (36, 36)),
    ]

    for total, rows, cols, physical_rows, physical_cols, row_index, data_rc, physical_rc in cases:
        layout = resolve_lut_layout("test-mode", total)

        assert len(layout.pages) == 1
        page = layout.pages[0]
        assert page.item_count == total
        assert page.data_rows == rows
        assert page.data_cols == cols
        assert page.physical_rows == physical_rows
        assert page.physical_cols == physical_cols

        cell = cell_for_row_index(layout, row_index)
        assert (cell.data_row, cell.data_col) == data_rc
        assert (cell.physical_row, cell.physical_col) == physical_rc
        assert row_index_for_cell(layout, cell.card_index, cell.data_row, cell.data_col) == row_index


def test_resolve_1024_extended_page_1_layout_uses_wide_padding() -> None:
    layout = resolve_lut_layout("5-Color Extended", 1024)

    assert len(layout.pages) == 1
    page = layout.pages[0]
    assert page.item_count == 1024
    assert page.data_rows == 32
    assert page.data_cols == 32
    assert page.padding == 4
    assert page.physical_rows == 40
    assert page.physical_cols == 40

    tail = cell_for_row_index(layout, 1023)
    assert (tail.data_row, tail.data_col) == (31, 31)
    assert (tail.physical_row, tail.physical_col) == (35, 35)


def test_resolve_2468_extended_layout_preserves_two_page_order() -> None:
    layout = resolve_lut_layout("5-Color Extended", 2468)

    assert [
        (
            p.start_index,
            p.item_count,
            p.data_rows,
            p.data_cols,
            p.padding,
            p.physical_rows,
            p.physical_cols,
        )
        for p in layout.pages
    ] == [
        (0, 1024, 32, 32, 4, 40, 40),
        (1024, 1444, 38, 38, 1, 40, 40),
    ]

    page_1_tail = cell_for_row_index(layout, 1023)
    page_2_head = cell_for_row_index(layout, 1024)

    assert page_1_tail.page_index == 0
    assert (page_1_tail.data_row, page_1_tail.data_col) == (31, 31)
    assert (page_1_tail.physical_row, page_1_tail.physical_col) == (35, 35)
    assert page_2_head.page_index == 1
    assert (page_2_head.data_row, page_2_head.data_col) == (0, 0)
    assert (page_2_head.physical_row, page_2_head.physical_col) == (1, 1)


def test_resolve_2738_layout_preserves_legacy_a_b_split() -> None:
    layout = resolve_lut_layout("8-Color Max", 2738)

    assert [(p.card_label, p.start_index, p.item_count, p.data_cols) for p in layout.pages] == [
        ("A", 0, 1369, 37),
        ("B", 1369, 1369, 37),
    ]

    second_head = cell_for_row_index(layout, 1369)
    assert second_head.card_index == 1
    assert second_head.card_label == "B"
    assert (second_head.data_row, second_head.data_col) == (0, 0)
    assert (second_head.physical_row, second_head.physical_col) == (1, 1)
    assert (second_head.display_row, second_head.display_col) == (1, 1)


def test_resolve_32768_full_8color_layout_uses_24_pages_with_short_tail() -> None:
    layout = resolve_lut_layout("8-Color Max", 32768)

    assert len(layout.pages) == 24
    assert layout.pages[0].item_count == 1369
    assert layout.pages[-1].start_index == 23 * 1369
    assert layout.pages[-1].item_count == 1281

    tail = cell_for_row_index(layout, 32767)
    assert tail.page_index == 23
    assert tail.card_label == "24"
    assert (tail.data_row, tail.data_col) == (34, 22)
    assert row_index_for_cell(layout, tail.card_index, 34, 22) == 32767
    assert row_index_for_cell(layout, tail.card_index, 34, 23) is None


def test_fallback_layout_keeps_legacy_square_virtual_card() -> None:
    layout = resolve_lut_layout("dynamic", 3)

    assert len(layout.pages) == 1
    assert layout.pages[0].data_rows == 2
    assert layout.pages[0].data_cols == 2
    assert cell_for_row_index(layout, 2).display_row == 2
    assert row_index_for_cell(layout, 0, 1, 1) is None


def test_resolve_extraction_page_layout_selects_current_physical_page() -> None:
    five_color_page_2 = resolve_extraction_page_layout(
        "5-Color Extended",
        2468,
        page="Page 2",
        eight_color_full_export=False,
    )
    eight_color_full_tail = resolve_extraction_page_layout(
        "8-Color Max",
        32768,
        page="Page 24",
        eight_color_full_export=True,
    )

    assert five_color_page_2.start_index == 1024
    assert five_color_page_2.data_rows == 38
    assert five_color_page_2.item_count == 1444
    assert eight_color_full_tail.start_index == 23 * 1369
    assert eight_color_full_tail.item_count == 1281


def test_localize_page_layout_preserves_page_label_but_uses_file_local_indexes() -> None:
    page = resolve_extraction_page_layout(
        "5-Color Extended",
        2468,
        page="Page 2",
        eight_color_full_export=False,
    )

    local_layout = localize_page_layout(page)
    cell = cell_for_row_index(local_layout, 0)

    assert cell.page_index == 1
    assert cell.page_label == "2"
    assert cell.card_index == 0
    assert cell.row_index == 0
    assert (cell.data_row, cell.data_col) == (0, 0)


def test_cell_from_normalized_point_and_overlay_bbox_use_backend_layout() -> None:
    layout = resolve_lut_layout("4-Color (RYBW)", 1024)

    cell = cell_from_normalized_point(layout, card_index=0, x=1.5 / 32, y=2.5 / 32)
    assert cell is not None
    assert cell.row_index == 65
    assert (cell.data_row, cell.data_col) == (2, 1)

    bbox = overlay_bbox_for_cell(cell)
    assert bbox == pytest.approx(
        {
            "left": 1 / 32,
            "top": 2 / 32,
            "width": 1 / 32,
            "height": 1 / 32,
        }
    )


def test_build_neighborhood_marks_out_of_bounds_and_trailing_cells_empty() -> None:
    layout = resolve_lut_layout("dynamic", 3)
    center = cell_for_row_index(layout, 1)
    lut_rgb = [(255, 255, 255), (240, 10, 0), (0, 0, 0)]

    rows = build_neighborhood(layout, lut_rgb, center, match_row_index=1, radius=1)

    assert len(rows) == 3
    assert [len(row) for row in rows] == [3, 3, 3]
    assert rows[1][1].is_match is True
    assert rows[1][1].row_index == 1
    assert rows[0][0].row_index is None
    assert rows[2][2].row_index is None
