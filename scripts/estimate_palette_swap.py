from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import cv2
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.material_color_solver import MaterialParams, solve_image_colors, srgb_to_linear
from core.material_lut_synthesis import load_multiple_materials
from core.pipeline.processing_ops.kmeans_quantizer import quantize_colors

logging.disable(logging.CRITICAL)


def load_rgb(path: Path) -> np.ndarray:
    data = np.fromfile(str(path), dtype=np.uint8)
    bgr = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if bgr is None:
        raise RuntimeError(f"Failed to read image: {path}")
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def make_virtual_material(
    name: str,
    srgb_rgb: tuple[int, int, int],
    k_vals: tuple[float, float, float],
    c0_rgb: tuple[int, int, int],
) -> MaterialParams:
    srgb_arr = np.asarray(srgb_rgb, dtype=np.uint8)
    c0_arr = np.asarray(c0_rgb, dtype=np.uint8)
    return MaterialParams(
        name=name,
        directory_name=name,
        E=srgb_to_linear(srgb_arr.reshape(1, 3))[0].astype(np.float64),
        k=np.asarray(k_vals, dtype=np.float64),
        C0_white=srgb_to_linear(c0_arr.reshape(1, 3))[0].astype(np.float64),
        estimated_rgb=srgb_arr,
    )


def weighted_percentile(values: np.ndarray, weights: np.ndarray, percentile: float) -> float:
    order = np.argsort(values)
    sorted_values = values[order]
    sorted_weights = weights[order]
    cum_weights = np.cumsum(sorted_weights)
    threshold = percentile / 100.0 * float(sorted_weights.sum())
    idx = int(np.searchsorted(cum_weights, threshold, side="left"))
    idx = min(max(idx, 0), sorted_values.shape[0] - 1)
    return float(sorted_values[idx])


def resolve_image(repo_root: Path, image_arg: str | None) -> Path:
    if image_arg:
        image_path = Path(image_arg)
        if not image_path.is_absolute():
            image_path = repo_root / image_path
        return image_path
    png_files = sorted(repo_root.glob("*.png"), key=lambda p: p.stat().st_size, reverse=True)
    if not png_files:
        raise FileNotFoundError("No PNG file found in repo root")
    return png_files[0]


def load_canonical_materials(repo_root: Path) -> list[MaterialParams]:
    cache_dir = repo_root / "materials" / "_solver_cache"
    meta_candidates = sorted(cache_dir.glob("*-N10-t0_08-white.meta.json"))
    if not meta_candidates:
        raise FileNotFoundError("No 10-layer white-substrate cache metadata found")
    meta = json.loads(meta_candidates[0].read_text(encoding="utf-8"))
    material_dirs = [item["directory_name"] for item in meta["canonical_materials"]]
    return load_multiple_materials(material_dirs)


def score_palette(
    unique_target: np.ndarray,
    weights: np.ndarray,
    palette: list[MaterialParams],
    beam_width: int,
) -> dict[str, float | int]:
    matched_rgb, _recipes, delta_e = solve_image_colors(
        unique_target,
        palette,
        layer_count=10,
        layer_height_mm=0.08,
        substrate="white",
        beam_width=beam_width,
    )
    return {
        "mean_de": float(np.average(delta_e, weights=weights)),
        "p50_de": weighted_percentile(delta_e, weights, 50.0),
        "p90_de": weighted_percentile(delta_e, weights, 90.0),
        "used_print_colors": int(np.unique(matched_rgb, axis=0).shape[0]),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", type=str, default=None)
    parser.add_argument("--beam-width", type=int, default=32)
    args = parser.parse_args()

    image_path = resolve_image(REPO_ROOT, args.image)
    rgb = load_rgb(image_path)
    quant = quantize_colors(rgb, 256, seed=42, skip_post_blur=True)
    unique_target, _inverse, counts = np.unique(
        quant.reshape(-1, 3), axis=0, return_inverse=True, return_counts=True
    )
    weights = counts.astype(np.float64)

    materials = load_canonical_materials(REPO_ROOT)
    red = materials[0]
    green = materials[2]
    blue = materials[3]
    lightblue = materials[6]
    white = materials[7]

    virtual_magenta = make_virtual_material(
        "virtual_magenta",
        (165, 70, 150),
        (
            float((red.k[0] + blue.k[0]) / 2.0),
            float(blue.k[1]),
            float(red.k[2] * 0.35),
        ),
        (190, 165, 190),
    )
    virtual_cyan = make_virtual_material(
        "virtual_cyan",
        (70, 190, 205),
        (
            float(blue.k[0]),
            float((green.k[1] + lightblue.k[1]) / 2.0),
            float((blue.k[2] + lightblue.k[2]) / 2.0),
        ),
        (165, 205, 210),
    )

    current = score_palette(unique_target, weights, materials, args.beam_width)
    replace_lightblue_with_magenta = score_palette(
        unique_target,
        weights,
        materials[:6] + [virtual_magenta, white],
        args.beam_width,
    )
    replace_lightblue_with_cyan = score_palette(
        unique_target,
        weights,
        materials[:6] + [virtual_cyan, white],
        args.beam_width,
    )
    remove_lightblue_add_magenta_cyan = score_palette(
        unique_target,
        weights,
        materials[:6] + [virtual_magenta, virtual_cyan, white],
        args.beam_width,
    )

    baseline = current["mean_de"]
    results = {
        "image_name": image_path.name,
        "beam_width": args.beam_width,
        "note": "Idealized virtual magenta/cyan materials. Directional estimate only.",
        "current_8": current,
        "replace_lightblue_with_magenta_8": replace_lightblue_with_magenta,
        "replace_lightblue_with_cyan_8": replace_lightblue_with_cyan,
        "remove_lightblue_add_magenta_cyan_9": remove_lightblue_add_magenta_cyan,
    }

    for key in [
        "current_8",
        "replace_lightblue_with_magenta_8",
        "replace_lightblue_with_cyan_8",
        "remove_lightblue_add_magenta_cyan_9",
    ]:
        item = results[key]
        item["delta_vs_current"] = float(item["mean_de"] - baseline)
        item["improvement_pct"] = float((baseline - item["mean_de"]) / baseline * 100.0)
        item["mean_de"] = round(float(item["mean_de"]), 2)
        item["p50_de"] = round(float(item["p50_de"]), 2)
        item["p90_de"] = round(float(item["p90_de"]), 2)
        item["delta_vs_current"] = round(float(item["delta_vs_current"]), 2)
        item["improvement_pct"] = round(float(item["improvement_pct"]), 2)

    print(json.dumps(results, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
