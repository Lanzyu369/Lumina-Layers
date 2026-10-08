"""Versioned persistence for the adopted Box spectral model.
已采用 Box 波段模型的带版本持久化。

Raw percentages are retained alongside a self-contained white reference. The
old XYZ coefficient file is never interpreted as spectral coefficients.
保留原始百分比读数及自包含白参考，不将旧 XYZ 系数文件解释为波段系数。
"""

from __future__ import annotations

import hmac
import math
from pathlib import Path
import shutil
from typing import Any, Mapping
import uuid

import numpy as np

from core.errors import CoreValidationError, MaterialArchiveConflictError
from core import lumina_box_archive as archive
from core.km_xyz import KMChannelFitDiagnostics, KMFitDiagnostics
from core.lumina_box_fit_records import build_spectral_fit_payload
from core.lumina_box_fitting import LuminaBoxSpectralFitResult, box_measurement_fingerprint
from core.lumina_box_spectral import (
    BoxWhiteReference,
    LUMINA_BOX_REFERENCE_REFLECTANCE,
    LUMINA_BOX_SPECTRAL_BOUNDARY_ID,
    LUMINA_BOX_SPECTRAL_MODEL_ID,
    LUMINA_BOX_SPECTRAL_OBJECTIVE_ID,
    LUMINA_BOX_PHYSICAL_WHITE_OBJECTIVE_IDS,
    LUMINA_BOX_SUPPORTED_OBJECTIVE_IDS,
    LuminaBoxModelError,
    LuminaBoxSpectralModel,
    SpectralMaterialParameters,
)

SPECTRAL_ARCHIVE_SCHEMA_VERSION = "3.0"
SPECTRAL_PARAMETERS_FILENAME = "lumina_box_spectral_parameters.json"
SPECTRAL_PARAMETERS_KEY = "optical_parameters_file"
SPECTRAL_ARCHIVE_FILES = ("material.json", archive.LUMINA_BOX_MEASUREMENTS_FILENAME, SPECTRAL_PARAMETERS_FILENAME)


def _assert_same(expected: Any, actual: Any, field: str) -> None:
    if isinstance(expected, dict):
        if not isinstance(actual, dict) or set(actual) != set(expected):
            raise CoreValidationError(f"{field} has an invalid schema shape")
        for key in expected:
            _assert_same(expected[key], actual[key], f"{field}.{key}")
    elif isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            raise CoreValidationError(f"{field} has an invalid array shape")
        for index, (left, right) in enumerate(zip(expected, actual, strict=True)):
            _assert_same(left, right, f"{field}[{index}]")
    elif isinstance(expected, bool):
        if type(actual) is not bool or actual != expected:
            raise CoreValidationError(f"{field} does not match the spectral model")
    elif isinstance(expected, (float, int)):
        if isinstance(actual, bool) or not isinstance(actual, (float, int)) or not math.isfinite(actual):
            raise CoreValidationError(f"{field} must be a finite number")
        if not math.isclose(expected, actual, rel_tol=1e-9, abs_tol=1e-8):
            raise CoreValidationError(f"{field} does not match the spectral model")
    elif actual != expected:
        raise CoreValidationError(f"{field} does not match the spectral model")


