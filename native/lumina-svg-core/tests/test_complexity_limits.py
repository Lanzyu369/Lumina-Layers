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
        stream.seek(256 * 1024 * 1024)
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


def test_many_flat_use_instances_are_not_rejected_by_a_raw_count_gate() -> None:
    uses = "".join(
        f"<use href='#shape' x='{index}'/>" for index in range(100)
    )
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 100 1'><defs>"
        "<rect id='shape' width='1' height='1' fill='red'/></defs>"
        f"{uses}</svg>"
    )

    assert result.status == "supported"
    assert len(result.commands) == 100


def test_many_small_elements_fit_the_document_memory_budget() -> None:
    element_count = 65_000
    rectangles = (
        "<rect x='0' y='0' width='1' height='1'/>" * element_count
    )

    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 1 1'>" + rectangles + "</svg>"
    )

    assert result.status == "supported"
    assert result.reason_code == ""
    assert len(result.commands) == element_count


def test_deep_use_expansion_fails_before_recursive_clone_growth() -> None:
    depth = 160
    definitions = "".join(
        f"<g id='node{index}'><use href='#node{index + 1}'/></g>"
        for index in range(depth)
    )
    definitions += f"<g id='node{depth}'><rect width='1' height='1'/></g>"
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 1 1'><defs>"
        f"{definitions}</defs><use href='#node0'/></svg>"
    )

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_complexity"
    assert result.commands == ()


def test_many_distinct_overlapping_paints_are_composited_without_pair_gate() -> None:
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

    assert result.status == "supported"
    assert result.reason_code == ""
    assert result.raw.geometry_count == count
    assert elapsed < 10.0


def test_boolean_ring_upper_bound_does_not_reject_a_small_valid_union() -> None:
    """A theoretical split count is not the number of emitted rings."""
    stripe_count = 660
    subpaths = ["M0 0H1000V1000H0Z"]
    for index in range(stripe_count):
        y = (index + 1) * 1000 / (stripe_count + 1)
        subpaths.append(f"M0 {y:.6f}H1000V{y + 0.25:.6f}H0Z")
    for index in range(stripe_count):
        x = (index + 1) * 1000 / (stripe_count + 1)
        subpaths.append(f"M{x:.6f} 0H{x + 0.25:.6f}V1000H{x:.6f}Z")

    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 1000 1000'>"
        f"<path fill='#123456' d='{' '.join(subpaths)}'/>"
        "</svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.reason_code == ""
    assert result.raw.geometry_count == 1
    assert result.raw.component_count == 1
    assert result.raw.hole_count == 0


@pytest.mark.skipif(sys.platform == "win32", reason="resource is POSIX-only")
def test_cross_operand_ring_amplification_is_bounded_inside_clipper() -> None:
    """A small pair of canonical operands must not allocate an unbounded result."""
    script = """
import json
import resource
import sys
from time import perf_counter
import lumina_svg_core

count = 1001
stripe_width = 25.0 / count
vertical = ' '.join(
    f'M{x:.12g} 0H{x + stripe_width:.12g}V100H{x:.12g}Z'
    for x in (index * 100.0 / count for index in range(count))
)
horizontal = ' '.join(
    f'M0 {y:.12g}H100V{y + stripe_width:.12g}H0Z'
    for y in (index * 100.0 / count for index in range(count))
)
svg = (
    "<svg viewBox='0 0 100 100'><defs><clipPath id='c'>"
    f"<path d='{vertical}'/></clipPath></defs>"
    f"<path clip-path='url(#c)' fill='red' d='{horizontal}'/></svg>"
)
before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
started = perf_counter()
result = lumina_svg_core.analyze_svg_svg(svg, 100.0, 0.02)
after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
unit = 1 if sys.platform == 'darwin' else 1024
print(json.dumps({
    'status': result.status,
    'reason': result.reason_code,
    'elapsed': perf_counter() - started,
    'rss_delta_bytes': max(0, after - before) * unit,
}))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
        timeout=15.0,
    )
    evidence = json.loads(completed.stdout)

    assert evidence["status"] == "unsupported"
    assert evidence["reason"] == "unsupported_complexity"
    assert evidence["elapsed"] < 5.0
    rss_limit_mib = 384 if sys.platform == "darwin" else 512
    assert evidence["rss_delta_bytes"] < rss_limit_mib * 1024 * 1024


@pytest.mark.skipif(sys.platform == "win32", reason="resource is POSIX-only")
def test_compositor_processes_large_bounded_overlap_within_document_budget(
) -> None:
    script = """
