"""Regression tests for mesh vertex welding at shape borders.

Covers the fix where ``VectorProcessor.build_mesh`` pipes the concatenated
per-slot mesh through ``Trimesh.merge_vertices`` so that coincident border
vertices (produced by independent per-shape ``_extrude_geometry`` calls on
neighbouring Shapely polygons) are welded.

Without welding, Three.js and most triangle-based renderers compute per-face
normals on two touching but vertex-disjoint surfaces, producing the visible
"spikes / fragments" users reported on stroke-heavy or multi-path SVGs
(e.g. ``test_images/1 (1).svg``).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import trimesh
from scipy.spatial import cKDTree
from shapely.geometry import Polygon, box

from core.vector_engine import (
    VectorAnalysis,
    VectorProcessor,
    _build_stepped_volume_mesh,
    _concatenate_meshes_fast,
)


def _coincident_pair_count(mesh: trimesh.Trimesh, tol: float = 1e-6) -> int:
    """Count vertex pairs within *tol* mm — i.e. would be welded together."""
    if mesh.vertices.shape[0] < 2:
        return 0
    tree = cKDTree(mesh.vertices)
    pairs = tree.query_pairs(r=tol, output_type="ndarray")
    return int(pairs.shape[0])


def _build_two_height_relief_board() -> trimesh.Trimesh:
    """Build the minimal adjacent-height board that reproduced broken faces."""

    matched_shapes = [
        {
            "geometry": box(0.0, 0.0, 5.0, 5.0),
            "recipe": [0],
            "matched_rgb": (255, 0, 0),
        },
        {
            "geometry": box(5.0, 0.0, 10.0, 5.0),
            "recipe": [0],
            "matched_rgb": (0, 255, 0),
        },
    ]
    meshes_by_slot = VectorProcessor._build_relief_meshes(
        matched_shapes=matched_shapes,
        num_layers=1,
        layer_h=0.2,
        num_channels=1,
        slot_names=["White"],
        scale_factor=1.0,
        backing_color_id=0,
        default_height_mm=1.0,
        height_mode="color",
        color_height_map={"#ff0000": 1.0, "#00ff00": 2.0},
        heightmap_path=None,
        heightmap_max_height=None,
        bbox=(0.0, 0.0, 10.0, 5.0),
        extrude_cache={},
    )
    board = _concatenate_meshes_fast(meshes_by_slot["Board"]["meshes"])
    board.merge_vertices()
    return board


def test_relief_backing_welds_adjacent_height_steps() -> None:
    """Different backing heights must form one closed stepped solid."""

    board = _build_two_height_relief_board()

    assert board.is_watertight
    np.testing.assert_allclose(board.bounds, [[0.0, 0.0, 0.0], [10.0, 5.0, 1.8]])
    assert float(board.volume) == pytest.approx(65.0)


def test_relief_backing_volume_preserves_internal_cavity_profile() -> None:
    """A cavity that closes above its opening must remain a closed volume."""

    outer = box(0.0, 0.0, 10.0, 10.0)
    cavity = box(4.0, 4.0, 6.0, 6.0)
    board = _build_stepped_volume_mesh(
        [
            {"geometry": outer, "z_offset": 0.0, "height": 0.4},
            {
                "geometry": outer.difference(cavity),
                "z_offset": 0.4,
                "height": 0.6,
            },
            {"geometry": outer, "z_offset": 1.0, "height": 0.4},
        ],
        scale_factor=1.0,
    )

    assert board is not None
    assert board.is_watertight
    assert float(board.volume) == pytest.approx(137.6)


def test_relief_backing_splits_t_junctions_on_shared_curves() -> None:
    """A tall region edge must align with multiple shorter neighbours."""

    left = Polygon([(0.0, 0.0), (5.0, 0.0), (6.0, 10.0), (0.0, 10.0)])
    shared_midpoint = (5.5 + 1e-12, 5.0)
    right_lower = Polygon([(5.0, 0.0), (10.0, 0.0), (10.0, 5.0), shared_midpoint])
    right_upper = Polygon([shared_midpoint, (10.0, 5.0), (10.0, 10.0), (6.0, 10.0)])
    board = _build_stepped_volume_mesh(
        [
            {"geometry": left, "z_offset": 0.0, "height": 1.8},
            {"geometry": right_lower, "z_offset": 0.0, "height": 0.8},
            {"geometry": right_upper, "z_offset": 0.0, "height": 1.4},
        ],
        scale_factor=1.0,
    )

    assert board is not None
    assert board.is_watertight
    expected_volume = left.area * 1.8 + right_lower.area * 0.8 + right_upper.area * 1.4
    assert float(board.volume) == pytest.approx(expected_volume)


def test_relief_backing_glb_round_trip_stays_watertight(tmp_path) -> None:
    """The repaired topology must survive the actual preview file format."""

    board = _build_two_height_relief_board()
    scene = trimesh.Scene()
    scene.add_geometry(board, geom_name="Board", node_name="Board")
    glb_path = tmp_path / "two-height-relief.glb"
    glb_path.write_bytes(scene.export(file_type="glb"))

    loaded = trimesh.load(glb_path, force="scene", process=False)
    loaded_board = next(iter(loaded.geometry.values()))
    assert loaded_board.is_watertight
    assert float(loaded_board.volume) == pytest.approx(65.0)


def test_real_svg_relief_preview_glb_is_watertight(tmp_path) -> None:
    """The reported illustrated SVG must export without broken mesh faces."""

    from core.pipeline.vector_glb_preview import export_vector_glb_preview

    repository_root = Path(__file__).resolve().parents[1]
    processor = VectorProcessor(
        str(
            repository_root
            / "lut-preset"
            / "Custom"
            / "Bambulab&PLA&RYBW&红-黄-蓝-白.npy"
        ),
        "4-Color (RYBW)",
    )
    analysis = processor.analyze_svg(
        str(repository_root / "test_images" / "1.svg"),
        target_width_mm=100.0,
    )
    matched_colors = sorted(
        {
            tuple(int(value) for value in shape["matched_rgb"][:3])
            for shape in analysis.matched_shapes
        }
    )
    height_map = {
        f"#{red:02x}{green:02x}{blue:02x}": 1.0 + (index % 3) * 0.8
        for index, (red, green, blue) in enumerate(matched_colors)
    }
    scene = processor.build_mesh(
        analysis=analysis,
        thickness_mm=1.0,
        structure_mode="Single-sided",
        enable_relief=True,
        height_mode="color",
        color_height_map=height_map,
    )

    assert scene.geometry["Board"].is_watertight
    glb_path = tmp_path / "illustrated-relief-preview.glb"
    export_vector_glb_preview(
        scene=scene,
        output_path=str(glb_path),
        structure_mode="Single-sided",
        color_mode="4-Color (RYBW)",
        preview_colors=analysis.preview_colors,
        slot_list=list(analysis.slot_names),
        analysis=analysis,
        ctx={"enable_relief": True},
    )
    loaded = trimesh.load(glb_path, force="scene", process=False)
    assert "backing_plate" in loaded.geometry
    assert loaded.geometry["backing_plate"].is_watertight


class TestBuildMeshVertexWelding:
    """Validate the root cause and the fix at ``build_mesh``'s concat boundary."""

    @staticmethod
    def _two_adjacent_extrusions() -> tuple[trimesh.Trimesh, trimesh.Trimesh]:
        """Build two boxes that share the edge x=5 (so six vertex pairs coincide
        along the border after extrusion)."""
        left = box(0.0, 0.0, 5.0, 5.0)
        right = box(5.0, 0.0, 10.0, 5.0)
        extrude = VectorProcessor._extrude_geometry
        left_meshes = extrude(left, height=1.0, z_offset=0.0, scale=1.0)
        right_meshes = extrude(right, height=1.0, z_offset=0.0, scale=1.0)
        assert left_meshes and right_meshes, "extrude_polygon returned empty mesh list"
        return left_meshes[0], right_meshes[0]

    def test_adjacent_shapes_produce_coincident_vertices(self):
        """Precondition: two adjacent extruded boxes share coincident border
        vertices that ``trimesh.util.concatenate`` does NOT weld."""
        left_mesh, right_mesh = self._two_adjacent_extrusions()
        combined = trimesh.util.concatenate([left_mesh, right_mesh])
        coincident = _coincident_pair_count(combined, tol=1e-9)
        assert coincident >= 4, (
            "Adjacent shapes should leave at least one coincident vertex pair "
            "per shared border corner; concatenate() must not weld them "
            "implicitly (if this fails, trimesh API semantics changed)."
        )

    def test_merge_vertices_welds_coincident_border(self):
        """``merge_vertices`` must eliminate the coincident pairs that caused
        Three.js to render visible seams at shape borders."""
        left_mesh, right_mesh = self._two_adjacent_extrusions()
        combined = trimesh.util.concatenate([left_mesh, right_mesh])
        v_before = int(combined.vertices.shape[0])
        combined.merge_vertices()
        v_after = int(combined.vertices.shape[0])
        assert v_after < v_before, (
            "merge_vertices must reduce the vertex count when adjacent shapes "
            "produced coincident border vertices"
        )
        remaining = _coincident_pair_count(combined, tol=1e-9)
        assert remaining == 0, (
            f"After merge_vertices the mesh must contain no coincident "
            f"vertex pairs, got {remaining}"
        )

    def test_build_mesh_call_site_uses_fast_concat_then_merge_vertices(self):
        """Governance: the fix in ``build_mesh`` must not regress by removing
        the ``merge_vertices`` call after per-slot mesh concatenation."""
        import inspect

        source = inspect.getsource(VectorProcessor.build_mesh)
        concat_idx = source.find("_concatenate_meshes_fast")
        assert concat_idx >= 0, "build_mesh must use the vector fast concat helper"
        merge_idx = source.find("merge_vertices", concat_idx)
        assert merge_idx >= 0, (
            "build_mesh must call merge_vertices() after fast concatenation so "
            "coincident border vertices are welded before the scene is "
            "handed to Three.js / exporters"
        )

    def test_build_mesh_fast_concat_does_not_depend_on_trimesh_generic_concatenate(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        left_mesh, right_mesh = self._two_adjacent_extrusions()
        processor = VectorProcessor.__new__(VectorProcessor)

        def fake_run_length_extrude(*_args, **_kwargs):
            return {
                "White": {
                    "meshes": [left_mesh, right_mesh],
                    "mat_id": 0,
                }
            }

        def fail_generic_concatenate(*_args, **_kwargs):
            raise AssertionError("build_mesh should use the vector fast concat helper")

        monkeypatch.setattr(
            VectorProcessor,
            "_run_length_extrude",
            staticmethod(fake_run_length_extrude),
        )
        monkeypatch.setattr(trimesh.util, "concatenate", fail_generic_concatenate)
        processor.color_mode = "4-Color (RYBW)"
        analysis = VectorAnalysis(
            shape_data=[],
            clipped_shapes=[],
            matched_shapes=[],
            silhouette=None,
            scale_factor=1.0,
            bbox=(0.0, 0.0, 10.0, 5.0),
            color_conf={},
            slot_names=["White"],
            num_channels=1,
            num_layers=1,
            preview_colors={0: [255, 255, 255, 255], "White": [255, 255, 255, 255]},
        )

        scene = processor.build_mesh(
            analysis=analysis,
            thickness_mm=0.0,
            structure_mode="Single-sided",
        )

        combined = scene.geometry["White"]
        assert float(combined.volume) == pytest.approx(
            float(left_mesh.volume + right_mesh.volume),
            rel=1e-6,
            abs=1e-6,
        )
        assert _coincident_pair_count(combined, tol=1e-9) == 0

    def test_build_mesh_fast_concat_accepts_single_array_chunk(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        source_mesh = VectorProcessor._extrude_geometry(
            box(0.0, 0.0, 2.0, 2.0),
            height=1.0,
            z_offset=0.0,
            scale=1.0,
        )[0]
        chunk = (source_mesh.vertices.copy(), source_mesh.faces.copy())
        processor = VectorProcessor.__new__(VectorProcessor)
        processor.color_mode = "4-Color (RYBW)"

        def fake_run_length_extrude(*_args, **_kwargs):
            return {
                "White": {
                    "meshes": [chunk],
                    "mat_id": 0,
                }
            }

        monkeypatch.setattr(
            VectorProcessor,
            "_run_length_extrude",
            staticmethod(fake_run_length_extrude),
        )
        analysis = VectorAnalysis(
            shape_data=[],
            clipped_shapes=[],
            matched_shapes=[],
            silhouette=None,
            scale_factor=1.0,
            bbox=(0.0, 0.0, 2.0, 2.0),
            color_conf={},
            slot_names=["White"],
            num_channels=1,
            num_layers=1,
            preview_colors={0: [255, 255, 255, 255], "White": [255, 255, 255, 255]},
        )

        scene = processor.build_mesh(
            analysis=analysis,
            thickness_mm=0.0,
            structure_mode="Single-sided",
        )

        assert sorted(scene.geometry) == ["White"]
        assert int(len(scene.geometry["White"].faces)) == int(len(source_mesh.faces))

def test_merge_vertices_preserves_volume_of_disjoint_parts():
    """Sanity guard: merging vertices must not collapse geometrically
    disjoint parts (boxes more than 1mm apart)."""
    far_left = box(0.0, 0.0, 1.0, 1.0)
    far_right = box(10.0, 0.0, 11.0, 1.0)
    extrude = VectorProcessor._extrude_geometry
    left = extrude(far_left, height=1.0, z_offset=0.0, scale=1.0)[0]
    right = extrude(far_right, height=1.0, z_offset=0.0, scale=1.0)[0]
    combined = trimesh.util.concatenate([left, right])
    vol_before = float(combined.volume)
    combined.merge_vertices()
    vol_after = float(combined.volume)
    assert vol_after == pytest.approx(vol_before, rel=1e-6, abs=1e-6)
