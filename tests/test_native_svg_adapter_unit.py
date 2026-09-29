"""Contracts for the sole Lumina-to-lumina-svg-core boundary."""

from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
import mmap as stdlib_mmap
import pickle
from types import SimpleNamespace

import numpy as np
import pytest
import shapely

from core.errors import (
    CoreProcessingError,
    CoreValidationError,
)
from core.native_svg_adapter import (
    NativeSvgFallback,
    NativeSvgGeometry,
    NativeSvgPaintContributor,
    analyze_native_svg,
    native_runtime_identity,
)


@pytest.mark.parametrize("coordinates", [
    [(675884046053, 323293585526), (676603618425, 324732730271),
     (676603618421, 324732730263), (675472861842, 322471217105)],
    [(686369243421, 641036184211), (686163651314, 640933388157),
     (686163651316, 640933388158), (682154605263, 638055098684)],
])
def test_native_coordinate_handoff_preserves_near_collinear_topology(
    monkeypatch: pytest.MonkeyPatch, coordinates,
) -> None:
    """Keep exact contact topology across a non-binary SVG scale.

    非二进制 SVG 比例转换必须保持近共线边界的拓扑。
    """
    result = _native_result()
    vertices = np.asarray(coordinates + [coordinates[0]], dtype=np.int64)
    vertices.setflags(write=False)
    result.raw.coordinates = vertices
    result.grid_to_source_unit = 9.728e-9
    result.bbox = (0.0, 0.0, 9728.0, 6376.0)
    result.scale_factor = 190.0 / 9728.0
    assert shapely.Polygon(vertices).is_valid
    assert not shapely.Polygon(vertices * result.grid_to_source_unit).is_valid
    monkeypatch.setattr(
        "core.native_svg_adapter._load_native_module",
        lambda: _native_module(result),
    )
    outcome = analyze_native_svg("numeric.svg", 190.0, 0.02)
    geometry = outcome.clipped_shapes[0]["geometry"]
    assert geometry.is_valid, shapely.is_valid_reason(geometry)
    domain = outcome.svg_coordinate_domain
    np.testing.assert_array_equal(
        np.rint(np.asarray(geometry.exterior.coords) / domain.grid_size),
        vertices,
    )
    assert outcome.bbox[2] * outcome.scale_factor == pytest.approx(190.0)
    assert domain.source_bbox == result.bbox
    for restored in (deepcopy(outcome), pickle.loads(pickle.dumps(outcome))):
        restored_geometry = restored.clipped_shapes[0]["geometry"]
        assert restored_geometry.is_valid
        assert shapely.get_precision(restored_geometry) == domain.grid_size
        np.testing.assert_array_equal(
            np.asarray(restored_geometry.exterior.coords),
            np.asarray(geometry.exterior.coords),
        )
    assert geometry.area * outcome.scale_factor**2 == pytest.approx(
        shapely.Polygon(vertices).area
        * (result.grid_to_source_unit * result.scale_factor)**2,
        rel=1e-12,
    )


@dataclass
class _FakeCollection:
    coordinates: np.ndarray
    ring_offsets: np.ndarray
    polygon_offsets: np.ndarray
    geometry_offsets: np.ndarray
    hole_parent: np.ndarray
    rgba: np.ndarray
    rgba_f64: np.ndarray
    draw_indices: np.ndarray
    source_indices: np.ndarray
    source_kinds: np.ndarray
    contributor_offsets: np.ndarray
    contributor_draw_indices: np.ndarray
    contributor_source_indices: np.ndarray
    contributor_source_kinds: np.ndarray
    contributor_weights: np.ndarray

    @property
    def geometry_count(self) -> int:
        return len(self.geometry_offsets) - 1

    @property
    def component_count(self) -> int:
        return len(self.polygon_offsets) - 1

    @property
    def hole_count(self) -> int:
        return int(np.count_nonzero(self.hole_parent >= 0))


@dataclass
class _FakeUnprintableFragments:
    reason_codes: tuple[str, ...]
    reason_ids: np.ndarray
    rgba: np.ndarray
    rgba_f64: np.ndarray
    draw_indices: np.ndarray
    source_indices: np.ndarray
    source_kinds: np.ndarray
    subpath_indices: np.ndarray

    @property
    def count(self) -> int:
        return len(self.reason_codes)


