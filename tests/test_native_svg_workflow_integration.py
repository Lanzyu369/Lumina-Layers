"""Product-workflow integration coverage for native SVG analysis results."""

from __future__ import annotations

import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import trimesh

from core.layered_coordinate_domain import (
    LAYERED_COORDINATE_DOMAIN_KEY,
    LayeredCoordinateDomain,
)
from core.pipeline.vector_branch import (
    _generate_vector_outline_mesh,
    _inject_vector_keychain_loop,
)
from core.pipeline.vector_glb_preview import (
    build_vector_preview_parts_from_analysis,
    export_vector_glb_preview_v2,
)
from core.puzzle import PuzzleLayoutConfig, build_puzzle_layout
from core.vector_engine import (
    VectorProcessor,
    apply_recipe_overrides_to_analysis,
)
from core.vector_large_format import slice_vector_analysis_into_tiles
from utils.bambu_3mf_writer import export_scene_with_bambu_metadata


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "native_svg"
PALETTE_RGB = np.asarray(
    [
        [255, 255, 255],
        [220, 20, 60],
        [255, 230, 0],
        [0, 100, 240],
    ],
    dtype=np.uint8,
)


def _processor(*, matcher: object | None = None) -> VectorProcessor:
    if matcher is None:
        matcher = SimpleNamespace(
            lut_rgb=PALETTE_RGB,
            lut_path="native-workflow-direct.npy",
        )
    processor = VectorProcessor.from_img_processor(
        matcher,
        "4-Color (RYBW)",
    )

    def match_colors(
        clipped_shapes,
        *_args,
        num_layers=5,
        **_kwargs,
    ):
        matched = []
        for index, item in enumerate(clipped_shapes):
            channel = index % 3 + 1
            matched.append(
                {
                    "geometry": item["geometry"],
                    "recipe": [channel] * int(num_layers),
                    "color": item["color"],
                    "matched_rgb": tuple(int(value) for value in PALETTE_RGB[channel]),
                }
            )
        return matched

    processor._match_colors = match_colors
    return processor


def _analyze(
    filename: str = "clip_inherited_fill.svg",
    *,
    target_width_mm: float = 40.0,
    matcher: object | None = None,
):
    pytest.importorskip("lumina_svg_core")
    processor = _processor(matcher=matcher)
    analysis = processor.analyze_svg(
        str(FIXTURES / filename),
        target_width_mm,
    )
    assert analysis.stage_timings["geometry_backend"] == "native"
    return processor, analysis


def _magnet() -> dict[str, object]:
    return {
        "id": "native-round",
        "shape": "round",
        "preset_key": "round-4",
        "diameter_mm": 4.0,
        "width_mm": None,
        "height_mm": None,
        "thickness_mm": 0.4,
        "center_x_mm": 0.0,
        "center_y_mm": 0.0,
    }


def _preview_colors_with_names(analysis) -> dict:
    colors = dict(analysis.preview_colors)
    for index, name in enumerate(analysis.slot_names):
        colors[name] = colors[index]
    colors["Board"] = colors[0]
    return colors


def _package_part_names(path: Path) -> set[str]:
    with zipfile.ZipFile(path) as package:
        root = ET.fromstring(package.read("Metadata/model_settings.config"))
    names = set()
    for part in root.findall(".//part"):
        for metadata in part.findall("metadata"):
            if metadata.attrib.get("key") == "name":
                names.add(metadata.attrib.get("value", ""))
    return names


