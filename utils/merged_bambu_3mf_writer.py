"""Merged Bambu 3MF writer (multi-object batch merge).
合并 Bambu 3MF writer（批量模式多对象合并）。

This module is a sibling of :mod:`utils.bambu_3mf_writer` and provides
the data shapes and writer for merged multi-object 3MF export.

Uses neroued_3mf (C++ streaming writer) for per-item mesh serialization
and reuses :class:`BambuStudio3MFWriter`'s metadata builders for Bambu/Orca
vendor metadata injection. The main model structure (N assembly objects,
N build items) is built with ElementTree since neroued_3mf's production
extension always produces a single top-level assembly.

本模块使用 neroued_3mf C++ 流式写入器序列化每个 item 的 mesh 数据，
并复用 :class:`BambuStudio3MFWriter` 的元数据构建器注入 Bambu/Orca
厂商元数据。主模型结构（N 个 assembly 对象、N 个 build item）使用
ElementTree 构建。

- :class:`MergedWriteError` is the single domain exception raised by
  the multi-object 3MF writer in this module.
- :class:`MaterialSlot` mirrors :class:`api.schemas.batch_sidecar.MaterialSlot`
  as a plain dataclass (no Pydantic dependency).
- :class:`MergedItem` is the canonical input shape for
  :class:`MergedBambu3MFWriter`.
"""

from __future__ import annotations

import copy
import io
import json
import os
import tempfile
import uuid
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Sequence

import numpy as np


class MergedWriteError(Exception):
    """Domain error raised by the merged 3MF writer.
    合并 3MF writer 抛出的领域异常。

    Raised exclusively by :class:`MergedBambu3MFWriter` when an object
    cannot be composed, an OPC archive cannot be packed, or disk I/O
    fails. The route layer (``convert_batch``) wraps the underlying cause
    with a ``stage`` label (currently ``"merge_3mf"``) and maps the
    exception to ``HTTP 500`` via
    :func:`api.errors.to_http_exception`. Callers SHOULD include the
    original exception as ``__cause__`` (``raise MergedWriteError(...) from exc``)
    to keep root-cause traceability in structured logs.

    本异常仅由 :class:`MergedBambu3MFWriter` 抛出，覆盖对象组合失败、
    OPC 打包失败、磁盘 I/O 失败等写出阶段错误。路由层
    (``convert_batch``) 在 ``except`` 边界给底层 cause 附加
    ``stage`` 标签（当前为 ``"merge_3mf"``）并通过
    :func:`api.errors.to_http_exception` 映射为 ``HTTP 500``。调用方应当用
    ``raise MergedWriteError(...) from exc`` 保留原始异常以便结构化日志
    追溯根因。
    """


@dataclass(frozen=True)
class MaterialSlot:
    """Material slot identity inside :class:`MergedItem`.
    :class:`MergedItem` 中的材料 slot 身份描述。

    The four fields are intentionally aligned with
    :class:`api.schemas.batch_sidecar.MaterialSlot` so that the parent
    process can hand sidecar slots straight into a :class:`MergedItem`
    without a translation step. This dataclass is deliberately NOT a
    Pydantic model: the ``utils`` layer must not pull in Pydantic as a
    transitive dependency, and merge-stage writers do not need
    request-style validation (the sidecar producer is the validation
    boundary).

    四个字段的含义与 :class:`api.schemas.batch_sidecar.MaterialSlot`
    一一对齐，让父进程可以把 sidecar slots 直接喂给
    :class:`MergedItem` 而无需翻译层。本 dataclass 故意不是 Pydantic
    模型：``utils`` 层不应引入 Pydantic 传递依赖，合并阶段 writer 也
    不需要请求级校验（sidecar 生产侧才是校验边界）。

    Attributes:
        slot_id: 0-based slot index in the slicer. Uniqueness within a
            single :class:`MergedItem` is enforced by the writer's
            ``slots`` validation, not by this dataclass.
            切片软件中的 0-based slot 索引。单个 :class:`MergedItem`
            内的唯一性由 writer 的 ``slots`` 校验保证，本 dataclass
            不强制。
        slot_name: Slot display name shown by the slicer
            (e.g. ``"Bambu PLA Black"``).
            切片软件中显示的 slot 名（例如 ``"Bambu PLA Black"``）。
        preview_color: Six-digit hex color used for frontend preview
            (e.g. ``"#101010"``).
            前端预览用六位十六进制颜色（例如 ``"#101010"``）。
        material_id: Stable identifier in the material archive (e.g.
            ``"GFL00"``); merged 3MF round-trip tests assert this value
            survives unchanged.
            材料 archive 中的稳定标识（例如 ``"GFL00"``）；合并 3MF
            round-trip 测试断言该值原样保留。
    """

    slot_id: int
    slot_name: str
    preview_color: str
    material_id: str


@dataclass(frozen=True)
class MergedItem:
    """One object input for :class:`MergedBambu3MFWriter`.
    :class:`MergedBambu3MFWriter` 的单个对象输入。

    The geometry source is the per-image export-grade 3MF produced by
    ``worker_batch_convert_item`` (see ``threemf_path`` in the worker
    return value). The merge stage reuses meshes and material
    definitions directly from that file so the full Bambu metadata
    (auxiliary meshes, slot bindings, slicer config) is preserved.

    几何源是 ``worker_batch_convert_item`` 产出的 per-image 导出级
    3MF（worker 返回值中的 ``threemf_path``）。合并阶段直接复用该
    文件中的 mesh 与材料定义，从而保留完整的 Bambu 元数据（辅助
    网格、slot 绑定、切片配置等）。

    NOT accepted as a geometry source:

    - :class:`trimesh.Scene` instances. Scene objects routinely lose
      vendor metadata when round-tripped through ``to_dict`` /
      ``dump_to_bytes`` and cannot be passed across the worker
      boundary anyway (workers communicate via file paths + scalars).
    - GLB-derived scenes (e.g. anything loaded from the per-image
      ``preview_glb_path``). Preview GLB is a frontend-only artifact
      and routinely strips slot bindings, auxiliary meshes, and
      slicer-side config; using it here is the canonical "preview model
      mistaken for export model" bug we explicitly forbid.

    禁止作为几何源使用：

    - :class:`trimesh.Scene` 实例。Scene 在跨函数 / 跨进程传递时常常
      丢失 vendor metadata（``to_dict`` / ``dump_to_bytes`` 之类的
      pickle hack 都不可靠），而且 worker 边界本身就只允许传文件路径
      + 标量。
    - GLB-derived scene（比如从 per-image ``preview_glb_path`` load
      回来的 Scene）。预览 GLB 仅服务前端 3D 显示，会丢 slot 绑定、
      辅助网格、切片配置；把它当成合并 3MF 的几何源是典型的"预览
      模型误当导出模型"bug，本模块明确禁止。

    Attributes:
        source_filename: Original upload filename (e.g. ``"kitten.png"``);
            kept for diagnostics and for object naming inside the
            merged 3MF.
            原始上传文件名（例如 ``"kitten.png"``）；用于诊断信息以及
            合并 3MF 内部对象命名。
        source_3mf_path: Path to the per-image export-grade 3MF that
            serves as the sole authoritative geometry / material
            source for this object in the merged 3MF.
            per-image 导出级 3MF 的路径；该对象在合并 3MF 中的几何
            与材料定义的唯一权威来源。
        slots: Full identity list of material slots used by this
            object. Order does not have to be contiguous in
            ``slot_id`` (the writer may remap to a contiguous range
            internally for slicer compatibility); round-trip tests
            still compare the four-tuple identity.
            该对象使用的全部材料 slot 身份列表。``slot_id`` 不要求
            连续（writer 内部可能为切片软件兼容性 remap 到连续区间），
            round-trip 测试仍按四元组身份比较。
        tx_mm: X translation in the merged-3MF world coordinate system.
            Specifies where the object's XY bbox **min corner** should
            land; the writer is responsible for compensating any
            non-zero local origin in ``source_3mf_path``.
            合并 3MF 世界坐标系下的 X 平移；指定该对象 XY 包围盒
            **左下角**应当落到的位置。``source_3mf_path`` 内部如有
            非零本地原点，由 writer 负责补偿。
        ty_mm: Y translation in the merged-3MF world coordinate system,
            with the same "bbox min corner" semantics as ``tx_mm``.
            合并 3MF 世界坐标系下的 Y 平移，``tx_mm`` 同款语义。
    """

    source_filename: str
    source_3mf_path: Path
    slots: tuple[MaterialSlot, ...]
    tx_mm: float
    ty_mm: float


__all__ = [
    "MergedWriteError",
    "MaterialSlot",
    "MergedItem",
    "MergedBambu3MFWriter",
]


# ---------------------------------------------------------------------------
# Internal helpers (zip / XML parsing of source 3MFs)
# ---------------------------------------------------------------------------

# 3MF / OPC namespaces.
_NS_CORE = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
_NS_PROD = "http://schemas.microsoft.com/3dmanufacturing/production/2015/06"
_NS_BAMBU = "http://schemas.bambulab.com/package/2021"
_NS_RELS = "http://schemas.openxmlformats.org/package/2006/relationships"
_NS_CONTENT_TYPES = "http://schemas.openxmlformats.org/package/2006/content-types"
_REL_TYPE_3DMODEL = "http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"
_REL_TYPE_BAMBU_SETTINGS = "http://schemas.bambulab.com/package/2021/settings"
_CONTENT_TYPE_3DMODEL = "application/vnd.ms-package.3dmanufacturing-3dmodel+xml"
_CONTENT_TYPE_RELS = "application/vnd.openxmlformats-package.relationships+xml"

