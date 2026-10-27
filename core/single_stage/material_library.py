"""Local material archive save/edit/delete, import/export, and listing."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from core.backed_gradient_smooth import SPECTRAL_SMOOTH_MODEL_ID
from core.lumina_box_archive import (
    LUMINA_BOX_PROFILE_KIND,
    validate_lumina_box_material_archive,
)
from core.lumina_box_spectral import LUMINA_BOX_SPECTRAL_MODEL_ID

from . import (
    material_files,
    material_package,
    material_registry_client,
    material_runs,
    material_sync,
)


@dataclass(frozen=True)
class MaterialArchiveSaveResult:
    """Persistent material archive save result.
    持久化耗材归档保存结果。

    Attributes:
        archive_path: Saved material archive JSON path. (保存后的耗材归档 JSON 路径)
        stage_a_params_path: Saved Stage A parameter JSON path. (保存后的 Stage A 参数 JSON 路径)
        material_summary: Archive summary for UI/API. (用于 UI/API 的归档摘要)
    """

    archive_path: str
    stage_a_params_path: str
    material_summary: dict[str, Any]


@dataclass(frozen=True)
class MaterialArchiveDeleteResult:
    """Persistent material archive delete result.
    持久化耗材归档删除结果。

    Attributes:
        directory_name: Deleted material directory name. (删除的耗材目录名)
        material_name: Deleted material name. (删除的耗材名称)
        deleted_path: Deleted material directory path. (删除的耗材目录路径)
    """

    directory_name: str
    material_name: str
    deleted_path: str


@dataclass(frozen=True)
class MaterialArchiveUpdateResult:
    """Persistent material archive metadata update result.
    持久化耗材归档元数据更新结果。

    Attributes:
        archive_path: Updated material archive JSON path. (更新后的耗材归档 JSON 路径)
        stage_a_params_path: Updated Stage A parameter JSON path. (更新后的 Stage A 参数 JSON 路径)
        material_summary: Archive summary for UI/API. (用于 UI/API 的归档摘要)
    """

    archive_path: str
    stage_a_params_path: str
    material_summary: dict[str, Any]


@dataclass(frozen=True)
class MaterialArchiveExportResult:
    """Persistent material archive export result.
    持久化耗材归档导出结果。

    Attributes:
        archive_path: Generated ZIP archive path. (生成的 ZIP 归档路径)
        download_filename: Suggested download filename. (建议下载文件名)
        exported_directory_names: Exported saved-material directory names. (导出的耗材目录名)
    """

    archive_path: str
    download_filename: str
    exported_directory_names: list[str]


@dataclass(frozen=True)
class MaterialArchiveImportResult:
    """Persistent material archive import result.
    持久化耗材归档导入结果。

    Attributes:
        imported_materials: Imported material summaries for UI/API. (用于 UI/API 的导入耗材摘要)
    """

    imported_materials: list[dict[str, Any]]


def _filter_integrity_checked_lumina_box_items(
    target_root: Path,
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Keep cached Lumina Box rows only while their sidecars still validate."""
    validated: list[dict[str, Any]] = []
    for item in items:
        if item.get("profile_kind") != "lumina_box":
            validated.append(item)
            continue
        directory_name = item.get("directory_name")
        if not isinstance(directory_name, str) or not directory_name:
            continue
        try:
            material_dir = material_files.resolve_saved_material_dir(target_root, directory_name)
            archive_payload = material_files._load_json_object(
                material_dir / "material.json",
                "Saved Lumina Box material archive is not valid UTF-8 JSON",
            )
        except (OSError, ValueError, FileNotFoundError):
            continue
        if validate_lumina_box_material_archive(material_dir, archive_payload):
            validated.append(item)
    return validated


def _install_lumina_box_bundle_package_atomically(
    *,
    manifest_root: Path,
    staged_material_dir: Path,
    destination_dir: Path,
    package: dict[str, Any],
) -> None:
    """Install a verified Lumina Box package by one directory replacement.
    通过一次目录替换安装已经校验的 Lumina Box 包。
    """
    if destination_dir.exists():
        raise FileExistsError(
            f"Lumina Box import destination already exists: {destination_dir.name}"
        )
    staging_dir = destination_dir.parent / (
        f".{destination_dir.name}.lumina-box-import-staging-{uuid.uuid4().hex}"
    )
    try:
        material_package._copy_material_bundle_package_files(
            manifest_root=manifest_root,
            staged_material_dir=staged_material_dir,
            destination_dir=staging_dir,
            package=package,
        )
        copied_archive_payload = material_files._load_json_object(
            staging_dir / "material.json",
            "Imported Lumina Box material archive is not valid UTF-8 JSON",
        )
        material_package._validate_lumina_box_archive_for_bundle(
            material_dir=staging_dir,
            archive_payload=copied_archive_payload,
            material_label=destination_dir.name,
        )
        if destination_dir.exists():
            raise FileExistsError(
                f"Lumina Box import destination already exists: {destination_dir.name}"
            )
        os.replace(staging_dir, destination_dir)
    except Exception:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise


