"""Optional SVG compensation remains identical across product entry points."""

from __future__ import annotations

import inspect
import pickle
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from api.schemas.converter import ConvertGenerateRequest, ConvertPreviewRequest
from core import converter
from core import vector_engine
from core.pipeline import vector_branch


SETTINGS = {
    "svg_hole_compensation_enabled": True,
    "svg_hole_max_area_mm2": 0.75,
    "svg_hole_max_width_mm": 0.12,
}


@pytest.mark.parametrize("model", [ConvertPreviewRequest, ConvertGenerateRequest])
def test_request_preserves_compensation_settings(model):
    request = model(lut_name="test.npy", **SETTINGS)
    assert {key: request.model_dump().get(key) for key in SETTINGS} == SETTINGS


@pytest.mark.parametrize("model", [ConvertPreviewRequest, ConvertGenerateRequest])
def test_request_defaults_leave_original_svg_unchanged(model):
    values = model(lut_name="test.npy").model_dump()
    assert values.get("svg_hole_compensation_enabled") is False
    assert values.get("svg_hole_max_area_mm2") == 0.5
    assert values.get("svg_hole_max_width_mm") == 0.1


@pytest.mark.parametrize("field", ["svg_hole_max_area_mm2", "svg_hole_max_width_mm"])
@pytest.mark.parametrize("value", [-0.01, float("nan"), float("inf")])
def test_request_rejects_nonphysical_compensation_threshold(field, value):
    with pytest.raises(ValidationError):
        ConvertPreviewRequest(lut_name="test.npy", **{field: value})


def test_lut_vector_factory_forwards_compensation(monkeypatch):
    processor = SimpleNamespace()
    monkeypatch.setattr(vector_engine, "VectorProcessor", lambda *a, **kw: processor)
    result = vector_branch._build_vector_processor(
        {"actual_lut_path": "test.npy", **SETTINGS},
        fallback_color_mode="4-Color (RYBW)",
    )
    assert {key: getattr(result, key, None) for key in SETTINGS} == SETTINGS


@pytest.mark.parametrize("entry", [
    converter.generate_preview_cached,
    converter.convert_image_to_3d,
    converter.generate_final_model,
])
def test_public_converter_accepts_optional_compensation_settings(entry):
    parameters = inspect.signature(entry).parameters
    assert all(key in parameters for key in SETTINGS)
    assert parameters["svg_hole_compensation_enabled"].default is False


def test_preview_wrapper_forwards_settings_without_modifying_them(monkeypatch):
    captured = {}

    def preview(ctx):
        captured.update(ctx)
        return {"display_image": "image", "cache": {}, "status_msg": "ok"}

    monkeypatch.setattr(converter, "run_preview_pipeline", preview)
    result = converter.generate_preview_cached(
        "image.svg", "test.npy", 220.0, "4-Color (RYBW)", **SETTINGS,
    )
    assert result[0] == "image"
    assert {key: captured.get(key) for key in SETTINGS} == SETTINGS


@pytest.mark.parametrize("changes, expected", [
    ({}, True),
    ({"svg_hole_compensation_enabled": False}, False),
    ({"svg_hole_max_area_mm2": 0.01}, False),
    ({"svg_hole_max_width_mm": 0.01}, False),
])
def test_generation_reuses_only_identical_compensation_settings(changes, expected):
    from api.routers.converter.generate import _preview_analysis_params_match
    from config import ModelingMode

    request = ConvertGenerateRequest(lut_name="test.npy", modeling_mode="vector", **SETTINGS)
    cache = {**request.model_dump(), "target_width_mm": 220.0, "material_source": "lut"}
    cache.update(changes)
    matches, _ = _preview_analysis_params_match(
        cache=cache, request=request, core_modeling_mode=ModelingMode.VECTOR,
        session_material_source="lut", target_width_mm=220.0,
    )
    assert matches is expected


def test_old_uncompensated_preview_remains_reusable_when_disabled():
    from api.routers.converter.generate import _preview_analysis_params_match
    from config import ModelingMode

    request = ConvertGenerateRequest(lut_name="test.npy", modeling_mode="vector")
    cache = {**request.model_dump(), "target_width_mm": 220.0, "material_source": "lut"}
    for field in SETTINGS:
        cache.pop(field)
    matches, _ = _preview_analysis_params_match(
        cache=cache, request=request, core_modeling_mode=ModelingMode.VECTOR,
        session_material_source="lut", target_width_mm=220.0,
    )
    assert matches


def test_missing_pure_cache_never_serializes_compensated_analysis(tmp_path):
    path = tmp_path / "empty.svg"
    path.write_text("<svg/>", encoding="utf-8")
    processor = SimpleNamespace(
        sampling_precision=1.0, svg_hole_compensation_enabled=True,
    )
    vector_engine._VECTOR_PARSE_CLIP_CACHE.clear()
    assert vector_branch._build_vector_parse_cache_artifacts(
        str(path), 220.0, processor, SimpleNamespace(),
    ) is None


