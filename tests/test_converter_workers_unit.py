"""Unit tests for converter worker function signatures and picklability.
Converter Worker 函数签名与可序列化性单元测试。

These tests verify that worker functions conform to the ProcessPoolExecutor
contract: they must be top-level picklable functions that accept only
serializable parameters (str, int, float, bool, dict) and return dict.

We do NOT call the actual worker functions (they depend on heavy core modules).
Instead we inspect function metadata and verify picklability.

**Validates: Requirements 2.4, 2.5**
"""

import inspect
import os
import pickle
import types
import zipfile
from types import SimpleNamespace
from typing import get_args, get_origin
from unittest.mock import patch

import numpy as np
import pytest

from api.workers.converter_workers import (
    worker_generate_large_format_svg_native,
    worker_generate_model,
    worker_generate_preview,
)

# Types that are safe to pass across process boundaries via pickle
SERIALIZABLE_TYPES = (str, int, float, bool, dict)


# ---------------------------------------------------------------------------
# Importability
# ---------------------------------------------------------------------------

class TestWorkerImportability:
    """Verify worker functions are importable top-level functions."""

    def test_worker_generate_preview_is_importable(self) -> None:
        """worker_generate_preview should be importable from the module."""
        assert worker_generate_preview is not None

    def test_worker_generate_model_is_importable(self) -> None:
        """worker_generate_model should be importable from the module."""
        assert worker_generate_model is not None

    def test_worker_generate_large_format_svg_native_is_importable(self) -> None:
        """worker_generate_large_format_svg_native should be importable from the module."""
        assert worker_generate_large_format_svg_native is not None

    def test_worker_generate_preview_is_function(self) -> None:
        """worker_generate_preview must be a plain function, not a method."""
        assert isinstance(worker_generate_preview, types.FunctionType)

    def test_worker_generate_model_is_function(self) -> None:
        """worker_generate_model must be a plain function, not a method."""
        assert isinstance(worker_generate_model, types.FunctionType)

    def test_worker_generate_large_format_svg_native_is_function(self) -> None:
        """worker_generate_large_format_svg_native must be a plain function."""
        assert isinstance(worker_generate_large_format_svg_native, types.FunctionType)


# ---------------------------------------------------------------------------
# Picklability (required for ProcessPoolExecutor)
# ---------------------------------------------------------------------------

class TestWorkerPicklability:
    """Worker functions must survive pickle round-trip for ProcessPoolExecutor."""

    def test_worker_generate_preview_is_picklable(self) -> None:
        """pickle.dumps/loads round-trip should return the same function."""
        restored = pickle.loads(pickle.dumps(worker_generate_preview))
        assert restored is worker_generate_preview

    def test_worker_generate_model_is_picklable(self) -> None:
        """pickle.dumps/loads round-trip should return the same function."""
        restored = pickle.loads(pickle.dumps(worker_generate_model))
        assert restored is worker_generate_model

    def test_worker_generate_large_format_svg_native_is_picklable(self) -> None:
        """pickle.dumps/loads round-trip should return the same function."""
        restored = pickle.loads(pickle.dumps(worker_generate_large_format_svg_native))
        assert restored is worker_generate_large_format_svg_native


# ---------------------------------------------------------------------------
# Parameter type annotations — all must be serializable scalars
# ---------------------------------------------------------------------------

