from __future__ import annotations

import json

from core.machine_registry import load_machine_registry


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
                        "application_metadata": "BambuStudio-02.07.01.57",
                        "sidecar_policy": "bambu_studio",
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
                                "nozzles": [
                                    {
                                        "device_profile_id": "BambuStudio:bbl:bambu-lab-h2d:0.4",
                                        "nozzle_size": "0.4",
                                        "source_profile_name": "Bambu Lab H2D 0.4 nozzle",
                                        "template": (
                                            "slicers/BambuStudio/02.07.01.57/"
                                            "metadata_templates/h2d_0_4.json"
                                        ),
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
    assert profile.application_metadata == "BambuStudio-02.07.01.57"
    assert profile.sidecar_policy == "bambu_studio"
