"""Focused v3 material-bundle coverage for Lumina Box archives."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import zipfile

import httpx
import pytest

from core.material_registry import (
    build_material_registry_catalog,
    upload_material_registry_package,
)
import core.single_stage.material_package as materials_module
from core.lumina_box_archive import save_lumina_box_material_archive
from core.km_xyz import (
    KM_XYZ_COLOR_BRIDGE_ID,
    KM_XYZ_FIT_OBJECTIVE_ID,
    KM_XYZ_MEASUREMENT_REFLECTION_BOUNDARY_ID,
    KM_XYZ_MEASUREMENT_PROTOCOL_ID,
)
from core.errors import CoreValidationError
from core.single_stage.materials import (
    export_saved_stage_a_material_archives,
    import_saved_stage_a_material_archives,
    install_material_registry_package,
    list_saved_stage_a_material_archives,
    validate_material_bundle_archive,
)


def _measurement_payload() -> dict[str, object]:
    return {
        "protocol_id": KM_XYZ_MEASUREMENT_PROTOCOL_ID,
        "value_scale": "percent_0_100",
        "measurement_backing_percent_xyz": [19.8, 19.7, 24.7],
        "samples": [
            {
                "thickness_mm": 0.08,
                "transmittance_percent_xyz": [83.0, 79.0, 75.0],
                "reflectance_percent_xyz": [22.0, 28.0, 34.0],
            },
            {
                "thickness_mm": 0.16,
                "transmittance_percent_xyz": [67.0, 61.0, 56.0],
                "reflectance_percent_xyz": [25.0, 31.0, 37.0],
            },
            {
                "thickness_mm": 0.32,
                "transmittance_percent_xyz": [42.0, 35.0, 30.0],
                "reflectance_percent_xyz": [30.0, 36.0, 42.0],
            },
        ],
    }


def _fit_payload(
    *,
    measurement_thickness_offset_mm: float = 0.125,
) -> dict[str, object]:
    measurement = _measurement_payload()
    samples = measurement["samples"]
    assert isinstance(samples, list)
    return {
        "parameters": {
            "K": [0.62, 0.81, 1.04],
            "S": [1.1, 0.8, 0.5],
            "unit": "mm^-1",
        },
        "sample_predictions": [
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
        ],
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
        "estimated_effective_d65_10_xyz_relative": [0.30, 0.36, 0.42],
        "estimated_reflectance_thickness_mm": 0.32,
        "estimated_rgb": [64, 108, 145],
        "warnings": [],
    }


def _save_lumina_box_fixture(materials_root: Path) -> tuple[Path, dict[str, object]]:
    result = save_lumina_box_material_archive(
        material_name="PLA Azure",
        brand="Lumina Test",
        material_type="PLA",
        notes="bundle fixture",
        measurement_payload=_measurement_payload(),
        fit_payload=_fit_payload(),
        materials_dir=str(materials_root),
    )
    material_dir = Path(result.archive_path).parent
    archive_payload = json.loads(
        (material_dir / "material.json").read_text(encoding="utf-8")
    )
    return material_dir, archive_payload


def test_lumina_box_archive_rejects_measurement_fields_outside_fixed_sample_contract(
    tmp_path: Path,
) -> None:
    measurement_payload = _measurement_payload()
    measurement_payload["instrument_metadata"] = {"calibration_complete": True}

    with pytest.raises(CoreValidationError, match="paired percent samples"):
        save_lumina_box_material_archive(
            material_name="PLA Azure",
            brand="Lumina Test",
            material_type="PLA",
            notes=None,
            measurement_payload=measurement_payload,
            fit_payload=_fit_payload(),
            materials_dir=str(tmp_path / "materials"),
        )


def _export_lumina_box_fixture(
    tmp_path: Path,
) -> tuple[Path, Path, dict[str, object]]:
    source_root = tmp_path / "source_materials"
    material_dir, archive_payload = _save_lumina_box_fixture(source_root)
    package_path = tmp_path / "lumina_box_v3.zip"
    export_saved_stage_a_material_archives(
        directory_names=["Lumina Test/PLA Azure"],
        materials_dir=str(source_root),
        output_path=str(package_path),
    )
    return package_path, material_dir, archive_payload


def _read_bundle_entries(package_path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(package_path, "r") as archive:
        return {
            info.filename: archive.read(info.filename)
            for info in archive.infolist()
            if not info.is_dir()
        }


def _write_bundle_entries(package_path: Path, entries: dict[str, bytes]) -> None:
    with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in entries.items():
            archive.writestr(name, payload)


def _bundle_manifest(entries: dict[str, bytes]) -> dict[str, object]:
    return json.loads(entries["lumina_material_bundle.json"].decode("utf-8"))


def _write_bundle_manifest(entries: dict[str, bytes], manifest: dict[str, object]) -> None:
    entries["lumina_material_bundle.json"] = json.dumps(
        manifest,
        ensure_ascii=False,
        indent=2,
    ).encode("utf-8")


def _required_content_hash(package: dict[str, object]) -> str:
    records = {
        str(record["role"]): record
        for record in package["files"]  # type: ignore[index]
        if isinstance(record, dict)
    }
    logical_lines = [
        f"material.json:{records['material_archive']['sha256']}",
        f"lumina_box_measurements.json:{records['measurement_data']['sha256']}",
        f"km_xyz_parameters.json:{records['optical_parameters']['sha256']}",
    ]
    return "sha256:" + hashlib.sha256("\n".join(logical_lines).encode("utf-8")).hexdigest()


def _refresh_v3_hashes(entries: dict[str, bytes]) -> None:
    manifest = _bundle_manifest(entries)
    package = manifest["packages"][0]  # type: ignore[index]
    assert isinstance(package, dict)
    material_path = next(
        record["path"]
        for record in package["files"]  # type: ignore[index]
        if record["role"] == "material_archive"
    )
    material = json.loads(entries[material_path].decode("utf-8"))
    for descriptor_key, role in (
        ("measurements", "measurement_data"),
        ("parameters", "optical_parameters"),
    ):
        sidecar_path = next(
            record["path"]
            for record in package["files"]  # type: ignore[index]
            if record["role"] == role
        )
        material["sidecar_integrity"][descriptor_key]["sha256"] = hashlib.sha256(
            entries[sidecar_path]
        ).hexdigest()
    entries[material_path] = (
        json.dumps(material, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    for record in package["files"]:  # type: ignore[index]
        path = record["path"]
        record["sha256"] = hashlib.sha256(entries[path]).hexdigest()
        record["bytes"] = len(entries[path])
    package["content_hash"] = _required_content_hash(package)
    _write_bundle_manifest(entries, manifest)


def test_lumina_box_export_v3_round_trips_three_files_and_identity(
    tmp_path: Path,
) -> None:
    package_path, source_dir, archive_payload = _export_lumina_box_fixture(tmp_path)
    manifest = validate_material_bundle_archive(archive_path=str(package_path))
    package = manifest["packages"][0]
    assert manifest["kind"] == "lumina_material_bundle"
    assert manifest["schema_version"] == "3.0"
    assert package["profile_kind"] == "lumina_box"
    assert archive_payload["schema_version"] == "2.2"
    assert archive_payload["measurement_thickness_offset_mm"] == pytest.approx(0.125)
    assert package["measurement_protocol_id"] == KM_XYZ_MEASUREMENT_PROTOCOL_ID
    assert package["objective_id"] == KM_XYZ_FIT_OBJECTIVE_ID
    assert package["color_bridge_id"] == KM_XYZ_COLOR_BRIDGE_ID
    assert {record["role"] for record in package["files"]} == {
        "material_archive",
        "measurement_data",
        "optical_parameters",
    }
    consistency = archive_payload["archive_consistency"]
    assert package["material_id"] == consistency["archive_id"]
    assert package["revision_id"] == consistency["revision_id"]
    assert package["archive_identity"]["archive_id"] == consistency["archive_id"]
    assert package["archive_identity"]["revision_id"] == consistency["revision_id"]
    assert package["archive_identity"]["color_bridge_id"] == KM_XYZ_COLOR_BRIDGE_ID
    assert package["compatibility"]["color_bridge_id"] == KM_XYZ_COLOR_BRIDGE_ID
    assert consistency["color_bridge_id"] == KM_XYZ_COLOR_BRIDGE_ID
    for filename in (
        "material.json",
        "lumina_box_measurements.json",
        "km_xyz_parameters.json",
    ):
        payload = json.loads((source_dir / filename).read_text(encoding="utf-8"))
        assert payload["color_bridge_id"] == KM_XYZ_COLOR_BRIDGE_ID
        assert payload["archive_consistency"]["color_bridge_id"] == KM_XYZ_COLOR_BRIDGE_ID
        assert payload["measurement_protocol_id"] == KM_XYZ_MEASUREMENT_PROTOCOL_ID
        assert payload["objective_id"] == KM_XYZ_FIT_OBJECTIVE_ID
    parameters_payload = json.loads(
        (source_dir / "km_xyz_parameters.json").read_text(encoding="utf-8")
    )
    assert parameters_payload["measurement_thickness_offset_mm"] == pytest.approx(
        0.125
    )
    assert parameters_payload["diagnostics"][
        "measurement_thickness_offset_mm"
    ] == pytest.approx(0.125)

    target_root = tmp_path / "target_materials"
    imported = import_saved_stage_a_material_archives(
        archive_path=str(package_path),
        materials_dir=str(target_root),
    )
    assert len(imported.imported_materials) == 1
    assert imported.imported_materials[0]["profile_kind"] == "lumina_box"
    imported_dir = target_root / "Lumina Test" / "PLA Azure"
    for filename in (
        "material.json",
        "lumina_box_measurements.json",
        "km_xyz_parameters.json",
    ):
        assert (imported_dir / filename).read_bytes() == (source_dir / filename).read_bytes()
    assert list_saved_stage_a_material_archives(
        materials_dir=str(target_root),
        profile_kind="lumina_box",
    )[0]["directory_name"] == "Lumina Test/PLA Azure"


@pytest.mark.parametrize(
    "mutation",
    ["missing_sidecar_bridge", "mismatched_sidecar_bridge", "unsupported_package_bridge"],
)
def test_lumina_box_v3_rejects_missing_or_incompatible_color_bridge_before_install(
    tmp_path: Path,
    mutation: str,
) -> None:
    package_path, _, _ = _export_lumina_box_fixture(tmp_path)
    entries = _read_bundle_entries(package_path)
    manifest = _bundle_manifest(entries)
    package = manifest["packages"][0]  # type: ignore[index]
    assert isinstance(package, dict)

    if mutation == "unsupported_package_bridge":
        package["color_bridge_id"] = "d65_10_to_d65_2_diagonal/v0"
        _write_bundle_manifest(entries, manifest)
    else:
        sidecar_role = (
            "measurement_data"
            if mutation == "missing_sidecar_bridge"
            else "optical_parameters"
        )
        sidecar_path = next(
            record["path"]
            for record in package["files"]
            if record["role"] == sidecar_role
        )
        sidecar_payload = json.loads(entries[sidecar_path].decode("utf-8"))
        if mutation == "missing_sidecar_bridge":
            sidecar_payload.pop("color_bridge_id")
        else:
            sidecar_payload["color_bridge_id"] = "d65_10_to_d65_2_diagonal/v0"
        entries[sidecar_path] = (
            json.dumps(sidecar_payload, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n"
        ).encode("utf-8")
        _refresh_v3_hashes(entries)

    _write_bundle_entries(package_path, entries)
    with pytest.raises(ValueError, match="(color bridge|color_bridge_id|integrity)"):
        import_saved_stage_a_material_archives(
            archive_path=str(package_path),
            materials_dir=str(tmp_path / "target_materials"),
        )
    assert list((tmp_path / "target_materials").rglob("material.json")) == []


@pytest.mark.parametrize("mutation", ["tamper", "missing_role", "path_traversal"])
def test_lumina_box_v3_rejects_tampering_before_install(
    tmp_path: Path,
    mutation: str,
) -> None:
    package_path, _, _ = _export_lumina_box_fixture(tmp_path)
    entries = _read_bundle_entries(package_path)
    manifest = _bundle_manifest(entries)
    package = manifest["packages"][0]
    assert isinstance(package, dict)
    if mutation == "tamper":
        parameters_path = next(
            record["path"]
            for record in package["files"]
            if record["role"] == "optical_parameters"
        )
        entries[parameters_path] = b'{"tampered":true}'
    elif mutation == "missing_role":
        package["files"] = [
            record
            for record in package["files"]
            if record["role"] != "measurement_data"
        ]
        _write_bundle_manifest(entries, manifest)
    else:
        measurement_record = next(
            record
            for record in package["files"]
            if record["role"] == "measurement_data"
        )
        measurement_record["path"] = "../lumina_box_measurements.json"
        _write_bundle_manifest(entries, manifest)
    _write_bundle_entries(package_path, entries)

    target_root = tmp_path / "target_materials"
    with pytest.raises((FileNotFoundError, ValueError), match="(hash|size|roles|Unsafe)"):
        import_saved_stage_a_material_archives(
            archive_path=str(package_path),
            materials_dir=str(target_root),
        )
    assert list(target_root.rglob("material.json")) == []


def test_lumina_box_v3_rejects_non_finite_or_negative_ks_before_install(
    tmp_path: Path,
) -> None:
    package_path, _, _ = _export_lumina_box_fixture(tmp_path)
    entries = _read_bundle_entries(package_path)
    manifest = _bundle_manifest(entries)
    package = manifest["packages"][0]
    assert isinstance(package, dict)
    parameters_path = next(
        record["path"]
        for record in package["files"]
        if record["role"] == "optical_parameters"
    )
    parameters = json.loads(entries[parameters_path].decode("utf-8"))
    parameters["parameters"]["K"][0] = -0.01
    entries[parameters_path] = json.dumps(
        parameters,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ).encode("utf-8") + b"\n"
    _refresh_v3_hashes(entries)
    _write_bundle_entries(package_path, entries)

    target_root = tmp_path / "target_materials"
    with pytest.raises(ValueError, match="integrity validation"):
        import_saved_stage_a_material_archives(
            archive_path=str(package_path),
            materials_dir=str(target_root),
        )
    assert list(target_root.rglob("material.json")) == []


def test_lumina_box_v3_failed_atomic_install_preserves_existing_archive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package_path, _, _ = _export_lumina_box_fixture(tmp_path)
    target_root = tmp_path / "target_materials"
    existing_dir = target_root / "Lumina Test" / "PLA Azure"
    existing_dir.mkdir(parents=True)
    existing_material = existing_dir / "material.json"
    existing_material.write_text(
        json.dumps(
            {
                "brand": "Lumina Test",
                "material_name": "PLA Azure",
                "stage_a_params_file": "stage_A_parameters.json",
            }
        ),
        encoding="utf-8",
    )
    (existing_dir / "stage_A_parameters.json").write_text(
        json.dumps(
            {
                "parameters": {
                    "channels": [{"E": [0.1, 0.2, 0.3], "k": [1.0, 1.1, 1.2]}],
                    "substrates": [{"substrate_id": "white", "C0": [1.0, 1.0, 1.0]}],
                }
            }
        ),
        encoding="utf-8",
    )
    original_bytes = existing_material.read_bytes()
    assert list_saved_stage_a_material_archives(
        materials_dir=str(target_root),
        profile_kind="stage_a",
    )[0]["directory_name"] == "Lumina Test/PLA Azure"
    original_replace = materials_module.os.replace

    def fail_staging_swap(source: str | Path, destination: str | Path) -> None:
        if "lumina-box-import-staging" in Path(source).name:
            raise OSError("simulated atomic install failure")
        original_replace(source, destination)

    monkeypatch.setattr(materials_module.os, "replace", fail_staging_swap)
    with pytest.raises(OSError, match="simulated atomic install failure"):
        import_saved_stage_a_material_archives(
            archive_path=str(package_path),
            materials_dir=str(target_root),
        )

    assert existing_material.read_bytes() == original_bytes
    assert list(target_root.rglob("*.lumina-box-import-staging-*")) == []
    assert list(target_root.rglob("PLA Azure_*")) == []
    assert list_saved_stage_a_material_archives(
        materials_dir=str(target_root),
        profile_kind="stage_a",
    )[0]["directory_name"] == "Lumina Test/PLA Azure"


def test_lumina_box_v3_sync_install_reuses_generic_importer(
    tmp_path: Path,
) -> None:
    package_path, _, archive_payload = _export_lumina_box_fixture(tmp_path)
    package_bytes = package_path.read_bytes()
    package_sha256 = hashlib.sha256(package_bytes).hexdigest()
    consistency = archive_payload["archive_consistency"]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/packages/lumina-box.zip":
            return httpx.Response(200, content=package_bytes)
        return httpx.Response(404)

    target_root = tmp_path / "target_materials"
    result = install_material_registry_package(
        package_url="/packages/lumina-box.zip",
        package_sha256=package_sha256,
        material_id=consistency["archive_id"],
        revision_id=consistency["revision_id"],
        registry_url="https://registry.test/v1",
        materials_dir=str(target_root),
        transport=httpx.MockTransport(handler),
    )
    assert result["installed_count"] == 1
    assert result["installed_materials"][0]["profile_kind"] == "lumina_box"
    assert (target_root / "Lumina Test" / "PLA Azure" / "material.json").is_file()


def test_material_registry_accepts_and_catalogs_lumina_box_v3(
    tmp_path: Path,
) -> None:
    package_path, _, archive_payload = _export_lumina_box_fixture(tmp_path)
    registry_root = tmp_path / "registry"
    uploaded = upload_material_registry_package(
        archive_path=str(package_path),
        packages_dir=str(registry_root),
        reject_duplicates=False,
    )
    catalog = build_material_registry_catalog(
        channels=["pending"],
        packages_dir=str(registry_root),
    )
    consistency = archive_payload["archive_consistency"]
    assert uploaded["materials"][0]["material_id"] == consistency["archive_id"]
    assert catalog["count"] == 1
    assert catalog["materials"][0]["revision_id"] == consistency["revision_id"]


def test_stage_a_export_and_import_remain_v2(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source_materials"
    source_dir = source_root / "BrandA" / "PLA Basic"
    source_dir.mkdir(parents=True)
    (source_dir / "material.json").write_text(
        json.dumps(
            {
                "brand": "BrandA",
                "material_name": "PLA Basic",
                "stage_a_params_file": "stage_A_parameters.json",
            }
        ),
        encoding="utf-8",
    )
    (source_dir / "stage_A_parameters.json").write_text(
        json.dumps(
            {
                "parameters": {
                    "channels": [{"E": [0.1, 0.2, 0.3], "k": [1.0, 1.1, 1.2]}],
                    "substrates": [{"substrate_id": "white", "C0": [1.0, 1.0, 1.0]}],
                }
            }
        ),
        encoding="utf-8",
    )
    package_path = tmp_path / "stage_a_v2.zip"
    export_saved_stage_a_material_archives(
        directory_names=["BrandA/PLA Basic"],
        materials_dir=str(source_root),
        output_path=str(package_path),
    )
    manifest = validate_material_bundle_archive(archive_path=str(package_path))
    assert manifest["schema_version"] == "2.0"
    imported = import_saved_stage_a_material_archives(
        archive_path=str(package_path),
        materials_dir=str(tmp_path / "target_materials"),
    )
    assert imported.imported_materials[0]["directory_name"] == "BrandA/PLA Basic"
