from __future__ import annotations

from collections.abc import Mapping
import logging
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
import trimesh

from config import ColorSystem, ModelingMode
from core.pipeline import (
    s05_preview_generation,
    s08_auxiliary_meshes,
    s11_glb_preview,
    s12_result_assembly,
)
from helpers_threemf_manifest import extract_manifest
from utils.bambu_3mf_writer import export_scene_with_bambu_metadata


def _preview_mapping_for_key_shape(
    *,
    material_id: int,
    material_name: str,
    rgba: list[int],
    key_shape: str,
) -> dict[object, list[int]]:
    if key_shape == "int":
        return {material_id: rgba}
    if key_shape == "str":
        return {str(material_id): rgba}
    if key_shape == "name":
        return {material_name: rgba}
    raise AssertionError(f"unsupported key shape: {key_shape}")


def _run_s05_with_loop_material(
    *,
    slot_names: list[str],
    preview_colors: Mapping[object, list[int]],
    material_id: int,
) -> dict:
    height = width = 32
    return s05_preview_generation.run(
        {
            "matched_rgb": np.full(
                (height, width, 3),
                [9, 9, 9],
                dtype=np.uint8,
            ),
            "mask_solid": np.ones((height, width), dtype=bool),
            "target_w": width,
            "target_h": height,
            "pixel_scale": 1.0,
            # Deliberately stale: the authoritative runtime palette below is
            # wider than this old color-system snapshot.
            "color_conf": {
                "slots": ["Legacy White"],
                "preview": {0: [255, 255, 255, 255]},
                "map": {"Legacy White": 0},
            },
            "preview_colors": dict(preview_colors),
            "slot_names": list(slot_names),
            "add_loop": True,
            "loop_pos": (16.0, 16.0),
            "loop_width": 6.0,
            "loop_length": 10.0,
            "loop_hole": 2.0,
            "material_matrix": np.full(
                (height, width, 5),
                material_id,
                dtype=np.int32,
            ),
        }
    )


@pytest.mark.parametrize(
    ("mode", "key_shape"),
    [
        ("4-Color (RYBW)", "int"),
        ("5-Color Extended", "str"),
        ("6-Color (RYBW)", "name"),
        ("8-Color Max", "int"),
    ],
)
def test_s05_loop_uses_authoritative_material_style_for_supported_modes(
    mode: str,
    key_shape: str,
) -> None:
    color_conf = ColorSystem.get(mode)
    slot_names = list(color_conf["slots"])
    material_id = len(slot_names) - 1
    material_name = slot_names[material_id]
    rgba = list(color_conf["preview"][material_id])
    preview_colors = _preview_mapping_for_key_shape(
        material_id=material_id,
        material_name=material_name,
        rgba=rgba,
        key_shape=key_shape,
    )

    result = _run_s05_with_loop_material(
        slot_names=slot_names,
        preview_colors=preview_colors,
        material_id=material_id,
    )

    assert result["loop_info"]["color_id"] == material_id
    assert result["loop_info"]["material_name"] == material_name
    assert result["loop_info"]["color_rgba"] == rgba
    assert np.any(
        np.all(
            result["preview_rgba"] == np.asarray(rgba, dtype=np.uint8),
            axis=2,
        )
    )


def test_s05_loop_preserves_custom_material_archive_name_and_color() -> None:
    slot_names = [
        "爱丽兹 PETG Basic 青色",
        "爱丽兹 PETG 白色",
        "自定义夜空紫",
        "自定义暖橙",
    ]
    rgba = [17, 34, 51, 255]

    result = _run_s05_with_loop_material(
        slot_names=slot_names,
        preview_colors={slot_names[3]: rgba},
        material_id=3,
    )

    assert result["loop_info"]["color_id"] == 3
    assert result["loop_info"]["material_name"] == slot_names[3]
    assert result["loop_info"]["color_rgba"] == rgba


@pytest.mark.parametrize(
    ("loop_info", "expected_label"),
    [
        (
            {"color_id": 7, "material_name": "自定义夜空紫"},
            "自定义夜空紫",
        ),
        ({"color_id": 7}, "Material 7"),
    ],
)
def test_s12_loop_status_does_not_reindex_resolved_material(
    loop_info: dict[str, object],
    expected_label: str,
) -> None:
    ctx = {
        "out_path": "/tmp/output.3mf",
        "glb_path": None,
        "preview_img": None,
        "mode_info": {"mode": ModelingMode.HIGH_FIDELITY},
        "target_w": 32,
        "target_h": 32,
        "loop_info": loop_info,
        "loop_added": True,
        "slot_names": ["White"],
        "heightmap_stats": None,
        "color_recipe_path": None,
        "_hifi_timings": {},
    }

    with patch("core.pipeline.s12_result_assembly.Stats"):
        result = s12_result_assembly.run(ctx)

    assert f"Loop: {expected_label}" in result["result_tuple"][3]


