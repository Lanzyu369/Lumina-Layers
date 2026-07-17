"""Native SVG large-format spatial override worker regression tests."""

from __future__ import annotations

import os
import pickle
import tempfile
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import cv2
import numpy as np
import pytest
from scipy.spatial import cKDTree
from shapely.geometry import box

from api.workers.converter_workers import (
    LargeFormatCachedAnalysisError,
    worker_generate_large_format_svg_native,
)
from core.vector_engine import (
    VectorAnalysis,
    VectorProcessor as _RealVectorProcessor,
    apply_matched_rgb_overrides_to_analysis,
)


class _SlicerCompatibleProcessor:
    """Keep the real static polygon extractor used by the tiler."""

    _extract_polygonal_geometry = staticmethod(
        _RealVectorProcessor._extract_polygonal_geometry
    )


def _fake_img_processor() -> object:
    lut_rgb = np.array(
        [
            [255, 255, 255],
            [255, 0, 0],
            [0, 255, 0],
            [0, 0, 255],
        ],
        dtype=np.uint8,
    )
    ref_stacks = np.array(
        [
            [0, 0, 0, 0, 0],
            [1, 1, 1, 1, 1],
            [2, 2, 2, 2, 2],
            [3, 3, 3, 3, 3],
        ],
        dtype=np.int16,
    )
    bgr = cv2.cvtColor(np.expand_dims(lut_rgb, axis=0), cv2.COLOR_RGB2BGR)
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2Lab).astype(np.float64).reshape(-1, 3)

    class _StubProcessor:
        def __init__(self) -> None:
            self.lut_rgb = lut_rgb
            self.ref_stacks = ref_stacks
            self.kdtree = cKDTree(lab)

        @staticmethod
        def _rgb_to_lab(rgb_array: np.ndarray) -> np.ndarray:
            arr = np.asarray(rgb_array, dtype=np.uint8).reshape(1, -1, 3)
            bgr_arr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
            return cv2.cvtColor(bgr_arr, cv2.COLOR_BGR2Lab).astype(np.float64).reshape(-1, 3)

    return _StubProcessor()


def _analysis(
    shapes: list[dict[str, object]],
    *,
    width_mm: float,
    height_mm: float,
) -> VectorAnalysis:
    silhouette = None
    for shape in shapes:
        geometry = shape["geometry"]
        silhouette = geometry if silhouette is None else silhouette.union(geometry)
    return VectorAnalysis(
        shape_data=[],
        clipped_shapes=[dict(shape) for shape in shapes],
        matched_shapes=[dict(shape) for shape in shapes],
        silhouette=silhouette,
        scale_factor=1.0,
        bbox=(0.0, 0.0, width_mm, height_mm),
        color_conf={"slots": ["White", "Red", "Green", "Blue"]},
        slot_names=["White", "Red", "Green", "Blue"],
        num_channels=4,
        num_layers=5,
        preview_colors={
            0: [255, 255, 255, 255],
            1: [255, 0, 0, 255],
            2: [0, 255, 0, 255],
            3: [0, 0, 255, 255],
        },
        stage_timings={},
    )


def _red_shape(x0: float, y0: float, x1: float, y1: float) -> dict[str, object]:
    return {
        "geometry": box(x0, y0, x1, y1),
        "color": (255, 0, 0),
        "matched_rgb": (255, 0, 0),
        "lut_idx": 1,
        "recipe": [1, 1, 1, 1, 1],
    }


def _params(
    *,
    total_width_mm: float,
    total_height_mm: float,
    tile_width_mm: float,
    tile_height_mm: float,
) -> dict[str, object]:
    return {
        "tile_name_prefix": "spatial",
        "total_width_mm": total_width_mm,
        "total_height_mm": total_height_mm,
        "tile_width_mm": tile_width_mm,
        "tile_height_mm": tile_height_mm,
        "spacer_thick": 1.2,
        "structure_mode": "Single-sided",
        "color_mode": "4-Color",
        "replacement_regions": [],
        "separate_backing": False,
    }


def _scene_for_slots(slot_names: set[str]) -> SimpleNamespace:
    return SimpleNamespace(
        geometry={
            name: SimpleNamespace(
                vertices=[(0.0, 0.0, 0.0)],
                faces=[(0, 0, 0)],
            )
            for name in slot_names
        }
    )


