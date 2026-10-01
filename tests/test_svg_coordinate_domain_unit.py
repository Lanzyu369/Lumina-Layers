"""Coordinate identity, exact working units and durable precision contracts."""
from copy import deepcopy
from concurrent.futures import ProcessPoolExecutor
import multiprocessing
import pickle
from pathlib import Path

import numpy as np
import pytest
import shapely
from shapely.geometry import Polygon, box

from core.svg_coordinate_domain import (
    PRINT_GRID_KEY,
    SvgCoordinateDomain,
    _ownership_query_view,
    project_print_regions,
)
from core.vector_engine import VectorAnalysis, _copy_vector_parse_clip_cache_entry
from core.vector_material_meshing import _read_material_input, _write_material_input


def _read_analysis_in_worker(path):
    import lumina_svg_core
    from core.native_svg_adapter import native_build_identity
    analysis = pickle.loads(Path(path).read_bytes())
    return {
        "precision": float(shapely.get_precision(analysis.silhouette)),
        "version": analysis.svg_coordinate_domain.version,
        "native_build": native_build_identity(),
        "native_path": str(Path(lumina_svg_core._lumina_svg_core.__file__).resolve()),
    }


def _integer_winding(geometry, point_twice):
    winding = 0
    parts = (geometry,) if isinstance(geometry, Polygon) else geometry.geoms
    for polygon in parts:
        for ring in (polygon.exterior, *polygon.interiors):
            points = [(2 * int(x), 2 * int(y)) for x, y in ring.coords]
            for (ax, ay), (bx, by) in zip(points, points[1:]):
                cross = (bx-ax)*(point_twice[1]-ay)-(by-ay)*(point_twice[0]-ax)
                if ay <= point_twice[1] < by and cross > 0:
                    winding += 1
                elif by <= point_twice[1] < ay and cross < 0:
                    winding -= 1
    return winding != 0


def _analysis():
    domain = SvgCoordinateDomain(9.728e-9, 190/9728, (0, 0, 9728, 6376))
    geometry = domain.restore_precision(Polygon(
        np.array([(0, 0), (10, 0), (10, 10), (0, 10)]) * domain.grid_size
    ))
    return VectorAnalysis(
        shape_data=[{"poly": geometry}], clipped_shapes=[{"geometry": geometry}],
        matched_shapes=[{"geometry": geometry, "recipe": [0]}], silhouette=geometry,
        scale_factor=domain.mm_per_unit, bbox=domain.bbox, color_conf={}, slot_names=["White"],
        num_channels=1, num_layers=1, preview_colors={}, svg_coordinate_domain=domain,
    )


@pytest.mark.parametrize("round_trip", [deepcopy, lambda a: pickle.loads(pickle.dumps(a))])
def test_analysis_round_trip_restores_declared_precision(round_trip):
    before = _analysis()
    after = round_trip(before)
    assert after.svg_coordinate_domain == before.svg_coordinate_domain
    for geometry in (after.silhouette, after.shape_data[0]["poly"],
                     after.clipped_shapes[0]["geometry"], after.matched_shapes[0]["geometry"]):
        assert shapely.get_precision(geometry) == before.svg_coordinate_domain.grid_size
        assert geometry.equals_exact(before.silhouette, 0)


def test_parse_cache_round_trip_keeps_source_identity_and_precision():
    analysis = _analysis()
    entry = {**vars(analysis), "geometry_stage_timings": {"geometry_backend": "native"}}
    restored = _copy_vector_parse_clip_cache_entry(pickle.loads(pickle.dumps(entry)))
    assert restored["svg_coordinate_domain"].source_bbox == (0, 0, 9728, 6376)
    assert shapely.get_precision(restored["silhouette"]) == analysis.svg_coordinate_domain.grid_size


def test_off_grid_geometry_is_not_reinterpreted_as_original_integer_topology():
    domain = _analysis().svg_coordinate_domain
    with pytest.raises(ValueError, match="declared coordinate grid"):
        domain.restore_precision(Polygon([(0, 0), (0.3, 0), (0, 0.3)]))


def test_material_transport_preserves_print_domain(tmp_path):
    path = tmp_path / "material.json"
    slab = {"geometry": shapely.set_precision(box(-2, -2, 8, 8), 1),
            "height": 0.08, "z_offset": 0.16, PRINT_GRID_KEY: 0.0001}
    _write_material_input(path, [slab])
    restored = _read_material_input(path)[0]
    assert restored[PRINT_GRID_KEY] == 0.0001
    assert shapely.get_precision(restored["geometry"]) == 1
    assert restored["geometry"].equals_exact(slab["geometry"], 0)


