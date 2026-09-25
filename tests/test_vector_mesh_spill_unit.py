"""Exact, disk-backed mesh accumulation under memory pressure."""
import gc
from pathlib import Path

import numpy as np
import pytest
import trimesh


def test_disk_accumulation_preserves_indices_and_array_lifetime(monkeypatch, tmp_path: Path):
    from core import vector_mesh_spill as spill
    import tempfile
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(spill, "_retained_memory_limit", lambda: 1)
    meshes = [trimesh.creation.box(), trimesh.creation.icosphere(subdivisions=1)]
    expected_vertices = np.vstack([mesh.vertices for mesh in meshes])
    expected_faces = np.vstack([meshes[0].faces, meshes[1].faces + len(meshes[0].vertices)])
    with spill.AdaptiveMeshAccumulator() as accumulator:
        for mesh in meshes:
            accumulator.add(mesh)
        result = accumulator.finish()
        assert accumulator.spilled
    gc.collect()
    np.testing.assert_array_equal(result.vertices, expected_vertices)
    np.testing.assert_array_equal(result.faces, expected_faces)
    retained = result.vertices
    del result
    gc.collect()
    np.testing.assert_array_equal(retained, expected_vertices)
    del retained
    gc.collect()
    assert not list(tmp_path.glob("lumina-vector-buffer-*"))


def test_pressure_switches_existing_buffers_to_disk(monkeypatch):
    from core import vector_mesh_spill as spill
    limit = [1024**3]
    monkeypatch.setattr(spill, "_retained_memory_limit", lambda: limit[0])
    monkeypatch.setattr(spill, "_RESAMPLE_BYTES", 1)
    with spill.AdaptiveMeshAccumulator() as accumulator:
        accumulator.add(trimesh.creation.box())
        assert not accumulator.spilled
        limit[0] = 1
        accumulator.add(trimesh.creation.box())
        assert accumulator.spilled
        assert len(accumulator.finish().vertices) == 16


def test_small_mesh_uses_memory_without_temporary_files(monkeypatch):
    from core import vector_mesh_spill as spill
    monkeypatch.setattr(spill, "_retained_memory_limit", lambda: 1024**3)
    monkeypatch.setattr(spill.tempfile, "TemporaryFile", lambda **kw: pytest.fail("unexpected disk use"))
    with spill.AdaptiveMeshAccumulator() as accumulator:
        accumulator.add(trimesh.creation.box())
        result = accumulator.finish()
        assert not accumulator.spilled
        assert result.is_watertight


def test_layered_volume_disk_path_matches_memory_path(monkeypatch):
    from core import vector_mesh_spill as spill
    from core.vector_layer_geometry import build_vector_layered_volume
    from shapely.geometry import box
    slabs = [{"geometry": box(i * 3, 0, i * 3 + 2, 2), "height": 0.16,
              "z_offset": (i % 3) * 0.08} for i in range(20)]
    monkeypatch.setattr(spill, "_retained_memory_limit", lambda: 1024**3)
    expected = build_vector_layered_volume(slabs, scale_mm_per_svg_unit=1.0)
    monkeypatch.setattr(spill, "_retained_memory_limit", lambda: 1)
    result = build_vector_layered_volume(slabs, scale_mm_per_svg_unit=1.0)
    np.testing.assert_array_equal(result.vertices, expected.vertices)
    np.testing.assert_array_equal(result.faces, expected.faces)
    assert result.metadata == expected.metadata


def test_disk_creation_failure_closes_already_opened_buffer(monkeypatch, tmp_path: Path):
    from core import vector_mesh_spill as spill
    monkeypatch.setattr(spill, "_retained_memory_limit", lambda: 1)
    real_temporary_file = spill.tempfile.TemporaryFile
    files = []

    def open_buffer(**kwargs):
        if files:
            raise OSError("disk full")
        file = real_temporary_file(dir=tmp_path, **kwargs)
        files.append(file)
        return file

    monkeypatch.setattr(spill.tempfile, "TemporaryFile", open_buffer)
    with pytest.raises(OSError, match="disk full"):
        with spill.AdaptiveMeshAccumulator() as accumulator:
            accumulator.add(trimesh.creation.box())
    assert files[0].closed
    assert not list(tmp_path.glob("lumina-vector-buffer-*"))
