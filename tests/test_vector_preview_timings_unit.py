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
    }
    ctx = {
        "image_path": "example.svg",
        "color_mode": "Material Archive",
        "target_width_mm": 60.0,
        "material_source": "material_archive",
        "actual_lut_path": "__material_archive__",
        "grid_resolution": 2048,
    }
    analysis = SimpleNamespace(
        shape_data=[object(), object()],
        clipped_shapes=[object()],
        matched_shapes=[object()],
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
    assert record.is_material_archive is True
    assert record.grid_resolution == 2048
    assert record.shape_count == 2
    assert record.clipped_shape_count == 1
    assert record.matched_shape_count == 1
    assert record.preview_width_px == 100
    assert record.preview_height_px == 50
    assert record.solid_pixel_count == 3
    assert record.material_matrix_shape == [2, 2, 5]


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
        stage_timings={},
        image_vectorizer_bounds=full_backing,
    )
    fake_processor = SimpleNamespace(analyze_svg=lambda **_kwargs: analysis)
    ctx = {
        "image_path": "example.svg",
        "color_mode": "8-Color Max",
        "target_width_mm": 20.0,
        "actual_lut_path": "fake.npy",
        "quantize_colors": 64,
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
    assert "backing_mask" in result["cache"]
    assert result["cache"]["backing_mask"].shape == result["cache"]["mask_solid"].shape
    assert np.count_nonzero(
        result["cache"]["backing_mask"] & ~result["cache"]["mask_solid"]
    ) > 0