_BAMBU_METADATA_PART_ORDER = (
    "Metadata/model_settings.config",
    "Metadata/project_settings.config",
    "Metadata/slice_info.config",
    "Metadata/filament_sequence.json",
    "Metadata/cut_information.xml",
    "Metadata/layer_config_ranges.xml",
    "Metadata/custom_gcode_per_layer.xml",
)

_BAMBU_THUMBNAIL_PARTS = (
    "Metadata/plate_1.png",
    "Metadata/plate_1_small.png",
    "Metadata/plate_no_light_1.png",
    "Metadata/top_1.png",
    "Metadata/pick_1.png",
)

_AUXILIARY_THUMBNAIL_PARTS = (
    "Auxiliaries/.thumbnails/thumbnail_3mf.png",
    "Auxiliaries/.thumbnails/thumbnail_middle.png",
    "Auxiliaries/.thumbnails/thumbnail_small.png",
)

# Lumina-private metadata key inside Metadata/model_settings.config that
# preserves the original ``MaterialSlot`` quadruples for an item, so that
# round-trip parsing can recover the input identity even when the writer
# remaps slot ids for slicer compatibility.
_LUMINA_SLOTS_JSON_KEY = "lumina_merged_slots_json"


@dataclass(frozen=True)
class _SourceMesh:
    """One mesh entry parsed from a source 3MF's per-item ``object_*.model``.

    Attributes:
        original_id: Original ``<object id>`` inside the source per-item
            ``.model`` file. Kept only for diagnostics; the writer
            renumbers to globally-unique IDs.
        element: The cloned ``<object>`` ElementTree element (with mesh
            geometry); ready to be serialised into the merged 3MF after
            the ``id`` attribute is rewritten.
        original_part_metadata: The matching ``<part id="original_id">``
            element from the source's ``Metadata/model_settings.config``.
            ``None`` if the source did not ship a Bambu config (best-
            effort default metadata is generated in that case).
    """

    original_id: int
    element: ET.Element
    original_part_metadata: ET.Element | None


@dataclass(frozen=True)
class _SourceAssembly:
    """The aggregate of one ``MergedItem`` after parsing its source 3MF.

    Attributes:
        meshes: All mesh ``<object>`` elements referenced by the source's
            top-level build item, in their declaration order.
        per_item_model_basename: The basename of the per-item
            ``3D/Objects/object_*.model`` file that contains ``meshes``.
            The merged 3MF re-emits the meshes under a fresh basename
            ``object_<idx>.model`` to avoid cross-item collisions.
        min_x: Minimum X vertex coordinate across all ``meshes`` (mm),
            after applying source component transforms.
        min_y: Minimum Y vertex coordinate across all ``meshes`` (mm),
            after applying source component transforms.
        source_assembly_part_metadata: ``<object>`` element from the
            source's ``Metadata/model_settings.config`` describing the
            top-level assembly (extruder default + face_count). ``None``
            if absent.
        source_plate_metadata: ``<plate>`` element from the source's
            ``Metadata/model_settings.config``. The merged writer reuses
            the direct ``<metadata>`` children and rebuilds only the
            ``<model_instance>`` list for all merged objects.
    component_transforms: Per-component transform strings from source.
    component_uuids: Per-component p:UUID strings from source.
    metadata_parts: Raw Bambu metadata parts copied from the source 3MF.
    project_settings: Parsed source project settings, if present.
    root_metadata: Top-level ``3D/3dmodel.model`` metadata from source.
    """

    meshes: tuple[_SourceMesh, ...]
    per_item_model_basename: str
    min_x: float
    min_y: float
    max_x: float
    max_y: float
    min_z: float
    max_z: float
    source_assembly_part_metadata: ET.Element | None
    source_plate_metadata: ET.Element | None
    component_transforms: tuple[str, ...]
    component_uuids: tuple[str, ...]
    metadata_parts: dict[str, bytes]
    project_settings: dict[str, Any] | None
    root_metadata: dict[str, str]


def _qname_core(tag: str) -> str:
    return f"{{{_NS_CORE}}}{tag}"


def _qname_prod(attr: str) -> str:
    return f"{{{_NS_PROD}}}{attr}"


def _qname_rels(tag: str) -> str:
    return f"{{{_NS_RELS}}}{tag}"


def _qname_ct(tag: str) -> str:
    return f"{{{_NS_CONTENT_TYPES}}}{tag}"


def _parse_transform_matrix(transform_str: str) -> list[float]:
    """Parse a 3MF 3x4 row-major transform string into 12 floats.

    3MF transform format: m00 m01 m02 m10 m11 m12 m20 m21 m22 tx ty tz
    Returns identity [1,0,0, 0,1,0, 0,0,1, 0,0,0] if empty or invalid.
    """
    if not transform_str or not transform_str.strip():
        return [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0]
    parts = transform_str.strip().split()
    if len(parts) != 12:
        return [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0]
    try:
        return [float(p) for p in parts]
    except ValueError:
        return [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0]


def _apply_transform_xy(
    matrix: list[float], vx: float, vy: float, vz: float
) -> tuple[float, float]:
    """Apply a 3x4 row-major affine transform and return (x, y).

    Matrix layout: [m00, m01, m02, m10, m11, m12, m20, m21, m22, tx, ty, tz]
    Result x = m00*vx + m01*vy + m02*vz + tx
    Result y = m10*vx + m11*vy + m12*vz + ty
    """
    m = matrix
    x = m[0] * vx + m[1] * vy + m[2] * vz + m[9]
    y = m[3] * vx + m[4] * vy + m[5] * vz + m[10]
    return x, y


def _apply_transform_xyz(
    matrix: list[float], vx: float, vy: float, vz: float
) -> tuple[float, float, float]:
    """Apply a 3x4 row-major affine transform and return all coordinates."""

    m = matrix
    return (
        m[0] * vx + m[1] * vy + m[2] * vz + m[9],
        m[3] * vx + m[4] * vy + m[5] * vz + m[10],
        m[6] * vx + m[7] * vy + m[8] * vz + m[11],
    )


def _validate_slots(slots: Sequence[MaterialSlot]) -> None:
    """Validate slots per task 10 rules.

    校验 slots 字段：长度 ≥ 1、``slot_id`` 唯一、四元组字段非空（空字符串
    视为非空但记 WARNING，不抛错）。``slot_id`` **不**强求连续。
    """

    if len(slots) < 1:
        raise MergedWriteError("MergedItem.slots must contain at least one slot")
    seen_ids: set[int] = set()
    for slot in slots:
        if not isinstance(slot, MaterialSlot):
            raise MergedWriteError(
                f"MergedItem.slots entries must be MaterialSlot; got {type(slot).__name__}"
            )
        if slot.slot_id in seen_ids:
            raise MergedWriteError(
                f"duplicate MaterialSlot.slot_id={slot.slot_id} within a single MergedItem"
            )
        seen_ids.add(slot.slot_id)