def test_compensated_preview_serializes_only_pure_geometry_and_provenance(tmp_path, monkeypatch):
    from shapely.geometry import box

    path = tmp_path / "source.svg"
    path.write_text("<svg/>", encoding="utf-8")
    processor = SimpleNamespace(
        sampling_precision=0.02, expand_stroke_to_fill=True,
        gradient_color_bands=16, svg_hole_compensation_enabled=True,
    )
    key = vector_engine._vector_parse_clip_cache_key(
        str(path), target_width_mm=220.0, sampling_precision=0.02,
        expand_stroke_to_fill=True, gradient_color_bands=16,
    )
    source = box(0, 0, 1, 1)
    entry = {
        "shape_data": [{"poly": source, "color": (1, 2, 3)}],
        "clipped_shapes": [{"geometry": source, "color": (1, 2, 3)}],
        "silhouette": source, "image_vectorizer_bounds": source.bounds,
        "scale_factor": 220.0, "bbox": source.bounds,
        "parse_warnings": [], "geometry_stage_timings": {"geometry_backend": "native"},
    }
    monkeypatch.setattr(vector_engine, "_VECTOR_PARSE_CLIP_CACHE", {key: entry})
    # The supplied full analysis deliberately has no geometry fields: the pure
    # cache must be the source, regardless of what compensation later produced.
    artifacts = vector_branch._build_vector_parse_cache_artifacts(
        str(path), 220.0, processor, SimpleNamespace(),
    )
    payload = pickle.loads(artifacts["vector_parse_clip_cache_blob"])
    assert payload["cache_key"] == key
    assert payload["entry"]["silhouette"].equals(source)
    assert artifacts["vector_parse_clip_cache_provenance"] == payload["provenance"]


@pytest.mark.parametrize("entry, step", [
    ("run_preview_pipeline", "p01_preview_validation"),
    ("run_raster_pipeline", "s01_input_validation"),
])
def test_nonvector_pipeline_cannot_silently_ignore_requested_compensation(monkeypatch, entry, step):
    from core.pipeline import coordinator

    monkeypatch.setattr(getattr(coordinator, step), "run", lambda ctx: ctx)
    result = getattr(coordinator, entry)({
        "image_path": "picture.png", "modeling_mode": "high-fidelity",
        **SETTINGS,
    })
    assert "SVG hole compensation requires" in result.get("error", "")


def test_api_returns_actionable_422_for_unsupported_compensation_scope():
    from fastapi import HTTPException
    from api.routers.converter import common

    with pytest.raises(HTTPException) as error:
        common._validate_svg_hole_compensation(
            enabled=True, image_path="picture.svg", modeling_mode="high-fidelity",
        )
    assert error.value.status_code == 422
    assert "vector mode" in str(error.value.detail)


def test_bug_report_index_records_compensation_strength(tmp_path):
    from api.feedback_index import generate_index_markdown

    text = generate_index_markdown(
        "LUM-test", tmp_path,
        {"context": {"advanced_params": {"generation": SETTINGS}}},
    )
    for field, value in SETTINGS.items():
        assert f"{field}: {value}" in text


def test_schema4_composite_patch_retains_exact_rgba_and_contributing_paints():
    from shapely.geometry import Polygon, box

    from core.native_svg_adapter import NativeSvgPaintContributor
    from core.svg_hole_compensation import compensate_svg_regions

    contributors = (
        NativeSvgPaintContributor(0, 4, "fill", 0.25),
        NativeSvgPaintContributor(1, 7, "fill", 0.5),
    )
    rgba = (0.123456, 0.456789, 0.876543, 0.75)
    regions = [
        {
            "geometry": geometry, "color": (31, 116, 224),
            "rgba": (31, 116, 224, 191), "rgba_f64": rgba,
            "source_kind": "composite", "native_paint_id": None,
            "native_draw_order": index, "native_paint_index": index,
            "native_paint_contributors": contributors,
        }
        for index, geometry in enumerate([
            box(0, 0, 2, 0.8), box(0, 1.2, 2, 2),
            box(0, 0.8, 0.8, 1.2), box(1.2, 0.8, 2, 1.2),
        ])
    ]
    result = compensate_svg_regions(
        regions, scale_factor=1.0,
        silhouette=Polygon(box(0, 0, 2, 2).exterior, [box(0.8, 0.8, 1.2, 1.2).exterior]),
    )
    patch = result.patches[0]
    assert patch["rgba_f64"] is rgba
    assert patch["compensation_source"]["native_paint_id"] is None
    assert patch["compensation_source"]["native_draw_order"] == 0
    assert patch["compensation_source"]["native_paint_contributors"] is contributors
