"""Puzzle 3MF assembly helpers.
拼图模式 3MF 组装辅助工具。

This module converts multiple per-piece 3MF files into a single combined 3MF
that preserves per-piece placement and groups each puzzle piece as a distinct
object in the final package.
本模块用于将多个单块 3MF 组合为一个统一的 3MF，并保留每块拼图的全局位置，
同时让最终文件中的每个拼图块都作为独立对象出现。
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
import io
import json
import logging
import os
import re
import zipfile
import xml.etree.ElementTree as ET

import numpy as np
import trimesh

from utils.bambu_3mf_writer import BambuStudio3MFWriter

log = logging.getLogger(__name__)

_CORE_NS = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
_PROD_NS = "http://schemas.microsoft.com/3dmanufacturing/production/2015/06"
_BAMBU_NS = "http://schemas.bambulab.com/package/2021"
_NS = {"m": _CORE_NS, "p": _PROD_NS, "BambuStudio": _BAMBU_NS}


@dataclass(frozen=True)
class PuzzlePiece3MFSource:
    """Per-piece source metadata for combined 3MF export.
    组合导出时每个拼图块的源文件元数据。

    Attributes:
        label: Stable piece label such as ``A1``.
            稳定的拼图块编号，例如 ``A1``。
        threemf_path: Path to the generated per-piece 3MF file.
            单块 3MF 文件路径。
        offset_x_mm: Global X offset in millimeters.
            拼图块在总装配中的全局 X 偏移，单位毫米。
        offset_y_mm: Global Y offset in millimeters.
            拼图块在总装配中的全局 Y 偏移，单位毫米。
    """

    label: str
    threemf_path: str
    offset_x_mm: float
    offset_y_mm: float


@dataclass(frozen=True)
class _LoadedPiecePackage:
    """Parsed per-piece 3MF package used for combined assembly.
    用于组合装配的单块 3MF 解析结果。

    Attributes:
        source: Piece source descriptor supplied by the caller.
            调用方提供的拼图块源描述。
        package_files: Raw ZIP entries keyed by package path.
            按包内路径索引的原始 ZIP 条目。
        root_model: Parsed root ``3D/3dmodel.model`` element.
            解析后的根 ``3D/3dmodel.model`` 元素。
        root_object: Parsed top-level piece object from the root model.
            根模型中的顶层拼图块对象。
        object_model_bytes: Raw per-piece object-model bytes.
            单块 object-model 原始字节。
        model_settings_object: Parsed object entry from ``model_settings.config``.
            ``model_settings.config`` 中的对象节点。
        plate_metadata: Reusable ``plate`` metadata copied into the combined file.
            可复用于组合文件的 ``plate`` 元数据。
    """

    source: PuzzlePiece3MFSource
    package_files: dict[str, bytes]
    root_model: ET.Element
    root_object: ET.Element
    object_model_bytes: bytes
    model_settings_object: ET.Element | None
    plate_metadata: dict[str, str]


@dataclass(frozen=True)
class _PieceMeshEntry:
    """Parsed mesh entry from a piece 3MF.
    从单块 3MF 中解析出的网格条目。
    """

    material_name: str
    mesh: trimesh.Trimesh


@dataclass(frozen=True)
class _PieceObjectEntry:
    """Mesh-object grouping entry for one puzzle piece.
    单个拼图块的网格对象分组条目。
    """

    object_id: int
    material_name: str


def assemble_puzzle_3mf(
    piece_sources: list[PuzzlePiece3MFSource],
    output_path: str,
    preview_colors: dict[object, object] | None,
    slot_names: list[str] | None,
    printer_id: str,
    slicer: str,
    nozzle_size: str = "0.4",
    overview_png_bytes: bytes | None = None,
    device_profile_id: str | None = None,
) -> str:
    """Assemble multiple puzzle piece 3MF files into one grouped 3MF.
    将多个拼图单块 3MF 组装为一个按块分组的统一 3MF。

    Args:
        piece_sources: Per-piece 3MF sources with global placement offsets.
            带有全局装配偏移量的单块 3MF 源列表。
        output_path: Target output 3MF path.
            目标输出 3MF 路径。
        preview_colors: Preview color mapping from the converter cache.
            来自 converter 缓存的预览颜色映射。
        slot_names: Slot-name list matching preview color IDs when needed.
            当颜色映射按槽位 ID 保存时使用的槽位名称列表。
        printer_id: Printer profile identifier.
            打印机配置 ID。
        slicer: Slicer software identifier.
            切片软件 ID。
        nozzle_size: Nozzle size variant for template selection.
            喷嘴尺寸变体，用于模板选择。
        overview_png_bytes: Combined assembly preview PNG reused for package thumbnails.
            （组合总览 PNG，可复用于包内缩略图资源）
        device_profile_id: Optional generated machine registry profile ID.
            可选的生成式机器注册表设备配置 ID。

    Returns:
        str: Output 3MF path.
            输出 3MF 文件路径。

    Raises:
        ValueError: If no valid piece geometry can be assembled.
            当无法组装出任何有效几何时抛出。
    """
    if not piece_sources:
        raise ValueError("Puzzle 3MF assembly received no piece sources.")

    piece_packages = [_load_piece_package(piece_source) for piece_source in piece_sources]
    root_object_start = _resolve_root_object_start(piece_packages)
    root_object_ids = list(
        range(
            root_object_start,
            root_object_start + len(piece_packages),
        )
    )

    base_files = {
        name: data
        for name, data in piece_packages[0].package_files.items()
        if name
        not in {
            "3D/3dmodel.model",
            "3D/_rels/3dmodel.model.rels",
            "Metadata/model_settings.config",
            "Metadata/cut_information.xml",
        }
        and not name.startswith("3D/Objects/")
    }

    combined_root = _clone_empty_root_model(piece_packages[0].root_model)
    combined_resources = combined_root.find("m:resources", _NS)
    combined_build = combined_root.find("m:build", _NS)
    if combined_resources is None or combined_build is None:
        raise ValueError("Combined puzzle root model is missing resources or build nodes.")

    combined_object_model = _clone_empty_object_model_root(
        ET.fromstring(piece_packages[0].object_model_bytes)
    )
    combined_object_resources = combined_object_model.find("m:resources", _NS)
    if combined_object_resources is None:
        raise ValueError("Combined puzzle object model is missing resources.")

    combined_object_model_path = "3D/Objects/object_1.model"
    global_mesh_object_id = 2
    part_id_maps_by_piece: list[dict[int, int]] = []

    for piece_package, root_object_id in zip(piece_packages, root_object_ids):
        piece_object_model = ET.fromstring(piece_package.object_model_bytes)
        piece_object_resources = piece_object_model.find("m:resources", _NS)
        if piece_object_resources is None:
            raise ValueError("Puzzle piece object model is missing resources.")

        part_id_map: dict[int, int] = {}
        for object_node in piece_object_resources.findall("m:object", _NS):
            try:
                original_object_id = int(object_node.get("id", "0"))
            except ValueError as exc:
                raise ValueError("Puzzle piece object model contains invalid object ID.") from exc
            remapped_object = copy.deepcopy(object_node)
            remapped_object.set("id", str(global_mesh_object_id))
            material_name = remapped_object.get("name") or ""
            resolved_pindex = _resolve_global_palette_index(
                material_name=material_name,
                global_slot_names=slot_names,
                fallback_pindex=remapped_object.get("pindex"),
            )
            remapped_object.set("pid", "1")
            remapped_object.set("pindex", str(resolved_pindex))
            combined_object_resources.append(remapped_object)
            part_id_map[original_object_id] = global_mesh_object_id
            global_mesh_object_id += 1
        part_id_maps_by_piece.append(part_id_map)

        root_object = copy.deepcopy(piece_package.root_object)
        root_object.set("id", str(root_object_id))
        root_object.attrib.pop("name", None)
        for component in root_object.findall("m:components/m:component", _NS):
            try:
                local_object_id = int(component.get("objectid", "0"))
            except ValueError as exc:
                raise ValueError("Puzzle piece root object contains invalid component object ID.") from exc
            if local_object_id not in part_id_map:
                raise ValueError("Puzzle piece root object references unknown component object ID.")
            component.set(f"{{{_PROD_NS}}}path", f"/{combined_object_model_path}")
            component.set("objectid", str(part_id_map[local_object_id]))
        combined_resources.append(root_object)

        ET.SubElement(
            combined_build,
            f"{{{_CORE_NS}}}item",
            {
                "objectid": str(root_object_id),
                "printable": "1",
                "transform": _build_translation_transform(
                    piece_package.source.offset_x_mm,
                    piece_package.source.offset_y_mm,
                    0.0,
                ),
            },
        )

    base_files[combined_object_model_path] = _to_xml_bytes(combined_object_model)
    base_files["3D/3dmodel.model"] = _to_xml_bytes(combined_root)
    base_files["3D/_rels/3dmodel.model.rels"] = _build_model_relationships_bytes([combined_object_model_path])
    log.info(
        "Base-layer-height modifier disabled for combined puzzle package",
        extra={"event": "puzzle_base_layer_height_modifier_disabled"},
    )
    writer = BambuStudio3MFWriter(
        output_path="combined-puzzle.3mf",
        settings={},
        color_mode="8-Color",
        printer_id=printer_id,
        slicer=slicer,
        nozzle_size=nozzle_size,
        device_profile_id=device_profile_id,
        enable_base_layer_height_modifier=False,
    )
    _set_root_model_metadata(combined_root, "Application", writer._get_app_version_str())
    _set_root_model_metadata(combined_root, "BambuStudio:3mfVersion", "1")
    base_files["3D/3dmodel.model"] = _to_xml_bytes(combined_root)
    base_files.pop("Metadata/layer_config_ranges.xml", None)
    if writer._should_emit_bambu_aux_parts():
        base_files["Metadata/cut_information.xml"] = _build_cut_information_bytes(len(piece_packages))
    else:
        base_files.pop("Metadata/cut_information.xml", None)
    base_files["Metadata/model_settings.config"] = _build_combined_model_settings_bytes(
        piece_packages=piece_packages,
        root_object_ids=root_object_ids,
        part_id_maps_by_piece=part_id_maps_by_piece,
        global_slot_names=slot_names,
        output_path=output_path,
    )
    base_files["Metadata/project_settings.config"] = _build_combined_project_settings_bytes(
        base_settings_bytes=base_files.get("Metadata/project_settings.config"),
        preview_colors=preview_colors,
        slot_names=slot_names,
        printer_id=printer_id,
        slicer=slicer,
        nozzle_size=nozzle_size,
        device_profile_id=device_profile_id,
    )
    base_files["Metadata/slice_info.config"] = _build_combined_slice_info_bytes(
        printer_id=printer_id,
        slicer=slicer,
        nozzle_size=nozzle_size,
        device_profile_id=device_profile_id,
    )
    _update_combined_filament_sequence(
        base_files=base_files,
        printer_id=printer_id,
        slicer=slicer,
        nozzle_size=nozzle_size,
        device_profile_id=device_profile_id,
    )
    if overview_png_bytes is not None:
        for preview_asset_path in (
            "Metadata/plate_1.png",
            "Metadata/plate_no_light_1.png",
            "Metadata/top_1.png",
            "Metadata/pick_1.png",
        ):
            base_files[preview_asset_path] = overview_png_bytes
    if "[Content_Types].xml" in base_files:
        base_files["[Content_Types].xml"] = _rewrite_content_types_bytes(
            base_files["[Content_Types].xml"],
            [combined_object_model_path],
        )

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in base_files.items():
            archive.writestr(name, data)
    return output_path


def _set_root_model_metadata(root: ET.Element, name: str, value: str) -> None:
    """Set model-level 3MF metadata under the root model element."""
    for metadata_node in root.findall("m:metadata", _NS):
        if metadata_node.get("name") == name:
            metadata_node.text = value
            return
    metadata_node = ET.Element(f"{{{_CORE_NS}}}metadata", attrib={"name": name})
    metadata_node.text = value
    root.insert(0, metadata_node)


def _load_piece_package(piece_source: PuzzlePiece3MFSource) -> _LoadedPiecePackage:
    """Load one generated puzzle-piece 3MF package.
    加载单个已生成的拼图块 3MF 包。

    Args:
        piece_source: Piece source descriptor.
            单块 3MF 的源描述。

    Returns:
        _LoadedPiecePackage: Parsed per-piece package data.
            解析后的单块包数据。

    Raises:
        ValueError: If the package is missing required parts.
            当包缺少必要结构时抛出。
    """

    threemf_path = piece_source.threemf_path
    if not os.path.exists(threemf_path):
        raise ValueError(f"Puzzle piece 3MF not found: {threemf_path}")

    try:
        with zipfile.ZipFile(threemf_path, "r") as archive:
            package_files = {name: archive.read(name) for name in archive.namelist()}
    except (OSError, zipfile.BadZipFile) as exc:
        raise ValueError(f"Failed to open puzzle piece 3MF '{threemf_path}': {exc}") from exc

    try:
        root_model = ET.fromstring(package_files["3D/3dmodel.model"])
    except KeyError as exc:
        raise ValueError(f"Puzzle piece 3MF is missing 3D/3dmodel.model: {threemf_path}") from exc
    except ET.ParseError as exc:
        raise ValueError(f"Failed to parse root model from '{threemf_path}': {exc}") from exc

    root_object = root_model.find("m:resources/m:object", _NS)
    if root_object is None:
        raise ValueError(f"Puzzle piece 3MF has no top-level object: {threemf_path}")

    object_model_path = _resolve_piece_object_model_path(root_object)
    if object_model_path not in package_files:
        raise ValueError(
            f"Puzzle piece 3MF references missing object model '{object_model_path}': {threemf_path}"
        )

    model_settings_object: ET.Element | None = None
    plate_metadata: dict[str, str] = {}
    model_settings_bytes = package_files.get("Metadata/model_settings.config")
    if model_settings_bytes is not None:
        try:
            model_settings_root = ET.fromstring(model_settings_bytes)
        except ET.ParseError as exc:
            raise ValueError(f"Failed to parse model_settings.config from '{threemf_path}': {exc}") from exc
        model_settings_object = model_settings_root.find("object")
        plate_metadata = _extract_plate_metadata(model_settings_root)

    return _LoadedPiecePackage(
        source=piece_source,
        package_files=package_files,
        root_model=root_model,
        root_object=copy.deepcopy(root_object),
        object_model_bytes=package_files[object_model_path],
        model_settings_object=copy.deepcopy(model_settings_object)
        if model_settings_object is not None
        else None,
        plate_metadata=plate_metadata,
    )


def _resolve_piece_object_model_path(root_object: ET.Element) -> str:
    """Resolve the referenced object-model path for one piece root object.
    解析单块根对象引用的 object-model 路径。
    """

    component = root_object.find("m:components/m:component", _NS)
    if component is None:
        return "3D/Objects/object_1.model"

    referenced_path = component.get(f"{{{_PROD_NS}}}path") or "/3D/Objects/object_1.model"
    return referenced_path.lstrip("/")


def _resolve_root_object_start(piece_packages: list[_LoadedPiecePackage]) -> int:
    """Return the starting top-level object ID for the combined package.
    返回组合包顶层对象 ID 的起始值。
    """

    existing_ids: list[int] = []
    for piece_package in piece_packages:
        try:
            existing_ids.append(int(piece_package.root_object.get("id", "10")))
        except ValueError:
            continue
    return max(existing_ids, default=10)


def _clone_empty_root_model(root_model: ET.Element) -> ET.Element:
    """Clone a root 3MF model and remove all resources/build entries.
    复制根 3MF 模型并清空资源与 build 条目。
    """

    normalized_root = copy.deepcopy(root_model)
    resources = normalized_root.find("m:resources", _NS)
    if resources is None:
        raise ValueError("Puzzle root model is missing resources.")
    for object_node in list(resources.findall("m:object", _NS)):
        resources.remove(object_node)

    build_node = normalized_root.find("m:build", _NS)
    if build_node is None:
        build_node = ET.SubElement(normalized_root, f"{{{_CORE_NS}}}build")
    else:
        for build_item in list(build_node.findall("m:item", _NS)):
            build_node.remove(build_item)
    return normalized_root


def _build_combined_model_settings_bytes(
    piece_packages: list[_LoadedPiecePackage],
    root_object_ids: list[int],
    part_id_maps_by_piece: list[dict[int, int]],
    global_slot_names: list[str] | None,
    output_path: str,
) -> bytes:
    """Build combined Bambu ``model_settings.config`` from per-piece packages.
    基于单块 3MF 包构建组合后的 Bambu ``model_settings.config``。
    """

    config = ET.Element("config")
    source_file = os.path.basename(output_path)

    for piece_package, root_object_id, part_id_map in zip(
        piece_packages,
        root_object_ids,
        part_id_maps_by_piece,
    ):
        if piece_package.model_settings_object is not None:
            object_node = copy.deepcopy(piece_package.model_settings_object)
        else:
            object_node = ET.Element("object")
            ET.SubElement(object_node, "metadata", attrib={"key": "extruder", "value": "1"})

        object_node.set("id", str(root_object_id))
        _set_object_metadata(object_node, "name", piece_package.source.label)
        _set_object_metadata(object_node, "extruder", _get_object_metadata(object_node, "extruder") or "1")
        for part_node in object_node.findall("part"):
            try:
                original_part_id = int(part_node.get("id", "0"))
            except ValueError as exc:
                raise ValueError("Puzzle piece model settings contain invalid part ID.") from exc
            if original_part_id not in part_id_map:
                raise ValueError("Puzzle piece model settings reference unknown part ID.")
            part_node.set("id", str(part_id_map[original_part_id]))
            _set_part_metadata(part_node, "source_file", source_file)
            material_name = _get_part_metadata(part_node, "name") or ""
            resolved_extruder = _resolve_global_material_extruder(
                material_name=material_name,
                global_slot_names=global_slot_names,
                fallback_extruder=_get_part_metadata(part_node, "extruder"),
            )
            _set_part_metadata(part_node, "extruder", str(resolved_extruder))
        config.append(object_node)

    plate_node = ET.SubElement(config, "plate")
    plate_metadata = piece_packages[0].plate_metadata or _extract_plate_metadata(ET.Element("config"))
    for key, value in plate_metadata.items():
        ET.SubElement(plate_node, "metadata", attrib={"key": key, "value": value})
    for index, root_object_id in enumerate(root_object_ids, start=1):
        instance_node = ET.SubElement(plate_node, "model_instance")
        ET.SubElement(instance_node, "metadata", attrib={"key": "object_id", "value": str(root_object_id)})
        ET.SubElement(instance_node, "metadata", attrib={"key": "instance_id", "value": "0"})
        ET.SubElement(instance_node, "metadata", attrib={"key": "identify_id", "value": str(index)})

    assemble_node = ET.SubElement(config, "assemble")
    for piece_package, root_object_id in zip(piece_packages, root_object_ids):
        ET.SubElement(
            assemble_node,
            "assemble_item",
            attrib={
                "object_id": str(root_object_id),
                "instance_id": "0",
                "transform": _build_translation_transform(
                    piece_package.source.offset_x_mm,
                    piece_package.source.offset_y_mm,
                    0.0,
                ),
                "offset": "0 0 0",
            },
        )

    tree = ET.ElementTree(config)
    ET.indent(tree, space="  ")
    buffer = io.BytesIO()
    buffer.write(b'<?xml version="1.0" encoding="UTF-8"?>\n')
    tree.write(buffer, encoding="utf-8", xml_declaration=False)
    return buffer.getvalue()


def _build_combined_project_settings_bytes(
    base_settings_bytes: bytes | None,
    preview_colors: dict[object, object] | None,
    slot_names: list[str] | None,
    printer_id: str,
    slicer: str,
    nozzle_size: str,
    device_profile_id: str | None,
) -> bytes:
    """Build combined ``project_settings.config`` with a stable global palette.

    构建组合后的 ``project_settings.config``，并使用稳定的全局耗材调色板。
    """

    material_names = [str(name) for name in (slot_names or []) if str(name)]
    if not material_names:
        if base_settings_bytes is None:
            raise ValueError("Combined puzzle 3MF is missing project settings metadata.")
        return base_settings_bytes

    if base_settings_bytes is not None:
        try:
            settings = json.loads(base_settings_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"Failed to parse puzzle project settings: {exc}") from exc
    else:
        writer = BambuStudio3MFWriter(
            output_path="combined-puzzle.3mf",
            settings={},
            color_mode="8-Color",
            printer_id=printer_id,
            slicer=slicer,
            nozzle_size=nozzle_size,
            device_profile_id=device_profile_id,
            enable_base_layer_height_modifier=False,
        )
        settings = writer._get_base_config_template()

    num_colors = len(material_names)
    _resize_project_settings_arrays(settings, num_colors)

    settings["filament_colour"] = [
        _rgb_to_hex(
            _resolve_preview_rgb_for_material_name(
                material_name=material_name,
                material_index=index,
                preview_colors=preview_colors,
                existing_hex=settings.get("filament_colour", []),
            )
        )
        for index, material_name in enumerate(material_names)
    ]

    settings.setdefault("single_extruder_multi_material", "1")
    settings.setdefault("enable_prime_tower", "1")
    return json.dumps(settings, indent=4, ensure_ascii=False).encode("utf-8")


def _build_combined_slice_info_bytes(
    *,
    printer_id: str,
    slicer: str,
    nozzle_size: str,
    device_profile_id: str | None,
) -> bytes:
    """Build fresh ``slice_info.config`` bytes for the combined package.

    为组合包构建新的 ``slice_info.config`` 元数据。
    """

    writer = BambuStudio3MFWriter(
        output_path="combined-puzzle.3mf",
        settings={},
        color_mode="8-Color",
        printer_id=printer_id,
        slicer=slicer,
        nozzle_size=nozzle_size,
        device_profile_id=device_profile_id,
        enable_base_layer_height_modifier=False,
    )
    return writer._build_slice_info_bytes()


def _update_combined_filament_sequence(
    *,
    base_files: dict[str, bytes],
    printer_id: str,
    slicer: str,
    nozzle_size: str,
    device_profile_id: str | None,
) -> None:
    """Refresh slicer-specific filament-sequence metadata for the combined package.

    为组合包刷新切片器相关的 filament-sequence 元数据。
    """

    writer = BambuStudio3MFWriter(
        output_path="combined-puzzle.3mf",
        settings={},
        color_mode="8-Color",
        printer_id=printer_id,
        slicer=slicer,
        nozzle_size=nozzle_size,
        device_profile_id=device_profile_id,
        enable_base_layer_height_modifier=False,
    )
    if not writer._should_emit_bambu_aux_parts():
        base_files.pop("Metadata/filament_sequence.json", None)
        return
    base_files["Metadata/filament_sequence.json"] = writer._build_filament_sequence_bytes()


def _resize_project_settings_arrays(settings: dict[str, object], num_colors: int) -> None:
    """Resize per-filament settings arrays to match the shared material count.

    将按耗材槽位存储的设置数组调整为与共享调色板长度一致。
    """

    resizable_array_keys = frozenset(
        {
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
        }
    )

    for key, value in list(settings.items()):
        if not isinstance(value, list) or not value:
            continue
        if key.startswith("filament_") or key in resizable_array_keys:
            if len(value) != num_colors:
                settings[key] = [value[0]] * num_colors


def _resolve_preview_rgb_for_material_name(
    material_name: str,
    material_index: int,
    preview_colors: dict[object, object] | None,
    existing_hex: list[object],
) -> tuple[int, int, int]:
    """Resolve the RGB color for one global material name.

    为全局材料名称解析 RGB 颜色。
    """

    normalized_preview = preview_colors or {}
    if material_name in normalized_preview:
        return _coerce_rgb_tuple(normalized_preview[material_name])

    slot_number = _slot_number_from_material_name(material_name)
    if slot_number is not None:
        slot_key = slot_number - 1
        if slot_key in normalized_preview:
            return _coerce_rgb_tuple(normalized_preview[slot_key])
        slot_key_str = str(slot_key)
        if slot_key_str in normalized_preview:
            return _coerce_rgb_tuple(normalized_preview[slot_key_str])

    if material_index in normalized_preview:
        return _coerce_rgb_tuple(normalized_preview[material_index])
    material_index_str = str(material_index)
    if material_index_str in normalized_preview:
        return _coerce_rgb_tuple(normalized_preview[material_index_str])

    if material_index < len(existing_hex):
        existing_value = existing_hex[material_index]
        if isinstance(existing_value, str) and re.fullmatch(r"#[0-9A-Fa-f]{6}", existing_value):
            return (
                int(existing_value[1:3], 16),
                int(existing_value[3:5], 16),
                int(existing_value[5:7], 16),
            )

    return (200, 200, 200)


def _resolve_global_material_extruder(
    material_name: str,
    global_slot_names: list[str] | None,
    fallback_extruder: str | None,
) -> int:
    """Resolve a part's global extruder index for the combined 3MF.

    为组合 3MF 解析 part 应使用的全局挤出机槽位编号。
    """

    normalized_slots = [str(name) for name in (global_slot_names or []) if str(name)]
    if material_name and material_name in normalized_slots:
        return normalized_slots.index(material_name) + 1

    slot_number = _slot_number_from_material_name(material_name)
    if slot_number is not None:
        return slot_number

    if fallback_extruder is not None:
        try:
            return int(fallback_extruder)
        except ValueError:
            pass
    return 1


def _resolve_global_palette_index(
    material_name: str,
    global_slot_names: list[str] | None,
    fallback_pindex: str | None,
) -> int:
    """Resolve the 0-based shared palette index for one mesh object.

    为单个 mesh 对象解析 0-based 的共享调色板索引。
    """

    normalized_slots = [str(name) for name in (global_slot_names or []) if str(name)]
    if material_name and material_name in normalized_slots:
        return normalized_slots.index(material_name)

    slot_number = _slot_number_from_material_name(material_name)
    if slot_number is not None:
        return slot_number - 1

    if fallback_pindex is not None:
        try:
            return int(fallback_pindex)
        except ValueError:
            pass
    return 0


def _slot_number_from_material_name(material_name: str) -> int | None:
    """Extract a 1-based slot number from a material label when present.

    从材料标签中提取 1-based 槽位编号。
    """

    match = re.match(r"Slot\s+(\d+)\b", material_name)
    if match is None:
        return None
    return int(match.group(1))


def _coerce_rgb_tuple(value: object) -> tuple[int, int, int]:
    """Coerce a color-like value into an RGB tuple.

    将颜色值转换为 RGB 元组。
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


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    """Convert RGB channels to a stable hex color string.

    将 RGB 通道转换为稳定的十六进制颜色字符串。
    """

    return f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"


