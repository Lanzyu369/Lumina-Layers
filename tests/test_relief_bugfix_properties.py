"""
Lumina Studio — 浮雕模式 Bug 修复 Property-Based 测试

使用 Hypothesis 验证 _normalize_color_height_map 的正确性属性。

Feature: relief-mode-bugfix, Property 1: Hex 键归一化幂等性
"""

import os
import sys

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

# Ensure project root is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.converter import _normalize_color_height_map

# ---------------------------------------------------------------------------
# Strategies: generate valid hex color strings (with/without '#' prefix)
# ---------------------------------------------------------------------------

_hex_char = st.sampled_from("0123456789abcdefABCDEF")

_hex6_body = st.text(_hex_char, min_size=6, max_size=6)

_hex_key = st.one_of(
    _hex6_body,                                    # e.g. "ff00aa"
    _hex6_body.map(lambda s: f"#{s}"),             # e.g. "#ff00aa"
)

_height_value = st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False)


# ============================================================================
# Property 1: Hex 键归一化幂等性
# Feature: relief-mode-bugfix, Property 1: Hex 键归一化幂等性
# **Validates: Requirements 1.1**
# ============================================================================

@settings(max_examples=200)
@given(
    color_height_map=st.dictionaries(
        keys=_hex_key,
        values=_height_value,
        min_size=1,
        max_size=20,
    ),
)
def test_normalize_keys_always_start_with_hash(
    color_height_map: dict[str, float],
) -> None:
    """All keys in the normalized map must start with '#'.

    归一化后的所有键必须以 '#' 开头。

    **Validates: Requirements 1.1**
    """
    normalized = _normalize_color_height_map(color_height_map)

    for key in normalized:
        assert key.startswith("#"), (
            f"Normalized key {key!r} does not start with '#'. "
            f"Original map keys: {list(color_height_map.keys())}"
        )


@settings(max_examples=200)
@given(
    color_height_map=st.dictionaries(
        keys=_hex_key,
        values=_height_value,
        min_size=1,
        max_size=20,
    ),
)
def test_normalize_is_idempotent(
    color_height_map: dict[str, float],
) -> None:
    """Normalizing twice yields the same result as normalizing once.

    归一化操作是幂等的：归一化两次的结果与一次相同。

    **Validates: Requirements 1.1**
    """
    once = _normalize_color_height_map(color_height_map)
    twice = _normalize_color_height_map(once)

    assert once == twice, (
        f"Normalization is not idempotent.\n"
        f"  once:  {once}\n"
        f"  twice: {twice}"
    )


@settings(max_examples=200)
@given(
    color_height_map=st.dictionaries(
        keys=_hex_key,
        values=_height_value,
        min_size=1,
        max_size=20,
    ),
)
def test_normalize_preserves_all_height_values(
    color_height_map: dict[str, float],
) -> None:
    """Normalization must not lose or alter any height value.

    归一化不应丢失或改变任何高度值（无冲突键时）。
    当 "abc123" 和 "#abc123" 同时存在时，后者会覆盖前者，
    这是 dict 的正常行为，不算丢失。

    **Validates: Requirements 1.1**
    """
    normalized = _normalize_color_height_map(color_height_map)

    for original_key, original_value in color_height_map.items():
        norm_key = original_key if original_key.startswith("#") else f"#{original_key}"

        # Check if there's a conflicting key (both "abc" and "#abc" present)
        bare = original_key.lstrip("#")
        has_conflict = bare in color_height_map and f"#{bare}" in color_height_map

        assert norm_key in normalized, (
            f"Expected key {norm_key!r} missing from normalized map. "
            f"Normalized keys: {list(normalized.keys())}"
        )

        if not has_conflict:
            # No collision — value must be preserved exactly
            assert normalized[norm_key] == original_value, (
                f"Height value changed for {norm_key!r}: "
                f"expected {original_value}, got {normalized[norm_key]}"
            )


# ============================================================================
# Property 2: 归一化后高度查找正确性
# Feature: relief-mode-bugfix, Property 2: 归一化后高度查找正确性
# **Validates: Requirements 1.3**
# ============================================================================

# Strategy: RGB component (0-255)
_rgb_component = st.integers(min_value=0, max_value=255)

# Strategy: a single RGB tuple
_rgb_tuple = st.tuples(_rgb_component, _rgb_component, _rgb_component)

# Strategy: a default_height that is distinguishable from mapped heights
_default_height = st.just(0.0)


