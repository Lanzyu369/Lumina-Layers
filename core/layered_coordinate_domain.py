"""Canonical coordinates shared by layered mesh producers and writers.

分层网格生产者与写出器共享的规范坐标契约。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import math
from numbers import Integral
from typing import Any

import numpy as np


LAYERED_COORDINATE_DOMAIN_KEY = "layered_coordinate_domain"
LAYERED_COORDINATE_DOMAIN_CERTIFIED_KEY = (
    "layered_coordinate_domain_certified"
)
LAYERED_COORDINATE_DOMAIN_VERSION = 1


def _finite_positive(value: object, *, name: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite positive number") from exc
    if not math.isfinite(parsed) or parsed <= 0.0:
        raise ValueError(f"{name} must be a finite positive number")
    return parsed


def _writer_lower_bound(value: float) -> float:
    return min(value, float(np.float32(value)))


def _writer_upper_bound(value: float) -> float:
    return max(value, float(np.float32(value)))


def _half_up_units(value_mm: float, grid_mm: float) -> int:
    units = int(math.floor(value_mm / grid_mm + 0.5))
    if units <= 0:
        raise ValueError("Canvas dimension is smaller than the coordinate grid")
    return units


def _metadata_sequence(value: object, *, name: str) -> Sequence[object]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError(f"{name} must be a sequence")
    return value


def _metadata_int_pair(value: object, *, name: str) -> tuple[int, int]:
    sequence = _metadata_sequence(value, name=name)
    if len(sequence) != 2:
        raise ValueError(f"{name} must contain two integers")
    parsed: list[int] = []
    for item in sequence:
        if isinstance(item, bool) or not isinstance(item, Integral):
            raise ValueError(f"{name} must contain two integers")
        parsed.append(int(item))
    return parsed[0], parsed[1]


def _metadata_float_tuple(
    value: object,
    *,
    name: str,
    length: int | None = None,
) -> tuple[float, ...]:
    sequence = _metadata_sequence(value, name=name)
    if length is not None and len(sequence) != length:
        raise ValueError(f"{name} has an invalid length")
    try:
        parsed = tuple(float(item) for item in sequence)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must contain numbers") from exc
    if not all(math.isfinite(item) for item in parsed):
        raise ValueError(f"{name} must contain finite numbers")
    return parsed


@dataclass(frozen=True)
class LayeredCoordinateDomain:
    """Own the integer XY canvas, Z schedule, and float32 writer envelope.

    持有整数 XY 画布、唯一 Z 分层边界，以及 float32 写出外包边界。

    The domain is immutable and validates that its writer envelope is derived
    from its own integer/layer coordinates. Metadata therefore cannot claim a
    wider envelope than the geometry contract actually owns.

    该对象不可变，并验证写出边界确实由自身整数与分层坐标推导，避免元数据
    伪造比真实坐标契约更宽的边界。
    """

    version: int
    xy_grid_mm: float
    canvas_min_units: tuple[int, int]
    canvas_max_units: tuple[int, int]
    layer_boundaries_mm: tuple[float, ...]
    writer_canvas_bounds_mm: tuple[float, float, float, float]
    writer_z_bounds_mm: tuple[float, float]

    def __post_init__(self) -> None:
        if (
            isinstance(self.version, bool)
            or not isinstance(self.version, Integral)
            or int(self.version) != LAYERED_COORDINATE_DOMAIN_VERSION
        ):
            raise ValueError("Unsupported layered coordinate-domain version")
        grid_mm = _finite_positive(self.xy_grid_mm, name="xy_grid_mm")
        min_units = _metadata_int_pair(
            self.canvas_min_units,
            name="canvas_min_units",
        )
        max_units = _metadata_int_pair(
            self.canvas_max_units,
            name="canvas_max_units",
        )
        if any(low >= high for low, high in zip(min_units, max_units)):
            raise ValueError("Canvas unit bounds must have positive area")

        boundaries = _metadata_float_tuple(
            self.layer_boundaries_mm,
            name="layer_boundaries_mm",
        )
        if len(boundaries) < 2 or boundaries[0] != 0.0:
            raise ValueError("Layer boundaries must start at zero")
        if any(
            current <= previous
            for previous, current in zip(boundaries, boundaries[1:])
        ):
            raise ValueError("Layer boundaries must be strictly increasing")

        writer_canvas = _metadata_float_tuple(
            self.writer_canvas_bounds_mm,
            name="writer_canvas_bounds_mm",
            length=4,
        )
        physical_canvas = (
            min_units[0] * grid_mm,
            min_units[1] * grid_mm,
            max_units[0] * grid_mm,
            max_units[1] * grid_mm,
        )
        expected_writer_canvas = (
            _writer_lower_bound(physical_canvas[0]),
            _writer_lower_bound(physical_canvas[1]),
            _writer_upper_bound(physical_canvas[2]),
            _writer_upper_bound(physical_canvas[3]),
        )
        if writer_canvas != expected_writer_canvas:
            raise ValueError("Writer XY envelope does not match canvas units")

        writer_z = _metadata_float_tuple(
            self.writer_z_bounds_mm,
            name="writer_z_bounds_mm",
            length=2,
        )
        expected_writer_z = (
            _writer_lower_bound(boundaries[0]),
            _writer_upper_bound(boundaries[-1]),
        )
        if writer_z != expected_writer_z:
            raise ValueError("Writer Z envelope does not match layer boundaries")

    @classmethod
    def from_canvas_and_layers(
        cls,
        *,
        width_mm: float,
        height_mm: float,
        xy_grid_mm: float,
        layer_heights_mm: Sequence[float],
    ) -> "LayeredCoordinateDomain":
        """Build one canonical domain from physical canvas and layer heights.

        根据物理画布尺寸与层高序列构建唯一的规范坐标域。

        Args:
            width_mm: Requested canvas width in millimetres.
                请求画布宽度，单位毫米。
            height_mm: Requested canvas height in millimetres.
                请求画布高度，单位毫米。
            xy_grid_mm: Shared integer XY grid size in millimetres.
                全部网格共享的整数 XY 格距，单位毫米。
            layer_heights_mm: Ordered positive display-layer heights.
                按顺序排列的正数显示层高。

        Returns:
            An immutable validated coordinate domain.
            一个不可变且已验证的坐标域。

        Raises:
            ValueError: If dimensions, grid, or layers are invalid.
                当尺寸、格距或层高无效时抛出。
        """

        width = _finite_positive(width_mm, name="width_mm")
        height = _finite_positive(height_mm, name="height_mm")
        grid = _finite_positive(xy_grid_mm, name="xy_grid_mm")
        heights = tuple(
            _finite_positive(value, name="layer_heights_mm")
            for value in layer_heights_mm
        )
        if not heights:
            raise ValueError("layer_heights_mm must not be empty")

        max_units = (
            _half_up_units(width, grid),
            _half_up_units(height, grid),
        )
        boundaries = (0.0,) + tuple(
            math.fsum(heights[:index])
            for index in range(1, len(heights) + 1)
        )
        physical_width = max_units[0] * grid
        physical_height = max_units[1] * grid
        return cls(
            version=LAYERED_COORDINATE_DOMAIN_VERSION,
            xy_grid_mm=grid,
            canvas_min_units=(0, 0),
            canvas_max_units=max_units,
            layer_boundaries_mm=boundaries,
            writer_canvas_bounds_mm=(
                _writer_lower_bound(0.0),
                _writer_lower_bound(0.0),
                _writer_upper_bound(physical_width),
                _writer_upper_bound(physical_height),
            ),
            writer_z_bounds_mm=(
                _writer_lower_bound(boundaries[0]),
                _writer_upper_bound(boundaries[-1]),
            ),
        )

    @property
    def layer_heights_mm(self) -> tuple[float, ...]:
        """Return nominal heights derived from the canonical boundaries.

        返回由规范 Z 边界推导出的名义层高。
        """

        return tuple(
            upper - lower
            for lower, upper in zip(
                self.layer_boundaries_mm,
                self.layer_boundaries_mm[1:],
            )
        )

    def to_metadata(self) -> dict[str, Any]:
        """Serialize the domain into JSON-safe scene metadata.

        将坐标域序列化为可安全写入 JSON 的场景元数据。
        """

        return {
            "version": int(self.version),
            "xy_grid_mm": float(self.xy_grid_mm),
            "canvas_min_units": list(self.canvas_min_units),
            "canvas_max_units": list(self.canvas_max_units),
            "layer_boundaries_mm": list(self.layer_boundaries_mm),
            "writer_canvas_bounds_mm": list(self.writer_canvas_bounds_mm),
            "writer_z_bounds_mm": list(self.writer_z_bounds_mm),
        }

    @classmethod
    def from_metadata(cls, value: object) -> "LayeredCoordinateDomain":
        """Parse and validate a coordinate domain from scene metadata.

        从场景元数据解析并验证坐标域。

        Args:
            value: Mapping returned by :meth:`to_metadata`.
                由 :meth:`to_metadata` 返回的映射。

        Returns:
            The validated immutable coordinate domain.
            验证后的不可变坐标域。

        Raises:
            ValueError: If metadata is missing, malformed, or forged.
                当元数据缺失、损坏或与自身坐标不一致时抛出。
        """

        if not isinstance(value, Mapping):
            raise ValueError("Layered coordinate-domain metadata must be a mapping")
        try:
            version = value["version"]
            grid = float(value["xy_grid_mm"])
            min_units = _metadata_int_pair(
                value["canvas_min_units"],
                name="canvas_min_units",
            )
            max_units = _metadata_int_pair(
                value["canvas_max_units"],
                name="canvas_max_units",
            )
            boundaries = _metadata_float_tuple(
                value["layer_boundaries_mm"],
                name="layer_boundaries_mm",
            )
            writer_canvas = _metadata_float_tuple(
                value["writer_canvas_bounds_mm"],
                name="writer_canvas_bounds_mm",
                length=4,
            )
            writer_z = _metadata_float_tuple(
                value["writer_z_bounds_mm"],
                name="writer_z_bounds_mm",
                length=2,
            )
        except KeyError as exc:
            raise ValueError("Layered coordinate-domain metadata is incomplete") from exc
        except (TypeError, ValueError) as exc:
            raise ValueError("Layered coordinate-domain metadata is malformed") from exc
        return cls(
            version=version,
            xy_grid_mm=grid,
            canvas_min_units=min_units,
            canvas_max_units=max_units,
            layer_boundaries_mm=boundaries,
            writer_canvas_bounds_mm=writer_canvas,
            writer_z_bounds_mm=writer_z,
        )


__all__ = [
    "LAYERED_COORDINATE_DOMAIN_CERTIFIED_KEY",
    "LAYERED_COORDINATE_DOMAIN_KEY",
    "LAYERED_COORDINATE_DOMAIN_VERSION",
    "LayeredCoordinateDomain",
]