def _build_translation_transform(offset_x_mm: float, offset_y_mm: float, offset_z_mm: float) -> str:
    """Build a 3MF translation transform string.
    构建 3MF 平移变换字符串。
    """

    return (
        "1 0 0 0 1 0 0 0 1 "
        f"{_format_float(offset_x_mm)} {_format_float(offset_y_mm)} {_format_float(offset_z_mm)}"
    )


def _format_float(value: float) -> str:
    """Format a float for stable XML output.
    将浮点数格式化为稳定的 XML 输出字符串。
    """

    return format(float(value), ".15g")


def _load_piece_mesh_entries(threemf_path: str) -> list[_PieceMeshEntry]:
    """Load mesh entries from a per-piece 3MF file.
    从单块 3MF 文件中加载网格条目。

    Args:
        threemf_path: Source 3MF path.
            源 3MF 路径。

    Returns:
        list[_PieceMeshEntry]: Parsed mesh entries.
            解析得到的网格条目列表。

    Raises:
        ValueError: If the 3MF file structure is invalid.
            当 3MF 结构无效时抛出。
    """

    if not os.path.exists(threemf_path):
        raise ValueError(f"Puzzle piece 3MF not found: {threemf_path}")

    entries: list[_PieceMeshEntry] = []
    try:
        with zipfile.ZipFile(threemf_path) as archive:
            object_model_names = sorted(
                name
                for name in archive.namelist()
                if name.startswith("3D/Objects/") and name.endswith(".model")
            )
            if not object_model_names:
                raise ValueError(f"Puzzle piece 3MF has no object model: {threemf_path}")

            for model_name in object_model_names:
                model_xml = archive.read(model_name)
                model_root = ET.fromstring(model_xml)
                for object_node in model_root.findall("m:resources/m:object", _NS):
                    mesh_node = object_node.find("m:mesh", _NS)
                    if mesh_node is None:
                        continue

                    mesh = _parse_mesh_node(mesh_node)
                    if mesh is None:
                        continue

                    material_name = object_node.get("name") or f"Object_{object_node.get('id', '0')}"
                    entries.append(_PieceMeshEntry(material_name=material_name, mesh=mesh))
    except (OSError, zipfile.BadZipFile, ET.ParseError) as exc:
        raise ValueError(f"Failed to parse puzzle piece 3MF '{threemf_path}': {exc}") from exc

    return entries


