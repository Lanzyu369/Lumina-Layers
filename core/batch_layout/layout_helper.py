"""Single-plate shelf-by-row layout helper for batch-mode merged 3MF.

批量模式合并 3MF 的单热床 shelf-by-row 排布 helper.

Design references:

* ``.kiro/specs/batch-mode-merged-3mf/requirements.md`` — Requirement 3
* ``.kiro/specs/batch-mode-merged-3mf/design.md`` — §Components 1, P1–P5

不变量 (must hold for every call) / Invariants:

1. Layout 不旋转、不缩放、不重排输入；输入顺序与输出顺序严格一致.
2. 行内相邻 X 间距 >= ``GAP_MM``，相邻行 Y 间距 >= ``GAP_MM``.
3. 任意两个 placement bbox 内部不相交.
4. Shelf 排布完成后，整组 bbox 会按其总包围框居中到热床中心.
5. ``exceeds_plate`` 当且仅当存在 placement 越出 ``[0, w] x [0, d]``.
6. 单 bbox 自身宽度 > ``plate_width_mm`` 时仍作为新行第一个对象放置，
   不拒绝、不缩放、不旋转 (Requirement 3 §2 末段).
7. 该模块完全 UI-agnostic：no logging, no I/O, no ``gap_mm`` parameter,
   no ``HTTPException``. 入参非法只抛 :class:`core.errors.CoreValidationError`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Sequence

from core.errors import CoreValidationError

# Module-level layout gap. NOT a function parameter, NOT exposed via API/UI.
# 排布间距常量 (mm). 不作为函数入参，不暴露到 API / UI / 配置层.
GAP_MM: Final[float] = 2.0


@dataclass(frozen=True)
class XYBBox:
    """XY footprint of a single object in millimetres.

    单个对象的 XY 包围盒 (mm).

    Attributes:
        width_mm: Extent along the X axis (must be > 0). X 方向尺寸.
        depth_mm: Extent along the Y axis (must be > 0). Y 方向尺寸.
    """

    width_mm: float
    depth_mm: float


@dataclass(frozen=True)
class Placement:
    """Translation (lower-left bbox corner) of one object on the plate.

    单个对象在热床上的 XY 平移 (bbox 左下角坐标，mm).
    当整组排布大于热床时，居中平移可能产生负坐标；这不是失败，
    只会通过 ``exceeds_plate`` 标识越界.

    Attributes:
        tx_mm: X translation of the bbox lower-left corner from plate origin.
        ty_mm: Y translation of the bbox lower-left corner from plate origin.
    """

    tx_mm: float
    ty_mm: float


@dataclass(frozen=True)
class LayoutResult:
    """Result of :func:`layout_shelf_by_row`.

    Layout 结果. ``placements[i]`` 与输入 ``bboxes[i]`` 一一对应.

    Attributes:
        placements: Per-input placements, in the original input order.
        exceeds_plate: ``True`` iff at least one placed bbox extends outside
            the plate rectangle ``[0, plate_width_mm] x [0, plate_depth_mm]``.
            任一对象越出热床矩形即为 ``True``; 越界本身不视为失败.
    """

    placements: tuple[Placement, ...]
    exceeds_plate: bool


def _validate_inputs(
    bboxes: Sequence[XYBBox],
    plate_width_mm: float,
    plate_depth_mm: float,
) -> None:
    """Validate plate and bbox dimensions.

    校验入参. 所有非法情况只抛 :class:`CoreValidationError`,
    严禁抛 ``ValueError`` / ``HTTPException``.
    """
    if plate_width_mm <= 0:
        raise CoreValidationError(
            f"plate_width_mm must be > 0, got {plate_width_mm!r}"
        )
    if plate_depth_mm <= 0:
        raise CoreValidationError(
            f"plate_depth_mm must be > 0, got {plate_depth_mm!r}"
        )
    for idx, bb in enumerate(bboxes):
        if bb.width_mm <= 0:
            raise CoreValidationError(
                f"bboxes[{idx}].width_mm must be > 0, got {bb.width_mm!r}"
            )
        if bb.depth_mm <= 0:
            raise CoreValidationError(
                f"bboxes[{idx}].depth_mm must be > 0, got {bb.depth_mm!r}"
            )


def layout_shelf_by_row(
    bboxes: Sequence[XYBBox],
    plate_width_mm: float,
    plate_depth_mm: float,
) -> LayoutResult:
    """Lay out ``bboxes`` on a single plate using shelf-by-row packing.

    单平面 shelf-by-row 排布. 不接受 ``gap_mm`` 入参 (使用模块级常量
    ``GAP_MM``); 不做 fit 校验 (越界仅置 ``exceeds_plate=True``).
    行内/行间排布先按左下角相对坐标计算，然后把整组总包围框平移到
    热床中心，使网页预览和合并 3MF 都默认居中.

    Algorithm (per Requirement 3 §2 / design §Components 1):

    * Iterate ``bboxes`` in input order; place each on the current row
      from left to right.
    * For each subsequent bbox, if ``current_row_x + GAP_MM + bb.width_mm``
      still fits within ``plate_width_mm``, place it on the same row with a
      ``GAP_MM`` horizontal gap from the previous bbox in that row.
    * Otherwise start a new row whose Y origin is the previous row's
      maximum depth edge plus ``GAP_MM``.
    * If a single bbox's ``width_mm`` exceeds ``plate_width_mm``, it is
      still placed as the first item of a new row (no rejection, no
      scaling, no rotation).

    Args:
        bboxes: Per-item XY footprints in upload order. 各 Successful_Item
            的 XY 包围盒，顺序与上传顺序保持一致.
        plate_width_mm: Plate extent along X (mm), must be > 0.
        plate_depth_mm: Plate extent along Y (mm), must be > 0.

    Returns:
        :class:`LayoutResult` whose ``placements`` length equals ``len(bboxes)``.

    Raises:
        CoreValidationError: ``plate_width_mm`` / ``plate_depth_mm`` <= 0,
            or any ``bb.width_mm`` / ``bb.depth_mm`` <= 0.
    """
    _validate_inputs(bboxes, plate_width_mm, plate_depth_mm)

    placements: list[Placement] = []
    if not bboxes:
        return LayoutResult(placements=(), exceeds_plate=False)

    # Row state. Row Y origin = lower-left Y of every bbox in the current row.
    row_origin_y: float = 0.0
    # Cursor X = next available X within the current row (lower-left of the
    # next bbox to be placed). Starts at row origin X = 0.
    cursor_x: float = 0.0
    # Maximum depth among all bboxes already placed in the current row.
    # Used to compute the Y origin of the next row when wrapping.
    row_max_depth: float = 0.0
    # ``True`` iff the next bbox is the very first item on its row (cursor
    # is at the row origin, no leading GAP_MM needed).
    is_first_in_row: bool = True

    for bb in bboxes:
        if is_first_in_row:
            # First bbox of the row sits flush against the row origin X = 0.
            # 单 bbox 宽度 > plate_width_mm 时仍按本分支放置 (不换行、不拒绝).
            tx = 0.0
            ty = row_origin_y
            placements.append(Placement(tx_mm=tx, ty_mm=ty))
            cursor_x = tx + bb.width_mm
            row_max_depth = bb.depth_mm
            is_first_in_row = False
            continue

        # Try to place bb on the current row with a GAP_MM separator from
        # the previous bbox.
        candidate_tx = cursor_x + GAP_MM
        candidate_right = candidate_tx + bb.width_mm
        if candidate_right <= plate_width_mm:
            # Fits on the current row.
            placements.append(Placement(tx_mm=candidate_tx, ty_mm=row_origin_y))
            cursor_x = candidate_right
            if bb.depth_mm > row_max_depth:
                row_max_depth = bb.depth_mm
        else:
            # Wrap to a new row. Y origin = previous row's max depth edge +
            # GAP_MM. New row's first bbox sits flush at row origin X = 0,
            # even when bb.width_mm > plate_width_mm.
            row_origin_y = row_origin_y + row_max_depth + GAP_MM
            tx = 0.0
            ty = row_origin_y
            placements.append(Placement(tx_mm=tx, ty_mm=ty))
            cursor_x = tx + bb.width_mm
            row_max_depth = bb.depth_mm
            # Already placed the first bbox of the new row, so the next
            # iteration is no longer "first in row".

    # Center the whole arranged group on the plate. This keeps the shelf
    # layout deterministic while avoiding the visually surprising "hug the
    # lower-left corner" result in previews and slicers.
    min_x = min(p.tx_mm for p in placements)
    min_y = min(p.ty_mm for p in placements)
    max_x = max(p.tx_mm + bb.width_mm for p, bb in zip(placements, bboxes))
    max_y = max(p.ty_mm + bb.depth_mm for p, bb in zip(placements, bboxes))
    group_width = max_x - min_x
    group_depth = max_y - min_y
    offset_x = (plate_width_mm - group_width) / 2.0 - min_x
    offset_y = (plate_depth_mm - group_depth) / 2.0 - min_y
    centered_placements = [
        Placement(tx_mm=p.tx_mm + offset_x, ty_mm=p.ty_mm + offset_y)
        for p in placements
    ]

    # ``exceeds_plate`` formula per requirements. Centering an oversized
    # group intentionally produces negative lower-left coordinates.
    exceeds_plate = any(
        p.tx_mm + bb.width_mm > plate_width_mm
        or p.ty_mm + bb.depth_mm > plate_depth_mm
        or p.tx_mm < 0
        or p.ty_mm < 0
        for p, bb in zip(centered_placements, bboxes)
    )

    return LayoutResult(
        placements=tuple(centered_placements),
        exceeds_plate=exceeds_plate,
    )
