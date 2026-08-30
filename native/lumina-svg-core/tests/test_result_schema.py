"""ABI-level result schema and NumPy lifetime contracts."""

from __future__ import annotations

import gc
from pathlib import Path

import numpy as np
import pytest

import lumina_svg_core


FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_result_buffers_are_typed_read_only_and_keep_owner_alive() -> None:
    result = lumina_svg_core.analyze_svg(
        FIXTURES / "basic_fill_stroke.svg",
        target_width_mm=20.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.schema_version == 1
    visible = result.visible
    coordinates = visible.coordinates
    ring_offsets = visible.ring_offsets
    polygon_offsets = visible.polygon_offsets
    geometry_offsets = visible.geometry_offsets
    rgba = visible.rgba
    draw_indices = visible.draw_indices
    source_indices = visible.source_indices
    source_kinds = visible.source_kinds
    hole_parent = visible.hole_parent

    del visible
    del result
    gc.collect()

    assert coordinates.dtype == np.dtype(np.int64)
    assert ring_offsets.dtype == np.dtype(np.uint64)
    assert polygon_offsets.dtype == np.dtype(np.uint64)
    assert geometry_offsets.dtype == np.dtype(np.uint64)
    assert rgba.dtype == np.dtype(np.uint8)
    assert draw_indices.dtype == np.dtype(np.int32)
    assert source_indices.dtype == np.dtype(np.int32)
    assert source_kinds.dtype == np.dtype(np.int32)
    assert hole_parent.dtype == np.dtype(np.int64)

    for array in (
        coordinates,
        ring_offsets,
        polygon_offsets,
        geometry_offsets,
        rgba,
        draw_indices,
        source_indices,
        source_kinds,
        hole_parent,
    ):
        assert not array.flags.writeable

    assert coordinates.ndim == 2
    assert coordinates.shape[1] == 2
    assert ring_offsets[0] == 0
    assert ring_offsets[-1] == len(coordinates)
    assert polygon_offsets[0] == 0
    assert polygon_offsets[-1] == len(ring_offsets) - 1
    assert geometry_offsets[0] == 0
    assert geometry_offsets[-1] == len(polygon_offsets) - 1
    for start, end in zip(ring_offsets[:-1], ring_offsets[1:], strict=True):
        assert np.array_equal(coordinates[start], coordinates[end - 1])


def test_unsupported_result_has_canonical_empty_collections() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 10 10'><text>x</text></svg>",
        target_width_mm=20.0,
        tolerance_mm=0.02,
    )

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_text"
    for collection in (result.raw, result.visible, result.silhouette):
        assert collection.coordinates.shape == (0, 2)
        assert collection.ring_offsets.tolist() == [0]
        assert collection.polygon_offsets.tolist() == [0]
        assert collection.geometry_offsets.tolist() == [0]
        assert collection.geometry_count == 0
        assert collection.component_count == 0
        assert collection.hole_count == 0


@pytest.mark.parametrize(
    ("target_width_mm", "tolerance_mm"),
    [(0.0, 0.02), (-1.0, 0.02), (20.0, 0.0), (20.0, float("nan"))],
)
def test_invalid_physical_parameters_fail_deterministically(
    target_width_mm: float,
    tolerance_mm: float,
) -> None:
    result = lumina_svg_core.analyze_svg(
        FIXTURES / "basic_fill_stroke.svg",
        target_width_mm=target_width_mm,
        tolerance_mm=tolerance_mm,
    )

    assert result.status == "invalid"
    assert result.reason_code == "invalid_physical_parameters"
    assert result.visible.geometry_count == 0