def _parse_source_assembly(item_idx: int, item: MergedItem) -> _SourceAssembly:
    """Parse one source 3MF and extract its mesh objects + metadata.

    解析单个源 3MF，提取该 item 的 mesh 对象与元数据。
    Preserves component transforms and UUIDs from source.
    """

    src_path = item.source_3mf_path
    if not isinstance(src_path, Path):
        src_path = Path(src_path)
    if not src_path.exists():
        raise MergedWriteError(
            f"MergedItem[{item_idx}].source_3mf_path does not exist: {src_path}"
        )

    try:
        with zipfile.ZipFile(src_path, "r") as zf:
            try:
                main_model_bytes = zf.read("3D/3dmodel.model")
            except KeyError as exc:
                raise MergedWriteError(
                    f"MergedItem[{item_idx}].source_3mf_path missing 3D/3dmodel.model"
                ) from exc

            main_root = _parse_xml_bytes(main_model_bytes)
            root_metadata = {
                metadata.get("name") or "": metadata.text or ""
                for metadata in main_root.findall(_qname_core("metadata"))
                if metadata.get("name")
            }

            # Identify the build target object id.
            build_elem = main_root.find(_qname_core("build"))
            if build_elem is None:
                raise MergedWriteError(
                    f"MergedItem[{item_idx}].source_3mf_path missing <build>"
                )
            build_items = list(build_elem.findall(_qname_core("item")))
            if not build_items:
                raise MergedWriteError(
                    f"MergedItem[{item_idx}].source_3mf_path has empty <build>"
                )
            target_objectid = build_items[0].get("objectid")
            if target_objectid is None:
                raise MergedWriteError(
                    f"MergedItem[{item_idx}].source_3mf_path build item missing objectid"
                )

            # Find the assembly object element with that id.
            resources_elem = main_root.find(_qname_core("resources"))
            if resources_elem is None:
                raise MergedWriteError(
                    f"MergedItem[{item_idx}].source_3mf_path missing <resources>"
                )
            assembly_elem = None
            for obj in resources_elem.findall(_qname_core("object")):
                if obj.get("id") == target_objectid:
                    assembly_elem = obj
                    break
            if assembly_elem is None:
                raise MergedWriteError(
                    f"MergedItem[{item_idx}].source_3mf_path has no <object id={target_objectid!r}>"
                )

            # Walk <components> to learn which per-item .model file holds
            # the actual mesh objects, plus the referenced objectids.
            components = assembly_elem.find(_qname_core("components"))
            if components is None:
                raise MergedWriteError(
                    f"MergedItem[{item_idx}].source_3mf_path build object lacks <components>; "
                    "merge writer requires component-style assembly objects"
                )
            # (p:path, objectid, transform, p:UUID)
            referenced: list[tuple[str, str, str, str]] = []
            for comp in components.findall(_qname_core("component")):
                p_path = comp.get(_qname_prod("path"))
                obj_id = comp.get("objectid")
                if not p_path or not obj_id:
                    raise MergedWriteError(
                        f"MergedItem[{item_idx}].source_3mf_path has <component> without "
                        "p:path or objectid"
                    )
                # Preserve transform and UUID from source component
                comp_transform = comp.get("transform") or ""
                comp_uuid = comp.get(_qname_prod("UUID")) or ""
                referenced.append((p_path, obj_id, comp_transform, comp_uuid))

            # All components must point to the same per-item .model file
            # (this is the shape produced by BambuStudio3MFWriter and by
            # the reference 多项目参考.3mf).
            distinct_paths = {p for p, _, _, _ in referenced}
            if len(distinct_paths) != 1:
                raise MergedWriteError(
                    f"MergedItem[{item_idx}].source_3mf_path components reference multiple "
                    f"per-item .model files: {sorted(distinct_paths)!r}; merge writer "
                    "requires a single per-item .model file"
                )
            per_item_path = next(iter(distinct_paths))
            # Strip leading slash for zip path.
            per_item_zip_path = per_item_path.lstrip("/")
            try:
                per_item_bytes = zf.read(per_item_zip_path)
            except KeyError as exc:
                raise MergedWriteError(
                    f"MergedItem[{item_idx}].source_3mf_path missing per-item model "
                    f"{per_item_zip_path!r}"
                ) from exc

            per_item_root = _parse_xml_bytes(per_item_bytes)
            per_item_resources = per_item_root.find(_qname_core("resources"))
            if per_item_resources is None:
                raise MergedWriteError(
                    f"MergedItem[{item_idx}] per-item model {per_item_zip_path!r} "
                    "missing <resources>"
                )

            # Collect referenced mesh objects in the order they appear in
            # <components> (preserves slot order in the merged output).
            id_to_obj: dict[str, ET.Element] = {}
            for obj in per_item_resources.findall(_qname_core("object")):
                obj_id = obj.get("id")
                if obj_id is not None:
                    id_to_obj[obj_id] = obj

            ordered_mesh_objs: list[tuple[str, ET.Element]] = []
            component_transforms: list[str] = []
            component_uuids: list[str] = []
            for _, ref_id, comp_transform, comp_uuid in referenced:
                if ref_id not in id_to_obj:
                    raise MergedWriteError(
                        f"MergedItem[{item_idx}] per-item model {per_item_zip_path!r} "
                        f"missing <object id={ref_id!r}> referenced by 3D/3dmodel.model"
                    )
                ordered_mesh_objs.append((ref_id, id_to_obj[ref_id]))
                component_transforms.append(comp_transform)
                component_uuids.append(comp_uuid)

            # Compute XY bbox across all referenced mesh vertices,
            # applying source component transforms to each vertex.
            min_x = float("inf")
            min_y = float("inf")
            max_x = float("-inf")
            max_y = float("-inf")
            min_z = float("inf")
            max_z = float("-inf")
            for comp_idx, (_, obj) in enumerate(ordered_mesh_objs):
                mesh = obj.find(_qname_core("mesh"))
                if mesh is None:
                    continue
                vertices = mesh.find(_qname_core("vertices"))
                if vertices is None:
                    continue
                # Parse the component transform for this mesh
                transform_matrix = _parse_transform_matrix(
                    component_transforms[comp_idx]
                )
                for vert in vertices.findall(_qname_core("vertex")):
                    x_str = vert.get("x")
                    y_str = vert.get("y")
                    z_str = vert.get("z")
                    if x_str is None or y_str is None:
                        continue
                    try:
                        vx = float(x_str)
                        vy = float(y_str)
                        vz = float(z_str) if z_str is not None else 0.0
                    except ValueError as exc:
                        raise MergedWriteError(
                            f"MergedItem[{item_idx}] per-item model has non-numeric "
                            f"vertex coordinate ({x_str!r}, {y_str!r})"
                        ) from exc
                    # Apply component transform to vertex
                    tx, ty, tz = _apply_transform_xyz(
                        transform_matrix,
                        vx,
                        vy,
                        vz,
                    )
                    if tx < min_x:
                        min_x = tx
                    if ty < min_y:
                        min_y = ty
                    if tx > max_x:
                        max_x = tx
                    if ty > max_y:
                        max_y = ty
                    if tz < min_z:
                        min_z = tz
                    if tz > max_z:
                        max_z = tz
            if (
                min_x == float("inf")
                or min_y == float("inf")
                or max_x == float("-inf")
                or max_y == float("-inf")
                or min_z == float("inf")
                or max_z == float("-inf")
            ):
                raise MergedWriteError(
                    f"MergedItem[{item_idx}].source_3mf_path has no vertices to "
                    "compute XY bbox"
                )

            # Optional source-side Metadata/model_settings.config: parse
            # and pull out the matching <part> entries so we can preserve
            # Bambu metadata (matrix, source_offset_*, mesh_stat).
            source_assembly_part_md = None
            source_plate_md = None
            source_part_md_by_id: dict[str, ET.Element] = {}
            try:
                config_bytes = zf.read("Metadata/model_settings.config")
            except KeyError:
                config_bytes = None
            if config_bytes is not None:
                try:
                    config_root = ET.fromstring(config_bytes)
                except ET.ParseError:
                    config_root = None
                if config_root is not None:
                    for cfg_obj in config_root.findall("object"):
                        if cfg_obj.get("id") != target_objectid:
                            continue
                        source_assembly_part_md = cfg_obj
                        for part in cfg_obj.findall("part"):
                            pid = part.get("id")
                            if pid is not None:
                                source_part_md_by_id[pid] = part
                        break
                    source_plate_md = config_root.find("plate")

            metadata_parts: dict[str, bytes] = {}
            for metadata_path in (
                *_BAMBU_METADATA_PART_ORDER,
                *_BAMBU_THUMBNAIL_PARTS,
                *_AUXILIARY_THUMBNAIL_PARTS,
            ):
                try:
                    metadata_parts[metadata_path] = zf.read(metadata_path)
                except KeyError:
                    continue

            project_settings: dict[str, Any] | None = None
            project_bytes = metadata_parts.get("Metadata/project_settings.config")
            if project_bytes is not None:
                try:
                    parsed_project = json.loads(project_bytes.decode("utf-8"))
                    if isinstance(parsed_project, dict):
                        project_settings = parsed_project
                except (UnicodeDecodeError, json.JSONDecodeError):
                    project_settings = None

            meshes: list[_SourceMesh] = []
            for orig_id, obj_elem in ordered_mesh_objs:
                meshes.append(
                    _SourceMesh(
                        original_id=int(orig_id) if orig_id.isdigit() else 0,
                        element=obj_elem,
                        original_part_metadata=source_part_md_by_id.get(orig_id),
                    )
                )

            return _SourceAssembly(
                meshes=tuple(meshes),
                per_item_model_basename=os.path.basename(per_item_zip_path),
                min_x=min_x,
                min_y=min_y,
                max_x=max_x,
                max_y=max_y,
                min_z=min_z,
                max_z=max_z,
                source_assembly_part_metadata=source_assembly_part_md,
                source_plate_metadata=source_plate_md,
                component_transforms=tuple(component_transforms),
                component_uuids=tuple(component_uuids),
                metadata_parts=metadata_parts,
                project_settings=project_settings,
                root_metadata=root_metadata,
            )
    except MergedWriteError:
        raise
    except (zipfile.BadZipFile, OSError) as exc:
        raise MergedWriteError(
            f"MergedItem[{item_idx}].source_3mf_path could not be opened as zip: {exc}"
        ) from exc
    except ET.ParseError as exc:
        raise MergedWriteError(
            f"MergedItem[{item_idx}].source_3mf_path has invalid XML: {exc}"
        ) from exc


def _parse_xml_bytes(payload: bytes) -> ET.Element:
    """Parse XML bytes and return the root element.

    Bare wrapper around ``ET.fromstring`` so the call sites remain
    declarative; ParseError is allowed to bubble so callers can wrap it
    into ``MergedWriteError`` with a fileset-aware message.
    """

    return ET.fromstring(payload)


def _format_float(value: float) -> str:
    """Format a float for stable 3MF metadata output (mirrors Bambu writer)."""

    return format(float(value), ".15g")


def _extract_mesh_arrays(
    mesh_element: ET.Element,
) -> tuple[np.ndarray, np.ndarray]:
    """Extract vertices and faces from a source 3MF mesh <object> element.

    从源 3MF 的 mesh <object> 元素中提取顶点和面数组。

    Returns:
        (vertices, faces) as numpy arrays (float64, int64).
    """
    mesh_elem = mesh_element.find(_qname_core("mesh"))
    if mesh_elem is None:
        return np.zeros((0, 3), dtype=np.float64), np.zeros((0, 3), dtype=np.int64)

    vertices_elem = mesh_elem.find(_qname_core("vertices"))
    triangles_elem = mesh_elem.find(_qname_core("triangles"))

    # Parse vertices.
    verts_list: list[list[float]] = []
    if vertices_elem is not None:
        for v in vertices_elem.findall(_qname_core("vertex")):
            x = float(v.get("x", "0"))
            y = float(v.get("y", "0"))
            z = float(v.get("z", "0"))
            verts_list.append([x, y, z])

    # Parse faces.
    faces_list: list[list[int]] = []
    if triangles_elem is not None:
        for t in triangles_elem.findall(_qname_core("triangle")):
            v1 = int(t.get("v1", "0"))
            v2 = int(t.get("v2", "0"))
            v3 = int(t.get("v3", "0"))
            faces_list.append([v1, v2, v3])

    vertices = np.array(verts_list, dtype=np.float64) if verts_list else np.zeros((0, 3), dtype=np.float64)
    faces = np.array(faces_list, dtype=np.int64) if faces_list else np.zeros((0, 3), dtype=np.int64)
    return vertices, faces


