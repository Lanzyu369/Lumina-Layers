"""Unit tests for the dedicated advanced_params sanitizer.

``advanced_params`` 专用 sanitizer 的单元测试。

These tests pin down the observable contract of
:func:`api.routers.feedback._sanitize_advanced_params`:

- Preserve up to 64 keys under ``relief.color_height_map`` (path-level
  exception raising the default 24-key cap).
- Truncate ``relief.color_height_map`` beyond 64 keys with the shared
  ``__truncated_keys`` marker.
- Keep arrays with up to 64 items untouched (``color_replacement.replacement_regions``
  at 32 and ``fridge_magnet.fridge_magnets`` at 20 both sit below the 64
  cap).
- Preserve nesting up to depth 6 (the generic sanitizer would cut at
  depth 4).
- Fall back to the default 24-key object cap on sibling groups that are
  not ``relief.color_height_map``.

Covers requirements 6.4, 6.5, 10.7.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from api.routers.feedback import _sanitize_advanced_params


def _color_height_map(count: int) -> dict[str, float]:
    """Build a ``color_height_map`` with *count* deterministic entries.

    构造包含 *count* 个条目的 ``color_height_map``。
    """
    return {f"#{i:06x}": float(i) * 0.01 for i in range(count)}


def test_sanitizer_preserves_color_height_map_with_64_entries() -> None:
    """64-entry color_height_map must survive without the truncation marker.

    ``relief.color_height_map`` 恰好 64 项时不得出现 ``__truncated_keys``。
    """
    chm = _color_height_map(64)
    payload = {"relief": {"enable_relief": True, "color_height_map": chm}}

    result = _sanitize_advanced_params(payload)

    relief = result["relief"]
    assert relief["enable_relief"] is True
    assert "__truncated_keys" not in relief["color_height_map"]
    assert len(relief["color_height_map"]) == 64
    assert relief["color_height_map"] == chm


def test_sanitizer_truncates_color_height_map_beyond_64_entries() -> None:
    """100-entry color_height_map trims to 64 with ``__truncated_keys == 36``.

    100 项的 ``color_height_map`` 会裁剪到 64 并设置 ``__truncated_keys = 36``。
    """
    chm = _color_height_map(100)
    payload = {"relief": {"enable_relief": True, "color_height_map": chm}}

    result = _sanitize_advanced_params(payload)

    sanitized_chm = result["relief"]["color_height_map"]
    # 64 preserved keys + 1 meta marker key.
    assert len(sanitized_chm) == 65
    assert sanitized_chm["__truncated_keys"] == 36

    # The first 64 keys (insertion order) are the ones preserved.
    preserved_keys = [k for k in sanitized_chm.keys() if k != "__truncated_keys"]
    expected_keys = [f"#{i:06x}" for i in range(64)]
    assert preserved_keys == expected_keys


def test_sanitizer_preserves_replacement_regions_with_32_items() -> None:
    """Array with 32 items must stay intact (cap is 64 array items).

    32 项的数组不会被裁剪（数组上限是 64）。
    """
    regions = [
        {
            "quantized_hex": f"#q{i:05x}",
            "matched_hex": f"#m{i:05x}",
            "replacement_hex": f"#r{i:05x}",
        }
        for i in range(32)
    ]
    payload = {"color_replacement": {"replacement_regions": regions}}

    result = _sanitize_advanced_params(payload)

    sanitized_regions = result["color_replacement"]["replacement_regions"]
    assert len(sanitized_regions) == 32
    # No "<truncated:N>" tail marker present.
    assert all(isinstance(item, dict) for item in sanitized_regions)
    assert sanitized_regions == regions


def test_sanitizer_preserves_fridge_magnets_with_20_items() -> None:
    """Fridge magnets list with 20 scalar items survives untouched.

    20 项冰箱贴（纯标量）全部保留，不被裁剪。
    """
    magnets = [
        {
            "id": f"mag-{i}",
            "shape": "round" if i % 2 == 0 else "rect",
            "preset_key": f"preset-{i}",
            "diameter_mm": 25.0 if i % 2 == 0 else None,
            "width_mm": None if i % 2 == 0 else 30.0,
            "height_mm": None if i % 2 == 0 else 20.0,
            "thickness_mm": 3.0,
            "center_x_mm": float(i),
            "center_y_mm": float(i) * 2.0,
        }
        for i in range(20)
    ]
    payload = {
        "fridge_magnet": {
            "enable_fridge_magnet": True,
            "selectedFridgeMagnetId": "mag-0",
            "fridge_magnets": magnets,
        }
    }

    result = _sanitize_advanced_params(payload)

    sanitized = result["fridge_magnet"]["fridge_magnets"]
    assert len(sanitized) == 20
    assert sanitized == magnets


def test_sanitizer_preserves_depth_6_nesting() -> None:
    """Six-level-deep dict nesting reaches the leaf scalar unchanged.

    六层嵌套字典时，叶子标量能被保留，generic sanitizer 会在第 4 层就截断。
    """
    payload = {
        "l1": {
            "l2": {
                "l3": {
                    "l4": {
                        "l5": {
                            "l6": "deep-leaf",
                        },
                    },
                },
            },
        },
    }

    result = _sanitize_advanced_params(payload)

    leaf = result["l1"]["l2"]["l3"]["l4"]["l5"]["l6"]
    assert leaf == "deep-leaf"


def test_sanitizer_applies_default_24_key_cap_on_sibling_groups() -> None:
    """Default 24-key cap still applies on a group other than relief.color_height_map.

    除 ``relief.color_height_map`` 以外的 sibling 分组仍然遵守 24 个 key 上限。
    """
    generation = {f"field_{i:02d}": i for i in range(30)}
    payload = {
        "relief": {
            "enable_relief": True,
            "color_height_map": _color_height_map(64),
        },
        "generation": generation,
    }

    result = _sanitize_advanced_params(payload)

    # relief.color_height_map keeps all 64 entries (path exception).
    assert "__truncated_keys" not in result["relief"]["color_height_map"]
    assert len(result["relief"]["color_height_map"]) == 64

    # generation is capped at 24 keys + the truncation marker.
    sanitized_generation = result["generation"]
    assert sanitized_generation["__truncated_keys"] == 6
    preserved_keys = [
        k for k in sanitized_generation.keys() if k != "__truncated_keys"
    ]
    assert len(preserved_keys) == 24
    assert preserved_keys == [f"field_{i:02d}" for i in range(24)]


# ---------------------------------------------------------------------------
# Property-based tests
# 属性测试
# ---------------------------------------------------------------------------


# Keys are bounded to 120 characters because ``_truncate_feedback_text``
# truncates longer keys to ``"<first 120 chars>...<truncated>"``. Two
# distinct generated keys that share a 120-char prefix would collapse
# onto the same sanitized key, which would cause the length-preservation
# assertion below to fail spuriously. Bounding the alphabet size here
# keeps the property aligned with its intent: the dedicated sanitizer
# must not insert ``__truncated_keys`` under ``relief.color_height_map``
# when the map has ≤ 64 entries.
#
# key 长度上限 120 是因为 ``_truncate_feedback_text`` 会对更长的 key
# 统一截断为 ``"<前 120 字符>...<truncated>"``，两个共享前 120 字符
# 的 key 在清洗后会冲突折叠，从而破坏下面的长度断言。这里约束 key
# 长度使属性测试聚焦于真正要验证的内容：当 ``relief.color_height_map``
# 只有 ≤ 64 项时，专用 sanitizer 不会插入 ``__truncated_keys`` 标记。
_chm_key_strategy = st.text(min_size=1, max_size=120)
_chm_value_strategy = st.floats(allow_nan=False, allow_infinity=False)
_chm_dict_strategy = st.dictionaries(
    keys=_chm_key_strategy,
    values=_chm_value_strategy,
    max_size=64,
)


@given(color_height_map=_chm_dict_strategy)
@settings(max_examples=200, deadline=None)
def test_sanitizer_preserves_color_height_map_within_cap_property(
    color_height_map: dict[str, float],
) -> None:
    """Property P3: dedicated sanitizer preserves ≤ 64-entry color_height_map.

    属性 P3：专用 sanitizer 对 ≤ 64 项的 color_height_map 不做截断。

    For any JSON-safe dict with ``relief.color_height_map`` of size ≤ 64,
    the sanitized output under ``result["relief"]["color_height_map"]``:

    - MUST NOT contain the ``__truncated_keys`` marker.
    - MUST have the same length as the original ``color_height_map``.

    对任意 size ≤ 64 的 ``relief.color_height_map`` JSON 安全字典，
    清洗后的 ``result["relief"]["color_height_map"]``：

    - 必须不含 ``__truncated_keys`` 标记；
    - 长度必须与原始 ``color_height_map`` 相等。

    **Validates: Requirements 6.4**
    """
    payload = {
        "relief": {
            "enable_relief": True,
            "color_height_map": color_height_map,
        }
    }

    result = _sanitize_advanced_params(payload)

    sanitized_chm = result["relief"]["color_height_map"]
    assert "__truncated_keys" not in sanitized_chm
    assert len(sanitized_chm) == len(color_height_map)
