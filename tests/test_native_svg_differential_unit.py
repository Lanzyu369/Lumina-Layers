"""Test-only differential audit for the supported Lumina native subset."""

from __future__ import annotations

from collections import defaultdict
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from shapely import affinity
from shapely.ops import unary_union

from core import native_svg_adapter
from core.native_svg_adapter import NativeSvgFallback
from core.vector_engine import VectorProcessor
import core.vector_engine as vector_engine


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "native_svg"
MANIFEST = json.loads(
    (FIXTURES / "golden_manifest.json").read_text(encoding="utf-8")
)


def _processor() -> VectorProcessor:
    processor = object.__new__(VectorProcessor)
    processor.color_mode = "4-Color (RYBW)"
    processor.sampling_precision = 0.02
    processor.expand_stroke_to_fill = False
    processor.auto_dynamic_range = False
    processor.img_processor = SimpleNamespace(
        lut_rgb=[(0, 0, 0)],
        lut_path="direct.npy",
    )
    processor._match_colors = lambda clipped, *_args, **_kwargs: [
        {
            "geometry": item["geometry"],
            "recipe": [0],
            "color": item["color"],
        }
        for item in clipped
    ]
    return processor


def _run(processor: VectorProcessor, path: Path, *, backend: str, monkeypatch):
    vector_engine._VECTOR_PARSE_CLIP_CACHE.clear()
    if backend == "native":
        return processor.analyze_svg(
            str(path), MANIFEST["target_width_mm"]
        )
    with monkeypatch.context() as context:
        context.setattr(
            native_svg_adapter,
            "analyze_native_svg",
            lambda *_args, **_kwargs: NativeSvgFallback(
                "differential_reference", "test"
            ),
        )
        return processor.analyze_svg(
            str(path), MANIFEST["target_width_mm"]
        )


def _by_color(analysis):
    grouped = defaultdict(list)
    for item in analysis.clipped_shapes:
        grouped[tuple(item["color"])].append(item["geometry"])
    return {color: unary_union(geometries) for color, geometries in grouped.items()}


def _geometry_census(geometry) -> tuple[int, int]:
    polygons = (
        geometry.geoms
        if geometry.geom_type == "MultiPolygon"
        else (geometry,)
    )
    return (
        len(polygons),
        sum(len(polygon.interiors) for polygon in polygons),
    )


def _ordered_paint_colors(analysis) -> list[tuple[int, int, int]]:
    return [
        tuple(item["color"])
        for item in analysis.clipped_shapes
    ]


def _ordered_material_identities(analysis) -> list[tuple[tuple[int, ...], tuple]]:
    return [
        (tuple(shape["color"]), tuple(material["recipe"]))
        for shape, material in zip(
            analysis.clipped_shapes,
            analysis.matched_shapes,
            strict=True,
        )
    ]


def _census_by_color(analysis) -> dict[tuple[int, int, int], tuple[int, int]]:
    return {
        color: _geometry_census(geometry)
        for color, geometry in _by_color(analysis).items()
    }


def _physical_geometry(geometry, scale_factor: float):
    return affinity.scale(
        geometry,
        xfact=scale_factor,
        yfact=scale_factor,
        origin=(0.0, 0.0),
    )


