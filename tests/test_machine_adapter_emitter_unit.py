from __future__ import annotations

from tools.machine_adapter.emitter import build_device_registry_entry
from tools.machine_adapter.providers import get_provider
from tools.machine_adapter.resolver import ResolvedMachineProfile, SourceFile


def test_emitter_builds_slicer_scoped_device_profile():
    native = ResolvedMachineProfile(
        name="Bambu Lab H2D 0.4 nozzle",
        vendor_key="BBL",
        settings={
            "printer_model": "Bambu Lab H2D",
            "printer_variant": "0.4",
            "nozzle_diameter": ["0.4", "0.4"],
            "printable_area": ["0x0", "350x0", "350x320", "0x320"],
            "printable_height": "325",
            "layer_height": "0.20",
        },
        source_files=(SourceFile(path="BBL/machine/H2D.json", sha256="abc"),),
    )

    entry = build_device_registry_entry(
        provider=get_provider("BambuStudio"),
        source_version="02.07.01.57",
        profile=native,
    )

    assert entry["device_profile_id"] == "BambuStudio:bbl:bambu-lab-h2d:0.4"
    assert entry["machine_profile_id"] == "BambuStudio:bbl:bambu-lab-h2d"
    assert entry["brand"] == "Bambu Lab"
    assert entry["bed_width"] == 350
    assert entry["bed_depth"] == 320


def test_emitter_normalizes_native_nozzle_variant_for_stable_profile_id():
    native = ResolvedMachineProfile(
        name="Bambu Lab P1S 0.40mm nozzle",
        vendor_key="BBL",
        settings={
            "printer_model": "Bambu Lab P1S",
            "printer_variant": "0.40mm",
            "nozzle_diameter": ["0.40mm"],
            "printable_area": ["0x0", "256x0", "256x256", "0x256"],
            "printable_height": "256",
        },
        source_files=(SourceFile(path="BBL/machine/P1S.json", sha256="abc"),),
    )

    entry = build_device_registry_entry(
        provider=get_provider("OrcaSlicer"),
        source_version="2.3.1",
        profile=native,
    )

    assert entry["device_profile_id"] == "OrcaSlicer:bbl:bambu-lab-p1s:0.4"
    assert entry["nozzle_size"] == "0.4"


def test_emitter_preserves_native_quarter_mm_nozzle_variant():
    native = ResolvedMachineProfile(
        name="Anycubic Kobra X 0.25 nozzle",
        vendor_key="Anycubic",
        settings={
            "printer_model": "Anycubic Kobra X",
            "printer_variant": "0.25",
            "nozzle_diameter": ["0.25"],
            "printable_area": ["0x0", "260x0", "260x260", "0x260"],
            "printable_height": "260",
        },
        source_files=(SourceFile(path="Anycubic/machine/Kobra X.json", sha256="abc"),),
    )

    entry = build_device_registry_entry(
        provider=get_provider("AnycubicSlicerNext"),
        source_version="1.3.2605.22",
        profile=native,
    )

    assert entry["device_profile_id"] == "AnycubicSlicerNext:anycubic:anycubic-kobra-x:0.25"
    assert entry["nozzle_size"] == "0.25"


def test_emitter_accepts_list_shaped_printable_height_from_native_profiles():
    native = ResolvedMachineProfile(
        name="Elegoo OrangeStorm Giga 0.4 nozzle",
        vendor_key="Elegoo",
        settings={
            "printer_model": "Elegoo OrangeStorm Giga",
            "printer_variant": "0.4",
            "nozzle_diameter": ["0.4"],
            "printable_area": ["0x0", "800x0", "800x800", "0x800"],
            "printable_height": ["1010"],
        },
        source_files=(SourceFile(path="Elegoo/machine/EOSGIGA.json", sha256="abc"),),
    )

    entry = build_device_registry_entry(
        provider=get_provider("ElegooSlicer"),
        source_version="01.05.00.07",
        profile=native,
    )

    assert entry["bed_height"] == 1010


def test_emitter_revision_uses_canonical_json_and_source_version():
    base_settings = {
        "printer_model": "Bambu Lab P1S",
        "printer_variant": "0.4",
        "nozzle_diameter": ["0.4"],
        "printable_height": "256",
    }
    reordered_settings = {
        "nozzle_diameter": ["0.4"],
        "printable_height": "256",
        "printer_variant": "0.4",
        "printer_model": "Bambu Lab P1S",
    }

    first = build_device_registry_entry(
        provider=get_provider("BambuStudio"),
        source_version="02.07.01.57",
        profile=ResolvedMachineProfile(
            name="Bambu Lab P1S 0.4 nozzle",
            vendor_key="BBL",
            settings=base_settings,
            source_files=(SourceFile(path="BBL/machine/P1S.json", sha256="abc"),),
        ),
    )
    second = build_device_registry_entry(
        provider=get_provider("BambuStudio"),
        source_version="02.07.01.57",
        profile=ResolvedMachineProfile(
            name="Bambu Lab P1S 0.4 nozzle",
            vendor_key="BBL",
            settings=reordered_settings,
            source_files=(SourceFile(path="BBL/machine/P1S.json", sha256="abc"),),
        ),
    )
    third = build_device_registry_entry(
        provider=get_provider("BambuStudio"),
        source_version="02.07.02.00",
        profile=ResolvedMachineProfile(
            name="Bambu Lab P1S 0.4 nozzle",
            vendor_key="BBL",
            settings=base_settings,
            source_files=(SourceFile(path="BBL/machine/P1S.json", sha256="abc"),),
        ),
    )

    assert first["revision"] == second["revision"]
    assert first["revision"] != third["revision"]
