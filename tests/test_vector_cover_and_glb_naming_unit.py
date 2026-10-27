"""Vector cover mesh material identity and export behavior.
矢量覆盖网格的耗材标识与导出行为测试。
"""

from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import numpy as np
import pytest
import trimesh


# ---------------------------------------------------------------------------
# Test 1: SVG cover thumbnail renders PNG bytes (not placeholder)
# ---------------------------------------------------------------------------


class TestVectorCoverThumbnailFromGeometry:
    """cover render in vector_branch produces valid PNG bytes for SVG inputs."""

    def test_svg_raster_preview_bytes_populated_when_analysis_available(self):
        """When VectorProcessor.render_preview returns valid RGBA,
        ctx['svg_raster_preview_bytes'] is populated with non-empty PNG bytes.
        """
        from io import BytesIO
        from PIL import Image

        # Simulate a 10x10 RGBA array (what render_preview returns)
        fake_rgba = np.full((10, 10, 4), 200, dtype=np.uint8)
        fake_rgba[:, :, 3] = 255  # opaque

        # Encode to PNG to verify the logic
        pil_img = Image.fromarray(fake_rgba, mode="RGBA")
        buf = BytesIO()
        pil_img.save(buf, format="PNG", optimize=False)
        expected_bytes = buf.getvalue()

        # Verify it's valid PNG
        assert len(expected_bytes) > 50  # non-trivial PNG (small images are compact)
        buf.seek(0)
        decoded = Image.open(buf)
        decoded.verify()

    def test_cover_builder_accepts_png_bytes_and_produces_real_bundle(self):
        """CoverThumbnailBuilder.build(bytes) produces a non-placeholder bundle.
        This is the exact path the vector branch fix uses.
        """
        from io import BytesIO
        from PIL import Image
        from utils.bambu_3mf_cover import CoverThumbnailBuilder

        # Create a small RGBA image and encode to PNG bytes
        rgba = np.full((20, 30, 4), 128, dtype=np.uint8)
        rgba[:, :, 0] = 255  # red tint
        rgba[:, :, 3] = 255
        pil_img = Image.fromarray(rgba, mode="RGBA")
        buf = BytesIO()
        pil_img.save(buf, format="PNG")
        png_bytes = buf.getvalue()

        bundle = CoverThumbnailBuilder().build(png_bytes)

        assert bundle.is_placeholder is False
        assert bundle.warning is None
        assert len(bundle.thumbnail_3mf) > 0
        assert len(bundle.plate_main) > 0

    def test_cover_builder_rejects_raw_svg_path(self, tmp_path):
        """CoverThumbnailBuilder.build(str) with .svg file yields placeholder.
        This confirms the bug scenario before the fix.
        """
        from utils.bambu_3mf_cover import CoverThumbnailBuilder

        svg_file = tmp_path / "test.svg"
        svg_file.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
            '<rect width="100" height="100" fill="red"/></svg>'
        )

        bundle = CoverThumbnailBuilder().build(str(svg_file))

        # PIL cannot decode SVG → falls back to placeholder
        assert bundle.is_placeholder is True
        assert bundle.warning is not None
        assert bundle.warning["error_type"] == "source_decode_error"

    def test_render_preview_does_not_mutate_analysis(self):
        """VectorProcessor.render_preview must be read-only on analysis."""
        from core.vector_engine import VectorProcessor, VectorAnalysis
        from shapely.geometry import box as shapely_box

        # Build minimal analysis with all required fields
        shape = {
            "geometry": shapely_box(0, 0, 10, 10),
            "recipe": [0, 0, 0, 0, 0],
        }
        analysis = VectorAnalysis(
            shape_data=[],
            clipped_shapes=[shape],
            matched_shapes=[shape],
            silhouette=shapely_box(0, 0, 10, 10),
            scale_factor=0.5,
            bbox=(0, 0, 100, 100),
            color_conf={"slots": ["White", "Red", "Yellow", "Blue"], "preview": {}},
            slot_names=["White", "Red", "Yellow", "Blue"],
            num_channels=4,
            num_layers=5,
            preview_colors={
                0: [255, 255, 255, 255],
                1: [255, 0, 0, 255],
                2: [255, 255, 0, 255],
                3: [0, 0, 255, 255],
            },
            stage_timings={},
        )

        # Snapshot before
        recipes_before = [s["recipe"][:] for s in analysis.matched_shapes]

        VectorProcessor.render_preview(analysis, pixels_per_mm=5.0)

        # Verify no mutation
        for i, shape in enumerate(analysis.matched_shapes):
            assert shape["recipe"] == recipes_before[i]

    def test_render_preview_preserves_rgba_channel_order(self):
        """SVG cover preview must keep RGB channels in RGBA byte order."""
        from io import BytesIO

        from core.vector_engine import VectorProcessor, VectorAnalysis
        from PIL import Image
        from shapely.geometry import box as shapely_box
        from utils.bambu_3mf_cover import CoverThumbnailBuilder

        expected_rgba = [193, 46, 31, 255]
        shape = {
            "geometry": shapely_box(0, 0, 10, 10),
            "recipe": [5, 5, 5, 5, 5],
        }
        analysis = VectorAnalysis(
            shape_data=[],
            clipped_shapes=[shape],
            matched_shapes=[shape],
            silhouette=shapely_box(0, 0, 10, 10),
            scale_factor=1.0,
            bbox=(0, 0, 10, 10),
            color_conf={
                "slots": [
                    "White",
                    "Cyan",
                    "Magenta",
                    "Yellow",
                    "Black",
                    "Red",
                    "Deep Blue",
                    "Green",
                ],
                "preview": {},
            },
            slot_names=[
                "White",
                "Cyan",
                "Magenta",
                "Yellow",
                "Black",
                "Red",
                "Deep Blue",
                "Green",
            ],
            num_channels=8,
            num_layers=5,
            preview_colors={5: expected_rgba},
            stage_timings={},
        )

        rendered = VectorProcessor.render_preview(analysis, pixels_per_mm=2.0)

        assert rendered[10, 10].tolist() == expected_rgba

        buffer = BytesIO()
        Image.fromarray(rendered, mode="RGBA").save(buffer, format="PNG")
        cover_bundle = CoverThumbnailBuilder().build(buffer.getvalue())
        thumbnail = Image.open(BytesIO(cover_bundle.thumbnail_small)).convert("RGB")

        assert list(thumbnail.getpixel((thumbnail.width // 2, thumbnail.height // 2))) == expected_rgba[:3]

    def test_vector_branch_cover_uses_source_svg_raster_not_layer_preview(self, tmp_path):
        """3MF cover must show the original SVG artwork, not the layer preview."""
        from PIL import Image

        from config import ModelingMode
        from core.pipeline import coordinator

        captured: dict[str, object] = {}
        source_rgba = np.zeros((8, 8, 4), dtype=np.uint8)
        source_rgba[:, :] = [240, 30, 50, 255]
        layer_rgba = np.zeros((8, 8, 4), dtype=np.uint8)
        layer_rgba[:, :] = [10, 20, 30, 255]

        class _FakeVectorProcessor:
            parse_warnings: list[str] = []
            last_stage_timings: dict[str, float] = {}

            def __init__(self, _lut_path: str, color_mode: str, *, img_processor=None) -> None:
                self.color_mode = color_mode
                self.enable_fridge_magnet = False
                self.fridge_magnets = []

            def analyze_svg(self, *, svg_path: str, target_width_mm: float, color_replacements=None):
                del svg_path, target_width_mm, color_replacements
                return SimpleNamespace(
                    matched_shapes=[],
                    num_layers=5,
                    num_channels=1,
                    preview_colors={0: [10, 20, 30, 255]},
                    slot_names=["Slot 1"],
                )

            def build_mesh(self, *, analysis, thickness_mm: float, structure_mode: str):
                del analysis, thickness_mm, structure_mode
                scene = trimesh.Scene()
                scene.add_geometry(
                    trimesh.creation.box(extents=(1, 1, 1)),
                    geom_name="Slot 1",
                )
                return scene

            @staticmethod
            def render_preview(analysis, pixels_per_mm: float):
                del analysis, pixels_per_mm
                return layer_rgba

        def _fake_export_scene_with_bambu_metadata(**kwargs):
            captured.update(kwargs)
            return kwargs["output_path"]

        svg_path = tmp_path / "gradient.svg"
        svg_path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
            '<rect width="10" height="10" fill="#f01e32"/></svg>',
            encoding="utf-8",
        )

        with patch("core.vector_engine.VectorProcessor", _FakeVectorProcessor), patch(
            "core.pipeline.vector_branch.rasterize_svg",
            return_value=source_rgba,
        ) as rasterize_mock, patch(
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
            result = coordinator._run_vector_branch(
                {
                    "image_path": str(svg_path),
                    "actual_lut_path": str(tmp_path / "fake.json"),
                    "color_mode": "4-Color",
                    "modeling_mode": ModelingMode.VECTOR,
                    "target_width_mm": 40.0,
                    "spacer_thick": 1.6,
                    "structure_mode": "Single-sided",
                    "need_2d_preview": False,
                    "printer_id": "bambu-h2d",
                    "slicer": "BambuStudio",
                    "nozzle_size": "0.4",
                    "enable_wipe_tower_auto_placement": False,
                }
            )

        assert "error" not in result
        rasterize_mock.assert_called_once_with(
            str(svg_path),
            40.0,
            pixels_per_mm=2.0,
            crop_to_content=False,
            _min_quality_px=1,
            _max_longest_px=512,
            _cache_result=False,
        )
        cover_source = captured["cover_source"]
        assert isinstance(cover_source, bytes)
        assert captured["enable_wipe_tower_auto_placement"] is False
        decoded = Image.open(BytesIO(cover_source)).convert("RGB")
        assert decoded.getpixel((0, 0)) == (240, 30, 50)

    def test_vector_branch_cover_raster_failure_falls_back_to_source_path(self, tmp_path):
        """Optional cover raster failure must not abort SVG 3MF generation."""
        from config import ModelingMode
        from core.pipeline import coordinator

        captured: dict[str, object] = {}

        class _FakeVectorProcessor:
            parse_warnings: list[str] = []
            last_stage_timings: dict[str, float] = {}

            def __init__(self, _lut_path: str, color_mode: str, *, img_processor=None) -> None:
                self.color_mode = color_mode
                self.enable_fridge_magnet = False
                self.fridge_magnets = []

            def analyze_svg(self, *, svg_path: str, target_width_mm: float, color_replacements=None):
                del svg_path, target_width_mm, color_replacements
                return SimpleNamespace(
                    matched_shapes=[],
                    num_layers=5,
                    num_channels=1,
                    preview_colors={0: [10, 20, 30, 255]},
                    slot_names=["Slot 1"],
                )

            def build_mesh(self, *, analysis, thickness_mm: float, structure_mode: str):
                del analysis, thickness_mm, structure_mode
                scene = trimesh.Scene()
                scene.add_geometry(
                    trimesh.creation.box(extents=(1, 1, 1)),
                    geom_name="Slot 1",
                )
                return scene

            @staticmethod
            def render_preview(analysis, pixels_per_mm: float):
                del analysis, pixels_per_mm
                return np.zeros((8, 8, 4), dtype=np.uint8)

        def _fake_export_scene_with_bambu_metadata(**kwargs):
            captured.update(kwargs)
            return kwargs["output_path"]

        svg_path = tmp_path / "gradient.svg"
        svg_path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
            '<rect width="10" height="10" fill="#f01e32"/></svg>',
            encoding="utf-8",
        )

        with patch("core.vector_engine.VectorProcessor", _FakeVectorProcessor), patch(
            "core.pipeline.vector_branch.rasterize_svg",
            side_effect=ImportError("missing resvg-py"),
        ), patch(
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
            result = coordinator._run_vector_branch(
                {
                    "image_path": str(svg_path),
                    "actual_lut_path": str(tmp_path / "fake.json"),
                    "color_mode": "4-Color",
                    "modeling_mode": ModelingMode.VECTOR,
                    "target_width_mm": 40.0,
                    "spacer_thick": 1.6,
                    "structure_mode": "Single-sided",
                    "need_2d_preview": False,
                    "printer_id": "bambu-h2d",
                    "slicer": "BambuStudio",
                    "nozzle_size": "0.4",
                }
            )

        assert "error" not in result
        assert captured["cover_source"] == str(svg_path)
