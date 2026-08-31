"""Fail-closed resource budgets for adversarial but compact SVG inputs."""

from __future__ import annotations

from math import cos, pi, sin
from pathlib import Path
import json
import subprocess
import sys
from time import perf_counter

import lumina_svg_core
import pytest


def test_oversized_file_fails_before_unbounded_read(tmp_path: Path) -> None:
    svg_path = tmp_path / "oversized.svg"
    with svg_path.open("wb") as stream:
        stream.write(b"<svg>")
        stream.seek(64 * 1024 * 1024)
        stream.write(b"x")

    recording = lumina_svg_core.record_paint_commands(svg_path)
    analysis = lumina_svg_core.analyze_svg(svg_path, 10.0, 0.02)

    assert recording.status == "unsupported"
    assert recording.reason_code == "unsupported_complexity"
    assert recording.commands == ()
    assert analysis.status == "unsupported"
    assert analysis.reason_code == "unsupported_complexity"


def test_deep_xml_element_nesting_fails_before_lunasvg_recursion() -> None:
    depth = 300
    svg = (
        "<svg viewBox='0 0 10 10'>"
        + "<g>" * depth
        + "<rect width='10' height='10'/>"
        + "</g>" * depth
        + "</svg>"
    )

    recording = lumina_svg_core.record_paint_commands_svg(svg)
    analysis = lumina_svg_core.analyze_svg_svg(svg, 10.0, 0.02)

    assert recording.status == "unsupported"
    assert recording.reason_code == "unsupported_complexity"
    assert recording.commands == ()
    assert analysis.status == "unsupported"
    assert analysis.reason_code == "unsupported_complexity"


def test_many_distinct_overlapping_paints_hit_compositor_work_budget() -> None:
    count = 1500
    rectangles = "".join(
        (
            f"<rect x='{index * 0.05:g}' y='{index * 0.05:g}' "
            f"width='{2000 - index * 0.1:g}' "
            f"height='{2000 - index * 0.1:g}' "
            f"fill='#{index % 251:02x}0000'/>"
        )
        for index in range(count)
    )
    started = perf_counter()
    result = lumina_svg_core.analyze_svg_svg(
        f"<svg viewBox='0 0 2000 2000'>{rectangles}</svg>",
        target_width_mm=200.0,
        tolerance_mm=0.02,
    )
    elapsed = perf_counter() - started

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_complexity"
    assert result.raw.geometry_count == 0
    assert elapsed < 2.0


