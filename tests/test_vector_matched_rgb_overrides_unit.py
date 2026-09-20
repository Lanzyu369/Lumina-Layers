"""Unit tests for vector-mode region-replacement propagation.
矢量模式区域替换在生成阶段是否正确回写到 ``VectorAnalysis``。

These tests cover the public helper ``apply_matched_rgb_overrides_to_analysis``
which is the bridge between (a) ``cache.matched_rgb`` mutated by
``/region-replace`` and ``/region-replace-batch`` and (b) the SVG-native
``_run_vector_branch``. Without this helper, region/multi-select edits
made through ColorWorkstation only show up in 2D / GLB previews and are
silently dropped from the generated 3MF.

测试覆盖 ``apply_matched_rgb_overrides_to_analysis``：当用户在 2D 预览
里通过 ``/region-replace`` 把某个像素区域改色后，生成阶段必须把那段
改色回写到 ``VectorAnalysis.matched_shapes``，否则 3MF 不会反映用户改动。
"""

from __future__ import annotations

import copy
import gc
import hashlib
import inspect
import importlib.util
import json
import logging
import os
import sys
import types
import weakref

import numpy as np
import pytest
from scipy.spatial import cKDTree
from shapely.geometry import (
    GeometryCollection,
    LineString,
    MultiPolygon,
    Polygon,
    box,
)

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

# Load core.vector_engine by file only when this process has not imported the
# canonical module yet, so the isolated load never replaces an object that other
# test modules already bound and patch.
# 仅在尚未导入标准模块时按文件加载，避免用副本替换其它测试模块已绑定并打补丁的
# 模块对象。
if "core.vector_engine" in sys.modules:
    _ve = sys.modules["core.vector_engine"]
else:
    _spec = importlib.util.spec_from_file_location(
        "core.vector_engine",
        os.path.join(_ROOT, "core", "vector_engine.py"),
    )
    _ve = importlib.util.module_from_spec(_spec)
    if "core" not in sys.modules:
        _pkg = types.ModuleType("core")
        _pkg.__path__ = [os.path.join(_ROOT, "core")]
        sys.modules["core"] = _pkg
    sys.modules["core.vector_engine"] = _ve
    setattr(sys.modules["core"], "vector_engine", _ve)
    assert _spec.loader is not None
    _spec.loader.exec_module(_ve)

VectorAnalysis = _ve.VectorAnalysis
apply_matched_rgb_overrides_to_analysis = getattr(
    _ve, "apply_matched_rgb_overrides_to_analysis", None
)


def test_runtime_candidate_does_not_share_a_full_canvas_oracle() -> None:
    assert not hasattr(
        _ve,
        "_apply_matched_rgb_overrides_full_canvas_reference",
    )
    implementation = getattr(
        _ve,
        "_apply_matched_rgb_overrides_to_analysis_impl",
    )
    assert "use_roi" not in inspect.signature(implementation).parameters


def _attach_caplog(caplog: pytest.LogCaptureFixture, logger_name: str, level: int) -> logging.Logger:
    """Attach pytest's capture handler to a non-propagating Lumina logger."""
    logger = logging.getLogger(logger_name)
    logger.addHandler(caplog.handler)
    caplog.set_level(level, logger=logger_name)
    return logger


# ---------------------------------------------------------------------------
# Minimal LUT fixture: 4 RGB anchors mapped to 4 distinct channel ids so the
# generated recipe makes the active channel obvious.
# ---------------------------------------------------------------------------


def _build_fake_img_processor() -> object:
    """Construct a SimpleNamespace-style stub providing the attributes
    ``_match_colors`` and the new override helper need.

    构造 ``_match_colors`` 与新增 helper 需要的最小 LUT 接口：
    ``lut_rgb``、``ref_stacks``、``kdtree`` 与 ``_rgb_to_lab``。
    """

    lut_rgb = np.array(
        [
            [255, 255, 255],  # idx 0 (white / backing)
            [255, 0, 0],      # idx 1 (red)
            [0, 255, 0],      # idx 2 (green)
            [0, 0, 255],      # idx 3 (blue)
        ],
        dtype=np.uint8,
    )

    # Each LUT entry's ref_stacks[idx] gives a per-layer channel id. Five
    # layers per entry, all pointing at that LUT row, so a recipe lookup
    # for matched_rgb == lut_rgb[i] yields a recipe of [i, i, i, i, i].
    # 每条 LUT 的 ref_stacks 行让所有层都用同一个通道，方便测试断言。
    ref_stacks = np.array(
        [[0, 0, 0, 0, 0], [1, 1, 1, 1, 1], [2, 2, 2, 2, 2], [3, 3, 3, 3, 3]],
        dtype=np.int16,
    )

    rgb_for_lab = np.expand_dims(lut_rgb, axis=0)  # (1, N, 3)
    import cv2

    bgr = cv2.cvtColor(rgb_for_lab, cv2.COLOR_RGB2BGR)
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2Lab).astype(np.float64).reshape(-1, 3)
    kdtree = cKDTree(lab)

    class _StubProcessor:
        def __init__(self) -> None:
            self.lut_rgb = lut_rgb
            self.ref_stacks = ref_stacks
            self.kdtree = kdtree

        @staticmethod
        def _rgb_to_lab(rgb_array: np.ndarray) -> np.ndarray:
            arr = np.asarray(rgb_array, dtype=np.uint8)
            if arr.ndim == 1:
                arr = arr.reshape(1, -1)
            arr_3d = arr.reshape(1, -1, 3)
            bgr = cv2.cvtColor(arr_3d, cv2.COLOR_RGB2BGR)
            return cv2.cvtColor(bgr, cv2.COLOR_BGR2Lab).astype(np.float64).reshape(-1, 3)

    return _StubProcessor()


def _make_two_shape_analysis() -> "VectorAnalysis":
    """Build a 10×10 mm canvas with two adjacent halves: top=red, bottom=green.

    构造一个 10×10 mm 画布，上半红、下半绿；scale_factor=1.0 让 ``bbox``
    单位与毫米一致，预览网格密度为默认 10 px/mm，便于断言。
    """
    top = box(0.0, 0.0, 10.0, 5.0)
    bot = box(0.0, 5.0, 10.0, 10.0)

    # ``recipe`` and ``matched_rgb`` mirror the output _match_colors would
    # produce against the fake LUT above (red → idx 1, green → idx 2).
    matched_shapes = [
        {
            "geometry": top,
            "color": (255, 0, 0),
            "matched_rgb": (255, 0, 0),
            "lut_idx": 1,
            "recipe": [1, 1, 1, 1, 1],
        },
        {
            "geometry": bot,
            "color": (0, 255, 0),
            "matched_rgb": (0, 255, 0),
            "lut_idx": 2,
            "recipe": [2, 2, 2, 2, 2],
        },
    ]

    return VectorAnalysis(
        shape_data=[],
        clipped_shapes=[
            {"geometry": top, "color": (255, 0, 0)},
            {"geometry": bot, "color": (0, 255, 0)},
        ],
        matched_shapes=matched_shapes,
        silhouette=None,
        scale_factor=1.0,
        bbox=(0.0, 0.0, 10.0, 10.0),
        color_conf={"slots": ["W", "R", "G", "B"], "preview": {}},
        slot_names=["W", "R", "G", "B"],
        num_channels=4,
        num_layers=5,
        preview_colors={
            0: [255, 255, 255, 255],
            1: [255, 0, 0, 255],
            2: [0, 255, 0, 255],
            3: [0, 0, 255, 255],
        },
    )


def _build_grid_arrays(
    analysis: "VectorAnalysis",
    pixels_per_mm: float = 10.0,
) -> tuple[np.ndarray, np.ndarray, int, int]:
    """Return ``(matched_rgb, mask_solid, h_px, w_px)`` aligned with the
    grid ``apply_matched_rgb_overrides_to_analysis`` will reproduce.

    构造与 helper 内部网格一致的 ``matched_rgb`` / ``mask_solid``，
    其中上半填红、下半填绿。
    """
    real_w = float(analysis.bbox[2])
    real_h = float(analysis.bbox[3])
    sf = float(analysis.scale_factor)
    w_mm = real_w * sf
    h_mm = real_h * sf
    w_px = max(1, int(round(w_mm * pixels_per_mm)))
    h_px = max(1, int(round(h_mm * pixels_per_mm)))

    matched_rgb = np.zeros((h_px, w_px, 3), dtype=np.uint8)
    mask_solid = np.zeros((h_px, w_px), dtype=bool)

    half = h_px // 2
    matched_rgb[:half, :, :] = (255, 0, 0)
    matched_rgb[half:, :, :] = (0, 255, 0)
    mask_solid[:, :] = True

    return matched_rgb, mask_solid, h_px, w_px


def _make_compound_analysis(geometry) -> "VectorAnalysis":
    """Build one red source record containing disconnected components."""

    shape = {
        "geometry": geometry,
        "color": (255, 0, 0),
        "matched_rgb": (255, 0, 0),
        "lut_idx": 1,
        "recipe": [1, 1, 1, 1, 1],
        "source_id": "compound-source",
        "draw_order": 7,
    }
    return VectorAnalysis(
        shape_data=[],
        clipped_shapes=[dict(shape)],
        matched_shapes=[shape],
        silhouette=geometry,
        scale_factor=1.0,
        bbox=(0.0, 0.0, 12.0, 4.0),
        color_conf={"slots": ["W", "R", "G", "B"], "preview": {}},
        slot_names=["W", "R", "G", "B"],
        num_channels=4,
        num_layers=5,
        preview_colors={
            0: [255, 255, 255, 255],
            1: [255, 0, 0, 255],
            2: [0, 255, 0, 255],
            3: [0, 0, 255, 255],
        },
    )


def _compound_cache_arrays() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return a red 12x4 mm cache on the helper's 10 px/mm grid."""

    matched_rgb = np.full((40, 120, 3), [255, 0, 0], dtype=np.uint8)
    mask_solid = np.ones((40, 120), dtype=bool)
    material_matrix = np.ones((40, 120, 5), dtype=np.int16)
    return matched_rgb, mask_solid, material_matrix


