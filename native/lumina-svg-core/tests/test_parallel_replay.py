"""Deterministic parallel normalization contracts."""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

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


def _nested_parallel_fixture_svg() -> str:
    paints = "".join(
        (
            f"<path d='M{2 + index * 4} 2h3v16h-3z' "
            f"fill='rgb({20 + index * 20},40,{220 - index * 20})' "
            "fill-opacity='.8'/>"
        )
        for index in range(8)
    )
    return (
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 40 20'>"
        "<defs>"
        "<clipPath id='ring' clip-rule='evenodd'>"
        "<path d='M1 1H39V19H1Z M15 6H25V14H15Z'/>"
        "</clipPath>"
        "<clipPath id='inset' transform='translate(.5 .5)'>"
        "<rect width='39' height='19'/>"
        "</clipPath>"
        "</defs>"
        "<g opacity='.75' clip-path='url(#ring)' transform='translate(.25 0)'>"
        "<g opacity='.5' clip-path='url(#inset)'>"
        "<rect width='40' height='20' fill='#010203'/>"
        + paints
        + "<path d='M2 10L12 10' fill='#abcdef'/>"
        "<path d='M2 17H38' fill='none' "
        "stroke='#123456' stroke-opacity='.6' stroke-width='1.25'/>"
        "</g></g></svg>"
    )


def _analyze(svg: str) -> Any:
    return lumina_svg_core.analyze_svg_svg(
        svg,
        target_width_mm=220.0,
        tolerance_mm=0.02,
    )


def test_parallel_replay_matches_forced_serial_output_byte_for_byte(
    monkeypatch,
) -> None:
    svg = _parallel_fixture_svg()

    monkeypatch.setenv("LUMINA_SVG_REPLAY_THREADS", "1")
    serial = _analyze(svg)

    monkeypatch.setenv("LUMINA_SVG_REPLAY_THREADS", "4")
    parallel = _analyze(svg)

    assert serial.status == parallel.status == "supported"
    assert serial.replay_worker_count == 1
    assert parallel.replay_worker_count == 4
    assert _result_snapshot(parallel) == _result_snapshot(serial)


def test_parallel_replay_preserves_nested_parser_semantics(monkeypatch) -> None:
    svg = _nested_parallel_fixture_svg()

    monkeypatch.setenv("LUMINA_SVG_REPLAY_THREADS", "1")
    serial = _analyze(svg)

    monkeypatch.setenv("LUMINA_SVG_REPLAY_THREADS", "4")
    parallel = _analyze(svg)

    assert serial.status == parallel.status == "supported"
    assert serial.replay_worker_count == 1
    assert parallel.replay_worker_count == 4
    assert serial.raw.hole_count >= 1
    assert serial.unprintable_fragments.reason_codes == ("line_only",)
    assert _result_snapshot(parallel) == _result_snapshot(serial)


def test_small_auto_workload_stays_serial(monkeypatch) -> None:
    monkeypatch.delenv("LUMINA_SVG_REPLAY_THREADS", raising=False)

    result = _analyze(
        "<svg viewBox='0 0 10 10'>"
        "<rect width='10' height='10' fill='#123456'/>"
        "</svg>"
    )

    assert result.status == "supported"
    assert result.replay_worker_count == 1


def test_requested_worker_count_is_bounded_and_output_is_stable(
    monkeypatch,
) -> None:
    svg = _parallel_fixture_svg()

    monkeypatch.setenv("LUMINA_SVG_REPLAY_THREADS", "1")
    serial = _analyze(svg)

    monkeypatch.setenv("LUMINA_SVG_REPLAY_THREADS", "250000")
    bounded = _analyze(svg)

    assert bounded.status == "supported"
    assert 1 <= bounded.replay_worker_count <= 16
    assert _result_snapshot(bounded) == _result_snapshot(serial)


@pytest.mark.parametrize("failing_paint_index", [0, 3, 7])
def test_parallel_normalization_failure_replays_in_document_order(
    monkeypatch,
    failing_paint_index: int,
) -> None:
    paints = [
        f"<rect x='{index * 10}' width='8' height='10'/>"
        for index in range(7)
    ]
    # The normal viewport proves these commands pass the stroke sizing pass.
    # A large empty viewport changes only the final normalization grid; its
    # finite miter refinement then fails without generating extra geometry.
    paints.insert(
        failing_paint_index,
        "<path d='M10 10L20 10L10.603 13.42' fill='none' "
        "stroke='red' stroke-width='2' stroke-linejoin='miter' "
        "stroke-miterlimit='4'/>",
    )
    document = "<svg viewBox='0 0 {extent} {extent}'>" + "".join(paints) + "</svg>"
    normal_svg = document.format(extent="100")
    svg = document.format(extent="1e24")
    recorded = lumina_svg_core.record_paint_commands_svg(svg)
    normal_recorded = lumina_svg_core.record_paint_commands_svg(normal_svg)
    assert recorded.status == "supported"
    assert normal_recorded.status == "supported"
    assert len(recorded.commands) == 8
    for command, normal_command in zip(
        recorded.commands, normal_recorded.commands, strict=True,
    ):
        assert command.path_points == normal_command.path_points
        assert command.matrix == normal_command.matrix

    monkeypatch.setenv("LUMINA_SVG_REPLAY_THREADS", "4")
    normal = _analyze(normal_svg)
    assert normal.status == "supported"
    assert normal.replay_worker_count == 4
    assert normal.raw.geometry_count == 8

    monkeypatch.setenv("LUMINA_SVG_REPLAY_THREADS", "1")
    serial = _analyze(svg)

    monkeypatch.setenv("LUMINA_SVG_REPLAY_THREADS", "4")
    retried = _analyze(svg)

    assert serial.status == retried.status == "unsupported"
    assert serial.reason_code == retried.reason_code == "unsupported_input_precision"
    assert serial.input_paint_count == retried.input_paint_count == 8
    assert serial.max_flattening_error_mm == retried.max_flattening_error_mm == 0.0
    assert _result_snapshot(retried) == _result_snapshot(serial)


def test_ordered_replay_failure_discards_staging_and_retries_serially(
    monkeypatch,
) -> None:
    svg = _nested_parallel_fixture_svg()

    monkeypatch.setenv("LUMINA_SVG_REPLAY_THREADS", "1")
    serial = _analyze(svg)

    monkeypatch.setenv("LUMINA_SVG_REPLAY_THREADS", "4")
    parallel = _analyze(svg)
    assert parallel.replay_worker_count == 4

    monkeypatch.setenv("LUMINA_SVG_TEST_REPLAY_FAIL_AFTER", "2")
    retried = _analyze(svg)

    assert retried.status == serial.status == "supported"
    assert retried.replay_worker_count == 1
    assert retried.max_flattening_error_mm == serial.max_flattening_error_mm
    assert retried.max_quantization_error_mm == serial.max_quantization_error_mm
    assert _result_snapshot(retried) == _result_snapshot(serial)


def test_ordered_replay_fault_seam_ignores_serial_workloads(monkeypatch) -> None:
    monkeypatch.setenv("LUMINA_SVG_REPLAY_THREADS", "4")
    monkeypatch.setenv("LUMINA_SVG_TEST_REPLAY_FAIL_AFTER", "1")

    result = _analyze(
        "<svg viewBox='0 0 10 10'>"
        "<rect width='10' height='10' fill='#123456'/>"
        "</svg>"
    )

    assert result.status == "supported"
    assert result.replay_worker_count == 1
