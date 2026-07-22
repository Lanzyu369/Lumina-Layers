from __future__ import annotations

import argparse
from collections.abc import Callable
import json
import os
from pathlib import Path
import tempfile
import urllib.request

if __package__ in {None, ""}:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.machine_adapter.import_profiles import AssetRoot, ImportSource, run_import_sources
from tools.machine_adapter.providers import get_provider


LOCAL_SLICER_SYSTEM_DIRS: dict[str, str] = {
    "BambuStudio": "BambuStudio/system",
    "OrcaSlicer": "OrcaSlicer/system",
    "SnapmakerOrca": "Snapmaker_Orca/system",
    "ElegooSlicer": "ElegooSlicer/system",
    "AnycubicSlicerNext": "AnycubicSlicerNext/system",
    "FlashStudio": "Orca-Flashforge/system",
}

APPLICATION_METADATA_OVERRIDES: dict[str, str] = {
    "AnycubicSlicerNext": "AnycubicSlicerNext-1.4.1.2",
    "FlashStudio": "BambuStudio-2.3.2",
}

CLIENT_VERSION_OVERRIDES: dict[str, str] = {
    "AnycubicSlicerNext": "1.4.1.2 20260604104233",
    "FlashStudio": "",
}

_OFFICIAL_ORCA_COVER_ASSETS: tuple[tuple[str, str, str], ...] = (
    (
        "Elegoo",
        "Elegoo Centauri_cover.png",
        "https://raw.githubusercontent.com/OrcaSlicer/OrcaSlicer/main/resources/profiles/Elegoo/Elegoo%20Centauri_cover.png",
    ),
    (
        "Elegoo",
        "Elegoo Centauri Carbon_cover.png",
        "https://raw.githubusercontent.com/OrcaSlicer/OrcaSlicer/main/resources/profiles/Elegoo/Elegoo%20Centauri%20Carbon_cover.png",
    ),
    (
        "Elegoo",
        "Elegoo Centauri Carbon 2_cover.png",
        "https://raw.githubusercontent.com/OrcaSlicer/OrcaSlicer/main/resources/profiles/Elegoo/Elegoo%20Centauri%20Carbon%202_cover.png",
    ),
)


def _default_appdata_root() -> Path:
    raw = os.environ.get("APPDATA")
    if raw:
        return Path(raw)
    return Path.home() / "AppData" / "Roaming"


def _default_asset_cache_root() -> Path:
    raw = os.environ.get("LOCALAPPDATA")
    if raw:
        return Path(raw) / "LuminaStudio" / "machine_adapter_asset_cache"
    return Path.home() / ".cache" / "lumina-studio" / "machine_adapter_asset_cache"


def _download_binary(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=20) as response:
        payload = response.read()
    if not payload:
        raise RuntimeError(f"Downloaded empty asset: {url}")
    with tempfile.NamedTemporaryFile(delete=False, dir=destination.parent, suffix=destination.suffix) as tmp:
        tmp.write(payload)
        temp_path = Path(tmp.name)
    temp_path.replace(destination)


def _vendor_source_version(source_root: Path, vendor_key: str) -> str:
    metadata_path = source_root / f"{vendor_key}.json"
    try:
        data = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "unknown"
    version = str(data.get("version") or "").strip()
    return version or "unknown"


def discover_local_import_sources(
    *,
    appdata_root: Path | None = None,
    slicer_ids: tuple[str, ...] | None = None,
) -> list[ImportSource]:
    """Discover installed slicer machine-profile sources.

    发现本机已安装切片软件的机器 profile 来源，用于生成 Lumina 内置
    machine_registry。每个 vendor 单独作为一个 ImportSource，保留原始
    profile 包版本，避免同一切片软件不同 vendor 版本混在一起。
    """
    root = appdata_root or _default_appdata_root()
    requested = slicer_ids or tuple(LOCAL_SLICER_SYSTEM_DIRS)
    sources: list[ImportSource] = []
    for slicer_id in requested:
        if slicer_id not in LOCAL_SLICER_SYSTEM_DIRS:
            raise KeyError(f"Unsupported local slicer id: {slicer_id}")
        provider = get_provider(slicer_id)
        source_root = root / LOCAL_SLICER_SYSTEM_DIRS[slicer_id]
        if not source_root.exists():
            continue
        for vendor_key in provider.default_vendor_keys:
            if not (source_root / vendor_key / "machine").exists():
                continue
            sources.append(
                ImportSource(
                    slicer_id=slicer_id,
                    source_root=source_root,
                    source_version=_vendor_source_version(source_root, vendor_key),
                    vendor_keys=(vendor_key,),
                    application_metadata=APPLICATION_METADATA_OVERRIDES.get(slicer_id),
                    client_version=CLIENT_VERSION_OVERRIDES.get(slicer_id),
                )
            )
    return sources


def _has_cover_assets(vendor_root: Path) -> bool:
    for pattern in ("*_cover.png", "*_cover.jpg", "*_cover.jpeg", "*_cover.webp", "*_cover.svg"):
        if next(vendor_root.glob(pattern), None) is not None:
            return True
    return False


