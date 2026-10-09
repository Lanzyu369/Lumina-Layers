from __future__ import annotations

import json
import os
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import trimesh

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


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


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


def _metadata_value(node: ET.Element, key: str) -> str | None:
    for metadata_node in node.findall("metadata"):
        if metadata_node.get("key") == key:
            return metadata_node.get("value")
    return None
