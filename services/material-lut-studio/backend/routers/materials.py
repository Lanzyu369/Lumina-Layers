"""MLS — Material-archive management router.
MLS — 耗材档案管理路由。

Owns the session-free material-archive lifecycle: list / update metadata /
delete / bulk export / bulk import. The business logic lives in
``core.single_stage`` (pure, UI-agnostic); this router only does validation,
file-registry URL issuance, and error translation, mirroring the main app's
``api/routers/single_stage.py`` handlers without copy-pasting algorithms.

拥有会话无关的耗材档案生命周期：列出 / 更新元数据 / 删除 / 批量导出 / 批量
导入。业务逻辑位于 ``core.single_stage``（纯逻辑、与 UI 无关）；本路由只做
校验、文件下载 URL 签发和错误翻译，对齐主应用 ``single_stage.py`` 的处理函数
而不复制算法。

Session-coupled save (``save-gradient-card-material``) is intentionally NOT
hosted here — it depends on the main app's SessionStore and stays owned by
the main Lumina API.
会话耦合的保存端点（``save-gradient-card-material``）刻意不在此托管——它依赖
主应用的 SessionStore，仍归主 Lumina API 所有。
"""

from __future__ import annotations

import os
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from .. import bootstrap

bootstrap.ensure_repo_on_path()

from api.file_bridge import upload_to_tempfile  # noqa: E402
from api.file_registry import FileRegistry  # noqa: E402
from api.schemas.single_stage import (  # noqa: E402
    GradientCardMaterialUpdateRequest,
    MaterialLibraryBulkExportRequest,
)
from api.schemas.responses import (  # noqa: E402
    GradientCardMaterialBulkExportResponse,
    GradientCardMaterialBulkImportResponse,
    GradientCardMaterialDeleteResponse,
    GradientCardMaterialLibraryResponse,
    GradientCardMaterialUpdateResponse,
)
from api.structured_logging import get_logger  # noqa: E402
from core.single_stage import (  # noqa: E402
    delete_saved_stage_a_material_archive,
    export_saved_stage_a_material_archives,
    import_saved_stage_a_material_archives,
    list_saved_stage_a_material_archives,
    update_saved_stage_a_material_archive_metadata,
)

from ..dependencies import get_file_registry
from .data import evict_material_cache

router = APIRouter(prefix="/api/mls/materials", tags=["MLS Materials"])
log = get_logger(__name__)

MATERIAL_LIBRARY_FILE_TTL_SECONDS = 600


def _saved_material_directory_name(material_summary: object, fallback: str) -> str:
    """Return the normalized saved-material directory name from a result.
    从结果摘要中返回规范化的已保存耗材目录名。
    """
    if isinstance(material_summary, dict):
        directory_name = material_summary.get("directory_name")
        if isinstance(directory_name, str) and directory_name.strip():
            return directory_name.strip()
    return fallback


def _rollback_imported_materials(directory_names: list[str]) -> None:
    """Best-effort delete of partially-imported materials after a failure.
    导入失败后尽力删除已部分导入的耗材，避免残留半成品档案。

    Args:
        directory_names: Directory names imported before the error. (出错前已导入的目录名)
    """
    for directory_name in directory_names:
        if not directory_name:
            continue
        try:
            delete_saved_stage_a_material_archive(directory_name=directory_name)
        except (FileNotFoundError, ValueError, TypeError, OSError, RuntimeError):
            # Rollback is best-effort; a failed cleanup must not mask the
            # original import error. 回滚尽力而为，清理失败不得掩盖原始错误。
            log.warning(
                "Failed to roll back imported material",
                extra={
                    "event": "mls_material_import_rollback_failed",
                    "directory_name": directory_name,
                    "error_type": "cleanup_error",
                },
            )


