"""Unified Vector mesh topology and memory regression tests."""

from __future__ import annotations

from types import SimpleNamespace
import xml.etree.ElementTree as ET

import numpy as np
import pytest
import trimesh
from shapely.geometry import MultiPolygon, Polygon, box

import core.vector_engine as vector_engine
from core.layered_coordinate_domain import (
    LAYERED_COORDINATE_DOMAIN_KEY,
    LayeredCoordinateDomain,
)
from core.mesh_export_parts import get_mesh_export_part_ranges
from core.vector_engine import (
    VectorAnalysis,
    VectorProcessor,
    _concatenate_meshes_fast,
)
from core.errors import VectorMeshMemoryBudgetError
from utils.bambu_3mf_writer import BambuStudio3MFWriter


def _edge_incidence_counts(mesh: trimesh.Trimesh) -> np.ndarray:
    faces = np.asarray(mesh.faces, dtype=np.int64)
    edges = np.concatenate(
        (faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]),
        axis=0,
    )
    edges.sort(axis=1)
    return np.unique(edges, axis=0, return_counts=True)[1]


def _assert_closed(mesh: trimesh.Trimesh, *, volume: float) -> None:
    assert mesh.is_watertight
    assert mesh.is_winding_consistent
    assert np.all(_edge_incidence_counts(mesh) == 2)
    assert abs(float(mesh.volume)) == pytest.approx(volume, abs=1e-5)


def _run_one_material(geometries, *, height: float = 0.2):
    result = VectorProcessor._run_length_extrude(
        matched_shapes=[
            {"geometry": geometry, "recipe": [0]}
            for geometry in geometries
        ],
        num_layers=1,
        layer_h=height,
        num_channels=1,
        slot_names=["White"],
        scale_factor=1.0,
    )
    return result["White"]["meshes"]


def test_build_mesh_uses_one_canvas_writer_grid_for_all_material_runs() -> None:
    """Remote material runs inherit the canvas writer grid, not local grids."""

    target_width_mm = 20_000.0
    canvas_width = 814.0
    canvas_height = 947.0
    scale_factor = target_width_mm / canvas_width
    processor = VectorProcessor.__new__(VectorProcessor)
    processor.color_mode = "4-Color (RYBW)"
    processor.enable_fridge_magnet = False
    processor.enable_coating = False
    processor.enable_outline = False
    processor.layer_height_mm = 0.08
    processor._merge_backing_into_material = False
    analysis = VectorAnalysis(
        shape_data=[],
        clipped_shapes=[],
        matched_shapes=[
            {"geometry": box(0.0, 0.0, 1.0, 1.0), "recipe": [0]},
            {"geometry": box(2.0, 0.0, 3.0, 1.0), "recipe": [1]},
        ],
        silhouette=box(0.0, 0.0, canvas_width, canvas_height),
        scale_factor=scale_factor,
        bbox=(0.0, 0.0, canvas_width, canvas_height),
        color_conf={},
        slot_names=["White", "Red"],
        num_channels=2,
        num_layers=1,
        preview_colors={
            0: [255, 255, 255, 255],
            1: [255, 0, 0, 255],
        },
    )

    scene = processor.build_mesh(
        analysis=analysis,
        thickness_mm=0.0,
        structure_mode="Single-sided",
    )

    domain = LayeredCoordinateDomain.from_metadata(
        scene.metadata[LAYERED_COORDINATE_DOMAIN_KEY]
    )
    assert analysis.coordinate_domain == domain
    assert domain.xy_grid_mm > 0.0001
    assert {
        (
            mesh.metadata.get("vector_layer_geometry")
            or mesh.metadata["vector_stepped_geometry"]
        )["grid_mm"]
        for mesh in scene.geometry.values()
    } == {domain.xy_grid_mm}


def test_run_length_keeps_large_body_and_printable_island() -> None:
    """A remote 5x5 mm island cannot disappear beside a 200x200 mm body."""

    meshes = _run_one_material(
        [
            box(0.0, 0.0, 200.0, 200.0),
            box(210.0, 0.0, 215.0, 5.0),
        ]
    )
    combined = _concatenate_meshes_fast(meshes)

    _assert_closed(combined, volume=(40_000.0 + 25.0) * 0.2)
    assert len(combined.split(only_watertight=False)) == 2


