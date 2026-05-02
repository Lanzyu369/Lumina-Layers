from __future__ import annotations

import numpy as np
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
