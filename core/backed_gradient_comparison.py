"""Canonical dual-backing comparison and portable research outputs.
规范双背板色卡对照及可移植研究产物。
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np

from config import ColorSystem
from core.backed_gradient_models import BackedGradientModel, restore_backed_gradient_model
from core.colorchecker.color_metrics import delta_e_2000
from core.extractor import _generate_recipes as canonical_generate_recipes
from core.km_xyz import km_relative_xyz_to_lab, km_relative_xyz_to_srgb_uint8
from core.lut_card_layout import cell_for_row_index, resolve_lut_layout

BLIND_RECIPES = ("RYBWW", "WWBYR", "RYYBB", "BBYYR")


def canonical_recipes() -> tuple[str, ...]:
    """Decode the project's canonical 1024 row order into visible-to-back codes.
    将项目规范的一千零二十四行顺序解码为可见面向内配方。

    Returns:
        Canonical visible-to-back recipe codes.（规范可见面向内配方代码。）
    """
    slots = ColorSystem.get("4-Color (RYBW)")["slots"]
    symbols = {"White": "W", "Red": "R", "Yellow": "Y", "Blue": "B"}
    return tuple("".join(symbols[slots[int(slot)]] for slot in row)
                 for row in canonical_generate_recipes("4-Color (RYBW)", 1024))


def prediction_envelope(model: BackedGradientModel, alternatives: Sequence[BackedGradientModel],
                        backing: str, recipes: Sequence[str] | None = None) -> dict:
    """Measure the explored prediction envelope in unclipped XYZ and Lab.
    在未裁切 XYZ 与 Lab 中评估已探索的预测包络。

    Args:
        model: Frozen candidate.（冻结候选。）
        alternatives: Accepted sensitivity endpoints.（合格敏感性端点。）
        backing: Actual W/K substrate.（实际白黑背板。）
        recipes: Optional fixed recipe subset.（可选固定配方子集。）

    Returns:
        Explored widths and per-recipe values.（已探索宽度和逐配方数值。）
    """
    codes = tuple(recipes or canonical_recipes())
    predictions = np.array([candidate.predict_recipes(codes, backing) / 100
                            for candidate in (model, *alternatives)])
    width = np.ptp(predictions, axis=0) * 100
    lab = km_relative_xyz_to_lab(predictions)
    diameters = np.zeros(len(codes))
    for index in range(len(lab) - 1):
        distance = delta_e_2000(lab[index:index + 1], lab[index + 1:])
        diameters = np.maximum(diameters, distance.max(axis=0))
    scalar_width = width.max(axis=1)
    return {
        "xyz_width_p95_pp": float(np.percentile(scalar_width, 95)),
        "xyz_width_max_pp": float(scalar_width.max()),
        "delta_e00_p95": float(np.percentile(diameters, 95)),
        "delta_e00_max": float(diameters.max()),
        "rows": [{"xyz_width_pp": width[i].tolist(), "delta_e00_width": float(diameters[i])}
                 for i in range(len(codes))],
    }


def build_comparison(models: Mapping[str, dict], *,
                     alternatives: Mapping[str, Sequence[BackedGradientModel]] | None = None) -> dict | None:
    """Build both actual backings in canonical order, without using the palette in fitting.
    按规范顺序生成两种实际背板，色卡不参与拟合。

    Args:
        models: Separate fitted family results.（独立模型拟合结果。）
        alternatives: Optional sensitivity models.（可选敏感性模型。）

    Returns:
        Dual-backing comparison, or None without two finite models.
            （双背板对照；缺少两个有限模型时为空。）
    """
    if any(not models.get(family, {}).get("parameters") for family in ("affine", "two_flux")):
        return None
    operators = {family: restore_backed_gradient_model(models[family]["parameters"])
                 for family in ("affine", "two_flux")}
    codes = canonical_recipes()
    layout = resolve_lut_layout("4-Color (RYBW)", len(codes))
    envelopes = {}
    predicted = {}
    for backing in ("W", "K"):
        predicted[backing] = {}
        envelopes[backing] = {}
        for family, operator in operators.items():
            xyz = operator.predict_recipes(codes, backing) / 100
            predicted[backing][family] = {"xyz": xyz, "rgb": km_relative_xyz_to_srgb_uint8(xyz)}
            envelopes[backing][family] = prediction_envelope(operator, (alternatives or {}).get(family, ()), backing, codes)
        predicted[backing]["delta"] = delta_e_2000(
            km_relative_xyz_to_lab(predicted[backing]["affine"]["xyz"]),
            km_relative_xyz_to_lab(predicted[backing]["two_flux"]["xyz"]),
        )
    rows = []
    for index, code in enumerate(codes):
        cell = cell_for_row_index(layout, index)
        backings = {}
        for backing in ("W", "K"):
            content = {}
            for family in operators:
                value = predicted[backing][family]
                rgb = value["rgb"][index].tolist()
                content[family] = {"xyz": value["xyz"][index].tolist(), "rgb": rgb,
                                   "hex": "#" + "".join(f"{channel:02X}" for channel in rgb)}
            content["delta_e00"] = float(predicted[backing]["delta"][index])
            content["stability"] = {family: envelopes[backing][family]["rows"][index] for family in operators}
            backings[backing] = content
        rows.append({"id": index + 1, "row": cell.data_row, "column": cell.data_col,
                     "recipe_visible_to_back": code, "backings": backings})
    blind = []
    for code in BLIND_RECIPES:
        record = {"recipe_visible_to_back": code, "backing": "W", "layer_mm": .08,
                  "backing_mm": 2.6, "total_mm": 3., "predictions": {}}
        for family, operator in operators.items():
            record["predictions"][family] = operator.predict_recipes([code], "W")[0].tolist()
        blind.append(record)
    return {
        "geometry": {"total_mm": 3., "upper_layers": 5, "layer_mm": .08, "backing_mm": 2.6},
        "model_ids": {family: models[family]["parameters"]["model_id"] for family in operators},
        "layer_order": "visible_to_back", "display_only_rgb_clipping": True, "native_black_floor_applied": True,
        "rows": rows, "blind_recipes": blind,
        "envelopes": {backing: {family: {key: value for key, value in info.items() if key != "rows"}
                                  for family, info in family_info.items()}
                      for backing, family_info in envelopes.items()},
    }


def export_comparison(result: dict, outputdir: str | Path) -> dict[str, str]:
    """Export frozen JSON, complete XYZ CSV, and a dual-backing PNG comparison.
    导出冻结 JSON、完整 XYZ CSV 与双背板 PNG 对照。

    Args:
        result: Complete fit result.（完整拟合结果。）
        outputdir: Caller-owned output directory.（调用方管理的输出目录。）

    Returns:
        Artifact labels and filenames.（产物名称与文件名。）
    """
    directory = Path(outputdir)
    directory.mkdir(parents=True, exist_ok=True)
    json_name = "result.json"
    (directory / json_name).write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    exports = {"json": json_name}
    comparison = result.get("comparison")
    if not comparison:
        return exports
    model_ids = {family: comparison.get("model_ids", {}).get(family)
                 or result.get("models", {}).get(family, {}).get("parameters", {}).get("model_id", "unknown")
                 for family in ("affine", "two_flux")}
    csv_name = "comparison.csv"
    fields = ["id", "row", "column", "recipe_visible_to_back", "backing", "model", "model_id", "X_relative", "Y_relative", "Z_relative", "hex", "model_delta_e00"]
    with (directory / csv_name).open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in comparison["rows"]:
            for backing in ("W", "K"):
                for family in ("affine", "two_flux"):
                    value = row["backings"][backing][family]
                    writer.writerow({"id": row["id"], "row": row["row"], "column": row["column"],
                                     "recipe_visible_to_back": row["recipe_visible_to_back"], "backing": backing, "model": family,
                                     "model_id": model_ids[family],
                                     "X_relative": value["xyz"][0], "Y_relative": value["xyz"][1], "Z_relative": value["xyz"][2],
                                     "hex": value["hex"], "model_delta_e00": row["backings"][backing]["delta_e00"]})
    from PIL import Image, ImageDraw, ImageFont

    tile, gap, heading, caption_height = 18, 24, 34, 78
    side = tile * 32
    canvas = Image.new("RGB", (side * 2 + gap * 3, (side + heading) * 2 + gap * 3 + caption_height), (240, 242, 245))
    drawing = ImageDraw.Draw(canvas)
    font_path = Path("C:/Windows/Fonts/msyh.ttc")
    font = ImageFont.truetype(str(font_path), 17) if font_path.exists() else ImageFont.load_default()
    caption = "总厚 3 mm，颜色 5 × 0.08 mm，实体背板 2.60 mm"
    drawing.text((gap, gap), caption if font_path.exists() else "Total 3 mm; upper 5 x 0.08 mm; actual backing 2.60 mm", font=font, fill=(30, 40, 55))
    drawing.text((gap, gap + 27), "仿真预览，待叠色实测验证" if font_path.exists() else "Simulation preview; mixed-stack measurements pending", font=font, fill=(65, 75, 90))
    for index, (backing, family) in enumerate((("W", "affine"), ("W", "two_flux"), ("K", "affine"), ("K", "two_flux"))):
        left, top = gap + (index % 2) * (side + gap), gap + caption_height + (index // 2) * (side + heading + gap)
        version = model_ids[family].rsplit("/", 1)[-1]
        title = ("白背板" if backing == "W" else "黑背板") + " · " + ("基础预测 " if family == "affine" else "散射返光预测 ") + version
        if not font_path.exists():
            title = ("White backing" if backing == "W" else "Black backing") + " | " + ("Baseline " if family == "affine" else "Scattering-return ") + version
        drawing.text((left, top), title, font=font, fill=(30, 40, 55))
        for row in comparison["rows"]:
            x, y = left + tile * row["column"], top + heading + tile * row["row"]
            drawing.rectangle((x, y, x + tile - 1, y + tile - 1), fill=tuple(row["backings"][backing][family]["rgb"]))
    png_name = "comparison.png"
    canvas.save(directory / png_name)
    exports.update(csv=csv_name, png=png_name)
    return exports
