"""Portable single-material archives for calibrated black/white gradients.
黑白底梯度标定的可移植单耗材档案。
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import shutil
from typing import Any, Mapping
from uuid import UUID, uuid4

from core import lumina_box_archive as archive
from core.backed_gradient_material import (
    BACKED_GRADIENT_PROTOCOL_ID, BackedGradientComponent,
    BackedGradientReference, BackedGradientMaterialModel,
)
from core.backed_gradient_smooth import SPECTRAL_SMOOTH_MODEL_ID, SPECTRAL_SMOOTH_OBJECTIVE_ID
from core.errors import CoreValidationError, MaterialArchiveConflictError
from core.km_xyz import KM_XYZ_COLOR_BRIDGE_ID, km_relative_xyz_to_srgb_uint8

BACKED_GRADIENT_ARCHIVE_SCHEMA_VERSION = "1.0"
BACKED_GRADIENT_PARAMETERS_FILENAME = "lumina_box_backed_gradient_parameters.json"
BACKED_GRADIENT_MEASUREMENTS_FILENAME = "lumina_box_backed_gradient_measurements.json"
BACKED_GRADIENT_ARCHIVE_FILES = ("material.json", BACKED_GRADIENT_MEASUREMENTS_FILENAME, BACKED_GRADIENT_PARAMETERS_FILENAME)
_GROUP_JOB_FIELDS = frozenset({"group", "group_material_snapshots", "group_fits"})


def _material_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    # Group job inputs live with the job; a portable archive owns one material.
    return archive._json_clone({key: value for key, value in payload.items() if key not in _GROUP_JOB_FIELDS})


def _validated_fit(payload: Mapping[str, Any]) -> dict[str, Any]:
    fit = _material_payload(payload)
    if fit.get("optical_model_id") != SPECTRAL_SMOOTH_MODEL_ID:
        raise CoreValidationError("Unsupported backed-gradient archive model")
    try:
        component = BackedGradientComponent.from_dict(fit["component"])
        reference = BackedGradientReference.from_dict(fit["reference"])
    except KeyError as error:
        raise CoreValidationError("The material archive needs its component and backing calibration") from error
    fit["component"], fit["reference"] = component.to_dict(), reference.to_dict()
    return fit


def load_backed_gradient_archive(material_dir: Path | str, main: Mapping[str, Any] | None = None
                                 ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Load a complete archive without refitting or consulting another material.
    加载完整档案，不重新拟合，也不依赖其他耗材。

    Args:
        material_dir: Archive directory.（档案目录。）
        main: Optional already-read main record.（可选已读取的主记录。）
    Returns:
        Main record, captured measurements, and fitted component/reference.
        （主记录、采集数据和已拟合组件及参考。）
    """
    directory = Path(material_dir)
    main = dict(main) if main is not None else archive._load_archive_payload(directory / "material.json")
    if not isinstance(main, dict):
        raise CoreValidationError("The material archive is not valid UTF-8 JSON")
    try:
        if (main["schema_version"] != BACKED_GRADIENT_ARCHIVE_SCHEMA_VERSION
                or main["optical_model"] != SPECTRAL_SMOOTH_MODEL_ID
                or main["measurement_protocol_id"] != BACKED_GRADIENT_PROTOCOL_ID
                or main["color_bridge_id"] != KM_XYZ_COLOR_BRIDGE_ID
                or main["measurements_file"] != BACKED_GRADIENT_MEASUREMENTS_FILENAME
                or main["optical_parameters_file"] != BACKED_GRADIENT_PARAMETERS_FILENAME):
            raise CoreValidationError("Unsupported backed-gradient material archive")
        sidecars = {}
        for role, filename in (("measurements", BACKED_GRADIENT_MEASUREMENTS_FILENAME),
                               ("parameters", BACKED_GRADIENT_PARAMETERS_FILENAME)):
            path = directory / filename
            integrity = main["sidecar_integrity"][role]
            if (path.is_symlink() or integrity["filename"] != filename
                    or integrity["sha256"] != archive._sha256_file(path)):
                raise CoreValidationError(f"{filename} does not match the saved archive")
            document = archive._load_archive_payload(path)
            if document is None or document.get("archive_consistency") != main["archive_consistency"]:
                raise CoreValidationError(f"{filename} belongs to a different material version")
            sidecars[role] = document
        fit = _validated_fit(sidecars["parameters"]["fit"])
        if main["reference_id"] != fit["reference"]["reference_id"]:
            raise CoreValidationError("The material and backing reference versions do not match")
        return main, sidecars["measurements"]["measurements"], fit
    except (KeyError, TypeError, ValueError, OSError) as error:
        raise CoreValidationError(f"Invalid backed-gradient material archive: {error}") from error