def _write_export(*, output_path: str, **_kwargs: object) -> None:
    with open(output_path, "wb") as handle:
        handle.write(b"3mf")


def _save_cache_paths(
    tmp_path,
    matched_rgb: np.ndarray,
    mask_solid: np.ndarray,
    material_matrix: np.ndarray,
) -> tuple[str, str, str]:
    matched_path = tmp_path / "matched.npy"
    mask_path = tmp_path / "mask.npy"
    material_path = tmp_path / "material.npy"
    np.save(matched_path, matched_rgb)
    np.save(mask_path, mask_solid)
    np.save(material_path, material_matrix)
    return str(matched_path), str(mask_path), str(material_path)


def test_large_format_cached_analysis_error_is_top_level_picklable() -> None:
    """The process pool must be able to return the typed cache failure."""

    original = LargeFormatCachedAnalysisError("cache changed after validation")
    restored = pickle.loads(pickle.dumps(original))
    assert type(restored) is LargeFormatCachedAnalysisError
    assert str(restored) == str(original)


@pytest.mark.parametrize("mutation", ["delete", "replace"])
def test_native_worker_wraps_cache_changed_after_route_validation(
    tmp_path,
    mutation: str,
) -> None:
    """TOCTOU cache read/parse failures must use the typed worker error."""

    analysis = _analysis(
        [_red_shape(1.0, 1.0, 9.0, 9.0)],
        width_mm=10.0,
        height_mm=10.0,
    )
    matched_path, mask_path, material_path = _save_cache_paths(
        tmp_path,
        np.full((100, 100, 3), [255, 0, 0], dtype=np.uint8),
        np.ones((100, 100), dtype=bool),
        np.ones((100, 100, 5), dtype=np.int16),
    )
    if mutation == "delete":
        os.unlink(mask_path)
    else:
        with open(material_path, "wb") as handle:
            handle.write(b"not-a-numpy-array")

    class _FakeVectorProcessor(_SlicerCompatibleProcessor):
        def __init__(self, _lut_path: str, _color_mode: str) -> None:
            self.img_processor = _fake_img_processor()

        def analyze_svg(self, **_kwargs: object) -> VectorAnalysis:
            return analysis

    params = _params(
        total_width_mm=10.0,
        total_height_mm=10.0,
        tile_width_mm=10.0,
        tile_height_mm=10.0,
    )
    params.update(
        matched_rgb_path=matched_path,
        mask_solid_path=mask_path,
        material_matrix_path=material_path,
    )
    slicer = MagicMock(side_effect=AssertionError("slicer must not run"))

    with (
        patch("core.vector_engine.VectorProcessor", _FakeVectorProcessor),
        patch("core.vector_large_format.slice_vector_analysis_into_tiles", slicer),
        pytest.raises(LargeFormatCachedAnalysisError) as exc_info,
    ):
        worker_generate_large_format_svg_native("image.svg", "lut.npy", params)

    assert isinstance(exc_info.value.__cause__, (OSError, ValueError))
    slicer.assert_not_called()