def test_native_analysis_builds_single_double_and_auxiliary_meshes() -> None:
    processor, analysis = _analyze()

    processor.enable_fridge_magnet = False
    processor.enable_coating = False
    baseline = processor.build_mesh(
        analysis,
        thickness_mm=1.2,
        structure_mode="Single-sided",
    )
    baseline_board_volume = abs(float(baseline.geometry["Board"].volume))

    processor.enable_fridge_magnet = True
    processor.fridge_magnets = [_magnet()]
    processor.enable_coating = True
    processor.coating_height_mm = 0.08
    processor.enable_outline = True
    processor.outline_width_mm = 0.5
    single = processor.build_mesh(
        analysis,
        thickness_mm=1.2,
        structure_mode="Single-sided",
    )
    single_color_volumes = {
        name: abs(float(mesh.volume))
        for name, mesh in single.geometry.items()
        if name in analysis.slot_names
    }
    double = processor.build_mesh(
        analysis,
        thickness_mm=1.2,
        structure_mode="Double-sided",
    )

    assert {"Board", "Coating"}.issubset(single.geometry)
    assert abs(float(single.geometry["Board"].volume)) < baseline_board_volume
    assert len(single.geometry["Coating"].split(only_watertight=False)) == 1
    assert len(double.geometry["Coating"].split(only_watertight=False)) == 2
    assert all(mesh.is_watertight for mesh in single.geometry.values())
    assert all(mesh.is_watertight for mesh in double.geometry.values())
    for name, volume in single_color_volumes.items():
        assert abs(float(double.geometry[name].volume)) == pytest.approx(
            2.0 * volume,
            rel=1e-6,
        )

    domain = LayeredCoordinateDomain.from_metadata(
        double.metadata[LAYERED_COORDINATE_DOMAIN_KEY]
    )
    assert analysis.coordinate_domain == domain
    canvas_bounds = domain.writer_canvas_bounds_mm
    assert canvas_bounds[2] - canvas_bounds[0] == pytest.approx(
        40.0,
        abs=0.001,
    )
    assert canvas_bounds[3] - canvas_bounds[1] == pytest.approx(
        24.0,
        abs=0.001,
    )


def test_native_analysis_drives_outline_keychain_glb_and_cross_slicer_3mf(
    tmp_path: Path,
) -> None:
    pytest.importorskip("rasterio")
    processor, analysis = _analyze(
        "fill_rules_transforms.svg",
        target_width_mm=12.0,
    )
    preview_colors = _preview_colors_with_names(analysis)
    scene = processor.build_mesh(
        analysis,
        thickness_mm=0.8,
        structure_mode="Single-sided",
    )
    context = {
        "add_loop": True,
        "loop_width": 4.0,
        "loop_length": 8.0,
        "loop_hole": 2.5,
        "loop_angle": 0.0,
        "loop_position": "top",
        "backing_color_id": 0,
        "spacer_thick": 0.8,
        "structure_mode": "Single-sided",
        "enable_coating": False,
    }
    assert _inject_vector_keychain_loop(
        context,
        scene,
        preview_colors,
        analysis.slot_names,
    )
    outline = _generate_vector_outline_mesh(
        analysis,
        0.5,
        preview_colors[0],
        analysis.slot_names[0],
        context,
        export_color_mode=processor.color_mode,
    )
    assert outline is not None and outline.is_watertight
    scene.add_geometry(outline, geom_name="Outline", node_name="Outline")
    preview_colors["Outline"] = preview_colors[0]

    assert scene.geometry["Keychain_Loop"].is_watertight
    assert scene.geometry["Keychain_Loop"].metadata[
        "bambu_material_name"
    ] in analysis.slot_names
    assert scene.geometry["Outline"].metadata[
        "bambu_material_name"
    ] in analysis.slot_names

    parts = build_vector_preview_parts_from_analysis(
        analysis=analysis,
        preview_colors=preview_colors,
        slot_list=list(analysis.slot_names),
        structure_mode="Single-sided",
        color_mode=processor.color_mode,
        thickness_mm=0.8,
        separate_backing=True,
        include_backing=True,
        include_outline=True,
        outline_width_mm=0.5,
    )
    assert {part.role for part in parts} == {"color", "backing", "outline"}
    glb_path = tmp_path / "native-workflow.glb"
    export_vector_glb_preview_v2(
        parts,
        output_path=str(glb_path),
        pixels_per_mm=1.0,
    )
    glb_scene = trimesh.load(glb_path, force="scene")
    assert {part.export_name for part in parts} == set(glb_scene.geometry)

    used_names = list(scene.geometry)
    for slicer in ("BambuStudio", "OrcaSlicer"):
        output_path = tmp_path / f"native-{slicer}.3mf"
        export_scene_with_bambu_metadata(
            scene=scene,
            output_path=str(output_path),
            slot_names=used_names,
            preview_colors=preview_colors,
            color_mode="4-Color",
            printer_id="bambu-p1s",
            slicer=slicer,
            nozzle_size="0.4",
            project_slot_names=analysis.slot_names,
        )
        with zipfile.ZipFile(output_path) as package:
            names = set(package.namelist())
            assert "3D/3dmodel.model" in names
            assert "Metadata/project_settings.config" in names
            assert "Metadata/model_settings.config" in names
        assert set(used_names).issubset(_package_part_names(output_path))


