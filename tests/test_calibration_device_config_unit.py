from __future__ import annotations

import json
import zipfile
from pathlib import Path

from config import PaletteEntry
from core.calibration import generate_bw_calibration_board
from core.single_stage import generate_single_stage_kit


def test_legacy_calibration_board_forwards_device_settings_to_writer(
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    def _fake_export_scene_with_bambu_metadata(**kwargs: object) -> None:
        captured.update(kwargs)
        Path(str(kwargs["output_path"])).write_bytes(b"3mf")

    monkeypatch.setattr("core.calibration.MODELS_DIR", str(tmp_path))
    monkeypatch.setattr(
        "core.calibration.export_scene_with_bambu_metadata",
        _fake_export_scene_with_bambu_metadata,
    )

    generate_bw_calibration_board(
        block_size_mm=3.0,
        gap_mm=0.4,
        backing_thickness_mm=0.4,
        printer_id="bambu-p1s",
        slicer="OrcaSlicer",
        nozzle_size="0.2",
    )

    assert captured["printer_id"] == "bambu-p1s"
    assert captured["slicer"] == "OrcaSlicer"
    assert captured["nozzle_size"] == "0.2"


def test_legacy_calibration_board_manifest_uses_selected_template(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("core.calibration.MODELS_DIR", str(tmp_path))

    output_path, _preview, _status = generate_bw_calibration_board(
        block_size_mm=3.0,
        gap_mm=0.4,
        backing_thickness_mm=0.4,
        printer_id="bambu-p1s",
        slicer="OrcaSlicer",
        nozzle_size="0.2",
    )

    with zipfile.ZipFile(output_path, "r") as archive:
        settings = json.loads(
            archive.read("Metadata/project_settings.config").decode("utf-8")
        )

    assert settings["printer_model"] == "Bambu Lab P1S"
    assert settings["printer_settings_id"] == "Bambu Lab P1S 0.2 nozzle"
    assert settings["nozzle_diameter"] == ["0.2"]


def test_single_stage_kit_forwards_device_settings_to_writer(
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    def _fake_export_scene_with_bambu_metadata(**kwargs: object) -> None:
        captured.update(kwargs)
        Path(str(kwargs["output_path"])).write_bytes(b"3mf")

    monkeypatch.setattr("core.single_stage.kit.MODELS_DIR", str(tmp_path))
    monkeypatch.setattr("core.single_stage.kit.TEMP_DIR", str(tmp_path))
    monkeypatch.setattr(
        "core.single_stage.kit.export_scene_with_bambu_metadata",
        _fake_export_scene_with_bambu_metadata,
    )
    monkeypatch.setattr(
        "core.single_stage.kit._resolve_colorchecker_bundle",
        lambda: (None, None),
    )

    generate_single_stage_kit(
        palette=[
            PaletteEntry(
                color="White",
                material="PLA Basic",
                hex_color="#FFFFFF",
                color_name="White",
            )
        ],
        printer_id="bambu-p1s",
        slicer="OrcaSlicer",
        nozzle_size="0.2",
    )

    assert captured["printer_id"] == "bambu-p1s"
    assert captured["slicer"] == "OrcaSlicer"
    assert captured["nozzle_size"] == "0.2"