def test_native_worker_applies_full_analysis_overrides_before_slicing(tmp_path) -> None:
    events: list[str] = []
    analysis = _analysis(
        [_red_shape(1.0, 1.0, 9.0, 9.0)],
        width_mm=10.0,
        height_mm=10.0,
    )
    matched = np.full((100, 100, 3), [0, 255, 0], dtype=np.uint8)
    mask = np.ones((100, 100), dtype=bool)
    material = np.full((100, 100, 5), 2, dtype=np.int16)
    matched_path, mask_path, material_path = _save_cache_paths(
        tmp_path,
        matched,
        mask,
        material,
    )

    class _FakeVectorProcessor(_SlicerCompatibleProcessor):
        def __init__(self, _lut_path: str, _color_mode: str) -> None:
            self.color_mode = "4-Color"
            self.img_processor = _fake_img_processor()

        def analyze_svg(self, **_kwargs: object) -> VectorAnalysis:
            events.append("analyze")
            return analysis

        def build_mesh(self, **_kwargs: object) -> SimpleNamespace:
            return _scene_for_slots({"Green"})

    def _apply_override(target: VectorAnalysis, **kwargs: object) -> int:
        events.append("override")
        assert target is analysis
        assert kwargs["strict"] is True
        assert np.array_equal(kwargs["matched_rgb"], matched)
        assert np.array_equal(kwargs["mask_solid"], mask)
        assert np.array_equal(kwargs["material_matrix"], material)
        target.matched_shapes[0]["matched_rgb"] = (0, 255, 0)
        target.matched_shapes[0]["recipe"] = [2, 2, 2, 2, 2]
        return 1

    def _slice(**kwargs: object) -> list[SimpleNamespace]:
        events.append("slice")
        sliced_analysis = kwargs["analysis"]
        assert sliced_analysis is analysis
        assert sliced_analysis.matched_shapes[0]["recipe"] == [2, 2, 2, 2, 2]
        return [SimpleNamespace(label="R1C1", analysis=sliced_analysis)]

    params = _params(
        total_width_mm=10.0,
        total_height_mm=10.0,
        tile_width_mm=10.0,
        tile_height_mm=10.0,
    )
    params.update(
        matched_rgb_path=matched_path,
        mask_solid_path=mask_path,
        material_matrix_path=material_path,
    )

    result = None
    with (
        patch("core.vector_engine.VectorProcessor", _FakeVectorProcessor),
        patch(
            "core.vector_engine.apply_matched_rgb_overrides_to_analysis",
            side_effect=_apply_override,
        ),
        patch("core.vector_large_format.slice_vector_analysis_into_tiles", side_effect=_slice),
        patch("api.workers.converter_workers._rasterize_tile_for_cover", return_value=None),
        patch(
            "utils.bambu_3mf_writer.export_scene_with_bambu_metadata",
            side_effect=_write_export,
        ),
    ):
        result = worker_generate_large_format_svg_native("image.svg", "lut.npy", params)

    try:
        assert events[:3] == ["analyze", "override", "slice"]
        assert result["tile_count"] == 1
    finally:
        if result is not None and os.path.exists(result["zip_path"]):
            os.unlink(result["zip_path"])


@pytest.mark.parametrize(
    "malformed_case",
    ["grid_mismatch", "matched_rank", "mask_dtype", "material_dtype"],
)
def test_native_worker_strict_malformed_cache_stops_before_slicing_or_zip(
    tmp_path,
    malformed_case: str,
) -> None:
    analysis = _analysis(
        [_red_shape(1.0, 1.0, 9.0, 9.0)],
        width_mm=10.0,
        height_mm=10.0,
    )
    matched = np.full((100, 100, 3), [255, 0, 0], dtype=np.uint8)
    mask = np.ones((100, 100), dtype=bool)
    material = np.ones((100, 100, 5), dtype=np.int16)
    if malformed_case == "grid_mismatch":
        matched = np.full((99, 100, 3), [255, 0, 0], dtype=np.uint8)
        mask = np.ones((99, 100), dtype=bool)
        material = np.ones((99, 100, 5), dtype=np.int16)
    elif malformed_case == "matched_rank":
        matched = np.zeros((100,), dtype=np.uint8)
    elif malformed_case == "mask_dtype":
        mask = np.ones((100, 100), dtype=np.uint8)
    else:
        material = np.ones((100, 100, 5), dtype=np.float32)
    matched_path, mask_path, material_path = _save_cache_paths(
        tmp_path,
        matched,
        mask,
        material,
    )

    class _FakeVectorProcessor(_SlicerCompatibleProcessor):
        def __init__(self, _lut_path: str, _color_mode: str) -> None:
            self.img_processor = _fake_img_processor()

        def analyze_svg(self, **_kwargs: object) -> VectorAnalysis:
            return analysis

    params = _params(
        total_width_mm=10.0,
        total_height_mm=10.0,
        tile_width_mm=10.0,
        tile_height_mm=10.0,
    )
    params.update(
        matched_rgb_path=matched_path,
        mask_solid_path=mask_path,
        material_matrix_path=material_path,
    )
    slicer = MagicMock(side_effect=AssertionError("slicer must not run"))
    zip_paths: list[str] = []
    original_mkstemp = tempfile.mkstemp

    def _capture_mkstemp(*args: object, **kwargs: object):
        fd, path = original_mkstemp(*args, **kwargs)
        if kwargs.get("suffix") == ".zip":
            zip_paths.append(path)
        return fd, path

    with (
        patch("core.vector_engine.VectorProcessor", _FakeVectorProcessor),
        patch("core.vector_large_format.slice_vector_analysis_into_tiles", slicer),
        patch("tempfile.mkstemp", side_effect=_capture_mkstemp),
    ):
        with pytest.raises(LargeFormatCachedAnalysisError):
            worker_generate_large_format_svg_native("image.svg", "lut.npy", params)

    slicer.assert_not_called()
    assert zip_paths == []