@pytest.mark.parametrize("case", MANIFEST["cases"], ids=lambda case: case["file"])
def test_native_matches_legacy_reference_within_physical_budget(
    case: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("lumina_svg_core")
    path = FIXTURES / str(case["file"])
    assert hashlib.sha256(path.read_bytes()).hexdigest() == case["sha256"]
    processor = _processor()

    native = _run(processor, path, backend="native", monkeypatch=monkeypatch)
    legacy = _run(processor, path, backend="legacy", monkeypatch=monkeypatch)

    expected_backend = str(case["expected_backend"])
    assert native.stage_timings["geometry_backend"] == expected_backend
    if expected_backend == "legacy":
        assert native.stage_timings["native_fallback_reason"] == (
            case["fallback_reason"]
        )
    assert legacy.stage_timings["geometry_backend"] == "legacy"
    assert native.bbox == pytest.approx(legacy.bbox, abs=0.001)
    assert native.scale_factor == pytest.approx(legacy.scale_factor, rel=1e-6)
    assert _ordered_paint_colors(native) == _ordered_paint_colors(legacy)
    assert _ordered_material_identities(native) == _ordered_material_identities(
        legacy
    )
    assert _census_by_color(native) == _census_by_color(legacy)

    native_by_color = _by_color(native)
    legacy_by_color = _by_color(legacy)
    assert native_by_color.keys() == legacy_by_color.keys()
    total_difference_mm2 = 0.0
    for color in native_by_color:
        native_geometry = native_by_color[color]
        legacy_geometry = legacy_by_color[color]
        native_physical = _physical_geometry(
            native_geometry, native.scale_factor
        )
        legacy_physical = _physical_geometry(
            legacy_geometry, legacy.scale_factor
        )
        area_difference_mm2 = abs(
            native_physical.area - legacy_physical.area
        )
        symmetric_difference_mm2 = native_physical.symmetric_difference(
            legacy_physical
        ).area
        boundary_distance_mm = native_physical.boundary.hausdorff_distance(
            legacy_physical.boundary
        )
        assert area_difference_mm2 <= case["max_area_difference_mm2"]
        assert boundary_distance_mm <= MANIFEST["tolerance_mm"]
        total_difference_mm2 += symmetric_difference_mm2
    assert total_difference_mm2 <= case["max_symmetric_difference_mm2"]


def test_native_differential_output_is_stable_across_uncached_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("lumina_svg_core")
    case = next(
        item
        for item in MANIFEST["cases"]
        if item["expected_backend"] == "native"
    )
    path = FIXTURES / str(case["file"])
    processor = _processor()
    fingerprints = []
    for _ in range(3):
        analysis = _run(
            processor, path, backend="native", monkeypatch=monkeypatch
        )
        digest = hashlib.sha256()
        for item in analysis.clipped_shapes:
            digest.update(bytes(item["color"]))
            digest.update(item["geometry"].wkb)
        fingerprints.append(digest.hexdigest())
    assert len(set(fingerprints)) == 1


@pytest.mark.parametrize(
    ("paint_attributes", "fallback_reason"),
    [
        ("fill='rebeccapurple'", "unsupported_color_syntax"),
        ("fill='aliceblue'", "unsupported_color_syntax"),
        ("fill='rgb(50%,0%,0%)'", "unsupported_color_syntax"),
        ("fill='rgba(1,2,3,100%)'", "unsupported_color_syntax"),
        ("fill='rgba(1,2,3,0%)'", "unsupported_color_syntax"),
        ("fill='hsla(0,100%,50%,1)'", "unsupported_color_syntax"),
        ("fill='red' fill-opacity='0%'", "unsupported_opacity_syntax"),
    ],
)
def test_legacy_incompatible_color_syntax_preserves_material_identity_by_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    paint_attributes: str,
    fallback_reason: str,
) -> None:
    pytest.importorskip("lumina_svg_core")
    path = tmp_path / "legacy-color-parity.svg"
    path.write_text(
        "<svg viewBox='0 0 20 10'>"
        f"<rect width='9' height='10' {paint_attributes}/>"
        "<rect x='11' width='9' height='10' fill='blue'/>"
        "</svg>",
        encoding="utf-8",
    )

    selected = _run(
        _processor(), path, backend="native", monkeypatch=monkeypatch
    )
    reference = _run(
        _processor(), path, backend="legacy", monkeypatch=monkeypatch
    )

    assert selected.stage_timings["geometry_backend"] == "legacy"
    assert selected.stage_timings["native_fallback_reason"] == fallback_reason
    assert _ordered_paint_colors(selected) == _ordered_paint_colors(reference)
    assert _ordered_material_identities(selected) == (
        _ordered_material_identities(reference)
    )


