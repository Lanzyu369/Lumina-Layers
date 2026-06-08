"""Read-only material Registry catalog helpers.
只读耗材 Registry catalog 辅助函数。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import zipfile
from pathlib import Path, PureWindowsPath
from typing import Any, Sequence
from urllib.parse import quote

_MATERIAL_BUNDLE_MANIFEST_FILENAME = "lumina_material_bundle.json"
_MATERIAL_REGISTRY_CATALOG_SCHEMA_VERSION = "1.0"
_MATERIAL_REGISTRY_PACKAGE_URL_PREFIX = "/api/material-registry/v1/packages"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _registry_packages_root(packages_dir: str | None = None) -> Path:
    raw_dir = str(
        packages_dir
        if packages_dir is not None
        else os.environ.get("LUMINA_MATERIAL_REGISTRY_PACKAGES_DIR", "")
    ).strip()
    if not raw_dir:
        raise ValueError("Material registry packages directory is not configured")
    root = Path(raw_dir)
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


def verify_material_registry_read_access(
    *,
    channels: Sequence[str],
    authorization: str | None,
) -> None:
    """Enforce MVP read-only channel access.
    执行 MVP 阶段只读频道访问控制。
    """
    private_channels = [channel for channel in channels if channel != "official"]
    if not private_channels:
        return
    expected_token = os.environ.get("LUMINA_MATERIAL_REGISTRY_TEAM_TOKEN", "").strip()
    if not expected_token:
        raise PermissionError("Material registry team channel is not configured")
    expected_header = f"Bearer {expected_token}"
    if str(authorization or "").strip() != expected_header:
        raise PermissionError("Material registry channel requires a team token")


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


def build_material_registry_catalog(
    *,
    channels: Sequence[str] | None = None,
    packages_dir: str | None = None,
) -> dict[str, Any]:
    """Build a catalog from local v2 package ZIP files.
    从本地 v2 耗材包 ZIP 文件构建 catalog。
    """
    normalized_channels = normalize_material_registry_channels(channels)
    channel_set = set(normalized_channels)
    root = _registry_packages_root(packages_dir)
    materials: list[dict[str, Any]] = []
    for zip_path in sorted(root.rglob("*.zip"), key=lambda path: path.as_posix()):
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
                    "package_url": package_url,
                    "package_sha256": package_sha256,
                    "package_bytes": package_bytes,
                }
            )
    materials.sort(
        key=lambda entry: (
            str(entry["channel"]),
            str(entry.get("display", {}).get("brand", "")).casefold(),
            str(entry.get("display", {}).get("material_name", "")).casefold(),
            str(entry["material_id"]),
            str(entry["revision_id"]),
        )
    )
    return {
        "schema_version": _MATERIAL_REGISTRY_CATALOG_SCHEMA_VERSION,
        "channels": normalized_channels,
        "count": len(materials),
        "materials": materials,
    }


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
