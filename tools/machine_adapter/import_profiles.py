from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import sys
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.machine_adapter.emitter import build_device_registry_entry
from tools.machine_adapter.providers import get_provider
from tools.machine_adapter.resolver import resolve_machine_profiles


@dataclass(frozen=True)
class ImportResult:
    device_count: int


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


def run_import(
    *,
    slicer_id: str,
    source_root: Path,
    source_version: str,
    vendor_keys: tuple[str, ...],
    output_root: Path,
    machine_name: str | None = None,
) -> ImportResult:
    provider = get_provider(slicer_id)
    machines: dict[str, dict[str, Any]] = {}
    templates: list[tuple[str, dict[str, Any]]] = []

    for vendor_key in vendor_keys:
        for profile in resolve_machine_profiles(root=source_root, vendor_key=vendor_key):
            if not _matches_machine_name(profile.name, profile.settings, machine_name):
                continue
            entry, template = build_device_registry_entry(
                provider=provider,
                source_version=source_version,
                profile=profile,
            )
            machine_id = str(entry["machine_profile_id"])
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
                    "thumbnail": entry["thumbnail"],
                    "nozzles": [],
                },
            )
            machine["nozzles"].append(
                {
                    "device_profile_id": entry["device_profile_id"],
                    "nozzle_size": entry["nozzle_size"],
                    "source_profile_name": entry["source_profile_name"],
                    "template": entry["template"],
                    "revision": entry["revision"],
                    "supported": entry["supported"],
                }
            )
            templates.append((str(entry["template"]), template))

    registry = {
        "schema_version": 1,
        "generated_at": "2026-06-09T00:00:00+08:00",
        "slicers": [
            {
                "slicer_id": provider.slicer_id,
                "display_name": provider.display_name,
                "source_kind": "local_install",
                "source_version": source_version,
                "profile_format": provider.profile_format,
                "application_metadata": (
                    f"ElegooSlicer-{source_version}"
                    if provider.slicer_id == "ElegooSlicer"
                    else f"BambuStudio-{source_version}"
                ),
                "sidecar_policy": provider.sidecar_policy,
                "machines": list(machines.values()),
            }
        ],
    }
    _write_json(output_root / "registry.json", registry)
    for relative_template_path, template in templates:
        _write_json(output_root / relative_template_path, template)

    return ImportResult(device_count=sum(len(machine["nozzles"]) for machine in machines.values()))


def main() -> int:
    parser = argparse.ArgumentParser(description="Import native slicer machine profiles into Lumina registry.")
    parser.add_argument("--slicer", required=True)
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--source-version", required=True)
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
    )
    print(f"Imported {result.device_count} device profiles")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