def _serialize_per_item_model_n3mf(
    n3mf,
    assembly: "_SourceAssembly",
    item: "MergedItem",
    start_id: int,
) -> bytes:
    """Serialize a per-item model file using neroued_3mf C++ library.

    使用 neroued_3mf C++ 库序列化单个 per-item model 文件。

    Creates a temporary neroued_3mf builder, adds all mesh objects for this
    item, writes to a temp file, and extracts the per-item model bytes.
    The mesh object IDs in the output will start at ``start_id``.

    Args:
        n3mf: The neroued_3mf module.
        assembly: Parsed source assembly for this item.
        item: The MergedItem being serialized.
        start_id: Starting object ID for meshes in this item.

    Returns:
        bytes: The per-item model XML content.
    """
    builder = n3mf.DocumentBuilder()
    builder.set_unit(n3mf.Unit.Millimeter)
    builder.set_language("en-US")
    builder.enable_production()
    builder.set_production_merge_objects(True)

    # Add mesh objects from source assembly.
    obj_ids: list[int] = []
    for mesh_idx, source_mesh in enumerate(assembly.meshes):
        vertices, faces = _extract_mesh_arrays(source_mesh.element)
        if vertices.shape[0] == 0 or faces.shape[0] == 0:
            # Create a minimal placeholder mesh if source is empty.
            vertices = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float64)
            faces = np.array([[0, 1, 2]], dtype=np.int64)

        n3mf_mesh = n3mf.Mesh.from_arrays(
            np.ascontiguousarray(vertices, dtype=np.float64),
            np.ascontiguousarray(faces, dtype=np.int64),
        )
        # Use slot name as object name if available.
        obj_name = f"mesh_{mesh_idx}"
        if mesh_idx < len(item.slots):
            obj_name = item.slots[mesh_idx].slot_name

        obj_id = builder.add_mesh_object(obj_name, n3mf_mesh)
        obj_ids.append(obj_id)

    # Must add at least one build item for neroued_3mf to produce output.
    if obj_ids:
        builder.add_build_item(obj_ids[0])

    doc = builder.build()
    opts = n3mf.WriteOptions()
    opts.vertex_precision = 6
    opts.compact_xml = True

    # Write to temp file and extract the per-item model bytes.
    fd, tmp_path = tempfile.mkstemp(suffix=".3mf")
    os.close(fd)
    try:
        n3mf.write_to_file(tmp_path, doc, opts)
        with zipfile.ZipFile(tmp_path, "r") as zf:
            # neroued_3mf puts mesh objects in 3D/Objects/object_1.model
            model_path = "3D/Objects/object_1.model"
            if model_path in zf.namelist():
                raw_bytes = zf.read(model_path)
            else:
                # Fallback: find any .model file in Objects/
                model_files = [
                    n for n in zf.namelist()
                    if n.startswith("3D/Objects/") and n.endswith(".model")
                ]
                if model_files:
                    raw_bytes = zf.read(model_files[0])
                else:
                    raise MergedWriteError(
                        "neroued_3mf did not produce a per-item model file"
                    )
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    # Rewrite object IDs to match the expected start_id sequence.
    # neroued_3mf assigns IDs starting from 1 (or mat_group_id+1).
    # We need IDs starting at start_id.
    raw_bytes = _rewrite_object_ids_in_model(raw_bytes, start_id, len(assembly.meshes))
    return raw_bytes


def _rewrite_object_ids_in_model(
    model_bytes: bytes, start_id: int, num_objects: int
) -> bytes:
    """Rewrite object IDs in a per-item model file to match expected sequence.

    重写 per-item model 文件中的 object ID 以匹配预期序列。

    neroued_3mf assigns its own IDs; we need them to be start_id, start_id+1, ...
    """
    root = ET.fromstring(model_bytes)
    resources = root.find(_qname_core("resources"))
    if resources is None:
        return model_bytes

    objects = resources.findall(_qname_core("object"))
    # Build a mapping from old IDs to new IDs.
    old_to_new: dict[str, str] = {}
    for idx, obj in enumerate(objects):
        old_id = obj.get("id")
        new_id = str(start_id + idx)
        if old_id is not None:
            old_to_new[old_id] = new_id
            obj.set("id", new_id)

    # Serialize with proper namespace registration (core as default, p as prefix).
    ET.register_namespace("", _NS_CORE)
    ET.register_namespace("p", _NS_PROD)
    tree = ET.ElementTree(root)
    buf = io.BytesIO()
    tree.write(buf, encoding="utf-8", xml_declaration=True)
    return buf.getvalue()


def _count_triangles_in_model(model_bytes: bytes) -> int:
    """Count mesh triangles in a per-item model file."""

    try:
        root = ET.fromstring(model_bytes)
    except ET.ParseError:
        return 0

    total = 0
    for obj in root.iter(_qname_core("object")):
        mesh = obj.find(_qname_core("mesh"))
        if mesh is None:
            continue
        triangles = mesh.find(_qname_core("triangles"))
        if triangles is not None:
            total += len(triangles.findall(_qname_core("triangle")))
    return total


def _parse_hex_color(hex_color: str) -> tuple[int, int, int]:
    """Parse ``#RRGGBB`` into an RGB tuple.

    解析 ``#RRGGBB`` 颜色。非法输入回退到中性灰，保证合并阶段不会因为
    某个 sidecar 的展示色缺失而产出空耗材表。
    """

    text = str(hex_color or "").strip()
    if text.startswith("#"):
        text = text[1:]
    if len(text) != 6:
        return (204, 204, 204)
    try:
        return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))
    except ValueError:
        return (204, 204, 204)


def _format_hex_color(slot: MaterialSlot) -> str:
    rgb = _parse_hex_color(slot.preview_color)
    return f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"


def _collect_project_slots(items: Sequence[MergedItem]) -> list[MaterialSlot]:
    """Collect project-wide material slots in slicer slot order.

    批量合并时耗材表是项目级的：各 item 的 ``extruder=1`` 都指向同一个
    全局 1 号槽。这里按 ``slot_id`` 汇总并去重，和单件 3MF 的耗材顺序对齐。
    """

    by_slot_id: dict[int, MaterialSlot] = {}
    for item in items:
        for slot in sorted(item.slots, key=lambda s: s.slot_id):
            by_slot_id.setdefault(slot.slot_id, slot)
    return [by_slot_id[slot_id] for slot_id in sorted(by_slot_id)]


def _unique_project_slot_names(slots: Sequence[MaterialSlot]) -> list[str]:
    """Return display names unique enough for BambuStudio3MFWriter's palette."""

    counts: dict[str, int] = {}
    names: list[str] = []
    for slot in slots:
        base_name = str(slot.slot_name or f"Slot {slot.slot_id + 1}").strip()
        if not base_name:
            base_name = f"Slot {slot.slot_id + 1}"
        count = counts.get(base_name, 0)
        counts[base_name] = count + 1
        if count == 0:
            names.append(base_name)
        else:
            names.append(f"{base_name} ({slot.slot_id + 1})")
    return names


def _build_preview_color_map(
    slots: Sequence[MaterialSlot], slot_names: Sequence[str]
) -> dict[object, tuple[int, int, int, int]]:
    """Build the preview-color map shape consumed by the existing writer."""

    preview_colors: dict[object, tuple[int, int, int, int]] = {}
    for idx, (slot, slot_name) in enumerate(zip(slots, slot_names)):
        rgb = _parse_hex_color(slot.preview_color)
        rgba = (rgb[0], rgb[1], rgb[2], 255)
        preview_colors[slot_name] = rgba
        preview_colors[idx] = rgba
        preview_colors[str(idx)] = rgba
        preview_colors[slot.slot_id] = rgba
        preview_colors[str(slot.slot_id)] = rgba
    return preview_colors


def _color_mode_for_slot_count(slot_count: int) -> str:
    if slot_count <= 2:
        return "BW"
    if slot_count <= 4:
        return "4-Color"
    if slot_count <= 6:
        return "6-Color"
    return "8-Color"


def _build_metadata_writer(
    items: Sequence[MergedItem], output_path: Path
):
    """Create a BambuStudio3MFWriter configured with the merged slot palette.

    这里只借用旧 writer 已验证的元数据构建逻辑，不让它写几何；几何仍由
    ``MergedBambu3MFWriter`` 负责多对象布局。
    """

    from utils.bambu_3mf_writer import BambuStudio3MFWriter

    project_slots = _collect_project_slots(items)
    slot_names = _unique_project_slot_names(project_slots)
    preview_colors = _build_preview_color_map(project_slots, slot_names)
    writer = BambuStudio3MFWriter(
        output_path=str(output_path),
        settings={},
        color_mode=_color_mode_for_slot_count(len(project_slots)),
        enable_base_layer_height_modifier=False,
    )
    if slot_names:
        writer._set_project_palette(slot_names, preview_colors)
    return writer


def _first_source_root_metadata(
    assemblies: Sequence[_SourceAssembly],
    key: str,
) -> str | None:
    for assembly in assemblies:
        value = assembly.root_metadata.get(key)
        if value:
            return value
    return None


def _first_source_project_settings(
    assemblies: Sequence[_SourceAssembly],
) -> dict[str, Any] | None:
    for assembly in assemblies:
        if assembly.project_settings:
            return copy.deepcopy(assembly.project_settings)
    return None


def _infer_printer_id_from_settings(settings: dict[str, Any]) -> str:
    """Resolve Lumina's printer id from native project-setting labels."""

    from config import list_printer_profiles

    haystack = " ".join(
        str(settings.get(key) or "")
        for key in ("printer_model", "printer_settings_id")
    ).casefold()
    profiles = sorted(
        list_printer_profiles(),
        key=lambda profile: len(profile.display_name),
        reverse=True,
    )
    for profile in profiles:
        labels = (
            profile.display_name,
            profile.id,
            profile.id.replace("-", " "),
        )
        if any(label.casefold() in haystack for label in labels):
            return profile.id
    return "bambu-h2d"