@router.get("")
async def list_materials(
    registry: FileRegistry = Depends(get_file_registry),
) -> GradientCardMaterialLibraryResponse:
    """List saved gradient-card material archives. (列出已保存的梯度卡耗材档案)"""
    try:
        materials = list_saved_stage_a_material_archives()
    except (ValueError, TypeError, OSError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    persistent_registry_session = f"material-library:{uuid.uuid4().hex}"
    response_items: list[dict[str, object]] = []
    for item in materials:
        material_file_url = (
            f"/api/files/{registry.register_path(
                persistent_registry_session,
                str(item['archive_path']),
                ttl_seconds=MATERIAL_LIBRARY_FILE_TTL_SECONDS,
            )}"
        )
        stage_a_path = item.get("stage_a_params_path")
        stage_a_params_url = (
            f"/api/files/{registry.register_path(
                persistent_registry_session,
                str(stage_a_path),
                ttl_seconds=MATERIAL_LIBRARY_FILE_TTL_SECONDS,
            )}"
            if isinstance(stage_a_path, str) and stage_a_path
            else None
        )
        response_items.append(
            {
                **item,
                "material_file_url": material_file_url,
                "stage_a_params_url": stage_a_params_url,
            }
        )

    return GradientCardMaterialLibraryResponse(
        status="ok",
        message=f"Loaded {len(response_items)} saved materials",
        materials=response_items,
    )


@router.patch("/{directory_name:path}")
async def update_material(
    directory_name: str,
    payload: GradientCardMaterialUpdateRequest,
    registry: FileRegistry = Depends(get_file_registry),
) -> GradientCardMaterialUpdateResponse:
    """Update saved gradient-card material metadata. (更新已保存耗材元数据)"""
    update_kwargs: dict[str, object] = {
        "directory_name": directory_name,
        "material_name": payload.material_name,
        "brand": payload.brand,
    }
    if payload.estimated_rgb is not None:
        update_kwargs["estimated_rgb"] = payload.estimated_rgb
    try:
        result = update_saved_stage_a_material_archive_metadata(**update_kwargs)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except (ValueError, TypeError, OSError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    persistent_registry_session = f"material-library:{uuid.uuid4().hex}"
    material_file_url = f"/api/files/{registry.register_path(
        persistent_registry_session,
        result.archive_path,
        ttl_seconds=MATERIAL_LIBRARY_FILE_TTL_SECONDS,
    )}"
    stage_a_params_url = f"/api/files/{registry.register_path(
        persistent_registry_session,
        result.stage_a_params_path,
        ttl_seconds=MATERIAL_LIBRARY_FILE_TTL_SECONDS,
    )}"
    material_name = (
        payload.material_name
        if payload.material_name is not None
        else str(
            result.material_summary.get("material_name")
            or result.material_summary.get("name")
            or ""
        )
    )
    metadata_keys_updated = sum(
        1
        for value in (payload.material_name, payload.brand, payload.estimated_rgb)
        if value is not None
    )
    normalized_directory_name = _saved_material_directory_name(
        result.material_summary,
        directory_name,
    )
    evict_material_cache(normalized_directory_name)
    log.info(
        "MLS material metadata updated",
        extra={
            "event": "mls_material_update_done",
            "directory_name": normalized_directory_name,
            "material_name": material_name,
            "metadata_keys_updated": metadata_keys_updated,
        },
    )
    return GradientCardMaterialUpdateResponse(
        status="ok",
        message="Gradient card material updated successfully",
        material={
            **result.material_summary,
            "material_file_url": material_file_url,
            "stage_a_params_url": stage_a_params_url,
        },
    )


