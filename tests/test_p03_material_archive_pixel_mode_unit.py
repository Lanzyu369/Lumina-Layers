from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from config import ModelingMode
from core.material_color_solver import MaterialParams
from core.pipeline.p03_core_processing import _run_material_archive_branch


class _EchoCache:
    """Echo target RGB while returning an explicit target-to-recipe mapping."""

    def __init__(
        self,
        layer_count: int,
        recipe_by_rgb: dict[tuple[int, int, int], tuple[int, ...]] | None = None,
    ):
        self.layer_count = layer_count
        self.recipe_by_rgb = recipe_by_rgb or {}
        self.grid_resolution = 64
        self.valid_cell_count = 1
        self.mode = "candidate_hybrid"
        self.metadata = {
            "palette_hash": "pixel-test",
            "grid_resolution": 64,
            "layer_count": layer_count,
            "mean_delta_e": 0.0,
            "max_delta_e": 0.0,
        }

    @property
    def palette_hash(self) -> str:
        return str(self.metadata["palette_hash"])

    def lookup(self, target_srgb, user_materials):
        del user_materials
        n = target_srgb.shape[0]
        recipes = np.zeros((n, self.layer_count), dtype=np.int32)
        for index, target in enumerate(target_srgb):
            recipe = self.recipe_by_rgb.get(tuple(int(value) for value in target))
            if recipe is not None:
                if len(recipe) != self.layer_count:
                    raise AssertionError("fake recipe must match layer_count")
                recipes[index] = np.asarray(recipe, dtype=np.int32)
        return (
            target_srgb.astype(np.uint8).copy(),
            recipes,
            np.zeros((n,), dtype=np.float64),
        )


def _material(name: str, rgb: tuple[int, int, int]) -> MaterialParams:
    estimated = np.asarray(rgb, dtype=np.uint8)
    linear = np.asarray(rgb, dtype=np.float64) / 255.0
    return MaterialParams(
        name=name,
        directory_name=name,
        E=linear,
        k=np.ones(3, dtype=np.float64),
        C0_white=np.ones(3, dtype=np.float64),
        estimated_rgb=estimated,
    )


def _write_pixel_art(path: Path) -> tuple[Path, set[tuple[int, int, int]]]:
    colors = [
        (250, 250, 250),
        (245, 245, 245),
        (240, 240, 240),
        (235, 235, 235),
        (230, 230, 230),
        (225, 225, 225),
        (220, 220, 220),
        (215, 215, 215),
        (210, 210, 210),
    ]
    rgb = np.zeros((12, 12, 3), dtype=np.uint8)
    for idx, color in enumerate(colors):
        y = (idx // 3) * 4
        x = (idx % 3) * 4
        rgb[y : y + 4, x : x + 4] = color
    rgba = np.dstack([rgb, np.full((12, 12), 255, dtype=np.uint8)])
    Image.fromarray(rgba, mode="RGBA").save(path)
    return path, {tuple(color) for color in colors}


def _write_semitransparent_pixel(path: Path) -> Path:
    rgba = np.array([[[13, 13, 13, 20]]], dtype=np.uint8)
    Image.fromarray(rgba, mode="RGBA").save(path)
    return path


def _write_dynamic_range_pixels(path: Path) -> Path:
    rgba = np.array(
        [[
            [13, 13, 13, 20],
            [240, 240, 240, 255],
        ]],
        dtype=np.uint8,
    )
    Image.fromarray(rgba, mode="RGBA").save(path)
    return path


def _write_sparse_visible_palette(path: Path) -> Path:
    rgba = np.zeros((10, 10, 4), dtype=np.uint8)
    visible_colors = np.array(
        [
            [0, 0, 0],
            [255, 0, 0],
            [0, 255, 0],
            [0, 0, 255],
            [255, 255, 0],
            [255, 0, 255],
            [0, 255, 255],
            [128, 128, 128],
            [255, 128, 0],
        ],
        dtype=np.uint8,
    )
    rgba[9, 1:10, :3] = visible_colors
    rgba[9, 1:10, 3] = 255
    Image.fromarray(rgba, mode="RGBA").save(path)
    return path


def test_material_archive_pixel_mode_preserves_exact_palette_when_budget_allows(
    tmp_path: Path, monkeypatch
) -> None:
    image_path, input_palette = _write_pixel_art(tmp_path / "pixel-art.png")
    layer_count = 5
    fake_cache = _EchoCache(layer_count=layer_count)

    import core.material_lut_provider as provider

    monkeypatch.setattr(
        provider,
        "load_solver_cache",
        lambda *args, **kwargs: (fake_cache, 64),
    )
    monkeypatch.setattr(
        provider,
        "load_solver_runtime",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("runtime should not be needed when cache is present")
        ),
    )

    ctx = {
        "image_path": str(image_path),
        "target_width_mm": 1.2,
        "modeling_mode": ModelingMode.PIXEL,
        "quantize_colors": 16,
        "_material_params": [
            _material("black", (0, 0, 0)),
            _material("white", (255, 255, 255)),
        ],
        "color_layers": layer_count,
        "layer_height_mm": 0.08,
        "material_substrate": "white",
        "material_source": "material_archive",
        "enable_cleanup": False,
    }

    result = _run_material_archive_branch(ctx)

    assert "error" not in result
    output_palette = {
        tuple(color)
        for color in result["quantized_image"][result["mask_solid"]].reshape(-1, 3)
    }
    assert output_palette == input_palette


