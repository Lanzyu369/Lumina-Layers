from __future__ import annotations

import json
from pathlib import Path

from tools.machine_adapter.import_profiles import run_import


def test_run_import_writes_registry_and_templates(tmp_path):
    source_root = Path("tests/fixtures/machine_adapter")
    output_root = tmp_path / "machine_registry"

    result = run_import(
        slicer_id="BambuStudio",
        source_root=source_root,
        source_version="02.07.01.57",
        vendor_keys=("BBL",),
        output_root=output_root,
    )

    assert result.device_count == 1
    registry = json.loads((output_root / "registry.json").read_text(encoding="utf-8"))
    assert registry["slicers"][0]["slicer_id"] == "BambuStudio"
    machine = registry["slicers"][0]["machines"][0]
    assert machine["thumbnail"] == "slicers/BambuStudio/02.07.01.57/assets/bambu-lab-h2d_cover.png"
    assert (output_root / machine["thumbnail"]).read_bytes() == b"fake-png-bytes-for-machine-adapter-test\n"
    templates = list((output_root / "slicers").rglob("*.json"))
    assert templates
    template = json.loads(templates[0].read_text(encoding="utf-8"))
    assert template["layer_height"] == "0.08"


def test_run_import_filters_by_machine_name(tmp_path):
    source_root = tmp_path / "profiles"
    machine_dir = source_root / "BBL" / "machine"
    machine_dir.mkdir(parents=True)
    (machine_dir / "fdm_common.json").write_text(
        json.dumps(
            {
                "type": "machine",
                "name": "fdm_common",
                "instantiation": "false",
                "printable_height": "325",
                "printable_area": ["0x0", "350x0", "350x320", "0x320"],
            }
        ),
        encoding="utf-8",
    )
    for model in ("Bambu Lab H2D", "Bambu Lab H2D Pro", "Bambu Lab P1S"):
        (machine_dir / f"{model} 0.4 nozzle.json").write_text(
            json.dumps(
                {
                    "type": "machine",
                    "name": f"{model} 0.4 nozzle",
                    "inherits": "fdm_common",
                    "instantiation": "true",
                    "printer_model": model,
                    "printer_variant": "0.4",
                    "nozzle_diameter": ["0.4"],
                }
            ),
            encoding="utf-8",
        )
    output_root = tmp_path / "machine_registry"

    result = run_import(
        slicer_id="BambuStudio",
        source_root=source_root,
        source_version="02.07.01.57",
        vendor_keys=("BBL",),
        output_root=output_root,
        machine_name="Bambu Lab H2D",
    )

    assert result.device_count == 1
    registry = json.loads((output_root / "registry.json").read_text(encoding="utf-8"))
    assert registry["slicers"][0]["machines"][0]["display_name"] == "Bambu Lab H2D"