def _infer_slicer_from_application(application: str | None) -> str:
    """Resolve the slicer family from the source 3MF application label."""

    label = str(application or "").casefold()
    if "orca" in label and "snapmaker" not in label:
        return "OrcaSlicer"
    if "elegoo" in label:
        return "ElegooSlicer"
    if "snapmaker" in label:
        return "SnapmakerOrca"
    if "flash" in label:
        return "FlashStudio"
    if "anycubic" in label:
        return "AnycubicSlicerNext"
    return "BambuStudio"


def _build_merged_placement_writer(
    items: Sequence[MergedItem],
    assemblies: Sequence[_SourceAssembly],
    output_path: Path,
):
    """Create a metadata writer configured for the merged source machine."""

    from utils.bambu_3mf_writer import BambuStudio3MFWriter

    source_settings = _first_source_project_settings(assemblies) or {}
    nozzle_size = source_settings.get("nozzle_diameter")
    if isinstance(nozzle_size, list):
        nozzle_size = nozzle_size[0] if nozzle_size else None
    return BambuStudio3MFWriter(
        output_path=str(output_path),
        settings=source_settings,
        color_mode=_color_mode_for_slot_count(
            len(_collect_project_slots(items))
        ),
        printer_id=_infer_printer_id_from_settings(source_settings),
        slicer=_infer_slicer_from_application(
            _first_source_root_metadata(assemblies, "Application")
        ),
        nozzle_size=nozzle_size,
        enable_base_layer_height_modifier=False,
    )


def _resolve_merged_wipe_tower_placement(
    items: Sequence[MergedItem],
    assemblies: Sequence[_SourceAssembly],
    output_path: Path,
):
    """Solve one tower layout around the complete merged model group."""

    from core.wipe_tower_placement import Rect, solve_wipe_tower_placement

    placement_writer = _build_merged_placement_writer(
        items,
        assemblies,
        output_path,
    )
    model_bounds = Rect(
        min(item.tx_mm for item in items),
        min(item.ty_mm for item in items),
        max(item.tx_mm + assembly.max_x - assembly.min_x for item, assembly in zip(items, assemblies)),
        max(item.ty_mm + assembly.max_y - assembly.min_y for item, assembly in zip(items, assemblies)),
    )
    model_height = max(
        assembly.max_z - assembly.min_z for assembly in assemblies
    )
    request = placement_writer._build_wipe_tower_placement_request(
        placement_writer.settings,
        model_bounds=model_bounds,
        model_height=model_height,
        material_count=len(_collect_project_slots(items)),
    )
    if request is None:
        placement = None
        translation = (0.0, 0.0)
    else:
        request = replace(request, model_translation_locked=True)
        placement = solve_wipe_tower_placement(request)
        translation = placement.model_translation
    return placement_writer, placement, translation


def _resize_project_setting_arrays(
    settings: dict[str, Any],
    slot_count: int,
    template_settings: dict[str, Any],
) -> None:
    """Resize filament-indexed arrays using the single-writer policy."""

    from utils.bambu_3mf_writer import (
        _FILAMENT_RESIZABLE_ARRAY_KEYS,
        _template_default_list_value,
    )

    for key, value in list(settings.items()):
        if not isinstance(value, list):
            continue
        if not (key.startswith("filament_") or key in _FILAMENT_RESIZABLE_ARRAY_KEYS):
            continue
        if len(value) == slot_count:
            continue
        if len(value) > slot_count:
            settings[key] = value[:slot_count]
            continue
        fill_value = _template_default_list_value(value, template_settings)
        settings[key] = list(value) + [fill_value] * (slot_count - len(value))


def _build_project_settings_bytes_for_merge(
    items: Sequence[MergedItem],
    assemblies: Sequence[_SourceAssembly],
    output_path: Path,
    *,
    placement_writer=None,
    placement=None,
) -> bytes:
    """Build non-empty project settings for the merged batch 3MF.

    优先复用第一份 per-image 3MF 里已经由单件 writer 写好的项目配置，
    这样打印机、喷嘴、切片器模板等设置不会被批量合并阶段重置；如果源
    文件缺失配置，则回退到 ``BambuStudio3MFWriter`` 的标准构建逻辑。
    """

    project_slots = _collect_project_slots(items)
    if not project_slots:
        raise MergedWriteError("Cannot build project_settings.config without slots")

    meta_writer = _build_metadata_writer(items, output_path)
    source_settings = _first_source_project_settings(assemblies)
    if source_settings is None:
        source_settings = json.loads(
            meta_writer._build_project_settings_bytes().decode("utf-8")
        )

    settings = copy.deepcopy(source_settings)
    template_settings = copy.deepcopy(source_settings)
    slot_count = len(project_slots)
    _resize_project_setting_arrays(settings, slot_count, template_settings)

    settings["filament_colour"] = [_format_hex_color(slot) for slot in project_slots]
    if settings.get("filament_ids") is not None:
        settings["filament_ids"] = [str(slot.material_id) for slot in project_slots]
    settings.setdefault("single_extruder_multi_material", "1")
    settings["enable_prime_tower"] = "1"
    printer_settings_id = settings.get("printer_settings_id")
    if isinstance(printer_settings_id, str) and printer_settings_id.strip():
        settings["print_compatible_printers"] = [printer_settings_id]

    if placement is not None and placement_writer is not None:
        settings["wipe_tower_x"] = placement_writer._replace_first_config_number(
            settings.get("wipe_tower_x"),
            placement.tower_x,
        )
        settings["wipe_tower_y"] = placement_writer._replace_first_config_number(
            settings.get("wipe_tower_y"),
            placement.tower_y,
        )
        settings["prime_tower_width"] = placement_writer._format_number(
            placement.tower_width
        )
        settings["wipe_tower_rotation_angle"] = placement_writer._format_number(
            placement.tower_rotation
        )
        from utils.bambu_3mf_writer import _normalize_difference_index

        settings["different_settings_to_system"] = _normalize_difference_index(
            settings.get("different_settings_to_system"),
            (
                "wipe_tower_x",
                "wipe_tower_y",
                "prime_tower_width",
                "wipe_tower_rotation_angle",
                "enable_prime_tower",
            ),
        )

    colours = settings.get("filament_colour")
    if not isinstance(colours, list) or not colours:
        raise MergedWriteError("project_settings.config would contain no filament_colour entries")
    return json.dumps(settings, indent=4, ensure_ascii=False).encode("utf-8")


def _build_layer_config_ranges_xml_from_sources(
    assemblies: Sequence[_SourceAssembly],
) -> bytes | None:
    """Merge source layer-height ranges using Bambu's model-object indexes.

    ``Metadata/layer_config_ranges.xml`` does not use 3MF resource/build
    object ids. Bambu-family slicers read its ``object id`` as a one-based
    model-object index, so merged batch output must write 1, 2, 3... in build
    order instead of the generated assembly ids.
    """

    objects_root = ET.Element("objects")
    for model_index, assembly in enumerate(assemblies, start=1):
        payload = assembly.metadata_parts.get("Metadata/layer_config_ranges.xml")
        if payload is None:
            continue
        try:
            source_root = ET.fromstring(payload)
        except ET.ParseError:
            continue

        merged_obj = ET.Element("object", attrib={"id": str(model_index)})
        for source_obj in source_root.findall("object"):
            for range_elem in source_obj.findall("range"):
                merged_obj.append(copy.deepcopy(range_elem))
        if list(merged_obj):
            objects_root.append(merged_obj)

    if not list(objects_root):
        return None
    return _serialize_xml_plain(objects_root)


def _build_default_cut_information_bytes(assembly_object_ids: Sequence[int]) -> bytes:
    objects_root = ET.Element("objects")
    for model_index, _assembly_id in enumerate(assembly_object_ids, start=1):
        obj = ET.SubElement(objects_root, "object", attrib={"id": str(model_index)})
        ET.SubElement(
            obj,
            "cut_id",
            attrib={"id": "0", "check_sum": "1", "connectors_cnt": "0"},
        )
    return _serialize_xml_plain(objects_root)


def _build_filament_sequence_bytes_for_merge() -> bytes:
    """Build the Bambu multi-object filament sequence sidecar."""

    data = {
        "plate_1": {
            "nozzle_sequence": [],
            "optimal_assignment": [],
            "sequence": [],
        }
    }
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _first_metadata_part(
    assemblies: Sequence[_SourceAssembly], metadata_path: str
) -> bytes | None:
    for assembly in assemblies:
        payload = assembly.metadata_parts.get(metadata_path)
        if payload is not None:
            return payload
    return None


_DEFAULT_PLATE_METADATA: tuple[tuple[str, str], ...] = (
    ("plater_id", "1"),
    ("plater_name", ""),
    ("locked", "false"),
    ("filament_map_mode", "Auto For Flush"),
    ("thumbnail_file", "Metadata/plate_1.png"),
    ("thumbnail_no_light_file", "Metadata/plate_no_light_1.png"),
    ("top_file", "Metadata/top_1.png"),
    ("pick_file", "Metadata/pick_1.png"),
)


def _append_source_object_metadata(
    target_object: ET.Element,
    source_object_metadata: ET.Element | None,
) -> None:
    """Copy direct object metadata from a source model_settings object.

    只复制源 ``<object>`` 直属的 ``<metadata>``，不复制 ``<part>``，
    因为 part id 会在合并时重新编号。这样保留 ``extruder`` /
    ``face_count`` 等对象级信息，同时避免把旧 part 结构重复塞回去。
    """

    copied_extruder = False
    if source_object_metadata is not None:
        for child in list(source_object_metadata):
            if child.tag != "metadata":
                continue
            cloned = copy.deepcopy(child)
            if cloned.get("key") == "extruder":
                copied_extruder = True
            target_object.append(cloned)

    if not copied_extruder:
        ET.SubElement(
            target_object,
            "metadata",
            attrib={"key": "extruder", "value": "1"},
        )