def test_material_archive_pixel_mode_quantizes_raw_pixels_when_budget_exceeded(
    tmp_path: Path, monkeypatch
) -> None:
    image_path, input_palette = _write_pixel_art(tmp_path / "pixel-art.png")
    layer_count = 5
    fake_cache = _EchoCache(layer_count=layer_count)
    seen: dict[str, object] = {}

    import core.material_lut_provider as provider
    import core.pipeline.processing_ops.kmeans_quantizer as quantizer

    def fake_quantize(
        image: np.ndarray,
        n_colors: int,
        *,
        mask: np.ndarray | None = None,
    ) -> np.ndarray:
        seen["n_colors"] = n_colors
        seen["input_palette"] = {
            tuple(color)
            for color in image[mask].reshape(-1, 3)
        }
        return image.copy()

    monkeypatch.setattr(
        provider,
        "load_solver_cache",
        lambda *args, **kwargs: (fake_cache, 64),
    )
    monkeypatch.setattr(
        provider,
        "load_solver_runtime",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("runtime should not be needed when cache is present")
        ),
    )
    monkeypatch.setattr(quantizer, "quantize_colors", fake_quantize)

    ctx = {
        "image_path": str(image_path),
        "target_width_mm": 1.2,
        "modeling_mode": ModelingMode.PIXEL,
        "quantize_colors": 4,
        "_material_params": [
            _material("black", (0, 0, 0)),
            _material("white", (255, 255, 255)),
        ],
        "color_layers": layer_count,
        "layer_height_mm": 0.08,
        "material_substrate": "white",
        "material_source": "material_archive",
        "enable_cleanup": False,
    }

    result = _run_material_archive_branch(ctx)

    assert "error" not in result
    assert seen["n_colors"] == 4
    assert seen["input_palette"] == input_palette


def test_material_archive_pixel_mode_uses_white_canvas_before_solver_substrate(
    tmp_path: Path, monkeypatch
) -> None:
    image_path = _write_semitransparent_pixel(tmp_path / "semitransparent.png")
    layer_count = 5
    fake_cache = _EchoCache(
        layer_count=layer_count,
        recipe_by_rgb={(236, 236, 236): (0, 1, 1, 0, 1)},
    )

    import core.material_lut_provider as provider

    monkeypatch.setattr(
        provider,
        "load_solver_cache",
        lambda *args, **kwargs: (fake_cache, 64),
    )
    monkeypatch.setattr(
        provider,
        "load_solver_runtime",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("runtime should not be needed when cache is present")
        ),
    )

    ctx = {
        "image_path": str(image_path),
        "target_width_mm": 0.1,
        "modeling_mode": ModelingMode.PIXEL,
        "quantize_colors": 16,
        "_material_params": [
            _material("black", (0, 0, 0)),
            _material("white", (255, 255, 255)),
        ],
        "color_layers": layer_count,
        "layer_height_mm": 0.08,
        "material_substrate": "white",
        "material_source": "material_archive",
        "enable_cleanup": False,
    }

    result = _run_material_archive_branch(ctx)

    assert "error" not in result
    assert result["mask_solid"].all()
    assert np.array_equal(
        result["quantized_image"][0, 0],
        np.array([236, 236, 236], dtype=np.uint8),
    )
    assert np.array_equal(
        result["matched_rgb"][0, 0],
        np.array([236, 236, 236], dtype=np.uint8),
    )
    assert np.array_equal(
        result["material_matrix"][0, 0],
        np.array([1, 0, 1, 1, 0], dtype=np.int32),
    )

    black_substrate_result = _run_material_archive_branch(
        {**ctx, "material_substrate": "black"}
    )
    assert np.array_equal(
        black_substrate_result["quantized_image"][0, 0],
        np.array([236, 236, 236], dtype=np.uint8),
    )


