"""Single-material inputs, reference reuse, and paired holdout isolation."""
from copy import deepcopy

import numpy as np
import pytest

from core import backed_gradient_fitting_v2 as legacy
from core import backed_gradient_material_fitting as fitting
from core.backed_gradient_material import BackedGradientComponent, BackedGradientMaterialModel, reference_from_parameters
from core.backed_gradient_smooth import BackedGradientSmoothTransport
from core.backed_gradient_store import THICKNESSES_MM
from core.errors import CoreValidationError


@pytest.fixture
def calibration():
    initial = legacy._initial(("W", "K"), 0)
    model = BackedGradientSmoothTransport({"W": initial[:5], "K": initial[5:]},
                                         {"W": [97., 98., 96.], "K": [0., 0., 0.]}, fitted_materials=("W", "K"))
    return reference_from_parameters(model.to_parameters())


def snapshot(calibration, component):
    model = BackedGradientMaterialModel(calibration)
    return {"dataset_id": "sample", "dataset_revision": 14, "input_hash": "frozen", "material_symbol": "R",
            "material_kind": component.kind, "samples": [
                {"record_id": f"{backing}:{thickness}", "backing": backing, "overlay_mm": thickness,
                 "reflectance_percent_xyz": model.predict_backed(component, backing, thickness).tolist()}
                for backing in ("W", "K") for thickness in THICKNESSES_MM]}


def test_single_material_fit_and_all_seven_paired_holdouts(calibration, monkeypatch):
    component = BackedGradientComponent("color", (4., 3., 2., 1., 0., 0., .7))
    document = snapshot(calibration, component)
    before = deepcopy(document)
    calls = []

    def fit(model, kind, symbol, rows, deadline):
        calls.append((kind, deepcopy(rows), model.reference.to_dict()))
        return component, True, [{"converged": True}]

    monkeypatch.setattr(fitting, "_fit_component", fit)
    result = fitting.fit_backed_gradient_material(document, calibration)
    assert result["converged"] and result["rmse_pp"] < 1e-10
    assert result["cv"]["converged"]
    assert result["input_hash"] == "frozen" and document == before
    assert len(calls) == 8 and len(calls[0][1]) == 14
    for index, thickness in enumerate(THICKNESSES_MM, 1):
        rows = calls[index][1]
        assert len(rows) == 12 and all(row["overlay_mm"] != thickness for row in rows)
        assert calls[index][2] == calibration.to_dict()
        fold = result["cv"]["folds"][index - 1]
        assert set(fold["training_record_ids"]).isdisjoint(fold["held_record_ids"])


def test_actual_single_material_optimizer_recovers_synthetic_readings(calibration):
    component = BackedGradientComponent("color", (4., 3., 2., 1., 0., 0., .7))
    document = snapshot(calibration, component)
    import time
    fitted, converged, attempts = fitting._fit_component(
        BackedGradientMaterialModel(calibration), "color", "R", document["samples"], time.monotonic() + 45.)
    predicted = fitting._predict(BackedGradientMaterialModel(calibration), fitted, document["samples"])
    assert converged and len(attempts) == 2
    assert fitting._summary(document["samples"], predicted)["rmse_pp"] < .02


@pytest.mark.parametrize("coefficients", [
    (3., 2., .5, -1., 0., .5, .7),  # Orange
    (-1., 3., 2., -1., 0., .5, .7),  # Purple
    (3., -1., 1., 3., 0., .5, .7),  # Green
    (-.5, -.5, -.5, -.5, 0., 0., .7),  # Gray
    (-4., -4., -4., -4., 1., 0., .7),  # Another white
    (3., 3., 3., 3., -3., 0., .7),  # Another black
])
def test_unclassified_material_fits_saturated_and_neutral_colors(calibration, coefficients):
    import time

    component = BackedGradientComponent("color", coefficients)
    document = snapshot(calibration, component)
    document["material_symbol"] = "material"
    model = BackedGradientMaterialModel(calibration)
    fitted, converged, attempts = fitting._fit_component(
        model, "color", "material", document["samples"], time.monotonic() + 45.)
    predicted = fitting._predict(model, fitted, document["samples"])
    assert converged and all(attempt["converged"] for attempt in attempts)
    assert fitted.kind == "color" and len(fitted.coefficients) == 7
    assert fitting._summary(document["samples"], predicted)["rmse_pp"] < .05


