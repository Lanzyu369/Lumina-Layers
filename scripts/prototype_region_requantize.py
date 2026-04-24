"""Prototype: per-region secondary re-quantisation vs flatten.
区域级二次量化原型，对比现有"去海带纹=全染代表色"方案。

Uses the canonical backend detector :func:`core.gradient_group_analyzer.
analyze_gradient_groups_with_region_id_map` with the *same defaults* the
preview pipeline feeds to the UI, so the groups / regions this script sees
are identical to what the user sees in the Color Workstation panel.

Three variants are rendered for eyeball comparison:

1. ``matched``     — unchanged material-archive preview (baseline).
2. ``flatten``     — every non-representative hex in each group is rewritten
   to the group's ``representative_hex`` (= the UI's top-level "Flatten all"
   button, ``applyAutoGradientReplace``).
3. ``requantize``  — per spatial region, weighted-majority-vote snap to the
   top-K most prevalent material hexes. Stripes collapse into contiguous
   bands while low-frequency gradient direction is preserved.

Example::

    python scripts/prototype_region_requantize.py \\
        --image 优化线条+高清.png \\
        --layers 10 --quantize 256 --k 3 --blur-sigma 10
"""

from __future__ import annotations

import argparse
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
from core.gradient_group_analyzer import (  # noqa: E402
    REGION_ID_ENCODING_MULTIPLIER,
    GradientGroup,
    GradientGroupAnalysisParams,
    analyze_gradient_groups_with_region_id_map,
)
from core.material_cache import load_material_solver_cache_with_fallback  # noqa: E402
from core.material_lut_synthesis import load_multiple_materials  # noqa: E402
from core.pipeline.processing_ops.kmeans_quantizer import quantize_colors  # noqa: E402


DEFAULT_MATERIALS = [
    "瑞贝思/瑞贝思 PLA 白",
    "瑞贝思/瑞贝思 PLA 黑",
    "瑞贝思/瑞贝思 PLA 红",
    "瑞贝思/瑞贝思 PLA 绿",
    "瑞贝思/瑞贝思 PLA 蓝",
    "瑞贝思/瑞贝思 PLA 黄",
    "彩多屋/PLA 天蓝色",
    "彩多屋/彩多屋 PLA 肤色",
]


# ---------------------------------------------------------------------------
# IO helper
# ---------------------------------------------------------------------------


def _imwrite(path: Path, rgb_arr: np.ndarray) -> None:
    """Write an RGB uint8 array via cv2 imencode to survive CJK paths on Windows."""
    bgr = cv2.cvtColor(rgb_arr, cv2.COLOR_RGB2BGR)
    encoded = cv2.imencode(".png", bgr)[1]
    encoded.tofile(str(path))


# ---------------------------------------------------------------------------
# Two quantisation strategies
# ---------------------------------------------------------------------------


def _flatten_group_all_pixels(
    matched: np.ndarray,
    group_mask: np.ndarray,
    representative_rgb: tuple[int, int, int],
) -> None:
    """In-place: replace every pixel in ``group_mask`` with representative.
    原地将 ``group_mask`` 内所有像素替换为组代表色，对齐前端
    ``applyAutoGradientReplace`` 的 ``colorRemapMap`` 语义。
    """
    if not group_mask.any():
        return
    matched[group_mask] = np.asarray(representative_rgb, dtype=np.uint8)


