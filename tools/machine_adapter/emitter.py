from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from config import format_native_nozzle_size, normalize_nozzle_size
from core.machine_process_overlay import apply_lumina_process_overlay
from tools.machine_adapter.providers import MachineAdapterProvider
from tools.machine_adapter.resolver import ResolvedMachineProfile

_BRAND_BY_VENDOR_KEY = {
    "BBL": "Bambu Lab",
    "Bambu": "Bambu Lab",
    "ELEGOO": "Elegoo",
    "Elegoo": "Elegoo",
    "Anycubic": "Anycubic",
    "Flashforge": "Flashforge",
    "Q Series": "QIDI",
    "X 4 Series": "QIDI",
    "X 5 Series": "QIDI",
}

_VENDOR_SLUG_BY_VENDOR_KEY = {
    "Q Series": "qidi",
    "X 4 Series": "qidi",
    "X 5 Series": "qidi",
}


def _slug(value: str) -> str:
    lowered = value.strip().lower()
    return re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")


def _safe_path_segment(value: str) -> str:
    segment = value.strip()
    if (
        not segment
        or segment in {".", ".."}
        or ".." in segment
        or "/" in segment
        or "\\" in segment
    ):
        raise ValueError(f"Unsafe machine registry path segment: {value!r}")
    return segment


def _first_nozzle(settings: dict[str, Any]) -> str:
    values = settings.get("nozzle_diameter") or [settings.get("printer_variant") or "0.4"]
    if isinstance(values, list):
        normalized = format_native_nozzle_size(values[0])
    else:
        normalized = format_native_nozzle_size(values)
    if normalized is None:
        normalized = format_native_nozzle_size(settings.get("printer_variant"))
    if normalized is None:
        normalized = normalize_nozzle_size(settings.get("printer_variant"))
    return normalized or "0.4"


def _point_to_xy(value: str) -> tuple[float, float] | None:
    parts = str(value).split("x", maxsplit=1)
    if len(parts) != 2:
        return None
    try:
        return float(parts[0]), float(parts[1])
    except ValueError:
        return None


def _bed_size(settings: dict[str, Any]) -> tuple[int, int]:
    area = settings.get("printable_area")
    if isinstance(area, list):
        points = [_point_to_xy(str(item)) for item in area]
        numeric = [point for point in points if point is not None]
        if numeric:
            xs = [point[0] for point in numeric]
            ys = [point[1] for point in numeric]
            width = int(round(max(xs) - min(xs)))
            depth = int(round(max(ys) - min(ys)))
            if width > 0 and depth > 0:
                return width, depth
    return 0, 0


def _bed_height(settings: dict[str, Any]) -> int:
    value = settings.get("printable_height") or "0"
    if isinstance(value, list):
        value = value[0] if value else "0"
    return int(float(str(value)))


def _brand(settings: dict[str, Any], vendor_key: str, printer_model: str) -> str:
    explicit = str(settings.get("brand") or "").strip()
    if explicit:
        return explicit
    mapped = _BRAND_BY_VENDOR_KEY.get(str(vendor_key).strip())
    if mapped:
        return mapped
    return printer_model.split(" ")[0] or vendor_key


def _content_revision(settings: dict[str, Any], source_hashes: list[str], source_version: str) -> str:
    digest = hashlib.sha256()
    digest.update(
        json.dumps(settings, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    digest.update(source_version.encode("utf-8"))
    for value in sorted(source_hashes):
        digest.update(value.encode("utf-8"))
    return f"sha256:{digest.hexdigest()}"


def _application_metadata(provider: MachineAdapterProvider, source_version: str) -> str:
    if provider.default_application_metadata is not None:
        return provider.default_application_metadata
    if provider.slicer_id == "ElegooSlicer":
        return f"ElegooSlicer-{source_version}"
    return f"BambuStudio-{source_version}"


def _project_format_version(provider: MachineAdapterProvider, source_version: str) -> str:
    """Return the project schema version written inside exported 3MF files."""

    application = _application_metadata(provider, source_version)
    if application.startswith("BambuStudio-"):
        return application.removeprefix("BambuStudio-")
    return source_version


def build_device_registry_entry(
    *,
    provider: MachineAdapterProvider,
    source_version: str,
    profile: ResolvedMachineProfile,
) -> tuple[dict[str, Any], dict[str, Any]]:
    settings = dict(profile.settings)
    safe_source_version = _safe_path_segment(source_version)
    printer_model = str(settings.get("printer_model") or profile.name)
    nozzle = _first_nozzle(settings)
    vendor_slug = _VENDOR_SLUG_BY_VENDOR_KEY.get(
        profile.vendor_key,
        _slug(profile.vendor_key),
    )
    machine_slug = _slug(printer_model)
    machine_profile_id = f"{provider.slicer_id}:{vendor_slug}:{machine_slug}"
    device_profile_id = f"{machine_profile_id}:{nozzle}"
    source_hashes = [item.sha256 for item in profile.source_files]
    template = apply_lumina_process_overlay(
        settings,
        source_profile_name=profile.name,
        slicer_id=provider.slicer_id,
    )
    if provider.slicer_id in {"FlashStudio", "QIDIStudio"}:
        # Vendor profile bundles and saved-project schemas are independent
        # version contracts. Preserve the observed native project version.
        template["version"] = _project_format_version(provider, safe_source_version)
    if provider.slicer_id == "QIDIStudio":
        template["printer_variant"] = nozzle
        template.setdefault("printer_extruder_id", ["1"])
    revision = _content_revision(template, source_hashes, safe_source_version)
    bed_width, bed_depth = _bed_size(settings)

    entry = {
        "device_profile_id": device_profile_id,
        "machine_profile_id": machine_profile_id,
        "slicer_id": provider.slicer_id,
        "display_name": printer_model,
        "brand": _brand(settings, profile.vendor_key, printer_model),
        "vendor_key": profile.vendor_key,
        "bed_width": bed_width,
        "bed_depth": bed_depth,
        "bed_height": _bed_height(settings),
        "thumbnail": "",
        "nozzle_size": nozzle,
        "source_profile_name": profile.name,
        "template": (
            f"slicers/{provider.slicer_id}/{safe_source_version}/metadata_templates/"
            f"{machine_slug}_{nozzle.replace('.', '_')}.json"
        ),
        "revision": revision,
        "supported": True,
        "application_metadata": _application_metadata(provider, safe_source_version),
        "sidecar_policy": provider.sidecar_policy,
        "source_hashes": source_hashes,
    }
    return entry, template
