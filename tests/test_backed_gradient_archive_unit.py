"""Self-contained archives preserve measurements and material versions."""
from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest

from core.backed_gradient_archive import load_backed_gradient_archive, save_backed_gradient_material_archive
from core.backed_gradient_material import reference_from_parameters, component_from_parameters, BackedGradientMaterialModel, BackedGradientComponent, BackedGradientReference
from core.backed_gradient_smooth import BackedGradientSmoothTransport, SPECTRAL_SMOOTH_MODEL_ID
from core.errors import CoreValidationError, MaterialArchiveConflictError
from core import backed_gradient_fitting_v2 as legacy


def _inputs():
    symbols = ("R", "W", "K")
    initial = legacy._initial(symbols, 0)
    original = BackedGradientSmoothTransport({symbol: initial[part] for symbol, part in legacy._slices(symbols).items()},
                                            {"W": [97., 98., 96.], "K": [0., 0., 0.]}, fitted_materials=symbols)
    parameters = original.to_parameters()
    reference = reference_from_parameters(parameters, source={"raw_frames": [{"sample": "retained"}]})
    fit = {"dataset_id": "saved-input", "dataset_revision": 15, "input_hash": "frozen-input", "material_symbol": "R",
           "optical_model_id": SPECTRAL_SMOOTH_MODEL_ID, "component": component_from_parameters(parameters, "R").to_dict(),
           "reference": reference.to_dict(), "rmse_pp": 1., "status": "complete", "converged": True}
    measurement = {"dataset_id": "saved-input", "dataset_revision": 15, "input_hash": "frozen-input",
                   "samples": [{"reflectance_percent_xyz": [0., 101., 42.]}],
                   "capture_history": [{"measurement": {"original_frame": "unaltered"}}]}
    return fit, measurement


def test_portable_archive_roundtrip_preserves_raw_history_and_predictions(tmp_path):
    fit, measurement = _inputs()
    result = save_backed_gradient_material_archive(material_name="Red", brand="Example", measurement_payload=measurement,
                                                    fit_payload=fit, materials_dir=str(tmp_path))
    main, captured, restored = load_backed_gradient_archive(Path(result.archive_path).parent)
    assert captured == measurement
    assert main["capture_dataset_id"] == "saved-input" and main["material_symbol"] == "R"
    assert restored["reference"] == fit["reference"]
    component = BackedGradientComponent.from_dict(restored["component"])
    model = BackedGradientMaterialModel(BackedGradientReference.from_dict(restored["reference"]))
    expected = model.predict_backed(component, "W", 3.) / 100.
    np.testing.assert_allclose(restored["estimated_xyz"], expected)


def test_overwrite_keeps_previous_archive_and_changes_revision(tmp_path):
    fit, measurement = _inputs()
    options = dict(material_name="Red", measurement_payload=measurement, fit_payload=fit, materials_dir=str(tmp_path))
    first = save_backed_gradient_material_archive(**options)
    directory = Path(first.archive_path).parent
    old, _, _ = load_backed_gradient_archive(directory)
    with pytest.raises(MaterialArchiveConflictError):
        save_backed_gradient_material_archive(**options)
    save_backed_gradient_material_archive(**options, overwrite=True)
    current, _, _ = load_backed_gradient_archive(directory)
    assert current["archive_consistency"]["archive_id"] == old["archive_consistency"]["archive_id"]
    assert current["archive_consistency"]["revision_id"] != old["archive_consistency"]["revision_id"]
    historical = directory / ".history" / old["archive_consistency"]["revision_id"]
    assert load_backed_gradient_archive(historical, old)[1] == measurement
    assert list(directory.rglob("material.json")) == [directory / "material.json"]


def test_archive_rejects_mixed_input_revision_and_detects_changed_sidecar(tmp_path):
    fit, measurement = _inputs()
    altered = deepcopy(measurement)
    altered["dataset_revision"] += 1
    with pytest.raises(CoreValidationError, match="different set"):
        save_backed_gradient_material_archive(material_name="Red", measurement_payload=altered,
                                              fit_payload=fit, materials_dir=str(tmp_path))
    saved = save_backed_gradient_material_archive(material_name="Red", measurement_payload=measurement,
                                                   fit_payload=fit, materials_dir=str(tmp_path))
    Path(saved.measurements_path).write_text("{}", encoding="utf-8")
    with pytest.raises(CoreValidationError, match="does not match"):
        load_backed_gradient_archive(Path(saved.archive_path).parent)


def test_single_archive_does_not_embed_derived_group_job_payloads(tmp_path):
    fit, measurement = _inputs()
    expected = deepcopy(measurement)
    for payload in (fit, measurement):
        payload.update(group={"materials": [deepcopy(expected)]},
                       group_material_snapshots=[deepcopy(expected)], group_fits={"another": {"raw": "group data"}})
    saved = save_backed_gradient_material_archive(material_name="Red", measurement_payload=measurement,
                                                   fit_payload=fit, materials_dir=str(tmp_path))
    _, restored_input, restored_fit = load_backed_gradient_archive(Path(saved.archive_path).parent)
    assert restored_input == expected
    assert not {"group", "group_material_snapshots", "group_fits"}.intersection(restored_fit)
    assert restored_fit["reference"] == fit["reference"]