def _local_requantize_region(
    matched_out: np.ndarray,
    matched_src: np.ndarray,
    original_source_rgb: np.ndarray,
    region_mask: np.ndarray,
    *,
    material_solver_cache,
    materials,
    local_quantize_colors: int,
) -> None:
    """User-requested two-step test: local 256-quantise + re-match materials.
    用户要求的两步试验：对原图的该 region 单独做 256 色量化（不与全图共用
    调色板预算），再用同一材料求解器重新匹配材料，最后合并回 matched。

    Step 1: the global preview already produced ``matched_src`` via a
    WHOLE-image 256-colour quantisation followed by material matching.
    Step 2: here we re-quantise the original source pixels belonging to
    this region to their own dedicated N-colour palette (default 256,
    but may be fewer if the region has fewer unique source colours),
    then push those new quantised colours through the same material
    solver to obtain a locally-computed matched patch, which overwrites
    the region in ``matched_out``.

    This tests whether dedicating a full 256-colour budget to the
    region (instead of sharing it with the rest of the canvas) reduces
    kelp banding after material matching.
    """
    if not region_mask.any():
        return

    ys, xs = np.nonzero(region_mask)
    # Extract original source pixels as a (N, 1, 3) image so quantize_colors
    # can treat them as a contiguous patch; it doesn't require true spatial
    # layout since k-means operates on the pixel set.
    region_pixels = original_source_rgb[ys, xs]  # (N, 3)
    patch_img = region_pixels.reshape(-1, 1, 3)
    locally_quantized = quantize_colors(
        patch_img, local_quantize_colors, skip_post_blur=True
    ).reshape(-1, 3)

    # Unique-colour pass through the material solver.
    unique_colors, inverse = np.unique(locally_quantized, axis=0, return_inverse=True)
    matched_rgb_unique, _recipes, _delta = material_solver_cache.lookup(
        unique_colors, materials
    )
    matched_pixels = matched_rgb_unique[inverse]

    matched_out[ys, xs] = matched_pixels.astype(np.uint8)


def _requantize_region_majority_vote(
    matched_out: np.ndarray,
    matched_src: np.ndarray,
    region_mask: np.ndarray,
    material_breakdown: list[dict],
    *,
    blur_sigma: float,
    top_k: int,
) -> None:
    """Weighted-majority-vote snap-to-palette, strictly inside ``region_mask``.
    加权多数投票再量化：对每个候选色建二值 mask，高斯软计数，每个像素输出
    取邻域内票数最多的候选色。区域外像素不投票，避免跨区漏色。

    This in-place writes into ``matched_out`` only for the in-mask pixels;
    samples are taken from ``matched_src`` (the original preview) so
    neighbouring regions already processed earlier don't pollute the vote.
    原图作为投票源、输出写入 matched_out，避免相邻区域处理顺序影响结果。
    """
    if not material_breakdown or not region_mask.any():
        return

    top_candidates = material_breakdown[: max(1, top_k)]
    palette = np.asarray([mc["rgb"] for mc in top_candidates], dtype=np.uint8)

    # Bbox crop (+ kernel-radius padding so Gaussian tail stays valid).
    ksize = max(3, int(round(blur_sigma * 6)) | 1)
    pad = ksize // 2
    H, W = matched_src.shape[:2]
    ys, xs = np.nonzero(region_mask)
    y0 = max(0, int(ys.min()) - pad)
    y1 = min(H, int(ys.max()) + 1 + pad)
    x0 = max(0, int(xs.min()) - pad)
    x1 = min(W, int(xs.max()) + 1 + pad)
    patch = matched_src[y0:y1, x0:x1]
    mask_patch = region_mask[y0:y1, x0:x1]

    # Per-candidate soft vote count via Gaussian convolution of binary mask.
    votes = np.empty(
        (patch.shape[0], patch.shape[1], palette.shape[0]), dtype=np.float32
    )
    for k, rgb in enumerate(palette):
        bin_mask = (
            (patch[..., 0] == rgb[0])
            & (patch[..., 1] == rgb[1])
            & (patch[..., 2] == rgb[2])
            & mask_patch
        ).astype(np.float32)
        votes[..., k] = cv2.GaussianBlur(
            bin_mask, (ksize, ksize), sigmaX=blur_sigma, sigmaY=blur_sigma
        )
    winner_patch = np.argmax(votes, axis=-1).astype(np.int32)

    # Map winner indices back to absolute coordinates and write only in-mask.
    winner_full = np.full((H, W), -1, dtype=np.int32)
    winner_full[y0:y1, x0:x1] = winner_patch
    winners = winner_full[ys, xs]
    matched_out[ys, xs] = palette[winners]


# ---------------------------------------------------------------------------
# Comparison rendering
# ---------------------------------------------------------------------------


def _label_strip(width: int, labels: list[str]) -> np.ndarray:
    strip_h = 28
    strip = np.full((strip_h, width, 3), 240, dtype=np.uint8)
    segments = width // len(labels)
    for i, label in enumerate(labels):
        cv2.putText(
            strip,
            label,
            (i * segments + 10, 20),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (20, 20, 20),
            1,
            cv2.LINE_AA,
        )
    return strip


