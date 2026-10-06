"""Benchmark LUT-Constrained K-Means vs legacy cv2.kmeans with LUT matching.

多量化级别矩阵测试：原始像素 → 量化 → LUT匹配 → 最终输出。
每种颜色模式使用对应 LUT，覆盖多个 n_colors 级别。
"""

from __future__ import annotations

import time
import hashlib
import sys
import os

import cv2
import numpy as np
from scipy.spatial import KDTree

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.pipeline.processing_ops.kmeans_quantizer import quantize_colors
from core.image_processing import LuminaImageProcessor

LUT_DIR = r"G:\Lumina\Lumina-Layers\lut-preset\Aliz\PETG"

MODE_CONFIGS = [
    ("BW",        f"{LUT_DIR}\\Aliz&4色PETG&RYBW.npy"),
    ("4-Color",   f"{LUT_DIR}\\Aliz&4色PETG&RYBW.npy"),
    ("6-Color",   f"{LUT_DIR}\\Aliz&6色PETG&RYBWGK.npy"),
    ("8-Color",   f"{LUT_DIR}\\Aliz&8色PETG.npy"),
]

N_COLORS_LEVELS = [36, 72, 144, 256, 1024]


def _load_lut_rgb(path: str) -> np.ndarray:
    lut = np.load(path)
    if lut.ndim == 3:
        lut = lut.reshape(-1, 3)
    return lut


def _lut_match_quantized(
    quantized: np.ndarray,
    lut_rgb: np.ndarray,
    lut_lab: np.ndarray,
    lut_tree: KDTree,
) -> np.ndarray:
    pixels = quantized.reshape(-1, 3)
    unique, inverse = np.unique(pixels, axis=0, return_inverse=True)
    unique_lab = LuminaImageProcessor._rgb_to_lab(unique.astype(np.uint8))
    _, matched_idx = lut_tree.query(unique_lab)
    matched_rgb = lut_rgb[matched_idx]
    return matched_rgb[inverse].reshape(quantized.shape)


def _compute_delta_e_mean(original_rgb: np.ndarray, output_rgb: np.ndarray) -> float:
    orig_lab = LuminaImageProcessor._rgb_to_lab(
        original_rgb.reshape(-1, 3).astype(np.uint8)
    )
    out_lab = LuminaImageProcessor._rgb_to_lab(
        output_rgb.reshape(-1, 3).astype(np.uint8)
    )
    return float(np.sqrt(((orig_lab - out_lab) ** 2).sum(axis=1)).mean())