def normalize_spectral_fit_payload(
    payload: Mapping[str, Any], measurements: Mapping[str, Any],
) -> dict[str, Any]:
    """Reconstruct and validate the complete spectral fit before trusting it.
    重新回算并校验完整波段拟合后再使用。

    Args:
        payload: Server-owned or persisted fit.（服务器持有或已保存的拟合。）
        measurements: Validated original percentages.（已校验原始百分比。）

    Returns:
        Canonical, reconstructed fit record.（标准化并已回算的拟合记录。）
    """
    try:
        if payload.get("optical_model_id") != LUMINA_BOX_SPECTRAL_MODEL_ID:
            raise LuminaBoxModelError("Unsupported Box spectral model")
        parameters = SpectralMaterialParameters.from_dict(payload["parameters"])
        reference = BoxWhiteReference.from_dict(payload["white_reference"])
        role = payload["is_reference_white"]
        if type(role) is not bool:
            raise LuminaBoxModelError("is_reference_white must be a boolean")
        objective_id = payload["diagnostics"].get("objective_id")
        if objective_id not in LUMINA_BOX_SUPPORTED_OBJECTIVE_IDS:
            raise LuminaBoxModelError("Unsupported Box spectral fitting objective")
        diagnostic = archive._normalized_diagnostics(payload["diagnostics"], objective_id=objective_id)
        if diagnostic["measurement_thickness_offset_mm"] != 0.0:
            raise LuminaBoxModelError("The adopted model has no fitted thickness offset")
        channels = tuple(KMChannelFitDiagnostics(
            item["channel"], item["transmittance_rmse"], item["reflectance_rmse"], tuple(item["warnings"]),
        ) for item in diagnostic["channels"])
        diagnostics = KMFitDiagnostics(**{**diagnostic, "channels": channels, "warnings": tuple(diagnostic["warnings"])})
        samples = measurements["samples"]
        d = np.array([sample["thickness_mm"] for sample in samples])
        t = np.array([sample["transmittance_percent_xyz"] for sample in samples]) / 100.0
        r = np.array([sample["reflectance_percent_xyz"] for sample in samples]) / 100.0
        g = np.asarray(measurements["measurement_backing_percent_xyz"]) / 100.0
        model = LuminaBoxSpectralModel()
        model.validate_reference_physics(
            reference, require_constraint=objective_id in LUMINA_BOX_PHYSICAL_WHITE_OBJECTIVE_IDS,
        )
        reference_q = model.reference_xyz(reference.white_parameters, reference.backing_base_relative_xyz)
        if not np.allclose(reference_q, reference.relative_xyz, atol=1e-9, rtol=0.0):
            raise LuminaBoxModelError("White reference does not reconstruct from its saved parameters")
        if role:
            if (
                not np.array_equal(parameters.values, reference.white_parameters.values)
                or not np.array_equal(g, reference.backing_base_relative_xyz)
                or box_measurement_fingerprint(d, t, r, g) != reference.measurement_sha256
            ):
                raise LuminaBoxModelError("Calibration-white parameters or measurements do not match its reference")
        pt, pr = model.observe(parameters, d, g, reference.relative_xyz)
        result = LuminaBoxSpectralFitResult(
            parameters, reference, role, pt, pr, g, float(parameters.values[7]),
            parameters.values[7] * g * reference.relative_xyz / LUMINA_BOX_REFERENCE_REFLECTANCE,
            diagnostics,
        )
        expected = build_spectral_fit_payload(result, measurements)
        _assert_same(expected, dict(payload), "spectral fit")
        for index, diagnostic_channel in enumerate(channels):
            for expected_rmse, actual_rmse in (
                (np.sqrt(np.mean((pt[:, index] - t[:, index]) ** 2)), diagnostic_channel.transmittance_rmse),
                (np.sqrt(np.mean((pr[:, index] - r[:, index]) ** 2)), diagnostic_channel.reflectance_rmse),
            ):
                if not math.isclose(float(expected_rmse), actual_rmse, rel_tol=1e-8, abs_tol=1e-10):
                    raise LuminaBoxModelError("Spectral diagnostics do not match reconstructed residuals")
        return expected
    except (KeyError, TypeError, ValueError) as exc:
        raise CoreValidationError(f"Invalid Box spectral fit: {exc}") from exc


def _common_metadata(
    archive_id: str, revision_id: str, reference_id: str,
    objective_id: str = LUMINA_BOX_SPECTRAL_OBJECTIVE_ID,
) -> dict[str, Any]:
    if objective_id not in LUMINA_BOX_SUPPORTED_OBJECTIVE_IDS:
        raise CoreValidationError("Unsupported Box spectral fitting objective")
    return {
        "schema_version": SPECTRAL_ARCHIVE_SCHEMA_VERSION,
        "optical_model": LUMINA_BOX_SPECTRAL_MODEL_ID,
        "measurement_protocol_id": archive.LUMINA_BOX_PROTOCOL_ID,
        "objective_id": objective_id,
        "color_bridge_id": archive.LUMINA_BOX_COLOR_BRIDGE_ID,
        "archive_consistency": {
            "schema_version": "2.0", "archive_id": archive_id, "revision_id": revision_id,
            "profile_kind": archive.LUMINA_BOX_PROFILE_KIND,
            "acquisition_source": archive.LUMINA_BOX_ACQUISITION_SOURCE,
            "optical_model_id": LUMINA_BOX_SPECTRAL_MODEL_ID,
            "measurement_protocol_id": archive.LUMINA_BOX_PROTOCOL_ID,
            "objective_id": objective_id,
            "color_bridge_id": archive.LUMINA_BOX_COLOR_BRIDGE_ID,
            "reference_id": reference_id,
        },
    }


