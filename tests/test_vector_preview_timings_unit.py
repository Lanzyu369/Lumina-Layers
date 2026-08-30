from __future__ import annotations

from types import SimpleNamespace
import logging
from unittest.mock import patch

import numpy as np
from shapely.geometry import box


def test_log_vector_preview_timings_emits_stage_breakdown(caplog) -> None:
    from core.pipeline.vector_branch import _log_vector_preview_timings

    timings = {
        "material_img_processor_s": 0.1,
        "processor_init_s": 0.2,
        "parse_s": 1.0,
        "occlusion_s": 2.0,
        "color_match_s": 3.0,
        "build_preview_cache_s": 4.0,
        "bed_rendering_s": 0.5,
        "vector_preview_total_s": 10.0,
        "material_parallelism_limit": "requested",
        "material_parallelism_demand_fallback": False,
    }
    ctx = {
        "image_path": "example.svg",
        "modeling_mode": "vector",
        "color_mode": "Material Archive",
        "target_width_mm": 60.0,
        "material_source": "material_archive",
        "actual_lut_path": "__material_archive__",
        "grid_resolution": 2048,
    }
    analysis = SimpleNamespace(
        shape_data=[{"color": (255, 0, 0)}, {"color": (0, 0, 255)}],
        clipped_shapes=[{"color": (255, 0, 0)}],
        matched_shapes=[{"color": (255, 0, 0)}],
        num_layers=5,
        num_channels=8,
    )
    raster_cache = {
        "target_w": 100,
        "target_h": 50,
        "mask_solid": np.array([[True, False], [True, True]], dtype=bool),
        "material_matrix": np.zeros((2, 2, 5), dtype=np.int16),
    }

    target_logger = logging.getLogger("lumina.core.pipeline.coordinator")
    target_logger.addHandler(caplog.handler)
    caplog.set_level(logging.INFO, logger=target_logger.name)
    try:
        _log_vector_preview_timings(timings, ctx, analysis, raster_cache)
    finally:
        target_logger.removeHandler(caplog.handler)

    records = [record for record in caplog.records if getattr(record, "event", None) == "vector_preview_timings"]
    assert len(records) == 1
    record = records[0]
    assert record.duration_ms == 10000.0
    assert record.timings["build_preview_cache_s"] == 4.0
    assert record.timings["occlusion_s"] == 2.0
    assert record.timings["material_parallelism_limit"] == "requested"
    assert record.timings["material_parallelism_demand_fallback"] is False
    assert record.is_material_archive is True
    assert record.modeling_mode == "vector"
    assert record.material_source == "material_archive"
    assert record.material_count == 8
    assert record.layer_count == 5
    assert record.unique_fill_count == 1
    assert record.grid_resolution == 2048
    assert record.shape_count == 2
    assert record.clipped_shape_count == 1
    assert record.matched_shape_count == 1
    assert record.preview_width_px == 100
    assert record.preview_height_px == 50
    assert record.solid_pixel_count == 3
    assert record.material_matrix_shape == [2, 2, 5]
    assert not hasattr(record, "image_path")
    assert not hasattr(record, "actual_lut_path")