def test_print_grid_ownership_preserves_coverage_and_later_paint():
    inputs = [box(0, 0, 4, 4), box(2, 0, 6, 4)]
    metrics = {}
    output = project_print_regions(inputs, mm_per_unit=1, grid_mm=1, metrics=metrics)
    assert output[0].intersection(output[1]).area == 0
    assert output[1].equals(inputs[1])
    assert shapely.union_all(output, grid_size=1).equals(box(0, 0, 6, 4))
    assert sum(g.area for g in output) == 24
    assert metrics["print_projection_overlap_pairs"] == 1


def test_print_grid_ownership_preserves_one_grid_wide_region():
    source = box(-12, -7, -11, -4)
    output = project_print_regions([source], mm_per_unit=1, grid_mm=1)
    assert output[0].area == source.area
    assert output[0].equals(source)


def test_ownership_query_view_keeps_vertices_and_returns_strict_interior_point():
    cells = np.asarray([shapely.set_precision(box(0, 0, 1, 3), 1.0)])
    query_cells = _ownership_query_view(cells)
    np.testing.assert_array_equal(
        shapely.get_coordinates(query_cells), shapely.get_coordinates(cells),
    )
    assert shapely.get_precision(query_cells) == 0.0
    point = shapely.point_on_surface(query_cells)
    assert shapely.within(point, query_cells).tolist() == [True]


def test_print_grid_ownership_preserves_large_regions_joined_by_one_grid():
    source = shapely.union_all([
        box(0, 0, 100000, 100000),
        box(0, 200000, 100000, 300000),
        box(50000, 100000, 50001, 200000),
    ])
    assert source.geom_type == "Polygon"
    assert source.area * 0.0001**2 == pytest.approx(200.001)

    shell = list(source.exterior.coords)[:-1]
    representations = [
        Polygon(shell[offset:] + shell[:offset])
        for offset in range(len(shell))
    ]
    representations.extend(
        Polygon(list(reversed(shell[offset:] + shell[:offset])))
        for offset in range(len(shell))
    )
    representations.append(shapely.affinity.translate(source, xoff=-400000, yoff=-700000))

    for geometry in representations:
        output = project_print_regions(
            [geometry], mm_per_unit=0.0001, grid_mm=0.0001,
        )
        assert output[0].area * 0.0001**2 == pytest.approx(200.001)
        assert output[0].equals(geometry)


def test_print_grid_ownership_keeps_two_region_control_and_labels():
    connected = shapely.union_all([
        box(0, 0, 100000, 100000),
        box(0, 200000, 100000, 300000),
        box(50000, 100000, 50001, 200000),
    ])
    other = box(200000, 0, 210000, 10000)
    output = project_print_regions(
        [connected, other], mm_per_unit=0.0001, grid_mm=0.0001,
    )
    assert [g.area * 0.0001**2 for g in output] == pytest.approx([200.001, 1.0])
    assert output[0].equals(connected)
    assert output[1].equals(other)


def test_print_grid_partition_keeps_owned_short_edge_triangle_and_metrics_parity():
    first_paint = box(0, 0, 10, 10)
    later_paint = Polygon([(1, 0), (10, 0), (10, 10), (0, 10), (0, 1)])
    expected_first = Polygon([(0, 0), (1, 0), (0, 1)])
    assert first_paint.is_valid and later_paint.is_valid
    assert expected_first.area == 0.5

    without_metrics = project_print_regions(
        [first_paint, later_paint], mm_per_unit=1, grid_mm=1,
    )
    metrics = {}
    with_metrics = project_print_regions(
        [first_paint, later_paint], mm_per_unit=1, grid_mm=1,
        metrics=metrics,
    )

    assert [geometry.area for geometry in without_metrics] == pytest.approx(
        [0.5, 99.5],
    )
    assert all(a.equals(b) for a, b in zip(without_metrics, with_metrics, strict=True))
    assert without_metrics[0].equals(expected_first)
    assert without_metrics[1].equals(later_paint)
    assert without_metrics[0].intersection(without_metrics[1]).area == 0
    assert shapely.union_all(without_metrics, grid_size=1).equals(first_paint)
    assert metrics["print_projection_collapsed_regions"] == 0