def test_deep_polygon_tree_is_exported_without_recursive_stack_growth() -> None:
    ring_count = 512
    rings = []
    for inset in range(ring_count):
        outer = 2 * ring_count - inset
        rings.append(
            f"M{inset} {inset}H{outer}V{outer}H{inset}Z"
        )
    result = lumina_svg_core.analyze_svg_svg(
        f"<svg viewBox='0 0 {2 * ring_count} {2 * ring_count}'>"
        f"<path fill-rule='evenodd' d='{' '.join(rings)}'/>"
        "</svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.raw.component_count == ring_count // 2
    assert result.raw.hole_count == ring_count // 2


def test_parallel_legacy_close_is_deterministic_for_64_convex_paints() -> None:
    rectangles = "".join(
        f"<rect x='{index * 2}' width='1' height='1' "
        f"fill='#{index:02x}0000'/>"
        for index in range(64)
    )
    svg = f"<svg viewBox='0 0 128 1'>{rectangles}</svg>"

    first = lumina_svg_core.analyze_svg_svg(
        svg,
        target_width_mm=128.0,
        tolerance_mm=0.02,
        legacy_close_delta_source_units=0.03,
    )
    second = lumina_svg_core.analyze_svg_svg(
        svg,
        target_width_mm=128.0,
        tolerance_mm=0.02,
        legacy_close_delta_source_units=0.03,
    )

    assert first.status == second.status == "supported"
    assert first.raw.geometry_count == second.raw.geometry_count == 64
    assert first.raw.coordinates.tobytes() == second.raw.coordinates.tobytes()
    assert first.raw.geometry_offsets.tobytes() == (
        second.raw.geometry_offsets.tobytes()
    )


def test_parallel_thread_launch_failure_is_controlled() -> None:
    triangles = "".join(
        f"<path d='M{index * 3} 0L{index * 3 + 2} 0"
        f"L{index * 3 + 1} 1.7320508Z' fill='#{index:02x}0000'/>"
        for index in range(64)
    )
    svg = f"<svg viewBox='0 0 192 2'>{triangles}</svg>"

    lumina_svg_core._set_thread_launch_failure_after_for_testing(1)
    try:
        result = lumina_svg_core.analyze_svg_svg(
            svg,
            target_width_mm=128.0,
            tolerance_mm=0.02,
            legacy_close_delta_source_units=0.03,
        )
    finally:
        lumina_svg_core._set_thread_launch_failure_after_for_testing(-1)

    assert result.status == "invalid"
    assert result.reason_code == "native_geometry_error"
    assert result.raw.geometry_count == 0


def test_unproven_large_legacy_close_is_rejected_before_offsets() -> None:
    vertex_count = 10_400
    points = [
        (
            round(1_000_000 + 900_000 * cos(2 * pi * index / vertex_count)),
            round(1_000_000 + 900_000 * sin(2 * pi * index / vertex_count)),
        )
        for index in range(vertex_count)
    ]
    # One deep concavity prevents the safe miter round-trip proof. The close
    # path must reject its quadratic offset candidate set before Clipper.
    points[0] = (1_000_000, 1_000_000)
    path = (
        f"M{points[0][0]} {points[0][1]}"
        + "".join(f"L{x} {y}" for x, y in points[1:])
        + "Z"
    )
    paints = "".join(
        f"<path d='{path}' fill='#{index:02x}0000'/>"
        for index in range(64)
    )
    svg = f"<svg viewBox='0 0 2000000 2000000'>{paints}</svg>"

    without_close = lumina_svg_core.analyze_svg_svg(
        svg,
        target_width_mm=200.0,
        tolerance_mm=0.02,
    )
    with_close = lumina_svg_core.analyze_svg_svg(
        svg,
        target_width_mm=200.0,
        tolerance_mm=0.02,
        legacy_close_delta_source_units=0.03,
    )

    assert without_close.status == "supported"
    assert without_close.raw.geometry_count == 64
    assert with_close.status == "unsupported"
    assert with_close.reason_code == "unsupported_complexity"
    assert with_close.raw.geometry_count == 0


@pytest.mark.parametrize(
    "body",
    [
        "<style>" + ".a{fill:red}" * 20_001 + "</style>",
        "<style>" + "g " * 100_001 + "{fill:red}</style>",
        "<path d='M0 0 " + "L1 1 " * 180_000 + "'/>",
        "<polygon points='" + "0,0 " * 260_000 + "'/>",
        "<path d='M0 0H10' stroke='red' stroke-dasharray='"
        + "1 " * 100_001
        + "'/>",
        "<path d='M0 0H10' style='"
        + "fill:red;" * 100_001
        + "'/>",
    ],
    ids=[
        "stylesheet-rules",
        "stylesheet-selector-chain",
        "path-data",
        "points",
        "dash-array",
        "inline-css",
    ],
)
def test_parser_allocation_budgets_reject_compact_amplifiers_early(
    body: str,
) -> None:
    started = perf_counter()
    result = lumina_svg_core.record_paint_commands_svg(
        f"<svg viewBox='0 0 10 10'>{body}</svg>"
    )
    elapsed = perf_counter() - started

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_complexity"
    assert result.commands == ()
    assert elapsed < 1.0


def test_internal_doctype_is_rejected_before_namespace_preflight() -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<!DOCTYPE svg [<!ENTITY payload '<u:tag/>'>]><svg/>"
    )

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_doctype"
    assert result.commands == ()


def test_stylesheet_cdata_does_not_hide_rules_after_fake_end_tag() -> None:
    css = (
        "<![CDATA[/* </styleX> */ .sentinel{content:'</styleX>';}"
        + ".a{fill:red}" * 20_001
        + "]]>"
    )
    started = perf_counter()
    result = lumina_svg_core.record_paint_commands_svg(
        f"<svg><style>{css}</style><rect class='a'/></svg>"
    )
    elapsed = perf_counter() - started

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_complexity"
    assert result.commands == ()
    assert elapsed < 1.0


@pytest.mark.parametrize("count", [12_000, 20_000])
def test_css_element_rule_cross_product_is_bounded_before_luna(
    count: int,
) -> None:
    svg = (
        "<svg><style>"
        + ".x{fill:red}" * count
        + "</style>"
        + "<rect class='x' width='1' height='1'/>" * count
        + "</svg>"
    )
    started = perf_counter()
    result = lumina_svg_core.record_paint_commands_svg(svg)
    elapsed = perf_counter() - started

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_complexity"
    assert result.commands == ()
    assert elapsed < 1.0


