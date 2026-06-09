from __future__ import annotations

from tools.machine_adapter.emitter import build_device_registry_entry
from tools.machine_adapter.providers import get_provider
from tools.machine_adapter.resolver import ResolvedMachineProfile, SourceFile


def test_emitter_builds_slicer_scoped_device_profile_and_applies_lumina_overlay():
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

    entry, template = build_device_registry_entry(
        provider=get_provider("BambuStudio"),
        source_version="02.07.01.57",
        profile=native,
    )

    assert entry["device_profile_id"] == "BambuStudio:bbl:bambu-lab-h2d:0.4"
    assert entry["machine_profile_id"] == "BambuStudio:bbl:bambu-lab-h2d"
    assert entry["sidecar_policy"] == "bambu_studio"
    assert entry["bed_width"] == 350
    assert entry["bed_depth"] == 320
    assert template["printer_model"] == "Bambu Lab H2D"
    assert template["layer_height"] == "0.08"
