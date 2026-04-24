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

from core.material_color_solver import (
    MaterialParams,
    rgb_to_lab,
    solve_image_colors,
    srgb_to_linear,
)
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


def build_skin_mask(rgb: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    ycrcb = cv2.cvtColor(rgb, cv2.COLOR_RGB2YCrCb)
    r = rgb[:, :, 0].astype(np.int32)
    g = rgb[:, :, 1].astype(np.int32)
    b = rgb[:, :, 2].astype(np.int32)
    h = hsv[:, :, 0].astype(np.int32)
    s = hsv[:, :, 1].astype(np.int32)
    v = hsv[:, :, 2].astype(np.int32)
    y = ycrcb[:, :, 0].astype(np.int32)
    cr = ycrcb[:, :, 1].astype(np.int32)
    cb = ycrcb[:, :, 2].astype(np.int32)
    rgb_rule = (
        (r > 80)
        & (g > 40)
        & (b > 20)
        & (r > g)
        & (r > b)
        & (np.abs(r - g) > 4)
    )
    ycrcb_rule = (
        (y > 55)
        & (cr >= 132)
        & (cr <= 180)
        & (cb >= 80)
        & (cb <= 136)
    )
    hsv_rule = (
        ((h <= 28) | (h >= 170))
        & (s >= 10)
        & (s <= 180)
        & (v >= 50)
    )
    mask = (rgb_rule & ycrcb_rule & hsv_rule).astype(np.uint8) * 255
    kernel_open = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    kernel_close = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel_open)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel_close)
    return mask > 0


def select_face_region(rgb: np.ndarray) -> tuple[np.ndarray, tuple[int, int, int, int]]:
    skin_mask = build_skin_mask(rgb)
    labels_count, labels, stats, centroids = cv2.connectedComponentsWithStats(
        skin_mask.astype(np.uint8),
        connectivity=8,
    )
    height, width = skin_mask.shape
    anchor = np.asarray([0.35 * width, 0.24 * height], dtype=np.float64)
    min_area = max(1500, int(0.00008 * height * width))
    best_label = -1
    best_score = -1.0
    for label in range(1, labels_count):
        x, y, w, h, area = stats[label]
        if area < min_area:
            continue
        cx, cy = centroids[label]
        if cy > 0.58 * height or y > 0.48 * height:
            continue
        aspect = float(w) / float(max(h, 1))
        if aspect < 0.28 or aspect > 1.9:
            continue
        distance = float(np.linalg.norm(np.asarray([cx, cy]) - anchor) / max(width, height))
        score = float(area) / (1.0 + 8.0 * distance)
        if cy < 0.12 * height:
            score *= 0.65
        if score > best_score:
            best_score = score
            best_label = label
    if best_label < 0:
        candidate_labels = []
        for label in range(1, labels_count):
            area = int(stats[label, cv2.CC_STAT_AREA])
            cy = float(centroids[label][1])
            if area >= min_area and cy <= 0.6 * height:
                candidate_labels.append(label)
        if not candidate_labels:
            raise RuntimeError("Failed to isolate face skin region")
        best_label = max(candidate_labels, key=lambda label: int(stats[label, cv2.CC_STAT_AREA]))
    x, y, w, h, _area = stats[best_label]
    pad_x = max(48, int(w * 0.28))
    pad_y = max(48, int(h * 0.32))
    x0 = max(0, x - pad_x)
    y0 = max(0, y - pad_y)
    x1 = min(width, x + w + pad_x)
    y1 = min(height, y + h + pad_y)
    bbox_mask = np.zeros_like(skin_mask, dtype=bool)
    bbox_mask[y0:y1, x0:x1] = True
    face_mask = skin_mask & bbox_mask
    return face_mask, (int(x0), int(y0), int(x1 - x0), int(y1 - y0))


