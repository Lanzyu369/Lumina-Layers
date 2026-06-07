"""SVG/vector GLB preview exporters.

This module keeps vector GLB preview export separate from the large
``vector_branch`` orchestration file. V1 remains the default exporter; V2 is
an opt-in local path selected by ``LUMINA_VECTOR_GLB_KERNEL``.

SVG/vector GLB 预览导出模块。V1 默认保持不变；V2 通过
``LUMINA_VECTOR_GLB_KERNEL`` 本地开启，并且必须能回退 V1。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
import json
import os
import time
from typing import Literal

import numpy as np
import trimesh
from shapely.affinity import scale as shapely_scale
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from shapely.validation import make_valid
from trimesh.visual.material import PBRMaterial

from api.structured_logging import get_logger
from config import PrinterConfig
from core.pipeline.s11_glb_preview import _build_color_extruded_mesh_v2


log = get_logger(__name__)

_VECTOR_GLB_KERNEL_ENV_VAR = "LUMINA_VECTOR_GLB_KERNEL"
_GLTF_UINT16_COMPONENT_TYPE = 5123
_GLTF_UINT32_COMPONENT_TYPE = 5125
_GLTF_FLOAT_COMPONENT_TYPE = 5126
_GLTF_UINT16_MAX_INDEX = 65535
_GLTF_QUANTIZATION_EXTENSION = "KHR_mesh_quantization"
_V2_UINT16_CHUNK_VERTEX_LIMIT = _GLTF_UINT16_MAX_INDEX + 1
_V2_VECTOR_COMPONENT_COMPOSE_CHUNK_SIZE = 64

VectorPreviewRole = Literal["color", "backing", "outline", "auxiliary"]


@dataclass(frozen=True)
class VectorPreviewExtrusion:
    """One 2D footprint extrusion in display-space millimetres.

    一段显示坐标系中的 2D footprint + Z 范围挤出描述。
    """

    footprint: BaseGeometry
    z_min: float
    z_max: float
    footprints: tuple[BaseGeometry, ...] = field(default_factory=tuple)
    footprints_validated: bool = False

    def __post_init__(self) -> None:
        if self.footprints:
            object.__setattr__(self, "footprints", tuple(self.footprints))
        else:
            object.__setattr__(self, "footprints", (self.footprint,))


@dataclass(frozen=True)
class VectorPreviewPart:
    """One named GLB preview part consumed by V1 and V2 exporters.

    V1 可以使用 ``fallback_mesh``；V2 优先使用 ``extrusions``。
    """

    source_name: str
    export_name: str
    role: VectorPreviewRole
    rgba: tuple[int, int, int, int]
    is_recolorable: bool
    extrusions: tuple[VectorPreviewExtrusion, ...] = field(default_factory=tuple)
    fallback_mesh: trimesh.Trimesh | None = None


def resolve_vector_glb_kernel_choice() -> str:
    """Return the requested SVG GLB kernel.

    Returns:
        ``"trimesh_v1"`` for the current default path, or
        ``"rasterio_manifold3d"`` for the opt-in V2 path.

    返回当前 SVG GLB kernel 选择：默认 ``trimesh_v1``，本地开启时返回
    ``rasterio_manifold3d``。
    """

    raw = (os.environ.get(_VECTOR_GLB_KERNEL_ENV_VAR) or "").strip().lower()
    if raw in {"", "v1", "trimesh", "trimesh_v1"}:
        return "trimesh_v1"
    if raw in {"v2", "rasterio_manifold3d", "rasterio+manifold3d"}:
        return "rasterio_manifold3d"
    log.warning(
        "Unknown LUMINA_VECTOR_GLB_KERNEL value, falling back to V1",
        extra={
            "event": "vector_glb_kernel_unknown_value",
            "value": raw,
            "error_type": "ValueError",
            "fallback_kernel": "trimesh_v1",
        },
    )
    return "trimesh_v1"


def coerce_preview_rgba(value: object) -> tuple[int, int, int, int] | None:
    """Return a safe RGBA tuple, accepting 0-1 or 0-255 input."""

    if value is None:
        return None
    try:
        rgba = np.asarray(value, dtype=float).reshape(-1)
    except (TypeError, ValueError):
        return None
    if rgba.size < 3:
        return None
    if rgba.max(initial=0.0) <= 1.0:
        rgba = rgba * 255.0
    if rgba.size < 4:
        rgba = np.concatenate([rgba[:3], np.array([255.0])])
    safe = np.clip(rgba[:4], 0, 255).astype(np.uint8)
    return (int(safe[0]), int(safe[1]), int(safe[2]), int(safe[3]))


def make_vector_glb_export_name(
    *,
    source_name: str,
    role: VectorPreviewRole,
    rgba: tuple[int, int, int, int],
    seen_names: set[str],
) -> str:
    """Return a frontend-compatible GLB geometry name and reserve it."""

    if role == "color":
        base = f"color_{rgba[0]:02x}{rgba[1]:02x}{rgba[2]:02x}"
    elif role == "backing":
        base = "backing_plate"
    elif role == "outline":
        base = "Outline"
    else:
        base = str(source_name or "auxiliary")

    candidate = base
    suffix = 0
    while candidate in seen_names:
        suffix += 1
        candidate = f"{base}_{suffix}"
    seen_names.add(candidate)
    return candidate


def _role_for_geometry(geom_name: object, slot_list: list[str]) -> VectorPreviewRole:
    name = str(geom_name)
    if name == "Board":
        return "backing"
    if name == "Outline":
        return "outline"
    if name in {str(item) for item in slot_list}:
        return "color"
    return "auxiliary"


def _color_for_geometry(
    geom_name: object,
    *,
    preview_colors: dict,
    slot_list: list,
) -> tuple[int, int, int, int]:
    for key in (geom_name, str(geom_name)):
        if key in preview_colors:
            rgba = coerce_preview_rgba(preview_colors.get(key))
            if rgba is not None:
                return rgba

    try:
        slot_index = list(slot_list).index(str(geom_name))
    except ValueError:
        slot_index = -1
    if slot_index >= 0:
        rgba = coerce_preview_rgba(preview_colors.get(slot_index))
        if rgba is not None:
            return rgba

    return (200, 200, 200, 255)


def _mesh_with_rgba(
    mesh: trimesh.Trimesh,
    rgba: tuple[int, int, int, int],
) -> trimesh.Trimesh:
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    geom = trimesh.Trimesh(vertices=vertices.copy(), faces=faces.copy(), process=False)
    rgba_arr = np.asarray(rgba, dtype=np.uint8)
    geom.visual = trimesh.visual.ColorVisuals(
        mesh=geom,
        face_colors=np.tile(rgba_arr, (len(faces), 1)),
    )
    return geom


def _mesh_geometry_only_copy(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    return trimesh.Trimesh(vertices=vertices.copy(), faces=faces.copy(), process=False)


def _mesh_with_material_rgba(
    mesh: trimesh.Trimesh,
    rgba: tuple[int, int, int, int],
    *,
    material_name: str,
) -> trimesh.Trimesh:
    rgba_list = [int(value) for value in rgba]
    mesh.visual = trimesh.visual.TextureVisuals(
        material=PBRMaterial(
            name=material_name,
            baseColorFactor=rgba_list,
        )
    )
    return mesh


def _split_mesh_for_uint16_indices(
    mesh: trimesh.Trimesh,
    *,
    max_vertices: int = _V2_UINT16_CHUNK_VERTEX_LIMIT,
) -> list[trimesh.Trimesh]:
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    if len(vertices) <= max_vertices or len(faces) == 0:
        return [_mesh_geometry_only_copy(mesh)]

    chunks: list[trimesh.Trimesh] = []
    faces_per_vertex = max(1.0, len(faces) / max(1, len(vertices)))
    start = 0
    while start < len(faces):
        end = _find_uint16_chunk_end(
            faces,
            start,
            max_vertices=max_vertices,
            faces_per_vertex=faces_per_vertex,
        )
        chunks.append(_build_mesh_chunk(vertices, faces[start:end]))
        start = end
    return chunks


def _find_uint16_chunk_end(
    faces: np.ndarray,
    start: int,
    *,
    max_vertices: int,
    faces_per_vertex: float,
) -> int:
    face_count = len(faces)
    safe_face_count = max(1, max_vertices // 3)
    estimated_face_count = max(
        safe_face_count,
        int(max_vertices * max(1.0, faces_per_vertex) * 0.95),
    )
    candidate = min(face_count, start + estimated_face_count)
    if candidate >= face_count:
        if _count_unique_face_vertices(faces[start:face_count]) <= max_vertices:
            return face_count
    elif _count_unique_face_vertices(faces[start:candidate]) <= max_vertices:
        return candidate

    best = min(face_count, start + safe_face_count)
    if _count_unique_face_vertices(faces[start:best]) <= max_vertices and best >= face_count:
        return face_count

    high = candidate
    low = best + 1
    upper = high - 1
    while low <= upper:
        midpoint = (low + upper) // 2
        if _count_unique_face_vertices(faces[start:midpoint]) <= max_vertices:
            best = midpoint
            low = midpoint + 1
        else:
            upper = midpoint - 1
    return max(best, start + 1)


def _count_unique_face_vertices(faces: np.ndarray) -> int:
    return int(np.unique(faces).size)


def _build_mesh_chunk(
    source_vertices: np.ndarray,
    source_faces: np.ndarray,
) -> trimesh.Trimesh:
    unique_indices, inverse = np.unique(source_faces.reshape(-1), return_inverse=True)
    chunk_vertices = source_vertices[unique_indices]
    chunk_faces = inverse.reshape((-1, 3)).astype(np.int64, copy=False)
    return trimesh.Trimesh(
        vertices=chunk_vertices.copy(),
        faces=chunk_faces.copy(),
        process=False,
    )


def _pack_meshes_for_uint16_indices(
    meshes: list[trimesh.Trimesh],
    *,
    max_vertices: int = _V2_UINT16_CHUNK_VERTEX_LIMIT,
) -> list[trimesh.Trimesh]:
    chunks: list[trimesh.Trimesh] = []
    vertex_batches: list[np.ndarray] = []
    face_batches: list[np.ndarray] = []
    vertex_count = 0

    def flush() -> None:
        nonlocal vertex_batches, face_batches, vertex_count
        if not vertex_batches:
            return
        chunks.append(
            trimesh.Trimesh(
                vertices=np.concatenate(vertex_batches, axis=0),
                faces=np.concatenate(face_batches, axis=0),
                process=False,
            )
        )
        vertex_batches = []
        face_batches = []
        vertex_count = 0

    for mesh in meshes:
        source_chunks: list[tuple[np.ndarray, np.ndarray]]
        mesh_vertices = np.asarray(mesh.vertices, dtype=np.float64)
        mesh_faces = np.asarray(mesh.faces, dtype=np.int64)
        if len(mesh_vertices) <= max_vertices:
            source_chunks = [(mesh_vertices, mesh_faces)]
        else:
            source_chunks = [
                (
                    np.asarray(source_chunk.vertices, dtype=np.float64),
                    np.asarray(source_chunk.faces, dtype=np.int64),
                )
                for source_chunk in _split_mesh_for_uint16_indices(
                    mesh,
                    max_vertices=max_vertices,
                )
            ]
        for vertices, faces in source_chunks:
            if len(vertices) == 0 or len(faces) == 0:
                continue
            if vertex_batches and vertex_count + len(vertices) > max_vertices:
                flush()
            vertex_batches.append(vertices)
            face_batches.append(faces + vertex_count)
            vertex_count += len(vertices)
    flush()
    return chunks


def _scene_reuse_chunks_for_uint16_indices(
    mesh: trimesh.Trimesh,
    *,
    max_vertices: int = _V2_UINT16_CHUNK_VERTEX_LIMIT,
) -> list[trimesh.Trimesh]:
    vertices = getattr(mesh, "vertices", None)
    if vertices is None or len(vertices) <= max_vertices:
        return [mesh]
    return _split_mesh_for_uint16_indices(mesh, max_vertices=max_vertices)


def _ordered_key_at(mapping: dict, index: object) -> object | None:
    try:
        return list(mapping.keys())[int(index)]
    except (IndexError, TypeError, ValueError):
        return None


def _downcast_v2_index_buffers_to_uint16(buffer_items: dict, tree: dict) -> None:
    accessors = tree.get("accessors")
    if not isinstance(accessors, dict):
        return

    converted_views: dict[int, tuple[list[int], list[int]]] = {}
    for mesh in tree.get("meshes", []) or []:
        for primitive in mesh.get("primitives", []) or []:
            accessor_index = primitive.get("indices")
            if accessor_index is None:
                continue
            accessor_key = _ordered_key_at(accessors, accessor_index)
            if accessor_key is None:
                continue
            accessor = accessors.get(accessor_key)
            if not isinstance(accessor, dict):
                continue
            if accessor.get("componentType") != _GLTF_UINT32_COMPONENT_TYPE:
                continue
            try:
                min_index = int(accessor.get("min", [0])[0])
                max_index = int(accessor.get("max", [0])[0])
                buffer_view = int(accessor["bufferView"])
            except (KeyError, TypeError, ValueError, IndexError):
                continue
            if buffer_view in converted_views:
                accessor["componentType"] = _GLTF_UINT16_COMPONENT_TYPE
                accessor["min"], accessor["max"] = converted_views[buffer_view]
                continue
            if min_index < 0 or max_index > _GLTF_UINT16_MAX_INDEX:
                continue
            buffer_key = _ordered_key_at(buffer_items, buffer_view)
            if buffer_key is None:
                continue
            raw = buffer_items.get(buffer_key)
            if raw is None:
                continue
            try:
                data = np.frombuffer(raw, dtype="<u4", count=int(accessor.get("count", 0)))
            except ValueError:
                continue
            if data.size == 0 or int(data.max(initial=0)) > _GLTF_UINT16_MAX_INDEX:
                continue
            downcast = data.astype("<u2").tobytes()
            if len(downcast) % 4:
                downcast += b"\x00" * (4 - (len(downcast) % 4))
            min_values = [int(data.min(initial=0))]
            max_values = [int(data.max(initial=0))]
            buffer_items[buffer_key] = downcast
            accessor["componentType"] = _GLTF_UINT16_COMPONENT_TYPE
            accessor["min"] = min_values
            accessor["max"] = max_values
            converted_views[buffer_view] = (min_values, max_values)


def _sort_v2_triangle_index_buffers_for_gzip(buffer_items: dict, tree: dict) -> None:
    accessors = tree.get("accessors")
    if not isinstance(accessors, dict):
        return

    sorted_views: set[tuple[object, int, int, str]] = set()
    for mesh in tree.get("meshes", []) or []:
        if not isinstance(mesh, dict):
            continue
        for primitive in mesh.get("primitives", []) or []:
            if not isinstance(primitive, dict):
                continue
            if int(primitive.get("mode", 4) or 4) != 4:
                continue
            accessor_index = primitive.get("indices")
            if accessor_index is None:
                continue
            accessor_key = _ordered_key_at(accessors, accessor_index)
            if accessor_key is None:
                continue
            accessor = accessors.get(accessor_key)
            if not isinstance(accessor, dict) or accessor.get("type") != "SCALAR":
                continue
            component_type = accessor.get("componentType")
            if component_type == _GLTF_UINT16_COMPONENT_TYPE:
                dtype = "<u2"
            elif component_type == _GLTF_UINT32_COMPONENT_TYPE:
                dtype = "<u4"
            else:
                continue
            try:
                count = int(accessor.get("count", 0) or 0)
                buffer_view = int(accessor["bufferView"])
                byte_offset = int(accessor.get("byteOffset", 0) or 0)
            except (KeyError, TypeError, ValueError):
                continue
            if count <= 0 or count % 3 != 0:
                continue
            buffer_key = _ordered_key_at(buffer_items, buffer_view)
            if buffer_key is None:
                continue
            raw = buffer_items.get(buffer_key)
            if not isinstance(raw, (bytes, bytearray)):
                continue
            view_key = (buffer_key, byte_offset, count, dtype)
            if view_key in sorted_views:
                continue
            itemsize = np.dtype(dtype).itemsize
            byte_length = count * itemsize
            if byte_offset < 0 or byte_offset + byte_length > len(raw):
                continue
            try:
                indices = np.frombuffer(
                    raw[byte_offset : byte_offset + byte_length],
                    dtype=dtype,
                ).reshape((-1, 3))
            except ValueError:
                continue
            if len(indices) <= 1:
                continue
            order = np.lexsort((indices[:, 1], indices[:, 0]))
            sorted_indices = indices[order].reshape(-1).astype(dtype, copy=False)
            updated = bytearray(raw)
            updated[byte_offset : byte_offset + byte_length] = sorted_indices.tobytes()
            buffer_items[buffer_key] = bytes(updated)
            sorted_views.add(view_key)


def _quantize_v2_position_buffers_to_uint16(buffer_items: dict, tree: dict) -> None:
    accessors = tree.get("accessors")
    if not isinstance(accessors, dict):
        return
    meshes = tree.get("meshes") or []
    nodes = tree.get("nodes") or []
    converted_any = False

    for mesh_index, mesh in enumerate(meshes):
        if not isinstance(mesh, dict):
            continue
        primitives = mesh.get("primitives") or []
        if len(primitives) != 1:
            continue
        primitive = primitives[0]
        if not isinstance(primitive, dict):
            continue
        position_accessor_index = (primitive.get("attributes") or {}).get("POSITION")
        position_accessor_key = _ordered_key_at(accessors, position_accessor_index)
        if position_accessor_key is None:
            continue
        accessor = accessors.get(position_accessor_key)
        if not _is_quantizable_position_accessor(accessor):
            continue
        mesh_nodes = [
            node
            for node in nodes
            if isinstance(node, dict) and node.get("mesh") == mesh_index
        ]
        if not mesh_nodes or any(_node_has_transform(node) for node in mesh_nodes):
            continue
        quantized = _quantized_position_buffer(buffer_items, accessor)
        if quantized is None:
            continue
        buffer_key, quantized_bytes, quantized_min, quantized_max, translation, scale = quantized
        buffer_items[buffer_key] = quantized_bytes
        accessor["componentType"] = _GLTF_UINT16_COMPONENT_TYPE
        accessor["normalized"] = True
        accessor["byteOffset"] = 0
        accessor["min"] = quantized_min
        accessor["max"] = quantized_max
        for node in mesh_nodes:
            node["translation"] = translation
            node["scale"] = scale
        converted_any = True

    if converted_any:
        extensions = set(tree.get("extensionsUsed") or [])
        extensions.add(_GLTF_QUANTIZATION_EXTENSION)
        tree["extensionsUsed"] = sorted(extensions)


def _sort_quantized_position_buffers_for_gzip(buffer_items: dict, tree: dict) -> None:
    accessors = tree.get("accessors")
    if not isinstance(accessors, dict):
        return

    position_orders: dict[tuple[object, int, int], tuple[np.ndarray, np.ndarray]] = {}
    remapped_index_views: set[tuple[object, int, int, str]] = set()
    sorted_attribute_views: set[tuple[object, int, int, str, int]] = set()
    for mesh in tree.get("meshes") or []:
        if not isinstance(mesh, dict):
            continue
        for primitive in mesh.get("primitives", []) or []:
            if not isinstance(primitive, dict):
                continue
            if int(primitive.get("mode", 4) or 4) != 4:
                continue
            position_accessor = _quantized_position_accessor_for_primitive(
                primitive,
                accessors,
            )
            if position_accessor is None:
                continue
            index_accessor = _index_accessor_for_primitive(primitive, accessors)
            if index_accessor is None:
                continue
            sort_result = _sort_quantized_position_accessor(
                buffer_items,
                position_accessor,
                position_orders,
            )
            if sort_result is None:
                continue
            order, remap = sort_result
            _sort_vertex_attribute_accessors_for_position_order(
                buffer_items,
                primitive,
                accessors,
                order,
                sorted_attribute_views,
            )
            _remap_index_accessor_for_sorted_positions(
                buffer_items,
                index_accessor,
                remap,
                remapped_index_views,
            )


def _quantized_position_accessor_for_primitive(
    primitive: dict,
    accessors: dict,
) -> dict | None:
    position_accessor_index = (primitive.get("attributes") or {}).get("POSITION")
    position_accessor_key = _ordered_key_at(accessors, position_accessor_index)
    if position_accessor_key is None:
        return None
    accessor = accessors.get(position_accessor_key)
    if not isinstance(accessor, dict):
        return None
    if (
        accessor.get("componentType") != _GLTF_UINT16_COMPONENT_TYPE
        or accessor.get("normalized") is not True
        or accessor.get("type") != "VEC3"
    ):
        return None
    return accessor


def _index_accessor_for_primitive(primitive: dict, accessors: dict) -> dict | None:
    accessor_index = primitive.get("indices")
    if accessor_index is None:
        return None
    accessor_key = _ordered_key_at(accessors, accessor_index)
    if accessor_key is None:
        return None
    accessor = accessors.get(accessor_key)
    if not isinstance(accessor, dict) or accessor.get("type") != "SCALAR":
        return None
    return accessor


def _sort_quantized_position_accessor(
    buffer_items: dict,
    accessor: dict,
    position_orders: dict[tuple[object, int, int], tuple[np.ndarray, np.ndarray]],
) -> tuple[np.ndarray, np.ndarray] | None:
    try:
        count = int(accessor.get("count", 0) or 0)
        buffer_view = int(accessor["bufferView"])
        byte_offset = int(accessor.get("byteOffset", 0) or 0)
    except (KeyError, TypeError, ValueError):
        return None
    if count <= 0 or byte_offset < 0:
        return None
    buffer_key = _ordered_key_at(buffer_items, buffer_view)
    if buffer_key is None:
        return None
    view_key = (buffer_key, byte_offset, count)
    if view_key in position_orders:
        return position_orders[view_key]
    raw = buffer_items.get(buffer_key)
    if not isinstance(raw, (bytes, bytearray)):
        return None
    byte_length = count * 3 * np.dtype("<u2").itemsize
    if byte_offset + byte_length > len(raw):
        return None
    try:
        positions = np.frombuffer(
            raw[byte_offset : byte_offset + byte_length],
            dtype="<u2",
        ).reshape((count, 3))
    except ValueError:
        return None
    order = np.lexsort((positions[:, 2], positions[:, 1], positions[:, 0]))
    inverse = np.empty(len(order), dtype=np.int64)
    inverse[order] = np.arange(len(order), dtype=np.int64)
    if not np.array_equal(order, np.arange(len(order), dtype=np.int64)):
        sorted_positions = positions[order].astype("<u2", copy=False)
        updated = bytearray(raw)
        updated[byte_offset : byte_offset + byte_length] = sorted_positions.tobytes()
        buffer_items[buffer_key] = bytes(updated)
    result = (order, inverse)
    position_orders[view_key] = result
    return result


def _sort_vertex_attribute_accessors_for_position_order(
    buffer_items: dict,
    primitive: dict,
    accessors: dict,
    order: np.ndarray,
    sorted_attribute_views: set[tuple[object, int, int, str, int]],
) -> None:
    attributes = primitive.get("attributes")
    if not isinstance(attributes, dict):
        return
    for attribute_name, accessor_index in attributes.items():
        if attribute_name == "POSITION":
            continue
        accessor_key = _ordered_key_at(accessors, accessor_index)
        if accessor_key is None:
            continue
        accessor = accessors.get(accessor_key)
        if not isinstance(accessor, dict):
            continue
        _sort_vertex_attribute_accessor_for_position_order(
            buffer_items,
            accessor,
            order,
            sorted_attribute_views,
        )


def _sort_vertex_attribute_accessor_for_position_order(
    buffer_items: dict,
    accessor: dict,
    order: np.ndarray,
    sorted_attribute_views: set[tuple[object, int, int, str, int]],
) -> None:
    if accessor.get("sparse") is not None:
        return
    dtype, component_count = _vertex_attribute_accessor_layout(accessor)
    if dtype is None or component_count <= 0:
        return
    try:
        count = int(accessor.get("count", 0) or 0)
        buffer_view = int(accessor["bufferView"])
        byte_offset = int(accessor.get("byteOffset", 0) or 0)
    except (KeyError, TypeError, ValueError):
        return
    if count != len(order) or count <= 0 or byte_offset < 0:
        return
    buffer_key = _ordered_key_at(buffer_items, buffer_view)
    if buffer_key is None:
        return
    raw = buffer_items.get(buffer_key)
    if not isinstance(raw, (bytes, bytearray)):
        return
    itemsize = np.dtype(dtype).itemsize
    byte_length = count * component_count * itemsize
    if byte_offset + byte_length > len(raw):
        return
    view_key = (buffer_key, byte_offset, count, dtype, component_count)
    if view_key in sorted_attribute_views:
        return
    try:
        data = np.frombuffer(
            raw[byte_offset : byte_offset + byte_length],
            dtype=dtype,
        ).reshape((count, component_count))
    except ValueError:
        return
    sorted_data = data[order].astype(dtype, copy=False)
    updated = bytearray(raw)
    updated[byte_offset : byte_offset + byte_length] = sorted_data.tobytes()
    buffer_items[buffer_key] = bytes(updated)
    sorted_attribute_views.add(view_key)


def _vertex_attribute_accessor_layout(accessor: dict) -> tuple[str | None, int]:
    component_type_to_dtype = {
        5120: "<i1",
        5121: "<u1",
        5122: "<i2",
        _GLTF_UINT16_COMPONENT_TYPE: "<u2",
        _GLTF_UINT32_COMPONENT_TYPE: "<u4",
        _GLTF_FLOAT_COMPONENT_TYPE: "<f4",
    }
    type_to_component_count = {
        "SCALAR": 1,
        "VEC2": 2,
        "VEC3": 3,
        "VEC4": 4,
    }
    dtype = component_type_to_dtype.get(accessor.get("componentType"))
    component_count = type_to_component_count.get(accessor.get("type"), 0)
    return dtype, component_count


def _remap_index_accessor_for_sorted_positions(
    buffer_items: dict,
    accessor: dict,
    remap: np.ndarray,
    remapped_index_views: set[tuple[object, int, int, str]],
) -> None:
    component_type = accessor.get("componentType")
    if component_type == _GLTF_UINT16_COMPONENT_TYPE:
        dtype = "<u2"
    elif component_type == _GLTF_UINT32_COMPONENT_TYPE:
        dtype = "<u4"
    else:
        return
    try:
        count = int(accessor.get("count", 0) or 0)
        buffer_view = int(accessor["bufferView"])
        byte_offset = int(accessor.get("byteOffset", 0) or 0)
    except (KeyError, TypeError, ValueError):
        return
    if count <= 0 or byte_offset < 0:
        return
    buffer_key = _ordered_key_at(buffer_items, buffer_view)
    if buffer_key is None:
        return
    view_key = (buffer_key, byte_offset, count, dtype)
    if view_key in remapped_index_views:
        return
    raw = buffer_items.get(buffer_key)
    if not isinstance(raw, (bytes, bytearray)):
        return
    itemsize = np.dtype(dtype).itemsize
    byte_length = count * itemsize
    if byte_offset + byte_length > len(raw):
        return
    try:
        indices = np.frombuffer(
            raw[byte_offset : byte_offset + byte_length],
            dtype=dtype,
        )
    except ValueError:
        return
    if indices.size == 0 or int(indices.max(initial=0)) >= len(remap):
        return
    remapped = remap[indices].astype(dtype, copy=False)
    updated = bytearray(raw)
    updated[byte_offset : byte_offset + byte_length] = remapped.tobytes()
    buffer_items[buffer_key] = bytes(updated)
    accessor["min"] = [int(remapped.min(initial=0))]
    accessor["max"] = [int(remapped.max(initial=0))]
    remapped_index_views.add(view_key)


def _is_quantizable_position_accessor(accessor: object) -> bool:
    return (
        isinstance(accessor, dict)
        and accessor.get("componentType") == _GLTF_FLOAT_COMPONENT_TYPE
        and accessor.get("type") == "VEC3"
        and int(accessor.get("count", 0) or 0) > 0
        and "bufferView" in accessor
    )


def _node_has_transform(node: dict) -> bool:
    return any(key in node for key in ("matrix", "translation", "rotation", "scale"))


def _quantized_position_buffer(
    buffer_items: dict,
    accessor: dict,
) -> tuple[object, bytes, list[int], list[int], list[float], list[float]] | None:
    try:
        count = int(accessor["count"])
        buffer_view = int(accessor["bufferView"])
        byte_offset = int(accessor.get("byteOffset", 0) or 0)
    except (KeyError, TypeError, ValueError):
        return None
    if count <= 0 or byte_offset != 0:
        return None
    buffer_key = _ordered_key_at(buffer_items, buffer_view)
    if buffer_key is None:
        return None
    raw = buffer_items.get(buffer_key)
    if not isinstance(raw, (bytes, bytearray)):
        return None
    byte_length = count * 3 * np.dtype("<f4").itemsize
    if len(raw) < byte_length:
        return None
    try:
        positions = np.frombuffer(raw[:byte_length], dtype="<f4").reshape((count, 3))
    except ValueError:
        return None
    if positions.size == 0 or not np.isfinite(positions).all():
        return None
    mins = positions.min(axis=0).astype(np.float64)
    maxs = positions.max(axis=0).astype(np.float64)
    scale = maxs - mins
    safe_scale = np.where(scale > 0.0, scale, 1.0)
    normalized = np.clip((positions.astype(np.float64) - mins) / safe_scale, 0.0, 1.0)
    quantized = np.rint(normalized * _GLTF_UINT16_MAX_INDEX).astype("<u2")
    for axis in np.where(scale <= 0.0)[0]:
        quantized[:, axis] = 0
    quantized_bytes = quantized.tobytes()
    if len(quantized_bytes) % 4:
        quantized_bytes += b"\x00" * (4 - (len(quantized_bytes) % 4))
    return (
        buffer_key,
        quantized_bytes,
        quantized.min(axis=0).astype(int).tolist(),
        quantized.max(axis=0).astype(int).tolist(),
        mins.tolist(),
        scale.tolist(),
    )


def _optimize_v2_glb_buffers(buffer_items: dict, tree: dict) -> None:
    _downcast_v2_index_buffers_to_uint16(buffer_items, tree)
    _quantize_v2_position_buffers_to_uint16(buffer_items, tree)
    _sort_quantized_position_buffers_for_gzip(buffer_items, tree)
    _sort_v2_triangle_index_buffers_for_gzip(buffer_items, tree)
    _deduplicate_v2_materials(tree)


def _deduplicate_v2_materials(tree: dict) -> None:
    materials = tree.get("materials")
    if not isinstance(materials, list) or len(materials) < 2:
        return

    seen: dict[str, int] = {}
    old_to_new: dict[int, int] = {}
    deduplicated: list[object] = []
    for index, material in enumerate(materials):
        key = _material_dedup_key(material)
        if key is None or key not in seen:
            old_to_new[index] = len(deduplicated)
            if key is not None:
                seen[key] = old_to_new[index]
            deduplicated.append(material)
            continue
        old_to_new[index] = seen[key]

    if len(deduplicated) == len(materials):
        return

    for mesh in tree.get("meshes") or []:
        if not isinstance(mesh, dict):
            continue
        for primitive in mesh.get("primitives") or []:
            if not isinstance(primitive, dict) or "material" not in primitive:
                continue
            try:
                old_material = int(primitive["material"])
            except (TypeError, ValueError):
                continue
            if old_material in old_to_new:
                primitive["material"] = old_to_new[old_material]
    tree["materials"] = deduplicated


def _material_dedup_key(material: object) -> str | None:
    if not isinstance(material, dict):
        return None
    canonical = {
        key: value
        for key, value in material.items()
        if key != "name"
    }
    return json.dumps(canonical, sort_keys=True, separators=(",", ":"))


def _write_glb_scene(
    glb_scene: trimesh.Scene,
    output_path: str,
    *,
    optimize_v2_buffers: bool = False,
) -> str:
    export_kwargs = {"file_type": "glb"}
    if optimize_v2_buffers:
        export_kwargs["buffer_postprocessor"] = _optimize_v2_glb_buffers
    exported = glb_scene.export(output_path, **export_kwargs)
    if isinstance(exported, (bytes, bytearray)):
        with open(output_path, "wb") as glb_file:
            glb_file.write(exported)
    if not os.path.exists(output_path):
        raise RuntimeError(f"Vector GLB export did not create file: {output_path}")
    return output_path


def build_vector_preview_parts_from_scene(
    *,
    scene: trimesh.Scene,
    preview_colors: dict,
    slot_list: list,
    copy_fallback_mesh: bool = True,
) -> list[VectorPreviewPart]:
    """Build fallback descriptors from an already display-oriented scene."""

    seen_names: set[str] = set()
    parts: list[VectorPreviewPart] = []
    for geom_name, source_geom in scene.geometry.items():
        vertices = getattr(source_geom, "vertices", None)
        faces = getattr(source_geom, "faces", None)
        if vertices is None or faces is None or len(vertices) == 0 or len(faces) == 0:
            continue
        role = _role_for_geometry(geom_name, list(slot_list))
        rgba = _color_for_geometry(
            geom_name,
            preview_colors=preview_colors,
            slot_list=list(slot_list),
        )
        export_name = make_vector_glb_export_name(
            source_name=str(geom_name),
            role=role,
            rgba=rgba,
            seen_names=seen_names,
        )
        parts.append(
            VectorPreviewPart(
                source_name=str(geom_name),
                export_name=export_name,
                role=role,
                rgba=rgba,
                is_recolorable=(role == "color"),
                fallback_mesh=(
                    _mesh_geometry_only_copy(source_geom)
                    if copy_fallback_mesh
                    else source_geom
                ),
            )
        )
    return parts


def export_vector_glb_preview_v1(
    parts: list[VectorPreviewPart],
    *,
    output_path: str,
) -> str:
    """Export a GLB by copying descriptor fallback meshes.

    复制 descriptor 中的 V1 fallback mesh，保持现有 GLB 行为。
    """

    glb_scene = trimesh.Scene()
    for part in parts:
        mesh = part.fallback_mesh
        if mesh is None:
            raise RuntimeError(f"V1 export requires fallback mesh for {part.source_name}")
        vertices = getattr(mesh, "vertices", None)
        faces = getattr(mesh, "faces", None)
        if vertices is None or faces is None or len(vertices) == 0 or len(faces) == 0:
            continue
        glb_scene.add_geometry(
            _mesh_with_rgba(mesh, part.rgba),
            geom_name=part.export_name,
        )

    if not glb_scene.geometry:
        raise RuntimeError("Vector GLB export has no non-empty geometries")
    return _write_glb_scene(glb_scene, output_path)


def export_vector_glb_preview_v2_scene_reuse(
    parts: list[VectorPreviewPart],
    *,
    output_path: str,
) -> str:
    """Export GLB by reusing the already-built V1 preview scene meshes.

    The geometry comes from the compatibility-proven scene path; V2 only
    changes GLB serialization details such as material colors and buffer
    post-processing.
    """

    t0 = time.perf_counter()
    glb_scene = trimesh.Scene()
    for part in parts:
        mesh = part.fallback_mesh
        if mesh is None:
            raise RuntimeError(f"V2 scene-reuse export requires mesh for {part.source_name}")
        vertices = getattr(mesh, "vertices", None)
        faces = getattr(mesh, "faces", None)
        if vertices is None or faces is None or len(vertices) == 0 or len(faces) == 0:
            continue
        chunks = _scene_reuse_chunks_for_uint16_indices(mesh)
        for index, chunk in enumerate(chunks):
            export_name = (
                part.export_name
                if len(chunks) == 1
                else f"{part.export_name}_chunk{index + 1:03d}"
            )
            glb_scene.add_geometry(
                _mesh_with_material_rgba(
                    chunk,
                    part.rgba,
                    material_name=f"{part.export_name}_material",
                ),
                geom_name=export_name,
            )

    if not glb_scene.geometry:
        raise RuntimeError("V2 scene-reuse GLB export has no non-empty geometries")
    result = _write_glb_scene(
        glb_scene,
        output_path,
        optimize_v2_buffers=True,
    )
    log.info(
        "Vector GLB V2 scene-reuse exported",
        extra={
            "event": "vector_glb_v2_scene_reuse_exported",
            "path": str(output_path),
            "part_count": len(parts),
            "geometry_count": len(glb_scene.geometry),
            "duration_ms": round((time.perf_counter() - t0) * 1000, 3),
        },
    )
    return result


@lru_cache(maxsize=1)
def _get_vector_v2_rasterizer_modules():
    """Return cached rasterio helpers for vector V2 footprint rasterization."""
    from rasterio.features import rasterize
    from rasterio.transform import from_origin

    return rasterize, from_origin


def _valid_geometry(geometry: BaseGeometry | None) -> BaseGeometry | None:
    if geometry is None or getattr(geometry, "is_empty", True):
        return None
    try:
        if not geometry.is_valid:
            geometry = make_valid(geometry)
    except (AttributeError, ValueError, TypeError):
        return None
    if geometry is None or getattr(geometry, "is_empty", True):
        return None
    return geometry


def _scaled_geometry_mm(geometry: BaseGeometry, scale_factor: float) -> BaseGeometry | None:
    try:
        return _valid_geometry(
            shapely_scale(
                geometry,
                xfact=scale_factor,
                yfact=scale_factor,
                origin=(0.0, 0.0),
            )
        )
    except (ValueError, TypeError, AttributeError):
        return None


def _analysis_silhouette(analysis: object, scale_factor: float) -> BaseGeometry | None:
    silhouette = _analysis_silhouette_raw(analysis)
    if silhouette is None:
        return None
    return _scaled_geometry_mm(silhouette, scale_factor)


def _analysis_silhouette_raw(analysis: object) -> BaseGeometry | None:
    silhouette = _valid_geometry(getattr(analysis, "silhouette", None))
    if silhouette is not None:
        return silhouette

    geometries: list[BaseGeometry] = []
    for shape in getattr(analysis, "matched_shapes", []) or []:
        geom = _valid_geometry(shape.get("geometry") if isinstance(shape, dict) else None)
        if geom is not None:
            geometries.append(geom)
    if not geometries:
        return None
    try:
        return _valid_geometry(unary_union(geometries))
    except (ValueError, TypeError, AttributeError):
        return None


def _filter_backing_holes(geometry: BaseGeometry, min_hole_area: float) -> BaseGeometry:
    if isinstance(geometry, Polygon):
        holes = [
            hole
            for hole in geometry.interiors
            if Polygon(hole).area >= min_hole_area
        ]
        return Polygon(geometry.exterior, holes)
    if isinstance(geometry, MultiPolygon):
        return MultiPolygon(
            [
                _filter_backing_holes(polygon, min_hole_area)
                for polygon in geometry.geoms
                if not polygon.is_empty
            ]
        )
    return geometry


def _prepare_backing_footprint(
    geometry: BaseGeometry,
    scale_factor: float,
) -> BaseGeometry | None:
    prepared = _valid_geometry(geometry)
    if prepared is None:
        return None
    try:
        closed = prepared.buffer(0.4, join_style="mitre", mitre_limit=2.0)
        if not closed.is_empty:
            closed = closed.buffer(-0.4, join_style="mitre", mitre_limit=2.0)
            if not closed.is_empty:
                prepared = _valid_geometry(closed) or prepared
    except (ValueError, TypeError, AttributeError):
        pass
    try:
        filtered = _filter_backing_holes(prepared, min_hole_area=0.3)
        prepared = _valid_geometry(filtered) or prepared
    except (ValueError, TypeError, AttributeError):
        pass
    try:
        expanded = prepared.buffer(0.15, join_style="mitre", mitre_limit=2.0)
        if not expanded.is_empty:
            prepared = _valid_geometry(expanded) or prepared
    except (ValueError, TypeError, AttributeError):
        pass
    return _scaled_geometry_mm(prepared, scale_factor)


def _analysis_backing_footprint(
    analysis: object,
    scale_factor: float,
    fallback_silhouette: BaseGeometry | None,
) -> BaseGeometry | None:
    backing = _valid_geometry(getattr(analysis, "image_vectorizer_bounds", None))
    if backing is not None:
        return _prepare_backing_footprint(backing, scale_factor)
    if fallback_silhouette is not None:
        return _prepare_backing_footprint(fallback_silhouette, scale_factor)
    return None


def _recipe_channel_runs(recipe: list[int]) -> list[tuple[int, int, int]]:
    runs: list[tuple[int, int, int]] = []
    start = 0
    while start < len(recipe):
        channel = int(recipe[start])
        end = start + 1
        while end < len(recipe) and int(recipe[end]) == channel:
            end += 1
        runs.append((channel, start, end))
        start = end
    return runs


def _slot_name_for_channel(channel: int, slot_list: list) -> str:
    if 0 <= channel < len(slot_list):
        return str(slot_list[channel])
    return f"channel_{channel}"


def build_vector_preview_parts_from_analysis(
    *,
    analysis: object,
    preview_colors: dict,
    slot_list: list,
    structure_mode: object,
    color_mode: object,
    thickness_mm: float,
    separate_backing: bool,
    include_backing: bool,
    include_outline: bool,
    outline_width_mm: float,
) -> list[VectorPreviewPart]:
    """Build V2 footprint descriptors from vector analysis geometry.

    从 vector analysis 的 2D 几何构建 V2 footprint 描述。第一版只描述普通
    颜色层、普通底板和普通 Outline。
    """

    del color_mode
    try:
        scale_factor = float(getattr(analysis, "scale_factor", 1.0) or 1.0)
    except (TypeError, ValueError):
        scale_factor = 1.0
    if scale_factor <= 0:
        scale_factor = 1.0

    try:
        layer_h = float(getattr(PrinterConfig, "LAYER_HEIGHT", 0.08) or 0.08)
    except (TypeError, ValueError):
        layer_h = 0.08

    seen_names: set[str] = set()
    grouped: dict[int, list[VectorPreviewExtrusion]] = {}
    for shape in getattr(analysis, "matched_shapes", []) or []:
        if not isinstance(shape, dict):
            continue
        geom = _valid_geometry(shape.get("geometry"))
        recipe_raw = shape.get("recipe") or []
        if geom is None or not recipe_raw:
            continue
        geom_mm = _scaled_geometry_mm(geom, scale_factor)
        if geom_mm is None:
            continue
        try:
            recipe = [int(channel) for channel in recipe_raw]
        except (TypeError, ValueError):
            continue
        for channel, start_layer, end_layer in _recipe_channel_runs(recipe):
            grouped.setdefault(channel, []).append(
                VectorPreviewExtrusion(
                    footprint=geom_mm,
                    z_min=float(start_layer) * layer_h,
                    z_max=float(end_layer) * layer_h,
                )
            )

    parts: list[VectorPreviewPart] = []
    for channel in sorted(grouped):
        source_name = _slot_name_for_channel(channel, list(slot_list))
        rgba = _color_for_geometry(
            source_name,
            preview_colors=preview_colors,
            slot_list=list(slot_list),
        )
        export_name = make_vector_glb_export_name(
            source_name=source_name,
            role="color",
            rgba=rgba,
            seen_names=seen_names,
        )
        parts.append(
            VectorPreviewPart(
                source_name=source_name,
                export_name=export_name,
                role="color",
                rgba=rgba,
                is_recolorable=True,
                extrusions=tuple(grouped[channel]),
            )
        )

    raw_silhouette = _analysis_silhouette_raw(analysis)
    silhouette = (
        _scaled_geometry_mm(raw_silhouette, scale_factor)
        if raw_silhouette is not None
        else None
    )
    backing_footprint = _analysis_backing_footprint(
        analysis,
        scale_factor,
        raw_silhouette,
    )
    if include_backing and backing_footprint is not None:
        backing_height = max(float(thickness_mm or 0.0), layer_h)
        is_double = "双面" in str(structure_mode or "") or "Double" in str(structure_mode or "")
        z_min = -backing_height if separate_backing or not is_double else 0.0
        z_max = 0.0 if separate_backing or not is_double else backing_height
        rgba = _color_for_geometry(
            "Board",
            preview_colors=preview_colors,
            slot_list=list(slot_list),
        )
        parts.append(
            VectorPreviewPart(
                source_name="Board",
                export_name=make_vector_glb_export_name(
                    source_name="Board",
                    role="backing",
                    rgba=rgba,
                    seen_names=seen_names,
                ),
                role="backing",
                rgba=rgba,
                is_recolorable=False,
                extrusions=(
                    VectorPreviewExtrusion(
                        footprint=backing_footprint,
                        z_min=float(z_min),
                        z_max=float(z_max),
                    ),
                ),
            )
        )

    if include_outline and silhouette is not None:
        try:
            outline = _valid_geometry(
                silhouette.buffer(float(outline_width_mm)).difference(silhouette)
            )
        except (ValueError, TypeError, AttributeError):
            outline = None
        if outline is not None:
            max_z = max(
                (extrusion.z_max for part in parts for extrusion in part.extrusions),
                default=layer_h,
            )
            rgba = _color_for_geometry(
                "Outline",
                preview_colors=preview_colors,
                slot_list=list(slot_list),
            )
            parts.append(
                VectorPreviewPart(
                    source_name="Outline",
                    export_name=make_vector_glb_export_name(
                        source_name="Outline",
                        role="outline",
                        rgba=rgba,
                        seen_names=seen_names,
                    ),
                    role="outline",
                    rgba=rgba,
                    is_recolorable=False,
                    extrusions=(
                        VectorPreviewExtrusion(
                            footprint=outline,
                            z_min=0.0,
                            z_max=float(max_z),
                        ),
                    ),
                )
            )

    return parts


def _mesh_from_extrusion_v2(
    extrusion: VectorPreviewExtrusion,
    *,
    rgba: tuple[int, int, int, int],
    pixels_per_mm: float,
) -> trimesh.Trimesh:
    if extrusion.footprints_validated:
        footprints = tuple(extrusion.footprints or (extrusion.footprint,))
    else:
        footprints = _valid_footprints_for_v2(
            extrusion.footprints or (extrusion.footprint,)
        )
    if not footprints:
        raise RuntimeError("V2 vector GLB extrusion has no valid footprints")
    minx, miny, maxx, maxy = _bounds_for_footprints(footprints)
    width = max(1, int(np.ceil((maxx - minx) * pixels_per_mm)))
    height = max(1, int(np.ceil((maxy - miny) * pixels_per_mm)))

    try:
        rasterize, from_origin = _get_vector_v2_rasterizer_modules()
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"V2 vector GLB rasterizer unavailable: {exc}") from exc

    transform = from_origin(minx, maxy, 1.0 / pixels_per_mm, 1.0 / pixels_per_mm)
    mask = rasterize(
        [(footprint, 1) for footprint in footprints],
        out_shape=(height, width),
        transform=transform,
        fill=0,
        all_touched=True,
        dtype=np.uint8,
    ).astype(bool)
    if not np.any(mask):
        raise RuntimeError("V2 vector GLB footprint rasterized to an empty mask")

    z_height = extrusion.z_max - extrusion.z_min
    if z_height <= 0:
        raise RuntimeError("V2 vector GLB extrusion has non-positive height")
    total_layers = max(1, int(round(z_height * pixels_per_mm)))
    mesh = _build_color_extruded_mesh_v2(
        mask=mask,
        height=height,
        total_layers=total_layers,
        rgba=np.asarray(rgba, dtype=np.uint8),
        assign_face_colors=False,
        component_compose_chunk_size=_V2_VECTOR_COMPONENT_COMPOSE_CHUNK_SIZE,
    )
    if mesh is None:
        raise RuntimeError("V2 vector GLB mesh kernel returned no mesh")

    transform_mm = np.eye(4)
    transform_mm[0, 0] = 1.0 / pixels_per_mm
    transform_mm[1, 1] = 1.0 / pixels_per_mm
    transform_mm[2, 2] = z_height / float(total_layers)
    transform_mm[0, 3] = minx
    transform_mm[1, 3] = miny
    transform_mm[2, 3] = extrusion.z_min
    mesh.apply_transform(transform_mm)
    return mesh


def _valid_footprints_for_v2(
    footprints: tuple[BaseGeometry, ...] | list[BaseGeometry],
) -> tuple[BaseGeometry, ...]:
    return tuple(
        valid
        for footprint in footprints
        if (valid := _valid_geometry(footprint)) is not None
    )


def _bounds_for_footprints(
    footprints: tuple[BaseGeometry, ...] | list[BaseGeometry],
) -> tuple[float, float, float, float]:
    bounds = np.asarray([footprint.bounds for footprint in footprints], dtype=float)
    return (
        float(np.min(bounds[:, 0])),
        float(np.min(bounds[:, 1])),
        float(np.max(bounds[:, 2])),
        float(np.max(bounds[:, 3])),
    )


def _batch_part_extrusions_for_v2(
    part: VectorPreviewPart,
) -> list[VectorPreviewExtrusion]:
    grouped: dict[tuple[float, float], list[BaseGeometry]] = {}
    for extrusion in part.extrusions:
        key = (float(extrusion.z_min), float(extrusion.z_max))
        grouped.setdefault(key, []).extend(extrusion.footprints or (extrusion.footprint,))

    batched: list[VectorPreviewExtrusion] = []
    for (z_min, z_max), footprints in grouped.items():
        valid_footprints = _valid_footprints_for_v2(footprints)
        if not valid_footprints:
            continue
        batched.append(
            VectorPreviewExtrusion(
                footprint=valid_footprints[0],
                z_min=z_min,
                z_max=z_max,
                footprints=valid_footprints,
                footprints_validated=True,
            )
        )
    return batched


def export_vector_glb_preview_v2(
    parts: list[VectorPreviewPart],
    *,
    output_path: str,
    pixels_per_mm: float = 10.0,
) -> str:
    """Export GLB by generating meshes from descriptor footprints."""

    t0 = time.perf_counter()
    glb_scene = trimesh.Scene()
    for part in parts:
        if not part.extrusions:
            raise RuntimeError(f"V2 export requires footprints for {part.source_name}")
        batched_extrusions = _batch_part_extrusions_for_v2(part)
        if not batched_extrusions:
            raise RuntimeError(f"V2 export has no valid footprints for {part.source_name}")
        meshes = [
            _mesh_from_extrusion_v2(
                extrusion,
                rgba=part.rgba,
                pixels_per_mm=pixels_per_mm,
            )
            for extrusion in batched_extrusions
        ]
        if part.role == "color":
            chunks = _pack_meshes_for_uint16_indices(meshes)
        else:
            combined = trimesh.util.concatenate(meshes) if len(meshes) > 1 else meshes[0]
            chunks = [_mesh_geometry_only_copy(combined)]
        if not chunks:
            raise RuntimeError(f"V2 export has no mesh chunks for {part.source_name}")
        for index, chunk in enumerate(chunks):
            export_name = (
                part.export_name
                if len(chunks) == 1
                else f"{part.export_name}_chunk{index + 1:03d}"
            )
            glb_scene.add_geometry(
                _mesh_with_material_rgba(
                    chunk,
                    part.rgba,
                    material_name=f"{export_name}_material",
                ),
                geom_name=export_name,
            )
    if not glb_scene.geometry:
        raise RuntimeError("V2 vector GLB export has no geometry")
    result = _write_glb_scene(
        glb_scene,
        output_path,
        optimize_v2_buffers=True,
    )
    log.info(
        "Vector GLB V2 exported",
        extra={
            "event": "vector_glb_v2_exported",
            "path": str(output_path),
            "part_count": len(parts),
            "geometry_count": len(glb_scene.geometry),
            "duration_ms": round((time.perf_counter() - t0) * 1000, 3),
        },
    )
    return result


def export_vector_glb_preview(
    *,
    scene: trimesh.Scene,
    output_path: str,
    structure_mode: object,
    color_mode: object,
    preview_colors: dict,
    slot_list: list,
    analysis: object | None,
    ctx: dict | None,
) -> str:
    """Dispatch SVG GLB preview export with whole-export V1 fallback."""

    kernel = resolve_vector_glb_kernel_choice()
    fallback_parts = build_vector_preview_parts_from_scene(
        scene=scene,
        preview_colors=preview_colors,
        slot_list=list(slot_list),
        copy_fallback_mesh=(kernel == "trimesh_v1"),
    )
    if kernel == "trimesh_v1":
        return export_vector_glb_preview_v1(fallback_parts, output_path=output_path)

    try:
        return export_vector_glb_preview_v2_scene_reuse(
            fallback_parts,
            output_path=output_path,
        )
    except Exception as exc:
        log.warning(
            "Vector GLB V2 failed; falling back to V1",
            extra={
                "event": "vector_glb_v2_runtime_fallback",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "fallback_kernel": "trimesh_v1",
            },
        )
        return export_vector_glb_preview_v1(fallback_parts, output_path=output_path)
