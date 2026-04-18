from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from helpers_threemf_manifest import (  # noqa: E402
    cleanup_paths,
    expected_family_signature,
    export_fixture_3mf,
    extract_manifest,
    extract_project_subset,
    list_printer_profiles,
    load_printer_template,
    manifest_sidecar_flags,
    supported_printer_slicer_pairs,
)


def main() -> int:
    failures: list[str] = []
    profile_map = {profile.id: profile for profile in list_printer_profiles()}

    for printer_id, slicer in supported_printer_slicer_pairs():
        profile = profile_map[printer_id]
        for nozzle_size in profile.supported_nozzle_sizes:
            template = load_printer_template(printer_id, slicer=slicer, nozzle_size=nozzle_size)
            expected_subset = extract_project_subset(template)
            family = expected_family_signature(slicer, nozzle_size)

            for case_name in ("full_palette", "sparse_palette"):
                output_path = export_fixture_3mf(
                    printer_id=printer_id,
                    slicer=slicer,
                    nozzle_size=nozzle_size,
                    case_name=case_name,
                )
                try:
                    manifest = extract_manifest(output_path)
                    if extract_project_subset(manifest["project_settings"]) != expected_subset:  # type: ignore[index]
                        failures.append(f"{printer_id}/{slicer}/{nozzle_size}/{case_name}: project subset mismatch")
                    root_metadata = manifest["root_metadata"]  # type: ignore[index]
                    if root_metadata.get("Application") != family["application"]:
                        failures.append(f"{printer_id}/{slicer}/{nozzle_size}/{case_name}: application mismatch")
                    if manifest["slice_header"] != family["slice_header"]:  # type: ignore[index]
                        failures.append(f"{printer_id}/{slicer}/{nozzle_size}/{case_name}: slice header mismatch")
                    sidecars = manifest_sidecar_flags(manifest["entries"])  # type: ignore[arg-type]
                    if sidecars["has_filament_sequence"] != family["requires_filament_sequence"]:
                        failures.append(f"{printer_id}/{slicer}/{nozzle_size}/{case_name}: filament_sequence mismatch")
                    if sidecars["has_cut_information"] != family["requires_cut_information"]:
                        failures.append(f"{printer_id}/{slicer}/{nozzle_size}/{case_name}: cut_information mismatch")
                    if sidecars["has_custom_gcode"] != family["requires_custom_gcode"]:
                        failures.append(f"{printer_id}/{slicer}/{nozzle_size}/{case_name}: custom_gcode mismatch")
                finally:
                    cleanup_paths(Path(output_path))

    if failures:
        print("3MF verification failed:")
        for failure in failures[:50]:
            print(f" - {failure}")
        return 1

    print("3MF verification passed for all printer/slicer/nozzle/case combinations.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
