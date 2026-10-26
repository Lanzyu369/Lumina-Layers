"""Contract tests for canonical material-recipe colour prediction.

耗材配方颜色预测的统一契约测试。
"""

from __future__ import annotations

import numpy as np
import pytest

from core.material_color_solver import (
    MaterialParams,
    forward_model,
    linear_to_srgb_float,
    predict_material_recipe_srgb,
)


def _probe_material() -> MaterialParams:
    return MaterialParams(
        name="Rounding probe",
        directory_name="rounding-probe",
        E=np.asarray((0.2, 0.4, 0.6), dtype=np.float64),
        k=np.asarray((1.3, 1.1, 0.9), dtype=np.float64),
        C0_white=np.asarray((0.3, 0.4, 0.5), dtype=np.float64),
        estimated_rgb=np.asarray((120, 140, 160), dtype=np.uint8),
    )


def test_white_substrate_uses_canonical_rounding() -> None:
    material = _probe_material()
    recipe = np.zeros(5, dtype=np.int32)

    predicted = predict_material_recipe_srgb(
        recipe,
        [material],
        layer_height_mm=0.08,
        substrate="white",
    )
    legacy_truncated = (
        linear_to_srgb_float(
            forward_model(
                recipe,
                [material],
                0.08,
                np.ones(3, dtype=np.float64),
            )
        )
        * 255.0
    ).astype(np.uint8)

    assert predicted.tolist() == [214, 229, 241]
    assert legacy_truncated.tolist() == [214, 229, 240]


def test_black_substrate_is_pure_black() -> None:
    material = _probe_material()
    recipe = np.zeros(5, dtype=np.int32)

    predicted = predict_material_recipe_srgb(
        recipe,
        [material],
        layer_height_mm=0.08,
        substrate="black",
    )
    near_black = (
        linear_to_srgb_float(
            forward_model(
                recipe,
                [material],
                0.08,
                np.full(3, 0.01, dtype=np.float64),
            )
        )
        * 255.0
    ).round().astype(np.uint8)

    assert predicted.tolist() == [80, 105, 118]
    assert near_black.tolist() == [83, 108, 120]


def test_invalid_substrate_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unsupported substrate"):
        predict_material_recipe_srgb(
            np.zeros(1, dtype=np.int32),
            [_probe_material()],
            layer_height_mm=0.08,
            substrate="transparent",
        )
