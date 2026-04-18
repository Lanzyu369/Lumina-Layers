"""
Lumina Studio - BambuStudio 3MF Writer
Enhanced 3MF export with BambuStudio-compatible metadata and configurations.

Uses neroued-3mf (C++ streaming writer with Production Extension) for 3MF
packaging, and injects Bambu/Orca vendor metadata via CustomPart.
"""

from __future__ import annotations

from dataclasses import dataclass
import io
import os
import sys
import time
import xml.etree.ElementTree as ET
import json
import copy
import re
from typing import List, Dict, Optional
import numpy as np

# Lazy imports: avoid >60s startup cost when imported via API.
# Only loaded when export functions are actually called.
_trimesh = None
_n3mf = None


def _get_trimesh():
    global _trimesh
    if _trimesh is None:
        import trimesh as _tm

        _trimesh = _tm
    return _trimesh


def _get_n3mf():
    global _n3mf
    if _n3mf is None:
        import neroued_3mf as _n

        _n3mf = _n
    return _n3mf


_CONFIG_TEMPLATE_CACHE = None
_PRINTER_TEMPLATE_CACHE: dict[str, dict] = {}


@dataclass(frozen=True)
class _MeshExportEntry:
    """Internal 3MF mesh export descriptor.

    内部 3MF 网格导出描述。

    Attributes:
        mesh: Trimesh geometry to export. (待导出的 Trimesh 几何体)
        object_name: Unique object name stored in the 3MF object list.
            (写入 3MF 对象列表的唯一对象名)
        material_name: Shared material/slot name used for global filament tables.
            (用于全局耗材表的共享材料或槽位名)
        color_rgb: RGB tuple for the shared material. (共享材料的 RGB 颜色)
    """

    mesh: object
    object_name: str
    material_name: str
    color_rgb: tuple[int, int, int]


def load_printer_template(
    printer_id: str,
    slicer: str = "BambuStudio",
    nozzle_size: Optional[str | float] = None,
) -> dict:
    """Load printer config template JSON for the given printer ID and slicer.
    加载指定机型和切片器的配置模板 JSON。

    Priority: printer_profiles/ directory first (matched via PrinterProfile.get_template_file),
    falls back to bambu_config_template.json for backward compatibility.
    优先从 printer_profiles/ 目录加载，找不到时回退到 bambu_config_template.json。

    Args:
        printer_id (str): Printer identifier, e.g. "bambu-h2d". (打印机标识)
        slicer (str): Slicer software identifier, e.g. "BambuStudio" or "OrcaSlicer". (切片器标识)
        nozzle_size (Optional[str | float]): Optional nozzle size variant, e.g. 0.2.
            Falls back to the base template when omitted or unavailable. (可选喷嘴尺寸变体)

    Returns:
        dict: Parsed JSON configuration template. (解析后的 JSON 配置模板)
    """
    global _PRINTER_TEMPLATE_CACHE

    from config import get_printer_profile, normalize_nozzle_size

    normalized_nozzle_size = normalize_nozzle_size(nozzle_size) or "0.4"
    cache_key = f"{printer_id}:{slicer}:{normalized_nozzle_size}"
    if cache_key in _PRINTER_TEMPLATE_CACHE:
        return copy.deepcopy(_PRINTER_TEMPLATE_CACHE[cache_key])

    profile = get_printer_profile(printer_id)
    template_file = profile.get_template_file(slicer, nozzle_size=normalized_nozzle_size)

    # Resolve printer_profiles/ directory
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        base_dir = sys._MEIPASS
    else:
        base_dir = os.path.join(os.path.dirname(__file__), "..")

    profile_path = os.path.join(base_dir, "printer_profiles", template_file)

    if os.path.exists(profile_path):
        with open(profile_path, "r", encoding="utf-8") as f:
            template = json.load(f)
        _PRINTER_TEMPLATE_CACHE[cache_key] = template
        print(
            f"[BAMBU_3MF] Loaded printer template: {profile_path} "
            f"(slicer={slicer}, nozzle_size={normalized_nozzle_size})"
        )
        return copy.deepcopy(template)

    # Fallback to legacy bambu_config_template.json
    fallback_path = os.path.join(base_dir, "bambu_config_template.json")
    if os.path.exists(fallback_path):
        with open(fallback_path, "r", encoding="utf-8") as f:
            template = json.load(f)
        _PRINTER_TEMPLATE_CACHE[cache_key] = template
        print(
            f"[BAMBU_3MF] Printer template not found for '{printer_id}' "
            f"(slicer={slicer}, nozzle_size={normalized_nozzle_size}), using fallback: {fallback_path}"
        )
        return copy.deepcopy(template)

    print(f"[WARNING] No printer template found for '{printer_id}', returning empty dict")
    return {}