def test_native_analysis_preserves_recipe_tiling_puzzle_and_material_metadata() -> None:
    solve_calls: list[list[tuple[int, int, int]]] = []

    class MaterialMatcher:
        lut_path = "material-archive-runtime"
        lut_rgb = PALETTE_RGB
        dynamic_layer_info = {"enabled": True, "max_layers": 6}
        material_solver_info = {"source": "material_archive", "base_channel_idx": 2}

        def solve_for_clipped_shapes(self, shapes, *, scale_factor):
            assert scale_factor > 0
            solve_calls.append([tuple(item["color"]) for item in shapes])

    processor, analysis = _analyze(matcher=MaterialMatcher())
    assert solve_calls and len(solve_calls[0]) == len(analysis.clipped_shapes)
    assert analysis.material_dynamic_layer_info == {
        "enabled": True,
        "max_layers": 6,
    }
    assert analysis.material_solver_info == {
        "source": "material_archive",
        "base_channel_idx": 2,
    }

    width_px = int(round(analysis.bbox[2] * analysis.scale_factor))
    height_px = int(round(analysis.bbox[3] * analysis.scale_factor))
    region_mask = np.ones((height_px, width_px), dtype=bool)
    apply_recipe_overrides_to_analysis(
        analysis,
        recipe_overrides=[
            {
                "region_id": "whole-document",
                "recipe": [3, 3, 3, 3, 3, 3],
                "layer_order": "Top2Bottom",
            }
        ],
        region_masks={"whole-document": region_mask},
        target_layers=6,
        base_channel_idx=2,
        pixels_per_mm=1.0,
    )
    assert analysis.num_layers == 6
    assert all(shape["recipe"] == [3, 3, 3, 3, 3, 3] for shape in analysis.matched_shapes)

    tiles = slice_vector_analysis_into_tiles(
        analysis=analysis,
        total_width_mm=40.0,
        total_height_mm=24.0,
        tile_width_mm=20.0,
        tile_height_mm=24.0,
    )
    assert [tile.label for tile in tiles] == ["R1C1", "R1C2"]
    assert all(tile.analysis.num_layers == 6 for tile in tiles)
    assert all(
        shape["recipe"] == [3, 3, 3, 3, 3, 3]
        for tile in tiles
        for shape in tile.analysis.matched_shapes
    )
    assert all(
        shape["geometry"].bounds[0] >= 0.0
        and shape["geometry"].bounds[2] <= 50.0 + 1e-9
        for tile in tiles
        for shape in tile.analysis.matched_shapes
    )

    _, puzzle_analysis = _analyze(
        "fill_rules_transforms.svg",
        target_width_mm=12.0,
    )
    preview_cache = VectorProcessor.build_preview_cache(
        puzzle_analysis,
        pixels_per_mm=2.0,
        supersample_preview=1,
    )
    solid_mask = preview_cache["mask_solid"]
    layout = build_puzzle_layout(
        PuzzleLayoutConfig(
            width_px=solid_mask.shape[1],
            height_px=solid_mask.shape[0],
            total_width_mm=12.0,
            total_height_mm=8.0,
            style="regular",
            sizing_mode="grid",
            rows=2,
            cols=2,
            seed=7,
            connector_style="classic",
            irregularity_strength=0.35,
            min_neck_width_mm=1.2,
            solid_mask=solid_mask,
        )
    )
    assert layout.layout_mode == "mask_aware"
    assert layout.pieces
    assert all(piece.polygon_px for piece in layout.pieces)
