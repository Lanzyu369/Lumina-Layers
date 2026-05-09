from __future__ import annotations

from types import SimpleNamespace
import logging

import numpy as np


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
