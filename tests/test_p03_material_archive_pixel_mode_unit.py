from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from config import ModelingMode
from core.material_color_solver import MaterialParams
from core.pipeline.p03_core_processing import _run_material_archive_branch


class _EchoCache:
    def __init__(self, layer_count: int):
        self.layer_count = layer_count
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
        return (
            target_srgb.astype(np.uint8).copy(),
            np.zeros((n, self.layer_count), dtype=np.int32),
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

    def fake_quantize(image: np.ndarray, n_colors: int) -> np.ndarray:
        seen["n_colors"] = n_colors
        seen["input_palette"] = {
            tuple(color) for color in image.reshape(-1, 3)
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