@router.post("/export")
async def export_materials(
    payload: MaterialLibraryBulkExportRequest,
    registry: FileRegistry = Depends(get_file_registry),
) -> GradientCardMaterialBulkExportResponse:
    """Export multiple saved materials as one ZIP archive. (批量导出为 ZIP)"""
    try:
        result = export_saved_stage_a_material_archives(
            directory_names=payload.directory_names,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except (ValueError, TypeError, OSError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    persistent_registry_session = f"material-export:{uuid.uuid4().hex}"
    download_id = registry.register_path(
        persistent_registry_session,
        result.archive_path,
        filename=result.download_filename,
        ttl_seconds=MATERIAL_LIBRARY_FILE_TTL_SECONDS,
    )
    log.info(
        "MLS materials exported",
        extra={
            "event": "mls_material_export_done",
            "exported_count": len(result.exported_directory_names),
            "download_id": download_id,
            "download_filename": result.download_filename,
        },
    )
    return GradientCardMaterialBulkExportResponse(
        status="ok",
        message=f"Exported {len(result.exported_directory_names)} saved materials",
        download_url=f"/api/files/{download_id}",
        filename=result.download_filename,
        exported_count=len(result.exported_directory_names),
        exported_directory_names=result.exported_directory_names,
    )


@router.post("/import")
async def import_materials(
    archives: list[UploadFile] = File(...),
) -> GradientCardMaterialBulkImportResponse:
    """Import one or more saved-material ZIP archives. (导入一个或多个耗材 ZIP)"""
    if not archives:
        raise HTTPException(status_code=422, detail="At least one archive must be uploaded")

    uploaded_archive_paths: list[str] = []
    imported_materials: list[dict[str, object]] = []
    imported_directory_names: list[str] = []
    try:
        for archive in archives:
            filename = archive.filename or ""
            if not filename.lower().endswith(".zip"):
                raise HTTPException(
                    status_code=422,
                    detail=f"Uploaded file must be a ZIP archive: {filename or '<unnamed>'}",
                )
            archive_path = await upload_to_tempfile(archive, suffix=".zip")
            uploaded_archive_paths.append(archive_path)
            result = import_saved_stage_a_material_archives(archive_path=archive_path)
            imported_materials.extend(result.imported_materials)
            imported_directory_names.extend(
                str(item.get("directory_name") or "")
                for item in result.imported_materials
                if isinstance(item.get("directory_name"), str)
                and str(item.get("directory_name") or "").strip()
            )
    except HTTPException:
        _rollback_imported_materials(imported_directory_names)
        raise
    except FileNotFoundError as exc:
        _rollback_imported_materials(imported_directory_names)
        raise HTTPException(status_code=404, detail=str(exc))
    except (ValueError, TypeError, OSError, RuntimeError) as exc:
        _rollback_imported_materials(imported_directory_names)
        raise HTTPException(status_code=422, detail=str(exc))
    finally:
        for archive_path in uploaded_archive_paths:
            try:
                os.remove(archive_path)
            except OSError:
                pass

    log.info(
        "MLS materials imported",
        extra={
            "event": "mls_material_import_done",
            "imported_count": len(imported_materials),
            "imported_directory_names_count": len(imported_directory_names),
            "archives_received": len(archives),
        },
    )
    for dn in imported_directory_names:
        evict_material_cache(dn)
    return GradientCardMaterialBulkImportResponse(
        status="ok",
        message=f"Imported {len(imported_materials)} saved materials",
        imported_count=len(imported_materials),
        imported_materials=imported_materials,
    )


@router.delete("/{directory_name:path}")
async def delete_material(
    directory_name: str,
) -> GradientCardMaterialDeleteResponse:
    """Delete a saved gradient-card material archive. (删除已保存的耗材档案)"""
    try:
        result = delete_saved_stage_a_material_archive(directory_name=directory_name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except (ValueError, TypeError, OSError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    evict_material_cache(result.directory_name)
    log.info(
        "MLS material deleted",
        extra={
            "event": "mls_material_delete_done",
            "directory_name": result.directory_name,
            "material_name": result.material_name,
        },
    )
    return GradientCardMaterialDeleteResponse(
        status="ok",
        message="Gradient card material deleted successfully",
        directory_name=result.directory_name,
        material_name=result.material_name,
    )
