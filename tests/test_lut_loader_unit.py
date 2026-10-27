"""Unit tests for LUT runtime loading helpers."""

from __future__ import annotations

import os

import numpy as np


def test_load_lut_reuses_runtime_cache_for_unchanged_file(tmp_path, monkeypatch):
    """Repeated identical LUT loads should avoid reparsing the source file."""
    from core.pipeline.processing_ops import lut_loader

    lut_path = tmp_path / "tiny_merged.npy"
    np.save(
        lut_path,
        np.array(
            [
                [255, 255, 255],
                [255, 0, 0],
                [0, 255, 0],
                [0, 0, 255],
            ],
            dtype=np.uint8,
        ),
    )
    original_loader = lut_loader.LUTManager.load_lut_with_metadata
    calls = {"count": 0}

    def _counting_loader(path: str):
        calls["count"] += 1
        return original_loader(path)

    monkeypatch.setattr(lut_loader.LUTManager, "load_lut_with_metadata", _counting_loader)

    first = lut_loader.load_lut(str(lut_path), "Merged")
    second = lut_loader.load_lut(str(lut_path), "Merged")

    assert calls["count"] == 1
    assert first is not second
    np.testing.assert_array_equal(first["lut_rgb"], second["lut_rgb"])
    np.testing.assert_array_equal(first["ref_stacks"], second["ref_stacks"])


def test_load_lut_runtime_cache_invalidates_when_file_changes(tmp_path, monkeypatch):
    """A changed LUT file at the same path must be parsed again."""
    from core.pipeline.processing_ops import lut_loader

    lut_path = tmp_path / "bw.npy"
    first_rgb = np.zeros((32, 3), dtype=np.uint8)
    second_rgb = first_rgb.copy()
    second_rgb[0] = [255, 128, 0]
    np.save(lut_path, first_rgb)
    first_mtime_ns = os.stat(lut_path).st_mtime_ns

    original_loader = lut_loader.LUTManager.load_lut_with_metadata
    calls = {"count": 0}

    def _counting_loader(path: str):
        calls["count"] += 1
        return original_loader(path)

    monkeypatch.setattr(lut_loader.LUTManager, "load_lut_with_metadata", _counting_loader)

    first = lut_loader.load_lut(str(lut_path), "BW")
    np.save(lut_path, second_rgb)
    changed_mtime_ns = first_mtime_ns + 1_000_000_000
    os.utime(lut_path, ns=(changed_mtime_ns, changed_mtime_ns))
    second = lut_loader.load_lut(str(lut_path), "BW")

    assert calls["count"] == 2
    np.testing.assert_array_equal(first["lut_rgb"][0], [0, 0, 0])
    np.testing.assert_array_equal(second["lut_rgb"][0], [255, 128, 0])