def _unprintable_fragments(
    *,
    reason_codes: tuple[str, ...] = (),
    rgba: tuple[tuple[int, int, int, int], ...] = (),
    rgba_f64: tuple[tuple[float, float, float, float], ...] | None = None,
    draw_indices: tuple[int, ...] = (),
    source_indices: tuple[int, ...] = (),
    source_kinds: tuple[int, ...] = (),
    subpath_indices: tuple[int, ...] = (),
) -> _FakeUnprintableFragments:
    if rgba_f64 is None:
        rgba_f64 = tuple(
            tuple(component / 255.0 for component in color)
            for color in rgba
        )
    values = _FakeUnprintableFragments(
        reason_codes=reason_codes,
        reason_ids=np.arange(len(reason_codes), dtype=np.int32),
        rgba=np.asarray(rgba, dtype=np.uint8).reshape((-1, 4)),
        rgba_f64=np.asarray(rgba_f64, dtype=np.float64).reshape((-1, 4)),
        draw_indices=np.asarray(draw_indices, dtype=np.int32),
        source_indices=np.asarray(source_indices, dtype=np.int32),
        source_kinds=np.asarray(source_kinds, dtype=np.int32),
        subpath_indices=np.asarray(subpath_indices, dtype=np.int32),
    )
    for value in vars(values).values():
        if isinstance(value, np.ndarray):
            value.setflags(write=False)
    return values


def _collection(
    *,
    source_kind: int = 0,
    rgba: tuple[int, int, int, int] = (255, 0, 0, 255),
    rgba_f64: tuple[float, float, float, float] = (1.0, 0.0, 0.0, 1.0),
    draw_index: int = 7,
    source_index: int = 3,
    contributors: tuple[tuple[int, int, int, float], ...] | None = None,
) -> _FakeCollection:
    if contributors is None:
        contributors = ((draw_index, source_index, source_kind, rgba_f64[3]),)
    collection = _FakeCollection(
        coordinates=np.asarray(
            [[0, 0], [100, 0], [100, 50], [0, 50], [0, 0]],
            dtype=np.int64,
        ),
        ring_offsets=np.asarray([0, 5], dtype=np.uint64),
        polygon_offsets=np.asarray([0, 1], dtype=np.uint64),
        geometry_offsets=np.asarray([0, 1], dtype=np.uint64),
        hole_parent=np.asarray([-1], dtype=np.int64),
        rgba=np.asarray([rgba], dtype=np.uint8),
        rgba_f64=np.asarray([rgba_f64], dtype=np.float64),
        draw_indices=np.asarray([draw_index], dtype=np.int32),
        source_indices=np.asarray([source_index], dtype=np.int32),
        source_kinds=np.asarray([source_kind], dtype=np.int32),
        contributor_offsets=np.asarray(
            [0, len(contributors)], dtype=np.uint64
        ),
        contributor_draw_indices=np.asarray(
            [item[0] for item in contributors], dtype=np.int32
        ),
        contributor_source_indices=np.asarray(
            [item[1] for item in contributors], dtype=np.int32
        ),
        contributor_source_kinds=np.asarray(
            [item[2] for item in contributors], dtype=np.int32
        ),
        contributor_weights=np.asarray(
            [item[3] for item in contributors], dtype=np.float64
        ),
    )
    for value in vars(collection).values():
        value.setflags(write=False)
    return collection


def _empty_collection() -> _FakeCollection:
    collection = _FakeCollection(
        coordinates=np.empty((0, 2), dtype=np.int64),
        ring_offsets=np.asarray([0], dtype=np.uint64),
        polygon_offsets=np.asarray([0], dtype=np.uint64),
        geometry_offsets=np.asarray([0], dtype=np.uint64),
        hole_parent=np.empty((0,), dtype=np.int64),
        rgba=np.empty((0, 4), dtype=np.uint8),
        rgba_f64=np.empty((0, 4), dtype=np.float64),
        draw_indices=np.empty((0,), dtype=np.int32),
        source_indices=np.empty((0,), dtype=np.int32),
        source_kinds=np.empty((0,), dtype=np.int32),
        contributor_offsets=np.asarray([0], dtype=np.uint64),
        contributor_draw_indices=np.empty((0,), dtype=np.int32),
        contributor_source_indices=np.empty((0,), dtype=np.int32),
        contributor_source_kinds=np.empty((0,), dtype=np.int32),
        contributor_weights=np.empty((0,), dtype=np.float64),
    )
    for value in vars(collection).values():
        value.setflags(write=False)
    return collection


