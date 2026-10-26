from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.machine_registry import (
    load_machine_registry,
    resolve_installed_bed_model,
    resolve_machine_registry_root,
)


def test_machine_registry_root_resolution_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    explicit_root = tmp_path / "explicit-registry"

    monkeypatch.setenv("LUMINA_MACHINE_REGISTRY_DIR", str(explicit_root))
    assert resolve_machine_registry_root() == explicit_root.resolve()

    monkeypatch.delenv("LUMINA_MACHINE_REGISTRY_DIR")
    assert resolve_machine_registry_root() == (
        Path(__file__).resolve().parents[1] / "machine_registry"
    )


def test_runtime_machine_registry_consumers_share_configured_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from api.export_device_validation import _machine_registry_path
    from api.routers.system import _machine_registry_root
    from utils.fatcat_metadata import select_metadata_target

    expected = (tmp_path / "machine_registry").resolve()
    unrelated_cwd = tmp_path / "cwd"
    unrelated_cwd.mkdir()
    monkeypatch.chdir(unrelated_cwd)
    monkeypatch.setenv("LUMINA_MACHINE_REGISTRY_DIR", str(expected))

    assert resolve_machine_registry_root() == expected
    assert _machine_registry_root() == expected
    assert _machine_registry_path() == expected / "registry.json"
    with pytest.raises(FileNotFoundError) as error:
        select_metadata_target(
            slicer="BambuStudio",
            printer_id="bambu-h2d",
            nozzle_size="0.4",
            device_profile_id=None,
            build_plate_id=None,
        )
    assert str(error.value) == f"Machine registry not found: {expected / 'registry.json'}"


