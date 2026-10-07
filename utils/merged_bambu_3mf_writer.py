"""Merge source geometry with Fat Cat metadata and one neroued package write.

复用源几何，由 Fat Cat 合成元数据，再由 neroued 一次写出批量或拼图 3MF。
"""

from __future__ import annotations

import json
import uuid
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping, Sequence

import numpy as np

if TYPE_CHECKING:
    from core.wipe_tower_placement import WipeTowerPlacementResult


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

    The first four fields are aligned with
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
        source_slot_index: Optional index in the source project's filament
            arrays. It differs from slot_id when puzzle palette order selects
            or reorders source slots.
            源项目耗材数组中的索引。拼图调色板选择或重排槽位时，它与 slot_id 不同。
    """

    slot_id: int
    slot_name: str
    preview_color: str
    material_id: str
    source_slot_index: int | None = None


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
        metadata: Fat Cat decoded metadata attached to this model object.
            Fat Cat 读取的模型对象元数据。
    """

    original_id: int
    element: ET.Element
    metadata: tuple[dict[str, str], ...]


@dataclass(frozen=True)
class _SourceAssembly:
    """The aggregate of one ``MergedItem`` after parsing its source 3MF.

    Attributes:
        meshes: All mesh ``<object>`` elements referenced by the source's
            top-level build item, in their declaration order.
        source_assembly_id: Source build object's id in the source 3MF.
        min_x: Minimum X vertex coordinate across all ``meshes`` (mm),
            after applying source component transforms.
        min_y: Minimum Y vertex coordinate across all ``meshes`` (mm),
            after applying source component transforms.
    component_transforms: Per-component transform strings from source.
    component_uuids: Per-component p:UUID strings from source.
    metadata_parts: Raw Bambu metadata parts copied from the source 3MF.
    project_settings: Parsed source project settings, if present.
    root_metadata: Top-level ``3D/3dmodel.model`` metadata from source.
    """

    meshes: tuple[_SourceMesh, ...]
    source_assembly_id: int
    source_assembly_uuid: str
    source_build_item_uuid: str
    min_x: float
    min_y: float
    max_x: float
    max_y: float
    min_z: float
    max_z: float
    component_transforms: tuple[str, ...]
    component_uuids: tuple[str, ...]
    base_material_groups: tuple[ET.Element, ...]
    metadata_parts: dict[str, bytes]
    project_settings: dict[str, Any] | None
    root_metadata: dict[str, str]
    source_metadata: dict[str, Any]
    source_model_index: int = 1


def _qname_core(tag: str) -> str:
    return f"{{{_NS_CORE}}}{tag}"


def _qname_prod(attr: str) -> str:
    return f"{{{_NS_PROD}}}{attr}"


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