@pytest.mark.parametrize(
    "red_geometry",
    [
        (
            "<g fill='green'><path fill='inherit' "
            "d='M0 0H9V10H0Z'/></g>"
        ),
        (
            "<g fill='green'><path style='fill:inherit' "
            "d='M0 0H9V10H0Z'/></g>"
        ),
        (
            "<g fill-rule='evenodd'><path fill='red' fill-rule='inherit' "
            "d='M0 0H9V10H0Z M2 2H7V8H2Z'/></g>"
        ),
    ],
)
def test_explicit_inherit_preserves_legacy_material_and_topology_by_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    red_geometry: str,
) -> None:
    pytest.importorskip("lumina_svg_core")
    path = tmp_path / "legacy-explicit-inherit.svg"
    path.write_text(
        "<svg viewBox='0 0 20 10'>"
        f"{red_geometry}"
        "<rect x='11' width='9' height='10' fill='blue'/>"
        "</svg>",
        encoding="utf-8",
    )

    selected = _run(
        _processor(), path, backend="native", monkeypatch=monkeypatch
    )
    reference = _run(
        _processor(), path, backend="legacy", monkeypatch=monkeypatch
    )

    assert selected.stage_timings["geometry_backend"] == "legacy"
    assert selected.stage_timings["native_fallback_reason"] == (
        "unsupported_legacy_explicit_inherit"
    )
    assert _ordered_paint_colors(selected) == _ordered_paint_colors(reference)
    assert _ordered_material_identities(selected) == (
        _ordered_material_identities(reference)
    )
    assert _census_by_color(selected) == _census_by_color(reference)


@pytest.mark.parametrize(
    "path_data",
    [
        "M10 10H90V90H10V10H50V50H10Z",
        (
            "M50 10 L73.5114 82.3607 L11.9577 37.6393 "
            "L88.0423 37.6393 L26.4886 82.3607 Z"
        ),
    ],
)
def test_self_intersecting_paint_preserves_legacy_topology_by_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    path_data: str,
) -> None:
    pytest.importorskip("lumina_svg_core")
    path = tmp_path / "legacy-self-intersection.svg"
    path.write_text(
        "<svg viewBox='0 0 100 100'>"
        f"<path d='{path_data}' fill='red' fill-rule='nonzero'/>"
        "</svg>",
        encoding="utf-8",
    )

    selected = _run(
        _processor(), path, backend="native", monkeypatch=monkeypatch
    )
    reference = _run(
        _processor(), path, backend="legacy", monkeypatch=monkeypatch
    )

    assert selected.stage_timings["geometry_backend"] == "legacy"
    assert selected.stage_timings["native_fallback_reason"] == (
        "unsupported_topology_collapse"
    )
    assert _ordered_material_identities(selected) == (
        _ordered_material_identities(reference)
    )
    assert _census_by_color(selected) == _census_by_color(reference)
    for color, selected_geometry in _by_color(selected).items():
        assert selected_geometry.equals_exact(
            _by_color(reference)[color], tolerance=1e-9
        )


@pytest.mark.parametrize("viewbox_size", [1.0, 0.001])
def test_small_user_unit_cubic_preserves_legacy_curve_sampling_by_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    viewbox_size: float,
) -> None:
    pytest.importorskip("lumina_svg_core")
    path = tmp_path / "legacy-small-user-unit-cubic.svg"
    path.write_text(
        f"<svg viewBox='0 0 {viewbox_size:g} {viewbox_size:g}'>"
        f"<path d='M0 {viewbox_size:g} C0 0 {viewbox_size / 4:g} 0 "
        f"{viewbox_size / 2:g} 0 C{viewbox_size * 3 / 4:g} 0 "
        f"{viewbox_size:g} 0 {viewbox_size:g} {viewbox_size:g}Z' "
        "fill='red' fill-rule='nonzero'/></svg>",
        encoding="utf-8",
    )

    selected = _run(
        _processor(), path, backend="native", monkeypatch=monkeypatch
    )
    reference = _run(
        _processor(), path, backend="legacy", monkeypatch=monkeypatch
    )

    assert selected.stage_timings["geometry_backend"] == "legacy"
    assert selected.stage_timings["native_fallback_reason"] == (
        "legacy_curve_tolerance_parity"
    )
    assert _ordered_material_identities(selected) == (
        _ordered_material_identities(reference)
    )
    assert _census_by_color(selected) == _census_by_color(reference)
    selected_by_color = _by_color(selected)
    reference_by_color = _by_color(reference)
    assert selected_by_color.keys() == reference_by_color.keys()
    for color, selected_geometry in selected_by_color.items():
        assert selected_geometry.hausdorff_distance(
            reference_by_color[color]
        ) <= 1e-9


