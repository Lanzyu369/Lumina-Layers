"""Verify complete advanced parameters survive public feedback validation.

验证完整高级参数通过公开工单校验后仍保持原样，不再按长度或层级截断。
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from api.routers.feedback import BugReportRequest
from tests.test_feedback_router_unit import _payload


def _validate_advanced_params(value):
    payload = _payload()
    payload["context"]["advanced_params"] = value
    return BugReportRequest.model_validate(payload).context.advanced_params


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

    result = _validate_advanced_params(payload)

    relief = result["relief"]
    assert relief["enable_relief"] is True
    assert "__truncated_keys" not in relief["color_height_map"]
    assert len(relief["color_height_map"]) == 64
    assert relief["color_height_map"] == chm


def test_report_preserves_color_height_map_beyond_64_entries() -> None:
    payload = {"relief": {"enable_relief": True, "color_height_map": _color_height_map(100)}}
    assert _validate_advanced_params(payload) == payload



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

    result = _validate_advanced_params(payload)

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

    result = _validate_advanced_params(payload)

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

    result = _validate_advanced_params(payload)

    leaf = result["l1"]["l2"]["l3"]["l4"]["l5"]["l6"]
    assert leaf == "deep-leaf"


def test_report_preserves_large_sibling_groups() -> None:
    payload = {"generation": {f"field_{i:02d}": i for i in range(100)}}
    assert _validate_advanced_params(payload) == payload



def test_sanitizer_preserves_complete_generation_with_wipe_tower_warning() -> None:
    """The current 25-key generation payload must keep its final warning list."""

    generation = {
        "structure_mode": "Single-sided",
        "modeling_mode": "high-fidelity",
        "color_layers": 5,
        "layer_height_mm": 0.08,
        "model_enable": False,
        "model_only": False,
        "model_threshold": None,
        "model_margin": None,
        "quantize_colors": 48,
        "quantize_colors_unlocked": False,
        "high_precision_3d_preview": False,
        "enable_cleanup": True,
        "svg_pixels_per_mm": 10,
        "hue_enable": False,
        "chroma_gate": 0,
        "use_lut_constrained": False,
        "auto_dynamic_range": False,
        "separate_backing": False,
        "material_dynamic_layer_count_enabled": False,
        "material_min_layer_count": None,
        "material_max_layer_count": None,
        "material_backing_material_dir_name": None,
        "material_delta_e00_tolerance": None,
        "enable_wipe_tower_auto_placement": False,
        "wipe_tower_warning_codes": [
            "wipe_tower_manual_adjustment_required"
        ],
    }
    assert len(generation) == 25

    result = _validate_advanced_params({"generation": generation})

    sanitized_generation = result["generation"]
    assert sanitized_generation["enable_wipe_tower_auto_placement"] is False
    assert sanitized_generation["wipe_tower_warning_codes"] == [
        "wipe_tower_manual_adjustment_required"
    ]
    assert "__truncated_keys" not in sanitized_generation


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

    result = _validate_advanced_params(payload)

    sanitized_chm = result["relief"]["color_height_map"]
    assert "__truncated_keys" not in sanitized_chm
    assert len(sanitized_chm) == len(color_height_map)