def _main_payload(
    common: dict[str, Any], fit: Mapping[str, Any], *, material_name: str,
    brand: str | None, material_type: str | None, notes: str | None,
    created_at: str, updated_at: str, sidecar_integrity: dict[str, Any],
) -> dict[str, Any]:
    copied = {key: fit[key] for key in (
        "is_reference_white", "measurement_backing_base_percent_xyz", "measurement_backing_scale",
        "measurement_thickness_offset_mm", "measurement_backing_effective_percent_xyz",
        "measurement_reflection_boundary_id", "estimated_effective_d65_10_xyz_relative",
        "estimated_reflectance_thickness_mm", "estimated_rgb",
    )}
    return {
        **common, **copied, "kind": "lumina_box_material", "material_name": material_name,
        "brand": brand, "material_type": material_type, "notes": notes,
        "created_at": created_at, "updated_at": updated_at,
        "profile_kind": archive.LUMINA_BOX_PROFILE_KIND,
        "acquisition_source": archive.LUMINA_BOX_ACQUISITION_SOURCE,
        "measurements_file": archive.LUMINA_BOX_MEASUREMENTS_FILENAME,
        SPECTRAL_PARAMETERS_KEY: SPECTRAL_PARAMETERS_FILENAME,
        "reference_id": fit["white_reference"]["reference_id"],
        "sidecar_integrity": sidecar_integrity,
    }


