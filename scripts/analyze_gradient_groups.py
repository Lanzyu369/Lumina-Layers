"""Diagnose gradient banding under material-archive preview.

在耗材档案预览下诊断渐变海带纹。

The material-archive pipeline quantises the source image and maps every
unique source colour to exactly one material recipe.  When the source has a
smooth gradient, adjacent source pixels that are perceptually almost
identical can still be mapped to different recipes, producing visible
"banding" (海带纹) stripes in the preview.

This script:

1. Runs ``core.converter.generate_preview_cached`` in material-archive mode
   to obtain the quantised source image and the matched RGB preview.
2. Scans every 4-neighbour adjacent pixel pair and records boundaries where
   the source Lab ΔE is small (i.e. originally a smooth gradient) but the
   matched material colour differs.
3. Merges all such "false split" boundaries via union-find into gradient
   groups — each group is a set of material colours that the user could
   one-click replace together.
4. Emits per-group masks, a compact JSON report, and stitched preview
   panels so we can eyeball whether the detection is accurate before
   wiring it into the UI.

Example:

    python scripts/analyze_gradient_groups.py \
        --image 优化线条+高清.png \
        --width-mm 200 --layers 10 --quantize 256
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import ModelingMode  # noqa: E402
from core.converter import generate_preview_cached  # noqa: E402
from core.material_color_solver import rgb_to_lab  # noqa: E402


DEFAULT_MATERIALS = [
    "瑞贝思/瑞贝思 PLA 白",
    "瑞贝思/瑞贝思 PLA 黑",
    "瑞贝思/瑞贝思 PLA 红",
    "瑞贝思/瑞贝思 PLA 绿",
    "瑞贝思/瑞贝思 PLA 蓝",
    "瑞贝思/瑞贝思 PLA 黄",
    "彩多屋/彩多屋 PLA 浅蓝",
    "彩多屋/彩多屋 PLA 肤色",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _hex(rgb: np.ndarray | tuple[int, int, int] | list[int]) -> str:
    r, g, b = (int(c) for c in rgb)
    return f"#{r:02X}{g:02X}{b:02X}"


def _encode_rgb(rgb_img: np.ndarray) -> np.ndarray:
    """Encode (..., 3) uint8 RGB to a single int32 code per pixel."""
    return (
        rgb_img[..., 0].astype(np.int32) * 65536
        + rgb_img[..., 1].astype(np.int32) * 256
        + rgb_img[..., 2].astype(np.int32)
    )


def _decode_code(code: int) -> tuple[int, int, int]:
    return ((code >> 16) & 0xFF, (code >> 8) & 0xFF, code & 0xFF)


class UnionFind:
    """Minimal path-compressing union-find over integer keys.
    简易路径压缩并查集（用于合并海带纹相邻耗材色）。
    """

    def __init__(self, items) -> None:
        self.parent: dict[int, int] = {int(x): int(x) for x in items}

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra = self.find(a)
        rb = self.find(b)
        if ra != rb:
            self.parent[ra] = rb

    def groups(self) -> dict[int, list[int]]:
        buckets: dict[int, list[int]] = {}
        for item in self.parent:
            root = self.find(item)
            buckets.setdefault(root, []).append(item)
        return buckets


def _adjacent_pair_stats(
    matched_codes: np.ndarray,
    source_lab: np.ndarray,
    solid_mask: np.ndarray,
) -> list[dict]:
    """Collect per-pair Lab ΔE statistics across 4-neighbour boundaries.
    收集上下/左右相邻像素对的原图 Lab ΔE 统计。

    Returns a list of dicts with keys ``code_a``, ``code_b``, ``count``,
    ``median_de``, ``mean_de``, ``p25_de``, ``p75_de``.
    """

    def _collect(a_codes, b_codes, a_lab, b_lab, a_solid, b_solid):
        mask = (a_codes != b_codes) & a_solid & b_solid
        if not mask.any():
            return (
                np.empty(0, dtype=np.int32),
                np.empty(0, dtype=np.int32),
                np.empty(0, dtype=np.float64),
            )
        ca = a_codes[mask]
        cb = b_codes[mask]
        la = a_lab[mask]
        lb = b_lab[mask]
        de = np.linalg.norm(la - lb, axis=1)
        return ca, cb, de

    # Horizontal adjacency (left, right)
    h_a, h_b, h_de = _collect(
        matched_codes[:, :-1],
        matched_codes[:, 1:],
        source_lab[:, :-1],
        source_lab[:, 1:],
        solid_mask[:, :-1],
        solid_mask[:, 1:],
    )
    # Vertical adjacency (top, bottom)
    v_a, v_b, v_de = _collect(
        matched_codes[:-1, :],
        matched_codes[1:, :],
        source_lab[:-1, :],
        source_lab[1:, :],
        solid_mask[:-1, :],
        solid_mask[1:, :],
    )

    all_a = np.concatenate([h_a, v_a])
    all_b = np.concatenate([h_b, v_b])
    all_de = np.concatenate([h_de, v_de])

    if all_a.size == 0:
        return []

    # Canonicalise (a, b) so that a <= b
    swap = all_a > all_b
    tmp = all_a[swap].copy()
    all_a[swap] = all_b[swap]
    all_b[swap] = tmp

    # Compose a stable 64-bit key = (a << 32) | b
    key = (all_a.astype(np.int64) << 32) | all_b.astype(np.int64)
    order = np.argsort(key, kind="stable")
    key_sorted = key[order]
    de_sorted = all_de[order]

    # Split boundaries of each unique key run
    unique_key, start_idx = np.unique(key_sorted, return_index=True)
    end_idx = np.append(start_idx[1:], key_sorted.size)

    stats: list[dict] = []
    for k, s, e in zip(unique_key, start_idx, end_idx):
        de_slice = de_sorted[s:e]
        a_val = int(k >> 32)
        b_val = int(k & 0xFFFFFFFF)
        stats.append(
            {
                "code_a": a_val,
                "code_b": b_val,
                "count": int(de_slice.size),
                "median_de": float(np.median(de_slice)),
                "mean_de": float(np.mean(de_slice)),
                "p25_de": float(np.percentile(de_slice, 25)),
                "p75_de": float(np.percentile(de_slice, 75)),
            }
        )
    return stats


def _source_samples_for_mask(
    quantized: np.ndarray,
    mask_2d: np.ndarray,
    top_n: int = 8,
) -> list[dict]:
    """Return the dominant quantised source colours under ``mask_2d``."""
    if not mask_2d.any():
        return []
    pixels = quantized[mask_2d]
    colours, counts = np.unique(pixels, axis=0, return_counts=True)
    order = np.argsort(-counts)
    colours = colours[order][:top_n]
    counts = counts[order][:top_n]
    return [
        {"hex": _hex(rgb), "rgb": rgb.tolist(), "pixel_count": int(cnt)}
        for rgb, cnt in zip(colours, counts)
    ]


# ---------------------------------------------------------------------------
# Visualisation helpers
# ---------------------------------------------------------------------------


def _draw_swatch_strip(
    width: int, height: int, swatches: list[tuple[tuple[int, int, int], int]]
) -> np.ndarray:
    strip = np.zeros((height, width, 3), dtype=np.uint8)
    total = sum(max(1, c) for _, c in swatches) or 1
    x = 0
    for rgb, cnt in swatches:
        seg = max(4, int(round(width * cnt / total)))
        strip[:, x : x + seg] = rgb
        x += seg
    if x < width and swatches:
        strip[:, x:] = swatches[-1][0]
    return strip


def _render_group_panel(
    quantized: np.ndarray,
    matched: np.ndarray,
    mask_2d: np.ndarray,
    group_colours: list[tuple[tuple[int, int, int], int]],
) -> np.ndarray:
    """Render a three-panel visualisation (source | matched | swatches)."""
    darkening = 0.18
    dark_src = (quantized.astype(np.float32) * darkening).astype(np.uint8)
    dark_matched = (matched.astype(np.float32) * darkening).astype(np.uint8)
    highlighted_src = dark_src.copy()
    highlighted_src[mask_2d] = quantized[mask_2d]
    highlighted_matched = dark_matched.copy()
    highlighted_matched[mask_2d] = matched[mask_2d]
    side_by_side = np.concatenate([highlighted_src, highlighted_matched], axis=1)
    strip = _draw_swatch_strip(
        width=side_by_side.shape[1],
        height=max(30, side_by_side.shape[0] // 16),
        swatches=group_colours,
    )
    return np.concatenate([side_by_side, strip], axis=0)


def _region_palette(count: int) -> np.ndarray:
    """Build a distinct pseudo-random RGB palette for region colour coding."""
    if count <= 0:
        return np.zeros((0, 3), dtype=np.uint8)
    # Golden-ratio hue sweep + fixed S/V gives visually distinct but saturated colours.
    hues = (np.arange(count) * 0.61803398875) % 1.0
    hsv = np.stack([hues, np.full(count, 0.72), np.full(count, 0.95)], axis=1)
    rgb_float = cv2.cvtColor(
        (hsv.reshape(1, -1, 3) * np.asarray([179, 255, 255])).astype(np.uint8),
        cv2.COLOR_HSV2RGB,
    ).reshape(-1, 3)
    return rgb_float.astype(np.uint8)


def _render_region_overlay(
    matched: np.ndarray,
    region_labels_2d: np.ndarray,
    region_ids: list[int],
) -> np.ndarray:
    """Render matched preview with per-region colour-coded overlay (50% alpha)."""
    darkened = (matched.astype(np.float32) * 0.35).astype(np.uint8)
    palette = _region_palette(len(region_ids))
    overlay = darkened.copy()
    for tint, rid in zip(palette, region_ids):
        mask = region_labels_2d == rid
        if not mask.any():
            continue
        region_pixels = matched[mask].astype(np.float32)
        blended = region_pixels * 0.55 + tint.astype(np.float32) * 0.45
        overlay[mask] = np.clip(blended, 0, 255).astype(np.uint8)
    return overlay


def _split_group_into_regions(
    group_mask_2d: np.ndarray,
    matched_codes_2d: np.ndarray,
    connectivity: int,
    min_region_pixels: int,
) -> tuple[np.ndarray, list[dict]]:
    """Label connected regions inside ``group_mask_2d``.
    Returns a tuple ``(labels_2d, regions)`` where ``regions`` is a list of
    region metadata dicts sorted by pixel count (desc). ``labels_2d`` uses 0
    for background; surviving regions keep their original CC ids so ids are
    stable across renders.
    """
    mask_u8 = group_mask_2d.astype(np.uint8)
    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(
        mask_u8, connectivity=connectivity
    )
    regions: list[dict] = []
    for label_id in range(1, num_labels):  # 0 is background
        area = int(stats[label_id, cv2.CC_STAT_AREA])
        if area < min_region_pixels:
            continue
        x = int(stats[label_id, cv2.CC_STAT_LEFT])
        y = int(stats[label_id, cv2.CC_STAT_TOP])
        w = int(stats[label_id, cv2.CC_STAT_WIDTH])
        h = int(stats[label_id, cv2.CC_STAT_HEIGHT])
        region_mask = labels == label_id
        region_codes = matched_codes_2d[region_mask]
        uniq, counts = np.unique(region_codes, return_counts=True)
        order = np.argsort(-counts)
        material_breakdown = [
            {
                "hex": _hex(_decode_code(int(uniq[i]))),
                "rgb": list(_decode_code(int(uniq[i]))),
                "pixel_count": int(counts[i]),
            }
            for i in order
        ]
        cx, cy = centroids[label_id]
        regions.append(
            {
                "label_id": int(label_id),
                "pixel_count": area,
                "bbox": [x, y, x + w, y + h],
                "centroid": [float(cx), float(cy)],
                "material_breakdown": material_breakdown,
            }
        )
    regions.sort(key=lambda r: -r["pixel_count"])
    for idx, region in enumerate(regions, 1):
        region["region_index"] = idx
    return labels, regions


def _merge_small_regions_into_nearest(
    labels_2d: np.ndarray,
    regions: list[dict],
    matched_codes_2d: np.ndarray,
    small_threshold: int,
) -> tuple[np.ndarray, list[dict]]:
    """Merge regions smaller than ``small_threshold`` into the spatially
    nearest larger region (by centroid) within the same gradient group.
    将小于阈值的区域按质心距离合并到同组内最近的大区域。

    Returns a new ``labels_2d`` (small regions rewritten to their target
    label_id) and an aggregated ``regions`` list.  If the caller disables the
    optimisation, this function should not be called.
    """
    if small_threshold <= 0 or not regions:
        return labels_2d, regions
    big = [r for r in regions if r["pixel_count"] >= small_threshold]
    small = [r for r in regions if r["pixel_count"] < small_threshold]
    if not big or not small:
        return labels_2d, regions

    big_centroids = np.asarray([r["centroid"] for r in big], dtype=np.float64)
    big_label_ids = np.asarray([r["label_id"] for r in big], dtype=np.int64)
    new_labels = labels_2d.copy()
    for small_region in small:
        sc = np.asarray(small_region["centroid"], dtype=np.float64)
        distances = np.linalg.norm(big_centroids - sc, axis=1)
        target_label = int(big_label_ids[int(np.argmin(distances))])
        new_labels[labels_2d == small_region["label_id"]] = target_label

    merged: list[dict] = []
    for r in big:
        mask_r = new_labels == r["label_id"]
        if not mask_r.any():
            continue
        area = int(mask_r.sum())
        ys, xs = np.nonzero(mask_r)
        bbox = [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]
        region_codes = matched_codes_2d[mask_r]
        uniq, counts = np.unique(region_codes, return_counts=True)
        order = np.argsort(-counts)
        material_breakdown = [
            {
                "hex": _hex(_decode_code(int(uniq[i]))),
                "rgb": list(_decode_code(int(uniq[i]))),
                "pixel_count": int(counts[i]),
            }
            for i in order
        ]
        merged.append(
            {
                "label_id": int(r["label_id"]),
                "pixel_count": area,
                "bbox": bbox,
                "centroid": [float(xs.mean()), float(ys.mean())],
                "material_breakdown": material_breakdown,
            }
        )
    merged.sort(key=lambda x: -x["pixel_count"])
    for idx, region in enumerate(merged, 1):
        region["region_index"] = idx
    return new_labels, merged


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyse banding gradient groups under material-archive preview."
    )
    parser.add_argument("--image", required=True, type=str, help="Input image path")
    parser.add_argument("--width-mm", type=float, default=200.0, help="Target width in mm")
    parser.add_argument("--layers", type=int, default=10, help="Material layer count (5-10)")
    parser.add_argument(
        "--layer-height-mm", type=float, default=0.08, help="Material layer height"
    )
    parser.add_argument(
        "--quantize", type=int, default=256, help="K-means quantisation colour count"
    )
    parser.add_argument(
        "--material",
        action="append",
        default=None,
        help="Material directory name under materials/ (repeatable).",
    )
    parser.add_argument(
        "--boundary-delta-e",
        type=float,
        default=4.0,
        help=(
            "Median source Lab ΔE across a boundary below which the boundary is "
            "treated as a 'false split' caused by the quantiser (gradient banding)."
        ),
    )
    parser.add_argument(
        "--min-boundary-pixels",
        type=int,
        default=30,
        help="Minimum boundary pixel count required to consider a pair reliable.",
    )
    parser.add_argument(
        "--min-material-pixels",
        type=int,
        default=100,
        help="Ignore material colours contributing fewer pixels in a group.",
    )
    parser.add_argument(
        "--max-matched-de",
        type=float,
        default=30.0,
        help=(
            "Cap on Lab ΔE between any two material colours inside one group. "
            "Prevents transitive chains from merging perceptually different hue "
            "families into the same gradient group."
        ),
    )
    parser.add_argument(
        "--min-region-pixels",
        type=int,
        default=500,
        help=(
            "Minimum pixel count for a spatial region (connected component) "
            "inside a gradient group. Smaller components are ignored as noise."
        ),
    )
    parser.add_argument(
        "--region-connectivity",
        type=int,
        choices=(4, 8),
        default=4,
        help="Pixel connectivity for spatial region labelling (4 or 8).",
    )
    parser.add_argument(
        "--max-regions-rendered-per-group",
        type=int,
        default=6,
        help="Cap on per-region PNG panels rendered per gradient group.",
    )
    parser.add_argument(
        "--merge-small-regions",
        action="store_true",
        help=(
            "Advanced: merge spatial regions smaller than "
            "--small-region-threshold into the nearest larger region (by "
            "centroid distance) within the same gradient group. Off by default."
        ),
    )
    parser.add_argument(
        "--small-region-threshold",
        type=int,
        default=2000,
        help=(
            "Region pixel count below which a region is treated as 'small' "
            "when --merge-small-regions is enabled."
        ),
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output directory (default: output/gradient_analysis_<timestamp>).",
    )
    parser.add_argument(
        "--max-groups-rendered",
        type=int,
        default=20,
        help="Limit the number of per-group PNG panels rendered to disk.",
    )
    return parser.parse_args()


def main() -> int:
    from api.structured_logging import configure_structured_logging

    configure_structured_logging()

    args = _parse_args()

    image_path = Path(args.image)
    if not image_path.is_absolute():
        image_path = ROOT / image_path
    image_path = image_path.resolve()
    if not image_path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")

    materials = args.material or DEFAULT_MATERIALS

    ts = time.strftime("%Y%m%d-%H%M%S")
    out_dir = (
        Path(args.output).resolve()
        if args.output
        else ROOT / "output" / f"gradient_analysis_{ts}"
    )
    (out_dir / "groups").mkdir(parents=True, exist_ok=True)

    print(
        f"[1/4] Generating preview: quantize={args.quantize} layers={args.layers} "
        f"materials={len(materials)}"
    )
    t0 = time.perf_counter()
    preview_img, cache, status_msg = generate_preview_cached(
        image_path=str(image_path),
        lut_path="__material_archive__",
        target_width_mm=args.width_mm,
        color_mode="Material",
        modeling_mode=ModelingMode.HIGH_FIDELITY,
        color_layers=args.layers,
        layer_height_mm=args.layer_height_mm,
        model_enable=False,
        model_only=False,
        quantize_colors=args.quantize,
        enable_cleanup=True,
        is_dark=True,
        material_source="material_archive",
        selected_materials=list(materials),
        material_layer_count=args.layers,
        material_layer_height_mm=args.layer_height_mm,
    )
    if cache is None:
        raise RuntimeError(f"Preview generation failed: {status_msg}")
    t_preview = time.perf_counter() - t0
    print(f"    preview ready in {t_preview:.1f}s  ({status_msg})")

    quantized = cache["quantized_image"].astype(np.uint8)
    matched = cache["matched_rgb"].astype(np.uint8)
    mask_solid = cache["mask_solid"].astype(bool)
    H, W = matched.shape[:2]
    assert quantized.shape[:2] == (H, W)
    assert mask_solid.shape == (H, W)

    # Persist base panels (use cv2 to bypass PIL Chinese-path issues on Windows).
    def _imwrite(path: Path, rgb_arr: np.ndarray) -> None:
        bgr = cv2.cvtColor(rgb_arr, cv2.COLOR_RGB2BGR)
        encoded = cv2.imencode(".png", bgr)[1]
        encoded.tofile(str(path))

    original = np.array(Image.open(image_path).convert("RGB"))
    _imwrite(out_dir / "00_original.png", original)
    _imwrite(out_dir / "01_quantized.png", quantized)
    _imwrite(out_dir / "02_matched_preview.png", matched)
    if isinstance(preview_img, np.ndarray):
        preview_rgb = preview_img
        if preview_rgb.ndim == 3 and preview_rgb.shape[2] == 4:
            preview_rgb = preview_rgb[..., :3]
        _imwrite(out_dir / "03_preview_rendered.png", preview_rgb.astype(np.uint8))
    elif preview_img is not None:
        preview_img.save(out_dir / "03_preview_rendered.png")

    # Compute Lab once for the quantised image (same space the solver uses).
    print("[2/4] Computing source Lab and scanning 4-neighbour boundaries")
    source_lab_flat = rgb_to_lab(quantized.reshape(-1, 3))
    source_lab = source_lab_flat.reshape(H, W, 3)
    matched_codes = _encode_rgb(matched)

    pair_stats = _adjacent_pair_stats(matched_codes, source_lab, mask_solid)
    total_boundary_pixels = sum(p["count"] for p in pair_stats)
    banding_pairs = [
        p
        for p in pair_stats
        if p["median_de"] <= args.boundary_delta_e and p["count"] >= args.min_boundary_pixels
    ]
    print(
        f"    {len(pair_stats)} distinct material-colour pairs along boundaries "
        f"({total_boundary_pixels} boundary px); "
        f"{len(banding_pairs)} look like banding "
        f"(median ΔE≤{args.boundary_delta_e}, count≥{args.min_boundary_pixels})"
    )

    # Merge banding pairs via constrained union-find: A-B are only merged when
    # the resulting cluster's max pairwise matched Lab ΔE stays within the cap.
    # 合并带状纹相邻对时附加 "cluster 内 Lab ΔE 不得超过上限" 的约束，
    # 避免链式传递把不同色系拉到一起。
    unique_codes_sorted = sorted({int(c) for c in np.unique(matched_codes[mask_solid]).tolist()})
    code_lab = {
        code: rgb_to_lab(np.asarray([_decode_code(code)], dtype=np.uint8))[0]
        for code in unique_codes_sorted
    }
    uf = UnionFind(unique_codes_sorted)
    cluster_members: dict[int, list[int]] = {code: [code] for code in unique_codes_sorted}
    # Try pairs in increasing median ΔE so the most confident banding merges happen first.
    for pair in sorted(banding_pairs, key=lambda p: (p["median_de"], -p["count"])):
        a, b = pair["code_a"], pair["code_b"]
        ra, rb = uf.find(a), uf.find(b)
        if ra == rb:
            continue
        combined = cluster_members[ra] + cluster_members[rb]
        labs = np.asarray([code_lab[c] for c in combined], dtype=np.float64)
        if labs.shape[0] >= 2:
            diff = labs[:, None, :] - labs[None, :, :]
            max_de = float(np.sqrt(np.einsum("ijk,ijk->ij", diff, diff)).max())
            if max_de > args.max_matched_de:
                continue
        uf.union(a, b)
        root = uf.find(a)
        cluster_members[root] = combined
        other = rb if root == ra else ra
        cluster_members.pop(other, None)
    buckets = uf.groups()
    # Per-material-colour pixel counts (over solid pixels only)
    solid_codes_flat = matched_codes[mask_solid]
    code_unique, code_counts = np.unique(solid_codes_flat, return_counts=True)
    code_to_count = {int(c): int(n) for c, n in zip(code_unique, code_counts)}

    # Build gradient groups with ≥2 material colours (filtered by min-material-pixels).
    print("[3/4] Assembling gradient groups (≥2 material colours each)")
    groups: list[dict] = []
    for members in buckets.values():
        if len(members) < 2:
            continue
        ranked = sorted(
            (
                {
                    "code": m,
                    "hex": _hex(_decode_code(m)),
                    "rgb": list(_decode_code(m)),
                    "pixel_count": int(code_to_count.get(m, 0)),
                }
                for m in members
            ),
            key=lambda item: -item["pixel_count"],
        )
        kept = [mc for mc in ranked if mc["pixel_count"] >= args.min_material_pixels]
        if len(kept) < 2:
            continue
        total_pixels = sum(mc["pixel_count"] for mc in kept)
        member_codes = np.asarray([mc["code"] for mc in kept], dtype=np.int64)
        group_pixel_mask_flat = np.isin(matched_codes.reshape(-1), member_codes) & mask_solid.reshape(-1)
        group_mask_2d = group_pixel_mask_flat.reshape(H, W)
        # Boundary edges internal to this group (for diagnostics)
        internal_pairs = [
            p
            for p in banding_pairs
            if p["code_a"] in {mc["code"] for mc in kept}
            and p["code_b"] in {mc["code"] for mc in kept}
        ]
        # Source-colour samples in this group's footprint
        source_samples = _source_samples_for_mask(quantized, group_mask_2d)
        # Weighted source Lab mean (representative)
        if source_samples:
            weights = np.asarray([s["pixel_count"] for s in source_samples], dtype=np.float64)
            rgbs = np.asarray([s["rgb"] for s in source_samples], dtype=np.uint8)
            mean_lab = np.average(rgb_to_lab(rgbs), axis=0, weights=weights).tolist()
        else:
            mean_lab = None
        groups.append(
            {
                "material_colours": kept,
                "total_pixel_count": total_pixels,
                "material_colour_count": len(kept),
                "source_colour_samples": source_samples,
                "source_lab_weighted_mean": mean_lab,
                "boundary_pair_count": len(internal_pairs),
                "boundary_edges": sorted(
                    (
                        {
                            "a": _hex(_decode_code(p["code_a"])),
                            "b": _hex(_decode_code(p["code_b"])),
                            "count": p["count"],
                            "median_de": round(p["median_de"], 3),
                            "mean_de": round(p["mean_de"], 3),
                        }
                        for p in internal_pairs
                    ),
                    key=lambda edge: -edge["count"],
                ),
            }
        )

    groups.sort(key=lambda g: -g["total_pixel_count"])
    for i, g in enumerate(groups, 1):
        g["group_index"] = i

    # ---- Spatial region split: each gradient group -> connected components ----
    merge_msg = (
        f", merging small regions (<{args.small_region_threshold} px) into nearest large"
        if args.merge_small_regions
        else ""
    )
    print(
        f"    splitting groups into regions (connectivity={args.region_connectivity}, "
        f"min_region_pixels={args.min_region_pixels}{merge_msg})"
    )
    for g in groups:
        members = np.asarray([mc["code"] for mc in g["material_colours"]], dtype=np.int64)
        group_mask_2d = np.isin(matched_codes.reshape(-1), members).reshape(H, W) & mask_solid
        region_labels_2d, regions = _split_group_into_regions(
            group_mask_2d=group_mask_2d,
            matched_codes_2d=matched_codes,
            connectivity=args.region_connectivity,
            min_region_pixels=args.min_region_pixels,
        )
        regions_before_merge = len(regions)
        if args.merge_small_regions and regions:
            region_labels_2d, regions = _merge_small_regions_into_nearest(
                labels_2d=region_labels_2d,
                regions=regions,
                matched_codes_2d=matched_codes,
                small_threshold=args.small_region_threshold,
            )
        g["_group_mask_2d"] = group_mask_2d
        g["_region_labels_2d"] = region_labels_2d
        g["regions"] = regions
        g["region_count"] = len(regions)
        g["region_count_before_merge"] = regions_before_merge
        g["region_pixel_total"] = int(sum(r["pixel_count"] for r in regions))

    # Render visualisations (bounded).
    print(
        f"[4/4] Rendering up to {min(args.max_groups_rendered, len(groups))} group panels "
        f"(total groups={len(groups)})"
    )
    render_cap = max(0, args.max_groups_rendered)
    for g in groups[:render_cap]:
        group_mask_2d = g["_group_mask_2d"]
        swatches = [(tuple(mc["rgb"]), mc["pixel_count"]) for mc in g["material_colours"]]
        panel = _render_group_panel(quantized, matched, group_mask_2d, swatches)
        _imwrite(out_dir / "groups" / f"group_{g['group_index']:02d}.png", panel)

        # Region colour-coded overlay (useful to eyeball how the group splits
        # spatially before picking a region sub-selection in the UI).
        if g["regions"]:
            region_ids = [r["label_id"] for r in g["regions"]]
            overlay = _render_region_overlay(matched, g["_region_labels_2d"], region_ids)
            _imwrite(
                out_dir / "groups" / f"group_{g['group_index']:02d}_regions_overlay.png",
                overlay,
            )

        # Per-region mini panels.
        region_dir = out_dir / "groups" / f"group_{g['group_index']:02d}_regions"
        per_region_cap = max(0, args.max_regions_rendered_per_group)
        if per_region_cap and g["regions"]:
            region_dir.mkdir(exist_ok=True)
            for r in g["regions"][:per_region_cap]:
                region_mask_2d = g["_region_labels_2d"] == r["label_id"]
                swatches_r = [(tuple(mb["rgb"]), mb["pixel_count"]) for mb in r["material_breakdown"]]
                panel_r = _render_group_panel(quantized, matched, region_mask_2d, swatches_r)
                _imwrite(region_dir / f"region_{r['region_index']:02d}.png", panel_r)

    # Drop internal numpy arrays before JSON serialisation.
    for g in groups:
        g.pop("_group_mask_2d", None)
        g.pop("_region_labels_2d", None)

    # Emit JSON + human summary.
    summary_payload = {
        "image": str(image_path),
        "materials": list(materials),
        "parameters": {
            "width_mm": args.width_mm,
            "layers": args.layers,
            "layer_height_mm": args.layer_height_mm,
            "quantize": args.quantize,
            "boundary_delta_e": args.boundary_delta_e,
            "min_boundary_pixels": args.min_boundary_pixels,
            "min_material_pixels": args.min_material_pixels,
            "max_matched_de": args.max_matched_de,
            "min_region_pixels": args.min_region_pixels,
            "region_connectivity": args.region_connectivity,
            "merge_small_regions": bool(args.merge_small_regions),
            "small_region_threshold": args.small_region_threshold,
        },
        "preview_seconds": round(t_preview, 3),
        "image_shape": [int(H), int(W)],
        "solid_pixel_count": int(mask_solid.sum()),
        "distinct_material_colours": len(unique_codes_sorted),
        "total_boundary_pixels": total_boundary_pixels,
        "banding_pair_count": len(banding_pairs),
        "gradient_group_count": len(groups),
        "gradient_groups": groups,
        "top_banding_pairs": sorted(
            (
                {
                    "a": _hex(_decode_code(p["code_a"])),
                    "b": _hex(_decode_code(p["code_b"])),
                    "count": p["count"],
                    "median_de": round(p["median_de"], 3),
                    "mean_de": round(p["mean_de"], 3),
                    "p25_de": round(p["p25_de"], 3),
                    "p75_de": round(p["p75_de"], 3),
                }
                for p in banding_pairs
            ),
            key=lambda edge: -edge["count"],
        )[:50],
    }
    (out_dir / "groups.json").write_text(
        json.dumps(summary_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    summary_lines: list[str] = []
    summary_lines.append(f"Image              : {image_path}")
    summary_lines.append(
        f"Preview            : {H}x{W} solid={int(mask_solid.sum())} "
        f"materials_distinct={len(unique_codes_sorted)}"
    )
    summary_lines.append(
        f"Banding thresholds : median ΔE<={args.boundary_delta_e}  "
        f"boundary_count>={args.min_boundary_pixels}  "
        f"min_material_pixels>={args.min_material_pixels}"
    )
    summary_lines.append(
        f"Banding pairs      : {len(banding_pairs)} / {len(pair_stats)} boundary pairs"
    )
    summary_lines.append(f"Gradient groups    : {len(groups)}")
    summary_lines.append("")
    for g in groups[:render_cap]:
        mat_summary = ", ".join(f"{mc['hex']}({mc['pixel_count']})" for mc in g["material_colours"])
        src_summary = ", ".join(s["hex"] for s in g["source_colour_samples"][:5])
        region_summary = ", ".join(
            f"R{r['region_index']}({r['pixel_count']})"
            for r in g["regions"][: args.max_regions_rendered_per_group]
        )
        region_count_desc = (
            f"{g['region_count']} (was {g['region_count_before_merge']} before merge)"
            if args.merge_small_regions and g["region_count"] != g["region_count_before_merge"]
            else str(g["region_count"])
        )
        summary_lines.append(
            f"  #{g['group_index']:02d}  {g['total_pixel_count']:>8d} px  "
            f"{g['material_colour_count']} materials  "
            f"regions={region_count_desc}  edges={g['boundary_pair_count']}\n"
            f"       materials : {mat_summary}\n"
            f"       sources≈  : {src_summary}\n"
            f"       regions   : {region_summary}"
        )
    (out_dir / "summary.txt").write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    print("\n" + "\n".join(summary_lines))
    print(f"\nOutput dir: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
