"""Deterministic parallel normalization contracts."""

from __future__ import annotations

from typing import Any

import numpy as np

import lumina_svg_core


def _geometry_snapshot(collection: Any) -> tuple[Any, ...]:
    array_names = (
        "coordinates",
        "ring_offsets",
        "polygon_offsets",
        "geometry_offsets",
        "hole_parent",
        "rgba",
        "rgba_f64",
        "draw_indices",
        "source_indices",
        "source_kinds",
        "contributor_offsets",
        "contributor_draw_indices",
        "contributor_source_indices",
        "contributor_source_kinds",
        "contributor_weights",
    )
    return tuple(
        (array.dtype.str, array.shape, array.tobytes())
        for name in array_names
        for array in (np.asarray(getattr(collection, name)),)
    )


def _result_snapshot(result: Any) -> tuple[Any, ...]:
    fragments = result.unprintable_fragments
    return (
        result.status,
        result.reason_code,
        result.schema_version,
        result.bbox,
        result.viewport_bounds,
        result.scale_factor,
        result.grid_to_source_unit,
        result.max_flattening_error_mm,
        result.max_quantization_error_mm,
        result.input_paint_count,
        _geometry_snapshot(result.raw),
        _geometry_snapshot(result.visible),
        _geometry_snapshot(result.silhouette),
        fragments.reason_codes,
        np.asarray(fragments.reason_ids).tobytes(),
        np.asarray(fragments.rgba).tobytes(),
        np.asarray(fragments.rgba_f64).tobytes(),
        np.asarray(fragments.draw_indices).tobytes(),
        np.asarray(fragments.source_indices).tobytes(),
        np.asarray(fragments.source_kinds).tobytes(),
        np.asarray(fragments.subpath_indices).tobytes(),
    )


def _parallel_fixture_svg() -> str:
    paints: list[str] = []
    for index in range(32):
        x = 2 + (index % 8) * 14
        y = 2 + (index // 8) * 24
        red = (index * 47) % 256
        green = (index * 83) % 256
        blue = (index * 131) % 256
        paints.append(
            f"<path fill='rgb({red},{green},{blue})' fill-rule='evenodd' "
            f"d='M{x} {y}h12v18h-12z m3 4h6v8h-6z'/>"
        )
        paints.append(
            f"<path d='M{x} {y + 20}c3 -4 9 -4 12 0' fill='none' "
            f"stroke='rgb({blue},{red},{green})' stroke-width='1.5' "
            "stroke-linecap='round'/>"
        )
    return (
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 116 100'>"
        "<g>"
        + "".join(paints)
        + "</g></svg>"
    )


def test_parallel_replay_matches_forced_serial_output_byte_for_byte(
    monkeypatch,
) -> None:
    svg = _parallel_fixture_svg()

    monkeypatch.setenv("LUMINA_SVG_REPLAY_THREADS", "1")
    serial = lumina_svg_core.analyze_svg_svg(
        svg,
        target_width_mm=220.0,
        tolerance_mm=0.02,
    )

    monkeypatch.setenv("LUMINA_SVG_REPLAY_THREADS", "4")
    parallel = lumina_svg_core.analyze_svg_svg(
        svg,
        target_width_mm=220.0,
        tolerance_mm=0.02,
    )

    assert serial.status == parallel.status == "supported"
    assert serial.replay_worker_count == 1
    assert parallel.replay_worker_count == 4
    assert _result_snapshot(parallel) == _result_snapshot(serial)