import json
import resource
import sys
from time import perf_counter
import lumina_svg_core

count = 15000
rectangles = ''.join(
    f"<rect x='{index * 0.001:g}' y='{index * 0.001:g}' "
    f"width='{100 - index * 0.002:g}' "
    f"height='{100 - index * 0.002:g}' "
    f"fill='#{index % 251:02x}0000'/>"
    for index in range(count)
)
svg = f"<svg viewBox='0 0 100 100'>{rectangles}</svg>"
before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
started = perf_counter()
result = lumina_svg_core.analyze_svg_svg(svg, 100.0, 0.02)
elapsed = perf_counter() - started
after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
unit = 1 if sys.platform == 'darwin' else 1024
print(json.dumps({
    'status': result.status,
    'reason': result.reason_code,
    'raw_geometry_count': result.raw.geometry_count,
    'visible_geometry_count': result.visible.geometry_count,
    'visible_component_count': result.visible.component_count,
    'elapsed': elapsed,
    'rss_delta_bytes': max(0, after - before) * unit,
}))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
        timeout=15.0,
    )
    evidence = json.loads(completed.stdout)

    assert evidence["status"] == "supported"
    assert evidence["reason"] == ""
    assert evidence["raw_geometry_count"] == 15_000
    assert evidence["visible_geometry_count"] == 15_000
    assert evidence["visible_component_count"] == 15_000
    assert evidence["elapsed"] < 8.0
    assert evidence["rss_delta_bytes"] < 256 * 1024 * 1024


@pytest.mark.skipif(sys.platform == "win32", reason="resource is POSIX-only")
def test_compositor_handles_dense_later_occluders_within_document_budget() -> None:
    script = """
import json
from time import perf_counter
import lumina_svg_core

count = 600
rectangles = ''.join(
    f"<rect x='5' y='49.75' width='90' height='.5' "
    f"transform='rotate({180.0 * index / count:.9g} 50 50)' "
    f"fill='#{(index * 37) % 256:02x}{(index * 67) % 256:02x}"
    f"{(index * 97) % 256:02x}'/>"
    for index in range(count)
)
svg = f"<svg viewBox='0 0 100 100'>{rectangles}</svg>"
started = perf_counter()
result = lumina_svg_core.analyze_svg_svg(svg, 100.0, 0.02)
print(json.dumps({
    'status': result.status,
    'reason': result.reason_code,
    'elapsed': perf_counter() - started,
}))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
        timeout=15.0,
    )
    evidence = json.loads(completed.stdout)

    assert evidence["status"] == "supported"
    assert evidence["reason"] == ""
    assert evidence["elapsed"] < 8.0


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


def test_many_convex_paints_are_deterministic() -> None:
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
    )
    second = lumina_svg_core.analyze_svg_svg(
        svg,
        target_width_mm=128.0,
        tolerance_mm=0.02,
    )

    assert first.status == second.status == "supported"
    assert first.raw.geometry_count == second.raw.geometry_count == 64
    assert first.raw.coordinates.tobytes() == second.raw.coordinates.tobytes()
    assert first.raw.geometry_offsets.tobytes() == (
        second.raw.geometry_offsets.tobytes()
    )


def test_large_sparse_paints_are_not_charged_as_all_pairs() -> None:
    vertex_count = 10_400
    points = [
        (
            round(1_000_000 + 900_000 * cos(2 * pi * index / vertex_count)),
            round(1_000_000 + 900_000 * sin(2 * pi * index / vertex_count)),
        )
        for index in range(vertex_count)
    ]
    # One deep concavity and the remaining locally sparse edges must not be
    # charged as a quadratic all-pairs set.
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

    first = lumina_svg_core.analyze_svg_svg(
        svg,
        target_width_mm=200.0,
        tolerance_mm=0.02,
    )
    started = perf_counter()
    second = lumina_svg_core.analyze_svg_svg(
        svg,
        target_width_mm=200.0,
        tolerance_mm=0.02,
    )
    elapsed = perf_counter() - started

    assert first.status == "supported"
    assert first.raw.geometry_count == 64
    assert second.status == "supported"
    assert second.raw.geometry_count == 64
    assert elapsed < 3.0


def test_large_legal_path_is_not_rejected_by_per_attribute_token_gate() -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 10 10'><path d='M0 0 "
        + "L1 1 " * 180_000
        + "'/></svg>"
    )

    assert result.status == "supported"
    assert result.reason_code == ""


@pytest.mark.skipif(sys.platform == "win32", reason="resource is POSIX-only")
def test_path_parse_budget_precedes_plutovg_element_allocation() -> None:
    script = """
