from __future__ import annotations

from pathlib import Path

from helpers_threemf_manifest import (
    cleanup_paths,
    expected_family_signature,
    export_fixture_3mf,
    extract_manifest,
    extract_project_subset,
    sample_manifest,
)


REFERENCE_CASES = [
    ("0.2 P1S.3mf", "bambu-p1s", "BambuStudio", "0.2"),
    ("Bambu P1S.3mf", "bambu-p1s", "BambuStudio", "0.4"),
    ("Orca P1S.3mf", "bambu-p1s", "OrcaSlicer", "0.4"),
    ("Elegoo slicer CC2.3mf", "elegoo-cc2", "ElegooSlicer", "0.4"),
    ("Snapmaker U1.3mf", "snapmaker-u1", "SnapmakerOrca", "0.4"),
    ("AnycubicSlicer.3mf", "anycubic-kobra-x", "AnycubicSlicerNext", "0.4"),
]


def test_reference_goldens_match_expected_family_metadata() -> None:
    failures: list[str] = []

    for sample_name, printer_id, slicer, nozzle_size in REFERENCE_CASES:
        output_path = export_fixture_3mf(
            printer_id=printer_id,
            slicer=slicer,
            nozzle_size=nozzle_size,
            case_name="full_palette",
        )
        try:
            generated = extract_manifest(output_path)
            sample = sample_manifest(sample_name)
            family = expected_family_signature(printer_id, slicer, nozzle_size)

            generated_root = generated["root_metadata"]  # type: ignore[index]
            sample_root = sample["root_metadata"]  # type: ignore[index]
            if generated_root.get("Application") != sample_root.get("Application"):
                failures.append(f"{sample_name}: application mismatch")
            if generated["slice_header"] != sample["slice_header"]:  # type: ignore[index]
                failures.append(f"{sample_name}: slice header mismatch")
            if generated_root.get("Application") != family["application"]:
                failures.append(f"{sample_name}: generated family application mismatch")

            generated_project = generated["project_settings"]  # type: ignore[index]
            sample_project = sample["project_settings"]  # type: ignore[index]
            for key in ("printer_settings_id", "printer_variant", "nozzle_diameter"):
                if generated_project.get(key) != sample_project.get(key):
                    failures.append(f"{sample_name}: project field '{key}' mismatch")

            if sample_name == "0.2 P1S.3mf":
                generated_subset = extract_project_subset(generated_project)
                sample_subset = extract_project_subset(sample_project)
                if generated_subset != sample_subset:
                    failures.append(f"{sample_name}: strict project subset mismatch")
        finally:
            cleanup_paths(Path(output_path))

    assert not failures, "\n".join(failures)
