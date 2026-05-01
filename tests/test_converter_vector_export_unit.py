"""Unit tests for the vector branch export in converter.py.

Validates that:
    1. The vector branch calls export_scene_with_bambu_metadata (not scene.export).
    2. The slot_names passed to the exporter match the final scene geometry keys.
"""

import sys
import os
import types
from unittest.mock import patch, MagicMock

# Add project root to path
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import pytest
import trimesh
import numpy as np
from utils.bambu_3mf_writer import export_scene_with_bambu_metadata, BambuStudio3MFWriter


def _build_fake_processor(scene):
    """Return a MagicMock that behaves like VectorProcessor."""
    vp = MagicMock()
    vp.svg_to_mesh.return_value = scene
    vp.img_processor.lut_rgb = np.zeros((256, 3))
    vp.img_processor._load_svg.return_value = np.zeros((100, 100, 4), dtype=np.uint8)
    vp.color_mode = "4-Color"

    fake_analysis = MagicMock()
    fake_analysis.preview_colors = {0: [255, 255, 255, 255], 1: [255, 0, 0, 255],
                                    2: [255, 255, 0, 255], 3: [0, 0, 255, 255]}
    fake_analysis.slot_names = ["White", "Red", "Yellow", "Blue"]
    fake_analysis.stage_timings = {}
    vp.analyze_svg.return_value = fake_analysis
    vp.build_mesh.return_value = scene
    vp.render_preview = MagicMock(return_value=np.zeros((100, 100, 4), dtype=np.uint8))
    return vp


# =====================================================================
# 1. Vector branch uses Bambu metadata export
# =====================================================================


