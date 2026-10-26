from __future__ import annotations

from typing import Any, Mapping

from config import format_native_nozzle_size


LUMINA_PROJECT_PRESET_NAME = "Lumina"


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
    *,
    aliases: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Replace defaults sharing a native field with an explicit override.

    根据工艺别名合并明确设置，移除同一原生字段的默认值。
    明确提供的相互矛盾值会保留，交由 Fat Cat 拒绝。

    Args:
        defaults: Product process defaults. 产品工艺默认值。
        requested: Caller-supplied settings. 调用方明确提供的设置。
        aliases: FatCat's public input-to-native field mapping.
            FatCat 公共合同中的输入名称映射。

    Returns:
        Combined values retaining explicit conflicts for validation.
        合并后的设置；明确输入中的冲突值仍保留以供校验。
    """

    supplied = dict(requested or {})
    field_aliases = (
        aliases if aliases is not None
        else {"initial_layer_height": "initial_layer_print_height"}
    )
    overridden = {
        field_aliases.get(key, key)
        for key, value in supplied.items()
        if value is not None
    }
    result = {
        key: value for key, value in defaults.items()
        if field_aliases.get(key, key) not in overridden
    }
    result.update(supplied)
    return result


def build_lumina_process_settings(
    settings: dict[str, Any] | None = None,
    *,
    nozzle_size: object = None,
    slicer_id: str = "",
    aliases: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return the explicit Lumina process values for one export.

    返回本次导出明确使用的 Lumina 工艺参数；不会读取机器模板。

    Args:
        settings: Explicit process overrides. 明确的工艺覆盖值。
        nozzle_size: Selected nozzle diameter. 已选喷嘴直径。
        slicer_id: Selected slicer identity. 已选切片软件身份。
        aliases: Public FatCat process aliases. FatCat 公共工艺别名。

    Returns:
        Product defaults combined with explicit overrides.
        合并产品默认值与明确覆盖值的工艺设置。
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
    return merge_lumina_process_settings(result, explicit, aliases=aliases)