def _projection_reference_geometries() -> list[object]:
    """Return geometry cases that exercise legacy OpenCV clipping semantics."""

    polygon_with_hole = Polygon(
        [
            (0.25, 0.25),
            (11.75, 0.4),
            (11.45, 7.65),
            (0.4, 7.7),
            (0.25, 0.25),
        ],
        holes=[
            [
                (3.15, 2.2),
                (8.65, 2.35),
                (8.3, 5.8),
                (3.4, 5.65),
                (3.15, 2.2),
            ]
        ],
    )
    disconnected = MultiPolygon(
        [
            box(0.15, 0.2, 2.35, 2.8),
            Polygon(
                [
                    (4.05, 1.1),
                    (11.72, 0.55),
                    (10.8, 7.45),
                    (5.3, 6.9),
                    (4.05, 1.1),
                ]
            ),
        ]
    )
    mixed_collection = GeometryCollection(
        [
            box(0.5, 0.5, 4.25, 6.5),
            box(7.1, 1.2, 11.5, 7.4),
            LineString([(0.0, 7.9), (12.0, 7.9)]),
        ]
    )
    clipped_outside_canvas = MultiPolygon(
        [
            box(-2.4, -1.6, 3.75, 4.55),
            Polygon(
                [
                    (9.45, 5.9),
                    (14.4, 5.5),
                    (13.7, 9.6),
                    (10.15, 8.8),
                    (9.45, 5.9),
                ]
            ),
        ]
    )
    subpixel_polygon = Polygon(
        [
            (0.049, 0.051),
            (0.151, 6.949),
            (6.051, 7.949),
            (11.951, 3.051),
            (11.849, 0.149),
            (0.049, 0.051),
        ]
    )
    fully_outside = MultiPolygon(
        [
            box(-8.0, -8.0, -4.0, -4.0),
            box(20.0, 20.0, 25.0, 25.0),
        ]
    )
    one_pixel_polygon = box(1.01, 1.01, 1.09, 1.09)
    return [
        polygon_with_hole,
        disconnected,
        mixed_collection,
        clipped_outside_canvas,
        subpixel_polygon,
        fully_outside,
        one_pixel_polygon,
    ]


def _make_projection_reference_analysis(geometry) -> "VectorAnalysis":
    shape = {
        "geometry": geometry,
        "color": (255, 0, 0),
        "matched_rgb": (255, 0, 0),
        "height_identity_rgb": (0, 255, 0),
        "lut_idx": 1,
        "recipe": [1, 1, 1, 1, 1],
        "original_recipe": [2, 2, 2, 2, 2],
        "source_id": "reference-corpus",
        "draw_order": 17,
    }
    return VectorAnalysis(
        shape_data=[],
        clipped_shapes=[dict(shape)],
        matched_shapes=[shape],
        silhouette=geometry,
        scale_factor=1.0,
        bbox=(0.0, 0.0, 12.0, 8.0),
        color_conf={"slots": ["W", "R", "G", "B"], "preview": {}},
        slot_names=["W", "R", "G", "B"],
        num_channels=4,
        num_layers=5,
        preview_colors={
            0: [255, 255, 255, 255],
            1: [255, 0, 0, 255],
            2: [0, 255, 0, 255],
            3: [0, 0, 255, 255],
        },
    )


def _projection_reference_arrays() -> tuple[
    np.ndarray,
    np.ndarray,
    np.ndarray,
    np.ndarray,
]:
    """Build deterministic colors, identities, recipes, and background holes."""

    yy, xx = np.indices((80, 120), dtype=np.int32)
    color_indices = (xx + 2 * yy) % 4
    palette = np.asarray(
        [
            [255, 255, 255],
            [255, 0, 0],
            [0, 255, 0],
            [0, 0, 255],
        ],
        dtype=np.uint8,
    )
    matched_rgb = palette[color_indices]
    height_identity_rgb = palette[(color_indices + 1) % 4]
    material_matrix = np.stack(
        [
            color_indices,
            (color_indices + 1) % 4,
            (color_indices + 2) % 4,
            (color_indices + 3) % 4,
            color_indices,
        ],
        axis=-1,
    ).astype(np.int16)
    mask_solid = ((3 * xx + 5 * yy) % 11) != 0
    return matched_rgb, height_identity_rgb, material_matrix, mask_solid


def _normalise_projection_value(value):
    if hasattr(value, "wkb_hex"):
        return ("geometry_wkb_hex", value.wkb_hex)
    if isinstance(value, np.ndarray):
        return (
            "ndarray",
            str(value.dtype),
            tuple(value.shape),
            value.tobytes(),
        )
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return tuple(
            (str(key), _normalise_projection_value(item))
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        )
    if isinstance(value, (list, tuple)):
        return tuple(_normalise_projection_value(item) for item in value)
    return value


def _normalise_projection_shapes(analysis: "VectorAnalysis") -> tuple:
    return tuple(
        _normalise_projection_value(shape)
        for shape in analysis.matched_shapes
    )


def _legacy_full_canvas_mask(
    geometry,
    *,
    canvas_shape: tuple[int, int],
    coord_scale: float,
) -> np.ndarray | None:
    """Frozen pre-ROI rasterizer copied from base SHA 8d26399b."""
    import cv2

    def iter_components(value):
        if value is None or value.is_empty:
            return []
        if value.geom_type == "Polygon":
            return [value]
        if value.geom_type in ("MultiPolygon", "GeometryCollection"):
            components = []
            for child in value.geoms:
                components.extend(iter_components(child))
            return components
        return []

    def points(coords):
        raster_points = np.column_stack(
            [
                coords[:, 0] * coord_scale,
                coords[:, 1] * coord_scale,
            ]
        ).astype(np.int32)
        return raster_points if len(raster_points) >= 3 else None

    region = np.zeros(canvas_shape, dtype=np.uint8)
    painted = False
    for polygon in iter_components(geometry):
        exterior = points(np.asarray(polygon.exterior.coords))
        if exterior is None:
            continue
        cv2.fillPoly(region, [exterior], 255)
        painted = True
        for interior in polygon.interiors:
            hole = points(np.asarray(interior.coords))
            if hole is not None:
                cv2.fillPoly(region, [hole], 0)
    return region.astype(bool) if painted else None


def _projection_snapshot_sha256(analysis: "VectorAnalysis") -> str:
    payload = json.dumps(
        _normalise_projection_shapes(analysis),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "geometry",
    [
        pytest.param(geometry, id=f"geometry-{index}")
        for index, geometry in enumerate(_projection_reference_geometries())
    ],
)
def test_roi_rasterizer_matches_full_canvas_mask_exactly(geometry) -> None:
    """A cropped raster must reconstruct the legacy full-canvas mask exactly."""

    roi_rasterizer = getattr(
        _ve,
        "_rasterize_geometry_roi_mask",
        None,
    )
    assert callable(roi_rasterizer)

    full_mask = _legacy_full_canvas_mask(
        geometry,
        canvas_shape=(80, 120),
        coord_scale=10.0,
    )
    roi_result = roi_rasterizer(
        geometry,
        canvas_shape=(80, 120),
        coord_scale=10.0,
    )

    if full_mask is None:
        assert roi_result is None
        return
    assert roi_result is not None
    y_slice, x_slice, roi_mask = roi_result
    reconstructed = np.zeros_like(full_mask, dtype=bool)
    reconstructed[y_slice, x_slice] = roi_mask
    np.testing.assert_array_equal(reconstructed, full_mask)


def test_roi_rasterizer_matches_seeded_polygon_corpus_exactly() -> None:
    roi_rasterizer = _ve._rasterize_geometry_roi_mask
    rng = np.random.default_rng(20260730)

    for canvas_shape, coord_scale in (
        ((7, 11), 0.75),
        ((80, 120), 10.0),
        ((211, 317), 25.3),
    ):
        for _index in range(64):
            points = rng.uniform(
                low=(-5.0, -4.0),
                high=(17.0, 12.0),
                size=(12, 2),
            )
            geometry = Polygon(points).convex_hull
            full_mask = _legacy_full_canvas_mask(
                geometry,
                canvas_shape=canvas_shape,
                coord_scale=coord_scale,
            )
            roi_result = roi_rasterizer(
                geometry,
                canvas_shape=canvas_shape,
                coord_scale=coord_scale,
            )
            assert full_mask is not None
            assert roi_result is not None
            y_slice, x_slice, roi_mask = roi_result
            reconstructed = np.zeros_like(full_mask, dtype=bool)
            reconstructed[y_slice, x_slice] = roi_mask
            np.testing.assert_array_equal(reconstructed, full_mask)


def test_roi_rasterizer_explicit_fully_outside_and_one_pixel_cases() -> None:
    fully_outside, one_pixel = _projection_reference_geometries()[-2:]

    outside_mask = _legacy_full_canvas_mask(
        fully_outside,
        canvas_shape=(80, 120),
        coord_scale=10.0,
    )
    one_pixel_mask = _legacy_full_canvas_mask(
        one_pixel,
        canvas_shape=(80, 120),
        coord_scale=10.0,
    )

    assert outside_mask is not None
    assert np.count_nonzero(outside_mask) == 0
    assert one_pixel_mask is not None
    assert np.count_nonzero(one_pixel_mask) == 1


@pytest.mark.parametrize(
    ("geometry", "expected_changed", "expected_sha256"),
    [
        pytest.param(
            geometry,
            expected_changed,
            expected_sha256,
            id=f"base-golden-{index}",
        )
        for index, (
            geometry,
            expected_changed,
            expected_sha256,
        ) in enumerate(
            zip(
                _projection_reference_geometries(),
                [1, 2, 2, 2, 1, 0, 1],
                [
                    "f16c4675c94f499284775b2ad6b58d50fef14815b413bfd5b055776572c57e12",
                    "0681b0aa801f7641a8520a4e2dcccaff9cd0a70f2681b25c4195288fc8538c0f",
                    "72e8a0f88bf8a7c8c0b8c8aa922ab57f50d3a246290dd3956afd83cfd72c9b52",
                    "3450b13c1917927aa279b2ed488a02fd6b6a6f972b6d2e23ab5011046afea13b",
                    "37a81835872dfe1958661546a5cea103ae25e557e3928f87db1f564ec66f8d5b",
                    "7d7bb8171b7e959890ad1af340338dd7acb3ee2ecefc9ab53ff0d8e10957d6e1",
                    "8edbc7805e3114c1d1a12e8ec717f61b1a77d11bbfc5cd87963f1bee7cb04b69",
                ],
                strict=True,
            )
        )
    ],
)
def test_roi_projection_matches_independent_base_shape_record_golden(
    geometry,
    expected_changed: int,
    expected_sha256: str,
) -> None:
    """ROI records must match golden output captured from base SHA 8d26399b."""

    candidate_analysis = _make_projection_reference_analysis(geometry)
    (
        matched_rgb,
        height_identity_rgb,
        material_matrix,
        mask_solid,
    ) = _projection_reference_arrays()
    kwargs = {
        "matched_rgb": matched_rgb,
        "height_identity_rgb": height_identity_rgb,
        "material_matrix": material_matrix,
        "mask_solid": mask_solid,
        "img_processor": _build_fake_img_processor(),
        "strict": True,
    }

    candidate_changed = apply_matched_rgb_overrides_to_analysis(
        candidate_analysis,
        **kwargs,
    )

    assert candidate_changed == expected_changed
    assert _projection_snapshot_sha256(candidate_analysis) == expected_sha256


