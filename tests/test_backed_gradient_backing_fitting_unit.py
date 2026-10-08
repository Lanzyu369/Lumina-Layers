"""Independent backing fitting preserves the original observation calibration."""
from copy import deepcopy

import numpy as np
import pytest

from core import backed_gradient_backing_fitting as fitting
from core import backed_gradient_fitting_v2 as legacy
from core.backed_gradient_material import BackedGradientComponent, BackedGradientMaterialModel, reference_from_parameters
from core.backed_gradient_smooth import BackedGradientSmoothTransport
from core.backed_gradient_store import THICKNESSES_MM
from core.errors import CoreValidationError


@pytest.fixture
def calibration():
    initial = legacy._initial(("W", "K"), 0)
    operator = BackedGradientSmoothTransport({"W": initial[:5], "K": initial[5:]},
                                            {"W": [105., 103., 110.], "K": [0., 0., 0.]}, fitted_materials=("W", "K"))
    return reference_from_parameters(operator.to_parameters())


def snapshot(reference, role):
    white = BackedGradientComponent("color", (-4., -4., -4., -4., 1., 0., .7))
    black = BackedGradientComponent("color", (2., 2., 2., 2., -2., 0., .65))
    components = {"W": white, "K": black}
    component = components[role]
    opposite_role = "K" if role == "W" else "W"
    model = BackedGradientMaterialModel(reference, components)
    rows = [{"record_id": f"{role}-{thickness}", "material_symbol": role, "sample_role": "coated",
             "backing": opposite_role, "overlay_mm": thickness,
             "reflectance_percent_xyz": model.predict_backed(component, opposite_role, thickness).tolist(),
             "measurement": {"mode": "Auto", "original_frame": f"frame-{thickness}"}}
            for thickness in THICKNESSES_MM]
    rows.append({"record_id": "bare", "material_symbol": role, "sample_role": "bare_backing",
                 "backing": role, "overlay_mm": 0.,
                 "reflectance_percent_xyz": model.predict_backed(component, role, 3.).tolist(),
                 "measurement": {"mode": "Auto", "original_frame": "frame-bare"}})
    return component, {"dataset_id": f"backing-{role}", "dataset_revision": 8, "input_hash": "frozen",
                       "material_symbol": role, "backing_role": role, "reference": reference.to_dict(),
                       "opposite_component": components[opposite_role].to_dict(), "samples": rows,
                       "backing_material_id": f"my-{role}", "opposite_material_id": f"actual-{opposite_role}",
                       "selected_record_ids": [row["record_id"] for row in rows]}


@pytest.mark.parametrize("role", ["W", "K"])
def test_independent_backing_actual_optimizer_and_holdouts(calibration, role):
    _component, document = snapshot(calibration, role)
    before = deepcopy(document)
    result = fitting.fit_backed_gradient_backing_material(document, time_budget_seconds=90.)
    assert result["converged"] and result["cv"]["converged"]
    assert result["rmse_pp"] < .05 and result["cv"]["rmse_pp"] < .2
    assert result["component"]["kind"] == "color" and len(result["component"]["coefficients"]) == 7
    assert result["reference"] == calibration.to_dict()
    assert result["opposite_component"] == document["opposite_component"]
    assert result["backing_role"] == role and result["material_symbol"] == role
    assert result["capture_history"] == document["samples"]
    assert result["selected_record_ids"] == document["selected_record_ids"]
    assert result["backing_material_id"] == f"my-{role}"
    assert result["opposite_material_id"] == document["opposite_material_id"]
    assert result["sample_predictions"][-1]["overlay_mm"] == 0.
    assert len(result["cv"]["folds"]) == 7
    for fold in result["cv"]["folds"]:
        assert set(fold["training_record_ids"]).isdisjoint(fold["held_record_ids"])
        assert "bare" in fold["training_record_ids"] and len(fold["training_record_ids"]) == 7
    np.testing.assert_allclose(result["estimated_xyz"], np.array(document["samples"][-1]["reflectance_percent_xyz"]) / 100., atol=.001)
    assert document == before


def test_holdouts_use_unclassified_starts_and_never_change_the_opposite(calibration, monkeypatch):
    component, document = snapshot(calibration, "W")
    calls = []

    def fit(model, kind, symbol, rows, deadline):
        assert kind == "color" and symbol == "material"
        assert model.reference.to_dict() == document["reference"]
        assert model.backings["K"].to_dict() == document["opposite_component"]
        calls.append(deepcopy(rows))
        return component, True, []

    monkeypatch.setattr(fitting.material_fitting, "_fit_component", fit)
    result = fitting.fit_backed_gradient_backing_material(document)
    assert result["rmse_pp"] < 1e-10 and result["cv"]["rmse_pp"] < 1e-10
    assert len(calls) == 8 and len(calls[0]) == 8
    for thickness, training in zip(THICKNESSES_MM, calls[1:], strict=True):
        assert len(training) == 7 and all(row["overlay_mm"] != thickness for row in training)
        assert training[-1]["overlay_mm"] == 3.


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "wrong_backing", "nan", "negative", "bare_not_zero"])
def test_invalid_backing_samples_fail_before_fitting(calibration, mutation, monkeypatch):
    _component, document = snapshot(calibration, "W")
    if mutation == "missing":
        document["samples"].pop()
    elif mutation == "duplicate":
        document["samples"].append(deepcopy(document["samples"][0]))
    elif mutation == "wrong_backing":
        document["samples"][0]["backing"] = "W"
    elif mutation in ("nan", "negative"):
        document["samples"][0]["reflectance_percent_xyz"][0] = np.nan if mutation == "nan" else -1.
    else:
        document["samples"][-1]["overlay_mm"] = 3.
    monkeypatch.setattr(fitting.material_fitting, "_fit_component", lambda *args: pytest.fail("invalid readings entered optimizer"))
    with pytest.raises(CoreValidationError):
        fitting.fit_backed_gradient_backing_material(document)


def test_zero_and_over_100_readings_remain_unmodified(calibration, monkeypatch):
    component, document = snapshot(calibration, "W")
    document["samples"][0]["reflectance_percent_xyz"] = [0., 101., 110.]
    monkeypatch.setattr(fitting.material_fitting, "_fit_component", lambda *args: (component, True, []))
    result = fitting.fit_backed_gradient_backing_material(document)
    assert result["capture_history"][0]["reflectance_percent_xyz"] == [0., 101., 110.]
    assert result["sample_predictions"][0]["measured_percent_xyz"] == [0., 101., 110.]


@pytest.mark.parametrize("allowance", [0., -1., np.inf, np.nan])
def test_invalid_time_allowance_fails_before_input_loading(allowance):
    with pytest.raises(CoreValidationError, match="time allowance"):
        fitting.fit_backed_gradient_backing_material({}, time_budget_seconds=allowance)
