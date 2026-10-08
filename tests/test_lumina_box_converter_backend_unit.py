"""Focused contracts for Lumina Box material-archive conversion plumbing."""

from __future__ import annotations

import json
import os
from hashlib import sha256
from pathlib import Path

import numpy as np
import pytest
from fastapi import HTTPException

from core.km_xyz import (
    KM_XYZ_COLOR_BRIDGE_ID,
    KM_XYZ_FIT_OBJECTIVE_ID,
    KM_XYZ_MEASUREMENT_PROTOCOL_ID,
    KM_XYZ_MEASUREMENT_REFLECTION_BOUNDARY_ID,
    KM_XYZ_MODEL_ID,
)
from core.material_color_solver import MaterialParams


def _paired_archive_payloads(
    *,
    measurement_thickness_offset_mm: float = 0.0,
) -> tuple[dict[str, object], dict[str, object]]:
    samples = [
        {
            "thickness_mm": thickness_mm,
            "transmittance_percent_xyz": transmittance,
            "reflectance_percent_xyz": reflectance,
        }
        for thickness_mm, transmittance, reflectance in (
            (0.08, [83.0, 79.0, 75.0], [22.0, 28.0, 34.0]),
            (0.16, [67.0, 61.0, 56.0], [25.0, 31.0, 37.0]),
            (0.32, [42.0, 35.0, 30.0], [30.0, 36.0, 42.0]),
        )
    ]
    predictions = [
        {
            "thickness_mm": sample["thickness_mm"],
            "transmittance": {
                "measured_percent_xyz": sample["transmittance_percent_xyz"],
                "predicted_percent_xyz": sample["transmittance_percent_xyz"],
                "residual_percentage_points_xyz": [0.0, 0.0, 0.0],
            },
            "reflectance": {
                "measured_percent_xyz": sample["reflectance_percent_xyz"],
                "predicted_percent_xyz": sample["reflectance_percent_xyz"],
                "residual_percentage_points_xyz": [0.0, 0.0, 0.0],
            },
        }
        for sample in samples
    ]
    return (
        {
            "protocol_id": KM_XYZ_MEASUREMENT_PROTOCOL_ID,
            "value_scale": "percent_0_100",
            "measurement_backing_percent_xyz": [19.8, 19.7, 24.7],
            "samples": samples,
        },
        {
            "parameters": {"K": [0.5, 0.6, 0.7], "S": [1.0, 1.1, 1.2], "unit": "mm^-1"},
            "sample_predictions": predictions,
            "residual_summary": {
                "transmittance_channel_rmse_percentage_points_xyz": [0.0, 0.0, 0.0],
                "reflectance_channel_rmse_percentage_points_xyz": [0.0, 0.0, 0.0],
                "channel_rmse_percentage_points_xyz": [0.0, 0.0, 0.0],
                "transmittance_rmse_percentage_points": 0.0,
                "reflectance_rmse_percentage_points": 0.0,
                "overall_rmse_percentage_points": 0.0,
                "max_abs_residual_percentage_points": 0.0,
                "max_abs_location": {
                    "thickness_mm": 0.08,
                    "modality": "transmittance",
                    "channel": "X",
                    "signed_residual_percentage_points": 0.0,
                },
            },
            "diagnostics": {
                "success": True,
                "message": "fixture converged",
                "nfev": 1,
                "start_count": 24,
                "robust_objective": 0.0,
                "jacobian_condition": 1.0,
                "measurement_thickness_offset_mm": measurement_thickness_offset_mm,
                "objective_id": KM_XYZ_FIT_OBJECTIVE_ID,
                "objective_config": {"pair_weighting": "equal"},
                "channels": [
                    {
                        "channel": channel,
                        "transmittance_rmse": 0.0,
                        "reflectance_rmse": 0.0,
                        "warnings": [],
                    }
                    for channel in ("X", "Y", "Z")
                ],
                "warnings": [],
            },
            "measurement_backing_base_percent_xyz": [19.8, 19.7, 24.7],
            "measurement_backing_scale": 1.0,
            "measurement_thickness_offset_mm": measurement_thickness_offset_mm,
            "measurement_backing_effective_percent_xyz": [19.8, 19.7, 24.7],
            "measurement_reflection_boundary_id": (
                KM_XYZ_MEASUREMENT_REFLECTION_BOUNDARY_ID
            ),
            "fit_quality": {
                "savable": True,
                "reasons": [],
                "thresholds": {
                    "modality_rmse_percentage_points": 10.0,
                    "overall_rmse_percentage_points": 10.0,
                    "max_abs_residual_percentage_points": 20.0,
                },
            },
            "estimated_effective_d65_10_xyz_relative": [0.3, 0.36, 0.42],
            "estimated_reflectance_thickness_mm": 0.32,
            "estimated_rgb": [64, 108, 145],
            "warnings": [],
        },
    )


