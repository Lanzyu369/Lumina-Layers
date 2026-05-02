"""Unit tests for slicer-specific 3MF metadata generation."""

import json
import zipfile
import xml.etree.ElementTree as ET
from types import SimpleNamespace

import trimesh

from utils import bambu_3mf_writer as writer_module
from utils.bambu_3mf_writer import BambuStudio3MFWriter, load_printer_template


class _FakeCustomPart:
    def __init__(self, path: str, content_type: str, data: bytes):
        self.path = path
        self.content_type = content_type
        self.data = data


class _FakeContentType:
    def __init__(self, extension: str, content_type: str):
        self.extension = extension
        self.content_type = content_type


class _FakeBuilder:
    def __init__(self) -> None:
        self.parts: list[_FakeCustomPart] = []
        self.content_types: list[_FakeContentType] = []

    def add_custom_part(self, part: _FakeCustomPart) -> None:
        self.parts.append(part)

    def add_custom_content_type(self, content_type: _FakeContentType) -> None:
        self.content_types.append(content_type)


def _metadata_values(parent: ET.Element) -> dict[str, str]:
    return {child.attrib["key"]: child.attrib["value"] for child in parent.findall("metadata")}


def _make_anycubic_writer(tmp_path) -> BambuStudio3MFWriter:
    writer = BambuStudio3MFWriter(
        str(tmp_path / "anycubic-test.3mf"),
        settings={},
        color_mode="4-Color",
        printer_id="anycubic-kobra-s1",
        slicer="AnycubicSlicerNext",
    )

    white = trimesh.creation.box(extents=[2, 4, 6])
    white.apply_translation([1, 2, 3])
    writer.add_mesh(white, "White", (255, 0, 0))

    green = trimesh.creation.box(extents=[1, 1, 1])
    green.apply_translation([2, 2, 0.5])
    writer.add_mesh(green, "Green", (0, 255, 0))
    return writer


