"""First-use identity, archive publication, and transfer contracts."""
from copy import deepcopy

import pytest

from core.backed_gradient_backing_store import create_black_white_pair, list_backing_materials
from core.backed_gradient_archive import load_backed_gradient_archive
from core.backed_gradient_backing_transfer import restore_material_captures
from core.backed_gradient_store import BackedGradientStore
from core.errors import CoreValidationError, CoreProcessingError
from tests.support.black_white_materials import register_black_white
from tests.test_backed_gradient_product_api_unit import reference_fixture


def test_first_pair_creates_two_complete_identities_in_one_operation(tmp_path):
    store = BackedGradientStore(tmp_path)
    first = create_black_white_pair(store, {"white": {"name": "White", "brand": "A"}, "black": {"name": "Black", "brand": "B"}})
    pair = {item["role"]: item for item in list_backing_materials(store)}
    assert len(pair) == 2
    assert first["dataset_id"] == pair["W"]["active_dataset_id"]
    for role, item in pair.items():
        opposite = pair["K" if role == "W" else "W"]
        assert item["opposite_material_id"] == opposite["material_id"]
        dataset = store.get(item["dataset_id"])
        assert dataset["workflow"]["material_symbol"] == role
        assert {key: dataset["materials"][key] for key in ("W", "K")} == {"W": "White", "K": "Black"}
    with pytest.raises(CoreValidationError):
        create_black_white_pair(store, {"white": {"name": "Same"}, "black": {"name": "Same"}})
    assert len(store.list()) == 2


def test_black_white_archives_transfer_with_eight_readings_and_usable_components(tmp_path):
    source, target = BackedGradientStore(tmp_path / "source"), BackedGradientStore(tmp_path / "target")
    reference = reference_fixture().to_dict()
    before = deepcopy(reference)
    pair = register_black_white(source, reference)
    entries = []
    for role, item in pair.items():
        path = source.root / item["name"]
        main, measurements, fit = load_backed_gradient_archive(path)
        assert main["backing_material_id"] == item["material_id"]
        assert main["material_symbol"] == role
        assert len(measurements["samples"]) == 8
        assert fit["component"] == reference["white" if role == "W" else "black"]
        assert fit["reference"] == before
        entries.append((measurements, fit, []))
    restore_material_captures(target, entries)
    restored = {item["material_id"]: item for item in list_backing_materials(target)}
    for item in pair.values():
        assert restored[item["material_id"]]["component"] == item["component"]
        assert len(target.get(item["dataset_id"])["captures"]) == 8


def test_new_pair_links_to_each_other_when_ready_profiles_already_exist(tmp_path):
    store = BackedGradientStore(tmp_path)
    register_black_white(store, reference_fixture().to_dict())
    existing = deepcopy(list_backing_materials(store))
    create_black_white_pair(store, {"white": {"name": "New White"}, "black": {"name": "New Black"}})
    materials = list_backing_materials(store)
    assert len(materials) == 4
    assert all(item in materials for item in existing)
    new = {item["role"]: item for item in materials if item["status"] == "draft"}
    for role, item in new.items():
        opposite = new["K" if role == "W" else "W"]
        workflow = store.get(item["dataset_id"])["workflow"]
        assert workflow["opposite_material_id"] == opposite["material_id"]
        assert "opposite_version_id" not in workflow


def test_references_alone_do_not_synthesize_materials(tmp_path):
    from core.backed_gradient_product_store import save_backing_reference

    store = BackedGradientStore(tmp_path)
    save_backing_reference(store, reference_fixture().to_dict(), "Reference")
    assert list_backing_materials(store) == []


def test_failed_second_archive_swap_restores_both_profiles_and_database(tmp_path, monkeypatch):
    from core import black_white_material_profiles as profiles

    store = BackedGradientStore(tmp_path / "library")
    pair = register_black_white(store, reference_fixture().to_dict())
    files = {path: path.read_bytes() for path in store.root.rglob("*.json")}
    before = list_backing_materials(store)
    replace = profiles.os.replace
    failed = False

    def fail_second(source, target):
        nonlocal failed
        if not failed and target == store.root / pair["K"]["name"]:
            failed = True
            raise OSError("second profile swap failed")
        return replace(source, target)

    monkeypatch.setattr(profiles.os, "replace", fail_second)
    with pytest.raises(CoreProcessingError, match="storage"):
        profiles.publish_black_white_profiles(store, [(item["snapshot"], item["fit"]) for item in pair.values()])
    assert list_backing_materials(store) == before
    assert all(path.read_bytes() == content for path, content in files.items())