def test_vector_slanted_runs_form_one_material_object() -> None:
    """One material stays one editable 3MF object across touching Z runs."""

    lower_footprint = Polygon(
        [(0.0, 0.0), (4.0, 0.0), (3.0, 2.0), (0.0, 1.0)]
    )
    upper_footprint = Polygon(
        [(1.0, 0.2), (5.0, 0.2), (4.0, 2.2), (1.0, 1.2)]
    )
    result = VectorProcessor._run_length_extrude(
        matched_shapes=[
            {"geometry": lower_footprint, "recipe": [0, 1]},
            {"geometry": upper_footprint, "recipe": [1, 0]},
        ],
        num_layers=2,
        layer_h=0.08,
        num_channels=2,
        slot_names=["White", "Red"],
        scale_factor=1.0,
    )

    white_meshes = result["White"]["meshes"]
    assert len(white_meshes) == 1
    white = white_meshes[0]
    assert white.is_watertight
    assert white.is_winding_consistent
    assert get_mesh_export_part_ranges(white) == ()

    writer = BambuStudio3MFWriter(
        "touching-slanted-runs.3mf",
        settings={},
        color_mode="4-Color",
        printer_id="bambu-p2s",
        slicer="BambuStudio",
    )
    writer.add_mesh(white, "White", (255, 255, 255))
    assert len(writer.objects) == 1
    assert writer.objects[0].object_name == "White"


def test_run_length_keeps_point_touching_shells_independent() -> None:
    geometry = MultiPolygon(
        [
            box(0.0, 0.0, 1.0, 1.0),
            box(1.0, 1.0, 2.0, 2.0),
        ]
    )
    assert geometry.is_valid

    combined = _concatenate_meshes_fast(_run_one_material([geometry]))

    _assert_closed(combined, volume=0.4)
    assert len(combined.split(only_watertight=False)) == 2


