"""Focused tests for the effective XYZ Kubelka-Munk optical core."""

from __future__ import annotations

import json
import warnings
from types import SimpleNamespace

import numpy as np
import pytest
from scipy.linalg import expm

import core.km_xyz as km_xyz_module
from core.errors import CoreValidationError
from core.km_xyz import (
    D65_10_WHITE_XYZ,
    KMValidationError,
    KMXYZParameters,
    KM_XYZ_COLOR_BRIDGE_ID,
    KM_XYZ_FIT_OBJECTIVE_ID,
    KM_XYZ_MEASUREMENT_PROTOCOL_ID,
    KM_XYZ_MEASUREMENT_REFLECTION_BOUNDARY_ID,
    KM_XYZ_MEASUREMENT_THICKNESS_OFFSET_MAX_MM,
    effective_d65_10_to_xyz_d65_2,
    fit_paired_km_xyz,
    km_layer_rt,
    km_relative_xyz_to_lab,
    km_relative_xyz_to_linear_srgb,
    km_stack_reflectance,
    linear_srgb_to_km_relative_xyz,
    relative_xyz_to_effective_d65_10,
    xyz_d65_2_to_effective_d65_10,
)


def _matrix_stack_reflectance(
    absorption: np.ndarray,
    scattering: np.ndarray,
    thicknesses: np.ndarray,
    backing: np.ndarray,
) -> np.ndarray:
    """Independent moderate-range transfer-matrix reference implementation."""
    result = np.empty(3, dtype=np.float64)
    for channel in range(3):
        total = np.eye(2, dtype=np.float64)
        for layer in range(absorption.shape[0] - 1, -1, -1):
            k_value = absorption[layer, channel]
            s_value = scattering[layer, channel]
            generator = np.array(
                [
                    [-(k_value + s_value), s_value],
                    [-s_value, k_value + s_value],
                ],
                dtype=np.float64,
            )
            total = expm(generator * thicknesses[layer]) @ total
        m00, m01 = total[0]
        m10, m11 = total[1]
        result[channel] = (
            backing[channel] * m00 - m10
        ) / (m11 - backing[channel] * m01)
    return result