def test_load_machine_registry_indexes_device_profiles(tmp_path):
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generated_at": "2026-06-09T00:00:00+08:00",
                "slicers": [
                    {
                        "slicer_id": "BambuStudio",
                        "display_name": "Bambu Studio",
                        "source_kind": "local_install",
                        "source_version": "02.07.01.57",
                        "profile_format": "bambu_orca",
                        "build_plates": [
                            {
                                "id": "textured-pei",
                                "display_name": "Textured PEI Plate",
                                "display_name_zh": "纹理PEI打印板",
                                "image": (
                                    "slicers/BambuStudio/02.07.01.57/"
                                    "assets/build-plates/bed_pei.png"
                                ),
                                "source_path": "resources/images/bed_pei.png",
                                "source_version": "02.07.01.57",
                                "revision": "sha256:plate",
                            }
                        ],
                        "machines": [
                            {
                                "machine_profile_id": "BambuStudio:bbl:bambu-lab-h2d",
                                "display_name": "Bambu Lab H2D",
                                "brand": "Bambu Lab",
                                "vendor_key": "BBL",
                                "bed_width": 350,
                                "bed_depth": 320,
                                "bed_height": 325,
                                "thumbnail": "slicers/BambuStudio/02.07.01.57/assets/h2d.png",
                                "bed_model": "bbl-3dp-H2D.stl",
                                "supported_build_plate_ids": ["textured-pei"],
                                "default_build_plate_id": "textured-pei",
                                "nozzles": [
                                    {
                                        "device_profile_id": "BambuStudio:bbl:bambu-lab-h2d:0.4",
                                        "nozzle_size": "0.4",
                                        "source_profile_name": "Bambu Lab H2D 0.4 nozzle",
                                        "revision": "sha256:abc",
                                        "supported": True,
                                    }
                                ],
                            }
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    registry = load_machine_registry(registry_path)

    profile = registry.get_device_profile("BambuStudio:bbl:bambu-lab-h2d:0.4")
    assert profile.slicer_id == "BambuStudio"
    assert profile.machine_profile_id == "BambuStudio:bbl:bambu-lab-h2d"
    assert profile.nozzle_size == "0.4"
    assert profile.bed_model == "bbl-3dp-H2D.stl"
    assert profile.default_build_plate_id == "textured-pei"
    assert [plate.id for plate in profile.build_plates] == ["textured-pei"]
    assert profile.build_plates[0].image.endswith("build-plates/bed_pei.png")
    assert profile.build_plates[0].display_name_zh == "纹理PEI打印板"

    resolved = registry.resolve_build_plate(profile.device_profile_id, "textured-pei")
    assert resolved.id == "textured-pei"
    assert resolved.display_name == "Textured PEI Plate"
    assert resolved.image == profile.build_plates[0].image


def test_resolve_installed_bed_model_stays_inside_the_matching_slicer_bundle(
    tmp_path: Path,
) -> None:
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generated_at": "2026-09-03T00:00:00+08:00",
                "slicers": [
                    {
                        "slicer_id": "OrcaSlicer",
                        "display_name": "OrcaSlicer",
                        "source_version": "02.04.00.00",
                        "build_plates": [],
                        "machines": [
                            {
                                "machine_profile_id": "OrcaSlicer:bbl:a1-mini",
                                "display_name": "Bambu Lab A1 mini",
                                "brand": "Bambu Lab",
                                "vendor_key": "BBL",
                                "bed_width": 180,
                                "bed_depth": 180,
                                "bed_height": 180,
                                "thumbnail": "",
                                "bed_model": "bbl-3dp-A1M.stl",
                                "supported_build_plate_ids": [],
                                "default_build_plate_id": "",
                                "nozzles": [
                                    {
                                        "device_profile_id": "OrcaSlicer:bbl:a1-mini:0.4",
                                        "nozzle_size": "0.4",
                                        "source_profile_name": "A1 mini 0.4 nozzle",
                                        "revision": "sha256:test",
                                        "supported": True,
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    profile = load_machine_registry(registry_path).get_device_profile(
        "OrcaSlicer:bbl:a1-mini:0.4"
    )
    orca_app = tmp_path / "OrcaSlicer.app"
    orca_model = (
        orca_app
        / "Contents"
        / "Resources"
        / "profiles"
        / "BBL"
        / "bbl-3dp-A1M.stl"
    )
    orca_model.parent.mkdir(parents=True)
    orca_model.write_bytes(b"orca-bed")
    bambu_app = tmp_path / "BambuStudio.app"
    bambu_model = (
        bambu_app
        / "Contents"
        / "Resources"
        / "profiles"
        / "BBL"
        / "bbl-3dp-A1M.stl"
    )
    bambu_model.parent.mkdir(parents=True)
    bambu_model.write_bytes(b"bambu-bed")

    resolved = resolve_installed_bed_model(
        profile,
        detected_slicers=[
            {"id": "bambu_studio", "exe_path": str(bambu_app)},
            {"id": "orca_slicer", "exe_path": str(orca_app)},
        ],
    )

    assert resolved == orca_model.resolve()
    assert resolved.read_bytes() == b"orca-bed"


@pytest.mark.parametrize(
    ("vendor_key", "bed_model"),
    [
        ("BBL", "../outside.stl"),
        ("BBL", r"..\outside.stl"),
        ("BBL", r"C:\outside.stl"),
        ("../BBL", "bed.stl"),
        (r"..\BBL", "bed.stl"),
    ],
)
def test_resolve_installed_bed_model_rejects_registry_path_segments(
    vendor_key: str,
    bed_model: str,
) -> None:
    profile = type(
        "Profile",
        (),
        {
            "slicer_id": "OrcaSlicer",
            "vendor_key": vendor_key,
            "bed_model": bed_model,
        },
    )()

    assert resolve_installed_bed_model(profile, detected_slicers=[]) is None


def test_resolve_installed_bed_model_rejects_vendor_symlink_escape(
    tmp_path: Path,
) -> None:
    app_path = tmp_path / "OrcaSlicer.app"
    profile_root = app_path / "Contents" / "Resources" / "profiles"
    profile_root.mkdir(parents=True)
    outside_vendor = tmp_path / "outside" / "BBL"
    outside_vendor.mkdir(parents=True)
    (outside_vendor / "bed.stl").write_bytes(b"outside-bed")
    try:
        (profile_root / "BBL").symlink_to(outside_vendor, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"Directory symlinks are unavailable: {exc}")

    profile = type(
        "Profile",
        (),
        {
            "slicer_id": "OrcaSlicer",
            "vendor_key": "BBL",
            "bed_model": "bed.stl",
        },
    )()

    resolved = resolve_installed_bed_model(
        profile,
        detected_slicers=[
            {"id": "orca_slicer", "exe_path": str(app_path)},
        ],
    )

    assert resolved is None


def test_resolve_installed_bed_model_rejects_profile_root_symlink_escape(
    tmp_path: Path,
) -> None:
    app_path = tmp_path / "OrcaSlicer.app"
    resources_root = app_path / "Contents" / "Resources"
    resources_root.mkdir(parents=True)
    outside_profiles = tmp_path / "outside" / "profiles"
    outside_model = outside_profiles / "BBL" / "bed.stl"
    outside_model.parent.mkdir(parents=True)
    outside_model.write_bytes(b"outside-bed")
    try:
        (resources_root / "profiles").symlink_to(
            outside_profiles,
            target_is_directory=True,
        )
    except OSError as exc:
        pytest.skip(f"Directory symlinks are unavailable: {exc}")

    profile = type(
        "Profile",
        (),
        {
            "slicer_id": "OrcaSlicer",
            "vendor_key": "BBL",
            "bed_model": "bed.stl",
        },
    )()

    resolved = resolve_installed_bed_model(
        profile,
        detected_slicers=[
            {"id": "orca_slicer", "exe_path": str(app_path)},
        ],
    )

    assert resolved is None


def test_load_machine_registry_rejects_duplicate_build_plate_ids(tmp_path):
    registry_path = tmp_path / "registry.json"
    plate = {
        "id": "textured-pei",
        "display_name": "Textured PEI Plate",
        "image": "assets/bed_pei.png",
        "source_path": "resources/images/bed_pei.png",
        "source_version": "2.4.0",
        "revision": "sha256:plate",
    }
    registry_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "generated_at": "2026-08-14T00:00:00+08:00",
                "slicers": [
                    {
                        "slicer_id": "OrcaSlicer",
                        "display_name": "OrcaSlicer",
                        "source_version": "02.04.00.00",
                        "build_plates": [plate, dict(plate)],
                        "machines": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Duplicate machine registry build plate"):
        load_machine_registry(registry_path)


def test_load_machine_registry_rejects_unknown_machine_build_plate_reference(tmp_path):
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "generated_at": "2026-08-14T00:00:00+08:00",
                "slicers": [
                    {
                        "slicer_id": "BambuStudio",
                        "display_name": "Bambu Studio",
                        "source_version": "02.07.01.57",
                        "build_plates": [],
                        "machines": [
                            {
                                "machine_profile_id": "BambuStudio:bbl:h2d",
                                "display_name": "Bambu Lab H2D",
                                "brand": "Bambu Lab",
                                "vendor_key": "BBL",
                                "bed_width": 350,
                                "bed_depth": 320,
                                "bed_height": 325,
                                "supported_build_plate_ids": ["missing"],
                                "default_build_plate_id": "missing",
                                "nozzles": [],
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Unknown machine registry build plate"):
        load_machine_registry(registry_path)


def test_load_machine_registry_rejects_duplicate_device_profile_ids(tmp_path):
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generated_at": "2026-06-09T00:00:00+08:00",
                "slicers": [
                    {
                        "slicer_id": "BambuStudio",
                        "display_name": "Bambu Studio",
                        "source_kind": "local_install",
                        "source_version": "02.07.01.57",
                        "profile_format": "bambu_orca",
                        "machines": [
                            {
                                "machine_profile_id": "BambuStudio:bbl:bambu-lab-h2d",
                                "display_name": "Bambu Lab H2D",
                                "brand": "Bambu Lab",
                                "vendor_key": "BBL",
                                "bed_width": 350,
                                "bed_depth": 320,
                                "bed_height": 325,
                                "thumbnail": "",
                                "nozzles": [
                                    {
                                        "device_profile_id": "duplicate",
                                        "nozzle_size": "0.4",
                                        "source_profile_name": "A",
                                        "revision": "sha256:a",
                                        "supported": True,
                                    },
                                    {
                                        "device_profile_id": "duplicate",
                                        "nozzle_size": "0.4",
                                        "source_profile_name": "B",
                                        "revision": "sha256:b",
                                        "supported": True,
                                    },
                                ],
                            }
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Duplicate machine registry device profile"):
        load_machine_registry(registry_path)
