"""Exact mesh accumulation with automatic disk spill under memory pressure."""

from __future__ import annotations

import mmap
import tempfile
from typing import BinaryIO

import numpy as np
import trimesh

from core.system_capacity import get_effective_memory_capacity
from core.vector_mesh_memory import (
    get_process_rss_bytes,
    resolve_vector_mesh_memory_budget_bytes,
)

_RESAMPLE_BYTES = 32 * 1024**2
_FACE_CHUNK_ROWS = 65_536


def _retained_memory_limit() -> int:
    rss = get_process_rss_bytes()
    remaining = resolve_vector_mesh_memory_budget_bytes() - int(rss or 0)
    # Container-aware: inside a memory-limited container the raw host figure is
    # not what this process may still allocate.
    # 计入容器上限：受限容器内，宿主机的可用内存不是本进程还能分配的量。
    available = get_effective_memory_capacity().available_bytes
    remaining = min(remaining, int(available)) if available is not None else 0
    # Leave room for the next extrusion and the final contiguous copy.
    return max(1, remaining // 3)


def _mapped_array(file: BinaryIO, count: int, dtype: np.dtype) -> np.ndarray:
    file.flush()
    mapping = mmap.mmap(file.fileno(), 0, access=mmap.ACCESS_WRITE)
    return np.ndarray((count, 3), dtype=dtype, buffer=mapping)


class AdaptiveMeshAccumulator:
    """Keep small meshes in RAM and stream larger retained state to disk.

    小网格保留在内存，内存紧张时将累计网格写盘；坐标和三角面顺序不变。
    临时文件由操作系统管理，返回数组的引用决定映射寿命，进程退出也会清理。
    """

    def __init__(self) -> None:
        self.spilled = False
        self.component_count = 0
        self._meshes: list[trimesh.Trimesh] = []
        self._vertices: BinaryIO | None = None
        self._faces: BinaryIO | None = None
        self._vertex_count = 0
        self._face_count = 0
        self._retained_bytes = 0
        self._sample_bytes = 0
        self._limit = _retained_memory_limit()

    def __enter__(self) -> AdaptiveMeshAccumulator:
        return self

    def __exit__(self, *_args) -> None:
        self._meshes.clear()
        for file in (self._vertices, self._faces):
            if file is not None:
                file.close()

    def _append_to_disk(self, mesh: trimesh.Trimesh) -> None:
        np.asarray(mesh.vertices, dtype=np.float64).tofile(self._vertices)
        faces = np.asarray(mesh.faces, dtype=np.int64)
        for start in range(0, len(faces), _FACE_CHUNK_ROWS):
            (faces[start:start + _FACE_CHUNK_ROWS] + self._vertex_count).tofile(self._faces)
        self._vertex_count += len(mesh.vertices)
        self._face_count += len(faces)

    def _spill(self) -> None:
        self._vertices = tempfile.TemporaryFile(prefix="lumina-vector-buffer-", buffering=0)
        self._faces = tempfile.TemporaryFile(prefix="lumina-vector-buffer-", buffering=0)
        for mesh in self._meshes:
            self._append_to_disk(mesh)
        self._meshes.clear()
        self._retained_bytes = 0
        self.spilled = True

    def add(self, mesh: trimesh.Trimesh) -> None:
        """Append one completed component, spilling before retaining too much.
        加入一个已完成的组件，在累计占用过大前写盘释放内存。
        """
        size = mesh.vertices.nbytes + mesh.faces.nbytes
        self._sample_bytes += size
        if not self.spilled and self._sample_bytes >= _RESAMPLE_BYTES:
            self._limit = _retained_memory_limit()
            self._sample_bytes = 0
        if not self.spilled and self._retained_bytes + size > self._limit:
            self._spill()
        if self.spilled:
            self._append_to_disk(mesh)
        else:
            self._meshes.append(mesh)
            self._retained_bytes += size
        self.component_count += 1

    def finish(self) -> trimesh.Trimesh:
        """Return one exact mesh whose disk buffers remain valid after close.
        返回顺序一致的完整网格，退出上下文后磁盘数组仍可使用。
        """
        if not self.component_count:
            raise ValueError("Vector layered-volume has no component meshes")
        if not self.spilled and self._retained_bytes > _retained_memory_limit():
            self._spill()
        if self.spilled:
            vertices = _mapped_array(self._vertices, self._vertex_count, np.dtype(np.float64))
            faces = _mapped_array(self._faces, self._face_count, np.dtype(np.int64))
        else:
            vertices = np.empty((sum(len(m.vertices) for m in self._meshes), 3), dtype=np.float64)
            faces = np.empty((sum(len(m.faces) for m in self._meshes), 3), dtype=np.int64)
            vertex_cursor = face_cursor = 0
            for mesh in self._meshes:
                next_vertex, next_face = vertex_cursor + len(mesh.vertices), face_cursor + len(mesh.faces)
                vertices[vertex_cursor:next_vertex] = mesh.vertices
                np.add(mesh.faces, vertex_cursor, out=faces[face_cursor:next_face])
                vertex_cursor, face_cursor = next_vertex, next_face
        return trimesh.Trimesh(vertices=vertices, faces=faces, process=False)


def copy_mesh_array(
    source: np.ndarray, dtype: np.dtype, *, offset: int = 0, force_disk: bool = False,
) -> np.ndarray:
    """Convert a mesh array in bounded chunks, spilling large buffers.
    分块转换网格数组，内存紧张时使用磁盘缓冲。

    Args:
        source: Nx3 mesh array. Nx3 网格数组。
        dtype: Writer destination dtype. 写出类型。
        offset: Validated face-index origin to subtract. 已校验的面索引原点。
        force_disk: Keep transformed cached normals out of heap copies.
            法线变换使用磁盘，避免增加完整内存副本。

    Returns:
        Contiguous array retaining its own backing storage. 自持存储的连续数组。
    """
    dtype = np.dtype(dtype)
    if not force_disk and offset == 0 and source.dtype == dtype and source.flags.c_contiguous:
        return source
    size = source.size * dtype.itemsize
    if (force_disk or size > _retained_memory_limit()) and size > 0:
        with tempfile.TemporaryFile(prefix="lumina-vector-buffer-", buffering=0) as file:
            file.truncate(size)
            result = _mapped_array(file, len(source), dtype)
    else:
        result = np.empty(source.shape, dtype=dtype)
    for start in range(0, len(source), _FACE_CHUNK_ROWS):
        end = start + _FACE_CHUNK_ROWS
        if offset:
            np.subtract(source[start:end], offset, out=result[start:end], casting="unsafe")
        else:
            result[start:end] = source[start:end]
    return result


def transform_layered_mesh(mesh: trimesh.Trimesh, matrix: np.ndarray) -> None:
    """Reflect a canonical mesh in bounded chunks, retaining mapped storage.
    对规范网格分块镜像，保留磁盘映射；其他网格沿用原变换。

    Args:
        mesh: Mesh to transform in place. 原地变换的网格。
        matrix: Existing axis-reflection matrix. 现有轴镜像矩阵。
    """
    matrix = np.asarray(matrix, dtype=np.float64)
    canonical_reflection = (
        matrix.shape == (4, 4)
        and np.array_equal(matrix, np.diag(np.diag(matrix)))
        and matrix[3, 3] == 1
        and np.all(np.isin(np.diag(matrix)[:3], [-1, 1]))
    )
    if ("vector_layer_geometry" not in mesh.metadata or not canonical_reflection
            or not mesh.vertices.flags.writeable or not mesh.faces.flags.writeable):
        mesh.apply_transform(matrix)
        return
    vertices, faces = mesh.vertices, mesh.faces
    transformed_normals = {}
    for key in ("face_normals", "vertex_normals"):
        if key in mesh._cache:
            original = mesh._cache.cache[key]
            normal = copy_mesh_array(original, np.dtype(np.float64), force_disk=True)
            for start in range(0, len(normal), _FACE_CHUNK_ROWS):
                end = start + _FACE_CHUNK_ROWS
                normal[start:end] = trimesh.util.unitize(
                    trimesh.transformations.transform_points(
                        original[start:end], matrix, translate=False,
                    ),
                )
            transformed_normals[key] = normal
    for start in range(0, len(vertices), _FACE_CHUNK_ROWS):
        end = start + _FACE_CHUNK_ROWS
        vertices[start:end] = trimesh.transformations.transform_points(vertices[start:end], matrix)
    if np.prod(np.diag(matrix)[:3]) < 0:
        for start in range(0, len(faces), _FACE_CHUNK_ROWS):
            end = start + _FACE_CHUNK_ROWS
            faces[start:end] = np.fliplr(faces[start:end]).copy()
    if "center_mass" in mesh._data:
        mesh.center_mass = trimesh.transformations.transform_points([mesh.center_mass], matrix)[0]
    mesh._cache.clear()
    mesh._cache.cache.update(transformed_normals)
    mesh._cache.id_set()
