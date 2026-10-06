from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path, PureWindowsPath
import re
import shutil
import sys
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from config import format_native_nozzle_size
from tools.machine_adapter.build_plates import (
    copy_native_build_plate_assets,
    intersect_machine_build_plate_scopes,
    resolve_machine_build_plates,
)
from tools.machine_adapter.emitter import build_device_registry_entry
from tools.machine_adapter.providers import get_provider
from tools.machine_adapter.resolver import (
    ResolvedMachineProfile,
    resolve_machine_model_settings,
    resolve_machine_profiles,
)

AssetRoot = tuple[Path, str]

_ELEGOO_CENTAURI_MODELS = {
    "elegoo centauri",
    "elegoo centauri carbon",
    "elegoo centauri carbon 2",
}
_SNAPMAKER_U1_MODEL = "snapmaker u1"
_MAX_THUMBNAIL_DIMENSION = 1000
_FLASHSTUDIO_MAX_SUPPORTED_NOZZLE_MM = 0.4
_QIDI_STUDIO_SUPPORTED_MODELS = {
    "q2",
    "q2c",
    "x-max 4",
    "x-plus 5",
}
_QIDI_STUDIO_MAX_SUPPORTED_NOZZLE_MM = 0.4


@dataclass(frozen=True)
class ImportResult:
    device_count: int


@dataclass(frozen=True)
class ImportSource:
    slicer_id: str
    source_root: Path
    source_version: str
    vendor_keys: tuple[str, ...]
    machine_name: str | None = None
    application_metadata: str | None = None
    client_version: str | None = None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _matches_machine_name(profile_name: str, settings: dict[str, Any], machine_name: str | None) -> bool:
    if not machine_name:
        return True
    needle = machine_name.strip().casefold()
    if not needle:
        return True
    printer_model = str(settings.get("printer_model") or "").strip().casefold()
    if printer_model:
        return printer_model == needle
    return profile_name.strip().casefold() == needle


def _asset_slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")


def _asset_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.strip().lower())


def _copy_thumbnail_file(source: Path, destination: Path) -> None:
    """Copy a registry thumbnail, bounding oversized raster assets.

    复制 registry 缩略图，并限制超大位图边长。部分官方 profile 会携带
    3000×3000、近 20 MB 的 PNG；设置页只显示机器卡片，不需要原始尺寸。
    """

    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.suffix.casefold() not in {".png", ".jpg", ".jpeg", ".webp"}:
        shutil.copyfile(source, destination)
        return
    try:
        from PIL import Image

        with Image.open(source) as image:
            if max(image.size) <= _MAX_THUMBNAIL_DIMENSION:
                shutil.copyfile(source, destination)
                return
            resized = image.copy()
            resized.thumbnail(
                (_MAX_THUMBNAIL_DIMENSION, _MAX_THUMBNAIL_DIMENSION),
                Image.Resampling.LANCZOS,
            )
            resized.save(destination, optimize=True)
    except (ImportError, OSError, ValueError):
        shutil.copyfile(source, destination)