def _two_paint_collection() -> _FakeCollection:
    collection = _FakeCollection(
        coordinates=np.asarray(
            [
                [0, 0],
                [100, 0],
                [100, 50],
                [0, 50],
                [0, 0],
                [0, 0],
                [100, 0],
                [100, 50],
                [0, 50],
                [0, 0],
            ],
            dtype=np.int64,
        ),
        ring_offsets=np.asarray([0, 5, 10], dtype=np.uint64),
        polygon_offsets=np.asarray([0, 1, 2], dtype=np.uint64),
        geometry_offsets=np.asarray([0, 1, 2], dtype=np.uint64),
        hole_parent=np.asarray([-1, -1], dtype=np.int64),
        rgba=np.asarray(
            [[255, 0, 0, 128], [0, 0, 255, 128]], dtype=np.uint8
        ),
        rgba_f64=np.asarray(
            [[1.0, 0.0, 0.0, 0.5], [0.0, 0.0, 1.0, 0.5]],
            dtype=np.float64,
        ),
        draw_indices=np.asarray([0, 1], dtype=np.int32),
        source_indices=np.asarray([4, 5], dtype=np.int32),
        source_kinds=np.asarray([0, 0], dtype=np.int32),
        contributor_offsets=np.asarray([0, 1, 2], dtype=np.uint64),
        contributor_draw_indices=np.asarray([0, 1], dtype=np.int32),
        contributor_source_indices=np.asarray([4, 5], dtype=np.int32),
        contributor_source_kinds=np.asarray([0, 0], dtype=np.int32),
        contributor_weights=np.asarray([0.5, 0.5], dtype=np.float64),
    )
    for value in vars(collection).values():
        value.setflags(write=False)
    return collection


def _collection_with_tiny_component() -> _FakeCollection:
    collection = _FakeCollection(
        coordinates=np.asarray(
            [
                [0, 0],
                [1000, 0],
                [1000, 1000],
                [0, 1000],
                [0, 0],
                [2000, 2000],
                [2001, 2000],
                [2001, 2001],
                [2000, 2001],
                [2000, 2000],
            ],
            dtype=np.int64,
        ),
        ring_offsets=np.asarray([0, 5, 10], dtype=np.uint64),
        polygon_offsets=np.asarray([0, 1, 2], dtype=np.uint64),
        geometry_offsets=np.asarray([0, 2], dtype=np.uint64),
        hole_parent=np.asarray([-1, -1], dtype=np.int64),
        rgba=np.asarray([[18, 52, 86, 255]], dtype=np.uint8),
        rgba_f64=np.asarray(
            [[18 / 255, 52 / 255, 86 / 255, 1.0]], dtype=np.float64
        ),
        draw_indices=np.asarray([7], dtype=np.int32),
        source_indices=np.asarray([3], dtype=np.int32),
        source_kinds=np.asarray([0], dtype=np.int32),
        contributor_offsets=np.asarray([0, 1], dtype=np.uint64),
        contributor_draw_indices=np.asarray([7], dtype=np.int32),
        contributor_source_indices=np.asarray([3], dtype=np.int32),
        contributor_source_kinds=np.asarray([0], dtype=np.int32),
        contributor_weights=np.asarray([1.0], dtype=np.float64),
    )
    for value in vars(collection).values():
        value.setflags(write=False)
    return collection


def _native_result(
    *,
    status: str = "supported",
    reason_code: str = "",
    source_kind: int = 0,
    image_vectorizer_origin: bool = False,
) -> SimpleNamespace:
    collection = _collection(source_kind=source_kind)
    return SimpleNamespace(
        status=status,
        reason_code=reason_code,
        schema_version=4,
        input_paint_count=1,
        bbox=(10.0, 20.0, 100.0, 50.0),
        viewport_bounds=(5.0, 6.0, 80.0, 40.0),
        image_vectorizer_origin=image_vectorizer_origin,
        scale_factor=0.2,
        grid_to_source_unit=1.0,
        recorder_seconds=0.01,
        kernel_seconds=0.02,
        bounds_seconds=0.001,
        replay_seconds=0.002,
        topology_seconds=0.003,
        normalization_raw_seconds=0.004,
        composite_seconds=0.005,
        normalization_visible_seconds=0.006,
        export_seconds=0.007,
        replay_worker_count=4,
        result_conversion_seconds=0.003,
        raw=collection,
        visible=collection,
        silhouette=collection,
        unprintable_fragments=_unprintable_fragments(),
    )