def test_run_length_avoids_whole_material_stepped_arrangement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Independent closed runs are concatenated without a global arrangement."""

    monkeypatch.setattr(
        vector_engine,
        "build_vector_stepped_volume",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("ordinary Vector entered whole-material arrangement")
        ),
    )

    combined = _concatenate_meshes_fast(
        _run_one_material(
            [box(0.0, 0.0, 1.0, 1.0), box(2.0, 0.0, 3.0, 1.0)]
        )
    )

    _assert_closed(combined, volume=0.4)
    assert len(combined.split(only_watertight=False)) == 2


def test_run_length_does_not_retry_memory_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        vector_engine,
        "_build_source_spatial_groups",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(MemoryError("budget")),
    )

    with pytest.raises(MemoryError, match="budget"):
        _run_one_material([box(0.0, 0.0, 1.0, 1.0)])


def test_failed_fast_extrusion_uses_local_stepped_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        vector_engine,
        "extrude_prepared_vector_run_group",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ValueError("local cap triangulation failed")
        ),
    )

    meshes, stats = vector_engine._build_source_spatial_groups(
        (box(0.0, 0.0, 4.0, 3.0),),
        height=0.08,
        z_offset=0.16,
        scale_factor=1.0,
    )

    assert len(meshes) == 1
    _assert_closed(meshes[0], volume=4.0 * 3.0 * 0.08)
    assert stats["failed_source_part_count"] == 0
    assert stats["local_stepped_fallback_applied"] is True


def test_incomplete_fast_preparation_uses_local_stepped_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        vector_engine,
        "prepare_vector_spatial_groups_best_effort",
        lambda *_args, **_kwargs: SimpleNamespace(
            groups=(),
            source_part_count=1,
            failed_part_count=1,
            failure_types=(("ValueError", 1),),
        ),
    )

    meshes, stats = vector_engine._build_source_spatial_groups(
        (box(0.0, 0.0, 2.0, 5.0),),
        height=0.2,
        z_offset=0.0,
        scale_factor=1.0,
    )

    assert len(meshes) == 1
    _assert_closed(meshes[0], volume=2.0)
    assert stats["failed_source_part_count"] == 0
    assert stats["local_stepped_fallback_applied"] is True


def test_double_sided_groups_by_material_run_not_svg_shape_count() -> None:
    matched_shapes = [
        {
            "geometry": box(float(index * 2), 0.0, float(index * 2 + 1), 1.0),
            "recipe": [0, 1],
        }
        for index in range(100)
    ]
    meshes_by_slot: dict[str, dict[str, object]] = {}

    VectorProcessor._add_double_sided_layers(
        matched_shapes=matched_shapes,
        num_layers=2,
        layer_h=0.08,
        num_channels=2,
        slot_names=["White", "Red"],
        scale_factor=1.0,
        top_z_start=1.6,
        meshes_by_slot=meshes_by_slot,
    )

    assert len(meshes_by_slot["White"]["meshes"]) == 1
    assert len(meshes_by_slot["Red"]["meshes"]) == 1
    assert all(
        mesh.is_watertight
        for data in meshes_by_slot.values()
        for mesh in data["meshes"]
    )


@pytest.mark.parametrize("structure_mode", ["Single-sided", "Double-sided"])
def test_build_mesh_merges_backing_into_one_editable_material_object(
    structure_mode: str,
) -> None:
    """The normal product path exports one object for one selected material."""

    processor = VectorProcessor.__new__(VectorProcessor)
    processor.color_mode = "4-Color (RYBW)"
    processor.enable_fridge_magnet = False
    processor.enable_coating = False
    processor.enable_outline = False
    processor.layer_height_mm = 0.08
    processor._merge_backing_into_material = True
    geometry = Polygon(
        [(0.0, 0.0), (6.0, 0.0), (5.0, 4.0), (0.0, 3.0)]
    )
    analysis = VectorAnalysis(
        shape_data=[],
        clipped_shapes=[],
        matched_shapes=[{"geometry": geometry, "recipe": [0, 0]}],
        silhouette=geometry,
        scale_factor=1.0,
        bbox=(0.0, 0.0, 6.0, 4.0),
        color_conf={},
        slot_names=["White"],
        num_channels=1,
        num_layers=2,
        preview_colors={0: [255, 255, 255, 255]},
    )

    scene = processor.build_mesh(
        analysis=analysis,
        thickness_mm=0.4,
        structure_mode=structure_mode,
        backing_color_id=0,
    )

    assert list(scene.geometry) == ["White"]
    white = scene.geometry["White"]
    assert white.is_watertight
    assert white.is_winding_consistent
    assert np.all(_edge_incidence_counts(white) == 2)
    assert get_mesh_export_part_ranges(white) == ()

    writer = BambuStudio3MFWriter(
        f"one-material-{structure_mode}.3mf",
        settings={},
        color_mode="4-Color",
        printer_id="bambu-p2s",
        slicer="BambuStudio",
    )
    writer.add_mesh(white, "White", (255, 255, 255))
    assert [obj.object_name for obj in writer.objects] == ["White"]


def test_build_mesh_exports_one_editable_3mf_part_per_used_material() -> None:
    """Disconnected SVG islands do not become separate slicer objects."""

    slot_names = ["White", "Red", "Yellow", "Black"]
    matched_shapes = []
    islands = []
    for material_index in range(len(slot_names)):
        for island_index in range(2):
            x_offset = float(material_index * 6 + island_index * 2)
            island = box(x_offset, 0.0, x_offset + 1.0, 1.0)
            islands.append(island)
            matched_shapes.append(
                {"geometry": island, "recipe": [material_index]}
            )

    processor = VectorProcessor.__new__(VectorProcessor)
    processor.color_mode = "4-Color (RYBW)"
    processor.enable_fridge_magnet = False
    processor.enable_coating = False
    processor.enable_outline = False
    processor.layer_height_mm = 0.08
    processor._merge_backing_into_material = True
    analysis = VectorAnalysis(
        shape_data=[],
        clipped_shapes=[],
        matched_shapes=matched_shapes,
        silhouette=MultiPolygon(islands),
        scale_factor=1.0,
        bbox=(0.0, 0.0, 23.0, 1.0),
        color_conf={},
        slot_names=slot_names,
        num_channels=len(slot_names),
        num_layers=1,
        preview_colors={
            index: [index * 60, index * 40, index * 20, 255]
            for index in range(len(slot_names))
        },
    )

    scene = processor.build_mesh(
        analysis=analysis,
        thickness_mm=0.4,
        structure_mode="Single-sided",
        backing_color_id=0,
    )

    assert list(scene.geometry) == slot_names
    assert all(
        get_mesh_export_part_ranges(mesh) == ()
        for mesh in scene.geometry.values()
    )

    writer = BambuStudio3MFWriter(
        "one-part-per-material.3mf",
        settings={},
        color_mode="4-Color",
        printer_id="bambu-p2s",
        slicer="BambuStudio",
    )
    for index, material_name in enumerate(slot_names):
        writer.add_mesh(
            scene.geometry[material_name],
            material_name,
            (index * 60, index * 40, index * 20),
        )

    assert [entry.object_name for entry in writer.objects] == slot_names
    model_settings = ET.fromstring(
        writer._build_model_settings_bytes([2, 3, 4, 5], 6, [0, 1, 2, 3])
    )
    assert len(model_settings.findall("./object/part")) == len(slot_names)


def test_double_sided_coating_stays_one_auxiliary_object() -> None:
    """Two coating shells share one editable scene and 3MF object."""

    processor = VectorProcessor.__new__(VectorProcessor)
    processor.color_mode = "4-Color (RYBW)"
    processor.enable_fridge_magnet = False
    processor.enable_coating = True
    processor.coating_height_mm = 0.08
    processor.enable_outline = False
    processor.layer_height_mm = 0.08
    processor._merge_backing_into_material = True
    geometry = box(0.0, 0.0, 6.0, 4.0)
    analysis = VectorAnalysis(
        shape_data=[],
        clipped_shapes=[],
        matched_shapes=[{"geometry": geometry, "recipe": [0, 0]}],
        silhouette=geometry,
        scale_factor=1.0,
        bbox=(0.0, 0.0, 6.0, 4.0),
        color_conf={},
        slot_names=["White"],
        num_channels=1,
        num_layers=2,
        preview_colors={0: [255, 255, 255, 255]},
    )

    scene = processor.build_mesh(
        analysis=analysis,
        thickness_mm=0.4,
        structure_mode="Double-sided",
        backing_color_id=0,
    )

    assert set(scene.geometry) == {"White", "Coating"}
    coating = scene.geometry["Coating"]
    assert coating.is_watertight
    assert get_mesh_export_part_ranges(coating) == ()

    writer = BambuStudio3MFWriter(
        "one-material-double-coating.3mf",
        settings={},
        color_mode="4-Color",
        printer_id="bambu-p2s",
        slicer="BambuStudio",
    )
    writer.add_mesh(coating, "Coating", (200, 200, 200))
    assert [obj.object_name for obj in writer.objects] == ["Coating"]


def test_auxiliary_islands_are_aggregated_per_material() -> None:
    geometry = MultiPolygon(
        [
            box(float(index * 2), 0.0, float(index * 2 + 1), 1.0)
            for index in range(100)
        ]
    )

    mesh = VectorProcessor._extrude_spatial_geometry_group(
        geometry,
        height=0.08,
        z_offset=-0.08,
        scale=1.0,
        stage="coating",
    )

    _assert_closed(mesh, volume=8.0)
    assert len(mesh.split(only_watertight=False)) == 100


def test_build_mesh_rejects_over_budget_before_meshing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LUMINA_VECTOR_MESH_MEMORY_BUDGET_MB", "1")
    processor = VectorProcessor.__new__(VectorProcessor)
    processor.color_mode = "4-Color (RYBW)"
    geometry = box(0.0, 0.0, 2.0, 2.0)
    analysis = VectorAnalysis(
        shape_data=[],
        clipped_shapes=[],
        matched_shapes=[{"geometry": geometry, "recipe": [0]}],
        silhouette=geometry,
        scale_factor=1.0,
        bbox=(0.0, 0.0, 2.0, 2.0),
        color_conf={},
        slot_names=["White"],
        num_channels=1,
        num_layers=1,
        preview_colors={0: [255, 255, 255, 255]},
    )

    with pytest.raises(VectorMeshMemoryBudgetError) as raised:
        processor.build_mesh(
            analysis=analysis,
            thickness_mm=0.0,
            structure_mode="Single-sided",
        )

    assert raised.value.stage == "preflight"