def test_native_worker_valid_zero_change_cache_still_succeeds(tmp_path) -> None:
    analysis = _analysis(
        [_red_shape(1.0, 1.0, 9.0, 9.0)],
        width_mm=10.0,
        height_mm=10.0,
    )
    matched = np.full((100, 100, 3), [255, 0, 0], dtype=np.uint8)
    mask = np.ones((100, 100), dtype=bool)
    material = np.ones((100, 100, 5), dtype=np.int16)
    matched_path, mask_path, material_path = _save_cache_paths(
        tmp_path,
        matched,
        mask,
        material,
    )
    strict_calls: list[bool] = []
    changed_values: list[int] = []

    class _FakeVectorProcessor(_SlicerCompatibleProcessor):
        def __init__(self, _lut_path: str, _color_mode: str) -> None:
            self.color_mode = "4-Color"
            self.img_processor = _fake_img_processor()

        def analyze_svg(self, **_kwargs: object) -> VectorAnalysis:
            return analysis

        def build_mesh(self, **_kwargs: object) -> SimpleNamespace:
            return _scene_for_slots({"Red"})

    def _recording_helper(*args: object, **kwargs: object) -> int:
        strict_calls.append(bool(kwargs.get("strict")))
        changed = apply_matched_rgb_overrides_to_analysis(*args, **kwargs)
        changed_values.append(changed)
        return changed

    params = _params(
        total_width_mm=10.0,
        total_height_mm=10.0,
        tile_width_mm=10.0,
        tile_height_mm=10.0,
    )
    params.update(
        matched_rgb_path=matched_path,
        mask_solid_path=mask_path,
        material_matrix_path=material_path,
    )

    result = None
    with (
        patch("core.vector_engine.VectorProcessor", _FakeVectorProcessor),
        patch(
            "core.vector_engine.apply_matched_rgb_overrides_to_analysis",
            side_effect=_recording_helper,
        ),
        patch("api.workers.converter_workers._rasterize_tile_for_cover", return_value=None),
        patch(
            "utils.bambu_3mf_writer.export_scene_with_bambu_metadata",
            side_effect=_write_export,
        ),
    ):
        result = worker_generate_large_format_svg_native("image.svg", "lut.npy", params)

    try:
        assert strict_calls == [True]
        assert changed_values == [0]
        assert result["tile_count"] == 1
    finally:
        if result is not None and os.path.exists(result["zip_path"]):
            os.unlink(result["zip_path"])


