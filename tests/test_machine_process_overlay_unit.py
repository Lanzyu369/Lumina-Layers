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
