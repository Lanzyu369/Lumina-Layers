"""Gradient-group analysis for material-archive preview banding.

渐变组分析：识别材料档案预览中被量化为多个耗材色的平滑渐变。

When the material-archive pipeline quantises a source image and maps each
unique source colour to a single material recipe, smooth gradients in the
source can be sliced into several discrete material colours — producing
visible banding (海带纹). This module locates those banded regions so the
UI can offer the user a one-click "replace the whole gradient with a single
representative colour" action or the more granular "replace one spatial
region" action.

The algorithm has three stages:

1. **Boundary scan.** For every 4-neighbour adjacent pixel pair where the
   matched material colour changes, record the source Lab ΔE. Pairs whose
   *median* source ΔE is low were originally a smooth gradient: the split
   into different material colours is an artefact of quantisation.

2. **Colour clustering.** Treat each small-ΔE boundary as an undirected
   edge and union its two material-colour endpoints. A secondary constraint
   caps the maximum pairwise Lab ΔE inside a cluster to prevent transitive
   chains from merging perceptually different hue families.

3. **Spatial region split.** Inside each colour cluster, label the
   connected components of the pixel mask to get the physical regions
   (face, mouth, sleeve, etc.). Optionally merge small components into the
   nearest larger one for cleaner UX.

All heavy lifting is plain NumPy / OpenCV so the function stays worker-
safe and has no UI or HTTP dependencies. The caller is responsible for
serialising the returned structures (every field is JSON-ready).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

import cv2
import numpy as np

from core.material_color_solver import rgb_to_lab


# ---------------------------------------------------------------------------
# Public parameters and return structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GradientGroupAnalysisParams:
    """Tunable thresholds for :func:`analyze_gradient_groups`.
    :func:`analyze_gradient_groups` 的可调阈值集合。

    Attributes:
        boundary_delta_e: Median source Lab ΔE across a 4-neighbour boundary
            below which we treat the material-colour split as gradient
            banding rather than a real edge.
        min_boundary_pixels: Minimum boundary pixel count required for a
            (material_a, material_b) pair to be considered reliable.
        min_material_pixels: Material-colour contribution threshold inside a
            gradient group; colours with fewer pixels are dropped.
        max_matched_de: Cap on pairwise matched Lab ΔE inside one group.
            Prevents transitive chains from merging blue → purple → pink.
        min_region_pixels: Minimum pixel count for a connected component to
            survive as a spatial region.
        region_connectivity: 4 or 8 — pixel adjacency for region labelling.
        merge_small_regions: If True, small regions (< ``small_region_threshold``)
            are merged by centroid distance into the nearest large region
            inside the same gradient group.
        small_region_threshold: Region pixel count below which a region is
            considered "small" when ``merge_small_regions`` is enabled.
    """

    boundary_delta_e: float = 8.0
    min_boundary_pixels: int = 15
    min_material_pixels: int = 30
    max_matched_de: float = 30.0
    min_region_pixels: int = 500
    region_connectivity: int = 4
    merge_small_regions: bool = False
    small_region_threshold: int = 2000

    def __post_init__(self) -> None:
        if self.boundary_delta_e < 0:
            raise ValueError("boundary_delta_e must be non-negative")
        if self.min_boundary_pixels < 1:
            raise ValueError("min_boundary_pixels must be >= 1")
        if self.min_material_pixels < 1:
            raise ValueError("min_material_pixels must be >= 1")
        if self.max_matched_de < 0:
            raise ValueError("max_matched_de must be non-negative")
        if self.min_region_pixels < 1:
            raise ValueError("min_region_pixels must be >= 1")
        if self.region_connectivity not in (4, 8):
            raise ValueError("region_connectivity must be 4 or 8")
        if self.small_region_threshold < 1:
            raise ValueError("small_region_threshold must be >= 1")


@dataclass
class GradientGroupRegion:
    """A connected spatial region inside a gradient group."""

    region_index: int  # 1-based index ordered by descending pixel_count
    pixel_count: int
    bbox: tuple[int, int, int, int]  # (x0, y0, x1, y1) inclusive-exclusive
    centroid: tuple[float, float]  # (cx, cy) in pixel coordinates
    material_breakdown: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class GradientGroup:
    """A cluster of material colours that originated from a smooth gradient."""

    group_index: int  # 1-based index ordered by descending total_pixel_count
    total_pixel_count: int
    material_colour_count: int
    material_colours: list[dict[str, Any]]
    representative_hex: str
    representative_rgb: tuple[int, int, int]
    boundary_pair_count: int
    regions: list[GradientGroupRegion]


# Encoding multiplier used when packing (group_index, region_index) into a
# single uint32 value for the region_id_map. 10000 comfortably exceeds any
# realistic per-group region count while staying well under uint32's ceiling
# for any plausible group_index, keeping the encoding trivially invertible
# for debugging (``group = encoded // 10000``, ``region = encoded % 10000``).
# 编码倍率：把 (group_index, region_index) 压成单个 uint32 使用，10000
# 足以覆盖任何合理的 region 数量，同时便于反解以辅助排查。
REGION_ID_ENCODING_MULTIPLIER: int = 10000


def _order_regions_by_spatial_adjacency(
    raw: list[GradientGroupRegion],
) -> list[GradientGroupRegion]:
    """Reorder regions so spatially adjacent ones land near each other.

    The list is produced by a classic nearest-neighbour TSP heuristic: the
    region with the most pixels becomes entry 1 (so the UI keeps its
    "largest / most important first" semantics), then each subsequent
    entry is the unvisited region whose centroid is closest to the
    previously placed region's centroid. Ties in pixel count or distance
    fall back to a stable input order for determinism.

    Purely spatial centroid distance is used. Region shape/adjacency via
    pixel edges would be more accurate, but the centroid approximation is
    good enough for list ordering and avoids allocating an N² adjacency
    graph. Callers are still free to keep pixel-count as a tiebreaker by
    pre-sorting, which is what both call sites already do.

    最近邻启发式：最大 region 放第 1 位（保留"主要区域在前"的 UI 语义），
    之后每一项都是离上一个已放置 region 质心最近的未访问 region。距离
    相等或像素数相等时按输入顺序稳定化，保证结果确定性。
    """

    if len(raw) <= 1:
        return list(raw)

    # Pre-sort by descending pixel_count so ties inside the NN loop fall
    # back to "bigger region wins" — natural for UI display and keeps the
    # ordering stable for snapshot-style tests. stable sort preserves
    # caller-supplied order among equal-count regions.
    # 先按像素数降序，这样 NN 距离相等时倾向大区域，顺序稳定可预期。
    sorted_raw = sorted(raw, key=lambda r: -r.pixel_count)

    centroids = np.asarray([r.centroid for r in sorted_raw], dtype=np.float64)
    n = len(sorted_raw)
    visited = np.zeros(n, dtype=bool)
    ordered_indices: list[int] = []

    # Start at the largest (index 0 after the sort above).
    current = 0
    visited[0] = True
    ordered_indices.append(0)
    for _ in range(n - 1):
        # Squared distance is monotonic with Euclidean distance — skip the
        # sqrt since we only need argmin. Mask visited entries with +inf.
        # 用平方距离比较，无需开方；已访问项置 +inf。
        diff = centroids - centroids[current]
        dist_sq = np.einsum("ij,ij->i", diff, diff)
        dist_sq = np.where(visited, np.inf, dist_sq)
        next_idx = int(np.argmin(dist_sq))
        visited[next_idx] = True
        ordered_indices.append(next_idx)
        current = next_idx

    return [sorted_raw[i] for i in ordered_indices]


@dataclass
class GradientGroupsAnalysis:
    """Analysis output that additionally exposes per-pixel region identities.
    在 :func:`analyze_gradient_groups` 的基础上额外返回每像素所属的
    (group_index, region_index) 编码，方便后续做精确像素级查询
    （例如 color-highlight 端点按区域精确裁剪）。

    Attributes:
        groups: Same list of :class:`GradientGroup` objects that
            :func:`analyze_gradient_groups` would return.
        region_id_map: ``(H, W)`` uint32 array. ``0`` means the pixel is not
            part of any gradient region; non-zero values encode
            ``group_index * REGION_ID_ENCODING_MULTIPLIER + region_index``.
            对不属于任何渐变区域的像素取值为 0；否则编码
            ``group_index * 10000 + region_index``。
    """

    groups: list[GradientGroup]
    region_id_map: np.ndarray


# ---------------------------------------------------------------------------
# Internal helpers (pure functions; no IO, no globals)
# ---------------------------------------------------------------------------


def _hex(rgb: Sequence[int]) -> str:
    r, g, b = (int(c) for c in rgb)
    return f"#{r:02X}{g:02X}{b:02X}"


def _encode_rgb(rgb_img: np.ndarray) -> np.ndarray:
    """Encode (..., 3) uint8 RGB to a single int32 code per pixel.
    将 ``(..., 3)`` 的 uint8 RGB 编码为每像素一个 int32 整型。
    """
    return (
        rgb_img[..., 0].astype(np.int32) * 65536
        + rgb_img[..., 1].astype(np.int32) * 256
        + rgb_img[..., 2].astype(np.int32)
    )


def _decode_code(code: int) -> tuple[int, int, int]:
    return ((code >> 16) & 0xFF, (code >> 8) & 0xFF, code & 0xFF)


class _UnionFind:
    """Path-compressing union-find over integer keys.
    路径压缩的并查集，仅供内部使用。
    """

    def __init__(self, items: Sequence[int]) -> None:
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
) -> list[dict[str, Any]]:
    """Return per-pair Lab ΔE statistics across 4-neighbour boundaries.

    Output rows contain ``code_a``, ``code_b``, ``count``, and
    ``median_de``. ``code_a <= code_b`` is guaranteed. Pairs never appear
    twice.
    """

    def _collect(
        a_codes: np.ndarray,
        b_codes: np.ndarray,
        a_lab: np.ndarray,
        b_lab: np.ndarray,
        a_solid: np.ndarray,
        b_solid: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
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

    h_a, h_b, h_de = _collect(
        matched_codes[:, :-1],
        matched_codes[:, 1:],
        source_lab[:, :-1],
        source_lab[:, 1:],
        solid_mask[:, :-1],
        solid_mask[:, 1:],
    )
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

    swap = all_a > all_b
    tmp = all_a[swap].copy()
    all_a[swap] = all_b[swap]
    all_b[swap] = tmp

    key = (all_a.astype(np.int64) << 32) | all_b.astype(np.int64)
    order = np.argsort(key, kind="stable")
    key_sorted = key[order]
    de_sorted = all_de[order]

    unique_key, start_idx = np.unique(key_sorted, return_index=True)
    end_idx = np.append(start_idx[1:], key_sorted.size)

    stats: list[dict[str, Any]] = []
    for k, s, e in zip(unique_key, start_idx, end_idx):
        de_slice = de_sorted[s:e]
        stats.append(
            {
                "code_a": int(k >> 32),
                "code_b": int(k & 0xFFFFFFFF),
                "count": int(de_slice.size),
                "median_de": float(np.median(de_slice)),
            }
        )
    return stats


def _split_group_into_regions(
    group_mask_2d: np.ndarray,
    matched_codes_2d: np.ndarray,
    *,
    connectivity: int,
    min_region_pixels: int,
) -> tuple[np.ndarray, list[GradientGroupRegion]]:
    """Label connected regions inside ``group_mask_2d``.

    Returns ``(labels_2d, regions)``. ``labels_2d`` uses 0 for background
    and keeps the original CC ids so downstream renders stay stable.
    ``regions`` is sorted by descending pixel count with 1-based
    ``region_index`` fields.
    """
    mask_u8 = group_mask_2d.astype(np.uint8)
    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(
        mask_u8, connectivity=connectivity
    )
    raw: list[GradientGroupRegion] = []
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
        raw.append(
            GradientGroupRegion(
                region_index=int(label_id),  # temporary; rewritten below
                pixel_count=area,
                bbox=(x, y, x + w, y + h),
                centroid=(float(cx), float(cy)),
                material_breakdown=material_breakdown,
            )
        )
    # Order regions so spatially adjacent ones are adjacent in the list
    # (NN heuristic on centroids, largest first). The downstream
    # ``region_index`` is just a UI display ranking — the CC label_id is
    # recovered separately by centroid/bbox sampling where needed, so the
    # switch from "pixel-count descending" to "NN on centroids" has no
    # effect on the region_id_map / mask-rebuild paths.
    # 空间相邻 region 在列表里相邻（最近邻启发式，最大区域优先）。
    ordered = _order_regions_by_spatial_adjacency(raw)
    # We keep the CC label_id in a side-channel so the caller can still map a
    # region back to labels_2d; region_index (1-based) is for UI display.
    regions: list[GradientGroupRegion] = []
    for idx, r in enumerate(ordered, 1):
        regions.append(
            GradientGroupRegion(
                region_index=idx,
                pixel_count=r.pixel_count,
                bbox=r.bbox,
                centroid=r.centroid,
                material_breakdown=r.material_breakdown,
            )
        )
    return labels, regions


def _merge_small_regions_into_nearest(
    labels_2d: np.ndarray,
    regions: list[GradientGroupRegion],
    matched_codes_2d: np.ndarray,
    *,
    small_threshold: int,
) -> tuple[np.ndarray, list[GradientGroupRegion]]:
    """Merge small regions into the nearest large region by centroid distance.
    将小区域按质心距离合并到同组内最近的大区域。

    Returns a new ``(labels_2d, regions)`` pair with small regions rewritten.
    If the group has no large region (every region is smaller than the
    threshold) the inputs are returned unchanged.
    """
    if small_threshold <= 0 or not regions:
        return labels_2d, regions
    big = [r for r in regions if r.pixel_count >= small_threshold]
    small = [r for r in regions if r.pixel_count < small_threshold]
    if not big or not small:
        return labels_2d, regions

    # The label_id we need is the CC label. It's lost once we rewrote regions
    # with 1-based ``region_index``, so rebuild a name→label_id map by
    # relabelling based on centroid lookup. Simpler: accept that
    # :func:`_split_group_into_regions` already keyed labels_2d by CC ids and
    # ``region_index`` is just a display ranking. Since we cannot invert the
    # mapping here, rebuild the mapping by scanning labels_2d once.
    # ``region_index`` to CC label: one per region; the order matches
    # ``regions`` because :func:`_split_group_into_regions` kept the same
    # ordering in its final pass.
    # Reconstruct CC label per region by spatial sampling (single pixel at
    # centroid row is reliable because centroids lie inside the connected
    # component with overwhelming probability).
    region_cc_labels: list[int] = []
    for r in regions:
        cy = int(round(r.centroid[1]))
        cx = int(round(r.centroid[0]))
        cy = max(0, min(labels_2d.shape[0] - 1, cy))
        cx = max(0, min(labels_2d.shape[1] - 1, cx))
        label_at = int(labels_2d[cy, cx])
        if label_at == 0:
            # Fallback: find any pixel with the dominant label in the bbox.
            x0, y0, x1, y1 = r.bbox
            sub = labels_2d[y0:y1, x0:x1]
            nonzero = sub[sub > 0]
            label_at = int(nonzero[0]) if nonzero.size > 0 else 0
        region_cc_labels.append(label_at)

    # Pair each region dataclass to its CC label.
    region_to_cc = dict(zip((id(r) for r in regions), region_cc_labels))

    big_centroids = np.asarray([r.centroid for r in big], dtype=np.float64)
    big_cc_labels = np.asarray(
        [region_to_cc[id(r)] for r in big], dtype=np.int64
    )
    new_labels = labels_2d.copy()
    for small_region in small:
        small_cc = region_to_cc[id(small_region)]
        if small_cc == 0:
            continue
        sc = np.asarray(small_region.centroid, dtype=np.float64)
        distances = np.linalg.norm(big_centroids - sc, axis=1)
        target_label = int(big_cc_labels[int(np.argmin(distances))])
        new_labels[labels_2d == small_cc] = target_label

    merged_raw: list[GradientGroupRegion] = []
    for r in big:
        cc_id = region_to_cc[id(r)]
        mask_r = new_labels == cc_id
        if not mask_r.any():
            continue
        area = int(mask_r.sum())
        ys, xs = np.nonzero(mask_r)
        bbox = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
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
        merged_raw.append(
            GradientGroupRegion(
                region_index=0,  # rewritten below
                pixel_count=area,
                bbox=bbox,
                centroid=(float(xs.mean()), float(ys.mean())),
                material_breakdown=material_breakdown,
            )
        )
    merged_raw.sort(key=lambda r: -r.pixel_count)
    # Reorder merged regions the same way as the pre-merge list so the UI
    # list surfaces spatially close regions together. 同样按最近邻重排。
    merged_ordered = _order_regions_by_spatial_adjacency(merged_raw)
    merged: list[GradientGroupRegion] = []
    for idx, r in enumerate(merged_ordered, 1):
        merged.append(
            GradientGroupRegion(
                region_index=idx,
                pixel_count=r.pixel_count,
                bbox=r.bbox,
                centroid=r.centroid,
                material_breakdown=r.material_breakdown,
            )
        )
    return new_labels, merged


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def _resolve_region_cc_label_for_regions(
    labels_2d: np.ndarray,
    regions: list[GradientGroupRegion],
) -> list[int]:
    """Return the CC label id inside ``labels_2d`` for each region.
    通过质心/bbox 采样反查每个 region 对应的连通分量 label id。

    The returned list is aligned with ``regions`` by index. An entry of 0
    indicates the region could not be mapped back to any CC label (the
    region's centroid landed on a background pixel and its bbox contains
    no foreground sample); callers should skip such regions.
    返回列表与 ``regions`` 同序；0 表示无法定位，调用方应跳过该 region。
    """
    if labels_2d.ndim != 2:
        return [0] * len(regions)
    h, w = labels_2d.shape
    resolved: list[int] = []
    for r in regions:
        cy = int(round(r.centroid[1]))
        cx = int(round(r.centroid[0]))
        cy = max(0, min(h - 1, cy))
        cx = max(0, min(w - 1, cx))
        label_at = int(labels_2d[cy, cx])
        if label_at == 0:
            x0, y0, x1, y1 = r.bbox
            x0 = max(0, min(w, x0))
            x1 = max(0, min(w, x1))
            y0 = max(0, min(h, y0))
            y1 = max(0, min(h, y1))
            if x1 > x0 and y1 > y0:
                sub = labels_2d[y0:y1, x0:x1]
                nonzero = sub[sub > 0]
                if nonzero.size > 0:
                    label_at = int(nonzero[0])
        resolved.append(label_at)
    return resolved


def _analyze_internal(
    *,
    matched_rgb: np.ndarray,
    quantized_rgb: np.ndarray,
    mask_solid: np.ndarray,
    params: GradientGroupAnalysisParams | None,
) -> tuple[list[GradientGroup], np.ndarray]:
    """Shared implementation for the public analyzer entry points.
    内部实现：既返回 groups，也返回每像素的 (group, region) 编码图。

    The returned ``region_id_map`` is always an ``(H, W)`` ``uint32`` array
    sized to ``matched_rgb`` (even if no groups are detected). A value of
    ``0`` means the pixel does not belong to any gradient region; any
    non-zero value equals
    ``group_index * REGION_ID_ENCODING_MULTIPLIER + region_index`` for the
    final, post-sort ``group_index`` and ``region_index``.
    """
    if params is None:
        params = GradientGroupAnalysisParams()

    if matched_rgb.ndim != 3 or matched_rgb.shape[2] != 3:
        raise ValueError("matched_rgb must have shape (H, W, 3)")
    if quantized_rgb.shape != matched_rgb.shape:
        raise ValueError("quantized_rgb shape must match matched_rgb shape")
    if mask_solid.shape != matched_rgb.shape[:2]:
        raise ValueError("mask_solid shape must match matched_rgb (H, W)")

    matched_u8 = np.ascontiguousarray(matched_rgb, dtype=np.uint8)
    quantized_u8 = np.ascontiguousarray(quantized_rgb, dtype=np.uint8)
    mask_bool = np.ascontiguousarray(mask_solid, dtype=bool)
    height, width = matched_u8.shape[:2]
    empty_region_id_map = np.zeros((height, width), dtype=np.uint32)

    # 1) Source Lab + matched colour codes.
    source_lab_flat = rgb_to_lab(quantized_u8.reshape(-1, 3))
    source_lab = source_lab_flat.reshape(height, width, 3)
    matched_codes = _encode_rgb(matched_u8)

    # 2) Boundary scan.
    pair_stats = _adjacent_pair_stats(matched_codes, source_lab, mask_bool)
    banding_pairs = [
        p
        for p in pair_stats
        if p["median_de"] <= params.boundary_delta_e
        and p["count"] >= params.min_boundary_pixels
    ]

    # 3) Constrained union-find on banding pairs.
    unique_codes_sorted = sorted(
        {int(c) for c in np.unique(matched_codes[mask_bool]).tolist()}
    )
    if not unique_codes_sorted:
        return [], empty_region_id_map
    code_lab_map: dict[int, np.ndarray] = {
        code: rgb_to_lab(np.asarray([_decode_code(code)], dtype=np.uint8))[0]
        for code in unique_codes_sorted
    }
    uf = _UnionFind(unique_codes_sorted)
    cluster_members: dict[int, list[int]] = {
        code: [code] for code in unique_codes_sorted
    }
    for pair in sorted(banding_pairs, key=lambda p: (p["median_de"], -p["count"])):
        a, b = pair["code_a"], pair["code_b"]
        ra, rb = uf.find(a), uf.find(b)
        if ra == rb:
            continue
        combined = cluster_members[ra] + cluster_members[rb]
        labs = np.asarray([code_lab_map[c] for c in combined], dtype=np.float64)
        if labs.shape[0] >= 2:
            diff = labs[:, None, :] - labs[None, :, :]
            max_de = float(np.sqrt(np.einsum("ijk,ijk->ij", diff, diff)).max())
            if max_de > params.max_matched_de:
                continue
        uf.union(a, b)
        root = uf.find(a)
        cluster_members[root] = combined
        other = rb if root == ra else ra
        cluster_members.pop(other, None)

    # 4) Per-code pixel counts (over solid pixels) for group filtering.
    solid_codes_flat = matched_codes[mask_bool]
    code_unique, code_counts = np.unique(solid_codes_flat, return_counts=True)
    code_to_count: dict[int, int] = {
        int(c): int(n) for c, n in zip(code_unique, code_counts)
    }

    # 5) Build gradient groups (≥ 2 material colours each).
    banding_pair_set: dict[tuple[int, int], dict[str, Any]] = {
        (p["code_a"], p["code_b"]): p for p in banding_pairs
    }
    buckets = uf.groups()
    # Each proto entry bundles the GradientGroup (with placeholder group_index=0),
    # the per-group CC label image, and its regions. We defer the final
    # group-index assignment and the region_id_map construction until after
    # sorting so that each pixel carries the *final* (group_index, region_index).
    # 中间结构同时保留 labels_2d 与 regions，排序完成后再统一编码 region_id_map。
    proto_entries: list[tuple[GradientGroup, np.ndarray, list[GradientGroupRegion]]] = []
    for members in buckets.values():
        if len(members) < 2:
            continue
        ranked_materials = sorted(
            (
                {
                    "code": m,
                    "hex": _hex(_decode_code(m)),
                    "rgb": list(_decode_code(m)),
                    "pixel_count": code_to_count.get(m, 0),
                }
                for m in members
            ),
            key=lambda mc: -mc["pixel_count"],
        )
        kept = [
            mc for mc in ranked_materials if mc["pixel_count"] >= params.min_material_pixels
        ]
        if len(kept) < 2:
            continue
        total_pixels = int(sum(mc["pixel_count"] for mc in kept))
        kept_codes = {mc["code"] for mc in kept}
        internal_pair_count = sum(
            1
            for (a, b) in banding_pair_set
            if a in kept_codes and b in kept_codes
        )
        member_codes_arr = np.asarray([mc["code"] for mc in kept], dtype=np.int64)
        group_mask_flat = np.isin(matched_codes.reshape(-1), member_codes_arr) & mask_bool.reshape(-1)
        group_mask_2d = group_mask_flat.reshape(height, width)

        # 6) Region split + optional small-region merge.
        region_labels_2d, regions = _split_group_into_regions(
            group_mask_2d,
            matched_codes,
            connectivity=params.region_connectivity,
            min_region_pixels=params.min_region_pixels,
        )
        if params.merge_small_regions and regions:
            region_labels_2d, regions = _merge_small_regions_into_nearest(
                region_labels_2d,
                regions,
                matched_codes,
                small_threshold=params.small_region_threshold,
            )

        # 7) Representative colour = material with most pixels.
        rep_mc = kept[0]
        rep_rgb = tuple(int(c) for c in rep_mc["rgb"])  # noqa: RUF005

        # Strip internal "code" field before returning to callers.
        material_colours_out: list[dict[str, Any]] = [
            {"hex": mc["hex"], "rgb": list(mc["rgb"]), "pixel_count": int(mc["pixel_count"])}
            for mc in kept
        ]

        proto_entries.append(
            (
                GradientGroup(
                    group_index=0,  # rewritten after sort
                    total_pixel_count=total_pixels,
                    material_colour_count=len(kept),
                    material_colours=material_colours_out,
                    representative_hex=rep_mc["hex"],
                    representative_rgb=rep_rgb,  # type: ignore[arg-type]
                    boundary_pair_count=int(internal_pair_count),
                    regions=regions,
                ),
                region_labels_2d,
                regions,
            )
        )

    proto_entries.sort(key=lambda entry: -entry[0].total_pixel_count)
    final: list[GradientGroup] = []
    region_id_map = empty_region_id_map  # reuse pre-allocated zero canvas
    for idx, (g, labels_2d, regions) in enumerate(proto_entries, 1):
        final.append(
            GradientGroup(
                group_index=idx,
                total_pixel_count=g.total_pixel_count,
                material_colour_count=g.material_colour_count,
                material_colours=g.material_colours,
                representative_hex=g.representative_hex,
                representative_rgb=g.representative_rgb,
                boundary_pair_count=g.boundary_pair_count,
                regions=g.regions,
            )
        )
        # Map each final region back to its CC label and stamp the encoded
        # (group_index, region_index) onto the corresponding pixels. Regions
        # whose CC label cannot be resolved are silently skipped — callers
        # fall back to broader highlight scopes (group-level or full preview)
        # without raising.
        # 每个 region 反查其 CC label id，并将 (group_index, region_index)
        # 编码写入对应像素；无法定位的 region 忽略不阻塞主流程。
        cc_labels = _resolve_region_cc_label_for_regions(labels_2d, regions)
        for region, cc_label in zip(regions, cc_labels):
            if cc_label <= 0:
                continue
            encoded = idx * REGION_ID_ENCODING_MULTIPLIER + region.region_index
            region_id_map[labels_2d == cc_label] = np.uint32(encoded)
    return final, region_id_map


def analyze_gradient_groups(
    *,
    matched_rgb: np.ndarray,
    quantized_rgb: np.ndarray,
    mask_solid: np.ndarray,
    params: GradientGroupAnalysisParams | None = None,
) -> list[GradientGroup]:
    """Identify smooth-gradient material-colour clusters and their regions.
    识别由量化造成的渐变型耗材色聚类，并拆分成空间区域。

    Args:
        matched_rgb: ``(H, W, 3)`` uint8 RGB image of the quantised material
            colours (the preview the user actually sees).
        quantized_rgb: ``(H, W, 3)`` uint8 RGB image of the quantised
            *source* colours (the input after K-means quantisation, before
            material matching). Used to detect whether a boundary was a
            real edge in the source or a smooth gradient.
        mask_solid: ``(H, W)`` bool mask of pixels that belong to the
            printable area (i.e. not transparent/background).
        params: tuning parameters; defaults are safe production values.

    Returns:
        List of :class:`GradientGroup`, sorted by descending pixel count.
        Each group guarantees ``len(regions) >= 1`` when returned.

    Raises:
        ValueError: if the inputs have mismatched shapes or wrong dtypes.
    """
    groups, _region_id_map = _analyze_internal(
        matched_rgb=matched_rgb,
        quantized_rgb=quantized_rgb,
        mask_solid=mask_solid,
        params=params,
    )
    return groups


def analyze_gradient_groups_with_region_id_map(
    *,
    matched_rgb: np.ndarray,
    quantized_rgb: np.ndarray,
    mask_solid: np.ndarray,
    params: GradientGroupAnalysisParams | None = None,
) -> GradientGroupsAnalysis:
    """Variant of :func:`analyze_gradient_groups` that also returns per-pixel IDs.
    在 :func:`analyze_gradient_groups` 的基础上额外返回 ``region_id_map``。

    Use this variant when callers need to later pinpoint the pixel mask of a
    specific region (e.g. the color-highlight endpoint clipping the preview
    overlay to exactly the pixels of a selected sub-region). For pure metadata
    consumers — panels, JSON responses, audits — :func:`analyze_gradient_groups`
    remains the cheaper entry point.
    """
    groups, region_id_map = _analyze_internal(
        matched_rgb=matched_rgb,
        quantized_rgb=quantized_rgb,
        mask_solid=mask_solid,
        params=params,
    )
    return GradientGroupsAnalysis(groups=groups, region_id_map=region_id_map)


def gradient_groups_to_json(groups: list[GradientGroup]) -> list[dict[str, Any]]:
    """Serialise :class:`GradientGroup` instances into plain JSON dicts.
    将 ``GradientGroup`` 序列化为 JSON 可传输的 dict 列表。
    """
    out: list[dict[str, Any]] = []
    for g in groups:
        out.append(
            {
                "group_index": g.group_index,
                "total_pixel_count": g.total_pixel_count,
                "material_colour_count": g.material_colour_count,
                "material_colours": list(g.material_colours),
                "representative_hex": g.representative_hex,
                "representative_rgb": list(g.representative_rgb),
                "boundary_pair_count": g.boundary_pair_count,
                "regions": [
                    {
                        "region_index": r.region_index,
                        "pixel_count": r.pixel_count,
                        "bbox": list(r.bbox),
                        "centroid": list(r.centroid),
                        "material_breakdown": list(r.material_breakdown),
                    }
                    for r in g.regions
                ],
            }
        )
    return out


def build_banding_remap_plan(
    groups: list[GradientGroup],
) -> dict[str, str]:
    """Return a dict mapping non-representative hex → representative hex.
    生成"非代表色 → 代表色"的映射，用于自动去海带纹。

    Representative hex is normalised to lowercase without the leading "#"
    so the frontend can feed it directly into the existing
    ``applyColorRemap`` / ``colorRemapMap`` path without extra parsing.
    """
    plan: dict[str, str] = {}
    for g in groups:
        target = g.representative_hex.lstrip("#").lower()
        for mc in g.material_colours:
            src = str(mc.get("hex", "")).lstrip("#").lower()
            if not src or src == target:
                continue
            plan[src] = target
    return plan
