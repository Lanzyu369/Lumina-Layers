"""Raw measurements, archive dispatch, and historical Lumina Box persistence.
原始测量、档案版本分派与旧版 Lumina Box 持久化。

New fits use the spectral archive writer; the KM implementation here remains
for verified historical reading, transfer, and explicit migration.
新拟合分派至波段档案写入器；此处保留 KM 实现供旧档案读取、传输及明确迁移使用。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import re
import shutil
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from api.structured_logging import get_logger
from config import MATERIALS_DIR
from core.errors import CoreValidationError, MaterialArchiveConflictError
from core.km_xyz import (
    KM_XYZ_COLOR_BRIDGE_ID,
    KM_XYZ_FIT_OBJECTIVE_ID,
    KM_XYZ_MEASUREMENT_REFLECTION_BOUNDARY_ID,
    KM_XYZ_MEASUREMENT_THICKNESS_OFFSET_MAX_MM,
    KM_XYZ_MEASUREMENT_PROTOCOL_ID,
    KM_XYZ_MODEL_ID,
)
from core.lumina_box_spectral import LUMINA_BOX_SPECTRAL_MODEL_ID
from core.backed_gradient_smooth import SPECTRAL_SMOOTH_MODEL_ID


LUMINA_BOX_PROFILE_KIND = "lumina_box"
LUMINA_BOX_ACQUISITION_SOURCE = "lumina_box"
LUMINA_BOX_OPTICAL_MODEL_ID = KM_XYZ_MODEL_ID
LUMINA_BOX_PROTOCOL_ID = KM_XYZ_MEASUREMENT_PROTOCOL_ID
LUMINA_BOX_COLOR_BRIDGE_ID = KM_XYZ_COLOR_BRIDGE_ID
LUMINA_BOX_OBJECTIVE_ID = KM_XYZ_FIT_OBJECTIVE_ID
LUMINA_BOX_MEASUREMENT_REFLECTION_BOUNDARY_ID = (
    KM_XYZ_MEASUREMENT_REFLECTION_BOUNDARY_ID
)
LUMINA_BOX_VALUE_SCALE = "percent_0_100"
LUMINA_BOX_RESIDUAL_UNIT = "percentage_point"
LUMINA_BOX_MEASUREMENTS_FILENAME = "lumina_box_measurements.json"
LUMINA_BOX_PARAMETERS_FILENAME = "km_xyz_parameters.json"
LUMINA_BOX_ARCHIVE_SCHEMA_VERSION = "2.2"
LUMINA_BOX_INTEGRITY_SCHEMA_VERSION = "1.0"
LUMINA_BOX_FIT_QUALITY_UNSAVABLE_CODE = "lumina_box_fit_quality_unsavable"
LUMINA_BOX_FIT_QUALITY_THRESHOLDS = {
    "modality_rmse_percentage_points": 10.0,
    "overall_rmse_percentage_points": 10.0,
    "max_abs_residual_percentage_points": 20.0,
}
_INVALID_WINDOWS_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")

_log = get_logger(__name__)
_ARCHIVE_WRITE_LOCK = threading.RLock()


def lumina_box_archive_filenames(optical_model_id: str) -> tuple[str, str, str]:
    """Return the exact durable file set for a recognized Box archive model.
    返回已识别 Box 模型对应的持久化文件集合。

    Args:
        optical_model_id: Explicit archive model identifier.（档案明确声明的模型标识。）

    Returns:
        Main archive, raw measurements, and versioned parameters filenames.
        （主档案、原始测量以及带版本参数的文件名。）
    """
    if optical_model_id == SPECTRAL_SMOOTH_MODEL_ID:
        from core.backed_gradient_archive import (
            BACKED_GRADIENT_MEASUREMENTS_FILENAME, BACKED_GRADIENT_PARAMETERS_FILENAME,
        )
        return "material.json", BACKED_GRADIENT_MEASUREMENTS_FILENAME, BACKED_GRADIENT_PARAMETERS_FILENAME
    if optical_model_id == LUMINA_BOX_SPECTRAL_MODEL_ID:
        from core.lumina_box_spectral_archive import SPECTRAL_PARAMETERS_FILENAME

        return "material.json", LUMINA_BOX_MEASUREMENTS_FILENAME, SPECTRAL_PARAMETERS_FILENAME
    if optical_model_id == LUMINA_BOX_OPTICAL_MODEL_ID:
        return "material.json", LUMINA_BOX_MEASUREMENTS_FILENAME, LUMINA_BOX_PARAMETERS_FILENAME
    raise CoreValidationError("Unsupported Lumina Box archive model")


@dataclass(frozen=True)
class LuminaBoxMaterialArchiveSaveResult:
    """Paths and public summary produced by a committed Lumina Box save."""

    archive_path: str
    measurements_path: str
    parameters_path: str
    material_summary: dict[str, Any]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_clone(value: Any) -> Any:
    """Make JSON serializability part of the archive contract."""
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise CoreValidationError("Lumina Box archive data is not valid finite JSON") from exc


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    """Return the exact canonical UTF-8 bytes used for an archive JSON file."""
    return (
        json.dumps(
            _json_clone(value),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _clean_required_text(value: str, *, field_name: str) -> str:
    cleaned = str(value).strip()
    if not cleaned:
        raise CoreValidationError(f"{field_name} is required")
    return cleaned


def _clean_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _sanitize_directory_name(value: str) -> str:
    cleaned = _INVALID_WINDOWS_FILENAME.sub("_", str(value)).strip().strip(". ")
    return cleaned or "material"


def _relative_directory_name(materials_root: Path, material_dir: Path) -> str:
    try:
        return material_dir.resolve().relative_to(materials_root.resolve()).as_posix()
    except (OSError, ValueError) as exc:
        raise CoreValidationError("Lumina Box archive path escapes the materials directory") from exc


def _load_archive_payload(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _is_lumina_box_archive(payload: Mapping[str, Any]) -> bool:
    return str(payload.get("profile_kind") or "").strip() == LUMINA_BOX_PROFILE_KIND


def _archive_consistency_metadata(
    *,
    archive_id: str,
    revision_id: str,
) -> dict[str, str]:
    """Return metadata that must agree across all three Lumina Box files."""
    return {
        "schema_version": LUMINA_BOX_INTEGRITY_SCHEMA_VERSION,
        "archive_id": archive_id,
        "revision_id": revision_id,
        "profile_kind": LUMINA_BOX_PROFILE_KIND,
        "acquisition_source": LUMINA_BOX_ACQUISITION_SOURCE,
        "optical_model_id": LUMINA_BOX_OPTICAL_MODEL_ID,
        "measurement_protocol_id": LUMINA_BOX_PROTOCOL_ID,
        "objective_id": LUMINA_BOX_OBJECTIVE_ID,
        "color_bridge_id": LUMINA_BOX_COLOR_BRIDGE_ID,
    }


def _sidecar_integrity_error(
    material_dir: Path,
    archive_payload: Mapping[str, Any],
) -> str | None:
    """Return a safe validation message when a Lumina Box archive is inconsistent."""
    expected_archive_fields = {
        "schema_version",
        "kind",
        "material_name",
        "brand",
        "material_type",
        "notes",
        "created_at",
        "updated_at",
        "profile_kind",
        "acquisition_source",
        "optical_model",
        "measurement_protocol_id",
        "objective_id",
        "color_bridge_id",
        "measurements_file",
        "km_xyz_parameters_file",
        "archive_consistency",
        "measurement_backing_base_percent_xyz",
        "measurement_backing_scale",
        "measurement_thickness_offset_mm",
        "measurement_backing_effective_percent_xyz",
        "measurement_reflection_boundary_id",
        "estimated_effective_d65_10_xyz_relative",
        "estimated_reflectance_thickness_mm",
        "estimated_rgb",
        "sidecar_integrity",
    }
    if set(archive_payload) != expected_archive_fields:
        return "material.json has an invalid schema shape"
    if not _is_lumina_box_archive(archive_payload):
        return "material.json is not a Lumina Box archive"
    if archive_payload.get("schema_version") != LUMINA_BOX_ARCHIVE_SCHEMA_VERSION:
        return "material.json has an unsupported schema_version"
    if archive_payload.get("kind") != "lumina_box_material":
        return "material.json has an invalid kind"
    if archive_payload.get("acquisition_source") != LUMINA_BOX_ACQUISITION_SOURCE:
        return "material.json has an invalid acquisition_source"
    if archive_payload.get("optical_model") != LUMINA_BOX_OPTICAL_MODEL_ID:
        return "material.json has an invalid optical_model"
    if archive_payload.get("measurement_protocol_id") != LUMINA_BOX_PROTOCOL_ID:
        return "material.json has an invalid measurement_protocol_id"
    if archive_payload.get("objective_id") != LUMINA_BOX_OBJECTIVE_ID:
        return "material.json has an invalid objective_id"
    if archive_payload.get("color_bridge_id") != LUMINA_BOX_COLOR_BRIDGE_ID:
        return "material.json has an invalid color_bridge_id"
    if archive_payload.get("measurements_file") != LUMINA_BOX_MEASUREMENTS_FILENAME:
        return "material.json has an invalid measurements_file"
    if archive_payload.get("km_xyz_parameters_file") != LUMINA_BOX_PARAMETERS_FILENAME:
        return "material.json has an invalid km_xyz_parameters_file"
    if (
        archive_payload.get("measurement_reflection_boundary_id")
        != LUMINA_BOX_MEASUREMENT_REFLECTION_BOUNDARY_ID
    ):
        return "material.json has an invalid measurement_reflection_boundary_id"

    consistency = archive_payload.get("archive_consistency")
    if not isinstance(consistency, Mapping):
        return "material.json is missing archive consistency metadata"
    expected_consistency_fields = {
        "schema_version",
        "archive_id",
        "revision_id",
        "profile_kind",
        "acquisition_source",
        "optical_model_id",
        "measurement_protocol_id",
        "objective_id",
        "color_bridge_id",
    }
    if set(consistency) != expected_consistency_fields:
        return "archive consistency metadata has an invalid schema shape"
    expected_consistency = {
        "schema_version": LUMINA_BOX_INTEGRITY_SCHEMA_VERSION,
        "profile_kind": LUMINA_BOX_PROFILE_KIND,
        "acquisition_source": LUMINA_BOX_ACQUISITION_SOURCE,
        "optical_model_id": LUMINA_BOX_OPTICAL_MODEL_ID,
        "measurement_protocol_id": LUMINA_BOX_PROTOCOL_ID,
        "objective_id": LUMINA_BOX_OBJECTIVE_ID,
        "color_bridge_id": LUMINA_BOX_COLOR_BRIDGE_ID,
    }
    for field, expected_value in expected_consistency.items():
        if consistency.get(field) != expected_value:
            return f"archive consistency metadata has an invalid {field}"
    for field in ("archive_id", "revision_id"):
        raw_value = consistency.get(field)
        if not isinstance(raw_value, str):
            return f"archive consistency metadata is missing {field}"
        try:
            uuid.UUID(raw_value)
        except (ValueError, AttributeError):
            return f"archive consistency metadata has an invalid {field}"

    sidecar_integrity = archive_payload.get("sidecar_integrity")
    if not isinstance(sidecar_integrity, Mapping):
        return "material.json is missing sidecar integrity metadata"
    if set(sidecar_integrity) != {"algorithm", "measurements", "parameters"}:
        return "material.json has an invalid sidecar integrity shape"
    if sidecar_integrity.get("algorithm") != "sha256":
        return "material.json has an unsupported sidecar integrity algorithm"

    expected_sidecars = {
        "measurements": LUMINA_BOX_MEASUREMENTS_FILENAME,
        "parameters": LUMINA_BOX_PARAMETERS_FILENAME,
    }
    loaded_sidecars: dict[str, dict[str, Any]] = {}
    for sidecar_key, expected_filename in expected_sidecars.items():
        descriptor = sidecar_integrity.get(sidecar_key)
        if not isinstance(descriptor, Mapping):
            return f"material.json is missing {sidecar_key} sidecar integrity metadata"
        if descriptor.get("filename") != expected_filename:
            return f"material.json has an invalid {sidecar_key} sidecar filename"
        expected_sha256 = descriptor.get("sha256")
        if not isinstance(expected_sha256, str) or not _SHA256_HEX.fullmatch(expected_sha256):
            return f"material.json has an invalid {sidecar_key} sidecar SHA-256"
        sidecar_path = material_dir / expected_filename
        if not sidecar_path.is_file():
            return f"{expected_filename} is missing"
        try:
            actual_sha256 = _sha256_file(sidecar_path)
        except OSError:
            return f"{expected_filename} could not be read"
        if not hmac.compare_digest(expected_sha256, actual_sha256):
            return f"{expected_filename} SHA-256 does not match material.json"
        sidecar_payload = _load_archive_payload(sidecar_path)
        if sidecar_payload is None:
            return f"{expected_filename} is not valid UTF-8 JSON"
        if sidecar_payload.get("schema_version") != LUMINA_BOX_ARCHIVE_SCHEMA_VERSION:
            return f"{expected_filename} has an unsupported schema_version"
        if sidecar_payload.get("optical_model") != LUMINA_BOX_OPTICAL_MODEL_ID:
            return f"{expected_filename} has an invalid optical_model"
        if (
            sidecar_payload.get("measurement_protocol_id")
            != LUMINA_BOX_PROTOCOL_ID
        ):
            return f"{expected_filename} has an invalid measurement_protocol_id"
        if sidecar_payload.get("color_bridge_id") != LUMINA_BOX_COLOR_BRIDGE_ID:
            return f"{expected_filename} has an invalid color_bridge_id"
        if sidecar_payload.get("archive_consistency") != dict(consistency):
            return f"{expected_filename} archive consistency metadata does not match material.json"
        loaded_sidecars[sidecar_key] = sidecar_payload

    try:
        measurements = _normalized_measurements_sidecar(loaded_sidecars["measurements"])
        _normalized_parameters_sidecar(
            loaded_sidecars["parameters"],
            measurements=measurements,
        )
    except CoreValidationError as exc:
        return f"Lumina Box paired sidecar data is invalid: {exc.detail}"

    if loaded_sidecars["measurements"].get(
        "measurement_backing_percent_xyz"
    ) != archive_payload.get("measurement_backing_base_percent_xyz"):
        return "measurement backing base does not match material.json"
    if loaded_sidecars["measurements"].get(
        "measurement_reflection_boundary_id"
    ) != archive_payload.get("measurement_reflection_boundary_id"):
        return "measurement reflection boundary does not match material.json"
    for field_name in (
        "measurement_backing_base_percent_xyz",
        "measurement_backing_scale",
        "measurement_thickness_offset_mm",
        "measurement_backing_effective_percent_xyz",
        "measurement_reflection_boundary_id",
    ):
        if loaded_sidecars["parameters"].get(field_name) != archive_payload.get(
            field_name
        ):
            return f"{field_name} does not match material.json"

    return None


def validate_lumina_box_material_archive(
    material_dir: Path,
    archive_payload: Mapping[str, Any] | None = None,
) -> bool:
    """Verify Lumina Box sidecar hashes and shared archive metadata.
    校验 Lumina Box 各版本档案的文件哈希及共享身份。

    Invalid archives are hidden from library responses instead of being loaded
    with potentially mismatched measurements and optical parameters.
    """
    payload = archive_payload
    if payload is None:
        payload = _load_archive_payload(material_dir / "material.json")
    if not isinstance(payload, Mapping):
        error_message = "material.json is not valid UTF-8 JSON"
    elif payload.get("optical_model") == SPECTRAL_SMOOTH_MODEL_ID:
        from core.backed_gradient_archive import load_backed_gradient_archive

        try:
            load_backed_gradient_archive(material_dir, payload)
            error_message = None
        except CoreValidationError as exc:
            error_message = exc.detail
    elif payload.get("optical_model") == LUMINA_BOX_SPECTRAL_MODEL_ID:
        from core.lumina_box_spectral_archive import load_spectral_archive

        try:
            load_spectral_archive(material_dir, payload)
            error_message = None
        except CoreValidationError as exc:
            error_message = exc.detail
    else:
        error_message = _sidecar_integrity_error(material_dir, payload)
    if error_message is None:
        return True
    _log.warning(
        "Lumina Box material archive integrity rejected",
        extra={
            "event": "lumina_box_archive_integrity_failed",
            "directory_name": material_dir.name,
            "error_type": "lumina_box_archive_integrity_error",
            "error_message": error_message,
        },
    )
    return False


def _same_identity(
    payload: Mapping[str, Any],
    *,
    material_name: str,
    brand: str | None,
) -> bool:
    if not _is_lumina_box_archive(payload):
        return False
    saved_name = _clean_optional_text(payload.get("material_name"))
    saved_brand = _clean_optional_text(payload.get("brand"))
    return (
        saved_name is not None
        and saved_name.casefold() == material_name.casefold()
        and (saved_brand or "").casefold() == (brand or "").casefold()
    )


def _iter_material_archives(materials_root: Path) -> list[tuple[Path, dict[str, Any]]]:
    if not materials_root.exists():
        return []
    records: list[tuple[Path, dict[str, Any]]] = []
    for archive_path in materials_root.rglob("material.json"):
        if not archive_path.is_file() or any(part.startswith(".") for part in archive_path.relative_to(materials_root).parts):
            continue
        payload = _load_archive_payload(archive_path)
        if payload is not None:
            records.append((archive_path, payload))
    return records


def _find_same_identity_archive(
    materials_root: Path,
    *,
    material_name: str,
    brand: str | None,
) -> tuple[Path, dict[str, Any]] | None:
    matches = [
        (path, payload)
        for path, payload in _iter_material_archives(materials_root)
        if _same_identity(payload, material_name=material_name, brand=brand)
    ]
    if not matches:
        return None
    matches.sort(key=lambda item: item[0].parent.as_posix())
    return matches[0]


def _as_finite_float(value: Any, *, field_name: str) -> float:
    """Return one finite JSON number while rejecting boolean coercion."""
    if isinstance(value, bool):
        raise CoreValidationError(f"{field_name} must be a finite number")
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise CoreValidationError(f"{field_name} must be a finite number") from exc
    if not math.isfinite(numeric):
        raise CoreValidationError(f"{field_name} must be a finite number")
    return numeric


def _as_measurement_thickness_offset_mm(value: Any, *, field_name: str) -> float:
    """Validate the fitted shared acquisition offset against the core bound."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CoreValidationError(f"{field_name} must be a finite number")
    offset_mm = _as_finite_float(value, field_name=field_name)
    if not 0.0 <= offset_mm <= KM_XYZ_MEASUREMENT_THICKNESS_OFFSET_MAX_MM:
        raise CoreValidationError(
            f"{field_name} must be in [0, {KM_XYZ_MEASUREMENT_THICKNESS_OFFSET_MAX_MM}]"
        )
    return offset_mm