def _side_by_side(images: list[np.ndarray], labels: list[str]) -> np.ndarray:
    target_h = max(im.shape[0] for im in images)
    resized = []
    for im in images:
        if im.shape[0] != target_h:
            scale = target_h / im.shape[0]
            new_w = max(1, int(round(im.shape[1] * scale)))
            resized.append(cv2.resize(im, (new_w, target_h), interpolation=cv2.INTER_AREA))
        else:
            resized.append(im)
    combined = np.concatenate(resized, axis=1)
    header = _label_strip(combined.shape[1], labels)
    return np.concatenate([header, combined], axis=0)


def _group_coverage_overlay(
    matched: np.ndarray,
    region_id_map: np.ndarray,
) -> np.ndarray:
    """Colour-code each gradient group on top of the dimmed preview.
    每个渐变组用一种显眼颜色覆盖在暗化的 matched 上，便于肉眼判断脸部
    被哪个组覆盖、是否完整。
    """
    base = (matched.astype(np.float32) * 0.32).astype(np.uint8)
    # Extract group_index = encoded // MULT (0 means no group).
    group_index_map = (region_id_map // REGION_ID_ENCODING_MULTIPLIER).astype(np.int32)
    unique_groups = [int(g) for g in np.unique(group_index_map) if g != 0]
    if not unique_groups:
        return base
    # Golden-ratio hue sweep for maximally distinct colours.
    hues = (np.arange(len(unique_groups)) * 0.61803398875) % 1.0
    hsv = np.stack(
        [hues * 179, np.full(len(unique_groups), 200), np.full(len(unique_groups), 230)],
        axis=1,
    ).astype(np.uint8)
    palette = cv2.cvtColor(hsv.reshape(1, -1, 3), cv2.COLOR_HSV2RGB).reshape(-1, 3)
    out = base.copy()
    for colour, g in zip(palette, unique_groups):
        mask = group_index_map == g
        if not mask.any():
            continue
        tinted = (
            matched[mask].astype(np.float32) * 0.45
            + colour.astype(np.float32) * 0.55
        )
        out[mask] = np.clip(tinted, 0, 255).astype(np.uint8)
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Prototype per-region secondary quantisation vs flatten, using the "
            "canonical core.gradient_group_analyzer backend. 使用后端正式"
            "渐变识别算法对比区域级二次量化 vs 当前平坦化去海带纹。"
        )
    )
    p.add_argument("--image", required=True, type=str)
    p.add_argument("--width-mm", type=float, default=200.0)
    p.add_argument("--layers", type=int, default=10)
    p.add_argument("--layer-height-mm", type=float, default=0.08)
    p.add_argument("--quantize", type=int, default=256)
    p.add_argument("--material", action="append", default=None)
    p.add_argument("--auto-bg", action="store_true")
    p.add_argument("--bg-tol", type=int, default=40)
    # Re-quantisation parameters.
    p.add_argument(
        "--k",
        type=int,
        default=3,
        help="Per-region palette cap: keep the top-K most prevalent hexes.",
    )
    p.add_argument(
        "--blur-sigma",
        type=float,
        default=10.0,
        help=(
            "Gaussian sigma (pixels) for the per-candidate vote convolution. "
            "Should be ≥ kelp stripe width so the majority-vote window spans "
            "several stripes. 6-16 px usually works for 2000px-wide canvases."
        ),
    )
    p.add_argument(
        "--mode",
        type=str,
        choices=("majority", "local-requantize"),
        default="local-requantize",
        help=(
            "Requantise algorithm: 'majority' = per-region weighted majority "
            "vote on top-K existing material hexes; 'local-requantize' = "
            "step1 global 256-quant + step2 per-region local 256-quant of "
            "the ORIGINAL source, re-matched through the material solver "
            "and spliced back in (the user's two-step experiment)."
        ),
    )
    p.add_argument(
        "--local-quantize-colors",
        type=int,
        default=256,
        help="N for the local k-means quantisation under 'local-requantize' mode.",
    )
    p.add_argument(
        "--max-groups-rendered",
        type=int,
        default=12,
        help="Limit per-group comparison panels on disk.",
    )
    p.add_argument(
        "--apply-to",
        type=str,
        default=None,
        help=(
            "Comma-separated region selector list, e.g. '3:5,3:7,5:2'. "
            "Each entry is 'group_index:region_index' (1-based, matching the "
            "identification crops under groups/GXX/RYY.png). Only listed "
            "regions receive the requantisation; all others stay baseline. "
            "If omitted, every region is requantised (bulk preview)."
        ),
    )
    p.add_argument(
        "--skip-identification-crops",
        action="store_true",
        help="Don't re-render per-region identification crops (faster reruns).",
    )
    p.add_argument(
        "--max-regions-per-group",
        type=int,
        default=15,
        help=(
            "Render at most the top-N regions per group (by pixel count) as "
            "identification crops. Total region count is typically in the "
            "hundreds; a cap keeps the output folder browseable."
        ),
    )
    p.add_argument("--output", type=str, default=None)
    return p.parse_args()


