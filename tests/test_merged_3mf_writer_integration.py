"""Integration tests for MergedBambu3MFWriter — real writer, no mocks.

Validates the output 3MF is structurally correct for Bambu/Orca slicers:
- Per-item .model files have triangles > 0
- Top-level model has requiredextensions="p"
- Raw XML contains NO ns0:path (only p:path)
- Build items have printable="1"
- Component transforms from source are preserved in bbox calculation

LUM-20250519-001 Issue 2 regression tests.
"""

from __future__ import annotations

import json
import os
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import pytest
import trimesh

from config import TEMP_DIR
from utils.bambu_3mf_writer import export_scene_with_bambu_metadata
from utils.merged_bambu_3mf_writer import (
    MergedBambu3MFWriter,
    MergedItem,
    MaterialSlot,
)

_NS_CORE = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
_NS_PROD = "http://schemas.microsoft.com/3dmanufacturing/production/2015/06"


def _make_source_3mf(offset_x: float = 0.0, offset_y: float = 0.0) -> Path:
    """Create a minimal real Bambu 3MF with one slot."""
    os.makedirs(TEMP_DIR, exist_ok=True)
    scene = trimesh.Scene()
    box = trimesh.creation.box(extents=[10.0, 8.0, 2.0])
    box.apply_translation([offset_x + 5.0, offset_y + 4.0, 1.0])
    box.metadata["bambu_material_name"] = "Bambu PLA Black"
    scene.add_geometry(box, geom_name="Bambu PLA Black")

    fd, path = tempfile.mkstemp(suffix=".3mf", dir=TEMP_DIR, prefix="integ_src_")
    os.close(fd)
    export_scene_with_bambu_metadata(
        scene=scene,
        output_path=path,
        slot_names=["Bambu PLA Black"],
        preview_colors={"Bambu PLA Black": (16, 16, 16, 255)},
        settings={},
        color_mode="4-Color",
    )
    return Path(path)


