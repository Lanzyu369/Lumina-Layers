"""Unit tests for the optional dense GEOS runtime boundary."""

from __future__ import annotations

import ctypes
import json
from pathlib import Path

import pytest
from shapely.geometry import MultiPolygon, Point, Polygon, box


class _FakeFunction:
    def __init__(self, implementation):
        self.implementation = implementation
        self.calls: list[tuple[object, ...]] = []
        self.argtypes = None
        self.restype = None

    def __call__(self, *args):
        self.calls.append(args)
        return self.implementation(*args)


def _fake_library(output_wkb: bytes, *, setter_result: int = 1):
    output_buffer = ctypes.create_string_buffer(output_wkb)
    library = type("FakeLibrary", (), {})()
    library.GEOS_init_r = _FakeFunction(lambda: 1)
    library.GEOS_finish_r = _FakeFunction(lambda _context: None)
    library.GEOSWKBReader_create_r = _FakeFunction(lambda _context: 2)
    library.GEOSWKBReader_destroy_r = _FakeFunction(
        lambda _context, _reader: None
    )
    library.GEOSWKBReader_read_r = _FakeFunction(
        lambda _context, _reader, _input, _size: 3
    )
    library.GEOSWKBWriter_create_r = _FakeFunction(lambda _context: 4)
    library.GEOSWKBWriter_destroy_r = _FakeFunction(
        lambda _context, _writer: None
    )

    def write_wkb(_context, _writer, _geometry, size_pointer):
        size_pointer._obj.value = len(output_wkb)
        return ctypes.addressof(output_buffer)

    library.GEOSWKBWriter_write_r = _FakeFunction(write_wkb)
    library.GEOSBufferParams_create_r = _FakeFunction(lambda _context: 5)
    library.GEOSBufferParams_destroy_r = _FakeFunction(
        lambda _context, _params: None
    )
    library.GEOSBufferParams_setJoinStyle_r = _FakeFunction(
        lambda _context, _params, _value: setter_result
    )
    library.GEOSBufferParams_setMitreLimit_r = _FakeFunction(
        lambda _context, _params, _value: setter_result
    )
    library.GEOSBufferParams_setQuadrantSegments_r = _FakeFunction(
        lambda _context, _params, _value: setter_result
    )
    library.GEOSBufferWithParams_r = _FakeFunction(
        lambda _context, _geometry, _params, _distance: 6
    )
    library.GEOSGeom_destroy_r = _FakeFunction(
        lambda _context, _geometry: None
    )
    library.GEOSFree_r = _FakeFunction(lambda _context, _buffer: None)
    library._output_buffer = output_buffer
    return library


def test_core_geos_adapter_passes_wkb_through_reentrant_api(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core import geos_buffer_fast

    output_wkb = Polygon([(0, 0), (3, 0), (3, 3), (0, 3)]).wkb
    fake = _fake_library(output_wkb)
    library_path = tmp_path / "libgeos_c.dylib"
    library_path.touch()
    monkeypatch.setattr(
        geos_buffer_fast.ctypes,
        "CDLL",
        lambda *_args, **_kwargs: fake,
    )

    backend = geos_buffer_fast.GEOSCBufferBackend(library_path)
    result = backend.buffer_wkb(
        b"input-wkb",
        geos_buffer_fast.BufferSettings(),
    )

    assert result == output_wkb
    assert len(fake.GEOSWKBReader_read_r.calls) == 1
    assert len(fake.GEOSBufferWithParams_r.calls) == 1
    assert len(fake.GEOSGeom_destroy_r.calls) == 2
    assert len(fake.GEOSFree_r.calls) == 1
    assert len(fake.GEOS_finish_r.calls) == 1
    assert all(name.endswith("_r") for name in vars(fake) if name.startswith("GEOS"))


def test_core_geos_adapter_cleans_up_after_failed_setter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core import geos_buffer_fast

    fake = _fake_library(Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]).wkb, setter_result=0)
    library_path = tmp_path / "libgeos_c.dylib"
    library_path.touch()
    monkeypatch.setattr(
        geos_buffer_fast.ctypes,
        "CDLL",
        lambda *_args, **_kwargs: fake,
    )

    backend = geos_buffer_fast.GEOSCBufferBackend(library_path)
    with pytest.raises(
        geos_buffer_fast.ProofLibraryError,
        match="quadrant segments",
    ):
        backend.buffer_wkb(b"input-wkb", geos_buffer_fast.BufferSettings())

    assert len(fake.GEOSBufferWithParams_r.calls) == 0
    assert len(fake.GEOSGeom_destroy_r.calls) == 1
    assert len(fake.GEOSBufferParams_destroy_r.calls) == 1
    assert len(fake.GEOSWKBWriter_destroy_r.calls) == 1
    assert len(fake.GEOSWKBReader_destroy_r.calls) == 1
    assert len(fake.GEOS_finish_r.calls) == 1


