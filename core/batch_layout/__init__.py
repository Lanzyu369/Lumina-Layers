"""Batch-mode shelf-by-row layout helper for merged 3MF output.

批量模式合并 3MF 的单平面 shelf-by-row 排布 helper.

This package is UI-agnostic and I/O-free. The layout algorithm uses a
module-level constant ``GAP_MM = 2.0`` (NOT a function parameter) and is
purely deterministic — same input yields the same output.

本包不做任何 I/O，不依赖 UI 层。排布间距使用模块级常量
``GAP_MM = 2.0``，**不**作为函数参数；同一输入两次调用得到完全相同的输出.
"""

from core.batch_layout.layout_helper import (
    GAP_MM,
    LayoutResult,
    Placement,
    XYBBox,
    layout_shelf_by_row,
)

__all__ = [
    "GAP_MM",
    "XYBBox",
    "Placement",
    "LayoutResult",
    "layout_shelf_by_row",
]