def test_unclassified_material_holdouts_never_use_held_readings(calibration, monkeypatch):
    component = BackedGradientComponent("color", (-.5, -.5, -.5, -.5, 0., 0., .7))
    document = snapshot(calibration, component)
    document["material_symbol"] = "material"
    calls = []

    def fit(model, kind, symbol, rows, deadline):
        assert kind == "color" and symbol == "material"
        calls.append(deepcopy(rows))
        return component, True, [{"converged": True}]

    monkeypatch.setattr(fitting, "_fit_component", fit)
    result = fitting.fit_backed_gradient_material(document, calibration)
    assert result["material_symbol"] == "material"
    assert len(calls) == 8
    for thickness, training in zip(THICKNESSES_MM, calls[1:], strict=True):
        assert len(training) == 12
        assert all(row["overlay_mm"] != thickness for row in training)


def test_other_white_does_not_replace_calibrated_backings(calibration, monkeypatch):
    white = BackedGradientComponent("white", (-2., 1., 1., 1., .5))
    document = snapshot(calibration, white)
    before = calibration.to_dict()
    monkeypatch.setattr(fitting, "_fit_component", lambda *args: (white, True, []))
    result = fitting.fit_backed_gradient_material(document, calibration)
    assert result["reference"] == before
    assert result["component"] != result["reference"]["white"]
    assert result["rmse_pp"] < 1e-10


def test_single_material_fit_uses_actual_backings_and_preserves_their_identity(calibration, monkeypatch):
    component = BackedGradientComponent("color", (4., 3., 2., 1., 0., 0., .7))
    backings = {"W": BackedGradientComponent("color", (-3., -3., -3., -3., .8, 0., .6)),
                "K": BackedGradientComponent("color", (2., 2., 2., 2., -2., 0., .6))}
    document = snapshot(calibration, component)
    document["backing_components"] = {key: value.to_dict() for key, value in backings.items()}
    document["backing_material_ids"] = {"W": "new-white", "K": "different-black"}
    actual = BackedGradientMaterialModel(calibration, backings)
    for row in document["samples"]:
        row["reflectance_percent_xyz"] = actual.predict_backed(component, row["backing"], row["overlay_mm"]).tolist()
    monkeypatch.setattr(fitting, "_fit_component", lambda *args: (component, True, []))
    result = fitting.fit_backed_gradient_material(document, calibration)
    assert result["rmse_pp"] < 1e-10 and result["cv"]["rmse_pp"] < 1e-10
    assert result["reference"] == calibration.to_dict()
    assert result["backing_components"] == document["backing_components"]
    assert result["backing_material_ids"] == document["backing_material_ids"]


def test_incomplete_pairs_fail_before_optimizer(calibration):
    component = BackedGradientComponent("color", (4., 3., 2., 1., 0., 0., .7))
    document = snapshot(calibration, component)
    document["samples"].pop()
    with pytest.raises(CoreValidationError, match="seven"):
        fitting.fit_backed_gradient_material(document, calibration)


def test_reference_first_build_needs_only_opposite_backings_and_bare_anchors(calibration, monkeypatch):
    model = BackedGradientMaterialModel(calibration)
    document = {
        "dataset_id": "backings", "dataset_revision": 16, "input_hash": "reference-input",
        "materials": {"W": "White backing A", "K": "Black backing B", "R": "Unrelated material"},
        "reference_anchors": {key: list(value) for key, value in calibration.anchors.items()},
        "conditions": {"total_mm": 3., "observation_face": "bed_contact", "diffuser_removed": True},
        "samples": [{"record_id": f"{symbol}:{thickness}", "material_symbol": symbol, "backing": backing,
                     "overlay_mm": thickness,
                     "reflectance_percent_xyz": model.predict_backed(component, backing, thickness).tolist()}
                    for symbol, backing, component in (("W", "K", calibration.white), ("K", "W", calibration.black))
                    for thickness in THICKNESSES_MM],
    }
    operator = BackedGradientSmoothTransport(
        {"W": calibration.white.coefficients, "K": calibration.black.coefficients}, calibration.anchors,
        fitted_materials=("W", "K"),
    )
    calls = []

    def fit(prepared, rows, deadline):
        calls.append(rows)
        return operator, [{"success": True, "rmse_pp": 0.}]

    monkeypatch.setattr(fitting, "_reference_initialization", fit)
    result = fitting.fit_backed_gradient_reference(document)
    assert result["converged"] and result["rmse_pp"] < 1e-10
    assert len(calls[0]) == 14
    assert all(row["material_symbol"] != row["backing"] for row in calls[0])
    assert result["reference"]["source"]["samples"] == document["samples"]
    assert result["reference"]["source"]["materials"] == {"W": "White backing A", "K": "Black backing B"}
    assert "materials" not in fitting._source(document)
    assert result["reference"]["source"]["calibration_stage"] == "bootstrap"
    assert result["reference"]["source"]["established"] is False
    assert result["cv"]["converged"]
    replay = fitting.fit_backed_gradient_reference(document)
    updated = fitting.fit_backed_gradient_reference({**document, "input_hash": "new-reference-input"})
    assert replay["reference"]["reference_id"] == result["reference"]["reference_id"]
    assert updated["reference"]["reference_id"] != result["reference"]["reference_id"]
    assert updated["reference"]["white"] == result["reference"]["white"]
    incomplete = deepcopy(document)
    incomplete["samples"].pop()
    with pytest.raises(CoreValidationError, match="seven"):
        fitting.fit_backed_gradient_reference(incomplete)