def test_material_archive_pixel_mode_composites_before_auto_dynamic_range(
    tmp_path: Path, monkeypatch
) -> None:
    image_path = _write_dynamic_range_pixels(tmp_path / "dynamic-range.png")
    fake_cache = _EchoCache(layer_count=5)
    fake_cache.lab_centers = np.array(
        [[20.0, 0.0, 0.0], [80.0, 0.0, 0.0]],
        dtype=np.float64,
    )

    import core.material_lut_provider as provider

    monkeypatch.setattr(
        provider,
        "load_solver_cache",
        lambda *args, **kwargs: (fake_cache, 64),
    )
    monkeypatch.setattr(
        provider,
        "load_solver_runtime",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("runtime should not be needed when cache is present")
        ),
    )

    result = _run_material_archive_branch(
        {
            "image_path": str(image_path),
            "target_width_mm": 0.2,
            "modeling_mode": ModelingMode.PIXEL,
            "quantize_colors": 16,
            "_material_params": [
                _material("black", (0, 0, 0)),
                _material("white", (255, 255, 255)),
            ],
            "color_layers": 5,
            "layer_height_mm": 0.08,
            "material_substrate": "white",
            "material_source": "material_archive",
            "auto_dynamic_range": True,
            "enable_cleanup": False,
        }
    )

    assert "error" not in result
    assert np.array_equal(
        result["quantized_image"][0],
        np.array([[236, 236, 236], [240, 240, 240]], dtype=np.uint8),
    )


def test_material_archive_pixel_mode_kmeans_ignores_transparent_air(
    tmp_path: Path, monkeypatch
) -> None:
    image_path = _write_sparse_visible_palette(tmp_path / "sparse-palette.png")
    fake_cache = _EchoCache(layer_count=5)

    import core.material_lut_provider as provider

    monkeypatch.setattr(
        provider,
        "load_solver_cache",
        lambda *args, **kwargs: (fake_cache, 64),
    )
    monkeypatch.setattr(
        provider,
        "load_solver_runtime",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("runtime should not be needed when cache is present")
        ),
    )

    result = _run_material_archive_branch(
        {
            "image_path": str(image_path),
            "target_width_mm": 1.0,
            "modeling_mode": ModelingMode.PIXEL,
            "quantize_colors": 8,
            "_material_params": [
                _material("black", (0, 0, 0)),
                _material("white", (255, 255, 255)),
            ],
            "color_layers": 5,
            "layer_height_mm": 0.08,
            "material_substrate": "white",
            "material_source": "material_archive",
            "enable_cleanup": False,
        }
    )

    assert "error" not in result
    assert int(np.count_nonzero(result["mask_solid"])) == 9
    visible_quantized = result["quantized_image"][result["mask_solid"]]
    assert np.unique(visible_quantized, axis=0).shape[0] == 8
    assert np.all(result["material_matrix"][~result["mask_solid"]] == -1)


def test_material_archive_pixel_mode_kmeans_honors_alpha_air_boundary(
    tmp_path: Path, monkeypatch
) -> None:
    image_path = tmp_path / "alpha-boundary.png"
    rgba = np.array(
        [[
            [1, 1, 1, 9],
            [0, 0, 0, 10],
            [64, 64, 64, 255],
        ]],
        dtype=np.uint8,
    )
    Image.fromarray(rgba, mode="RGBA").save(image_path)
    fake_cache = _EchoCache(layer_count=5)
    seen: dict[str, object] = {}

    import core.material_lut_provider as provider
    import core.pipeline.processing_ops.kmeans_quantizer as quantizer

    def fake_quantize(
        image: np.ndarray,
        n_colors: int,
        *,
        mask: np.ndarray | None = None,
    ) -> np.ndarray:
        if mask is None:
            raise AssertionError("pixel-mode K-Means must receive mask_solid")
        seen["shape"] = image[mask].reshape(1, -1, 3).shape
        seen["colors"] = image[mask].reshape(-1, 3).copy()
        seen["n_colors"] = n_colors
        return image.copy()

    monkeypatch.setattr(
        provider,
        "load_solver_cache",
        lambda *args, **kwargs: (fake_cache, 64),
    )
    monkeypatch.setattr(quantizer, "quantize_colors", fake_quantize)

    result = _run_material_archive_branch(
        {
            "image_path": str(image_path),
            "target_width_mm": 0.3,
            "modeling_mode": ModelingMode.PIXEL,
            "quantize_colors": 1,
            "_material_params": [
                _material("black", (0, 0, 0)),
                _material("white", (255, 255, 255)),
            ],
            "color_layers": 5,
            "layer_height_mm": 0.08,
            "material_substrate": "white",
            "material_source": "material_archive",
            "enable_cleanup": False,
        }
    )

    assert "error" not in result
    assert result["mask_solid"].tolist() == [[False, True, True]]
    assert seen["shape"] == (1, 2, 3)
    assert seen["n_colors"] == 1
    assert np.all(result["material_matrix"][0, 0] == -1)
