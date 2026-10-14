"""Independent component propagation must preserve the retained v3 results."""
from copy import deepcopy
from itertools import product

import numpy as np
import pytest

from core import backed_gradient_fitting_v2 as legacy
from core.backed_gradient_material import (
    BackedGradientComponent, BackedGradientReference, BackedGradientMaterialModel,
    component_from_parameters, reference_from_parameters,
)
from core.backed_gradient_smooth import BackedGradientSmoothTransport
from core.errors import CoreValidationError


@pytest.fixture
def original():
    symbols = ("R", "Y", "B", "W", "K")
    vector = legacy._initial(symbols, 0)
    return BackedGradientSmoothTransport(
        {symbol: vector[part] for symbol, part in legacy._slices(symbols).items()},
        {"W": [97., 98., 96.], "K": [.01, .02, 0.]},
    )


def test_components_preserve_all_material_thickness_predictions(original):
    parameters = original.to_parameters()
    reference = reference_from_parameters(parameters)
    model = BackedGradientMaterialModel(reference)
    for symbol in original.fitted_materials:
        component = component_from_parameters(parameters, symbol)
        for backing in ("W", "K"):
            thickness = np.array([0., .08, .16, .24, .32, .64, 1.28, 2., 3.])
            np.testing.assert_allclose(model.predict_backed(component, backing, thickness),
                                       original.predict_backed(symbol, backing, thickness), atol=1e-12, rtol=0.)


def test_indexed_recipes_keep_layer_order_and_physics_across_batch_boundaries(original):
    parameters = original.to_parameters()
    symbols = original.fitted_materials
    reference = reference_from_parameters(parameters)
    model = BackedGradientMaterialModel(reference)
    components = [component_from_parameters(parameters, symbol) for symbol in symbols]
    recipes = ["RYBWW", "WWBYR", "RYYBB", "BBYYR"] * 513
    indices = np.array([[symbols.index(symbol) for symbol in recipe[::-1]] for recipe in recipes])
    for backing in ("W", "K"):
        np.testing.assert_allclose(
            model.predict_recipes(components, indices, .08, backing=components[symbols.index(backing)], backing_mm=2.6),
            original.predict_recipes(recipes, backing), atol=1e-12, rtol=0.,
        )
    predicted = model.predict_recipes(components, indices[:2], .08, backing=reference.white, backing_mm=2.6)
    assert not np.allclose(predicted[0], predicted[1])


def test_same_kind_materials_and_other_backing_are_independent(original):
    parameters = original.to_parameters()
    reference = reference_from_parameters(parameters)
    before = reference.to_dict()
    red = component_from_parameters(parameters, "R")
    other_red = BackedGradientComponent("color", (0., 1., 2., 3., 1., 1., .6))
    other_white = BackedGradientComponent("white", (-3., 1., 2., 1., .6))
    model = BackedGradientMaterialModel(reference)
    predicted = model.predict_recipes([red, other_red, other_white], np.array([[0, 0], [1, 1], [2, 2]]), .08,
                                       backing=other_red, backing_mm=1.12)
    assert np.unique(predicted, axis=0).shape == (3, 3)
    assert reference.to_dict() == before
    homogeneous = model.predict_recipes([other_white], np.zeros((1, 10), dtype=int), .08,
                                          backing=other_white, backing_mm=2.2)
    np.testing.assert_allclose(homogeneous[0], model.predict_backed(other_white, "W", 3.), atol=1e-12, rtol=0.)


def test_reference_and_components_roundtrip_without_mutating_source(original):
    source = {"input_hash": "original", "samples": [{"xyz": [0., 101., 105.]}]}
    reference = reference_from_parameters(original.to_parameters(), source=source)
    source["samples"].clear()
    restored = BackedGradientReference.from_dict(reference.to_dict())
    assert len(restored.source["samples"]) == 1
    assert restored.to_dict() == reference.to_dict()
    assert BackedGradientComponent.from_dict(reference.white.to_dict()) == reference.white
    with pytest.raises(CoreValidationError):
        BackedGradientComponent("color", (1., 2.))
    bad = deepcopy(reference.to_dict())
    bad["anchors"]["W"][0] = 0.
    with pytest.raises(CoreValidationError):
        BackedGradientReference.from_dict(bad)


