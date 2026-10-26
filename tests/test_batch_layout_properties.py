"""Property-based tests for ``core.batch_layout.layout_shelf_by_row``.

Lumina Studio - Batch 模式合并 3MF 单热床排布属性测试.

Validates the five named properties from the spec
``.kiro/specs/batch-mode-merged-3mf`` (design.md §Components 1, tasks.md
Task 5):

* **P1 No overlap** — any two placement bboxes have disjoint interiors.
* **P2 Spacing >= GAP_MM** — both intra-row X gaps and inter-row Y gaps
  are >= ``GAP_MM`` (2.0 mm).
* **P3 Determinism** — two calls with identical inputs yield equal results.
* **P4 exceeds_plate iff overflow** — the result's ``exceeds_plate`` flag
  is true iff at least one placement edge falls outside
  ``[0, plate_width_mm] x [0, plate_depth_mm]``.
* **P5 Input order preserved** — ``placements[i]`` corresponds to
  ``bboxes[i]`` one-to-one in placement order.

This test deliberately does **NOT** assert "all models fit on the plate";
the spec allows ``exceeds_plate=True`` and only requires that the flag
correctly reflects whether overflow occurred (P4).
"""

from __future__ import annotations

import os
import sys
from typing import Sequence

from hypothesis import given, settings
from hypothesis import strategies as st

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.batch_layout import GAP_MM, LayoutResult, Placement, XYBBox, layout_shelf_by_row

# Tolerance for floating-point edge-case comparisons. The algorithm only
# performs additions of finitely many ``GAP_MM`` / dimension values, so
# accumulated error stays well below this bound for the chosen ranges.
# 浮点比较容差. 算法只做有限次加法，误差远小于该值.
EPS: float = 1e-9


# ---------------------------------------------------------------------------
# Hypothesis strategies / 测试数据生成策略
# ---------------------------------------------------------------------------

# Per-task spec: width_mm / depth_mm in [10.0, 400.0].
_dim_strategy = st.floats(
    min_value=10.0,
    max_value=400.0,
    allow_nan=False,
    allow_infinity=False,
)


@st.composite
def _bbox_strategy(draw: st.DrawFn) -> XYBBox:
    """Generate a single ``XYBBox`` with both dimensions in [10.0, 400.0]."""
    w = draw(_dim_strategy)
    d = draw(_dim_strategy)
    return XYBBox(width_mm=w, depth_mm=d)


# Per-task spec: bboxes count in [1, 8].
_bboxes_strategy = st.lists(_bbox_strategy(), min_size=1, max_size=8)

# Per-task spec: plate_width_mm / plate_depth_mm in [50.0, 350.0].
_plate_strategy = st.floats(
    min_value=50.0,
    max_value=350.0,
    allow_nan=False,
    allow_infinity=False,
)


# ---------------------------------------------------------------------------
# Helpers / 辅助函数
# ---------------------------------------------------------------------------

def _group_rows(
    placements: Sequence[Placement],
    bboxes: Sequence[XYBBox],
) -> list[list[tuple[int, Placement, XYBBox]]]:
    """Group placements into rows by their ``ty_mm`` (input order preserved).

    按 ``ty_mm`` 把 placements 分组成行. 算法保证同一行内每个 placement
    共享相同的 ``ty_mm`` (= row_origin_y at placement time)，因此可直接
    用 ``ty_mm`` 作为行键. 返回值的行顺序按 ``ty_mm`` 升序; 行内顺序
    按输入顺序保持 (与 ``tx_mm`` 升序等价，由算法保证).

    Returns:
        A list of rows; each row is a list of ``(input_index, placement, bbox)``
        triples sorted by input order.
    """
    rows: dict[float, list[tuple[int, Placement, XYBBox]]] = {}
    for idx, (p, bb) in enumerate(zip(placements, bboxes)):
        rows.setdefault(p.ty_mm, []).append((idx, p, bb))
    # Row order = ascending ty_mm (matches the algorithm's wrap order).
    return [rows[k] for k in sorted(rows.keys())]


def _has_any_overflow(result: LayoutResult, bboxes: Sequence[XYBBox],
                      plate_width_mm: float, plate_depth_mm: float) -> bool:
    """Independent overflow recomputation for P4 oracle.

    P4 oracle: 独立重新计算是否越界，避免直接依赖被测代码内部的同名
    短路逻辑.
    """
    for p, bb in zip(result.placements, bboxes):
        if p.tx_mm < 0.0 or p.ty_mm < 0.0:
            return True
        if p.tx_mm + bb.width_mm > plate_width_mm + EPS:
            return True
        if p.ty_mm + bb.depth_mm > plate_depth_mm + EPS:
            return True
    return False


