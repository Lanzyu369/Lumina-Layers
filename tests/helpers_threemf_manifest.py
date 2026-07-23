from __future__ import annotations

import json
import os
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import trimesh

from config import list_printer_profiles
from utils.bambu_3mf_writer import export_scene_with_bambu_metadata

_CORE_NS = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
_NS = {"m": _CORE_NS}

FULL_PALETTE_SLOT_NAMES = [
    "Slot 1 (White)",
    "Slot 2 (Black)",
    "Slot 3 (Green)",
    "Slot 4 (Blue)",
    "Slot 5 (Magenta)",
    "Slot 6 (Red)",
    "Slot 7 (Yellow)",
    "Slot 8 (Cyan)",
]
FULL_PALETTE_PREVIEW_COLORS = {
    0: (255, 255, 255, 255),
    1: (0, 0, 0, 255),
    2: (0, 174, 66, 255),
    3: (10, 41, 137, 255),
    4: (236, 0, 140, 255),
    5: (220, 20, 60, 255),
    6: (255, 230, 0, 255),
    7: (0, 134, 214, 255),
}
TEMPLATE_PROJECT_KEYS = (
    "printer_model",
    "printer_settings_id",
    "print_settings_id",
    "default_print_profile",
    "default_filament_profile",
    "inherits_group",
    "nozzle_diameter",
    "printer_variant",
    "printable_area",
    "printable_height",
    "initial_layer_line_width",
    "outer_wall_line_width",
    "inner_wall_line_width",
    "top_surface_line_width",
    "sparse_infill_line_width",
    "internal_solid_infill_line_width",
    "support_line_width",
    "line_width",
    "wall_generator",
)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def supported_printer_slicer_pairs() -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for profile in list_printer_profiles():
        slicers: list[str] = []
        if profile.template_file.startswith("bambu_"):
            slicers.append("BambuStudio")
        slicers.extend(profile.slicer_templates.keys())
        seen: set[str] = set()
        for slicer in slicers:
            if slicer in seen:
                continue
            seen.add(slicer)
            pairs.append((profile.id, slicer))
    return pairs


def load_expected_template_direct(
    *,
    printer_id: str,
    slicer: str,
    nozzle_size: str,
) -> dict[str, object]:
    from config import get_printer_profile

    profiles_dir = repo_root() / "printer_profiles"
    profile = get_printer_profile(printer_id)
    template_name = profile.get_template_file(slicer, nozzle_size=nozzle_size)
    template_path = profiles_dir / template_name
    if not template_path.exists():
        raise FileNotFoundError(f"Expected template missing: {template_path}")
    return json.loads(template_path.read_text(encoding="utf-8"))


def reserve_temp_3mf(prefix: str) -> Path:
    temp_dir = repo_root() / "output" / "temp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    fd, path = tempfile.mkstemp(prefix=prefix, suffix=".3mf", dir=temp_dir)
    os.close(fd)
    return Path(path)


def cleanup_paths(*paths: Path) -> None:
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def build_export_fixture(case_name: str) -> tuple[trimesh.Scene, list[str], dict[int, tuple[int, int, int, int]], list[str] | None]:
    scene = trimesh.Scene()
    if case_name == "full_palette":
        slot_names = FULL_PALETTE_SLOT_NAMES[:4]
        project_slot_names = None
    elif case_name == "sparse_palette":
        slot_names = [FULL_PALETTE_SLOT_NAMES[0], FULL_PALETTE_SLOT_NAMES[2]]
        project_slot_names = list(FULL_PALETTE_SLOT_NAMES)
    else:
        raise ValueError(f"Unknown fixture case: {case_name}")

    for index, slot_name in enumerate(slot_names):
        mesh = trimesh.creation.box(extents=[1, 1, 1])
        mesh.apply_translation([index * 2.0, 0.0, 0.0])
        mesh.metadata["bambu_material_name"] = slot_name
        scene.add_geometry(mesh, geom_name=slot_name)
    return scene, slot_names, dict(FULL_PALETTE_PREVIEW_COLORS), project_slot_names


def export_fixture_3mf(
    *,
    printer_id: str,
    slicer: str,
    nozzle_size: str,
    case_name: str,
) -> Path:
    scene, slot_names, preview_colors, project_slot_names = build_export_fixture(case_name)
    output_path = reserve_temp_3mf(f"{printer_id}_{slicer}_{nozzle_size}_{case_name}_")
    export_scene_with_bambu_metadata(
        scene=scene,
        output_path=str(output_path),
        slot_names=slot_names,
        preview_colors=preview_colors,
        settings={},
        color_mode="8-Color",
        printer_id=printer_id,
        slicer=slicer,
        nozzle_size=nozzle_size,
        project_slot_names=project_slot_names,
    )
    return output_path