def test_native_zero_and_over_100_are_not_clipped(original):
    payload = original.to_parameters()
    payload["reference_anchors"] = {"W": [105., 103., 110.], "K": [0., 0., 0.]}
    reference = reference_from_parameters(payload)
    model = BackedGradientMaterialModel(reference)
    np.testing.assert_allclose(model.predict_backed(reference.white, "W", .24), [105., 103., 110.], atol=1e-12)
    np.testing.assert_allclose(model.predict_backed(reference.black, "K", .24), [0., 0., 0.], atol=1e-12)


def test_explicit_original_backings_preserve_all_1024_recipes(original):
    reference = reference_from_parameters(original.to_parameters())
    model = BackedGradientMaterialModel(reference, {"W": reference.white.to_dict(), "K": reference.black.to_dict()})
    palette = "RYBW"
    components = [component_from_parameters(original.to_parameters(), symbol) for symbol in palette]
    recipes = ["".join(values) for values in product(palette, repeat=5)]
    indices = np.array([[palette.index(symbol) for symbol in recipe[::-1]] for recipe in recipes])
    for backing in ("W", "K"):
        result = model.predict_recipes(components, indices, .08, backing=model.backings[backing], backing_mm=2.6)
        np.testing.assert_allclose(result, original.predict_recipes(recipes, backing), atol=1e-12, rtol=0.)


def test_selected_generic_backings_change_propagation_without_reanchoring_xyz(original):
    reference = reference_from_parameters(original.to_parameters())
    before = reference.to_dict()
    actual_white = BackedGradientComponent("color", (-3., -3.5, -4., -4.5, .8, .4, .65))
    actual_black = BackedGradientComponent("color", (2., 2.5, 3., 3.5, -2., .4, .65))
    coating = component_from_parameters(original.to_parameters(), "R")
    changed = BackedGradientMaterialModel(reference, {"W": actual_white, "K": actual_black})
    unchanged = BackedGradientMaterialModel(reference)
    for role, backing in changed.backings.items():
        actual = changed.predict_backed(coating, role, .16)
        expected = unchanged.predict_recipes([coating], np.array([[0]]), .16, backing=backing, backing_mm=2.84)[0]
        np.testing.assert_array_equal(actual, expected)
        assert not np.allclose(actual, unchanged.predict_backed(coating, role, .16))
    for component in (reference.white, reference.black, actual_white, actual_black):
        np.testing.assert_array_equal(changed.predict_backed(component, "W", 3.),
                                      unchanged.predict_backed(component, "W", 3.))
    assert reference.to_dict() == before
    assert not np.allclose(changed.predict_backed(actual_white, "W", 3.), reference.anchors["W"])


def test_actual_backings_require_both_materials(original):
    reference = reference_from_parameters(original.to_parameters())
    with pytest.raises(CoreValidationError, match="actual white and black"):
        BackedGradientMaterialModel(reference, {"W": reference.white})


@pytest.mark.parametrize("layer_count", [0, 5, 8, 10])
@pytest.mark.parametrize("backing_symbol", ["W", "K", "R"])
def test_compiled_recipes_match_numpy_fallback(original, monkeypatch, layer_count, backing_symbol):
    from core import backed_gradient_recipe_kernel as kernel

    parameters = original.to_parameters()
    reference = reference_from_parameters(parameters)
    model = BackedGradientMaterialModel(reference)
    components = [component_from_parameters(parameters, symbol) for symbol in original.fitted_materials]
    backing = components[original.fitted_materials.index(backing_symbol)]
    recipes = np.random.default_rng(725).integers(0, len(components), (257, layer_count))
    actual = model.predict_recipes(components, recipes, .08, backing=backing, backing_mm=1.2)
    monkeypatch.setattr(kernel, "predict_compiled", None)
    expected = model.predict_recipes(components, recipes, .08, backing=backing, backing_mm=1.2)
    np.testing.assert_allclose(actual, expected, rtol=1e-13, atol=1e-12)


def test_compiled_ports_reject_upper_triangular_channel():
    from core.backed_gradient_recipe_kernel import pack_ports

    port = np.eye(2)
    port[0, 1] = .1
    with pytest.raises(ValueError, match="lower triangular"):
        pack_ports((port,) * 4)
