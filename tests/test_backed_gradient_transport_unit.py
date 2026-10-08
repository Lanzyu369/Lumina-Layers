"""Finite-backing spectral transport invariants and serialization boundaries."""
import copy

import numpy as np
import pytest

from core.backed_gradient_optics import BackedGradientOptics
from core.backed_gradient_transport import (
    BackedGradientTransport,
    SPECTRAL_FOUR_FLUX_MODEL_ID,
)
from core.errors import CoreValidationError


def model():
    coefficients = {
        "R": [*np.log([25., 20., 5., .1]), np.log(1.), 1., .7],
        "Y": [*np.log([20., 8., .03, .02]), np.log(2.), 1., .7],
        "B": [*np.log([.01, 1., 25., 25.]), np.log(1.), 1., .7],
        "W": [np.log(.02), 0., np.log(1.), 1., .7],
        "K": [np.log(20.), np.log(.05), 0., .7],
    }
    return BackedGradientTransport(coefficients, {"W": [96.65, 96.52, 101.25], "K": [.102, .080, .066]})


def test_same_material_five_layers_equal_continuous_overlay_for_each_real_backing():
    operator = model()
    for backing in ("W", "K"):
        for symbol in operator.fitted_materials:
            split = operator.predict_recipes([symbol * 5], backing)[0]
            continuous = operator.predict_backed(symbol, backing, .4)
            np.testing.assert_allclose(split, continuous, rtol=1e-11, atol=1e-10)


def test_bare_references_and_homogeneous_three_mm_controls_are_fixed_anchors():
    operator = model()
    for backing in ("W", "K"):
        for material in operator.fitted_materials:
            np.testing.assert_allclose(operator.predict_backed(material, backing, 0), operator.anchors[backing], atol=1e-10)
        readings = operator.predict_backed(backing, backing, np.array([.08, .16, .24, .32, .64, 1.28, 2.]))
        np.testing.assert_allclose(readings, np.tile(operator.anchors[backing], (7, 1)), atol=1e-10)
    assert operator.predict_backed("W", "W", .24)[2] > 100


def test_recipe_position_matches_visible_face_instead_of_per_recipe_correction():
    operator = model()
    forward = operator.predict_recipes(["RYBWW", "WWBYR", "RYYBB", "BBYYR"], "W")
    assert np.max(np.abs(forward[0] - forward[1])) > 1
    assert np.max(np.abs(forward[2] - forward[3])) > 1
    single = np.vstack([operator.predict_recipes([recipe], "W")[0] for recipe in ["RYBWW", "WWBYR", "RYYBB", "BBYYR"]])
    np.testing.assert_allclose(forward, single, rtol=1e-13, atol=1e-12)


def test_backing_decreases_by_overlay_thickness_and_can_change_recipe_predictions():
    operator = model()
    white = operator.predict_backed("R", "W", np.array([.08, .32, 2.]))
    black = operator.predict_backed("R", "K", np.array([.08, .32, 2.]))
    assert np.max(white[0] - black[0]) > 10
    assert np.max(white[-1] - black[-1]) < np.max(white[0] - black[0])
    assert np.isfinite(white).all() and np.isfinite(black).all()


def test_batched_samples_match_individual_predictions_for_both_backings_and_thicknesses():
    operator = model()
    materials = tuple(symbol for symbol in operator.fitted_materials for _ in range(2))
    backings = ("W", "K") * len(operator.fitted_materials)
    thicknesses = np.linspace(.08, 2., len(materials))
    batch = operator.predict_samples(materials, backings, thicknesses)
    single = np.array([operator.predict_backed(symbol, backing, d)
                       for symbol, backing, d in zip(materials, backings, thicknesses)])
    np.testing.assert_allclose(batch, single, atol=1e-11, rtol=1e-12)
    assert operator.predict_samples([], [], []).shape == (0, 3)
    with pytest.raises(CoreValidationError):
        operator.predict_samples(["R"], ["W", "K"], [.08])
    with pytest.raises(CoreValidationError):
        operator.predict_samples(["R"], ["W"], [float("inf")])


