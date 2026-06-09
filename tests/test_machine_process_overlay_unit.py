from __future__ import annotations

from core.machine_process_overlay import apply_lumina_process_overlay


def test_lumina_overlay_preserves_protected_process_fields():
    native = {
        "layer_height": "0.20",
        "initial_layer_height": "0.20",
        "wall_loops": "2",
        "top_shell_layers": "5",
        "sparse_infill_density": "15%",
        "printer_model": "Bambu Lab H2D",
        "printable_height": "325",
    }

    merged = apply_lumina_process_overlay(native)

    assert merged["printer_model"] == "Bambu Lab H2D"
    assert merged["printable_height"] == "325"
    assert merged["layer_height"] == "0.08"
    assert merged["initial_layer_height"] == "0.08"
    assert merged["wall_loops"] == "1"
    assert merged["top_shell_layers"] == "0"
    assert merged["sparse_infill_density"] == "100%"


def test_lumina_overlay_preserves_temperature_array_shape():
    native = {"nozzle_temperature": ["210"], "bed_temperature": ["55"], "filament_type": ["PETG"]}

    merged = apply_lumina_process_overlay(native, slot_count=8)

    assert merged["nozzle_temperature"] == ["220"] * 8
    assert merged["bed_temperature"] == ["60"] * 8
    assert merged["filament_type"] == ["PLA"] * 8


def test_lumina_overlay_fills_missing_profile_id_and_line_widths():
    native = {
        "printer_model": "Bambu Lab H2D",
        "printer_settings_id": "",
        "nozzle_diameter": ["0.4", "0.4"],
    }

    merged = apply_lumina_process_overlay(
        native,
        source_profile_name="Bambu Lab H2D 0.4 nozzle",
    )

    assert merged["printer_settings_id"] == "Bambu Lab H2D 0.4 nozzle"
    assert merged["line_width"] == "0.42"
    assert merged["initial_layer_line_width"] == "0.42"


def test_lumina_overlay_uses_safe_initial_line_width_for_0_2_nozzle():
    native = {
        "printer_settings_id": "",
        "nozzle_diameter": ["0.2"],
    }

    merged = apply_lumina_process_overlay(
        native,
        source_profile_name="Bambu Lab H2D 0.2 nozzle",
    )

    assert merged["line_width"] == "0.22"
    assert merged["initial_layer_line_width"] == "0.25"