@pytest.mark.parametrize(
    "red_geometry",
    [
        "<rect x='1em' y='1' width='8' height='8' fill='red'/>",
        "<rect x='1ex' y='1' width='8' height='8' fill='red'/>",
        "<rect x='1' y='1' width='1em' height='8' fill='red'/>",
        (
            "<g font-size='20'><rect x='1em' y='1' width='8' "
            "height='8' fill='red'/></g>"
        ),
    ],
)
def test_font_relative_geometry_units_preserve_material_census_by_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    red_geometry: str,
) -> None:
    pytest.importorskip("lumina_svg_core")
    path = tmp_path / "font-relative-length.svg"
    path.write_text(
        "<svg viewBox='0 0 100 100'>"
        f"{red_geometry}"
        "<rect x='80' y='1' width='8' height='8' fill='blue'/>"
        "</svg>",
        encoding="utf-8",
    )

    selected = _run(
        _processor(), path, backend="native", monkeypatch=monkeypatch
    )
    reference = _run(
        _processor(), path, backend="legacy", monkeypatch=monkeypatch
    )

    assert selected.stage_timings["geometry_backend"] == "legacy"
    assert selected.stage_timings["native_fallback_reason"] == (
        "unsupported_font_relative_length"
    )
    assert _ordered_paint_colors(selected) == _ordered_paint_colors(reference)
    assert _census_by_color(selected) == _census_by_color(reference)


def test_nested_font_relative_viewport_uses_the_same_legacy_error_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("lumina_svg_core")
    path = tmp_path / "nested-font-relative-length.svg"
    path.write_text(
        "<svg viewBox='0 0 100 100'>"
        "<svg x='1em' y='1' width='8' height='8' viewBox='0 0 8 8'>"
        "<rect width='8' height='8' fill='red'/></svg>"
        "<rect x='80' y='1' width='8' height='8' fill='blue'/>"
        "</svg>",
        encoding="utf-8",
    )

    native_outcome = native_svg_adapter.analyze_native_svg(
        str(path), MANIFEST["target_width_mm"], 0.02
    )
    assert native_outcome == NativeSvgFallback(
        "unsupported_nested_svg", "0.1.1"
    )
    with pytest.raises(ValueError, match="could not convert string to float"):
        _run(_processor(), path, backend="native", monkeypatch=monkeypatch)
    with pytest.raises(ValueError, match="could not convert string to float"):
        _run(_processor(), path, backend="legacy", monkeypatch=monkeypatch)


@pytest.mark.parametrize(
    "document",
    [
        (
            "<svg viewBox='0 0 100 100'>"
            "<svg x='2' y='3' width='10' height='10' viewBox='0 0 10 10' "
            "overflow='visible'><rect x='-5' width='20' height='10' "
            "fill='red'/></svg>"
            "<rect x='80' y='80' width='10' height='10' fill='blue'/>"
            "</svg>"
        ),
        (
            "<svg viewBox='0 0 100 100'>"
            "<svg x='10' y='20' width='40' height='20'>"
            "<rect x='10%' y='20%' width='50%' height='40%' fill='red'/>"
            "</svg>"
            "<rect x='80' y='80' width='10' height='10' fill='blue'/>"
            "</svg>"
        ),
    ],
)
def test_nested_svg_coordinate_contract_uses_whole_document_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    document: str,
) -> None:
    pytest.importorskip("lumina_svg_core")
    path = tmp_path / "nested-coordinate-parity.svg"
    path.write_text(document, encoding="utf-8")

    selected = _run(
        _processor(), path, backend="native", monkeypatch=monkeypatch
    )
    reference = _run(
        _processor(), path, backend="legacy", monkeypatch=monkeypatch
    )

    assert selected.stage_timings["geometry_backend"] == "legacy"
    assert selected.stage_timings["native_fallback_reason"] == (
        "unsupported_nested_svg"
    )
    assert selected.bbox == pytest.approx(reference.bbox, abs=0.001)
    assert selected.scale_factor == pytest.approx(reference.scale_factor)
    assert _ordered_paint_colors(selected) == _ordered_paint_colors(reference)
    assert _census_by_color(selected) == _census_by_color(reference)