@pytest.mark.parametrize("failed_fold", [None, 2])
def test_incremental_group_keeps_slot_identity_and_refits_all_pairs(calibration, monkeypatch, failed_fold):
    source = calibration.to_dict()
    source["source"] = {"backing_id": "original-backings", "established": False}
    model = BackedGradientMaterialModel(calibration)
    backing_rows = [
        {"record_id": f"base-{symbol}-{thickness}", "material_symbol": symbol, "backing": backing,
         "overlay_mm": thickness, "reflectance_percent_xyz": model.predict_backed(component, backing, thickness).tolist()}
        for symbol, backing, component in (("W", "K", calibration.white), ("K", "W", calibration.black))
        for thickness in THICKNESSES_MM
    ]
    components = [BackedGradientComponent("color", (4., 3., 2., 1., 0., 0., .7)),
                  BackedGradientComponent("color", (3., 2., 1., 0., 1., 1., .6)),
                  BackedGradientComponent("white", (-2., 1., 1., 1., .5)),
                  BackedGradientComponent("black", (2., -2., 1., .5))]
    materials = []
    for index, component in enumerate(components):
        document = snapshot(calibration, component)
        document["dataset_id"] = f"material-{index}"
        document["material_symbol"] = ("R", "R", "W", "K")[index]
        document["reference"] = source
        for row in document["samples"]:
            row["record_id"] = f"{index}-{row['record_id']}"
        materials.append(document)
    vector = np.r_[calibration.white.coefficients, calibration.black.coefficients,
                   *(component.coefficients for component in components)]
    problem = fitting._GroupProblem({"reference": source, "backing_samples": backing_rows, "materials": materials})
    indices = problem.training_indices
    pattern = problem.jacobian_pattern(indices)
    groups = fitting.group_columns(pattern)
    dense = fitting.approx_derivative(lambda values: problem.residual(values, indices), vector,
                                     method="2-point", bounds=problem.bounds)
    compressed = fitting.approx_derivative(lambda values: problem.residual(values, indices), vector,
                                          method="2-point", bounds=problem.bounds, sparsity=(pattern, groups)).toarray()
    np.testing.assert_allclose(compressed, dense, atol=1e-10, rtol=1e-10)
    assert len(set(groups)) < len(vector)
    calls = []

    def fake_fit(problem, indices, deadline):
        calls.append([problem.rows[index] for index in indices])
        return vector, [{"converged": len(calls) - 2 != failed_fold, "objective": 0.},
                        {"converged": False, "objective": 1.}]

    monkeypatch.setattr(fitting._GroupProblem, "fit", fake_fit)
    result = fitting.fit_backed_gradient_material_group({"reference": source, "backing_samples": backing_rows,
                                                        "materials": materials, "input_hash": "all-inputs"})
    assert len(calls) == 8 and result["rmse_pp"] < 1e-10
    assert result["converged"]
    assert result["cv"]["converged"] is (failed_fold is None)
    assert result["cv"]["reference_fixed"] is False
    assert result["cv"]["rmse_pp"] < 1e-10
    assert len(result["material_fits"]) == 4
    for index, thickness in enumerate(THICKNESSES_MM, 1):
        assert all(row["overlay_mm"] != thickness for row in calls[index])
    reference = result["reference"]
    assert reference["source"]["backing_id"] == "original-backings"
    assert reference["source"]["group_input_hash"] == "all-inputs"
    assert reference["source"]["established"] is False
    assert all("reference" not in entry for entry in reference["source"]["material_inputs"])
    assert result["material_fits"]["material-0:R"]["component"] != result["material_fits"]["material-1:R"]["component"]
    assert result["material_fits"]["material-2:W"]["component"] != reference["white"]
    assert result["material_fits"]["material-3:K"]["component"] != reference["black"]
    for fit in result["material_fits"].values():
        assert fit["reference"] == reference
        assert fit["cv"]["rmse_pp"] < 1e-10
        assert fit["cv"]["converged"] is (failed_fold is None)
        for index, fold in enumerate(fit["cv"]["folds"]):
            assert fold["converged"] is (index != failed_fold)
            assert set(fold["training_record_ids"]).isdisjoint(fold["held_record_ids"])
    replay = fitting.fit_backed_gradient_material_group({"reference": source, "backing_samples": backing_rows,
                                                        "materials": materials, "input_hash": "all-inputs"})
    updated = fitting.fit_backed_gradient_material_group({"reference": source, "backing_samples": backing_rows,
                                                         "materials": materials, "input_hash": "new-records"})
    assert replay["reference"]["reference_id"] == reference["reference_id"]
    assert updated["reference"]["reference_id"] != reference["reference_id"]
    assert updated["reference"]["white"] == reference["white"]
    assert updated["reference"]["black"] == reference["black"]


