"""Focused regressions for S09 3MF export handoff."""

from __future__ import annotations

import trimesh
from unittest.mock import patch

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
        nozzle_size: str | float | None = None,
        watermark: str = "LuminaStudio",
        project_slot_names=None,
        enable_base_layer_height_modifier: bool = True,
        base_height_mm: float = 0.0,
        color_height_mm: float = 0.0,
        face_orientation: str = "down",
    ) -> str:
        captured["scene"] = scene
        captured["output_path"] = output_path
        captured["slot_names"] = list(slot_names)
        captured["preview_colors"] = dict(preview_colors)
        captured["color_mode"] = color_mode
        captured["printer_id"] = printer_id
        captured["slicer"] = slicer
        captured["nozzle_size"] = nozzle_size
        captured["project_slot_names"] = list(project_slot_names) if project_slot_names is not None else None
        captured["watermark"] = watermark
        captured["enable_base_layer_height_modifier"] = enable_base_layer_height_modifier
        captured["base_height_mm"] = base_height_mm
        captured["color_height_mm"] = color_height_mm
        captured["face_orientation"] = face_orientation
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


def _make_minimal_s09_ctx(tmp_path, **extra_ctx) -> dict:
    scene = trimesh.Scene()
    scene.add_geometry(trimesh.creation.box(extents=[1, 1, 1]), geom_name="Slot 1")

    ctx = {
        "scene": scene,
        "valid_slot_names": ["Slot 1"],
        "slot_names": ["Slot 1"],
        "preview_colors": {"Slot 1": (255, 0, 0, 255)},
        "color_mode": "4-Color",
        "image_path": str(tmp_path / "source.png"),
        "modeling_mode": ModelingMode.HIGH_FIDELITY,
        "target_w": 16,
        "pixel_scale": 1.0,
        "structure_mode": "单面",
        "printer_id": "bambu-h2d",
        "slicer": "BambuStudio",
        "nozzle_size": "0.4",
    }
    ctx.update(extra_ctx)
    return ctx


def test_s09_passes_base_layer_kwargs_when_ctx_has_them(tmp_path) -> None:
    with patch.object(s09_export_3mf, "MODELS_DIR", str(tmp_path)), patch.object(
        s09_export_3mf,
        "generate_model_filename",
        lambda *_args: "ctx-values.3mf",
    ), patch.object(s09_export_3mf, "export_scene_with_bambu_metadata", autospec=True) as mock_export:
        mock_export.return_value = str(tmp_path / "ctx-values.3mf")

        result = s09_export_3mf.run(
            _make_minimal_s09_ctx(
                tmp_path,
                bambu_base_height_mm=0.8,
                bambu_color_height_mm=2.4,
                bambu_face_orientation="down",
                enable_base_layer_height_modifier=True,
            )
        )

    assert result["out_path"] == str(tmp_path / "ctx-values.3mf")
    kwargs = mock_export.call_args.kwargs
    assert kwargs["enable_base_layer_height_modifier"] is True
    assert kwargs["base_height_mm"] == 0.8
    assert kwargs["color_height_mm"] == 2.4
    assert kwargs["face_orientation"] == "down"


def test_s09_falls_back_to_safe_defaults_when_ctx_missing_keys(tmp_path) -> None:
    with patch.object(s09_export_3mf, "MODELS_DIR", str(tmp_path)), patch.object(
        s09_export_3mf,
        "generate_model_filename",
        lambda *_args: "defaults.3mf",
    ), patch.object(s09_export_3mf, "export_scene_with_bambu_metadata", autospec=True) as mock_export:
        mock_export.return_value = str(tmp_path / "defaults.3mf")

        result = s09_export_3mf.run(_make_minimal_s09_ctx(tmp_path))

    assert result["out_path"] == str(tmp_path / "defaults.3mf")
    kwargs = mock_export.call_args.kwargs
    assert kwargs["enable_base_layer_height_modifier"] is True
    assert kwargs["base_height_mm"] == 0.0
    assert kwargs["color_height_mm"] == 0.0
    assert kwargs["face_orientation"] == "down"


def test_s09_passes_face_up_for_five_color(tmp_path) -> None:
    with patch.object(s09_export_3mf, "MODELS_DIR", str(tmp_path)), patch.object(
        s09_export_3mf,
        "generate_model_filename",
        lambda *_args: "face-up.3mf",
    ), patch.object(s09_export_3mf, "export_scene_with_bambu_metadata", autospec=True) as mock_export:
        mock_export.return_value = str(tmp_path / "face-up.3mf")

        s09_export_3mf.run(_make_minimal_s09_ctx(tmp_path, bambu_face_orientation="up"))

    assert mock_export.call_args.kwargs["face_orientation"] == "up"


def test_s09_passes_face_double_for_doublesided(tmp_path) -> None:
    with patch.object(s09_export_3mf, "MODELS_DIR", str(tmp_path)), patch.object(
        s09_export_3mf,
        "generate_model_filename",
        lambda *_args: "face-double.3mf",
    ), patch.object(s09_export_3mf, "export_scene_with_bambu_metadata", autospec=True) as mock_export:
        mock_export.return_value = str(tmp_path / "face-double.3mf")

        s09_export_3mf.run(_make_minimal_s09_ctx(tmp_path, bambu_face_orientation="double"))

    assert mock_export.call_args.kwargs["face_orientation"] == "double"
