from __future__ import annotations

import logging

import numpy as np
import pytest
import trimesh

from core.pipeline import s08_auxiliary_meshes


class _FakeMesher:
    def generate_mesh(self, *args, **kwargs):
        return trimesh.creation.box(extents=(1, 1, 1))


def _first_face_color(mesh) -> list[int]:
    return [int(value) for value in np.asarray(mesh.visual.face_colors)[0].tolist()]


def test_material_archive_backing_and_outline_use_inferred_white_slot() -> None:
    mask_solid = np.zeros((4, 4), dtype=bool)
    mask_solid[1:3, 1:3] = True
    preview_colors = {
        0: [0, 180, 0, 255],
        1: [248, 248, 245, 255],
    }
    ctx = {
        "scene": trimesh.Scene(),
        "valid_slot_names": [],
        "full_matrix": np.full((2, 4, 4), -1, dtype=int),
        "mask_solid": mask_solid,
        "matched_rgb": np.zeros((4, 4, 3), dtype=np.uint8),
        "target_h": 4,
        "target_w": 4,
        "pixel_scale": 0.1,
        "total_layers": 2,
        "preview_colors": preview_colors,
        "transform": np.eye(4),
        "mesher": _FakeMesher(),
        "separate_backing": True,
        "enable_cloisonne": False,
        "backing_metadata": {},
        "enable_coating": False,
        "enable_outline": True,
        "outline_width": 0.1,
        "free_color_set": None,
        "add_loop": False,
        "loop_info": None,
        "material_source": "material_archive",
        "material_base_channel_idx": 1,
        "slot_names": ["PLA Green", "PLA White"],
    }

    result = s08_auxiliary_meshes.run(ctx)

    backing_mesh = result["scene"].geometry["Backing"]
    outline_mesh = result["scene"].geometry["Outline"]

    assert backing_mesh.metadata["bambu_material_name"] == "PLA White"
    assert outline_mesh.metadata["bambu_material_name"] == "PLA White"
    assert _first_face_color(backing_mesh) == [248, 248, 245, 255]
    assert _first_face_color(outline_mesh) == [248, 248, 245, 255]
    assert result["preview_colors"]["Backing"] == [248, 248, 245, 255]
    assert result["preview_colors"]["Outline"] == [248, 248, 245, 255]
    assert result["valid_slot_names"][-2:] == ["Backing", "Outline"]


def test_keychain_loop_preserves_selected_material_name_for_slicer_metadata() -> None:
    preview_colors = {
        0: [0, 122, 214, 255],
        1: [248, 248, 245, 255],
    }
    ctx = {
        "scene": trimesh.Scene(),
        "valid_slot_names": [],
        "full_matrix": np.full((2, 4, 4), -1, dtype=int),
        "mask_solid": np.ones((4, 4), dtype=bool),
        "matched_rgb": np.zeros((4, 4, 3), dtype=np.uint8),
        "target_h": 4,
        "target_w": 4,
        "pixel_scale": 0.1,
        "total_layers": 2,
        "preview_colors": preview_colors,
        "transform": np.eye(4),
        "mesher": _FakeMesher(),
        "separate_backing": False,
        "enable_cloisonne": False,
        "backing_metadata": {},
        "enable_coating": False,
        "enable_outline": False,
        "outline_width": 0.1,
        "free_color_set": None,
        "add_loop": True,
        "loop_info": {
            "width_mm": 4.0,
            "length_mm": 8.0,
            "hole_dia_mm": 2.5,
            "attach_x_mm": 0.0,
            "attach_y_mm": 0.0,
            "color_id": 0,
        },
        "material_source": "material_archive",
        "material_base_channel_idx": 1,
        "slot_names": ["爱丽兹 PETG Basic 青色", "爱丽兹 PETG 白色"],
    }

    result = s08_auxiliary_meshes.run(ctx)

    loop_mesh = result["scene"].geometry["Keychain_Loop"]
    assert loop_mesh.metadata["bambu_material_name"] == "爱丽兹 PETG Basic 青色"
    assert _first_face_color(loop_mesh) == [0, 122, 214, 255]


def test_keychain_loop_resolves_name_keyed_runtime_material_style() -> None:
    slot_names = [
        "爱丽兹 PETG Basic 青色",
        "爱丽兹 PETG 白色",
        "自定义夜空紫",
        "自定义暖橙",
    ]
    selected_rgba = [17, 34, 51, 255]
    existing_aux_color = [91, 81, 71, 255]
    preview_colors = {
        slot_names[3]: selected_rgba,
        "Keychain_Loop": existing_aux_color,
    }
    ctx = {
        "scene": trimesh.Scene(),
        "valid_slot_names": [],
        "full_matrix": np.full((2, 4, 4), -1, dtype=int),
        "mask_solid": np.ones((4, 4), dtype=bool),
        "matched_rgb": np.zeros((4, 4, 3), dtype=np.uint8),
        "target_h": 4,
        "target_w": 4,
        "pixel_scale": 0.1,
        "total_layers": 2,
        "preview_colors": preview_colors,
        "color_conf": {
            "slots": ["Legacy White"],
            "preview": {0: [255, 255, 255, 255]},
        },
        "transform": np.eye(4),
        "mesher": _FakeMesher(),
        "separate_backing": False,
        "enable_cloisonne": False,
        "backing_metadata": {},
        "enable_coating": False,
        "enable_outline": False,
        "outline_width": 0.1,
        "free_color_set": None,
        "add_loop": True,
        "loop_info": {
            "width_mm": 4.0,
            "length_mm": 8.0,
            "hole_dia_mm": 2.5,
            "attach_x_mm": 0.0,
            "attach_y_mm": 0.0,
            "color_id": 3,
        },
        "material_source": "material_archive",
        "material_base_channel_idx": 1,
        "slot_names": slot_names,
    }

    result = s08_auxiliary_meshes.run(ctx)

    assert result["loop_added"] is True
    loop_mesh = result["scene"].geometry["Keychain_Loop"]
    assert loop_mesh.metadata["bambu_material_name"] == slot_names[3]
    assert _first_face_color(loop_mesh) == selected_rgba
    assert result["preview_colors"]["Keychain_Loop"] == existing_aux_color