import json
import resource
import sys
from time import perf_counter
import lumina_svg_core

svg = "<svg><path d='M0 0" + "L0 0" * 3_000_000 + "'/></svg>"
before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
started = perf_counter()
result = lumina_svg_core.record_paint_commands_svg(svg)
after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
unit = 1 if sys.platform == 'darwin' else 1024
print(json.dumps({
    'status': result.status,
    'reason': result.reason_code,
    'elapsed': perf_counter() - started,
    'rss_delta_bytes': max(0, after - before) * unit,
}))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
        timeout=10.0,
    )
    evidence = json.loads(completed.stdout)

    assert evidence["status"] == "unsupported"
    assert evidence["reason"] == "unsupported_complexity"
    assert evidence["elapsed"] < 5.0
    assert evidence["rss_delta_bytes"] < 96 * 1024 * 1024


@pytest.mark.skipif(sys.platform == "win32", reason="resource is POSIX-only")
def test_points_parse_budget_precedes_point_list_allocation() -> None:
    script = """
import json
import resource
import sys
from time import perf_counter
import lumina_svg_core

svg = "<svg><polygon points='" + "0,0 " * 2_100_000 + "'/></svg>"
before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
started = perf_counter()
result = lumina_svg_core.record_paint_commands_svg(svg)
after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
unit = 1 if sys.platform == 'darwin' else 1024
print(json.dumps({
    'status': result.status,
    'reason': result.reason_code,
    'elapsed': perf_counter() - started,
    'rss_delta_bytes': max(0, after - before) * unit,
}))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
        timeout=10.0,
    )
    evidence = json.loads(completed.stdout)

    assert evidence["status"] == "unsupported"
    assert evidence["reason"] == "unsupported_complexity"
    assert evidence["elapsed"] < 5.0
    assert evidence["rss_delta_bytes"] < 96 * 1024 * 1024


@pytest.mark.skipif(sys.platform == "win32", reason="resource is POSIX-only")
def test_invalid_transform_arity_does_not_allocate_all_numbers() -> None:
    script = """
import json
import resource
import sys
from time import perf_counter
import lumina_svg_core

svg = "<svg><rect width='1' height='1' transform='matrix(" + "1 " * 4_000_000 + ")'/></svg>"
before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
started = perf_counter()
result = lumina_svg_core.record_paint_commands_svg(svg)
after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
unit = 1 if sys.platform == 'darwin' else 1024
print(json.dumps({
    'status': result.status,
    'reason': result.reason_code,
    'elapsed': perf_counter() - started,
    'rss_delta_bytes': max(0, after - before) * unit,
}))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
        timeout=10.0,
    )
    evidence = json.loads(completed.stdout)

    assert evidence["status"] == "unsupported"
    assert evidence["reason"] == "unsupported_attribute_value"
    assert evidence["elapsed"] < 5.0
    assert evidence["rss_delta_bytes"] < 64 * 1024 * 1024


