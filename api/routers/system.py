"""Lumina Studio API — System Management Router.
Lumina Studio API — 系统管理路由。

Provides cache cleanup utilities and the ``POST /api/system/clear-cache``
endpoint (endpoint registered in a later task).
提供缓存清理工具函数，以及 ``POST /api/system/clear-cache`` 端点
（端点在后续任务中注册）。
"""

import json
import os
import re
import uuid
from contextlib import suppress
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from PIL import Image

import config
from api.dependencies import get_file_registry, get_session_store
from api.file_bridge import ensure_png_tempfile
from api.file_registry import FileRegistry
from api.preview_resources import (
    register_preview_for_artifact,
    register_preview_resource_upload,
    validate_preview_context,
)
from api.schemas.system import (
    CacheCleanupDetails,
    ClearCacheResponse,
    ClearCacheResult,
    DeviceProfileInfo,
    PrinterInfo,
    PrinterListResponse,
    SaveSettingsResponse,
    SlicerInfo,
    SlicerListResponse,
    StatsResponse,
    UserSettings,
    UserSettingsResponse,
)
from api.session_store import SessionStore
from api.structured_logging import get_logger

router = APIRouter(prefix="/api/system", tags=["System"])
log = get_logger(__name__)

CLEANABLE_EXTENSIONS: set[str] = {".3mf", ".glb", ".png", ".jpg", ".txt"}
PROTECTED_FILES: set[str] = {"lumina_stats.txt", "lumina_lut.json"}
EPHEMERAL_PREVIEW_TTL_SECONDS = 600
MACHINE_REGISTRY_ASSET_MEDIA_TYPES: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
}