# ============================================================================
# Property 1 - No overlap between any two placement bboxes.
# **Validates: Requirements 3.3, 3.6**
# ============================================================================

@settings(max_examples=100, deadline=None)
@given(
    bboxes=_bboxes_strategy,
    plate_width_mm=_plate_strategy,
    plate_depth_mm=_plate_strategy,
)
def test_p1_no_overlap(
    bboxes: list[XYBBox],
    plate_width_mm: float,
    plate_depth_mm: float,
) -> None:
    """P1: 任意 i != j, placement bbox 内部不相交.

    Two axis-aligned bboxes ``A`` and ``B`` overlap (interior intersection
    non-empty) iff ``A.x0 < B.x1 and B.x0 < A.x1 and A.y0 < B.y1 and B.y0 < A.y1``.
    Strict inequalities are correct here: edge-touching counts as no overlap.
    """
    result = layout_shelf_by_row(bboxes, plate_width_mm, plate_depth_mm)
    placements = result.placements

    n = len(placements)
    for i in range(n):
        for j in range(i + 1, n):
            ax0 = placements[i].tx_mm
            ay0 = placements[i].ty_mm
            ax1 = ax0 + bboxes[i].width_mm
            ay1 = ay0 + bboxes[i].depth_mm
            bx0 = placements[j].tx_mm
            by0 = placements[j].ty_mm
            bx1 = bx0 + bboxes[j].width_mm
            by1 = by0 + bboxes[j].depth_mm

            x_overlap = ax0 + EPS < bx1 and bx0 + EPS < ax1
            y_overlap = ay0 + EPS < by1 and by0 + EPS < ay1
            assert not (x_overlap and y_overlap), (
                f"placements[{i}] and placements[{j}] overlap: "
                f"A=({ax0},{ay0})-({ax1},{ay1}) "
                f"B=({bx0},{by0})-({bx1},{by1})"
            )


# ============================================================================
# Property 2 - intra-row X gaps and inter-row Y gaps both >= GAP_MM.
# **Validates: Requirements 3.3, 3.6**
# ============================================================================

@settings(max_examples=100, deadline=None)
@given(
    bboxes=_bboxes_strategy,
    plate_width_mm=_plate_strategy,
    plate_depth_mm=_plate_strategy,
)
def test_p2_spacing_at_least_gap_mm(
    bboxes: list[XYBBox],
    plate_width_mm: float,
    plate_depth_mm: float,
) -> None:
    """P2: 行内 X 间距 >= GAP_MM, 行间 Y 间距 >= GAP_MM.

    Algorithm invariant: every placement within the same row shares the
    same ``ty_mm``, so grouping by ``ty_mm`` reliably reconstructs rows.
    """
    result = layout_shelf_by_row(bboxes, plate_width_mm, plate_depth_mm)
    rows = _group_rows(result.placements, bboxes)

    # Intra-row X gaps. Within a row, items are emitted in input order and
    # the algorithm assigns strictly increasing tx_mm, so adjacent gap =
    # next.tx_mm - (prev.tx_mm + prev.width_mm) >= GAP_MM.
    for row in rows:
        for k in range(len(row) - 1):
            _, prev_p, prev_bb = row[k]
            _, next_p, _ = row[k + 1]
            gap = next_p.tx_mm - (prev_p.tx_mm + prev_bb.width_mm)
            assert gap + EPS >= GAP_MM, (
                f"intra-row X gap {gap} < GAP_MM={GAP_MM}: "
                f"prev=({prev_p.tx_mm}+{prev_bb.width_mm}) next={next_p.tx_mm}"
            )

    # Inter-row Y gaps. Each row's "top" = max(ty_mm + depth_mm) over its
    # members. Next row's ty_mm must be at least prev_top + GAP_MM.
    for k in range(len(rows) - 1):
        prev_row = rows[k]
        next_row = rows[k + 1]
        prev_top = max(p.ty_mm + bb.depth_mm for _, p, bb in prev_row)
        next_y = next_row[0][1].ty_mm
        gap = next_y - prev_top
        assert gap + EPS >= GAP_MM, (
            f"inter-row Y gap {gap} < GAP_MM={GAP_MM}: "
            f"prev_top={prev_top} next_y={next_y}"
        )


# ============================================================================
# Property 3 - Determinism: same input -> equal result on two calls.
# **Validates: Requirements 3.3, 3.6**
# ============================================================================

@settings(max_examples=100, deadline=None)
@given(
    bboxes=_bboxes_strategy,
    plate_width_mm=_plate_strategy,
    plate_depth_mm=_plate_strategy,
)
def test_p3_determinism(
    bboxes: list[XYBBox],
    plate_width_mm: float,
    plate_depth_mm: float,
) -> None:
    """P3: 同一输入两次调用结果 ``==``."""
    r1 = layout_shelf_by_row(bboxes, plate_width_mm, plate_depth_mm)
    r2 = layout_shelf_by_row(bboxes, plate_width_mm, plate_depth_mm)
    assert r1 == r2, f"non-deterministic: {r1} != {r2}"