def overlap(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return not (ax + aw <= bx or bx + bw <= ax or ay + ah <= by or by + bh <= ay)


def projected_steps(lab_patch_flat: np.ndarray, mean_lab: np.ndarray, axis: np.ndarray) -> int:
    proj = (lab_patch_flat - mean_lab) @ axis
    return int(np.unique(np.round(proj * 4.0) / 4.0).shape[0])


def select_face_patches(
    orig_lab_img: np.ndarray,
    face_mask: np.ndarray,
    bbox: tuple[int, int, int, int],
) -> list[dict[str, object]]:
    x0, y0, width, height = bbox
    if width < 48 or height < 48:
        return []
    win = int(np.clip(min(width, height) * 0.24, 48, 96))
    win = min(win, width, height)
    step = max(16, win // 2)
    yy, xx = np.mgrid[0:win, 0:win]
    design = np.column_stack([xx.ravel(), yy.ravel(), np.ones(win * win)])
    candidates: list[dict[str, object]] = []
    y_stop = y0 + height - win + 1
    x_stop = x0 + width - win + 1
    for y in range(y0, max(y_stop, y0 + 1), step):
        for x in range(x0, max(x_stop, x0 + 1), step):
            mask_patch = face_mask[y:y + win, x:x + win]
            coverage = float(mask_patch.mean())
            if coverage < 0.34:
                continue
            patch = orig_lab_img[y:y + win, x:x + win]
            residuals = []
            fit_ranges = []
            for channel in range(3):
                values = patch[:, :, channel].reshape(-1).astype(np.float64)
                coef, *_ = np.linalg.lstsq(design, values, rcond=None)
                fit = design @ coef
                residuals.append(float(np.sqrt(np.mean((values - fit) ** 2))))
                fit_ranges.append(float(fit.max() - fit.min()))
            smooth = float(np.mean(residuals))
            gradient = float(np.mean(fit_ranges))
            if gradient < 2.0:
                continue
            score = coverage * gradient / (smooth + 0.35)
            candidates.append({
                "rect": (int(x), int(y), int(win), int(win)),
                "score": score,
            })
    if not candidates:
        center_x = x0 + max(0, (width - win) // 2)
        center_y = y0 + max(0, (height - win) // 2)
        candidates = [{"rect": (int(center_x), int(center_y), int(win), int(win)), "score": 0.0}]
    selected: list[dict[str, object]] = []
    for item in sorted(candidates, key=lambda data: float(data["score"]), reverse=True):
        rect = item["rect"]
        if all(not overlap(rect, prev["rect"]) for prev in selected):
            selected.append(item)
        if len(selected) == 3:
            break
    patch_specs: list[dict[str, object]] = []
    for index, item in enumerate(selected, start=1):
        x, y, w, h = item["rect"]
        patch_flat = orig_lab_img[y:y + h, x:x + w].reshape(-1, 3)
        mean_lab = patch_flat.mean(axis=0)
        _, _, vh = np.linalg.svd(patch_flat - mean_lab, full_matrices=False)
        axis = vh[0]
        patch_specs.append({
            "index": index,
            "xywh": [int(x), int(y), int(w), int(h)],
            "mean_lab": mean_lab,
            "axis": axis,
            "orig_steps": projected_steps(patch_flat, mean_lab, axis),
        })
    return patch_specs


def evaluate_palette(
    unique_target: np.ndarray,
    inverse: np.ndarray,
    weights: np.ndarray,
    palette: list[MaterialParams],
    beam_width: int,
    rgb: np.ndarray,
    orig_lab_flat: np.ndarray,
    face_mask: np.ndarray,
    patch_specs: list[dict[str, object]],
) -> dict[str, object]:
    matched_rgb_unique, _recipes, delta_e = solve_image_colors(
        unique_target,
        palette,
        layer_count=10,
        layer_height_mm=0.08,
        substrate="white",
        beam_width=beam_width,
    )
    matched_img = matched_rgb_unique[inverse].reshape(rgb.shape)
    matched_lab_flat = rgb_to_lab(matched_img.reshape(-1, 3))
    pixel_de_flat = np.linalg.norm(orig_lab_flat - matched_lab_flat, axis=1)
    face_flat = face_mask.reshape(-1)
    face_pixel_de = pixel_de_flat[face_flat]
    matched_face = matched_img[face_mask]
    matched_lab_img = matched_lab_flat.reshape(rgb.shape)
    patch_reports = []
    patch_steps = []
    for spec in patch_specs:
        x, y, w, h = spec["xywh"]
        patch_flat = matched_lab_img[y:y + h, x:x + w].reshape(-1, 3)
        steps = projected_steps(patch_flat, spec["mean_lab"], spec["axis"])
        patch_steps.append(steps)
        patch_reports.append({
            "index": int(spec["index"]),
            "xywh": spec["xywh"],
            "orig_steps": int(spec["orig_steps"]),
            "scenario_steps": int(steps),
        })
    return {
        "overall_mean_de": float(np.average(delta_e, weights=weights)),
        "overall_p90_de": weighted_percentile(delta_e, weights, 90.0),
        "used_print_colors": int(np.unique(matched_rgb_unique, axis=0).shape[0]),
        "face_mean_pixel_de": float(face_pixel_de.mean()),
        "face_p50_pixel_de": float(np.percentile(face_pixel_de, 50.0)),
        "face_p90_pixel_de": float(np.percentile(face_pixel_de, 90.0)),
        "face_used_print_colors": int(np.unique(matched_face.reshape(-1, 3), axis=0).shape[0]),
        "face_patch_mean_steps": float(np.mean(patch_steps)) if patch_steps else 0.0,
        "face_patches": patch_reports,
    }


def round_metrics(metrics: dict[str, object]) -> dict[str, object]:
    rounded = dict(metrics)
    for key in [
        "overall_mean_de",
        "overall_p90_de",
        "face_mean_pixel_de",
        "face_p50_pixel_de",
        "face_p90_pixel_de",
        "face_patch_mean_steps",
        "delta_overall_vs_current",
        "delta_face_vs_current",
        "delta_overall_vs_magenta_swap",
        "delta_face_vs_magenta_swap",
        "improvement_pct_overall_vs_current",
        "improvement_pct_face_vs_current",
        "improvement_pct_overall_vs_magenta_swap",
        "improvement_pct_face_vs_magenta_swap",
    ]:
        if key in rounded:
            rounded[key] = round(float(rounded[key]), 2)
    return rounded


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", type=str, default=None)
    parser.add_argument("--beam-width", type=int, default=32)
    args = parser.parse_args()

    image_path = resolve_image(REPO_ROOT, args.image)
    rgb = load_rgb(image_path)
    quant = quantize_colors(rgb, 256, seed=42, skip_post_blur=True)
    unique_target, inverse, counts = np.unique(
        quant.reshape(-1, 3),
        axis=0,
        return_inverse=True,
        return_counts=True,
    )
    weights = counts.astype(np.float64)
    orig_lab_flat = rgb_to_lab(rgb.reshape(-1, 3))
    orig_lab_img = orig_lab_flat.reshape(rgb.shape)
    face_mask, face_bbox = select_face_region(rgb)
    patch_specs = select_face_patches(orig_lab_img, face_mask, face_bbox)

    materials = load_canonical_materials(REPO_ROOT)
    red = materials[0]
    skin = materials[1]
    green = materials[2]
    blue = materials[3]
    yellow = materials[4]
    black = materials[5]
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
    virtual_violet = make_virtual_material(
        "virtual_violet",
        (118, 80, 172),
        (
            float((red.k[0] + blue.k[0]) / 2.0),
            float(blue.k[1] * 0.92),
            float(red.k[2] * 0.24),
        ),
        (170, 150, 198),
    )
    virtual_warm_peach = make_virtual_material(
        "virtual_warm_peach",
        (236, 184, 158),
        (
            float(skin.k[0] * 0.92),
            float((skin.k[1] + yellow.k[1]) * 0.5),
            float((skin.k[2] + red.k[2]) * 0.36),
        ),
        (235, 214, 202),
    )
    virtual_orange = make_virtual_material(
        "virtual_orange",
        (245, 166, 96),
        (
            float(red.k[0] * 0.78),
            float(yellow.k[1] * 0.82),
            float(red.k[2] * 0.46),
        ),
        (238, 198, 162),
    )

    scenario_palettes = {
        "current_8": materials,
        "magenta_swap_8": materials[:6] + [virtual_magenta, white],
        "magenta_cyan_9": materials[:6] + [virtual_magenta, virtual_cyan, white],
        "magenta_violet_9": materials[:6] + [virtual_magenta, virtual_violet, white],
        "magenta_warm_peach_9": materials[:6] + [virtual_magenta, virtual_warm_peach, white],
        "magenta_orange_9": materials[:6] + [virtual_magenta, virtual_orange, white],
        "magenta_orange_no_skin_8": [
            red,
            green,
            blue,
            yellow,
            black,
            virtual_magenta,
            virtual_orange,
            white,
        ],
    }

    scenario_results: dict[str, dict[str, object]] = {}
    for name, palette in scenario_palettes.items():
        scenario_results[name] = evaluate_palette(
            unique_target,
            inverse,
            weights,
            palette,
            args.beam_width,
            rgb,
            orig_lab_flat,
            face_mask,
            patch_specs,
        )

    current_overall = float(scenario_results["current_8"]["overall_mean_de"])
    current_face = float(scenario_results["current_8"]["face_mean_pixel_de"])
    magenta_overall = float(scenario_results["magenta_swap_8"]["overall_mean_de"])
    magenta_face = float(scenario_results["magenta_swap_8"]["face_mean_pixel_de"])

    for name, metrics in scenario_results.items():
        metrics["delta_overall_vs_current"] = float(metrics["overall_mean_de"] - current_overall)
        metrics["delta_face_vs_current"] = float(metrics["face_mean_pixel_de"] - current_face)
        metrics["improvement_pct_overall_vs_current"] = float(
            (current_overall - float(metrics["overall_mean_de"])) / current_overall * 100.0
        )
        metrics["improvement_pct_face_vs_current"] = float(
            (current_face - float(metrics["face_mean_pixel_de"])) / current_face * 100.0
        )
        metrics["delta_overall_vs_magenta_swap"] = float(metrics["overall_mean_de"] - magenta_overall)
        metrics["delta_face_vs_magenta_swap"] = float(metrics["face_mean_pixel_de"] - magenta_face)
        metrics["improvement_pct_overall_vs_magenta_swap"] = float(
            (magenta_overall - float(metrics["overall_mean_de"])) / magenta_overall * 100.0
        )
        metrics["improvement_pct_face_vs_magenta_swap"] = float(
            (magenta_face - float(metrics["face_mean_pixel_de"])) / magenta_face * 100.0
        )
        scenario_results[name] = round_metrics(metrics)

    candidate_rank = []
    for name in [
        "magenta_cyan_9",
        "magenta_violet_9",
        "magenta_warm_peach_9",
        "magenta_orange_9",
    ]:
        metrics = scenario_results[name]
        candidate_rank.append({
            "name": name,
            "face_mean_pixel_de": metrics["face_mean_pixel_de"],
            "face_improvement_pct_vs_magenta_swap": metrics["improvement_pct_face_vs_magenta_swap"],
            "overall_mean_de": metrics["overall_mean_de"],
            "overall_improvement_pct_vs_magenta_swap": metrics["improvement_pct_overall_vs_magenta_swap"],
            "face_patch_mean_steps": metrics["face_patch_mean_steps"],
        })
    candidate_rank.sort(
        key=lambda item: (
            float(item["face_mean_pixel_de"]),
            float(item["overall_mean_de"]),
            -float(item["face_patch_mean_steps"]),
        )
    )

    output = {
        "image_name": image_path.name,
        "beam_width": args.beam_width,
        "note": "Virtual materials are idealized directional estimates, not measured real filaments.",
        "face_region": {
            "bbox": list(face_bbox),
            "skin_pixel_count": int(face_mask.sum()),
            "patches": [
                {
                    "index": int(spec["index"]),
                    "xywh": spec["xywh"],
                    "orig_steps": int(spec["orig_steps"]),
                }
                for spec in patch_specs
            ],
        },
        "scenarios": scenario_results,
        "candidate_rank_after_magenta_swap": candidate_rank,
    }
    print(json.dumps(output, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
