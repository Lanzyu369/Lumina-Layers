"""Optional WKB-only boundary for the dense GEOS buffer runtime."""

from __future__ import annotations

import ctypes
import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from shapely import from_wkb
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry

from api.structured_logging import get_logger


log = get_logger(__name__)

EXPECTED_GEOS_REPOSITORY = "https://github.com/libgeos/geos.git"
EXPECTED_GEOS_REF = "3.13.1"
EXPECTED_GEOS_COMMIT = "431568d6e311e0bbfb057b4ec3d44d0d3ba3335f"
EXPECTED_PATCH_SHA256 = (
    "f0f0b940a25d11df50548dad4838ad8197588304b20e983274158d23c8da96c5"
)
MIN_DENSE_COMPONENTS = 2_048
MANIFEST_ENV = "LUMINA_GEOS_BUFFER_FAST_MANIFEST"
UNVERIFIED_LIBRARY_ENV = "LUMINA_GEOS_BUFFER_FAST_LIBRARY"
ALLOW_UNVERIFIED_ENV = "LUMINA_GEOS_BUFFER_FAST_ALLOW_UNVERIFIED"

_CACHE_UNSET = object()
_runtime_cache_lock = threading.Lock()
_runtime_cache_config: object = _CACHE_UNSET
_runtime_cache_backend: object = None


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


def _runtime_configuration() -> tuple[str | None, str | None, str | None]:
    return (
        os.environ.get(MANIFEST_ENV),
        os.environ.get(UNVERIFIED_LIBRARY_ENV),
        os.environ.get(ALLOW_UNVERIFIED_ENV),
    )


def _manifest_library_path(manifest_path: Path) -> Path:
    if not manifest_path.is_absolute():
        raise ProofLibraryError("dense GEOS manifest path must be absolute")
    if not manifest_path.is_file():
        raise ProofLibraryError(f"dense GEOS manifest does not exist: {manifest_path}")
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProofLibraryError(
            f"failed to read dense GEOS manifest: {manifest_path}"
        ) from exc
    if not isinstance(payload, dict):
        raise ProofLibraryError("dense GEOS manifest must contain a JSON object")

    expected_identity = {
        "geos_repository": EXPECTED_GEOS_REPOSITORY,
        "geos_ref": EXPECTED_GEOS_REF,
        "geos_commit": EXPECTED_GEOS_COMMIT,
        "patch_sha256": EXPECTED_PATCH_SHA256,
    }
    for field, expected in expected_identity.items():
        actual = payload.get(field)
        if actual != expected:
            raise ProofLibraryError(
                f"dense GEOS manifest has unexpected {field}: {actual!r}"
            )

    raw_library_path = payload.get("library_path")
    if not isinstance(raw_library_path, str) or not raw_library_path:
        raise ProofLibraryError("dense GEOS manifest library_path must be a string")
    library_path = Path(raw_library_path)
    if not library_path.is_absolute():
        raise ProofLibraryError("dense GEOS library path must be absolute")
    if not library_path.is_file():
        raise ProofLibraryError(f"dense GEOS library does not exist: {library_path}")
    return library_path


def _create_runtime_backend(
    configuration: tuple[str | None, str | None, str | None],
) -> GEOSCBufferBackend | None:
    manifest_value, unverified_value, allow_unverified = configuration
    if manifest_value:
        return GEOSCBufferBackend(_manifest_library_path(Path(manifest_value)))
    if not unverified_value:
        return None
    if allow_unverified != "1":
        raise ProofLibraryError(
            "unverified dense GEOS library requires "
            f"{ALLOW_UNVERIFIED_ENV}=1"
        )
    return GEOSCBufferBackend(Path(unverified_value))


def resolve_runtime_backend() -> GEOSCBufferBackend | None:
    """Resolve and cache the optional verified runtime. / 解析并缓存可选验证运行时。"""

    global _runtime_cache_backend, _runtime_cache_config

    configuration = _runtime_configuration()
    with _runtime_cache_lock:
        if configuration == _runtime_cache_config:
            return cast("GEOSCBufferBackend | None", _runtime_cache_backend)
        try:
            backend = _create_runtime_backend(configuration)
        except Exception as exc:
            log.warning(
                "Dense GEOS runtime unavailable; using the stock buffer path",
                extra={
                    "event": "dense_geos_runtime_unavailable",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "path": configuration[0] or configuration[1],
                },
            )
            backend = None
        _runtime_cache_config = configuration
        _runtime_cache_backend = backend
        if backend is not None:
            log.debug(
                "Dense GEOS runtime resolved",
                extra={
                    "event": "dense_geos_runtime_resolved",
                    "path": configuration[0] or configuration[1],
                    "verified": bool(configuration[0]),
                },
            )
        return backend


def reset_runtime_cache_for_tests() -> None:
    """Clear process-local runtime resolution state. / 清理进程内运行时解析状态。"""

    global _runtime_cache_backend, _runtime_cache_config

    with _runtime_cache_lock:
        _runtime_cache_config = _CACHE_UNSET
        _runtime_cache_backend = None


def try_dense_positive_buffer(
    geometry: BaseGeometry,
    settings: BufferSettings | None = None,
) -> BaseGeometry | None:
    """Try the verified dense positive buffer. / 尝试已验证的密集正向缓冲。"""

    resolved_settings = settings or BufferSettings()
    if resolved_settings != BufferSettings():
        return None
    if not isinstance(geometry, MultiPolygon):
        return None
    component_count = len(geometry.geoms)
    if component_count < MIN_DENSE_COMPONENTS:
        return None
    if geometry.is_empty or not geometry.is_valid:
        return None

    backend = resolve_runtime_backend()
    if backend is None:
        return None
    try:
        candidate = from_wkb(backend.buffer_wkb(geometry.wkb, resolved_settings))
        if not isinstance(candidate, (Polygon, MultiPolygon)):
            raise ProofLibraryError(
                f"dense GEOS returned non-polygon output: {candidate.geom_type}"
            )
        if candidate.is_empty or not candidate.is_valid:
            raise ProofLibraryError("dense GEOS returned empty or invalid output")
    except Exception as exc:
        log.warning(
            "Dense GEOS buffer failed; using the stock buffer path",
            extra={
                "event": "dense_geos_buffer_failed",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "path": os.environ.get(MANIFEST_ENV)
                or os.environ.get(UNVERIFIED_LIBRARY_ENV),
                "component_count": component_count,
            },
        )
        return None

    log.debug(
        "Dense GEOS buffer completed",
        extra={
            "event": "dense_geos_buffer_done",
            "component_count": component_count,
        },
    )
    return candidate