def _parse_mesh_node(mesh_node: ET.Element) -> trimesh.Trimesh | None:
    """Parse a 3MF ``<mesh>`` node into a Trimesh object.
    将 3MF 的 ``<mesh>`` 节点解析为 Trimesh 对象。

    Args:
        mesh_node: XML mesh node.
            XML 网格节点。

    Returns:
        trimesh.Trimesh | None: Parsed mesh, or ``None`` if empty.
            解析后的网格；若为空则返回 ``None``。
    """

    vertices: list[tuple[float, float, float]] = []
    for vertex in mesh_node.findall("m:vertices/m:vertex", _NS):
        vertices.append(
            (
                float(vertex.get("x", "0")),
                float(vertex.get("y", "0")),
                float(vertex.get("z", "0")),
            )
        )

    faces: list[tuple[int, int, int]] = []
    for triangle in mesh_node.findall("m:triangles/m:triangle", _NS):
        faces.append(
            (
                int(triangle.get("v1", "0")),
                int(triangle.get("v2", "0")),
                int(triangle.get("v3", "0")),
            )
        )

    if not vertices or not faces:
        return None

    return trimesh.Trimesh(
        vertices=np.asarray(vertices, dtype=np.float64),
        faces=np.asarray(faces, dtype=np.int64),
        process=False,
    )