def test_explicit_recipe_backing_keeps_bare_three_mm_anchor_and_changes_actual_geometry():
    operator = model()
    recipe = ["RYBWW"]
    default = operator.predict_recipes(recipe, "W")
    explicit = operator.predict_recipes(recipe, "W", backing_mm=2.6)
    np.testing.assert_array_equal(default, explicit)
    changed = operator.predict_recipes(recipe, "W", backing_mm=1.)
    assert np.max(np.abs(changed - default)) > .01
    assert operator.total_mm == 3.
    np.testing.assert_allclose(operator.predict_backed("W", "W", .24), operator.anchors["W"], atol=1e-10)
    for thickness in [0., -.1, float("nan"), True]:
        with pytest.raises(CoreValidationError):
            operator.predict_recipes(recipe, "W", backing_mm=thickness)


def test_spectral_schema_roundtrip_is_independent_and_coefficients_are_immutable():
    operator = model()
    exported = operator.to_parameters()
    assert exported["family"] == "spectral_four_flux"
    assert exported["model_id"] == SPECTRAL_FOUR_FLUX_MODEL_ID
    assert len(exported["materials"]["R"]) == 7
    assert len(exported["materials"]["W"]) == 5
    assert len(exported["materials"]["K"]) == 4
    assert "absorption_xyz" not in exported["materials"]["R"]
    restored = BackedGradientTransport.from_parameters(exported)
    codes = ["RYBWW", "WWBYR", "RYYBB", "BBYYR"]
    np.testing.assert_array_equal(restored.predict_recipes(codes, "W"), operator.predict_recipes(codes, "W"))
    with pytest.raises(CoreValidationError):
        BackedGradientOptics.from_parameters(exported)
    with pytest.raises(ValueError):
        operator.coefficients["W"][0] = 0
    with pytest.raises(ValueError):
        operator.anchors["K"][0] = 1


def test_no_surrogate_for_unmeasured_cmg_and_invalid_geometry_is_rejected():
    operator = model()
    with pytest.raises(CoreValidationError, match="not fitted"):
        operator.predict_backed("C", "W", .24)
    for thickness in [-.08, 3.08, float("nan")]:
        with pytest.raises(CoreValidationError):
            operator.predict_backed("R", "W", thickness)
    for codes in [[], ["RYBWW", "RYB"], ["RYYBC"]]:
        with pytest.raises(CoreValidationError):
            operator.predict_recipes(codes, "W")
    with pytest.raises(CoreValidationError):
        operator.predict_recipes(["R" * 38], "W")
    with pytest.raises(CoreValidationError):
        operator.predict_recipes(["RYBWW"], "W", True)


def test_restore_rejects_legacy_id_and_nonfinite_spectral_fields():
    exported = model().to_parameters()
    changed = copy.deepcopy(exported)
    changed["model_id"] = "backed_gradient_effective_two_flux/v1"
    with pytest.raises(CoreValidationError, match="Unsupported"):
        BackedGradientTransport.from_parameters(changed)
    changed = copy.deepcopy(exported)
    changed["materials"]["W"]["absorption_power"] = float("nan")
    with pytest.raises(CoreValidationError):
        BackedGradientTransport.from_parameters(changed)


@pytest.mark.parametrize("field,value", [
    ("surface_model", "different_surface"), ("internal_interfaces", "air_between_layers"),
    ("observation_mapping", "white_gain_per_material"), ("native_black_floor", False),
    ("native_black_floor", 1),
])
def test_restore_rejects_declared_observation_boundaries_it_cannot_reproduce(field, value):
    exported = model().to_parameters()
    exported[field] = value
    with pytest.raises(CoreValidationError, match="Unsupported"):
        BackedGradientTransport.from_parameters(exported)


def test_restore_rejects_missing_extra_or_ambiguous_coefficient_fields():
    exported = model().to_parameters()
    for change in ("missing_material", "extra_material", "extra_coefficient", "missing_coefficient"):
        changed = copy.deepcopy(exported)
        if change == "missing_material":
            changed["materials"].pop("R")
        elif change == "extra_material":
            changed["materials"]["C"] = dict(changed["materials"]["R"])
        elif change == "extra_coefficient":
            changed["materials"]["W"]["per_material_gain"] = 1.
        else:
            changed["materials"]["K"].pop("forward_fraction")
        with pytest.raises(CoreValidationError):
            BackedGradientTransport.from_parameters(changed)
    changed = copy.deepcopy(exported)
    changed["materials"]["R"]["forward_fraction"] = 1.1
    with pytest.raises(CoreValidationError):
        BackedGradientTransport.from_parameters(changed)


