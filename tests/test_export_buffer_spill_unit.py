"""Lossless bounded export buffers."""
import mmap
from types import SimpleNamespace

import numpy as np
import pytest


def test_export_buffers_spill_and_preserve_source(monkeypatch):
    from core import vector_mesh_spill as spill
    from utils.bambu_3mf_writer import _materialize_n3mf_mesh_view_arrays
    monkeypatch.setattr(spill, "_retained_memory_limit", lambda: 1)
    vertices = np.array([[0., 0., 0.], [1., 0., 0.], [0., 1., 0.]])
    faces = np.array([[0, 1, 2]], dtype=np.int64)
    actual_v, actual_f = _materialize_n3mf_mesh_view_arrays(SimpleNamespace(vertices=vertices, faces=faces))
    assert isinstance(actual_v.base, mmap.mmap)
    assert isinstance(actual_f.base, mmap.mmap)
    np.testing.assert_array_equal(actual_v, vertices.astype(np.float32))
    np.testing.assert_array_equal(actual_f, faces.astype(np.uint32))
    assert vertices.flags.writeable and faces.flags.writeable
    assert not actual_v.flags.writeable and not actual_f.flags.writeable


def test_offset_conversion_is_chunked_and_exact(monkeypatch):
    from core import vector_mesh_spill as spill
    monkeypatch.setattr(spill, "_retained_memory_limit", lambda: 1)
    source = np.arange(120, dtype=np.int64).reshape(-1, 3) + 40
    result = spill.copy_mesh_array(source, np.dtype(np.uint32), offset=40)
    np.testing.assert_array_equal(result, (source - 40).astype(np.uint32))


@pytest.mark.parametrize("value", [float("inf"), 1e100])
def test_export_rejects_nonfinite_source_or_conversion(value):
    from utils.bambu_3mf_writer import _materialize_n3mf_mesh_view_arrays
    vertices = np.array([[value, 0., 0.], [1., 0., 0.], [0., 1., 0.]])
    with np.errstate(over="ignore"), pytest.raises(ValueError, match="finite"):
        _materialize_n3mf_mesh_view_arrays(SimpleNamespace(vertices=vertices, faces=np.array([[0, 1, 2]])))