def _has_loose_cover_assets(asset_root: Path) -> bool:
    cover_suffixes = {".png", ".jpg", ".jpeg", ".webp", ".svg"}
    for item in asset_root.iterdir():
        if (
            item.is_file()
            and item.suffix.casefold() in cover_suffixes
            and "cover" in item.name.casefold()
        ):
            return True
    return False


def discover_local_asset_roots(
    *,
    appdata_root: Path | None = None,
    slicer_ids: tuple[str, ...] | None = None,
) -> tuple[AssetRoot, ...]:
    """Discover local vendor directories that can provide machine images.

    发现本机切片软件中可提供机器图片的 vendor 目录。某些切片软件不会把
    这些 vendor 作为 Lumina 导入来源，但里面仍有可复用的 ``*_cover``
    资源，例如 BambuStudio/system/Elegoo。
    """
    root = appdata_root or _default_appdata_root()
    requested = slicer_ids or tuple(LOCAL_SLICER_SYSTEM_DIRS)
    asset_roots: list[AssetRoot] = []
    seen: set[tuple[str, str]] = set()
    for slicer_id in requested:
        if slicer_id not in LOCAL_SLICER_SYSTEM_DIRS:
            raise KeyError(f"Unsupported local slicer id: {slicer_id}")
        source_root = root / LOCAL_SLICER_SYSTEM_DIRS[slicer_id]
        if not source_root.exists():
            continue
        for vendor_root in sorted(source_root.iterdir(), key=lambda item: item.name.casefold()):
            if not vendor_root.is_dir() or not _has_cover_assets(vendor_root):
                continue
            key = (source_root.resolve().as_posix().casefold(), vendor_root.name.casefold())
            if key in seen:
                continue
            seen.add(key)
            asset_roots.append((source_root, vendor_root.name))
        snapmaker_web_images = (
            source_root.parent
            / "web"
            / "flutter_web"
            / "assets"
            / "assets"
            / "images"
        )
        if slicer_id == "SnapmakerOrca" and snapmaker_web_images.is_dir() and _has_loose_cover_assets(snapmaker_web_images):
            key = (snapmaker_web_images.resolve().as_posix().casefold(), "")
            if key not in seen:
                seen.add(key)
                asset_roots.append((snapmaker_web_images, ""))
    return tuple(asset_roots)


def ensure_official_orca_cover_asset_cache(
    *,
    cache_root: Path | None = None,
    downloader: Callable[[str, Path], None] = _download_binary,
) -> tuple[AssetRoot, ...]:
    """Prepare official Orca cover assets used by local profile sync.

    准备本地同步时需要复用的 Orca 官方机器图片。优先使用已缓存文件；
    缺失时下载到用户本机缓存目录，避免把开发缓存写进项目仓库。
    """
    root = cache_root or _default_asset_cache_root()
    profile_root = root / "OrcaSlicer" / "profiles"
    seen_vendors: set[str] = set()
    for vendor_key, filename, url in _OFFICIAL_ORCA_COVER_ASSETS:
        destination = profile_root / vendor_key / filename
        if not destination.exists() or destination.stat().st_size == 0:
            downloader(url, destination)
        seen_vendors.add(vendor_key)
    return tuple(
        (profile_root, vendor_key)
        for vendor_key in sorted(seen_vendors)
        if _has_cover_assets(profile_root / vendor_key)
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sync local slicer machine profiles into a Lumina machine registry."
    )
    parser.add_argument("--appdata-root")
    parser.add_argument("--asset-cache-root")
    parser.add_argument("--skip-official-orca-assets", action="store_true")
    parser.add_argument("--output", default="machine_registry")
    parser.add_argument("--slicer", action="append", dest="slicers")
    args = parser.parse_args()

    sources = discover_local_import_sources(
        appdata_root=Path(args.appdata_root) if args.appdata_root else None,
        slicer_ids=tuple(args.slicers) if args.slicers else None,
    )
    asset_roots = discover_local_asset_roots(
        appdata_root=Path(args.appdata_root) if args.appdata_root else None,
        slicer_ids=tuple(args.slicers) if args.slicers else None,
    )
    official_asset_roots: tuple[AssetRoot, ...] = ()
    if not args.skip_official_orca_assets:
        try:
            official_asset_roots = ensure_official_orca_cover_asset_cache(
                cache_root=Path(args.asset_cache_root) if args.asset_cache_root else None,
            )
        except Exception as exc:
            print(f"Skipped official Orca cover asset cache: {exc}")
    result = run_import_sources(
        sources,
        output_root=Path(args.output),
        asset_search_roots=(*asset_roots, *official_asset_roots),
    )
    print(f"Imported {result.device_count} device profiles from {len(sources)} local source packages")
    for source in sources:
        print(
            f"- {source.slicer_id} {source.source_version} "
            f"vendors={','.join(source.vendor_keys)} root={source.source_root}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