def test_roi_projection_records_bounded_pixel_work_metrics() -> None:
    geometry = MultiPolygon(
        [
            box(0.5, 0.5, 1.5, 1.5),
            box(9.0, 5.0, 11.5, 7.5),
        ]
    )
    analysis = _make_projection_reference_analysis(geometry)
    (
        matched_rgb,
        height_identity_rgb,
        material_matrix,
        mask_solid,
    ) = _projection_reference_arrays()

    apply_matched_rgb_overrides_to_analysis(
        analysis,
        matched_rgb=matched_rgb,
        height_identity_rgb=height_identity_rgb,
        material_matrix=material_matrix,
        mask_solid=mask_solid,
        img_processor=_build_fake_img_processor(),
        strict=True,
    )

    metrics = analysis.matched_rgb_override_metrics
    assert metrics["raster_strategy"] == "roi"
    assert metrics["component_count"] == 2
    assert metrics["full_canvas_pixel_work"] == 2 * 80 * 120
    assert 0 < metrics["roi_pixel_work"] < metrics["full_canvas_pixel_work"]
    assert 0 < metrics["max_roi_pixels"] < 80 * 120
    assert metrics["effective_pixel_count"] > 0
    assert metrics["pixel_work_reduction_ratio"] == pytest.approx(
        metrics["full_canvas_pixel_work"] / metrics["roi_pixel_work"]
    )


def test_dimension_change_projects_only_edited_vector_components() -> None:
    """Old edit pixels map to fresh smooth paths without replacing untouched shapes."""

    edited_geometry = box(1.0, 1.0, 4.0, 4.0)
    untouched_geometry = box(7.0, 2.0, 10.0, 6.0)
    analysis = VectorAnalysis(
        shape_data=[],
        clipped_shapes=[],
        matched_shapes=[
            {
                "geometry": edited_geometry,
                "color": (0, 255, 0),
                "matched_rgb": (0, 255, 0),
                "height_identity_rgb": (0, 255, 0),
                "recipe": [2, 2, 2, 2, 2],
            },
            {
                "geometry": untouched_geometry,
                "color": (0, 0, 255),
                "matched_rgb": (0, 0, 255),
                "height_identity_rgb": (0, 0, 255),
                "recipe": [3, 3, 3, 3, 3],
            },
        ],
        silhouette=edited_geometry.union(untouched_geometry),
        scale_factor=2.0,
        bbox=(0.0, 0.0, 12.0, 8.0),
        color_conf={"slots": ["W", "R", "G", "B"], "preview": {}},
        slot_names=["W", "R", "G", "B"],
        num_channels=4,
        num_layers=5,
        preview_colors={},
    )
    pristine_rgb = np.full((80, 120, 3), [255, 255, 255], dtype=np.uint8)
    edited_rgb = pristine_rgb.copy()
    edited_rgb[10:41, 10:41] = [255, 0, 0]
    pristine_material = np.zeros((80, 120, 5), dtype=np.int16)
    edited_material = pristine_material.copy()
    edited_material[10:41, 10:41] = 1

    changed = apply_matched_rgb_overrides_to_analysis(
        analysis,
        matched_rgb=edited_rgb,
        original_matched_rgb=pristine_rgb,
        height_identity_rgb=pristine_rgb,
        material_matrix=edited_material,
        original_material_matrix=pristine_material,
        mask_solid=np.ones((80, 120), dtype=bool),
        img_processor=_build_fake_img_processor(),
        source_grid_shape=(80, 120),
        strict=True,
    )

    assert changed == 1
    assert tuple(analysis.matched_shapes[0]["matched_rgb"]) == (255, 0, 0)
    assert analysis.matched_shapes[0]["recipe"] == [1, 1, 1, 1, 1]
    assert tuple(analysis.matched_shapes[1]["matched_rgb"]) == (0, 0, 255)
    assert analysis.matched_shapes[1]["recipe"] == [3, 3, 3, 3, 3]


def test_roi_projection_caches_repeated_rgb_lut_queries() -> None:
    geometry = MultiPolygon(
        [
            box(0.5, 0.5, 2.0, 2.0),
            box(4.0, 2.0, 6.0, 4.0),
            box(8.0, 5.0, 11.0, 7.5),
        ]
    )
    analysis = _make_projection_reference_analysis(geometry)
    matched_rgb = np.full((80, 120, 3), [255, 0, 0], dtype=np.uint8)
    identity_rgb = matched_rgb.copy()
    material_matrix = np.ones((80, 120, 5), dtype=np.int16)
    mask_solid = np.ones((80, 120), dtype=bool)
    processor = _build_fake_img_processor()
    original_rgb_to_lab = processor._rgb_to_lab
    original_kdtree = processor.kdtree
    calls = {"rgb_to_lab": 0, "query": 0}

    def _counted_rgb_to_lab(values):
        calls["rgb_to_lab"] += 1
        return original_rgb_to_lab(values)

    class _CountingTree:
        def query(self, values):
            calls["query"] += 1
            return original_kdtree.query(values)

    processor._rgb_to_lab = _counted_rgb_to_lab
    processor.kdtree = _CountingTree()

    apply_matched_rgb_overrides_to_analysis(
        analysis,
        matched_rgb=matched_rgb,
        height_identity_rgb=identity_rgb,
        material_matrix=material_matrix,
        mask_solid=mask_solid,
        img_processor=processor,
        strict=True,
    )

    assert calls == {"rgb_to_lab": 1, "query": 1}


@pytest.mark.parametrize(
    ("row_count", "layer_count", "low", "high"),
    [
        (1, 1, 0, 1),
        (257, 5, -1, 4),
        (513, 10, -1, 16),
        (129, 20, 0, 3),
    ],
)
def test_packed_material_stack_vote_matches_numpy_unique_exactly(
    row_count: int,
    layer_count: int,
    low: int,
    high: int,
) -> None:
    rng = np.random.default_rng(
        20260730 + row_count + layer_count
    )
    stacks = rng.integers(
        low,
        high,
        size=(row_count, layer_count),
        dtype=np.int32,
    )
    if row_count >= 4:
        stacks[1] = stacks[0]
        stacks[3] = stacks[2]

    expected_rows, expected_counts = np.unique(
        stacks,
        axis=0,
        return_counts=True,
    )
    actual_rows, actual_counts, _used_packed = (
        _ve._unique_material_stacks_exact(stacks)
    )

    np.testing.assert_array_equal(actual_rows, expected_rows)
    np.testing.assert_array_equal(actual_counts, expected_counts)


def test_material_stack_uint64_encoding_matches_mixed_radix_reference() -> None:
    stacks = np.asarray(
        [
            [-1, 0, 3, 2],
            [3, 2, 1, -1],
            [0, 0, 0, 0],
        ],
        dtype=np.int32,
    )
    min_value = -1
    radix = 5
    expected = np.asarray(
        [
            sum(
                (int(value) - min_value)
                * (radix ** (stacks.shape[1] - column - 1))
                for column, value in enumerate(row)
            )
            for row in stacks
        ],
        dtype=np.uint64,
    )

    actual = _ve._pack_material_stacks_uint64(
        stacks,
        min_value=min_value,
        radix=radix,
    )

    np.testing.assert_array_equal(actual, expected)


def test_packed_material_stack_vote_preserves_legacy_int32_coercion() -> None:
    stacks = np.asarray(
        [
            [-1, 0, 3, 2],
            [3, 2, 1, -1],
            [0, 0, 0, 0],
        ],
        dtype=np.int8,
    )

    rows, _counts, used_packed = _ve._unique_material_stacks_exact(stacks)

    assert used_packed is True
    assert rows.dtype == np.int32


def test_material_stack_vote_keeps_safe_compact_rows_inside_packer(
    monkeypatch,
) -> None:
    stacks = np.asarray(
        [
            [-1, 0, 3, 2],
            [3, 2, 1, -1],
            [0, 0, 0, 0],
        ],
        dtype=np.int16,
    )
    packed_input_dtypes: list[np.dtype] = []
    original_pack = _ve._pack_material_stacks_uint64

    def recording_pack(rows, *, min_value, radix):
        packed_input_dtypes.append(rows.dtype)
        return original_pack(
            rows,
            min_value=min_value,
            radix=radix,
        )

    monkeypatch.setattr(
        _ve,
        "_pack_material_stacks_uint64",
        recording_pack,
    )

    rows, _counts, used_packed = _ve._unique_material_stacks_exact(stacks)

    assert used_packed is True
    assert packed_input_dtypes == [np.dtype(np.int16)]
    assert rows.dtype == np.int32


def test_material_stack_vote_preserves_legacy_int32_wrap_and_tie_break() -> None:
    stacks = np.asarray(
        [
            [0],
            [2**31],
        ],
        dtype=np.int64,
    )
    legacy_rows, legacy_counts = np.unique(
        stacks.astype(np.int32),
        axis=0,
        return_counts=True,
    )

    rows, counts, _used_packed = _ve._unique_material_stacks_exact(stacks)

    np.testing.assert_array_equal(rows, legacy_rows)
    np.testing.assert_array_equal(counts, legacy_counts)
    assert rows[int(np.argmax(counts))].tolist() == [-(2**31)]


def test_material_stack_vote_coerces_uint64_like_legacy_without_overflow() -> None:
    stacks = np.asarray(
        [
            [0],
            [np.iinfo(np.uint64).max],
            [0],
        ],
        dtype=np.uint64,
    )
    legacy_rows, legacy_counts = np.unique(
        stacks.astype(np.int32),
        axis=0,
        return_counts=True,
    )

    rows, counts, _used_packed = _ve._unique_material_stacks_exact(stacks)

    np.testing.assert_array_equal(rows, legacy_rows)
    np.testing.assert_array_equal(counts, legacy_counts)
    assert rows[int(np.argmax(counts))].tolist() == [0]