def test_vector_preview_branch_preserves_backing_mask_in_cache() -> None:
    from core.pipeline.vector_branch import _run_vector_preview_branch
    from core.vector_engine import VectorAnalysis

    visible_shape = box(4, 4, 16, 16)
    full_backing = box(0, 0, 20, 20)
    analysis = VectorAnalysis(
        shape_data=[],
        clipped_shapes=[
            {"geometry": visible_shape, "color": (255, 0, 0), "draw_order": 0}
        ],
        matched_shapes=[
            {
                "geometry": visible_shape,
                "recipe": [1, 1, 1, 1, 1],
                "color": (255, 0, 0),
                "matched_rgb": (255, 0, 0),
            }
        ],
        silhouette=visible_shape,
        scale_factor=1.0,
        bbox=(0.0, 0.0, 20.0, 20.0),
        color_conf={},
        slot_names=["White", "Red"],
        num_channels=2,
        num_layers=5,
        preview_colors={
            0: [255, 255, 255, 255],
            1: [255, 0, 0, 255],
        },
        stage_timings={
            "native_svg_s": 0.1,
            "geometry_backend": "native",
            "native_cache_hit": False,
        },
        image_vectorizer_bounds=full_backing,
    )
    fake_processor = SimpleNamespace(analyze_svg=lambda **_kwargs: analysis)
    ctx = {
        "image_path": "example.svg",
        "color_mode": "8-Color Max",
        "target_width_mm": 20.0,
        "actual_lut_path": "fake.npy",
        "modeling_mode": "vector",
        "color_layers": 7,
        "layer_height_mm": 0.12,
        "quantize_colors": 64,
        "enable_cleanup": False,
        "hue_weight": 0.4,
        "chroma_gate": 9.0,
        "use_lut_constrained": True,
        "auto_dynamic_range": True,
        "model_enable": True,
        "model_only": False,
        "model_threshold": 0.25,
        "model_margin": 0.05,
        "svg_pixels_per_mm": 8.0,
        "material_source": "lut",
        "backing_color_id": 0,
        "is_dark": True,
        "lut_metadata": None,
    }

    with (
        patch(
            "core.pipeline.vector_branch._build_vector_processor",
            return_value=fake_processor,
        ),
        patch("core.pipeline.vector_branch.p06_bed_rendering.run", side_effect=lambda value: value),
        patch("core.pipeline.vector_branch.extract_color_palette", return_value=[]),
    ):
        result = _run_vector_preview_branch(ctx)

    assert "error" not in result
    assert result["vector_timing"]["vector_preview_total_s"] >= 0.0
    assert result["vector_timing"]["geometry_backend"] == "native"
    assert result["vector_timing"]["native_cache_hit"] is False
    assert "backing_mask" in result["cache"]
    assert result["cache"]["backing_mask"].shape == result["cache"]["mask_solid"].shape
    assert np.count_nonzero(
        result["cache"]["backing_mask"] & ~result["cache"]["mask_solid"]
    ) > 0
    assert {
        key: result["cache"].get(key)
        for key in (
            "target_width_mm",
            "color_mode",
            "modeling_mode",
            "color_layers",
            "layer_height_mm",
            "quantize_colors",
            "enable_cleanup",
            "hue_weight",
            "chroma_gate",
            "use_lut_constrained",
            "auto_dynamic_range",
            "model_enable",
            "model_only",
            "model_threshold",
            "model_margin",
            "svg_pixels_per_mm",
            "material_source",
        )
    } == {
        "target_width_mm": 20.0,
        "color_mode": "8-Color Max",
        "modeling_mode": "vector",
        "color_layers": 7,
        "layer_height_mm": 0.12,
        "quantize_colors": 64,
        "enable_cleanup": False,
        "hue_weight": 0.4,
        "chroma_gate": 9.0,
        "use_lut_constrained": True,
        "auto_dynamic_range": True,
        "model_enable": True,
        "model_only": False,
        "model_threshold": 0.25,
        "model_margin": 0.05,
        "svg_pixels_per_mm": 8.0,
        "material_source": "lut",
    }


def test_vector_preview_replacements_keep_pristine_height_and_recipe() -> None:
    """Native SVG re-preview applies display remaps after stable identity capture."""
    from core.pipeline.vector_branch import _run_vector_preview_branch
    from core.vector_engine import VectorAnalysis

    visible_shape = box(0, 0, 10, 10)
    analysis = VectorAnalysis(
        shape_data=[],
        clipped_shapes=[
            {"geometry": visible_shape, "color": (255, 0, 0), "draw_order": 0}
        ],
        matched_shapes=[
            {
                "geometry": visible_shape,
                "recipe": [1, 1, 1, 1, 1],
                "original_recipe": [0, 0, 0, 0, 0],
                "color": (255, 0, 0),
                "matched_rgb": (0, 0, 255),
                "height_identity_rgb": (255, 0, 0),
            }
        ],
        silhouette=visible_shape,
        scale_factor=1.0,
        bbox=(0.0, 0.0, 10.0, 10.0),
        color_conf={},
        slot_names=["Red", "Blue"],
        num_channels=2,
        num_layers=5,
        preview_colors={
            0: [255, 0, 0, 255],
            1: [0, 0, 255, 255],
        },
        stage_timings={},
    )
    captured: dict = {}

    def analyze_svg(**kwargs):
        captured.update(kwargs)
        return analysis

    ctx = {
        "image_path": "replacement.svg",
        "color_mode": "4-Color RYBW",
        "target_width_mm": 10.0,
        "actual_lut_path": "fake.npy",
        "modeling_mode": "vector",
        "color_layers": 5,
        "layer_height_mm": 0.08,
        "quantize_colors": 64,
        "enable_cleanup": False,
        "material_source": "lut",
        "backing_color_id": 0,
        "is_dark": True,
        "replacement_regions": [
            {
                "matched_hex": "#ff0000",
                "replacement_hex": "#0000ff",
            }
        ],
    }

    with (
        patch(
            "core.pipeline.vector_branch._build_vector_processor",
            return_value=SimpleNamespace(analyze_svg=analyze_svg),
        ),
        patch(
            "core.pipeline.vector_branch.p06_bed_rendering.run",
            side_effect=lambda value: value,
        ),
        patch("core.pipeline.vector_branch.extract_color_palette", return_value=[]),
    ):
        result = _run_vector_preview_branch(ctx)

    assert "error" not in result
    assert captured["color_replacements"] == ctx["replacement_regions"]
    cache = result["cache"]
    solid = cache["mask_solid"]
    assert np.all(cache["matched_rgb"][solid] == [0, 0, 255])
    assert np.all(cache["original_matched_rgb"][solid] == [255, 0, 0])
    assert cache["original_matched_rgb"] is cache["height_identity_rgb"]
    assert np.all(cache["material_matrix"][solid] == 1)
    assert np.all(cache["original_material_matrix"][solid] == 0)
