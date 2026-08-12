"""Regression tests for vector mesh topology at shape borders.

Independently extruded prisms remain independently indexed closed shells.
Welding coincident vertices without first removing the prisms' internal faces
turns their shared border into an edge referenced by more than two triangles,
which Bambu Studio and OrcaSlicer classify as non-manifold.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import trimesh
from scipy.spatial import cKDTree
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

import core.vector_engine as vector_engine
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


def _indexed_edge_incidence(mesh: trimesh.Trimesh) -> np.ndarray:
    """Return triangle incidence counts for every indexed mesh edge."""

    faces = np.asarray(mesh.faces, dtype=np.int64)
    edges = np.concatenate(
        [faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]],
        axis=0,
    )
    edges.sort(axis=1)
    _, counts = np.unique(edges, axis=0, return_counts=True)
    return counts


class _CoverageMetadataMesh:
    """Mesh sentinel that rejects the expensive triangle-volume fallback."""

    metadata = {"_lumina_planar_coverage_mm2": 12.5}

    @property
    def volume(self):
        raise AssertionError("metadata fast path must not scan mesh volume")


def test_planar_coverage_uses_extrusion_metadata_without_volume_scan() -> None:
    """Known planar coverage must make conservation independent of face count."""

    coverage = vector_engine._extruded_planar_coverage_mm2(
        [_CoverageMetadataMesh()],
        height=0.2,
    )

    assert coverage == pytest.approx(12.5)


def test_hole_free_polygon_avoids_full_topology_scan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A valid simple polygon must not pay for a full 3D edge scan."""

    geometry = Polygon(
        [(0.0, 0.0), (3.0, 0.0), (3.0, 1.0), (1.0, 1.0), (1.0, 3.0), (0.0, 3.0)]
    )
    assert geometry.is_valid
    assert not geometry.interiors

    def _unexpected_watertight_scan(_mesh):
        raise AssertionError("simple polygon must use the topology fast path")

    monkeypatch.setattr(
        trimesh.Trimesh,
        "is_watertight",
        property(_unexpected_watertight_scan),
    )

    meshes = VectorProcessor._extrude_geometry(
        geometry,
        height=1.0,
        z_offset=0.0,
        scale=1.0,
        extrude_cache={},
    )

    assert len(meshes) == 1
    assert np.all(_indexed_edge_incidence(meshes[0]) == 2)


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


@pytest.mark.parametrize("touch_offset", [0.0, 1e-13])
def test_extrude_geometry_separates_exterior_from_touching_hole_ring(
    touch_offset: float,
) -> None:
    """Point-touching outer/hole rings must extrude as a manifold solid."""

    geometry = Polygon(
        [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)],
        [
            [
                (touch_offset, 5.0),
                (2.0, 4.0),
                (2.0, 6.0),
                (touch_offset, 5.0),
            ]
        ],
    )
    assert geometry.is_valid

    meshes = VectorProcessor._extrude_geometry(
        geometry,
        height=1.0,
        z_offset=0.0,
        scale=1.0,
        extrude_cache={},
    )

    assert len(meshes) == 1
    mesh = meshes[0]
    edge_counts = _indexed_edge_incidence(mesh)
    assert np.all(edge_counts == 2)
    assert mesh.is_watertight
    np.testing.assert_allclose(mesh.bounds, [[0.0, 0.0, 0.0], [10.0, 10.0, 1.0]])
    assert float(mesh.volume) == pytest.approx(float(geometry.area), abs=0.01)