def _stage_a_material(name: str = "stage-a") -> MaterialParams:
    return MaterialParams(
        name=name,
        directory_name=name,
        E=np.asarray([0.4, 0.3, 0.2], dtype=np.float64),
        k=np.asarray([2.0, 3.0, 4.0], dtype=np.float64),
        C0_white=np.ones(3, dtype=np.float64),
        estimated_rgb=np.asarray([120, 100, 80], dtype=np.uint8),
    )


def _lumina_material(
    name: str = "lumina",
    *,
    protocol: str = KM_XYZ_MEASUREMENT_PROTOCOL_ID,
) -> MaterialParams:
    return MaterialParams(
        name=name,
        directory_name=name,
        E=np.zeros(3, dtype=np.float64),
        k=np.zeros(3, dtype=np.float64),
        C0_white=np.ones(3, dtype=np.float64),
        estimated_rgb=np.asarray([128, 128, 128], dtype=np.uint8),
        optical_model_id=KM_XYZ_MODEL_ID,
        km_K=np.asarray([0.5, 0.6, 0.7], dtype=np.float64),
        km_S=np.asarray([1.0, 1.1, 1.2], dtype=np.float64),
        coefficient_unit="mm^-1",
        measurement_protocol_id=protocol,
        color_bridge_id=KM_XYZ_COLOR_BRIDGE_ID,
        archive_revision_id="revision-1",
    )