def _parse_region_selector(spec: str | None) -> set[tuple[int, int]] | None:
    """Parse ``'3:5,3:7,5:2'`` into ``{(3, 5), (3, 7), (5, 2)}``; None = all.
    将 CLI 选择表达式解析为 (group, region) 集合；None 表示应用到所有 region。
    """
    if spec is None:
        return None
    result: set[tuple[int, int]] = set()
    for token in spec.split(","):
        token = token.strip()
        if not token:
            continue
        try:
            g_str, r_str = token.split(":")
            result.add((int(g_str), int(r_str)))
        except ValueError as exc:
            raise ValueError(
                f"Invalid --apply-to token {token!r}; expected 'group:region'"
            ) from exc
    return result


def _render_region_identification(
    matched: np.ndarray,
    region_mask: np.ndarray,
    bbox: tuple[int, int, int, int],
    pad: int = 32,
) -> np.ndarray:
    """Return a crop of ``matched`` with the region highlighted.
    裁 bbox 并把 region 外的像素大幅变暗 + 外框描亮蓝，方便用户一眼
    看出"这个 region 对应的是图里哪块内容"。
    """
    H, W = matched.shape[:2]
    x0 = max(0, bbox[0] - pad)
    y0 = max(0, bbox[1] - pad)
    x1 = min(W, bbox[2] + pad)
    y1 = min(H, bbox[3] + pad)
    crop = matched[y0:y1, x0:x1].copy()
    local_mask = region_mask[y0:y1, x0:x1]

    # Dim everything outside the region to 25% brightness so the region
    # itself pops visually, but keep enough context to recognise body part.
    dimmed = (crop.astype(np.float32) * 0.25).astype(np.uint8)
    out = np.where(local_mask[..., None], crop, dimmed)

    # Draw a thin cyan outline around the region mask for extra pop.
    edge = local_mask.astype(np.uint8) * 255
    edge = cv2.Canny(edge, 50, 150)
    out[edge > 0] = (0, 220, 255)
    return out