@pytest.mark.skipif(sys.platform == "win32", reason="resource is POSIX-only")
def test_xml_attribute_budget_precedes_namespace_vector_allocation() -> None:
    script = """
import json
import resource
import sys
from time import perf_counter
import lumina_svg_core

attributes = ''.join(f" data-{index}='x'" for index in range(100_000))
svg = f"<svg><rect width='1' height='1'{attributes}/></svg>"
before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
started = perf_counter()
result = lumina_svg_core.record_paint_commands_svg(svg)
after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
unit = 1 if sys.platform == 'darwin' else 1024
print(json.dumps({
    'status': result.status,
    'reason': result.reason_code,
    'elapsed': perf_counter() - started,
    'rss_delta_bytes': max(0, after - before) * unit,
}))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
        timeout=10.0,
    )
    evidence = json.loads(completed.stdout)

    assert evidence["status"] == "unsupported"
    assert evidence["reason"] == "unsupported_complexity"
    assert evidence["elapsed"] < 5.0
    assert evidence["rss_delta_bytes"] < 64 * 1024 * 1024


def test_internal_doctype_is_rejected_before_namespace_preflight() -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<!DOCTYPE svg [<!ENTITY payload '<u:tag/>'>]><svg/>"
    )

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_doctype"
    assert result.commands == ()


def test_sparse_unique_simple_class_css_preserves_resolved_paint_metadata(
) -> None:
    count = 3_000

    def color(index: int) -> str:
        return (
            f"#{index & 0xFF:02x}"
            f"{(index >> 8) & 0xFF:02x}"
            f"{(index >> 16) & 0xFF:02x}"
        )

    stylesheet = "".join(
        f".c{index}{{fill:{color(index)}}}" for index in range(count)
    )
    rectangles = "".join(
        f"<rect class='c{index}' x='{index}' width='1' height='1'/>"
        for index in range(count)
    )
    first = lumina_svg_core.record_paint_commands_svg(
        f"<svg viewBox='0 0 {count} 1'>"
        f"<style>{stylesheet}</style>{rectangles}</svg>"
    )
    second = lumina_svg_core.record_paint_commands_svg(
        f"<svg viewBox='0 0 {count} 1'>"
        f"<style>{stylesheet}</style>{rectangles}</svg>"
    )

    assert first.status == second.status == "supported"
    assert len(first.commands) == len(second.commands) == count
    sample_indices = (0, 1, 255, 256, count - 1)
    assert [tuple(first.commands[index].rgba) for index in sample_indices] == [
        tuple(bytes.fromhex(color(index)[1:])) + (255,)
        for index in sample_indices
    ]
    expected_source_indices = list(range(2, count + 2))
    assert [
        command.source_index for command in first.commands
    ] == expected_source_indices
    assert [
        command.source_index for command in second.commands
    ] == expected_source_indices


def test_simple_class_index_handles_normal_unmatched_work_above_ticket_size(
) -> None:
    rule_count = 10_000
    element_count = 15_001
    stylesheet = "".join(
        f".c{index}{{fill:red}}" for index in range(rule_count)
    )
    elements = "<g class='unmatched'/>" * element_count

    started = perf_counter()
    result = lumina_svg_core.record_paint_commands_svg(
        f"<svg><style>{stylesheet}</style>{elements}</svg>"
    )
    elapsed = perf_counter() - started

    assert result.status == "supported"
    assert result.reason_code == ""
    assert result.commands == ()
    assert elapsed < 2.0


def test_simple_class_index_preserves_rule_order_and_multi_class_cascade(
) -> None:
    svg = (
        "<svg viewBox='0 0 3 1'><style>"
        ".a{fill:#ff0000}.b{fill:#00ff00}.a{fill:#0000ff}"
        "</style>"
        "<rect class='a' width='1' height='1'/>"
        "<rect class='a b' x='1' width='1' height='1'/>"
        "<rect class='a' x='2' width='1' height='1' "
        "style='fill:#ffff00'/>"
        "</svg>"
    )

    result = lumina_svg_core.record_paint_commands_svg(svg)

    assert result.status == "supported"
    assert [tuple(command.rgba) for command in result.commands] == [
        (0, 0, 255, 255),
        (0, 0, 255, 255),
        (255, 255, 0, 255),
    ]


@pytest.mark.skipif(sys.platform == "win32", reason="resource is POSIX-only")
def test_selector_lists_share_declarations_without_quadratic_copies() -> None:
    script = """
import json
import resource
import sys
import lumina_svg_core