def _native_module(
    result: SimpleNamespace,
    calls: list[tuple[object, ...]] | None = None,
) -> SimpleNamespace:
    def analyze_svg(*args: object) -> SimpleNamespace:
        if calls is not None:
            calls.append(args)
        return result

    return SimpleNamespace(
        __version__="0.3.0",
        RESULT_SCHEMA_VERSION=4,
        analyze_svg=analyze_svg,
    )


def test_supported_result_preserves_lumina_coordinate_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "core.native_svg_adapter._load_native_module",
        lambda: _native_module(_native_result()),
    )

    outcome = analyze_native_svg(
        "fixture.svg",
        target_width_mm=20.0,
        tolerance_mm=0.02,
        expand_stroke_to_fill=False,
    )

    assert isinstance(outcome, NativeSvgGeometry)
    assert outcome.bbox == (10.0, 20.0, 100.0, 50.0)
    assert outcome.scale_factor == pytest.approx(0.2)
    assert outcome.shape_data[0]["poly"].bounds == pytest.approx(
        (0.0, 0.0, 100.0, 50.0)
    )
    assert outcome.clipped_shapes[0]["geometry"].bounds == pytest.approx(
        (0.0, 0.0, 100.0, 50.0)
    )
    assert outcome.clipped_shapes[0]["color"] == (255, 0, 0)
    assert outcome.shape_data[0]["rgba"] == (255, 0, 0, 255)
    assert outcome.shape_data[0]["rgba_f64"] == (1.0, 0.0, 0.0, 1.0)
    assert outcome.shape_data[0]["native_paint_index"] == 7
    assert outcome.shape_data[0]["native_source_index"] == 3
    assert outcome.shape_data[0]["native_paint_id"] == (3, 7)
    assert outcome.shape_data[0]["native_paint_contributors"] == (
        NativeSvgPaintContributor(
            native_draw_order=7,
            native_source_index=3,
            source_kind="fill",
            weight=1.0,
        ),
    )
    assert outcome.clipped_shapes[0]["rgba"] == (255, 0, 0, 255)
    assert outcome.clipped_shapes[0]["rgba_f64"] == (
        1.0,
        0.0,
        0.0,
        1.0,
    )
    assert outcome.clipped_shapes[0]["native_paint_index"] == 7
    assert outcome.clipped_shapes[0]["native_source_index"] == 3
    assert outcome.clipped_shapes[0]["native_paint_id"] == (3, 7)
    assert outcome.clipped_shapes[0]["native_component_index"] == 0
    assert outcome.clipped_shapes[0]["geometry_normalized"] is True
    assert outcome.geometry_backend == "native"
    assert outcome.stage_timings["native_bounds_s"] == 0.001
    assert outcome.stage_timings["native_replay_s"] == 0.002
    assert outcome.stage_timings["native_topology_s"] == 0.003
    assert outcome.stage_timings["native_normalize_raw_s"] == 0.004
    assert outcome.stage_timings["native_composite_s"] == 0.005
    assert outcome.stage_timings["native_normalize_visible_s"] == 0.006
    assert outcome.stage_timings["native_export_s"] == 0.007


def test_adapter_preserves_every_native_component_without_area_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _native_result()
    collection = _collection_with_tiny_component()
    result.grid_to_source_unit = 0.001
    result.raw = collection
    result.visible = collection
    result.silhouette = collection
    monkeypatch.setattr(
        "core.native_svg_adapter._load_native_module",
        lambda: _native_module(result),
    )

    outcome = analyze_native_svg("fixture.svg", 20.0, 0.02)

    assert isinstance(outcome, NativeSvgGeometry)
    assert len(outcome.shape_data) == 1
    assert len(outcome.shape_data[0]["poly"].geoms) == 2
    assert len(outcome.clipped_shapes) == 2
    assert sorted(
        float(item["geometry"].area)
        * outcome.svg_coordinate_domain.source_units_per_unit**2
        for item in outcome.clipped_shapes
    ) == pytest.approx([0.000001, 1.0])
    assert {
        item["native_component_index"] for item in outcome.clipped_shapes
    } == {0, 1}


