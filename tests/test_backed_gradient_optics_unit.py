"""Math contracts for touching layers and calibrated finite substrates."""
import copy

import numpy as np
import pytest
from scipy.linalg import expm

from core.backed_gradient_optics import BackedGradientOptics, MATERIAL_SYMBOLS
from core.errors import CoreValidationError


def coefficients(family):
    values = np.ones((len(MATERIAL_SYMBOLS), 3, 2))
    if family == "affine":
        values[..., 0] = 2
        values[..., 1] = .4
        values[3, :, 1] = 1
        values[4, :, 1] = .02
        values[0, :, 1] = [.6, .2, .1]
        values[2, :, 1] = [.1, .2, .6]
    else:
        values[..., 0] = .4
        values[..., 1] = 1
        values[3, :, 0] = .03
        values[3, :, 1] = 3
        values[4, :, 0] = 7
        values[4, :, 1] = .08
        values[0, :, 0] = [.3, 2, 3]
        values[2, :, 0] = [3, 2, .3]
    return values


def operator(family):
    return BackedGradientOptics(family, coefficients(family), {"W": [98, 99, 100.5], "K": [0, 0, 0]})


def independent_rt(k, s, thickness):
    matrix = np.array([[-k - s, s], [-s, k + s]])
    transfer = expm(matrix * thickness)
    return -transfer[1, 0] / transfer[1, 1], 1 / transfer[1, 1]


@pytest.mark.parametrize("family", ["affine", "two_flux"])
def test_same_material_split_and_independent_measured_anchors(family):
    model = operator(family)
    for symbol in model.fitted_materials:
        together = model.latent_material(symbol, .24)
        split = model.add_material(symbol, .08, model.latent_material(symbol, .16))
        np.testing.assert_allclose(together, split, rtol=1e-11, atol=1e-12)
    for symbol in ("W", "K"):
        actual = model.predict_backed(symbol, symbol, [.08, .16, .8, 2])
        np.testing.assert_allclose(actual, np.tile(model.anchors[symbol], (4, 1)), atol=1e-10)
        np.testing.assert_allclose(model.predict_backed("R", symbol, 0), model.anchors[symbol], atol=1e-10)
    assert model.anchors["W"][2] > 100
    assert model.coefficients[4, 0, 1] > 0  # A reported zero is not zero physical scattering/asymptote.


def test_two_flux_uses_actual_remaining_substrate_not_ideal_or_constant_backing():
    model = operator("two_flux")
    d = .8
    expected = []
    for channel in range(3):
        r, t = independent_rt(*model.coefficients[0, channel], d)
        rear, _ = independent_rt(*model.coefficients[3, channel], 3 - d)
        white, _ = independent_rt(*model.coefficients[3, channel], 3)
        black, _ = independent_rt(*model.coefficients[4, channel], 3)
        latent = r + t * t * rear / (1 - r * rear)
        expected.append(model.anchors["W"][channel] * (latent - black) / (white - black))
    np.testing.assert_allclose(model.predict_backed("R", "W", d), expected, atol=1e-10)
    actual = model.predict_backed("R", "W", d)
    wrong = model.report(model.add_material("R", d, model.latent_material("W", 3)))
    assert np.max(np.abs(actual - wrong)) > .01


@pytest.mark.parametrize("family", ["affine", "two_flux"])
def test_visible_order_is_retained_and_parameters_round_trip(family):
    model = operator(family)
    prediction = model.predict_recipes(["RYBWW", "WWBYR"], "W")
    assert np.max(np.abs(prediction[0] - prediction[1])) > .1
    restored = BackedGradientOptics.from_parameters(model.to_parameters())
    np.testing.assert_array_equal(restored.predict_recipes(["RYBWW", "WWBYR"], "W"), prediction)
    assert np.isfinite(model.predict_recipes(["WWWWW", "BBBBB"], "K")).all()


def test_affine_common_scale_is_a_gauge_and_white_gauge_is_enforced():
    model = operator("affine")
    latent = model.latent_material("R", .5)
    white, black = model.latent_material("W", 3), model.latent_material("K", 3)
    scaled = model.anchors["K"] + (model.anchors["W"] - model.anchors["K"]) * (3 * latent - 3 * black) / (3 * white - 3 * black)
    np.testing.assert_allclose(scaled, model.report(latent))
    invalid = coefficients("affine")
    invalid[3, :, 1] = .98
    with pytest.raises(CoreValidationError, match="gauge"):
        BackedGradientOptics("affine", invalid, model.anchors)


def test_zero_coefficients_and_large_thickness_are_finite():
    values = coefficients("two_flux")
    values[0] = 0
    model = BackedGradientOptics("two_flux", values, {"W": [98, 98, 98], "K": [0, 0, 0]})
    np.testing.assert_array_equal(model.latent_material("R", [0, 10000]), np.zeros((2, 3)))
    np.testing.assert_array_equal(model.add_material("R", 2, np.array([.1, .2, .3])), [.1, .2, .3])


def test_native_black_subtraction_floor_and_unfitted_optional_materials():
    model = operator("two_flux")
    latent = model.latent_material("K", 3) - .01
    assert np.all(model.report_unfloored(latent) < 0)
    np.testing.assert_array_equal(model.report(latent), [0, 0, 0])
    assert set(model.to_parameters()["materials"]) == set("RYBWK")
    with pytest.raises(CoreValidationError, match="not fitted"):
        model.predict_backed("C", "W", .16)
    with pytest.raises(ValueError):
        model.anchors["W"][0] = 0
