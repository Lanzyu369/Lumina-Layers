"""生成「自动动态范围」映射曲线的 Excel 演示。

一张工作表，一张图：横轴 = 原始 L*，纵轴 = 映射后 L*，
展示三种有代表性的档案在不同打印机/材料可达亮度范围下，
原图亮度会被压缩到什么位置。

采用 Cineon 指数三段曲线：轻度压缩时中段严格恒等（斜率 1），
两端用指数 toe/shoulder 柔化，端点处斜率 ≈ 0.2。

运行方式：

    python scripts/build_auto_dr_curve_excel.py

输出：
    progress/auto_dr_curve_demo.xlsx
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

# 保证无论 CWD 在哪都能 import 到仓库根。
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from openpyxl import Workbook
from openpyxl.chart import ScatterChart, Reference, Series
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from core.pipeline.processing_ops.dynamic_range_compressor import _remap_l_channel


# --------------------------------------------------------------------------- #
# 样式常量                                                                    #
# --------------------------------------------------------------------------- #

_HEADER_FILL = PatternFill("solid", fgColor="FF1F3A5F")
_HEADER_FONT = Font(bold=True, color="FFFFFFFF")
_TITLE_FONT = Font(bold=True, size=14)
_SECTION_FONT = Font(bold=True, size=11)


# --------------------------------------------------------------------------- #
# 对外入口                                                                    #
# --------------------------------------------------------------------------- #


def _remap(
    l_src: float,
    tgt_lo: float,
    tgt_hi: float,
) -> float:
    """代表典型输入的映射结果：假设源图硬端点为 [0, 100]。

    Cineon 指数曲线不再需要软端点参数；源范围直接取硬端点 [0, 100]，
    曲线自动根据 tgt_lo / tgt_hi 与硬端点的差值计算 toe / shoulder 宽度。
    """
    return float(
        _remap_l_channel(
            np.array([l_src], dtype=np.float64),
            src_lo_hard=0.0,
            src_hi_hard=100.0,
            tgt_lo=tgt_lo,
            tgt_hi=tgt_hi,
        )[0]
    )


def build(output_path: Path) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "亮度映射曲线"

    # -------- 顶部说明 -------- #
    ws["A1"] = "自动动态范围：原始 L* → 映射后 L*"
    ws["A1"].font = _TITLE_FONT
    ws.merge_cells("A1:F1")

    intro_rows = [
        "这张表只回答一个问题：如果把「自动动态范围」打开，",
        "原图里每个亮度值（L*），会被压缩到什么位置？",
        "",
        "· 横轴：原图里每个像素的亮度 L*（0 = 纯黑，100 = 纯白）",
        "· 纵轴：经过自动动态范围处理后，这个像素会变成的亮度 L*",
        "· 对角虚线（参考线）：不压缩、原样输出，作对照",
        "",
        "下面三条曲线分别对应「目标可达亮度范围」的三种典型场景，",
        "范围越窄（比如打印机做不出很黑或很亮的颜色），曲线越「躺平」，",
        "意味着原图的对比度被压缩得越狠。",
        "",
        "曲线采用 Cineon 指数三段设计：轻度压缩时中段严格恒等（斜率 1），",
        "两端用指数 toe/shoulder 柔化，端点处斜率 ≈ 0.2；重度压缩时",
        "两段指数直接相接，曲线仍保持 C1 连续（无斜率突变）。",
    ]
    for i, text in enumerate(intro_rows, start=2):
        ws.cell(row=i, column=1, value=text).alignment = Alignment(wrap_text=True)
        ws.merge_cells(start_row=i, start_column=1, end_row=i, end_column=6)

    # -------- 表头 -------- #
    data_title_row = 2 + len(intro_rows) + 1
    ws.cell(row=data_title_row, column=1, value="数据表（每行对应一个原始 L* 采样点）").font = _SECTION_FONT
    ws.merge_cells(start_row=data_title_row, start_column=1, end_row=data_title_row, end_column=6)

    header_row = data_title_row + 1

    # 三种典型目标范围。(标签, tgt_lo, tgt_hi)
    scenarios = [
        ("打印机可达 [5, 95]\n（亮度范围很宽，压缩最轻）", 5.0, 95.0),
        ("打印机可达 [14, 86]\n（常见 FDM 4 色档案）", 14.0, 86.0),
        ("打印机可达 [22, 78]\n（范围很窄，压缩最重）", 22.0, 78.0),
    ]

    headers = [
        "原始 L*（输入）",
        *(label for label, _, _ in scenarios),
        "对角参考线\n（不压缩，y = x）",
    ]
    for col, name in enumerate(headers, start=1):
        cell = ws.cell(row=header_row, column=col, value=name)
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[header_row].height = 42
    for col in range(1, len(headers) + 1):
        ws.column_dimensions[get_column_letter(col)].width = 22

    # -------- 数据 -------- #
    # 401 个采样点（0.25 L* 步长）——比 101 点密 4 倍，
    # 让 Reinhard 滚降区间内的曲率变化清晰可见。
    src_samples = np.linspace(0.0, 100.0, 401)
    data_start = header_row + 1
    for i, l_src in enumerate(src_samples):
        row = data_start + i
        ws.cell(row=row, column=1, value=float(l_src))
        for j, (_, lo, hi) in enumerate(scenarios, start=2):
            ws.cell(row=row, column=j, value=_remap(float(l_src), lo, hi))
        # 最后一列：对角参考线
        ws.cell(row=row, column=2 + len(scenarios), value=float(l_src))
    data_end = data_start + len(src_samples) - 1

    # -------- 散点图 -------- #
    # 关键：scatterStyle 必须显式设为 "smooth" 或 "smoothMarker"，否则 Excel
    # 会把 X 轴当分类轴渲染（1,2,3... 而不是实际 L* 数值），导致 X/Y 对不上。
    chart = ScatterChart()
    chart.scatterStyle = "smooth"
    chart.title = "原始 L* → 映射后 L*（Cineon 指数曲线）"
    chart.style = 2
    chart.x_axis.title = "原始 L*（输入亮度，0 = 黑，100 = 白）"
    chart.y_axis.title = "映射后 L*（输出亮度）"
    # 锁定坐标轴到 0..100，方便肉眼判断「压得多狠」。
    chart.x_axis.scaling.min = 0
    chart.x_axis.scaling.max = 100
    chart.y_axis.scaling.min = 0
    chart.y_axis.scaling.max = 100
    # 让两轴使用相同刻度间隔，方便与对角线对比。
    chart.x_axis.majorUnit = 10
    chart.y_axis.majorUnit = 10
    # 强制两轴交于 0。
    chart.x_axis.crosses = "autoZero"
    chart.y_axis.crosses = "autoZero"
    # 关键修复：openpyxl 默认把两轴 axPos 都设为 "l"（左），导致 X 轴被画
    # 成左侧纵轴、Y 轴与之重叠。显式把 X 轴放到底部、Y 轴放到左侧。
    chart.x_axis.axPos = "b"
    chart.y_axis.axPos = "l"
    # 同步勾选主刻度，避免默认为 "none" 时 X 轴看不见刻度。
    chart.x_axis.majorTickMark = "out"
    chart.y_axis.majorTickMark = "out"
    chart.height = 14
    chart.width = 22

    # 规范写法：xvalues 单独一个 Reference（一列），values 同形状（一列），
    # 两者 min_row/max_row 完全一致，避免 Excel 把第一个 y 值当成 label。
    x_ref = Reference(ws, min_col=1, min_row=data_start, max_row=data_end)
    for j, (label, _, _) in enumerate(scenarios, start=2):
        y_ref = Reference(ws, min_col=j, min_row=data_start, max_row=data_end)
        series = Series(y_ref, xvalues=x_ref, title=label.replace("\n", " "))
        series.smooth = True
        chart.series.append(series)
    # 对角参考线（不平滑，作为直线对照）
    y_identity = Reference(
        ws,
        min_col=2 + len(scenarios),
        min_row=data_start,
        max_row=data_end,
    )
    identity_series = Series(y_identity, xvalues=x_ref, title="对角参考线（不压缩）")
    identity_series.smooth = False
    chart.series.append(identity_series)

    ws.add_chart(chart, f"H{data_title_row}")

    # -------- 三段「怎么看」提示 -------- #
    tip_row = data_end + 3
    ws.cell(row=tip_row, column=1, value="怎么看这张图？").font = _SECTION_FONT
    ws.merge_cells(start_row=tip_row, start_column=1, end_row=tip_row, end_column=6)
    tips = [
        "1) 曲线两端贴合横轴/顶边的程度 = 黑白保留程度。",
        "   左端越接近 y=tgt_lo，意味着纯黑被压缩到该档案能达到的最暗色；",
        "   右端越接近 y=tgt_hi，意味着纯白被压缩到该档案能达到的最亮色。",
        "",
        "2) 中段斜率 = 整图的对比度保留比例。",
        "   斜率越接近 1，对比度越接近原图；越「躺平」说明中间调被挤成一团。",
        "",
        "3) 曲线与对角线的垂直距离 = 该像素被「抬高 / 压低」了多少 L*。",
        "   距离越大，视觉上的偏移越明显。",
    ]
    for i, text in enumerate(tips, start=tip_row + 1):
        cell = ws.cell(row=i, column=1, value=text)
        cell.alignment = Alignment(wrap_text=True)
        ws.merge_cells(start_row=i, start_column=1, end_row=i, end_column=6)

    # -------- 保存 -------- #
    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)
    return output_path


def main() -> int:
    from api.structured_logging import configure_structured_logging

    configure_structured_logging()

    out = _REPO_ROOT / "progress" / "auto_dr_curve_demo.xlsx"
    saved = build(out)
    print(f"已生成 {saved.relative_to(_REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