def test_nonzero_root_with_nested_svg_uses_same_legacy_empty_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("lumina_svg_core")
    path = tmp_path / "nonzero-root-nested.svg"
    path.write_text(
        "<svg viewBox='10 20 10 10'>"
        "<svg x='2' y='3' width='5' height='4' viewBox='0 0 10 8'>"
        "<rect width='10' height='8' fill='red'/></svg>"
        "</svg>",
        encoding="utf-8",
    )

    outcome = native_svg_adapter.analyze_native_svg(
        str(path), MANIFEST["target_width_mm"], 0.02
    )
    assert outcome == NativeSvgFallback("unsupported_nested_svg", "0.1.1")
    with pytest.raises(ValueError, match="No valid"):
        _run(_processor(), path, backend="native", monkeypatch=monkeypatch)
    with pytest.raises(ValueError, match="No valid"):
        _run(_processor(), path, backend="legacy", monkeypatch=monkeypatch)


@pytest.mark.parametrize(
    ("viewbox", "path_data"),
    [
        (
            "10 20 10 10",
            "M11 21H19V29H11Z M13 23H17V27H13Z",
        ),
        (
            "-10 -20 10 10",
            "M-9 -19H-1V-11H-9Z M-7 -17H-3V-13H-7Z",
        ),
    ],
    ids=["positive-origin", "negative-origin"],
)
@pytest.mark.parametrize("fill_rule", ["evenodd", "nonzero"])
def test_nonzero_root_viewbox_origin_falls_back_with_legacy_parity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    viewbox: str,
    path_data: str,
    fill_rule: str,
) -> None:
    pytest.importorskip("lumina_svg_core")
    path = tmp_path / f"root-origin-{fill_rule}.svg"
    path.write_text(
        f"<svg viewBox='{viewbox}'>"
        f"<path d='{path_data}' fill='#123456' fill-rule='{fill_rule}'/>"
        "</svg>",
        encoding="utf-8",
    )

    outcome = native_svg_adapter.analyze_native_svg(
        str(path), MANIFEST["target_width_mm"], 0.02
    )
    assert outcome == NativeSvgFallback(
        "unsupported_viewbox_origin", "0.1.1"
    )

    selected = _run(
        _processor(), path, backend="native", monkeypatch=monkeypatch
    )
    reference = _run(
        _processor(), path, backend="legacy", monkeypatch=monkeypatch
    )

    assert selected.stage_timings["geometry_backend"] == "legacy"
    assert selected.stage_timings["native_fallback_reason"] == (
        "unsupported_viewbox_origin"
    )
    assert selected.bbox == pytest.approx(reference.bbox, abs=0.001)
    assert selected.scale_factor == pytest.approx(reference.scale_factor)
    assert _ordered_material_identities(selected) == (
        _ordered_material_identities(reference)
    )
    assert _census_by_color(selected) == _census_by_color(reference)