def test_zero_black_anchor_and_bright_white_are_preserved_after_whole_stack_mapping():
    payload = model().to_parameters()
    payload["reference_anchors"] = {"W": [101.25, 103.5, 109.125], "K": [0., 0., 0.]}
    operator = BackedGradientTransport.from_parameters(payload)
    for backing in ("W", "K"):
        expected = np.asarray(payload["reference_anchors"][backing])
        for material in operator.fitted_materials:
            np.testing.assert_allclose(operator.predict_backed(material, backing, 0), expected, atol=1e-10)
        np.testing.assert_allclose(operator.predict_recipes([backing * 5], backing)[0], expected, atol=1e-10)
    assert np.min(operator.predict_recipes(["WWWWW"], "W")) > 100
    predictions = operator.predict_recipes(["RYBWW", "WWBYR", "RYYBB", "BBYYR"], "K")
    assert np.isfinite(predictions).all()
    assert np.min(predictions) >= 0


def test_fixed_spectral_grid_and_xyz_weights_cannot_be_changed_by_a_fit():
    from core.lumina_box_spectral import load_box_spectral_basis

    basis = load_box_spectral_basis()
    np.testing.assert_array_equal(basis.wavelengths, np.arange(360., 835., 5.))
    np.testing.assert_array_equal(basis.anchors, np.linspace(450., 650., 4))
    assert basis.weights.shape == (3, 95)
    assert np.min(basis.weights) >= 0
    np.testing.assert_allclose(basis.weights.sum(axis=1), np.ones(3), atol=1e-12, rtol=0)
    for values in (basis.wavelengths, basis.anchors, basis.weights):
        assert not values.flags.writeable
        with pytest.raises(ValueError):
            values.flat[0] = 0


def test_two_touching_materials_match_independent_matrix_exponential_transport():
    from scipy.linalg import expm

    from core.lumina_box_transport import outer_surface_port, reverse_optical_port

    operator = model()
    front, cosine = outer_surface_port(45.)
    rear = reverse_optical_port(outer_surface_port(0.)[0])

    def surface_transfer(port):
        reflection, back_reflection, transmission, back_transmission = port
        inverse = np.linalg.inv(back_transmission)
        return np.block([[transmission - back_reflection @ inverse @ reflection, back_reflection @ inverse],
                         [-inverse @ reflection, inverse]])

    def bulk_transfer(symbol, wavelength_index, thickness):
        absorption, scattering, fraction = operator._spectra[symbol]
        k, s = absorption[wavelength_index], scattering[wavelength_index]
        attenuation = (k + s) / cosine
        diffuse_absorption = 2 * k
        diffuse_scattering = 2 * (1 - fraction) * s
        forward_scattering = fraction * s / cosine
        backward_scattering = (1 - fraction) * s / cosine
        generator = np.array([
            [-attenuation, 0., 0., 0.],
            [forward_scattering, -diffuse_absorption - diffuse_scattering, backward_scattering, diffuse_scattering],
            [0., 0., attenuation, 0.],
            [-backward_scattering, -diffuse_scattering, -forward_scattering, diffuse_absorption + diffuse_scattering],
        ])
        return expm(generator * thickness)

    for thickness in (.08, .16):
        spectral_response = []
        for index in range(95):
            transfer = (surface_transfer(rear) @ bulk_transfer("W", index, 3 - thickness)
                        @ bulk_transfer("R", index, thickness) @ surface_transfer(front))
            reflection = -np.linalg.solve(transfer[2:, 2:], transfer[2:, :2])
            spectral_response.append(reflection[1, 0])
        latent = np.asarray(spectral_response) @ operator._basis.weights.T
        expected = operator.anchors["K"] + (operator.anchors["W"] - operator.anchors["K"]) * (
            latent - operator._black_latent) / (operator._white_latent - operator._black_latent)
        np.testing.assert_allclose(operator.predict_backed("R", "W", thickness), np.maximum(expected, 0.),
                                   atol=1e-9, rtol=1e-10)