class TestParameterAnnotations:
    """Verify all parameter annotations are serializable types."""

    @staticmethod
    def _get_param_annotations(fn) -> dict[str, type]:
        """Extract parameter name → annotation mapping (excluding 'return')."""
        sig = inspect.signature(fn)
        return {
            name: param.annotation
            for name, param in sig.parameters.items()
            if param.annotation is not inspect.Parameter.empty
        }

    @staticmethod
    def _annotation_is_serializable(annotation: object) -> bool:
        if annotation in SERIALIZABLE_TYPES or annotation is type(None):
            return True
        origin = get_origin(annotation)
        if origin is None and isinstance(annotation, types.UnionType):
            return all(
                TestParameterAnnotations._annotation_is_serializable(option)
                for option in get_args(annotation)
            )
        if origin is not None:
            return all(
                TestParameterAnnotations._annotation_is_serializable(option)
                for option in get_args(annotation)
            )
        return False

    def test_preview_params_are_serializable(self) -> None:
        """All worker_generate_preview params must be basic serializable types."""
        annotations = self._get_param_annotations(worker_generate_preview)
        assert len(annotations) > 0, "Function should have type annotations"
        for name, ann in annotations.items():
            assert self._annotation_is_serializable(ann), (
                f"Parameter '{name}' has non-serializable type {ann}"
            )

    def test_model_params_are_serializable(self) -> None:
        """All worker_generate_model params must be basic serializable types."""
        annotations = self._get_param_annotations(worker_generate_model)
        assert len(annotations) > 0, "Function should have type annotations"
        for name, ann in annotations.items():
            assert self._annotation_is_serializable(ann), (
                f"Parameter '{name}' has non-serializable type {ann}"
            )

    def test_large_format_svg_native_params_are_serializable(self) -> None:
        """All worker_generate_large_format_svg_native params must be serializable."""
        annotations = self._get_param_annotations(worker_generate_large_format_svg_native)
        assert len(annotations) > 0, "Function should have type annotations"
        for name, ann in annotations.items():
            assert self._annotation_is_serializable(ann), (
                f"Parameter '{name}' has non-serializable type {ann}"
            )

    def test_preview_has_expected_param_count(self) -> None:
        """worker_generate_preview should expose the full preview parameter set."""
        sig = inspect.signature(worker_generate_preview)
        assert len(sig.parameters) == 22

    def test_model_has_expected_param_count(self) -> None:
        """worker_generate_model should have 3 parameters."""
        sig = inspect.signature(worker_generate_model)
        assert len(sig.parameters) == 3

    def test_large_format_svg_native_has_expected_param_count(self) -> None:
        """worker_generate_large_format_svg_native should have 3 parameters."""
        sig = inspect.signature(worker_generate_large_format_svg_native)
        assert len(sig.parameters) == 3

    def test_preview_param_names(self) -> None:
        """Verify expected parameter names for worker_generate_preview."""
        sig = inspect.signature(worker_generate_preview)
        expected = {
            "image_path", "lut_path", "target_width_mm",
            "color_mode", "modeling_mode", "quantize_colors",
            "color_layers", "layer_height_mm", "enable_cleanup", "is_dark",
            "model_enable", "model_only", "model_threshold", "model_margin",
            "hue_weight", "chroma_gate",
            "material_source", "selected_materials",
            "material_layer_count", "material_layer_height_mm",
        }
        assert set(sig.parameters.keys()) == expected

    def test_model_param_names(self) -> None:
        """Verify expected parameter names for worker_generate_model."""
        sig = inspect.signature(worker_generate_model)
        expected = {"image_path", "lut_path", "params"}
        assert set(sig.parameters.keys()) == expected

    def test_large_format_svg_native_param_names(self) -> None:
        """Verify expected parameter names for worker_generate_large_format_svg_native."""
        sig = inspect.signature(worker_generate_large_format_svg_native)
        expected = {"image_path", "lut_path", "params"}
        assert set(sig.parameters.keys()) == expected


# ---------------------------------------------------------------------------
# Return type annotation — must be dict
# ---------------------------------------------------------------------------

class TestReturnAnnotations:
    """Verify return type annotations are dict."""

    def test_preview_returns_dict(self) -> None:
        """worker_generate_preview return annotation should be dict."""
        hints = inspect.signature(worker_generate_preview).return_annotation
        assert hints is dict

    def test_model_returns_dict(self) -> None:
        """worker_generate_model return annotation should be dict."""
        hints = inspect.signature(worker_generate_model).return_annotation
        assert hints is dict

    def test_large_format_svg_native_returns_dict(self) -> None:
        """worker_generate_large_format_svg_native return annotation should be dict."""
        hints = inspect.signature(worker_generate_large_format_svg_native).return_annotation
        assert hints is dict


# ---------------------------------------------------------------------------
# Top-level function check (not bound to a class)
# ---------------------------------------------------------------------------

class TestTopLevelFunctions:
    """Worker functions must be module-level, not class methods."""

    def test_preview_has_no_self_param(self) -> None:
        """Top-level functions should not have 'self' or 'cls' parameter."""
        sig = inspect.signature(worker_generate_preview)
        assert "self" not in sig.parameters
        assert "cls" not in sig.parameters

    def test_model_has_no_self_param(self) -> None:
        """Top-level functions should not have 'self' or 'cls' parameter."""
        sig = inspect.signature(worker_generate_model)
        assert "self" not in sig.parameters
        assert "cls" not in sig.parameters

    def test_large_format_svg_native_has_no_self_param(self) -> None:
        """Top-level functions should not have 'self' or 'cls' parameter."""
        sig = inspect.signature(worker_generate_large_format_svg_native)
        assert "self" not in sig.parameters
        assert "cls" not in sig.parameters

    def test_preview_qualname_is_module_level(self) -> None:
        """__qualname__ should equal __name__ for top-level functions."""
        assert "." not in worker_generate_preview.__qualname__

    def test_model_qualname_is_module_level(self) -> None:
        """__qualname__ should equal __name__ for top-level functions."""
        assert "." not in worker_generate_model.__qualname__

    def test_large_format_svg_native_qualname_is_module_level(self) -> None:
        """__qualname__ should equal __name__ for top-level functions."""
        assert "." not in worker_generate_large_format_svg_native.__qualname__


