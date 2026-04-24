"""Regression tests for the P03 on-the-fly cache build fallback.
P03 临时缓存构建回退路径的回归测试。

When no persisted ``MaterialSolverCache`` is found on disk, P03 now builds a
temporary low-resolution (64 cubed) cache in-memory via
:func:`core.material_cache.build_material_solver_cache` and uses it for
lookup.  The cross-N ``ensure_not_worse_than_smaller_N`` step is skipped for
cache-based paths (both persisted and on-the-fly).

没有持久化缓存时，P03 现在会现场构建一个最低分辨率 (64^3) 的临时缓存，
用于颜色匹配。缓存路径（持久化和临时）均跳过跨 N 比较。

Locks in:
    * ``solver_path == "cache_built_on_the_fly"`` in ``material_solver_info``;
    * ``build_material_solver_cache`` is invoked exactly once;
    * the cross-N fallback helper is NOT invoked for the on-the-fly cache path;
    * ``material_matrix`` still carries correct Top2Bottom recipes after reversal.
"""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import numpy as np
import pytest
from PIL import Image

from config import ModelingMode
from core.material_color_solver import (
    DEFAULT_LAYER_HEIGHT_MM,
    MaterialParams,
)
from core.pipeline.p03_core_processing import _run_material_archive_branch


# ---------------------------------------------------------------------------
# Fixtures — tiny palette with a well-defined white entry.
# ---------------------------------------------------------------------------


def _mat(name: str, E: tuple, k: tuple) -> MaterialParams:
    return MaterialParams(
        name=name,
        directory_name=name.lower(),
        E=np.asarray(E, dtype=np.float64),
        k=np.asarray(k, dtype=np.float64),
        C0_white=np.asarray((1.0, 1.0, 1.0), dtype=np.float64),
        estimated_rgb=np.asarray(
            [int(round(255 * c)) for c in E], dtype=np.uint8
        ),
    )


RED = _mat("Red", E=(0.6, 0.05, 0.05), k=(4.0, 4.0, 4.0))
BLUE = _mat("Blue", E=(0.05, 0.1, 0.6), k=(4.0, 4.0, 4.0))
WHITE = _mat("White", E=(0.95, 0.95, 0.95), k=(0.5, 0.5, 0.5))
PALETTE_WITH_WHITE = [RED, BLUE, WHITE]


def _write_solid_color_png(path: Path, rgb: tuple[int, int, int], size: int = 4) -> Path:
    arr = np.zeros((size, size, 4), dtype=np.uint8)
    arr[..., 0] = rgb[0]
    arr[..., 1] = rgb[1]
    arr[..., 2] = rgb[2]
    arr[..., 3] = 255
    Image.fromarray(arr, mode="RGBA").save(path)
    return path


def _make_ctx(image_path: Path, *, layer_count: int = 6) -> dict:
    return {
        "image_path": str(image_path),
        "target_width_mm": 2.0,
        "modeling_mode": ModelingMode.PIXEL,
        "quantize_colors": 2,
        "auto_bg": False,
        "bg_tol": 10,
        "_material_params": PALETTE_WITH_WHITE,
        "color_layers": layer_count,
        "layer_height_mm": DEFAULT_LAYER_HEIGHT_MM,
        "material_substrate": "white",
        "material_source": "material_archive",
    }


# ---------------------------------------------------------------------------
# Fake cache stub
# ---------------------------------------------------------------------------


class _FakeCache:
    """Minimal stub that mimics MaterialSolverCache for P03 on-the-fly path."""

    def __init__(self, matched_rgb, recipes, delta_e, layer_count):
        self._matched_rgb = matched_rgb
        self._recipes = recipes
        self._delta_e = delta_e
        self._layer_count = layer_count
        self.valid_cell_count = 1
        self.metadata = {
            "palette_hash": "test",
            "grid_resolution": 64,
            "layer_count": layer_count,
            "mean_delta_e": 0.0,
            "max_delta_e": 0.0,
            "build_time_seconds": 0.01,
            "built_at": "2026-01-01T00:00:00Z",
        }

    @property
    def palette_hash(self):
        return self.metadata["palette_hash"]

    @property
    def grid_resolution(self):
        return int(self.metadata["grid_resolution"])

    @property
    def layer_count(self):
        return self._layer_count

    def lookup(self, target_srgb, user_materials):
        n = target_srgb.shape[0]
        return (
            np.broadcast_to(self._matched_rgb, (n, 3)).copy(),
            np.broadcast_to(self._recipes, (n, self._layer_count)).copy(),
            np.broadcast_to(self._delta_e, (n,)).copy(),
        )


# ---------------------------------------------------------------------------
# On-the-fly cache build tests
# ---------------------------------------------------------------------------


