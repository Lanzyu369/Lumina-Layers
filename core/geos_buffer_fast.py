"""Optional WKB-only boundary for the dense GEOS buffer runtime."""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
from pathlib import Path


class ProofLibraryError(RuntimeError):
    """Report an isolated GEOS runtime failure. / 表示隔离 GEOS 运行时失败。"""


@dataclass(frozen=True)
class BufferSettings:
    """Describe contour buffer parameters. / 描述轮廓缓冲参数。"""

    distance: float = 0.03
    quadrant_segments: int = 1
    join_style: int = 2
    mitre_limit: float = 2.0


class GEOSCBufferBackend:
    """Call an isolated ``libgeos_c`` with WKB only. / 仅通过 WKB 调用隔离库。"""

    def __init__(self, library_path: Path) -> None:
        """Load one absolute GEOS C shared library. / 加载绝对路径的 GEOS C 动态库。"""

        if not library_path.is_absolute():
            raise ProofLibraryError("proof GEOS library path must be absolute")
        if not library_path.is_file():
            raise ProofLibraryError(f"proof GEOS library does not exist: {library_path}")
        try:
            self._library = ctypes.CDLL(
                str(library_path),
                mode=getattr(ctypes, "RTLD_LOCAL", 0),
            )
        except OSError as exc:
            raise ProofLibraryError(
                f"failed to load proof GEOS library: {library_path}"
            ) from exc
        self._bind_reentrant_api()

    def _declare(self, name: str, argtypes: list[object], restype: object) -> None:
        try:
            function = getattr(self._library, name)
        except AttributeError as exc:
            raise ProofLibraryError(f"proof GEOS symbol is missing: {name}") from exc
        function.argtypes = argtypes
        function.restype = restype

    def _bind_reentrant_api(self) -> None:
        pointer = ctypes.c_void_p
        byte_pointer = ctypes.POINTER(ctypes.c_ubyte)
        size_pointer = ctypes.POINTER(ctypes.c_size_t)
        declarations = {
            "GEOS_init_r": ([], pointer),
            "GEOS_finish_r": ([pointer], None),
            "GEOSWKBReader_create_r": ([pointer], pointer),
            "GEOSWKBReader_destroy_r": ([pointer, pointer], None),
            "GEOSWKBReader_read_r": (
                [pointer, pointer, byte_pointer, ctypes.c_size_t],
                pointer,
            ),
            "GEOSWKBWriter_create_r": ([pointer], pointer),
            "GEOSWKBWriter_destroy_r": ([pointer, pointer], None),
            "GEOSWKBWriter_write_r": (
                [pointer, pointer, pointer, size_pointer],
                pointer,
            ),
            "GEOSBufferParams_create_r": ([pointer], pointer),
            "GEOSBufferParams_destroy_r": ([pointer, pointer], None),
            "GEOSBufferParams_setJoinStyle_r": (
                [pointer, pointer, ctypes.c_int],
                ctypes.c_int,
            ),
            "GEOSBufferParams_setMitreLimit_r": (
                [pointer, pointer, ctypes.c_double],
                ctypes.c_int,
            ),
            "GEOSBufferParams_setQuadrantSegments_r": (
                [pointer, pointer, ctypes.c_int],
                ctypes.c_int,
            ),
            "GEOSBufferWithParams_r": (
                [pointer, pointer, pointer, ctypes.c_double],
                pointer,
            ),
            "GEOSGeom_destroy_r": ([pointer, pointer], None),
            "GEOSFree_r": ([pointer, pointer], None),
        }
        for name, (argtypes, restype) in declarations.items():
            self._declare(name, argtypes, restype)

    @staticmethod
    def _require_pointer(value: object, operation: str) -> object:
        if not value:
            raise ProofLibraryError(f"proof GEOS returned null during {operation}")
        return value

    def buffer_wkb(self, input_wkb: bytes, settings: BufferSettings) -> bytes:
        """Buffer one WKB geometry. / 对一个 WKB 几何执行缓冲。"""

        library = self._library
        context = reader = writer = parameters = input_geometry = None
        result_geometry = output_buffer = None
        try:
            context = self._require_pointer(library.GEOS_init_r(), "context creation")
            reader = self._require_pointer(
                library.GEOSWKBReader_create_r(context),
                "WKB reader creation",
            )
            writer = self._require_pointer(
                library.GEOSWKBWriter_create_r(context),
                "WKB writer creation",
            )
            parameters = self._require_pointer(
                library.GEOSBufferParams_create_r(context),
                "buffer parameter creation",
            )
            source_buffer = (ctypes.c_ubyte * len(input_wkb)).from_buffer_copy(input_wkb)
            input_geometry = self._require_pointer(
                library.GEOSWKBReader_read_r(
                    context,
                    reader,
                    source_buffer,
                    len(input_wkb),
                ),
                "WKB read",
            )
            setters = (
                (
                    library.GEOSBufferParams_setQuadrantSegments_r,
                    settings.quadrant_segments,
                    "quadrant segments",
                ),
                (
                    library.GEOSBufferParams_setJoinStyle_r,
                    settings.join_style,
                    "join style",
                ),
                (
                    library.GEOSBufferParams_setMitreLimit_r,
                    settings.mitre_limit,
                    "mitre limit",
                ),
            )
            for setter, value, label in setters:
                if setter(context, parameters, value) != 1:
                    raise ProofLibraryError(
                        f"proof GEOS rejected buffer parameter: {label}"
                    )
            result_geometry = self._require_pointer(
                library.GEOSBufferWithParams_r(
                    context,
                    input_geometry,
                    parameters,
                    settings.distance,
                ),
                "positive buffer",
            )
            output_size = ctypes.c_size_t()
            output_buffer = self._require_pointer(
                library.GEOSWKBWriter_write_r(
                    context,
                    writer,
                    result_geometry,
                    ctypes.byref(output_size),
                ),
                "WKB write",
            )
            return ctypes.string_at(output_buffer, output_size.value)
        finally:
            if context:
                if output_buffer:
                    library.GEOSFree_r(context, output_buffer)
                if result_geometry:
                    library.GEOSGeom_destroy_r(context, result_geometry)
                if input_geometry:
                    library.GEOSGeom_destroy_r(context, input_geometry)
                if parameters:
                    library.GEOSBufferParams_destroy_r(context, parameters)
                if writer:
                    library.GEOSWKBWriter_destroy_r(context, writer)
                if reader:
                    library.GEOSWKBReader_destroy_r(context, reader)
                library.GEOS_finish_r(context)
