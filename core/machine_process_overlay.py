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


def apply_lumina_process_overlay(
    native_settings: dict[str, Any],
    *,
    slot_count: int = 8,
) -> dict[str, Any]:
    """Apply Lumina's protected 3MF process settings over native profiles.

    Native slicer profiles identify machines and provide defaults. They must
    not replace Lumina's current printable process contract such as 0.08 mm
    layer height and fixed slot-array shapes.
    """
    merged = deepcopy(native_settings)
    merged.update(PROTECTED_LUMINA_PROCESS_SETTINGS)
    merged["nozzle_temperature"] = ["220"] * slot_count
    merged["bed_temperature"] = ["60"] * slot_count
    merged["filament_type"] = ["PLA"] * slot_count
    return merged