def _material_summary_from_saved_archive(
    target_root: Path,
    material_dir: Path,
    archive_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    archive_path = material_dir / "material.json"
    payload = archive_payload or material_files._load_json_object(
        archive_path,
        "Saved material archive is not valid UTF-8 JSON",
    )
    if material_package._is_lumina_box_archive_payload(payload):
        return _lumina_box_material_library_item_from_archive(
            target_root,
            material_dir,
            payload,
        )
    relative_directory_name = material_files._relative_directory_name(target_root, material_dir)
    stage_a_params_path = material_files._resolve_stage_a_params_path(material_dir, payload)
    if not stage_a_params_path.exists():
        raise FileNotFoundError(
            f"Saved Stage A parameters not found for material: {relative_directory_name}"
        )
    verification_runs = payload.get("verification_runs")
    try:
        verification_count = int(
            payload.get("verification_count")
            or (len(verification_runs) if isinstance(verification_runs, list) else 1)
            or 1
        )
    except (TypeError, ValueError):
        verification_count = len(verification_runs) if isinstance(verification_runs, list) and verification_runs else 1
    brand_value = material_files._saved_material_brand_from_archive_payload(
        payload,
        relative_directory_name,
    )
    material_name = str(payload.get("material_name") or material_dir.name)
    picker_metadata = material_files._picker_metadata_from_archive(
        payload,
        material_name=material_name,
        relative_directory_name=relative_directory_name,
    )
    aggregation = payload.get("aggregation") if isinstance(payload.get("aggregation"), dict) else None
    aggregation_method: str | None = None
    aggregation_selection: dict[str, Any] | None = None
    if isinstance(aggregation, dict):
        method_value = aggregation.get("method")
        if isinstance(method_value, str):
            aggregation_method = method_value
        selection_value = aggregation.get("selection")
        if isinstance(selection_value, dict):
            aggregation_selection = material_files._json_clone(selection_value)
    usage_payload = material_files._load_usage_payload(material_dir)
    return {
        "material_name": material_name,
        "directory_name": relative_directory_name,
        "profile_kind": _STAGE_A_PROFILE_KIND,
        "notes": payload.get("notes"),
        "brand": brand_value,
        **picker_metadata,
        "archive_path": str(archive_path),
        "stage_a_params_path": str(stage_a_params_path),
        "verification_count": verification_count,
        "created_at": payload.get("created_at"),
        "updated_at": payload.get("updated_at") or payload.get("created_at"),
        # Aggregation diagnostics surfaced to the frontend so the user
        # can see which historical runs participated in the joint refit
        # and which were excluded by the bias filter / cross-val ranking.
        # (聚合诊断信息透传给前端用于"合并诊断"折叠区)
        "aggregation_method": aggregation_method,
        "aggregation_selection": aggregation_selection,
        "usage_total": int(usage_payload.get("total") or 0),
        "usage_by_color_mode": dict(usage_payload.get("by_color_mode") or {}),
        "usage_last_used_at": usage_payload.get("last_used_at"),
        "usage_last_used_color_mode": usage_payload.get("last_used_color_mode"),
    }


_STAGE_A_PROFILE_KIND = "stage_a"
_LUMINA_BOX_PROFILE_KIND = "lumina_box"
_SUPPORTED_MATERIAL_PROFILE_KINDS = frozenset(
    {_STAGE_A_PROFILE_KIND, _LUMINA_BOX_PROFILE_KIND}
)


def _material_profile_kind_from_archive(archive_payload: dict[str, Any]) -> str:
    """Resolve profile kind while treating pre-Lumina-Box archives as Stage A."""
    raw_value = archive_payload.get("profile_kind")
    if not isinstance(raw_value, str) or not raw_value.strip():
        return _STAGE_A_PROFILE_KIND
    normalized = raw_value.strip().lower()
    return normalized if normalized in _SUPPORTED_MATERIAL_PROFILE_KINDS else _STAGE_A_PROFILE_KIND


def _lumina_box_material_library_item_from_archive(
    target_root: Path,
    material_dir: Path,
    archive_payload: dict[str, Any],
) -> dict[str, Any]:
    """Build a generic material-library row for a Lumina Box archive.

    The generic library must be able to show a KM archive without trying to
    resolve the Stage A parameter sidecar that it intentionally does not have.
    """
    from core.lumina_box_archive import (
        LUMINA_BOX_COLOR_BRIDGE_ID,
        validate_lumina_box_material_archive,
    )

    if not validate_lumina_box_material_archive(material_dir, archive_payload):
        raise ValueError("Saved Lumina Box material archive failed integrity validation")
    archive_path = material_dir / "material.json"
    relative_directory_name = material_files._relative_directory_name(target_root, material_dir)
    material_name = str(archive_payload.get("material_name") or material_dir.name)
    picker_metadata = material_files._picker_metadata_from_archive(
        archive_payload,
        material_name=material_name,
        relative_directory_name=relative_directory_name,
    )
    raw_estimated_xyz = archive_payload.get(
        "estimated_effective_d65_10_xyz_relative"
    )
    if not isinstance(raw_estimated_xyz, list):
        raw_estimated_xyz = []
    raw_estimated_rgb = archive_payload.get("estimated_rgb")
    if not isinstance(raw_estimated_rgb, list):
        raw_estimated_rgb = []
    try:
        estimated_xyz = [float(value) for value in raw_estimated_xyz[:3]]
    except (TypeError, ValueError):
        estimated_xyz = []
    try:
        estimated_rgb = [int(value) for value in raw_estimated_rgb[:3]]
    except (TypeError, ValueError):
        estimated_rgb = []
    usage_payload = material_files._load_usage_payload(material_dir)
    return {
        "material_name": material_name,
        "directory_name": relative_directory_name,
        "brand": material_files._saved_material_brand_from_archive_payload(
            archive_payload,
            relative_directory_name,
        ),
        **picker_metadata,
        "created_at": archive_payload.get("created_at"),
        "updated_at": archive_payload.get("updated_at")
        or archive_payload.get("created_at"),
        "archive_path": str(archive_path),
        "stage_a_params_path": None,
        "estimated_rgb": estimated_rgb,
        "estimated_xyz": estimated_xyz,
        "layer_height_mm": None,
        "mean_delta_e": None,
        "verification_count": 1,
        "verification_history": [],
        "usage_total": int(usage_payload.get("total") or 0),
        "usage_by_color_mode": dict(usage_payload.get("by_color_mode") or {}),
        "usage_last_used_at": usage_payload.get("last_used_at"),
        "usage_last_used_color_mode": usage_payload.get("last_used_color_mode"),
        "profile_kind": _LUMINA_BOX_PROFILE_KIND,
        "acquisition_source": str(
            archive_payload.get("acquisition_source") or "lumina_box"
        ),
        "optical_model_id": str(
            archive_payload.get("optical_model") or "km_xyz/v1"
        ),
        "measurement_protocol_id": archive_payload.get("measurement_protocol_id"),
        "capture_dataset_id": archive_payload.get("capture_dataset_id"),
        "material_symbol": archive_payload.get("material_symbol"),
        "reference_id": archive_payload.get("reference_id"),
        "color_bridge_id": LUMINA_BOX_COLOR_BRIDGE_ID,
    }


def _saved_material_library_item_from_archive(
    target_root: Path,
    material_dir: Path,
    archive_payload: dict[str, Any],
) -> dict[str, Any]:
    if _material_profile_kind_from_archive(archive_payload) == _LUMINA_BOX_PROFILE_KIND:
        return _lumina_box_material_library_item_from_archive(
            target_root,
            material_dir,
            archive_payload,
        )
    archive_path = material_dir / "material.json"
    try:
        stage_a_path = material_files._resolve_stage_a_params_path(material_dir, archive_payload)
    except ValueError:
        stage_a_path = material_dir / "stage_A_parameters.json"
    fit_summary = archive_payload.get("fit_summary") or {}
    material_summary = archive_payload.get("material_summary") or {}
    overall_validation = fit_summary.get("overall_validation") or {}
    estimated_rgb = material_summary.get("estimated_rgb")
    if not isinstance(estimated_rgb, list):
        estimated_rgb = []
    try:
        estimated_rgb_values = [int(value) for value in estimated_rgb[:3]]
    except (TypeError, ValueError):
        estimated_rgb_values = []
    verification_runs = material_runs._load_existing_verification_runs(
        material_dir,
        archive_payload,
    )
    verification_history = material_runs._summarize_verification_runs(verification_runs)
    try:
        verification_count = int(
            archive_payload.get("verification_count")
            or len(verification_history)
            or 1
        )
    except (TypeError, ValueError):
        verification_count = len(verification_history) or 1

    relative_directory_name = material_files._relative_directory_name(target_root, material_dir)
    brand_value = material_files._saved_material_brand_from_archive_payload(
        archive_payload,
        relative_directory_name,
    )
    material_name = str(
        archive_payload.get("material_name") or material_dir.name
    )
    picker_metadata = material_files._picker_metadata_from_archive(
        archive_payload,
        material_name=material_name,
        relative_directory_name=relative_directory_name,
    )
    usage_payload = material_files._load_usage_payload(material_dir)
    return {
        "material_name": material_name,
        "directory_name": relative_directory_name,
        "profile_kind": _STAGE_A_PROFILE_KIND,
        "brand": brand_value,
        **picker_metadata,
        "created_at": archive_payload.get("created_at"),
        "updated_at": archive_payload.get("updated_at")
        or archive_payload.get("created_at"),
        "archive_path": str(archive_path),
        "stage_a_params_path": (
            str(stage_a_path) if stage_a_path.exists() else None
        ),
        "estimated_rgb": estimated_rgb_values,
        "layer_height_mm": material_summary.get("layer_height_mm"),
        "mean_delta_e": overall_validation.get("mean_delta_e"),
        "verification_count": verification_count,
        "verification_history": verification_history,
        # Usage statistics (sidecar file, never gates main flow):
        # 使用次数（边车文件，缺失/损坏时回退为 0，不阻塞主流程）
        "usage_total": int(usage_payload.get("total") or 0),
        "usage_by_color_mode": dict(usage_payload.get("by_color_mode") or {}),
        "usage_last_used_at": usage_payload.get("last_used_at"),
        "usage_last_used_color_mode": usage_payload.get("last_used_color_mode"),
    }


def save_stage_a_material_archive(
    *,
    material_name: str,
    params_payload: dict[str, Any],
    fit_summary: dict[str, Any],
    source_summary: dict[str, Any],
    material_summary: dict[str, Any],
    materials_dir: str | None = None,
    existing_directory_name: str | None = None,
    save_mode: str = "merge",
    brand: str | None = None,
) -> MaterialArchiveSaveResult:
    """Persist a Stage A material archive into the project materials directory.
    将 Stage A 耗材档案持久化保存到项目 materials 目录。

    Args:
        material_name: User-provided material name. (用户输入的耗材名称)
        params_payload: Stage A payload to persist. (待保存的 Stage A 数据)
        fit_summary: Stage A fit summary. (Stage A 拟合摘要)
        source_summary: Input-source metadata. (输入来源元数据)
        material_summary: Material extraction summary. (耗材提取摘要)
        materials_dir: Optional override output directory. (可选的输出目录覆盖)
        existing_directory_name: Optional existing material directory to update. (可选的已有耗材目录名)
        save_mode: ``"merge"`` to append to existing verification runs and
            aggregate, or ``"override"`` to replace all previous runs with the
            current result only. (合并已有验证或覆盖)
        brand: Optional brand sub-directory. When provided and creating a new
            material, the archive is stored under
            ``materials/<brand>/<material_name>/``. Ignored when
            ``existing_directory_name`` is provided. (可选的品牌子目录名称)

    Returns:
        MaterialArchiveSaveResult: Saved archive information. (保存结果)
    """
    if save_mode not in ("merge", "override"):
        raise ValueError(f"Invalid save_mode: {save_mode!r}, expected 'merge' or 'override'")
    target_root = Path(materials_dir or material_files.MATERIALS_DIR)
    target_root.mkdir(parents=True, exist_ok=True)
    archive_path: Path
    created_at: str
    final_material_name = material_name
    final_brand: str | None = None
    picker_metadata: dict[str, str] = {}
    verification_runs: list[dict[str, Any]] = []
    if existing_directory_name:
        material_dir = material_files._resolve_material_dir(target_root, existing_directory_name)
        archive_path = material_dir / "material.json"
        if not archive_path.exists():
            raise FileNotFoundError(f"Saved material archive not found: {existing_directory_name}")
        try:
            existing_archive_payload = json.loads(archive_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError("Existing material archive is not valid UTF-8 JSON") from exc
        created_at = str(existing_archive_payload.get("created_at") or material_files._now_iso())
        final_material_name = str(existing_archive_payload.get("material_name") or material_name)
        final_brand = material_files._saved_material_brand_from_archive_payload(
            existing_archive_payload,
            material_files._relative_directory_name(target_root, material_dir),
        )
        for key in material_files._MATERIAL_PICKER_METADATA_KEYS:
            value = material_files._clean_optional_archive_text(
                existing_archive_payload.get(key)
            )
            if value is not None:
                picker_metadata[key] = value
        if save_mode == "merge":
            verification_runs = material_runs._load_existing_verification_runs(material_dir, existing_archive_payload)
    else:
        sanitized_brand = None
        if isinstance(brand, str) and brand.strip():
            sanitized_brand = brand.strip()
        final_brand = sanitized_brand
        material_dir = material_files._unique_material_dir(
            target_root, material_name, brand=sanitized_brand
        )
        material_dir.mkdir(parents=True, exist_ok=True)
        archive_path = material_dir / "material.json"
        created_at = material_files._now_iso()
    if "material_profile_id" not in picker_metadata:
        picker_metadata["material_profile_id"] = f"profile_{uuid.uuid4().hex}"

    new_image_source = material_runs._coerce_image_source(source_summary.get("image_source"))
    if save_mode == "merge" and verification_runs:
        existing_image_sources = material_runs._collect_run_image_sources(verification_runs)
        # Two physically inconsistent sources cannot be safely merged: their
        # (E, k) live in different "white-balanced reference" frames so any
        # combined refit (or even a parameter mean) is meaningless.
        # Reject the merge with an actionable error so the user can either
        # re-shoot the new capture in the same mode or drop into ``override``.
        # 两种来源的样本不可混合聚合：它们的 (E, k) 处于不同的"白平衡参考系"，
        # 任何合并重拟合或参数均值都没有物理意义。明确拒绝并给出 actionable
        # 错误，让用户要么按相同来源重拍，要么改用 override 模式。
        if (
            existing_image_sources
            and new_image_source not in existing_image_sources
            and new_image_source is not None
        ):
            existing_label = ", ".join(sorted(existing_image_sources))
            raise ValueError(
                "Cannot merge gradient-card captures from different image "
                f"sources: existing runs use [{existing_label}] but the new "
                f"capture is tagged '{new_image_source}'. Re-capture the new "
                "card in the same mode, or use save_mode='override' to "
                "discard previous verification runs."
            )
    verification_runs.append(
        material_runs._build_verification_run(
            params_payload=params_payload,
            fit_summary=fit_summary,
            material_summary=material_summary,
            source_summary=source_summary,
        )
    )

    # Compute the cross-material session reference once per save call.
    # We anchor on the freshly appended run's ``captured_at`` and the
    # current ``image_source`` so the median is drawn only from captures
    # that share the same physical lighting/exposure context. The
    # current material directory is excluded from the walk so its own
    # historical reading does not anchor the median against which it
    # would later be compared (i.e. self-anchoring is forbidden).
    # When no qualifying samples exist (first calibration session,
    # mismatched image source, etc.) the helper returns ``None`` and
    # ``_aggregate_stage_a_runs`` falls back to legacy selection.
    # 一次保存只算一次 session 中位数；锚点是新 run 的捕获时间 + image_source。
    # 排除当前材料目录避免自我参照；无匹配样本时返回 None，落回旧逻辑。
    fresh_run_captured_at = (
        verification_runs[-1].get("captured_at")
        if verification_runs and isinstance(verification_runs[-1], dict)
        else None
    )
    session_white_c0_reference = material_runs._compute_session_white_c0_reference(
        target_root,
        image_source=new_image_source,
        captured_at_iso=(
            fresh_run_captured_at
            if isinstance(fresh_run_captured_at, str)
            else None
        ),
        exclude_directory=material_dir,
    )

    payload, aggregated_fit_summary, aggregated_material_summary = material_runs._aggregate_stage_a_runs(
        material_name=final_material_name,
        params_payload=params_payload,
        fit_summary=fit_summary,
        material_summary=material_summary,
        verification_runs=verification_runs,
        session_white_c0_reference=session_white_c0_reference,
    )

    stage_a_params_path = material_dir / "stage_A_parameters.json"
    stage_a_params_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    updated_at = material_files._now_iso()
    archive_aggregation_method = str(
        ((payload.get("meta") or {}).get("aggregation_method"))
        or "mean"
    )
    archive_selection = (payload.get("meta") or {}).get("selection")
    if not isinstance(archive_selection, dict):
        archive_selection = None
    image_source_tags = material_runs._collect_run_image_sources(verification_runs)
    if not image_source_tags:
        image_source_label: str | None = None
    elif len(image_source_tags) == 1:
        image_source_label = next(iter(image_source_tags))
    else:
        # Cannot happen in normal flow because the merge-consistency check
        # rejects mixed sources earlier, but if it ever does (e.g. legacy
        # archive seeded with mixed sources), preserve the truth so audits
        # can flag it instead of silently picking one.
        # 正常流程不会触发；保留真实状态便于审计而非偷偷择一。
        image_source_label = "mixed"
    archive_payload = {
        "schema_version": "1.1",
        "kind": "lumina_stage_a_material",
        "material_name": final_material_name,
        "brand": final_brand,
        **picker_metadata,
        "created_at": created_at,
        "updated_at": updated_at,
        "stage_a_params_file": stage_a_params_path.name,
        "fit_summary": aggregated_fit_summary,
        "material_summary": aggregated_material_summary,
        "source": material_files._json_clone(source_summary),
        "verification_count": len(verification_runs),
        "verification_runs": verification_runs,
        "aggregation": {
            "method": archive_aggregation_method,
            "aggregated_at": updated_at,
            "image_source": image_source_label,
            "selection": archive_selection,
        },
    }
    archive_path.write_text(
        json.dumps(archive_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    result_summary = _material_summary_from_saved_archive(
        target_root,
        material_dir,
        archive_payload,
    )
    material_files._invalidate_material_library_cache(target_root)
    return MaterialArchiveSaveResult(
        archive_path=str(archive_path),
        stage_a_params_path=str(stage_a_params_path),
        material_summary=result_summary,
    )


_ESTIMATED_RGB_UNSET: Any = object()


def _validate_estimated_rgb_override(value: Sequence[int]) -> list[int]:
    """Validate and normalize a user-supplied sRGB override triplet.
    校验并归一化用户提供的 sRGB 覆盖三元组。

    Args:
        value: Iterable of 3 integer channels in [0, 255]. (3 个 [0, 255] 内整数通道)

    Returns:
        Normalized ``[R, G, B]`` list of ints. (归一化后的 ``[R, G, B]`` 整数列表)

    Raises:
        ValueError: If the value is not a 3-length iterable of valid channels.
    """
    if isinstance(value, (str, bytes)) or not hasattr(value, "__iter__"):
        raise ValueError("estimated_rgb must be a 3-element sequence of integers")
    channels = list(value)
    if len(channels) != 3:
        raise ValueError("estimated_rgb must contain exactly 3 channels")
    normalized: list[int] = []
    for channel in channels:
        try:
            channel_int = int(channel)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "estimated_rgb channels must be integers in [0, 255]"
            ) from exc
        if not 0 <= channel_int <= 255:
            raise ValueError(
                "estimated_rgb channels must be integers in [0, 255]"
            )
        normalized.append(channel_int)
    return normalized


def update_saved_stage_a_material_archive_metadata(
    *,
    directory_name: str,
    material_name: str,
    brand: str | None = None,
    estimated_rgb: Sequence[int] | Any = _ESTIMATED_RGB_UNSET,
    materials_dir: str | None = None,
    notes: Any = _ESTIMATED_RGB_UNSET,
    material_type: Any = _ESTIMATED_RGB_UNSET,
) -> MaterialArchiveUpdateResult:
    """Update saved material metadata while retaining its optical parameters.
    更新已保存耗材的元数据，保留光学参数。

    Args:
        directory_name: Saved material directory name. (已保存的耗材目录名)
        material_name: Updated user-facing material name. (更新后的耗材名称)
        brand: Updated optional brand label. (更新后的可选品牌标签)
        estimated_rgb: Optional user-overridden display sRGB ``[R, G, B]``
            triplet. Pass ``_ESTIMATED_RGB_UNSET`` (default) to leave the
            previously stored value unchanged. (可选的用户覆盖显示 sRGB 三元组;
            默认 ``_ESTIMATED_RGB_UNSET`` 时保留原值不变)
        materials_dir: Optional materials root override. (可选的 materials 根目录覆盖)
        notes: Optional notes; omission retains the saved value.（可选备注；省略时保留原值。）
        material_type: Optional filament type; omission retains the saved value.
            （可选耗材类型；省略时保留原值。）

    Returns:
        MaterialArchiveUpdateResult: Updated archive information. (更新结果)
    """
    cleaned_material_name = str(material_name).strip()
    if not cleaned_material_name:
        raise ValueError("material_name is required")
    cleaned_brand = None
    if isinstance(brand, str):
        stripped_brand = brand.strip()
        cleaned_brand = stripped_brand or None

    normalized_estimated_rgb: list[int] | None
    if estimated_rgb is _ESTIMATED_RGB_UNSET:
        normalized_estimated_rgb = None
    else:
        normalized_estimated_rgb = _validate_estimated_rgb_override(estimated_rgb)

    target_root = Path(materials_dir or material_files.MATERIALS_DIR)
    material_dir = material_files._resolve_material_dir(target_root, directory_name)
    archive_path = material_dir / "material.json"
    if not archive_path.exists():
        raise FileNotFoundError(f"Saved material archive not found: {directory_name}")
    archive_payload = material_files._load_json_object(
        archive_path,
        "Existing material archive is not valid UTF-8 JSON",
    )
    if archive_payload.get("optical_model") == SPECTRAL_SMOOTH_MODEL_ID:
        if not validate_lumina_box_material_archive(material_dir, archive_payload):
            raise ValueError("The saved Box material cannot be read")
        if normalized_estimated_rgb is not None:
            raise ValueError("This material's display color is calculated from its measurements")
        archive_payload.update(material_name=cleaned_material_name, brand=cleaned_brand, updated_at=material_files._now_iso())
        for field, value in (("notes", notes), ("material_type", material_type)):
            if value is not _ESTIMATED_RGB_UNSET:
                archive_payload[field] = str(value).strip() or None if value is not None else None
        archive_path.write_text(json.dumps(archive_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        material_files._invalidate_material_library_cache(target_root)
        return MaterialArchiveUpdateResult(
            archive_path=str(archive_path),
            stage_a_params_path=str(material_dir / archive_payload["optical_parameters_file"]),
            material_summary=_lumina_box_material_library_item_from_archive(target_root, material_dir, archive_payload),
        )
    stage_a_params_path = material_files._resolve_stage_a_params_path(material_dir, archive_payload)
    if not stage_a_params_path.exists():
        raise FileNotFoundError(
            f"Saved Stage A parameters not found for material: {directory_name}"
        )
    stage_a_payload = material_files._load_json_object(
        stage_a_params_path,
        "Saved Stage A parameters are not valid UTF-8 JSON",
    )

    updated_at = material_files._now_iso()
    archive_payload["material_name"] = cleaned_material_name
    archive_payload["brand"] = cleaned_brand
    archive_payload["updated_at"] = updated_at
    for field, value in (("notes", notes), ("material_type", material_type)):
        if value is not _ESTIMATED_RGB_UNSET:
            archive_payload[field] = str(value).strip() or None if value is not None else None
    if normalized_estimated_rgb is not None:
        material_summary = archive_payload.get("material_summary")
        if not isinstance(material_summary, dict):
            material_summary = {}
            archive_payload["material_summary"] = material_summary
        material_summary["estimated_rgb"] = normalized_estimated_rgb
    fit_summary = archive_payload.get("fit_summary")
    if isinstance(fit_summary, dict):
        fit_summary["colors"] = [cleaned_material_name]
    archive_path.write_text(
        json.dumps(archive_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    updated_stage_a_payload = material_runs._update_stage_a_payload_material_name(
        stage_a_payload,
        cleaned_material_name,
    )
    stage_a_params_path.write_text(
        json.dumps(updated_stage_a_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    material_files._invalidate_material_library_cache(target_root)
    return MaterialArchiveUpdateResult(
        archive_path=str(archive_path),
        stage_a_params_path=str(stage_a_params_path),
        material_summary=_saved_material_library_item_from_archive(
            target_root,
            material_dir,
            archive_payload,
        ),
    )


def delete_saved_stage_a_material_archive(
    *,
    directory_name: str,
    materials_dir: str | None = None,
) -> MaterialArchiveDeleteResult:
    """Delete a saved Stage A material archive directory.
    删除已保存的 Stage A 耗材档案目录。

    Args:
        directory_name: Saved material directory name. (已保存的耗材目录名)
        materials_dir: Optional override output directory. (可选的输出目录覆盖)

    Returns:
        MaterialArchiveDeleteResult: Deleted archive information. (删除结果)
    """
    target_root = Path(materials_dir or material_files.MATERIALS_DIR)
    material_dir = material_files._resolve_material_dir(target_root, directory_name)
    archive_path = material_dir / "material.json"
    material_name = material_dir.name
    if archive_path.exists():
        try:
            archive_payload = json.loads(archive_path.read_text(encoding="utf-8"))
            material_name = str(archive_payload.get("material_name") or material_name)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            material_name = material_dir.name
    relative_directory_name = material_files._relative_directory_name(target_root, material_dir)
    deleted_path = str(material_dir)
    parent_dir = material_dir.parent
    shutil.rmtree(material_dir)
    material_files._prune_empty_parents(parent_dir, target_root)
    material_files._invalidate_material_library_cache(target_root)
    return MaterialArchiveDeleteResult(
        directory_name=relative_directory_name,
        material_name=material_name,
        deleted_path=deleted_path,
    )


def export_saved_stage_a_material_archives(
    *,
    directory_names: list[str],
    materials_dir: str | None = None,
    output_path: str | None = None,
) -> MaterialArchiveExportResult:
    """Export compatible saved material archives into a ZIP file.
    将兼容的已保存耗材档案导出为 ZIP 文件。

    Args:
        directory_names: Saved material directory names to export. (要导出的耗材目录名)
        materials_dir: Optional materials root override. (可选的 materials 根目录覆盖)
        output_path: Optional ZIP output path override. (可选的 ZIP 输出路径覆盖)

    Returns:
        MaterialArchiveExportResult: Generated ZIP archive metadata. (生成的 ZIP 归档信息)
    """
    normalized_names = material_files._normalize_material_directory_names(directory_names)
    target_root = Path(materials_dir or material_files.MATERIALS_DIR)
    selected_profile_kinds: set[str] = set()
    selected_box_models: set[str] = set()
    for directory_name in normalized_names:
        material_dir = material_files._resolve_material_dir(target_root, directory_name)
        material_archive_path = material_dir / "material.json"
        if not material_archive_path.is_file():
            raise FileNotFoundError(
                f"Saved material archive not found: {directory_name}"
            )
        archive_payload = material_files._load_json_object(
            material_archive_path,
            "Saved material archive is not valid UTF-8 JSON",
        )
        if material_package._is_lumina_box_archive_payload(archive_payload):
            selected_box_models.add(str(archive_payload.get("optical_model")))
        selected_profile_kinds.add(
            (
                _LUMINA_BOX_PROFILE_KIND
                if material_package._is_lumina_box_archive_payload(archive_payload)
                else _STAGE_A_PROFILE_KIND
            )
        )
    if len(selected_profile_kinds) != 1:
        raise ValueError(
            "Stage A and Lumina Box material archives must be exported separately"
        )
    if len(selected_box_models) > 1:
        raise ValueError("Upgrade older Lumina Box profiles before exporting them with the new model")
    bundle_schema_version = (
        material_package._LUMINA_BOX_MATERIAL_PACKAGE_SCHEMA_VERSION
        if _LUMINA_BOX_PROFILE_KIND in selected_profile_kinds
        else material_package._MATERIAL_PACKAGE_SCHEMA_VERSION
    )
    if selected_box_models == {LUMINA_BOX_SPECTRAL_MODEL_ID}:
        bundle_schema_version = material_package._SPECTRAL_BOX_MATERIAL_PACKAGE_SCHEMA_VERSION
    elif selected_box_models == {SPECTRAL_SMOOTH_MODEL_ID}:
        bundle_schema_version = material_package._BACKED_GRADIENT_BOX_PACKAGE_SCHEMA_VERSION
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    download_filename = f"lumina_materials_{len(normalized_names)}_{timestamp}.zip"
    zip_output_path = (
        Path(output_path)
        if isinstance(output_path, str) and output_path.strip()
        else Path(material_files.TEMP_DIR) / f"lumina_material_export_{uuid.uuid4().hex}.zip"
    )
    zip_output_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": "1.0",
        "kind": "lumina_material_export",
        "exported_at": material_files._now_iso(),
        "directory_names": normalized_names,
        "material_count": len(normalized_names),
    }
    bundle_manifest = {
        "schema_version": bundle_schema_version,
        "kind": "lumina_material_bundle",
        "exported_at": manifest["exported_at"],
        "material_count": len(normalized_names),
        "packages": [],
    }
    try:
        with zipfile.ZipFile(
            zip_output_path,
            "w",
            compression=zipfile.ZIP_DEFLATED,
        ) as archive:
            archive.writestr(
                material_package._MATERIAL_EXPORT_MANIFEST_FILENAME,
                json.dumps(manifest, ensure_ascii=False, indent=2),
            )
            for directory_name in normalized_names:
                material_dir = material_files._resolve_material_dir(target_root, directory_name)
                material_archive_path = material_dir / "material.json"
                if not material_archive_path.is_file():
                    raise FileNotFoundError(
                        f"Saved material archive not found: {directory_name}"
                    )
                relative_directory_name = material_files._relative_directory_name(
                    target_root,
                    material_dir,
                )
                package_manifest, files_to_write = (
                    material_package._build_material_bundle_package_manifest(
                        target_root=target_root,
                        material_dir=material_dir,
                    )
                )
                bundle_manifest["packages"].append(package_manifest)
                for file_path, zip_path in files_to_write:
                    archive.write(file_path, zip_path)
            archive.writestr(
                material_package._MATERIAL_BUNDLE_MANIFEST_FILENAME,
                json.dumps(bundle_manifest, ensure_ascii=False, indent=2),
            )
    except Exception:
        try:
            zip_output_path.unlink()
        except OSError:
            pass
        raise

    return MaterialArchiveExportResult(
        archive_path=str(zip_output_path),
        download_filename=download_filename,
        exported_directory_names=normalized_names,
    )


def import_saved_stage_a_material_archives(
    *,
    archive_path: str,
    materials_dir: str | None = None,
    selected_material_id: str | None = None,
    selected_revision_id: str | None = None,
) -> MaterialArchiveImportResult:
    """Import one ZIP file containing one or more supported material archives.
    导入一个包含一个或多个受支持耗材档案的 ZIP 文件。

    Args:
        archive_path: ZIP archive path to import. (要导入的 ZIP 归档路径)
        materials_dir: Optional materials root override. (可选的 materials 根目录覆盖)
        selected_material_id: Optional package material_id to import from a
            bundle. (可选：从 bundle 中只导入指定 material_id)
        selected_revision_id: Optional package revision_id to import from a
            bundle. (可选：从 bundle 中只导入指定 revision_id)

    Returns:
        MaterialArchiveImportResult: Imported material summaries. (导入后的耗材摘要)
    """
    from core.material_lut_synthesis import validate_stage_a_solver_parameters

    selected_material_id = str(selected_material_id or "").strip()
    selected_revision_id = str(selected_revision_id or "").strip()
    if bool(selected_material_id) != bool(selected_revision_id):
        raise ValueError(
            "selected_material_id and selected_revision_id must be provided together"
        )
    target_root = Path(materials_dir or material_files.MATERIALS_DIR)
    target_root.mkdir(parents=True, exist_ok=True)
    extract_root = Path(
        tempfile.mkdtemp(prefix="material_archive_import_", dir=material_files.TEMP_DIR)
    )
    try:
        extracted_root = material_package._safe_extract_material_zip(archive_path, extract_root)
        manifest_root = extracted_root
        if not (
            (manifest_root / material_package._MATERIAL_BUNDLE_MANIFEST_FILENAME).is_file()
            or (manifest_root / material_package._MATERIAL_EXPORT_MANIFEST_FILENAME).is_file()
        ):
            if (
                (extract_root / material_package._MATERIAL_BUNDLE_MANIFEST_FILENAME).is_file()
                or (extract_root / material_package._MATERIAL_EXPORT_MANIFEST_FILENAME).is_file()
            ):
                manifest_root = extract_root
        bundle_manifest = material_package._load_material_bundle_manifest(manifest_root)
        manifest = material_package._load_material_export_manifest(manifest_root)
        bundle_schema_version = (
            str(bundle_manifest["schema_version"])
            if bundle_manifest is not None
            else None
        )
        material_root = (
            extracted_root / "materials"
            if (extracted_root / "materials").is_dir()
            else extracted_root
        )
        package_by_directory: dict[str, dict[str, Any]] = {}
        if bundle_manifest is not None:
            raw_packages = bundle_manifest["packages"]
            normalized_directory_names = []
            selected_package_found = False
            for raw_package in raw_packages:
                if not isinstance(raw_package, dict):
                    raise ValueError("Material bundle manifest contains invalid package")
                raw_material_id = str(raw_package.get("material_id") or "").strip()
                raw_revision_id = str(raw_package.get("revision_id") or "").strip()
                if selected_material_id:
                    if (
                        raw_material_id != selected_material_id
                        or raw_revision_id != selected_revision_id
                    ):
                        continue
                    selected_package_found = True
                material_package._verify_material_bundle_package(
                    extracted_root=manifest_root,
                    package=raw_package,
                    schema_version=str(bundle_schema_version),
                )
                normalized_directory_name = material_files._normalize_relative_directory_name(
                    str(raw_package.get("local_directory") or "")
                )
                normalized_directory_names.append(normalized_directory_name)
                package_by_directory[normalized_directory_name] = raw_package
            if selected_material_id and not selected_package_found:
                raise ValueError(
                    "Selected material bundle package not found: "
                    f"{selected_material_id}/{selected_revision_id}"
                )
            normalized_directory_names = material_files._normalize_material_directory_names(
                normalized_directory_names
            )
            staged_material_dirs = [
                material_root / Path(directory_name)
                for directory_name in normalized_directory_names
            ]
        elif manifest is not None:
            raw_directory_names = manifest.get("directory_names")
            if not isinstance(raw_directory_names, list) or not raw_directory_names:
                raise ValueError(
                    "Material export manifest is missing directory_names"
                )
            normalized_directory_names = material_files._normalize_material_directory_names(
                raw_directory_names
            )
            staged_material_dirs = [
                material_root / Path(directory_name)
                for directory_name in normalized_directory_names
            ]
        else:
            staged_material_dirs = sorted(
                material_files._discover_saved_material_dirs(material_root),
                key=lambda path: path.as_posix(),
            )

        if not staged_material_dirs:
            raise ValueError(
                "Material archive ZIP does not contain any saved material directories"
            )

        imported_materials: list[dict[str, Any]] = []
        created_material_dirs: list[Path] = []
        installed_packages: list[tuple[dict[str, Any], Path]] = []
        try:
            for staged_material_dir in staged_material_dirs:
                relative_directory_name = material_files._relative_directory_name(
                    material_root,
                    staged_material_dir,
                )
                package = package_by_directory.get(relative_directory_name)
                if package is not None and material_sync._installed_material_bundle_revision_path(
                    target_root=target_root,
                    package=package,
                ) is not None:
                    continue
                material_archive_path = staged_material_dir / "material.json"
                if not material_archive_path.is_file():
                    raise FileNotFoundError(
                        f"Saved material archive not found in ZIP: {relative_directory_name}"
                    )
                archive_payload = material_files._load_json_object(
                    material_archive_path,
                    "Saved material archive is not valid UTF-8 JSON",
                )
                is_lumina_box = material_package._is_lumina_box_archive_payload(archive_payload)
                if is_lumina_box:
                    material_package._validate_lumina_box_archive_for_bundle(
                        material_dir=staged_material_dir,
                        archive_payload=archive_payload,
                        material_label=relative_directory_name,
                    )
                else:
                    stage_a_params_path = material_files._resolve_stage_a_params_path(
                        staged_material_dir,
                        archive_payload,
                    )
                    if not stage_a_params_path.is_file():
                        raise FileNotFoundError(
                            "Saved Stage A parameters not found in ZIP: "
                            f"{relative_directory_name}"
                        )
                    stage_a_payload = material_files._load_json_object(
                        stage_a_params_path,
                        "Saved Stage A parameters are not valid UTF-8 JSON",
                    )
                    validate_stage_a_solver_parameters(
                        stage_a_payload,
                        material_label=relative_directory_name,
                    )
                destination_dir = material_files._import_target_material_dir(
                    target_root,
                    relative_directory_name,
                )
                try:
                    if is_lumina_box and package is not None:
                        _install_lumina_box_bundle_package_atomically(
                            manifest_root=manifest_root,
                            staged_material_dir=staged_material_dir,
                            destination_dir=destination_dir,
                            package=package,
                        )
                    elif package is not None:
                        material_package._copy_material_bundle_package_files(
                            manifest_root=manifest_root,
                            staged_material_dir=staged_material_dir,
                            destination_dir=destination_dir,
                            package=package,
                        )
                    else:
                        shutil.copytree(staged_material_dir, destination_dir)
                except Exception:
                    if destination_dir.exists():
                        shutil.rmtree(destination_dir, ignore_errors=True)
                    raise
                created_material_dirs.append(destination_dir)
                if package is not None:
                    installed_packages.append((package, destination_dir))
                imported_materials.append(
                    _material_summary_from_saved_archive(
                        target_root,
                        destination_dir,
                        archive_payload,
                    )
                )
            capture_imports = []
            packages_by_path = {path: package for package, path in installed_packages}
            for item in imported_materials:
                if item.get("optical_model_id") == SPECTRAL_SMOOTH_MODEL_ID:
                    from core.backed_gradient_archive import load_backed_gradient_archive
                    from core.backed_gradient_backing_transfer import restore_material_captures
                    from core.backed_gradient_store import BackedGradientStore

                    path = target_root / item["directory_name"]
                    _, measurements, fit = load_backed_gradient_archive(path)
                    supplement = packages_by_path.get(path, {}).get("backed_gradient_backing_documents", [])
                    capture_imports.append((measurements, fit, supplement))
            if capture_imports:
                restore_material_captures(BackedGradientStore(target_root), capture_imports)
            material_sync._record_material_sync_entries(
                target_root=target_root,
                installed_packages=installed_packages,
            )
            material_files._invalidate_material_library_cache(target_root)
        except Exception:
            for created_dir in reversed(created_material_dirs):
                parent_dir = created_dir.parent
                shutil.rmtree(created_dir, ignore_errors=True)
                material_files._prune_empty_parents(parent_dir, target_root)
            raise

        return MaterialArchiveImportResult(imported_materials=imported_materials)
    finally:
        shutil.rmtree(extract_root, ignore_errors=True)


def list_saved_stage_a_material_archives(
    *,
    materials_dir: str | None = None,
    profile_kind: str | None = _STAGE_A_PROFILE_KIND,
) -> list[dict[str, Any]]:
    """List saved Stage A material archives from the project materials directory.
    列出项目 materials 目录中已保存的 Stage A 耗材档案。

    Args:
        materials_dir: Optional override output directory. (可选的输出目录覆盖)

    Returns:
        list[dict[str, Any]]: Material archive summaries sorted by recency. (按时间倒序的耗材档案摘要)
    """
    normalized_profile_kind: str | None
    if profile_kind is None:
        normalized_profile_kind = None
    else:
        normalized_profile_kind = str(profile_kind).strip().lower()
        if normalized_profile_kind == "all":
            normalized_profile_kind = None
        elif normalized_profile_kind not in _SUPPORTED_MATERIAL_PROFILE_KINDS:
            accepted = ", ".join(
                sorted(_SUPPORTED_MATERIAL_PROFILE_KINDS | {"all"})
            )
            raise ValueError(
                f"Unsupported material profile_kind: {profile_kind!r}; expected {accepted}"
            )
    target_root = Path(materials_dir or material_files.MATERIALS_DIR)
    if not target_root.exists():
        return []
    cached_items = material_files._cached_material_library_items(target_root)
    if cached_items is not None:
        items = material_registry_client._apply_official_registry_metadata(
            _filter_integrity_checked_lumina_box_items(target_root, cached_items)
        )
        return [
            item
            for item in items
            if normalized_profile_kind is None
            or item.get("profile_kind", _STAGE_A_PROFILE_KIND) == normalized_profile_kind
        ]

    items: list[dict[str, Any]] = []
    archive_paths = [
        path for path in target_root.rglob("material.json") if path.is_file()
    ]
    filtered_archive_paths = material_files._filter_nested_material_archive_paths(archive_paths)
    sync_metadata_by_directory = material_sync._material_sync_metadata_by_directory(target_root)

    for archive_path in sorted(
        filtered_archive_paths,
        key=lambda path: path.parent.stat().st_mtime,
        reverse=True,
    ):
        material_dir = archive_path.parent
        try:
            archive_payload = json.loads(archive_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        try:
            item = _saved_material_library_item_from_archive(
                target_root,
                material_dir,
                archive_payload,
            )
        except (OSError, ValueError, FileNotFoundError):
            if _material_profile_kind_from_archive(archive_payload) == _LUMINA_BOX_PROFILE_KIND:
                continue
            raise
        content_hash = material_package._local_material_content_hash(material_dir, archive_payload)
        if content_hash:
            item["content_hash"] = content_hash
        item.update(sync_metadata_by_directory.get(item["directory_name"], {}))
        items.append(item)
    material_registry_client._apply_official_registry_metadata(items)
    material_files._store_material_library_cache(target_root, items)
    return [
        item
        for item in items
        if normalized_profile_kind is None
        or item.get("profile_kind", _STAGE_A_PROFILE_KIND) == normalized_profile_kind
    ]
