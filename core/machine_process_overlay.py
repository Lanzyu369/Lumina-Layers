from __future__ import annotations

from copy import deepcopy
from typing import Any


PROTECTED_LUMINA_PROCESS_SETTINGS: dict[str, Any] = {
    "layer_height": "0.08",
    "initial_layer_height": "0.08",
    "wall_loops": "1",
    "top_shell_layers": "0",
    "bottom_shell_layers": "1",
    "bottom_surface_pattern": "monotonicline",
    "elefant_foot_compensation": "0",
    "sparse_infill_density": "100%",
    "sparse_infill_pattern": "zig-zag",
    "print_speed": "100",
    "travel_speed": "150",
    "enable_support": "0",
    "brim_width": "5",
    "brim_type": "auto_brim",
}


def _has_meaningful_value(value: Any) -> bool:
    return value is not None and str(value).strip() not in {"", "null", "None"}


def _format_mm(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _first_nozzle_mm(settings: dict[str, Any]) -> float:
    raw = settings.get("nozzle_diameter")
    if isinstance(raw, list) and raw:
        raw = raw[0]
    if raw is None:
        raw = settings.get("printer_variant")
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.4


def _default_line_widths(settings: dict[str, Any]) -> tuple[str, str]:
    nozzle = _first_nozzle_mm(settings)
    line_width = nozzle + 0.02
    initial_line_width = 0.25 if nozzle <= 0.25 else line_width
    return _format_mm(line_width), _format_mm(initial_line_width)


def apply_lumina_process_overlay(
    native_settings: dict[str, Any],
    *,
    slot_count: int = 8,
    source_profile_name: str | None = None,
) -> dict[str, Any]:
    """Apply Lumina's protected 3MF process settings over native profiles.

    Native slicer profiles identify machines and provide defaults. They must
    not replace Lumina's current printable process contract such as 0.08 mm
    layer height and fixed slot-array shapes.
    """
    merged = deepcopy(native_settings)
    merged.update(PROTECTED_LUMINA_PROCESS_SETTINGS)
    if not _has_meaningful_value(merged.get("printer_settings_id")):
        profile_name = source_profile_name or merged.get("printer_model")
        if _has_meaningful_value(profile_name):
            merged["printer_settings_id"] = str(profile_name)
    line_width, initial_line_width = _default_line_widths(merged)
    if not _has_meaningful_value(merged.get("line_width")):
        merged["line_width"] = line_width
    if not _has_meaningful_value(merged.get("initial_layer_line_width")):
        merged["initial_layer_line_width"] = initial_line_width
    merged["nozzle_temperature"] = ["220"] * slot_count
    merged["bed_temperature"] = ["60"] * slot_count
    merged["filament_type"] = ["PLA"] * slot_count
    return merged