class TestP03OnTheFlyCacheBuild:
    def test_solver_meta_reports_cache_built_on_the_fly(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When no persisted cache exists, ``material_solver_info`` must report
        ``solver_path == "cache_built_on_the_fly"`` with build metadata."""
        image_path = _write_solid_color_png(tmp_path / "red.png", (220, 40, 30))
        ctx = _make_ctx(image_path, layer_count=6)

        red_idx = PALETTE_WITH_WHITE.index(RED)
        recipe = np.full((1, 6), red_idx, dtype=np.int32)
        matched_rgb = np.asarray([[220, 40, 30]], dtype=np.uint8)
        delta_e = np.asarray([1.5], dtype=np.float64)
        fake_cache = _FakeCache(matched_rgb, recipe, delta_e, 6)

        monkeypatch.setattr(
            "core.material_cache.load_material_solver_cache",
            lambda *args, **kwargs: None,
        )
        monkeypatch.setattr(
            "core.material_cache.build_material_solver_cache",
            lambda **kwargs: fake_cache,
        )

        result = _run_material_archive_branch(ctx)
        solver_info = result["material_solver_info"]

        assert solver_info["path"] == "cache_built_on_the_fly"
        assert "build_time_seconds" in solver_info
        assert solver_info["grid_resolution"] == 64
        assert solver_info["grid_fallback_used"] is True
        assert solver_info["reason"] == "no_persisted_cache"
        assert solver_info["mean_delta_e"] == pytest.approx(1.5)
        assert solver_info["max_delta_e"] == pytest.approx(1.5)

    def test_recipe_reaches_material_matrix_after_reversal(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Bottom2Top recipe from on-the-fly cache must be reversed to
        Top2Bottom in ``material_matrix``."""
        image_path = _write_solid_color_png(tmp_path / "red.png", (220, 40, 30))
        ctx = _make_ctx(image_path, layer_count=6)

        red_idx = PALETTE_WITH_WHITE.index(RED)
        white_idx = PALETTE_WITH_WHITE.index(WHITE)
        blue_idx = PALETTE_WITH_WHITE.index(BLUE)
        # Bottom2Top recipe: [W, W, W, B, B, R]
        recipe_b2t = np.asarray(
            [[white_idx, white_idx, white_idx, blue_idx, blue_idx, red_idx]],
            dtype=np.int32,
        )
        fake_cache = _FakeCache(
            np.asarray([[200, 60, 50]], dtype=np.uint8),
            recipe_b2t,
            np.asarray([0.5], dtype=np.float64),
            6,
        )

        monkeypatch.setattr(
            "core.material_cache.load_material_solver_cache",
            lambda *args, **kwargs: None,
        )
        monkeypatch.setattr(
            "core.material_cache.build_material_solver_cache",
            lambda **kwargs: fake_cache,
        )

        result = _run_material_archive_branch(ctx)
        material_matrix = result["material_matrix"]
        mask_solid = result["mask_solid"]

        # Pipeline stores Top2Bottom; the reversal turns [W,W,W,B,B,R] into
        # [R,B,B,W,W,W] along the last axis.
        expected_top_to_bottom = [red_idx, blue_idx, blue_idx, white_idx, white_idx, white_idx]
        assert material_matrix.shape[-1] == 6
        for y, x in np.argwhere(mask_solid):
            actual = material_matrix[y, x].tolist()
            assert actual == expected_top_to_bottom, (
                f"pixel ({y},{x}) got {actual}, expected {expected_top_to_bottom}"
            )


class TestP03OnTheFlyCacheGuards:
    def test_cross_n_fallback_is_not_invoked(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``ensure_not_worse_than_smaller_N`` must NOT be called when the
        on-the-fly cache is used — it is an exhaustive grid result already."""
        image_path = _write_solid_color_png(tmp_path / "red.png", (220, 40, 30))
        ctx = _make_ctx(image_path, layer_count=6)

        red_idx = PALETTE_WITH_WHITE.index(RED)
        recipe = np.full((1, 6), red_idx, dtype=np.int32)
        fake_cache = _FakeCache(
            np.asarray([[220, 40, 30]], dtype=np.uint8),
            recipe,
            np.asarray([0.0], dtype=np.float64),
            6,
        )

        monkeypatch.setattr(
            "core.material_cache.load_material_solver_cache",
            lambda *args, **kwargs: None,
        )
        monkeypatch.setattr(
            "core.material_cache.build_material_solver_cache",
            lambda **kwargs: fake_cache,
        )

        call_counter = {"n": 0}

        def _mock_fallback(*args, **kwargs):
            call_counter["n"] += 1
            raise AssertionError("cross-N fallback should not be called")

        monkeypatch.setattr(
            "core.material_lut_synthesis.ensure_not_worse_than_smaller_N",
            _mock_fallback,
        )

        result = _run_material_archive_branch(ctx)
        assert call_counter["n"] == 0
        assert "not_worse_fallback" not in result["material_solver_info"]

    def test_build_cache_is_invoked_exactly_once(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Pipeline must invoke ``build_material_solver_cache`` exactly once
        when no persisted cache is found."""
        image_path = _write_solid_color_png(tmp_path / "red.png", (220, 40, 30))
        ctx = _make_ctx(image_path, layer_count=6)

        red_idx = PALETTE_WITH_WHITE.index(RED)
        recipe = np.full((1, 6), red_idx, dtype=np.int32)
        fake_cache = _FakeCache(
            np.asarray([[220, 40, 30]], dtype=np.uint8),
            recipe,
            np.asarray([0.0], dtype=np.float64),
            6,
        )

        monkeypatch.setattr(
            "core.material_cache.load_material_solver_cache",
            lambda *args, **kwargs: None,
        )

        call_counter = {"n": 0}

        def _mock_build(**kwargs):
            call_counter["n"] += 1
            assert kwargs["grid_resolution"] == 64
            return fake_cache

        monkeypatch.setattr(
            "core.material_cache.build_material_solver_cache",
            _mock_build,
        )

        _run_material_archive_branch(ctx)
        assert call_counter["n"] == 1