def _resolve_material_rgba(
    material_name: str,
    preview_colors: dict[object, object] | None,
    slot_names: list[str] | None,
) -> tuple[int, int, int, int]:
    """Resolve export RGBA for a material or auxiliary mesh name.
    为材质名或辅助对象名解析导出颜色。

    Args:
        material_name: Scene geometry/material name.
            场景几何或材质名称。
        preview_colors: Preview color mapping from cache.
            来自缓存的预览颜色映射。
        slot_names: Slot-name list corresponding to material indices.
            与材质索引对应的槽位名称列表。

    Returns:
        tuple[int, int, int, int]: RGBA tuple.
            RGBA 颜色元组。
    """

    normalized_slots = slot_names or []
    normalized_preview = preview_colors or {}

    if material_name in normalized_preview:
        return _coerce_rgba_tuple(normalized_preview[material_name])

    if material_name in normalized_slots:
        slot_index = normalized_slots.index(material_name)
        if slot_index in normalized_preview:
            return _coerce_rgba_tuple(normalized_preview[slot_index])

    if material_name in {"Backing", "Outline", "Keychain_Loop"}:
        if normalized_slots:
            base_slot = normalized_slots[0]
            if base_slot in normalized_preview:
                return _coerce_rgba_tuple(normalized_preview[base_slot])
        if 0 in normalized_preview:
            return _coerce_rgba_tuple(normalized_preview[0])
        return (255, 255, 255, 255)

    if material_name == "Wire":
        return (218, 165, 32, 255)

    if material_name == "Coating":
        return (200, 200, 200, 255)

    if material_name.startswith("Free_") and len(material_name) >= 11:
        hex_value = material_name.split("_", 1)[1]
        try:
            return (
                int(hex_value[0:2], 16),
                int(hex_value[2:4], 16),
                int(hex_value[4:6], 16),
                255,
            )
        except ValueError:
            pass

    log.debug("Puzzle 3MF color fallback for material '%s'", material_name)
    return (200, 200, 200, 255)