@pytest.mark.parametrize(
    ("reason", "document"),
    [
        (
            "unsupported_percentage_without_viewbox",
            "<svg width='100' height='50'>"
            "<rect x='10%' y='20%' width='50%' height='40%' fill='red'/>"
            "</svg>",
        ),
        (
            "unsupported_root_overflow",
            "<svg width='100' height='100' viewBox='0 0 100 100' "
            "overflow='hidden'>"
            "<rect x='-10' y='-10' width='120' height='120' fill='red'/>"
            "</svg>",
        ),
        (
            "unsupported_root_transform",
            "<svg viewBox='0 0 100 100' transform='translate(50 20)'>"
            "<rect x='10' y='10' width='20' height='20' fill='red'/>"
            "</svg>",
        ),
        (
            "unsupported_root_transform",
            "<svg viewBox='0 0 100 100' transform='scale(2)'>"
            "<rect x='10' y='10' width='20' height='20' fill='red'/>"
            "</svg>",
        ),
        (
            "unsupported_root_transform",
            "<svg viewBox='0 0 100 100' transform='rotate(30)'>"
            "<rect x='10' y='10' width='20' height='20' fill='red'/>"
            "</svg>",
        ),
        (
            "unsupported_root_transform",
            "<svg viewBox='0 0 100 100' "
            "transform='matrix(1 0.2 0.3 1 5 7)'>"
            "<rect x='10' y='10' width='20' height='20' fill='red'/>"
            "</svg>",
        ),
        (
            "unsupported_root_position",
            "<svg viewBox='0 0 100 100' x='50' y='20'>"
            "<rect x='10' y='10' width='20' height='20' fill='red'/>"
            "</svg>",
        ),
    ],
    ids=[
        "percent-without-viewbox",
        "root-overflow",
        "root-translate",
        "root-scale",
        "root-rotate",
        "root-matrix",
        "root-position",
    ],
)
def test_root_layout_contract_falls_back_with_legacy_parity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reason: str,
    document: str,
) -> None:
    pytest.importorskip("lumina_svg_core")
    path = tmp_path / f"{reason}.svg"
    path.write_text(document, encoding="utf-8")

    outcome = native_svg_adapter.analyze_native_svg(
        str(path), MANIFEST["target_width_mm"], 0.02
    )
    assert outcome == NativeSvgFallback(reason, "0.1.1")
    selected = _run(
        _processor(), path, backend="native", monkeypatch=monkeypatch
    )
    reference = _run(
        _processor(), path, backend="legacy", monkeypatch=monkeypatch
    )

    assert selected.stage_timings["geometry_backend"] == "legacy"
    assert selected.stage_timings["native_fallback_reason"] == reason
    assert selected.bbox == pytest.approx(reference.bbox, abs=0.001)
    assert selected.scale_factor == pytest.approx(reference.scale_factor)
    assert _ordered_material_identities(selected) == (
        _ordered_material_identities(reference)
    )
    assert _census_by_color(selected) == _census_by_color(reference)


def test_original_quadratic_source_falls_back_with_legacy_parity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("lumina_svg_core")
    path = tmp_path / "quadratic-chain.svg"
    path.write_text(
        "<svg viewBox='0 0 100 100'>"
        "<path d='M0 0Q0 30 0 50T90 50L100 0Z' fill='red'/>"
        "</svg>",
        encoding="utf-8",
    )

    outcome = native_svg_adapter.analyze_native_svg(
        str(path), MANIFEST["target_width_mm"], 0.02
    )
    assert outcome == NativeSvgFallback(
        "unsupported_quadratic", "0.1.1"
    )
    selected = _run(
        _processor(), path, backend="native", monkeypatch=monkeypatch
    )
    reference = _run(
        _processor(), path, backend="legacy", monkeypatch=monkeypatch
    )

    assert selected.stage_timings["geometry_backend"] == "legacy"
    assert selected.stage_timings["native_fallback_reason"] == (
        "unsupported_quadratic"
    )
    assert selected.bbox == pytest.approx(reference.bbox, abs=0.001)
    assert selected.scale_factor == pytest.approx(reference.scale_factor)
    assert _ordered_material_identities(selected) == (
        _ordered_material_identities(reference)
    )
    assert _census_by_color(selected) == _census_by_color(reference)


@pytest.mark.parametrize(
    "ancestor",
    ["root", "group", "defs"],
)
def test_inherited_clip_rule_falls_back_with_legacy_parity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    ancestor: str,
) -> None:
    pytest.importorskip("lumina_svg_core")
    clip = (
        "<clipPath id='c'><path d='M10 10H90V90H10Z "
        "M30 30H70V70H30Z'/></clipPath>"
    )
    if ancestor == "root":
        document = (
            "<svg viewBox='0 0 100 100' clip-rule='evenodd'>"
            f"<defs>{clip}</defs>"
            "<rect width='100' height='100' fill='red' "
            "clip-path='url(#c)'/></svg>"
        )
    elif ancestor == "group":
        document = (
            "<svg viewBox='0 0 100 100'><g clip-rule='evenodd'>"
            f"<defs>{clip}</defs>"
            "<rect width='100' height='100' fill='red' "
            "clip-path='url(#c)'/></g></svg>"
        )
    else:
        document = (
            "<svg viewBox='0 0 100 100'>"
            f"<defs clip-rule='evenodd'>{clip}</defs>"
            "<rect width='100' height='100' fill='red' "
            "clip-path='url(#c)'/></svg>"
        )
    path = tmp_path / f"inherited-clip-rule-{ancestor}.svg"
    path.write_text(document, encoding="utf-8")

    outcome = native_svg_adapter.analyze_native_svg(
        str(path), MANIFEST["target_width_mm"], 0.02
    )
    assert outcome == NativeSvgFallback(
        "unsupported_clip_rule_inheritance", "0.1.1"
    )
    selected = _run(
        _processor(), path, backend="native", monkeypatch=monkeypatch
    )
    reference = _run(
        _processor(), path, backend="legacy", monkeypatch=monkeypatch
    )

    assert selected.stage_timings["geometry_backend"] == "legacy"
    assert selected.stage_timings["native_fallback_reason"] == (
        "unsupported_clip_rule_inheritance"
    )
    assert selected.bbox == pytest.approx(reference.bbox, abs=0.001)
    assert selected.scale_factor == pytest.approx(reference.scale_factor)
    assert _census_by_color(selected) == _census_by_color(reference)