def test_original_white_black_archives_reuse_backing_parameters_without_duplicate_fit_weight(calibration):
    red = BackedGradientComponent("color", (4., 3., 2., 1., 0., 0., .7))
    materials = []
    for symbol, component in (("R", red), ("W", calibration.white), ("K", calibration.black)):
        document = snapshot(calibration, component)
        document["dataset_id"] = "original-complete-dataset"
        document["material_symbol"] = symbol
        document["backing_role"] = symbol if symbol in ("W", "K") else None
        for row in document["samples"]:
            row["material_symbol"] = symbol
        materials.append(document)
    backing = [row for entry in materials[1:] for row in entry["samples"] if row["material_symbol"] != row["backing"]]
    problem = fitting._GroupProblem({"reference": calibration.to_dict(), "backing_samples": backing, "materials": materials})
    vector = np.r_[calibration.white.coefficients, calibration.black.coefficients, red.coefficients]
    assert len(problem.bounds[0]) == len(vector) == 16
    assert len(problem.training_indices) == 28
    assert len(problem.rows) == 56
    model, components = problem.operator(vector)
    assert components[1] == model.reference.white
    assert components[2] == model.reference.black
    assert np.max(np.abs(problem.residual(vector, problem.training_indices))) < 1e-10


def test_same_color_materials_are_distinct_group_evidence_without_color_labels(calibration, monkeypatch):
    model = BackedGradientMaterialModel(calibration)
    backings = [
        {"record_id": f"base-{symbol}-{thickness}", "material_symbol": symbol, "backing": backing,
         "overlay_mm": thickness, "reflectance_percent_xyz": model.predict_backed(component, backing, thickness).tolist()}
        for symbol, backing, component in (("W", "K", calibration.white), ("K", "W", calibration.black))
        for thickness in THICKNESSES_MM
    ]
    components = [BackedGradientComponent("color", (value, value, value, value, 0., 0., .7))
                  for value in (-1., -.5, 0.)]
    documents = []
    for index, component in enumerate(components):
        document = snapshot(calibration, component)
        document.update(dataset_id=f"gray-{index}", material_symbol="material")
        for row in document["samples"]:
            row["record_id"] = f"{index}-{row['record_id']}"
        documents.append(document)
    vector = np.r_[calibration.white.coefficients, calibration.black.coefficients,
                   *(component.coefficients for component in components)]
    calls = []

    def fit(problem, indices, deadline):
        calls.append([problem.rows[index] for index in indices])
        assert len(problem.bounds[0]) == 30
        return vector, [{"converged": True, "objective": 0.}]

    monkeypatch.setattr(fitting._GroupProblem, "fit", fit)
    result = fitting.fit_backed_gradient_material_group({"reference": calibration.to_dict(),
                                                        "backing_samples": backings, "materials": documents})
    assert result["reference"]["source"]["established"] is True
    fits = result["material_fits"]
    assert set(fits) == {f"gray-{index}:material" for index in range(3)}
    assert len({tuple(fit["component"]["coefficients"]) for fit in fits.values()}) == 3
    assert result["rmse_pp"] < 1e-10 and result["cv"]["rmse_pp"] < 1e-10
    assert len(calls) == 8
    for thickness, training in zip(THICKNESSES_MM, calls[1:], strict=True):
        assert all(row["overlay_mm"] != thickness for row in training)
        assert len(training) == 48


@pytest.mark.parametrize("allowance", [0., -1., np.inf, np.nan])
def test_group_fit_rejects_invalid_time_allowance_before_reading_inputs(allowance):
    with pytest.raises(CoreValidationError, match="time allowance"):
        fitting.fit_backed_gradient_material_group({}, time_budget_seconds=allowance)