def main() -> int:
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
        else ROOT / "output" / f"requantize_proto_{ts}"
    )
    (out_dir / "groups").mkdir(parents=True, exist_ok=True)
    print(f"Output -> {out_dir}")

    # ------- Preview generation -------
    print(
        f"[1/3] Preview quantize={args.quantize} layers={args.layers} "
        f"materials={len(materials)}"
    )
    t0 = time.perf_counter()
    preview_img, cache, status = generate_preview_cached(
        image_path=str(image_path),
        lut_path="__material_archive__",
        target_width_mm=args.width_mm,
        auto_bg=args.auto_bg,
        bg_tol=args.bg_tol,
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
        raise RuntimeError(f"Preview generation failed: {status}")
    print(f"    ready in {time.perf_counter() - t0:.1f}s  ({status})")

    quantized = np.asarray(cache["quantized_image"], dtype=np.uint8)
    matched = np.asarray(cache["matched_rgb"], dtype=np.uint8)
    mask_solid = np.asarray(cache["mask_solid"], dtype=bool)

    _imwrite(out_dir / "00_original.png", np.array(Image.open(image_path).convert("RGB")))
    _imwrite(out_dir / "01_matched_baseline.png", matched)

    # ------- Canonical gradient detection (same params the UI uses) -------
    # NOTE: GradientGroupAnalysisParams() defaults match api.routers.converter.
    # preview._compute_and_store_gradient_groups → backend uses these exact
    # values, so the groups we process here are the groups the UI panel shows.
    # 后端 preview 路径调用时用的就是默认参数，脚本也保持一致保证 UI 同步。
    print("[2/3] Canonical gradient-group detection (core.gradient_group_analyzer)")
    analysis = analyze_gradient_groups_with_region_id_map(
        matched_rgb=matched,
        quantized_rgb=quantized,
        mask_solid=mask_solid,
        params=GradientGroupAnalysisParams(),
    )
    groups: list[GradientGroup] = analysis.groups
    region_id_map = analysis.region_id_map
    print(
        f"    {len(groups)} groups, {sum(len(g.regions) for g in groups)} regions "
        f"(boundary_delta_e=8.0 default, matches UI)"
    )
    for g in groups:
        hexes = ", ".join(mc["hex"] for mc in g.material_colours)
        print(
            f"    G{g.group_index:02d}  px={g.total_pixel_count:>8d}  "
            f"regions={len(g.regions):>3d}  repr={g.representative_hex}  "
            f"hexes=[{hexes}]"
        )

    # ------- Per-region identification crops (let the user pick targets) -------
    # 为每个 region 输出一张"这个 region 在图里对应哪块"的标识图，
    # 区域内正常亮度、区域外调暗到 25%、外沿描青色边，便于人眼快速确认。
    selector = _parse_region_selector(args.apply_to)
    if selector is not None:
        print(f"    --apply-to filter: {sorted(selector)}")

    if not args.skip_identification_crops:
        cap = max(0, args.max_regions_per_group)
        print(
            f"    rendering per-region identification crops "
            f"(top {cap}/group by pixel count, groups/GXX/RYY.png)"
        )
        for g in groups:
            group_dir = out_dir / "groups" / f"G{g.group_index:02d}"
            group_dir.mkdir(parents=True, exist_ok=True)
            group_encoded_base = g.group_index * REGION_ID_ENCODING_MULTIPLIER
            # Regions are already sorted by descending pixel_count in the
            # core analyser, but sort again defensively in case upstream
            # changes ordering (e.g. spatial-adjacency reshuffle).
            top_regions = sorted(g.regions, key=lambda r: -r.pixel_count)[:cap]
            for r in top_regions:
                encoded = group_encoded_base + r.region_index
                region_mask = region_id_map == encoded
                if not region_mask.any():
                    continue
                ident = _render_region_identification(matched, region_mask, r.bbox)
                _imwrite(
                    group_dir / f"R{r.region_index:02d}_px{r.pixel_count}.png",
                    ident,
                )

    # ------- Apply variants -------
    selected_desc = (
        "ALL regions" if selector is None
        else f"{len(selector)} selected region(s)"
    )
    print(
        f"[3/3] Building flatten (group-level, UI apply_now) "
        f"+ requantize[{args.mode}] on {selected_desc}"
    )

    # Materials list + solver cache loaded once, reused for every region under
    # 'local-requantize' mode (matches the same solver the pipeline used).
    # 仅 local-requantize 模式需要；majority 模式下不必加载。
    mat_params = None
    solver_cache = None
    original_rgb = None
    if args.mode == "local-requantize":
        mat_params = load_multiple_materials(list(materials))
        # Pipeline default substrate is "white" (see p03_core_processing.py).
        # 求解器缓存使用与管线一致的 "white" 基底。
        solver_cache, _grid = load_material_solver_cache_with_fallback(
            materials=mat_params,
            layer_count=args.layers,
            layer_height_mm=args.layer_height_mm,
            substrate="white",
        )
        if solver_cache is None:
            raise RuntimeError(
                "Failed to load material solver cache for substrate=white; "
                "run a normal preview first so the cache is built on disk."
            )
        # Load original source and resize to preview resolution so index-aligned
        # sampling by region_mask works.
        # 原图需缩放到预览分辨率，以便用 region_mask 直接索引像素。
        original_pil = Image.open(image_path).convert("RGB")
        target_h, target_w = matched.shape[:2]
        if original_pil.size != (target_w, target_h):
            original_pil = original_pil.resize((target_w, target_h), Image.LANCZOS)
        original_rgb = np.asarray(original_pil, dtype=np.uint8)

    flatten_full = matched.copy()
    requant_full = matched.copy()
    for g in groups:
        group_encoded_base = g.group_index * REGION_ID_ENCODING_MULTIPLIER
        group_mask = (
            (region_id_map >= group_encoded_base)
            & (region_id_map < group_encoded_base + REGION_ID_ENCODING_MULTIPLIER)
        )
        _flatten_group_all_pixels(flatten_full, group_mask, g.representative_rgb)

        for r in g.regions:
            if selector is not None and (g.group_index, r.region_index) not in selector:
                continue
            encoded = group_encoded_base + r.region_index
            region_mask = region_id_map == encoded
            if args.mode == "majority":
                _requantize_region_majority_vote(
                    requant_full,
                    matched,
                    region_mask,
                    r.material_breakdown,
                    blur_sigma=args.blur_sigma,
                    top_k=args.k,
                )
            else:  # local-requantize
                _local_requantize_region(
                    requant_full,
                    matched,
                    original_rgb,
                    region_mask,
                    material_solver_cache=solver_cache,
                    materials=mat_params,
                    local_quantize_colors=args.local_quantize_colors,
                )

    _imwrite(out_dir / "02_flatten_full.png", flatten_full)
    _imwrite(out_dir / "03_requantize_full.png", requant_full)

    # Diff mask: make it obvious which pixels each variant actually modified.
    flat_diff = np.any(flatten_full != matched, axis=-1)
    req_diff = np.any(requant_full != matched, axis=-1)
    diff_flat = np.where(
        flat_diff[..., None],
        np.array([0, 255, 0], dtype=np.uint8),
        (matched.astype(np.float32) * 0.25).astype(np.uint8),
    )
    diff_req = np.where(
        req_diff[..., None],
        np.array([255, 0, 255], dtype=np.uint8),
        (matched.astype(np.float32) * 0.25).astype(np.uint8),
    )
    _imwrite(out_dir / "05_flatten_diff_mask.png", diff_flat)
    _imwrite(out_dir / "06_requantize_diff_mask.png", diff_req)
    print(
        f"    flatten modified {int(flat_diff.sum())} px "
        f"({100 * flat_diff.mean():.1f}% of canvas); "
        f"requantize modified {int(req_diff.sum())} px "
        f"({100 * req_diff.mean():.1f}% of canvas)"
    )

    # Per-group coverage colour map so we can see exactly where each group
    # lives and whether the face is split across multiple groups.
    _imwrite(out_dir / "07_group_coverage.png", _group_coverage_overlay(matched, region_id_map))

    # Full 3-way comparison.
    _imwrite(
        out_dir / "04_full_compare.png",
        _side_by_side(
            [matched, flatten_full, requant_full],
            labels=["matched (baseline)", "flatten (current UI)", f"requantize K={args.k}"],
        ),
    )

    # Per-group cropped panels.
    render_cap = max(0, args.max_groups_rendered)
    for g in groups[:render_cap]:
        if not g.regions:
            continue
        xs0 = min(r.bbox[0] for r in g.regions)
        ys0 = min(r.bbox[1] for r in g.regions)
        xs1 = max(r.bbox[2] for r in g.regions)
        ys1 = max(r.bbox[3] for r in g.regions)
        pad = 24
        H, W = matched.shape[:2]
        xs0 = max(0, xs0 - pad)
        ys0 = max(0, ys0 - pad)
        xs1 = min(W, xs1 + pad)
        ys1 = min(H, ys1 + pad)
        crops = [
            matched[ys0:ys1, xs0:xs1],
            flatten_full[ys0:ys1, xs0:xs1],
            requant_full[ys0:ys1, xs0:xs1],
        ]
        panel = _side_by_side(
            crops,
            labels=[
                f"G{g.group_index:02d} matched",
                f"G{g.group_index:02d} flatten",
                f"G{g.group_index:02d} requantize K={args.k}",
            ],
        )
        _imwrite(out_dir / "groups" / f"group_{g.group_index:02d}.png", panel)

    print("\nDone.")
    print(f"Full compare : {out_dir / '04_full_compare.png'}")
    print(f"Diff masks   : {out_dir / '05_flatten_diff_mask.png'}, "
          f"{out_dir / '06_requantize_diff_mask.png'}")
    print(f"Group coverage colour map: {out_dir / '07_group_coverage.png'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
