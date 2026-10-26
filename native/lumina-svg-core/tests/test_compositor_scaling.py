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


def _overlapping_elapsed(count: int) -> float:
    # Keep every lower paint distinct so an exact-duplicate shortcut cannot
    # hide quadratic overlap enumeration.  The final rectangle covers every
    # earlier paint, so an incremental suffix coverage stays constant-sized.
    rectangles = "".join(
        (
            f'<rect x="{index / (count * 20):.9g}" '
            f'y="{index / (count * 20):.9g}" '
            f'width="{9 - index / (count * 10):.9g}" '
            f'height="{9 - index / (count * 10):.9g}" '
            f'fill="#{index % 251:02x}0000"/>'
        )
        for index in range(count - 1)
    )
    # Two final half-planes jointly cover the canvas.  Neither paint alone is
    # a rectangular occluder for the other lower paints, so an implementation
    # that rebuilds a union from every later paint still does quadratic work.
    rectangles += (
        '<rect width="5" height="10" fill="#0000ff"/>'
        '<rect x="5" width="5" height="10" fill="#00ff00"/>'
    )
    started = perf_counter()
    result = lumina_svg_core.analyze_svg_svg(
        f'<svg viewBox="0 0 10 10">{rectangles}</svg>',
        target_width_mm=10.0,
        tolerance_mm=0.02,
    )
    elapsed = perf_counter() - started
    assert result.status == "supported"
    assert result.visible.component_count == 2
    return elapsed


def _distributed_components_elapsed(count: int) -> float:
    extent = count * 4 + 2
    paints = "".join(
        (
            f'<path d="M{index * 2} {index * 2}h1v1h-1z '
            f'M{extent - index * 2} {extent - index * 2}h1v1h-1z" '
            f'fill="#{index % 251:02x}0000"/>'
        )
        for index in range(count)
    )
    started = perf_counter()
    result = lumina_svg_core.analyze_svg_svg(
        f'<svg viewBox="0 0 {extent + 2} {extent + 2}">{paints}</svg>',
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )
    elapsed = perf_counter() - started
    assert result.status == "supported", result.reason_code
    assert result.visible.component_count == count * 2
    return elapsed


def test_disconnected_paints_do_not_scale_quadratically() -> None:
    small_elapsed = min(_elapsed(600) for _ in range(2))
    large_elapsed = min(_elapsed(2400) for _ in range(2))

    assert large_elapsed < small_elapsed * 8.0 + 0.05


def test_fully_overlapping_paints_use_incremental_suffix_coverage() -> None:
    small_elapsed = min(_overlapping_elapsed(200) for _ in range(2))
    large_elapsed = min(_overlapping_elapsed(800) for _ in range(2))

    assert large_elapsed < small_elapsed * 10.0 + 0.05


def test_distributed_visible_components_use_hierarchical_coverage() -> None:
    small_elapsed = min(
        _distributed_components_elapsed(150) for _ in range(2)
    )
    large_elapsed = min(
        _distributed_components_elapsed(600) for _ in range(2)
    )

    assert large_elapsed < small_elapsed * 10.0 + 0.1


def _duplicate_paints_elapsed(count: int) -> float:
    paints = "".join(
        f'<rect width="10" height="10" fill="#{index % 251:02x}0000"/>'
        for index in range(count)
    )
    started = perf_counter()
    result = lumina_svg_core.analyze_svg_svg(
        f'<svg viewBox="0 0 10 10">{paints}</svg>',
        target_width_mm=10.0,
        tolerance_mm=0.02,
    )
    elapsed = perf_counter() - started
    assert result.status == "supported"
    assert result.visible.component_count == 1
    assert result.visible.draw_indices.tolist() == [count - 1]
    assert result.visible.rgba.tolist() == [[(count - 1) % 251, 0, 0, 255]]
    return elapsed


def test_exact_duplicate_paints_keep_last_owner_with_bounded_lookup() -> None:
    small_elapsed = min(_duplicate_paints_elapsed(600) for _ in range(2))
    large_elapsed = min(_duplicate_paints_elapsed(2400) for _ in range(2))

    assert large_elapsed < small_elapsed * 8.0 + 0.05
