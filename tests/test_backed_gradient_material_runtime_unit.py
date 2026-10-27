"""Production material adapters retain the adopted optical predictions."""
from dataclasses import replace
from itertools import product
import json
from pathlib import Path
import zipfile

import numpy as np
import pytest

from core.backed_gradient_material import (
    BACKED_GRADIENT_PROTOCOL_ID, component_from_parameters, reference_from_parameters,
)
from core.backed_gradient_smooth import BackedGradientSmoothTransport, SPECTRAL_SMOOTH_MODEL_ID
from core.km_xyz import KM_XYZ_COLOR_BRIDGE_ID, km_relative_xyz_to_linear_srgb
from core.material_cache import describe_palette
from core.material_color_solver import (
    MaterialParams, forward_model, predict_material_recipe_srgb, predict_material_recipes_colorimetry,
)
from core.material_optical_runtime import (
    MaterialMeasurementProtocolMismatchError, bind_material_backing, bind_material_print_backing,
    validate_material_optical_contract,
)


@pytest.fixture
def backed_palette():
    coefficients = {
        "R": (0., 0., -2., -3., 0., 1., .7),
        "Y": (-.5, -2., -3., -3., 0., 1., .7),
        "B": (-3., -2., 0., 0., 0., 1., .7),
        "W": (-6., 0., 0., 0., .7),
        "K": (2., -4., 0., .5),
    }
    original = BackedGradientSmoothTransport(coefficients, {"W": (96., 96., 96.), "K": (.1, .1, .1)})
    parameters = original.to_parameters()
    reference = reference_from_parameters(parameters)
    materials = [MaterialParams(
        name=symbol, directory_name=f"test/{symbol}", E=np.ones(3), k=np.zeros(3),
        C0_white=np.ones(3), estimated_rgb=np.array([128, 128, 128], dtype=np.uint8),
        optical_model_id=SPECTRAL_SMOOTH_MODEL_ID,
        measurement_protocol_id=BACKED_GRADIENT_PROTOCOL_ID, color_bridge_id=KM_XYZ_COLOR_BRIDGE_ID,
        backed_gradient_component=component_from_parameters(parameters, symbol),
        backed_gradient_reference=reference,
    ) for symbol in coefficients]
    return original, materials


@pytest.mark.parametrize("backing,index", [("W", 3), ("K", 4)])
def test_all_1024_recipes_retain_version3_prediction_and_layer_order(backed_palette, backing, index):
    original, materials = backed_palette
    codes = ["".join(recipe) for recipe in product("RYBW", repeat=5)]
    indices = {symbol: i for i, symbol in enumerate("RYBWK")}
    recipes = np.array([[indices[symbol] for symbol in reversed(recipe)] for recipe in codes])
    bound = bind_material_backing(materials, index, 2.6)
    actual = predict_material_recipes_colorimetry(recipes, bound, .08, "white" if backing == "W" else "black")
    expected = original.predict_recipes(codes, backing) / 100.
    np.testing.assert_allclose(actual.matching_xyz, expected, atol=2e-14)
    np.testing.assert_allclose(forward_model(recipes[1], bound, .08), km_relative_xyz_to_linear_srgb(expected[1]))
    np.testing.assert_array_equal(predict_material_recipe_srgb(recipes[1], bound, .08), actual.display_srgb[1])


def test_print_backing_and_parameter_changes_invalidate_descriptors(backed_palette):
    _, materials = backed_palette
    white = bind_material_backing(materials, 3, 2.6)
    thinner = bind_material_backing(materials, 3, 1.2)
    black = bind_material_backing(materials, 4, 2.6)
    assert describe_palette(white) != describe_palette(thinner)
    assert describe_palette(white) != describe_palette(black)
    assert materials[0].backed_gradient_backing_component is None


def test_different_reference_batches_cannot_be_combined(backed_palette):
    _, materials = backed_palette
    changed = replace(materials[0].backed_gradient_reference, reference_id="another-reference")
    with pytest.raises(MaterialMeasurementProtocolMismatchError):
        validate_material_optical_contract([replace(materials[0], backed_gradient_reference=changed), materials[1]])


def test_same_color_role_can_hold_distinct_materials(backed_palette):
    _, materials = backed_palette
    red, yellow = materials[:2]
    assert red.backed_gradient_component.kind == yellow.backed_gradient_component.kind == "color"
    values = predict_material_recipes_colorimetry(np.array([[0] * 5, [1] * 5]), [red, yellow], .08)
    assert not np.allclose(values.matching_xyz[0], values.matching_xyz[1])


def test_single_material_recipe_can_use_embedded_black_reference(backed_palette):
    _, materials = backed_palette
    bound = bind_material_print_backing([materials[0]], substrate="black", thickness_mm=1.28)
    assert bound[0].backed_gradient_backing_component == materials[0].backed_gradient_reference.black
    assert bound[0].backed_gradient_backing_thickness_mm == 1.28


