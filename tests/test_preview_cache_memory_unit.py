import numpy as np

from api.preview_cache_memory import (
    build_preview_cache_memory_profile,
    should_log_preview_cache_memory_profile_at_info,
)


def test_build_preview_cache_memory_profile_summarizes_arrays() -> None:
    cache = {
        "matched_rgb": np.zeros((2, 3, 3), dtype=np.uint8),
        "material_matrix": np.ones((2, 3, 4), dtype=np.int16),
        "mask_solid": np.ones((2, 3), dtype=bool),
        "color_palette": [{"name": "white"}],
        "target_w": 3,
        "target_h": 2,
    }

    profile = build_preview_cache_memory_profile(
        cache,
        session_id="sid-1",
        modeling_mode="vector",
        cache_data_bytes=4096,
        process_rss_bytes=123456,
    )

    assert profile["event"] == "preview_cache_memory_profile"
    assert profile["session_id"] == "sid-1"
    assert profile["modeling_mode"] == "vector"
    assert profile["cache_data_bytes"] == 4096
    assert profile["process_rss_bytes"] == 123456
    assert profile["array_total_bytes"] == 72
    assert profile["array_count"] == 3
    assert profile["largest_arrays"][0] == {
        "field": "material_matrix",
        "shape": [2, 3, 4],
        "dtype": "int16",
        "nbytes": 48,
    }


def test_build_preview_cache_memory_profile_handles_missing_cache() -> None:
    profile = build_preview_cache_memory_profile(
        None,
        session_id="sid-2",
        modeling_mode="raster",
        cache_data_bytes=None,
        process_rss_bytes=None,
    )

    assert profile["array_total_bytes"] == 0
    assert profile["array_count"] == 0
    assert profile["largest_arrays"] == []


def test_preview_cache_memory_profile_info_flag(monkeypatch) -> None:
    monkeypatch.delenv("LUMINA_PREVIEW_CACHE_MEMORY_PROFILE_INFO", raising=False)
    assert should_log_preview_cache_memory_profile_at_info() is False

    monkeypatch.setenv("LUMINA_PREVIEW_CACHE_MEMORY_PROFILE_INFO", "1")
    assert should_log_preview_cache_memory_profile_at_info() is True

    monkeypatch.setenv("LUMINA_PREVIEW_CACHE_MEMORY_PROFILE_INFO", "true")
    assert should_log_preview_cache_memory_profile_at_info() is True

    monkeypatch.setenv("LUMINA_PREVIEW_CACHE_MEMORY_PROFILE_INFO", "0")
    assert should_log_preview_cache_memory_profile_at_info() is False
