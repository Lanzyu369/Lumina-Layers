"""Unit tests for thin wrapper behavior in core.converter."""

from __future__ import annotations

import inspect
from unittest.mock import patch

from config import ModelingMode
from core.converter import convert_image_to_3d, generate_final_model


def test_height_identity_path_preserves_legacy_positional_bindings() -> None:
    """New height identity input must not shift either public positional API."""

    for public_api in (convert_image_to_3d, generate_final_model):
        signature = inspect.signature(public_api)
        positional_names = [
            name
            for name, parameter in signature.parameters.items()
            if parameter.kind
            in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            )
        ]
        matched_index = positional_names.index("matched_rgb_path")
        assert positional_names[matched_index : matched_index + 4] == [
            "matched_rgb_path",
            "mask_solid_path",
            "material_matrix_path",
            "reuse_preview_analysis",
        ]
        assert (
            signature.parameters["height_identity_rgb_path"].kind
            is inspect.Parameter.KEYWORD_ONLY
        )

        sentinels = [object() for _ in positional_names]
        bound = signature.bind(*sentinels)
        for name, sentinel in zip(positional_names, sentinels):
            assert bound.arguments[name] is sentinel
        assert "height_identity_rgb_path" not in bound.arguments


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


def test_generate_final_model_forwards_device_profile_id() -> None:
    """generate_final_model should forward registry device profile selection."""

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
            color_mode="4-Color (RYBW)",
            add_loop=False,
            loop_width=4.0,
            loop_length=8.0,
            loop_hole=2.5,
            loop_pos=None,
            modeling_mode=ModelingMode.HIGH_FIDELITY,
            quantize_colors=64,
            device_profile_id="BambuStudio:bbl:bambu-lab-h2d:0.4",
        )

    assert result == ("out.3mf", "out.glb", None, "OK", None)
    assert (
        convert_image_to_3d_mock.call_args.kwargs["device_profile_id"]
        == "BambuStudio:bbl:bambu-lab-h2d:0.4"
    )