def test_print_projection_metrics_are_lazy_and_share_the_ownership_index(monkeypatch):
    real_tree = shapely.STRtree
    trees = []

    class CountingTree:
        def __init__(self, geometries):
            self._tree = real_tree(geometries)
            self.query_count = 0
            trees.append(self)

        def query(self, *args, **kwargs):
            self.query_count += 1
            return self._tree.query(*args, **kwargs)

    monkeypatch.setattr(shapely, "STRtree", CountingTree)
    regions = [box(0, 0, 4, 4), box(2, 0, 6, 4)]
    without_metrics = project_print_regions(
        regions, mm_per_unit=1, grid_mm=1,
    )
    assert len(trees) == 1
    assert trees[0].query_count == 1

    trees.clear()
    metrics = {}
    with_metrics = project_print_regions(
        regions, mm_per_unit=1, grid_mm=1, metrics=metrics,
    )
    assert len(trees) == 1
    assert trees[0].query_count == 2
    assert metrics["print_projection_overlap_pairs"] == 1
    assert all(
        a.equals(b)
        for a, b in zip(without_metrics, with_metrics, strict=True)
    )


def test_triangulation_keeps_print_grid_contacts_before_millimetre_encoding():
    from core.vector_layer_geometry import (
        _IndexedPolygon, _IndexedRunGroup, _extrude_indexed_run_group,
    )
    units = np.array([
        (1716797, 73047), (1716406, 72656), (1715820, 72461),
        (1715820, 72070), (1716016, 72266), (1717969, 71484),
    ], dtype=np.int64)
    area_mm2 = Polygon(units).area * 0.0001**2
    prepared = _IndexedRunGroup(
        (_IndexedPolygon(units, ()),), 0.0001, area_mm2, len(units), 0,
    )
    mesh = _extrude_indexed_run_group(prepared, height_mm=0.08, z_offset_mm=0.0)
    assert mesh.is_watertight
    assert mesh.volume == pytest.approx(area_mm2 * 0.08, rel=1e-8)


def test_spawn_restores_coordinate_contract_and_native_build(tmp_path):
    import lumina_svg_core
    from core.native_svg_adapter import native_build_identity
    analysis = _analysis()
    path = tmp_path / "analysis.pickle"
    path.write_bytes(pickle.dumps(analysis))
    with ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn")) as pool:
        result = pool.submit(_read_analysis_in_worker, str(path)).result(timeout=30)
    assert result == {
        "precision": analysis.svg_coordinate_domain.grid_size,
        "version": analysis.svg_coordinate_domain.version,
        "native_build": native_build_identity(),
        "native_path": str(Path(lumina_svg_core._lumina_svg_core.__file__).resolve()),
    }


@pytest.mark.parametrize("source_factor", [0.003, 1.0, 4096.0])
def test_partition_preserves_hole_island_and_labels_by_independent_winding(source_factor):
    shell = np.array([(-4, -4), (4, -4), (4, 4), (-4, 4)], dtype=float)
    hole = np.array([(-2, -2), (-2, 2), (2, 2), (2, -2)], dtype=float)
    island = np.array([(-1, -1), (1, -1), (1, 1), (-1, 1)], dtype=float)
    inputs = [Polygon(shell*source_factor, [hole*source_factor]), Polygon(island*source_factor)]
    output = project_print_regions(inputs, mm_per_unit=1/source_factor, grid_mm=1)
    assert all(g.is_valid for g in output)
    for x in range(-9, 10, 2):
        for y in range(-9, 10, 2):
            expected_shell = abs(x) < 8 and abs(y) < 8 and not (abs(x) < 4 and abs(y) < 4)
            expected_island = abs(x) < 2 and abs(y) < 2
            assert _integer_winding(output[0], (x, y)) == expected_shell
            assert _integer_winding(output[1], (x, y)) == expected_island


