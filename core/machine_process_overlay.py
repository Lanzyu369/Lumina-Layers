from __future__ import annotations

from typing import Any

from config import format_native_nozzle_size


PROTECTED_LUMINA_PROCESS_SETTINGS: dict[str, Any] = {
    "layer_height": "0.08",
    "initial_layer_height": "0.08",
    "initial_layer_print_height": "0.08",
    "wall_loops": "1",
    "wall_generator": "arachne",
    "skirt_loops": "0",
    "skirt_distance": "2",
    "skirt_height": "1",
    "draft_shield": "disabled",
    "top_shell_layers": "0",
    "bottom_shell_layers": "1",
    "bottom_surface_pattern": "monotonicline",
    "elefant_foot_compensation": "0",
    "sparse_infill_density": "100%",
    "sparse_infill_pattern": "zig-zag",
    "travel_speed": "150",
    "enable_support": "0",
    "brim_width": "5",
    "brim_type": "auto_brim",
}

_PROTECTED_LINE_WIDTH_KEYS = (
    "line_width",
    "inner_wall_line_width",
    "outer_wall_line_width",
    "top_surface_line_width",
    "sparse_infill_line_width",
    "internal_solid_infill_line_width",
    "support_line_width",
)


def _format_mm(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def merge_lumina_process_settings(
    defaults: dict[str, Any],
    requested: dict[str, Any] | None,
) -> dict[str, Any]:
    """Apply explicit settings without retaining a competing first-layer default.

    合并明确工艺设置；指定任一首层高度名称时，移除两个名称下的默认值。
    明确提供的相互矛盾值会保留，交由 Fat Cat 拒绝。

    Args:
        defaults: Product process defaults. 产品工艺默认值。
        requested: Caller-supplied settings. 调用方明确提供的设置。

    Returns:
        Combined values retaining explicit conflicts for validation.
        合并后的设置；明确输入中的冲突值仍保留以供校验。
    """

    supplied = dict(requested or {})
    result = dict(defaults)
    first_layer_keys = ("initial_layer_height", "initial_layer_print_height")
    if any(supplied.get(key) is not None for key in first_layer_keys):
        for key in first_layer_keys:
            result.pop(key, None)
    result.update(supplied)
    return result


def build_lumina_process_settings(
    settings: dict[str, Any] | None = None,
    *,
    nozzle_size: object = None,
    slicer_id: str = "",
) -> dict[str, str]:
    """Return the explicit Lumina process values for one export.

    返回本次导出明确使用的 Lumina 工艺参数；不会读取机器模板。
    """

    requested = dict(settings or {})
    nozzle = format_native_nozzle_size(nozzle_size) or "0.4"
    nozzle_mm = float(nozzle)
    line_width = _format_mm(nozzle_mm + 0.02)
    initial_line_width = "0.25" if nozzle_mm <= 0.25 else line_width
    result = {key: str(value) for key, value in PROTECTED_LUMINA_PROCESS_SETTINGS.items()}
    if slicer_id == "PrusaSlicer":
        # Product default: Prusa has no automatic-brim enum.
        result["brim_type"] = "outer_only"
    result.update({key: line_width for key in _PROTECTED_LINE_WIDTH_KEYS})
    result["initial_layer_line_width"] = initial_line_width
    explicit = {
        key: str(value)
        for key, value in requested.items()
        if value is not None and not isinstance(value, (dict, list, tuple))
    }
    return merge_lumina_process_settings(result, explicit)


def apply_lumina_process_overlay(
    native_settings: dict[str, Any],
    *,
    slot_count: int = 8,
    source_profile_name: str | None = None,
    slicer_id: str | None = None,
) -> dict[str, Any]:
    """Compatibility wrapper for callers of the former build-time overlay.

    兼容旧调用；新导出把工艺参数作为明确请求传给 Fat Cat。
    """

    del slot_count, source_profile_name, slicer_id
    result = dict(native_settings)
    raw_nozzle = native_settings.get("nozzle_diameter")
    if isinstance(raw_nozzle, (list, tuple)) and raw_nozzle:
        raw_nozzle = raw_nozzle[0]
    nozzle_size = (
        format_native_nozzle_size(raw_nozzle)
        or format_native_nozzle_size(native_settings.get("printer_variant"))
        or "0.4"
    )
    result.update(build_lumina_process_settings(nozzle_size=nozzle_size))
    return result