def extract_manifest(path: Path) -> dict[str, object]:
    with zipfile.ZipFile(path, "r") as archive:
        names = sorted(archive.namelist())
        root_model = ET.fromstring(archive.read("3D/3dmodel.model"))
        root_metadata = {
            node.attrib["name"]: (node.text or "")
            for node in root_model.findall("m:metadata", _NS)
        }
        project_settings = json.loads(archive.read("Metadata/project_settings.config").decode("utf-8"))
        slice_info_root = ET.fromstring(archive.read("Metadata/slice_info.config"))
        slice_header = {
            node.attrib["key"]: node.attrib.get("value", "")
            for node in slice_info_root.findall("./header/header_item")
        }
        model_settings_root = ET.fromstring(archive.read("Metadata/model_settings.config"))
        plate_metadata = {
            node.attrib["key"]: node.attrib.get("value", "")
            for node in model_settings_root.findall("./plate/metadata")
        }
        part_extruders = {
            _metadata_value(part, "name"): _metadata_value(part, "extruder")
            for part in model_settings_root.findall("./object/part")
        }

    return {
        "entries": names,
        "root_metadata": root_metadata,
        "project_settings": project_settings,
        "slice_header": slice_header,
        "plate_metadata": plate_metadata,
        "part_extruders": part_extruders,
    }


def extract_project_subset(project_settings: dict[str, object]) -> dict[str, object]:
    return {
        key: project_settings.get(key)
        for key in TEMPLATE_PROJECT_KEYS
        if key in project_settings
    }


def expected_family_signature(printer_id: str, slicer: str, nozzle_size: str) -> dict[str, object]:
    if slicer == "BambuStudio":
        h2_family = {"bambu-h2c", "bambu-h2d", "bambu-h2d-pro", "bambu-h2s"}
        if nozzle_size == "0.2" and printer_id not in h2_family:
            client_version = "02.04.00.70"
        else:
            client_version = "02.05.00.66"
        return {
            "application": f"BambuStudio-{client_version}",
            "slice_header": {
                "X-BBL-Client-Type": "slicer",
                "X-BBL-Client-Version": client_version,
            },
            "requires_filament_sequence": True,
            "requires_cut_information": True,
            "requires_custom_gcode": False,
        }
    if slicer == "OrcaSlicer":
        return {
            "application": "BambuStudio-2.3.2-rc2",
            "slice_header": {
                "X-BBL-Client-Type": "slicer",
                "X-BBL-Client-Version": "",
            },
            "requires_filament_sequence": False,
            "requires_cut_information": False,
            "requires_custom_gcode": False,
        }
    if slicer == "SnapmakerOrca":
        return {
            "application": "SnapmakerOrca-02.02.49.02",
            "slice_header": {
                "X-BBL-Client-Type": "slicer",
                "X-BBL-Client-Version": "02.02.49.02",
            },
            "requires_filament_sequence": False,
            "requires_cut_information": False,
            "requires_custom_gcode": False,
        }
    if slicer == "ElegooSlicer":
        return {
            "application": "ElegooSlicer-1.3.2.9",
            "slice_header": {
                "X-BBL-Client-Type": "slicer",
                "X-BBL-Client-Version": "01.03.02.09",
                "X-BBL-Client-Name": "ElegooSlicer",
            },
            "requires_filament_sequence": False,
            "requires_cut_information": False,
            "requires_custom_gcode": False,
        }
    if slicer == "AnycubicSlicerNext":
        return {
            "application": "BambuStudio-1.3.9.4",
            "slice_header": {
                "X-ACNext-Client-Type": "slicer",
                "X-ACNext-Client-Version": "1.3.9.4 20260319225535",
            },
            "requires_filament_sequence": False,
            "requires_cut_information": False,
            "requires_custom_gcode": True,
        }
    if slicer == "FlashStudio":
        return {
            "application": "BambuStudio-2.3.2",
            "slice_header": {
                "X-BBL-Client-Type": "slicer",
                "X-BBL-Client-Version": "",
            },
            "requires_filament_sequence": False,
            "requires_cut_information": False,
            "requires_custom_gcode": False,
        }
    raise ValueError(f"Unsupported slicer family: {slicer}")


def manifest_sidecar_flags(entries: list[str]) -> dict[str, bool]:
    return {
        "has_filament_sequence": "Metadata/filament_sequence.json" in entries,
        "has_cut_information": "Metadata/cut_information.xml" in entries,
        "has_custom_gcode": "Metadata/custom_gcode_per_layer.xml" in entries,
    }


def sample_manifest(name: str) -> dict[str, object]:
    return extract_manifest(repo_root() / "元数据分析" / name)


def _metadata_value(node: ET.Element, key: str) -> str | None:
    for metadata_node in node.findall("metadata"):
        if metadata_node.get("key") == key:
            return metadata_node.get("value")
    return None