def _coerce_rgba_tuple(value: object) -> tuple[int, int, int, int]:
    """Coerce a preview-color value into an RGBA tuple.
    将预览颜色值转换为 RGBA 元组。
    """

    if isinstance(value, np.ndarray):
        array = value.tolist()
    elif isinstance(value, (list, tuple)):
        array = list(value)
    else:
        raise ValueError(f"Unsupported preview color value: {type(value)!r}")

    if len(array) == 3:
        array.append(255)
    if len(array) < 4:
        raise ValueError("Preview color value must have at least 3 channels.")
    return tuple(int(channel) for channel in array[:4])


def _group_piece_objects_in_3mf(output_path: str, piece_order: list[str]) -> None:
    """Rewrite a combined 3MF into one top-level object per puzzle piece.
    将组合后的 3MF 重写为“每个拼图块一个顶层对象”的结构。

    Args:
        output_path: Combined 3MF file path. (合并后的 3MF 文件路径)
        piece_order: Preferred user-facing piece order. (优先使用的拼图块排序)
    """

    if not os.path.exists(output_path):
        raise ValueError(f"Combined puzzle 3MF not found: {output_path}")

    ET.register_namespace("", _CORE_NS)
    ET.register_namespace("p", _PROD_NS)
    ET.register_namespace("BambuStudio", _BAMBU_NS)

    try:
        with zipfile.ZipFile(output_path, "r") as archive:
            files_data = {name: archive.read(name) for name in archive.namelist()}
    except (OSError, zipfile.BadZipFile) as exc:
        raise ValueError(f"Failed to open combined puzzle 3MF '{output_path}': {exc}") from exc

    root_model_path = "3D/3dmodel.model"
    model_settings_path = "Metadata/model_settings.config"
    cut_information_path = "Metadata/cut_information.xml"
    object_model_paths = sorted(
        name
        for name in files_data
        if name.startswith("3D/Objects/object_") and name.endswith(".model")
    )
    if root_model_path not in files_data or not object_model_paths:
        raise ValueError("Combined puzzle 3MF is missing expected model parts.")

    try:
        root_model = ET.fromstring(files_data[root_model_path])
        object_model = ET.fromstring(files_data[object_model_paths[0]])
    except ET.ParseError as exc:
        raise ValueError(f"Failed to parse combined puzzle 3MF XML: {exc}") from exc

    object_resources = object_model.find("m:resources", _NS)
    if object_resources is None:
        raise ValueError("Combined puzzle object model is missing resources.")

    mesh_objects = [
        object_node
        for object_node in object_resources.findall("m:object", _NS)
        if object_node.find("m:mesh", _NS) is not None
    ]
    if not mesh_objects:
        raise ValueError("Combined puzzle object model has no mesh objects.")

    piece_groups: dict[str, list[_PieceObjectEntry]] = {}
    object_templates: dict[int, ET.Element] = {}
    for object_node in mesh_objects:
        object_id = int(object_node.get("id", "0"))
        object_name = object_node.get("name") or f"Object_{object_id}"
        piece_label, material_name = _split_piece_object_name(object_name)
        object_templates[object_id] = copy.deepcopy(object_node)
        piece_groups.setdefault(piece_label, []).append(
            _PieceObjectEntry(object_id=object_id, material_name=material_name)
        )

    ordered_piece_labels = _resolve_piece_labels(piece_groups, piece_order)
    if not ordered_piece_labels:
        raise ValueError("Combined puzzle 3MF has no grouped piece labels.")

    root_resources = root_model.find("m:resources", _NS)
    build_node = root_model.find("m:build", _NS)
    if root_resources is None or build_node is None:
        raise ValueError("Combined puzzle root model is missing resources or build nodes.")

    max_existing_id = max(
        int(object_node.get("id", "0"))
        for object_node in mesh_objects
    )
    next_piece_object_id = max_existing_id + 1
    piece_object_ids: dict[str, int] = {}

    for object_node in list(root_resources.findall("m:object", _NS)):
        root_resources.remove(object_node)
    for build_item in list(build_node.findall("m:item", _NS)):
        build_node.remove(build_item)

    for stale_model_path in object_model_paths:
        files_data.pop(stale_model_path, None)

    piece_model_paths: dict[str, str] = {}
    for piece_index, piece_label in enumerate(ordered_piece_labels, start=1):
        piece_object_id = next_piece_object_id
        next_piece_object_id += 1
        piece_object_ids[piece_label] = piece_object_id
        piece_model_path = f"3D/Objects/object_{piece_index}.model"
        piece_model_paths[piece_label] = piece_model_path
        ordered_entries = sorted(piece_groups[piece_label], key=_piece_entry_sort_key)
        piece_model_root = _clone_empty_object_model_root(object_model)
        piece_model_resources = piece_model_root.find("m:resources", _NS)
        if piece_model_resources is None:
            raise ValueError("Combined puzzle object model is missing resources.")

        root_object = ET.SubElement(
            root_resources,
            f"{{{_CORE_NS}}}object",
            {
                "id": str(piece_object_id),
                "name": piece_label,
                "type": "model",
            },
        )
        components_node = ET.SubElement(root_object, f"{{{_CORE_NS}}}components")
        for local_object_id, entry in enumerate(ordered_entries, start=1):
            piece_object_node = copy.deepcopy(object_templates[entry.object_id])
            piece_object_node.set("id", str(local_object_id))
            piece_object_node.attrib.pop("name", None)
            piece_object_node.attrib.pop("pid", None)
            piece_object_node.attrib.pop("pindex", None)
            piece_model_resources.append(piece_object_node)
            ET.SubElement(
                components_node,
                f"{{{_CORE_NS}}}component",
                {
                    f"{{{_PROD_NS}}}path": f"/{piece_model_path}",
                    "objectid": str(local_object_id),
                },
            )

        files_data[piece_model_path] = _to_xml_bytes(piece_model_root)
        ET.SubElement(
            build_node,
            f"{{{_CORE_NS}}}item",
            {
                "objectid": str(piece_object_id),
                "printable": "1",
                "transform": "1 0 0 0 1 0 0 0 1 0 0 0",
            },
        )

    if model_settings_path in files_data:
        files_data[model_settings_path] = _rewrite_model_settings_bytes(
            files_data[model_settings_path],
            piece_groups,
            piece_object_ids,
            ordered_piece_labels,
            output_path,
        )

    files_data["3D/_rels/3dmodel.model.rels"] = _build_model_relationships_bytes(
        [piece_model_paths[label] for label in ordered_piece_labels]
    )
    files_data[cut_information_path] = _build_cut_information_bytes(len(ordered_piece_labels))
    files_data[root_model_path] = _to_xml_bytes(root_model)

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files_data.items():
            archive.writestr(name, data)