def _find_first_source_plate(assemblies: Sequence[_SourceAssembly]) -> ET.Element | None:
    """Return the first reusable source ``<plate>`` metadata element."""

    for assembly in assemblies:
        if assembly.source_plate_metadata is not None:
            return assembly.source_plate_metadata
    return None


def _append_plate_metadata(
    plate: ET.Element,
    source_plate_metadata: ET.Element | None,
) -> None:
    """Append plate-level metadata, preferring the source 3MF shape.

    优先复用单件 3MF 已经写好的盘面 metadata；如果源文件没有 plate，
    才回退到旧单件 writer 的默认 Bambu/Orca 盘面字段。
    """

    if source_plate_metadata is not None:
        copied_any = False
        for child in list(source_plate_metadata):
            if child.tag != "metadata":
                continue
            plate.append(copy.deepcopy(child))
            copied_any = True
        if copied_any:
            return

    for key, value in _DEFAULT_PLATE_METADATA:
        ET.SubElement(plate, "metadata", attrib={"key": key, "value": value})


def _metadata_value(node: ET.Element, key: str) -> str | None:
    for metadata in node.findall("metadata"):
        if metadata.get("key") == key:
            return metadata.get("value")
    return None


def _build_bambu_metadata_files(
    items: Sequence[MergedItem],
    assemblies: Sequence[_SourceAssembly],
    assembly_object_ids: Sequence[int],
    output_path: Path,
    model_settings_bytes: bytes,
    *,
    placement_writer=None,
    placement=None,
) -> dict[str, bytes]:
    """Build all Bambu metadata parts for the merged package."""

    meta_writer = _build_metadata_writer(items, output_path)
    metadata_files: dict[str, bytes] = {
        "Metadata/model_settings.config": model_settings_bytes,
        "Metadata/project_settings.config": _build_project_settings_bytes_for_merge(
            items,
            assemblies,
            output_path,
            placement_writer=placement_writer,
            placement=placement,
        ),
        "Metadata/slice_info.config": _first_metadata_part(
            assemblies, "Metadata/slice_info.config"
        ) or meta_writer._build_slice_info_bytes(),
        "Metadata/filament_sequence.json": _build_filament_sequence_bytes_for_merge(),
        "Metadata/cut_information.xml": _build_default_cut_information_bytes(
            assembly_object_ids
        ),
    }

    layer_config = _build_layer_config_ranges_xml_from_sources(assemblies)
    if layer_config is not None:
        metadata_files["Metadata/layer_config_ranges.xml"] = layer_config

    custom_gcode = _first_metadata_part(assemblies, "Metadata/custom_gcode_per_layer.xml")
    if custom_gcode is not None:
        metadata_files["Metadata/custom_gcode_per_layer.xml"] = custom_gcode

    if placement_writer is not None:
        placement_writer._wipe_tower_placement_cache = placement
        metadata_files[
            "Metadata/lumina_wipe_tower_placement.json"
        ] = placement_writer._build_wipe_tower_placement_metadata_bytes()

    # Thumbnails are not essential for slicing, but copying existing ones keeps
    # the merged 3MF closer to packages produced by the single writer.
    for thumbnail_path in (*_BAMBU_THUMBNAIL_PARTS, *_AUXILIARY_THUMBNAIL_PARTS):
        payload = _first_metadata_part(assemblies, thumbnail_path)
        if payload is not None:
            metadata_files[thumbnail_path] = payload

    return metadata_files


def _build_content_types_bytes() -> bytes:
    """Build an OPC content-type table matching Bambu multi-object samples."""

    ct_root = ET.Element(f"{{{_NS_CONTENT_TYPES}}}Types")
    defaults = {
        "model": _CONTENT_TYPE_3DMODEL,
        "png": "image/png",
        "rels": _CONTENT_TYPE_RELS,
        "gcode": "text/x.gcode",
    }
    for extension, content_type in defaults.items():
        node = ET.SubElement(ct_root, f"{{{_NS_CONTENT_TYPES}}}Default")
        node.set("Extension", extension)
        node.set("ContentType", content_type)

    return _serialize_xml_for_ns(ct_root, _NS_CONTENT_TYPES)


def _build_model_relationships_bytes(per_item_model_paths: Sequence[str]) -> bytes:
    """Build ``3D/_rels/3dmodel.model.rels`` with per-item model rels.

    Bambu Studio's multi-object reference 3MFs keep Metadata/*.config files at
    their canonical package paths and do not attach them through this rels part.
    Mirroring that shape prevents the slicer from treating merged batch output
    as a generic 3MF without project/process settings.
    """

    rels_root = ET.Element(f"{{{_NS_RELS}}}Relationships")

    for idx, path in enumerate(per_item_model_paths, start=1):
        rel = ET.SubElement(rels_root, f"{{{_NS_RELS}}}Relationship")
        rel.set("Target", "/" + path)
        rel.set("Id", f"rel-{idx}")
        rel.set("Type", _REL_TYPE_3DMODEL)

    return _serialize_xml_for_ns(rels_root, _NS_RELS)


def _build_top_relationships_bytes(metadata_paths: Sequence[str]) -> bytes:
    """Build package root relationships with Bambu-style cover thumbnails."""

    rels_root = ET.Element(f"{{{_NS_RELS}}}Relationships")
    top_rel = ET.SubElement(rels_root, f"{{{_NS_RELS}}}Relationship")
    top_rel.set("Target", "/3D/3dmodel.model")
    top_rel.set("Id", "rel-1")
    top_rel.set("Type", _REL_TYPE_3DMODEL)

    metadata_set = set(metadata_paths)
    if "Auxiliaries/.thumbnails/thumbnail_3mf.png" in metadata_set:
        thumbnail_target = "/Auxiliaries/.thumbnails/thumbnail_3mf.png"
        middle_target = "/Auxiliaries/.thumbnails/thumbnail_middle.png"
        small_target = "/Auxiliaries/.thumbnails/thumbnail_small.png"
    else:
        thumbnail_target = "/Metadata/plate_1.png"
        middle_target = "/Metadata/plate_1.png"
        small_target = (
            "/Metadata/plate_1_small.png"
            if "Metadata/plate_1_small.png" in metadata_set
            else "/Metadata/plate_1.png"
        )

    thumbnail_rels = [
        (
            "rel-2",
            thumbnail_target,
            "http://schemas.openxmlformats.org/package/2006/relationships/metadata/thumbnail",
        ),
        (
            "rel-4",
            middle_target,
            "http://schemas.bambulab.com/package/2021/cover-thumbnail-middle",
        ),
        (
            "rel-5",
            small_target,
            "http://schemas.bambulab.com/package/2021/cover-thumbnail-small",
        ),
    ]
    for rel_id, target, rel_type in thumbnail_rels:
        if target.lstrip("/") not in metadata_set:
            continue
        rel = ET.SubElement(rels_root, f"{{{_NS_RELS}}}Relationship")
        rel.set("Target", target)
        rel.set("Id", rel_id)
        rel.set("Type", rel_type)

    return _serialize_xml_for_ns(rels_root, _NS_RELS)


# ---------------------------------------------------------------------------
# MergedBambu3MFWriter — multi-object merged 3MF writer
# ---------------------------------------------------------------------------


