"""Regression coverage for bounded source-order occlusion work."""

from __future__ import annotations

from time import perf_counter

import lumina_svg_core


def _disconnected_rectangles(count: int) -> str:
    columns = 60
    rows = (count + columns - 1) // columns
    rectangles = "".join(
        (
            f'<rect x="{(index % columns) * 3}" '
            f'y="{(index // columns) * 3}" width="1" height="1" '
            f'fill="#{index % 256:02x}0000"/>'
        )
        for index in range(count)
    )
    return f'<svg viewBox="0 0 180 {rows * 3}">{rectangles}</svg>'


def _elapsed(count: int) -> float:
    started = perf_counter()
    result = lumina_svg_core.analyze_svg_svg(
        _disconnected_rectangles(count),
        target_width_mm=180.0,
        tolerance_mm=0.02,
    )
    elapsed = perf_counter() - started
    assert result.status == "supported"
    assert result.visible.component_count == count
    return elapsed


def test_disconnected_paints_do_not_scale_quadratically() -> None:
    small_elapsed = min(_elapsed(600) for _ in range(2))
    large_elapsed = min(_elapsed(2400) for _ in range(2))

    assert large_elapsed < small_elapsed * 8.0 + 0.05
