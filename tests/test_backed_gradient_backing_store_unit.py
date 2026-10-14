"""Independent backing records retain raw data and observation-scale identity."""
from copy import deepcopy
from uuid import uuid4

import pytest

from core import backed_gradient_fitting_v2 as legacy
from core.backed_gradient_backing_store import (
    create_black_white_pair, backing_material_snapshot, backing_selection, create_backing_material_dataset,
    get_backing_material, list_backing_materials, save_backing_material_result, save_backing_material_results,
)
from core.backed_gradient_material import reference_from_parameters
from core.backed_gradient_product_store import create_material_dataset, material_snapshot, save_backing_reference
from core.backed_gradient_smooth import BackedGradientSmoothTransport
from core.backed_gradient_store import BackedGradientStore, THICKNESSES_MM
from core.errors import CoreValidationError


@pytest.fixture
def store(tmp_path):
    return BackedGradientStore(tmp_path)


@pytest.fixture
def reference():
    initial = legacy._initial(("W", "K"), 0)
    model = BackedGradientSmoothTransport({"W": initial[:5], "K": initial[5:]},
                                         {"W": [97., 98., 96.], "K": [0., 0., 0.]}, fitted_materials=("W", "K"))
    return reference_from_parameters(model.to_parameters(), source={"dataset_id": str(uuid4()),
        "materials": {"W": "Original White", "K": "Original Black"}, "brand": "First", "material_type": "PETG"}).to_dict()


def _capture(store, dataset, *, bare=(100.5, 99., 98.)):
    role = dataset["workflow"]["material_symbol"]
    opposite = "K" if role == "W" else "W"
    for index, thickness in enumerate(THICKNESSES_MM):
        store.save_capture(dataset["dataset_id"], {
            "capture_id": str(uuid4()), "measurement_id": str(uuid4()),
            "material_symbol": role, "backing": opposite, "sample_role": "coated",
            "overlay_mm": thickness, "reflectance_percent_xyz": [index, index + 1, index + 2],
        })
    store.save_capture(dataset["dataset_id"], {
        "capture_id": str(uuid4()), "measurement_id": str(uuid4()),
        "material_symbol": role, "backing": role, "sample_role": "bare_backing",
        "overlay_mm": 0., "reflectance_percent_xyz": list(bare),
    })


def _projected(store, reference):
    from tests.support.black_white_materials import register_black_white
    return register_black_white(store, reference)


def test_registered_materials_keep_their_parameters_without_virtual_projections(store, reference):
    before = deepcopy(reference)
    pair = _projected(store, reference)
    assert pair["W"]["name"] == "Original White"
    assert pair["K"]["name"] == "Original Black"
    for role, name in (("W", "white"), ("K", "black")):
        item = pair[role]
        assert item["component"] == reference[name]
        assert item["reference"] == before
        assert get_backing_material(store, item["material_id"], version_id=item["version_id"]) == item
    with store._connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM gradient_backing_materials").fetchone()[0] == 2


def test_first_backing_can_be_saved_before_opposite_is_measured(store):
    dataset = create_black_white_pair(store, {"white": {"name": "White A", "brand": "A"}, "black": {"name": "Black B"}})
    profiles = {row["role"]: row for row in list_backing_materials(store)}
    assert len(profiles) == 2 and profiles["K"]["status"] == "draft"
    assert store.get(profiles["K"]["dataset_id"])["captures"] == []
    _capture(store, dataset)
    snapshot = backing_material_snapshot(store, dataset["dataset_id"])
    assert len(snapshot["samples"]) == 8 and len(snapshot["capture_history"]) == 8
    assert snapshot["bare_xyz"][0] == 100.5
    assert snapshot["samples"][0]["reflectance_percent_xyz"][0] == 0
    saved = save_backing_material_result(store, snapshot, None)
    assert saved["status"] == "measured"
    assert saved["snapshot"]["capture_export"]["dataset"]["captures"] == snapshot["capture_export"]["dataset"]["captures"]
    assert get_backing_material(store, profiles["K"]["material_id"])["status"] == "draft"
    assert save_backing_material_result(store, snapshot, None) == saved


