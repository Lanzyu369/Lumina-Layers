from __future__ import annotations

import importlib
from pathlib import Path

from helpers_threemf_manifest import (
    cleanup_paths,
    expected_family_signature,
    export_fixture_3mf,
    extract_manifest,
    extract_project_subset,
    list_printer_profiles,
    load_expected_template_direct,
    manifest_sidecar_flags,
    supported_printer_slicer_pairs,
)


def test_template_matrix_script_imports_expected_helpers() -> None:
    module = importlib.import_module("scripts.verify_3mf_template_matrix")

    assert callable(module.main)


def test_template_matrix_helper_exposes_expected_template_loader() -> None:
    template = load_expected_template_direct(
        printer_id="bambu-h2d",
        slicer="BambuStudio",
        nozzle_size="0.4",
    )

    assert template["printer_model"]
    assert template["layer_height"] == "0.08"


def test_3mf_template_matrix_matches_selected_template_and_family_rules() -> None:
    profile_map = {profile.id: profile for profile in list_printer_profiles()}
    failures: list[str] = []

    for printer_id, slicer in supported_printer_slicer_pairs():
        profile = profile_map[printer_id]
        for nozzle_size in profile.supported_nozzle_sizes:
            template = load_expected_template_direct(
                printer_id=printer_id,
                slicer=slicer,
                nozzle_size=nozzle_size,
            )
            expected_subset = extract_project_subset(template)
            family = expected_family_signature(printer_id, slicer, nozzle_size)

            for case_name in ("full_palette", "sparse_palette"):
                output_path = export_fixture_3mf(
                    printer_id=printer_id,
                    slicer=slicer,
                    nozzle_size=nozzle_size,
                    case_name=case_name,
                )
                try:
                    manifest = extract_manifest(output_path)
                    project_subset = extract_project_subset(manifest["project_settings"])  # type: ignore[index]
                    if project_subset != expected_subset:
                        failures.append(
                            f"{printer_id}/{slicer}/{nozzle_size}/{case_name}: project subset mismatch"
                        )

                    root_metadata = manifest["root_metadata"]  # type: ignore[index]
                    if root_metadata.get("Application") != family["application"]:
                        failures.append(
                            f"{printer_id}/{slicer}/{nozzle_size}/{case_name}: application mismatch"
                        )

                    slice_header = manifest["slice_header"]  # type: ignore[index]
                    if slice_header != family["slice_header"]:
                        failures.append(
                            f"{printer_id}/{slicer}/{nozzle_size}/{case_name}: slice header mismatch"
                        )

                    sidecars = manifest_sidecar_flags(manifest["entries"])  # type: ignore[arg-type]
                    if sidecars["has_filament_sequence"] != family["requires_filament_sequence"]:
                        failures.append(
                            f"{printer_id}/{slicer}/{nozzle_size}/{case_name}: filament_sequence sidecar mismatch"
                        )
                    if sidecars["has_cut_information"] != family["requires_cut_information"]:
                        failures.append(
                            f"{printer_id}/{slicer}/{nozzle_size}/{case_name}: cut_information sidecar mismatch"
                        )
                    if sidecars["has_custom_gcode"] != family["requires_custom_gcode"]:
                        failures.append(
                            f"{printer_id}/{slicer}/{nozzle_size}/{case_name}: custom_gcode sidecar mismatch"
                        )
                finally:
                    cleanup_paths(Path(output_path))

    assert not failures, "\n".join(failures[:20])


def test_printer_profile_templates_use_arachne_wall_generator() -> None:
    failures: list[str] = []
    profile_map = {profile.id: profile for profile in list_printer_profiles()}

    for printer_id, slicer in supported_printer_slicer_pairs():
        profile = profile_map[printer_id]
        for nozzle_size in profile.supported_nozzle_sizes:
            template = load_expected_template_direct(
                printer_id=printer_id,
                slicer=slicer,
                nozzle_size=nozzle_size,
            )
            if template.get("wall_generator") != "arachne":
                failures.append(
                    f"{printer_id}/{slicer}/{nozzle_size}: "
                    f"wall_generator={template.get('wall_generator')!r}"
                )
                continue

            different_settings = template.get("different_settings_to_system")
            first_diff_group = (
                str(different_settings[0])
                if isinstance(different_settings, list) and different_settings
                else ""
            )
            if "wall_generator" not in first_diff_group.split(";"):
                failures.append(
                    f"{printer_id}/{slicer}/{nozzle_size}: "
                    "different_settings_to_system missing wall_generator"
                )

    assert not failures, "\n".join(failures[:20])
