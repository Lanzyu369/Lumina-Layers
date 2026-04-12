"""Unit tests for thin wrapper behavior in core.converter."""

from __future__ import annotations

from unittest.mock import patch

from config import ModelingMode
from core.converter import generate_final_model


def test_generate_final_model_forwards_fridge_magnet_kwargs_intact() -> None:
    """generate_final_model should pass fridge-magnet kwargs through unchanged."""

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

    with patch(
        "core.converter.convert_image_to_3d",
        return_value=("out.3mf", "out.glb", None, "OK", None),
    ) as convert_image_to_3d_mock:
        result = generate_final_model(
            image_path="image.png",
            lut_path="lut.npy",
            target_width_mm=80.0,
            spacer_thick=1.5,
            structure_mode="Single-sided",
            auto_bg=True,
            bg_tol=60,
            color_mode="4-Color (RYBW)",
            add_loop=True,
            loop_width=5.0,
            loop_length=10.0,
            loop_hole=3.0,
            loop_pos=(50.0, 50.0),
            modeling_mode=ModelingMode.HIGH_FIDELITY,
            quantize_colors=64,
            enable_fridge_magnet=True,
            fridge_magnets=expected_fridge_magnets,
        )

    assert result == ("out.3mf", "out.glb", None, "OK", None)
    assert convert_image_to_3d_mock.call_args.kwargs["enable_fridge_magnet"] is True
    assert convert_image_to_3d_mock.call_args.kwargs["fridge_magnets"] == expected_fridge_magnets