def test_direct_s08_unresolved_loop_material_warns_once_and_aborts(caplog) -> None:
    private_material_name = "Private Custom Material"
    ctx = {
        "scene": trimesh.Scene(),
        "valid_slot_names": [],
        "full_matrix": np.full((2, 4, 4), -1, dtype=int),
        "mask_solid": np.ones((4, 4), dtype=bool),
        "matched_rgb": np.zeros((4, 4, 3), dtype=np.uint8),
        "target_h": 4,
        "target_w": 4,
        "pixel_scale": 0.1,
        "total_layers": 2,
        "preview_colors": {},
        "color_conf": {"slots": ["Legacy White"], "preview": {}},
        "transform": np.eye(4),
        "mesher": _FakeMesher(),
        "separate_backing": False,
        "enable_cloisonne": False,
        "backing_metadata": {},
        "enable_coating": False,
        "enable_outline": False,
        "outline_width": 0.1,
        "free_color_set": None,
        "add_loop": True,
        "loop_info": {
            "width_mm": 4.0,
            "length_mm": 8.0,
            "hole_dia_mm": 2.5,
            "attach_x_mm": 0.0,
            "attach_y_mm": 0.0,
            "color_id": 1,
        },
        "material_source": "material_archive",
        "material_base_channel_idx": 0,
        "slot_names": ["White", private_material_name],
    }
    target_logger = logging.getLogger(s08_auxiliary_meshes._log.name)
    target_logger.addHandler(caplog.handler)
    caplog.set_level(logging.WARNING, logger=target_logger.name)

    try:
        with pytest.raises(
            ValueError,
            match="Loop material identity or preview color is unavailable",
        ):
            s08_auxiliary_meshes.run(ctx)
    finally:
        target_logger.removeHandler(caplog.handler)

    records = [
        record
        for record in caplog.records
        if getattr(record, "event", None)
        == "loop_material_preview_unresolved"
    ]
    assert len(records) == 1
    assert records[0].material_id == 1
    assert private_material_name not in records[0].getMessage()
    assert "Keychain_Loop" not in ctx["scene"].geometry


def test_keychain_geometry_failure_warns_and_keeps_the_model(
    monkeypatch,
    caplog,
) -> None:
    existing_aux_color = [91, 81, 71, 255]
    ctx = {
        "scene": trimesh.Scene(),
        "valid_slot_names": [],
        "full_matrix": np.full((2, 4, 4), -1, dtype=int),
        "mask_solid": np.ones((4, 4), dtype=bool),
        "matched_rgb": np.zeros((4, 4, 3), dtype=np.uint8),
        "target_h": 4,
        "target_w": 4,
        "pixel_scale": 0.1,
        "total_layers": 2,
        "preview_colors": {
            1: [17, 34, 51, 255],
            "Keychain_Loop": existing_aux_color,
        },
        "color_conf": {},
        "transform": np.eye(4),
        "mesher": _FakeMesher(),
        "separate_backing": False,
        "enable_cloisonne": False,
        "backing_metadata": {},
        "enable_coating": False,
        "enable_outline": False,
        "outline_width": 0.1,
        "free_color_set": None,
        "add_loop": True,
        "loop_info": {
            "width_mm": 4.0,
            "length_mm": 8.0,
            "hole_dia_mm": 2.5,
            "attach_x_mm": 0.0,
            "attach_y_mm": 0.0,
            "color_id": 1,
        },
        "material_source": "material_archive",
        "material_base_channel_idx": 0,
        "slot_names": ["White", "Archive Blue"],
    }
    monkeypatch.setattr(
        s08_auxiliary_meshes,
        "create_keychain_loop",
        lambda **_kwargs: None,
    )
    target_logger = logging.getLogger(s08_auxiliary_meshes._log.name)
    target_logger.addHandler(caplog.handler)
    caplog.set_level(logging.WARNING, logger=target_logger.name)

    try:
        result = s08_auxiliary_meshes.run(ctx)
    finally:
        target_logger.removeHandler(caplog.handler)

    assert result["loop_added"] is False
    assert "Keychain_Loop" not in result["scene"].geometry
    assert result["preview_colors"]["Keychain_Loop"] == existing_aux_color
    records = [
        record
        for record in caplog.records
        if getattr(record, "event", None)
        == "s08_keychain_loop_creation_failed"
    ]
    assert len(records) == 1
    assert records[0].error_type == "RuntimeError"
    assert records[0].material_id == 1
