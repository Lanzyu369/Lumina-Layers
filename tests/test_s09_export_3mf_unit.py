"""Focused regressions for S09 3MF export handoff."""

from __future__ import annotations

import trimesh

from config import ModelingMode
from core.pipeline import s09_export_3mf


def test_s09_passes_full_slot_names_to_exporter(monkeypatch, tmp_path) -> None:
    """S09 should preserve the full selected palette when exporting sparse scenes."""

    captured: dict[str, object] = {}

    def _fake_export_scene_with_bambu_metadata(
        *,
        scene,
        output_path: str,
        slot_names,
        preview_colors,
        settings,
        color_mode: str,
        printer_id: str,
        slicer: str,
        watermark: str = "LuminaStudio",
        project_slot_names=None,
    ) -> str:
        captured["scene"] = scene
        captured["output_path"] = output_path
        captured["slot_names"] = list(slot_names)
        captured["preview_colors"] = dict(preview_colors)
        captured["color_mode"] = color_mode
        captured["printer_id"] = printer_id
        captured["slicer"] = slicer
        captured["project_slot_names"] = list(project_slot_names) if project_slot_names is not None else None
        captured["watermark"] = watermark
        return output_path

    monkeypatch.setattr(s09_export_3mf, "MODELS_DIR", str(tmp_path))
    monkeypatch.setattr(s09_export_3mf, "generate_model_filename", lambda *_args: "native-export.3mf")
    monkeypatch.setattr(s09_export_3mf, "export_scene_with_bambu_metadata", _fake_export_scene_with_bambu_metadata)

    scene = trimesh.Scene()
    scene.add_geometry(trimesh.creation.box(extents=[1, 1, 1]), geom_name="yellow")

    ctx = {
        "scene": scene,
        "valid_slot_names": ["yellow"],
        "slot_names": ["bambugreen", "black", "blue", "cyan", "magenta", "red", "white", "yellow"],
        "preview_colors": {7: [255, 230, 0, 255]},
        "color_mode": "8-Color",
        "image_path": str(tmp_path / "native.png"),
        "modeling_mode": ModelingMode.HIGH_FIDELITY,
        "target_w": 16,
        "pixel_scale": 1.0,
        "structure_mode": "双面",
        "printer_id": "bambu-h2d",
        "slicer": "BambuStudio",
    }

    result = s09_export_3mf.run(ctx)

    assert result["out_path"] == str(tmp_path / "native-export.3mf")
    assert captured["slot_names"] == ["yellow"]
    assert captured["project_slot_names"] == [
        "bambugreen",
        "black",
        "blue",
        "cyan",
        "magenta",
        "red",
        "white",
        "yellow",
    ]