def test_adapter_preserves_composite_rgba_and_source_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _native_result()
    result.input_paint_count = 2
    result.raw = _two_paint_collection()
    result.visible = _collection(
        source_kind=3,
        rgba=(85, 0, 170, 191),
        rgba_f64=(1 / 3, 0.0, 2 / 3, 0.75),
        draw_index=-1,
        source_index=-1,
        contributors=(
            (0, 4, 0, 0.25),
            (1, 5, 0, 0.5),
        ),
    )
    monkeypatch.setattr(
        "core.native_svg_adapter._load_native_module",
        lambda: _native_module(result),
    )

    outcome = analyze_native_svg("fixture.svg", 20.0, 0.02)

    assert isinstance(outcome, NativeSvgGeometry)
    item = outcome.clipped_shapes[0]
    assert item["source_kind"] == "composite"
    assert item["rgba"] == (85, 0, 170, 191)
    assert item["rgba_f64"] == pytest.approx(
        (1 / 3, 0.0, 2 / 3, 0.75), abs=1e-15
    )
    assert item["native_draw_order"] == -1
    assert item["native_source_index"] == -1
    assert item["native_paint_id"] is None
    assert item["native_paint_contributors"] == (
        NativeSvgPaintContributor(0, 4, "fill", 0.25),
        NativeSvgPaintContributor(1, 5, "fill", 0.5),
    )


@pytest.mark.parametrize(
    ("contributors", "rgba", "rgba_f64"),
    [
        (
            ((0, 4, 0, 0.25), (2, 6, 0, 0.5)),
            (85, 0, 170, 191),
            (1 / 3, 0.0, 2 / 3, 0.75),
        ),
        (
            ((0, 4, 0, 0.25), (1, 5, 0, 0.5)),
            (0, 255, 0, 191),
            (0.0, 1.0, 0.0, 0.75),
        ),
    ],
)
def test_adapter_rejects_visible_provenance_that_disagrees_with_raw_paints(
    monkeypatch: pytest.MonkeyPatch,
    contributors: tuple[tuple[int, int, int, float], ...],
    rgba: tuple[int, int, int, int],
    rgba_f64: tuple[float, float, float, float],
) -> None:
    result = _native_result()
    result.input_paint_count = 2
    result.raw = _two_paint_collection()
    result.visible = _collection(
        source_kind=3,
        rgba=rgba,
        rgba_f64=rgba_f64,
        draw_index=-1,
        source_index=-1,
        contributors=contributors,
    )
    monkeypatch.setattr(
        "core.native_svg_adapter._load_native_module",
        lambda: _native_module(result),
    )

    with pytest.raises(CoreProcessingError) as error:
        analyze_native_svg("fixture.svg", 20.0, 0.02)

    assert error.value.reason_code == "invalid_provenance_schema"


def test_adapter_keeps_valid_area_with_partial_alpha_line_fragment(
    tmp_path,
) -> None:
    svg_path = tmp_path / "partial-alpha-fragment.svg"
    svg_path.write_text(
        "<svg viewBox='0 0 10 10'>"
        "<rect width='10' height='10' fill='red'/>"
        "<path d='M0 5H10' fill='rgb(1,2,3)' fill-opacity='.5'/>"
        "</svg>",
        encoding="utf-8",
    )

    outcome = analyze_native_svg(str(svg_path), 10.0, 0.02)

    assert isinstance(outcome, NativeSvgGeometry)
    assert len(outcome.clipped_shapes) == 1
    assert len(outcome.unprintable_fragments) == 1
    fragment = outcome.unprintable_fragments[0]
    assert fragment.reason_code == "line_only"
    assert fragment.rgba == (1, 2, 3, 128)
    assert fragment.rgba_f64 == pytest.approx(
        (1 / 255, 2 / 255, 3 / 255, 0.5), abs=1e-15
    )


def test_adapter_preserves_unprintable_fragment_identity_and_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _native_result()
    result.input_paint_count = 2
    result.unprintable_fragments = _unprintable_fragments(
        reason_codes=("line_only",),
        rgba=((18, 52, 86, 255),),
        rgba_f64=((18 / 255, 52 / 255, 86 / 255, 0.99999999),),
        draw_indices=(1,),
        source_indices=(9,),
        source_kinds=(0,),
        subpath_indices=(2,),
    )
    monkeypatch.setattr(
        "core.native_svg_adapter._load_native_module",
        lambda: _native_module(result),
    )

    outcome = analyze_native_svg("fixture.svg", 20.0, 0.02)

    assert isinstance(outcome, NativeSvgGeometry)
    assert len(outcome.unprintable_fragments) == 1
    fragment = outcome.unprintable_fragments[0]
    assert fragment.reason_code == "line_only"
    assert fragment.rgba == (18, 52, 86, 255)
    assert fragment.rgba_f64 == pytest.approx(
        (18 / 255, 52 / 255, 86 / 255, 0.99999999), abs=1e-15
    )
    assert fragment.native_paint_id == (9, 1)
    assert fragment.source_kind == "fill"
    assert fragment.subpath_index == 2
    assert outcome.stage_timings["native_input_paint_count"] == 2
    assert outcome.stage_timings["native_output_paint_count"] == 1
    assert outcome.stage_timings["native_hole_count"] == 0
    assert outcome.stage_timings["native_unprintable_fragment_count"] == 1
    assert outcome.stage_timings["native_replay_worker_count"] == 4
    assert outcome.stage_timings["native_unprintable_reasons"] == {
        "line_only": 1
    }