def _try_load_machine_registry():
    """Load optional generated machine registry, returning None on absence/failure.
    加载可选的生成机器注册表；不存在或读取失败时返回 None。
    """
    registry_root = Path(os.environ.get("LUMINA_MACHINE_REGISTRY_DIR", "machine_registry"))
    registry_path = registry_root / "registry.json"
    if not registry_path.exists():
        return None
    try:
        from core.machine_registry import load_machine_registry

        return load_machine_registry(registry_path)
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        log.warning(
            "Machine registry could not be loaded; using legacy printer profiles",
            extra={
                "event": "system_machine_registry_load_failed",
                "path": str(registry_path),
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
        )
        return None


def _slug_machine_id(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")


def _unique_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        unique.append(value)
    return unique


def _registry_printer_id(
    *,
    display_name: str,
    brand: str,
    existing_ids: set[str],
) -> str:
    base = _slug_machine_id(display_name) or _slug_machine_id(f"{brand}-{display_name}")
    candidate = base or "registry-printer"
    if candidate not in existing_ids:
        return candidate
    branded = _slug_machine_id(f"{brand}-{display_name}")
    if branded and branded not in existing_ids:
        return branded
    suffix = 2
    while f"{candidate}-{suffix}" in existing_ids:
        suffix += 1
    return f"{candidate}-{suffix}"


def _registry_machines_by_key() -> dict[tuple[str, str], dict[str, object]]:
    registry = _try_load_machine_registry()
    if registry is None:
        return {}

    machines_by_key: dict[tuple[str, str], dict[str, object]] = {}
    for device in sorted(
        registry.devices_by_id.values(),
        key=lambda item: (item.display_name, item.brand, item.slicer_id, item.nozzle_size),
    ):
        key = (device.display_name.casefold(), device.brand.casefold())
        machine = machines_by_key.setdefault(
            key,
            {
                "display_name": device.display_name,
                "brand": device.brand,
                "bed_width": device.bed_width,
                "bed_depth": device.bed_depth,
                "bed_height": device.bed_height,
                "thumbnail": device.thumbnail,
                "profiles": [],
            },
        )
        if device.thumbnail and not machine["thumbnail"]:
            machine["thumbnail"] = device.thumbnail
        profiles = machine["profiles"]
        assert isinstance(profiles, list)
        profiles.append(
            DeviceProfileInfo(
                device_profile_id=device.device_profile_id,
                slicer_id=device.slicer_id,
                nozzle_size=device.nozzle_size,
                source_profile_name=device.source_profile_name,
                revision=device.revision,
                supported=device.supported,
            )
        )
    return machines_by_key


def _machine_registry_root() -> Path:
    return Path(os.environ.get("LUMINA_MACHINE_REGISTRY_DIR", "machine_registry")).resolve()


def _purge_subdir(subdir: str) -> tuple[int, int]:
    """Delete all files in *subdir*, return ``(count, bytes)``."""
    count = 0
    freed = 0
    if not os.path.isdir(subdir):
        return count, freed
    for entry in os.scandir(subdir):
        if not entry.is_file():
            continue
        try:
            size = entry.stat().st_size
            os.remove(entry.path)
            count += 1
            freed += size
        except OSError:
            pass
    return count, freed


def cleanup_output_dir(output_dir: str) -> tuple[int, int]:
    """Scan *output_dir* and its ``temp/`` / ``models/`` subdirectories,
    deleting transient files.

    扫描 *output_dir* 及其 ``temp/``、``models/`` 子目录，删除临时文件。

    - ``temp/`` and ``models/`` sub-directories: **all** files are deleted.
    - Main *output_dir*: only files whose extension is in
      :data:`CLEANABLE_EXTENSIONS` are deleted, **except** files listed in
      :data:`PROTECTED_FILES`.

    Returns:
        ``(deleted_count, freed_bytes)``。
        If *output_dir* does not exist, returns ``(0, 0)`` without raising.
    """
    if not os.path.isdir(output_dir):
        return 0, 0

    deleted_count = 0
    freed_bytes = 0

    for sub in ("temp", "models"):
        c, b = _purge_subdir(os.path.join(output_dir, sub))
        deleted_count += c
        freed_bytes += b

    for entry in os.scandir(output_dir):
        if not entry.is_file():
            continue
        if entry.name in PROTECTED_FILES:
            continue
        _, ext = os.path.splitext(entry.name)
        if ext.lower() not in CLEANABLE_EXTENSIONS:
            continue
        try:
            size = entry.stat().st_size
            os.remove(entry.path)
            deleted_count += 1
            freed_bytes += size
        except OSError:
            pass

    return deleted_count, freed_bytes


def perform_cache_cleanup(
    file_registry: FileRegistry,
    session_store: SessionStore,
    output_dir: str,
) -> ClearCacheResult:
    """Coordinate a full cache cleanup across all subsystems.

    执行缓存清理，依次清理 FileRegistry、SessionStore 和 OUTPUT_DIR，
    返回汇总统计结果。

    Steps:
        1. ``FileRegistry.clear_all()`` — clear registry & delete files
        2. ``SessionStore.clear_all()`` — clear sessions & temp files
        3. ``cleanup_output_dir()`` — delete matching files in OUTPUT_DIR
    """
    registry_cleaned: int = file_registry.clear_all()
    sessions_cleaned: int = session_store.clear_all()
    output_files_cleaned, freed_bytes = cleanup_output_dir(output_dir)

    return ClearCacheResult(
        registry_cleaned=registry_cleaned,
        sessions_cleaned=sessions_cleaned,
        output_files_cleaned=output_files_cleaned,
        total_freed_bytes=freed_bytes,
    )


@router.post("/image-preview")
async def image_preview(
    file: UploadFile,
    file_registry: FileRegistry = Depends(get_file_registry),
) -> dict:
    """Convert any image (including RAW/HEIC) to PNG and return a preview URL.
    将任意图片（包括 RAW/HEIC）转为 PNG 并返回预览 URL。

    Args:
        file: 上传的图片文件
        file_registry: 文件注册表依赖

    Returns:
        dict: {preview_url, width, height}
    """
    original_filename = file.filename or "unknown"
    png_path = await ensure_png_tempfile(file)
    try:
        with Image.open(png_path) as img:
            width, height = img.size
    except (OSError, ValueError) as exc:
        with suppress(OSError):
            if os.path.exists(png_path):
                os.unlink(png_path)
        raise HTTPException(
            status_code=422,
            detail="无法读取图片尺寸：无效或损坏的图片文件",
        ) from exc
    file_id = file_registry.register_path(
        str(uuid.uuid4()),
        png_path,
        "preview.png",
        ttl_seconds=EPHEMERAL_PREVIEW_TTL_SECONDS,
    )
    file_size_bytes = os.path.getsize(png_path)
    log.info(
        "Image preview generated",
        extra={
            "event": "system_image_preview_done",
            "original_filename": original_filename,
            "file_id": file_id,
            "image_width": int(width),
            "image_height": int(height),
            "file_size_bytes": int(file_size_bytes),
        },
    )
    return {"preview_url": f"/api/files/{file_id}", "width": width, "height": height}


@router.post("/preview-resources")
async def preview_resources(
    file: UploadFile = File(...),
    context: str = Form(...),
    file_registry: FileRegistry = Depends(get_file_registry),
) -> dict:
    """Register a private image resource and return a bounded public preview.
    注册私有图像资源，并只返回受尺寸限制的小预览。
    """
    context_value = validate_preview_context(context)
    result = await register_preview_resource_upload(
        file_registry,
        file,
        context=context_value,
    )
    log.info(
        "Preview resource registered",
        extra={
            "event": "system_preview_resource_done",
            "context": context_value,
            "full_width": result.full_width,
            "full_height": result.full_height,
            "preview_width": result.preview_width,
            "preview_height": result.preview_height,
            "source_type": result.source_type,
        },
    )
    return {
        "resource_id": result.resource_id,
        "preview_id": result.preview_id,
        "preview_url": result.preview_url,
        "full_width": result.full_width,
        "full_height": result.full_height,
        "preview_width": result.preview_width,
        "preview_height": result.preview_height,
        "source_type": result.source_type,
    }


@router.post("/preview-artifacts")
async def preview_artifacts(
    resource_id: str = Form(...),
    context: str = Form(...),
    file_registry: FileRegistry = Depends(get_file_registry),
) -> dict:
    """Return a bounded public preview for an existing private artifact.
    基于已有私有资源返回受尺寸限制的小预览。
    """
    context_value = validate_preview_context(context)
    result = register_preview_for_artifact(
        file_registry,
        context=context_value,
        resource_id=resource_id,
    )
    log.info(
        "Preview artifact registered",
        extra={
            "event": "system_preview_artifact_done",
            "context": context_value,
            "preview_width": result.preview_width,
            "preview_height": result.preview_height,
        },
    )
    return {
        "preview_id": result.preview_id,
        "preview_url": result.preview_url,
        "preview_width": result.preview_width,
        "preview_height": result.preview_height,
    }


@router.post("/clear-cache")
def clear_cache(
    file_registry: FileRegistry = Depends(get_file_registry),
    session_store: SessionStore = Depends(get_session_store),
) -> ClearCacheResponse:
    """Clear all cached/temporary files across subsystems.

    清除所有子系统中的缓存和临时文件，返回清理统计信息。
    """
    result: ClearCacheResult = perform_cache_cleanup(file_registry, session_store, config.OUTPUT_DIR)
    total_deleted: int = result.registry_cleaned + result.sessions_cleaned + result.output_files_cleaned
    return ClearCacheResponse(
        status="success",
        message=f"Cache cleared: {total_deleted} files deleted",
        deleted_files=total_deleted,
        freed_bytes=result.total_freed_bytes,
        details=CacheCleanupDetails(
            registry_cleaned=result.registry_cleaned,
            sessions_cleaned=result.sessions_cleaned,
            output_files_cleaned=result.output_files_cleaned,
        ),
    )


# ---------------------------------------------------------------------------
# Printers endpoint
# ---------------------------------------------------------------------------


@router.get("/printers")
def get_printers() -> PrinterListResponse:
    """Return all supported printer models.
    返回所有支持的打印机型号列表。

    Returns:
        PrinterListResponse: List of printer metadata. (打印机元数据列表)
    """
    profiles = config.list_printer_profiles()
    registry_machines = _registry_machines_by_key()
    printers = []
    existing_ids = {profile.id for profile in profiles}
    attached_registry_keys: set[tuple[str, str]] = set()
    for p in profiles:
        # Build supported slicer list: default template → BambuStudio, plus slicer_templates keys
        slicers = []
        # If template_file starts with "bambu_", default slicer is BambuStudio
        if p.template_file.startswith("bambu_"):
            slicers.append("BambuStudio")
        slicers.extend(p.slicer_templates.keys())
        key = (p.display_name.casefold(), p.brand.casefold())
        registry_machine = registry_machines.get(key, {})
        registry_device_profiles = registry_machine.get("profiles", [])
        assert isinstance(registry_device_profiles, list)
        registry_slicers = [
            profile.slicer_id
            for profile in registry_device_profiles
            if isinstance(profile, DeviceProfileInfo)
        ]
        registry_nozzles = [
            profile.nozzle_size
            for profile in registry_device_profiles
            if isinstance(profile, DeviceProfileInfo)
        ]
        unique_slicers = _unique_preserve_order([*slicers, *registry_slicers])
        unique_nozzles = _unique_preserve_order([*p.supported_nozzle_sizes, *registry_nozzles])
        attached_registry_keys.add(key)
        printers.append(
            PrinterInfo(
                id=p.id,
                display_name=p.display_name,
                brand=p.brand,
                bed_width=p.bed_width,
                bed_depth=p.bed_depth,
                bed_height=p.bed_height,
                supported_nozzle_sizes=unique_nozzles,
                supported_slicers=unique_slicers,
                thumbnail=str(registry_machine.get("thumbnail") or p.thumbnail),
                device_profiles=registry_device_profiles,
            )
        )
    for key, registry_machine in registry_machines.items():
        if key in attached_registry_keys:
            continue
        profiles_for_machine = registry_machine.get("profiles", [])
        assert isinstance(profiles_for_machine, list)
        device_profiles = [
            profile
            for profile in profiles_for_machine
            if isinstance(profile, DeviceProfileInfo)
        ]
        display_name = str(registry_machine["display_name"])
        brand = str(registry_machine["brand"])
        printer_id = _registry_printer_id(
            display_name=display_name,
            brand=brand,
            existing_ids=existing_ids,
        )
        existing_ids.add(printer_id)
        printers.append(
            PrinterInfo(
                id=printer_id,
                display_name=display_name,
                brand=brand,
                bed_width=int(registry_machine["bed_width"]),
                bed_depth=int(registry_machine["bed_depth"]),
                bed_height=int(registry_machine["bed_height"]),
                supported_nozzle_sizes=_unique_preserve_order(
                    [profile.nozzle_size for profile in device_profiles]
                ),
                supported_slicers=_unique_preserve_order(
                    [profile.slicer_id for profile in device_profiles]
                ),
                thumbnail=str(registry_machine.get("thumbnail") or ""),
                device_profiles=device_profiles,
            )
        )
    return PrinterListResponse(status="success", printers=printers)


@router.get("/machine-registry/assets/{asset_path:path}")
def get_machine_registry_asset(asset_path: str) -> FileResponse:
    """Serve a generated machine-registry image asset.
    返回生成机器注册表中的图片资产。
    """
    registry_root = _machine_registry_root()
    requested = (registry_root / asset_path).resolve()
    try:
        inside_registry = os.path.commonpath([str(registry_root), str(requested)]) == str(registry_root)
    except ValueError:
        inside_registry = False
    if not inside_registry:
        raise HTTPException(status_code=400, detail="Invalid machine registry asset path")

    media_type = MACHINE_REGISTRY_ASSET_MEDIA_TYPES.get(requested.suffix.lower())
    if media_type is None:
        raise HTTPException(status_code=404, detail="Machine registry asset not found")
    if not requested.exists() or not requested.is_file():
        raise HTTPException(status_code=404, detail="Machine registry asset not found")
    return FileResponse(path=requested, media_type=media_type)


# ---------------------------------------------------------------------------
# Slicers endpoint
# ---------------------------------------------------------------------------


@router.get("/slicers")
def get_slicers() -> SlicerListResponse:
    """Return all supported slicer software options.
    返回所有支持的切片器软件列表。

    Returns:
        SlicerListResponse: List of slicer metadata. (切片器元数据列表)
    """
    slicers = [SlicerInfo(id=s["id"], display_name=s["display_name"]) for s in config.SUPPORTED_SLICERS]
    return SlicerListResponse(status="success", slicers=slicers)


# ---------------------------------------------------------------------------
# Settings & Stats endpoints
# ---------------------------------------------------------------------------

SETTINGS_FILE: Path = Path("user_settings.json")


@router.get("/settings")
def get_settings() -> UserSettingsResponse:
    """Read persisted user settings with safe fallback.

    读取 user_settings.json 并返回 UserSettings；文件缺失、损坏或顶层结构
    非对象时返回默认值。

    Returns:
        UserSettingsResponse: Current settings or defaults.
            当前设置；无法安全读取时返回默认设置。
    """
    if not SETTINGS_FILE.exists():
        return UserSettingsResponse(status="success", settings=UserSettings())
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return UserSettingsResponse(status="success", settings=UserSettings())
        return UserSettingsResponse(status="success", settings=UserSettings(**data))
    except (json.JSONDecodeError, ValueError):
        return UserSettingsResponse(status="success", settings=UserSettings())


@router.post("/settings")
def save_settings(settings: UserSettings) -> SaveSettingsResponse:
    """将 UserSettings 写入 user_settings.json。"""
    try:
        settings_payload = settings.model_dump()
        serialized = json.dumps(settings_payload, indent=2, ensure_ascii=False)
        SETTINGS_FILE.write_text(serialized, encoding="utf-8")
        log.info(
            "User settings saved",
            extra={
                "event": "system_save_settings_done",
                "settings_field_count": len(settings_payload),
                "bytes_written": len(serialized.encode("utf-8")),
                "settings_path": str(SETTINGS_FILE),
            },
        )
        return SaveSettingsResponse(status="success", message="Settings saved")
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Failed to save settings: {e}")


@router.get("/stats")
def get_stats() -> StatsResponse:
    """获取使用统计数据。"""
    from utils.stats import Stats

    data: dict = Stats.get_all()
    return StatsResponse(
        calibrations=data.get("calibrations", 0),
        extractions=data.get("extractions", 0),
        conversions=data.get("conversions", 0),
    )