def _rewrite_model_settings_bytes(
    model_settings_bytes: bytes,
    piece_groups: dict[str, list[_PieceObjectEntry]],
    piece_object_ids: dict[str, int],
    ordered_piece_labels: list[str],
    output_path: str,
) -> bytes:
    """Rewrite Bambu model settings so each puzzle piece is its own object.
    重写 Bambu 的 model settings，使每个拼图块都有独立对象元数据。
    """

    try:
        existing_root = ET.fromstring(model_settings_bytes)
    except ET.ParseError as exc:
        raise ValueError(f"Failed to parse model_settings.config: {exc}") from exc

    part_templates: dict[int, ET.Element] = {}
    for part_node in existing_root.findall(".//part"):
        try:
            part_id = int(part_node.get("id", "0"))
        except ValueError:
            continue
        part_templates[part_id] = copy.deepcopy(part_node)

    plate_metadata = _extract_plate_metadata(existing_root)
    config = ET.Element("config")
    source_file = os.path.basename(output_path)

    for piece_label in ordered_piece_labels:
        object_id = piece_object_ids[piece_label]
        object_node = ET.SubElement(config, "object", attrib={"id": str(object_id)})
        ET.SubElement(object_node, "metadata", attrib={"key": "name", "value": piece_label})
        ET.SubElement(object_node, "metadata", attrib={"key": "extruder", "value": "1"})

        total_face_count = 0
        ordered_entries = sorted(
            piece_groups[piece_label],
            key=lambda entry: _piece_part_sort_key(entry, part_templates),
        )
        for part_index, entry in enumerate(ordered_entries, start=1):
            template = part_templates.get(entry.object_id)
            extruder_index = _resolve_material_extruder(
                material_name=entry.material_name,
                template=template,
                fallback_extruder=part_index,
            )
            part_node = _build_grouped_part_node(
                template=template,
                part_index=part_index,
                material_name=entry.material_name,
                extruder_index=extruder_index,
                source_file=source_file,
                source_volume_id=part_index - 1,
            )
            total_face_count += _get_part_face_count(part_node)
            object_node.append(part_node)

        if total_face_count > 0:
            ET.SubElement(object_node, "metadata", attrib={"face_count": str(total_face_count)})

    plate_node = ET.SubElement(config, "plate")
    for key, value in plate_metadata.items():
        ET.SubElement(plate_node, "metadata", attrib={"key": key, "value": value})
    for index, piece_label in enumerate(ordered_piece_labels, start=1):
        instance_node = ET.SubElement(plate_node, "model_instance")
        ET.SubElement(
            instance_node,
            "metadata",
            attrib={"key": "object_id", "value": str(piece_object_ids[piece_label])},
        )
        ET.SubElement(instance_node, "metadata", attrib={"key": "instance_id", "value": "0"})
        ET.SubElement(instance_node, "metadata", attrib={"key": "identify_id", "value": str(index)})

    assemble_node = ET.SubElement(config, "assemble")
    for piece_label in ordered_piece_labels:
        ET.SubElement(
            assemble_node,
            "assemble_item",
            attrib={
                "object_id": str(piece_object_ids[piece_label]),
                "instance_id": "0",
                "transform": "1 0 0 0 1 0 0 0 1 0 0 0",
                "offset": "0 0 0",
            },
        )

    tree = ET.ElementTree(config)
    ET.indent(tree, space="  ")
    buffer = io.BytesIO()
    buffer.write(b'<?xml version="1.0" encoding="UTF-8"?>\n')
    tree.write(buffer, encoding="utf-8", xml_declaration=False)
    return buffer.getvalue()


