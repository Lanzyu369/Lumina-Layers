"""Read-only material Registry catalog helpers.
只读耗材 Registry catalog 辅助函数。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
import time
import zipfile
from pathlib import Path, PureWindowsPath
from typing import Any, Iterator, Sequence
from urllib.parse import quote

from core.single_stage.materials import validate_material_bundle_archive

_MATERIAL_BUNDLE_MANIFEST_FILENAME = "lumina_material_bundle.json"
_MATERIAL_REGISTRY_CATALOG_SCHEMA_VERSION = "1.0"
_MATERIAL_REGISTRY_PACKAGE_URL_PREFIX = "/api/material-registry/v1/packages"
_MATERIAL_REGISTRY_TMP_DIRNAME = "_tmp"
_MATERIAL_REGISTRY_CATALOG_CACHE_TTL_S = 5 * 60
_MATERIAL_REGISTRY_CATALOG_CACHE_LOCK = threading.RLock()
_MATERIAL_REGISTRY_CATALOG_CACHE: dict[tuple[str, tuple[str, ...]], dict[str, Any]] = {}
_MATERIAL_REGISTRY_PUBLIC_CHANNELS = frozenset({"official", "community"})


class MaterialRegistryDuplicateError(ValueError):
    """Raised when a Registry package duplicates an existing material revision.
    Registry 包与现有耗材 revision 重复时抛出。
    """


def _json_clone(payload: Any) -> Any:
    return json.loads(json.dumps(payload, ensure_ascii=False))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _registry_packages_root(
    packages_dir: str | None = None,
    *,
    create: bool = False,
) -> Path:
    raw_dir = str(
        packages_dir
        if packages_dir is not None
        else os.environ.get("LUMINA_MATERIAL_REGISTRY_PACKAGES_DIR", "")
    ).strip()
    if not raw_dir:
        raise ValueError("Material registry packages directory is not configured")
    root = Path(raw_dir)
    if create:
        root.mkdir(parents=True, exist_ok=True)
    if not root.is_dir():
        raise ValueError(f"Material registry packages directory does not exist: {raw_dir}")
    return root.resolve()


def normalize_material_registry_channels(channels: Sequence[str] | None = None) -> list[str]:
    """Normalize requested Registry channels.
    规范化请求的 Registry 频道。
    """
    if channels is None:
        candidates = ["official"]
    else:
        candidates = [str(channel) for channel in channels]
    normalized: list[str] = []
    for raw_channel in candidates:
        channel = str(raw_channel).strip()
        if not channel:
            continue
        if not re.fullmatch(r"[a-z0-9_-]+", channel):
            raise ValueError(f"Material registry channel is invalid: {channel}")
        if channel not in normalized:
            normalized.append(channel)
    return normalized or ["official"]


def is_material_registry_public_channel(channel: str) -> bool:
    """Return whether a Registry channel is safe for anonymous read access.
    判断 Registry 频道是否允许匿名只读访问。
    """
    return str(channel or "").strip() in _MATERIAL_REGISTRY_PUBLIC_CHANNELS


def verify_material_registry_read_access(
    *,
    channels: Sequence[str],
    authorization: str | None,
) -> None:
    """Enforce MVP read-only channel access.
    执行 MVP 阶段只读频道访问控制。
    """
    private_channels = [
        channel for channel in channels if not is_material_registry_public_channel(channel)
    ]
    if not private_channels:
        return
    expected_token = os.environ.get("LUMINA_MATERIAL_REGISTRY_TEAM_TOKEN", "").strip()
    if not expected_token:
        raise PermissionError("Material registry team channel is not configured")
    expected_header = f"Bearer {expected_token}"
    if str(authorization or "").strip() != expected_header:
        raise PermissionError("Material registry channel requires a team token")


def verify_material_registry_write_access(*, official_password: str | None) -> None:
    """Enforce server-side Registry write access for upload/approval flows.
    执行服务端 Registry 写入接口的权限校验。
    """
    expected_password = os.environ.get(
        "LUMINA_MATERIAL_REGISTRY_OFFICIAL_PASSWORD",
        "",
    ).strip()
    if not expected_password:
        raise PermissionError("Material registry official password is not configured")
    if str(official_password or "").strip() != expected_password:
        raise PermissionError("Material registry official password is invalid")


def _load_bundle_manifest(zip_path: Path) -> dict[str, Any] | None:
    try:
        with zipfile.ZipFile(zip_path, "r") as archive:
            manifest_payload = json.loads(
                archive.read(_MATERIAL_BUNDLE_MANIFEST_FILENAME).decode("utf-8")
            )
    except (OSError, KeyError, UnicodeDecodeError, json.JSONDecodeError, zipfile.BadZipFile):
        return None
    if not isinstance(manifest_payload, dict):
        return None
    if str(manifest_payload.get("kind") or "") != "lumina_material_bundle":
        return None
    if str(manifest_payload.get("schema_version") or "") != "2.0":
        return None
    packages = manifest_payload.get("packages")
    if not isinstance(packages, list):
        return None
    return manifest_payload


def _package_url_for_path(root: Path, zip_path: Path) -> str:
    relative = zip_path.resolve().relative_to(root.resolve()).as_posix()
    return f"{_MATERIAL_REGISTRY_PACKAGE_URL_PREFIX}/{quote(relative, safe='/')}"


def _safe_registry_filename_segment(value: Any, fallback: str) -> str:
    segment = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value or "").strip()).strip(".-")
    return segment or fallback


def _normalize_registry_local_directory(value: Any) -> str:
    return (
        str(value or "")
        .strip()
        .replace("\\", "/")
        .strip("/")
    )


def _normalize_registry_content_hash(value: Any) -> str:
    return str(value or "").strip().lower()


def _material_registry_duplicate_key(entry: dict[str, Any]) -> tuple[str, str] | None:
    directory = _normalize_registry_local_directory(entry.get("local_directory"))
    content_hash = _normalize_registry_content_hash(entry.get("content_hash"))
    if not directory or not content_hash:
        return None
    return directory, content_hash


def _package_material_entries(
    *,
    root: Path,
    zip_path: Path,
    manifest: dict[str, Any],
    package_sha256: str | None = None,
    package_bytes: int | None = None,
    package_url: str | None = None,
) -> list[dict[str, Any]]:
    resolved_package_sha256 = package_sha256 or _sha256_file(zip_path)
    resolved_package_bytes = package_bytes if package_bytes is not None else int(zip_path.stat().st_size)
    resolved_package_url = package_url or _package_url_for_path(root, zip_path)
    materials: list[dict[str, Any]] = []
    raw_packages = manifest.get("packages")
    if not isinstance(raw_packages, list):
        return materials
    for raw_package in raw_packages:
        if not isinstance(raw_package, dict):
            continue
        channel = str(raw_package.get("channel") or "official")
        display = raw_package.get("display")
        compatibility = raw_package.get("compatibility")
        materials.append(
            {
                "material_id": str(raw_package.get("material_id") or ""),
                "revision_id": str(raw_package.get("revision_id") or ""),
                "content_hash": str(raw_package.get("content_hash") or ""),
                "channel": channel,
                "visibility": str(raw_package.get("visibility") or channel),
                "local_directory": str(raw_package.get("local_directory") or ""),
                "display": display if isinstance(display, dict) else {},
                "compatibility": compatibility if isinstance(compatibility, dict) else {},
                "package_url": resolved_package_url,
                "package_sha256": resolved_package_sha256,
                "package_bytes": resolved_package_bytes,
            }
        )
    return materials


def _material_registry_catalog_cache_key(
    root: Path,
    channels: Sequence[str],
) -> tuple[str, tuple[str, ...]]:
    return str(root), tuple(channels)


def _is_material_registry_tmp_relative_path(relative_path: Path) -> bool:
    return _MATERIAL_REGISTRY_TMP_DIRNAME in relative_path.parts


def _iter_material_registry_package_paths(root: Path) -> Iterator[tuple[Path, Path]]:
    for zip_path in sorted(root.rglob("*.zip"), key=lambda path: path.as_posix()):
        try:
            relative = zip_path.resolve().relative_to(root)
        except ValueError:
            continue
        if _is_material_registry_tmp_relative_path(relative):
            continue
        yield zip_path, relative


def _material_registry_package_marker(root: Path) -> tuple[tuple[str, int, int], ...]:
    marker: list[tuple[str, int, int]] = []
    for zip_path, relative_path in _iter_material_registry_package_paths(root):
        try:
            stat = zip_path.stat()
        except OSError:
            continue
        marker.append(
            (relative_path.as_posix(), int(stat.st_size), int(stat.st_mtime_ns))
        )
    return tuple(marker)


def _cached_material_registry_catalog(
    *,
    root: Path,
    channels: Sequence[str],
    marker: tuple[tuple[str, int, int], ...],
) -> dict[str, Any] | None:
    cache_key = _material_registry_catalog_cache_key(root, channels)
    now = time.monotonic()
    with _MATERIAL_REGISTRY_CATALOG_CACHE_LOCK:
        cached = _MATERIAL_REGISTRY_CATALOG_CACHE.get(cache_key)
        if not cached:
            return None
        cached_at = float(cached.get("cached_at") or 0.0)
        if now - cached_at > _MATERIAL_REGISTRY_CATALOG_CACHE_TTL_S:
            _MATERIAL_REGISTRY_CATALOG_CACHE.pop(cache_key, None)
            return None
        if cached.get("marker") != marker:
            _MATERIAL_REGISTRY_CATALOG_CACHE.pop(cache_key, None)
            return None
        payload = cached.get("payload")
        if not isinstance(payload, dict):
            return None
        return _json_clone(payload)


def _store_material_registry_catalog_cache(
    *,
    root: Path,
    channels: Sequence[str],
    marker: tuple[tuple[str, int, int], ...],
    payload: dict[str, Any],
) -> None:
    cache_key = _material_registry_catalog_cache_key(root, channels)
    with _MATERIAL_REGISTRY_CATALOG_CACHE_LOCK:
        _MATERIAL_REGISTRY_CATALOG_CACHE[cache_key] = {
            "cached_at": time.monotonic(),
            "marker": marker,
            "payload": _json_clone(payload),
        }


def _invalidate_material_registry_catalog_cache(root: Path) -> None:
    root_key = str(root)
    with _MATERIAL_REGISTRY_CATALOG_CACHE_LOCK:
        stale_keys = [
            cache_key
            for cache_key in _MATERIAL_REGISTRY_CATALOG_CACHE
            if cache_key[0] == root_key
        ]
        for cache_key in stale_keys:
            _MATERIAL_REGISTRY_CATALOG_CACHE.pop(cache_key, None)


def _normalize_material_registry_pagination(
    *,
    limit: int | None = None,
    offset: int | None = 0,
) -> tuple[int | None, int]:
    normalized_offset = 0 if offset is None else int(offset)
    if normalized_offset < 0:
        raise ValueError("Material registry catalog offset must be non-negative")
    if limit is None:
        return None, normalized_offset
    normalized_limit = int(limit)
    if normalized_limit <= 0:
        raise ValueError("Material registry catalog limit must be positive")
    return normalized_limit, normalized_offset


def _paginate_material_registry_catalog(
    catalog: dict[str, Any],
    *,
    limit: int | None = None,
    offset: int | None = 0,
) -> dict[str, Any]:
    normalized_limit, normalized_offset = _normalize_material_registry_pagination(
        limit=limit,
        offset=offset,
    )
    raw_materials = catalog.get("materials")
    materials = raw_materials if isinstance(raw_materials, list) else []
    total_count = int(catalog.get("total_count") or len(materials))
    if normalized_limit is None:
        paged_materials = materials[normalized_offset:]
    else:
        paged_materials = materials[
            normalized_offset : normalized_offset + normalized_limit
        ]
    payload = dict(catalog)
    payload["materials"] = paged_materials
    payload["count"] = len(paged_materials)
    payload["total_count"] = total_count
    payload["offset"] = normalized_offset
    payload["limit"] = normalized_limit
    return _json_clone(payload)


def _normalize_material_registry_query(query: str | None = None) -> str:
    return " ".join(str(query or "").casefold().split())


def _material_registry_entry_matches_query(
    entry: dict[str, Any],
    query: str,
) -> bool:
    if not query:
        return True
    searchable_values: list[str] = [
        str(entry.get("material_id") or ""),
        str(entry.get("revision_id") or ""),
        str(entry.get("content_hash") or ""),
        str(entry.get("channel") or ""),
        str(entry.get("visibility") or ""),
        str(entry.get("local_directory") or ""),
    ]
    for key in ("display", "compatibility"):
        value = entry.get(key)
        if isinstance(value, dict):
            searchable_values.append(json.dumps(value, ensure_ascii=False, sort_keys=True))
    haystack = " ".join(searchable_values).casefold()
    return all(token in haystack for token in query.split())


def _filter_material_registry_catalog(
    catalog: dict[str, Any],
    *,
    query: str | None = None,
) -> dict[str, Any]:
    normalized_query = _normalize_material_registry_query(query)
    if not normalized_query:
        return _json_clone(catalog)
    raw_materials = catalog.get("materials")
    materials = raw_materials if isinstance(raw_materials, list) else []
    filtered_materials = [
        entry
        for entry in materials
        if isinstance(entry, dict)
        and _material_registry_entry_matches_query(entry, normalized_query)
    ]
    payload = dict(catalog)
    payload["materials"] = filtered_materials
    payload["count"] = len(filtered_materials)
    payload["total_count"] = len(filtered_materials)
    payload["offset"] = 0
    payload["limit"] = None
    return _json_clone(payload)


def _material_registry_catalog_identity(entry: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(entry.get("material_id") or ""),
        str(entry.get("revision_id") or ""),
        str(entry.get("content_hash") or "").lower(),
    )


def _material_registry_catalog_channel_priority(entry: dict[str, Any]) -> int:
    channel = str(entry.get("channel") or "").strip()
    return {
        "official": 30,
        "team": 20,
        "community": 10,
        "pending": 0,
    }.get(channel, 0)


def _deduplicate_material_registry_catalog_entries(
    entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    selected: dict[tuple[str, str, str], dict[str, Any]] = {}
    for entry in entries:
        identity = _material_registry_catalog_identity(entry)
        if not all(identity):
            selected[(identity[0], identity[1], f"{identity[2]}:{len(selected)}")] = entry
            continue
        existing = selected.get(identity)
        if existing is None or (
            _material_registry_catalog_channel_priority(entry)
            > _material_registry_catalog_channel_priority(existing)
        ):
            selected[identity] = entry
    return list(selected.values())


def _rewrite_material_registry_package_channel(
    *,
    source_zip_path: Path,
    destination_zip_path: Path,
    channel: str,
) -> dict[str, Any]:
    manifest = _load_bundle_manifest(source_zip_path)
    if manifest is None:
        raise ValueError("Material registry package manifest is invalid")
    updated_manifest = json.loads(json.dumps(manifest))
    raw_packages = updated_manifest.get("packages")
    if not isinstance(raw_packages, list) or not raw_packages:
        raise ValueError("Material registry package manifest is invalid")
    for raw_package in raw_packages:
        if isinstance(raw_package, dict):
            raw_package["channel"] = channel
            raw_package["visibility"] = channel

    destination_zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(source_zip_path, "r") as source_archive:
        with zipfile.ZipFile(
            destination_zip_path,
            "w",
            compression=zipfile.ZIP_DEFLATED,
        ) as destination_archive:
            for member in source_archive.infolist():
                if member.filename == _MATERIAL_BUNDLE_MANIFEST_FILENAME:
                    continue
                destination_archive.writestr(member, source_archive.read(member.filename))
            destination_archive.writestr(
                _MATERIAL_BUNDLE_MANIFEST_FILENAME,
                json.dumps(updated_manifest, ensure_ascii=False, indent=2),
            )
    return updated_manifest


def _store_material_registry_package(
    *,
    source_zip_path: Path,
    channel: str,
    packages_dir: str | None = None,
) -> dict[str, Any]:
    normalized_channel = normalize_material_registry_channels([channel])[0]
    root = _registry_packages_root(packages_dir, create=True)
    manifest = validate_material_bundle_archive(archive_path=str(source_zip_path))
    packages = manifest.get("packages")
    if not isinstance(packages, list) or not packages or not isinstance(packages[0], dict):
        raise ValueError("Material registry package manifest is invalid")
    first_package = packages[0]
    material_segment = _safe_registry_filename_segment(
        first_package.get("material_id"),
        "material",
    )
    revision_segment = _safe_registry_filename_segment(
        first_package.get("revision_id"),
        "revision",
    )
    tmp_dir = root / "_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix="material_registry_package_",
        suffix=".zip",
        dir=tmp_dir,
    )
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        updated_manifest = _rewrite_material_registry_package_channel(
            source_zip_path=source_zip_path,
            destination_zip_path=tmp_path,
            channel=normalized_channel,
        )
        package_sha256 = _sha256_file(tmp_path)
        destination_path = (
            root
            / normalized_channel
            / material_segment
            / f"{revision_segment}-{package_sha256[:12]}.zip"
        )
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path.replace(destination_path)
    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass
    relative = destination_path.relative_to(root).as_posix()
    materials = _package_material_entries(
        root=root,
        zip_path=destination_path,
        manifest=updated_manifest,
    )
    _invalidate_material_registry_catalog_cache(root)
    return {
        "channel": normalized_channel,
        "package_path": relative,
        "package_url": _package_url_for_path(root, destination_path),
        "package_sha256": _sha256_file(destination_path),
        "package_bytes": int(destination_path.stat().st_size),
        "materials": materials,
    }


def upload_material_registry_package(
    *,
    archive_path: str,
    channel: str = "pending",
    packages_dir: str | None = None,
    reject_duplicates: bool = True,
) -> dict[str, Any]:
    """Store an uploaded material package in the Registry package root.
    将上传的耗材包保存到 Registry 包目录。
    """
    validate_material_bundle_archive(archive_path=archive_path)
    if reject_duplicates:
        assert_material_registry_package_not_duplicate(
            archive_path=archive_path,
            packages_dir=packages_dir,
        )
    return _store_material_registry_package(
        source_zip_path=Path(archive_path),
        channel=channel,
        packages_dir=packages_dir,
    )


def find_duplicate_material_registry_package_entries(
    *,
    archive_path: str,
    packages_dir: str | None = None,
    channels: Sequence[str] | None = ("official", "pending"),
) -> list[dict[str, Any]]:
    """Find Registry entries with the same local directory and content hash.
    查找与待上传包 local_directory + content_hash 相同的 Registry 条目。
    """
    root = _registry_packages_root(packages_dir, create=True)
    source_path = Path(archive_path)
    manifest = _load_bundle_manifest(source_path)
    if manifest is None:
        raise ValueError("Material registry package manifest is invalid")
    source_entries = _package_material_entries(
        root=root,
        zip_path=source_path,
        manifest=manifest,
        package_sha256="",
        package_bytes=0,
        package_url="local-upload.zip",
    )
    source_keys = {
        key
        for key in (
            _material_registry_duplicate_key(entry)
            for entry in source_entries
        )
        if key is not None
    }
    if not source_keys:
        return []

    catalog = build_material_registry_catalog(
        channels=channels,
        packages_dir=packages_dir,
    )
    duplicates: list[dict[str, Any]] = []
    raw_entries = catalog.get("materials")
    if not isinstance(raw_entries, list):
        return duplicates
    for raw_entry in raw_entries:
        if not isinstance(raw_entry, dict):
            continue
        existing_key = _material_registry_duplicate_key(raw_entry)
        if existing_key in source_keys:
            duplicates.append(_json_clone(raw_entry))
    return duplicates


def assert_material_registry_package_not_duplicate(
    *,
    archive_path: str,
    packages_dir: str | None = None,
    channels: Sequence[str] | None = ("official", "pending"),
) -> None:
    """Raise when a package duplicates an existing pending/official entry.
    若包与现有 pending/official 条目重复则抛出。
    """
    duplicates = find_duplicate_material_registry_package_entries(
        archive_path=archive_path,
        packages_dir=packages_dir,
        channels=channels,
    )
    if not duplicates:
        return
    first = duplicates[0]
    raise MaterialRegistryDuplicateError(
        "Material registry package already exists: "
        f"{first.get('local_directory')} "
        f"{first.get('content_hash')} "
        f"({first.get('channel')})"
    )


def approve_material_registry_package(
    *,
    package_path: str,
    official_password: str,
    packages_dir: str | None = None,
) -> dict[str, Any]:
    """Approve a Registry package into the public official channel.
    将 Registry 包审批为公开 official 频道。
    """
    verify_material_registry_write_access(official_password=official_password)
    source_path = resolve_material_registry_package_path(
        package_path=package_path,
        packages_dir=packages_dir,
    )
    return _store_material_registry_package(
        source_zip_path=source_path,
        channel="official",
        packages_dir=packages_dir,
    )


def build_material_registry_catalog(
    *,
    channels: Sequence[str] | None = None,
    packages_dir: str | None = None,
    limit: int | None = None,
    offset: int | None = 0,
    query: str | None = None,
) -> dict[str, Any]:
    """Build a catalog from local v2 package ZIP files.
    从本地 v2 耗材包 ZIP 文件构建 catalog。
    """
    normalized_channels = normalize_material_registry_channels(channels)
    channel_set = set(normalized_channels)
    root = _registry_packages_root(packages_dir)
    package_marker = _material_registry_package_marker(root)
    cached_catalog = _cached_material_registry_catalog(
        root=root,
        channels=normalized_channels,
        marker=package_marker,
    )
    if cached_catalog is not None:
        return _paginate_material_registry_catalog(
            _filter_material_registry_catalog(cached_catalog, query=query),
            limit=limit,
            offset=offset,
        )

    materials: list[dict[str, Any]] = []
    for zip_path, _relative_path in _iter_material_registry_package_paths(root):
        manifest = _load_bundle_manifest(zip_path)
        if manifest is None:
            continue
        package_sha256 = _sha256_file(zip_path)
        package_bytes = int(zip_path.stat().st_size)
        package_url = _package_url_for_path(root, zip_path)
        raw_packages = manifest.get("packages") if isinstance(manifest, dict) else []
        for raw_package in raw_packages:
            if not isinstance(raw_package, dict):
                continue
            channel = str(raw_package.get("channel") or "official")
            if channel not in channel_set:
                continue
            entry = _package_material_entries(
                root=root,
                zip_path=zip_path,
                manifest={"packages": [raw_package]},
                package_sha256=package_sha256,
                package_bytes=package_bytes,
                package_url=package_url,
            )[0]
            materials.append(entry)
    materials = _deduplicate_material_registry_catalog_entries(materials)
    materials.sort(
        key=lambda entry: (
            str(entry["channel"]),
            str(entry.get("display", {}).get("brand", "")).casefold(),
            str(entry.get("display", {}).get("material_name", "")).casefold(),
            str(entry["material_id"]),
            str(entry["revision_id"]),
        )
    )
    catalog = {
        "schema_version": _MATERIAL_REGISTRY_CATALOG_SCHEMA_VERSION,
        "channels": normalized_channels,
        "count": len(materials),
        "total_count": len(materials),
        "offset": 0,
        "limit": None,
        "materials": materials,
    }
    _store_material_registry_catalog_cache(
        root=root,
        channels=normalized_channels,
        marker=package_marker,
        payload=catalog,
    )
    return _paginate_material_registry_catalog(
        _filter_material_registry_catalog(catalog, query=query),
        limit=limit,
        offset=offset,
    )


def material_registry_package_channels(zip_path: Path) -> list[str]:
    """Return channels declared by one package ZIP.
    返回一个耗材包 ZIP 声明的频道。
    """
    manifest = _load_bundle_manifest(zip_path)
    if manifest is None:
        raise ValueError("Material registry package manifest is invalid")
    channels: list[str] = []
    raw_packages = manifest.get("packages")
    if not isinstance(raw_packages, list):
        raise ValueError("Material registry package manifest is invalid")
    for raw_package in raw_packages:
        if not isinstance(raw_package, dict):
            continue
        channel = str(raw_package.get("channel") or "official").strip() or "official"
        if channel not in channels:
            channels.append(channel)
    return channels or ["official"]


def resolve_material_registry_package_path(
    *,
    package_path: str,
    packages_dir: str | None = None,
) -> Path:
    """Resolve a requested package path under the configured package root.
    在已配置包目录内安全解析请求的 package 路径。
    """
    raw_path = str(package_path or "").strip().replace("\\", "/")
    windows_path = PureWindowsPath(str(package_path or "").strip())
    if (
        not raw_path
        or raw_path.startswith("/")
        or windows_path.is_absolute()
        or windows_path.drive
        or windows_path.anchor
    ):
        raise ValueError(f"Unsafe material registry package path: {package_path}")
    parts = [part for part in raw_path.split("/") if part]
    if not parts or any(part in {".", ".."} for part in parts):
        raise ValueError(f"Unsafe material registry package path: {package_path}")
    if _MATERIAL_REGISTRY_TMP_DIRNAME in parts:
        raise ValueError(f"Unsafe material registry package path: {package_path}")
    relative = Path(*parts)
    if relative.suffix.lower() != ".zip":
        raise ValueError("Material registry package path must reference a ZIP file")
    root = _registry_packages_root(packages_dir)
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Unsafe material registry package path: {package_path}") from exc
    if not candidate.is_file():
        raise FileNotFoundError(f"Material registry package not found: {relative.as_posix()}")
    return candidate