def _as_xyz_triplet(
    value: Any,
    *,
    field_name: str,
    lower: float | None = None,
    upper: float | None = None,
) -> list[float]:
    """Validate a finite XYZ triplet with optional inclusive bounds."""
    if not isinstance(value, list) or len(value) != 3:
        raise CoreValidationError(f"{field_name} must contain exactly 3 channels")
    normalized = [
        _as_finite_float(channel, field_name=f"{field_name}[{index}]")
        for index, channel in enumerate(value)
    ]
    if lower is not None and any(channel < lower for channel in normalized):
        raise CoreValidationError(f"{field_name} channels must be >= {lower}")
    if upper is not None and any(channel > upper for channel in normalized):
        raise CoreValidationError(f"{field_name} channels must be <= {upper}")
    return normalized


def _as_percent_xyz(
    value: Any,
    *,
    field_name: str,
    require_positive_channels: bool = False,
) -> list[float]:
    """Validate one percent-scale XYZ triplet for the paired protocol."""
    normalized = _as_xyz_triplet(
        value,
        field_name=field_name,
        lower=0.0,
        upper=100.0,
    )
    if require_positive_channels and any(channel == 0.0 for channel in normalized):
        raise CoreValidationError("transmittance_zero_requires_detection_limit")
    return normalized