def test_loop_material_identity_survives_s05_s08_and_actual_3mf_export(
    tmp_path: Path,
) -> None:
    slot_names = ["Archive White", "Archive Red", "Archive Yellow", "Archive Blue"]
    selected_rgba = [17, 34, 51, 255]
    preview_colors = {slot_names[3]: selected_rgba}
    s05_result = _run_s05_with_loop_material(
        slot_names=slot_names,
        preview_colors=preview_colors,
        material_id=3,
    )

    s08_result = s08_auxiliary_meshes.run(
        {
            **s05_result,
            "scene": trimesh.Scene(),
            "valid_slot_names": [],
            "full_matrix": np.full((5, 32, 32), -1, dtype=np.int32),
            "total_layers": 5,
            "transform": np.eye(4),
            "mesher": object(),
            "separate_backing": False,
            "enable_cloisonne": False,
            "backing_metadata": {},
            "enable_coating": False,
            "enable_outline": False,
            "free_color_set": None,
            "material_source": "material_archive",
            "material_base_channel_idx": 0,
        }
    )

    assert s08_result["loop_added"] is True
    assert s08_result["valid_slot_names"] == ["Keychain_Loop"]
    assert "Keychain_Loop" not in slot_names
    assert s08_result["preview_colors"]["Keychain_Loop"] == selected_rgba
    loop_mesh = s08_result["scene"].geometry["Keychain_Loop"]
    assert loop_mesh.metadata["bambu_material_name"] == slot_names[3]
    assert list(np.asarray(loop_mesh.visual.face_colors)[0]) == selected_rgba

    output_path = tmp_path / "loop-material-identity.3mf"
    export_scene_with_bambu_metadata(
        scene=s08_result["scene"],
        output_path=str(output_path),
        slot_names=s08_result["valid_slot_names"],
        preview_colors=s08_result["preview_colors"],
        project_slot_names=slot_names,
        settings={},
        color_mode="4-Color",
        printer_id="bambu-h2d",
        slicer="BambuStudio",
        nozzle_size="0.4",
        enable_base_layer_height_modifier=False,
    )

    manifest = extract_manifest(output_path)
    project_settings = manifest["project_settings"]
    assert manifest["part_extruders"]["Keychain_Loop"] == "4"
    assert len(project_settings["filament_colour"]) == len(slot_names)
    assert project_settings["filament_colour"][3].upper() == "#112233"
    assert all("Keychain_Loop" not in name for name in slot_names)


def test_s05_unresolved_loop_material_warns_once_without_private_fields(
    caplog,
) -> None:
    private_material_name = "Private Custom Material"
    target_logger = logging.getLogger(s05_preview_generation._log.name)
    target_logger.addHandler(caplog.handler)
    caplog.set_level(logging.WARNING, logger=target_logger.name)

    try:
        with pytest.raises(
            ValueError,
            match="Loop material identity or preview color is unavailable",
        ):
            _run_s05_with_loop_material(
                slot_names=["White", private_material_name],
                preview_colors={},
                material_id=1,
            )
    finally:
        target_logger.removeHandler(caplog.handler)

    records = [
        record
        for record in caplog.records
        if getattr(record, "event", None)
        == "loop_material_preview_unresolved"
    ]
    assert len(records) == 1
    record = records[0]
    assert record.error_type == "LoopMaterialResolutionError"
    assert record.reason == "unresolved_color"
    assert record.material_id == 1
    assert record.slot_count == 2
    assert record.preview_color_count == 0
    assert record.available_material_ids == []
    assert record.resolution_attempts == [
        "preview_int",
        "preview_str",
        "preview_name",
        "color_conf_name",
        "canonical_name",
    ]
    assert private_material_name not in record.getMessage()
    assert not hasattr(record, "path")


def test_s05_without_loop_does_not_require_material_preview_mapping() -> None:
    result = s05_preview_generation.run(
        {
            "matched_rgb": np.zeros((2, 2, 3), dtype=np.uint8),
            "mask_solid": np.ones((2, 2), dtype=bool),
            "target_w": 2,
            "target_h": 2,
            "pixel_scale": 1.0,
            "color_conf": {},
            "add_loop": False,
        }
    )

    assert result["loop_info"] is None


@pytest.mark.parametrize("key_shape", ["int", "str", "name"])
def test_existing_s11_material_preview_resolution_remains_compatible(
    key_shape: str,
) -> None:
    slot_names = ["White", "Red", "Yellow", "Archive Blue"]
    selected_rgba = [17, 34, 51, 255]
    cache = {
        "slot_names": slot_names,
        "preview_colors": _preview_mapping_for_key_shape(
            material_id=3,
            material_name=slot_names[3],
            rgba=selected_rgba,
            key_shape=key_shape,
        ),
        "color_conf": {"preview": {0: [255, 255, 255, 255]}},
    }

    rgba = s11_glb_preview._preview_rgba_for_material(cache, 3)

    assert rgba.tolist() == selected_rgba