def test_native_worker_projects_three_disconnected_local_edits_into_tiles(
    tmp_path,
) -> None:
    shapes = [
        _red_shape(0.5, 0.5, 2.5, 3.5),
        _red_shape(3.2, 0.5, 5.5, 3.5),
        _red_shape(6.7, 0.5, 10.8, 3.5),
    ]
    analysis = _analysis(shapes, width_mm=12.0, height_mm=4.0)
    matched = np.full((40, 120, 3), 255, dtype=np.uint8)
    mask = np.zeros((40, 120), dtype=bool)
    material = np.full((40, 120, 5), -1, dtype=np.int16)

    def _paint(shape_index: int, rgb: tuple[int, int, int], recipe: list[int]) -> None:
        x0, y0, x1, y1 = shapes[shape_index]["geometry"].bounds
        ys = slice(int(round(y0 * 10)), int(round(y1 * 10)) + 1)
        xs = slice(int(round(x0 * 10)), int(round(x1 * 10)) + 1)
        matched[ys, xs, :] = rgb
        mask[ys, xs] = True
        material[ys, xs, :] = np.asarray(recipe, dtype=np.int16)

    _paint(0, (255, 0, 0), [1, 1, 1, 1, 1])
    _paint(1, (0, 255, 0), [2, 1, 2, 1, 2])
    _paint(2, (0, 0, 255), [3, 3, 1, 3, 3])
    matched_path, mask_path, material_path = _save_cache_paths(
        tmp_path,
        matched,
        mask,
        material,
    )
    tile_summaries: list[list[tuple[tuple[int, int, int], tuple[int, ...]]]] = []
    exported_slots: list[set[str]] = []

    class _FakeVectorProcessor(_SlicerCompatibleProcessor):
        def __init__(self, _lut_path: str, _color_mode: str) -> None:
            self.color_mode = "4-Color"
            self.img_processor = _fake_img_processor()

        def analyze_svg(self, **_kwargs: object) -> VectorAnalysis:
            return analysis

        def build_mesh(self, *, analysis: VectorAnalysis, **_kwargs: object) -> SimpleNamespace:
            summary = [
                (tuple(shape["matched_rgb"]), tuple(shape["recipe"]))
                for shape in analysis.matched_shapes
            ]
            tile_summaries.append(summary)
            used_slots = {
                analysis.slot_names[int(shape["recipe"][0])]
                for shape in analysis.matched_shapes
            }
            return _scene_for_slots(used_slots)

    def _capture_export(*, slot_names: list[str], output_path: str, **_kwargs: object) -> None:
        exported_slots.append(set(slot_names))
        _write_export(output_path=output_path)

    params = _params(
        total_width_mm=12.0,
        total_height_mm=4.0,
        tile_width_mm=6.0,
        tile_height_mm=4.0,
    )
    params.update(
        matched_rgb_path=matched_path,
        mask_solid_path=mask_path,
        material_matrix_path=material_path,
    )

    result = None
    with (
        patch("core.vector_engine.VectorProcessor", _FakeVectorProcessor),
        patch("api.workers.converter_workers._rasterize_tile_for_cover", return_value=None),
        patch(
            "utils.bambu_3mf_writer.export_scene_with_bambu_metadata",
            side_effect=_capture_export,
        ),
    ):
        result = worker_generate_large_format_svg_native("image.svg", "lut.npy", params)

    try:
        assert result["tile_count"] == 2
        assert tile_summaries == [
            [
                ((255, 0, 0), (1, 1, 1, 1, 1)),
                ((0, 255, 0), (2, 1, 2, 1, 2)),
            ],
            [((0, 0, 255), (3, 3, 1, 3, 3))],
        ]
        assert exported_slots == [{"Red", "Green"}, {"Blue"}]
    finally:
        if result is not None and os.path.exists(result["zip_path"]):
            os.unlink(result["zip_path"])


def test_native_worker_keeps_pure_global_replacement_flow(tmp_path) -> None:
    analysis = _analysis(
        [_red_shape(1.0, 1.0, 9.0, 9.0)],
        width_mm=10.0,
        height_mm=10.0,
    )
    received_replacements: list[dict[str, str]] = []
    tile_colors: list[tuple[int, int, int]] = []

    class _FakeVectorProcessor(_SlicerCompatibleProcessor):
        def __init__(self, _lut_path: str, _color_mode: str) -> None:
            self.color_mode = "4-Color"
            self.img_processor = _fake_img_processor()

        def analyze_svg(
            self,
            *,
            color_replacements: dict[str, str],
            **_kwargs: object,
        ) -> VectorAnalysis:
            received_replacements.append(dict(color_replacements))
            analysis.matched_shapes[0]["matched_rgb"] = (0, 255, 0)
            analysis.matched_shapes[0]["recipe"] = [2, 2, 2, 2, 2]
            return analysis

        def build_mesh(self, *, analysis: VectorAnalysis, **_kwargs: object) -> SimpleNamespace:
            tile_colors.append(tuple(analysis.matched_shapes[0]["matched_rgb"]))
            return _scene_for_slots({"Green"})

    params = _params(
        total_width_mm=10.0,
        total_height_mm=10.0,
        tile_width_mm=10.0,
        tile_height_mm=10.0,
    )
    params["replacement_regions"] = [
        {
            "matched_hex": "#ff0000",
            "replacement_hex": "#00ff00",
        }
    ]

    result = None
    with (
        patch("core.vector_engine.VectorProcessor", _FakeVectorProcessor),
        patch("api.workers.converter_workers._rasterize_tile_for_cover", return_value=None),
        patch(
            "utils.bambu_3mf_writer.export_scene_with_bambu_metadata",
            side_effect=_write_export,
        ),
    ):
        result = worker_generate_large_format_svg_native("image.svg", "lut.npy", params)

    try:
        assert received_replacements == [{"#ff0000": "#00ff00"}]
        assert tile_colors == [(0, 255, 0)]
        assert result["tile_count"] == 1
    finally:
        if result is not None and os.path.exists(result["zip_path"]):
            os.unlink(result["zip_path"])