class TestAnycubicWriterMetadata:
    def test_writer_base_template_uses_selected_nozzle_size_variant(self) -> None:
        writer = BambuStudio3MFWriter(
            "selected-nozzle.3mf",
            settings={},
            color_mode="4-Color",
            printer_id="bambu-p1s",
            slicer="BambuStudio",
            nozzle_size="0.2",
        )

        settings = writer._get_base_config_template()
        assert settings["nozzle_diameter"] == ["0.2"]
        assert settings["printer_settings_id"] == "Bambu Lab P1S 0.2 nozzle"

    def test_shared_material_palette_deduplicates_project_filaments(self) -> None:
        writer = BambuStudio3MFWriter(
            "shared-materials.3mf",
            settings={},
            color_mode="8-Color",
            printer_id="bambu-h2d",
            slicer="BambuStudio",
        )

        first = trimesh.creation.box(extents=[1, 1, 1])
        first.metadata["bambu_material_name"] = "Slot 1 (White)"
        writer.add_mesh(first, "A1__Slot 1 (White)", (255, 255, 255))

        second = trimesh.creation.box(extents=[1, 1, 1])
        second.apply_translation([2, 0, 0])
        second.metadata["bambu_material_name"] = "Slot 1 (White)"
        writer.add_mesh(second, "A2__Slot 1 (White)", (255, 255, 255))

        third = trimesh.creation.box(extents=[1, 1, 1])
        third.apply_translation([4, 0, 0])
        third.metadata["bambu_material_name"] = "Slot 2 (Black)"
        writer.add_mesh(third, "A1__Slot 2 (Black)", (0, 0, 0))

        settings = json.loads(writer._build_project_settings_bytes().decode("utf-8"))
        assert settings["filament_colour"] == ["#FFFFFF", "#000000"]

        root = ET.fromstring(writer._build_model_settings_bytes([1, 2, 3], 4, [0, 0, 1]))
        part_extruders = [
            _metadata_values(part)["extruder"]
            for part in root.findall("./object/part")
        ]
        assert part_extruders == ["1", "1", "2"]

    def test_bambu_project_settings_copy_petg_template_row_for_petg_materials(self) -> None:
        writer = BambuStudio3MFWriter(
            "petg-materials.3mf",
            settings={},
            color_mode="4-Color",
            printer_id="bambu-p1s",
            slicer="BambuStudio",
            nozzle_size="0.2",
        )
        writer._set_project_palette(
            ["爱丽兹 PETG Basic 青色", "PLA Basic White"],
            {
                0: (0, 122, 214, 255),
                1: (255, 255, 255, 255),
            },
        )

        settings = json.loads(writer._build_project_settings_bytes().decode("utf-8"))

        assert settings["filament_type"] == ["PETG", "PLA"]
        assert settings["filament_settings_id"] == [
            "Bambu PETG Basic @BBL X1C 0.2 nozzle",
            "Bambu PLA Basic @BBL X1C 0.2 nozzle",
        ]
        assert settings["nozzle_temperature"] == ["255", "220"]
        assert settings["nozzle_temperature_initial_layer"] == ["245", "220"]
        assert settings["textured_plate_temp"] == ["70", "55"]
        assert settings["cool_plate_temp"] == ["0", "35"]

    def test_orca_project_settings_derive_petg_metadata_when_template_is_pla_only(self) -> None:
        writer = BambuStudio3MFWriter(
            "orca-petg-materials.3mf",
            settings={},
            color_mode="4-Color",
            printer_id="bambu-p1s",
            slicer="OrcaSlicer",
            nozzle_size="0.2",
        )
        writer._set_project_palette(
            ["PETG HF Red", "PLA Basic White"],
            {
                0: (220, 20, 60, 255),
                1: (255, 255, 255, 255),
            },
        )

        settings = json.loads(writer._build_project_settings_bytes().decode("utf-8"))

        assert settings["filament_type"] == ["PETG", "PLA"]
        assert settings["filament_settings_id"] == [
            "Bambu PETG HF @BBL X1C",
            "Bambu PLA Basic @BBL X1C",
        ]
        assert settings["nozzle_temperature"] == ["255", "220"]
        assert settings["nozzle_temperature_initial_layer"] == ["245", "220"]
        assert settings["textured_plate_temp"] == ["70", "55"]

    def test_anycubic_model_settings_match_sample_shape(self, tmp_path) -> None:
        writer = _make_anycubic_writer(tmp_path)

        root = ET.fromstring(writer._build_model_settings_bytes([1, 2], 3))
        first_part = root.find("./object/part")
        assert first_part is not None

        part_meta = _metadata_values(first_part)
        assert part_meta["source_file"] == "anycubic-test.3mf"
        assert part_meta["source_object_id"] == "0"
        assert part_meta["source_volume_id"] == "0"
        assert part_meta["source_offset_x"] == "1"
        assert part_meta["source_offset_y"] == "2"
        assert part_meta["source_offset_z"] == "3"
        assert part_meta["extruder"] == "1"
        assert part_meta["matrix"] == "1 0 0 2 0 1 0 4 0 0 1 6 0 0 0 1"

        plate = root.find("./plate")
        assert plate is not None
        plate_meta = _metadata_values(plate)
        assert "filament_map_mode" not in plate_meta
        assert plate_meta["thumbnail_file"] == "Metadata/plate_1.png"
        assert plate_meta["thumbnail_no_light_file"] == "Metadata/plate_no_light_1.png"
        assert plate_meta["top_file"] == "Metadata/top_1.png"
        assert plate_meta["pick_file"] == "Metadata/pick_1.png"

        model_instance = plate.find("./model_instance")
        assert model_instance is not None
        instance_meta = _metadata_values(model_instance)
        assert instance_meta["identify_id"] == "160"

    def test_anycubic_project_settings_preserve_template_filament_metadata(self, tmp_path) -> None:
        writer = _make_anycubic_writer(tmp_path)
        settings = json.loads(writer._build_project_settings_bytes().decode("utf-8"))
        template = load_printer_template("anycubic-kobra-s1", slicer="AnycubicSlicerNext")

        expected_vendor = template["filament_vendor"][0]
        expected_filament_id = template["filament_ids"][0]
        expected_settings_id = template["filament_settings_id"][0]

        assert settings["filament_vendor"] == [expected_vendor, expected_vendor]
        assert settings["filament_ids"] == [expected_filament_id, expected_filament_id]
        assert settings["filament_settings_id"] == [expected_settings_id, expected_settings_id]
        assert settings["filament_colour"] == ["#FF0000", "#00FF00"]
        assert all(value != "Bambu Lab" for value in settings["filament_vendor"])
        assert all(value != "GFA00" for value in settings["filament_ids"])

    def test_export_scene_uses_global_slot_number_for_sparse_slots(self, monkeypatch) -> None:
        captured_colors: list[tuple[str, tuple[int, int, int]]] = []

        class _FakeWriter:
            def __init__(
                self,
                output_path: str,
                settings=None,
                color_mode: str = "4-Color",
                printer_id: str = "bambu-h2d",
                slicer: str = "BambuStudio",
                nozzle_size: str | None = None,
                watermark: str = "LuminaStudio",
            ) -> None:
                self.output_path = output_path

            def add_mesh(self, mesh, name: str, color_rgb: tuple[int, int, int]) -> None:
                captured_colors.append((name, color_rgb))

            def export(self) -> str:
                return self.output_path

        monkeypatch.setattr(writer_module, "BambuStudio3MFWriter", _FakeWriter)

        scene = trimesh.Scene()
        scene.add_geometry(trimesh.creation.box(extents=[1, 1, 1]), geom_name="Slot 1 (White)")
        shifted = trimesh.creation.box(extents=[1, 1, 1])
        shifted.apply_translation([2, 0, 0])
        scene.add_geometry(shifted, geom_name="Slot 3 (Green)")

        out_path = writer_module.export_scene_with_bambu_metadata(
            scene=scene,
            output_path="sparse-slots.3mf",
            slot_names=["Slot 1 (White)", "Slot 3 (Green)"],
            preview_colors={
                0: (255, 255, 255, 255),
                1: (0, 0, 0, 255),
                2: (0, 174, 66, 255),
            },
            settings={},
            color_mode="8-Color",
            printer_id="bambu-h2d",
            slicer="BambuStudio",
        )

        assert out_path == "sparse-slots.3mf"
        assert captured_colors == [
            ("Slot 1 (White)", (255, 255, 255)),
            ("Slot 3 (Green)", (0, 174, 66)),
        ]

    def test_export_scene_uses_full_palette_order_for_sparse_native_plain_names(self, monkeypatch) -> None:
        captured_colors: list[tuple[str, tuple[int, int, int]]] = []
        captured_object_names: list[str] = []
        captured_settings: dict[str, object] = {}
        captured_color_mode: dict[str, str] = {}

        class _CapturingWriter(writer_module.BambuStudio3MFWriter):
            def __init__(
                self,
                output_path: str,
                settings=None,
                color_mode: str = "4-Color",
                printer_id: str = "bambu-h2d",
                slicer: str = "BambuStudio",
                nozzle_size: str | None = None,
                watermark: str = "LuminaStudio",
            ) -> None:
                captured_color_mode["value"] = color_mode
                super().__init__(output_path, settings, color_mode, printer_id, slicer, nozzle_size, watermark)

            def add_mesh(self, mesh, name: str, color_rgb: tuple[int, int, int]) -> None:
                captured_colors.append((name, color_rgb))
                super().add_mesh(mesh, name, color_rgb)

            def export(self) -> str:
                captured_object_names.extend(entry.object_name for entry in self.objects)
                captured_settings.update(json.loads(self._build_project_settings_bytes().decode("utf-8")))
                return self.output_path

        monkeypatch.setattr(writer_module, "BambuStudio3MFWriter", _CapturingWriter)

        scene = trimesh.Scene()
        for offset, name in enumerate(("yellow", "red", "white", "bambugreen")):
            mesh = trimesh.creation.box(extents=[1, 1, 1])
            mesh.apply_translation([offset * 2, 0, 0])
            scene.add_geometry(mesh, geom_name=name)

        full_palette = [
            "bambugreen",
            "black",
            "blue",
            "cyan",
            "magenta",
            "red",
            "white",
            "yellow",
        ]
        preview_colors = {
            0: (0, 174, 66, 255),
            1: (0, 0, 0, 255),
            2: (10, 41, 137, 255),
            3: (0, 255, 255, 255),
            4: (255, 0, 255, 255),
            5: (220, 20, 60, 255),
            6: (255, 255, 255, 255),
            7: (255, 230, 0, 255),
        }

        out_path = writer_module.export_scene_with_bambu_metadata(
            scene=scene,
            output_path="native-sparse.3mf",
            slot_names=["yellow", "red", "white", "bambugreen"],
            preview_colors=preview_colors,
            settings={},
            color_mode="8-Color",
            printer_id="bambu-h2d",
            slicer="BambuStudio",
            project_slot_names=full_palette,
        )

        assert out_path == "native-sparse.3mf"
        assert captured_color_mode["value"] == "8-Color"
        assert captured_object_names == ["yellow", "red", "white", "bambugreen"]
        assert captured_colors == [
            ("yellow", (255, 230, 0)),
            ("red", (220, 20, 60)),
            ("white", (255, 255, 255)),
            ("bambugreen", (0, 174, 66)),
        ]
        assert captured_settings["filament_colour"] == [
            "#00AE42",
            "#000000",
            "#0A2989",
            "#00FFFF",
            "#FF00FF",
            "#DC143C",
            "#FFFFFF",
            "#FFE600",
        ]
        assert len(captured_settings["filament_ids"]) == 8

    def test_anycubic_slice_info_and_custom_parts_use_acnext_layout(
        self,
        tmp_path,
        monkeypatch,
    ) -> None:
        writer = _make_anycubic_writer(tmp_path)
        slice_info = ET.fromstring(writer._build_slice_info_bytes())
        header = slice_info.find("./header")
        assert header is not None
        header_items = {item.attrib["key"]: item.attrib["value"] for item in header.findall("header_item")}

        assert header_items == {
            "X-ACNext-Client-Type": "slicer",
            "X-ACNext-Client-Version": "1.3.9.4 20260319225535",
        }

        fake_n3mf = SimpleNamespace(
            CustomPart=_FakeCustomPart,
            CustomContentType=_FakeContentType,
        )
        monkeypatch.setattr(writer_module, "_n3mf", fake_n3mf)

        builder = _FakeBuilder()
        writer._inject_metadata_parts(builder, [1, 2], 3)

        part_paths = [part.path for part in builder.parts]
        assert "Metadata/custom_gcode_per_layer.xml" in part_paths
        assert "Metadata/filament_sequence.json" not in part_paths
        assert "Metadata/cut_information.xml" not in part_paths

        custom_part = next(part for part in builder.parts if part.path == "Metadata/custom_gcode_per_layer.xml")
        custom_xml = ET.fromstring(custom_part.data)
        plate = custom_xml.find("./plate")
        assert plate is not None
        plate_info = plate.find("./plate_info")
        mode = plate.find("./mode")
        assert plate_info is not None and plate_info.attrib["id"] == "1"
        assert mode is not None and mode.attrib["value"] == "MultiExtruder"

    def test_anycubic_export_package_contains_expected_files(self, tmp_path) -> None:
        writer = _make_anycubic_writer(tmp_path)
        out_path = writer.export()

        with zipfile.ZipFile(out_path) as package:
            names = set(package.namelist())
            assert "Metadata/plate_1.png" in names
            assert "Metadata/plate_no_light_1.png" in names
            assert "Metadata/top_1.png" in names
            assert "Metadata/pick_1.png" in names
            assert "Metadata/custom_gcode_per_layer.xml" in names
            assert "Metadata/filament_sequence.json" not in names
            assert "Metadata/cut_information.xml" not in names

            model_root = ET.fromstring(package.read("3D/3dmodel.model"))
            core_ns = {"m": "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"}
            model_metadata = {
                node.attrib["name"]: (node.text or "") for node in model_root.findall("m:metadata", core_ns)
            }
            assert model_metadata["Application"] == "BambuStudio-1.3.9.4"
            assert model_metadata["BambuStudio:3mfVersion"] == "1"

            slice_root = ET.fromstring(package.read("Metadata/slice_info.config"))
            header = slice_root.find("./header")
            assert header is not None
            header_items = {item.attrib["key"]: item.attrib["value"] for item in header.findall("header_item")}
            assert header_items["X-ACNext-Client-Type"] == "slicer"
            assert header_items["X-ACNext-Client-Version"] == "1.3.9.4 20260319225535"

    def test_h2d_0_2_bambu_version_uses_h2_family_client_stamp(self, tmp_path) -> None:
        writer = writer_module.BambuStudio3MFWriter(
            output_path=str(tmp_path / "h2d-0_2.3mf"),
            settings={},
            color_mode="4-Color",
            printer_id="bambu-h2d",
            slicer="BambuStudio",
            nozzle_size="0.2",
        )

        assert writer._get_app_version_str() == "BambuStudio-02.05.00.66"

        slice_info = ET.fromstring(writer._build_slice_info_bytes())
        header = slice_info.find("./header")
        assert header is not None
        header_items = {item.attrib["key"]: item.attrib["value"] for item in header.findall("header_item")}
        assert header_items["X-BBL-Client-Version"] == "02.05.00.66"
