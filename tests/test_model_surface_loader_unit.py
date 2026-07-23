from __future__ import annotations

import pytest
import trimesh

from core.model_surface.loader import load_model_surface_mesh
from core.model_surface.types import ModelSurfaceError


def test_load_model_surface_mesh_reports_processed_box(tmp_path):
    path = tmp_path / "plate.stl"
    trimesh.creation.box(extents=(80.0, 40.0, 5.0)).export(path)

    loaded = load_model_surface_mesh(path)

    assert loaded.summary.extents_mm == pytest.approx((80.0, 40.0, 5.0))
    assert loaded.summary.face_count > 0
    assert loaded.summary.is_watertight is True
    assert loaded.summary.unit_warning is None


def test_load_model_surface_mesh_rejects_unknown_extension(tmp_path):
    path = tmp_path / "plate.step"
    path.write_text("not supported", encoding="utf-8")

    with pytest.raises(ModelSurfaceError, match="Only STL and OBJ"):
        load_model_surface_mesh(path)


def test_load_model_surface_mesh_warns_for_tiny_inch_like_model(tmp_path):
    path = tmp_path / "inch_plate.stl"
    trimesh.creation.box(extents=(8.0, 8.0, 0.2)).export(path)

    loaded = load_model_surface_mesh(path)

    assert loaded.summary.unit_warning == "model_dimensions_look_like_inches"