def load_spectral_archive(
    material_dir: Path, archive_payload: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Validate all archive bytes, identities, and spectral predictions.
    校验全部档案文件、标识及波段预测。

    Args:
        material_dir: Resolved material directory.（已解析的耗材目录。）
        archive_payload: Optional already-read main record.（可选已读取主记录。）

    Returns:
        Main record, original measurement payload, and verified fit.
        （主记录、原始测量载荷及已校验拟合。）
    """
    main = archive_payload or archive._load_archive_payload(material_dir / "material.json")
    if not isinstance(main, Mapping):
        raise CoreValidationError("Box material.json is not valid UTF-8 JSON")
    try:
        consistency = main["archive_consistency"]
        archive_id, revision_id = consistency["archive_id"], consistency["revision_id"]
        uuid.UUID(archive_id)
        uuid.UUID(revision_id)
        common = _common_metadata(archive_id, revision_id, main["reference_id"], main["objective_id"])
        sidecars: dict[str, dict[str, Any]] = {}
        integrity = main["sidecar_integrity"]
        if set(integrity) != {"algorithm", "measurements", "parameters"} or integrity["algorithm"] != "sha256":
            raise CoreValidationError("Invalid spectral sidecar integrity descriptor")
        for role, filename in (
            ("measurements", archive.LUMINA_BOX_MEASUREMENTS_FILENAME), ("parameters", SPECTRAL_PARAMETERS_FILENAME),
        ):
            entry = integrity[role]
            path = material_dir / filename
            if (
                set(entry) != {"filename", "sha256"} or entry["filename"] != filename
                or not path.resolve().is_relative_to(material_dir.resolve())
                or not isinstance(entry["sha256"], str) or not archive._SHA256_HEX.fullmatch(entry["sha256"])
                or not hmac.compare_digest(archive._sha256_file(path), entry["sha256"])
            ):
                raise CoreValidationError(f"{filename} integrity does not match material.json")
            payload = archive._load_archive_payload(path)
            if payload is None:
                raise CoreValidationError(f"{filename} is not valid UTF-8 JSON")
            for key, expected in common.items():
                _assert_same(expected, payload.get(key), f"{filename}.{key}")
            sidecars[role] = payload
        measurement_file = sidecars["measurements"]
        measurements = archive._normalized_measurement_payload({
            "protocol_id": measurement_file["measurement_protocol_id"],
            "value_scale": measurement_file["value_scale"],
            "measurement_backing_percent_xyz": measurement_file["measurement_backing_percent_xyz"],
            "samples": measurement_file["samples"],
        }, allow_zero_transmittance=True)
        expected_measurements = {
            **common, "value_scale": archive.LUMINA_BOX_VALUE_SCALE,
            "measurement_backing_percent_xyz": measurements["measurement_backing_percent_xyz"],
            "samples": measurements["samples"],
        }
        _assert_same(expected_measurements, measurement_file, "measurement sidecar")
        parameters_file = sidecars["parameters"]
        fit = normalize_spectral_fit_payload(parameters_file["fit"], measurements)
        if fit["diagnostics"]["objective_id"] != common["objective_id"]:
            raise CoreValidationError("Fit objective does not match archive metadata")
        _assert_same({**common, "fit": fit}, parameters_file, "parameter sidecar")
        expected_main = _main_payload(
            common, fit, material_name=archive._clean_required_text(main["material_name"], field_name="material_name"),
            brand=archive._clean_optional_text(main["brand"]), material_type=archive._clean_optional_text(main["material_type"]),
            notes=archive._clean_optional_text(main["notes"]), created_at=main["created_at"], updated_at=main["updated_at"],
            sidecar_integrity=dict(integrity),
        )
        _assert_same(expected_main, dict(main), "material.json")
        return dict(main), measurements, fit
    except (KeyError, TypeError, ValueError, OSError) as exc:
        raise CoreValidationError(f"Invalid Box spectral archive: {exc}") from exc


def spectral_archive_summary(materials_root: Path, material_dir: Path, main: Mapping[str, Any]) -> dict[str, Any]:
    """Build the public library summary for one validated spectral archive.
    为已校验的波段档案构建公开材料库摘要。

    Args:
        materials_root: Library root.（材料库根目录。）
        material_dir: Material directory.（耗材目录。）
        main: Validated main record.（已校验主记录。）

    Returns:
        Material summary including calibration role.（含白参考角色的耗材摘要。）
    """
    result = {key: main.get(key) for key in (
        "material_name", "brand", "material_type", "notes", "created_at", "updated_at",
        "profile_kind", "acquisition_source", "optical_model", "measurement_protocol_id", "color_bridge_id",
        "measurement_backing_base_percent_xyz", "measurement_backing_scale", "measurement_thickness_offset_mm",
        "measurement_backing_effective_percent_xyz", "measurement_reflection_boundary_id",
        "estimated_effective_d65_10_xyz_relative", "estimated_reflectance_thickness_mm", "estimated_rgb",
        "is_reference_white", "reference_id",
    )}
    result.update({"directory_name": archive._relative_directory_name(materials_root, material_dir),
                   "optical_model_id": LUMINA_BOX_SPECTRAL_MODEL_ID,
                   "fit_objective_id": main.get("objective_id")})
    return result


def save_spectral_material_archive(
    *, material_name: str, brand: str | None, material_type: str | None, notes: str | None,
    measurement_payload: Mapping[str, Any], fit_payload: Mapping[str, Any],
    overwrite: bool = False, materials_dir: str | None = None,
) -> archive.LuminaBoxMaterialArchiveSaveResult:
    """Stage and atomically save a complete spectral material archive.
    暂存并原子保存完整波段耗材档案。

    Args:
        material_name: Material display name.（耗材显示名称。）
        brand: Optional manufacturer.（可选品牌。）
        material_type: Optional polymer type.（可选材料种类。）
        notes: Existing or new operator notes.（已有或新的操作备注。）
        measurement_payload: Original percentage measurements.（原始百分比测量。）
        fit_payload: Server-owned adopted-model result.（服务器持有的已采用模型结果。）
        overwrite: Explicit permission to replace the same material.（明确替换同一耗材。）
        materials_dir: Optional library root.（可选材料库根目录。）

    Returns:
        Committed paths and library summary.（已提交路径及材料库摘要。）
    """
    name = archive._clean_required_text(material_name, field_name="material_name")
    brand = archive._clean_optional_text(brand)
    material_type = archive._clean_optional_text(material_type)
    notes = archive._clean_optional_text(notes)
    measurements = archive._normalized_measurement_payload(
        measurement_payload, allow_zero_transmittance=True,
    )
    fit = normalize_spectral_fit_payload(fit_payload, measurements)
    if not fit["fit_quality"]["savable"]:
        raise CoreValidationError("The spectral material fit is not eligible for saving")
    root_path = Path(materials_dir or archive.MATERIALS_DIR).resolve()
    with archive._ARCHIVE_WRITE_LOCK:
        root_path.mkdir(parents=True, exist_ok=True)
        existing = archive._find_same_identity_archive(root_path, material_name=name, brand=brand)
        if existing is not None and not overwrite:
            raise MaterialArchiveConflictError("A material archive already uses this Lumina Box brand and name")
        parent = root_path / archive._sanitize_directory_name(brand) if brand else root_path
        target = existing[0].parent if existing is not None else parent / archive._sanitize_directory_name(name)
        if not target.resolve().is_relative_to(root_path) or target.resolve() == root_path:
            raise CoreValidationError("Spectral material path escapes the library")
        if target.exists() and existing is None:
            raise MaterialArchiveConflictError("The material directory is already occupied")
        parent = target.parent
        parent.mkdir(parents=True, exist_ok=True)
        staged = parent / f".{target.name}.spectral-staging-{uuid.uuid4().hex}"
        existing_main = existing[1] if existing is not None else {}
        now = archive._now_iso()
        old_consistency = existing_main.get("archive_consistency", {})
        archive_id = str(old_consistency.get("archive_id") or uuid.uuid4())
        common = _common_metadata(
            archive_id, str(uuid.uuid4()), fit["white_reference"]["reference_id"],
            fit["diagnostics"]["objective_id"],
        )
        measurement_file = {**common, "value_scale": archive.LUMINA_BOX_VALUE_SCALE,
                            "measurement_backing_percent_xyz": measurements["measurement_backing_percent_xyz"],
                            "samples": measurements["samples"]}
        parameter_file = {**common, "fit": fit}
        try:
            if target.exists():
                shutil.copytree(target, staged, symlinks=True)
            else:
                staged.mkdir()
            for filename in SPECTRAL_ARCHIVE_FILES:
                path = staged / filename
                if path.is_symlink():
                    raise CoreValidationError("Material contract files must not be symbolic links")
            measurement_path = staged / archive.LUMINA_BOX_MEASUREMENTS_FILENAME
            parameter_path = staged / SPECTRAL_PARAMETERS_FILENAME
            archive._write_json(measurement_path, measurement_file)
            archive._write_json(parameter_path, parameter_file)
            integrity = {"algorithm": "sha256",
                         "measurements": {"filename": measurement_path.name, "sha256": archive._sha256_file(measurement_path)},
                         "parameters": {"filename": parameter_path.name, "sha256": archive._sha256_file(parameter_path)}}
            main = _main_payload(
                common, fit, material_name=name, brand=brand, material_type=material_type, notes=notes,
                created_at=str(existing_main.get("created_at") or now), updated_at=now, sidecar_integrity=integrity,
            )
            archive._write_json(staged / "material.json", main)
            old_parameters = staged / archive.LUMINA_BOX_PARAMETERS_FILENAME
            if old_parameters.is_file() or old_parameters.is_symlink():
                old_parameters.unlink()
            load_spectral_archive(staged, main)
            archive._commit_staged_material_directory(staged_dir=staged, target_dir=target, overwrite=overwrite)
        finally:
            if staged.exists() and staged.parent.resolve() == parent.resolve() and staged.name.startswith(f".{target.name}.spectral-staging-"):
                shutil.rmtree(staged)
        return archive.LuminaBoxMaterialArchiveSaveResult(
            archive_path=str(target / "material.json"),
            measurements_path=str(target / archive.LUMINA_BOX_MEASUREMENTS_FILENAME),
            parameters_path=str(target / SPECTRAL_PARAMETERS_FILENAME),
            material_summary=spectral_archive_summary(root_path, target, main),
        )


def load_calibration_white_reference(
    directory_name: str, *, materials_dir: str | None = None,
) -> BoxWhiteReference:
    """Load an explicitly selected saved calibration white.
    加载明确选择的已保存校准白耗材。

    Args:
        directory_name: Relative saved material directory.（已保存耗材的相对目录。）
        materials_dir: Optional material library root.（可选材料库根目录。）

    Returns:
        The validated portable white reference.（已校验的可迁移白参考。）
    """
    from core.single_stage import resolve_saved_material_dir

    library = Path(materials_dir or archive.MATERIALS_DIR)
    try:
        material_dir = resolve_saved_material_dir(library, directory_name)
        _main, _measurements, fit = load_spectral_archive(material_dir)
    except (FileNotFoundError, OSError, ValueError) as exc:
        raise CoreValidationError("The selected calibration white is unavailable; save it with the new Box model first") from exc
    if not fit["is_reference_white"]:
        raise CoreValidationError("The selected material was not fitted as the instrument calibration white")
    reference = BoxWhiteReference.from_dict(fit["white_reference"])
    LuminaBoxSpectralModel().validate_reference_physics(reference, require_constraint=True)
    return reference