def test_core_geos_adapter_rejects_relative_library_path() -> None:
    from core.geos_buffer_fast import GEOSCBufferBackend, ProofLibraryError

    with pytest.raises(ProofLibraryError, match="absolute"):
        GEOSCBufferBackend(Path("relative/libgeos_c.so"))


def _clear_runtime_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    from core import geos_buffer_fast

    for variable in (
        geos_buffer_fast.MANIFEST_ENV,
        geos_buffer_fast.UNVERIFIED_LIBRARY_ENV,
        geos_buffer_fast.ALLOW_UNVERIFIED_ENV,
    ):
        monkeypatch.delenv(variable, raising=False)
    geos_buffer_fast.reset_runtime_cache_for_tests()


def _write_verified_manifest(
    tmp_path: Path,
    *,
    library_path: Path | None = None,
    **overrides: object,
) -> Path:
    from core import geos_buffer_fast

    resolved_library = library_path or (tmp_path / "libgeos_c.dylib")
    if resolved_library.is_absolute():
        resolved_library.touch(exist_ok=True)
    payload: dict[str, object] = {
        "geos_repository": geos_buffer_fast.EXPECTED_GEOS_REPOSITORY,
        "geos_ref": geos_buffer_fast.EXPECTED_GEOS_REF,
        "geos_commit": geos_buffer_fast.EXPECTED_GEOS_COMMIT,
        "patch_sha256": geos_buffer_fast.EXPECTED_PATCH_SHA256,
        "library_path": str(resolved_library),
    }
    payload.update(overrides)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    return manifest_path


def _dense_geometry(component_count: int = 2_048) -> MultiPolygon:
    return MultiPolygon(
        [box(index * 2.0, 0.0, index * 2.0 + 1.0, 1.0) for index in range(component_count)]
    )


def test_runtime_is_disabled_when_no_capability_is_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core import geos_buffer_fast

    _clear_runtime_environment(monkeypatch)

    assert geos_buffer_fast.resolve_runtime_backend() is None


def test_runtime_rejects_missing_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core import geos_buffer_fast

    _clear_runtime_environment(monkeypatch)
    warnings: list[dict[str, object]] = []
    monkeypatch.setattr(
        geos_buffer_fast.log,
        "warning",
        lambda _message, *, extra: warnings.append(extra),
    )
    monkeypatch.setenv(
        geos_buffer_fast.MANIFEST_ENV,
        str(tmp_path / "missing.json"),
    )

    assert geos_buffer_fast.resolve_runtime_backend() is None
    assert len(warnings) == 1
    assert warnings[0]["event"] == "dense_geos_runtime_unavailable"
    assert warnings[0]["error_type"] == "ProofLibraryError"


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("geos_ref", "3.13.0"),
        ("geos_commit", "0" * 40),
        ("patch_sha256", "f" * 64),
    ],
)
def test_runtime_rejects_wrong_build_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    bad_value: str,
) -> None:
    from core import geos_buffer_fast

    _clear_runtime_environment(monkeypatch)
    manifest_path = _write_verified_manifest(tmp_path, **{field: bad_value})
    monkeypatch.setenv(geos_buffer_fast.MANIFEST_ENV, str(manifest_path))

    assert geos_buffer_fast.resolve_runtime_backend() is None


@pytest.mark.parametrize("library_path", [Path("relative/libgeos_c.so"), None])
def test_runtime_rejects_missing_or_relative_library_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    library_path: Path | None,
) -> None:
    from core import geos_buffer_fast

    _clear_runtime_environment(monkeypatch)
    if library_path is None:
        missing = tmp_path / "libgeos_c.so"
        manifest_path = _write_verified_manifest(tmp_path, library_path=missing)
        missing.unlink()
    else:
        manifest_path = _write_verified_manifest(tmp_path, library_path=library_path)
    monkeypatch.setenv(geos_buffer_fast.MANIFEST_ENV, str(manifest_path))

    assert geos_buffer_fast.resolve_runtime_backend() is None