def test_second_backing_resumes_registered_identity_and_can_read_first_full_measurements(store):
    first = create_black_white_pair(store, {"white": {"name": "White A"}, "black": {"name": "Black B"}})
    _capture(store, first)
    white = save_backing_material_result(store, backing_material_snapshot(store, first["dataset_id"]), None)
    second = create_backing_material_dataset(store, {"name": "Black B", "role": "K", "material_id": white["opposite_material_id"]})
    _capture(store, second, bare=(0., 0., 0.))
    black = backing_material_snapshot(store, second["dataset_id"])
    assert black["opposite"]["version_id"] == white["version_id"]
    assert len(black["opposite"]["snapshot"]["samples"]) == 8
    assert len(list_backing_materials(store)) == 2
    # The first capture began against a placeholder, so it can now resolve the measured counterpart.
    save_backing_material_result(store, black, None)
    assert backing_material_snapshot(store, first["dataset_id"])["opposite"]["status"] == "measured"


def test_recollection_keeps_old_version_available_and_updates_only_own_entity(store, reference):
    pair = _projected(store, reference)
    dataset = create_backing_material_dataset(store, {"name": "Independent White", "role": "W",
        "opposite_material_id": pair["K"]["material_id"]})
    _capture(store, dataset)
    snapshot = backing_material_snapshot(store, dataset["dataset_id"])
    first = save_backing_material_result(store, snapshot, {"component": reference["white"], "reference": reference})
    new_capture = create_backing_material_dataset(store, {"name": "Independent White", "role": "W", "material_id": first["material_id"]})
    current = get_backing_material(store, first["material_id"])
    assert current["status"] == "ready" and current["dataset_id"] == first["dataset_id"]
    assert current["active_dataset_id"] == new_capture["dataset_id"]
    _capture(store, new_capture, bare=(98., 99., 99.))
    second = save_backing_material_result(store, backing_material_snapshot(store, new_capture["dataset_id"]),
                                         {"component": reference["white"], "reference": reference})
    assert first["version_id"] != second["version_id"]
    assert get_backing_material(store, first["material_id"], version_id=first["version_id"]) == first
    assert get_backing_material(store, pair["K"]["material_id"])["component"] == reference["black"]


def test_selected_physical_backings_are_frozen_separately_from_observation_reference(store, reference):
    pair = _projected(store, reference)
    white_capture = create_backing_material_dataset(store, {"name": "White from another brand", "role": "W",
        "brand": "Another", "opposite_material_id": pair["K"]["material_id"]})
    _capture(store, white_capture)
    component = deepcopy(reference["white"])
    component["coefficients"][2] += .2
    white = save_backing_material_result(store, backing_material_snapshot(store, white_capture["dataset_id"]),
                                        {"component": component, "reference": reference})
    material = create_material_dataset(store, {"name": "Orange", "white_backing_id": white["material_id"],
                                               "black_backing_id": pair["K"]["material_id"]})
    for backing in ("W", "K"):
        for thickness in THICKNESSES_MM:
            store.save_capture(material["dataset_id"], {"capture_id": str(uuid4()), "measurement_id": str(uuid4()),
                "material_symbol": "material", "backing": backing, "sample_role": "coated", "overlay_mm": thickness,
                "reflectance_percent_xyz": [10., 20., 30.]})
    frozen = material_snapshot(store, material["dataset_id"])
    assert frozen["backing_components"]["W"] == component
    assert frozen["reference"]["white"] == reference["white"]
    assert frozen["backing_material_versions"]["W"] == white["version_id"]
    assert frozen["reference_id"] == reference["reference_id"]


