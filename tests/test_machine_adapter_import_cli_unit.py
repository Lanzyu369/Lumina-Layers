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
    templates = list((output_root / "slicers").rglob("*.json"))
    assert templates
    template = json.loads(templates[0].read_text(encoding="utf-8"))
    assert template["layer_height"] == "0.08"
