"""Shared compact writer cases for the Fat Cat integration checks."""

from copy import deepcopy
from pathlib import Path

import trimesh

from fatcat_native_source_fixtures import complete_native_project
import utils.bambu_3mf_writer as writer_module


CASES = ("bambu-p1s-02-mixed2", "orca-p1s-06-mixed2", "orca-p1s-06-distinct2", "bambu-a1mini-04-expanded10")


def make_writer(output: Path, case: str):
    """Create a reproducible writer case and its exact source-field overrides.

    构造可复查的真实 writer 样例，并返回明确的模板覆盖；不冒称正常转换。
    """
    if case == "bambu-p1s-02-mixed2":
        slicer, machine, nozzle = "BambuStudio", "p1s", "0.2"
        names = ["White", "PETG Black"]
    elif case in {"orca-p1s-06-distinct2", "orca-p1s-06-mixed2"}:
        slicer, machine, nozzle = "OrcaSlicer", "p1s", "0.6"
        names = ["Red", "PETG Blue" if case.endswith("mixed2") else "Blue"]
    elif case == "bambu-a1mini-04-expanded10":
        slicer, machine, nozzle = "BambuStudio", "a1-mini", "0.4"
        names = [f"Material {index + 1}" for index in range(10)]
    else:
        raise ValueError(f"Unknown evidence case: {case}")
    colours = [(230 - index * 17, 30 + index * 11, 40 + index * 19) for index in range(len(names))]
    writer = writer_module.BambuStudio3MFWriter(
        str(output), printer_id=f"bambu-{machine}", slicer=slicer, nozzle_size=nozzle,
        device_profile_id=f"{slicer}:bbl:bambu-lab-{machine}:{nozzle}",
        build_plate_id="textured-pei-plate", preserve_template_filament_slots=False,
        material_types={name: ("PETG" if name.startswith("PETG") else "PLA") for name in names},
        settings={"layer_height": "0.12", "initial_layer_print_height": "0.20"},
        enable_base_layer_height_modifier=True, enable_wipe_tower_auto_placement=True,
        base_height_mm=0.8, color_height_mm=0.4, face_orientation="down", watermark="",
    )
    writer._set_project_palette(names, dict(zip(names, colours)))
    for index, (name, colour) in enumerate(zip(names, colours)):
        mesh = trimesh.creation.box(extents=(4.0, 4.0, 1.2))
        mesh.apply_translation((index * 4.0, 0.0, 0.6))
        writer.add_mesh(mesh, name, colour)
    source = writer._get_base_config_template()
    overrides = {}
    if case == "orca-p1s-06-distinct2":
        source = complete_native_project(writer, ["PLA", "PLA"], colours=colours)
        overrides = {
            "filament_flow_ratio": ["0.91", "0.95", "0.93", "0.97"],
            "filament_retraction_length": ["0.60", "0.65", "0.70", "0.75"],
            "nozzle_temperature": ["218", "228", "219", "229"],
            "nozzle_temperature_initial_layer": ["220", "230", "221", "231"],
        }
        differences = deepcopy(source["different_settings_to_system"])
        for slot in range(2):
            differences[slot + 1] = ";".join(sorted(overrides))
        overrides["different_settings_to_system"] = differences
        source.update(deepcopy(overrides))
        writer._custom_template = deepcopy(source)
    return writer, source, overrides