def test_adapter_defaults_worker_telemetry_for_older_schema_four_wheel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _native_result()
    del result.replay_worker_count
    monkeypatch.setattr(
        "core.native_svg_adapter._load_native_module",
        lambda: _native_module(result),
    )

    outcome = analyze_native_svg("fixture.svg", 20.0, 0.02)

    assert isinstance(outcome, NativeSvgGeometry)
    assert outcome.stage_timings["native_replay_worker_count"] == 1


def test_adapter_keeps_composite_area_collapse_without_fabricated_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _native_result()
    result.input_paint_count = 2
    result.unprintable_fragments = _unprintable_fragments(
        reason_codes=("area_collapse",),
        rgba=((85, 0, 170, 191),),
        rgba_f64=((1 / 3, 0.0, 2 / 3, 0.75),),
        draw_indices=(-1,),
        source_indices=(-1,),
        source_kinds=(3,),
        subpath_indices=(-1,),
    )
    monkeypatch.setattr(
        "core.native_svg_adapter._load_native_module",
        lambda: _native_module(result),
    )

    outcome = analyze_native_svg("fixture.svg", 20.0, 0.02)

    assert isinstance(outcome, NativeSvgGeometry)
    fragment = outcome.unprintable_fragments[0]
    assert fragment.reason_code == "area_collapse"
    assert fragment.source_kind == "composite"
    assert fragment.native_draw_order == -1
    assert fragment.native_source_index == -1
    assert fragment.native_paint_id is None


def test_unknown_native_source_kind_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "core.native_svg_adapter._load_native_module",
        lambda: _native_module(_native_result(source_kind=99)),
    )

    with pytest.raises(CoreProcessingError) as error:
        analyze_native_svg("fixture.svg", 20.0, 0.02)

    assert error.value.reason_code == "invalid_source_schema"


@pytest.mark.parametrize(
    ("field_name", "dtype", "reason_code"),
    [
        ("rgba", np.int16, "invalid_material_schema"),
        ("rgba_f64", np.float32, "invalid_material_schema"),
        ("draw_indices", np.int64, "invalid_draw_schema"),
        ("source_indices", np.int64, "invalid_draw_schema"),
        ("source_kinds", np.int64, "invalid_source_schema"),
        (
            "contributor_offsets",
            np.int64,
            "invalid_provenance_schema",
        ),
        (
            "contributor_weights",
            np.float32,
            "invalid_provenance_schema",
        ),
    ],
)
def test_native_paint_metadata_with_wrong_dtype_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    field_name: str,
    dtype: type[np.generic],
    reason_code: str,
) -> None:
    result = _native_result()
    collection = result.raw
    setattr(collection, field_name, getattr(collection, field_name).astype(dtype))
    monkeypatch.setattr(
        "core.native_svg_adapter._load_native_module",
        lambda: _native_module(result),
    )

    with pytest.raises(CoreProcessingError) as error:
        analyze_native_svg("fixture.svg", 20.0, 0.02)

    assert error.value.reason_code == reason_code


@pytest.mark.parametrize(
    ("mutation", "reason_code"),
    [
        (
            lambda collection: setattr(
                collection,
                "coordinates",
                np.asfortranarray(collection.coordinates),
            ),
            "invalid_coordinate_schema",
        ),
        (
            lambda collection: setattr(
                collection,
                "ring_offsets",
                collection.ring_offsets.astype(np.int64),
            ),
            "invalid_offset_schema",
        ),
        (
            lambda collection: setattr(
                collection,
                "hole_parent",
                np.asarray([1], dtype=np.int64),
            ),
            "invalid_hole_schema",
        ),
        (
            lambda collection: collection.coordinates.setflags(write=True),
            "invalid_coordinate_schema",
        ),
    ],
)
def test_native_geometry_array_abi_mismatch_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    mutation,
    reason_code: str,
) -> None:
    result = _native_result()
    mutation(result.raw)
    monkeypatch.setattr(
        "core.native_svg_adapter._load_native_module",
        lambda: _native_module(result),
    )

    with pytest.raises(CoreProcessingError) as error:
        analyze_native_svg("fixture.svg", 20.0, 0.02)

    assert error.value.reason_code == reason_code


