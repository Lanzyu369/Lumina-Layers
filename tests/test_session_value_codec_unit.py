"""Unit tests for the Postgres SessionStore JSONB value codec.
Postgres SessionStore JSONB 值编解码单元测试。
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from api.session_value_codec import decode_session_value, encode_session_value


def test_codec_round_trips_nested_preview_cache_like_payload() -> None:
    """Codec should preserve nested dict/list/set/tuple/ndarray values.
    编解码应保留嵌套 dict/list/set/tuple/ndarray 值。
    """
    payload = {
        "matched_rgb": np.arange(12, dtype=np.uint8).reshape(2, 2, 3),
        "material_matrix": np.array([[0, 1], [2, 3]], dtype=np.int16),
        "free_color_set": {"#000000", "#ffffff"},
        "shape": (2, 2),
        "regions": [{"id": "r1", "mask": np.array([[True, False]], dtype=np.bool_)}],
    }

    encoded = encode_session_value(payload)
    decoded = decode_session_value(encoded)

    np.testing.assert_array_equal(decoded["matched_rgb"], payload["matched_rgb"])
    np.testing.assert_array_equal(decoded["material_matrix"], payload["material_matrix"])
    np.testing.assert_array_equal(decoded["regions"][0]["mask"], payload["regions"][0]["mask"])
    assert decoded["free_color_set"] == payload["free_color_set"]
    assert decoded["shape"] == payload["shape"]


def test_codec_output_is_plain_json_shape() -> None:
    """Encoded values should contain only JSON-compatible container types.
    编码结果应只包含 JSON 兼容容器类型。
    """
    payload = {
        "array": np.array([[1, 2], [3, 4]], dtype=np.uint8),
        "colors": {"red", "blue"},
    }

    encoded = encode_session_value(payload)

    assert isinstance(encoded, dict)
    assert isinstance(encoded["items"], list)


def test_codec_round_trips_bytes_and_non_finite_floats() -> None:
    """Codec should preserve bytes plus NaN/Infinity values.
    编解码应保留 bytes 与 NaN/Infinity。
    """
    payload = {"blob": b"abc", "nan": float("nan"), "inf": float("inf"), "neg_inf": float("-inf")}

    decoded = decode_session_value(encode_session_value(payload))

    assert decoded["blob"] == b"abc"
    assert math.isnan(decoded["nan"])
    assert decoded["inf"] == float("inf")
    assert decoded["neg_inf"] == float("-inf")


def test_codec_raises_for_unpickleable_values() -> None:
    """Unpickleable values should fail with a clear ``TypeError``.
    无法 pickle 的值应以清晰 ``TypeError`` 失败。
    """
    with pytest.raises(TypeError, match="not serializable"):
        encode_session_value(lambda value: value)