def _profile_model_key(profile_name: str, settings: dict[str, Any]) -> str:
    raw_name = str(settings.get("printer_model") or settings.get("name") or profile_name).strip()
    name = re.sub(r"\s+\d+(?:\.\d+)?\s*(?:mm\s*)?nozzle.*$", "", raw_name, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", name).strip().casefold()


def _list_length(value: Any) -> int:
    if isinstance(value, list):
        return len(value)
    return 1 if value not in {None, ""} else 0


def _has_multiple_physical_tools(settings: dict[str, Any]) -> bool:
    return max(
        _list_length(settings.get("nozzle_diameter")),
        _list_length(settings.get("extruder_offset")),
    ) > 1


def _has_automatic_single_nozzle_toolchange(settings: dict[str, Any]) -> bool:
    gcode = str(settings.get("change_filament_gcode") or "").casefold()
    if "next_extruder" not in gcode:
        return False
    return "t[next_extruder]" in gcode or "m620" in gcode or "m621" in gcode


def _is_multicolor_machine_profile(settings: dict[str, Any]) -> bool:
    if _has_multiple_physical_tools(settings):
        return True
    if _has_automatic_single_nozzle_toolchange(settings):
        return True
    return False


def _is_flashstudio_multicolor_machine_profile(settings: dict[str, Any]) -> bool:
    single_extruder_multicolor = str(
        settings.get("single_extruder_multi_material") or ""
    ).strip().casefold()
    if single_extruder_multicolor in {"1", "true"}:
        return True
    return max(
        _list_length(settings.get("nozzle_diameter")),
        _list_length(settings.get("printer_extruder_id")),
    ) > 1


def _has_uniform_nozzle_signature(settings: dict[str, Any]) -> bool:
    raw_values = settings.get("nozzle_diameter")
    values = raw_values if isinstance(raw_values, list) else [raw_values]
    if not values or values == [None]:
        values = [settings.get("printer_variant")]
    normalized = [
        normalized
        for value in values
        if (normalized := format_native_nozzle_size(value)) is not None
    ]
    return len(set(normalized)) <= 1


def _profile_nozzle_size(profile: ResolvedMachineProfile) -> str:
    raw_values = profile.settings.get("nozzle_diameter")
    values = raw_values if isinstance(raw_values, list) else [raw_values]
    for value in values:
        normalized = format_native_nozzle_size(value)
        if normalized is not None:
            return normalized
    return format_native_nozzle_size(profile.settings.get("printer_variant")) or "0.4"


def _is_high_flow_profile(profile: ResolvedMachineProfile) -> bool:
    variant = str(profile.settings.get("printer_variant") or "").strip().casefold()
    return "hf" in variant or bool(re.search(r"\bhf\b", profile.name, flags=re.IGNORECASE))


def _registered_machine_profile_names(
    *,
    source_root: Path,
    vendor_key: str,
) -> set[str]:
    """Return machine presets exposed by the slicer's vendor manifest.

    返回切片软件 vendor manifest 正式暴露的机器预设。目录中可能保留未发布、
    已下线或实验性 JSON；只扫描文件会把这些残留配置误注册为可选机型。
    """

    manifest_path = source_root / f"{vendor_key}.json"
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return set()
    machine_list = payload.get("machine_list")
    if not isinstance(machine_list, list):
        return set()
    return {
        str(item.get("name") or "").strip().casefold()
        for item in machine_list
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    }


def _select_flashstudio_multicolor_profiles(
    profiles: list[ResolvedMachineProfile],
    *,
    source_root: Path,
    vendor_key: str,
) -> list[ResolvedMachineProfile]:
    """Select official Flash Studio multi-color presets, one per nozzle size.

    以 Flash Studio 的正式 ``machine_list`` 为边界，再依据机器预设中的多材料
    或多喷头声明识别多色机型，并只保留不大于 0.4 mm 的口径。普通/HF 预设
    口径相同时优先普通版。
    """

    registered_names = _registered_machine_profile_names(
        source_root=source_root,
        vendor_key=vendor_key,
    )
    if not registered_names:
        return []
    registered_profiles = [
        profile
        for profile in profiles
        if profile.name.strip().casefold() in registered_names
    ]
    multicolor_models = {
        _profile_model_key(profile.name, profile.settings)
        for profile in registered_profiles
        if _is_flashstudio_multicolor_machine_profile(profile.settings)
    }
    selected: dict[tuple[str, str], ResolvedMachineProfile] = {}
    for profile in registered_profiles:
        model_key = _profile_model_key(profile.name, profile.settings)
        if model_key not in multicolor_models:
            continue
        nozzle_size = _profile_nozzle_size(profile)
        if float(nozzle_size) > _FLASHSTUDIO_MAX_SUPPORTED_NOZZLE_MM:
            continue
        key = (model_key, nozzle_size)
        current = selected.get(key)
        if current is None or (
            _is_high_flow_profile(current) and not _is_high_flow_profile(profile)
        ):
            selected[key] = profile
    return sorted(
        selected.values(),
        key=lambda profile: (
            _profile_model_key(profile.name, profile.settings),
            float(_profile_nozzle_size(profile)),
        ),
    )


def _select_qidi_studio_profiles(
    profiles: list[ResolvedMachineProfile],
    *,
    source_root: Path,
    vendor_key: str,
) -> list[ResolvedMachineProfile]:
    """Select QIDI Box-capable models and their native <=0.4 mm presets.

    以 QIDI Studio 02.07.02.60 的正式 ``machine_list`` 为边界，只导入
    用户提供原生 3MF 样例覆盖的 Q2、Q2C、X-Max 4 与 X-Plus 5。喷嘴口径
    继续以软件清单为准，并遵守 Lumina 不支持大于 0.4 mm 的边界。
    """

    registered_names = _registered_machine_profile_names(
        source_root=source_root,
        vendor_key=vendor_key,
    )
    if not registered_names:
        return []

    selected: list[ResolvedMachineProfile] = []
    for profile in profiles:
        if profile.name.strip().casefold() not in registered_names:
            continue
        model_key = _profile_model_key(profile.name, profile.settings)
        if model_key not in _QIDI_STUDIO_SUPPORTED_MODELS:
            continue
        nozzle_size = _profile_nozzle_size(profile)
        if float(nozzle_size) > _QIDI_STUDIO_MAX_SUPPORTED_NOZZLE_MM:
            continue
        selected.append(profile)
    return sorted(
        selected,
        key=lambda profile: (
            _profile_model_key(profile.name, profile.settings),
            float(_profile_nozzle_size(profile)),
        ),
    )


def _should_import_profile(
    *,
    provider_id: str,
    vendor_key: str,
    profile_name: str,
    settings: dict[str, Any],
) -> bool:
    if not _has_uniform_nozzle_signature(settings):
        return False
    vendor = vendor_key.casefold()
    model_key = _profile_model_key(profile_name, settings)
    if provider_id in {"OrcaSlicer", "ElegooSlicer"} and vendor == "elegoo":
        return model_key in _ELEGOO_CENTAURI_MODELS
    if provider_id in {"OrcaSlicer", "SnapmakerOrca"} and vendor == "snapmaker":
        return model_key == _SNAPMAKER_U1_MODEL
    if provider_id != "OrcaSlicer":
        return True
    return _is_multicolor_machine_profile(settings)


def _copy_thumbnail_asset(
    *,
    source_root: Path,
    vendor_key: str,
    display_name: str,
    provider_id: str,
    source_version: str,
    output_root: Path,
    asset_roots: tuple[AssetRoot, ...] = (),
) -> str:
    roots = ((source_root, vendor_key), *asset_roots)
    seen_roots: set[tuple[str, str]] = set()
    suffixes = (".png", ".jpg", ".jpeg", ".webp", ".svg")
    target_cover_key = _asset_key(f"{display_name} cover")
    for candidate_root, candidate_vendor in roots:
        root_key = (candidate_root.resolve().as_posix().casefold(), candidate_vendor.casefold())
        if root_key in seen_roots:
            continue
        seen_roots.add(root_key)
        vendor_root = candidate_root / candidate_vendor
        for suffix in suffixes:
            source_path = vendor_root / f"{display_name}_cover{suffix}"
            if not source_path.exists():
                continue
            relative_path = (
                Path("slicers")
                / provider_id
                / source_version
                / "assets"
                / f"{_asset_slug(display_name)}_cover{suffix}"
            )
            destination = output_root / relative_path
            _copy_thumbnail_file(source_path, destination)
            return relative_path.as_posix()
        if not vendor_root.exists():
            continue
        for source_path in sorted(vendor_root.rglob("*"), key=lambda item: item.as_posix()):
            if not source_path.is_file() or source_path.suffix.lower() not in suffixes:
                continue
            if _asset_key(source_path.stem) != target_cover_key:
                continue
            relative_path = (
                Path("slicers")
                / provider_id
                / source_version
                / "assets"
                / f"{_asset_slug(display_name)}_cover{source_path.suffix.lower()}"
            )
            destination = output_root / relative_path
            _copy_thumbnail_file(source_path, destination)
            return relative_path.as_posix()
    return ""


def _resolve_machine_model_settings_from_roots(
    *,
    source_root: Path,
    vendor_key: str,
    printer_model: str,
    asset_roots: tuple[AssetRoot, ...],
) -> dict[str, Any]:
    roots = ((source_root, vendor_key), *asset_roots)
    seen_roots: set[str] = set()
    for root, candidate_vendor in roots:
        if candidate_vendor.casefold() != vendor_key.casefold():
            continue
        root_key = root.resolve().as_posix().casefold()
        if root_key in seen_roots:
            continue
        seen_roots.add(root_key)
        try:
            settings = resolve_machine_model_settings(
                root=root,
                vendor_key=candidate_vendor,
                printer_model=printer_model,
            )
        except (FileNotFoundError, KeyError, OSError, ValueError):
            continue
        if settings:
            return settings
    return {}


def _safe_bed_model_filename(value: object) -> str:
    """Keep only a safe STL basename for runtime installed-slicer lookup."""

    filename = str(value or "").strip()
    path = Path(filename)
    if (
        not filename
        or filename in {".", ".."}
        or "/" in filename
        or "\\" in filename
        or "\0" in filename
        or PureWindowsPath(filename).drive
        or path.is_absolute()
        or path.name != filename
        or path.suffix.casefold() != ".stl"
    ):
        return ""
    return filename


def run_import(
    *,
    slicer_id: str,
    source_root: Path,
    source_version: str,
    vendor_keys: tuple[str, ...],
    output_root: Path,
    machine_name: str | None = None,
    application_metadata: str | None = None,
    client_version: str | None = None,
    build_plate_source_roots: dict[str, Path] | None = None,
) -> ImportResult:
    source = ImportSource(
        slicer_id=slicer_id,
        source_root=source_root,
        source_version=source_version,
        vendor_keys=vendor_keys,
        machine_name=machine_name,
        application_metadata=application_metadata,
        client_version=client_version,
    )
    slicer_payload, device_count = _collect_import_payload(
        source,
        output_root=output_root,
        build_plate_source_roots=build_plate_source_roots,
    )
    _write_import_payload(output_root=output_root, slicers=[slicer_payload])
    return ImportResult(device_count=device_count)


def _collect_import_payload(
    source: ImportSource,
    *,
    output_root: Path,
    asset_roots: tuple[AssetRoot, ...] = (),
    bed_model_metadata_roots: tuple[AssetRoot, ...] | None = None,
    build_plate_source_roots: dict[str, Path] | None = None,
) -> tuple[dict[str, Any], int]:
    slicer_id = source.slicer_id
    source_root = source.source_root
    source_version = source.source_version
    vendor_keys = source.vendor_keys
    machine_name = source.machine_name
    native_bed_metadata_roots = (
        asset_roots if bed_model_metadata_roots is None else bed_model_metadata_roots
    )
    provider = get_provider(slicer_id)
    build_plates = copy_native_build_plate_assets(
        slicer_id=provider.slicer_id,
        source_root=source_root,
        source_version=source_version,
        output_root=output_root,
        source_roots=build_plate_source_roots,
    )
    available_build_plate_ids = {str(plate["id"]) for plate in build_plates}
    machines: dict[str, dict[str, Any]] = {}
    machine_plate_resolutions: dict[str, list[tuple[list[str], str]]] = {}
    seen_device_profile_ids: set[str] = set()

    for vendor_key in vendor_keys:
        try:
            profiles = resolve_machine_profiles(root=source_root, vendor_key=vendor_key)
        except FileNotFoundError:
            continue
        if provider.slicer_id == "FlashStudio" and vendor_key.casefold() == "flashforge":
            profiles = _select_flashstudio_multicolor_profiles(
                profiles,
                source_root=source_root,
                vendor_key=vendor_key,
            )
        elif provider.slicer_id == "QIDIStudio":
            profiles = _select_qidi_studio_profiles(
                profiles,
                source_root=source_root,
                vendor_key=vendor_key,
            )
        for profile in profiles:
            if not _matches_machine_name(profile.name, profile.settings, machine_name):
                continue
            if not _should_import_profile(
                provider_id=provider.slicer_id,
                vendor_key=profile.vendor_key,
                profile_name=profile.name,
                settings=profile.settings,
            ):
                continue
            entry, _retired_template_output = build_device_registry_entry(
                provider=provider,
                source_version=source_version,
                profile=profile,
            )
            device_profile_id = str(entry["device_profile_id"])
            if device_profile_id in seen_device_profile_ids:
                raise ValueError(f"Duplicate machine registry device profile: {device_profile_id}")
            seen_device_profile_ids.add(device_profile_id)
            machine_id = str(entry["machine_profile_id"])
            thumbnail = _copy_thumbnail_asset(
                source_root=source_root,
                vendor_key=profile.vendor_key,
                display_name=str(entry["display_name"]),
                provider_id=provider.slicer_id,
                source_version=source_version,
                output_root=output_root,
                asset_roots=asset_roots,
            )
            printer_model = str(
                profile.settings.get("printer_model") or entry["display_name"]
            )
            machine_model_settings = _resolve_machine_model_settings_from_roots(
                source_root=source_root,
                vendor_key=profile.vendor_key,
                printer_model=printer_model,
                asset_roots=native_bed_metadata_roots,
            )
            bed_model = _safe_bed_model_filename(
                str(
                    machine_model_settings.get("bed_model")
                    or profile.settings.get("bed_model")
                    or ""
                )
            )
            build_plate_settings = {
                **machine_model_settings,
                **profile.settings,
            }
            supported_build_plate_ids, default_build_plate_id = (
                resolve_machine_build_plates(
                    slicer_id=provider.slicer_id,
                    settings=build_plate_settings,
                    available_plate_ids=available_build_plate_ids,
                    source_version=source_version,
                    machine_profile_id=machine_id,
                )
            )
            machine_plate_resolutions.setdefault(machine_id, []).append(
                (supported_build_plate_ids, default_build_plate_id)
            )
            machine = machines.setdefault(
                machine_id,
                {
                    "machine_profile_id": machine_id,
                    "display_name": entry["display_name"],
                    "brand": entry["brand"],
                    "vendor_key": entry["vendor_key"],
                    "bed_width": entry["bed_width"],
                    "bed_depth": entry["bed_depth"],
                    "bed_height": entry["bed_height"],
                    "thumbnail": thumbnail or entry["thumbnail"],
                    "bed_model": bed_model,
                    "supported_build_plate_ids": supported_build_plate_ids,
                    "default_build_plate_id": default_build_plate_id,
                    "nozzles": [],
                },
            )
            machine["nozzles"].append(
                {
                    "device_profile_id": device_profile_id,
                    "nozzle_size": entry["nozzle_size"],
                    "source_profile_name": entry["source_profile_name"],
                    "revision": entry["revision"],
                    "supported": entry["supported"],
                }
            )

    for machine_id, resolutions in machine_plate_resolutions.items():
        supported_build_plate_ids, default_build_plate_id = (
            intersect_machine_build_plate_scopes(resolutions)
        )
        machines[machine_id]["supported_build_plate_ids"] = supported_build_plate_ids
        machines[machine_id]["default_build_plate_id"] = default_build_plate_id

    if source.application_metadata is not None:
        application_metadata = source.application_metadata
    elif provider.default_application_metadata is not None:
        application_metadata = provider.default_application_metadata
    else:
        application_metadata = (
            f"ElegooSlicer-{source_version}"
            if provider.slicer_id == "ElegooSlicer"
            else f"{provider.slicer_id}-{source_version}"
        )
    client_version = (
        source.client_version
        if source.client_version is not None
        else provider.default_client_version
    )
    slicer_payload = {
        "slicer_id": provider.slicer_id,
        "display_name": provider.display_name,
        "source_kind": "local_install",
        "source_version": source_version,
        "profile_format": provider.profile_format,
        "application_metadata": application_metadata,
        "sidecar_policy": provider.sidecar_policy,
        "build_plates": build_plates,
        "machines": list(machines.values()),
    }
    if client_version is not None:
        slicer_payload["client_version"] = client_version
    device_count = sum(len(machine["nozzles"]) for machine in machines.values())
    return slicer_payload, device_count


def _write_import_payload(
    *,
    output_root: Path,
    slicers: list[dict[str, Any]],
) -> None:
    seen_device_profile_ids: set[str] = set()
    for slicer in slicers:
        for machine in slicer.get("machines", []):
            for nozzle in machine.get("nozzles", []):
                device_profile_id = str(nozzle["device_profile_id"])
                if device_profile_id in seen_device_profile_ids:
                    raise ValueError(f"Duplicate machine registry device profile: {device_profile_id}")
                seen_device_profile_ids.add(device_profile_id)

    registry = {
        "schema_version": 1,
        "generated_at": "2026-06-09T00:00:00+08:00",
        "slicers": slicers,
    }
    _write_json(output_root / "registry.json", registry)


def run_import_sources(
    sources: list[ImportSource],
    *,
    output_root: Path,
    asset_search_roots: tuple[AssetRoot, ...] = (),
    bed_model_metadata_search_roots_by_slicer: dict[
        str, tuple[AssetRoot, ...]
    ] | None = None,
) -> ImportResult:
    if not sources:
        raise ValueError(
            "No machine profile sources were discovered; refusing to overwrite registry"
        )
    slicers: list[dict[str, Any]] = []
    device_count = 0
    source_asset_roots = tuple(
        (source.source_root, vendor_key)
        for source in sources
        for vendor_key in source.vendor_keys
    )
    all_asset_roots = (*source_asset_roots, *asset_search_roots)
    build_plate_source_roots = {
        source.slicer_id: source.source_root for source in sources
    }
    for source in sources:
        if bed_model_metadata_search_roots_by_slicer is None:
            bed_model_metadata_roots = all_asset_roots
        else:
            bed_model_metadata_roots = (
                *(
                    (source.source_root, vendor_key)
                    for vendor_key in source.vendor_keys
                ),
                *bed_model_metadata_search_roots_by_slicer.get(
                    source.slicer_id,
                    (),
                ),
            )
        slicer_payload, source_device_count = _collect_import_payload(
            source,
            output_root=output_root,
            asset_roots=all_asset_roots,
            bed_model_metadata_roots=bed_model_metadata_roots,
            build_plate_source_roots=build_plate_source_roots,
        )
        if source_device_count == 0:
            continue
        slicers.append(slicer_payload)
        device_count += source_device_count
    _write_import_payload(output_root=output_root, slicers=slicers)
    return ImportResult(device_count=device_count)


def main() -> int:
    parser = argparse.ArgumentParser(description="Import native slicer machine profiles into Lumina registry.")
    parser.add_argument("--slicer", required=True)
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--source-version", required=True)
    parser.add_argument("--application-metadata")
    parser.add_argument("--client-version")
    parser.add_argument("--vendor", action="append", dest="vendors")
    parser.add_argument("--machine-name")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    provider = get_provider(args.slicer)
    result = run_import(
        slicer_id=args.slicer,
        source_root=Path(args.source_root),
        source_version=args.source_version,
        vendor_keys=tuple(args.vendors or provider.default_vendor_keys),
        output_root=Path(args.output),
        machine_name=args.machine_name,
        application_metadata=args.application_metadata,
        client_version=args.client_version,
    )
    print(f"Imported {result.device_count} device profiles")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