def test_candidate_cache_preserves_xyz_and_rebinds_user_material_order(backed_palette, tmp_path):
    from core.material_candidate_cache import (
        MaterialCandidateCacheConfig, build_material_candidate_runtime,
        load_material_candidate_runtime, save_material_candidate_runtime,
    )
    _, original = backed_palette
    materials = bind_material_backing([original[0], original[3]], 1, 2.6)
    config = MaterialCandidateCacheConfig(candidate_budget=64, batch_recipe_count=64, build_worker_count=1)
    runtime = build_material_candidate_runtime(
        materials=materials, layer_count=5, layer_height_mm=.08,
        config=config,
    )
    assert runtime.achieved_xyz is not None
    assert runtime.optical_model_id == SPECTRAL_SMOOTH_MODEL_ID
    save_material_candidate_runtime(runtime, cache_root=tmp_path)
    reordered = list(reversed(materials))
    restored = load_material_candidate_runtime(reordered, 5, .08, candidate_budget=64, cache_root=tmp_path, config=config)
    assert restored is not None
    targets = np.array([[150, 80, 90], [210, 205, 200]], dtype=np.uint8)
    rgb, recipes, _ = restored.lookup(targets, reordered)
    actual = predict_material_recipes_colorimetry(recipes, reordered, .08)
    np.testing.assert_array_equal(rgb, actual.display_srgb)
    changed = bind_material_backing(reordered, 0, 1.2)
    assert load_material_candidate_runtime(changed, 5, .08, candidate_budget=64, cache_root=tmp_path, config=config) is None


def test_dynamic_catalog_uses_its_own_version3_cache_namespace(backed_palette):
    from core.material_dynamic_catalog_cache import build_dynamic_catalog_cache_key
    _, original = backed_palette
    materials = bind_material_backing([original[0], original[3]], 1, 2.6)
    key = build_dynamic_catalog_cache_key(
        materials=materials, backing_material_index=1, layer_height_mm=.08,
        min_layer_count=5, max_layer_count=6, candidate_budget=64, substrate="white",
    )
    assert key.algorithm_version == "dynamic-box-backed-gradient-ciede2000-v3"
    assert key.candidate_source_version == "box-backed-gradient-hybrid-v3"


@pytest.fixture
def saved_backed_material(backed_palette, tmp_path):
    from core.backed_gradient_archive import save_backed_gradient_material_archive
    from core.backed_gradient_store import BackedGradientStore
    _, materials = backed_palette
    material = materials[0]
    captures = BackedGradientStore(tmp_path / "capture-origin")
    dataset = captures.create({"name": "Single Red", "brand": "Test", "materials": {"R": "Red"}})
    for index in range(2):
        captures.save_capture(dataset["dataset_id"], {
            "capture_id": "batch-a", "measurement_id": f"raw-{index}", "material_symbol": "R",
            "backing": "W", "sample_role": "coated", "overlay_mm": .08,
            "reflectance_percent_xyz": [float(index), 101., 23.4],
        })
    measurements = {"dataset_id": dataset["dataset_id"], "capture_export": captures.export(dataset["dataset_id"])}
    fit = {
        "optical_model_id": SPECTRAL_SMOOTH_MODEL_ID, "component": material.backed_gradient_component.to_dict(),
        "reference": material.backed_gradient_reference.to_dict(), "dataset_id": dataset["dataset_id"], "material_symbol": "R",
    }
    root = tmp_path / "materials"
    saved = save_backed_gradient_material_archive(
        material_name="Red", brand="Test", measurement_payload=measurements,
        fit_payload=fit, materials_dir=str(root),
    )
    return root, saved, measurements