# ============================================================================
# Property 4 - ``exceeds_plate`` is equivalent to "any placement crosses the
# plate rectangle [0, plate_width_mm] x [0, plate_depth_mm]".
# **Validates: Requirements 3.4, 3.6, 10.1**
# ============================================================================

@settings(max_examples=100, deadline=None)
@given(
    bboxes=_bboxes_strategy,
    plate_width_mm=_plate_strategy,
    plate_depth_mm=_plate_strategy,
)
def test_p4_exceeds_plate_iff_overflow(
    bboxes: list[XYBBox],
    plate_width_mm: float,
    plate_depth_mm: float,
) -> None:
    """P4: ``exceeds_plate`` 严格等价于"是否存在 placement 越出热床"."""
    result = layout_shelf_by_row(bboxes, plate_width_mm, plate_depth_mm)
    expected = _has_any_overflow(result, bboxes, plate_width_mm, plate_depth_mm)
    assert result.exceeds_plate == expected, (
        f"exceeds_plate={result.exceeds_plate} but oracle={expected}; "
        f"placements={result.placements} bboxes={bboxes} "
        f"plate=({plate_width_mm},{plate_depth_mm})"
    )


# ============================================================================
# Property 5 - Input order preservation: placements[i] <-> bboxes[i] 1:1.
# **Validates: Requirements 3.3, 3.6**
# ============================================================================

@settings(max_examples=100, deadline=None)
@given(
    bboxes=_bboxes_strategy,
    plate_width_mm=_plate_strategy,
    plate_depth_mm=_plate_strategy,
)
def test_p5_input_order_preserved(
    bboxes: list[XYBBox],
    plate_width_mm: float,
    plate_depth_mm: float,
) -> None:
    """P5: ``placements[i]`` 与 ``bboxes[i]`` 一一对应, 不重排.

    Structural witness: walking the placements in input order, the
    ``(ty_mm, tx_mm)`` pair must be lexicographically non-decreasing -
    i.e., either we stay on the same row with strictly larger ``tx_mm``,
    or we move to a strictly larger ``ty_mm`` (a new row). Any reordering
    of the input would break this invariant.
    """
    result = layout_shelf_by_row(bboxes, plate_width_mm, plate_depth_mm)
    placements = result.placements

    # Length must match input.
    assert len(placements) == len(bboxes), (
        f"len(placements)={len(placements)} != len(bboxes)={len(bboxes)}"
    )

    # Walk in input order and assert lexicographic monotonicity.
    for i in range(len(placements) - 1):
        prev = placements[i]
        nxt = placements[i + 1]
        same_row = abs(nxt.ty_mm - prev.ty_mm) <= EPS
        if same_row:
            # Within a row, next item's tx_mm must be strictly greater than
            # the previous one's right edge (P2 already enforces the
            # GAP_MM lower bound; here we only need strict ordering).
            prev_right = prev.tx_mm + bboxes[i].width_mm
            assert nxt.tx_mm + EPS >= prev_right, (
                f"input order broken at i={i}: same row but "
                f"next.tx_mm={nxt.tx_mm} < prev_right={prev_right}"
            )
        else:
            # New row: ty_mm must strictly increase.
            assert nxt.ty_mm > prev.ty_mm, (
                f"input order broken at i={i}: ty_mm did not increase "
                f"({prev.ty_mm} -> {nxt.ty_mm})"
            )


def test_layout_centers_arranged_group_on_plate() -> None:
    """Example regression: shelf group is centered after row packing.

    This keeps the batch preview / merged 3MF from hugging the lower-left
    corner while preserving 2 mm gaps and input order.
    """
    result = layout_shelf_by_row(
        [
            XYBBox(width_mm=30.0, depth_mm=20.0),
            XYBBox(width_mm=30.0, depth_mm=20.0),
        ],
        plate_width_mm=256.0,
        plate_depth_mm=256.0,
    )

    assert result.placements == (
        Placement(tx_mm=97.0, ty_mm=118.0),
        Placement(tx_mm=129.0, ty_mm=118.0),
    )
    assert result.exceeds_plate is False


def test_layout_centers_oversized_group_and_reports_overflow() -> None:
    """Oversized layouts may become negative after centering, but still output."""
    result = layout_shelf_by_row(
        [XYBBox(width_mm=300.0, depth_mm=20.0)],
        plate_width_mm=256.0,
        plate_depth_mm=256.0,
    )

    assert result.placements == (Placement(tx_mm=-22.0, ty_mm=118.0),)
    assert result.exceeds_plate is True