def test_opposite_and_selection_require_correct_roles_and_complete_models(store, reference):
    pair = _projected(store, reference)
    with pytest.raises(CoreValidationError, match="opposite role"):
        create_backing_material_dataset(store, {"name": "White", "role": "W", "opposite_material_id": pair["W"]["material_id"]})
    dataset = create_black_white_pair(store, {"white": {"name": "White"}, "black": {"name": "Unmeasured black"}})
    draft = get_backing_material(store, dataset["workflow"]["backing_material_id"])
    with pytest.raises(CoreValidationError, match="completed"):
        backing_selection(store, draft["material_id"], pair["K"]["material_id"])
    with pytest.raises(CoreValidationError, match="missing backing readings"):
        backing_material_snapshot(store, dataset["dataset_id"])


def test_different_observation_scales_cannot_be_silently_mixed(store, reference):
    original = _projected(store, reference)
    other = deepcopy(reference)
    other["reference_id"] = "independent-observation-calibration"
    other["source"]["dataset_id"] = str(uuid4())
    other["anchors"]["W"][0] += 1.
    other["source"]["materials"] = {"W": "Other White", "K": "Other Black"}
    white = _projected(store, other)["W"]
    with pytest.raises(CoreValidationError, match="different measurement calibrations"):
        backing_selection(store, white["material_id"], original["K"]["material_id"])


def test_new_observation_reference_does_not_create_duplicate_backing_entities(store, reference):
    reference["source"]["independent_backings"] = True
    save_backing_reference(store, reference, "New independent calibration")
    assert list_backing_materials(store) == []


def test_measured_opposite_can_become_ready_without_recreating_waiting_capture(store, reference):
    first = create_black_white_pair(store, {"white": {"name": "White A"}, "black": {"name": "Black B"}})
    _capture(store, first)
    white_snapshot = backing_material_snapshot(store, first["dataset_id"])
    white = save_backing_material_result(store, white_snapshot, None)
    second = create_backing_material_dataset(store, {"name": "Black B", "role": "K", "material_id": white["opposite_material_id"]})
    assert "opposite_version_id" not in second["workflow"]
    _capture(store, second, bare=(0., 0., 0.))
    ready = save_backing_material_result(store, white_snapshot, {"component": reference["white"], "reference": reference})
    resumed = backing_material_snapshot(store, second["dataset_id"])
    assert resumed["opposite"]["version_id"] == ready["version_id"]
    assert resumed["reference"] == reference and resumed["opposite_component"] == reference["white"]


def test_bootstrap_publication_rolls_back_both_materials_if_second_write_fails(store, reference, monkeypatch):
    from core import backed_gradient_product_store as product_store

    white_capture = create_black_white_pair(store, {"white": {"name": "White A"}, "black": {"name": "Black B"}})
    _capture(store, white_capture)
    white_snapshot = backing_material_snapshot(store, white_capture["dataset_id"])
    white = save_backing_material_result(store, white_snapshot, None)
    black_capture = create_backing_material_dataset(store, {"name": "Black B", "role": "K", "material_id": white["opposite_material_id"]})
    _capture(store, black_capture, bare=(0., 0., 0.))
    black_snapshot = backing_material_snapshot(store, black_capture["dataset_id"])
    black = save_backing_material_result(store, black_snapshot, None)
    entries = [(white_snapshot, {"component": reference["white"], "reference": reference}),
               (black_snapshot, {"component": reference["black"], "reference": reference})]
    original = product_store._save_backing_reference
    calls = 0

    def fail_second(connection, payload, name):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise CoreValidationError("Injected second publication failure")
        return original(connection, payload, name)

    monkeypatch.setattr(product_store, "_save_backing_reference", fail_second)
    with pytest.raises(CoreValidationError, match="second publication"):
        save_backing_material_results(store, entries)
    assert get_backing_material(store, white["material_id"]) == white
    assert get_backing_material(store, black["material_id"]) == black
    with store._connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM gradient_backing_material_versions").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM gradient_references").fetchone()[0] == 0
    monkeypatch.setattr(product_store, "_save_backing_reference", original)
    saved = save_backing_material_results(store, entries)
    assert [item["status"] for item in saved] == ["ready", "ready"]
    assert save_backing_material_results(store, entries) == saved