@pytest.mark.parametrize(
    ("dtype", "wrapped_value"),
    [
        (np.int64, 2**31),
        (np.uint64, np.iinfo(np.uint64).max),
    ],
)
@pytest.mark.parametrize("strict", [False, True])
def test_public_projection_preserves_legacy_integer_matrix_coercion(
    dtype,
    wrapped_value: int,
    strict: bool,
) -> None:
    analysis = _make_projection_reference_analysis(box(0.0, 0.0, 12.0, 8.0))
    matched_rgb = np.full((80, 120, 3), [255, 0, 0], dtype=np.uint8)
    identity_rgb = matched_rgb.copy()
    mask_solid = np.zeros((80, 120), dtype=bool)
    mask_solid[10, 10:12] = True
    material_matrix = np.zeros((80, 120, 5), dtype=dtype)
    material_matrix[10, 10] = [0, 2, 2, 2, 2]
    material_matrix[10, 11] = [wrapped_value, 3, 3, 3, 3]

    changed = apply_matched_rgb_overrides_to_analysis(
        analysis,
        matched_rgb=matched_rgb,
        height_identity_rgb=identity_rgb,
        material_matrix=material_matrix,
        mask_solid=mask_solid,
        img_processor=_build_fake_img_processor(),
        strict=strict,
    )

    assert changed == 1
    assert analysis.matched_shapes[0]["recipe"] == [3, 3, 3, 3, 3]


def test_packed_material_stack_vote_uses_one_numpy_code_buffer(
    monkeypatch,
) -> None:
    stacks = np.asarray(
        [
            [2, 0, 0],
            [1, 9, 9],
            [2, 0, 0],
            [3, 1, 4],
            [1, 9, 9],
        ],
        dtype=np.int8,
    )
    chunk_sizes: list[int] = []
    original_pack = _ve._pack_material_stacks_uint64

    def _recording_pack(rows, *, min_value, radix):
        chunk_sizes.append(int(rows.shape[0]))
        return original_pack(
            rows,
            min_value=min_value,
            radix=radix,
        )

    # A former implementation split the rows into tiny chunks and accumulated
    # Python ``dict[int, int]`` entries. Across thousands of components those
    # short-lived objects made the interpreter retain hundreds of MiB. Keep
    # this stale knob present during the regression test to prove it is ignored.
    monkeypatch.setattr(
        _ve,
        "_MATERIAL_STACK_PACK_CHUNK_ROWS",
        2,
        raising=False,
    )
    monkeypatch.setattr(
        _ve,
        "_pack_material_stacks_uint64",
        _recording_pack,
    )

    expected_rows, expected_counts = np.unique(
        stacks,
        axis=0,
        return_counts=True,
    )
    actual_rows, actual_counts, used_packed = (
        _ve._unique_material_stacks_exact(stacks)
    )

    assert chunk_sizes == [len(stacks)]
    assert used_packed is True
    np.testing.assert_array_equal(actual_rows, expected_rows)
    np.testing.assert_array_equal(actual_counts, expected_counts)


def test_packed_material_stack_vote_stays_numpy_on_high_cardinality(
    monkeypatch,
) -> None:
    stacks = np.asarray(
        [
            [0, 0],
            [0, 1],
            [1, 0],
            [1, 1],
        ],
        dtype=np.int8,
    )
    monkeypatch.setattr(
        _ve,
        "_MATERIAL_STACK_PACK_MAX_UNIQUE",
        2,
        raising=False,
    )

    expected_rows, expected_counts = np.unique(
        stacks,
        axis=0,
        return_counts=True,
    )
    actual_rows, actual_counts, used_packed = (
        _ve._unique_material_stacks_exact(stacks)
    )

    assert used_packed is True
    np.testing.assert_array_equal(actual_rows, expected_rows)
    np.testing.assert_array_equal(actual_counts, expected_counts)


def test_packed_material_stack_vote_preserves_lexicographic_tie_break() -> None:
    stacks = np.asarray(
        [
            [2, 0, 0],
            [1, 9, 9],
            [2, 0, 0],
            [1, 9, 9],
        ],
        dtype=np.int32,
    )

    rows, counts, used_packed = _ve._unique_material_stacks_exact(stacks)
    dominant = rows[int(np.argmax(counts))]

    assert used_packed is True
    assert dominant.tolist() == [1, 9, 9]


def test_material_stack_vote_falls_back_exactly_when_uint64_would_overflow() -> None:
    rng = np.random.default_rng(20260730)
    stacks = rng.integers(
        0,
        16,
        size=(128, 40),
        dtype=np.int32,
    )
    expected_rows, expected_counts = np.unique(
        stacks,
        axis=0,
        return_counts=True,
    )

    actual_rows, actual_counts, used_packed = (
        _ve._unique_material_stacks_exact(stacks)
    )

    assert used_packed is False
    np.testing.assert_array_equal(actual_rows, expected_rows)
    np.testing.assert_array_equal(actual_counts, expected_counts)


