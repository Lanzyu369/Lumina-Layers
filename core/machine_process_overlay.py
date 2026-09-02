from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

from config import format_native_nozzle_size, list_printer_profiles


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
    "print_speed": "100",
    "travel_speed": "150",
    "enable_support": "0",
    "brim_width": "5",
    "brim_type": "auto_brim",
}

_PROTECTED_LINE_WIDTH_KEYS: tuple[str, ...] = (
    "line_width",
    "inner_wall_line_width",
    "outer_wall_line_width",
    "top_surface_line_width",
    "sparse_infill_line_width",
    "internal_solid_infill_line_width",
    "support_line_width",
)

_PROTECTED_DIFFERENCE_KEYS: tuple[str, ...] = (
    *PROTECTED_LUMINA_PROCESS_SETTINGS.keys(),
    *_PROTECTED_LINE_WIDTH_KEYS,
    "initial_layer_line_width",
    "printer_settings_id",
    "nozzle_temperature",
    "nozzle_temperature_initial_layer",
    "bed_temperature",
    "bed_temperature_initial_layer",
    "textured_plate_temp",
    "textured_plate_temp_initial_layer",
    "hot_plate_temp",
    "hot_plate_temp_initial_layer",
    "eng_plate_temp",
    "eng_plate_temp_initial_layer",
    "cool_plate_temp",
    "cool_plate_temp_initial_layer",
    "filament_type",
)


def _has_meaningful_value(value: Any) -> bool:
    return value is not None and str(value).strip() not in {"", "null", "None"}


def _format_mm(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _first_nozzle_mm(settings: dict[str, Any]) -> float:
    raw = settings.get("nozzle_diameter")
    if isinstance(raw, list) and raw:
        raw = raw[0]
    normalized = format_native_nozzle_size(raw)
    if normalized is None:
        normalized = format_native_nozzle_size(settings.get("printer_variant"))
    return float(normalized or "0.4")


def _normalized_nozzle_size_from_settings(settings: dict[str, Any]) -> str:
    raw = settings.get("nozzle_diameter")
    if isinstance(raw, list) and raw:
        raw = raw[0]
    return (
        format_native_nozzle_size(raw)
        or format_native_nozzle_size(settings.get("printer_variant"))
        or "0.4"
    )


def _default_line_widths(settings: dict[str, Any]) -> tuple[str, str]:
    nozzle = _first_nozzle_mm(settings)
    line_width = nozzle + 0.02
    initial_line_width = 0.25 if nozzle <= 0.25 else line_width
    return _format_mm(line_width), _format_mm(initial_line_width)


def _match_lumina_printer_id(settings: dict[str, Any], source_profile_name: str | None) -> str | None:
    model = str(settings.get("printer_model") or "").strip().casefold()
    source = str(source_profile_name or "").strip().casefold()
    for profile in list_printer_profiles():
        display_name = profile.display_name.casefold()
        if model == display_name or source.startswith(display_name):
            return profile.id
    return None


def _load_lumina_line_width_contract(
    settings: dict[str, Any],
    *,
    slicer_id: str | None,
    source_profile_name: str | None,
) -> dict[str, str]:
    if not slicer_id:
        return {}
    printer_id = _match_lumina_printer_id(settings, source_profile_name)
    if not printer_id:
        return {}
    try:
        profile = next(item for item in list_printer_profiles() if item.id == printer_id)
        template_name = profile.get_template_file(
            slicer_id,
            nozzle_size=_normalized_nozzle_size_from_settings(settings),
        )
        template_path = Path(__file__).resolve().parents[1] / "printer_profiles" / template_name
        template = json.loads(template_path.read_text(encoding="utf-8"))
    except (StopIteration, OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return {}
    keys = (*_PROTECTED_LINE_WIDTH_KEYS, "initial_layer_line_width")
    return {key: str(template[key]) for key in keys if key in template}


def _merge_difference_index(value: Any) -> list[str]:
    existing: list[str] = []
    if isinstance(value, list):
        raw_items = value
    elif _has_meaningful_value(value):
        raw_items = [value]
    else:
        raw_items = []
    for raw_item in raw_items:
        for token in str(raw_item).split(";"):
            normalized = token.strip()
            if normalized:
                existing.append(normalized)
    merged = sorted({*existing, *_PROTECTED_DIFFERENCE_KEYS})
    return [";".join(merged)] if merged else []


def apply_lumina_process_overlay(
    native_settings: dict[str, Any],
    *,
    slot_count: int = 8,
    source_profile_name: str | None = None,
    slicer_id: str | None = None,
) -> dict[str, Any]:
    """Apply Lumina's protected 3MF process settings over native profiles.

    Native slicer profiles identify machines and provide defaults. They must
    not replace Lumina's current printable process contract such as 0.08 mm
    layer height and fixed slot-array shapes.
    """
    merged = deepcopy(native_settings)
    merged.update(PROTECTED_LUMINA_PROCESS_SETTINGS)
    # Orca 2.4's precise-wall correction can delete a large printable region
    # when Arachne is used with Lumina's intentional one-wall artwork process.
    # Bambu Studio already ships the equivalent profile with this disabled.
    orca_precise_wall_override = slicer_id == "OrcaSlicer"
    if orca_precise_wall_override:
        merged["precise_outer_wall"] = "0"
    profile_name = source_profile_name or merged.get("printer_model")
    if _has_meaningful_value(profile_name):
        merged["printer_settings_id"] = str(profile_name)
    line_width, initial_line_width = _default_line_widths(merged)
    template_line_widths = _load_lumina_line_width_contract(
        merged,
        slicer_id=slicer_id,
        source_profile_name=source_profile_name,
    )
    for key in _PROTECTED_LINE_WIDTH_KEYS:
        merged[key] = template_line_widths.get(key, line_width)
    merged["initial_layer_line_width"] = template_line_widths.get(
        "initial_layer_line_width",
        initial_line_width,
    )
    merged["nozzle_temperature"] = ["220"] * slot_count
    merged["nozzle_temperature_initial_layer"] = ["220"] * slot_count
    merged["bed_temperature"] = ["60"] * slot_count
    merged["bed_temperature_initial_layer"] = ["60"] * slot_count
    for key in (
        "textured_plate_temp",
        "textured_plate_temp_initial_layer",
        "hot_plate_temp",
        "hot_plate_temp_initial_layer",
        "eng_plate_temp",
        "eng_plate_temp_initial_layer",
    ):
        merged[key] = ["60"] * slot_count
    merged["cool_plate_temp"] = ["0"] * slot_count
    merged["cool_plate_temp_initial_layer"] = ["0"] * slot_count
    merged["filament_type"] = ["PLA"] * slot_count
    merged["different_settings_to_system"] = _merge_difference_index(
        merged.get("different_settings_to_system")
    )
    if orca_precise_wall_override:
        merged["different_settings_to_system"] = _merge_difference_index(
            [
                *merged["different_settings_to_system"],
                "precise_outer_wall",
            ]
        )
    return merged