def test_verified_runtime_backend_is_cached(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core import geos_buffer_fast

    _clear_runtime_environment(monkeypatch)
    manifest_path = _write_verified_manifest(tmp_path)
    monkeypatch.setenv(geos_buffer_fast.MANIFEST_ENV, str(manifest_path))
    created: list[Path] = []

    class FakeBackend:
        def __init__(self, library_path: Path) -> None:
            created.append(library_path)

    monkeypatch.setattr(geos_buffer_fast, "GEOSCBufferBackend", FakeBackend)

    first = geos_buffer_fast.resolve_runtime_backend()
    second = geos_buffer_fast.resolve_runtime_backend()

    assert first is second
    assert created == [tmp_path / "libgeos_c.dylib"]


def test_runtime_load_failure_is_cached_as_stock_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core import geos_buffer_fast

    _clear_runtime_environment(monkeypatch)
    manifest_path = _write_verified_manifest(tmp_path)
    monkeypatch.setenv(geos_buffer_fast.MANIFEST_ENV, str(manifest_path))
    attempts = 0

    def fail_to_load(_library_path: Path) -> None:
        nonlocal attempts
        attempts += 1
        raise geos_buffer_fast.ProofLibraryError("simulated load failure")

    monkeypatch.setattr(geos_buffer_fast, "GEOSCBufferBackend", fail_to_load)

    assert geos_buffer_fast.resolve_runtime_backend() is None
    assert geos_buffer_fast.resolve_runtime_backend() is None
    assert attempts == 1


def test_unverified_library_requires_explicit_development_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core import geos_buffer_fast

    _clear_runtime_environment(monkeypatch)
    library_path = tmp_path / "libgeos_c.dylib"
    library_path.touch()
    monkeypatch.setenv(geos_buffer_fast.UNVERIFIED_LIBRARY_ENV, str(library_path))
    monkeypatch.setattr(
        geos_buffer_fast,
        "GEOSCBufferBackend",
        lambda path: ("backend", path),
    )

    assert geos_buffer_fast.resolve_runtime_backend() is None

    geos_buffer_fast.reset_runtime_cache_for_tests()
    monkeypatch.setenv(geos_buffer_fast.ALLOW_UNVERIFIED_ENV, "1")
    assert geos_buffer_fast.resolve_runtime_backend() == ("backend", library_path)


def test_positive_fast_path_skips_geometry_below_dense_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core import geos_buffer_fast

    monkeypatch.setattr(
        geos_buffer_fast,
        "resolve_runtime_backend",
        lambda: pytest.fail("small geometry must not resolve the optional runtime"),
    )

    assert geos_buffer_fast.try_dense_positive_buffer(_dense_geometry(2_047)) is None


def test_positive_fast_path_accepts_valid_dense_polygonal_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core import geos_buffer_fast

    geometry = _dense_geometry()

    class FakeBackend:
        def buffer_wkb(self, input_wkb: bytes, settings: object) -> bytes:
            assert input_wkb == geometry.wkb
            assert settings == geos_buffer_fast.BufferSettings()
            return geometry.wkb

    monkeypatch.setattr(
        geos_buffer_fast,
        "resolve_runtime_backend",
        lambda: FakeBackend(),
    )

    result = geos_buffer_fast.try_dense_positive_buffer(geometry)

    assert result is not None
    assert result.equals_exact(geometry, tolerance=0.0)


@pytest.mark.parametrize(
    "candidate_wkb",
    [
        b"not-wkb",
        Point(0.0, 0.0).wkb,
        Polygon([(0, 0), (2, 2), (0, 2), (2, 0), (0, 0)]).wkb,
    ],
)
def test_positive_fast_path_returns_none_for_invalid_output(
    monkeypatch: pytest.MonkeyPatch,
    candidate_wkb: bytes,
) -> None:
    from core import geos_buffer_fast

    class FakeBackend:
        def buffer_wkb(self, _input_wkb: bytes, _settings: object) -> bytes:
            return candidate_wkb

    monkeypatch.setattr(
        geos_buffer_fast,
        "resolve_runtime_backend",
        lambda: FakeBackend(),
    )

    assert geos_buffer_fast.try_dense_positive_buffer(_dense_geometry()) is None


def test_positive_fast_path_returns_none_when_runtime_call_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core import geos_buffer_fast

    class FailingBackend:
        def buffer_wkb(self, _input_wkb: bytes, _settings: object) -> bytes:
            raise RuntimeError("simulated call failure")

    monkeypatch.setattr(
        geos_buffer_fast,
        "resolve_runtime_backend",
        lambda: FailingBackend(),
    )

    assert geos_buffer_fast.try_dense_positive_buffer(_dense_geometry()) is None