class TestVectorBranchExport:
    """Confirm the vector conversion path goes through the unified
    Bambu metadata exporter rather than the plain trimesh export."""

    @patch("utils.bambu_3mf_writer.export_scene_with_bambu_metadata")
    @patch("core.vector_engine.VectorProcessor")
    def test_bambu_export_called(self, MockVP, mock_bambu_export, tmp_path):
        """export_scene_with_bambu_metadata should be invoked for SVG vector mode."""
        from config import ModelingMode

        svg_file = tmp_path / "test.svg"
        svg_file.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">'
            '<rect x="0" y="0" width="100" height="100" fill="#ff0000"/>'
            "</svg>"
        )

        fake_scene = trimesh.Scene()
        mesh = trimesh.creation.box(extents=[10, 10, 1])
        mesh.metadata["name"] = "White"
        mesh.visual.face_colors = [255, 255, 255, 255]
        fake_scene.add_geometry(mesh, geom_name="White")

        MockVP.return_value = _build_fake_processor(fake_scene)

        from core.converter import convert_image_to_3d

        dummy_lut = str(tmp_path / "dummy.npy")
        np.save(dummy_lut, np.zeros(10))

        convert_image_to_3d(
            image_path=str(svg_file),
            lut_path=dummy_lut,
            target_width_mm=50.0,
            spacer_thick=1.6,
            structure_mode="Single-sided",
            color_mode="4-Color",
            add_loop=False,
            loop_width=5,
            loop_length=20,
            loop_hole=3,
            loop_pos="Top",
            modeling_mode=ModelingMode.VECTOR,
        )

        mock_bambu_export.assert_called_once()

    @patch("utils.bambu_3mf_writer.export_scene_with_bambu_metadata")
    @patch("core.vector_engine.VectorProcessor")
    def test_slot_names_match_scene_geometry(self, MockVP, mock_bambu_export, tmp_path):
        """When backing is merged, slot_names should match the post-merge geometry keys."""
        from config import ModelingMode

        svg_file = tmp_path / "test2.svg"
        svg_file.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="50" height="50">'
            '<circle cx="25" cy="25" r="20" fill="#0000ff"/>'
            "</svg>"
        )

        fake_scene = trimesh.Scene()
        for name in ["White", "Cyan", "Board"]:
            m = trimesh.creation.box(extents=[5, 5, 0.5])
            m.metadata["name"] = name
            fake_scene.add_geometry(m, geom_name=name)

        MockVP.return_value = _build_fake_processor(fake_scene)

        from core.converter import convert_image_to_3d

        dummy_lut = str(tmp_path / "dummy2.npy")
        np.save(dummy_lut, np.zeros(10))

        convert_image_to_3d(
            image_path=str(svg_file),
            lut_path=dummy_lut,
            target_width_mm=30.0,
            spacer_thick=1.6,
            structure_mode="Single-sided",
            color_mode="4-Color",
            add_loop=False,
            loop_width=5,
            loop_length=20,
            loop_hole=3,
            loop_pos="Top",
            modeling_mode=ModelingMode.VECTOR,
        )

        _, kwargs = mock_bambu_export.call_args
        assert kwargs["slot_names"] == ["White", "Cyan"]

    @patch("utils.bambu_3mf_writer.export_scene_with_bambu_metadata")
    @patch("core.vector_engine.VectorProcessor")
    def test_slot_names_keep_board_when_separate_backing_enabled(self, MockVP, mock_bambu_export, tmp_path):
        """When separate_backing=True, Board should remain an exported slot."""
        from config import ModelingMode

        svg_file = tmp_path / "test3.svg"
        svg_file.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="50" height="50">'
            '<circle cx="25" cy="25" r="20" fill="#0000ff"/>'
            "</svg>"
        )

        fake_scene = trimesh.Scene()
        for name in ["White", "Cyan", "Board"]:
            m = trimesh.creation.box(extents=[5, 5, 0.5])
            m.metadata["name"] = name
            fake_scene.add_geometry(m, geom_name=name)

        MockVP.return_value = _build_fake_processor(fake_scene)

        from core.converter import convert_image_to_3d

        dummy_lut = str(tmp_path / "dummy3.npy")
        np.save(dummy_lut, np.zeros(10))

        convert_image_to_3d(
            image_path=str(svg_file),
            lut_path=dummy_lut,
            target_width_mm=30.0,
            spacer_thick=1.6,
            structure_mode="Single-sided",
            color_mode="4-Color",
            add_loop=False,
            loop_width=5,
            loop_length=20,
            loop_hole=3,
            loop_pos="Top",
            modeling_mode=ModelingMode.VECTOR,
            separate_backing=True,
        )

        _, kwargs = mock_bambu_export.call_args
        assert kwargs["slot_names"] == ["White", "Cyan", "Board"]

    @patch("utils.bambu_3mf_writer.export_scene_with_bambu_metadata")
    @patch("core.vector_engine.VectorProcessor")
    def test_vector_export_centers_scene_on_selected_printer_bed(self, MockVP, mock_bambu_export, tmp_path):
        """Vector branch should center ordinary final exports before Bambu 3MF writing."""
        from config import ModelingMode

        svg_file = tmp_path / "center-vector.svg"
        svg_file.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="50" height="50">'
            '<rect x="0" y="0" width="50" height="50" fill="#ffffff"/>'
            "</svg>"
        )

        fake_scene = trimesh.Scene()
        mesh = trimesh.creation.box(extents=[20, 10, 1])
        mesh.metadata["name"] = "White"
        fake_scene.add_geometry(mesh, geom_name="White")
        MockVP.return_value = _build_fake_processor(fake_scene)

        from core.converter import convert_image_to_3d

        dummy_lut = str(tmp_path / "dummy-centered-vector.npy")
        np.save(dummy_lut, np.zeros(10))

        convert_image_to_3d(
            image_path=str(svg_file),
            lut_path=dummy_lut,
            target_width_mm=30.0,
            spacer_thick=1.6,
            structure_mode="Single-sided",
            color_mode="4-Color",
            add_loop=False,
            loop_width=5,
            loop_length=20,
            loop_hole=3,
            loop_pos="Top",
            modeling_mode=ModelingMode.VECTOR,
            printer_id="bambu-p1s",
        )

        _, kwargs = mock_bambu_export.call_args
        exported_scene = kwargs["scene"]
        bounds = exported_scene.bounds
        center_x = (bounds[0][0] + bounds[1][0]) / 2
        center_y = (bounds[0][1] + bounds[1][1]) / 2
        assert center_x == pytest.approx(128)
        assert center_y == pytest.approx(128)

    @patch("utils.bambu_3mf_writer.export_scene_with_bambu_metadata")
    @patch("core.vector_engine.VectorProcessor")
    def test_vector_branch_sets_processor_coating_options(self, MockVP, mock_bambu_export, tmp_path):
        from config import ModelingMode

        svg_file = tmp_path / "coating-vector.svg"
        svg_file.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="50" height="50">'
            '<rect x="0" y="0" width="50" height="50" fill="#ffffff"/>'
            "</svg>"
        )

        fake_scene = trimesh.Scene()
        mesh = trimesh.creation.box(extents=[20, 10, 1])
        mesh.metadata["name"] = "White"
        fake_scene.add_geometry(mesh, geom_name="White")
        fake_processor = _build_fake_processor(fake_scene)
        MockVP.return_value = fake_processor

        from core.converter import convert_image_to_3d

        dummy_lut = str(tmp_path / "dummy-coating-vector.npy")
        np.save(dummy_lut, np.zeros(10))

        convert_image_to_3d(
            image_path=str(svg_file),
            lut_path=dummy_lut,
            target_width_mm=30.0,
            spacer_thick=1.6,
            structure_mode="Single-sided",
            color_mode="4-Color",
            add_loop=False,
            loop_width=5,
            loop_length=20,
            loop_hole=3,
            loop_pos="Top",
            modeling_mode=ModelingMode.VECTOR,
            enable_coating=True,
            coating_height_mm=0.12,
        )

        assert fake_processor.enable_coating is True
        assert fake_processor.coating_height_mm == 0.12

    @patch("utils.bambu_3mf_writer.export_scene_with_bambu_metadata")
    @patch("core.vector_engine.VectorProcessor")
    def test_empty_scene_returns_error(self, MockVP, mock_bambu_export, tmp_path):
        """Empty vector scene should fail before exporter is called."""
        from config import ModelingMode

        svg_file = tmp_path / "empty.svg"
        svg_file.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
            '<rect x="0" y="0" width="10" height="10" fill="#ffffff"/>'
            "</svg>"
        )

        empty_scene = trimesh.Scene()
        MockVP.return_value = _build_fake_processor(empty_scene)

        from core.converter import convert_image_to_3d

        dummy_lut = str(tmp_path / "dummy4.npy")
        np.save(dummy_lut, np.zeros(10))

        out_path, glb_path, preview_img, msg, _ = convert_image_to_3d(
            image_path=str(svg_file),
            lut_path=dummy_lut,
            target_width_mm=20.0,
            spacer_thick=1.6,
            structure_mode="Single-sided",
            color_mode="4-Color",
            add_loop=False,
            loop_width=5,
            loop_length=20,
            loop_hole=3,
            loop_pos="Top",
            modeling_mode=ModelingMode.VECTOR,
        )

        assert out_path is None
        assert glb_path is None
        assert preview_img is None
        assert "no valid geometry" in msg.lower()
        mock_bambu_export.assert_not_called()

    @patch("utils.bambu_3mf_writer.export_scene_with_bambu_metadata")
    @patch("core.vector_engine.VectorProcessor")
    def test_fridge_magnet_params_forwarded_to_build_mesh(self, MockVP, mock_bambu_export, tmp_path):
        """Vector branch should forward fridge-magnet params into build_mesh."""
        from config import ModelingMode

        svg_file = tmp_path / "fridge.svg"
        svg_file.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="50" height="50">'
            '<circle cx="25" cy="25" r="20" fill="#0000ff"/>'
            "</svg>"
        )

        fake_scene = trimesh.Scene()
        mesh = trimesh.creation.box(extents=[5, 5, 0.5])
        mesh.metadata["name"] = "White"
        fake_scene.add_geometry(mesh, geom_name="White")

        fake_processor = _build_fake_processor(fake_scene)
        MockVP.return_value = fake_processor

        expected_fridge_magnets = [
            {
                "id": "magnet-round",
                "shape": "round",
                "preset_key": "round-18",
                "diameter_mm": 18.0,
                "width_mm": None,
                "height_mm": None,
                "thickness_mm": 2.0,
                "center_x_mm": 20.0,
                "center_y_mm": 25.0,
            }
        ]

        from core.converter import convert_image_to_3d

        dummy_lut = str(tmp_path / "dummy-fridge.npy")
        np.save(dummy_lut, np.zeros(10))

        convert_image_to_3d(
            image_path=str(svg_file),
            lut_path=dummy_lut,
            target_width_mm=30.0,
            spacer_thick=1.6,
            structure_mode="Single-sided",
            color_mode="4-Color",
            add_loop=False,
            loop_width=5,
            loop_length=20,
            loop_hole=3,
            loop_pos="Top",
            modeling_mode=ModelingMode.VECTOR,
            enable_fridge_magnet=True,
            fridge_magnets=expected_fridge_magnets,
        )

        _, kwargs = fake_processor.build_mesh.call_args
        assert kwargs["enable_fridge_magnet"] is True
        assert kwargs["fridge_magnets"] == expected_fridge_magnets


class TestBambuExportGuardrails:

    def test_export_scene_raises_on_missing_slot_geometry(self, tmp_path):
        scene = trimesh.Scene()
        scene.add_geometry(trimesh.creation.box(extents=[5, 5, 1]), geom_name="White")

        out_path = tmp_path / "out.3mf"
        with pytest.raises(ValueError, match="Missing geometries"):
            export_scene_with_bambu_metadata(
                scene=scene,
                output_path=str(out_path),
                slot_names=["White", "Cyan"],
                preview_colors={0: [255, 255, 255, 255], 1: [0, 134, 214, 255]},
                settings={},
                color_mode="4-Color",
            )

    def test_writer_add_mesh_rejects_empty_mesh(self, tmp_path):
        writer = BambuStudio3MFWriter(str(tmp_path / "x.3mf"), settings={}, color_mode="4-Color")
        empty = trimesh.Trimesh(vertices=np.zeros((0, 3)), faces=np.zeros((0, 3), dtype=np.int64))
        with pytest.raises(ValueError, match="empty geometry"):
            writer.add_mesh(empty, "White", (255, 255, 255))