count = 2_000
selectors = ','.join(f'.selector{index}' for index in range(count))
declarations = 'fill:red;' * count
svg = f'<svg><style>{selectors}{{{declarations}}}</style></svg>'
before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
result = lumina_svg_core.record_paint_commands_svg(svg)
after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
unit = 1 if sys.platform == 'darwin' else 1024
print(json.dumps({
    'status': result.status,
    'reason': result.reason_code,
    'rss_delta_bytes': max(0, after - before) * unit,
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

    assert evidence["status"] == "supported"
    assert evidence["reason"] == ""
    assert evidence["rss_delta_bytes"] < 96 * 1024 * 1024


@pytest.mark.skipif(sys.platform == "win32", reason="resource is POSIX-only")
def test_repeated_class_tokens_do_not_multiply_candidate_storage() -> None:
    script = """
import json
import resource
import sys
import lumina_svg_core

rule_count = 2_000
token_count = 5_000
stylesheet = '.a{fill:red}' * rule_count
classes = ' '.join(['a'] * token_count)
svg = (
    "<svg viewBox='0 0 1 1'><style>"
    + stylesheet
    + "</style><rect class='"
    + classes
    + "' width='1' height='1'/></svg>"
)
before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
result = lumina_svg_core.record_paint_commands_svg(svg)
after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
unit = 1 if sys.platform == 'darwin' else 1024
print(json.dumps({
    'status': result.status,
    'reason': result.reason_code,
    'command_count': len(result.commands),
    'rss_delta_bytes': max(0, after - before) * unit,
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

    assert evidence["status"] == "supported"
    assert evidence["reason"] == ""
    assert evidence["command_count"] == 1
    assert evidence["rss_delta_bytes"] < 64 * 1024 * 1024


@pytest.mark.skipif(sys.platform == "win32", reason="resource is POSIX-only")
@pytest.mark.parametrize(
    ("payload_expression", "expected_reason"),
    [
        ("','.join(['.a'] * 1_000_001) + '{fill:red}'", "unsupported_complexity"),
        ("'.a{' + 'fill:red;' * 300_001 + '}'", "unsupported_complexity"),
    ],
    ids=["selector-list", "declaration-list"],
)
def test_css_parse_limits_apply_before_building_oversized_rule(
    payload_expression: str,
    expected_reason: str,
) -> None:
    script = f"""
import json
import resource
import sys
from time import perf_counter
import lumina_svg_core

stylesheet = {payload_expression}
svg = '<svg><style>' + stylesheet + '</style></svg>'
before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
started = perf_counter()
result = lumina_svg_core.record_paint_commands_svg(svg)
after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
unit = 1 if sys.platform == 'darwin' else 1024
print(json.dumps({{
    'status': result.status,
    'reason': result.reason_code,
    'elapsed': perf_counter() - started,
    'rss_delta_bytes': max(0, after - before) * unit,
}}))
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
    assert evidence["reason"] == expected_reason
    assert evidence["elapsed"] < 3.0
    assert evidence["rss_delta_bytes"] < 96 * 1024 * 1024


def test_unrelated_unique_class_attributes_do_not_change_paint_results() -> None:
    count = 40_000
    elements = "".join(
        f"<g class='unrelated{index}'/>" for index in range(count)
    )
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 1 1'><style>.target{fill:red}</style>"
        f"{elements}</svg>"
    )

    assert result.status == "supported"
    assert result.commands == ()


def test_css_match_budget_counts_nested_selector_nodes() -> None:
    selector_count = 5_001
    element_count = 10_001
    excluded = ",".join(
        f".excluded{index}" for index in range(selector_count)
    )
    svg = (
        "<svg><style>g:not("
        + excluded
        + "){fill:red}</style>"
        + "<g/>" * element_count
        + "</svg>"
    )

    started = perf_counter()
    result = lumina_svg_core.record_paint_commands_svg(svg)
    elapsed = perf_counter() - started

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_complexity"
    assert result.commands == ()
    assert elapsed < 5.0


def test_css_match_budget_counts_indirect_sibling_traversal() -> None:
    sibling_count = 10_001
    svg = (
        "<svg><style>g ~ rect{fill:red}</style><g/>"
        + "<rect/>" * sibling_count
        + "</svg>"
    )

    started = perf_counter()
    result = lumina_svg_core.record_paint_commands_svg(svg)
    elapsed = perf_counter() - started

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_complexity"
    assert result.commands == ()
    assert elapsed < 5.0


@pytest.mark.skipif(sys.platform == "win32", reason="resource is POSIX-only")
def test_css_contains_selector_has_linear_matching_cost() -> None:
    script = """
import json
from time import perf_counter
import lumina_svg_core

haystack = 'a' * 1_000_000
needle = 'a' * 500_000 + 'b'
svg = (
    "<svg viewBox='0 0 1 1'><style>"
    + "rect[id*='" + needle + "']{fill:red}"
    + "</style><rect id='" + haystack + "' width='1' height='1'/></svg>"
)
started = perf_counter()
result = lumina_svg_core.record_paint_commands_svg(svg)
print(json.dumps({
    'status': result.status,
    'reason': result.reason_code,
    'elapsed': perf_counter() - started,
    'command_count': len(result.commands),
}))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
        timeout=3.0,
    )
    evidence = json.loads(completed.stdout)

    assert evidence["status"] == "supported"
    assert evidence["reason"] == ""
    assert evidence["command_count"] == 1
    assert evidence["elapsed"] < 2.0


def test_css_deferred_capabilities_fail_before_quadratic_retention() -> None:
    declaration_count = 350
    element_count = 350
    declarations = ";".join(
        f"offset-{index}:1" for index in range(declaration_count)
    )
    elements = "<rect width='1' height='1'/>" * element_count
    svg = (
        "<svg viewBox='0 0 1 1'><style>rect{"
        + declarations
        + "}</style>"
        + elements
        + "</svg>"
    )

    started = perf_counter()
    result = lumina_svg_core.record_paint_commands_svg(svg)
    elapsed = perf_counter() - started

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_complexity"
    assert result.commands == ()
    assert elapsed < 2.0


def test_use_clone_budget_preflights_reparsed_attribute_bytes() -> None:
    path_data = "M0 0 " + "L1 1 " * 10_000
    use_count = 1_001
    uses = "<use href='#source'/>" * use_count
    svg = (
        "<svg viewBox='0 0 2 2'><defs>"
        f"<path id='source' d='{path_data}'/>"
        f"</defs>{uses}</svg>"
    )

    started = perf_counter()
    result = lumina_svg_core.record_paint_commands_svg(svg)
    elapsed = perf_counter() - started

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_complexity"
    assert result.commands == ()
    assert elapsed < 5.0


def test_use_clone_budget_preflights_nested_reference_amplification() -> None:
    path_data = "M0 0 " + "L1 1 " * 10_000
    use_count = 1_001
    uses = "<use href='#wrapper'/>" * use_count
    svg = (
        "<svg viewBox='0 0 2 2'><defs>"
        f"<path id='source' d='{path_data}'/>"
        "<g id='wrapper'><use href='#source'/></g>"
        f"</defs>{uses}</svg>"
    )

    started = perf_counter()
    result = lumina_svg_core.record_paint_commands_svg(svg)
    elapsed = perf_counter() - started

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_complexity"
    assert result.commands == ()
    assert elapsed < 5.0


def test_nested_use_does_not_copy_already_built_shadow_children() -> None:
    uses = "<use href='#wrapper'/>" * 3
    svg = (
        "<svg viewBox='0 0 2 2'><defs>"
        "<rect id='red' width='1' height='1' fill='#123456'/>"
        "<rect id='blue' x='1' width='1' height='1' fill='#abcdef'/>"
        "<g id='wrapper'><use href='#red'/><use href='#blue'/></g>"
        f"</defs>{uses}</svg>"
    )

    result = lumina_svg_core.record_paint_commands_svg(svg)

    assert result.status == "supported"
    assert result.reason_code == ""
    assert tuple(command.rgba for command in result.commands) == (
        (18, 52, 86, 255),
        (171, 205, 239, 255),
    ) * 3


def test_known_unsupported_text_skips_use_clone_amplification() -> None:
    text = "x" * 20_000
    uses = "<use href='#source'/>" * 1_000
    svg = (
        "<svg viewBox='0 0 2 2'><defs>"
        f"<text id='source'>{text}</text>"
        f"</defs>{uses}</svg>"
    )

    started = perf_counter()
    result = lumina_svg_core.record_paint_commands_svg(svg)
    elapsed = perf_counter() - started

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_text"
    assert result.commands == ()
    assert elapsed < 2.0


def test_use_clone_preflight_preserves_bounded_path_reuse() -> None:
    use_count = 1_001
    uses = "<use href='#source'/>" * use_count
    svg = (
        "<svg viewBox='0 0 2 2'><defs>"
        "<path id='source' d='M0 0 L1 0 L0 1 Z' fill='#123456'/>"
        f"</defs>{uses}</svg>"
    )

    result = lumina_svg_core.record_paint_commands_svg(svg)

    assert result.status == "supported"
    assert result.reason_code == ""
    assert len(result.commands) == use_count
    assert all(command.rgba == (18, 52, 86, 255) for command in result.commands)


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


def test_large_sparse_nonconvex_path_uses_local_interaction_budget() -> None:
    vertex_count = 7_000
    points = []
    for index in range(vertex_count):
        angle = 2 * pi * index / vertex_count
        radius = 100 if index == 0 else 490
        points.append(
            f"{500 + radius * cos(angle):.6f},"
            f"{500 + radius * sin(angle):.6f}"
        )
    svg = (
        "<svg viewBox='0 0 1000 1000'><path d='M"
        + " ".join(points)
        + "Z'/></svg>"
    )

    started = perf_counter()
    result = lumina_svg_core.analyze_svg_svg(
        svg,
        100.0,
        0.02,
    )
    elapsed = perf_counter() - started

    assert result.status == "supported"
    assert result.raw.component_count == 1
    assert result.raw.hole_count == 0
    assert elapsed < 1.0


@pytest.mark.skipif(sys.platform == "win32", reason="resource is POSIX-only")
def test_many_disjoint_small_nonconvex_paths_charge_actual_intersections() -> None:
    script = """
import json
import resource
import sys
from math import cos, pi, sin
from time import perf_counter
import lumina_svg_core

paint_count = 8_500
point_count = 90
paints = []
for paint_index in range(paint_count):
    center_x = (paint_index % 500) * 0.2 + 0.1
    center_y = (paint_index // 500) * 0.2 + 0.1
    points = []
    for point_index in range(point_count):
        angle = 2 * pi * point_index / point_count
        radius = 0.09 if point_index % 2 == 0 else 0.045
        points.append(
            f'{center_x + radius * cos(angle):.8f},'
            f'{center_y + radius * sin(angle):.8f}'
        )
    paints.append("<path d='M" + ' '.join(points) + "Z'/>")
svg = "<svg viewBox='0 0 100 100'>" + ''.join(paints) + "</svg>"
before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
started = perf_counter()
result = lumina_svg_core.analyze_svg_svg(svg, 100.0, 0.02)
after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
unit = 1 if sys.platform == 'darwin' else 1024
print(json.dumps({
    'status': result.status,
    'reason': result.reason_code,
    'geometry_count': result.raw.geometry_count,
    'elapsed': perf_counter() - started,
    'rss_delta_bytes': max(0, after - before) * unit,
}))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
        timeout=45.0,
    )
    evidence = json.loads(completed.stdout)

    assert evidence["status"] == "supported"
    assert evidence["reason"] == ""
    assert evidence["geometry_count"] == 8_500
    assert evidence["elapsed"] < 40.0
    assert evidence["rss_delta_bytes"] < 768 * 1024 * 1024


@pytest.mark.skipif(sys.platform == "win32", reason="resource is POSIX-only")
def test_dashed_stroke_simplification_counts_actual_rdp_comparisons() -> None:
    script = """
import json
import resource
import sys
from time import perf_counter
import lumina_svg_core

points = ' '.join(
    f'L{index} {index % 2}' for index in range(2, 30_002)
)
svg = (
    "<svg viewBox='0 0 30002 2'><path d='M0 0 C.25 0 .75 1 1 1 "
    + points
    + "' fill='none' stroke='black' stroke-width='.1' "
      "stroke-dasharray='1000000 1'/></svg>"
)
before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
started = perf_counter()
result = lumina_svg_core.analyze_svg_svg(svg, 30_002.0, 0.02)
after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
unit = 1 if sys.platform == 'darwin' else 1024
print(json.dumps({
    'status': result.status,
    'reason': result.reason_code,
    'elapsed': perf_counter() - started,
    'rss_delta_bytes': max(0, after - before) * unit,
}))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
        timeout=10.0,
    )
    evidence = json.loads(completed.stdout)

    assert evidence["status"] == "unsupported"
    assert evidence["reason"] == "unsupported_complexity"
    assert evidence["elapsed"] < 5.0
    assert evidence["rss_delta_bytes"] < 256 * 1024 * 1024
