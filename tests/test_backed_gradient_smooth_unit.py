"""Fixed v3 policy, objective units, held-thickness isolation, and v2 compatibility."""
from copy import deepcopy
import inspect
import time

import numpy as np
import pytest

from core import backed_gradient_fitting_v2 as fitting
from core.backed_gradient_models import restore_backed_gradient_model
from core.backed_gradient_smooth import (
    BackedGradientSmoothTransport,
    SPECTRAL_CURVATURE_WEIGHT,
    SPECTRAL_SMOOTH_MODEL_ID,
    spectral_curvature_residual,
)
from core.backed_gradient_transport import BackedGradientTransport
from core.errors import CoreValidationError
from support.backed_gradient import synthetic_snapshot


def _model(smooth=True):
    prepared = fitting.shared._prepare(synthetic_snapshot(), True)
    vector = fitting._initial(prepared.present, 0)
    return fitting._operator(prepared, vector, smooth=smooth)


def _snapshot():
    model = _model()
    snapshot = synthetic_snapshot()
    for row in snapshot["samples"]:
        row["reflectance_percent_xyz"] = model.predict_backed(row["material_symbol"], row["backing"], row["overlay_mm"]).tolist()
    return snapshot


def test_v3_has_the_same_physics_parameter_count_and_recipe_geometry_as_v2():
    model = _model()
    original = _model(False)
    assert sum(len(values) for values in model.coefficients.values()) == 30
    assert model.to_parameters()["model_id"] == SPECTRAL_SMOOTH_MODEL_ID
    for backing in ("W", "K"):
        np.testing.assert_array_equal(model.predict_recipes(["RYBWW", "WWBYR"], backing), original.predict_recipes(["RYBWW", "WWBYR"], backing))
        np.testing.assert_array_equal(model.predict_recipes(["RRRBBB"], backing, backing_mm=2.52), original.predict_recipes(["RRRBBB"], backing, backing_mm=2.52))
    restored = restore_backed_gradient_model(model.to_parameters())
    assert isinstance(restored, BackedGradientSmoothTransport)
    np.testing.assert_array_equal(restored.predict_recipes(["RYBWW"], "W"), model.predict_recipes(["RYBWW"], "W"))
    with pytest.raises(CoreValidationError):
        BackedGradientTransport.from_parameters(model.to_parameters())
    with pytest.raises(CoreValidationError):
        BackedGradientSmoothTransport.from_parameters(original.to_parameters())


def test_fixed_curvature_uses_only_four_color_absorption_logs_and_ignores_wk():
    coefficients = {"R": [0., 1., 3., 5., 0., 2., .7], "W": [1., 2., 3., 4., .7], "K": [1., 2., 3., .7]}
    expected = SPECTRAL_CURVATURE_WEIGHT * np.array([1., 0.])
    np.testing.assert_array_equal(spectral_curvature_residual(coefficients), expected)
    coefficients["R"][4:] = [3., 0., .2]
    coefficients["W"] = [-3., -4., 1., 0., .05]
    coefficients["K"] = [-2., 4., 4., .98]
    np.testing.assert_array_equal(spectral_curvature_residual(coefficients), expected)
    assert spectral_curvature_residual({"W": coefficients["W"], "K": coefficients["K"]}).size == 0


@pytest.mark.parametrize("mutation", ["objective", "weight", "extra_parameter", "surface", "floor", "boolean_alias"])
def test_restore_rejects_changed_policy_or_inherited_boundary(mutation):
    payload = _model().to_parameters()
    if mutation == "objective":
        payload["objective_id"] = "different_objective"
    elif mutation == "weight":
        payload["regularization"]["weight"] = .004
    elif mutation == "extra_parameter":
        payload["regularization"]["additional_free_parameters"] = 1
    elif mutation == "surface":
        payload["surface_model"] = "different_surface"
    elif mutation == "boolean_alias":
        payload["regularization"]["white_black_penalized"] = 0
    else:
        payload["native_black_floor"] = False
    with pytest.raises(CoreValidationError):
        BackedGradientSmoothTransport.from_parameters(payload)


def test_augmented_objective_is_raw_xyz_fraction_plus_fixed_prior_and_uses_data_count():
    prepared = fitting.shared._prepare(_snapshot(), True)
    vector = fitting._initial(prepared.present, 0)
    for row in prepared.training:
        row["reflectance_percent_xyz"] = (np.asarray(row["reflectance_percent_xyz"]) + [1., 2., 3.]).tolist()
    plain = fitting._spectral_residual(vector, prepared, prepared.training)
    augmented = fitting._spectral_residual(vector, prepared, prepared.training, smooth=True)
    prior = np.concatenate([np.diff(vector[part][:4], n=2) for symbol, part in fitting._slices(prepared.present).items() if symbol not in ("W", "K")])
    np.testing.assert_allclose(plain.reshape(-1, 3), np.tile([-.01, -.02, -.03], (len(prepared.training), 1)), atol=1e-15)
    np.testing.assert_array_equal(augmented[:plain.size], plain)
    np.testing.assert_array_equal(augmented[plain.size:], .003 * prior)


def test_best_attempt_uses_the_regularized_objective_without_changing_legacy_selection():
    attempts = [{"seed": 0, "success": False, "rmse_pp": .9, "regularized_objective_sse": .03},
                {"seed": 1, "success": True, "rmse_pp": 1., "regularized_objective_sse": .02}]
    assert fitting._best_attempt(attempts) is attempts[1]
    plain = [{"seed": 0, "rmse_pp": .9}, {"seed": 1, "rmse_pp": 1.}]
    assert fitting._best_attempt(plain) is plain[0]