@pytest.mark.parametrize("grid_to_source_unit", [0.0, -1.0, float("nan")])
def test_native_invalid_coordinate_domain_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    grid_to_source_unit: float,
) -> None:
    result = _native_result()
    result.grid_to_source_unit = grid_to_source_unit
    monkeypatch.setattr(
        "core.native_svg_adapter._load_native_module",
        lambda: _native_module(result),
    )

    with pytest.raises(CoreProcessingError) as error:
        analyze_native_svg("fixture.svg", 20.0, 0.02)

    assert error.value.reason_code == "invalid_coordinate_domain"


def test_native_result_schema_mismatch_fails_before_array_conversion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _native_result()
    result.schema_version = 1
    monkeypatch.setattr(
        "core.native_svg_adapter._load_native_module",
        lambda: _native_module(result),
    )

    with pytest.raises(CoreProcessingError) as error:
        analyze_native_svg("fixture.svg", 20.0, 0.02)

    assert error.value.reason_code == "native_schema_mismatch"


def test_runtime_identity_uses_exported_native_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _native_module(_native_result())
    module.RESULT_SCHEMA_VERSION = 7
    monkeypatch.setattr(
        "core.native_svg_adapter._load_native_module", lambda: module
    )

    assert native_runtime_identity() == ("native", "0.3.0", 7)


def test_image_vectorizer_origin_preserves_normalized_viewport_anchor(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svg_path = tmp_path / "vectorized.svg"
    svg_path.write_text(
        "<svg data-lumina-origin='image-vectorizer' viewBox='0 0 100 50'>"
        "<rect x='10' y='10' width='20' height='20'/></svg>",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "core.native_svg_adapter._load_native_module",
        lambda: _native_module(
            _native_result(image_vectorizer_origin=True)
        ),
    )

    outcome = analyze_native_svg(str(svg_path), 20.0, 0.02)

    assert isinstance(outcome, NativeSvgGeometry)
    assert outcome.image_vectorizer_bounds is not None
    assert outcome.image_vectorizer_bounds.bounds == pytest.approx(
        (5.0, 6.0, 85.0, 46.0)
    )


def test_adapter_calls_one_vectorized_constructor_per_collection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[object, ...]] = []
    constructor = shapely.from_ragged_array

    def recording_constructor(*args, **kwargs):
        calls.append(args)
        return constructor(*args, **kwargs)

    monkeypatch.setattr(shapely, "from_ragged_array", recording_constructor)
    monkeypatch.setattr(
        "core.native_svg_adapter._load_native_module",
        lambda: _native_module(_native_result()),
    )

    outcome = analyze_native_svg(
        "fixture.svg", 20.0, 0.02, expand_stroke_to_fill=False
    )

    assert isinstance(outcome, NativeSvgGeometry)
    assert len(calls) == 3


@pytest.mark.parametrize(
    "reason_code",
    [
        "unsupported_marker",
        "unsupported_vector_effect",
        "unsupported_external_resource",
        "unsupported_xml_encoding",
        "unsupported_duplicate_id",
        "unsupported_input_precision",
        "unsupported_namespace",
        "unsupported_explicit_inherit",
        "unsupported_href_precedence",
        "unsupported_quadratic",
    ],
)
def test_unsupported_native_result_requests_whole_document_fallback(
    monkeypatch: pytest.MonkeyPatch,
    reason_code: str,
) -> None:
    monkeypatch.setattr(
        "core.native_svg_adapter._load_native_module",
        lambda: _native_module(
            _native_result(status="unsupported", reason_code=reason_code)
        ),
    )

    outcome = analyze_native_svg("fixture.svg", 20.0, 0.02)

    assert outcome == NativeSvgFallback(
        reason_code=reason_code,
        native_version="0.3.0",
    )


def test_native_geometry_capacity_requests_whole_document_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "core.native_svg_adapter._load_native_module",
        lambda: _native_module(
            _native_result(
                status="unsupported",
                reason_code="unsupported_geometry_capacity",
            )
        ),
    )

    outcome = analyze_native_svg("fixture.svg", 20.0, 0.02)

    assert outcome == NativeSvgFallback(
        reason_code="unsupported_geometry_capacity",
        native_version="0.3.0",
    )