def main() -> None:
    from api.structured_logging import configure_structured_logging

    configure_structured_logging()

    image_path = r"G:\Lumina\Lumina-Layers\test_images\LUT_Stress_Test_HD.png"

    print(f"Loading image: {image_path}")
    img_bgr = cv2.imread(image_path)
    rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    h, w = rgb.shape[:2]
    print(f"  {w}×{h}  ({w * h / 1e6:.1f}M px)\n")

    all_results = []

    for mode_label, lut_path in MODE_CONFIGS:
        lut_rgb = _load_lut_rgb(lut_path)
        lut_lab = LuminaImageProcessor._rgb_to_lab(lut_rgb)
        lut_tree = KDTree(lut_lab)
        lut_fp = hashlib.sha1(lut_lab.tobytes()).hexdigest()[:12]

        print(f"{'─' * 65}")
        print(f"  {mode_label}  |  LUT: {os.path.basename(lut_path)}  ({len(lut_rgb)} entries)")
        print(f"{'─' * 65}")
        print(
            f"  {'n_colors':>8} {'Old(s)':>8} {'New(s)':>8} {'Ratio':>7} "
            f"{'ΔE_old':>7} {'ΔE_new':>7} {'ΔE_Δ':>7} {'LUT-pen.':>9}"
        )
        print(f"  {'─' * 65}")

        for n_colors in N_COLORS_LEVELS:
            # Old path
            t0 = time.perf_counter()
            out_old = quantize_colors(rgb, n_colors=n_colors, seed=42, skip_post_blur=True)
            final_old = _lut_match_quantized(out_old, lut_rgb, lut_lab, lut_tree)
            t_old = time.perf_counter() - t0
            de_old = _compute_delta_e_mean(rgb, final_old)
            de_lutmatch = _compute_delta_e_mean(out_old, final_old)

            # New path
            t0 = time.perf_counter()
            out_new = quantize_colors(
                rgb, n_colors=n_colors, seed=42, skip_post_blur=True,
                lut_lab=lut_lab, lut_rgb=lut_rgb, lut_tree=lut_tree,
                use_lut_constrained=True, lut_fingerprint=lut_fp,
            )
            final_new = _lut_match_quantized(out_new, lut_rgb, lut_lab, lut_tree)
            t_new = time.perf_counter() - t0
            de_new = _compute_delta_e_mean(rgb, final_new)

            ratio = t_new / t_old if t_old > 0 else float("inf")
            de_delta = de_new - de_old
            sign = "+" if de_delta > 0 else ""

            print(
                f"  {n_colors:>8} {t_old:>8.2f} {t_new:>8.2f} "
                f"{ratio:>6.2f}× "
                f"{de_old:>7.2f} {de_new:>7.2f} "
                f"{sign}{de_delta:>6.2f} {de_lutmatch:>9.2f}"
            )

            all_results.append({
                "mode": mode_label,
                "lut_size": len(lut_rgb),
                "n_colors": n_colors,
                "old_s": t_old, "new_s": t_new,
                "ratio": ratio,
                "de_old": de_old, "de_new": de_new,
                "de_delta": de_delta,
                "de_lutmatch": de_lutmatch,
            })
        print()

    # ============ 精度汇总 ============
    print(f"{'=' * 88}")
    print(f"  ΔE Summary  (↑ worse  ↓ better)")
    print(f"{'=' * 88}")
    print(f"{'n_colors':>8}", end="")
    for _, label in MODE_CONFIGS:
        print(f"  {label:>14}", end="")
    print()
    print(f"{'─' * 8}", end="")
    for _ in MODE_CONFIGS:
        print("  ──────────────", end="")
    print()
    for n_colors in N_COLORS_LEVELS:
        print(f"{n_colors:>8}", end="")
        for mode_label, _ in MODE_CONFIGS:
            matches = [r for r in all_results if r["mode"] == mode_label and r["n_colors"] == n_colors]
            if matches:
                r = matches[0]
                sign = "+" if r["de_delta"] > 0 else ""
                direction = "↓" if r["de_delta"] < 0 else ("↑" if r["de_delta"] > 0 else "=")
                print(f"  {direction} {sign}{r['de_delta']:>6.2f}  ({r['de_old']:.1f}→{r['de_new']:.1f})", end="")
            else:
                print(f"  {'─':>14}", end="")
        print()

    # ============ 速度汇总 ============
    print(f"\n{'=' * 88}")
    print(f"  Speed Summary  (ratio = new / old)")
    print(f"{'=' * 88}")
    print(f"{'n_colors':>8}", end="")
    for _, label in MODE_CONFIGS:
        print(f"  {label:>18}", end="")
    print()
    print(f"{'─' * 8}", end="")
    for _ in MODE_CONFIGS:
        print("  ──────────────────", end="")
    print()
    for n_colors in N_COLORS_LEVELS:
        print(f"{n_colors:>8}", end="")
        for mode_label, _ in MODE_CONFIGS:
            matches = [r for r in all_results if r["mode"] == mode_label and r["n_colors"] == n_colors]
            if matches:
                r = matches[0]
                print(f"  {r['ratio']:.2f}× ({r['old_s']:.1f}s→{r['new_s']:.1f}s)", end="")
            else:
                print(f"  {'─':>18}", end="")
        print()

    # ============ LUT-penalty 汇总（仅老路径）============
    print(f"\n{'=' * 88}")
    print(f"  LUT-match Penalty (old path only): ΔE(quantized → LUT-matched)")
    print(f"{'=' * 88}")
    print(f"{'n_colors':>8}", end="")
    for _, label in MODE_CONFIGS:
        print(f"  {label:>10}", end="")
    print()
    for n_colors in N_COLORS_LEVELS:
        print(f"{n_colors:>8}", end="")
        for mode_label, _ in MODE_CONFIGS:
            matches = [r for r in all_results if r["mode"] == mode_label and r["n_colors"] == n_colors]
            if matches:
                print(f"  {matches[0]['de_lutmatch']:>10.2f}", end="")
            else:
                print(f"  {'─':>10}", end="")
        print()


if __name__ == "__main__":
    main()
