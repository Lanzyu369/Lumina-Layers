from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from tools.machine_adapter.build_plates import (
    copy_native_build_plate_assets,
    intersect_machine_build_plate_scopes,
    resolve_machine_build_plates,
)
from tools.machine_adapter.resolver import (
    resolve_machine_model_settings,
    resolve_machine_profiles,
)


def _resolve_machine_plate_scope(
    *,
    source_root: Path,
    slicer_id: str,
    source_version: str,
    machine: dict[str, Any],
    plate_ids: set[str],
) -> tuple[list[str], str]:
    nozzle_profiles = {
        profile.name: profile
        for profile in resolve_machine_profiles(
            root=source_root,
            vendor_key=str(machine.get("vendor_key") or ""),
        )
    }
    model_settings = resolve_machine_model_settings(
        root=source_root,
        vendor_key=str(machine.get("vendor_key") or ""),
        printer_model=str(machine.get("display_name") or ""),
    )
    resolutions = []
    for nozzle in machine.get("nozzles") or []:
        source_name = str(nozzle.get("source_profile_name") or "")
        profile = nozzle_profiles.get(source_name)
        if profile is None:
            raise ValueError(
                "Native source profile is missing while resolving build plates: "
                f"{slicer_id}/{source_name}"
            )
        resolutions.append(resolve_machine_build_plates(
            slicer_id=slicer_id,
            settings={**model_settings, **profile.settings},
            available_plate_ids=plate_ids,
            source_version=source_version,
            machine_profile_id=str(machine.get("machine_profile_id") or ""),
        ))
    return intersect_machine_build_plate_scopes(resolutions)


def update_registry_build_plates(
    *,
    registry_root: Path,
    source_roots: dict[str, Path],
) -> None:
    """Refresh neutral selector artwork without touching native project sources.

    刷新中性打印板选择器图片，不修改原生项目来源。
    """

    registry_path = registry_root / "registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    for slicer in registry["slicers"]:
        slicer_id = str(slicer["slicer_id"])
        source_root = source_roots.get(slicer_id)
        build_plates = copy_native_build_plate_assets(
            slicer_id=slicer_id,
            source_root=source_root or registry_root,
            source_version=str(slicer["source_version"]),
            output_root=registry_root,
            source_roots=source_roots,
        )
        if not build_plates:
            continue
        slicer["build_plates"] = build_plates
        if source_root is None:
            continue
        plate_ids = {str(plate["id"]) for plate in build_plates}
        for machine in slicer["machines"]:
            supported, default = _resolve_machine_plate_scope(
                source_root=source_root,
                slicer_id=slicer_id,
                source_version=str(slicer["source_version"]),
                machine=machine,
                plate_ids=plate_ids,
            )
            machine["supported_build_plate_ids"] = supported
            machine["default_build_plate_id"] = default
    registry_path.write_text(
        json.dumps(registry, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh bundled native build plates.")
    parser.add_argument("--registry-root", required=True, type=Path)
    parser.add_argument(
        "--source",
        action="append",
        default=[],
        metavar="SLICER_ID=PROFILES_ROOT",
    )
    args = parser.parse_args()
    sources: dict[str, Path] = {}
    for raw in args.source:
        slicer_id, separator, path = raw.partition("=")
        if not separator or not slicer_id or not path:
            parser.error(f"Invalid --source value: {raw!r}")
        sources[slicer_id] = Path(path)
    update_registry_build_plates(
        registry_root=args.registry_root,
        source_roots=sources,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