class BambuStudio3MFWriter:
    """Enhanced 3MF writer with BambuStudio-compatible metadata.
    使用 neroued-3mf Production Extension 生成 Bambu 兼容 3MF。

    Features:
    - Embeds print settings (layer height, temperatures, speeds)
    - Adds color information to objects via BaseMaterial
    - Compatible with BambuStudio/OrcaSlicer/ElegooSlicer/SnapmakerOrca
    - C++ streaming XML serialisation with native ZIP64 support
    """

    DEFAULT_SETTINGS = {
        "layer_height": "0.08",
        "initial_layer_height": "0.08",
        "wall_loops": "1",
        "top_shell_layers": "0",
        "bottom_shell_layers": "0",
        "sparse_infill_density": "100%",
        "sparse_infill_pattern": "zig-zag",
        "nozzle_temperature": ["220", "220", "220", "220"],
        "bed_temperature": ["60", "60", "60", "60"],
        "filament_type": ["PLA", "PLA", "PLA", "PLA"],
        "print_speed": "100",
        "travel_speed": "150",
        "enable_support": "0",
        "brim_width": "5",
        "brim_type": "auto_brim",
    }

    def __init__(
        self,
        output_path: str,
        settings: Optional[Dict] = None,
        color_mode: str = "4-Color",
        printer_id: str = "bambu-h2d",
        slicer: str = "BambuStudio",
        nozzle_size: Optional[str | float] = None,
        watermark: str = "LuminaStudio",
    ):
        """Initialize 3MF writer with printer-specific template support.
        初始化 3MF 写入器，支持机型和切片器专属配置模板。

        Args:
            output_path (str): Output .3mf file path. (输出 .3mf 文件路径)
            settings (Optional[Dict]): Custom print settings overrides. (自定义打印设置覆盖)
            color_mode (str): Color mode ('4-Color', '6-Color', '8-Color', 'BW'). (颜色模式)
            printer_id (str): Printer identifier for template selection, default 'bambu-h2d'. (打印机标识)
            slicer (str): Slicer software identifier, default 'BambuStudio'. (切片器标识)
            nozzle_size (Optional[str | float]): Nozzle size variant used for template selection.
                (用于模板选择的喷嘴尺寸变体)
            watermark (str): Watermark text embedded in the 3MF ZIP structure. (嵌入 3MF ZIP 结构的水印文本)
        """
        from config import normalize_nozzle_size, normalize_slicer_software_id

        self.output_path = output_path
        self.settings = {**self.DEFAULT_SETTINGS, **(settings or {})}
        self.objects: list[_MeshExportEntry] = []
        self.color_mode = color_mode
        self.printer_id = printer_id
        self.slicer = normalize_slicer_software_id(slicer)
        self.nozzle_size = normalize_nozzle_size(nozzle_size) or "0.4"
        self.watermark = watermark
        self._project_slot_names: list[str] = []
        self._project_preview_colors: dict | None = None

    def add_mesh(self, mesh: _get_trimesh().Trimesh, name: str, color_rgb: tuple):
        """Add a mesh object to the scene.
        将网格对象添加到场景中。

        Args:
            mesh: Trimesh object
            name: Object name (e.g., "White", "Cyan", "Magenta")
            color_rgb: RGB color tuple (0-255)
        """
        if mesh is None:
            raise ValueError(f"[BAMBU_3MF] Cannot add mesh '{name}': mesh is None")

        vertices = getattr(mesh, "vertices", None)
        faces = getattr(mesh, "faces", None)
        v_count = len(vertices) if vertices is not None else 0
        f_count = len(faces) if faces is not None else 0
        if v_count == 0 or f_count == 0:
            raise ValueError(f"[BAMBU_3MF] Cannot add mesh '{name}': empty geometry (v={v_count}, f={f_count})")

        metadata = getattr(mesh, "metadata", {}) or {}
        material_name = str(metadata.get("bambu_material_name") or name)
        self.objects.append(
            _MeshExportEntry(
                mesh=mesh,
                object_name=name,
                material_name=material_name,
                color_rgb=tuple(int(channel) for channel in color_rgb[:3]),
            )
        )

    def _set_project_palette(self, slot_names: list[str], preview_colors: Dict) -> None:
        """Configure the project-wide palette used for exported metadata.

        配置导出元数据使用的项目级完整调色板。
        """

        self._project_slot_names = [str(name) for name in slot_names if str(name)]
        self._project_preview_colors = dict(preview_colors or {})

    def _build_object_material_palette(self) -> tuple[list[tuple[str, tuple[int, int, int]]], dict[str, int]]:
        """Build the compact material palette from queued mesh objects only.

        从待导出的网格对象中构建仅包含实际对象的紧凑材料调色板。
        """

        palette: list[tuple[str, tuple[int, int, int]]] = []
        name_to_index: dict[str, int] = {}
        for entry in self.objects:
            if entry.material_name in name_to_index:
                continue
            name_to_index[entry.material_name] = len(palette)
            palette.append((entry.material_name, entry.color_rgb))
        return palette, name_to_index

    def _build_material_palette(self) -> tuple[list[tuple[str, tuple[int, int, int]]], dict[str, int]]:
        """Build the shared export palette for meshes and project metadata.

        构建用于网格与项目元数据的共享导出调色板。

        Returns:
            tuple[list[tuple[str, tuple[int, int, int]]], dict[str, int]]:
                Ordered shared-material palette and material-name to palette-index map.
                （有序共享材料调色板，以及材料名到调色板索引的映射）
        """

        object_palette, _ = self._build_object_material_palette()
        if not self._project_slot_names:
            return object_palette, {
                material_name: idx for idx, (material_name, _) in enumerate(object_palette)
            }

        palette: list[tuple[str, tuple[int, int, int]]] = []
        name_to_index: dict[str, int] = {}
        preview_colors = self._project_preview_colors or {}
        for slot_index, slot_name in enumerate(self._project_slot_names):
            if slot_name in name_to_index:
                continue
            color_rgb, _ = _resolve_preview_color_for_slot_name(
                slot_name=slot_name,
                slot_index=slot_index,
                preview_colors=preview_colors,
            )
            name_to_index[slot_name] = len(palette)
            palette.append((slot_name, color_rgb))

        for material_name, color_rgb in object_palette:
            if material_name in name_to_index:
                continue
            name_to_index[material_name] = len(palette)
            palette.append((material_name, color_rgb))
        return palette, name_to_index

    def export(self) -> str:
        """Export all meshes to a BambuStudio-compatible 3MF file.
        将所有网格导出为 BambuStudio 兼容的 3MF 文件。

        Returns:
            str: Path to the exported 3MF file
        """
        if len(self.objects) == 0:
            raise ValueError("[BAMBU_3MF] Refusing to export 3MF: no mesh objects were added")

        print(f"[BAMBU_3MF] Exporting {len(self.objects)} objects to {self.output_path}")
        _exp_t0 = time.perf_counter()

        n3mf = _get_n3mf()

        builder = n3mf.DocumentBuilder()
        builder.set_unit(n3mf.Unit.Millimeter)
        builder.set_language("en-US")

        builder.enable_production()
        builder.set_production_merge_objects(True)

        builder.add_namespace("BambuStudio", "http://schemas.bambulab.com/package/2021")
        builder.add_metadata("Application", self._get_app_version_str())
        builder.add_metadata("BambuStudio:3mfVersion", "1")
        builder.add_external_model_metadata("BambuStudio:3mfVersion", "1")

        material_palette, material_indices = self._build_material_palette()
        materials = [
            n3mf.BaseMaterial(name, n3mf.Color(rgb[0], rgb[1], rgb[2]))
            for name, rgb in material_palette
        ]
        mat_group_id = builder.add_base_material_group(materials)

        object_ids: list[int] = []
        material_index_by_object: list[int] = []
        for entry in self.objects:
            n3mf_mesh = n3mf.Mesh.from_arrays(
                np.ascontiguousarray(entry.mesh.vertices, dtype=np.float64),
                np.ascontiguousarray(entry.mesh.faces, dtype=np.int64),
            )
            material_index = material_indices[entry.material_name]
            obj_id = builder.add_mesh_object(entry.object_name, n3mf_mesh, mat_group_id, material_index)
            builder.add_build_item(obj_id)
            object_ids.append(obj_id)
            material_index_by_object.append(material_index)

        assembly_id = object_ids[-1] + 1 if object_ids else mat_group_id + 1
        self._inject_metadata_parts(builder, object_ids, assembly_id, material_index_by_object)

        doc = builder.build()

        opts = n3mf.WriteOptions()
        opts.vertex_precision = 6
        opts.compact_xml = True
        if self.watermark and hasattr(n3mf, "WatermarkConfig"):
            opts.watermark = n3mf.WatermarkConfig(payload=self.watermark.encode("utf-8"))
        elif self.watermark:
            n3mf_version = getattr(n3mf, "__version__", "unknown")
            print(
                "[BAMBU_3MF] Watermark disabled: "
                f"neroued_3mf {n3mf_version} does not provide WatermarkConfig"
            )

        n3mf.write_to_file(self.output_path, doc, opts)

        print(f"[BAMBU_3MF] [OK] Export complete: {self.output_path} ({time.perf_counter() - _exp_t0:.3f}s total)")
        return self.output_path

    # ------------------------------------------------------------------
    # Slicer version string
    # ------------------------------------------------------------------

    def _get_app_version_str(self) -> str:
        """Return slicer-appropriate Application version string.
        返回适配不同切片器的 Application 版本字符串。
        """
        _VERSION_MAP = {
            "SnapmakerOrca": "BambuStudio-2.2.4",
            "ElegooSlicer": "ElegooSlicer-1.3.2.9",
            "OrcaSlicer": "BambuStudio-2.3.2-rc2",
            "AnycubicSlicerNext": "BambuStudio-1.3.9.4",
        }
        if self.slicer == "BambuStudio":
            return f"BambuStudio-{self._get_bambu_client_version()}"
        return _VERSION_MAP.get(self.slicer, "BambuStudio-02.02.01.04")

    def _get_bambu_client_version(self) -> str:
        """Return the BambuStudio client-version stamp for this printer/nozzle combination."""
        if self.nozzle_size != "0.2":
            return "02.05.00.66"
        h2_family = {"bambu-h2c", "bambu-h2d", "bambu-h2d-pro", "bambu-h2s"}
        if self.printer_id in h2_family:
            return "02.05.00.66"
        return "02.04.00.70"

    def _is_anycubic_slicer(self) -> bool:
        """Return whether the current export targets Anycubic Slicer Next.
        返回当前导出是否面向 Anycubic Slicer Next。
        """
        return self.slicer == "AnycubicSlicerNext"

    def _should_emit_bambu_aux_parts(self) -> bool:
        """Return whether the export should include Bambu-only aux metadata parts."""
        return self.slicer == "BambuStudio"

    @staticmethod
    def _format_number(value: float) -> str:
        """Format a float for stable metadata output.
        将浮点数格式化为稳定的元数据输出字符串。
        """
        return format(float(value), ".15g")

    def _get_identify_id(self) -> str:
        """Return a slicer-specific plate identify_id value.
        返回切片器专属的 plate identify_id 值。
        """
        if self._is_anycubic_slicer():
            return "160"
        return "1"

    # ------------------------------------------------------------------
    # Bambu vendor metadata injection (CustomPart)
    # ------------------------------------------------------------------

    def _inject_metadata_parts(
        self,
        builder: _get_n3mf().DocumentBuilder,
        object_ids: list[int],
        assembly_id: int,
        material_index_by_object: list[int] | None = None,
    ) -> None:
        """Inject all Bambu vendor metadata files into the 3MF via CustomPart.
        通过 CustomPart 向 3MF 中注入所有 Bambu 厂商元数据。
        """
        parts = [
            (
                "Metadata/model_settings.config",
                "text/xml",
                self._build_model_settings_bytes(object_ids, assembly_id, material_index_by_object),
            ),
            ("Metadata/project_settings.config", "text/xml", self._build_project_settings_bytes()),
            ("Metadata/slice_info.config", "text/xml", self._build_slice_info_bytes()),
        ]
        if self._is_anycubic_slicer():
            parts.append(
                ("Metadata/custom_gcode_per_layer.xml", "text/xml", self._build_custom_gcode_per_layer_bytes())
            )
        elif self._should_emit_bambu_aux_parts():
            parts.extend(
                [
                    ("Metadata/filament_sequence.json", "application/json", self._build_filament_sequence_bytes()),
                    ("Metadata/cut_information.xml", "text/xml", self._build_cut_information_bytes()),
                ]
            )
        preview_png = self._build_preview_placeholder_png_bytes()
        parts.extend(
            [
                ("Metadata/plate_1.png", "image/png", preview_png),
                ("Metadata/plate_no_light_1.png", "image/png", preview_png),
                ("Metadata/top_1.png", "image/png", preview_png),
                ("Metadata/pick_1.png", "image/png", preview_png),
            ]
        )
        for path, content_type, data in parts:
            builder.add_custom_part(_get_n3mf().CustomPart(path, content_type, data))

        builder.add_custom_content_type(_get_n3mf().CustomContentType("config", "text/xml"))
        builder.add_custom_content_type(_get_n3mf().CustomContentType("json", "application/json"))
        builder.add_custom_content_type(_get_n3mf().CustomContentType("xml", "text/xml"))
        builder.add_custom_content_type(_get_n3mf().CustomContentType("png", "image/png"))

    # ------------------------------------------------------------------
    # Individual metadata builders (return bytes, no filesystem I/O)
    # ------------------------------------------------------------------

    def _build_model_settings_bytes(
        self,
        object_ids: list[int],
        assembly_id: int,
        material_index_by_object: list[int] | None = None,
    ) -> bytes:
        """Build model_settings.config XML as bytes.
        构建 model_settings.config XML（字节形式）。
        """
        config = ET.Element("config")

        obj_elem = ET.SubElement(config, "object", attrib={"id": str(assembly_id)})
        ET.SubElement(obj_elem, "metadata", attrib={"key": "extruder", "value": "1"})

        source_file = os.path.basename(self.output_path)
        if material_index_by_object is None:
            resolved_material_indices = list(range(len(self.objects)))
        else:
            resolved_material_indices = material_index_by_object

        for idx, (entry, obj_id, material_index) in enumerate(
            zip(self.objects, object_ids, resolved_material_indices)
        ):
            bounds = np.asarray(getattr(entry.mesh, "bounds", np.zeros((2, 3))), dtype=np.float64)
            if bounds.shape != (2, 3):
                bounds = np.zeros((2, 3), dtype=np.float64)
            center_x, center_y, center_z = bounds.mean(axis=0)
            max_x, max_y, max_z = bounds[1]
            matrix_value = (
                "1 0 0 "
                f"{self._format_number(max_x)} "
                "0 1 0 "
                f"{self._format_number(max_y)} "
                "0 0 1 "
                f"{self._format_number(max_z)} "
                "0 0 0 1"
            )
            part = ET.SubElement(obj_elem, "part", attrib={"id": str(obj_id), "subtype": "normal_part"})
            ET.SubElement(part, "metadata", attrib={"key": "name", "value": entry.object_name})
            ET.SubElement(part, "metadata", attrib={"key": "matrix", "value": matrix_value})
            ET.SubElement(part, "metadata", attrib={"key": "source_file", "value": source_file})
            ET.SubElement(part, "metadata", attrib={"key": "source_object_id", "value": "0"})
            ET.SubElement(part, "metadata", attrib={"key": "source_volume_id", "value": str(idx)})
            ET.SubElement(part, "metadata", attrib={"key": "source_offset_x", "value": self._format_number(center_x)})
            ET.SubElement(part, "metadata", attrib={"key": "source_offset_y", "value": self._format_number(center_y)})
            ET.SubElement(part, "metadata", attrib={"key": "source_offset_z", "value": self._format_number(center_z)})
            ET.SubElement(part, "metadata", attrib={"key": "extruder", "value": str(material_index + 1)})
            ET.SubElement(
                part,
                "mesh_stat",
                attrib={
                    "edges_fixed": "0",
                    "degenerate_facets": "0",
                    "facets_removed": "0",
                    "facets_reversed": "0",
                    "backwards_edges": "0",
                },
            )

        plate = ET.SubElement(config, "plate")
        ET.SubElement(plate, "metadata", attrib={"key": "plater_id", "value": "1"})
        ET.SubElement(plate, "metadata", attrib={"key": "plater_name", "value": ""})
        ET.SubElement(plate, "metadata", attrib={"key": "locked", "value": "false"})
        if not self._is_anycubic_slicer():
            ET.SubElement(plate, "metadata", attrib={"key": "filament_map_mode", "value": "Auto For Flush"})
        ET.SubElement(plate, "metadata", attrib={"key": "thumbnail_file", "value": "Metadata/plate_1.png"})
        ET.SubElement(
            plate, "metadata", attrib={"key": "thumbnail_no_light_file", "value": "Metadata/plate_no_light_1.png"}
        )
        ET.SubElement(plate, "metadata", attrib={"key": "top_file", "value": "Metadata/top_1.png"})
        ET.SubElement(plate, "metadata", attrib={"key": "pick_file", "value": "Metadata/pick_1.png"})

        model_instance = ET.SubElement(plate, "model_instance")
        ET.SubElement(model_instance, "metadata", attrib={"key": "object_id", "value": str(assembly_id)})
        ET.SubElement(model_instance, "metadata", attrib={"key": "instance_id", "value": "0"})
        ET.SubElement(model_instance, "metadata", attrib={"key": "identify_id", "value": self._get_identify_id()})

        tree = ET.ElementTree(config)
        ET.indent(tree, space="  ")

        buf = io.BytesIO()
        buf.write(b'<?xml version="1.0" encoding="UTF-8"?>\n')
        tree.write(buf, encoding="utf-8", xml_declaration=False)
        return buf.getvalue()

    def _build_project_settings_bytes(self) -> bytes:
        """Build project_settings.config JSON as bytes.
        构建 project_settings.config JSON（字节形式）。
        """
        material_palette, _ = self._build_material_palette()
        num_colors = len(material_palette)

        settings = self._get_base_config_template()

        _RESIZABLE_ARRAY_KEYS = frozenset(
            [
                "nozzle_temperature",
                "nozzle_temperature_initial_layer",
                "nozzle_temperature_range_low",
                "nozzle_temperature_range_high",
                "bed_temperature",
                "bed_temperature_initial_layer",
                "activate_air_filtration",
                "additional_cooling_fan_speed",
                "chamber_temperatures",
                "close_fan_the_first_x_layers",
                "complete_print_exhaust_fan_speed",
                "cool_plate_temp",
                "cool_plate_temp_initial_layer",
                "during_print_exhaust_fan_speed",
                "eng_plate_temp",
                "eng_plate_temp_initial_layer",
                "fan_cooling_layer_time",
                "fan_max_speed",
                "fan_min_speed",
                "hot_plate_temp",
                "hot_plate_temp_initial_layer",
                "textured_plate_temp",
                "textured_plate_temp_initial_layer",
            ]
        )

        for key, value in settings.items():
            if isinstance(value, list) and len(value) > 0:
                if key.startswith("filament_") or key in _RESIZABLE_ARRAY_KEYS:
                    if len(value) != num_colors:
                        template_value = value[0] if value else "0"
                        settings[key] = [template_value] * num_colors

        settings.update(self._build_filament_arrays(material_palette))

        settings.setdefault("single_extruder_multi_material", "1")
        settings.setdefault("enable_prime_tower", "1")

        if self.settings:
            for key in [
                "layer_height",
                "initial_layer_height",
                "wall_loops",
                "top_shell_layers",
                "bottom_shell_layers",
                "sparse_infill_density",
                "sparse_infill_pattern",
                "print_speed",
                "travel_speed",
                "enable_support",
                "brim_width",
                "brim_type",
            ]:
                if key in self.settings:
                    settings[key] = self.settings[key]

        return json.dumps(settings, indent=4, ensure_ascii=False).encode("utf-8")

    def _build_slice_info_bytes(self) -> bytes:
        """Build slice_info.config XML as bytes.
        构建 slice_info.config XML（字节形式）。
        """
        config = ET.Element("config")
        header = ET.SubElement(config, "header")
        if self._is_anycubic_slicer():
            ET.SubElement(header, "header_item", attrib={"key": "X-ACNext-Client-Type", "value": "slicer"})
            ET.SubElement(
                header, "header_item", attrib={"key": "X-ACNext-Client-Version", "value": "1.3.9.4 20260319225535"}
            )
        else:
            ET.SubElement(header, "header_item", attrib={"key": "X-BBL-Client-Type", "value": "slicer"})
            if self.slicer == "BambuStudio":
                client_version = self._get_bambu_client_version()
                ET.SubElement(header, "header_item", attrib={"key": "X-BBL-Client-Version", "value": client_version})
            elif self.slicer == "ElegooSlicer":
                ET.SubElement(header, "header_item", attrib={"key": "X-BBL-Client-Version", "value": "01.03.02.09"})
                ET.SubElement(header, "header_item", attrib={"key": "X-BBL-Client-Name", "value": "ElegooSlicer"})
            else:
                ET.SubElement(header, "header_item", attrib={"key": "X-BBL-Client-Version", "value": ""})

        tree = ET.ElementTree(config)
        ET.indent(tree, space="  ")

        buf = io.BytesIO()
        buf.write(b'<?xml version="1.0" encoding="UTF-8"?>\n')
        tree.write(buf, encoding="utf-8", xml_declaration=False)
        return buf.getvalue()

    @staticmethod
    def _build_filament_sequence_bytes() -> bytes:
        """Build filament_sequence.json as bytes.
        构建 filament_sequence.json（字节形式）。
        """
        data = {"plate_1": {"sequence": []}}
        return json.dumps(data, ensure_ascii=False).encode("utf-8")

    @staticmethod
    def _build_cut_information_bytes() -> bytes:
        """Build cut_information.xml as bytes.
        构建 cut_information.xml（字节形式）。
        """
        config = ET.Element("objects")
        obj = ET.SubElement(config, "object", attrib={"id": "1"})
        ET.SubElement(obj, "cut_id", attrib={"id": "0", "check_sum": "1", "connectors_cnt": "0"})

        tree = ET.ElementTree(config)
        ET.indent(tree, space=" ")

        buf = io.BytesIO()
        buf.write(b'<?xml version="1.0" encoding="utf-8"?>\n')
        tree.write(buf, encoding="utf-8", xml_declaration=False)
        return buf.getvalue()

    @staticmethod
    def _build_custom_gcode_per_layer_bytes() -> bytes:
        """Build Anycubic custom_gcode_per_layer.xml as bytes.
        构建 Anycubic 的 custom_gcode_per_layer.xml（字节形式）。
        """
        config = ET.Element("custom_gcodes_per_layer")
        plate = ET.SubElement(config, "plate")
        ET.SubElement(plate, "plate_info", attrib={"id": "1"})
        ET.SubElement(plate, "mode", attrib={"value": "MultiExtruder"})

        tree = ET.ElementTree(config)
        ET.indent(tree, space="  ")

        buf = io.BytesIO()
        buf.write(b'<?xml version="1.0" encoding="utf-8"?>\n')
        tree.write(buf, encoding="utf-8", xml_declaration=False)
        return buf.getvalue()

    @staticmethod
    def _build_preview_placeholder_png_bytes() -> bytes:
        """Build a tiny valid PNG payload for referenced plate preview assets."""
        # 1x1 transparent PNG
        return (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc`\x00\x01"
            b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        )

    # ------------------------------------------------------------------
    # Config template & filament arrays (unchanged logic)
    # ------------------------------------------------------------------

    def _get_base_config_template(self) -> dict:
        """Get complete BambuStudio configuration template for the selected printer.
        获取所选机型的完整 BambuStudio 配置模板。

        Uses load_printer_template() to load printer-specific templates from
        printer_profiles/ directory, falling back to bambu_config_template.json.

        Returns:
            dict: Complete configuration template. (完整配置模板)
        """
        template = load_printer_template(
            self.printer_id,
            slicer=self.slicer,
            nozzle_size=self.nozzle_size,
        )
        if template:
            return template

        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            template_path = os.path.join(sys._MEIPASS, "bambu_config_template.json")
        else:
            template_path = os.path.join(os.path.dirname(__file__), "..", "bambu_config_template.json")

        global _CONFIG_TEMPLATE_CACHE
        if os.path.exists(template_path):
            if _CONFIG_TEMPLATE_CACHE is None:
                with open(template_path, "r", encoding="utf-8") as f:
                    _CONFIG_TEMPLATE_CACHE = json.load(f)
            return copy.deepcopy(_CONFIG_TEMPLATE_CACHE)
        else:
            print("[WARNING] bambu_config_template.json not found, using minimal config")
            return self._get_minimal_config_template()

    @staticmethod
    def _get_minimal_config_template() -> dict:
        """Fallback minimal configuration template."""
        return {
            "layer_height": "0.08",
            "initial_layer_height": "0.08",
            "wall_loops": "1",
            "top_shell_layers": "0",
            "bottom_shell_layers": "0",
            "sparse_infill_density": "100%",
            "sparse_infill_pattern": "zig-zag",
            "nozzle_temperature": ["220"] * 8,
            "nozzle_temperature_initial_layer": ["220"] * 8,
        }

    def _build_filament_arrays(self, material_palette: list[tuple[str, tuple[int, int, int]]]) -> dict:
        """Build filament-related arrays for the shared material palette.
        为共享材料调色板构建耗材相关数组。

        Args:
            material_palette: Ordered shared material palette.
                （有序的共享材料调色板）

        Returns:
            dict: Filament arrays with correct lengths.
                （长度正确的耗材数组）
        """
        arrays: dict[str, list] = {}

        arrays["filament_colour"] = []
        for _, color_rgb in material_palette:
            hex_color = f"#{color_rgb[0]:02X}{color_rgb[1]:02X}{color_rgb[2]:02X}"
            arrays["filament_colour"].append(hex_color)

        return arrays


# ======================================================================
# Public convenience function (signature unchanged from original)
# ======================================================================


def export_scene_with_bambu_metadata(
    scene: _get_trimesh().Scene,
    output_path: str,
    slot_names: List[str],
    preview_colors: Dict,
    settings: Optional[Dict] = None,
    color_mode: str = "4-Color",
    printer_id: str = "bambu-h2d",
    slicer: str = "BambuStudio",
    nozzle_size: Optional[str | float] = None,
    watermark: str = "LuminaStudio",
    project_slot_names: Optional[List[str]] = None,
):
    """Export a Trimesh scene to BambuStudio/OrcaSlicer-compatible 3MF with metadata.
    将 Trimesh 场景导出为 BambuStudio/OrcaSlicer 兼容的 3MF 文件（含元数据）。

    Args:
        scene (_get_trimesh().Scene): Trimesh Scene containing all meshes. (包含所有网格的场景)
        output_path (str): Output .3mf file path. (输出 .3mf 文件路径)
        slot_names (List[str]): Actually used material names. (实际使用的材料名称列表)
        preview_colors (Dict): Material ID to RGBA color mapping. (材料 ID 到 RGBA 颜色映射)
        settings (Optional[Dict]): Custom print settings. (自定义打印设置)
        color_mode (str): Color mode ('4-Color', '6-Color', '8-Color', 'BW'). (颜色模式)
        printer_id (str): Printer identifier for template selection, default 'bambu-h2d'. (打印机标识)
        slicer (str): Slicer software identifier, default 'BambuStudio'. (切片器标识)
        nozzle_size (Optional[str | float]): Nozzle size variant used for template selection.
            (用于模板选择的喷嘴尺寸变体)
        watermark (str): Watermark text embedded in the 3MF ZIP structure. (嵌入 3MF ZIP 结构的水印文本)
        project_slot_names (Optional[List[str]]): Full selected source palette/material names to preserve
            in exported project metadata when available. (可选，导出项目元数据时应保留的完整来源调色板/材料名称)

    Returns:
        str: Path to the exported 3MF file. (导出的 3MF 文件路径)
    """
    if scene is None:
        raise ValueError("[BAMBU_3MF] Scene is None")
    if not slot_names:
        raise ValueError("[BAMBU_3MF] slot_names is empty - no exportable objects")

    resolved_project_slot_names = [str(name) for name in (project_slot_names or []) if str(name)]
    palette_color_count = len(resolved_project_slot_names) if resolved_project_slot_names else len(slot_names)

    if palette_color_count <= 2:
        actual_color_mode = "BW"
    elif palette_color_count <= 4:
        actual_color_mode = "4-Color"
    elif palette_color_count <= 6:
        actual_color_mode = "6-Color"
    else:
        actual_color_mode = "8-Color"

    print(
        f"[BAMBU_3MF] LUT color_mode: {color_mode}, Palette colors: {palette_color_count} → 3MF mode: {actual_color_mode}"
    )

    writer = BambuStudio3MFWriter(
        output_path, settings, actual_color_mode,
        printer_id=printer_id, slicer=slicer, nozzle_size=nozzle_size, watermark=watermark,
    )
    if resolved_project_slot_names:
        writer._set_project_palette(resolved_project_slot_names, preview_colors)

    name_to_color: dict[str, tuple] = {}
    project_slot_indices = {name: idx for idx, name in enumerate(resolved_project_slot_names)}
    print("[BAMBU_3MF] Building color mapping:")
    for idx, slot_name in enumerate(slot_names):
        resolved_slot_index = project_slot_indices.get(slot_name, idx)
        color_rgb, source = _resolve_preview_color_for_slot_name(
            slot_name=slot_name,
            slot_index=resolved_slot_index,
            preview_colors=preview_colors,
        )
        name_to_color[slot_name] = color_rgb
        print(f"[BAMBU_3MF]   {idx}: '{slot_name}' -> RGB{color_rgb} ({source})")

    print(f"[BAMBU_3MF] Color mapping complete: {list(name_to_color.keys())}")

    print("[BAMBU_3MF] Adding meshes to 3MF:")
    unmatched = []
    for idx, slot_name in enumerate(slot_names):
        mesh = scene.geometry.get(slot_name)
        if mesh is None:
            unmatched.append(slot_name)
            print(f"[BAMBU_3MF]   {idx}: '{slot_name}' - NOT FOUND in scene")
            continue

        color_rgb = name_to_color.get(slot_name, (200, 200, 200))
        writer.add_mesh(mesh, slot_name, color_rgb)
        print(f"[BAMBU_3MF]   {idx}: '{slot_name}' -> RGB{color_rgb} (added to 3MF)")

    if unmatched:
        raise ValueError("[BAMBU_3MF] Missing geometries for slot names: " + ", ".join(unmatched))

    return writer.export()


def _resolve_preview_color_for_slot_name(
    slot_name: str,
    slot_index: int,
    preview_colors: Dict,
) -> tuple[tuple[int, int, int], str]:
    """Resolve a slot color from preview metadata.

    根据预览颜色元数据解析槽位颜色。

    Args:
        slot_name: User-facing slot/material name.
            用户可见的槽位或材料名称。
        slot_index: Compact slot index in the current export order.
            当前导出顺序中的紧凑槽位索引。
        preview_colors: Preview color mapping from the pipeline cache.
            来自流水线缓存的预览颜色映射。

    Returns:
        tuple[tuple[int, int, int], str]:
            Resolved RGB color and a short resolution source label.
            解析得到的 RGB 颜色，以及解析来源标记。
    """

    if slot_name in preview_colors:
        return _coerce_preview_rgb(preview_colors[slot_name]), "by name"

    slot_number = _parse_slot_number(slot_name)
    if slot_number is not None:
        slot_key = slot_number - 1
        if slot_key in preview_colors:
            return _coerce_preview_rgb(preview_colors[slot_key]), "by slot"
        slot_key_str = str(slot_key)
        if slot_key_str in preview_colors:
            return _coerce_preview_rgb(preview_colors[slot_key_str]), "by slot"

    if slot_index in preview_colors:
        return _coerce_preview_rgb(preview_colors[slot_index]), "by index"

    slot_index_str = str(slot_index)
    if slot_index_str in preview_colors:
        return _coerce_preview_rgb(preview_colors[slot_index_str]), "by index"

    return (200, 200, 200), "fallback"


def _parse_slot_number(slot_name: str) -> int | None:
    """Extract a 1-based slot number from a slot label when present.

    从槽位名称中提取 1-based 槽位编号。
    """

    match = re.match(r"Slot\s+(\d+)\b", slot_name)
    if match is None:
        return None
    return int(match.group(1))


def _coerce_preview_rgb(value: object) -> tuple[int, int, int]:
    """Coerce a preview-color value into an RGB tuple.

    将预览颜色值转换为 RGB 元组。
    """

    if isinstance(value, np.ndarray):
        channels = value.tolist()
    elif isinstance(value, (list, tuple)):
        channels = list(value)
    else:
        raise ValueError(f"Unsupported preview color value: {type(value)!r}")

    if len(channels) < 3:
        raise ValueError("Preview color value must have at least 3 channels.")
    return tuple(int(channel) for channel in channels[:3])