@pytest.mark.skipif(
    apply_matched_rgb_overrides_to_analysis is None,
    reason="apply_matched_rgb_overrides_to_analysis not yet implemented",
)
class TestApplyMatchedRgbOverrides:
    """Verify ``apply_matched_rgb_overrides_to_analysis`` propagates a
    ``cache.matched_rgb`` mutation back into ``analysis.matched_shapes``.

    校验 helper 把 ``cache.matched_rgb`` 的修改回写到 ``matched_shapes``。
    """

    def test_region_replace_red_to_blue_updates_matched_shape(self):
        """Pixel-level red→blue swap on the top half must rewrite the
        matched shape's ``matched_rgb`` and ``recipe``.

        红→蓝的像素级覆写必须让顶部 shape 的 matched_rgb / recipe 跟着
        变成蓝色通道；否则生成的 3MF 仍按原 LUT 配方，错失用户改色。
        """
        analysis = _make_two_shape_analysis()
        img_processor = _build_fake_img_processor()
        matched_rgb, mask_solid, h_px, _ = _build_grid_arrays(analysis)

        # Simulate /region-replace: top half red → blue.
        # 模拟 /region-replace：上半红色像素整体改写为蓝色。
        half = h_px // 2
        matched_rgb[:half, :, :] = (0, 0, 255)

        changed = apply_matched_rgb_overrides_to_analysis(
            analysis,
            matched_rgb=matched_rgb,
            mask_solid=mask_solid,
            img_processor=img_processor,
        )

        assert changed == 1, "exactly one shape's colour was edited"
        top_shape = analysis.matched_shapes[0]
        bot_shape = analysis.matched_shapes[1]

        assert top_shape["matched_rgb"] == (0, 0, 255)
        assert top_shape["recipe"] == [3, 3, 3, 3, 3]
        # Untouched bottom shape stays on the green LUT entry.
        assert bot_shape["matched_rgb"] == (0, 255, 0)
        assert bot_shape["recipe"] == [2, 2, 2, 2, 2]

    def test_dynamic_cached_matrix_is_authoritative_for_native_svg_recipe(self):
        """Dynamic vector generation must preserve cached display RGB + stack."""

        analysis = _make_two_shape_analysis()
        analysis.num_layers = 7
        analysis.material_dynamic_layer_info = {
            "enabled": True,
            "min_layer_count": 5,
            "max_layer_count": 7,
            "colors": [
                {
                    "target_srgb": [255, 0, 0],
                    "matched_srgb": [10, 20, 30],
                    "actual_layer_count": 4,
                    "padding_layer_count": 3,
                    "actual_recipe_top_to_bottom": [1, 1, 1, 1],
                    "print_recipe_top_to_bottom": [1, 1, 1, 1, 0, 0, 0],
                }
            ],
        }
        img_processor = _build_fake_img_processor()
        matched_rgb, mask_solid, h_px, w_px = _build_grid_arrays(analysis)
        matched_rgb[: h_px // 2, :, :] = (10, 20, 30)
        material_matrix = np.empty((h_px, w_px, 7), dtype=np.int32)
        material_matrix[: h_px // 2, :, :] = [1, 1, 1, 1, 0, 0, 0]
        material_matrix[h_px // 2 :, :, :] = [2, 2, 2, 2, 2, 2, 2]

        changed = apply_matched_rgb_overrides_to_analysis(
            analysis,
            matched_rgb=matched_rgb,
            mask_solid=mask_solid,
            material_matrix=material_matrix,
            img_processor=img_processor,
            strict=True,
            prefer_cached_material_state=True,
        )

        assert changed >= 1
        top_shape = analysis.matched_shapes[0]
        assert top_shape["matched_rgb"] == (10, 20, 30)
        assert top_shape["recipe"] == [1, 1, 1, 1, 0, 0, 0]
        assert top_shape["material_dynamic_recipe"]["actual_layer_count"] == 4
        assert top_shape["material_dynamic_recipe"]["padding_layer_count"] == 3

        preview_cache = _ve.VectorProcessor.build_preview_cache(
            analysis,
            pixels_per_mm=10.0,
        )
        assert preview_cache["material_matrix"].dtype == np.int32
        assert (1, 1, 1, 1, 0, 0, 0) in {
            tuple(row.tolist())
            for row in preview_cache["material_matrix"][preview_cache["mask_solid"]]
        }

    def test_region_replace_logs_structured_success_event(self, caplog):
        """A successful helper rewrite must emit a structured DEBUG event."""
        analysis = _make_two_shape_analysis()
        img_processor = _build_fake_img_processor()
        matched_rgb, mask_solid, h_px, _ = _build_grid_arrays(analysis)
        matched_rgb[: h_px // 2, :, :] = (0, 0, 255)

        target_logger = _attach_caplog(caplog, "lumina.core.vector_engine", logging.DEBUG)
        try:
            changed = apply_matched_rgb_overrides_to_analysis(
                analysis,
                matched_rgb=matched_rgb,
                mask_solid=mask_solid,
                img_processor=img_processor,
            )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert changed == 1
        records = [
            record
            for record in caplog.records
            if getattr(record, "event", None) == "vector_overrides_applied"
        ]
        assert len(records) == 1
        record = records[0]
        assert record.levelno == logging.DEBUG
        assert getattr(record, "shape_count") == 2
        assert getattr(record, "rewritten_count") == 1
        assert not record.getMessage().lstrip().startswith("[")

    def test_engine_overrides_applied_emits_at_debug_not_info(self, caplog):
        """INFO-only capture must not receive the engine override event."""
        analysis = _make_two_shape_analysis()
        img_processor = _build_fake_img_processor()
        matched_rgb, mask_solid, h_px, _ = _build_grid_arrays(analysis)
        matched_rgb[: h_px // 2, :, :] = (0, 0, 255)

        target_logger = _attach_caplog(caplog, "lumina.core.vector_engine", logging.INFO)
        try:
            changed = apply_matched_rgb_overrides_to_analysis(
                analysis,
                matched_rgb=matched_rgb,
                mask_solid=mask_solid,
                img_processor=img_processor,
            )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert changed == 1
        assert all(
            getattr(record, "event", None) != "vector_overrides_applied"
            for record in caplog.records
            if record.levelno >= logging.INFO
        )

    def test_no_change_returns_zero_and_keeps_recipes(self):
        """When ``matched_rgb`` matches the existing shape colours the
        helper must be a no-op.

        当 ``matched_rgb`` 与现有 shape 颜色一致时，helper 应不改写任何
        shape，避免重复运算引入随机抖动。
        """
        analysis = _make_two_shape_analysis()
        img_processor = _build_fake_img_processor()
        matched_rgb, mask_solid, _, _ = _build_grid_arrays(analysis)

        changed = apply_matched_rgb_overrides_to_analysis(
            analysis,
            matched_rgb=matched_rgb,
            mask_solid=mask_solid,
            img_processor=img_processor,
        )

        assert changed == 0
        assert analysis.matched_shapes[0]["recipe"] == [1, 1, 1, 1, 1]
        assert analysis.matched_shapes[1]["recipe"] == [2, 2, 2, 2, 2]

    @pytest.mark.parametrize(
        "compound_factory",
        [
            pytest.param(MultiPolygon, id="multipolygon"),
            pytest.param(GeometryCollection, id="geometry-collection"),
        ],
    )
    def test_small_disconnected_component_keeps_its_local_recipe(
        self,
        compound_factory,
    ):
        """A small edited island must not lose the vote to a larger sibling."""

        small = box(0.5, 0.5, 1.5, 1.5)
        large = box(4.0, 0.5, 11.5, 3.5)
        analysis = _make_compound_analysis(compound_factory([small, large]))
        matched_rgb, mask_solid, material_matrix = _compound_cache_arrays()
        matched_rgb[5:16, 5:16, :] = (0, 0, 255)
        material_matrix[5:16, 5:16, :] = np.array([3, 1, 3, 1, 3])

        changed = apply_matched_rgb_overrides_to_analysis(
            analysis,
            matched_rgb=matched_rgb,
            material_matrix=material_matrix,
            mask_solid=mask_solid,
            img_processor=_build_fake_img_processor(),
        )

        assert changed == 1
        assert len(analysis.matched_shapes) == 2
        small_record, large_record = analysis.matched_shapes
        assert small_record["geometry"].equals(small)
        assert small_record["matched_rgb"] == (0, 0, 255)
        assert small_record["recipe"] == [3, 1, 3, 1, 3]
        assert large_record["geometry"].equals(large)
        assert large_record["matched_rgb"] == (255, 0, 0)
        assert large_record["recipe"] == [1, 1, 1, 1, 1]
        assert [record["source_id"] for record in analysis.matched_shapes] == [
            "compound-source",
            "compound-source",
        ]
        assert [record["draw_order"] for record in analysis.matched_shapes] == [7, 7]

    def test_large_disconnected_component_does_not_recolor_small_sibling(self):
        """A dominant edited island must not recolor an unselected sibling."""

        small = box(0.5, 0.5, 1.5, 1.5)
        large = box(4.0, 0.5, 11.5, 3.5)
        analysis = _make_compound_analysis(MultiPolygon([small, large]))
        matched_rgb, mask_solid, material_matrix = _compound_cache_arrays()
        matched_rgb[5:36, 40:116, :] = (0, 255, 0)
        material_matrix[5:36, 40:116, :] = np.array([2, 1, 2, 1, 2])

        changed = apply_matched_rgb_overrides_to_analysis(
            analysis,
            matched_rgb=matched_rgb,
            material_matrix=material_matrix,
            mask_solid=mask_solid,
            img_processor=_build_fake_img_processor(),
        )

        assert changed == 1
        assert len(analysis.matched_shapes) == 2
        small_record, large_record = analysis.matched_shapes
        assert small_record["geometry"].equals(small)
        assert small_record["matched_rgb"] == (255, 0, 0)
        assert small_record["recipe"] == [1, 1, 1, 1, 1]
        assert large_record["geometry"].equals(large)
        assert large_record["matched_rgb"] == (0, 255, 0)
        assert large_record["recipe"] == [2, 1, 2, 1, 2]

    def test_same_display_assignment_keeps_distinct_component_height_identities(self):
        """Two source heights may collide on one achieved display colour."""

        small = box(0.5, 0.5, 1.5, 1.5)
        large = box(4.0, 0.5, 11.5, 3.5)
        analysis = _make_compound_analysis(MultiPolygon([small, large]))
        analysis.matched_shapes[0]["matched_rgb"] = (0, 0, 255)
        analysis.matched_shapes[0]["recipe"] = [3, 3, 3, 3, 3]
        matched_rgb, mask_solid, material_matrix = _compound_cache_arrays()
        matched_rgb[:, :, :] = (0, 0, 255)
        material_matrix[:, :, :] = 3
        height_identity_rgb = np.full_like(matched_rgb, (255, 0, 0))
        height_identity_rgb[5:36, 40:116, :] = (0, 255, 0)

        changed = apply_matched_rgb_overrides_to_analysis(
            analysis,
            matched_rgb=matched_rgb,
            height_identity_rgb=height_identity_rgb,
            material_matrix=material_matrix,
            mask_solid=mask_solid,
            img_processor=_build_fake_img_processor(),
        )

        assert changed == 0
        assert len(analysis.matched_shapes) == 2
        assert analysis.matched_shapes[0]["matched_rgb"] == (0, 0, 255)
        assert analysis.matched_shapes[1]["matched_rgb"] == (0, 0, 255)
        assert analysis.matched_shapes[0]["height_identity_rgb"] == (255, 0, 0)
        assert analysis.matched_shapes[1]["height_identity_rgb"] == (0, 255, 0)
        assert all(
            "original_lut_idx" not in shape
            for shape in analysis.matched_shapes
        )

    def test_partial_component_replacement_preserves_source_height_identity(self):
        """A locally replaced component and its sibling retain one source height."""

        small = box(0.5, 0.5, 1.5, 1.5)
        large = box(4.0, 0.5, 11.5, 3.5)
        analysis = _make_compound_analysis(MultiPolygon([small, large]))
        matched_rgb, mask_solid, material_matrix = _compound_cache_arrays()
        matched_rgb[5:16, 5:16, :] = (0, 0, 255)
        material_matrix[5:16, 5:16, :] = 3
        height_identity_rgb = np.full_like(matched_rgb, (255, 0, 0))

        changed = apply_matched_rgb_overrides_to_analysis(
            analysis,
            matched_rgb=matched_rgb,
            height_identity_rgb=height_identity_rgb,
            material_matrix=material_matrix,
            mask_solid=mask_solid,
            img_processor=_build_fake_img_processor(),
        )

        assert changed == 1
        assert len(analysis.matched_shapes) == 2
        assert analysis.matched_shapes[0]["matched_rgb"] == (0, 0, 255)
        assert analysis.matched_shapes[1]["matched_rgb"] == (255, 0, 0)
        assert {
            shape["height_identity_rgb"]
            for shape in analysis.matched_shapes
        } == {(255, 0, 0)}

    def test_compound_zero_change_and_uniform_global_change_keep_one_record(self):
        """Only divergent component assignments require structural splitting."""

        small = box(0.5, 0.5, 1.5, 1.5)
        large = box(4.0, 0.5, 11.5, 3.5)
        geometry = MultiPolygon([small, large])
        matched_rgb, mask_solid, material_matrix = _compound_cache_arrays()
        analysis = _make_compound_analysis(geometry)

        unchanged = apply_matched_rgb_overrides_to_analysis(
            analysis,
            matched_rgb=matched_rgb,
            material_matrix=material_matrix,
            mask_solid=mask_solid,
            img_processor=_build_fake_img_processor(),
        )

        assert unchanged == 0
        assert len(analysis.matched_shapes) == 1
        assert analysis.matched_shapes[0]["geometry"].equals(geometry)

        matched_rgb[:, :, :] = (0, 0, 255)
        material_matrix[:, :, :] = np.array([3, 3, 1, 3, 3])
        changed = apply_matched_rgb_overrides_to_analysis(
            analysis,
            matched_rgb=matched_rgb,
            material_matrix=material_matrix,
            mask_solid=mask_solid,
            img_processor=_build_fake_img_processor(),
        )

        assert changed == 2
        assert len(analysis.matched_shapes) == 1
        assert analysis.matched_shapes[0]["geometry"].equals(geometry)
        assert analysis.matched_shapes[0]["matched_rgb"] == (0, 0, 255)
        assert analysis.matched_shapes[0]["recipe"] == [3, 3, 1, 3, 3]

    def test_material_matrix_recipe_is_used_when_rgb_is_unchanged(self):
        analysis = _make_two_shape_analysis()
        img_processor = _build_fake_img_processor()
        matched_rgb, mask_solid, h_px, w_px = _build_grid_arrays(analysis)
        material_matrix = np.zeros((h_px, w_px, 5), dtype=np.int32)
        material_matrix[: h_px // 2, :, :] = np.array([3, 1, 1, 1, 1])
        material_matrix[h_px // 2 :, :, :] = np.array([2, 2, 2, 2, 2])

        changed = apply_matched_rgb_overrides_to_analysis(
            analysis,
            matched_rgb=matched_rgb,
            material_matrix=material_matrix,
            mask_solid=mask_solid,
            img_processor=img_processor,
        )

        assert changed == 1
        assert analysis.matched_shapes[0]["matched_rgb"] == (255, 0, 0)
        assert analysis.matched_shapes[0]["recipe"] == [3, 1, 1, 1, 1]

    def test_short_cached_material_stack_is_padded_to_requested_layers(self):
        """A stale/short cached stack must not leave requested vector layers as air."""
        analysis = _make_two_shape_analysis()
        analysis.num_layers = 10
        analysis.matched_shapes[0]["recipe"] = [1] * 10
        analysis.matched_shapes[1]["recipe"] = [2] * 10
        img_processor = _build_fake_img_processor()
        matched_rgb, mask_solid, h_px, w_px = _build_grid_arrays(analysis)
        material_matrix = np.zeros((h_px, w_px, 5), dtype=np.int32)
        material_matrix[: h_px // 2, :, :] = 3
        material_matrix[h_px // 2 :, :, :] = 2

        changed = apply_matched_rgb_overrides_to_analysis(
            analysis,
            matched_rgb=matched_rgb,
            material_matrix=material_matrix,
            mask_solid=mask_solid,
            img_processor=img_processor,
        )

        assert changed == 1
        assert analysis.matched_shapes[0]["recipe"] == [3] * 10
        assert analysis.matched_shapes[1]["recipe"] == [2] * 10
        runs = _ve.VectorProcessor._build_channel_runs(
            analysis.matched_shapes[0]["recipe"],
            analysis.num_layers,
            analysis.num_channels,
        )
        assert runs[3] == [(0, 9)]

    def test_pixels_outside_mask_solid_are_ignored(self):
        """Mutations on background pixels (``mask_solid == False``) must
        not influence the per-shape dominant colour vote.

        ``mask_solid`` 之外的像素（背景）即便被改写也不能影响 shape 的
        dominant 颜色统计；防止背景噪声误改正确的 shape 配方。
        """
        analysis = _make_two_shape_analysis()
        img_processor = _build_fake_img_processor()
        matched_rgb, mask_solid, h_px, w_px = _build_grid_arrays(analysis)

        # Carve a thin background strip across the top half but flood it
        # with blue. The shape mask still claims the strip pixels so this
        # exercises the mask_solid intersection guard.
        # 在上半挖一条细 background 条并涂蓝；shape mask 还覆盖这条带，
        # 用来检查 mask_solid 求交是否真的过滤掉了背景颜色。
        half = h_px // 2
        bg_strip = slice(0, max(1, half // 4))
        mask_solid[bg_strip, :] = False
        matched_rgb[bg_strip, :, :] = (0, 0, 255)

        changed = apply_matched_rgb_overrides_to_analysis(
            analysis,
            matched_rgb=matched_rgb,
            mask_solid=mask_solid,
            img_processor=img_processor,
        )

        assert changed == 0
        assert analysis.matched_shapes[0]["matched_rgb"] == (255, 0, 0)
        assert analysis.matched_shapes[0]["recipe"] == [1, 1, 1, 1, 1]

    def test_grid_size_mismatch_returns_zero_and_logs(self, caplog):
        """If ``matched_rgb`` shape disagrees with the helper's
        reconstructed grid, refuse silently and emit a warning rather
        than corrupting the analysis.

        当 ``matched_rgb`` 尺寸与 helper 复算的 preview 网格不一致时，
        函数应直接放弃改写并发出警告，避免破坏 ``matched_shapes``。
        """
        analysis = _make_two_shape_analysis()
        img_processor = _build_fake_img_processor()

        bogus_rgb = np.zeros((11, 11, 3), dtype=np.uint8)
        bogus_mask = np.ones((11, 11), dtype=bool)

        target_logger = _attach_caplog(caplog, "lumina.core.vector_engine", logging.WARNING)
        try:
            changed = apply_matched_rgb_overrides_to_analysis(
                analysis,
                matched_rgb=bogus_rgb,
                mask_solid=bogus_mask,
                img_processor=img_processor,
            )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert changed == 0
        assert analysis.matched_shapes[0]["recipe"] == [1, 1, 1, 1, 1]
        # Warning text must mention the mismatched shape so on-call can
        # debug the upstream cache serialization quickly.
        # 警告文案需要含失配尺寸，方便排查上游缓存序列化是否走样。
        joined = " ".join(rec.message for rec in caplog.records)
        assert "shape" in joined.lower() or "grid" in joined.lower()
        records = [
            record
            for record in caplog.records
            if getattr(record, "event", None) == "vector_overrides_grid_mismatch"
        ]
        assert len(records) == 1
        record = records[0]
        assert getattr(record, "matched_rgb_shape") == [11, 11]
        assert getattr(record, "mask_solid_shape") == [11, 11]
        assert getattr(record, "expected_shape") == [100, 100]
        assert getattr(record, "error_type") == "ValueError"

    @pytest.mark.parametrize(
        "invalid_case",
        [
            "matched_dtype",
            "mask_dtype",
            "spatial_grid",
            "material_rank",
            "material_dtype",
            "material_grid",
            "material_empty_channels",
        ],
    )
    def test_strict_mode_raises_for_invalid_cache_inputs(self, invalid_case):
        """Worker-bound strict mode must reject every malformed cache grid."""

        analysis = _make_two_shape_analysis()
        img_processor = _build_fake_img_processor()
        matched_rgb, mask_solid, h_px, w_px = _build_grid_arrays(analysis)
        material_matrix = np.ones((h_px, w_px, 5), dtype=np.int16)

        if invalid_case == "matched_dtype":
            matched_rgb = matched_rgb.astype(np.int16)
        elif invalid_case == "mask_dtype":
            mask_solid = mask_solid.astype(np.uint8)
        elif invalid_case == "spatial_grid":
            mask_solid = mask_solid[:-1, :]
        elif invalid_case == "material_rank":
            material_matrix = material_matrix[..., 0]
        elif invalid_case == "material_dtype":
            material_matrix = material_matrix.astype(np.float32)
        elif invalid_case == "material_grid":
            material_matrix = material_matrix[:, :-1, :]
        elif invalid_case == "material_empty_channels":
            material_matrix = material_matrix[..., :0]

        with pytest.raises(ValueError):
            apply_matched_rgb_overrides_to_analysis(
                analysis,
                matched_rgb=matched_rgb,
                material_matrix=material_matrix,
                mask_solid=mask_solid,
                img_processor=img_processor,
                strict=True,
            )

    def test_strict_mode_validates_cache_even_when_analysis_has_no_shapes(self):
        """An empty SVG must not turn malformed worker input into success."""

        analysis = _make_two_shape_analysis()
        analysis.matched_shapes = []
        matched_rgb, mask_solid, h_px, w_px = _build_grid_arrays(analysis)

        with pytest.raises(ValueError):
            apply_matched_rgb_overrides_to_analysis(
                analysis,
                matched_rgb=matched_rgb.astype(np.int16),
                material_matrix=np.ones((h_px, w_px, 5), dtype=np.int16),
                mask_solid=mask_solid,
                img_processor=_build_fake_img_processor(),
                strict=True,
            )

    def test_strict_mode_allows_valid_zero_change(self):
        """A valid cache with no edits is success, not a strict-mode failure."""

        analysis = _make_two_shape_analysis()
        img_processor = _build_fake_img_processor()
        matched_rgb, mask_solid, h_px, w_px = _build_grid_arrays(analysis)
        material_matrix = np.zeros((h_px, w_px, 5), dtype=np.int16)
        material_matrix[: h_px // 2, :, :] = 1
        material_matrix[h_px // 2 :, :, :] = 2

        changed = apply_matched_rgb_overrides_to_analysis(
            analysis,
            matched_rgb=matched_rgb,
            material_matrix=material_matrix,
            mask_solid=mask_solid,
            img_processor=img_processor,
            strict=True,
        )

        assert changed == 0


@pytest.mark.skipif(
    apply_matched_rgb_overrides_to_analysis is not None,
    reason=(
        "Reproducer guard: only meaningful while the helper is missing. "
        "Once apply_matched_rgb_overrides_to_analysis exists this test is "
        "auto-skipped, leaving the behavioural suite above as the regression."
    ),
)
def test_helper_must_be_exported_from_vector_engine():
    """Red-light reproducer: documents the missing public surface.

    红灯复现：在 helper 真正落地前，明确指出 ``vector_engine`` 缺少这
    个公共函数；helper 一旦实现该测试自动跳过，让上面的行为测试接管
    回归保护。
    """
    pytest.fail(
        "core.vector_engine.apply_matched_rgb_overrides_to_analysis "
        "is required so vector-mode region replacements survive "
        "into the generated 3MF."
    )


# ---------------------------------------------------------------------------
# Coordinator wiring: ensure ``_run_vector_branch`` reads the new ctx keys
# (``matched_rgb_path`` / ``mask_solid_path``) and forwards them to the
# helper. Without this hookup the helper would never run in production.
# ---------------------------------------------------------------------------


class TestRunVectorBranchWiring:
    """Verify the coordinator forwards cache snapshots to the helper.

    校验 ``_run_vector_branch`` 把 ``matched_rgb_path`` / ``mask_solid_path``
    透传给 ``apply_matched_rgb_overrides_to_analysis``，确保生产环境真的
    会调用我们的修复函数。
    """

    def _patch_dependencies(
        self,
        captured: dict,
        helper_call_log: list[dict],
        *,
        helper_result: int = 0,
        helper_error: Exception | None = None,
        recipe_call_log: list[dict] | None = None,
        helper_metrics: dict | None = None,
        on_build_mesh=None,
        on_export=None,
        retain_helper_arguments: bool = True,
    ):
        """Build the patch context shared by both wiring tests.

        构造两个 wiring 测试共用的 patch 上下文，覆盖 VectorProcessor、
        3MF 导出器与 helper 调用。
        """
        from types import SimpleNamespace
        from unittest.mock import patch

        import trimesh

        from core.pipeline import coordinator

        class _FakeAnalysis:
            pass

        class _FakeVectorProcessor:
            parse_warnings: list[str] = []
            last_stage_timings: dict[str, float] = {}

            def __init__(self, _lut_path: str, color_mode: str, *, img_processor=None) -> None:
                self.color_mode = color_mode
                self.enable_fridge_magnet = False
                self.fridge_magnets = []
                # Non-trivial sentinel so the helper patch can confirm it
                # got the same processor object the branch used.
                # 非平凡哨兵；helper patch 用它确认收到的就是分支构造的处理器。
                self.img_processor = SimpleNamespace(tag="fake-img-processor")
                captured["processor_ref"] = weakref.ref(self)

            def analyze_svg(self, *, svg_path: str, target_width_mm: float, color_replacements=None):
                del svg_path, target_width_mm, color_replacements
                analysis = _FakeAnalysis()
                analysis.matched_shapes = []
                analysis.num_layers = 5
                analysis.num_channels = 4
                analysis.preview_colors = {0: [255, 0, 0, 255]}
                analysis.slot_names = ["Slot 1"]
                analysis.image_vectorizer_bounds = None
                analysis.scale_factor = 1.0
                captured["analysis_ref"] = weakref.ref(analysis)
                return analysis

            def build_mesh(self, *, analysis, thickness_mm: float, structure_mode: str):
                del analysis, thickness_mm, structure_mode
                if on_build_mesh is not None:
                    on_build_mesh()
                scene = trimesh.Scene()
                scene.add_geometry(trimesh.creation.box(extents=(1, 1, 1)), geom_name="Slot 1")
                return scene

            @staticmethod
            def render_preview(analysis, pixels_per_mm: float):
                del analysis, pixels_per_mm
                return None

        def _fake_helper(*args, **kwargs):
            helper_call_log.append(
                {"args": args, "kwargs": kwargs}
                if retain_helper_arguments
                else {"called": True}
            )
            if helper_error is not None:
                raise helper_error
            if helper_metrics is not None:
                args[0].matched_rgb_override_metrics = dict(helper_metrics)
            return helper_result

        def _fake_recipe_helper(*args, **kwargs):
            if recipe_call_log is not None:
                recipe_call_log.append({"args": args, "kwargs": kwargs})

        def _fake_export_scene_with_bambu_metadata(**kwargs):
            if on_export is not None:
                on_export()
            captured.update(kwargs)
            return kwargs["output_path"]

        return patch.multiple(
            "core.vector_engine",
            VectorProcessor=_FakeVectorProcessor,
            apply_matched_rgb_overrides_to_analysis=_fake_helper,
            apply_recipe_overrides_to_analysis=_fake_recipe_helper,
        ), patch(
            "utils.bambu_3mf_writer.export_scene_with_bambu_metadata",
            side_effect=_fake_export_scene_with_bambu_metadata,
        ), patch("core.naming.generate_model_filename", lambda *_args: "vector-out.3mf"), patch(
            "core.naming.generate_preview_filename",
            lambda *_args: "vector-preview.glb",
        ), patch("utils.Stats.increment", lambda *_args, **_kwargs: None), patch.object(
            coordinator,
            "_report_progress",
            lambda *_args, **_kwargs: None,
        )

    def test_helper_invoked_when_cache_paths_are_provided(self, tmp_path):
        """Spinning up a vector branch with both ``matched_rgb_path`` and
        ``mask_solid_path`` populated must invoke the helper exactly once.

        ``_run_vector_branch`` 拿到两条缓存路径时必须正好调用 helper 一次。
        """
        from unittest.mock import patch

        from config import MODELS_DIR, OUTPUT_DIR, ModelingMode
        from core.pipeline import coordinator

        matched_rgb_path = tmp_path / "matched.npy"
        height_identity_rgb_path = tmp_path / "height-identity.npy"
        mask_solid_path = tmp_path / "mask.npy"
        material_matrix_path = tmp_path / "material.npy"
        np.save(matched_rgb_path, np.zeros((4, 4, 3), dtype=np.uint8))
        np.save(
            height_identity_rgb_path,
            np.full((4, 4, 3), [255, 0, 0], dtype=np.uint8),
        )
        np.save(mask_solid_path, np.ones((4, 4), dtype=bool))
        np.save(material_matrix_path, np.ones((4, 4, 5), dtype=np.int32))

        captured: dict = {}
        helper_calls: list[dict] = []
        helper_metrics = {
            "raster_strategy": "roi",
            "component_count": 7,
            "full_canvas_pixel_work": 11200,
            "roi_pixel_work": 700,
            "max_roi_pixels": 200,
            "effective_pixel_count": 490,
            "pixel_work_reduction_ratio": 16.0,
            "rewritten_component_count": 0,
            "output_shape_count": 7,
        }
        cms = self._patch_dependencies(
            captured,
            helper_calls,
            helper_metrics=helper_metrics,
        )

        with cms[0], cms[1], cms[2], cms[3], cms[4], cms[5], patch(
            "config.MODELS_DIR", str(tmp_path)
        ), patch("config.OUTPUT_DIR", str(tmp_path)):
            ctx = {
                "image_path": str(tmp_path / "vector.svg"),
                "actual_lut_path": str(tmp_path / "fake.json"),
                "color_mode": "5-Color Extended",
                "modeling_mode": ModelingMode.HIGH_FIDELITY,
                "target_width_mm": 40.0,
                "spacer_thick": 1.6,
                "structure_mode": "单面",
                "need_2d_preview": False,
                "printer_id": "bambu-h2d",
                "slicer": "BambuStudio",
                "nozzle_size": "0.4",
                "svg_pixels_per_mm": 5.0,
                "matched_rgb_path": str(matched_rgb_path),
                "height_identity_rgb_path": str(height_identity_rgb_path),
                "mask_solid_path": str(mask_solid_path),
                "material_matrix_path": str(material_matrix_path),
            }

            result = coordinator._run_vector_branch(ctx)

        assert "error" not in result
        assert len(helper_calls) == 1
        kwargs = helper_calls[0]["kwargs"]
        assert "matched_rgb" in kwargs
        assert "height_identity_rgb" in kwargs
        assert "mask_solid" in kwargs
        assert "material_matrix" in kwargs
        # These arrays come from the preview cache, which is currently built
        # at 10 px/mm even when the generate request uses another SVG density.
        assert kwargs["pixels_per_mm"] == 10.0
        assert kwargs["material_matrix"].shape == (4, 4, 5)
        assert np.all(kwargs["height_identity_rgb"] == [255, 0, 0])
        # img_processor must be the FakeVectorProcessor's stub attribute,
        # not some unrelated object — the helper relies on its KDTree.
        # img_processor 必须是分支构造的处理器持有的对象，否则 helper 会
        # 拿到错误的 KDTree，等于没修。
        assert kwargs["img_processor"].tag == "fake-img-processor"
        timings = result["vector_timing"]
        assert {
            "analyze_svg_s",
            "matched_rgb_override_s",
            "recipe_override_s",
            "build_mesh_s",
            "mesh_total_s",
            "export_3mf_s",
            "export_glb_s",
            "vector_branch_total_s",
        }.issubset(timings)
        assert timings["matched_rgb_override_s"] > 0.0
        assert timings["recipe_override_s"] == 0.0
        assert timings["build_mesh_s"] > 0.0
        assert result["matched_rgb_override_metrics"] == helper_metrics
        assert timings["matched_rgb_override_component_count"] == 7
        assert timings["matched_rgb_override_full_canvas_pixel_work"] == 11200
        assert timings["matched_rgb_override_roi_pixel_work"] == 700
        assert timings["matched_rgb_override_max_roi_pixels"] == 200
        assert timings["matched_rgb_override_effective_pixel_count"] == 490
        assert timings["matched_rgb_override_pixel_work_reduction_ratio"] == 16.0

    def test_cached_override_arrays_are_released_before_mesh_build(
        self,
        tmp_path,
    ):
        """Large preview arrays must not overlap the mesh-build memory peak."""
        from unittest.mock import patch

        from config import ModelingMode
        from core.pipeline import coordinator
        from core.preview_analysis_cache import REQUIRED_PREVIEW_ANALYSIS_REUSE

        array_paths = {
            "matched_rgb_path": tmp_path / "matched.npy",
            "height_identity_rgb_path": tmp_path / "height-identity.npy",
            "mask_solid_path": tmp_path / "mask.npy",
            "material_matrix_path": tmp_path / "material.npy",
        }
        np.save(
            array_paths["matched_rgb_path"],
            np.zeros((4, 4, 3), dtype=np.uint8),
        )
        np.save(
            array_paths["height_identity_rgb_path"],
            np.zeros((4, 4, 3), dtype=np.uint8),
        )
        np.save(
            array_paths["mask_solid_path"],
            np.ones((4, 4), dtype=bool),
        )
        np.save(
            array_paths["material_matrix_path"],
            np.ones((4, 4, 5), dtype=np.int16),
        )

        original_load = np.load
        loaded_array_refs: list[weakref.ReferenceType[np.ndarray]] = []
        load_options: list[dict] = []

        def _tracked_load(*args, **kwargs):
            load_options.append(dict(kwargs))
            loaded = original_load(*args, **kwargs)
            loaded_array_refs.append(weakref.ref(loaded))
            return loaded

        def _assert_cache_arrays_released() -> None:
            gc.collect()
            assert len(loaded_array_refs) == 4
            assert all(ref() is None for ref in loaded_array_refs)

        captured: dict = {}
        helper_calls: list[dict] = []
        cms = self._patch_dependencies(
            captured,
            helper_calls,
            on_build_mesh=_assert_cache_arrays_released,
            retain_helper_arguments=False,
        )
        ctx = {
            "image_path": str(tmp_path / "vector.svg"),
            "actual_lut_path": str(tmp_path / "fake.json"),
            "color_mode": "5-Color Extended",
            "modeling_mode": ModelingMode.HIGH_FIDELITY,
            "target_width_mm": 40.0,
            "spacer_thick": 1.6,
            "structure_mode": "单面",
            "need_2d_preview": False,
            "printer_id": "bambu-h2d",
            "slicer": "BambuStudio",
            "nozzle_size": "0.4",
            "reuse_preview_analysis": REQUIRED_PREVIEW_ANALYSIS_REUSE,
            **{key: str(path) for key, path in array_paths.items()},
        }

        with cms[0], cms[1], cms[2], cms[3], cms[4], cms[5], patch(
            "config.MODELS_DIR",
            str(tmp_path),
        ), patch("config.OUTPUT_DIR", str(tmp_path)), patch(
            "core.pipeline.vector_branch.np.load",
            side_effect=_tracked_load,
        ):
            result = coordinator._run_vector_branch(ctx)

        assert "error" not in result
        assert helper_calls == [{"called": True}]
        assert len(load_options) == 4
        assert all(
            options.get("mmap_mode") == "r"
            for options in load_options
        )

    def test_analysis_is_released_before_export_without_2d_preview(
        self,
        tmp_path,
    ):
        """Completed mesh exports must not retain the full analysis graph."""
        from unittest.mock import patch

        from config import ModelingMode
        from core.pipeline import coordinator
        from core.preview_analysis_cache import REQUIRED_PREVIEW_ANALYSIS_REUSE

        array_paths = {
            "matched_rgb_path": tmp_path / "matched.npy",
            "height_identity_rgb_path": tmp_path / "height-identity.npy",
            "mask_solid_path": tmp_path / "mask.npy",
            "material_matrix_path": tmp_path / "material.npy",
        }
        np.save(
            array_paths["matched_rgb_path"],
            np.zeros((4, 4, 3), dtype=np.uint8),
        )
        np.save(
            array_paths["height_identity_rgb_path"],
            np.zeros((4, 4, 3), dtype=np.uint8),
        )
        np.save(
            array_paths["mask_solid_path"],
            np.ones((4, 4), dtype=bool),
        )
        np.save(
            array_paths["material_matrix_path"],
            np.ones((4, 4, 5), dtype=np.int16),
        )

        captured: dict = {}
        helper_calls: list[dict] = []

        def _assert_heavy_objects_released() -> None:
            gc.collect()
            assert captured["analysis_ref"]() is None
            assert captured["processor_ref"]() is None

        cms = self._patch_dependencies(
            captured,
            helper_calls,
            on_export=_assert_heavy_objects_released,
            retain_helper_arguments=False,
        )
        ctx = {
            "image_path": str(tmp_path / "vector.svg"),
            "actual_lut_path": str(tmp_path / "fake.json"),
            "color_mode": "5-Color Extended",
            "modeling_mode": ModelingMode.HIGH_FIDELITY,
            "target_width_mm": 40.0,
            "spacer_thick": 1.6,
            "structure_mode": "单面",
            "need_2d_preview": False,
            "printer_id": "bambu-h2d",
            "slicer": "BambuStudio",
            "nozzle_size": "0.4",
            "reuse_preview_analysis": REQUIRED_PREVIEW_ANALYSIS_REUSE,
            **{key: str(path) for key, path in array_paths.items()},
        }

        with cms[0], cms[1], cms[2], cms[3], cms[4], cms[5], patch(
            "config.MODELS_DIR",
            str(tmp_path),
        ), patch("config.OUTPUT_DIR", str(tmp_path)):
            result = coordinator._run_vector_branch(ctx)

        assert "error" not in result
        assert helper_calls == [{"called": True}]

    def test_helper_skipped_when_only_one_cache_path_present(self, tmp_path):
        """Either path missing (or both) must skip the helper to avoid a
        partial / inconsistent override pass.

        只缺一条路径就要整体跳过 helper，避免半套覆盖污染 ``matched_shapes``。
        """
        from unittest.mock import patch

        from config import ModelingMode
        from core.pipeline import coordinator

        matched_rgb_path = tmp_path / "matched.npy"
        np.save(matched_rgb_path, np.zeros((4, 4, 3), dtype=np.uint8))

        captured: dict = {}
        helper_calls: list[dict] = []
        cms = self._patch_dependencies(captured, helper_calls)

        with cms[0], cms[1], cms[2], cms[3], cms[4], cms[5], patch(
            "config.MODELS_DIR", str(tmp_path)
        ), patch("config.OUTPUT_DIR", str(tmp_path)):
            ctx = {
                "image_path": str(tmp_path / "vector.svg"),
                "actual_lut_path": str(tmp_path / "fake.json"),
                "color_mode": "5-Color Extended",
                "modeling_mode": ModelingMode.HIGH_FIDELITY,
                "target_width_mm": 40.0,
                "spacer_thick": 1.6,
                "structure_mode": "单面",
                "need_2d_preview": False,
                "printer_id": "bambu-h2d",
                "slicer": "BambuStudio",
                "nozzle_size": "0.4",
                "matched_rgb_path": str(matched_rgb_path),
                # mask_solid_path intentionally absent / None
                "mask_solid_path": None,
            }

            result = coordinator._run_vector_branch(ctx)

        assert "error" not in result
        assert helper_calls == []

    def test_required_cache_projection_error_aborts_vector_generation(
        self,
        tmp_path,
    ) -> None:
        """A required spatial cache error must not continue to 3MF export."""

        from unittest.mock import patch

        from config import ModelingMode
        from core.errors import CachedPreviewAnalysisError
        from core.pipeline import coordinator
        from core.preview_analysis_cache import REQUIRED_PREVIEW_ANALYSIS_REUSE

        matched_rgb_path = tmp_path / "matched.npy"
        mask_solid_path = tmp_path / "mask.npy"
        material_matrix_path = tmp_path / "material.npy"
        np.save(matched_rgb_path, np.zeros((4, 4, 3), dtype=np.uint8))
        np.save(mask_solid_path, np.ones((4, 4), dtype=bool))
        np.save(material_matrix_path, np.ones((4, 4, 5), dtype=np.int32))

        captured: dict = {}
        helper_calls: list[dict] = []
        cms = self._patch_dependencies(
            captured,
            helper_calls,
            helper_error=ValueError("cached grid is incompatible"),
        )

        with cms[0], cms[1], cms[2], cms[3], cms[4], cms[5], patch(
            "config.MODELS_DIR", str(tmp_path)
        ), patch("config.OUTPUT_DIR", str(tmp_path)), pytest.raises(
            CachedPreviewAnalysisError
        ):
            coordinator._run_vector_branch(
                {
                    "image_path": str(tmp_path / "vector.svg"),
                    "actual_lut_path": str(tmp_path / "fake.json"),
                    "color_mode": "5-Color Extended",
                    "modeling_mode": ModelingMode.VECTOR,
                    "target_width_mm": 40.0,
                    "spacer_thick": 1.6,
                    "structure_mode": "单面",
                    "need_2d_preview": False,
                    "printer_id": "bambu-h2d",
                    "slicer": "BambuStudio",
                    "nozzle_size": "0.4",
                    "matched_rgb_path": str(matched_rgb_path),
                    "mask_solid_path": str(mask_solid_path),
                    "material_matrix_path": str(material_matrix_path),
                    "reuse_preview_analysis": REQUIRED_PREVIEW_ANALYSIS_REUSE,
                }
            )

        assert len(helper_calls) == 1
        assert helper_calls[0]["kwargs"]["strict"] is True
        assert set(captured) == {"analysis_ref", "processor_ref"}

    def test_recipe_helper_uses_preview_cache_grid_when_svg_density_differs(self, tmp_path):
        """Recipe override masks are preview-cache artifacts, not generation rasters."""
        import pickle
        from unittest.mock import patch

        from config import ModelingMode
        from core.pipeline import coordinator

        masks_path = tmp_path / "recipe-masks.pkl"
        with open(masks_path, "wb") as handle:
            pickle.dump({"region-A": np.ones((4, 4), dtype=bool)}, handle)

        captured: dict = {}
        helper_calls: list[dict] = []
        recipe_calls: list[dict] = []
        cms = self._patch_dependencies(
            captured,
            helper_calls,
            recipe_call_log=recipe_calls,
        )

        with cms[0], cms[1], cms[2], cms[3], cms[4], cms[5], patch(
            "config.MODELS_DIR", str(tmp_path)
        ), patch("config.OUTPUT_DIR", str(tmp_path)):
            ctx = {
                "image_path": str(tmp_path / "vector.svg"),
                "actual_lut_path": str(tmp_path / "fake.json"),
                "color_mode": "5-Color Extended",
                "modeling_mode": ModelingMode.HIGH_FIDELITY,
                "target_width_mm": 40.0,
                "spacer_thick": 1.6,
                "structure_mode": "单面",
                "need_2d_preview": False,
                "printer_id": "bambu-h2d",
                "slicer": "BambuStudio",
                "nozzle_size": "0.4",
                "svg_pixels_per_mm": 5.0,
                "recipe_overrides": [
                    {
                        "region_id": "region-A",
                        "recipe": [1, 2, 3, 4, 0],
                        "layer_order": "Top2Bottom",
                    }
                ],
                "recipe_override_masks_path": str(masks_path),
                "color_layers": 5,
            }

            result = coordinator._run_vector_branch(ctx)

        assert "error" not in result
        assert helper_calls == []
        assert len(recipe_calls) == 1
        kwargs = recipe_calls[0]["kwargs"]
        assert kwargs["pixels_per_mm"] == 10.0
        assert kwargs["region_masks"]["region-A"].shape == (4, 4)
        timings = result["vector_timing"]
        assert timings["matched_rgb_override_s"] == 0.0
        assert timings["recipe_override_s"] > 0.0
        assert timings["build_mesh_s"] > 0.0

    def test_vector_branch_logs_structured_events(self, tmp_path, caplog):
        """The coordinator vector branch must emit explicit structured events."""
        from unittest.mock import patch

        from config import ModelingMode
        from core.pipeline import coordinator

        matched_rgb_path = tmp_path / "matched.npy"
        mask_solid_path = tmp_path / "mask.npy"
        np.save(matched_rgb_path, np.zeros((4, 4, 3), dtype=np.uint8))
        np.save(mask_solid_path, np.ones((4, 4), dtype=bool))

        captured: dict = {}
        helper_calls: list[dict] = []
        cms = self._patch_dependencies(captured, helper_calls, helper_result=2)
        target_logger = _attach_caplog(caplog, "lumina.core.pipeline.coordinator", logging.DEBUG)

        try:
            with cms[0], cms[1], cms[2], cms[3], cms[4], cms[5], patch(
                "config.MODELS_DIR", str(tmp_path)
            ), patch("config.OUTPUT_DIR", str(tmp_path)):
                ctx = {
                    "image_path": str(tmp_path / "vector.svg"),
                    "actual_lut_path": str(tmp_path / "fake.json"),
                    "color_mode": "5-Color Extended",
                    "modeling_mode": ModelingMode.VECTOR,
                    "target_width_mm": 40.0,
                    "spacer_thick": 1.6,
                    "structure_mode": "单面",
                    "need_2d_preview": False,
                    "printer_id": "bambu-h2d",
                    "slicer": "BambuStudio",
                    "nozzle_size": "0.4",
                    "matched_rgb_path": str(matched_rgb_path),
                    "mask_solid_path": str(mask_solid_path),
                }

                result = coordinator._run_vector_branch(ctx)
        finally:
            target_logger.removeHandler(caplog.handler)

        assert "error" not in result
        events = {getattr(record, "event", None) for record in caplog.records}
        assert {
            "vector_branch_init",
            "vector_matched_rgb_overrides_applied",
            "vector_3mf_exported",
            "vector_2d_preview_skipped",
            "vector_timings",
            "vector_branch_done",
        }.issubset(events)
        canary_records = [
            record
            for record in caplog.records
            if getattr(record, "event", None) == "vector_matched_rgb_overrides_applied"
        ]
        assert len(canary_records) == 1
        assert canary_records[0].levelno == logging.INFO
        assert all(
            getattr(record, "event", None)
            for record in caplog.records
            if record.levelno >= logging.INFO
        )
        assert all(not record.getMessage().lstrip().startswith("[") for record in caplog.records)