@settings(max_examples=200)
@given(
    color_height_map=st.dictionaries(
        keys=_hex_key,
        values=st.floats(min_value=1.0, max_value=100.0, allow_nan=False, allow_infinity=False),
        min_size=1,
        max_size=20,
    ),
    rgb=_rgb_tuple,
)
def test_normalized_height_lookup_returns_mapped_value(
    color_height_map: dict[str, float],
    rgb: tuple[int, int, int],
) -> None:
    """If a pixel's '#rrggbb' exists in the normalized map, lookup returns the mapped height.

    如果像素的 '#rrggbb' 格式存在于归一化后的 map 中，查找应返回映射的高度值而非 default_height。

    This replicates the exact lookup pattern used inside _build_relief_voxel_matrix:
      1. Normalize the color_height_map
      2. Build hex_color = f'#{r:02x}{g:02x}{b:02x}'
      3. Look up hex_color in the normalized map

    **Validates: Requirements 1.3**
    """
    default_height = 0.0
    normalized = _normalize_color_height_map(color_height_map)

    r, g, b = rgb
    hex_color = f'#{r:02x}{g:02x}{b:02x}'

    if hex_color in normalized:
        # The lookup should return the mapped height, NOT default_height
        looked_up_height = normalized[hex_color]
        assert looked_up_height != default_height, (
            f"Pixel {hex_color} found in normalized map but height equals default_height "
            f"({default_height}). Mapped heights must be > 0 (range [1.0, 100.0]) "
            f"so this should never equal default_height=0.0. "
            f"Got: {looked_up_height}"
        )


@settings(max_examples=200)
@given(
    color_height_map=st.dictionaries(
        keys=_hex_key,
        values=_height_value,
        min_size=1,
        max_size=20,
    ),
    rgb=_rgb_tuple,
)
def test_normalized_height_lookup_uses_correct_value(
    color_height_map: dict[str, float],
    rgb: tuple[int, int, int],
) -> None:
    """When a pixel color exists in the map (with or without '#'), the normalized
    lookup must return the exact height value associated with that color.

    当像素颜色存在于 map 中（无论带不带 '#'），归一化后的查找必须返回该颜色关联的精确高度值。

    This verifies the full normalization → lookup chain:
      - Original key "ff0000" with height 5.0 → normalized "#ff0000" → lookup for pixel (255,0,0) → 5.0
      - Original key "#ff0000" with height 5.0 → normalized "#ff0000" → lookup for pixel (255,0,0) → 5.0

    **Validates: Requirements 1.3**
    """
    normalized = _normalize_color_height_map(color_height_map)

    r, g, b = rgb
    hex_color = f'#{r:02x}{g:02x}{b:02x}'

    if hex_color in normalized:
        looked_up = normalized[hex_color]

        # Determine expected value: the original map should have this color
        # under either "rrggbb" or "#rrggbb" key (or both, with '#' winning last)
        bare_key = hex_color[1:]  # strip '#'
        hash_key = hex_color

        # The normalized value should match one of the original entries
        possible_originals = []
        if bare_key in color_height_map:
            possible_originals.append(color_height_map[bare_key])
        if hash_key in color_height_map:
            possible_originals.append(color_height_map[hash_key])

        assert looked_up in possible_originals, (
            f"Lookup for {hex_color} returned {looked_up}, "
            f"but original map values for this color were {possible_originals}. "
            f"Original map: {color_height_map}"
        )


@settings(max_examples=200)
@given(
    # Generate a map where we KNOW a specific color is present
    rgb=_rgb_tuple,
    height=st.floats(min_value=0.5, max_value=50.0, allow_nan=False, allow_infinity=False),
    use_hash_prefix=st.booleans(),
)
def test_height_lookup_always_finds_inserted_color(
    rgb: tuple[int, int, int],
    height: float,
    use_hash_prefix: bool,
) -> None:
    """For any RGB pixel, if we insert its hex representation into color_height_map
    (with or without '#'), the normalized lookup must find it and return the correct height.

    对于任意 RGB 像素，如果将其 hex 表示插入 color_height_map（带或不带 '#'），
    归一化后的查找必须找到它并返回正确的高度值。

    **Validates: Requirements 1.3**
    """
    r, g, b = rgb
    bare_hex = f'{r:02x}{g:02x}{b:02x}'

    # Build the map with the key in the chosen format
    key = f'#{bare_hex}' if use_hash_prefix else bare_hex
    color_height_map = {key: height}

    normalized = _normalize_color_height_map(color_height_map)

    # The lookup key used by _build_relief_voxel_matrix
    lookup_key = f'#{r:02x}{g:02x}{b:02x}'

    assert lookup_key in normalized, (
        f"Lookup key {lookup_key!r} not found in normalized map {normalized}. "
        f"Original key was {key!r}."
    )
    assert normalized[lookup_key] == height, (
        f"Expected height {height} for {lookup_key!r}, got {normalized[lookup_key]}."
    )
