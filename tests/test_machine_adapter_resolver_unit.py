from __future__ import annotations

from pathlib import Path

from tools.machine_adapter.resolver import resolve_machine_profiles


def test_resolver_expands_inherits_and_includes():
    root = Path("tests/fixtures/machine_adapter")

    profiles = resolve_machine_profiles(root=root, vendor_key="BBL")

    assert len(profiles) == 1
    profile = profiles[0]
    assert profile.name == "Bambu Lab H2D 0.4 nozzle"
    assert profile.settings["printer_model"] == "Bambu Lab H2D"
    assert profile.settings["printable_height"] == "325"
    assert profile.settings["machine_start_gcode"] == "G28 ; home"
    assert profile.source_files
    assert all(item.sha256 for item in profile.source_files)