def _write_archive(
    root: Path,
    directory_name: str,
    *,
    profile_kind: str | None,
) -> None:
    material_dir = root / directory_name
    material_dir.mkdir(parents=True)
    payload: dict[str, object] = {"material_name": directory_name}
    if profile_kind is not None:
        payload["profile_kind"] = profile_kind
    (material_dir / "material.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )


def _write_valid_lumina_archive(
    root: Path,
    name: str,
    *,
    measurement_thickness_offset_mm: float = 0.0,
) -> Path:
    """Create a persisted three-file Lumina Box archive for entry validation."""

    from core.lumina_box_archive import save_lumina_box_material_archive

    measurement_payload, fit_payload = _paired_archive_payloads(
        measurement_thickness_offset_mm=measurement_thickness_offset_mm
    )
    saved = save_lumina_box_material_archive(
        material_name=name,
        brand=None,
        material_type=None,
        notes=None,
        measurement_payload=measurement_payload,
        fit_payload=fit_payload,
        materials_dir=str(root),
    )
    return Path(saved.archive_path).parent


def test_diffuser_scale_is_archival_acquisition_data_not_runtime_ks(
    tmp_path: Path,
) -> None:
    """Runtime material parameters retain only the fitted K/S vectors."""
    from core.material_lut_synthesis import load_material_params

    _write_valid_lumina_archive(
        tmp_path,
        "diffuser-scale",
        measurement_thickness_offset_mm=0.125,
    )
    material = load_material_params("diffuser-scale", materials_dir=str(tmp_path))
    assert material.km_K.tolist() == pytest.approx([0.5, 0.6, 0.7])
    assert material.km_S.tolist() == pytest.approx([1.0, 1.1, 1.2])
    assert not hasattr(material, "measurement_backing_scale")
    assert not hasattr(material, "measurement_thickness_offset_mm")


def _replace_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _refresh_sidecar_hash(
    material_path: Path,
    *,
    sidecar_key: str,
    sidecar_path: Path,
) -> None:
    material_payload = json.loads(material_path.read_text(encoding="utf-8"))
    material_payload["sidecar_integrity"][sidecar_key]["sha256"] = sha256(
        sidecar_path.read_bytes()
    ).hexdigest()
    _replace_json(material_path, material_payload)


def test_profile_contract_defaults_legacy_archive_to_stage_a_and_rejects_kind_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An old archive/request remains Stage A; it cannot be requested as KM."""

    from core.pipeline import _input_validation_common as validation

    _write_archive(tmp_path, "legacy", profile_kind=None)
    monkeypatch.setattr(validation, "MATERIALS_DIR", tmp_path)
    monkeypatch.setattr(
        validation,
        "load_materials",
        lambda selected_materials: [_stage_a_material("legacy")],
    )

    kind, materials = validation.load_and_validate_material_archive_profile(
        ["legacy"],
        profile_kind=None,
    )

    assert kind == "stage_a"
    assert materials[0].optical_model_id == "beer_lambert/v1"
    with pytest.raises(validation.MaterialArchiveProfileError) as exc_info:
        validation.load_and_validate_material_archive_profile(
            ["legacy"],
            profile_kind="lumina_box",
        )
    assert exc_info.value.error_type == "material_profile_kind_mismatch"


def test_profile_contract_rejects_mixed_models_and_km_protocols(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lumina selections require one KM model and one measurement protocol."""

    from core.pipeline import _input_validation_common as validation

    _write_archive(tmp_path, "lumina-a", profile_kind="lumina_box")
    _write_archive(tmp_path, "lumina-b", profile_kind="lumina_box")
    monkeypatch.setattr(validation, "MATERIALS_DIR", tmp_path)
    monkeypatch.setattr(
        validation,
        "validate_lumina_box_material_archive",
        lambda material_dir, archive_payload: True,
    )

    monkeypatch.setattr(
        validation,
        "load_materials",
        lambda selected_materials: [_lumina_material("lumina-a"), _stage_a_material("legacy")],
    )
    with pytest.raises(validation.MaterialArchiveProfileError) as mixed_models:
        validation.load_and_validate_material_archive_profile(
            ["lumina-a", "lumina-b"],
            profile_kind="lumina_box",
        )
    assert "incompatible optical model" in str(mixed_models.value)

    monkeypatch.setattr(
        validation,
        "load_materials",
        lambda selected_materials: [
            _lumina_material("lumina-a"),
            _lumina_material("lumina-b", protocol="other-protocol/v1"),
        ],
    )
    with pytest.raises(validation.MaterialArchiveProfileError) as mixed_protocols:
        validation.load_and_validate_material_archive_profile(
            ["lumina-a", "lumina-b"],
            profile_kind="lumina_box",
        )
    assert "measurement protocol" in str(mixed_protocols.value)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "unknown",
        "sidecar_mismatch",
    ],
)
def test_lumina_converter_entry_rejects_missing_unknown_or_inconsistent_bridge(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    """The converter must not let runtime defaults accept invalid bridge data."""

    from core.lumina_box_archive import (
        LUMINA_BOX_MEASUREMENTS_FILENAME,
        LUMINA_BOX_PARAMETERS_FILENAME,
    )
    from core.pipeline import _input_validation_common as validation

    material_dir = _write_valid_lumina_archive(tmp_path, f"bridge-{mutation}")
    material_path = material_dir / "material.json"
    if mutation == "missing":
        material_payload = json.loads(material_path.read_text(encoding="utf-8"))
        del material_payload["color_bridge_id"]
        _replace_json(material_path, material_payload)
    elif mutation == "unknown":
        material_payload = json.loads(material_path.read_text(encoding="utf-8"))
        material_payload["color_bridge_id"] = "unknown-bridge/v1"
        _replace_json(material_path, material_payload)
    else:
        measurements_path = material_dir / LUMINA_BOX_MEASUREMENTS_FILENAME
        measurements_payload = json.loads(measurements_path.read_text(encoding="utf-8"))
        measurements_payload["color_bridge_id"] = "other-bridge/v1"
        _replace_json(measurements_path, measurements_payload)
        _refresh_sidecar_hash(
            material_path,
            sidecar_key="measurements",
            sidecar_path=measurements_path,
        )
        # Keep the second sidecar untouched: this is a three-file divergence,
        # not merely a stale checksum.
        assert (material_dir / LUMINA_BOX_PARAMETERS_FILENAME).is_file()

    monkeypatch.setattr(validation, "MATERIALS_DIR", tmp_path)
    monkeypatch.setattr(
        validation,
        "load_materials",
        lambda selected_materials: [_lumina_material(selected_materials[0])],
    )

    with pytest.raises(validation.MaterialArchiveProfileError) as exc_info:
        validation.load_and_validate_material_archive_profile(
            [material_dir.name],
            profile_kind="lumina_box",
        )
    assert "bridge/integrity" in str(exc_info.value)


def test_schema_session_reuse_and_source_guard_preserve_profile_kind() -> None:
    """Generate inherits its preview kind, but never changes it in-place."""

    from api.routers.converter.common import _resolve_material_profile_kind
    from api.routers.converter.generate import _resolve_session_material_profile_kind
    from api.schemas.converter import ConvertGenerateRequest, ConvertPreviewRequest

    assert (
        ConvertPreviewRequest.model_validate({"lut_name": "test-lut"})
        .material_profile_kind
        == "stage_a"
    )
    request = ConvertGenerateRequest.model_validate({"lut_name": "test-lut"})
    assert request.material_profile_kind == "stage_a"
    assert "material_profile_kind" not in request.model_fields_set

    session_data = {"material_profile_kind": "lumina_box"}
    assert _resolve_session_material_profile_kind(
        session_data,
        request,
        material_source="material_archive",
    ) == "lumina_box"

    mismatched_request = ConvertGenerateRequest.model_validate(
        {"lut_name": "test-lut", "material_profile_kind": "stage_a"}
    )
    with pytest.raises(HTTPException) as mismatch:
        _resolve_session_material_profile_kind(
            session_data,
            mismatched_request,
            material_source="material_archive",
        )
    assert mismatch.value.status_code == 422

    with pytest.raises(HTTPException) as source_error:
        _resolve_material_profile_kind(
            material_source="lut",
            material_profile_kind="stage_a",
        )
    assert source_error.value.status_code == 422


def test_standard_large_puzzle_and_color_card_cache_profile_guard() -> None:
    """A cache's optical profile is an archive identity, not a size setting."""

    from api.routers.converter.color_card import _require_color_card_cache_metadata
    from api.routers.converter.common import (
        MATERIAL_ARCHIVE_PROFILE_CACHE_INCOMPATIBLE_DETAIL,
        _require_material_archive_profile_cache_consistency,
    )
    from api.routers.converter.generate import _require_preview_cache_for_generate
    from api.routers.converter.puzzle import _require_puzzle_cache

    legacy_session = {
        "material_source": "material_archive",
        "preview_cache": {},
    }
    # _require_preview_cache_for_generate is shared by standard and large
    # format generation. Missing session/cache markers were created before
    # Lumina Box and remain a Stage A pair in all four paths.
    assert _require_material_archive_profile_cache_consistency(
        legacy_session,
        legacy_session["preview_cache"],
    ) == "stage_a"
    assert _require_preview_cache_for_generate(legacy_session) == ({}, None)
    assert _require_puzzle_cache(legacy_session, fields=set()) == {}
    assert _require_color_card_cache_metadata(legacy_session) == {}

    lumina_session = {
        "material_source": "material_archive",
        "material_profile_kind": "lumina_box",
        "preview_cache": {"material_profile_kind": "stage_a"},
    }
    for cache_entry in (
        lambda: _require_preview_cache_for_generate(lumina_session),
        lambda: _require_puzzle_cache(lumina_session, fields=set()),
        lambda: _require_color_card_cache_metadata(lumina_session),
    ):
        with pytest.raises(HTTPException) as mismatch:
            cache_entry()
        assert mismatch.value.status_code == 409
        assert mismatch.value.detail == MATERIAL_ARCHIVE_PROFILE_CACHE_INCOMPATIBLE_DETAIL

    unknown_cache = {"material_profile_kind": "unknown-profile/v1"}
    with pytest.raises(HTTPException) as unknown:
        _require_material_archive_profile_cache_consistency(
            {
                "material_source": "material_archive",
                "material_profile_kind": "lumina_box",
            },
            unknown_cache,
        )
    assert unknown.value.status_code == 409

    with pytest.raises(HTTPException) as unknown_session:
        _require_material_archive_profile_cache_consistency(
            {
                "material_source": "material_archive",
                "material_profile_kind": "unknown-profile/v1",
            },
            {},
        )
    assert unknown_session.value.status_code == 409


def test_preview_cache_and_large_format_params_keep_lumina_kind() -> None:
    """The preview cache and tiled 3MF worker params carry the same kind."""

    from api.routers.converter.generate import _resolve_large_format_shared_params
    from api.schemas.converter import LargeFormatConvertGenerateRequest
    from core.pipeline.p04_cache_building import run as build_preview_cache

    matched_rgb = np.asarray([[[10, 20, 30]]], dtype=np.uint8)
    ctx = build_preview_cache(
        {
            "matched_rgb": matched_rgb,
            "material_matrix": np.zeros((1, 1, 5), dtype=np.int16),
            "mask_solid": np.ones((1, 1), dtype=bool),
            "target_w": 1,
            "target_h": 1,
            "target_width_mm": 60.0,
            "color_conf": {"slots": [], "preview": {}},
            "color_mode": "4-Color (RYBW)",
            "quantize_colors": 48,
            "material_source": "material_archive",
            "material_profile_kind": "lumina_box",
        }
    )
    assert ctx["cache"]["material_profile_kind"] == "lumina_box"

    request = LargeFormatConvertGenerateRequest.model_validate(
        {"lut_name": "__material_archive__", "modeling_mode": "vector"}
    )
    params = _resolve_large_format_shared_params(
        {
            "material_source": "material_archive",
            "material_profile_kind": "lumina_box",
            "selected_materials": ["lumina-base", "lumina-red"],
            "material_backing_material_index": 1,
        },
        request,
        None,
        dynamic_material_settings=(True, 5, 8, 0.5),
    )
    assert params["material_profile_kind"] == "lumina_box"
    assert params["material_backing_material_index"] == 1
    assert params["material_dynamic_layer_count_enabled"] is True


def test_lumina_raster_preview_and_3mf_workers_forward_same_profile_and_backing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Raster preview → final 3MF retains Lumina runtime and backing identity."""

    from api.workers import converter_workers
    from core import converter
    from core.pipeline import _input_validation_common as validation

    monkeypatch.setattr(
        validation,
        "load_and_validate_material_archive_profile",
        lambda selected_materials, *, profile_kind: ("lumina_box", [_lumina_material()]),
    )
    monkeypatch.setattr("config.TEMP_DIR", str(tmp_path))

    preview_kwargs: dict[str, object] = {}

    def fake_preview(**kwargs: object):
        preview_kwargs.update(kwargs)
        return np.zeros((2, 2, 3), dtype=np.uint8), {"material_profile_kind": "lumina_box"}, "ok"

    monkeypatch.setattr(converter, "generate_preview_cached", fake_preview)
    preview_result = converter_workers.worker_generate_preview(
        "input.png",
        "__material_archive__",
        60.0,
        "4-Color (RYBW)",
        "high-fidelity",
        None,
        None,
        48,
        True,
        material_source="material_archive",
        selected_materials=["lumina-base", "lumina-red"],
        material_profile_kind="lumina_box",
        material_backing_material_index=1,
        material_dynamic_layer_count_enabled=True,
        material_min_layer_count=5,
        material_max_layer_count=8,
    )
    try:
        assert preview_kwargs["material_profile_kind"] == "lumina_box"
        assert preview_kwargs["material_backing_material_index"] == 1
        assert preview_kwargs["material_dynamic_layer_count_enabled"] is True
    finally:
        for value in preview_result.values():
            if isinstance(value, str) and os.path.isfile(value):
                os.unlink(value)

    generate_kwargs: dict[str, object] = {}

    def fake_generate(**kwargs: object):
        generate_kwargs.update(kwargs)
        return "out.3mf", None, None, "ok", None

    monkeypatch.setattr(converter, "generate_final_model", fake_generate)
    result = converter_workers.worker_generate_model(
        "input.png",
        "__material_archive__",
        {
            "target_width_mm": 60.0,
            "spacer_thick": 0.8,
            "structure_mode": "Double-sided",
            "color_mode": "4-Color (RYBW)",
            "material_source": "material_archive",
            "selected_materials": ["lumina-base", "lumina-red"],
            "material_profile_kind": "lumina_box",
            "material_backing_material_index": 1,
            "material_dynamic_layer_count_enabled": True,
        },
    )
    assert result["threemf_path"] == "out.3mf"
    assert generate_kwargs["material_profile_kind"] == "lumina_box"
    assert generate_kwargs["material_backing_material_index"] == 1
    assert generate_kwargs["material_dynamic_layer_count_enabled"] is True


def test_lumina_batch_and_native_svg_workers_receive_profile_kind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Batch and native SVG paths use the same Lumina profile boundary."""

    from api.workers import converter_workers
    from core import converter
    from core.pipeline import _input_validation_common as validation

    monkeypatch.setattr(
        validation,
        "load_and_validate_material_archive_profile",
        lambda selected_materials, *, profile_kind: ("lumina_box", [_lumina_material()]),
    )
    batch_kwargs: dict[str, object] = {}

    def fake_convert(**kwargs: object):
        batch_kwargs.update(kwargs)
        return None, None, None, "expected test stop", None

    monkeypatch.setattr(converter, "convert_image_to_3d", fake_convert)
    batch_result = converter_workers.worker_batch_convert_item(
        "input.png",
        "__material_archive__",
        60.0,
        0.8,
        "Double-sided",
        "4-Color (RYBW)",
        "high-fidelity",
        None,
        None,
        48,
        True,
        "lumina-batch-",
        material_source="material_archive",
        selected_materials=["lumina-base", "lumina-red"],
        material_profile_kind="lumina_box",
        material_backing_material_index=1,
    )
    assert batch_result["threemf_path"] is None
    assert batch_kwargs["material_profile_kind"] == "lumina_box"
    assert batch_kwargs["material_backing_material_index"] == 1

    captured_svg_ctx: dict[str, object] = {}

    def stop_after_svg_validation(ctx: dict, **kwargs: object) -> str:
        captured_svg_ctx.update(ctx)
        return "error"

    monkeypatch.setattr(validation, "_apply_material_archive_branch", stop_after_svg_validation)
    with pytest.raises(ValueError, match="Material archive validation failed"):
        converter_workers.worker_generate_large_format_svg_native(
            "input.svg",
            "__material_archive__",
            {
                "total_width_mm": 60.0,
                "total_height_mm": 40.0,
                "tile_width_mm": 60.0,
                "tile_height_mm": 40.0,
                "color_mode": "4-Color (RYBW)",
                "material_source": "material_archive",
                "selected_materials": ["lumina-base", "lumina-red"],
                "material_profile_kind": "lumina_box",
            },
        )
    assert captured_svg_ctx["material_profile_kind"] == "lumina_box"


def test_optical_contract_value_errors_map_to_safe_422() -> None:
    """A direct core optical mismatch must not be presented as a traceback/500."""

    from api.errors import to_http_exception
    from core.material_optical_runtime import MaterialMeasurementProtocolMismatchError

    mapped = to_http_exception(
        MaterialMeasurementProtocolMismatchError("internal protocol details"),
        "preview",
    )
    assert mapped.status_code == 422
    assert mapped.detail["code"] == "material_measurement_protocol_mismatch"
    assert mapped.detail["message"] == "internal protocol details"