def _parse_source_assembly(
    item_idx: int, item: MergedItem, *, metadata_target: Any | None = None,
) -> _SourceAssembly:
    """Parse one source 3MF and extract its mesh objects + metadata.

    解析单个源 3MF，提取该 item 的 mesh 对象与元数据。
    Preserves component transforms and UUIDs from source.
    """

    from utils.fatcat_metadata import _read_source_metadata_parts, read_model_object_metadata

    src_path = item.source_3mf_path
    if not isinstance(src_path, Path):
        src_path = Path(src_path)
    if not src_path.exists():
        raise MergedWriteError(
            f"MergedItem[{item_idx}].source_3mf_path does not exist: {src_path}"
        )

    try:
        with zipfile.ZipFile(src_path, "r") as zf:
            source_metadata, source_parts = _read_source_metadata_parts(
                zf, target=metadata_target,
            )
            main_model_bytes = source_parts.get("source_model")
            if main_model_bytes is None:
                raise MergedWriteError(
                    f"MergedItem[{item_idx}].source_3mf_path missing 3D/3dmodel.model"
                )

            main_root = _parse_xml_bytes(main_model_bytes)
            root_metadata = source_metadata["source_root_metadata"]

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
            source_assembly_uuid = assembly_elem.get(_qname_prod("UUID")) or ""
            source_build_item_uuid = (
                build_items[0].get(_qname_prod("UUID")) or ""
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
                p_path = comp.get(_qname_prod("path")) or "/3D/3dmodel.model"
                obj_id = comp.get("objectid")
                if not obj_id:
                    raise MergedWriteError(
                        f"MergedItem[{item_idx}].source_3mf_path has <component> without "
                        "objectid"
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
            object_metadata = {
                item["id"]: tuple(item["metadata"])
                for item in read_model_object_metadata(per_item_bytes.decode("utf-8"))
            }
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

            metadata_parts = {
                "Metadata/model_settings.config": source_parts["model_settings"],
            }
            if "slice_info" in source_parts:
                metadata_parts["Metadata/slice_info.config"] = source_parts["slice_info"]
            layer_ranges_path = "Metadata/layer_config_ranges.xml"
            if layer_ranges_path in zf.namelist():
                metadata_parts[layer_ranges_path] = zf.read(layer_ranges_path)
            project_settings = source_metadata["project_settings"]

            meshes: list[_SourceMesh] = []
            for orig_id, obj_elem in ordered_mesh_objs:
                meshes.append(
                    _SourceMesh(
                        original_id=int(orig_id) if orig_id.isdigit() else 0,
                        element=obj_elem,
                        metadata=object_metadata.get(orig_id, ()),
                    )
                )

            return _SourceAssembly(
                meshes=tuple(meshes),
                source_assembly_id=int(target_objectid),
                source_model_index=1,  # This parser selects build_items[0].
                source_assembly_uuid=source_assembly_uuid,
                source_build_item_uuid=source_build_item_uuid,
                min_x=min_x,
                min_y=min_y,
                max_x=max_x,
                max_y=max_y,
                min_z=min_z,
                max_z=max_z,
                component_transforms=tuple(component_transforms),
                component_uuids=tuple(component_uuids),
                base_material_groups=tuple(
                    per_item_resources.findall(_qname_core("basematerials"))
                ),
                metadata_parts=metadata_parts,
                project_settings=project_settings,
                root_metadata=root_metadata,
                source_metadata=source_metadata,
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


def _n3mf_transform(n3mf: Any, values: Sequence[float]) -> Any:
    transform = n3mf.Transform()
    transform.m = [float(value) for value in values]
    return transform


def _map_base_material_id(
    source_id: str | None, ids_by_source: dict[str, int]
) -> int | None:
    if source_id is None:
        return None
    mapped_id = ids_by_source.get(source_id)
    if mapped_id is None:
        raise MergedWriteError(f"Source material resource {source_id} is missing")
    return mapped_id


def _transformed_assembly_bbox(
    assembly: _SourceAssembly, transform: Sequence[float],
) -> list[float]:
    corners = np.asarray([
        (x, y, z)
        for x in (assembly.min_x, assembly.max_x)
        for y in (assembly.min_y, assembly.max_y)
        for z in (assembly.min_z, assembly.max_z)
    ], dtype=np.float64)
    # 3MF stores the 3x3 linear transform followed by its translation row.
    matrix = np.asarray(transform, dtype=np.float64)
    corners = corners @ matrix[:9].reshape(3, 3) + matrix[9:12]
    return [
        float(corners[:, 0].min()), float(corners[:, 1].min()),
        float(corners[:, 0].max()), float(corners[:, 1].max()),
    ]


def _infer_printer_id_from_settings(
    settings: dict[str, Any], *, slicer: str, nozzle_size: object,
) -> str:
    """Resolve a Lumina printer only from exact registry source identity."""

    from config import format_native_nozzle_size, list_printer_profiles
    from core.machine_registry import load_machine_registry, resolve_machine_registry_root

    source_name = str(settings.get("printer_settings_id") or "").strip()
    nozzle = format_native_nozzle_size(nozzle_size)
    if not source_name or not nozzle:
        raise MergedWriteError(
            "Merged export needs an explicit printer selection because its source "
            "project has no exact machine/nozzle identity"
        )
    registry_path = resolve_machine_registry_root() / "registry.json"
    registry = load_machine_registry(registry_path)
    devices = [
        profile for profile in registry.devices_by_id.values()
        if profile.supported
        and profile.slicer_id == slicer
        and profile.nozzle_size == nozzle
        and profile.source_profile_name == source_name
    ]
    identities = {
        (profile.display_name.casefold(), profile.brand.casefold())
        for profile in devices
    }
    matches = [
        profile for profile in list_printer_profiles()
        if (profile.display_name.casefold(), profile.brand.casefold()) in identities
        and nozzle in profile.supported_nozzle_sizes
    ]
    if len(matches) != 1:
        raise MergedWriteError(
            "Merged export could not map native machine identity exactly: "
            f"{slicer}/{source_name}/{nozzle} (Lumina matches: {len(matches)})"
        )
    return matches[0].id


def _resolve_merged_wipe_tower_placement(
    items: Sequence[MergedItem],
    assemblies: Sequence[_SourceAssembly],
    layout: Mapping[str, Any],
    *,
    enable_wipe_tower_auto_placement: bool,
    printer_id: str,
    slicer: str,
    nozzle_size: str,
    build_transforms: Sequence[Sequence[float]] | None = None,
) -> tuple[WipeTowerPlacementResult | None, tuple[float, float]]:
    """Solve one tower layout around the complete merged model group."""

    from core.wipe_tower_placement import Rect, solve_wipe_tower_placement

    from utils.bambu_3mf_writer import _build_wipe_tower_placement_request

    if not enable_wipe_tower_auto_placement:
        return None, (0.0, 0.0)
    if build_transforms is None:
        model_bounds = Rect(
            min(item.tx_mm for item in items),
            min(item.ty_mm for item in items),
            max(
                item.tx_mm + assembly.max_x - assembly.min_x
                for item, assembly in zip(items, assemblies)
            ),
            max(
                item.ty_mm + assembly.max_y - assembly.min_y
                for item, assembly in zip(items, assemblies)
            ),
        )
        model_height = max(
            assembly.max_z - assembly.min_z for assembly in assemblies
        )
        model_translation_locked = True
    else:
        model_bounds = Rect(
            min(
                assembly.min_x + float(transform[9])
                for assembly, transform in zip(assemblies, build_transforms)
            ),
            min(
                assembly.min_y + float(transform[10])
                for assembly, transform in zip(assemblies, build_transforms)
            ),
            max(
                assembly.max_x + float(transform[9])
                for assembly, transform in zip(assemblies, build_transforms)
            ),
            max(
                assembly.max_y + float(transform[10])
                for assembly, transform in zip(assemblies, build_transforms)
            ),
        )
        model_height = max(assembly.max_z for assembly in assemblies) - min(
            assembly.min_z for assembly in assemblies
        )
        model_translation_locked = False
    request = _build_wipe_tower_placement_request(
        layout,
        model_bounds=model_bounds,
        model_height=model_height,
        material_count=len({slot.slot_id for item in items for slot in item.slots}),
        printer_id=printer_id,
        slicer=slicer,
        nozzle_size=nozzle_size,
    )
    if request is None:
        placement = None
        translation = (0.0, 0.0)
    else:
        request = replace(request, model_translation_locked=model_translation_locked)
        placement = solve_wipe_tower_placement(request)
        translation = placement.model_translation
    return placement, translation


# ---------------------------------------------------------------------------
# MergedBambu3MFWriter — multi-object merged 3MF writer
# ---------------------------------------------------------------------------


class MergedBambu3MFWriter:
    """Merge source geometry and tuning into one native slicer project.

    将各源工程的几何和工艺合并为一个目标切片软件原生工程。

    FatCat merges metadata, material identities and object settings. This writer
    reuses source meshes/transforms and follows FatCat's core/Production layout
    policy, then asks Neroued to write one archive. The historical class name and
    public signature remain compatible with existing callers.
    FatCat 合并元数据、耗材身份和局部设置；此 writer 复用源网格及变换，
    按 FatCat 的布局规则调用 Neroued 单次写包，保留现有类名和公开签名。
    """

    def write(
        self,
        items: Sequence[MergedItem],
        output_path: Path,
        *,
        plate_width_mm: float,
        plate_depth_mm: float,
        enable_wipe_tower_auto_placement: bool = True,
        metadata_target: Any | None = None,
        printer_id: str | None = None,
        nozzle_size: str | None = None,
        device_profile_id: str | None = None,
        build_plate_id: str | None = None,
    ) -> None:
        """Write merged 3MF to ``output_path``.

        Args:
            items: Sequence of MergedItem objects to merge.
            output_path: Destination path for the merged 3MF file.
            plate_width_mm: Plate X dimension (mm); stored in metadata.
            plate_depth_mm: Plate Y dimension (mm); stored in metadata.
            enable_wipe_tower_auto_placement: Whether to solve and apply one
                wipe-tower layout for the full merged group. (是否为整个合并模型组
                求解并应用擦料塔自动布局。)
            metadata_target: Explicit Fat Cat target for the selected slicer.
                所选切片软件的明确 Fat Cat 目标。
            printer_id: Explicit Lumina printer profile used for layout.
                (布局使用的 Lumina 打印机配置。)
            nozzle_size: Explicit target nozzle size used for layout.
                (布局使用的目标喷嘴尺寸。)
            device_profile_id: Explicit slicer device profile used for layout.
                (布局使用的明确切片器设备配置。)
            build_plate_id: Explicit native build plate used for layout.
                (布局使用的明确原生打印板。)

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
            assemblies.append(_parse_source_assembly(
                idx, item, metadata_target=metadata_target,
            ))

        if metadata_target is None:
            from utils.fatcat_metadata import select_metadata_target

            source_layout = assemblies[0].source_metadata["layout"]
            source_nozzles = source_layout["nozzle_diameters"]
            source_nozzle = nozzle_size or (source_nozzles[0] if source_nozzles else None)
            source_slicer = assemblies[0].source_metadata["source_slicer"] or "BambuStudio"
            source_printer = printer_id or _infer_printer_id_from_settings(
                source_layout, slicer=source_slicer, nozzle_size=source_nozzle,
            )
            metadata_target = select_metadata_target(
                slicer=source_slicer, printer_id=source_printer, nozzle_size=source_nozzle,
                device_profile_id=device_profile_id, build_plate_id=build_plate_id,
            )
            if build_plate_id is None:
                metadata_target = replace(metadata_target, build_plate_uid="")
        try:
            self._write_fatcat_opc(
                items, assemblies, output_path, plate_width_mm, plate_depth_mm,
                enable_wipe_tower_auto_placement, metadata_target=metadata_target,
                printer_id=printer_id, nozzle_size=nozzle_size,
                device_profile_id=device_profile_id, build_plate_id=build_plate_id,
            )
        except MergedWriteError:
            raise
        except (OSError, ET.ParseError) as exc:
            raise MergedWriteError(
                f"Failed to write merged 3MF to {output_path}: {exc}"
            ) from exc

    def write_puzzle(
        self,
        items: Sequence[MergedItem],
        output_path: Path,
        *,
        build_transforms: Sequence[Sequence[float]],
        overview_png_bytes: bytes | None,
        metadata_target: Any,
        printer_id: str,
        nozzle_size: str,
        device_profile_id: str,
        build_plate_id: str,
        enable_wipe_tower_auto_placement: bool,
        source_materials: Sequence[Mapping[str, object]] | None = None,
    ) -> None:
        """Write puzzle pieces through Fat Cat and one neroued package build.

        通过 Fat Cat 和一次 neroued 写包输出拼图块。

        Args:
            items: Source piece 3MFs and their material slots.
                拼图源 3MF 和对应材料槽位。
            output_path: Destination 3MF path. (输出 3MF 路径)
            build_transforms: Lumina-computed root transforms per piece.
                Lumina 为每块计算的根变换。
            overview_png_bytes: Combined puzzle overview image. (拼图总览图字节)
            metadata_target: Explicit Fat Cat target. (明确的 Fat Cat 目标)
            printer_id: Selected printer profile. (所选打印机配置)
            nozzle_size: Selected nozzle size. (所选喷嘴尺寸)
            device_profile_id: Explicit slicer device profile.
                明确的切片器设备配置。
            build_plate_id: Explicit native build plate. (明确的原生打印板)
            enable_wipe_tower_auto_placement: Whether tower placement is enabled.
                是否启用擦料塔布局。
            source_materials: Optional ordered full palette for sparse sources.
                稀疏源项目可选的完整有序调色板。

        Raises:
            MergedWriteError: If the input count differs or a source cannot be parsed.
                输入数量不匹配或源文件无法解析时抛出。
        """
        if not items:
            raise MergedWriteError("items must not be empty")
        if len(items) != len(build_transforms):
            raise MergedWriteError(
                "Puzzle items and build transforms must have equal length"
            )

        assemblies = []
        for index, item in enumerate(items):
            _validate_slots(item.slots)
            assemblies.append(_parse_source_assembly(
                index, item, metadata_target=metadata_target,
            ))

        self._write_fatcat_opc(
            items,
            assemblies,
            output_path,
            0.0,
            0.0,
            enable_wipe_tower_auto_placement,
            metadata_target=metadata_target,
            printer_id=printer_id,
            nozzle_size=nozzle_size,
            device_profile_id=device_profile_id,
            build_plate_id=build_plate_id,
            build_transforms=build_transforms,
            source_materials=source_materials,
            resource_overrides={
                "plate_main": overview_png_bytes,
                "plate_no_light": overview_png_bytes,
                "top_preview": overview_png_bytes,
                "pick_preview": overview_png_bytes,
            } if overview_png_bytes is not None else None,
        )

    def _write_fatcat_opc(
        self,
        items: Sequence[MergedItem],
        assemblies: list[_SourceAssembly],
        output_path: Path,
        plate_width_mm: float,
        plate_depth_mm: float,
        enable_wipe_tower_auto_placement: bool,
        *,
        metadata_target: Any,
        printer_id: str | None,
        nozzle_size: str | None,
        device_profile_id: str | None,
        build_plate_id: str | None,
        build_transforms: Sequence[Sequence[float]] | None = None,
        resource_overrides: Mapping[str, bytes] | None = None,
        source_materials: Sequence[Mapping[str, object]] | None = None,
    ) -> None:
        import neroued_3mf as n3mf

        from config import normalize_slicer_software_id
        from utils.bambu_3mf_writer import (
            BambuStudio3MFWriter,
            _apply_metadata_components,
            _apply_root_model_metadata,
            _build_wipe_tower_placement_metadata_payload,
            _resolve_export_device,
        )
        from utils.bambu_3mf_cover import CoverThumbnailBuilder
        from utils.fatcat_metadata import (
            build_merged_model_metadata_request,
            build_merged_project_settings_request,
            compose_model_metadata,
            compose_project_settings,
            metadata_resource_specs,
            patch_wipe_tower,
            read_project_layout,
        )

        project_request = build_merged_project_settings_request(
            target=metadata_target,
            sources=[
                (str(index), assembly.project_settings, item.slots)
                for index, (assembly, item) in enumerate(zip(assemblies, items))
            ],
        )
        if source_materials:
            project_request.update({
                "source_materials": [dict(material) for material in source_materials],
                "machine_uid": metadata_target.machine_uid,
                "nozzle_uid": metadata_target.nozzle_uid,
            })
        project_result = compose_project_settings(
            assemblies[0].project_settings, project_request
        )
        final_project = json.loads(project_result["project_settings_json"])
        resolved_slicer = normalize_slicer_software_id(metadata_target.slicer_id)
        layout = read_project_layout(
            {**BambuStudio3MFWriter.DEFAULT_SETTINGS, **final_project},
            slicer_id=resolved_slicer,
        )
        source_layout = assemblies[0].source_metadata["layout"]
        source_nozzles = source_layout["nozzle_diameters"]
        source_nozzle = nozzle_size or (source_nozzles[0] if source_nozzles else None)
        resolved_printer_id = printer_id or _infer_printer_id_from_settings(
            source_layout,
            slicer=resolved_slicer,
            nozzle_size=source_nozzle,
        )
        resolved_nozzle_size, _, _ = _resolve_export_device(
            printer_id=resolved_printer_id,
            slicer=resolved_slicer,
            nozzle_size=source_nozzle,
            device_profile_id=str(device_profile_id or "").strip() or None,
            build_plate_id=str(build_plate_id or "").strip() or None,
        )
        placement, group_translation = _resolve_merged_wipe_tower_placement(
            items,
            assemblies,
            layout,
            enable_wipe_tower_auto_placement=enable_wipe_tower_auto_placement,
            printer_id=resolved_printer_id,
            slicer=resolved_slicer,
            nozzle_size=resolved_nozzle_size,
            build_transforms=build_transforms,
        )
        if build_transforms is None and group_translation != (0.0, 0.0):
            items = tuple(
                replace(
                    item,
                    tx_mm=item.tx_mm + group_translation[0],
                    ty_mm=item.ty_mm + group_translation[1],
                )
                for item in items
            )
        elif build_transforms is not None and group_translation != (0.0, 0.0):
            translated_transforms = []
            for transform in build_transforms:
                values = [float(value) for value in transform]
                values[9] += group_translation[0]
                values[10] += group_translation[1]
                translated_transforms.append(values)
            build_transforms = translated_transforms
        if placement is not None:
            final_project = patch_wipe_tower(
                final_project,
                {
                    "enabled": True,
                    "width_mm": placement.tower_width,
                    "rotation_deg": placement.tower_rotation,
                    "positions": [
                        {
                            "plate_index": 0,
                            "x_mm": placement.tower_x,
                            "y_mm": placement.tower_y,
                        }
                    ],
                },
                project_result["wipe_tower_dialect"],
            )

        source_mappings = {
            mapping["source_id"]: {
                slot["source_slot_index"]: slot["output_slot_index"]
                for slot in mapping["slots"]
            }
            for mapping in project_result["source_slot_mappings"]
        }
        builder = n3mf.DocumentBuilder()
        builder.set_unit(n3mf.Unit.Millimeter)
        builder.set_language("en-US")
        core_layout = project_result["metadata_defaults"].get("geometry_layout") == "core"
        if not core_layout:
            builder.enable_production()
            builder.set_production_build_uuid(str(uuid.uuid4()))

        material_group_ids: list[dict[str, int]] = []
        material_indexes: list[dict[str, dict[int, int]]] = []
        global_material_group = None
        palette_index = {}
        if source_materials:
            palette_index = {str(material["name"]): index for index, material in enumerate(source_materials)}
            global_material_group = builder.add_base_material_group([
                n3mf.BaseMaterial(str(material["name"]), n3mf.Color.from_hex(str(material["colour"])))
                for material in source_materials
            ])
        for assembly in assemblies:
            ids_by_source: dict[str, int] = {}
            indexes_by_source: dict[str, dict[int, int]] = {}
            for group in assembly.base_material_groups:
                source_group_id = group.get("id")
                materials = [
                    n3mf.BaseMaterial(
                        material.get("name") or "",
                        n3mf.Color.from_hex(
                            material.get("displaycolor") or "#FFFFFFFF"
                        ),
                    )
                    for material in group.findall(_qname_core("base"))
                ]
                target_group_id = (global_material_group if global_material_group is not None
                                   else builder.add_base_material_group(materials))
                if source_group_id is not None:
                    ids_by_source[source_group_id] = target_group_id
                    if global_material_group is not None:
                        indexes_by_source[source_group_id] = {
                            index: palette_index[material.get("name") or ""]
                            for index, material in enumerate(group.findall(_qname_core("base")))
                            if (material.get("name") or "") in palette_index
                        }
            material_group_ids.append(ids_by_source)
            material_indexes.append(indexes_by_source)

        def property_index(
            model_index: int, group_id: str | None, value: str | int,
        ) -> int:
            index = int(value)
            if global_material_group is None:
                return index
            try:
                return material_indexes[model_index - 1][group_id][index]
            except KeyError as exc:
                raise MergedWriteError("Source base material is absent from the selected palette") from exc

        metadata_models: list[dict[str, Any]] = []
        summary_objects: list[dict[str, Any]] = []
        assembly_ids_by_model: dict[int, int] = {}
        for model_index, (item, assembly) in enumerate(zip(items, assemblies), start=1):
            mesh_ids: list[int] = []
            face_count = 0
            for mesh_index, source_mesh in enumerate(assembly.meshes):
                vertices, faces = _extract_mesh_arrays(source_mesh.element)
                face_count += int(faces.shape[0])
                mesh = n3mf.Mesh.from_arrays(
                    np.ascontiguousarray(vertices, dtype=np.float64),
                    np.ascontiguousarray(faces, dtype=np.int64),
                )
                source_object = source_mesh.element
                source_pid = source_object.get("pid")
                source_pindex = source_object.get("pindex")
                target_pid = _map_base_material_id(
                    source_pid, material_group_ids[model_index - 1]
                )
                triangle_elements = source_object.findall(
                    f"{_qname_core('mesh')}/{_qname_core('triangles')}/"
                    f"{_qname_core('triangle')}"
                )
                if any(
                    any(name in triangle.attrib for name in ("pid", "p1", "p2", "p3"))
                    for triangle in triangle_elements
                ):
                    default_index = int(source_pindex or "0")
                    mesh.triangle_properties = [
                        n3mf.TriangleProperty(
                            _map_base_material_id(
                                triangle.get("pid") or source_pid,
                                material_group_ids[model_index - 1],
                            )
                            or 0,
                            property_index(model_index, triangle.get("pid") or source_pid, triangle.get("p1") or default_index),
                            property_index(model_index, triangle.get("pid") or source_pid, triangle.get("p2") or default_index),
                            property_index(model_index, triangle.get("pid") or source_pid, triangle.get("p3") or default_index),
                        )
                        for triangle in triangle_elements
                    ]

                source_name = source_object.get("name")
                if not source_name and mesh_index < len(item.slots):
                    source_name = item.slots[mesh_index].slot_name
                mesh_id = builder.add_mesh_object(
                    source_name or f"mesh_{mesh_index}",
                    mesh,
                    pid=target_pid,
                    pindex=property_index(model_index, source_pid, source_pindex) if source_pindex is not None else None,
                )
                mesh_ids.append(mesh_id)
                if source_object.get("partnumber"):
                    builder.set_part_number(mesh_id, source_object.get("partnumber"))
                for metadata in source_mesh.metadata:
                    builder.add_object_metadata(
                        mesh_id, metadata["name"], metadata["value"], metadata["type"],
                    )
                object_uuid = source_object.get(_qname_prod("UUID"))
                if object_uuid and not core_layout:
                    builder.set_object_uuid(mesh_id, object_uuid)
                if not core_layout and mesh_index < len(assembly.component_transforms):
                    builder.set_component_transform(
                        mesh_id,
                        _n3mf_transform(
                            n3mf,
                            _parse_transform_matrix(
                                assembly.component_transforms[mesh_index]
                            ),
                        ),
                    )
                if not core_layout and mesh_index < len(assembly.component_uuids):
                    component_uuid = assembly.component_uuids[mesh_index]
                    builder.set_component_uuid(
                        mesh_id, component_uuid or str(uuid.uuid4())
                    )
            if build_transforms is None:
                dx = item.tx_mm - assembly.min_x
                dy = item.ty_mm - assembly.min_y
                dz = 0.0
                build_transform = [
                    1.0, 0.0, 0.0,
                    0.0, 1.0, 0.0,
                    0.0, 0.0, 1.0,
                    dx, dy, dz,
                ]
            else:
                build_transform = [
                    float(value)
                    for value in build_transforms[model_index - 1]
                ]
                dx, dy, dz = build_transform[9:12]
            group_name = item.source_filename or f"object_{model_index}"
            if core_layout:
                group_id = builder.add_component_object(group_name, [
                    n3mf.Component(mesh_id, _n3mf_transform(
                        n3mf, _parse_transform_matrix(assembly.component_transforms[index]),
                    ))
                    for index, mesh_id in enumerate(mesh_ids)
                ])
            else:
                group_id = builder.add_production_group(
                    group_name, mesh_ids, assembly.source_assembly_uuid or str(uuid.uuid4()),
                )
            assembly_ids_by_model[model_index] = group_id
            source_id = str(model_index - 1)
            source_mapping = source_mappings[source_id]
            output_slot_count = len(project_result["merged_slots"])
            source_slot_count = assembly.source_metadata["project_filament_count"]
            source_slot_output_indexes = [
                source_mapping.get(index, output_slot_count)
                for index in range(source_slot_count)
            ]
            source_model_settings = assembly.metadata_parts[
                "Metadata/model_settings.config"
            ].decode("utf-8")
            model_request: dict[str, Any] = {
                "model_index": model_index,
                "assembly_id": group_id,
                "instance_id": "0",
                "identify_id": str(model_index),
                "source_assembly_id": assembly.source_assembly_id,
                "source_model_index": assembly.source_model_index,
                "source_model_settings_xml": source_model_settings,
                "face_count": face_count,
                "parts": [
                    {
                        "part_id": mesh_id,
                        "source_part_id": source_mesh.original_id,
                    }
                    for mesh_id, source_mesh in zip(mesh_ids, assembly.meshes)
                ],
                "source_slot_output_indexes": source_slot_output_indexes,
                "output_slot_count": output_slot_count,
                "default_slot_output_index": source_mapping.get(0, min(source_mapping.values())),
                "source_slots": [
                    {
                        "slot_id": slot.slot_id,
                        "slot_name": slot.slot_name,
                        "preview_color": slot.preview_color,
                        "material_id": slot.material_id,
                    }
                    for slot in item.slots
                ],
                "source_root_metadata": assembly.root_metadata,
                "transform": build_transform,
                "offset_mm": [dx, dy, dz],
            }
            layer_ranges = assembly.metadata_parts.get(
                "Metadata/layer_config_ranges.xml"
            )
            if layer_ranges is not None:
                model_request["source_layer_config_ranges_xml"] = (
                    layer_ranges.decode("utf-8")
                )
            metadata_models.append(model_request)
            summary_objects.append({
                "model_index": model_index,
                "name": item.source_filename or f"object_{model_index}",
                "bbox": _transformed_assembly_bbox(assembly, build_transform),
            })

        placement_payload = _build_wipe_tower_placement_metadata_payload(
            placement,
            enabled=enable_wipe_tower_auto_placement,
            output_path=str(output_path),
            printer_id=resolved_printer_id,
            slicer=resolved_slicer,
        )
        metadata_request = build_merged_model_metadata_request(
            target=metadata_target,
            objects=metadata_models,
            bed_type=project_result["metadata_defaults"]["plate_value"],
            wipe_tower_placement=placement_payload,
            source_slice_info_xml=(
                assemblies[0].metadata_parts["Metadata/slice_info.config"].decode(
                    "utf-8"
                )
                if "Metadata/slice_info.config" in assemblies[0].metadata_parts
                else None
            ),
        )
        metadata_request["output_options"] = {
            "emit_lumina_merged_slots_json": True,
        }
        if project_result["metadata_defaults"]["plate_summary"]:
            metadata_request["component_inputs"]["plate_summary"] = {
                "bbox_all": [
                    min(obj["bbox"][0] for obj in summary_objects),
                    min(obj["bbox"][1] for obj in summary_objects),
                    max(obj["bbox"][2] for obj in summary_objects),
                    max(obj["bbox"][3] for obj in summary_objects),
                ],
                "objects": summary_objects,
                "filament_colors": [slot["preview_color"] for slot in project_result["merged_slots"]],
                "layer_height": layout["layer_height"],
                "nozzle_diameter": layout["nozzle_diameters"][0],
                "bed_type": project_result["metadata_defaults"]["sidecar_bed_value"],
            }

        # Source previews describe their old geometry/layout, even for one input.
        resource_bytes: dict[str, bytes] = {}
        if resource_overrides:
            resource_bytes.update(resource_overrides)
        if "plate_main" in resource_bytes:
            cover = CoverThumbnailBuilder().build(resource_bytes["plate_main"])
            resource_bytes.update({
                "thumbnail_package": cover.thumbnail_3mf,
                "thumbnail_middle": cover.thumbnail_middle,
                "thumbnail_small": cover.thumbnail_small,
            })
            if "plate_small" in metadata_resource_specs(metadata_target.slicer_id):
                resource_bytes["plate_small"] = BambuStudio3MFWriter._build_plate_small_bytes(
                    resource_bytes["plate_main"]
                )
        metadata_request["resource_roles"] = list(resource_bytes)
        metadata_result = compose_model_metadata(final_project, metadata_request)
        _apply_root_model_metadata(builder, metadata_result["root_model"])
        _apply_metadata_components(builder, metadata_result, resource_bytes)

        for build_item in metadata_result["build_items"]:
            model_index = build_item["model_index"]
            properties = build_item["properties"]
            builder.add_build_item(
                assembly_ids_by_model[model_index],
                _n3mf_transform(
                    n3mf,
                    [float(value) for value in build_item["transform"].split()],
                ),
                uuid=(
                    "" if core_layout else (
                        assemblies[model_index - 1].source_build_item_uuid
                        or str(uuid.uuid4())
                    )
                ),
                auto_drop=properties.get("auto_drop", ""),
            )

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        document = builder.build()
        options = n3mf.WriteOptions()
        options.vertex_precision = 9
        options.compact_xml = True
        n3mf.write_to_file(str(output_path), document, options)