def _as_measurement_backing_percent_xyz(value: Any, *, field_name: str) -> list[float]:
    """Validate a user-supplied diffuser base as strict JSON numbers."""
    if not isinstance(value, list) or len(value) != 3:
        raise CoreValidationError(f"{field_name} must contain exactly 3 channels")
    normalized: list[float] = []
    for index, channel in enumerate(value):
        if isinstance(channel, bool) or not isinstance(channel, (int, float)):
            raise CoreValidationError(
                f"{field_name}[{index}] must be a finite number in (0, 100]"
            )
        numeric = float(channel)
        if not math.isfinite(numeric) or not 0.0 < numeric <= 100.0:
            raise CoreValidationError(
                f"{field_name}[{index}] must be a finite number in (0, 100]"
            )
        normalized.append(numeric)
    return normalized


def _as_positive_thickness(value: Any, *, field_name: str) -> float:
    numeric = _as_finite_float(value, field_name=field_name)
    if numeric <= 0.0:
        raise CoreValidationError(f"{field_name} must be a finite positive number")
    return numeric


def evaluate_lumina_box_fit_quality(
    *,
    diagnostics: Mapping[str, Any],
    residual_summary: Mapping[str, Any],
    reference_physics: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Report fit warnings and whether a converged profile can be archived.
    报告拟合警告，并判断已收敛的配色档案是否可保存。

    Residual thresholds are diagnostic notices, not persistence barriers.
    Saving a converged fit preserves its measurements and errors for later
    validation. Original records remain independent of optimizer success.
    误差阈值仅用于诊断提醒；保存时保留测量值和误差，供后续验证。
    原始记录的保存仍不受拟合是否收敛影响。
    """
    reasons: list[str] = []
    if diagnostics.get("success") is not True:
        reasons.append("optimizer_failed")
    if reference_physics and reference_physics.get("lower_bound_active") is True:
        reasons.append("white_reference_lower_bound_active")
    modality_limit = LUMINA_BOX_FIT_QUALITY_THRESHOLDS[
        "modality_rmse_percentage_points"
    ]
    transmittance_rmse = residual_summary.get("transmittance_rmse_percentage_points")
    if isinstance(transmittance_rmse, (int, float)) and float(transmittance_rmse) > modality_limit:
        reasons.append("transmittance_rmse_exceeds_limit")
    reflectance_rmse = residual_summary.get("reflectance_rmse_percentage_points")
    if isinstance(reflectance_rmse, (int, float)) and float(reflectance_rmse) > modality_limit:
        reasons.append("reflectance_rmse_exceeds_limit")
    overall_rmse = residual_summary.get("overall_rmse_percentage_points")
    if isinstance(overall_rmse, (int, float)) and float(overall_rmse) > (
        LUMINA_BOX_FIT_QUALITY_THRESHOLDS["overall_rmse_percentage_points"]
    ):
        reasons.append("overall_rmse_exceeds_limit")
    max_abs_residual = residual_summary.get("max_abs_residual_percentage_points")
    if isinstance(max_abs_residual, (int, float)) and float(max_abs_residual) > (
        LUMINA_BOX_FIT_QUALITY_THRESHOLDS[
            "max_abs_residual_percentage_points"
        ]
    ):
        reasons.append("max_abs_residual_exceeds_limit")
    return {
        "savable": diagnostics.get("success") is True,
        "reasons": reasons,
        "thresholds": dict(LUMINA_BOX_FIT_QUALITY_THRESHOLDS),
    }


def _normalized_fit_quality(
    value: Any,
    *,
    diagnostics: Mapping[str, Any],
    residual_summary: Mapping[str, Any],
) -> dict[str, Any]:
    """Preserve diagnostic warnings while rejecting forged or failed fits."""
    expected_quality = evaluate_lumina_box_fit_quality(
        diagnostics=diagnostics,
        residual_summary=residual_summary,
    )
    if not isinstance(value, dict) or set(value) != {
        "savable",
        "reasons",
        "thresholds",
    }:
        raise CoreValidationError("Lumina Box fit_quality has an invalid shape")
    if value != expected_quality:
        raise CoreValidationError("Lumina Box fit_quality does not match fit diagnostics")
    if not expected_quality["savable"]:
        raise CoreValidationError(LUMINA_BOX_FIT_QUALITY_UNSAVABLE_CODE)
    return expected_quality


def _normalized_measurement_payload(
    value: Mapping[str, Any], *, allow_zero_transmittance: bool = False,
) -> dict[str, Any]:
    """Validate paired readings, preserving the historical KM positive-T contract."""
    measurements = _json_clone(value)
    if not isinstance(measurements, dict):
        raise CoreValidationError("Lumina Box measurement record must be a JSON object")
    expected_fields = {
        "protocol_id",
        "value_scale",
        "measurement_backing_percent_xyz",
        "samples",
    }
    if set(measurements) != expected_fields:
        raise CoreValidationError(
            "Lumina Box measurement record must contain only paired percent samples"
        )
    if measurements["protocol_id"] != LUMINA_BOX_PROTOCOL_ID:
        raise CoreValidationError("Lumina Box measurement record has an invalid protocol_id")
    if measurements["value_scale"] != LUMINA_BOX_VALUE_SCALE:
        raise CoreValidationError("Lumina Box measurement record has an invalid value_scale")
    measurement_backing_percent_xyz = _as_measurement_backing_percent_xyz(
        measurements["measurement_backing_percent_xyz"],
        field_name="measurement_backing_percent_xyz",
    )
    raw_samples = measurements["samples"]
    if not isinstance(raw_samples, list) or len(raw_samples) < 3:
        raise CoreValidationError("Lumina Box measurement record requires at least three samples")

    samples: list[dict[str, Any]] = []
    for index, sample in enumerate(raw_samples):
        if not isinstance(sample, dict) or set(sample) != {
            "thickness_mm",
            "transmittance_percent_xyz",
            "reflectance_percent_xyz",
        }:
            raise CoreValidationError("Lumina Box paired sample has an invalid shape")
        samples.append(
            {
                "thickness_mm": _as_positive_thickness(
                    sample["thickness_mm"],
                    field_name=f"samples[{index}].thickness_mm",
                ),
                "transmittance_percent_xyz": _as_percent_xyz(
                    sample["transmittance_percent_xyz"],
                    field_name=f"samples[{index}].transmittance_percent_xyz",
                    require_positive_channels=not allow_zero_transmittance,
                ),
                "reflectance_percent_xyz": _as_percent_xyz(
                    sample["reflectance_percent_xyz"],
                    field_name=f"samples[{index}].reflectance_percent_xyz",
                ),
            }
        )
    thicknesses = [sample["thickness_mm"] for sample in samples]
    if len(set(thicknesses)) != len(thicknesses):
        raise CoreValidationError("Lumina Box samples must not repeat a thickness_mm value")
    samples.sort(key=lambda sample: sample["thickness_mm"])
    return {
        "protocol_id": LUMINA_BOX_PROTOCOL_ID,
        "value_scale": LUMINA_BOX_VALUE_SCALE,
        "measurement_backing_percent_xyz": measurement_backing_percent_xyz,
        "samples": samples,
    }


def _as_string_list(value: Any, *, field_name: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise CoreValidationError(f"{field_name} must be a list of strings")
    return list(value)


def _normalized_modality_prediction(value: Any, *, field_name: str) -> dict[str, Any]:
    expected_fields = {
        "measured_percent_xyz",
        "predicted_percent_xyz",
        "residual_percentage_points_xyz",
    }
    if not isinstance(value, dict) or set(value) != expected_fields:
        raise CoreValidationError(f"{field_name} has an invalid paired prediction shape")
    measured = _as_percent_xyz(
        value["measured_percent_xyz"],
        field_name=f"{field_name}.measured_percent_xyz",
    )
    predicted = _as_percent_xyz(
        value["predicted_percent_xyz"],
        field_name=f"{field_name}.predicted_percent_xyz",
    )
    residual = _as_xyz_triplet(
        value["residual_percentage_points_xyz"],
        field_name=f"{field_name}.residual_percentage_points_xyz",
    )
    for index, residual_value in enumerate(residual):
        if not math.isclose(
            residual_value,
            predicted[index] - measured[index],
            rel_tol=0.0,
            abs_tol=1.0e-8,
        ):
            raise CoreValidationError(
                f"{field_name}.residual_percentage_points_xyz does not match "
                "predicted minus measured"
            )
    return {
        "measured_percent_xyz": measured,
        "predicted_percent_xyz": predicted,
        "residual_percentage_points_xyz": residual,
    }


def _normalized_sample_predictions(
    value: Any,
    *,
    measurements: Mapping[str, Any],
) -> list[dict[str, Any]]:
    samples = measurements["samples"]
    if not isinstance(value, list) or len(value) != len(samples):
        raise CoreValidationError(
            "Lumina Box sample_predictions must match the paired measurement count"
        )
    normalized: list[dict[str, Any]] = []
    for index, (prediction, measurement) in enumerate(zip(value, samples, strict=True)):
        expected_fields = {"thickness_mm", "transmittance", "reflectance"}
        if not isinstance(prediction, dict) or set(prediction) != expected_fields:
            raise CoreValidationError("Lumina Box sample prediction has an invalid shape")
        thickness = _as_positive_thickness(
            prediction["thickness_mm"],
            field_name=f"sample_predictions[{index}].thickness_mm",
        )
        if not math.isclose(
            thickness,
            float(measurement["thickness_mm"]),
            rel_tol=0.0,
            abs_tol=1.0e-12,
        ):
            raise CoreValidationError(
                "Lumina Box sample prediction thicknesses do not match measurements"
            )
        transmittance = _normalized_modality_prediction(
            prediction["transmittance"],
            field_name=f"sample_predictions[{index}].transmittance",
        )
        reflectance = _normalized_modality_prediction(
            prediction["reflectance"],
            field_name=f"sample_predictions[{index}].reflectance",
        )
        for response_key, measurement_key, modality in (
            ("transmittance", "transmittance_percent_xyz", transmittance),
            ("reflectance", "reflectance_percent_xyz", reflectance),
        ):
            if any(
                not math.isclose(
                    observed,
                    float(expected),
                    rel_tol=0.0,
                    abs_tol=1.0e-12,
                )
                for observed, expected in zip(
                    modality["measured_percent_xyz"],
                    measurement[measurement_key],
                    strict=True,
                )
            ):
                raise CoreValidationError(
                    "Lumina Box sample prediction measured values do not match "
                    f"{response_key} measurements"
                )
        normalized.append(
            {
                "thickness_mm": thickness,
                "transmittance": transmittance,
                "reflectance": reflectance,
            }
        )
    return normalized


def _normalized_residual_summary(value: Any) -> dict[str, Any]:
    expected_fields = {
        "transmittance_channel_rmse_percentage_points_xyz",
        "reflectance_channel_rmse_percentage_points_xyz",
        "channel_rmse_percentage_points_xyz",
        "transmittance_rmse_percentage_points",
        "reflectance_rmse_percentage_points",
        "overall_rmse_percentage_points",
        "max_abs_residual_percentage_points",
        "max_abs_location",
    }
    if not isinstance(value, dict) or set(value) != expected_fields:
        raise CoreValidationError("Lumina Box residual_summary has an invalid shape")
    normalized: dict[str, Any] = {}
    for field_name in (
        "transmittance_channel_rmse_percentage_points_xyz",
        "reflectance_channel_rmse_percentage_points_xyz",
        "channel_rmse_percentage_points_xyz",
    ):
        channels = _as_xyz_triplet(value[field_name], field_name=field_name, lower=0.0)
        normalized[field_name] = channels
    for field_name in (
        "transmittance_rmse_percentage_points",
        "reflectance_rmse_percentage_points",
        "overall_rmse_percentage_points",
        "max_abs_residual_percentage_points",
    ):
        metric = _as_finite_float(value[field_name], field_name=field_name)
        if metric < 0.0:
            raise CoreValidationError(f"{field_name} must be non-negative")
        normalized[field_name] = metric
    location = value["max_abs_location"]
    expected_location_fields = {
        "thickness_mm",
        "modality",
        "channel",
        "signed_residual_percentage_points",
    }
    if not isinstance(location, dict) or set(location) != expected_location_fields:
        raise CoreValidationError("Lumina Box max_abs_location has an invalid shape")
    modality = location["modality"]
    channel = location["channel"]
    if modality not in {"transmittance", "reflectance"}:
        raise CoreValidationError("Lumina Box max_abs_location has an invalid modality")
    if channel not in {"X", "Y", "Z"}:
        raise CoreValidationError("Lumina Box max_abs_location has an invalid channel")
    normalized["max_abs_location"] = {
        "thickness_mm": _as_positive_thickness(
            location["thickness_mm"],
            field_name="max_abs_location.thickness_mm",
        ),
        "modality": modality,
        "channel": channel,
        "signed_residual_percentage_points": _as_finite_float(
            location["signed_residual_percentage_points"],
            field_name="max_abs_location.signed_residual_percentage_points",
        ),
    }
    return normalized


def _normalized_diagnostics(
    value: Any, *, objective_id: str = LUMINA_BOX_OBJECTIVE_ID,
) -> dict[str, Any]:
    expected_fields = {
        "success",
        "message",
        "nfev",
        "start_count",
        "robust_objective",
        "jacobian_condition",
        "measurement_thickness_offset_mm",
        "objective_id",
        "objective_config",
        "channels",
        "warnings",
    }
    if not isinstance(value, dict) or set(value) != expected_fields:
        raise CoreValidationError("Lumina Box diagnostics has an invalid shape")
    if not isinstance(value["success"], bool):
        raise CoreValidationError("Lumina Box diagnostics.success must be a boolean")
    if not isinstance(value["message"], str):
        raise CoreValidationError("Lumina Box diagnostics.message must be a string")
    if not isinstance(value["objective_id"], str) or not value["objective_id"].strip():
        raise CoreValidationError("Lumina Box diagnostics.objective_id is required")
    if value["objective_id"] != objective_id:
        raise CoreValidationError("Lumina Box diagnostics.objective_id is unsupported")
    if not isinstance(value["objective_config"], dict):
        raise CoreValidationError("Lumina Box diagnostics.objective_config must be an object")
    channels = value["channels"]
    if not isinstance(channels, list) or len(channels) != 3:
        raise CoreValidationError("Lumina Box diagnostics.channels must contain X, Y, and Z")
    normalized_channels: list[dict[str, Any]] = []
    expected_channel_fields = {
        "channel",
        "transmittance_rmse",
        "reflectance_rmse",
        "warnings",
    }
    for channel in channels:
        if not isinstance(channel, dict) or set(channel) != expected_channel_fields:
            raise CoreValidationError("Lumina Box channel diagnostics has an invalid shape")
        if channel["channel"] not in {"X", "Y", "Z"}:
            raise CoreValidationError("Lumina Box channel diagnostics has an invalid channel")
        normalized_channels.append(
            {
                "channel": channel["channel"],
                "transmittance_rmse": _as_finite_float(
                    channel["transmittance_rmse"],
                    field_name="channel diagnostics.transmittance_rmse",
                ),
                "reflectance_rmse": _as_finite_float(
                    channel["reflectance_rmse"],
                    field_name="channel diagnostics.reflectance_rmse",
                ),
                "warnings": _as_string_list(
                    channel["warnings"],
                    field_name="channel diagnostics.warnings",
                ),
            }
        )
    if {item["channel"] for item in normalized_channels} != {"X", "Y", "Z"}:
        raise CoreValidationError("Lumina Box diagnostics.channels must contain X, Y, and Z")
    def _as_non_negative_integer(field_name: str) -> int:
        raw_value = value[field_name]
        if isinstance(raw_value, bool):
            raise CoreValidationError(f"Lumina Box diagnostics.{field_name} must be an integer")
        try:
            integer = int(raw_value)
        except (TypeError, ValueError) as exc:
            raise CoreValidationError(
                f"Lumina Box diagnostics.{field_name} must be an integer"
            ) from exc
        if integer < 0 or integer != raw_value:
            raise CoreValidationError(
                f"Lumina Box diagnostics.{field_name} must be non-negative"
            )
        return integer
    jacobian = value["jacobian_condition"]
    if jacobian is not None:
        jacobian = _as_finite_float(
            jacobian,
            field_name="diagnostics.jacobian_condition",
        )
    return {
        "success": value["success"],
        "message": value["message"],
        "nfev": _as_non_negative_integer("nfev"),
        "start_count": _as_non_negative_integer("start_count"),
        "robust_objective": _as_finite_float(
            value["robust_objective"],
            field_name="diagnostics.robust_objective",
        ),
        "jacobian_condition": jacobian,
        "measurement_thickness_offset_mm": _as_measurement_thickness_offset_mm(
            value["measurement_thickness_offset_mm"],
            field_name="diagnostics.measurement_thickness_offset_mm",
        ),
        "objective_id": value["objective_id"],
        "objective_config": _json_clone(value["objective_config"]),
        "channels": normalized_channels,
        "warnings": _as_string_list(value["warnings"], field_name="diagnostics.warnings"),
    }


def _normalized_fit_payload(
    value: Mapping[str, Any],
    *,
    measurements: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate durable paired predictions and diagnostics without aliases."""
    fit = _json_clone(value)
    if not isinstance(fit, dict):
        raise CoreValidationError("Lumina Box fit record must be a JSON object")
    expected_fields = {
        "parameters",
        "sample_predictions",
        "residual_summary",
        "diagnostics",
        "measurement_backing_base_percent_xyz",
        "measurement_backing_scale",
        "measurement_thickness_offset_mm",
        "measurement_backing_effective_percent_xyz",
        "measurement_reflection_boundary_id",
        "fit_quality",
        "estimated_effective_d65_10_xyz_relative",
        "estimated_reflectance_thickness_mm",
        "estimated_rgb",
        "warnings",
    }
    if set(fit) != expected_fields:
        raise CoreValidationError("Lumina Box fit record has an invalid paired shape")
    parameters = fit["parameters"]
    if not isinstance(parameters, dict) or set(parameters) != {"K", "S", "unit"}:
        raise CoreValidationError("Lumina Box fit result is missing KM parameters")
    if parameters["unit"] != "mm^-1":
        raise CoreValidationError("Lumina Box KM coefficient unit must be mm^-1")
    K = _as_xyz_triplet(parameters["K"], field_name="parameters.K", lower=0.0)
    S = _as_xyz_triplet(parameters["S"], field_name="parameters.S", lower=0.0)
    sample_predictions = _normalized_sample_predictions(
        fit["sample_predictions"],
        measurements=measurements,
    )
    residual_summary = _normalized_residual_summary(fit["residual_summary"])
    diagnostics = _normalized_diagnostics(fit["diagnostics"])
    measurement_backing_base_percent_xyz = _as_measurement_backing_percent_xyz(
        fit["measurement_backing_base_percent_xyz"],
        field_name="measurement_backing_base_percent_xyz",
    )
    if any(
        not math.isclose(actual, expected, rel_tol=0.0, abs_tol=1.0e-12)
        for actual, expected in zip(
            measurement_backing_base_percent_xyz,
            measurements["measurement_backing_percent_xyz"],
            strict=True,
        )
    ):
        raise CoreValidationError(
            "measurement_backing_base_percent_xyz must match the request snapshot"
        )
    measurement_backing_scale = _as_finite_float(
        fit["measurement_backing_scale"],
        field_name="measurement_backing_scale",
    )
    if measurement_backing_scale <= 0.0:
        raise CoreValidationError("measurement_backing_scale must be positive")
    measurement_backing_scale_max = 100.0 / max(
        measurement_backing_base_percent_xyz
    )
    if measurement_backing_scale > measurement_backing_scale_max + 1.0e-12:
        raise CoreValidationError("measurement_backing_scale exceeds its derived bound")
    measurement_thickness_offset_mm = _as_measurement_thickness_offset_mm(
        fit["measurement_thickness_offset_mm"],
        field_name="measurement_thickness_offset_mm",
    )
    if not math.isclose(
        measurement_thickness_offset_mm,
        diagnostics["measurement_thickness_offset_mm"],
        rel_tol=0.0,
        abs_tol=1.0e-12,
    ):
        raise CoreValidationError(
            "measurement_thickness_offset_mm must match fit diagnostics"
        )
    measurement_backing_effective_percent_xyz = _as_xyz_triplet(
        fit["measurement_backing_effective_percent_xyz"],
        field_name="measurement_backing_effective_percent_xyz",
        lower=0.0,
        upper=100.0,
    )
    if any(
        not math.isclose(
            actual,
            measurement_backing_scale * base,
            rel_tol=0.0,
            abs_tol=1.0e-10,
        )
        for actual, base in zip(
            measurement_backing_effective_percent_xyz,
            measurement_backing_base_percent_xyz,
            strict=True,
        )
    ):
        raise CoreValidationError(
            "measurement_backing_effective_percent_xyz must equal scale times base"
        )
    if (
        fit["measurement_reflection_boundary_id"]
        != LUMINA_BOX_MEASUREMENT_REFLECTION_BOUNDARY_ID
    ):
        raise CoreValidationError("Lumina Box fit has an invalid reflection boundary")
    fit_quality = _normalized_fit_quality(
        fit["fit_quality"],
        diagnostics=diagnostics,
        residual_summary=residual_summary,
    )
    estimated_relative = _as_xyz_triplet(
        fit["estimated_effective_d65_10_xyz_relative"],
        field_name="estimated_effective_d65_10_xyz_relative",
        lower=0.0,
        upper=1.0,
    )
    estimated_thickness = _as_positive_thickness(
        fit["estimated_reflectance_thickness_mm"],
        field_name="estimated_reflectance_thickness_mm",
    )
    last_prediction = sample_predictions[-1]
    if not math.isclose(
        estimated_thickness,
        last_prediction["thickness_mm"],
        rel_tol=0.0,
        abs_tol=1.0e-12,
    ):
        raise CoreValidationError(
            "estimated_reflectance_thickness_mm must be the greatest sample thickness"
        )
    expected_estimated = [
        channel / 100.0
        for channel in last_prediction["reflectance"]["predicted_percent_xyz"]
    ]
    if any(
        not math.isclose(actual, expected, rel_tol=0.0, abs_tol=1.0e-10)
        for actual, expected in zip(estimated_relative, expected_estimated, strict=True)
    ):
        raise CoreValidationError(
            "estimated_effective_d65_10_xyz_relative must match the greatest-thickness "
            "predicted reflectance"
        )
    estimated_rgb = fit["estimated_rgb"]
    if (
        not isinstance(estimated_rgb, list)
        or len(estimated_rgb) != 3
        or any(isinstance(channel, bool) for channel in estimated_rgb)
    ):
        raise CoreValidationError("estimated_rgb must contain exactly 3 integer channels")
    normalized_rgb: list[int] = []
    for channel in estimated_rgb:
        try:
            integer = int(channel)
        except (TypeError, ValueError) as exc:
            raise CoreValidationError(
                "estimated_rgb must contain exactly 3 integer channels"
            ) from exc
        if integer != channel or not 0 <= integer <= 255:
            raise CoreValidationError("estimated_rgb channels must be integers in [0, 255]")
        normalized_rgb.append(integer)
    return {
        "parameters": {"K": K, "S": S, "unit": "mm^-1"},
        "sample_predictions": sample_predictions,
        "residual_summary": residual_summary,
        "diagnostics": diagnostics,
        "measurement_backing_base_percent_xyz": measurement_backing_base_percent_xyz,
        "measurement_backing_scale": measurement_backing_scale,
        "measurement_thickness_offset_mm": measurement_thickness_offset_mm,
        "measurement_backing_effective_percent_xyz": (
            measurement_backing_effective_percent_xyz
        ),
        "measurement_reflection_boundary_id": (
            LUMINA_BOX_MEASUREMENT_REFLECTION_BOUNDARY_ID
        ),
        "fit_quality": fit_quality,
        "estimated_effective_d65_10_xyz_relative": estimated_relative,
        "estimated_reflectance_thickness_mm": estimated_thickness,
        "estimated_rgb": normalized_rgb,
        "warnings": _as_string_list(fit["warnings"], field_name="warnings"),
    }


def _normalized_measurements_sidecar(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the 2.2 measurement sidecar without accepting legacy shapes."""
    expected_fields = {
        "schema_version",
        "measurement_protocol_id",
        "objective_id",
        "optical_model",
        "color_bridge_id",
        "archive_consistency",
        "value_scale",
        "measurement_backing_percent_xyz",
        "measurement_reflection_boundary_id",
        "samples",
    }
    if set(value) != expected_fields:
        raise CoreValidationError("Lumina Box measurements sidecar has an invalid shape")
    if value["objective_id"] != LUMINA_BOX_OBJECTIVE_ID:
        raise CoreValidationError("Lumina Box measurements sidecar has an invalid objective_id")
    if (
        value["measurement_reflection_boundary_id"]
        != LUMINA_BOX_MEASUREMENT_REFLECTION_BOUNDARY_ID
    ):
        raise CoreValidationError(
            "Lumina Box measurements sidecar has an invalid reflection boundary"
        )
    return _normalized_measurement_payload(
        {
            "protocol_id": value["measurement_protocol_id"],
            "value_scale": value["value_scale"],
            "measurement_backing_percent_xyz": value[
                "measurement_backing_percent_xyz"
            ],
            "samples": value["samples"],
        }
    )


def _normalized_parameters_sidecar(
    value: Mapping[str, Any],
    *,
    measurements: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate the 2.2 parameter sidecar's paired prediction records."""
    expected_fields = {
        "schema_version",
        "measurement_protocol_id",
        "optical_model",
        "color_bridge_id",
        "coefficient_unit",
        "archive_consistency",
        "value_scale",
        "residual_unit",
        "parameters",
        "objective_id",
        "objective_config",
        "sample_predictions",
        "residual_summary",
        "diagnostics",
        "measurement_backing_base_percent_xyz",
        "measurement_backing_scale",
        "measurement_thickness_offset_mm",
        "measurement_backing_effective_percent_xyz",
        "measurement_reflection_boundary_id",
        "fit_quality",
        "estimated_effective_d65_10_xyz_relative",
        "estimated_reflectance_thickness_mm",
        "estimated_rgb",
        "warnings",
    }
    if set(value) != expected_fields:
        raise CoreValidationError("Lumina Box parameters sidecar has an invalid shape")
    if value["coefficient_unit"] != "mm^-1":
        raise CoreValidationError("Lumina Box parameters sidecar has an invalid coefficient_unit")
    if value["value_scale"] != LUMINA_BOX_VALUE_SCALE:
        raise CoreValidationError("Lumina Box parameters sidecar has an invalid value_scale")
    if value["residual_unit"] != LUMINA_BOX_RESIDUAL_UNIT:
        raise CoreValidationError("Lumina Box parameters sidecar has an invalid residual_unit")
    if value["objective_id"] != LUMINA_BOX_OBJECTIVE_ID:
        raise CoreValidationError("Lumina Box parameters sidecar has an invalid objective_id")
    diagnostics = value["diagnostics"]
    if not isinstance(diagnostics, dict) or set(diagnostics) != {
        "success",
        "message",
        "nfev",
        "start_count",
        "robust_objective",
        "jacobian_condition",
        "measurement_thickness_offset_mm",
        "channels",
        "warnings",
    }:
        raise CoreValidationError("Lumina Box parameters diagnostics has an invalid shape")
    return _normalized_fit_payload(
        {
            "parameters": value["parameters"],
            "sample_predictions": value["sample_predictions"],
            "residual_summary": value["residual_summary"],
            "diagnostics": {
                "success": diagnostics["success"],
                "message": diagnostics["message"],
                "nfev": diagnostics["nfev"],
                "start_count": diagnostics["start_count"],
                "robust_objective": diagnostics["robust_objective"],
                "jacobian_condition": diagnostics["jacobian_condition"],
                "measurement_thickness_offset_mm": diagnostics[
                    "measurement_thickness_offset_mm"
                ],
                "objective_id": value["objective_id"],
                "objective_config": value["objective_config"],
                "channels": diagnostics["channels"],
                "warnings": diagnostics["warnings"],
            },
            "measurement_backing_base_percent_xyz": value[
                "measurement_backing_base_percent_xyz"
            ],
            "measurement_backing_scale": value["measurement_backing_scale"],
            "measurement_thickness_offset_mm": value[
                "measurement_thickness_offset_mm"
            ],
            "measurement_backing_effective_percent_xyz": value[
                "measurement_backing_effective_percent_xyz"
            ],
            "measurement_reflection_boundary_id": value[
                "measurement_reflection_boundary_id"
            ],
            "fit_quality": value["fit_quality"],
            "estimated_effective_d65_10_xyz_relative": value[
                "estimated_effective_d65_10_xyz_relative"
            ],
            "estimated_reflectance_thickness_mm": value[
                "estimated_reflectance_thickness_mm"
            ],
            "estimated_rgb": value["estimated_rgb"],
            "warnings": value["warnings"],
        },
        measurements=measurements,
    )


def _archive_summary(
    materials_root: Path,
    material_dir: Path,
    archive_payload: Mapping[str, Any],
) -> dict[str, Any]:
    if archive_payload.get("optical_model") == SPECTRAL_SMOOTH_MODEL_ID:
        from core.single_stage.material_library import (
            _lumina_box_material_library_item_from_archive,
        )

        return _lumina_box_material_library_item_from_archive(materials_root, material_dir, dict(archive_payload))
    if archive_payload.get("optical_model") == LUMINA_BOX_SPECTRAL_MODEL_ID:
        from core.lumina_box_spectral_archive import spectral_archive_summary

        return spectral_archive_summary(materials_root, material_dir, archive_payload)
    estimated_relative_xyz = archive_payload.get(
        "estimated_effective_d65_10_xyz_relative"
    )
    if not isinstance(estimated_relative_xyz, list):
        estimated_relative_xyz = []
    estimated_rgb = archive_payload.get("estimated_rgb")
    if not isinstance(estimated_rgb, list):
        estimated_rgb = []
    return {
        "material_name": str(archive_payload.get("material_name") or material_dir.name),
        "directory_name": _relative_directory_name(materials_root, material_dir),
        "brand": _clean_optional_text(archive_payload.get("brand")),
        "material_type": _clean_optional_text(archive_payload.get("material_type")),
        "notes": _clean_optional_text(archive_payload.get("notes")),
        "created_at": archive_payload.get("created_at"),
        "updated_at": archive_payload.get("updated_at") or archive_payload.get("created_at"),
        "profile_kind": LUMINA_BOX_PROFILE_KIND,
        "acquisition_source": LUMINA_BOX_ACQUISITION_SOURCE,
        "optical_model": str(
            archive_payload.get("optical_model") or LUMINA_BOX_OPTICAL_MODEL_ID
        ),
        "optical_model_id": str(
            archive_payload.get("optical_model") or LUMINA_BOX_OPTICAL_MODEL_ID
        ),
        "measurement_protocol_id": str(
            archive_payload.get("measurement_protocol_id") or LUMINA_BOX_PROTOCOL_ID
        ),
        "color_bridge_id": LUMINA_BOX_COLOR_BRIDGE_ID,
        "measurement_backing_base_percent_xyz": _json_clone(
            archive_payload.get("measurement_backing_base_percent_xyz") or []
        ),
        "measurement_backing_scale": archive_payload.get(
            "measurement_backing_scale"
        ),
        "measurement_thickness_offset_mm": archive_payload.get(
            "measurement_thickness_offset_mm"
        ),
        "measurement_backing_effective_percent_xyz": _json_clone(
            archive_payload.get("measurement_backing_effective_percent_xyz") or []
        ),
        "measurement_reflection_boundary_id": archive_payload.get(
            "measurement_reflection_boundary_id"
        ),
        "estimated_effective_d65_10_xyz_relative": _json_clone(
            estimated_relative_xyz
        ),
        "estimated_reflectance_thickness_mm": archive_payload.get(
            "estimated_reflectance_thickness_mm"
        ),
        "estimated_rgb": _json_clone(estimated_rgb),
        "archive_path": str(material_dir / "material.json"),
        "measurements_path": str(material_dir / LUMINA_BOX_MEASUREMENTS_FILENAME),
        "parameters_path": str(material_dir / LUMINA_BOX_PARAMETERS_FILENAME),
    }


def list_lumina_box_material_archives(
    *,
    materials_dir: str | None = None,
) -> list[dict[str, Any]]:
    """List valid Lumina Box archives sorted by newest on-disk update first.
    按更新时间倒序列出通过完整性校验的各版本 Lumina Box 档案。
    """
    materials_root = Path(materials_dir or MATERIALS_DIR)
    items: list[dict[str, Any]] = []
    for archive_path, payload in _iter_material_archives(materials_root):
        if not _is_lumina_box_archive(payload):
            continue
        material_dir = archive_path.parent
        if not validate_lumina_box_material_archive(material_dir, payload):
            continue
        items.append(_archive_summary(materials_root, material_dir, payload))
    items.sort(
        key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""),
        reverse=True,
    )
    return items


_RAW_MEASUREMENT_FIELDS = (
    "material_name", "brand", "material_type", "notes",
    "measurement_backing_percent_xyz", "samples",
)
_RAW_REFERENCE_FIELDS = (
    "is_reference_white", "reference_directory_name", "reference_min_reflectance_percent",
)


def _raw_xyz_strings(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 3
        and all(isinstance(channel, str) for channel in value)
    )


def _validated_raw_measurements(value: Mapping[str, Any]) -> dict[str, Any]:
    data = _json_clone(value)
    if (not isinstance(data, dict) or not set(_RAW_MEASUREMENT_FIELDS).issubset(data)
            or set(data) - set(_RAW_MEASUREMENT_FIELDS + _RAW_REFERENCE_FIELDS)):
        raise CoreValidationError("Raw measurement data has an invalid shape")
    if not isinstance(data.get("is_reference_white", False), bool):
        raise CoreValidationError("Raw white-reference role must be boolean")
    reference_name = data.get("reference_directory_name")
    if reference_name is not None and not isinstance(reference_name, str):
        raise CoreValidationError("Raw white-reference selection must contain text")
    minimum = data.get("reference_min_reflectance_percent")
    if minimum is not None and (not isinstance(minimum, str) or len(minimum) > 128):
        raise CoreValidationError("Raw white-reference lower bound must contain text")
    if any(
        not isinstance(data[field], str)
        for field in _RAW_MEASUREMENT_FIELDS[:4]
    ):
        raise CoreValidationError("Raw measurement metadata must contain text")
    if not _raw_xyz_strings(data["measurement_backing_percent_xyz"]):
        raise CoreValidationError("Raw diffuser readings require three text values")
    samples = data["samples"]
    if not isinstance(samples, list) or len(samples) > 512:
        raise CoreValidationError("Raw measurements require at most 512 rows")
    for sample in samples:
        if not isinstance(sample, dict) or set(sample) != {
            "thickness_mm", "reflectance_percent_xyz", "transmittance_percent_xyz",
        }:
            raise CoreValidationError("Raw measurement row has an invalid shape")
        if (
            not isinstance(sample["thickness_mm"], str)
            or not _raw_xyz_strings(sample["reflectance_percent_xyz"])
            or not _raw_xyz_strings(sample["transmittance_percent_xyz"])
        ):
            raise CoreValidationError("Raw thickness and XYZ readings must be text")
    return data


def _measurement_records_root(materials_dir: str | None) -> Path:
    return Path(materials_dir or MATERIALS_DIR) / ".lumina-box-measurements"


def save_lumina_box_measurements(
    data: Mapping[str, Any], *, materials_dir: str | None = None,
) -> dict[str, Any]:
    """Save an immutable raw capture independently of fitting and sessions.
    独立于拟合与会话，保存一份不会覆盖旧记录的原始采集数据。

    Args:
        data: Input text, including incomplete or out-of-fit-range rows.
            （输入原文，允许未填完或超出拟合范围的行）
        materials_dir: Optional library root.（可选的耗材库根目录）

    Returns:
        The persisted record, including its ID and creation time.
        （已保存的记录，含编号与创建时间）
    """
    record = {
        **_validated_raw_measurements(data),
        "schema_version": "1.2",
        "kind": "lumina_box_measurements",
        "record_id": str(uuid.uuid4()),
        "created_at": _now_iso(),
    }
    directory = _measurement_records_root(materials_dir)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{record['record_id']}.json"
    staging = directory / f".{record['record_id']}.tmp"
    try:
        _write_json(staging, record)
        os.replace(staging, target)
    finally:
        staging.unlink(missing_ok=True)
    return record


def load_lumina_box_measurements(
    record_id: str, *, materials_dir: str | None = None,
) -> dict[str, Any]:
    """Read saved input text without fitting or changing it.
    读取保存的输入原文，不执行拟合或修改数据。

    Args:
        record_id: UUID of the saved capture.（采集记录的 UUID）
        materials_dir: Optional library root.（可选的耗材库根目录）

    Returns:
        The saved capture.（已保存的采集记录）
    """
    try:
        canonical_id = str(uuid.UUID(record_id))
    except (ValueError, TypeError, AttributeError) as exc:
        raise CoreValidationError("Invalid measurement record ID") from exc
    path = _measurement_records_root(materials_dir) / f"{canonical_id}.json"
    if not path.is_file():
        raise FileNotFoundError("Lumina Box measurement record was not found")
    record = _load_archive_payload(path)
    if (
        record is None
        or record.get("kind") != "lumina_box_measurements"
        or record.get("record_id") != canonical_id
        or not isinstance(record.get("created_at"), str)
    ):
        raise CoreValidationError("Saved measurement record is unreadable")
    _validated_raw_measurements({
        key: record.get(key) for key in _RAW_MEASUREMENT_FIELDS + _RAW_REFERENCE_FIELDS if key in record
    })
    return record


def list_lumina_box_measurements(
    *, materials_dir: str | None = None,
) -> list[dict[str, Any]]:
    """List saved raw captures without admitting them as fitted materials.
    列出原始采集记录，不将它们当作已拟合耗材使用。

    Args:
        materials_dir: Optional library root.（可选的耗材库根目录）

    Returns:
        Capture summaries sorted newest first.（按时间倒序的采集摘要）
    """
    records: list[dict[str, Any]] = []
    for path in _measurement_records_root(materials_dir).glob("*.json"):
        try:
            record = load_lumina_box_measurements(
                path.stem, materials_dir=materials_dir,
            )
        except (CoreValidationError, OSError) as exc:
            _log.warning(
                "Saved Lumina Box measurements could not be read",
                extra={
                    "event": "lumina_box_measurements_read_failed",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "path": str(path),
                },
            )
            continue
        records.append({
            key: record[key]
            for key in ("record_id", "created_at", "material_name", "brand")
        } | {"sample_count": len(record["samples"])})
    return sorted(records, key=lambda item: item["created_at"], reverse=True)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_bytes(_json_bytes(payload))


def _commit_staged_material_directory(
    *,
    staged_dir: Path,
    target_dir: Path,
    overwrite: bool,
) -> None:
    """Swap a complete staged directory into place without exposing partial files."""
    backup_dir: Path | None = None
    if target_dir.exists():
        if not overwrite:
            raise MaterialArchiveConflictError(
                "A material archive already uses this Lumina Box brand and name"
            )
        backup_dir = target_dir.parent / f".{target_dir.name}.lumina-box-backup-{uuid.uuid4().hex}"
        os.replace(target_dir, backup_dir)
    try:
        os.replace(staged_dir, target_dir)
    except OSError:
        if backup_dir is not None and backup_dir.exists() and not target_dir.exists():
            os.replace(backup_dir, target_dir)
        raise
    if backup_dir is not None:
        shutil.rmtree(backup_dir, ignore_errors=True)


def save_lumina_box_material_archive(
    *,
    material_name: str,
    brand: str | None,
    material_type: str | None,
    notes: str | None,
    measurement_payload: Mapping[str, Any],
    fit_payload: Mapping[str, Any],
    overwrite: bool = False,
    materials_dir: str | None = None,
) -> LuminaBoxMaterialArchiveSaveResult:
    """Persist a server-owned Lumina Box fit as a three-file material archive.
    按模型版本将服务器持有的拟合保存为完整的三文件耗材档案。

    Existing same-brand/name Lumina Box archives are rejected by default.  When
    ``overwrite`` is explicit, the completed staged directory replaces the old
    directory as one swap; a failed swap restores the pre-existing archive.
    """
    if fit_payload.get("optical_model_id") == LUMINA_BOX_SPECTRAL_MODEL_ID:
        from core.lumina_box_spectral_archive import save_spectral_material_archive

        return save_spectral_material_archive(
            material_name=material_name, brand=brand, material_type=material_type, notes=notes,
            measurement_payload=measurement_payload, fit_payload=fit_payload,
            overwrite=overwrite, materials_dir=materials_dir,
        )
    cleaned_name = _clean_required_text(material_name, field_name="material_name")
    cleaned_brand = _clean_optional_text(brand)
    cleaned_type = _clean_optional_text(material_type)
    cleaned_notes = _clean_optional_text(notes)
    measurements = _normalized_measurement_payload(measurement_payload)
    fit = _normalized_fit_payload(
        fit_payload,
        measurements=measurements,
    )
    parameters = fit["parameters"]
    K = parameters["K"]
    S = parameters["S"]

    materials_root = Path(materials_dir or MATERIALS_DIR)
    with _ARCHIVE_WRITE_LOCK:
        materials_root.mkdir(parents=True, exist_ok=True)
        existing = _find_same_identity_archive(
            materials_root,
            material_name=cleaned_name,
            brand=cleaned_brand,
        )
        if existing is not None and not overwrite:
            raise MaterialArchiveConflictError(
                "A material archive already uses this Lumina Box brand and name"
            )

        parent_dir = materials_root
        if cleaned_brand is not None:
            parent_dir = parent_dir / _sanitize_directory_name(cleaned_brand)
        target_dir = (
            existing[0].parent
            if existing is not None
            else parent_dir / _sanitize_directory_name(cleaned_name)
        )
        if existing is None and target_dir.exists():
            raise CoreValidationError(
                "The requested Lumina Box archive directory is already occupied by a different archive"
            )
        parent_dir.mkdir(parents=True, exist_ok=True)
        staged_dir = parent_dir / f".{target_dir.name}.lumina-box-staging-{uuid.uuid4().hex}"
        created_at = (
            str(existing[1].get("created_at") or _now_iso())
            if existing is not None
            else _now_iso()
        )
        updated_at = _now_iso()
        existing_consistency = (
            existing[1].get("archive_consistency")
            if existing is not None and isinstance(existing[1], Mapping)
            else None
        )
        existing_archive_id = (
            existing_consistency.get("archive_id")
            if isinstance(existing_consistency, Mapping)
            else None
        )
        try:
            archive_id = str(uuid.UUID(str(existing_archive_id)))
        except (TypeError, ValueError, AttributeError):
            archive_id = str(uuid.uuid4())
        archive_consistency = _archive_consistency_metadata(
            archive_id=archive_id,
            revision_id=str(uuid.uuid4()),
        )
        archive_payload = {
            "schema_version": LUMINA_BOX_ARCHIVE_SCHEMA_VERSION,
            "kind": "lumina_box_material",
            "material_name": cleaned_name,
            "brand": cleaned_brand,
            "material_type": cleaned_type,
            "notes": cleaned_notes,
            "created_at": created_at,
            "updated_at": updated_at,
            "profile_kind": LUMINA_BOX_PROFILE_KIND,
            "acquisition_source": LUMINA_BOX_ACQUISITION_SOURCE,
            "optical_model": LUMINA_BOX_OPTICAL_MODEL_ID,
            "measurement_protocol_id": LUMINA_BOX_PROTOCOL_ID,
            "objective_id": LUMINA_BOX_OBJECTIVE_ID,
            "color_bridge_id": LUMINA_BOX_COLOR_BRIDGE_ID,
            "measurements_file": LUMINA_BOX_MEASUREMENTS_FILENAME,
            "km_xyz_parameters_file": LUMINA_BOX_PARAMETERS_FILENAME,
            "archive_consistency": archive_consistency,
            "measurement_backing_base_percent_xyz": fit[
                "measurement_backing_base_percent_xyz"
            ],
            "measurement_backing_scale": fit["measurement_backing_scale"],
            "measurement_thickness_offset_mm": fit[
                "measurement_thickness_offset_mm"
            ],
            "measurement_backing_effective_percent_xyz": fit[
                "measurement_backing_effective_percent_xyz"
            ],
            "measurement_reflection_boundary_id": fit[
                "measurement_reflection_boundary_id"
            ],
            "estimated_effective_d65_10_xyz_relative": fit[
                "estimated_effective_d65_10_xyz_relative"
            ],
            "estimated_reflectance_thickness_mm": fit[
                "estimated_reflectance_thickness_mm"
            ],
            "estimated_rgb": fit["estimated_rgb"],
        }
        measurement_record = {
            "schema_version": LUMINA_BOX_ARCHIVE_SCHEMA_VERSION,
            "measurement_protocol_id": LUMINA_BOX_PROTOCOL_ID,
            "objective_id": LUMINA_BOX_OBJECTIVE_ID,
            "optical_model": LUMINA_BOX_OPTICAL_MODEL_ID,
            "color_bridge_id": LUMINA_BOX_COLOR_BRIDGE_ID,
            "archive_consistency": archive_consistency,
            "value_scale": LUMINA_BOX_VALUE_SCALE,
            "measurement_backing_percent_xyz": measurements[
                "measurement_backing_percent_xyz"
            ],
            "measurement_reflection_boundary_id": (
                LUMINA_BOX_MEASUREMENT_REFLECTION_BOUNDARY_ID
            ),
            "samples": measurements["samples"],
        }
        parameters_record = {
            "schema_version": LUMINA_BOX_ARCHIVE_SCHEMA_VERSION,
            "measurement_protocol_id": LUMINA_BOX_PROTOCOL_ID,
            "optical_model": LUMINA_BOX_OPTICAL_MODEL_ID,
            "color_bridge_id": LUMINA_BOX_COLOR_BRIDGE_ID,
            "coefficient_unit": "mm^-1",
            "value_scale": LUMINA_BOX_VALUE_SCALE,
            "residual_unit": LUMINA_BOX_RESIDUAL_UNIT,
            "parameters": {"K": K, "S": S, "unit": "mm^-1"},
            "archive_consistency": archive_consistency,
            "objective_id": fit["diagnostics"]["objective_id"],
            "objective_config": fit["diagnostics"]["objective_config"],
            "sample_predictions": fit["sample_predictions"],
            "residual_summary": fit["residual_summary"],
            "diagnostics": {
                "success": fit["diagnostics"]["success"],
                "message": fit["diagnostics"]["message"],
                "nfev": fit["diagnostics"]["nfev"],
                "start_count": fit["diagnostics"]["start_count"],
                "robust_objective": fit["diagnostics"]["robust_objective"],
                "jacobian_condition": fit["diagnostics"]["jacobian_condition"],
                "measurement_thickness_offset_mm": fit["diagnostics"][
                    "measurement_thickness_offset_mm"
                ],
                "channels": fit["diagnostics"]["channels"],
                "warnings": fit["diagnostics"]["warnings"],
            },
            "measurement_backing_base_percent_xyz": fit[
                "measurement_backing_base_percent_xyz"
            ],
            "measurement_backing_scale": fit["measurement_backing_scale"],
            "measurement_thickness_offset_mm": fit[
                "measurement_thickness_offset_mm"
            ],
            "measurement_backing_effective_percent_xyz": fit[
                "measurement_backing_effective_percent_xyz"
            ],
            "measurement_reflection_boundary_id": fit[
                "measurement_reflection_boundary_id"
            ],
            "fit_quality": fit["fit_quality"],
            "estimated_effective_d65_10_xyz_relative": fit[
                "estimated_effective_d65_10_xyz_relative"
            ],
            "estimated_reflectance_thickness_mm": fit[
                "estimated_reflectance_thickness_mm"
            ],
            "estimated_rgb": fit["estimated_rgb"],
            "warnings": fit["warnings"],
        }
        try:
            staged_dir.mkdir(parents=False, exist_ok=False)
            _write_json(staged_dir / LUMINA_BOX_MEASUREMENTS_FILENAME, measurement_record)
            _write_json(staged_dir / LUMINA_BOX_PARAMETERS_FILENAME, parameters_record)
            archive_payload["sidecar_integrity"] = {
                "algorithm": "sha256",
                "measurements": {
                    "filename": LUMINA_BOX_MEASUREMENTS_FILENAME,
                    "sha256": _sha256_file(
                        staged_dir / LUMINA_BOX_MEASUREMENTS_FILENAME
                    ),
                },
                "parameters": {
                    "filename": LUMINA_BOX_PARAMETERS_FILENAME,
                    "sha256": _sha256_file(
                        staged_dir / LUMINA_BOX_PARAMETERS_FILENAME
                    ),
                },
            }
            _write_json(staged_dir / "material.json", archive_payload)
            _commit_staged_material_directory(
                staged_dir=staged_dir,
                target_dir=target_dir,
                overwrite=bool(overwrite),
            )
        except (MaterialArchiveConflictError, OSError, RuntimeError):
            shutil.rmtree(staged_dir, ignore_errors=True)
            raise

    summary = _archive_summary(materials_root, target_dir, archive_payload)
    _log.info(
        "Lumina Box material archive saved",
        extra={
            "event": "lumina_box_archive_saved",
            "directory_name": summary["directory_name"],
            "overwrite": bool(overwrite),
        },
    )
    return LuminaBoxMaterialArchiveSaveResult(
        archive_path=summary["archive_path"],
        measurements_path=summary["measurements_path"],
        parameters_path=summary["parameters_path"],
        material_summary=summary,
    )