def _matrix_layer_rt(
    absorption: np.ndarray,
    scattering: np.ndarray,
    thicknesses: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Generate black-backed layer R/T without calling the production forward."""
    thickness_values = np.atleast_1d(np.asarray(thicknesses, dtype=np.float64))
    reflectance = np.empty((thickness_values.size, 3), dtype=np.float64)
    transmittance = np.empty_like(reflectance)
    for row, thickness in enumerate(thickness_values):
        for channel in range(3):
            k_value = absorption[channel]
            s_value = scattering[channel]
            generator = np.array(
                [
                    [-(k_value + s_value), s_value],
                    [-s_value, k_value + s_value],
                ],
                dtype=np.float64,
            )
            transfer = expm(generator * thickness)
            reflectance[row, channel] = -transfer[1, 0] / transfer[1, 1]
            transmittance[row, channel] = 1.0 / transfer[1, 1]
    return reflectance, transmittance


_DIFFUSER_BASE_XYZ = np.array([0.198, 0.197, 0.247], dtype=np.float64)


def _joint_fit_parameter_vector(
    absorption: np.ndarray,
    scattering: np.ndarray,
    backing_scale: float,
    thickness_offset_mm: float = 0.0,
) -> np.ndarray:
    optical_parameters = np.column_stack([absorption, scattering])
    return np.concatenate(
        [
            np.log(optical_parameters).ravel(),
            [backing_scale, thickness_offset_mm],
        ]
    )


def _diffuser_backed_reference(
    absorption: np.ndarray,
    scattering: np.ndarray,
    thicknesses: np.ndarray,
    backing_base_xyz: np.ndarray,
    backing_scale: float,
    thickness_offset_mm: float = 0.0,
) -> tuple[np.ndarray, np.ndarray]:
    intrinsic_reflectance, transmittance = _matrix_layer_rt(
        absorption,
        scattering,
        thicknesses + thickness_offset_mm,
    )
    effective_backing = backing_base_xyz * backing_scale
    measured_reflectance = intrinsic_reflectance + (
        transmittance**2 * effective_backing
    ) / (1.0 - intrinsic_reflectance * effective_backing)
    return measured_reflectance, transmittance


def test_layer_zero_thickness_and_analytic_limits() -> None:
    absorption = np.array([0.0, 2.0, 0.0, 1.5])
    scattering = np.array([0.0, 0.0, 3.0, 2.0])
    reflectance, transmittance = km_layer_rt(absorption, scattering, 0.0)
    np.testing.assert_array_equal(reflectance, np.zeros(4))
    np.testing.assert_array_equal(transmittance, np.ones(4))

    pure_absorption_r, pure_absorption_t = km_layer_rt(2.0, 0.0, 0.4)
    assert float(pure_absorption_r) == pytest.approx(0.0)
    assert float(pure_absorption_t) == pytest.approx(np.exp(-0.8))

    pure_scattering_r, pure_scattering_t = km_layer_rt(0.0, 3.0, 0.4)
    assert float(pure_scattering_r) == pytest.approx(1.2 / 2.2)
    assert float(pure_scattering_t) == pytest.approx(1.0 / 2.2)
    assert float(pure_scattering_r + pure_scattering_t) == pytest.approx(1.0)


def test_layer_extreme_optical_depth_remains_finite() -> None:
    reflectance, transmittance = km_layer_rt(
        np.array([1.0e6, 0.0, 1.0e-12, 1.0e300]),
        np.array([1.0e6, 1.0e300, 1.0e6, 1.0e300]),
        np.array([1.0e6, 1.0e300, 1.0e6, 1.0e300]),
    )
    assert np.all(np.isfinite(reflectance))
    assert np.all(np.isfinite(transmittance))
    assert np.all((reflectance >= 0.0) & (reflectance <= 1.0))
    assert np.all((transmittance >= 0.0) & (transmittance <= 1.0))
    assert np.all(reflectance + transmittance <= 1.0 + 1.0e-12)
    np.testing.assert_array_equal(
        km_stack_reflectance(
            np.zeros((1, 3)),
            np.full((1, 3), 1.0e300),
            1.0e300,
            np.ones(3),
        ),
        np.ones(3),
    )


def test_layer_extreme_finite_coefficients_do_not_underflow_to_nan() -> None:
    maximum = np.finfo(np.float64).max
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        reflectance, transmittance = km_layer_rt(
            np.array([1.0e-300, maximum, 0.0]),
            np.array([1.0e300, maximum, maximum]),
            np.array([1.0, 1.0, maximum]),
        )

    assert np.all(np.isfinite(reflectance))
    assert np.all(np.isfinite(transmittance))
    assert transmittance[0] > 0.0
    assert np.all((reflectance >= 0.0) & (reflectance <= 1.0))
    assert np.all((transmittance >= 0.0) & (transmittance <= 1.0))


def test_high_pure_scattering_layer_on_white_backing_reaches_stable_limit() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        result = km_stack_reflectance(
            np.zeros((1, 3), dtype=np.float64),
            np.full((1, 3), 4.0e15, dtype=np.float64),
            1.0,
            np.ones(3, dtype=np.float64),
        )

    np.testing.assert_array_equal(result, np.ones(3, dtype=np.float64))


def test_two_identical_layers_equal_one_layer_of_summed_thickness() -> None:
    absorption = np.array([0.6, 1.2, 2.0])
    scattering = np.array([2.5, 0.7, 1.1])
    first_r, first_t = km_layer_rt(absorption, scattering, 0.18)
    second_r, second_t = km_layer_rt(absorption, scattering, 0.31)
    denominator = 1.0 - second_r * first_r
    combined_r = second_r + second_t**2 * first_r / denominator
    combined_t = second_t * first_t / denominator

    expected_r, expected_t = km_layer_rt(absorption, scattering, 0.49)
    np.testing.assert_allclose(combined_r, expected_r, rtol=1.0e-12, atol=1.0e-12)
    np.testing.assert_allclose(combined_t, expected_t, rtol=1.0e-12, atol=1.0e-12)


@pytest.mark.parametrize(
    "backing",
    [np.zeros(3, dtype=np.float64), np.ones(3, dtype=np.float64)],
)
def test_bottom_to_top_recurrence_matches_transfer_matrix(backing: np.ndarray) -> None:
    absorption = np.array(
        [[0.4, 1.7, 0.9], [2.1, 0.2, 1.3], [0.8, 2.4, 0.3]],
        dtype=np.float64,
    )
    scattering = np.array(
        [[2.2, 0.5, 1.4], [0.3, 2.8, 0.6], [1.7, 0.4, 2.5]],
        dtype=np.float64,
    )
    thicknesses = np.array([0.08, 0.12, 0.2], dtype=np.float64)

    actual = km_stack_reflectance(
        absorption,
        scattering,
        thicknesses,
        backing,
    )
    expected = _matrix_stack_reflectance(
        absorption,
        scattering,
        thicknesses,
        backing,
    )
    np.testing.assert_allclose(actual, expected, rtol=2.0e-13, atol=2.0e-13)


def test_layer_order_is_bottom_to_top_and_order_sensitive() -> None:
    bottom_to_top_k = np.array([[0.4, 2.0, 1.0], [3.0, 0.2, 1.5]])
    bottom_to_top_s = np.array([[3.0, 0.4, 2.0], [0.2, 3.0, 0.5]])
    white_backing = np.ones(3, dtype=np.float64)

    actual = km_stack_reflectance(
        bottom_to_top_k,
        bottom_to_top_s,
        0.08,
        white_backing,
    )
    expected = _matrix_stack_reflectance(
        bottom_to_top_k,
        bottom_to_top_s,
        np.array([0.08, 0.08]),
        white_backing,
    )
    reversed_result = km_stack_reflectance(
        bottom_to_top_k[::-1],
        bottom_to_top_s[::-1],
        0.08,
        white_backing,
    )

    np.testing.assert_allclose(actual, expected, rtol=1.0e-13, atol=1.0e-13)
    assert np.max(np.abs(actual - reversed_result)) > 0.01


def test_d65_10_effective_bridge_round_trips_display_and_matching_spaces() -> None:
    assert KM_XYZ_COLOR_BRIDGE_ID == "d65_10_to_d65_2_diagonal/v1"
    np.testing.assert_allclose(
        relative_xyz_to_effective_d65_10(np.ones(3)),
        D65_10_WHITE_XYZ,
    )
    np.testing.assert_allclose(
        km_relative_xyz_to_lab(np.ones(3)),
        np.array([100.0, 0.0, 0.0]),
        atol=1.0e-12,
    )
    np.testing.assert_allclose(
        km_relative_xyz_to_linear_srgb(np.ones(3)),
        np.ones(3),
        atol=1.0e-6,
    )

    linear_rgb = np.array([[0.12, 0.51, 0.83], [0.9, 0.2, 0.04]])
    relative_xyz = linear_srgb_to_km_relative_xyz(linear_rgb)
    np.testing.assert_allclose(
        km_relative_xyz_to_linear_srgb(relative_xyz),
        linear_rgb,
        atol=2.0e-7,
    )

    xyz_d65_2 = np.array([0.22, 0.31, 0.47])
    np.testing.assert_allclose(
        effective_d65_10_to_xyz_d65_2(
            xyz_d65_2_to_effective_d65_10(xyz_d65_2)
        ),
        xyz_d65_2,
        atol=1.0e-15,
    )


def test_joint_diffuser_fit_recovers_xyz_parameters_scale_and_row_order() -> None:
    thicknesses = np.array(
        [
            0.08,
            0.16,
            0.24,
            0.32,
            0.40,
            0.48,
            0.56,
            0.64,
            0.72,
            0.80,
            1.60,
            3.00,
        ]
    )
    expected = KMXYZParameters(
        K=np.array([1.2, 0.55, 2.0]),
        S=np.array([3.0, 1.4, 0.8]),
    )
    expected_scale = 1.4
    expected_thickness_offset = 0.12
    reflectance, transmittance = _diffuser_backed_reference(
        expected.K,
        expected.S,
        thicknesses,
        _DIFFUSER_BASE_XYZ,
        expected_scale,
        expected_thickness_offset,
    )

    result = fit_paired_km_xyz(
        thicknesses,
        transmittance,
        reflectance,
        _DIFFUSER_BASE_XYZ,
    )
    permutation = np.array([7, 1, 11, 0, 9, 3, 5, 2, 10, 4, 8, 6])
    permuted_result = fit_paired_km_xyz(
        thicknesses[permutation],
        transmittance[permutation],
        reflectance[permutation],
        _DIFFUSER_BASE_XYZ,
    )

    assert result.diagnostics.success is True
    assert result.diagnostics.warnings == ()
    assert result.diagnostics.objective_id == KM_XYZ_FIT_OBJECTIVE_ID
    assert KM_XYZ_FIT_OBJECTIVE_ID == (
        "km_xyz_paired_linear_tr_diffuser_offset_soft_l1/v3"
    )
    assert (
        KM_XYZ_MEASUREMENT_PROTOCOL_ID
        == "lumina_box_xyz_paired_diffuser_km/v2"
    )
    assert (
        KM_XYZ_MEASUREMENT_REFLECTION_BOUNDARY_ID
        == "instrument_diffuser_scaled/v1"
    )
    assert KM_XYZ_MEASUREMENT_THICKNESS_OFFSET_MAX_MM == pytest.approx(0.4)
    objective_config = result.diagnostics.objective_config
    assert objective_config["transmittance_residual"] == "linear"
    assert objective_config["reflectance_residual"] == "linear_diffuser_backed"
    assert objective_config["modality_weights"] == {
        "transmittance": 0.5,
        "reflectance": 0.5,
    }
    assert objective_config["f_scale"] == pytest.approx(1.0 / np.sqrt(72.0))
    backing_config = objective_config["measurement_backing"]
    assert backing_config["reflection_boundary_id"] == (
        KM_XYZ_MEASUREMENT_REFLECTION_BOUNDARY_ID
    )
    np.testing.assert_allclose(
        backing_config["base_relative_xyz"],
        _DIFFUSER_BASE_XYZ,
    )
    assert backing_config["scale_bounds"] == pytest.approx(
        [0.0, 1.0 / np.max(_DIFFUSER_BASE_XYZ)]
    )
    thickness_config = objective_config["measurement_thickness"]
    assert thickness_config == {
        "model": "shared_nonnegative_acquisition_offset",
        "effective_formula": "thickness_mm_plus_offset_mm",
        "offset_bounds_mm": [0.0, 0.4],
        "offset_near_bound_fraction": 0.01,
    }
    assert objective_config["solver"] == {
        "parameterization": (
            "log_k_log_s_direct_backing_scale_direct_thickness_offset"
        ),
        "optical_parameter_bounds": [1.0e-10, 1.0e4],
        "method": "trf",
        "x_scale": "jac",
        "max_nfev": 1500,
        "start_count": 96,
    }
    json.dumps(objective_config)
    np.testing.assert_allclose(result.parameters.K, expected.K, rtol=2.0e-5)
    np.testing.assert_allclose(result.parameters.S, expected.S, rtol=2.0e-5)
    np.testing.assert_allclose(permuted_result.parameters.K, expected.K, rtol=2.0e-5)
    np.testing.assert_allclose(permuted_result.parameters.S, expected.S, rtol=2.0e-5)
    assert result.measurement_backing_scale == pytest.approx(expected_scale, rel=2.0e-5)
    assert permuted_result.measurement_backing_scale == pytest.approx(
        expected_scale,
        rel=2.0e-5,
    )
    assert result.measurement_thickness_offset_mm == pytest.approx(
        expected_thickness_offset,
        rel=2.0e-5,
    )
    assert result.diagnostics.measurement_thickness_offset_mm == pytest.approx(
        expected_thickness_offset,
        rel=2.0e-5,
    )
    assert permuted_result.measurement_thickness_offset_mm == pytest.approx(
        expected_thickness_offset,
        rel=2.0e-5,
    )
    np.testing.assert_array_equal(
        result.measurement_backing_base_relative_xyz,
        _DIFFUSER_BASE_XYZ,
    )
    np.testing.assert_allclose(
        result.measurement_backing_effective_relative_xyz,
        _DIFFUSER_BASE_XYZ * result.measurement_backing_scale,
    )
    np.testing.assert_allclose(
        result.measurement_backing_effective_relative_xyz
        / result.measurement_backing_base_relative_xyz,
        np.full(3, result.measurement_backing_scale),
    )
    assert np.max(result.measurement_backing_effective_relative_xyz) <= 1.0
    runtime_reflectance = km_stack_reflectance(
        result.parameters.K[np.newaxis, :],
        result.parameters.S[np.newaxis, :],
        0.4,
        np.ones(3),
    )
    expected_runtime_reflectance = _matrix_stack_reflectance(
        expected.K[np.newaxis, :],
        expected.S[np.newaxis, :],
        np.array([0.4]),
        np.ones(3),
    )
    offset_applied_incorrectly = _matrix_stack_reflectance(
        expected.K[np.newaxis, :],
        expected.S[np.newaxis, :],
        np.array([0.4 + expected_thickness_offset]),
        np.ones(3),
    )
    np.testing.assert_allclose(
        runtime_reflectance,
        expected_runtime_reflectance,
        rtol=2.0e-5,
    )
    assert np.max(np.abs(runtime_reflectance - offset_applied_incorrectly)) > 0.01
    assert result.predicted_transmittance_xyz.shape == (12, 3)
    assert result.predicted_reflectance_xyz.shape == (12, 3)
    np.testing.assert_allclose(
        result.predicted_transmittance_xyz,
        transmittance,
        rtol=1.0e-7,
        atol=1.0e-10,
    )
    np.testing.assert_allclose(
        result.predicted_reflectance_xyz,
        reflectance,
        rtol=1.0e-7,
        atol=1.0e-10,
    )
    assert result.diagnostics.start_count == 96
    assert result.diagnostics.robust_objective < 1.0e-12
    assert result.diagnostics.jacobian_condition is not None
    for diagnostic in result.diagnostics.channels:
        assert diagnostic.transmittance_rmse < 1.0e-8
        assert diagnostic.reflectance_rmse < 1.0e-8
        assert not hasattr(diagnostic, "log_transmittance_rmse")


def test_diffuser_backed_reflection_formula_uses_runtime_base_and_shared_scale() -> None:
    thicknesses = np.array([0.08, 0.24, 0.72], dtype=np.float64)
    absorption = np.array([0.8, 1.3, 0.4])
    scattering = np.array([2.1, 0.7, 1.8])
    backing_base = np.array([0.12, 0.23, 0.31])
    backing_scale = 0.9
    thickness_offset = 0.06
    fit_parameters = _joint_fit_parameter_vector(
        absorption,
        scattering,
        backing_scale,
        thickness_offset,
    )
    expected_reflectance, expected_transmittance = _diffuser_backed_reference(
        absorption,
        scattering,
        thicknesses,
        backing_base,
        backing_scale,
        thickness_offset,
    )
    predicted_transmittance, predicted_reflectance = (
        km_xyz_module._predict_paired_measurements(
            fit_parameters,
            thicknesses,
            backing_base,
        )
    )

    np.testing.assert_allclose(
        predicted_transmittance,
        expected_transmittance,
        rtol=1.0e-13,
        atol=1.0e-14,
    )
    np.testing.assert_allclose(
        predicted_reflectance,
        expected_reflectance,
        rtol=1.0e-13,
        atol=1.0e-14,
    )


def test_linear_paired_objective_gives_each_modality_half_the_weight() -> None:
    thicknesses = np.array([0.2, 0.4], dtype=np.float64)
    fit_parameters = _joint_fit_parameter_vector(
        np.array([0.7, 0.9, 1.1]),
        np.array([2.0, 1.5, 0.8]),
        1.2,
    )
    predicted_transmittance, predicted_reflectance = (
        km_xyz_module._predict_paired_measurements(
            fit_parameters,
            thicknesses,
            _DIFFUSER_BASE_XYZ,
        )
    )
    observed_transmittance = predicted_transmittance - 0.02
    observed_reflectance = predicted_reflectance - 0.02

    residuals = km_xyz_module._fit_residuals(
        fit_parameters,
        thicknesses,
        observed_transmittance,
        observed_reflectance,
        _DIFFUSER_BASE_XYZ,
    )

    expected_unit_residual = np.full(6, 1.0 / np.sqrt(12.0))
    np.testing.assert_allclose(residuals[:6], expected_unit_residual, atol=1.0e-14)
    np.testing.assert_allclose(residuals[6:], expected_unit_residual, atol=1.0e-14)
    assert float(np.dot(residuals[:6], residuals[:6])) == pytest.approx(0.5)
    assert float(np.dot(residuals[6:], residuals[6:])) == pytest.approx(0.5)


def test_diffuser_backed_reflectance_may_decrease_with_thickness() -> None:
    thicknesses = np.array([0.02, 0.08, 0.2, 0.5], dtype=np.float64)
    absorption = np.array([5.0, 4.0, 3.0])
    scattering = np.array([0.1, 0.2, 0.3])
    reflectance, transmittance = _diffuser_backed_reference(
        absorption,
        scattering,
        thicknesses,
        _DIFFUSER_BASE_XYZ,
        2.5,
    )
    assert np.all(np.diff(reflectance, axis=0) < 0.0)

    result = fit_paired_km_xyz(
        thicknesses,
        transmittance,
        reflectance,
        _DIFFUSER_BASE_XYZ,
    )

    assert not any(
        "reflectance_non_monotonic" in warning
        for warning in result.diagnostics.warnings
    )
    np.testing.assert_allclose(result.parameters.K, absorption, rtol=1.0e-5)
    np.testing.assert_allclose(result.parameters.S, scattering, rtol=1.0e-5)
    assert result.measurement_thickness_offset_mm == pytest.approx(0.0, abs=1.0e-7)
    assert (
        "measurement_thickness_offset_near_bound"
        in result.diagnostics.warnings
    )


def test_multistart_selection_uses_soft_l1_result_cost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    starts = (
        _joint_fit_parameter_vector(
            np.full(3, 2.0),
            np.full(3, 3.0),
            0.5 * (1.0 / np.max(_DIFFUSER_BASE_XYZ)),
            0.1,
        ),
        _joint_fit_parameter_vector(
            np.full(3, 4.0),
            np.full(3, 5.0),
            0.995 * (1.0 / np.max(_DIFFUSER_BASE_XYZ)),
            0.399,
        ),
    )
    monkeypatch.setattr(
        km_xyz_module,
        "_deterministic_fit_starts",
        lambda _thicknesses, _transmittance, _scale_max: starts,
    )
    fake_results = iter(
        [
            SimpleNamespace(
                x=starts[0],
                fun=np.zeros(18),
                cost=0.8,
                success=True,
                message="first",
                nfev=3,
                jac=np.eye(18, 8),
            ),
            SimpleNamespace(
                x=starts[1],
                fun=np.full(18, 10.0),
                cost=0.2,
                success=True,
                message="second",
                nfev=5,
                jac=np.eye(18, 8),
            ),
        ]
    )
    calls: list[dict[str, object]] = []

    def fake_least_squares(*_args: object, **kwargs: object) -> object:
        calls.append(kwargs)
        return next(fake_results)

    monkeypatch.setattr(km_xyz_module, "least_squares", fake_least_squares)
    result = fit_paired_km_xyz(
        np.array([0.1, 0.2, 0.3]),
        np.full((3, 3), 0.5),
        np.full((3, 3), 0.2),
        _DIFFUSER_BASE_XYZ,
    )

    np.testing.assert_allclose(result.parameters.K, np.full(3, 4.0))
    np.testing.assert_allclose(result.parameters.S, np.full(3, 5.0))
    assert result.diagnostics.robust_objective == pytest.approx(0.2)
    assert result.diagnostics.start_count == 2
    assert "measurement_backing_scale_near_bound" in result.diagnostics.warnings
    assert (
        "measurement_thickness_offset_near_bound"
        in result.diagnostics.warnings
    )
    assert result.measurement_thickness_offset_mm == pytest.approx(0.399)
    assert len(calls) == 2
    assert calls[0]["loss"] == "soft_l1"
    assert calls[0]["f_scale"] == pytest.approx(1.0 / np.sqrt(18.0))
    assert calls[0]["method"] == "trf"
    assert calls[0]["x_scale"] == "jac"
    assert calls[0]["max_nfev"] == 1500
    lower_bounds, upper_bounds = calls[0]["bounds"]
    np.testing.assert_allclose(np.exp(lower_bounds[:6]), np.full(6, 1.0e-10))
    np.testing.assert_allclose(np.exp(upper_bounds[:6]), np.full(6, 1.0e4))
    assert lower_bounds[6] == 0.0
    assert upper_bounds[6] == pytest.approx(1.0 / np.max(_DIFFUSER_BASE_XYZ))
    assert lower_bounds[7] == 0.0
    assert upper_bounds[7] == pytest.approx(0.4)


def test_derived_blue_profile_regression_has_blue_runtime_target_and_low_rmse() -> None:
    """Derived blue fixture containing no raw instrument or customer data."""
    thicknesses = np.array(
        [0.08, 0.16, 0.24, 0.32, 0.40, 0.48, 0.56, 0.64, 0.72, 0.80, 1.60, 3.00]
    )
    reflectance, transmittance = _diffuser_backed_reference(
        np.array([4.0, 5.0, 0.4]),
        np.array([1.0, 1.0, 2.0]),
        thicknesses,
        _DIFFUSER_BASE_XYZ,
        1.8,
        0.054,
    )
    perturbation = np.linspace(-0.001, 0.001, thicknesses.size)[:, None]
    derived_transmittance = np.clip(
        transmittance * (1.0 + perturbation * np.array([0.4, -0.2, 0.3])),
        np.finfo(np.float64).tiny,
        1.0,
    )
    derived_reflectance = np.clip(
        reflectance + perturbation * np.array([0.5, -0.3, 0.4]),
        0.0,
        1.0,
    )

    result = fit_paired_km_xyz(
        thicknesses,
        derived_transmittance,
        derived_reflectance,
        _DIFFUSER_BASE_XYZ,
    )
    runtime_relative_xyz = km_stack_reflectance(
        result.parameters.K[np.newaxis, :],
        result.parameters.S[np.newaxis, :],
        0.4,
        np.ones(3),
    )
    runtime_linear_rgb = km_relative_xyz_to_linear_srgb(runtime_relative_xyz)

    assert runtime_linear_rgb[2] > runtime_linear_rgb[0]
    assert runtime_linear_rgb[2] > runtime_linear_rgb[1]
    assert max(
        diagnostic.transmittance_rmse
        for diagnostic in result.diagnostics.channels
    ) < 0.003
    assert max(
        diagnostic.reflectance_rmse
        for diagnostic in result.diagnostics.channels
    ) < 0.003
    assert result.measurement_thickness_offset_mm == pytest.approx(
        0.054,
        abs=0.003,
    )
    assert result.diagnostics.start_count == 96


def test_derived_red_profile_regression_has_red_runtime_target_and_low_rmse() -> None:
    """Derived red fixture containing no raw instrument or customer data."""
    thicknesses = np.array(
        [0.08, 0.16, 0.24, 0.32, 0.40, 0.48, 0.56, 0.64, 0.72, 0.80, 1.60, 3.00]
    )
    reflectance, transmittance = _diffuser_backed_reference(
        np.array([0.4, 3.0, 5.0]),
        np.array([2.0, 1.0, 1.0]),
        thicknesses,
        _DIFFUSER_BASE_XYZ,
        1.6,
        0.152,
    )
    perturbation = np.linspace(-0.001, 0.001, thicknesses.size)[:, None]
    derived_transmittance = np.clip(
        transmittance * (1.0 + perturbation * np.array([-0.3, 0.2, 0.4])),
        np.finfo(np.float64).tiny,
        1.0,
    )
    derived_reflectance = np.clip(
        reflectance + perturbation * np.array([-0.4, 0.3, 0.5]),
        0.0,
        1.0,
    )

    result = fit_paired_km_xyz(
        thicknesses,
        derived_transmittance,
        derived_reflectance,
        _DIFFUSER_BASE_XYZ,
    )
    runtime_relative_xyz = km_stack_reflectance(
        result.parameters.K[np.newaxis, :],
        result.parameters.S[np.newaxis, :],
        0.4,
        np.ones(3),
    )
    runtime_linear_rgb = km_relative_xyz_to_linear_srgb(runtime_relative_xyz)

    assert runtime_linear_rgb[0] > runtime_linear_rgb[1]
    assert runtime_linear_rgb[0] > runtime_linear_rgb[2]
    assert max(
        diagnostic.transmittance_rmse
        for diagnostic in result.diagnostics.channels
    ) < 0.003
    assert max(
        diagnostic.reflectance_rmse
        for diagnostic in result.diagnostics.channels
    ) < 0.003
    assert result.measurement_thickness_offset_mm == pytest.approx(
        0.152,
        abs=0.003,
    )
    assert result.diagnostics.start_count == 96


def test_zero_transmittance_is_rejected_but_zero_reflectance_is_allowed() -> None:
    thicknesses = np.array([0.1, 0.2, 0.4], dtype=np.float64)
    _, transmittance = _matrix_layer_rt(
        np.array([0.8, 1.0, 1.2]),
        np.array([0.5, 0.7, 0.9]),
        thicknesses,
    )
    zero_transmittance = transmittance.copy()
    zero_transmittance[0, 0] = 0.0
    with pytest.raises(CoreValidationError, match="> 0"):
        fit_paired_km_xyz(
            thicknesses,
            zero_transmittance,
            np.zeros_like(transmittance),
            _DIFFUSER_BASE_XYZ,
        )

    result = fit_paired_km_xyz(
        thicknesses,
        transmittance,
        np.zeros_like(transmittance),
        _DIFFUSER_BASE_XYZ,
    )
    assert result.predicted_reflectance_xyz.shape == (3, 3)
    assert np.all(np.isfinite(result.parameters.K))
    assert np.all(np.isfinite(result.parameters.S))


@pytest.mark.parametrize(
    ("thicknesses", "transmittance", "reflectance", "backing", "match"),
    [
        (
            [0.08, 0.16],
            np.ones((2, 3)),
            np.zeros((2, 3)),
            _DIFFUSER_BASE_XYZ,
            "at least three",
        ),
        (
            [0.08, 0.08, 0.24],
            np.ones((3, 3)),
            np.zeros((3, 3)),
            _DIFFUSER_BASE_XYZ,
            "must be unique",
        ),
        (
            [0.08, 0.16, 0.24],
            np.ones((3, 2)),
            np.zeros((3, 3)),
            _DIFFUSER_BASE_XYZ,
            r"transmittance_xyz must have shape \(N, 3\)",
        ),
        (
            [0.08, 0.16, 0.24],
            np.full((3, 3), 1.01),
            np.zeros((3, 3)),
            _DIFFUSER_BASE_XYZ,
            "must be <= 1.0",
        ),
        (
            [0.08, 0.16, 0.24],
            np.ones((3, 3)),
            np.zeros(3),
            _DIFFUSER_BASE_XYZ,
            r"reflectance_xyz must have shape \(N, 3\)",
        ),
        (
            [0.08, 0.16, 0.24],
            np.ones((3, 3)),
            np.full((3, 3), -0.01),
            _DIFFUSER_BASE_XYZ,
            r"in \[0, 1\]",
        ),
        (
            [0.08, np.inf, 0.24],
            np.ones((3, 3)),
            np.zeros((3, 3)),
            _DIFFUSER_BASE_XYZ,
            "finite",
        ),
        (
            [0.08, 0.16, 0.24],
            np.full((3, 3), np.nan),
            np.zeros((3, 3)),
            _DIFFUSER_BASE_XYZ,
            "finite",
        ),
        (
            [0.08, 0.16, 0.24],
            np.ones((3, 3)),
            np.full((3, 3), np.nan),
            _DIFFUSER_BASE_XYZ,
            "finite",
        ),
        (
            [0.08, 0.16, 0.24],
            np.ones((3, 3)),
            np.zeros((3, 3)),
            np.array([0.2, 0.3]),
            r"shape \(3,\)",
        ),
        (
            [0.08, 0.16, 0.24],
            np.ones((3, 3)),
            np.zeros((3, 3)),
            np.array([0.2, 0.0, 0.3]),
            "must be > 0",
        ),
        (
            [0.08, 0.16, 0.24],
            np.ones((3, 3)),
            np.zeros((3, 3)),
            np.array([0.2, 1.01, 0.3]),
            "<= 1.0",
        ),
        (
            [0.08, 0.16, 0.24],
            np.ones((3, 3)),
            np.zeros((3, 3)),
            np.array([0.2, np.nan, 0.3]),
            "finite",
        ),
        (
            [0.08, 0.16, 0.24],
            np.ones((3, 3)),
            np.zeros((3, 3)),
            np.full(3, np.nextafter(0.0, 1.0)),
            "finite scale bound",
        ),
    ],
)
def test_paired_fit_rejects_invalid_measurements(
    thicknesses: object,
    transmittance: np.ndarray,
    reflectance: np.ndarray,
    backing: np.ndarray,
    match: str,
) -> None:
    with pytest.raises(CoreValidationError, match=match):
        fit_paired_km_xyz(thicknesses, transmittance, reflectance, backing)


def test_old_single_reflection_fit_contract_is_not_exported() -> None:
    assert not hasattr(km_xyz_module, "fit_km_xyz")
    assert not hasattr(km_xyz_module, "KM_XYZ_REFLECTION_BOUNDARY")
    assert not hasattr(
        km_xyz_module,
        "KM_XYZ_MEASUREMENT_BACKING_BASE_RELATIVE_XYZ",
    )
    assert not hasattr(km_xyz_module, "_km_layer_log_transmittance")
    with pytest.raises(TypeError, match="measurement_backing_base_xyz"):
        fit_paired_km_xyz(
            np.array([0.1, 0.2, 0.3]),
            np.full((3, 3), 0.5),
            np.full((3, 3), 0.2),
        )
    with pytest.raises(TypeError, match="reflection_thickness_mm"):
        fit_paired_km_xyz(
            np.array([0.1, 0.2, 0.3]),
            np.full((3, 3), 0.5),
            np.full((3, 3), 0.2),
            _DIFFUSER_BASE_XYZ,
            reflection_thickness_mm=3.0,
        )


def test_stack_rejects_invalid_coefficients_and_backing() -> None:
    with pytest.raises(KMValidationError, match="non-negative"):
        km_stack_reflectance(
            np.array([[-1.0, 1.0, 1.0]]),
            np.ones((1, 3)),
            0.08,
            np.ones(3),
        )
    with pytest.raises(KMValidationError, match="<= 1.0"):
        km_stack_reflectance(
            np.ones((1, 3)),
            np.ones((1, 3)),
            0.08,
            np.array([1.1, 1.0, 1.0]),
        )
