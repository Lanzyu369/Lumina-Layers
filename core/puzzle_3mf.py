"""Puzzle 3MF assembly helpers.
拼图模式 3MF 组装辅助工具。

This module converts multiple per-piece 3MF files into a single combined 3MF
that preserves per-piece placement and groups each puzzle piece as a distinct
object in the final package.
本模块用于将多个单块 3MF 组合为一个统一的 3MF，并保留每块拼图的全局位置，
同时让最终文件中的每个拼图块都作为独立对象出现。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

import numpy as np


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
    build_plate_id: str | None = None,
    enable_wipe_tower_auto_placement: bool = True,
) -> str:
    """Assemble multiple puzzle piece 3MF files into one grouped 3MF.
    将多个拼图单块 3MF 组装为一个按块分组的统一 3MF。

    Source metadata is read by Fat Cat; the shared merged writer preserves
    piece placement and writes the final package once through neroued.
    源元数据由 Fat Cat 读取，共用合并写入器保留拼图位置并通过 neroued 一次写包。

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
        enable_wipe_tower_auto_placement: Whether to solve one wipe-tower
            layout for the final combined geometry.（是否针对最终组合几何求解
            一次擦料塔布局。）

    Returns:
        str: Output 3MF path.
            输出 3MF 文件路径。

    Raises:
        ValueError: If no valid piece geometry can be assembled.
            当无法组装出任何有效几何时抛出。
    """
    if not piece_sources:
        raise ValueError("Puzzle 3MF assembly received no piece sources.")

    from utils.fatcat_metadata import read_source_metadata, select_metadata_target
    from utils.merged_bambu_3mf_writer import MaterialSlot

    metadata_target = select_metadata_target(
        slicer=slicer,
        printer_id=printer_id,
        nozzle_size=nozzle_size,
        device_profile_id=device_profile_id,
        build_plate_id=build_plate_id,
    )
    piece_slots = [
        tuple(
            MaterialSlot(**slot)
            for slot in read_source_metadata(
                piece_source.threemf_path,
                target=metadata_target,
            )["slots"]
        )
        for piece_source in piece_sources
    ]
    return assemble_puzzle_3mf_fatcat(
        piece_sources=piece_sources,
        piece_slots=piece_slots,
        output_path=output_path,
        slot_names=slot_names,
        preview_colors=preview_colors,
        slot_index_by_name=None,
        printer_id=printer_id,
        slicer=slicer,
        nozzle_size=nozzle_size,
        device_profile_id=device_profile_id,
        build_plate_id=build_plate_id,
        overview_png_bytes=overview_png_bytes,
        metadata_target=metadata_target,
        enable_wipe_tower_auto_placement=enable_wipe_tower_auto_placement,
    )


def assemble_puzzle_3mf_fatcat(
    piece_sources: list[PuzzlePiece3MFSource],
    piece_slots: Sequence[Sequence[Any]],
    output_path: str,
    slot_names: list[str] | None,
    preview_colors: dict[object, object] | None,
    slot_index_by_name: Mapping[str, int] | None,
    printer_id: str,
    slicer: str,
    nozzle_size: str,
    device_profile_id: str,
    build_plate_id: str,
    overview_png_bytes: bytes,
    metadata_target: Any,
    enable_wipe_tower_auto_placement: bool = True,
) -> str:
    """Write puzzle metadata through Fat Cat while retaining Lumina placement.

    拼图位置仍由 Lumina 计算；最终元数据由 Fat Cat 合成并交给 neroued 写包。

    Args:
        piece_sources: Generated piece 3MFs with Lumina-computed offsets.
            Lumina 已计算偏移量的拼图单块 3MF。
        piece_slots: Source material identities for each piece 3MF.
            每个拼图单块 3MF 的源材料槽位身份。
        output_path: Destination 3MF path. (输出 3MF 路径)
        slot_names: Ordered global puzzle palette. (全局拼图调色板顺序)
        preview_colors: Product colors for the ordered palette.
            全局调色板对应的产品颜色。
        slot_index_by_name: Business palette slot to source-array index.
            业务调色板槽位到源数组索引的映射。
        printer_id: Selected Lumina printer profile. (所选 Lumina 打印机配置)
        slicer: Explicit selected slicer. (明确选择的切片软件)
        nozzle_size: Selected nozzle size. (所选喷嘴尺寸)
        device_profile_id: Explicit slicer device profile. (明确的切片器设备配置)
        build_plate_id: Explicit native build plate. (明确的原生打印板)
        overview_png_bytes: Combined puzzle overview image. (拼图总览图字节)
        metadata_target: Explicit Fat Cat target selected by the API route.
            API 路由明确选择的 Fat Cat 目标。
        enable_wipe_tower_auto_placement: Whether to solve one final layout.
            是否求解一次最终擦料塔布局。

    Returns:
        str: Written 3MF path. (写出的 3MF 路径)

    Raises:
        ValueError: If the source count and material-slot count differ or no
            source pieces are supplied. (源文件与材料槽位数量不匹配或没有源块时抛出)
    """
    if not piece_sources:
        raise ValueError("Puzzle 3MF assembly received no piece sources.")
    if len(piece_sources) != len(piece_slots):
        raise ValueError("Puzzle piece sources and material slots must have equal length.")

    from utils.merged_bambu_3mf_writer import MergedBambu3MFWriter, MergedItem

    selected_piece_slots = _select_puzzle_palette_slots(
        piece_slots=piece_slots,
        slot_names=slot_names,
        preview_colors=preview_colors,
        slot_index_by_name=slot_index_by_name,
    )

    # MergedItem translations are bbox minima; puzzle offsets use build_transforms below.
    items = [
        MergedItem(
            source_filename=piece_source.label,
            source_3mf_path=Path(piece_source.threemf_path),
            slots=tuple(slots),
            tx_mm=0.0,
            ty_mm=0.0,
        )
        for piece_source, slots in zip(piece_sources, selected_piece_slots)
    ]
    build_transforms = [
        [
            1.0, 0.0, 0.0,
            0.0, 1.0, 0.0,
            0.0, 0.0, 1.0,
            piece_source.offset_x_mm,
            piece_source.offset_y_mm,
            0.0,
        ]
        for piece_source in piece_sources
    ]
    MergedBambu3MFWriter().write_puzzle(
        items,
        Path(output_path),
        build_transforms=build_transforms,
        overview_png_bytes=overview_png_bytes,
        metadata_target=metadata_target,
        printer_id=printer_id,
        nozzle_size=nozzle_size,
        device_profile_id=device_profile_id,
        build_plate_id=build_plate_id,
        enable_wipe_tower_auto_placement=enable_wipe_tower_auto_placement,
        source_materials=[
            {"name": name, "colour": _rgb_to_hex(_resolve_preview_rgb_for_material_name(
                name, index, preview_colors, "#C8C8C8"))}
            for index, name in enumerate(slot_names or [])
        ],
    )
    return output_path


def _select_puzzle_palette_slots(
    *,
    piece_slots: Sequence[Sequence[Any]],
    slot_names: list[str] | None,
    preview_colors: dict[object, object] | None,
    slot_index_by_name: Mapping[str, int] | None,
) -> list[tuple[Any, ...]]:
    """Select each source's slots in the final global puzzle palette order.

    按最终全局拼图调色板顺序，为每份源项目选出并重排对应槽位。
    """

    palette = [str(name) for name in (slot_names or []) if str(name)]
    if not palette:
        return [
            tuple(
                slot
                if getattr(slot, "source_slot_index", None) is not None
                else replace(slot, source_slot_index=int(slot.slot_id))
                for slot in source_slots
            )
            for source_slots in piece_slots
        ]

    source_indexes = slot_index_by_name or {
        name: index for index, name in enumerate(palette)
    }
    selected_by_piece: list[tuple[Any, ...]] = []
    for source_slots in piece_slots:
        slots_by_index = {int(slot.slot_id): slot for slot in source_slots}
        selected: list[Any] = []
        for output_index, name in enumerate(palette):
            source_index = int(source_indexes.get(name, output_index))
            source_slot = next((slot for slot in source_slots if slot.slot_name == name), None)
            if source_slot is None and len(source_slots) >= len(palette):
                source_slot = slots_by_index.get(source_index)
            if source_slot is None:
                # A sparse piece contributes only its real source slots.
                # The library completes genuinely absent global selections.
                continue
            source_index = int(source_slot.slot_id)
            preview_color = _rgb_to_hex(
                _resolve_preview_rgb_for_material_name(
                    material_name=name,
                    material_index=output_index,
                    preview_colors=preview_colors,
                    fallback_hex=source_slot.preview_color,
                )
            )
            selected.append(
                replace(
                    source_slot,
                    slot_id=output_index,
                    slot_name=name,
                    preview_color=preview_color,
                    source_slot_index=source_index,
                )
            )
        selected_by_piece.append(tuple(selected))
    return selected_by_piece


def _resolve_preview_rgb_for_material_name(
    material_name: str,
    material_index: int,
    preview_colors: dict[object, object] | None,
    fallback_hex: str,
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

    if re.fullmatch(r"#[0-9A-Fa-f]{6}", fallback_hex):
        return (
            int(fallback_hex[1:3], 16),
            int(fallback_hex[3:5], 16),
            int(fallback_hex[5:7], 16),
        )

    return (200, 200, 200)


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