class MergedBambu3MFWriter:
    """Write N MergedItem objects into a SINGLE Bambu-compatible 3MF.

    每个 MergedItem 对应：
        - 1 个 per-item ``.model`` 文件（含该 item 的所有 mesh ``<object>``）
        - 1 个顶层 ``3D/3dmodel.model`` 中的 assembly ``<object>``
          （含 ``<components>`` 引用 per-item ``.model``）
        - 1 个 ``<build><item>`` 引用 assembly object（带 XY 平移 transform）
        - 1 个 ``Metadata/model_settings.config`` 中的 ``<object>``
          （含 ``<part>`` 子节点保留 Bambu 元数据）
        - 1 个 ``<plate><model_instance>`` 条目，将对象绑定到热床与工艺视图
        - 1 个 ``<assemble><assemble_item>`` 条目

    结构对齐 ``元数据分析/多项目参考.3mf`` 中
    ``3D/3dmodel.model``、``3D/_rels/3dmodel.model.rels``、
    ``Metadata/model_settings.config``。

    NOTE: 不修改 ``utils/bambu_3mf_writer.py::BambuStudio3MFWriter`` 的
    现有公开签名。
    """

    def write(
        self,
        items: Sequence[MergedItem],
        output_path: Path,
        *,
        plate_width_mm: float,
        plate_depth_mm: float,
    ) -> None:
        """Write merged 3MF to ``output_path``.

        Args:
            items: Sequence of MergedItem objects to merge.
            output_path: Destination path for the merged 3MF file.
            plate_width_mm: Plate X dimension (mm); stored in metadata.
            plate_depth_mm: Plate Y dimension (mm); stored in metadata.

        Raises:
            MergedWriteError: items is empty, source_3mf_path parse fails,
                OPC packaging fails, slots validation fails, disk IO fails.
        """
        if not items:
            raise MergedWriteError("items must not be empty")

        # Validate all items' slots upfront.
        for idx, item in enumerate(items):
            try:
                _validate_slots(item.slots)
            except MergedWriteError as exc:
                raise MergedWriteError(
                    f"MergedItem[{idx}] slots validation failed: {exc}"
                ) from exc

        # Parse all source 3MFs.
        assemblies: list[_SourceAssembly] = []
        for idx, item in enumerate(items):
            assemblies.append(_parse_source_assembly(idx, item))

        try:
            self._write_opc(items, assemblies, output_path, plate_width_mm, plate_depth_mm)
        except MergedWriteError:
            raise
        except (OSError, ET.ParseError) as exc:
            raise MergedWriteError(
                f"Failed to write merged 3MF to {output_path}: {exc}"
            ) from exc

    def _write_opc(
        self,
        items: Sequence[MergedItem],
        assemblies: list[_SourceAssembly],
        output_path: Path,
        plate_width_mm: float,
        plate_depth_mm: float,
    ) -> None:
        """Build and write the OPC (ZIP) archive using neroued_3mf.

        Uses neroued_3mf C++ library for per-item mesh serialization
        (proper XML with correct namespace prefixes, no ns0: pollution),
        and reuses BambuStudio3MFWriter's metadata builders for Bambu/Orca
        vendor metadata (project_settings, slice_info, model_settings, etc.).

        使用 neroued_3mf C++ 库序列化每个 item 的 mesh 数据（正确的 XML
        命名空间前缀），并复用 BambuStudio3MFWriter 的元数据构建器生成
        Bambu/Orca 厂商元数据。
        """
        import neroued_3mf as n3mf
        import uuid as _uuid

        placement_writer, placement, group_translation = (
            _resolve_merged_wipe_tower_placement(
                items,
                assemblies,
                output_path,
            )
        )
        if group_translation != (0.0, 0.0):
            items = tuple(
                replace(
                    item,
                    tx_mm=item.tx_mm + group_translation[0],
                    ty_mm=item.ty_mm + group_translation[1],
                )
                for item in items
            )

        N = len(items)
        next_id = 1

        per_item_model_paths: list[str] = []
        assembly_object_ids: list[int] = []
        per_item_mesh_ids: list[list[int]] = []
        per_item_face_counts: list[int] = []

        # Build per-item .model files using neroued_3mf for proper mesh XML.
        per_item_model_bytes_list: list[bytes] = []
        for idx in range(N):
            assembly = assemblies[idx]
            mesh_ids: list[int] = []

            per_item_bytes = _serialize_per_item_model_n3mf(
                n3mf, assembly, items[idx], next_id
            )
            for _mesh_idx in range(len(assembly.meshes)):
                mesh_ids.append(next_id)
                next_id += 1

            per_item_mesh_ids.append(mesh_ids)
            per_item_model_path = f"3D/Objects/object_{idx + 1}.model"
            per_item_model_paths.append(per_item_model_path)
            per_item_model_bytes_list.append(per_item_bytes)
            per_item_face_counts.append(_count_triangles_in_model(per_item_bytes))

        # Allocate assembly object IDs.
        for idx in range(N):
            assembly_id = next_id
            next_id += 1
            assembly_object_ids.append(assembly_id)

        # Build top-level 3D/3dmodel.model.
        main_model = ET.Element(_qname_core("model"))
        main_model.set("unit", "millimeter")
        main_model.set("xml:lang", "en-US")
        main_model.set("requiredextensions", "p")

        application = _first_source_root_metadata(assemblies, "Application")
        if not application:
            application = _build_metadata_writer(items, output_path)._get_app_version_str()
        ET.SubElement(
            main_model,
            _qname_core("metadata"),
            attrib={"name": "Application"},
        ).text = application
        ET.SubElement(
            main_model,
            _qname_core("metadata"),
            attrib={"name": "BambuStudio:3mfVersion"},
        ).text = _first_source_root_metadata(assemblies, "BambuStudio:3mfVersion") or "1"

        main_resources = ET.SubElement(main_model, _qname_core("resources"))
        for idx in range(N):
            assembly = assemblies[idx]
            obj_elem = ET.SubElement(main_resources, _qname_core("object"))
            obj_elem.set("id", str(assembly_object_ids[idx]))
            obj_elem.set("type", "model")

            components_elem = ET.SubElement(obj_elem, _qname_core("components"))
            per_item_path = "/" + per_item_model_paths[idx]
            for mesh_idx, mesh_id in enumerate(per_item_mesh_ids[idx]):
                comp = ET.SubElement(components_elem, _qname_core("component"))
                comp.set(_qname_prod("path"), per_item_path)
                comp.set("objectid", str(mesh_id))
                # Preserve source component transform (or identity).
                if mesh_idx < len(assembly.component_transforms):
                    src_transform = assembly.component_transforms[mesh_idx]
                else:
                    src_transform = None
                comp.set("transform", src_transform or "1 0 0 0 1 0 0 0 1 0 0 0")
                # Preserve or generate valid p:UUID.
                if mesh_idx < len(assembly.component_uuids):
                    src_uuid = assembly.component_uuids[mesh_idx]
                else:
                    src_uuid = None
                comp.set(_qname_prod("UUID"), src_uuid or str(_uuid.uuid4()))

        # Build section with transforms.
        build_elem = ET.SubElement(main_model, _qname_core("build"))
        build_elem.set(_qname_prod("UUID"), str(_uuid.uuid4()))
        for idx in range(N):
            item = items[idx]
            assembly = assemblies[idx]
            dx = item.tx_mm - assembly.min_x
            dy = item.ty_mm - assembly.min_y
            transform = f"1 0 0 0 1 0 0 0 1 {_format_float(dx)} {_format_float(dy)} 0"

            build_item = ET.SubElement(build_elem, _qname_core("item"))
            build_item.set("objectid", str(assembly_object_ids[idx]))
            build_item.set("transform", transform)
            build_item.set("printable", "1")
            build_item.set(_qname_prod("UUID"), str(_uuid.uuid4()))

        main_model_bytes = _serialize_xml_with_ns(main_model)

        # Build Metadata/model_settings.config.
        #
        # Bambu/Orca do not treat <object> alone as enough project
        # structure: the plate-level <model_instance> list is what binds
        # each object to the build plate and to its process/material UI.
        # Keep the shape aligned with the trusted single-item writer and
        # the multi-object reference files: objects -> plate -> assemble.
        config_root = ET.Element("config")

        for idx in range(N):
            item = items[idx]
            assembly = assemblies[idx]

            cfg_obj = ET.SubElement(config_root, "object")
            cfg_obj.set("id", str(assembly_object_ids[idx]))
            _append_source_object_metadata(
                cfg_obj,
                assembly.source_assembly_part_metadata,
            )
            if not any(
                child.tag == "metadata" and "face_count" in child.attrib
                for child in cfg_obj
            ):
                ET.SubElement(
                    cfg_obj,
                    "metadata",
                    attrib={"face_count": str(per_item_face_counts[idx])},
                )

            # Clone source part elements fully (preserving subtype, metadata,
            # mesh_stat etc.), only rewrite the id to the new mesh id.
            for mesh_idx, mesh_id in enumerate(per_item_mesh_ids[idx]):
                source_mesh = assembly.meshes[mesh_idx]
                if source_mesh.original_part_metadata is not None:
                    part_clone = copy.deepcopy(source_mesh.original_part_metadata)
                    part_clone.set("id", str(mesh_id))
                    cfg_obj.append(part_clone)
                else:
                    part_elem = ET.SubElement(cfg_obj, "part")
                    part_elem.set("id", str(mesh_id))
                    if mesh_idx < len(item.slots):
                        slot = item.slots[mesh_idx]
                        md_name = ET.SubElement(part_elem, "metadata")
                        md_name.set("key", "name")
                        md_name.set("value", slot.slot_name)
                        md_ext = ET.SubElement(part_elem, "metadata")
                        md_ext.set("key", "extruder")
                        md_ext.set("value", str(mesh_idx + 1))

            # Store original MaterialSlot quadruples as JSON for round-trip (P8).
            slots_json = json.dumps(
                [
                    {
                        "slot_id": s.slot_id,
                        "slot_name": s.slot_name,
                        "preview_color": s.preview_color,
                        "material_id": s.material_id,
                    }
                    for s in item.slots
                ],
                ensure_ascii=False,
            )
            md_slots = ET.SubElement(cfg_obj, "metadata")
            md_slots.set("key", _LUMINA_SLOTS_JSON_KEY)
            md_slots.set("value", slots_json)

        plate_elem = ET.SubElement(config_root, "plate")
        _append_plate_metadata(plate_elem, _find_first_source_plate(assemblies))
        for idx in range(N):
            model_instance = ET.SubElement(plate_elem, "model_instance")
            ET.SubElement(
                model_instance,
                "metadata",
                attrib={"key": "object_id", "value": str(assembly_object_ids[idx])},
            )
            ET.SubElement(
                model_instance,
                "metadata",
                attrib={"key": "instance_id", "value": "0"},
            )
            ET.SubElement(
                model_instance,
                "metadata",
                attrib={"key": "identify_id", "value": str(idx + 1)},
            )

        assemble_elem = ET.SubElement(config_root, "assemble")
        for idx in range(N):
            item = items[idx]
            assembly = assemblies[idx]
            dx = item.tx_mm - assembly.min_x
            dy = item.ty_mm - assembly.min_y

            # <assemble_item>
            assemble_item = ET.SubElement(assemble_elem, "assemble_item")
            assemble_item.set("object_id", str(assembly_object_ids[idx]))
            assemble_item.set("instance_id", "0")
            assemble_item.set(
                "transform",
                f"1 0 0 0 1 0 0 0 1 {_format_float(dx)} {_format_float(dy)} 0",
            )
            assemble_item.set("offset", f"{_format_float(dx)} {_format_float(dy)} 0")

        config_bytes = _serialize_xml_plain(config_root)

        # Generate Bambu vendor metadata by reusing the same metadata builders
        # and source metadata that single-item 3MF export already trusts.
        bambu_metadata_files = _build_bambu_metadata_files(
            items,
            assemblies,
            assembly_object_ids,
            output_path,
            config_bytes,
            placement_writer=placement_writer,
            placement=placement,
        )
        metadata_paths = list(bambu_metadata_files.keys())
        top_rels_bytes = _build_top_relationships_bytes(metadata_paths)
        rels_bytes = _build_model_relationships_bytes(per_item_model_paths)
        ct_bytes = _build_content_types_bytes()

        # Write the ZIP.
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("[Content_Types].xml", ct_bytes)
            zf.writestr("_rels/.rels", top_rels_bytes)
            zf.writestr("3D/3dmodel.model", main_model_bytes)
            zf.writestr("3D/_rels/3dmodel.model.rels", rels_bytes)
            for idx in range(N):
                zf.writestr(per_item_model_paths[idx], per_item_model_bytes_list[idx])
            for meta_path, meta_bytes in bambu_metadata_files.items():
                zf.writestr(meta_path, meta_bytes)

        # Post-write sanity check.
        self._sanity_check(output_path, per_item_model_paths)

    def _sanity_check(self, output_path: Path, per_item_model_paths: list[str]) -> None:
        """Post-write sanity check: verify the output 3MF is structurally valid."""
        try:
            with zipfile.ZipFile(output_path, "r") as zf:
                zip_names = set(zf.namelist())
                for model_path in per_item_model_paths:
                    if model_path not in zip_names:
                        raise MergedWriteError(
                            f"Sanity check failed: per-item model {model_path!r} "
                            "missing from output ZIP"
                        )
                # Check NO file in the ZIP contains ns0: prefix.
                for name in zip_names:
                    if name.endswith((".xml", ".model", ".rels")):
                        content = zf.read(name).decode("utf-8", errors="replace")
                        if "ns0:" in content:
                            raise MergedWriteError(
                                f"Sanity check failed: {name} contains 'ns0:' "
                                "prefix — namespace registration broken"
                            )
                # Must have project_settings.config (Bambu requirement).
                required_metadata = {
                    "Metadata/model_settings.config",
                    "Metadata/project_settings.config",
                    "Metadata/slice_info.config",
                }
                missing_metadata = sorted(required_metadata - zip_names)
                if missing_metadata:
                    raise MergedWriteError(
                        "Sanity check failed: missing Bambu metadata "
                        + ", ".join(missing_metadata)
                    )
                main_model_root = ET.fromstring(zf.read("3D/3dmodel.model"))
                root_metadata = {
                    node.get("name"): node.text or ""
                    for node in main_model_root.findall(_qname_core("metadata"))
                }
                if not root_metadata.get("Application"):
                    raise MergedWriteError(
                        "Sanity check failed: 3D/3dmodel.model missing "
                        "Application metadata"
                    )
                if not root_metadata.get("BambuStudio:3mfVersion"):
                    raise MergedWriteError(
                        "Sanity check failed: 3D/3dmodel.model missing "
                        "BambuStudio:3mfVersion metadata"
                    )

                # Match Bambu multi-object package samples: metadata files stay
                # at canonical paths and rely on the slicer's project parser,
                # while content types stay minimal.
                ct_root = ET.fromstring(zf.read("[Content_Types].xml"))
                default_extensions = {
                    node.get("Extension")
                    for node in ct_root.findall(f"{{{_NS_CONTENT_TYPES}}}Default")
                }
                for extension in ("gcode", "model", "png", "rels"):
                    if extension not in default_extensions:
                        raise MergedWriteError(
                            f"Sanity check failed: [Content_Types].xml missing "
                            f"Default Extension={extension!r}"
                        )

                project_settings = json.loads(
                    zf.read("Metadata/project_settings.config").decode("utf-8")
                )
                filament_colours = project_settings.get("filament_colour")
                if not isinstance(filament_colours, list) or not filament_colours:
                    raise MergedWriteError(
                        "Sanity check failed: project_settings.config has no "
                        "filament_colour entries"
                    )
                # Check package root relationships and their targets.
                top_rels_bytes = zf.read("_rels/.rels")
                top_rels_root = ET.fromstring(top_rels_bytes)
                ns_rels = "http://schemas.openxmlformats.org/package/2006/relationships"
                has_main_model_rel = False
                for rel in top_rels_root.findall(f"{{{ns_rels}}}Relationship"):
                    target = rel.get("Target", "").lstrip("/")
                    if target and target not in zip_names:
                        raise MergedWriteError(
                            f"Sanity check failed: root rels Target {target!r} "
                            "not in ZIP"
                        )
                    if target == "3D/3dmodel.model" and rel.get("Type") == _REL_TYPE_3DMODEL:
                        has_main_model_rel = True
                if not has_main_model_rel:
                    raise MergedWriteError(
                        "Sanity check failed: root rels missing 3D/3dmodel.model"
                    )

                # Check 3D/_rels targets exist and only point at per-item model
                # files, matching Bambu's own multi-object package shape.
                rels_bytes = zf.read("3D/_rels/3dmodel.model.rels")
                rels_root = ET.fromstring(rels_bytes)
                expected_model_targets = set(per_item_model_paths)
                object_rel_targets: set[str] = set()
                for rel in rels_root.findall(f"{{{ns_rels}}}Relationship"):
                    target = rel.get("Target", "").lstrip("/")
                    if target and target not in zip_names:
                        raise MergedWriteError(
                            f"Sanity check failed: rels Target {target!r} not in ZIP"
                        )
                    if rel.get("Type") == _REL_TYPE_BAMBU_SETTINGS:
                        raise MergedWriteError(
                            "Sanity check failed: Bambu metadata must not be "
                            "attached through 3D/_rels/3dmodel.model.rels"
                        )
                    if rel.get("Type") == _REL_TYPE_3DMODEL:
                        object_rel_targets.add(target)
                if object_rel_targets != expected_model_targets:
                    raise MergedWriteError(
                        "Sanity check failed: 3D model relationships "
                        f"{sorted(object_rel_targets)!r} != "
                        f"{sorted(expected_model_targets)!r}"
                    )
                # Count total vertices and triangles.
                total_vertices = 0
                total_triangles = 0
                for model_path in per_item_model_paths:
                    model_bytes = zf.read(model_path)
                    model_root = ET.fromstring(model_bytes)
                    for obj in model_root.iter(_qname_core("object")):
                        mesh = obj.find(_qname_core("mesh"))
                        if mesh is None:
                            continue
                        verts = mesh.find(_qname_core("vertices"))
                        tris = mesh.find(_qname_core("triangles"))
                        if verts is not None:
                            total_vertices += len(verts.findall(_qname_core("vertex")))
                        if tris is not None:
                            total_triangles += len(tris.findall(_qname_core("triangle")))
                if total_vertices == 0:
                    raise MergedWriteError("Sanity check failed: output 3MF has 0 vertices")
                if total_triangles == 0:
                    raise MergedWriteError("Sanity check failed: output 3MF has 0 triangles")
                # model_settings.config: each object must have at least one part.
                config_bytes_check = zf.read("Metadata/model_settings.config")
                config_root_check = ET.fromstring(config_bytes_check)
                config_objects = config_root_check.findall("object")
                for cfg_obj in config_objects:
                    parts = cfg_obj.findall("part")
                    if not parts:
                        obj_id = cfg_obj.get("id", "?")
                        raise MergedWriteError(
                            f"Sanity check failed: config object id={obj_id} has no parts"
                        )
                plate = config_root_check.find("plate")
                if plate is None:
                    raise MergedWriteError(
                        "Sanity check failed: model_settings.config has no plate"
                    )
                model_instances = plate.findall("model_instance")
                if len(model_instances) != len(config_objects):
                    raise MergedWriteError(
                        "Sanity check failed: model_instance count "
                        f"{len(model_instances)} != object count {len(config_objects)}"
                    )
                object_ids = {cfg_obj.get("id") for cfg_obj in config_objects}
                for instance in model_instances:
                    object_id = _metadata_value(instance, "object_id")
                    instance_id = _metadata_value(instance, "instance_id")
                    if object_id not in object_ids:
                        raise MergedWriteError(
                            "Sanity check failed: model_instance object_id "
                            f"{object_id!r} has no config object"
                        )
                    if instance_id != "0":
                        raise MergedWriteError(
                            "Sanity check failed: model_instance instance_id "
                            f"{instance_id!r} is not 0"
                        )
        except MergedWriteError:
            raise
        except Exception as exc:
            raise MergedWriteError(
                f"Sanity check failed: could not reopen output 3MF: {exc}"
            ) from exc


