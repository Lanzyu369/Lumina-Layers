from __future__ import annotations

import numpy as np
import pytest

from core.pipeline import material_dynamic_layers


def _entry(
    target: list[int],
    delta_e00: float,
    *,
    duplicate_cap: bool = False,
) -> dict:
    options = [
        {"max_effective_layer_count": 5, "delta_e00": delta_e00},
        {"max_effective_layer_count": 6, "delta_e00": delta_e00 / 2.0},
        {"max_effective_layer_count": 7, "delta_e00": delta_e00 / 4.0},
    ]
    if duplicate_cap:
        options.append(
            {
                "max_effective_layer_count": 6,
                "delta_e00": delta_e00 / 3.0,
            }
        )
    return {"target_srgb": target, "layer_cap_options": options}


def _naive_reference(
    color_entries: list[dict],
    target_rgb_map: np.ndarray,
    mask_solid: np.ndarray | None,
) -> list[dict]:
    rgb = np.asarray(target_rgb_map, dtype=np.uint8)
    solid = (
        np.asarray(mask_solid, dtype=bool)
        if isinstance(mask_solid, np.ndarray)
        else np.ones(rgb.shape[:2], dtype=bool)
    )
    weighted_entries: list[tuple[int, dict[int, float]]] = []
    all_layer_caps: set[int] = set()
    for entry in color_entries:
        if not isinstance(entry, dict):
            continue
        target = entry.get("target_srgb")
        options = entry.get("layer_cap_options")
        if (
            not isinstance(target, (list, tuple))
            or len(target) != 3
            or not isinstance(options, list)
            or not options
        ):
            continue
        option_map: dict[int, float] = {}
        for option in options:
            if not isinstance(option, dict):
                continue
            try:
                layer_cap = int(option["max_effective_layer_count"])
                delta_e00 = float(option["delta_e00"])
            except (KeyError, TypeError, ValueError):
                continue
            option_map[layer_cap] = delta_e00
        if not option_map:
            continue
        target_row = np.asarray(target, dtype=np.uint8)
        pixel_count = int(np.sum(np.all(rgb == target_row, axis=-1) & solid))
        if pixel_count <= 0:
            continue
        weighted_entries.append((pixel_count, option_map))
        all_layer_caps.update(option_map)

    if not weighted_entries or not all_layer_caps:
        return []

    curve: list[dict] = []
    previous_mean: float | None = None
    for layer_cap in sorted(all_layer_caps):
        applicable = [
            (pixel_count, options[layer_cap])
            for pixel_count, options in weighted_entries
            if layer_cap in options
        ]
        total_pixels = sum(pixel_count for pixel_count, _ in applicable)
        weighted_mean = sum(
            pixel_count * delta_e00 for pixel_count, delta_e00 in applicable
        ) / total_pixels
        marginal = (
            0.0
            if previous_mean is None
            else max(0.0, previous_mean - weighted_mean)
        )
        curve.append(
            {
                "max_effective_layer_count": layer_cap,
                "weighted_mean_delta_e00": round(float(weighted_mean), 12),
                "marginal_delta_e00_reduction": round(float(marginal), 12),
            }
        )
        previous_mean = weighted_mean
    return curve


def test_recompute_matches_naive_for_chunked_non_contiguous_map() -> None:
    rng = np.random.default_rng(20260714)
    height, width = 129, 257
    palette = np.asarray(
        [
            [10, 20, 30],
            [40, 50, 60],
            [70, 80, 90],
            [100, 110, 120],
            [130, 140, 150],
        ],
        dtype=np.uint8,
    )
    owners = rng.integers(0, len(palette), size=(height, width))
    contiguous_rgb = palette[owners]
    padded_rgb = np.zeros((height, width + 1, 3), dtype=np.uint8)
    padded_rgb[:, :width] = contiguous_rgb
    rgb = padded_rgb[:, :width]
    assert not rgb.flags.c_contiguous

    padded_solid = np.zeros((height, width + 1), dtype=bool)
    padded_solid[:, :width] = rng.random((height, width)) > 0.13
    solid = padded_solid[:, :width]
    rgb[0, 0] = [1, 2, 3]

    entries = [
        _entry(palette[index].tolist(), float(index + 1), duplicate_cap=index == 2)
        for index in range(len(palette))
    ]
    entries.extend(
        [
            _entry(palette[0].tolist(), 9.0),
            _entry([250, 251, 252], 11.0),
            {"target_srgb": [10, 20], "layer_cap_options": []},
            {"target_srgb": [10, 20, 30], "layer_cap_options": [{}]},
        ]
    )

    expected = _naive_reference(entries, rgb, solid)
    actual = material_dynamic_layers.recompute_dynamic_material_benefit_curve(
        entries,
        rgb,
        solid,
    )

    assert actual == expected


def test_recompute_matches_naive_without_explicit_mask() -> None:
    rgb = np.asarray(
        [
            [[10, 20, 30], [40, 50, 60], [40, 50, 60]],
            [[10, 20, 30], [10, 20, 30], [1, 2, 3]],
        ],
        dtype=np.uint8,
    )
    entries = [
        _entry([10, 20, 30], 1.0),
        _entry([40, 50, 60], 3.0),
    ]

    assert material_dynamic_layers.recompute_dynamic_material_benefit_curve(
        entries,
        rgb,
        None,
    ) == _naive_reference(entries, rgb, None)


