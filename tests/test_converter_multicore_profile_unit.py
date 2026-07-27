from pathlib import Path

import numpy as np
import pytest
import trimesh

from config import ModelingMode
from scripts.profile_converter_multicore import (
    MATERIAL_PALETTES,
    ProfileCase,
    build_report,
    build_pipeline_context,
    semantic_snapshot,
    summarize_runs,
)


@pytest.mark.parametrize("size", [8, 12, 15])
def test_material_palette_has_requested_unique_archives(size: int) -> None:
    palette = MATERIAL_PALETTES[size]
    assert len(palette) == size
    assert len(set(palette)) == size
    for directory_name in palette:
        archive = Path("materials") / directory_name / "material.json"
        stage_a = Path("materials") / directory_name / "stage_A_parameters.json"
        assert archive.is_file()
        assert stage_a.is_file()


@pytest.mark.parametrize(
    ("kind", "mode"),
    [("raster", ModelingMode.HIGH_FIDELITY), ("vector", ModelingMode.VECTOR)],
)
def test_build_pipeline_context_uses_quality_locked_profile_settings(
    tmp_path: Path,
    kind: str,
    mode: ModelingMode,
) -> None:
    source = tmp_path / ("input.svg" if kind == "vector" else "input.png")
    source.write_bytes(b"<svg/>" if kind == "vector" else b"not-decoded-in-this-test")
    case = ProfileCase(
        name=f"{kind}-12",
        kind=kind,
        input_path=source,
        target_width_mm=299.0,
        material_count=12,
    )

    ctx = build_pipeline_context(case)

    assert ctx["modeling_mode"] is mode
    assert ctx["material_source"] == "material_archive"
    assert ctx["selected_materials"] == MATERIAL_PALETTES[12]
    assert ctx["material_layer_count"] == 10
    assert ctx["material_layer_height_mm"] == 0.08
    assert ctx["quantize_colors"] == 64
    assert ctx["target_width_mm"] == 299.0
    assert ctx["structure_mode"] == "single-sided"


def _scene_with_geometry_order(order: tuple[str, ...]) -> trimesh.Scene:
    scene = trimesh.Scene()
    meshes = {
        "red": trimesh.creation.box(extents=(2.0, 1.0, 0.4)),
        "blue": trimesh.creation.box(extents=(1.0, 3.0, 0.8)),
    }
    for name in order:
        scene.add_geometry(meshes[name].copy(), node_name=name, geom_name=name)
    return scene


def test_semantic_snapshot_is_stable_across_array_layout_and_scene_order() -> None:
    rgb = np.arange(36, dtype=np.uint8).reshape(3, 4, 3)
    matrix = np.arange(24, dtype=np.int32).reshape(3, 4, 2)
    first = semantic_snapshot(
        {
            "matched_rgb": rgb,
            "material_matrix": matrix,
            "mask_solid": np.ones((3, 4), dtype=bool),
            "scene": _scene_with_geometry_order(("red", "blue")),
            "slot_names": ["white", "black"],
        }
    )
    second = semantic_snapshot(
        {
            "matched_rgb": np.asfortranarray(rgb),
            "material_matrix": np.asfortranarray(matrix),
            "mask_solid": np.asfortranarray(np.ones((3, 4), dtype=bool)),
            "scene": _scene_with_geometry_order(("blue", "red")),
            "slot_names": ["white", "black"],
        }
    )
    assert first == second


def test_semantic_snapshot_changes_when_geometry_or_layers_change() -> None:
    ctx = {
        "matched_rgb": np.zeros((2, 2, 3), dtype=np.uint8),
        "material_matrix": np.zeros((2, 2, 2), dtype=np.int32),
        "mask_solid": np.ones((2, 2), dtype=bool),
        "scene": _scene_with_geometry_order(("red", "blue")),
        "slot_names": ["white", "black"],
    }
    baseline = semantic_snapshot(ctx)
    changed_layers = {**ctx, "material_matrix": np.ones((2, 2, 2), dtype=np.int32)}
    changed_scene = {
        **ctx,
        "scene": trimesh.Scene(trimesh.creation.box(extents=(9.0, 1.0, 0.4))),
    }
    assert semantic_snapshot(changed_layers) != baseline
    assert semantic_snapshot(changed_scene) != baseline


def test_summarize_runs_reports_cold_warm_median_and_p90() -> None:
    summary = summarize_runs(
        [
            {"total_s": 9.0, "peak_rss_mb": 100.0},
            {"total_s": 5.0, "peak_rss_mb": 110.0},
            {"total_s": 7.0, "peak_rss_mb": 120.0},
        ]
    )
    assert summary["cold"]["total_s"] == 9.0
    assert summary["warm_median"]["total_s"] == 6.0
    assert summary["p90"]["total_s"] == pytest.approx(6.8)
    assert summary["peak"]["peak_rss_mb"] == 120.0


def test_build_report_omits_absolute_source_and_material_paths(
    tmp_path: Path,
) -> None:
    source = tmp_path / "private-user-image.jpg"
    source.write_bytes(b"image")
    case = ProfileCase(
        name="raster-12",
        kind="raster",
        input_path=source,
        target_width_mm=299.0,
        material_count=12,
    )
    report = build_report(
        case,
        runs=[{"total_s": 1.0, "peak_rss_mb": 2.0}],
    )
    serialized = repr(report)
    assert str(tmp_path) not in serialized
    assert report["input"]["name"] == source.name
    assert report["input"]["sha256"]
    assert report["materials"]["count"] == 12
    assert "directory_names" not in report["materials"]