def test_adapter_trusts_native_fill_only_stroke_policy_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "core.native_svg_adapter._load_native_module",
        lambda: _native_module(_native_result(source_kind=1)),
    )

    outcome = analyze_native_svg(
        "fixture.svg", 20.0, 0.02, expand_stroke_to_fill=False
    )

    assert isinstance(outcome, NativeSvgGeometry)
    assert outcome.shape_data[0]["source_kind"] == "stroke_only"


def test_adapter_passes_requested_stroke_policy_to_native_core(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        "core.native_svg_adapter._load_native_module",
        lambda: _native_module(_native_result(), calls),
    )

    outcome = analyze_native_svg(
        "fixture.svg", 20.0, 0.02, expand_stroke_to_fill=False
    )

    assert calls == [("fixture.svg", 20.0, 0.02, False)]
    assert isinstance(outcome, NativeSvgGeometry)


def test_enabled_native_stroke_geometry_reaches_vector_analysis_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "core.native_svg_adapter._load_native_module",
        lambda: _native_module(_native_result(source_kind=1)),
    )

    outcome = analyze_native_svg(
        "fixture.svg", 20.0, 0.02, expand_stroke_to_fill=True
    )

    assert isinstance(outcome, NativeSvgGeometry)
    assert outcome.shape_data[0]["source_kind"] == "stroke_only"
    assert outcome.shape_data[0]["rgba"] == (255, 0, 0, 255)


@pytest.mark.parametrize("element", ["style", "use", "svg:use"])
def test_style_and_use_documents_trust_native_capability_result(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    element: str,
) -> None:
    svg_path = tmp_path / "reference-policy.svg"
    svg_path.write_text(f"<svg><{element}/></svg>", encoding="utf-8")
    monkeypatch.setattr(
        "core.native_svg_adapter._load_native_module",
        lambda: _native_module(_native_result()),
    )

    outcome = analyze_native_svg(str(svg_path), 20.0, 0.02)

    assert isinstance(outcome, NativeSvgGeometry)


def test_adapter_does_not_rescan_supported_svg_source(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svg_path = tmp_path / "split-reference.svg"
    svg_path.write_bytes(
        b"<svg>" + b" " * (64 * 1024 - 8) + b"<style/></svg>"
    )
    monkeypatch.setattr(
        "core.native_svg_adapter._load_native_module",
        lambda: _native_module(_native_result()),
    )

    outcome = analyze_native_svg(str(svg_path), 20.0, 0.02)

    assert isinstance(outcome, NativeSvgGeometry)




def test_invalid_svg_maps_to_existing_value_error_behavior(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "core.native_svg_adapter._load_native_module",
        lambda: _native_module(
            _native_result(status="invalid", reason_code="invalid_svg")
        ),
    )

    with pytest.raises(ValueError, match="Invalid SVG"):
        analyze_native_svg("fixture.svg", 20.0, 0.02)


def test_valid_native_empty_result_raises_existing_value_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "core.native_svg_adapter._load_native_module",
        lambda: _native_module(
            _native_result(status="invalid", reason_code="empty_geometry")
        ),
    )

    with pytest.raises(ValueError, match="No valid shapes found in SVG"):
        analyze_native_svg("fixture.svg", 20.0, 0.02)


def test_supported_fragment_only_result_raises_existing_value_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _native_result()
    empty = _empty_collection()
    result.input_paint_count = 1
    result.raw = empty
    result.visible = empty
    result.silhouette = empty
    result.unprintable_fragments = _unprintable_fragments(
        reason_codes=("line_only",),
        rgba=((255, 0, 0, 255),),
        draw_indices=(0,),
        source_indices=(0,),
        source_kinds=(0,),
        subpath_indices=(0,),
    )
    monkeypatch.setattr(
        "core.native_svg_adapter._load_native_module",
        lambda: _native_module(result),
    )

    with pytest.raises(ValueError, match="No valid shapes found in SVG"):
        analyze_native_svg("fixture.svg", 20.0, 0.02)


def test_numeric_range_error_is_a_core_validation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "core.native_svg_adapter._load_native_module",
        lambda: _native_module(
            _native_result(status="invalid", reason_code="numeric_range_error")
        ),
    )

    with pytest.raises(CoreValidationError, match="numeric range"):
        analyze_native_svg("fixture.svg", 20.0, 0.02)


def test_native_internal_error_is_not_silently_reparsed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "core.native_svg_adapter._load_native_module",
        lambda: _native_module(
            _native_result(status="invalid", reason_code="native_geometry_error")
        ),
    )

    with pytest.raises(CoreProcessingError, match="native SVG"):
        analyze_native_svg("fixture.svg", 20.0, 0.02)