def _build_grouped_part_node(
    template: ET.Element | None,
    part_index: int,
    material_name: str,
    extruder_index: int,
    source_file: str,
    source_volume_id: int,
) -> ET.Element:
    """Create one grouped part node for puzzle model settings.
    为拼图 model settings 创建单个 grouped part 节点。
    """

    if template is not None:
        part_node = copy.deepcopy(template)
        part_node.set("id", str(part_index))
    else:
        part_node = ET.Element("part", attrib={"id": str(part_index), "subtype": "normal_part"})
        ET.SubElement(part_node, "mesh_stat", attrib={"face_count": "0"})

    _set_part_metadata(part_node, "name", material_name)
    _set_part_metadata(part_node, "source_file", source_file)
    _set_part_metadata(part_node, "source_object_id", "0")
    _set_part_metadata(part_node, "source_volume_id", str(source_volume_id))
    _set_part_metadata(part_node, "extruder", str(extruder_index))
    return part_node


def _piece_part_sort_key(
    entry: _PieceObjectEntry,
    part_templates: dict[int, ET.Element],
) -> tuple[int, str, int]:
    """Return a stable sort key for grouped puzzle parts.

    返回拼图分组 part 的稳定排序键。
    """

    template = part_templates.get(entry.object_id)
    extruder_index = _resolve_material_extruder(
        material_name=entry.material_name,
        template=template,
        fallback_extruder=10**6,
    )
    return (extruder_index, entry.material_name, entry.object_id)


def _resolve_material_extruder(
    material_name: str,
    template: ET.Element | None,
    fallback_extruder: int,
) -> int:
    """Resolve the shared extruder index for one grouped material.

    解析分组材料应使用的共享挤出机槽位编号。
    """

    slot_number = _slot_number_from_material_name(material_name)
    if slot_number is not None:
        return slot_number

    if template is not None:
        extruder_value = _get_part_metadata(template, "extruder")
        if extruder_value is not None:
            try:
                return int(extruder_value)
            except ValueError:
                pass

    return fallback_extruder


def _extract_plate_metadata(root: ET.Element) -> dict[str, str]:
    """Extract reusable plate metadata from an existing model_settings tree.
    从现有 model_settings 树中提取可复用的 plate 元数据。
    """

    defaults = {
        "plater_id": "1",
        "plater_name": "",
        "locked": "false",
        "filament_map_mode": "Auto For Flush",
        "thumbnail_file": "Metadata/plate_1.png",
        "thumbnail_no_light_file": "Metadata/plate_no_light_1.png",
        "top_file": "Metadata/top_1.png",
        "pick_file": "Metadata/pick_1.png",
    }
    plate_node = root.find("plate")
    if plate_node is None:
        return defaults

    extracted = defaults.copy()
    for metadata_node in plate_node.findall("metadata"):
        key = metadata_node.get("key")
        value = metadata_node.get("value")
        if key and value is not None:
            extracted[key] = value
    return extracted


def _split_piece_object_name(object_name: str) -> tuple[str, str]:
    """Split a combined scene object name into piece label and material name.
    将组合场景对象名拆分为拼图块标签与材质名。
    """

    piece_label, separator, material_name = object_name.partition("__")
    if separator:
        return piece_label, material_name or piece_label
    return object_name, object_name


def _resolve_piece_labels(
    piece_groups: dict[str, list[_PieceObjectEntry]],
    piece_order: list[str],
) -> list[str]:
    """Resolve final piece-label order with user order preferred first.
    解析最终的拼图块顺序，优先使用用户提供的顺序。
    """

    ordered_labels: list[str] = []
    seen: set[str] = set()
    for label in piece_order:
        if label in piece_groups and label not in seen:
            ordered_labels.append(label)
            seen.add(label)

    remaining = sorted(
        (label for label in piece_groups if label not in seen),
        key=_piece_label_sort_key,
    )
    ordered_labels.extend(remaining)
    return ordered_labels


def _piece_label_sort_key(label: str) -> tuple[int, int, str]:
    """Return a natural sort key for labels like ``A1`` and ``AA12``.
    返回 ``A1``、``AA12`` 这类标签的自然排序键。
    """

    match = re.fullmatch(r"([A-Z]+)(\d+)", label)
    if match is None:
        return (10**9, 10**9, label)

    letters = match.group(1)
    col_value = int(match.group(2))
    row_value = 0
    for char in letters:
        row_value = row_value * 26 + (ord(char) - ord("A") + 1)
    return (row_value, col_value, label)


def _get_part_metadata(part_node: ET.Element, key: str) -> str | None:
    """Read one metadata value from a part node.
    读取 part 节点上的单个 metadata 值。
    """

    for metadata_node in part_node.findall("metadata"):
        if metadata_node.get("key") == key:
            return metadata_node.get("value")
    return None


def _get_object_metadata(object_node: ET.Element, key: str) -> str | None:
    """Read one metadata value from an object node.
    读取 object 节点上的单个 metadata 值。
    """

    for metadata_node in object_node.findall("metadata"):
        if metadata_node.get("key") == key:
            return metadata_node.get("value")
    return None


