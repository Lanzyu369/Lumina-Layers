from __future__ import annotations

import inspect
from pathlib import Path

from fastapi import HTTPException
import pytest

from api.export_device_validation import validate_export_device_selection
from api.routers.calibration import (
    calibration_generate,
    calibration_generate_single_stage_kit,
)
from api.routers.converter.generate import (
    convert_batch,
    convert_generate,
    convert_generate_large_format,
)
from api.routers.converter.puzzle import generate_puzzle
from api.routers.five_color import generate_swatch
from api.routers.single_stage import generate_material_swatch


def test_export_device_validation_allows_legacy_requests_without_registry_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LUMINA_MACHINE_REGISTRY_DIR", "/missing/registry")

    validate_export_device_selection(
        printer_id="bambu-h2d",
        slicer="BambuStudio",
        nozzle_size="0.4",
        device_profile_id=None,
        build_plate_id=None,
    )


def test_export_device_validation_accepts_supported_device_and_plate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LUMINA_MACHINE_REGISTRY_DIR", raising=False)

    validate_export_device_selection(
        printer_id="bambu-h2d",
        slicer="BambuStudio",
        nozzle_size="0.4",
        device_profile_id="BambuStudio:bbl:bambu-lab-h2d:0.4",
        build_plate_id="textured-pei-plate",
    )


@pytest.mark.parametrize(
    ("overrides", "detail_fragment"),
    [
        (
            {"device_profile_id": None, "build_plate_id": "textured-pei-plate"},
            "requires device_profile_id",
        ),
        (
            {"device_profile_id": "missing-device"},
            "Unknown machine registry device profile",
        ),
        (
            {"printer_id": "bambu-p1s"},
            "does not match requested printer",
        ),
        (
            {"slicer": "OrcaSlicer"},
            "does not match requested slicer/nozzle",
        ),
        (
            {"nozzle_size": "0.2"},
            "does not match requested slicer/nozzle",
        ),
        (
            {"build_plate_id": "cool-plate"},
            "Unsupported build plate",
        ),
    ],
)
def test_export_device_validation_rejects_invalid_combinations_with_422(
    monkeypatch: pytest.MonkeyPatch,
    overrides: dict[str, str | None],
    detail_fragment: str,
) -> None:
    monkeypatch.delenv("LUMINA_MACHINE_REGISTRY_DIR", raising=False)
    selection: dict[str, str | None] = {
        "printer_id": "bambu-h2d",
        "slicer": "BambuStudio",
        "nozzle_size": "0.4",
        "device_profile_id": "BambuStudio:bbl:bambu-lab-h2d:0.4",
        "build_plate_id": "textured-pei-plate",
    }
    selection.update(overrides)

    with pytest.raises(HTTPException) as exc_info:
        validate_export_device_selection(**selection)

    assert exc_info.value.status_code == 422
    assert detail_fragment in str(exc_info.value.detail)


def test_export_device_validation_reports_missing_explicit_registry_as_503(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv(
        "LUMINA_MACHINE_REGISTRY_DIR",
        str(tmp_path / "missing-registry"),
    )

    with pytest.raises(HTTPException) as exc_info:
        validate_export_device_selection(
            printer_id="bambu-h2d",
            slicer="BambuStudio",
            nozzle_size="0.4",
            device_profile_id="BambuStudio:bbl:bambu-lab-h2d:0.4",
            build_plate_id="textured-pei-plate",
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "Machine registry is unavailable."


@pytest.mark.parametrize(
    "registry_json",
    [
        '{"schema_version": 1, "generated_at": "test", "slicers": [{}]}',
        '{"schema_version": 1, "generated_at": "test", "slicers": null}',
    ],
)
def test_export_device_validation_reports_malformed_registry_as_503(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    registry_json: str,
) -> None:
    registry_root = tmp_path / "machine-registry"
    registry_root.mkdir()
    (registry_root / "registry.json").write_text(registry_json, encoding="utf-8")
    monkeypatch.setenv("LUMINA_MACHINE_REGISTRY_DIR", str(registry_root))

    with pytest.raises(HTTPException) as exc_info:
        validate_export_device_selection(
            printer_id="bambu-h2d",
            slicer="BambuStudio",
            nozzle_size="0.4",
            device_profile_id="BambuStudio:bbl:bambu-lab-h2d:0.4",
            build_plate_id="textured-pei-plate",
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "Machine registry is unavailable."


@pytest.mark.parametrize(
    ("route", "first_generation_step"),
    [
        (convert_generate, "_validate_native_vector_relief_compatibility"),
        (convert_generate_large_format, "_validate_native_vector_relief_compatibility"),
        (convert_batch, "_validate_material_source"),
        (generate_puzzle, "if generate_params.enable_fridge_magnet"),
        (calibration_generate, "mode = request.color_mode.value"),
        (calibration_generate_single_stage_kit, "palette = ["),
        (generate_swatch, "from api.file_bridge import"),
        (generate_material_swatch, "from api.file_bridge import"),
    ],
)
def test_export_routes_call_shared_validator_before_generation(
    route,
    first_generation_step: str,
) -> None:
    assert route.__globals__["validate_export_device_selection"] is (
        validate_export_device_selection
    )
    source = inspect.getsource(route)
    assert source.index("validate_export_device_selection(") < source.index(
        first_generation_step
    )
