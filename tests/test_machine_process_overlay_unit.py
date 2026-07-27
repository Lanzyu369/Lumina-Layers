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


def test_lumina_overlay_preserves_native_quarter_nozzle_width():
    native = {
        "printer_model": "Flashforge AD5X",
        "printer_settings_id": "",
        "nozzle_diameter": ["0.25"],
    }

    merged = apply_lumina_process_overlay(
        native,
        source_profile_name="Flashforge AD5X 0.25 nozzle",
        slicer_id="FlashStudio",
    )

    assert merged["line_width"] == "0.27"
    assert merged["initial_layer_line_width"] == "0.25"


def test_lumina_overlay_overrides_native_profile_process_conflicts():
    native = {
        "printer_settings_id": "Native Wrong P1S Profile",
        "nozzle_diameter": ["0.2"],
        "line_width": "0.8",
        "initial_layer_line_width": "0.8",
        "nozzle_temperature": ["255"],
        "nozzle_temperature_initial_layer": ["245"],
        "bed_temperature": ["80"],
        "bed_temperature_initial_layer": ["90"],
        "textured_plate_temp": ["90"],
        "textured_plate_temp_initial_layer": ["95"],
        "hot_plate_temp": ["90"],
        "hot_plate_temp_initial_layer": ["95"],
        "eng_plate_temp": ["90"],
        "eng_plate_temp_initial_layer": ["95"],
        "cool_plate_temp": ["35"],
        "cool_plate_temp_initial_layer": ["40"],
        "filament_type": ["PETG"],
    }

    merged = apply_lumina_process_overlay(
        native,
        slot_count=3,
        source_profile_name="Bambu Lab P1S 0.2 nozzle",
    )

    assert merged["printer_settings_id"] == "Bambu Lab P1S 0.2 nozzle"
    assert merged["line_width"] == "0.22"
    assert merged["initial_layer_line_width"] == "0.25"
    assert merged["nozzle_temperature"] == ["220"] * 3
    assert merged["nozzle_temperature_initial_layer"] == ["220"] * 3
    assert merged["bed_temperature"] == ["60"] * 3
    assert merged["bed_temperature_initial_layer"] == ["60"] * 3
    assert merged["textured_plate_temp"] == ["60"] * 3
    assert merged["textured_plate_temp_initial_layer"] == ["60"] * 3
    assert merged["hot_plate_temp"] == ["60"] * 3
    assert merged["hot_plate_temp_initial_layer"] == ["60"] * 3
    assert merged["eng_plate_temp"] == ["60"] * 3
    assert merged["eng_plate_temp_initial_layer"] == ["60"] * 3
    assert merged["cool_plate_temp"] == ["0"] * 3
    assert merged["cool_plate_temp_initial_layer"] == ["0"] * 3
    assert merged["filament_type"] == ["PLA"] * 3


def test_lumina_overlay_overrides_derived_line_widths_and_difference_index():
    native = {
        "printer_settings_id": "Native Wrong Profile",
        "nozzle_diameter": ["0.4"],
        "initial_layer_print_height": "0.28",
        "line_width": "0.8",
        "initial_layer_line_width": "0.8",
        "inner_wall_line_width": "0.8",
        "outer_wall_line_width": "0.8",
        "top_surface_line_width": "0.8",
        "sparse_infill_line_width": "0.8",
        "internal_solid_infill_line_width": "0.8",
        "support_line_width": "0.8",
        "different_settings_to_system": ["line_width"],
    }

    merged = apply_lumina_process_overlay(
        native,
        source_profile_name="Bambu Lab H2D 0.4 nozzle",
    )

    assert merged["initial_layer_print_height"] == "0.08"
    assert merged["line_width"] == "0.42"
    assert merged["initial_layer_line_width"] == "0.42"
    assert merged["inner_wall_line_width"] == "0.42"
    assert merged["outer_wall_line_width"] == "0.42"
    assert merged["top_surface_line_width"] == "0.42"
    assert merged["sparse_infill_line_width"] == "0.42"
    assert merged["internal_solid_infill_line_width"] == "0.42"
    assert merged["support_line_width"] == "0.42"
    different_settings = merged["different_settings_to_system"]
    assert isinstance(different_settings, list)
    assert len(different_settings) == 1
    difference_index = set(different_settings[0].split(";"))
    assert difference_index >= {
        "initial_layer_print_height",
        "line_width",
        "initial_layer_line_width",
        "inner_wall_line_width",
        "outer_wall_line_width",
        "top_surface_line_width",
        "sparse_infill_line_width",
        "internal_solid_infill_line_width",
        "support_line_width",
    }


def test_lumina_overlay_normalizes_difference_index_to_single_semicolon_string():
    native = {
        "printer_settings_id": "Native Wrong Profile",
        "nozzle_diameter": ["0.4"],
        "different_settings_to_system": [
            "line_width;wall_loops",
            "top_shell_layers",
            "",
        ],
    }

    merged = apply_lumina_process_overlay(
        native,
        source_profile_name="Bambu Lab H2D 0.4 nozzle",
    )

    different_settings = merged["different_settings_to_system"]
    assert isinstance(different_settings, list)
    assert different_settings == [different_settings[0]]
    difference_index = different_settings[0].split(";")
    assert difference_index == sorted(set(difference_index))
    assert {"line_width", "wall_loops", "top_shell_layers"} <= set(difference_index)
    assert all(";" not in item for item in different_settings[1:])


def test_lumina_overlay_prefers_existing_lumina_template_line_width_contract():
    native = {
        "printer_model": "Bambu Lab P1S",
        "printer_settings_id": "Native Wrong P1S Profile",
        "nozzle_diameter": ["0.4"],
        "line_width": "0.8",
        "inner_wall_line_width": "0.8",
        "sparse_infill_line_width": "0.8",
        "internal_solid_infill_line_width": "0.8",
    }

    merged = apply_lumina_process_overlay(
        native,
        source_profile_name="Bambu Lab P1S 0.4 nozzle",
        slicer_id="BambuStudio",
    )

    assert merged["line_width"] == "0.42"
    assert merged["inner_wall_line_width"] == "0.45"
    assert merged["sparse_infill_line_width"] == "0.45"
    assert merged["internal_solid_infill_line_width"] == "0.42"