def test_extrude_geometry_preserves_parts_when_precision_splits_thin_bridge() -> None:
    """A sub-resolution bridge may split, but neither lobe may be dropped."""

    geometry = unary_union(
        [
            box(0.0, 0.0, 1.0, 1.0),
            box(1.0, 0.5, 2.0, 0.5 + 1e-13),
            box(2.0, 0.0, 3.0, 1.0),
        ]
    )
    assert geometry.geom_type == "Polygon"
    assert geometry.is_valid

    meshes = VectorProcessor._extrude_geometry(
        geometry,
        height=1.0,
        z_offset=0.0,
        scale=1.0,
        extrude_cache={},
    )

    assert len(meshes) == 1
    mesh = meshes[0]
    assert np.all(_indexed_edge_incidence(mesh) == 2)
    assert mesh.is_watertight
    np.testing.assert_allclose(mesh.bounds, [[0.0, 0.0, 0.0], [3.0, 1.0, 1.0]])
    assert float(mesh.volume) == pytest.approx(float(geometry.area), abs=0.01)


def test_extrude_geometry_separates_point_touching_hole_rings() -> None:
    """Two holes sharing one point must not create a four-face vertical edge."""

    geometry = Polygon(
        [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)],
        [
            [(2.0, 4.0), (5.0, 5.0), (2.0, 6.0), (2.0, 4.0)],
            [(8.0, 4.0), (8.0, 6.0), (5.0, 5.0), (8.0, 4.0)],
        ],
    )
    assert geometry.is_valid

    meshes = VectorProcessor._extrude_geometry(
        geometry,
        height=1.0,
        z_offset=0.0,
        scale=1.0,
        extrude_cache={},
    )

    assert len(meshes) == 1
    mesh = meshes[0]
    assert np.all(_indexed_edge_incidence(mesh) == 2)
    assert mesh.is_watertight
    np.testing.assert_allclose(mesh.bounds, [[0.0, 0.0, 0.0], [10.0, 10.0, 1.0]])
    assert float(mesh.volume) == pytest.approx(float(geometry.area), abs=0.01)


def test_large_touching_hole_uses_linear_contact_repair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A huge ring contact must not invoke GEOS's superlinear buffer path."""

    angles = np.linspace(np.pi, np.pi * 3.0, 20_001)
    hole_coordinates = np.column_stack(
        (
            10.0 + 10.0 * np.cos(angles),
            50.0 + 10.0 * np.sin(angles),
        )
    )
    hole_coordinates[-1] = hole_coordinates[0]
    geometry = Polygon(
        [
            (0.0, 0.0),
            (100.0, 0.0),
            (100.0, 100.0),
            (0.0, 100.0),
            (0.0, 50.0),
        ],
        [hole_coordinates],
    )
    assert geometry.is_valid

    def _unexpected_buffer(*_args, **_kwargs):
        raise AssertionError("simple point contacts must not call GEOS buffer")

    monkeypatch.setattr(Polygon, "buffer", _unexpected_buffer)
    repaired = vector_engine._separate_polygon_ring_contacts(
        geometry,
        geometry_gap=0.0001,
    )

    assert repaired.is_valid
    assert len(repaired.interiors[0].coords) == len(geometry.interiors[0].coords)
    assert float(repaired.area) == pytest.approx(float(geometry.area), abs=1e-8)
    exterior_vertices = set(repaired.exterior.coords[:-1])
    hole_vertices = set(repaired.interiors[0].coords[:-1])
    assert exterior_vertices.isdisjoint(hole_vertices)


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


@pytest.mark.parametrize("right_height", [1.0, 1.8])
def test_relief_backing_keeps_corner_touching_shells_separate(
    right_height: float,
) -> None:
    """Point-touching regions must remain independent manifold shells."""

    lower_left = box(0.0, 0.0, 1.0, 1.0)
    upper_right = box(1.0, 1.0, 2.0, 2.0)
    board = _build_stepped_volume_mesh(
        [
            {"geometry": lower_left, "z_offset": 0.0, "height": 1.0},
            {
                "geometry": upper_right,
                "z_offset": 0.0,
                "height": right_height,
            },
        ],
        scale_factor=1.0,
    )

    assert board is not None
    assert board.is_watertight
    assert len(board.split(only_watertight=False)) == 2
    assert float(board.volume) == pytest.approx(1.0 + right_height)


