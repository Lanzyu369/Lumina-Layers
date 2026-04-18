"""Unit tests for pipeline-level Bambu base-layer modifier context propagation."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pytest
import trimesh

from config import ModelingMode, PrinterConfig
from core.pipeline import coordinator, s06_voxel_building


_EXPECTED_CASES = [
    ("4-Color", "单面", 10, 0.8, 0.8, 0.8, "down"),
    ("4-Color", "双面", 10, 0.8, 0.8, 0.8, "double"),
    ("5-Color Extended", "单面", 15, 1.6, 1.6, 1.2, "up"),
    ("BW", "单面", 5, 0.4, 0.4, 0.4, "down"),
    ("4-Color", "单面", 0, 0.8, 0.8, 0.0, "down"),
    ("4-Color", "单面", 5, 0.0, 0.08, 0.4, "down"),
]


@pytest.mark.parametrize(
    ("color_mode", "structure_mode", "num_layers", "thickness_mm", "expected_base", "expected_color", "expected_face"),
    _EXPECTED_CASES,
)
def test_vector_pipeline_ctx_formula_matches_expected_mapping(
    color_mode: str,
    structure_mode: str,
    num_layers: int,
    thickness_mm: float,
    expected_base: float,
    expected_color: float,
    expected_face: str,
) -> None:
    ctx: dict[str, object] = {}

    coordinator._update_bambu_base_layer_ctx_for_vector(
        ctx,
        color_mode=color_mode,
        structure_mode=structure_mode,
        num_layers=num_layers,
        thickness_mm=thickness_mm,
    )

    assert ctx["bambu_base_height_mm"] == expected_base
    assert ctx["bambu_color_height_mm"] == expected_color
    assert ctx["bambu_face_orientation"] == expected_face
    assert ctx["enable_base_layer_height_modifier"] is True


@pytest.mark.parametrize(
    ("color_mode", "structure_mode", "num_layers", "thickness_mm", "expected_base", "expected_color", "expected_face"),
    _EXPECTED_CASES,
)
def test_voxel_pipeline_sets_bambu_ctx_values(
    color_mode: str,
    structure_mode: str,
    num_layers: int,
    thickness_mm: float,
    expected_base: float,
    expected_color: float,
    expected_face: str,
) -> None:
    material_matrix = np.zeros((3, 3, num_layers), dtype=int)
    mask_solid = np.ones((3, 3), dtype=bool)
    matched_rgb = np.zeros((3, 3, 3), dtype=np.uint8)
    ctx = {
        "material_matrix": material_matrix,
        "mask_solid": mask_solid,
        "spacer_thick": thickness_mm,
        "structure_mode": structure_mode,
        "backing_color_id": 0,
        "color_mode": color_mode,
        "enable_cloisonne": False,
        "enable_relief": False,
        "color_height_map": None,
        "height_mode": "color",
        "heightmap_path": None,
        "heightmap_max_height": None,
        "matched_rgb": matched_rgb,
        "pixel_scale": 0.1,
    }

    result = s06_voxel_building.run(ctx)

    assert result["bambu_base_height_mm"] == expected_base
    assert result["bambu_color_height_mm"] == expected_color
    assert result["bambu_face_orientation"] == expected_face
    assert result["enable_base_layer_height_modifier"] is True


def test_vector_branch_passes_bambu_modifier_kwargs_to_exporter(tmp_path) -> None:
    captured: dict[str, object] = {}

    class _FakeVectorProcessor:
        parse_warnings: list[str] = []
        last_stage_timings: dict[str, float] = {}

        def __init__(self, _lut_path: str, color_mode: str) -> None:
            self.color_mode = color_mode
            self.enable_fridge_magnet = False
            self.fridge_magnets = []

        def analyze_svg(self, *, svg_path: str, target_width_mm: float, color_replacements=None):
            del svg_path, target_width_mm, color_replacements
            return SimpleNamespace(
                num_layers=15,
                preview_colors={0: [255, 0, 0, 255]},
                slot_names=["Slot 1"],
            )

        def build_mesh(self, *, analysis, thickness_mm: float, structure_mode: str):
            del analysis, thickness_mm, structure_mode
            scene = trimesh.Scene()
            scene.add_geometry(trimesh.creation.box(extents=(1, 1, 1)), geom_name="Slot 1")
            return scene

        @staticmethod
        def render_preview(analysis, pixels_per_mm: float):
            del analysis, pixels_per_mm
            return None

    def _fake_export_scene_with_bambu_metadata(**kwargs):
        captured.update(kwargs)
        return kwargs["output_path"]

    with patch("core.vector_engine.VectorProcessor", _FakeVectorProcessor), patch(
        "utils.bambu_3mf_writer.export_scene_with_bambu_metadata",
        side_effect=_fake_export_scene_with_bambu_metadata,
    ), patch("core.naming.generate_model_filename", lambda *_args: "vector-out.3mf"), patch(
        "core.naming.generate_preview_filename",
        lambda *_args: "vector-preview.glb",
    ), patch("config.MODELS_DIR", str(tmp_path)), patch(
        "config.OUTPUT_DIR",
        str(tmp_path),
    ), patch("utils.Stats.increment", lambda *_args, **_kwargs: None), patch.object(
        coordinator,
        "_report_progress",
        lambda *_args, **_kwargs: None,
    ):
        ctx = {
            "image_path": str(tmp_path / "vector.svg"),
            "actual_lut_path": str(tmp_path / "fake.json"),
            "color_mode": "5-Color Extended",
            "modeling_mode": ModelingMode.HIGH_FIDELITY,
            "target_width_mm": 40.0,
            "spacer_thick": 1.6,
            "structure_mode": "单面",
            "need_2d_preview": False,
            "printer_id": "bambu-h2d",
            "slicer": "BambuStudio",
            "nozzle_size": "0.4",
        }

        result = coordinator._run_vector_branch(ctx)

    assert "error" not in result
    assert captured["enable_base_layer_height_modifier"] is True
    assert captured["base_height_mm"] == 1.6
    assert captured["color_height_mm"] == 15 * PrinterConfig.LAYER_HEIGHT
    assert captured["face_orientation"] == "up"