def test_independent_archive_library_export_import_and_feedback_roundtrip(saved_backed_material, tmp_path):
    from api.feedback_materials_bundle import pack_materials
    from core.backed_gradient_archive import BACKED_GRADIENT_ARCHIVE_FILES, load_backed_gradient_archive
    from core.material_lut_synthesis import load_multiple_materials
    from core.single_stage.materials import (
        export_saved_stage_a_material_archives, import_saved_stage_a_material_archives,
        list_saved_stage_a_material_archives,
    )
    root, saved, measurements = saved_backed_material
    directory = saved.material_summary["directory_name"]
    loaded = load_multiple_materials([directory], materials_dir=str(root))
    assert loaded[0].optical_model_id == SPECTRAL_SMOOTH_MODEL_ID
    listed = list_saved_stage_a_material_archives(materials_dir=str(root), profile_kind="lumina_box")
    assert listed[0]["capture_dataset_id"] == measurements["dataset_id"]
    assert listed[0]["material_symbol"] == "R"
    exported = export_saved_stage_a_material_archives(
        directory_names=[directory], materials_dir=str(root), output_path=str(tmp_path / "export.zip"),
    )
    with zipfile.ZipFile(exported.archive_path) as package:
        manifest = json.loads(package.read("lumina_material_bundle.json"))
    assert manifest["schema_version"] == "5.0"
    restored_root = tmp_path / "imported"
    restored = import_saved_stage_a_material_archives(archive_path=exported.archive_path, materials_dir=str(restored_root))
    assert len(restored.imported_materials) == 1
    imported_directory = restored.imported_materials[0]["directory_name"]
    _, captured, _ = load_backed_gradient_archive(restored_root / imported_directory)
    assert captured == measurements
    from core.backed_gradient_product_store import list_backing_references
    from core.backed_gradient_store import BackedGradientStore
    imported_store = BackedGradientStore(restored_root)
    references = list_backing_references(imported_store)
    assert len(references) == 1
    assert references[0]["reference_id"] == saved.material_summary["reference_id"]
    imported_dataset = imported_store.get(measurements["dataset_id"])
    assert imported_dataset["captures"] == measurements["capture_export"]["dataset"]["captures"]
    assert imported_dataset["selected_capture_ids"] == measurements["capture_export"]["dataset"]["selected_capture_ids"]
    imported_store.save_capture(measurements["dataset_id"], {
        "capture_id": "batch-b", "measurement_id": "next-reading", "material_symbol": "R", "backing": "K",
        "sample_role": "coated", "overlay_mm": .16, "reflectance_percent_xyz": [2., 3., 4.],
    })
    assert len(imported_store.get(measurements["dataset_id"])["captures"]) == 3
    feedback = pack_materials(root, [directory], tmp_path / "feedback.zip", archive_profile_kind="lumina_box")
    assert feedback.status == "attached"
    with zipfile.ZipFile(feedback.path) as package:
        assert {Path(name).name for name in package.namelist()} == set(BACKED_GRADIENT_ARCHIVE_FILES)


def test_library_metadata_edit_preserves_optical_and_original_bytes(saved_backed_material):
    from core.backed_gradient_archive import load_backed_gradient_archive
    from core.single_stage.materials import update_saved_stage_a_material_archive_metadata, delete_saved_stage_a_material_archive
    root, saved, measurements = saved_backed_material
    before = [Path(saved.measurements_path).read_bytes(), Path(saved.parameters_path).read_bytes()]
    directory = saved.material_summary["directory_name"]
    updated = update_saved_stage_a_material_archive_metadata(
        directory_name=directory, material_name="Renamed Red", brand="New Brand", notes="Batch 2",
        materials_dir=str(root),
    )
    main, _, _ = load_backed_gradient_archive(Path(updated.archive_path).parent)
    assert (main["material_name"], main["brand"], main["notes"]) == ("Renamed Red", "New Brand", "Batch 2")
    assert [Path(saved.measurements_path).read_bytes(), Path(saved.parameters_path).read_bytes()] == before
    delete_saved_stage_a_material_archive(directory_name=directory, materials_dir=str(root))
    assert not Path(saved.archive_path).exists()


def test_library_api_metadata_recipe_preview_and_export_download(saved_backed_material, monkeypatch):
    from api.app import create_app
    from fastapi.testclient import TestClient
    from api.dependencies import get_file_registry, get_session_store
    from api.file_registry import FileRegistry
    from api.session_store import SessionStore

    root, saved, measurements = saved_backed_material
    for module in ("core.single_stage.material_files", "core.material_lut_synthesis", "core.material_lut_provider",
                   "core.pipeline._input_validation_common", "api.file_registry"):
        monkeypatch.setattr(f"{module}.MATERIALS_DIR", str(root))
    registry = FileRegistry()
    store = SessionStore()
    source_session_id = store.create()
    app = create_app()
    app.dependency_overrides[get_file_registry] = lambda: registry
    app.dependency_overrides[get_session_store] = lambda: store
    client = TestClient(app, base_url="http://127.0.0.1")
    directory = saved.material_summary["directory_name"]
    listing = client.get("/api/extractor/gradient-card-materials", params={"profile_kind": "lumina_box"})
    assert listing.status_code == 200, listing.text
    assert listing.json()["materials"][0]["capture_dataset_id"] == measurements["dataset_id"]
    edited = client.patch(f"/api/extractor/gradient-card-materials/{directory}", json={
        "material_name": "Renamed", "brand": "Edited", "notes": "Keep readings",
    })
    assert edited.status_code == 200, edited.text
    assert edited.json()["material"]["stage_a_params_url"] is None
    assert edited.json()["material"]["optical_parameters_url"]
    preview = client.post("/api/extractor/material-recipe-preview", json={
        "directory_names": [directory] * 5, "material_profile_kind": "lumina_box",
    })
    assert preview.status_code == 200, preview.text
    exported = client.post("/api/extractor/gradient-card-materials/export", json={"directory_names": [directory]})
    assert exported.status_code == 200, exported.text
    url = exported.json()["download_url"]
    file_id = url.rsplit("/", 1)[1]
    closed = client.post("/api/session/close", json={"session_id": source_session_id})
    assert closed.status_code == 200
    download = client.get(url)
    assert download.status_code == 200 and download.content[:2] == b"PK"
    registry.cleanup_file(file_id)
