"""Backing infill rules shared by converter export paths.
转换器各导出路径共用的底板填充规则。

The slicer receives one global sparse-infill density for deep backing plus
100-percent object-height ranges adjacent to each viewing surface. Keeping
the geometry math here prevents raster, vector, batch, and tiled exports from
drifting apart.
切片器使用一个深层底板全局填充率，并在每个观赏面附近接收 100% 的对象高度
范围。几何计算集中在这里，避免光栅、矢量、批量和分片导出产生差异。
"""

from __future__ import annotations

import math

from config import PrinterConfig


_VALID_FACES = frozenset({"down", "up", "double"})


def normalize_backing_infill_density_percent(value: object) -> int:
    """Validate and normalize a backing infill percentage.
    校验并规范化底板填充百分比。

    Args:
        value: Requested percentage. Integer-valued floats are accepted.
            请求的百分比；允许数值等价于整数的浮点数。

    Returns:
        int: Percentage within the configured safe range.
            配置安全范围内的整数百分比。

    Raises:
        ValueError: If the value is non-finite, fractional, or out of range.
            数值非有限、带小数或越界时抛出。
    """
    if isinstance(value, bool):
        raise ValueError("Backing infill density must be an integer percentage.")
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "Backing infill density must be an integer percentage."
        ) from exc
    if not math.isfinite(numeric) or not numeric.is_integer():
        raise ValueError("Backing infill density must be an integer percentage.")
    density = int(numeric)
    minimum = PrinterConfig.BACKING_INFILL_DENSITY_MIN_PERCENT
    maximum = PrinterConfig.BACKING_INFILL_DENSITY_MAX_PERCENT
    if density < minimum or density > maximum:
        raise ValueError(
            f"Backing infill density must be between {minimum}% and {maximum}%."
        )
    return density


def resolve_effective_backing_infill_density_percent(
    requested_density_percent: object,
    *,
    base_height_mm: float,
    face: str,
    solid_depth_mm: float | None = None,
) -> int:
    """Resolve the global density after applying the solid-surface contract.
    应用观赏面实心规则后，解析 3MF 的全局底板填充率。

    A backing that is no deeper than the protected surface zone is globally
    solid. For double-sided work, both protected zones are considered and an
    overlapping pair likewise makes the whole backing solid.
    当底板不深于受保护的观赏面区域时，整块底板采用实心填充；双面作品会同时
    计算两侧区域，两侧相交时也会让整块底板保持实心。

    Args:
        requested_density_percent: User-requested sparse-infill percentage.
            用户请求的稀疏填充百分比。
        base_height_mm: Quantized backing height in millimetres.
            量化后的底板高度（毫米）。
        face: Viewing orientation: ``down``, ``up``, or ``double``.
            观赏面朝向：``down``、``up`` 或 ``double``。
        solid_depth_mm: Optional override for tests; ``None`` reads the
            canonical project configuration value.
            测试可选覆盖；``None`` 读取项目唯一配置值。

    Returns:
        int: Effective global sparse-infill percentage.
            实际写入 3MF 的全局稀疏填充百分比。

    Raises:
        ValueError: If geometry or configuration values are invalid.
            几何或配置值无效时抛出。
    """
    requested = normalize_backing_infill_density_percent(
        requested_density_percent
    )
    base_height = float(base_height_mm)
    if not math.isfinite(base_height) or base_height < 0:
        raise ValueError("Backing height must be a finite non-negative value.")
    normalized_face = str(face).strip().lower()
    if normalized_face not in _VALID_FACES:
        raise ValueError(f"Unsupported viewing-surface orientation: {face!r}")
    depth = _resolve_solid_depth_mm(solid_depth_mm)
    if base_height <= 0:
        return PrinterConfig.BACKING_INFILL_DENSITY_MAX_PERCENT
    protected_backing_depth = depth * (2 if normalized_face == "double" else 1)
    if base_height <= protected_backing_depth + 1e-9:
        return PrinterConfig.BACKING_INFILL_DENSITY_MAX_PERCENT
    return requested


def get_viewing_surface_solid_z_ranges(
    *,
    base_height_mm: float,
    color_height_mm: float,
    face: str,
    solid_depth_mm: float | None = None,
) -> list[tuple[float, float]]:
    """Return model Z ranges that must use 100-percent infill.
    返回必须使用 100% 填充的模型 Z 区间。

    The configured depth is measured through the backing starting at the
    colour/backing interface. Optical colour layers are included in the same
    protected range so the complete viewing-side volume remains solid.
    配置深度从彩色层与底板的交界处向底板内计算；彩色层也并入同一受保护区间，
    从而保证观赏面一侧的完整体积保持实心。

    Args:
        base_height_mm: Quantized backing height in millimetres.
            量化后的底板高度（毫米）。
        color_height_mm: Optical colour height per viewing side.
            每个观赏面的彩色层高度（毫米）。
        face: Viewing orientation: ``down``, ``up``, or ``double``.
            观赏面朝向：``down``、``up`` 或 ``double``。
        solid_depth_mm: Optional override for tests; ``None`` reads project
            configuration.
            测试可选覆盖；``None`` 读取项目配置。

    Returns:
        list[tuple[float, float]]: Sorted, non-overlapping ``(min_z, max_z)``
            ranges in millimetres.
            按 Z 排序且互不重叠的毫米区间。

    Raises:
        ValueError: If geometry or configuration values are invalid.
            几何或配置值无效时抛出。
    """
    base_height = float(base_height_mm)
    color_height = float(color_height_mm)
    if not math.isfinite(base_height) or base_height <= 0:
        return []
    if not math.isfinite(color_height) or color_height < 0:
        raise ValueError("Color height must be a finite non-negative value.")
    normalized_face = str(face).strip().lower()
    if normalized_face not in _VALID_FACES:
        raise ValueError(f"Unsupported viewing-surface orientation: {face!r}")
    depth = min(_resolve_solid_depth_mm(solid_depth_mm), base_height)
    if normalized_face == "down":
        return [(0.0, color_height + depth)]
    if normalized_face == "up":
        return [(base_height - depth, base_height + color_height)]

    total_height = base_height + (2.0 * color_height)
    ranges = [
        (0.0, color_height + depth),
        (color_height + base_height - depth, total_height),
    ]
    return _merge_touching_ranges(ranges)


def _resolve_solid_depth_mm(value: float | None) -> float:
    depth = (
        PrinterConfig.VIEWING_SURFACE_SOLID_DEPTH_MM
        if value is None
        else float(value)
    )
    if not math.isfinite(depth) or depth <= 0:
        raise ValueError("Viewing-surface solid depth must be a positive value.")
    return depth


def _merge_touching_ranges(
    ranges: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    normalized = sorted(
        (float(start), float(end))
        for start, end in ranges
        if end > start + 1e-9
    )
    merged: list[tuple[float, float]] = []
    for start, end in normalized:
        if not merged or start > merged[-1][1] + 1e-9:
            merged.append((start, end))
            continue
        merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    return merged