def test_direct_clip_rule_remains_native_with_legacy_parity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("lumina_svg_core")
    path = tmp_path / "direct-clip-rule.svg"
    path.write_text(
        "<svg viewBox='0 0 100 100'><defs>"
        "<clipPath id='c' clip-rule='evenodd'>"
        "<path d='M10 10H90V90H10Z M30 30H70V70H30Z'/>"
        "</clipPath></defs>"
        "<rect width='100' height='100' fill='red' "
        "clip-path='url(#c)'/></svg>",
        encoding="utf-8",
    )

    selected = _run(
        _processor(), path, backend="native", monkeypatch=monkeypatch
    )
    reference = _run(
        _processor(), path, backend="legacy", monkeypatch=monkeypatch
    )

    assert selected.stage_timings["geometry_backend"] == "native"
    assert _census_by_color(selected) == _census_by_color(reference)


@pytest.mark.parametrize(
    ("fill_rule", "second_path"),
    [
        ("evenodd", "M10 10H90V90H10Z"),
        ("nonzero", "M10 10V90H90V10Z"),
    ],
)
def test_native_empty_normalization_falls_back_with_legacy_parity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fill_rule: str,
    second_path: str,
) -> None:
    pytest.importorskip("lumina_svg_core")
    path = tmp_path / f"native-empty-{fill_rule}.svg"
    path.write_text(
        "<svg viewBox='0 0 100 100'>"
        f"<path d='M10 10H90V90H10Z {second_path}' fill='red' "
        f"fill-rule='{fill_rule}'/></svg>",
        encoding="utf-8",
    )

    outcome = native_svg_adapter.analyze_native_svg(
        str(path), MANIFEST["target_width_mm"], 0.02
    )
    assert outcome == NativeSvgFallback(
        "legacy_empty_geometry_parity", "0.1.1"
    )
    selected = _run(
        _processor(), path, backend="native", monkeypatch=monkeypatch
    )
    reference = _run(
        _processor(), path, backend="legacy", monkeypatch=monkeypatch
    )

    assert selected.stage_timings["geometry_backend"] == "legacy"
    assert selected.stage_timings["native_fallback_reason"] == (
        "legacy_empty_geometry_parity"
    )
    assert _census_by_color(selected) == _census_by_color(reference)


def test_incompatible_multi_component_postprocess_falls_back_to_legacy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("lumina_svg_core")
    path = tmp_path / "multi-component-postprocess.svg"
    path.write_text(
        "<svg viewBox='0 0 100 100'><path fill='red' d='"
        "M55.52831753041504 66.3046688201546 "
        "L55.52831753041504 72.93040052353409 "
        "L47.339743941791944 73.63466187069454 "
        "L53.28877361479757 75.44200987424085 "
        "L53.2656320529904 75.07386941278561 "
        "L73.09976273935555 73.8270823593993 "
        "L73.43087174116687 79.09442869213571 "
        "L75.37109811756244 74.24712851807058 Z "
        "M33.18047101838028 57.359507658012994 "
        "L28.90746374836685 68.03483355590957 "
        "L44.810623640889176 72.86630118368933 "
        "L44.810623640889176 62.01470293567081 Z'/></svg>",
        encoding="utf-8",
    )

    outcome = native_svg_adapter.analyze_native_svg(
        str(path), MANIFEST["target_width_mm"], 0.02
    )
    assert outcome == NativeSvgFallback(
        "legacy_contour_normalization_incompatible", "0.1.1"
    )
    selected = _run(
        _processor(), path, backend="native", monkeypatch=monkeypatch
    )
    reference = _run(
        _processor(), path, backend="legacy", monkeypatch=monkeypatch
    )

    assert selected.stage_timings["geometry_backend"] == "legacy"
    assert selected.stage_timings["native_fallback_reason"] == (
        "legacy_contour_normalization_incompatible"
    )
    assert _census_by_color(selected) == _census_by_color(reference)


