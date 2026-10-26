"""Unit tests for :mod:`core.gradient_group_analyzer`.

Validates:
- Empty / solid-colour inputs produce no groups.
- A synthetic banded gradient collapses into one group with all bands.
- The Lab-distance cap (``max_matched_de``) prevents cross-hue chaining.
- Spatial region split surfaces disjoint regions.
- ``merge_small_regions`` fuses tiny components into the nearest big one.
- ``build_banding_remap_plan`` emits lowercase hex maps suitable for the
  existing ``colorRemapMap`` channel.
"""

from __future__ import annotations

import numpy as np
import pytest

from core.gradient_group_analyzer import (
    GradientGroupAnalysisParams,
    REGION_ID_ENCODING_MULTIPLIER,
    analyze_gradient_groups,
    analyze_gradient_groups_with_region_id_map,
    build_banding_remap_plan,
    gradient_groups_to_json,
)


def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    s = h.lstrip("#")
    return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)


def _make_banded_gradient(
    *,
    height: int,
    width: int,
    bands: list[tuple[int, int, int]],
    stripe_height: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Build a synthetic material-archive scene.

    The *matched* image has sharp horizontal stripes (banding artefact).
    The *quantised source* image is a smooth vertical luminance gradient —
    adjacent pixels in the source are perceptually very close, so the
    analyser should see the band edges as "false splits".
    """
    matched = np.zeros((height, width, 3), dtype=np.uint8)
    for i, rgb in enumerate(bands):
        y0 = i * stripe_height
        y1 = min(height, (i + 1) * stripe_height)
        matched[y0:y1] = rgb
    base = np.linspace(80, 220, height, dtype=np.float32)
    quant = np.zeros_like(matched)
    quant[..., 0] = base[:, None]
    quant[..., 1] = base[:, None]
    quant[..., 2] = base[:, None]
    mask = np.ones((height, width), dtype=bool)
    return matched, quant, mask


def test_empty_solid_returns_no_groups() -> None:
    matched = np.full((16, 16, 3), 128, dtype=np.uint8)
    quant = matched.copy()
    mask = np.ones((16, 16), dtype=bool)

    groups = analyze_gradient_groups(
        matched_rgb=matched, quantized_rgb=quant, mask_solid=mask
    )

    assert groups == []


def test_banded_gradient_collapses_into_single_group() -> None:
    bands = [
        _hex_to_rgb("#D2AEB4"),
        _hex_to_rgb("#D0A3AC"),
        _hex_to_rgb("#C78F94"),
        _hex_to_rgb("#BE868A"),
    ]
    matched, quant, mask = _make_banded_gradient(
        height=40, width=40, bands=bands, stripe_height=10
    )

    params = GradientGroupAnalysisParams(
        boundary_delta_e=8.0,
        min_boundary_pixels=5,
        min_material_pixels=10,
        max_matched_de=30.0,
        min_region_pixels=10,
    )

    groups = analyze_gradient_groups(
        matched_rgb=matched,
        quantized_rgb=quant,
        mask_solid=mask,
        params=params,
    )

    assert len(groups) == 1
    g = groups[0]
    assert g.material_colour_count == 4
    assert g.total_pixel_count == 40 * 40
    # Representative colour is the material with the highest pixel count.
    hex_counts = {
        mc["hex"].upper(): mc["pixel_count"] for mc in g.material_colours
    }
    rep = max(hex_counts.items(), key=lambda kv: kv[1])[0]
    assert g.representative_hex.upper() == rep
    # All bands are contiguous → single connected region.
    assert len(g.regions) == 1
    assert g.regions[0].pixel_count == 40 * 40


def test_disjoint_regions_split() -> None:
    bands = [
        _hex_to_rgb("#D2AEB4"),
        _hex_to_rgb("#D0A3AC"),
    ]
    matched, quant, mask = _make_banded_gradient(
        height=20, width=40, bands=bands, stripe_height=10
    )
    # Cut the picture in two with a transparent column in the middle.
    mask[:, 18:22] = False

    groups = analyze_gradient_groups(
        matched_rgb=matched,
        quantized_rgb=quant,
        mask_solid=mask,
        params=GradientGroupAnalysisParams(
            boundary_delta_e=8.0,
            min_boundary_pixels=3,
            min_material_pixels=5,
            max_matched_de=25.0,
            min_region_pixels=10,
        ),
    )

    assert len(groups) == 1
    g = groups[0]
    assert len(g.regions) == 2
    assert sum(r.pixel_count for r in g.regions) == int(mask.sum())
    # Region indices are 1-based and ordered by descending pixel count.
    assert [r.region_index for r in g.regions] == [1, 2]
    assert g.regions[0].pixel_count >= g.regions[1].pixel_count


def test_max_matched_de_blocks_cross_hue_chaining() -> None:
    # Three bands whose neighbours are close, but A↔C are far apart.
    bands = [
        _hex_to_rgb("#D0A3AC"),  # warm pink
        _hex_to_rgb("#B0A3C8"),  # lavender (bridge)
        _hex_to_rgb("#8DA9D2"),  # cool blue
    ]
    matched, quant, mask = _make_banded_gradient(
        height=30, width=30, bands=bands, stripe_height=10
    )

    tight = analyze_gradient_groups(
        matched_rgb=matched,
        quantized_rgb=quant,
        mask_solid=mask,
        params=GradientGroupAnalysisParams(
            boundary_delta_e=12.0,
            min_boundary_pixels=5,
            min_material_pixels=5,
            max_matched_de=15.0,
            min_region_pixels=5,
        ),
    )
    loose = analyze_gradient_groups(
        matched_rgb=matched,
        quantized_rgb=quant,
        mask_solid=mask,
        params=GradientGroupAnalysisParams(
            boundary_delta_e=12.0,
            min_boundary_pixels=5,
            min_material_pixels=5,
            max_matched_de=60.0,
            min_region_pixels=5,
        ),
    )

    # Tight cap prevents the A↔B↔C chain from fusing everything into one
    # group. Loose cap allows the full three-band chain to be merged.
    assert sum(g.material_colour_count for g in tight) <= 2
    assert any(g.material_colour_count == 3 for g in loose)


def test_merge_small_regions_optional() -> None:
    bands = [
        _hex_to_rgb("#D2AEB4"),
        _hex_to_rgb("#D0A3AC"),
    ]
    matched, quant, mask = _make_banded_gradient(
        height=30, width=60, bands=bands, stripe_height=15
    )
    # Big left block + several small disconnected islands on the right.
    mask[:, 30:35] = False
    # Punch a few tiny holes to make multiple islands.
    mask[10:13, 40:43] = True  # island 1 (3x3=9)
    mask[5:7, 50:52] = True   # island 2 (2x2=4)
    # Disable most of the right half so only the islands remain.
    mask[:, 35:] = False
    mask[10:13, 40:43] = True
    mask[5:7, 50:52] = True

    params_no_merge = GradientGroupAnalysisParams(
        boundary_delta_e=12.0,
        min_boundary_pixels=3,
        min_material_pixels=5,
        max_matched_de=25.0,
        min_region_pixels=1,
    )
    params_merge = GradientGroupAnalysisParams(
        boundary_delta_e=12.0,
        min_boundary_pixels=3,
        min_material_pixels=5,
        max_matched_de=25.0,
        min_region_pixels=1,
        merge_small_regions=True,
        small_region_threshold=50,
    )

    without = analyze_gradient_groups(
        matched_rgb=matched, quantized_rgb=quant, mask_solid=mask, params=params_no_merge
    )
    merged = analyze_gradient_groups(
        matched_rgb=matched, quantized_rgb=quant, mask_solid=mask, params=params_merge
    )

    assert len(without) == 1
    # Without merging we should see several regions; with merging small
    # islands should fuse into the single big block.
    assert len(without[0].regions) >= 2
    assert len(merged[0].regions) == 1


def test_build_banding_remap_plan_is_lowercase_and_skips_representative() -> None:
    bands = [
        _hex_to_rgb("#D2AEB4"),
        _hex_to_rgb("#D0A3AC"),
        _hex_to_rgb("#C78F94"),
    ]
    matched, quant, mask = _make_banded_gradient(
        height=30, width=30, bands=bands, stripe_height=10
    )
    groups = analyze_gradient_groups(
        matched_rgb=matched,
        quantized_rgb=quant,
        mask_solid=mask,
        params=GradientGroupAnalysisParams(
            boundary_delta_e=8.0,
            min_boundary_pixels=3,
            min_material_pixels=5,
            max_matched_de=30.0,
            min_region_pixels=5,
        ),
    )
    assert len(groups) == 1
    rep = groups[0].representative_hex.lstrip("#").lower()

    plan = build_banding_remap_plan(groups)
    assert rep not in plan  # representative never remaps to itself
    for src, dst in plan.items():
        assert src == src.lower()
        assert dst == rep
        assert src != rep


def test_json_serialisation_round_trip() -> None:
    bands = [
        _hex_to_rgb("#D2AEB4"),
        _hex_to_rgb("#D0A3AC"),
    ]
    matched, quant, mask = _make_banded_gradient(
        height=20, width=20, bands=bands, stripe_height=10
    )
    groups = analyze_gradient_groups(
        matched_rgb=matched,
        quantized_rgb=quant,
        mask_solid=mask,
        params=GradientGroupAnalysisParams(
            boundary_delta_e=8.0,
            min_boundary_pixels=3,
            min_material_pixels=5,
            max_matched_de=25.0,
            min_region_pixels=5,
        ),
    )
    payload = gradient_groups_to_json(groups)
    assert isinstance(payload, list)
    assert all(isinstance(g, dict) for g in payload)
    assert payload[0]["material_colour_count"] == 2
    assert "regions" in payload[0]
    assert payload[0]["representative_hex"].startswith("#")
    # JSON lists only — no numpy, no dataclass types.
    import json

    json.dumps(payload)  # should not raise


def test_region_id_map_is_empty_for_solid_input() -> None:
    """Solid frames yield no groups and an all-zero region_id_map.
    纯色图应无任何渐变分组，region_id_map 全零。
    """
    matched = np.full((16, 16, 3), 128, dtype=np.uint8)
    quant = matched.copy()
    mask = np.ones((16, 16), dtype=bool)

    analysis = analyze_gradient_groups_with_region_id_map(
        matched_rgb=matched, quantized_rgb=quant, mask_solid=mask
    )

    assert analysis.groups == []
    assert analysis.region_id_map.shape == (16, 16)
    assert analysis.region_id_map.dtype == np.uint32
    assert int(analysis.region_id_map.sum()) == 0


def test_region_id_map_encodes_disjoint_regions() -> None:
    """Each spatial region gets its own encoded (group, region) value.
    每个空间区域应获得独立的 (group, region) 编码；互不重叠。
    """
    bands = [
        _hex_to_rgb("#D2AEB4"),
        _hex_to_rgb("#D0A3AC"),
    ]
    matched, quant, mask = _make_banded_gradient(
        height=20, width=40, bands=bands, stripe_height=10
    )
    # Split the canvas horizontally so two disjoint regions share materials.
    mask[:, 18:22] = False

    analysis = analyze_gradient_groups_with_region_id_map(
        matched_rgb=matched,
        quantized_rgb=quant,
        mask_solid=mask,
        params=GradientGroupAnalysisParams(
            boundary_delta_e=8.0,
            min_boundary_pixels=3,
            min_material_pixels=5,
            max_matched_de=25.0,
            min_region_pixels=10,
        ),
    )

    assert len(analysis.groups) == 1
    g = analysis.groups[0]
    assert len(g.regions) == 2

    region_id_map = analysis.region_id_map
    # Expected encodings for each region.
    expected_ids = [
        g.group_index * REGION_ID_ENCODING_MULTIPLIER + r.region_index
        for r in g.regions
    ]

    # All non-zero values must be one of the expected encodings.
    non_zero = region_id_map[region_id_map != 0]
    unique_ids = set(int(v) for v in np.unique(non_zero))
    assert unique_ids == set(expected_ids)

    # Per-region pixel counts in the map must match the region metadata.
    for region, encoded in zip(g.regions, expected_ids):
        stamped_pixels = int((region_id_map == np.uint32(encoded)).sum())
        assert stamped_pixels == region.pixel_count

    # Masked-out pixels must stay zero so the map never claims background.
    assert int(region_id_map[~mask].sum()) == 0


def test_analyze_gradient_groups_is_equivalent_to_with_map_groups() -> None:
    """The legacy entry point must stay byte-compatible with the new one.
    旧入口返回的 groups 必须与新入口的 ``analysis.groups`` 完全一致，
    保证重构无任何行为回归。
    """
    bands = [
        _hex_to_rgb("#D2AEB4"),
        _hex_to_rgb("#D0A3AC"),
        _hex_to_rgb("#C78F94"),
    ]
    matched, quant, mask = _make_banded_gradient(
        height=30, width=30, bands=bands, stripe_height=10
    )
    params = GradientGroupAnalysisParams(
        boundary_delta_e=8.0,
        min_boundary_pixels=3,
        min_material_pixels=5,
        max_matched_de=30.0,
        min_region_pixels=5,
    )

    legacy = analyze_gradient_groups(
        matched_rgb=matched, quantized_rgb=quant, mask_solid=mask, params=params
    )
    analysis = analyze_gradient_groups_with_region_id_map(
        matched_rgb=matched, quantized_rgb=quant, mask_solid=mask, params=params
    )

    assert gradient_groups_to_json(legacy) == gradient_groups_to_json(
        analysis.groups
    )


def test_invalid_input_shapes_raise() -> None:
    m = np.zeros((4, 4, 3), dtype=np.uint8)
    q = np.zeros((5, 5, 3), dtype=np.uint8)
    s = np.ones((4, 4), dtype=bool)

    with pytest.raises(ValueError, match="quantized_rgb shape"):
        analyze_gradient_groups(matched_rgb=m, quantized_rgb=q, mask_solid=s)

    with pytest.raises(ValueError, match="mask_solid shape"):
        analyze_gradient_groups(
            matched_rgb=m,
            quantized_rgb=m.copy(),
            mask_solid=np.ones((3, 3), dtype=bool),
        )

    with pytest.raises(ValueError, match="matched_rgb"):
        analyze_gradient_groups(
            matched_rgb=np.zeros((4, 4), dtype=np.uint8),
            quantized_rgb=np.zeros((4, 4), dtype=np.uint8),
            mask_solid=s,
        )


def test_regions_are_ordered_by_spatial_adjacency() -> None:
    """Four CC regions laid out L→R in a row should come out as a NN
    traversal (largest first, then nearest unvisited by centroid), never
    in an order that skips over a spatial neighbour.

    The legacy "sort by descending pixel_count" ordering could interleave
    regions of nearly equal size regardless of where they sit on the
    canvas — breaking the user mental model that "adjacent squares in the
    panel list ≈ adjacent bands on the image". This test pins the NN
    behaviour so the panel's checkbox list stays spatially coherent.

    布局：等高等宽的 4 块同组渐变色区，从左到右依次摆放且像素数递减。
    预期顺序 = 从最大（第 1 块）开始依次向右邻居推进。
    """

    # Shared two-colour band so all four regions are one gradient group.
    band_a = _hex_to_rgb("#a03030")
    band_b = _hex_to_rgb("#a05050")

    # Row height 40 makes each region tall enough to beat min_region_pixels.
    # Widths decrease left→right so NN order == input order (1,2,3,4).
    # Left→right 宽度递减，NN 顺序应等于输入顺序。
    region_widths = [200, 160, 120, 80]
    gap = 20
    height = 40
    width = sum(region_widths) + gap * (len(region_widths) - 1) + 20
    matched = np.full((height, width, 3), 255, dtype=np.uint8)
    quantized = matched.copy()
    solid = np.zeros((height, width), dtype=bool)

    x = 10
    for w in region_widths:
        # Alternate band_a / band_b rows inside each region to form the
        # gradient banding the analyzer requires; the exact band pattern
        # doesn't matter for ordering, just that the region mask is one
        # connected component.
        # 每个区域内部用两色条纹制造 banding，保证分析器识别为渐变组。
        matched[: height // 2, x : x + w] = band_a
        matched[height // 2 :, x : x + w] = band_b
        quantized[: height // 2, x : x + w] = band_a
        quantized[height // 2 :, x : x + w] = band_b
        solid[:, x : x + w] = True
        x += w + gap

    params = GradientGroupAnalysisParams(
        boundary_delta_e=50.0,
        min_boundary_pixels=1,
        min_material_pixels=10,
        min_region_pixels=100,
        region_connectivity=4,
        merge_small_regions=False,
    )
    groups = analyze_gradient_groups(
        matched_rgb=matched,
        quantized_rgb=quantized,
        mask_solid=solid,
        params=params,
    )

    assert len(groups) == 1, "The 4 regions should collapse into one gradient group"
    regions = groups[0].regions
    assert len(regions) == len(region_widths)
    # Region 1 must be the largest (leftmost here since widths decrease).
    # 第 1 位必须是最大区域。
    assert regions[0].pixel_count == max(r.pixel_count for r in regions)
    # The centroid X should increase monotonically — NN traversal from the
    # largest (leftmost) must walk right neighbour by neighbour, never
    # skipping one in the middle. 质心 X 必须单调递增，证明 NN 顺序生效。
    centroid_xs = [r.centroid[0] for r in regions]
    assert centroid_xs == sorted(centroid_xs), (
        f"regions should be ordered L→R by centroid X, got {centroid_xs}"
    )