def test_relief_backing_scales_by_connected_component() -> None:
    """Unrelated height levels must not subdivide disconnected regions."""

    region_count = 40
    board = _build_stepped_volume_mesh(
        [
            {
                "geometry": box(index * 2.0, 0.0, index * 2.0 + 1.0, 1.0),
                "z_offset": 0.0,
                "height": 1.0 + index * 0.01,
            }
            for index in range(region_count)
        ],
        scale_factor=1.0,
    )

    assert board is not None
    assert board.is_watertight
    assert len(board.split(only_watertight=False)) == region_count
    assert len(board.faces) <= region_count * 20


def _native_kernel_contract_slabs() -> list[dict]:
    """Return a stepped solid that exercises holes, offsets, and XY scaling."""

    outer = box(-2.0, 3.0, 8.0, 13.0)
    cavity = box(1.0, 6.0, 3.0, 8.0)
    return [
        {"geometry": outer, "z_offset": 0.35, "height": 0.4},
        {
            "geometry": outer.difference(cavity),
            "z_offset": 0.75,
            "height": 0.6,
        },
        {"geometry": outer, "z_offset": 1.35, "height": 0.25},
    ]


@pytest.mark.skipif(
    vector_engine._load_relief_manifold3d() is None,
    reason="optional manifold3d fast kernel is not installed",
)
def test_relief_backing_uses_native_kernel_without_python_finalize(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Installed manifold3d must bypass the expensive atomic-prism fallback."""

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("Python atomic-prism fallback was unexpectedly used")

    monkeypatch.setattr(
        vector_engine,
        "_build_stepped_volume_mesh_python_prepared",
        fail_if_called,
    )
    board = _build_stepped_volume_mesh(
        _native_kernel_contract_slabs(),
        scale_factor=1.7,
    )

    assert board is not None
    assert board.is_watertight
    np.testing.assert_allclose(
        board.bounds,
        [[-3.4, 5.1, 0.35], [13.6, 22.1, 1.6]],
    )
    assert float(board.volume) == pytest.approx(
        (100.0 * 0.4 + 96.0 * 0.6 + 100.0 * 0.25) * 1.7**2,
        rel=1e-6,
    )


def test_relief_backing_missing_native_dependency_uses_exact_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Base installs and unsupported wheels must retain watertight correctness."""

    fallback_calls = 0
    real_fallback = vector_engine._build_stepped_volume_mesh_python_prepared

    def counted_fallback(*args, **kwargs):
        nonlocal fallback_calls
        fallback_calls += 1
        return real_fallback(*args, **kwargs)

    monkeypatch.setattr(vector_engine, "_load_relief_manifold3d", lambda: None)
    monkeypatch.setattr(
        vector_engine,
        "_build_stepped_volume_mesh_python_prepared",
        counted_fallback,
    )
    board = _build_stepped_volume_mesh(
        _native_kernel_contract_slabs(),
        scale_factor=1.7,
    )

    assert fallback_calls == 1
    assert board is not None
    assert board.is_watertight
    assert float(board.volume) == pytest.approx(
        (100.0 * 0.4 + 96.0 * 0.6 + 100.0 * 0.25) * 1.7**2,
    )


@pytest.mark.skipif(
    vector_engine._load_relief_manifold3d() is None,
    reason="optional manifold3d fast kernel is not installed",
)
def test_relief_backing_native_and_python_kernels_preserve_topology() -> None:
    """Fast and fallback kernels must agree on cavities and point contacts."""

    slabs = _native_kernel_contract_slabs()
    native = vector_engine._build_stepped_volume_mesh_manifold(
        slabs,
        scale_factor=1.7,
    )
    fallback = vector_engine._build_stepped_volume_mesh_python(
        slabs,
        scale_factor=1.7,
    )

    assert native is not None
    assert fallback is not None
    assert native.is_watertight
    assert fallback.is_watertight
    np.testing.assert_allclose(native.bounds, fallback.bounds, atol=1e-8)
    assert float(native.volume) == pytest.approx(
        float(fallback.volume),
        rel=1e-6,
        abs=1e-6,
    )

    point_touching = [
        {"geometry": box(0.0, 0.0, 1.0, 1.0), "z_offset": 0.2, "height": 1.0},
        {"geometry": box(1.0, 1.0, 2.0, 2.0), "z_offset": 0.2, "height": 1.8},
    ]
    native_point_touch = vector_engine._build_stepped_volume_mesh_manifold(
        point_touching,
        scale_factor=1.0,
    )
    fallback_point_touch = vector_engine._build_stepped_volume_mesh_python(
        point_touching,
        scale_factor=1.0,
    )
    assert native_point_touch is not None
    assert fallback_point_touch is not None
    assert len(native_point_touch.split(only_watertight=False)) == 2
    assert len(fallback_point_touch.split(only_watertight=False)) == 2


@pytest.mark.skipif(
    vector_engine._load_relief_manifold3d() is None,
    reason="optional manifold3d fast kernel is not installed",
)
def test_relief_backing_native_groups_same_z_fragments_before_union() -> None:
    """One height slab must not become many independently triangulated solids."""

    base = box(0.0, 0.0, 12.0, 4.0)
    raised_fragments = [
        box(index * 2.0, 0.0, index * 2.0 + 1.0, 4.0)
        for index in range(6)
    ]
    slabs = [
        {"geometry": base, "z_offset": 0.0, "height": 0.5},
        *[
            {"geometry": fragment, "z_offset": 0.5, "height": 0.7}
            for fragment in raised_fragments
        ],
    ]
    native = vector_engine._build_stepped_volume_mesh_manifold(
        slabs,
        scale_factor=1.0,
    )
    fallback = vector_engine._build_stepped_volume_mesh_python(
        slabs,
        scale_factor=1.0,
    )

    assert native is not None
    assert fallback is not None
    assert native.is_watertight
    assert float(native.volume) == pytest.approx(float(fallback.volume))
    assert len(native.faces) < len(fallback.faces)


@pytest.mark.parametrize("native_failure", ["exception", "invalid_mesh"])
def test_relief_backing_native_failure_rebuilds_whole_board_with_fallback(
    monkeypatch: pytest.MonkeyPatch,
    native_failure: str,
) -> None:
    """A failed or invalid native result must never leak a partial Board."""

    fallback_calls = 0
    real_fallback = vector_engine._build_stepped_volume_mesh_python_prepared

    def counted_fallback(*args, **kwargs):
        nonlocal fallback_calls
        fallback_calls += 1
        return real_fallback(*args, **kwargs)

    if native_failure == "exception":
        def broken_native(*_args, **_kwargs):
            raise RuntimeError("simulated manifold3d runtime failure")
    else:
        def broken_native(*_args, **_kwargs):
            return trimesh.creation.box(extents=(1.0, 1.0, 1.0))

    monkeypatch.setattr(
        vector_engine,
        "_build_stepped_volume_mesh_manifold_prepared",
        broken_native,
    )
    monkeypatch.setattr(
        vector_engine,
        "_build_stepped_volume_mesh_python_prepared",
        counted_fallback,
    )
    board = _build_stepped_volume_mesh(
        _native_kernel_contract_slabs(),
        scale_factor=1.7,
    )

    assert fallback_calls == 1
    assert board is not None
    assert board.is_watertight
    np.testing.assert_allclose(
        board.bounds,
        [[-3.4, 5.1, 0.35], [13.6, 22.1, 1.6]],
    )


def test_corner_touching_relief_stays_watertight_through_build_and_glb(
    tmp_path,
) -> None:
    """Scene assembly and preview export must preserve independent shells."""

    from core.pipeline.vector_glb_preview import export_vector_glb_preview

    svg_path = tmp_path / "corner-touch.svg"
    svg_path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" '
        'viewBox="0 0 20 20">'
        '<rect x="0" y="0" width="10" height="10" fill="#ff0000"/>'
        '<rect x="10" y="10" width="10" height="10" fill="#00ff00"/>'
        "</svg>",
        encoding="utf-8",
    )
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
    analysis = processor.analyze_svg(str(svg_path), target_width_mm=20.0)
    height_map = {
        f"#{red:02x}{green:02x}{blue:02x}": 1.0 + index * 0.8
        for index, (red, green, blue) in enumerate(
            sorted(
                {
                    tuple(int(value) for value in shape["matched_rgb"][:3])
                    for shape in analysis.matched_shapes
                }
            )
        )
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
    assert len(scene.geometry["Board"].split(only_watertight=False)) == 2
    glb_path = tmp_path / "corner-touch-preview.glb"
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
    assert loaded.geometry["backing_plate"].is_watertight
    assert len(loaded.geometry["backing_plate"].split(only_watertight=False)) == 2


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


class TestBuildMeshShellTopology:
    """Validate the slicer topology contract at ``build_mesh`` assembly."""

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

    def test_merge_vertices_turns_shared_border_non_manifold(self):
        """Blind welding reproduces the slicer's multi-face-edge warning."""
        left_mesh, right_mesh = self._two_adjacent_extrusions()
        combined = trimesh.util.concatenate([left_mesh, right_mesh])
        safe_counts = _indexed_edge_incidence(combined)
        assert np.all(safe_counts == 2)

        combined.merge_vertices()
        welded_counts = _indexed_edge_incidence(combined)
        assert np.any(welded_counts > 2)

    def test_build_mesh_call_site_does_not_weld_independent_shells(self):
        """Governance: normal slot assembly must not weld closed prisms."""
        import inspect

        source = inspect.getsource(VectorProcessor.build_mesh)
        concat_idx = source.find("_concatenate_meshes_fast")
        assert concat_idx >= 0, "build_mesh must use the vector fast concat helper"
        merge_idx = source.find("merge_vertices", concat_idx)
        assert merge_idx < 0, (
            "build_mesh must retain independently indexed closed shells; "
            "blind merge_vertices() creates multi-face shared edges"
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
        assert _coincident_pair_count(combined, tol=1e-9) >= 4
        edge_counts = _indexed_edge_incidence(combined)
        assert np.all(edge_counts == 2)

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


def test_run_length_extrude_preserves_source_area_when_optimized_union_is_lossy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A lossy union must fall back instead of exporting a partial run."""

    source_geometries = [
        box(0.0, 0.0, 1.0, 1.0),
        box(2.0, 0.0, 3.0, 1.0),
    ]

    def _drop_second_geometry(geometries):
        return tuple(geometries)[0]

    monkeypatch.setattr(
        vector_engine,
        "_union_run_group_geometries",
        _drop_second_geometry,
    )

    meshes_by_slot = VectorProcessor._run_length_extrude(
        matched_shapes=[
            {"geometry": geometry, "recipe": [0]}
            for geometry in source_geometries
        ],
        num_layers=1,
        layer_h=0.2,
        num_channels=1,
        slot_names=["White"],
        scale_factor=1.0,
        extrude_cache={},
    )

    meshes = meshes_by_slot["White"]["meshes"]
    actual_volume = sum(abs(float(mesh.volume)) for mesh in meshes)
    expected_volume = sum(float(geometry.area) for geometry in source_geometries) * 0.2
    assert actual_volume == pytest.approx(expected_volume, rel=1e-6, abs=1e-6)


def test_run_length_extrude_rejects_incomplete_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed primary and fallback extrusion must not return a bad model."""

    monkeypatch.setattr(
        VectorProcessor,
        "_extrude_geometry",
        staticmethod(lambda *_args, **_kwargs: []),
    )

    with pytest.raises(ValueError, match="coverage"):
        VectorProcessor._run_length_extrude(
            matched_shapes=[{"geometry": box(0.0, 0.0, 2.0, 2.0), "recipe": [0]}],
            num_layers=1,
            layer_h=0.2,
            num_channels=1,
            slot_names=["White"],
            scale_factor=1.0,
            extrude_cache={},
        )