class TestMergedWriterBambuCompatibility:
    """Real writer integration: output 3MF must be Bambu/Orca compatible."""

    def test_output_has_triangles_and_correct_structure(self) -> None:
        """Per-item .model files have triangles > 0, correct namespace prefixes."""
        src1 = _make_source_3mf(offset_x=0.0)
        src2 = _make_source_3mf(offset_x=15.0)

        items = [
            MergedItem(
                source_filename="a.png",
                source_3mf_path=src1,
                slots=(MaterialSlot(0, "Black", "#101010", "GFL00"),),
                tx_mm=0.0,
                ty_mm=0.0,
            ),
            MergedItem(
                source_filename="b.png",
                source_3mf_path=src2,
                slots=(MaterialSlot(0, "Black", "#101010", "GFL00"),),
                tx_mm=50.0,
                ty_mm=20.0,
            ),
        ]

        fd, out_path = tempfile.mkstemp(suffix=".3mf", dir=TEMP_DIR, prefix="integ_out_")
        os.close(fd)

        try:
            writer = MergedBambu3MFWriter()
            writer.write(items, Path(out_path), plate_width_mm=200.0, plate_depth_mm=200.0)

            with zipfile.ZipFile(out_path, "r") as zf:
                # 1. Top-level model has requiredextensions="p"
                main_xml = zf.read("3D/3dmodel.model").decode("utf-8")
                assert 'requiredextensions' in main_xml, (
                    "Missing requiredextensions attribute"
                )
                assert '"p"' in main_xml, "requiredextensions should be 'p'"

                # 2. No ns0:path in raw XML
                assert "ns0:path" not in main_xml, (
                    "Found ns0:path — namespace registration broken"
                )
                assert "ns0:" not in main_xml, (
                    "Found ns0: prefix — namespace registration broken"
                )

                # 3. Has p:path
                assert "p:path" in main_xml, "Missing p:path in components"

                # 4. Build items have printable="1"
                assert 'printable="1"' in main_xml, (
                    "Build items missing printable='1'"
                )

                # 5. Per-item models have triangles > 0
                for idx in range(2):
                    model_path = f"3D/Objects/object_{idx}.model"
                    assert model_path in zf.namelist(), (
                        f"Missing {model_path}"
                    )
                    model_bytes = zf.read(model_path)
                    model_root = ET.fromstring(model_bytes)
                    tri_count = 0
                    for obj in model_root.iter(f"{{{_NS_CORE}}}object"):
                        mesh = obj.find(f"{{{_NS_CORE}}}mesh")
                        if mesh is None:
                            continue
                        tris = mesh.find(f"{{{_NS_CORE}}}triangles")
                        if tris is not None:
                            tri_count += len(tris.findall(f"{{{_NS_CORE}}}triangle"))
                    assert tri_count > 0, (
                        f"{model_path} has 0 triangles — slicer will show empty"
                    )

                # 6. Bambu/Orca project metadata keeps the plate/object
                # binding that makes process/material presets visible.
                settings_root = ET.fromstring(zf.read("Metadata/model_settings.config"))
                plate = settings_root.find("plate")
                assert plate is not None, "model_settings.config missing <plate>"
                model_instances = plate.findall("model_instance")
                assert len(model_instances) == 2
                assert {
                    md.get("value")
                    for instance in model_instances
                    for md in instance.findall("metadata")
                    if md.get("key") == "object_id"
                } == {
                    obj.get("id")
                    for obj in settings_root.findall("object")
                }
        finally:
            for p in (src1, src2, Path(out_path)):
                try:
                    p.unlink(missing_ok=True)
                except OSError:
                    pass

    def test_component_transform_applied_to_bbox(self) -> None:
        """Source 3MF with non-identity component transform: world bbox min
        must equal placement after merge.

        This prevents regression of ignoring component transforms in bbox
        calculation.
        """
        # Create a source 3MF where the mesh is at local origin but the
        # component has a translation transform.
        src = _make_source_3mf(offset_x=20.0, offset_y=10.0)

        items = [
            MergedItem(
                source_filename="offset.png",
                source_3mf_path=src,
                slots=(MaterialSlot(0, "Black", "#101010", "GFL00"),),
                tx_mm=100.0,
                ty_mm=50.0,
            ),
        ]

        fd, out_path = tempfile.mkstemp(suffix=".3mf", dir=TEMP_DIR, prefix="integ_transform_")
        os.close(fd)

        try:
            writer = MergedBambu3MFWriter()
            writer.write(items, Path(out_path), plate_width_mm=300.0, plate_depth_mm=300.0)

            # Parse output and compute world bbox min.
            with zipfile.ZipFile(out_path, "r") as zf:
                main_root = ET.fromstring(zf.read("3D/3dmodel.model"))
                build = main_root.find(f"{{{_NS_CORE}}}build")
                build_items = build.findall(f"{{{_NS_CORE}}}item")
                assert len(build_items) == 1

                # Get build item transform.
                transform_str = build_items[0].get("transform")
                parts = transform_str.split()
                build_dx = float(parts[9])
                build_dy = float(parts[10])

                # Get per-item model vertices.
                resources = main_root.find(f"{{{_NS_CORE}}}resources")
                obj = resources.findall(f"{{{_NS_CORE}}}object")[0]
                components = obj.find(f"{{{_NS_CORE}}}components")
                comp = components.findall(f"{{{_NS_CORE}}}component")[0]
                per_item_path = comp.get(f"{{{_NS_PROD}}}path").lstrip("/")
                comp_transform_str = comp.get("transform", "1 0 0 0 1 0 0 0 1 0 0 0")
                comp_parts = comp_transform_str.split()
                comp_dx = float(comp_parts[9])
                comp_dy = float(comp_parts[10])

                mesh_id = comp.get("objectid")
                per_item_root = ET.fromstring(zf.read(per_item_path))
                per_item_resources = per_item_root.find(f"{{{_NS_CORE}}}resources")
                mesh_obj = None
                for o in per_item_resources.findall(f"{{{_NS_CORE}}}object"):
                    if o.get("id") == mesh_id:
                        mesh_obj = o
                        break
                assert mesh_obj is not None

                mesh = mesh_obj.find(f"{{{_NS_CORE}}}mesh")
                vertices = mesh.find(f"{{{_NS_CORE}}}vertices")
                min_x = float("inf")
                min_y = float("inf")
                for v in vertices.findall(f"{{{_NS_CORE}}}vertex"):
                    x = float(v.get("x"))
                    y = float(v.get("y"))
                    if x < min_x:
                        min_x = x
                    if y < min_y:
                        min_y = y

                # World bbox min = local vertex min + component transform + build transform
                world_min_x = min_x + comp_dx + build_dx
                world_min_y = min_y + comp_dy + build_dy

                assert abs(world_min_x - 100.0) < 1e-3, (
                    f"World min_x={world_min_x:.4f} != target tx_mm=100.0"
                )
                assert abs(world_min_y - 50.0) < 1e-3, (
                    f"World min_y={world_min_y:.4f} != target ty_mm=50.0"
                )
        finally:
            for p in (src, Path(out_path)):
                try:
                    p.unlink(missing_ok=True)
                except OSError:
                    pass

    def test_project_process_and_filament_presets_are_preserved(self) -> None:
        """Merged 3MF keeps source project process/device/filament presets."""
        os.makedirs(TEMP_DIR, exist_ok=True)
        scene = trimesh.Scene()
        box = trimesh.creation.box(extents=[10.0, 8.0, 2.0])
        box.apply_translation([5.0, 4.0, 1.0])
        box.metadata["bambu_material_name"] = "Bambu PLA Black"
        scene.add_geometry(box, geom_name="Bambu PLA Black")

        fd, src_path = tempfile.mkstemp(
            suffix=".3mf",
            dir=TEMP_DIR,
            prefix="integ_preset_src_",
        )
        os.close(fd)
        export_scene_with_bambu_metadata(
            scene=scene,
            output_path=src_path,
            slot_names=["Bambu PLA Black"],
            preview_colors={"Bambu PLA Black": (16, 16, 16, 255)},
            settings={},
            color_mode="4-Color",
            printer_id="bambu-p1s",
            slicer="OrcaSlicer",
            nozzle_size="0.2",
            enable_base_layer_height_modifier=False,
        )

        items = [
            MergedItem(
                source_filename="preset-a.png",
                source_3mf_path=Path(src_path),
                slots=(MaterialSlot(0, "Bambu PLA Black", "#101010", "GFL00"),),
                tx_mm=10.0,
                ty_mm=20.0,
            ),
            MergedItem(
                source_filename="preset-b.png",
                source_3mf_path=Path(src_path),
                slots=(MaterialSlot(0, "Bambu PLA Black", "#101010", "GFL00"),),
                tx_mm=40.0,
                ty_mm=20.0,
            ),
        ]

        fd, out_path = tempfile.mkstemp(
            suffix=".3mf",
            dir=TEMP_DIR,
            prefix="integ_preset_merged_",
        )
        os.close(fd)

        try:
            writer = MergedBambu3MFWriter()
            writer.write(items, Path(out_path), plate_width_mm=200.0, plate_depth_mm=200.0)

            with (
                zipfile.ZipFile(src_path, "r") as src_zip,
                zipfile.ZipFile(out_path, "r") as out_zip,
            ):
                src_project = json.loads(
                    src_zip.read("Metadata/project_settings.config").decode("utf-8")
                )
                merged_project = json.loads(
                    out_zip.read("Metadata/project_settings.config").decode("utf-8")
                )
                for key in (
                    "print_settings_id",
                    "printer_model",
                    "printer_settings_id",
                    "default_print_profile",
                    "filament_settings_id",
                    "nozzle_diameter",
                ):
                    assert merged_project.get(key) == src_project.get(key)
        finally:
            for p in (Path(src_path), Path(out_path)):
                try:
                    p.unlink(missing_ok=True)
                except OSError:
                    pass
