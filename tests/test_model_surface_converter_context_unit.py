from __future__ import annotations

from core.pipeline.coordinator import run_raster_pipeline


def test_run_raster_pipeline_stop_after_s08_skips_export(monkeypatch):
    calls: list[str] = []

    class Step:
        def __init__(self, name: str) -> None:
            self.name = name

        def run(self, ctx: dict) -> dict:
            calls.append(self.name)
            ctx["scene"] = object()
            ctx["valid_slot_names"] = ["color_ff0000"]
            ctx["preview_colors"] = {"color_ff0000": (255, 0, 0)}
            return ctx

    import core.pipeline.coordinator as coordinator

    monkeypatch.setattr(coordinator.s01_input_validation, "run", Step("S01").run)
    monkeypatch.setattr(coordinator.s02_image_processing, "run", Step("S02").run)
    monkeypatch.setattr(coordinator.s03_color_replacement, "run", Step("S03").run)
    monkeypatch.setattr(coordinator.s04_debug_preview, "run", Step("S04").run)
    monkeypatch.setattr(coordinator.s05_preview_generation, "run", Step("S05").run)
    monkeypatch.setattr(coordinator.s06_voxel_building, "run", Step("S06").run)
    monkeypatch.setattr(coordinator.s07_mesh_generation, "run", Step("S07").run)
    monkeypatch.setattr(coordinator.s08_auxiliary_meshes, "run", Step("S08").run)
    monkeypatch.setattr(coordinator.s09_export_3mf, "run", Step("S09").run)
    monkeypatch.setattr(coordinator.s10_color_recipe, "run", Step("S10").run)
    monkeypatch.setattr(coordinator.s11_glb_preview, "run", Step("S11").run)
    monkeypatch.setattr(coordinator.s12_result_assembly, "run", Step("S12").run)

    result = run_raster_pipeline({"stop_after_step": "S08"})

    assert calls == ["S01", "S02", "S03", "S04", "S05", "S06", "S07", "S08"]
    assert result["_pipeline_stopped_after"] == "S08"
    assert result["valid_slot_names"] == ["color_ff0000"]


def test_build_image_model_context_sets_reusable_scene_defaults(monkeypatch):
    from core.converter import build_image_model_context

    progress_calls: list[float] = []
    captured: dict = {}

    def fake_run_raster_pipeline(ctx: dict) -> dict:
        captured.update(ctx)
        ctx["scene"] = object()
        return ctx

    monkeypatch.setattr("core.converter.run_raster_pipeline", fake_run_raster_pipeline)

    result = build_image_model_context(
        image_path="/tmp/source.png",
        lut_path="/tmp/lut.npy",
        stop_after_step="S08",
        progress=lambda value, desc="": progress_calls.append(value),
    )

    assert result["scene"] is not None
    assert captured["need_2d_preview"] is False
    assert captured["cover_source_path"] == "/tmp/source.png"
    assert captured["stop_after_step"] == "S08"
    assert "progress" in captured