def test_recompute_matches_naive_for_randomized_valid_metadata() -> None:
    for seed in range(25):
        rng = np.random.default_rng(seed)
        target_count = 1 + seed % 19
        codes = (
            np.arange(target_count, dtype=np.uint32) * np.uint32(7919)
            + np.uint32(0x123456)
        ) & np.uint32(0xFFFFFF)
        palette = np.stack(
            (
                (codes >> np.uint32(16)) & np.uint32(0xFF),
                (codes >> np.uint32(8)) & np.uint32(0xFF),
                codes & np.uint32(0xFF),
            ),
            axis=1,
        ).astype(np.uint8)
        height = 1 + (seed * 17) % 73
        width = 1 + (seed * 61) % 127
        owners = rng.integers(0, target_count, size=(height, width))
        rgb = palette[owners]
        if seed % 4 == 0:
            padded = np.zeros((height, width + 1, 3), dtype=np.uint8)
            padded[:, :width] = rgb
            rgb = padded[:, :width]
        rgb[0, 0] = [1, 2, 3]
        solid = rng.random((height, width)) > 0.21
        mask = None if seed % 3 == 0 else solid

        entries: list[dict] = []
        order = rng.permutation(target_count)
        for index in order:
            caps = rng.choice(
                np.arange(5, 11),
                size=1 + int(rng.integers(0, 6)),
                replace=False,
            )
            options = [
                {
                    "max_effective_layer_count": int(cap),
                    "delta_e00": float(rng.random() * 12.0),
                }
                for cap in caps
            ]
            if index % 5 == 0:
                options.append(
                    {
                        "max_effective_layer_count": int(caps[0]),
                        "delta_e00": float(rng.random() * 12.0),
                    }
                )
            entries.append(
                {
                    "target_srgb": palette[index].tolist(),
                    "layer_cap_options": options,
                }
            )
        if seed % 2 == 0:
            entries.append(entries[0].copy())

        expected = _naive_reference(entries, rgb, mask)
        actual = material_dynamic_layers.recompute_dynamic_material_benefit_curve(
            entries,
            rgb,
            mask,
        )

        assert actual == expected, f"seed={seed}"


def test_recompute_preserves_reference_rounding_for_large_catalog() -> None:
    rng = np.random.default_rng(20260714)
    codes = (
        np.arange(256, dtype=np.uint32) * np.uint32(7919)
        + np.uint32(0x123456)
    ) & np.uint32(0xFFFFFF)
    palette = np.stack(
        (
            (codes >> np.uint32(16)) & np.uint32(0xFF),
            (codes >> np.uint32(8)) & np.uint32(0xFF),
            codes & np.uint32(0xFF),
        ),
        axis=1,
    ).astype(np.uint8)
    owners = rng.integers(0, len(palette), size=(147, 256))
    rgb = palette[owners]
    solid = rng.random(owners.shape) > 0.04
    delta_e00 = rng.uniform(0.05, 12.0, size=(len(palette), 6))
    entries = [
        {
            "target_srgb": target.tolist(),
            "layer_cap_options": [
                {
                    "max_effective_layer_count": layer_cap,
                    "delta_e00": float(delta_e00[index, layer_cap - 5]),
                }
                for layer_cap in range(5, 11)
            ],
        }
        for index, target in enumerate(palette)
    ]

    expected = _naive_reference(entries, rgb, solid)
    actual = material_dynamic_layers.recompute_dynamic_material_benefit_curve(
        entries,
        rgb,
        solid,
    )

    assert actual == expected


def test_recompute_does_not_scan_full_map_once_per_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rgb = np.tile(
        np.asarray([[[10, 20, 30], [40, 50, 60]]], dtype=np.uint8),
        (64, 64, 1),
    )
    solid = np.ones(rgb.shape[:2], dtype=bool)
    entries = [
        _entry([10, 20, 30], 1.0),
        _entry([40, 50, 60], 3.0),
    ]
    expected = _naive_reference(entries, rgb, solid)
    original_all = np.all

    def guarded_all(array, *args, **kwargs):
        axis = kwargs.get("axis", args[0] if args else None)
        if axis == -1 and np.asarray(array).ndim == 3:
            raise AssertionError("detected one full RGB-map scan per target")
        return original_all(array, *args, **kwargs)

    monkeypatch.setattr(material_dynamic_layers.np, "all", guarded_all)

    actual = material_dynamic_layers.recompute_dynamic_material_benefit_curve(
        entries,
        rgb,
        solid,
    )

    assert actual == expected


def test_recompute_keeps_each_rgb_working_chunk_within_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chunk_budget = material_dynamic_layers._RGB_COUNT_CHUNK_PIXELS
    rgb = np.tile(
        np.asarray([[[10, 20, 30]]], dtype=np.uint8),
        (2, chunk_budget + 17, 1),
    )
    solid = np.ones(rgb.shape[:2], dtype=bool)
    entries = [_entry([10, 20, 30], 1.0)]
    observed_chunk_sizes: list[int] = []
    original_pack = material_dynamic_layers._pack_rgb24_rows

    def recording_pack(rgb_rows: np.ndarray) -> np.ndarray:
        observed_chunk_sizes.append(len(rgb_rows))
        return original_pack(rgb_rows)

    monkeypatch.setattr(
        material_dynamic_layers,
        "_pack_rgb24_rows",
        recording_pack,
    )

    actual = material_dynamic_layers.recompute_dynamic_material_benefit_curve(
        entries,
        rgb,
        solid,
    )

    assert actual == _naive_reference(entries, rgb, solid)
    assert observed_chunk_sizes
    assert max(observed_chunk_sizes) <= chunk_budget
