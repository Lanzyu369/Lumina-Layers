import logging
from pathlib import Path

import numpy as np

from core.converter import (
    _compute_connected_region_mask_4n,
    _recommend_lut_colors_by_rgb,
)
from core.pipeline import pipeline_utils

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_connected_region_4n_splits_diagonal_islands():
    q = np.array([
        [[255, 0, 0], [0, 0, 0], [255, 0, 0]],
        [[0, 0, 0], [255, 0, 0], [0, 0, 0]],
        [[255, 0, 0], [0, 0, 0], [255, 0, 0]],
    ], dtype=np.uint8)
    solid = np.ones((3, 3), dtype=bool)

    mask = _compute_connected_region_mask_4n(q, solid, 1, 1)

    assert mask.sum() == 1
    assert mask[1, 1]


def test_recommend_lut_colors_returns_top_k_sorted():
    lut = [
        {"color": (255, 0, 0), "hex": "#ff0000"},
        {"color": (250, 10, 10), "hex": "#fa0a0a"},
        {"color": (0, 255, 0), "hex": "#00ff00"},
    ]

    rec = _recommend_lut_colors_by_rgb((254, 2, 2), lut, top_k=2)

    assert len(rec) == 2
    assert rec[0]["hex"] == "#ff0000"


def test_generate_preview_cache_contract_requires_quantized_image_key():
    from core.converter import _ensure_quantized_image_in_cache

    cache = {"matched_rgb": np.zeros((2, 2, 3), dtype=np.uint8)}
    out = _ensure_quantized_image_in_cache(cache)

    assert "quantized_image" in out
    assert out["quantized_image"].shape == (2, 2, 3)


def test_preview_click_records_region_and_dual_hex():
    from core.converter import _build_selection_meta

    q_rgb = (10, 20, 30)
    m_rgb = (40, 50, 60)
    meta = _build_selection_meta(q_rgb, m_rgb, scope="region")

    assert meta["selected_quantized_hex"] == "#0a141e"
    assert meta["selected_matched_hex"] == "#28323c"
    assert meta["selection_scope"] == "region"


def test_highlight_uses_region_mask_when_present():
    from core.converter import _resolve_highlight_mask

    color_match = np.array([[True, True], [False, True]])
    region = np.array([[False, True], [False, False]])
    solid = np.array([[True, True], [True, True]])

    mask = _resolve_highlight_mask(color_match, solid, region_mask=region, scope="region")

    assert np.array_equal(mask, region)


def test_apply_region_replacement_only_changes_masked_pixels():
    from core.converter import _apply_region_replacement

    img = np.array([
        [[10, 10, 10], [10, 10, 10]],
        [[10, 10, 10], [10, 10, 10]],
    ], dtype=np.uint8)
    mask = np.array([[True, False], [False, False]])

    out = _apply_region_replacement(img, mask, (255, 0, 0))

    assert tuple(out[0, 0]) == (255, 0, 0)
    assert tuple(out[0, 1]) == (10, 10, 10)


def test_dual_recommendation_returns_two_groups_of_ten_or_less():
    from core.converter import _build_dual_recommendations

    lut = [{"color": (i, i, i), "hex": f"#{i:02x}{i:02x}{i:02x}"} for i in range(32)]
    rec = _build_dual_recommendations((10, 10, 10), (20, 20, 20), lut, top_k=10)

    assert set(rec.keys()) == {"by_quantized", "by_matched"}
    assert len(rec["by_quantized"]) == 10
    assert len(rec["by_matched"]) == 10


def test_resolve_click_selection_hexes_prefers_matched_for_display():
    from core.converter import _resolve_click_selection_hexes

    cache = {
        "selected_quantized_hex": "#112233",
        "selected_matched_hex": "#445566",
    }

    display_hex, state_hex = _resolve_click_selection_hexes(cache, "#112233")

    assert display_hex == "#445566"
    assert state_hex == "#112233"


def test_extract_lut_available_colors_logs_single_info_event(tmp_path, caplog):
    lut_path = tmp_path / "sample_lut.npy"
    np.save(
        lut_path,
        np.array(
            [
                [[255, 0, 0], [0, 255, 0]],
                [[255, 0, 0], [0, 0, 255]],
            ],
            dtype=np.uint8,
        ),
    )

    target_logger = pipeline_utils.log
    target_logger.addHandler(caplog.handler)
    caplog.set_level(logging.DEBUG, logger=target_logger.name)
    try:
        colors = pipeline_utils.extract_lut_available_colors(str(lut_path))
    finally:
        target_logger.removeHandler(caplog.handler)

    events = [getattr(record, "event", None) for record in caplog.records]
    assert {entry["hex"] for entry in colors} == {"#0000ff", "#00ff00", "#ff0000"}
    assert events.count("lut_colors_loading") == 1
    assert events.count("lut_colors_loaded") == 1
    assert "lut_colors_extracted" not in events

    info_events = [
        getattr(record, "event", None)
        for record in caplog.records
        if record.levelno == logging.INFO
    ]
    assert info_events == ["lut_colors_loaded"]


def test_lut_colors_loaded_omits_unique_count_when_no_duplicates(tmp_path, caplog):
    """When LUT entries are all unique, lut_colors_loaded must not carry unique_count."""
    lut_path = tmp_path / "no_dupes.npy"
    rgb = np.array([[0, 0, 0], [128, 128, 128], [255, 255, 255]], dtype=np.uint8)
    np.save(lut_path, rgb)

    target_logger = pipeline_utils.log
    target_logger.addHandler(caplog.handler)
    caplog.set_level(logging.INFO, logger=target_logger.name)
    try:
        pipeline_utils.extract_lut_available_colors(str(lut_path))
    finally:
        target_logger.removeHandler(caplog.handler)

    info_records = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "lut_colors_loaded"
    ]
    assert len(info_records) == 1
    record = info_records[0]
    assert getattr(record, "color_count") == 3
    assert not hasattr(record, "unique_count")


def test_lut_colors_loaded_includes_unique_count_when_duplicates_present(tmp_path, caplog):
    """When the LUT contains duplicates, both color_count and unique_count must appear."""
    lut_path = tmp_path / "with_dupes.npy"
    rgb = np.array(
        [[0, 0, 0], [0, 0, 0], [128, 128, 128], [255, 255, 255], [255, 255, 255]],
        dtype=np.uint8,
    )
    np.save(lut_path, rgb)

    target_logger = pipeline_utils.log
    target_logger.addHandler(caplog.handler)
    caplog.set_level(logging.INFO, logger=target_logger.name)
    try:
        pipeline_utils.extract_lut_available_colors(str(lut_path))
    finally:
        target_logger.removeHandler(caplog.handler)

    info_records = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "lut_colors_loaded"
    ]
    assert len(info_records) == 1
    record = info_records[0]
    assert getattr(record, "color_count") == 5
    assert getattr(record, "unique_count") == 3