def test_worker_generate_model_forwards_fridge_magnet_params_intact() -> None:
    """worker_generate_model should pass fridge-magnet params through untouched."""

    expected_fridge_magnets = [
        {
            "id": "magnet-round",
            "shape": "round",
            "preset_key": "round-18",
            "diameter_mm": 18.0,
            "width_mm": None,
            "height_mm": None,
            "thickness_mm": 2.0,
            "center_x_mm": 20.0,
            "center_y_mm": 25.0,
        },
        {
            "id": "magnet-rect",
            "shape": "rect",
            "preset_key": "rect-20x10",
            "diameter_mm": None,
            "width_mm": 20.0,
            "height_mm": 10.0,
            "thickness_mm": 2.5,
            "center_x_mm": 40.0,
            "center_y_mm": 15.0,
        },
    ]
    params = {
        "target_width_mm": 80.0,
        "spacer_thick": 1.5,
        "structure_mode": "Single-sided",
        "color_mode": "4-Color (RYBW)",
        "add_loop": True,
        "loop_width": 5.0,
        "loop_length": 10.0,
        "loop_hole": 3.0,
        "loop_pos": (50.0, 50.0),
        "enable_fridge_magnet": True,
        "fridge_magnets": expected_fridge_magnets,
        "modeling_mode": "high-fidelity",
    }

    with patch(
        "core.converter.generate_final_model",
        return_value=("out.3mf", "out.glb", None, "OK", None),
    ) as generate_final_model_mock:
        result = worker_generate_model("image.png", "lut.npy", params)

    assert result == {
        "threemf_path": "out.3mf",
        "glb_path": "out.glb",
        "status_msg": "OK",
    }
    generate_final_model_mock.assert_called_once_with(
        image_path="image.png",
        lut_path="lut.npy",
        **params,
    )


def test_worker_generate_preview_accepts_numpy_preview_image(tmp_path) -> None:
    preview_img = np.zeros((4, 6, 4), dtype=np.uint8)
    preview_img[..., 0] = 255
    cache_payload = {"preview_rgba": preview_img.copy(), "color_conf": {}}

    with (
        patch(
            "core.converter.generate_preview_cached",
            return_value=(preview_img, cache_payload, "OK"),
        ),
        patch("config.TEMP_DIR", str(tmp_path)),
    ):
        result = worker_generate_preview(
            image_path="image.png",
            lut_path="lut.npy",
            target_width_mm=60.0,
            color_mode="4-Color (RYBW)",
            modeling_mode="high-fidelity",
            color_layers=10,
            layer_height_mm=0.08,
            quantize_colors=16,
            enable_cleanup=True,
        )

    assert result["status_msg"] == "OK"
    assert result["preview_png_path"] is not None
    assert result["cache_data_path"] is not None
    assert os.path.exists(result["preview_png_path"])
    assert os.path.exists(result["cache_data_path"])

    try:
        with open(result["cache_data_path"], "rb") as handle:
            restored_cache = pickle.load(handle)
        assert restored_cache["preview_rgba"].shape == (4, 6, 4)
    finally:
        os.unlink(result["preview_png_path"])
        os.unlink(result["cache_data_path"])


