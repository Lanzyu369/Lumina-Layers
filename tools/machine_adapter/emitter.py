from __future__ import annotations

import hashlib
import re
from typing import Any

from core.machine_process_overlay import apply_lumina_process_overlay
from tools.machine_adapter.providers import MachineAdapterProvider
from tools.machine_adapter.resolver import ResolvedMachineProfile


def _slug(value: str) -> str:
    lowered = value.strip().lower()
    return re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")


def _first_nozzle(settings: dict[str, Any]) -> str:
    values = settings.get("nozzle_diameter") or [settings.get("printer_variant") or "0.4"]
    if isinstance(values, list):
        return str(values[0])
    return str(values)


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


def _content_revision(settings: dict[str, Any], source_hashes: list[str]) -> str:
    digest = hashlib.sha256()
    digest.update(repr(sorted(settings.items(), key=lambda item: item[0])).encode("utf-8"))
    for value in sorted(source_hashes):
        digest.update(value.encode("utf-8"))
    return f"sha256:{digest.hexdigest()}"


def _application_metadata(provider: MachineAdapterProvider, source_version: str) -> str:
    if provider.slicer_id == "ElegooSlicer":
        return f"ElegooSlicer-{source_version}"
    return f"BambuStudio-{source_version}"


def build_device_registry_entry(
    *,
    provider: MachineAdapterProvider,
    source_version: str,
    profile: ResolvedMachineProfile,
) -> tuple[dict[str, Any], dict[str, Any]]:
    settings = dict(profile.settings)
    printer_model = str(settings.get("printer_model") or profile.name)
    nozzle = _first_nozzle(settings)
    vendor_slug = _slug(profile.vendor_key)
    machine_slug = _slug(printer_model)
    machine_profile_id = f"{provider.slicer_id}:{vendor_slug}:{machine_slug}"
    device_profile_id = f"{machine_profile_id}:{nozzle}"
    source_hashes = [item.sha256 for item in profile.source_files]
    template = apply_lumina_process_overlay(settings, source_profile_name=profile.name)
    revision = _content_revision(template, source_hashes)
    bed_width, bed_depth = _bed_size(settings)

    entry = {
        "device_profile_id": device_profile_id,
        "machine_profile_id": machine_profile_id,
        "slicer_id": provider.slicer_id,
        "display_name": printer_model,
        "brand": str(settings.get("brand") or printer_model.split(" ")[0] or profile.vendor_key),
        "vendor_key": profile.vendor_key,
        "bed_width": bed_width,
        "bed_depth": bed_depth,
        "bed_height": int(float(str(settings.get("printable_height") or "0"))),
        "thumbnail": "",
        "nozzle_size": nozzle,
        "source_profile_name": profile.name,
        "template": (
            f"slicers/{provider.slicer_id}/{source_version}/metadata_templates/"
            f"{machine_slug}_{nozzle.replace('.', '_')}.json"
        ),
        "revision": revision,
        "supported": True,
        "application_metadata": _application_metadata(provider, source_version),
        "sidecar_policy": provider.sidecar_policy,
        "source_hashes": source_hashes,
    }
    return entry, template