@pytest.mark.skipif(sys.platform == "win32", reason="resource is POSIX-only")
def test_stylesheet_preflight_has_bounded_peak_rss() -> None:
    script = """
import json
import resource
import sys
from time import perf_counter
import lumina_svg_core

before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
svg = "<svg><style>" + ".a{fill:red}" * 20_001 + "</style></svg>"
started = perf_counter()
result = lumina_svg_core.record_paint_commands_svg(svg)
elapsed = perf_counter() - started
after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
unit = 1 if sys.platform == "darwin" else 1024
print(json.dumps({
    "status": result.status,
    "reason": result.reason_code,
    "elapsed": elapsed,
    "rss_delta_bytes": max(0, after - before) * unit,
}))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
        timeout=5.0,
    )
    evidence = json.loads(completed.stdout)

    assert evidence["status"] == "unsupported"
    assert evidence["reason"] == "unsupported_complexity"
    assert evidence["elapsed"] < 1.0
    assert evidence["rss_delta_bytes"] < 64 * 1024 * 1024


@pytest.mark.skipif(sys.platform == "win32", reason="resource is POSIX-only")
def test_css_cross_product_preflight_has_bounded_peak_rss() -> None:
    script = """
import json
import resource
import sys
from time import perf_counter
import lumina_svg_core

count = 20_000
svg = (
    "<svg><style>" + ".x{fill:red}" * count + "</style>"
    + "<rect class='x' width='1' height='1'/>" * count + "</svg>"
)
before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
started = perf_counter()
result = lumina_svg_core.record_paint_commands_svg(svg)
elapsed = perf_counter() - started
after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
unit = 1 if sys.platform == "darwin" else 1024
print(json.dumps({
    "status": result.status,
    "reason": result.reason_code,
    "elapsed": elapsed,
    "rss_delta_bytes": max(0, after - before) * unit,
}))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
        timeout=5.0,
    )
    evidence = json.loads(completed.stdout)

    assert evidence["status"] == "unsupported"
    assert evidence["reason"] == "unsupported_complexity"
    assert evidence["elapsed"] < 1.0
    assert evidence["rss_delta_bytes"] < 96 * 1024 * 1024


@pytest.mark.skipif(sys.platform == "win32", reason="resource is POSIX-only")
def test_namespace_preflight_rejects_nested_binding_amplifier_early() -> None:
    script = """
import json
import resource
import sys
from time import perf_counter
import lumina_svg_core

depth = 127
bindings_per_level = 2_000
opening_tags = []
for level in range(depth):
    bindings = " ".join(
        f"xmlns:p{level}_{index}='urn:lumina:{level}:{index}'"
        for index in range(bindings_per_level)
    )
    opening_tags.append(f"<g {bindings}>")
svg = (
    "<svg viewBox='0 0 10 10'>"
    + "".join(opening_tags)
    + "<rect width='10' height='10'/>"
    + "</g>" * depth
    + "</svg>"
)
before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
started = perf_counter()
result = lumina_svg_core.record_paint_commands_svg(svg)
elapsed = perf_counter() - started
after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
unit = 1 if sys.platform == "darwin" else 1024
print(json.dumps({
    "status": result.status,
    "reason": result.reason_code,
    "elapsed": elapsed,
    "rss_delta_bytes": max(0, after - before) * unit,
}))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
        timeout=5.0,
    )
    evidence = json.loads(completed.stdout)

    assert evidence["status"] == "unsupported"
    assert evidence["reason"] == "unsupported_namespace"
    assert evidence["elapsed"] < 1.0
    assert evidence["rss_delta_bytes"] < 96 * 1024 * 1024


@pytest.mark.skipif(sys.platform == "win32", reason="resource is POSIX-only")
def test_self_intersection_budget_precedes_first_clipper_union() -> None:
    script = """
import json
import resource
import sys
from math import cos, pi, sin
from time import perf_counter
import lumina_svg_core

vertex_count = 10_000
step = vertex_count // 2 - 1
index = 0
points = []
for _ in range(vertex_count):
    angle = 2 * pi * index / vertex_count
    points.append(
        f"{500 + 490 * cos(angle):.3f},{500 + 490 * sin(angle):.3f}"
    )
    index = (index + step) % vertex_count
svg = (
    "<svg viewBox='0 0 1000 1000'><path d='M"
    + " ".join(points)
    + "Z'/></svg>"
)
before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
started = perf_counter()
result = lumina_svg_core.analyze_svg_svg(svg, 100.0, 0.02)
elapsed = perf_counter() - started
after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
unit = 1 if sys.platform == "darwin" else 1024
print(json.dumps({
    "status": result.status,
    "reason": result.reason_code,
    "elapsed": elapsed,
    "rss_delta_bytes": max(0, after - before) * unit,
}))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
        timeout=5.0,
    )
    evidence = json.loads(completed.stdout)

    assert evidence["status"] == "unsupported"
    assert evidence["reason"] == "unsupported_complexity"
    assert evidence["elapsed"] < 1.0
    assert evidence["rss_delta_bytes"] < 96 * 1024 * 1024