def test_worker_generate_large_format_svg_native_uses_sanitized_tile_prefix_in_zip_entries(tmp_path) -> None:
    """Native SVG worker should emit safe ZIP entry names using tile_name_prefix."""

    class _FakeVectorProcessor:
        def __init__(self, lut_path: str, color_mode: str) -> None:
            self.lut_path = lut_path
            self.color_mode = color_mode

        def analyze_svg(self, **_kwargs):
            return "analysis"

        def build_mesh(self, **_kwargs):
            fake_geom = SimpleNamespace(vertices=[(0, 0, 0)], faces=[(0, 0, 0)])
            return SimpleNamespace(geometry={"Slot1": fake_geom})

    fake_tile = SimpleNamespace(
        label="R1C1",
        analysis=SimpleNamespace(
            preview_colors={0: [255, 0, 0, 255]},
            slot_names=["Slot1"],
        ),
    )

    def _fake_export_scene_with_bambu_metadata(*, output_path: str, **_kwargs) -> None:
        with open(output_path, "wb") as handle:
            handle.write(b"3mf")

    params = {
        "tile_name_prefix": r"bad:name*",
        "total_width_mm": 120.0,
        "total_height_mm": 80.0,
        "tile_width_mm": 60.0,
        "tile_height_mm": 80.0,
        "spacer_thick": 1.2,
        "structure_mode": "Single-sided",
        "color_mode": "4-Color",
        "replacement_regions": [],
        "separate_backing": False,
    }

    with (
        patch("core.pipeline.s03_color_replacement._normalize_color_replacements_input", return_value={}),
        patch("core.vector_engine.VectorProcessor", _FakeVectorProcessor),
        patch("core.vector_large_format.slice_vector_analysis_into_tiles", return_value=[fake_tile]),
        patch("utils.bambu_3mf_writer.export_scene_with_bambu_metadata", side_effect=_fake_export_scene_with_bambu_metadata),
    ):
        result = worker_generate_large_format_svg_native("image.svg", "lut.npy", params)

    try:
        with zipfile.ZipFile(result["zip_path"], "r") as archive:
            assert archive.namelist() == ["bad_name_R1C1.3mf"]
    finally:
        if os.path.exists(result["zip_path"]):
            os.unlink(result["zip_path"])


def test_worker_generate_large_format_svg_native_raises_when_all_tiles_are_empty() -> None:
    """Native SVG worker should surface the empty-slice failure clearly."""

    class _FakeVectorProcessor:
        def __init__(self, lut_path: str, color_mode: str) -> None:
            self.lut_path = lut_path
            self.color_mode = color_mode

        def analyze_svg(self, **_kwargs):
            return "analysis"

    params = {
        "tile_name_prefix": "poster-art",
        "total_width_mm": 120.0,
        "total_height_mm": 80.0,
        "tile_width_mm": 60.0,
        "tile_height_mm": 80.0,
        "spacer_thick": 1.2,
        "structure_mode": "Single-sided",
        "color_mode": "4-Color",
        "replacement_regions": [],
        "separate_backing": False,
    }

    with (
        patch("core.pipeline.s03_color_replacement._normalize_color_replacements_input", return_value={}),
        patch("core.vector_engine.VectorProcessor", _FakeVectorProcessor),
        patch("core.vector_large_format.slice_vector_analysis_into_tiles", return_value=[]),
    ):
        with pytest.raises(ValueError, match="All SVG large-format tiles were empty after slicing"):
            worker_generate_large_format_svg_native("image.svg", "lut.npy", params)


def test_worker_generate_large_format_svg_native_cleans_current_tile_file_on_export_exception() -> None:
    """Native SVG worker should delete the current tile file if export fails before append."""

    class _FakeVectorProcessor:
        def __init__(self, lut_path: str, color_mode: str) -> None:
            self.lut_path = lut_path
            self.color_mode = color_mode

        def analyze_svg(self, **_kwargs):
            return "analysis"

        def build_mesh(self, **_kwargs):
            fake_geom = SimpleNamespace(vertices=[(0, 0, 0)], faces=[(0, 0, 0)])
            return SimpleNamespace(geometry={"Slot1": fake_geom})

    fake_tiles = [
        SimpleNamespace(
            label="R1C1",
            analysis=SimpleNamespace(preview_colors={0: [255, 0, 0, 255]}, slot_names=["Slot1"]),
        ),
    ]
    created_paths: list[str] = []

    def _fake_export_scene_with_bambu_metadata(*, output_path: str, **_kwargs) -> None:
        with open(output_path, "wb") as handle:
            handle.write(b"3mf")
        created_paths.append(output_path)
        raise RuntimeError("tile export failed")

    params = {
        "tile_name_prefix": "poster-art",
        "total_width_mm": 120.0,
        "total_height_mm": 80.0,
        "tile_width_mm": 60.0,
        "tile_height_mm": 80.0,
        "spacer_thick": 1.2,
        "structure_mode": "Single-sided",
        "color_mode": "4-Color",
        "replacement_regions": [],
        "separate_backing": False,
    }

    with (
        patch("core.pipeline.s03_color_replacement._normalize_color_replacements_input", return_value={}),
        patch("core.vector_engine.VectorProcessor", _FakeVectorProcessor),
        patch("core.vector_large_format.slice_vector_analysis_into_tiles", return_value=fake_tiles),
        patch("utils.bambu_3mf_writer.export_scene_with_bambu_metadata", side_effect=_fake_export_scene_with_bambu_metadata),
    ):
        with pytest.raises(RuntimeError, match="tile export failed"):
            worker_generate_large_format_svg_native("image.svg", "lut.npy", params)

    assert created_paths
    assert all(not os.path.exists(path) for path in created_paths)