def save_backed_gradient_material_archive(
    *, material_name: str, measurement_payload: Mapping[str, Any], fit_payload: Mapping[str, Any],
    brand: str | None = None, material_type: str | None = None, notes: str | None = None,
    overwrite: bool = False, materials_dir: str | None = None,
) -> archive.LuminaBoxMaterialArchiveSaveResult:
    """Save an independent material with its raw readings and embedded calibration.
    保存独立耗材、原始读数和内嵌背板标定。

    Args:
        material_name: Material display name.（耗材显示名称。）
        measurement_payload: Full selected readings and retained capture history.（选用读数与完整采集历史。）
        fit_payload: Server-owned component fit.（服务器持有的耗材拟合。）
        brand: Optional brand.（可选品牌。）
        material_type: Optional filament type.（可选耗材种类。）
        notes: Optional user notes.（可选用户备注。）
        overwrite: Update an existing same-name material.（更新同名耗材。）
        materials_dir: Optional material library location.（可选耗材库位置。）
    Returns:
        Saved paths and material-library item.（保存位置与耗材库条目。）
    """
    name = archive._clean_required_text(material_name, field_name="material_name")
    brand, material_type, notes = (archive._clean_optional_text(value) for value in (brand, material_type, notes))
    measurements = _material_payload(measurement_payload)
    fit = _validated_fit(fit_payload)
    for key in ("dataset_id", "dataset_revision", "input_hash"):
        if key in fit and key in measurements and fit[key] != measurements[key]:
            raise CoreValidationError("The fit belongs to a different set of material readings")
    component = BackedGradientComponent.from_dict(fit["component"])
    reference = BackedGradientReference.from_dict(fit["reference"])
    estimate = BackedGradientMaterialModel(reference).predict_backed(component, "W", 3.) / 100.
    fit["estimated_xyz"] = estimate.tolist()
    fit["estimated_rgb"] = km_relative_xyz_to_srgb_uint8(estimate).tolist()
    root = Path(materials_dir or archive.MATERIALS_DIR).resolve()
    with archive._ARCHIVE_WRITE_LOCK:
        root.mkdir(parents=True, exist_ok=True)
        existing = archive._find_same_identity_archive(root, material_name=name, brand=brand, material_type=material_type)
        if existing is not None and not overwrite:
            raise MaterialArchiveConflictError("A material with this brand and name is already saved")
        parent = root / archive._sanitize_directory_name(brand) if brand else root
        target = existing[0].parent if existing is not None else parent / archive._sanitize_directory_name(name)
        if not target.resolve().is_relative_to(root) or target.resolve() == root:
            raise CoreValidationError("The material must remain inside the material library")
        if target.exists() and existing is None:
            raise MaterialArchiveConflictError("This material directory is already occupied")
        old = existing[1] if existing is not None else {}
        consistency = {
            "schema_version": "1.0", "archive_id": old.get("archive_consistency", {}).get("archive_id", str(uuid4())),
            "revision_id": str(uuid4()), "profile_kind": "lumina_box", "acquisition_source": "lumina_box_backed_gradient",
            "optical_model_id": SPECTRAL_SMOOTH_MODEL_ID, "measurement_protocol_id": BACKED_GRADIENT_PROTOCOL_ID,
            "objective_id": SPECTRAL_SMOOTH_OBJECTIVE_ID, "color_bridge_id": KM_XYZ_COLOR_BRIDGE_ID,
            "reference_id": reference.reference_id,
        }
        common = {"schema_version": BACKED_GRADIENT_ARCHIVE_SCHEMA_VERSION,
                  "optical_model": SPECTRAL_SMOOTH_MODEL_ID, "measurement_protocol_id": BACKED_GRADIENT_PROTOCOL_ID,
                  "objective_id": SPECTRAL_SMOOTH_OBJECTIVE_ID, "color_bridge_id": KM_XYZ_COLOR_BRIDGE_ID,
                  "archive_consistency": consistency}
        parent = target.parent
        parent.mkdir(parents=True, exist_ok=True)
        staged = parent / f".{target.name}.backed-gradient-staging-{uuid4().hex}"
        try:
            if target.exists():
                shutil.copytree(target, staged, symlinks=True)
            else:
                staged.mkdir()
            for filename in BACKED_GRADIENT_ARCHIVE_FILES:
                if (staged / filename).is_symlink():
                    raise CoreValidationError("Material archive files cannot be symbolic links")
            # Preserve earlier fitted revisions together with their original inputs.
            if old:
                try:
                    previous_id = str(UUID(old["archive_consistency"]["revision_id"]))
                except (KeyError, TypeError, ValueError):
                    previous_id = str(uuid4())
                previous = staged / ".history" / previous_id
                previous.mkdir(parents=True, exist_ok=True)
                for filename in ("material.json", old.get("measurements_file"), old.get("optical_parameters_file"), old.get("km_xyz_parameters_file")):
                    if filename and Path(filename).name == filename and (staged / filename).is_file():
                        destination = "version.json" if filename == "material.json" else filename
                        shutil.copy2(staged / filename, previous / destination)
            archive._write_json(staged / BACKED_GRADIENT_MEASUREMENTS_FILENAME, {**common, "measurements": measurements})
            archive._write_json(staged / BACKED_GRADIENT_PARAMETERS_FILENAME, {**common, "fit": fit})
            integrity = {"algorithm": "sha256"}
            for role, filename in (("measurements", BACKED_GRADIENT_MEASUREMENTS_FILENAME), ("parameters", BACKED_GRADIENT_PARAMETERS_FILENAME)):
                integrity[role] = {"filename": filename, "sha256": archive._sha256_file(staged / filename)}
            now = archive._now_iso()
            main = {
                **common, "kind": "lumina_box_material", "profile_kind": "lumina_box",
                "acquisition_source": "lumina_box_backed_gradient", "material_name": name, "brand": brand,
                "material_type": material_type, "notes": notes, "created_at": old.get("created_at", now), "updated_at": now,
                "measurements_file": BACKED_GRADIENT_MEASUREMENTS_FILENAME, "optical_parameters_file": BACKED_GRADIENT_PARAMETERS_FILENAME,
                "reference_id": reference.reference_id, "capture_dataset_id": fit.get("dataset_id"),
                "material_symbol": fit.get("material_symbol"), "material_kind": component.kind,
                "backing_material_id": measurements.get("backing_material_id"),
                "estimated_rgb": fit["estimated_rgb"], "estimated_effective_d65_10_xyz_relative": estimate.tolist(),
                "rmse_pp": fit.get("rmse_pp"), "status": fit.get("status", "complete"),
                "sidecar_integrity": integrity,
            }
            archive._write_json(staged / "material.json", main)
            load_backed_gradient_archive(staged, main)
            archive._commit_staged_material_directory(staged_dir=staged, target_dir=target, overwrite=overwrite)
        finally:
            if staged.exists():
                shutil.rmtree(staged)
        summary = {**deepcopy(main), "directory_name": archive._relative_directory_name(root, target),
                   "optical_model_id": SPECTRAL_SMOOTH_MODEL_ID}
        return archive.LuminaBoxMaterialArchiveSaveResult(
            str(target / "material.json"), str(target / BACKED_GRADIENT_MEASUREMENTS_FILENAME),
            str(target / BACKED_GRADIENT_PARAMETERS_FILENAME), summary,
        )