@pytest.mark.parametrize(
    "path_data",
    [
        "M10 10H90V90H10Z M49.98 20H50.02V80H49.98Z",
        "M10 10H90V90H50.02V20H49.98V90H10Z",
        (
            "M10 10 L90 10 L90 90 L39.83308898930126 90 "
            "L39.79082728731835 82.16007974157606 "
            "L39.69503373258287 90 L10 90 Z"
        ),
    ],
    ids=["narrow-hole", "narrow-notch", "asymmetric-slanted-notch"],
)
def test_changed_legacy_contour_close_falls_back_with_exact_legacy_parity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    path_data: str,
) -> None:
    pytest.importorskip("lumina_svg_core")
    path = tmp_path / "legacy-contour-close.svg"
    path.write_text(
        "<svg viewBox='0 0 100 100'>"
        f"<path fill='red' fill-rule='evenodd' d='{path_data}'/>"
        "</svg>",
        encoding="utf-8",
    )

    selected = _run(
        _processor(), path, backend="native", monkeypatch=monkeypatch
    )
    reference = _run(
        _processor(), path, backend="legacy", monkeypatch=monkeypatch
    )

    assert selected.stage_timings["geometry_backend"] == "legacy"
    assert selected.stage_timings["native_fallback_reason"] == (
        "legacy_contour_normalization_incompatible"
    )
    assert _census_by_color(selected) == _census_by_color(reference)
    selected_by_color = _by_color(selected)
    reference_by_color = _by_color(reference)
    for color in selected_by_color:
        assert selected_by_color[color].equals(reference_by_color[color])


def test_subthreshold_independent_paint_is_dropped_without_losing_parity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("lumina_svg_core")
    path = tmp_path / "subthreshold-independent-paint.svg"
    path.write_text(
        "<svg viewBox='0 0 100 100'>"
        "<rect width='50' height='50' fill='red'/>"
        "<rect x='90' y='90' width='.005' height='.005' fill='blue'/>"
        "</svg>",
        encoding="utf-8",
    )

    selected = _run(
        _processor(), path, backend="native", monkeypatch=monkeypatch
    )
    reference = _run(
        _processor(), path, backend="legacy", monkeypatch=monkeypatch
    )

    assert selected.stage_timings["geometry_backend"] == "native"
    assert selected.stage_timings["native_legacy_area_filter_identity"] is False
    assert _ordered_paint_colors(selected) == [(255, 0, 0)]
    assert _ordered_material_identities(selected) == (
        _ordered_material_identities(reference)
    )
    assert _census_by_color(selected) == _census_by_color(reference)


def test_macro_viewbox_uses_legacy_scale_clamp_without_losing_material(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("lumina_svg_core")
    path = tmp_path / "macro-viewbox-area-clamp.svg"
    path.write_text(
        "<svg viewBox='0 0 1000000000 1000000000'>"
        "<rect width='500000000' height='500000000' fill='red'/>"
        "<rect x='900000000' y='900000000' width='100000' "
        "height='50000' fill='blue'/></svg>",
        encoding="utf-8",
    )

    selected = _run(
        _processor(), path, backend="native", monkeypatch=monkeypatch
    )
    reference = _run(
        _processor(), path, backend="legacy", monkeypatch=monkeypatch
    )

    assert selected.stage_timings["geometry_backend"] == "native"
    assert _ordered_paint_colors(selected) == [(255, 0, 0), (0, 0, 255)]
    assert _ordered_paint_colors(selected) == _ordered_paint_colors(reference)
    assert _ordered_material_identities(selected) == (
        _ordered_material_identities(reference)
    )
    assert _census_by_color(selected) == _census_by_color(reference)