def test_same_version_new_native_build_invalidates_parse_cache(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from core import native_svg_adapter
    from core.vector_engine import (
        _vector_parse_clip_cache_key, _serialize_vector_parse_clip_cache,
        _vector_parse_clip_cache_provenance, _load_vector_parse_clip_cache_artifact_by_provenance,
    )
    binary = tmp_path / "native.pyd"
    binary.write_bytes(b"first build")
    monkeypatch.setattr(native_svg_adapter, "_load_native_module", lambda: SimpleNamespace(
        __version__="0.3.0", RESULT_SCHEMA_VERSION=4,
        _lumina_svg_core=SimpleNamespace(__file__=str(binary)),
    ))
    source = tmp_path / "source.svg"
    source.write_text("<svg/>", encoding="utf-8")
    options = dict(target_width_mm=190, sampling_precision=0.02,
                   expand_stroke_to_fill=False, gradient_color_bands=None)
    key = _vector_parse_clip_cache_key(str(source), **options)
    artifact = tmp_path / "cache.pickle"
    artifact.write_bytes(_serialize_vector_parse_clip_cache(key, vars(_analysis())))
    binary.write_bytes(b"second distinct build")
    updated = _vector_parse_clip_cache_key(str(source), **options)
    assert key != updated
    assert key[-3:] == updated[-3:] == ("native", "0.3.0", 4)
    assert _load_vector_parse_clip_cache_artifact_by_provenance(
        str(artifact), _vector_parse_clip_cache_provenance(key),
    ) is None
    assert source.is_file()


def test_fractional_tile_boundary_reuses_one_global_partition(monkeypatch):
    from types import SimpleNamespace
    from core.vector_large_format import VectorAnalysisTiler
    from core.vector_engine import VectorProcessor
    domain = SvgCoordinateDomain(2**-20, 1.0, (0.0, 0.0, 3.0, 1.0))
    geometry = domain.restore_precision(box(0, 0, 3, 1))
    analysis = VectorAnalysis(
        shape_data=[{"poly": geometry}], clipped_shapes=[{"geometry": geometry}],
        matched_shapes=[{"geometry": geometry, "recipe": [0], "color": (255, 255, 255)}],
        silhouette=geometry, scale_factor=1.0, bbox=domain.bbox, color_conf={},
        slot_names=["White"], num_channels=1, num_layers=1,
        preview_colors={0: (255, 255, 255, 255)}, svg_coordinate_domain=domain,
    )
    tiles = list(VectorAnalysisTiler(analysis, 3.0, 1.0, 1.50005, 1.0).iter_tiles())
    assert len(tiles) == 2
    global_parts = []
    for tile in tiles:
        restored = deepcopy(tile.analysis)
        record = restored.matched_shapes[0]
        assert restored.svg_coordinate_domain.source_bbox == domain.source_bbox
        assert shapely.get_precision(record["print_geometry"]) == 1.0
        origin = restored.svg_coordinate_domain.frame_origin_mm
        global_parts.append(shapely.affinity.translate(
            record["print_geometry"], xoff=round(origin[0]/0.0001), yoff=round(origin[1]/0.0001),
        ))
    assert global_parts[0].intersection(global_parts[1]).area == 0
    assert shapely.union_all(global_parts, grid_size=1).equals(box(0, 0, 30000, 10000))
    def repeated_projection(*args, **kwargs):
        raise AssertionError("A tile must reuse the global print partition")
    monkeypatch.setattr("core.vector_engine.project_print_regions", repeated_projection)
    processor = VectorProcessor.from_img_processor(SimpleNamespace(), "Material Archive")
    processor.layer_height_mm = 0.08
    volumes = [abs(processor.build_mesh(tile.analysis, 0.0).geometry["White"].volume) for tile in tiles]
    assert sum(volumes) == pytest.approx(3.0 * 0.08)


def test_native_identity_belongs_to_loaded_module_not_replaced_disk_file(monkeypatch, tmp_path):
    from types import ModuleType, SimpleNamespace
    from core import native_svg_adapter
    binary = tmp_path / "native.pyd"
    binary.write_bytes(b"loaded build")
    loaded = ModuleType("native_binary")
    loaded.__file__ = str(binary)
    package = SimpleNamespace(_lumina_svg_core=loaded)
    monkeypatch.setattr(native_svg_adapter, "_load_native_module", lambda: package)
    first = native_svg_adapter.native_build_identity()
    binary.write_bytes(b"replacement on disk, not loaded by this process")
    assert native_svg_adapter.native_build_identity() == first
    replacement = ModuleType("new_native_binary")
    replacement.__file__ = str(binary)
    package._lumina_svg_core = replacement
    assert native_svg_adapter.native_build_identity() != first


def test_native_tile_layout_does_not_materialize_print_geometry(monkeypatch):
    from core.vector_large_format import VectorAnalysisTiler
    def unexpected_projection(*args, **kwargs):
        raise AssertionError("Layout planning must remain independent of print preparation")
    monkeypatch.setattr("core.vector_large_format.project_print_regions", unexpected_projection)
    analysis = _analysis()
    tiler = VectorAnalysisTiler(analysis, 190, 124.53125, 100, 100)
    assert len(tiler.build_tile_specs()) == 4


def test_mixed_slab_domains_cannot_silently_change_the_declared_print_grid():
    from core.vector_layer_geometry import build_vector_layered_volume
    slabs = [
        {"geometry": box(0, 0, 10000, 10000), "height": 0.08, "z_offset": 0.0},
        {"geometry": shapely.set_precision(box(0, 0, 100, 100), 1),
         "height": 0.08, "z_offset": 0.08, PRINT_GRID_KEY: 0.0001},
    ]
    with pytest.raises(ValueError, match="Mixed slab domains"):
        build_vector_layered_volume(slabs, scale_mm_per_svg_unit=1.0)