def _serialize_xml_with_ns(root: ET.Element) -> bytes:
    """Serialize a 3MF model element with proper namespace prefixes.

    Temporarily registers core as default namespace and 'p' for production.
    Uses a fresh BytesIO to avoid cross-contamination.
    """
    # These registrations are global but we always set them right before
    # serializing 3MF model files. The rels/content-types files use
    # _serialize_xml_for_ns which sets its own default before writing.
    ET.register_namespace("", _NS_CORE)
    ET.register_namespace("p", _NS_PROD)
    tree = ET.ElementTree(root)
    buf = io.BytesIO()
    tree.write(buf, encoding="utf-8", xml_declaration=True)
    return buf.getvalue()


def _serialize_xml_for_ns(root: ET.Element, default_ns: str) -> bytes:
    """Serialize an XML element with a specific default namespace.

    Registers the given namespace as default right before writing to avoid
    ns0: prefix pollution from other namespace registrations.
    """
    ET.register_namespace("", default_ns)
    tree = ET.ElementTree(root)
    buf = io.BytesIO()
    tree.write(buf, encoding="utf-8", xml_declaration=True)
    return buf.getvalue()


def _serialize_xml_plain(root: ET.Element) -> bytes:
    """Serialize an XML element without namespace registration.

    Used for model_settings.config which has no namespace.
    """
    tree = ET.ElementTree(root)
    buf = io.BytesIO()
    tree.write(buf, encoding="utf-8", xml_declaration=True)
    return buf.getvalue()


def _serialize_xml(root: ET.Element) -> bytes:
    """Legacy serializer — delegates to _serialize_xml_plain."""
    return _serialize_xml_plain(root)