def _set_object_metadata(object_node: ET.Element, key: str, value: str) -> None:
    """Set or create one metadata key/value under an object node.
    设置或创建 object 节点下的单个 metadata 键值。
    """

    for metadata_node in object_node.findall("metadata"):
        if metadata_node.get("key") == key:
            metadata_node.set("value", value)
            return
    ET.SubElement(object_node, "metadata", attrib={"key": key, "value": value})


def _set_part_metadata(part_node: ET.Element, key: str, value: str) -> None:
    """Set or create one metadata key/value under a part node.
    设置或创建 part 节点下的单个 metadata 键值。
    """

    for metadata_node in part_node.findall("metadata"):
        if metadata_node.get("key") == key:
            metadata_node.set("value", value)
            return
    ET.SubElement(part_node, "metadata", attrib={"key": key, "value": value})


def _get_part_face_count(part_node: ET.Element) -> int:
    """Return the face_count declared under a part node if present.
    返回 part 节点下声明的 face_count，若无则返回 0。
    """

    mesh_stat = part_node.find("mesh_stat")
    if mesh_stat is None:
        return 0
    try:
        return int(mesh_stat.get("face_count", "0"))
    except ValueError:
        return 0


def _to_xml_bytes(root: ET.Element) -> bytes:
    """Serialize an XML tree to UTF-8 bytes with declaration.
    将 XML 树序列化为带声明头的 UTF-8 字节串。
    """

    ET.register_namespace("", _CORE_NS)
    ET.register_namespace("p", _PROD_NS)
    ET.register_namespace("BambuStudio", _BAMBU_NS)
    tree = ET.ElementTree(root)
    buffer = bytearray()
    buffer.extend(b'<?xml version="1.0" encoding="UTF-8"?>\n')
    import io

    byte_stream = io.BytesIO()
    tree.write(byte_stream, encoding="utf-8", xml_declaration=False)
    buffer.extend(byte_stream.getvalue())
    return bytes(buffer)


def _clone_empty_object_model_root(object_model: ET.Element) -> ET.Element:
    """Clone an object-model root and strip mesh resources/build items.

    复制 object-model 根节点并清空其中的网格资源与 build 项。
    """

    normalized_root = copy.deepcopy(object_model)
    resources = normalized_root.find("m:resources", _NS)
    if resources is None:
        raise ValueError("Combined puzzle object model is missing resources.")

    for object_node in list(resources.findall("m:object", _NS)):
        resources.remove(object_node)

    build_node = normalized_root.find("m:build", _NS)
    if build_node is None:
        build_node = ET.SubElement(normalized_root, f"{{{_CORE_NS}}}build")
    else:
        for build_item in list(build_node):
            build_node.remove(build_item)

    return normalized_root


def _build_model_relationships_bytes(object_model_paths: list[str]) -> bytes:
    """Build root-model relationship XML for grouped puzzle object models.

    为拼图分组 object-model 构建根模型关系文件。
    """

    relationships = ET.Element(
        "Relationships",
        attrib={"xmlns": "http://schemas.openxmlformats.org/package/2006/relationships"},
    )
    for index, object_model_path in enumerate(object_model_paths, start=1):
        ET.SubElement(
            relationships,
            "Relationship",
            attrib={
                "Target": f"/{object_model_path}",
                "Id": f"rel-{index}",
                "Type": "http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel",
            },
        )

    tree = ET.ElementTree(relationships)
    ET.indent(tree, space=" ")
    buffer = io.BytesIO()
    buffer.write(b'<?xml version="1.0" encoding="UTF-8"?>\n')
    tree.write(buffer, encoding="utf-8", xml_declaration=False)
    return buffer.getvalue()


def _rewrite_content_types_bytes(content_types_bytes: bytes, object_model_paths: list[str]) -> bytes:
    """Ensure all external object-model parts are declared in ``[Content_Types].xml``.
    确保所有外部 object-model part 都在 ``[Content_Types].xml`` 中声明。

    Args:
        content_types_bytes: Existing content-types XML bytes.
            现有 content-types XML 字节。
        object_model_paths: Object-model part paths without leading slash.
            不带前导斜杠的 object-model part 路径。

    Returns:
        bytes: Rewritten content-types XML bytes.
            重写后的 content-types XML 字节。
    """

    content_type_value = "application/vnd.ms-package.3dmanufacturing-3dmodel+xml"
    content_types_ns = "http://schemas.openxmlformats.org/package/2006/content-types"
    override_tag = f"{{{content_types_ns}}}Override"

    try:
        root = ET.fromstring(content_types_bytes)
    except ET.ParseError as exc:
        raise ValueError(f"Failed to parse [Content_Types].xml: {exc}") from exc

    declared_parts = {
        override.get("PartName")
        for override in root.findall(override_tag)
    }
    for object_model_path in object_model_paths:
        part_name = f"/{object_model_path}"
        if part_name in declared_parts:
            continue
        ET.SubElement(
            root,
            override_tag,
            attrib={
                "PartName": part_name,
                "ContentType": content_type_value,
            },
        )

    ET.register_namespace("", content_types_ns)
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    buffer = io.BytesIO()
    buffer.write(b'<?xml version="1.0" encoding="UTF-8"?>\n')
    tree.write(buffer, encoding="utf-8", xml_declaration=False)
    return buffer.getvalue()


def _build_cut_information_bytes(object_count: int) -> bytes:
    """Build cut-information metadata for grouped puzzle objects.

    为拼图分组对象构建 cut-information 元数据。

    Args:
        object_count: Number of top-level puzzle objects.
            （顶层拼图对象数量）

    Returns:
        bytes: Serialized ``cut_information.xml`` bytes.
            （序列化后的 ``cut_information.xml`` 字节）
    """

    objects_node = ET.Element("objects")
    for object_index in range(1, max(object_count, 1) + 1):
        object_node = ET.SubElement(objects_node, "object", attrib={"id": str(object_index)})
        ET.SubElement(
            object_node,
            "cut_id",
            attrib={"id": "0", "check_sum": "1", "connectors_cnt": "0"},
        )

    tree = ET.ElementTree(objects_node)
    ET.indent(tree, space=" ")
    buffer = io.BytesIO()
    buffer.write(b'<?xml version="1.0" encoding="utf-8"?>\n')
    tree.write(buffer, encoding="utf-8", xml_declaration=False)
    return buffer.getvalue()


def _piece_entry_sort_key(entry: _PieceObjectEntry) -> tuple[int, str, int]:
    """Return the stable local object order inside one puzzle piece model.

    返回单个拼图块内部的稳定局部对象排序。
    """

    slot_match = re.match(r"Slot\s+(\d+)\b", entry.material_name)
    if slot_match is not None:
        return (int(slot_match.group(1)), entry.material_name, entry.object_id)
    return (10**9, entry.material_name, entry.object_id)
