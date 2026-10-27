"""JSONB-safe codec for Postgres session values.
Postgres session 值的 JSONB 安全编解码。

The memory ``SessionStore`` can hold arbitrary Python objects, including
NumPy arrays used by preview / replacement caches. The Postgres backend stores
session payloads in JSONB, so this codec preserves those internal values via
small typed JSON envelopes.
内存版 ``SessionStore`` 可保存任意 Python 对象，包括 preview / replacement 缓存
使用的 NumPy 数组。Postgres 后端使用 JSONB，因此这里用带类型标记的 JSON 包装
保留这些内部值。
"""

from __future__ import annotations

import base64
import math
import pickle
from typing import Any

import numpy as np

_TYPE_KEY = "__lumina_session_type__"


def encode_session_value(value: Any) -> Any:
    """Encode a Python session value into JSONB-compatible data.
    将 Python session 值编码为 JSONB 兼容数据。

    Args:
        value: Any value currently accepted by the in-memory ``SessionStore``.
            当前内存版 ``SessionStore`` 可接受的任意值。

    Returns:
        Any: A structure made only of JSON-compatible primitives, lists, and dicts.
        仅由 JSON 兼容基本类型、list、dict 组成的结构。
    """
    return _encode(value)


def decode_session_value(value: Any) -> Any:
    """Decode data produced by :func:`encode_session_value`.
    解码 :func:`encode_session_value` 产生的数据。

    Args:
        value: JSONB value loaded from Postgres.
            从 Postgres JSONB 读出的值。

    Returns:
        Any: The reconstructed Python value.
        还原后的 Python 值。
    """
    return _decode(value)


def _encode(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if math.isfinite(value):
            return value
        if math.isnan(value):
            label = "nan"
        elif value > 0:
            label = "inf"
        else:
            label = "-inf"
        return {_TYPE_KEY: "float", "value": label}
    if isinstance(value, np.generic):
        return _encode(value.item())
    if isinstance(value, np.ndarray):
        if value.dtype.hasobject:
            return _encode_pickle(value)
        array = np.ascontiguousarray(value)
        return {
            _TYPE_KEY: "ndarray",
            "dtype": str(array.dtype),
            "shape": list(array.shape),
            "data": base64.b64encode(array.tobytes()).decode("ascii"),
        }
    if isinstance(value, bytes):
        return {_TYPE_KEY: "bytes", "data": base64.b64encode(value).decode("ascii")}
    if isinstance(value, tuple):
        return {_TYPE_KEY: "tuple", "items": [_encode(item) for item in value]}
    if isinstance(value, set):
        return {_TYPE_KEY: "set", "items": [_encode(item) for item in value]}
    if isinstance(value, list):
        return [_encode(item) for item in value]
    if isinstance(value, dict):
        return {
            _TYPE_KEY: "dict",
            "items": [[_encode(key), _encode(item)] for key, item in value.items()],
        }
    return _encode_pickle(value)


def _decode(value: Any) -> Any:
    if isinstance(value, list):
        return [_decode(item) for item in value]
    if not isinstance(value, dict):
        return value
    type_name = value.get(_TYPE_KEY)
    if not type_name:
        return {key: _decode(item) for key, item in value.items()}
    if type_name == "float":
        label = value["value"]
        if label == "nan":
            return float("nan")
        if label == "inf":
            return float("inf")
        return float("-inf")
    if type_name == "ndarray":
        raw = base64.b64decode(value["data"].encode("ascii"))
        array = np.frombuffer(raw, dtype=np.dtype(value["dtype"]))
        return array.reshape(tuple(value["shape"])).copy()
    if type_name == "bytes":
        return base64.b64decode(value["data"].encode("ascii"))
    if type_name == "tuple":
        return tuple(_decode(item) for item in value["items"])
    if type_name == "set":
        return {_decode(item) for item in value["items"]}
    if type_name == "dict":
        return {_decode(key): _decode(item) for key, item in value["items"]}
    if type_name == "pickle":
        raw = base64.b64decode(value["data"].encode("ascii"))
        return pickle.loads(raw)
    raise ValueError(f"Unknown Lumina session value type: {type_name!r}")


def _encode_pickle(value: Any) -> dict[str, str]:
    try:
        raw = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
    except (pickle.PicklingError, TypeError, AttributeError, ValueError) as exc:
        raise TypeError(f"Session value of type {type(value).__name__!r} is not serializable") from exc
    return {_TYPE_KEY: "pickle", "data": base64.b64encode(raw).decode("ascii")}
