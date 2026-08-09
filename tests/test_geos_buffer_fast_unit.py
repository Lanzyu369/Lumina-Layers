"""Unit tests for the optional dense GEOS runtime boundary."""

from __future__ import annotations

import ctypes
from pathlib import Path

import pytest
from shapely.geometry import Polygon


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
